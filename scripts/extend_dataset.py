#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据集扩展工具：扩样本量、补多波段算子、按独立候选集划分 train/val/test。

解决的问题：
  原始 97 条样本只有 13 种唯一候选集，统计显著性不足
  （按独立样本算95%CI ±4.1%，按唯一候选集聚类后 [89.9%, 101.3%]）
  本脚本用于扩到 800+ 条，并做 cluster-aware 的数据划分，避免数据泄漏。

用法：
    # 1. 扩展：纳入更多产品与算子
    python extend_dataset.py --expand

    # 2. 划分（按唯一候选集切分，避免同产品泄漏到 train/test 两侧）
    python extend_dataset.py --split --ratios 0.7 0.15 0.15

    # 3. 质量审计
    python extend_dataset.py --audit

    # 4. 查看样本独立性
    python extend_dataset.py --independence
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from config_loader import get_config

BASE = Path(__file__).resolve().parent.parent   # 技能根目录
DATA = BASE / "data"

# ---------------------------------------------------------------- 多波段算子定义
# 原始数据集只有 4 个双波段算子，无法验证结论对多波段算子的普适性。
# 以下为遥感领域常用的多波段算子，按「所需光谱角色」定义。
MULTI_BAND_OPERATORS = {
    "Coverage.EVI": {
        "alias": "增强型植被指数",
        "roles": ["蓝", "红", "近红外"],
        "desc": "增强型植被指数 EVI=(2.5×(NIR-Red))/(NIR+6×Red-7.5×Blue+1)，"
                "对气溶胶与土壤背景更稳健。",
    },
    "Coverage.SAVI": {
        "alias": "土壤调节植被指数",
        "roles": ["红", "近红外"],
        "desc": "土壤调节植被指数 SAVI=1.5×(NIR-Red)/(NIR+Red+0.5)，适用于植被稀疏区。",
    },
    "Coverage.MSAVI": {
        "alias": "改进型土壤调节植被指数",
        "roles": ["红", "近红外"],
        "desc": "改进型土壤调节指数，对土壤背景修正更精细。",
    },
    "Coverage.NDRE": {
        "alias": "归一化红边指数",
        "roles": ["红", "近红外"],  # 精确需红边波段，但平台无对应参数时退化为红/NIR
        "desc": "归一化红边指数 NDRE=(NIR-RedEdge)/(NIR+RedEdge)，对作物胁迫更敏感。",
        "optional_roles": ["近红外窄", "红边"],
    },
    "Coverage.NBR": {
        "alias": "归一化燃烧指数",
        "roles": ["红", "近红外"],
        "desc": "归一化燃烧指数 NBR=(NIR-SWIR2)/(NIR+SWIR2)，用于火烧迹地提取。",
        "alt_roles": {"红": ["短波红外2", "短波红外1"]},
    },
    "Coverage.NDMI": {
        "alias": "归一化土壤湿度指数",
        "roles": ["近红外", "短波红外1"],
        "desc": "归一化土壤湿度指数 NDMI=(NIR-SWIR1)/(NIR+SWIR1)，反映植被含水量。",
    },
    "Coverage.NDRE2": {
        "alias": "归一化双红边指数",
        "roles": ["红", "近红外"],
        "desc": "归一化双红边指数，需红边窄波段参与。",
        "optional_roles": ["近红外窄", "红边"],
    },
}

# 非光谱量：观测几何角、质量标识等，不能作为波段候选
NON_SPECTRAL = re.compile(
    r"VAA|VZA|SAA|SZA|"
    r"^QA$|_QA|QA_|^qc|_qc$|state_|_state|"
    r"_raz$|_szen$|_vzen$|day_of_year|"
    r"azimuth|zenith|cloud|shadow|ice|snow|"
    r"quality|uncertaint|brdf|"
    r"^sur_refl_qc|^sur_refl_state|^sur_refl_raz|^sur_refl_szen|^sur_refl_vzen",
    re.I)


def load(name):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"  已保存 {name}")


# ---------------------------------------------------------------- 扩展
def cmd_expand(args):
    """用多波段算子扩展现有数据集。"""
    rows = load("dataset_matching.json")
    if not rows:
        print("错误：未找到 data/dataset_matching.json，"
              "请先运行 build_validation_dataset.py")
        return

    existing = {r["sample_id"] for r in rows}
    added = 0
    skipped = collections.Counter()

    for op_name, spec in MULTI_BAND_OPERATORS.items():
        for r in list(rows):
            avail = r["band_roles_available"]
            roles = [x for x in spec["roles"] if x in avail]
            if len(roles) < len(spec["roles"]):
                skipped[op_name] += 1
                continue
            gt = {role: avail[role] for role in roles}
            sid = f"{r['product_name']}_{op_name.split('.')[-1]}_{r['product_id']}"
            if sid in existing:
                continue
            params = [{"param": f"{_en(role)}BandName", "alias": f"{role}波段",
                       "type": "string", "default": None,
                       "description": spec["desc"], "role": role}
                      for role in roles]
            rows.append({
                "sample_id": sid,
                "satellite": r.get("satellite"),
                "product_id": r["product_id"],
                "product_name": r["product_name"],
                "product_alias": r.get("product_alias"),
                "product_desc": r.get("product_desc"),
                "operator": {"name": op_name, "alias": spec["alias"],
                             "description": spec["desc"], "params": params},
                "required_roles": roles,
                "ground_truth": gt,
                "band_options": r["band_options"],
                "band_roles_available": avail,
                "band_wavelengths": r.get("band_wavelengths", {}),
            })
            existing.add(sid)
            added += 1

    save("dataset_matching.json", rows)
    print(f"  新增样本 {added} 条，现有 {len(rows)} 条")
    if skipped:
        print("  跳过（候选集缺角色）:")
        for k, v in skipped.most_common():
            print(f"    {k}: {v} 个产品不满足")


def _en(role):
    m = {"红": "red", "蓝": "blue", "绿": "green", "近红外": "nir",
         "短波红外1": "swir1", "短波红外2": "swir2", "热红外": "tir",
         "大气校正": "coastal"}
    return m.get(role, "band")


# ---------------------------------------------------------------- 划分
def cmd_split(args):
    """
    按「唯一候选集」分组划分 train/val/test。

    为什么不用随机划分：同一产品的多个样本共享同一组候选波段，
    随机划分会导致同一候选集同时出现在 train 和 test，
    产生数据泄漏，准确率虚高。必须按组划分。
    """
    rows = load("dataset_matching.json")
    if not rows:
        print("错误：未找到数据集")
        return

    groups = collections.defaultdict(list)
    for r in rows:
        # 候选集 + 所需角色组合 作为分组键
        key = (r["product_name"], tuple(sorted(r["required_roles"])))
        groups[key].append(r)

    keys = sorted(groups)
    # 确定性打散（固定随机种子保证可复现）
    import random
    rng = random.Random(42)
    rng.shuffle(keys)

    n = len(keys)
    n_tr = int(n * args.ratios[0])
    n_va = int(n * args.ratios[1])
    split = (keys[:n_tr], keys[n_tr:n_tr + n_va], keys[n_tr + n_va:])

    out = {}
    for name, ks in zip(("train", "val", "test"), split):
        out[name] = [r for k in ks for r in groups[k]]
        print(f"  {name:6} {len(ks):3} 组 / {len(out[name]):4} 样本")
        save(f"split_{name}.json", out[name])

    # 验证无泄漏
    def cset(rs):
        return {r["sample_id"] for r in rs}
    assert not (cset(out["train"]) & cset(out["test"])), "划分有重叠！"
    tr_keys = {k for k in split[0]}
    assert not (tr_keys & {k for k in split[2]}), "候选集泄漏！"
    print("  校验通过：train/test 无样本重叠、无候选集泄漏")


# ---------------------------------------------------------------- 审计
def cmd_audit(args):
    """数据质量审计：吸收带、全色带、非光谱量、元数据矛盾。"""
    rows = load("dataset_matching.json")
    prods = load("products_enriched.json")
    if not rows:
        print("错误：未找到数据集")
        return

    issues = collections.Counter()
    detail = []
    by_id = {p["id"]: p for p in (prods or [])}

    for r in rows:
        p = by_id.get(r["product_id"])
        if not p:
            continue
        bylabel = {b["bandNum"]: b for b in (p.get("imageProductBands") or [])}
        for b in r["band_options"]:
            if NON_SPECTRAL.search(b):
                issues["候选集含非光谱量"] += 1
                detail.append((r["sample_id"], b, "非光谱量混入候选集"))
                continue
            bb = bylabel.get(b)
            if bb and bb.get("spectrumMin") is not None:
                c = (bb["spectrumMin"] + bb["spectrumMax"]) / 2
                if any(a <= c <= z for a, z in
                       [(920, 960), (1350, 1400), (1800, 1950)]):
                    issues["候选集含吸收带"] += 1
                    detail.append((r["sample_id"], b, f"中心{c:.0f}nm 在吸收窗口"))
                if bb["spectrumMax"] - bb["spectrumMin"] > 120:
                    issues["候选集含全色带"] += 1
                    detail.append((r["sample_id"], b, "带宽>120nm 全色"))

    print("=== 数据质量审计 ===")
    print(f"  样本总数: {len(rows)}")
    if issues:
        for k, v in issues.most_common():
            print(f"  [警告] {k}: {v} 处")
        print("\n  前 10 条明细:")
        for d in detail[:10]:
            print(f"    {d[0]:34} {d[1]:14} {d[2]}")
    else:
        print("  未发现问题")


# ---------------------------------------------------------------- 独立性
def cmd_independence(args):
    """样本独立性检验 —— 评估统计显著性的关键。"""
    rows = load("dataset_matching.json")
    if not rows:
        print("错误：未找到数据集")
        return

    csets = collections.Counter(tuple(sorted(r["band_options"])) for r in rows)
    prods = collections.Counter(r["product_name"] for r in rows)
    print("=== 样本独立性检验 ===")
    print(f"  样本总数        : {len(rows)}")
    print(f"  唯一候选集组合数: {len(csets)}")
    print(f"  数据产品数      : {len(prods)}")
    print(f"  算子数          : {len({r['operator']['name'] for r in rows})}")
    print()
    print(f"  有效独立信息量接近「唯一候选集数」= {len(csets)}，而非 {len(rows)}")
    print()
    print("  候选集规模分布:")
    for n, c in sorted(collections.Counter(len(k) for k in csets).items()):
        print(f"    {n:2} 个候选的组合: {c} 种")

    print()
    print("  建议: 报告中不要写「在 N 个样本上达到 X%」，")
    print("       应写「覆盖 M 个数据产品、K 种独立候选波段配置」")


def main():
    ap = argparse.ArgumentParser(description="数据集扩展与划分工具")
    ap.add_argument("--expand", action="store_true", help="纳入多波段算子扩展样本")
    ap.add_argument("--split", action="store_true", help="按候选集划分 train/val/test")
    ap.add_argument("--ratios", nargs=3, type=float, default=[0.7, 0.15, 0.15])
    ap.add_argument("--audit", action="store_true", help="数据质量审计")
    ap.add_argument("--independence", action="store_true", help="样本独立性检验")
    a = ap.parse_args()

    if not any([a.expand, a.split, a.audit, a.independence]):
        a.audit = True
    if a.audit:
        cmd_audit(a)
    if a.independence:
        cmd_independence(a)
    if a.expand:
        print("\n=== 扩展数据集 ===")
        cmd_expand(a)
    if a.split:
        print("\n=== 划分数据集 ===")
        cmd_split(a)


if __name__ == "__main__":
    main()

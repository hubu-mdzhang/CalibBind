#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩展波段评测集的规则基线 —— 衡量 5 类任务各自的难度下限。

用途：
    原评测集只在 T1（角色波段名）上做过基线，得出「仅标签 6.7%、
    角色级 83.0%」的结论。扩展到 T2~T5 后，需要知道新任务是否
    真的带来了额外难度，还是只是把同一件事换了种问法。

基线（均为无 LLM 的确定性规则，用于给出难度下限）：
    B0 恒定猜 1        —— 对应「默认值几乎全是 1」的真实场景
    B1 编号位置猜测     —— 假设 B1=蓝/B2=绿/B3=红 的通用编号制
    B2 角色元数据直读   —— 直接读 band_roles_available（等于泄题，仅作上界参考）
    B3 序号类专用       —— T2/T5 读 rank_map 转换

用法：
    python eval_band_benchmark.py
    python eval_band_benchmark.py --by-operator
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 技能内数据在 data/，工程目录内数据与脚本同级 —— 两种布局都要能跑
DATA = HERE.parent / "data" if (HERE.parent / "data").is_dir() else HERE
BENCH = DATA / "dataset_matching_extended.json"

# 通用编号制假设（Landsat/国产多光谱）：B1蓝 B2绿 B3红 B4近红外 B5/B6 SWIR
GENERIC_NUM = {"b1": "蓝", "b2": "绿", "b3": "红", "b4": "近红外",
               "b5": "短波红外1", "b6": "短波红外2", "b7": "短波红外1"}
# v2: 序号基址为 0 的参数（与 build_band_benchmark.ZERO_BASED_PARAMS 一致）
ZERO_BASED = {"bandIndex"}


def _num_key(label: str):
    m = re.fullmatch(r"(?:sr_|st_)?b(\d{1,2}a?)", (label or "").strip(), re.I)
    return ("b" + m.group(1).lower()) if m else None


def baseline_constant(sample) -> dict:
    """
    B0：完全不做推理，只照抄平台默认值。
    这正是真实用户「不看文档直接跑」的行为：
      - 序号类参数默认值几乎全是 1，猜 1 会意外地拿到不少分
      - 名称类参数默认值是 RED/NIR 等通用标签，与产品实际标签无关，
        故按「答案等于候选集首项」这一最强猜测处理
    """
    out = {}
    opts = sample["band_options"] or [""]
    for p in sample["operator"]["params"]:
        t = (p.get("type") or "").strip()
        if t == "Integer":
            # v2: bandIndex（OGE 原生区间统计）平台默认 0，其余 Integer 默认 1
            out[p["param"]] = 0 if p.get("param") in ZERO_BASED else 1
        elif t == "List[Integer]":
            out[p["param"]] = [1, 1, 1]
        elif t == "String":
            out[p["param"]] = opts[0]
        elif t == "List[String]":
            n = len(p.get("role") or [1])
            out[p["param"]] = [opts[0]] * n
    return out


def baseline_generic_number(sample) -> dict:
    """
    B1：假设通用编号制（B1蓝 B2绿 B3红 B4近红外），从标签反推角色再作答。
    这是最「天真」的做法，对 MODIS / Landsat 这类编号制不通用的产品必然失败，
    用来观察「跨传感器编号制冲突」到底吃掉了多少准确率。
    推不出的参数一律回落到候选集首项（尽力猜，而不是弃答），
    否则分母不一致，跨基线无法比较。
    """
    roles = {}
    for lbl in sample["band_options"]:
        k = _num_key(lbl)
        if k and k in GENERIC_NUM:
            roles.setdefault(GENERIC_NUM[k], lbl)
    opts = sample["band_options"] or [""]
    out = {}
    for p in sample["operator"]["params"]:
        role, t = p.get("role"), (p.get("type") or "").strip()

        def conv(label: str, pname: str = ""):
            """把波段标签转成该参数类型要求的答案形式（v2: bandIndex 0 起）。"""
            if t.startswith("List[Integer]"):
                return [sample["rank_map"].get(label, 1)]
            if t.startswith("List["):
                return [label]
            if t == "Integer":
                r = sample["rank_map"].get(label, 1)
                return r - 1 if pname in ZERO_BASED else r
            return label

        if isinstance(role, list):
            vals = [roles.get(r) or opts[0] for r in role]
            if t.startswith("List[Integer]"):
                out[p["param"]] = [sample["rank_map"].get(v, 1) for v in vals]
            else:
                out[p["param"]] = vals
        elif role and role in roles:
            out[p["param"]] = conv(roles[role], p["param"])
        elif role == "__PAN__":
            out[p["param"]] = (sample["pan_bands"] or [opts[0]])[0]
        else:
            out[p["param"]] = conv(opts[0], p["param"])
    return out


def baseline_oracle(sample) -> dict:
    """B3：直接使用构建期真值（等价于 100% 上界），用于验证评测管线本身无误。"""
    return dict(sample["ground_truth"])


def score(sample, pred: dict) -> float:
    """
    样本级得分：所有出题参数全对得 1 分，部分对按比例给分（参数级严格匹配）。
    未作答的参数按 0 计 —— 基线若弃答不会获得"跳过"的好处。
    """
    gt = sample["ground_truth"]
    if not gt:
        return 0.0
    ok = 0
    for k, v in gt.items():
        pv = pred.get(k)
        if isinstance(v, list):
            ok += 1 if (isinstance(pv, list) and list(pv) == list(v)) else 0
        else:
            ok += 1 if pv == v else 0
    return ok / len(gt)


BASELINES = {"B0_恒定猜1": baseline_constant,
             "B1_通用编号制": baseline_generic_number,
             "B3_真值上界": baseline_oracle}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-operator", action="store_true", help="按算子拆分")
    a = ap.parse_args()

    samples = json.loads(BENCH.read_text(encoding="utf-8"))
    print(f"扩展评测集 {len(samples)} 条样本\n")

    tasks = sorted({s["task"] for s in samples})
    print(f"{'任务':<5}{'名称':<16}{'样本':>6}" +
          "".join(f"{k:>14}" for k in BASELINES))
    print("-" * (27 + 14 * len(BASELINES)))
    for t in tasks:
        sub = [s for s in samples if s["task"] == t]
        row = f"{t:<5}{sub[0]['task_label']:<16}{len(sub):>6}"
        for name, fn in BASELINES.items():
            sc = [score(s, fn(s)) for s in sub]
            row += f"{(sum(sc) / len(sc) * 100 if sc else 0):>13.1f}%"
        print(row)

    if a.by_operator:
        print()
        for t in tasks:
            sub = [s for s in samples if s["task"] == t]
            print(f"\n[{t}] {sub[0]['task_label']}")
            byop = collections.defaultdict(list)
            for s in sub:
                byop[s["operator"]["name"]].append(s)
            for op, ss in sorted(byop.items(), key=lambda x: -len(x[1])):
                cells = []
                for name, fn in BASELINES.items():
                    sc = [score(s, fn(s)) for s in ss]
                    cells.append(f"{name}={sum(sc) / len(sc) * 100:.1f}%")
                print(f"    {op:<44}{len(ss):>4}  " + "  ".join(cells))


if __name__ == "__main__":
    main()
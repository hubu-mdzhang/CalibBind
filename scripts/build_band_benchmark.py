#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩展波段匹配评测集 —— 从 4 个算子扩展到全平台 5 类波段任务。

背景：
    原评测集只覆盖 4 个「光谱角色 -> 波段名」的算子
    （NDVI / NDWI / NDBI / NDSSI），97 条样本、13 种唯一候选集。
    扫描全部 489 个算子后确认，含波段语义的算子有 84 个，
    按参数类型可归为 5 类任务，其中只有第 1 类被原评测集覆盖。

5 类任务：
    T1 角色波段名    redBandName/nirBandName/... -> String
                      原评测集覆盖的即是这一类
    T2 角色→波段序号  band / bandIndex / channel -> Integer
                      与 T1 同一批算子语义、不同答案形式：
                      问「第几个波段」而非「叫什么名字」，
                      需先理解产品波段排序，且默认值几乎全为 1，无提示
    T3 波段名列表    selectBands / normalizedDifference -> List[String]
    T4 融合配对      panSharp / broveyFusion / IHSFusion
                      需同时给出多光谱波段组与对应的全色波段，
                      全色波段识别本身是一个独立子任务
    T5 多通道索引    radiometricIndicesByOTB 一次绑定 5 个通道

用法：
    python build_band_benchmark.py --scan          # 扫描并列出全部候选算子
    python build_band_benchmark.py --build         # 构建扩展评测集
    python build_band_benchmark.py --build --task T2
    python build_band_benchmark.py --report        # 统计各任务可造样本量
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 技能内数据在 data/，工程目录内数据与脚本同级 —— 两种布局都要能跑
DATA = HERE.parent / "data" if (HERE.parent / "data").is_dir() else HERE
sys.path.insert(0, str(HERE))

from build_validation_dataset import (  # noqa: E402
    infer_role, _num_map, _is_panchromatic, _band_is_absorption,
    role_by_wavelength, ROLE_CENTER, ROLE_KEYWORDS_COMMON, GF_NUM,
)

PRODUCTS_FILE = DATA / "dataset_products.json"
OPERATORS_FILE = DATA / "operator_params_all.json"
OUT_MATCHING = DATA / "dataset_matching_extended.json"
OUT_INDEX = DATA / "band_task_index.json"

PAN_ROLE = "__PAN__"
# v2：这些参数的序号从 0 起始（平台参数描述明写「索引从0开始递增」，默认值 0）
ZERO_BASED_PARAMS = {"bandIndex"}

# ---------------------------------------------------------------- 任务定义
# ops: 算子名 -> {参数名: 所需角色}
#   角色为 str  -> 单角色
#   角色为 tuple -> 需同时绑定这几个角色（列表型参数）
#   角色为 None  -> 不做角色约束（仅 T4 的权重类附属参数）
#   角色为 __PAN__ -> 需绑定全色波段
TASK_DEFS = {
    "T1": {
        "label": "角色波段名",
        "value_type": "String",
        "answer": "band_name",
        "desc": "由光谱角色反查该产品下的波段标签，最主流的波段绑定形式",
        "ops": {
            "Coverage.NDVI":  {"redBandName": "红", "nirBandName": "近红外"},
            "Coverage.NDWI":  {"greenBandName": "绿", "nirBandName": "近红外"},
            "Coverage.NDBI":  {"swirBandName": "短波红外1", "nirBandName": "近红外"},
            "Coverage.NDSSI": {"blueBandName": "蓝", "nirBandName": "近红外"},
            "Coverage.LST":   {"tirBandName": "热红外"},
        },
    },
    "T2": {
        "label": "角色→波段序号",
        "value_type": "Integer",
        "answer": "band_index",
        "desc": "答案形式是波段在产品中的位置（bandRank）而非名称；"
                "需先理解产品波段排序规则，且默认值几乎全是 1，几乎无提示信息。"
                "这是与 T1 语义相同、输出形式不同的对照任务",
        "ops": {
            # 区域统计 / 直方图：任意波段均可，用近红外作代表
            "Coverage.reduceRegion":  {"bandIndex": "近红外"},
            "Coverage.histogramBin":  {"bandIndex": "近红外"},
            # 矢量化 / 等值线：通常对高程或首个波段，这里用红光作代表
            "Coverage.polygonizeByGDAL":         {"band": "红"},
            "Coverage.contourByGDAL":             {"band": "红"},
            "Coverage.contourPolygonByGDAL":      {"band": "红"},
            # 地形因子：作用于高程，用短波红外1作代表（非高程产品仅测排序推理）
            "Coverage.aspectByGDAL":                       {"band": "短波红外1"},
            "Coverage.hillShadeByGDAL":                    {"band": "短波红外1"},
            "Coverage.slopeByGDAL":                        {"band": "短波红外1"},
            "Coverage.roughnessByGDAL":                    {"band": "短波红外1"},
            "Coverage.fillNodataByGDAL":                   {"band": "短波红外1"},
            "Coverage.proximityByGDAL":                    {"band": "短波红外1"},
            "Coverage.tpiTopographicPositionIndexByGDAL":  {"band": "短波红外1"},
            "Coverage.triTerrainRuggednessIndexByGDAL":    {"band": "短波红外1"},
            "Coverage.rescaleRasterByQGIS":                {"band": "短波红外1"},
            # 纹理 / 边缘：单通道运算，用蓝波段
            "Coverage.SFSTextureExtractionByOTB": {"channel": "蓝"},
            "Coverage.edgeExtractionByOTB":       {"channel": "蓝"},
        },
    },
    "T3": {
        "label": "波段名列表",
        "value_type": "List[String]",
        "answer": "band_list",
        "desc": "一次给出一组波段名；normalizedDifference 固定两个角色，"
                "selectBands/rename 为任意子集选择",
        "ops": {
            "Coverage.normalizedDifference":   {"bandNames": ("红", "近红外")},
            "Coverage.selectBands":            {"bands": ("蓝", "绿", "红")},
            "Coverage.rename":                 {"name": ("蓝", "绿", "红")},
            "Coverage.addStyles":              {"bands": ("红", "绿", "近红外")},
            "CoverageCollection.addStyles":    {"bands": ("红", "绿", "近红外")},
        },
    },
    "T4": {
        "label": "融合配对",
        "value_type": "List + String",
        "answer": "mixed",
        "desc": "需同时给出参与融合的多光谱波段组与对应全色波段；"
                "全色波段识别本身即为一个独立子任务（跨可见光—近红外的宽波段）。"
                "注意两类算子的答案形式不同：panSharp 的 bandList 是 List[Integer]（序号），"
                "broveyFusion 的 mul 是 List[String]（波段名）",
        "ops": {
            # bandList 为 List[Integer]，答案是参与融合的波段序号
            "Coverage.panSharp": {"bandList": ("蓝", "绿", "红"), "answer_as": "index"},
            # mul 为 List[String]（波段名），pan 为 String（全色波段名）
            "Coverage.broveyFusion": {"mul": ("红", "绿", "近红外"), "pan": PAN_ROLE,
                                      "answer_as": "name"},
        },
    },
    "T5": {
        "label": "多通道索引",
        "value_type": "Integer x 5",
        "answer": "band_index",
        "desc": "一次请求需绑定 5 个通道（蓝/绿/红/近红外/中红外），"
                "单次决策复杂度最高，且全部为序号答案",
        "ops": {
            "Coverage.radiometricIndicesByOTB": {
                "channelsBlue": "蓝", "channelsGreen": "绿", "channelsRed": "红",
                "channelsNir": "近红外", "channelsMir": "短波红外2",
            },
        },
    },
}


# ---------------------------------------------------------------- 产品波段索引
def product_band_index(prod: dict) -> dict | None:
    """
    重建单个产品的波段索引。若 bandRank 不可信（同一产品内大量重复、
    或不从 1 连续递增），返回 None —— 序号类任务（T2/T5）无法据此定真值。
    """
    bands = prod.get("bands") or []
    if not bands:
        return None

    nmap = _num_map(prod.get("name") or "", prod.get("alias") or "")
    role_bands: dict[str, list[str]] = collections.defaultdict(list)
    rank_map: dict[str, int] = {}
    pan_bands: list[str] = []
    wavelength: dict[str, list] = {}
    band_names: dict[str, str] = {}

    for b in bands:
        label = b.get("bandNum")
        if not label:
            continue
        band_names[label] = b.get("bandName") or ""
        lo, hi = b.get("spectrumMin"), b.get("spectrumMax")
        if b.get("bandRank") is not None:
            rank_map[label] = b["bandRank"]
        if lo is not None and hi is not None:
            wavelength[label] = [lo, hi]
        # 吸收/观测几何量不做候选
        if _band_is_absorption(label, lo or 0, hi or 0):
            continue
        if lo is not None and hi is not None and _is_panchromatic(lo, hi):
            pan_bands.append(label)
            continue
        role = infer_role(label, nmap, lo, hi, band_name=b.get("bandName"))
        if role:
            role_bands[role].append(label)

    # v2 多解裁决：①波段名精确命中该角色关键词者优先 ②中心波长最接近角色标准中心
    # ③无后缀（B8 优于 B8A）④短名 ⑤字典序。
    # 原规则只按「短名/字典序」，会把 S2 的红边 B07 当成近红外（B08 bandName=NIR 被忽略）。
    def _role_key(label: str, role: str) -> tuple:
        wl = wavelength.get(label)
        center = (wl[0] + wl[1]) / 2 if wl else ROLE_CENTER.get(role, 0.0)
        label_center = ROLE_CENTER.get(role, center)
        name = band_names.get(label) or ""
        kw_hit = any(re.search(p, t, re.I)
                     for p in ROLE_KEYWORDS_COMMON.get(role, [])
                     for t in (name, label) if t)
        return (0 if kw_hit else 1, abs(center - label_center),
                bool(re.search(r"\d[a-zA-Z]$", label or "")),
                len(label or ""), label or "")

    role_rank: dict[str, str] = {}
    for role, labels in role_bands.items():
        role_rank[role] = sorted(labels, key=lambda s: _role_key(s, role))[0]

    candidates = sorted(set(role_rank.values()) | set(pan_bands))
    if not candidates:
        return None

    # v2 元数据一致性校验：波段标签（评分答案）与波长（真值依据）必须自洽。
    # 实例：平台 S2A_MSIL2A 的 B01_60m 标 458~523nm（蓝），编号制却是大气校正，
    # 整个产品的标签相对波长错位一格 —— 标签不可作为判分答案，排除该产品。
    n_checked = n_conflict = 0
    # 仅在存在权威编号制的家族上校验（高光谱/国产产品的 B1..Bn 是通道序号，
    # 不遵循 Sentinel/Landsat/MODIS 的波段编号语义，不能拿来判冲突）
    if nmap is not GF_NUM:
        for label, wl in wavelength.items():
            m = re.fullmatch(r"(?:sr_|st_)?b(\d{1,2}a?)(?:[_-]\d+m)?", (label or "").strip(), re.I)
            if not m:
                continue
            g = m.group(1).lower()
            key = "b" + (str(int(g[:-1])) + "a" if g.endswith("a") else str(int(g)))
            lbl_role = nmap.get(key)
            wl_role = role_by_wavelength(wl[0], wl[1])
            if lbl_role and wl_role:
                n_checked += 1
                if lbl_role != wl_role:
                    n_conflict += 1
        if n_checked >= 3 and n_conflict / n_checked > 0.3:
            print(f"[排除] {prod.get('name')}: 标签-波长角色冲突 {n_conflict}/{n_checked}，元数据自相矛盾")
            return None

    # bandRank 可信性校验：序号类任务的真值来源
    ranks = [r for r in rank_map.values() if r is not None]
    rank_reliable = bool(ranks) and len(ranks) == len(set(ranks)) \
        and sorted(ranks) == list(range(1, len(ranks) + 1))

    return {"role_bands": dict(role_bands), "role_rank": role_rank,
            "rank_map": rank_map, "rank_reliable": rank_reliable,
            "pan_bands": sorted(pan_bands), "wavelength": wavelength,
            "candidates": candidates}


def load_products() -> list[dict]:
    raw = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    return [x for cat in raw for x in cat["products"]]


def load_param_index() -> tuple[dict, dict]:
    """
    加载算子参数。优先用 --scan 产出的 operator_params_all.json；
    若工程目录没有该文件，则回退到原始 schema（operator_schemas_all.json /
    operators_all.json）现场展开，保证脚本在任何布局下都能跑。
    """
    params = collections.defaultdict(dict)
    alias = {}

    if OPERATORS_FILE.exists():
        for r in json.loads(OPERATORS_FILE.read_text(encoding="utf-8")):
            params[r["operator"]][r["param"]] = r
            alias.setdefault(r["operator"], r.get("operator_alias"))
        return params, alias

    for cand in (DATA / "operator_schemas_all.json", DATA / "operators_all.json"):
        if not cand.exists():
            continue
        raw = json.loads(cand.read_text(encoding="utf-8"))
        items = raw.values() if isinstance(raw, dict) else raw
        for op in items:
            name = op.get("name")
            if not name:
                continue
            alias.setdefault(name, op.get("alias"))
            for a in op.get("args") or []:
                params[name][a.get("name")] = {
                    "param_alias": a.get("alias"), "type": a.get("type"),
                    "default": a.get("default"), "desc": a.get("description"),
                }
        break
    return params, alias


# ---------------------------------------------------------------- 样本构建
def build_samples(task: str, products: list[dict], pidx: dict,
                  params: dict, alias: dict) -> list[dict]:
    spec = TASK_DEFS[task]
    answer_kind = spec["answer"]
    need_rank = answer_kind == "band_index"      # 序号类要求 rank 可信
    samples: list[dict] = []

    for prod in products:
        pi = pidx.get(prod.get("name") or "")
        if not pi:
            continue
        if need_rank and not pi["rank_reliable"]:
            continue

        for op_name, need in spec["ops"].items():
            # T4 混合作子：answer_as 决定该算子出序号还是波段名
            as_index = need.get("answer_as") == "index"
            need_rank = as_index or answer_kind == "band_index"
            if need_rank and not pi["rank_reliable"]:
                continue
            plan, ok = [], True
            for pname, role in need.items():
                if role is None or pname == "answer_as":   # 附属参数，不出题
                    continue
                if role == PAN_ROLE:
                    if not pi["pan_bands"]:
                        ok = False
                        break
                    plan.append((pname, PAN_ROLE, pi["pan_bands"][0]))
                elif isinstance(role, tuple):
                    got = []
                    for r in role:
                        if r not in pi["role_rank"]:
                            ok = False
                            break
                        got.append(pi["role_rank"][r])
                    if not ok:
                        break
                    plan.append((pname, list(role), got))
                else:
                    if role not in pi["role_rank"]:
                        ok = False
                        break
                    plan.append((pname, role, pi["role_rank"][role]))
            if not ok or not plan:
                continue

            # 由波段标签转成该任务的答案形式
            use_index = need_rank
            # v2: 序号基址按参数自身语义
            #   bandIndex（OGE 原生 histogramBin / reduceRegion）→ 从 0 起（平台描述明写「索引从0开始递增」，默认值 0）
            #   band（GDAL/QGIS）、channel（OTB）、bandList → 从 1 起（描述明写「从 1 起始」，默认值 1）
            zero_base = any(pn in ZERO_BASED_PARAMS for pn, _, _ in plan)
            gt, gt_desc = {}, {}
            for pname, role, ans in plan:
                if use_index:
                    def _rank(x):
                        r = pi["rank_map"].get(x)
                        return None if r is None else (r - 1 if zero_base else r)
                    # panSharp 的 bandList 是列表 -> 序号也要成列表
                    if isinstance(ans, list):
                        idxs = [_rank(x) for x in ans]
                    else:
                        idxs = _rank(ans)
                    if idxs is None or (isinstance(idxs, list) and None in idxs):
                        ok = False
                        break
                    gt[pname] = idxs
                    joined = "/".join(ans) if isinstance(ans, list) else ans
                    gt_desc[pname] = (f"波段 {joined} 的序号为 {idxs}")
                else:
                    gt[pname] = ans
                    gt_desc[pname] = (
                        f"全色波段 {ans}" if role == PAN_ROLE
                        else (f"{'/'.join(role)} -> {ans}" if isinstance(role, list)
                              else f"{role} -> {ans}"))
            if not ok or not gt:
                continue

            samples.append({
                # v2: 保留命名空间，避免 Coverage.addStyles 与
                # CoverageCollection.addStyles 生成同名 id（旧版 22 处碰撞）
                "sample_id": f"{task}_{prod['name']}_{op_name.replace('.', '_')}",
                "task": task,
                "task_label": spec["label"],
                "answer_type": answer_kind,
                "product_name": prod.get("name"),
                "product_alias": prod.get("alias"),
                "product_desc": (prod.get("description") or "").strip()[:300],
                "sensor": prod.get("sensor"),
                "operator": {
                    "name": op_name,
                    "alias": alias.get(op_name),
                    "params": [{
                        "param": p, "role": r,
                        "alias": (params.get(op_name, {}).get(p) or {}).get("param_alias"),
                        "type": (params.get(op_name, {}).get(p) or {}).get("type"),
                        "default": (params.get(op_name, {}).get(p) or {}).get("default"),
                        "description": (params.get(op_name, {}).get(p) or {}).get("desc"),
                    } for p, r, _ in plan],
                },
                "ground_truth": gt,
                "ground_truth_desc": gt_desc,
                "band_options": pi["candidates"],
                "band_roles_available": pi["role_rank"],
                "pan_bands": pi["pan_bands"],
                "band_wavelengths": pi["wavelength"],
                "rank_map": pi["rank_map"],
                "candidate_count": len(pi["candidates"]),
            })
    return samples


def scan() -> dict:
    products = load_products()
    params, alias = load_param_index()
    pidx = {}
    for p in products:
        pi = product_band_index(p)
        if pi:
            pidx[p.get("name")] = pi

    out = {
        "product_total": len(products),
        "product_usable": len(pidx),
        "product_rank_reliable": sum(1 for v in pidx.values() if v["rank_reliable"]),
        "tasks": {},
    }
    for t in TASK_DEFS:
        s = build_samples(t, products, pidx, params, alias)
        ops = collections.Counter(x["operator"]["name"] for x in s)
        cand_sets = {"\x1f".join(x["band_options"]) for x in s}
        prod_sets = {x["product_name"] for x in s}
        out["tasks"][t] = {
            "label": TASK_DEFS[t]["label"],
            "desc": TASK_DEFS[t]["desc"],
            "answer_type": TASK_DEFS[t]["answer"],
            "operators": sorted(ops),
            "operator_count": len(ops),
            "sample_count": len(s),
            "product_count": len(prod_sets),
            "unique_candidate_sets": len(cand_sets),
            "per_operator": dict(ops.most_common()),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="扫描全平台波段算子分布")
    ap.add_argument("--build", action="store_true", help="构建扩展评测集")
    ap.add_argument("--report", action="store_true", help="统计各任务可造样本量")
    ap.add_argument("--task", default="", help="只构建某一类任务，如 T2")
    a = ap.parse_args()

    if not (a.scan or a.build or a.report):
        ap.print_help()
        return

    products = load_products()
    params, alias = load_param_index()
    pidx = {p.get("name"): product_band_index(p) for p in products}
    pidx = {k: v for k, v in pidx.items() if v}

    if a.scan or a.report:
        rel = sum(1 for v in pidx.values() if v["rank_reliable"])
        print(f"产品总数 {len(products)}  可用 {len(pidx)}  "
              f"bandRank 可信 {rel}\n")
        print(f"{'任务':<5}{'名称':<16}{'算子':>5}{'样本':>7}{'产品':>6}{'唯一候选集':>11}")
        print("-" * 54)
        for t, v in TASK_DEFS.items():
            s = build_samples(t, products, pidx, params, alias)
            ops = {x["operator"]["name"] for x in s}
            prods = {x["product_name"] for x in s}
            cs = {"\x1f".join(x["band_options"]) for x in s}
            print(f"{t:<5}{v['label']:<16}{len(ops):>5}{len(s):>7}"
                  f"{len(prods):>6}{len(cs):>11}")
        if a.scan:
            for t, v in TASK_DEFS.items():
                s = build_samples(t, products, pidx, params, alias)
                c = collections.Counter(x["operator"]["name"] for x in s)
                print(f"\n[{t}] {v['label']} —— {v['desc']}")
                for op, n in c.most_common():
                    print(f"    {op:<48}{n:>5}")
        rep = scan()
        OUT_INDEX.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n索引已写出：{OUT_INDEX.name}")

    if a.build:
        tasks = [a.task] if a.task else list(TASK_DEFS)
        all_s = []
        for t in tasks:
            s = build_samples(t, products, pidx, params, alias)
            all_s += s
            print(f"[{t}] {TASK_DEFS[t]['label']}: {len(s)} 条")
        OUT_MATCHING.write_text(json.dumps(all_s, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        print(f"\n扩展评测集：{len(all_s)} 条 -> {OUT_MATCHING.name}")


if __name__ == "__main__":
    main()
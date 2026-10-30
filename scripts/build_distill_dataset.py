#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 1：蒸馏/微调数据集构建

设计要点：
  1. 评测集（611/288）冻结不动；本脚本只产出训练集 train/val.jsonl
     与评测集的「泛化切片」索引（留出产品的样本 id 列表）。
  2. 切分按「波段表指纹」聚类后整族同侧——MODIS 系/GF 系/S2 系等
     近重复产品绝不允许跨 train/test，防止变相泄漏。
  3. 训练样本 = 基准管线（build_samples）+ T2 类算子的角色变体
     （「任意波段均可」的算子换角色重新出题，真值仍由波长推导）。
  4. 每条样本同时带 ground_truth（硬标签）字段；
     软标签由 label_distill_teacher.py 事后用 Jev 补充。
  5. modes 字段记录两种输入条件，训练时由训练器展开（不落盘重复）。

用法：python scripts/build_distill_dataset.py
产出：data/distill/train.jsonl, val.jsonl, stats.json,
      data/distill/heldout_slice_index.json
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_band_benchmark as BBB  # noqa: E402

DATA = HERE.parent / "data"
OUT = DATA / "distill"

# ---------------------------------------------------------------- 切分表
# 指纹聚类后手工定稿（近重复产品整族同侧）：
TEST_PRODUCTS = [
    "LC08_C02_L1", "LC08_C02_L2", "LC08_L1T", "LC09_C02_L1", "LC09_C02_L2",
    "LC_Ref",                                   # 现代 Landsat 簇
    "LJ4I_HSI_5B", "LJ3II_L1B_Fusion",          # 珞珈（5B/融合，指纹独立）
    "S2A_MSIL2A", "S2_MSIL2A",                  # S2 L2A 簇
]
DEV_PRODUCTS = [
    "LT05_L1TP_C02_T1",                         # Landsat-5（指纹 ≠ L8/9）
    "S2A_MSIL1C", "S2_MSIL1C",                  # S2 L1C 簇
    "LJ4I_HSI_17B",                             # 珞珈高光谱 17B（≠32B/5B）
]
# 其余基准产品（20 个）→ TRAIN：MODIS 全簇 10（MOD/MYD/MODIS09A1、09Q1、
# 13A1、13Q1）+ GF 全簇 5（GF1×4 + GF6）+ HiGLASS + CN_FCH30_2020
# + LJ4I_HSI_32B + S2A_MSIL1C + S2B_MSIL1C。
# 注：S2A_MSIL1C 原钉在 DEV，因与 S2B_MSIL1C（train）指纹完全相同，
# 被下面 assign_splits 的纯性校验整簇归并到 train，故 dev 实为 3 个。
# 最终口径：test 10 / dev 3 / train 20 = 33（以 stats.json 为准）。

# ---------------------------------------------------------------- 角色变体
# v2：T2 全部 16 个「任意波段均可」类算子都做角色变体（原 5 个 → 16 个），
# 目的是让「按角色选波段」的能力覆盖每个 T2 算子，而不是让学生把
# 算子名记成固定答案。合法角色仍受产品实际波段约束（缺角色的产品自然跳过）。
VAR_ALL = ["蓝", "绿", "红", "近红外", "短波红外1", "短波红外2"]
# GDAL/QGIS 地形与统计类（band）、OTB 纹理类（channel）、OGE 原生统计（bandIndex）
VARIANT_ROLES = {
    "Coverage.reduceRegion":  VAR_ALL,
    "Coverage.histogramBin":  VAR_ALL,
    "Coverage.polygonizeByGDAL":     VAR_ALL,
    "Coverage.contourByGDAL":        VAR_ALL,
    "Coverage.contourPolygonByGDAL": VAR_ALL,
    "Coverage.aspectByGDAL":  VAR_ALL,
    "Coverage.hillShadeByGDAL": VAR_ALL,
    "Coverage.slopeByGDAL":   VAR_ALL,
    "Coverage.roughnessByGDAL": VAR_ALL,
    "Coverage.fillNodataByGDAL": VAR_ALL,
    "Coverage.proximityByGDAL": VAR_ALL,
    "Coverage.tpiTopographicPositionIndexByGDAL": VAR_ALL,
    "Coverage.triTerrainRuggednessIndexByGDAL": VAR_ALL,
    "Coverage.rescaleRasterByQGIS": VAR_ALL,
    "Coverage.SFSTextureExtractionByOTB": VAR_ALL,
    "Coverage.edgeExtractionByOTB": VAR_ALL,
}
CN_ALIAS = {"蓝": "blue", "绿": "green", "红": "red", "近红外": "nir",
            "短波红外1": "swir1", "短波红外2": "swir2"}


def family(name: str) -> str:
    for prefix, fam in [("LC", "Landsat"), ("LT05", "Landsat"), ("LC09", "Landsat"),
                        ("MOD", "MODIS"), ("MYD", "MODIS"), ("MODIS", "MODIS"),
                        ("S2", "Sentinel"), ("LJ", "珞珈"), ("GF", "高分")]:
        if name.startswith(prefix):
            return fam
    return "其他"


def fingerprint(prod: dict) -> tuple:
    """波段表指纹：标签+波长四舍五入后排序，用于近重复聚类。
    注意 load_products 展开的产品用 bands 字段（bandNum=标签）。"""
    bands = prod.get("bands") or []
    sig = sorted((b.get("bandNum") or "",
                  round(b.get("spectrumMin") or 0),
                  round(b.get("spectrumMax") or 0)) for b in bands)
    return tuple(sig)


def assign_splits(products: list[dict], bench_products: set[str]) -> dict[str, str]:
    """按 TEST/DEV 钉住名单分配；非基准产品排除；校验指纹簇不跨侧。"""
    split = {}
    for p in products:
        n = p["name"]
        if n not in bench_products:
            split[n] = "exclude"
        elif n in TEST_PRODUCTS:
            split[n] = "test"
        elif n in DEV_PRODUCTS:
            split[n] = "dev"
        else:
            split[n] = "train"
    # 指纹簇纯性校验（仅基准产品）
    clusters: dict[tuple, set[str]] = {}
    for p in products:
        if split[p["name"]] == "exclude":
            continue
        clusters.setdefault(fingerprint(p), set()).add(split[p["name"]])
    bad = {k: v for k, v in clusters.items() if len(v) > 1}
    for fp, sides in bad.items():
        names = [p["name"] for p in products if fingerprint(p) == fp]
        print(f"[警告] 指纹簇跨侧 {sides}: {names} —— 以多数侧归并")
        majority = "train" if "train" in sides else ("test" if "test" in sides else "dev")
        for n in names:
            split[n] = majority
    return split


def gen_variants(task: str, products: list[dict], pidx: dict,
                 params: dict, alias: dict) -> list[dict]:
    """对 TASK_DEFS 深拷贝换角色表后调用 build_samples 生成变体。"""
    out = []
    orig_ops = BBB.TASK_DEFS[task]["ops"]
    for op_name, roles in VARIANT_ROLES.items():
        if op_name not in orig_ops:
            continue
        param_name = next(iter(orig_ops[op_name]))
        for role in roles:
            tag = CN_ALIAS.get(role, role)
            patched = copy.deepcopy(orig_ops)
            patched[op_name] = {param_name: role}
            BBB.TASK_DEFS[task]["ops"] = patched
            try:
                got = BBB.build_samples(task, products, pidx, params, alias)
            finally:
                BBB.TASK_DEFS[task]["ops"] = orig_ops
            for s in got:
                s["sample_id"] = f"{s['sample_id']}_{tag}_var"
                s["is_variant"] = True
                s["variant_role"] = role
            out.extend(got)
    return out


def main() -> None:
    products_all = BBB.load_products()
    params, alias = BBB.load_param_index()
    pidx = {}
    for p in products_all:
        pi = BBB.product_band_index(p)
        if pi:
            pidx[p["name"]] = pi

    # 基准产品集合（冻结评测集的产品）
    ext = json.loads((DATA / "dataset_matching_extended.json").read_text(encoding="utf-8"))
    # v1 main set (dataset_matching.json) removed from the release; its product set
    # is a subset of the v2 benchmark, so the union (and thus the derived splits)
    # is unchanged. Keep the union form for backward compatibility.
    v1_path = DATA / "dataset_matching.json"
    main = json.loads(v1_path.read_text(encoding="utf-8")) if v1_path.exists() else []
    bench_products = ({s["product_name"] for s in ext}
                      | {s["product_name"] for s in main})
    bench = [p for p in products_all if p["name"] in bench_products]
    split = assign_splits(bench, bench_products)

    train_p = [p for p in bench if split[p["name"]] == "train"]
    val_p = [p for p in bench if split[p["name"]] == "dev"]

    # 每任务生成：固定口径 + 角色变体（仅 T2）
    pools = {"train": train_p, "val": val_p}
    result: dict[str, list] = {"train": [], "val": []}
    for side, plist in pools.items():
        for task in ["T1", "T2", "T3", "T4", "T5"]:
            base = BBB.build_samples(task, plist, pidx, params, alias)
            for s in base:
                s["is_variant"] = False
                s["modes"] = ["labels_only", "with_wavelength"]
            result[side].extend(base)
            if task == "T2":
                var = gen_variants(task, plist, pidx, params, alias)
                for s in var:
                    s["modes"] = ["labels_only", "with_wavelength"]
                result[side].extend(var)

    # 泛化切片索引：评测集中属于留出产品的样本 id
    test_names = {n for n, s in split.items() if s == "test"}
    slice_ext = [s["sample_id"] for s in ext if s["product_name"] in test_names]
    slice_main = [s["sample_id"] for s in main if s["product_name"] in test_names]

    OUT.mkdir(parents=True, exist_ok=True)
    for side, rows in result.items():
        with (OUT / f"{side}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 统计
    def stats(rows: list) -> dict:
        by_task = collections.Counter(r["task"] for r in rows)
        by_prod = collections.Counter(r["product_name"] for r in rows)
        variants = sum(1 for r in rows if r.get("is_variant"))
        cand = {json.dumps(sorted(r["band_options"]), ensure_ascii=False) for r in rows}
        return {"n": len(rows), "by_task": dict(by_task),
                "n_products": len(by_prod), "n_variant": variants,
                "unique_candidate_sets": len(cand)}

    stats_out = {
        "splits": {k: stats(v) for k, v in result.items()},
        "split_products": {k: sorted(p["name"] for p in v) for k, v in pools.items()},
        "test_products": sorted(test_names),
    }
    (OUT / "stats.json").write_text(json.dumps(stats_out, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (OUT / "heldout_slice_index.json").write_text(json.dumps(
        {"extended": slice_ext, "main": slice_main,
         "test_products": sorted(test_names)}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print("=" * 64)
    print("蒸馏数据集构建完成")
    print("=" * 64)
    for side in ["train", "val"]:
        s = stats_out["splits"][side]
        print(f"{side}: {s['n']} 条 | 按任务 {s['by_task']} | "
              f"变体 {s['n_variant']} | 产品 {s['n_products']} | "
              f"唯一候选集 {s['unique_candidate_sets']}")
    print(f"留出产品: {sorted(test_names)}")
    print(f"泛化切片: extended {len(slice_ext)} 条 + main {len(slice_main)} 条")
    print(f"软标签: 待 label_distill_teacher.py（Jev, ~$0.25）")


if __name__ == "__main__":
    import collections  # noqa: E402
    main()

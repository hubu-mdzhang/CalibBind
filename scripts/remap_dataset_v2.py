#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把既有评测集按 v2 角色规则重映射（保留题号与题面，只更新真值/候选/角色表）。

用于 288 主集：题目集合不变，仅把 ground_truth 及其依赖字段换成 v2 结果；
若某题所需角色在新规则下已不存在（如 GF6 的红边被误当 SWIR1），该题剔除。

用法：python scripts/remap_dataset_v2.py --in data/dataset_matching.json --out data/dataset_matching.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_band_benchmark as B  # noqa: E402

DATA = HERE.parent / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=str(DATA / "dataset_matching.json"))
    ap.add_argument("--out", dest="dst", default=str(DATA / "dataset_matching.json"))
    a = ap.parse_args()

    rows = json.loads(Path(a.src).read_text(encoding="utf-8"))
    prods = {p["name"]: p for p in B.load_products()}
    pidx = {}
    for n, p in prods.items():
        pi = B.product_band_index(p)
        if pi:
            pidx[n] = pi

    kept, dropped = [], []
    changed = 0
    for r in rows:
        pid = r["product_name"]
        pi = pidx.get(pid)
        if not pi:
            dropped.append((r["sample_id"], "产品不可用"))
            continue
        gt, miss = {}, None
        for role in r["required_roles"]:
            lab = pi["role_rank"].get(role)
            if lab is None:
                miss = role
                break
            gt[role] = lab
        if miss:
            dropped.append((r["sample_id"], f"缺角色 {miss}"))
            continue
        if gt != r["ground_truth"]:
            changed += 1
        r["ground_truth"] = gt
        r["band_options"] = pi["candidates"]
        r["band_roles_available"] = pi["role_rank"]
        r["band_wavelengths"] = pi["wavelength"]
        kept.append(r)

    Path(a.dst).write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"保留 {len(kept)} / {len(rows)} | 真值变化 {changed} | 剔除 {len(dropped)}")
    if dropped:
        import collections
        print("剔除原因:", dict(collections.Counter(x[1] for x in dropped)))
        print("剔除样例:", dropped[:5])


if __name__ == "__main__":
    main()

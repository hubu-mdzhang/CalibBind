#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 0.1：OGE 平台波段算子全普查

对 operator_params_all.json（全平台 2195 参数）逐算子分类，
回答「平台上到底有多少算子需要绑定波段」：

  Tier A  resource_type=band 的参数（类型系统直接标注）
  Tier B  参数名/别名命中波段模式，但 resource_type 未标 band
          （T2 的 bandIndex、T3 的 List、T4 的融合参数都在这层）
  Tier C  仅算子描述提及波段（疑似，需人工复核，不计入主口径）

并给出与 band_task_index.json（T1~T5 已覆盖 29 算子）的对账：
覆盖了谁、漏了谁、漏的原因线索。

用法：python scripts/census_band_operators.py
产出：data/census_band_operators.json + 控制台汇总表
"""
from __future__ import annotations

import json
import re
import collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"

PARAMS_FILE = DATA / "operator_params_all.json"
INDEX_FILE = DATA / "band_task_index.json"
OUT_FILE = DATA / "census_band_operators.json"

# 参数名/别名波段模式（Tier B）。band 用词边界，排除 bandwidth 之类
BAND_NAME_RE = re.compile(
    r"(band|channel)s?$|^(band|channel)[_A-Z]|_band|_channel|band[a-z]*$",
    re.I,
)
BAND_EXCLUDE_RE = re.compile(r"bandwidth|vibration", re.I)
CN_ALIAS_RE = re.compile(r"波段|通道|全色")

# 显式融合参数名（broveyFusion.mul/pan：名字不含 band，靠角色/描述定位）
FUSION_PARAM_RE = re.compile(r"^(mul|pan)$", re.I)


def param_hit(p: dict) -> tuple[str | None, str]:
    """返回 (命中层, 证据)。未命中返回 (None, '')。"""
    name = (p.get("param") or "")
    alias = (p.get("param_alias") or "")
    desc = (p.get("desc") or "")
    rtype = p.get("resource_type") or ""

    # 排除假阳性：地理加权回归的核带宽（bandWidth/带宽，单位公里）等
    joined = f"{name} {alias}"
    if BAND_EXCLUDE_RE.search(joined) or "带宽" in alias:
        return None, ""

    if rtype == "band":
        return "A", f"resource_type=band ({name})"

    if BAND_NAME_RE.search(name):
        return "B", f"参数名命中 ({name})"
    if CN_ALIAS_RE.search(alias):
        return "B", f"别名命中 ({alias})"
    if FUSION_PARAM_RE.match(name) and ("波段" in desc or "全色" in desc):
        return "B", f"融合参数 ({name})"

    if rtype == "band_range":
        return "C", f"band_range 约束型 ({name})"
    if "波段" in desc and "继承" not in desc:
        return "C", "仅描述提及波段（疑似）"
    return None, ""


def main() -> None:
    params = json.loads(PARAMS_FILE.read_text(encoding="utf-8"))
    ops: dict[str, list[dict]] = collections.defaultdict(list)
    for p in params:
        ops[p["operator"]].append(p)

    census = {}
    for op, plist in sorted(ops.items()):
        hits = []
        for p in plist:
            tier, why = param_hit(p)
            if tier:
                hits.append({"param": p.get("param"), "type": p.get("type"),
                             "resource_type": p.get("resource_type"),
                             "tier": tier, "why": why})
        if not hits:
            continue
        tiers = {h["tier"] for h in hits}
        tier = "A" if "A" in tiers else ("B" if "B" in tiers else "C")
        census[op] = {
            "alias": plist[0].get("operator_alias"),
            "namespace": plist[0].get("namespace"),
            "tier": tier,
            "n_params": len(plist),
            "band_params": hits,
        }

    # 对账：T1~T5 已覆盖
    idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    covered = {op: t for t, v in idx["tasks"].items() for op in v["operators"]}

    ab = {op: c for op, c in census.items() if c["tier"] in ("A", "B")}
    cov_in_census = {op: covered[op] for op in ab if op in covered}
    cov_not_in_census = {op: t for op, t in covered.items() if op not in census}
    uncov = {op: c for op, c in ab.items() if op not in covered}

    print("=" * 72)
    print("OGE 平台波段算子普查")
    print("=" * 72)
    print(f"全平台算子           : {len(ops)}")
    print(f"命中波段参数的算子   : {len(census)}  (A={sum(1 for c in census.values() if c['tier']=='A')}"
          f"  B={sum(1 for c in census.values() if c['tier']=='B')}"
          f"  C={sum(1 for c in census.values() if c['tier']=='C')})")
    print(f"主口径 A+B           : {len(ab)}")
    print(f"T1~T5 已覆盖         : {len(covered)}")
    print(f"  其中落在 A+B       : {len(cov_in_census)}")
    print(f"  已覆盖但普查未命中 : {len(cov_not_in_census)}  {sorted(cov_not_in_census)[:5]}")
    print(f"A+B 中未覆盖         : {len(uncov)}")

    # 未覆盖算子的答案形态线索
    forms = collections.Counter()
    for op, c in uncov.items():
        types = {h["type"] for h in c["band_params"]}
        key = "+".join(sorted(t or "?" for t in types))
        forms[key] += 1
    print("\n未覆盖算子的参数类型组合分布:")
    for k, n in forms.most_common(10):
        print(f"  {n:3d}  {k}")

    out = {
        "meta": {
            "total_operators": len(ops),
            "total_params": len(params),
            "census_hit": len(census),
            "ab_main": len(ab),
            "covered_t1t5": len(covered),
        },
        "reconciliation": {
            "covered_and_hit": cov_in_census,
            "covered_not_hit": cov_not_in_census,
        },
        "operators": census,
    }
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已保存 {OUT_FILE.name}")

    # 打印 A/B 级未覆盖清单（前 40）
    print("\n[A+B 未覆盖清单]（答案形态待逐个归因）")
    for op, c in list(uncov.items())[:40]:
        ps = ", ".join(f"{h['param']}({h['type']})" for h in c["band_params"][:3])
        print(f"  {op:<52} {ps}")


if __name__ == "__main__":
    main()

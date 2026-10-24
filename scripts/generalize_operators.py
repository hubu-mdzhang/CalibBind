#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用算子参数匹配器 —— 把波段匹配的思路扩展到全部 489 个算子。

动机：
    原波段匹配只覆盖 4 个算子（NDVI/NDWI/NDBI/NDSSI），
    但 OGE 平台有 489 个算子，其中大量算子的参数同样需要绑定数据资源：
      - 产品 ID（coverageID / productID）
      - 波段名（redBandName / nirBandName）
      - 矢量图层、掩膜、空间范围
    这些参数同样存在「命名异构、需人工查文档」的痛点。

本脚本提供：
    1. 全平台算子参数扫描与分类
    2. 参数类型识别（波段 / 产品 / 矢量 / 数值 / 字符串）
    3. 生成「参数类型」维度的评测集，把基准扩展到非波段算子

用法：
    # 扫描全平台算子参数
    python generalize_operators.py --scan

    # 只看某类参数
    python generalize_operators.py --scan --filter band

    # 构建扩展评测集（产品 ID 绑定场景）
    python generalize_operators.py --build --task product_id

    # 统计各类参数占比
    python generalize_operators.py --stats
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from config_loader import get_config

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

# ---------------------------------------------------------------- 参数类型识别规则
# 依据参数名与默认值判断参数绑定的资源类型
PARAM_TYPE_RULES = [
    ("band", re.compile(r"band|波段|spectrum", re.I),
     ["bandName", "bandNameArray", "redBandName", "nirBandName"]),
    ("product_id", re.compile(r"productID|productId|coverageID|coverageId|datasetID|"
                              r"imageID|sceneID|影像|产品编号", re.I),
     ["productID", "coverageID"]),
    ("vector", re.compile(r"feature|vector|shapefile|polygon|图层|矢量", re.I),
     ["featureCollection", "vectorLayer"]),
    ("band_range", re.compile(r"range|window|subset|crop|裁剪|范围|分辨率", re.I),
     ["range", "subset"]),
    ("threshold", re.compile(r"threshold|thresh|阈值", re.I), ["threshold"]),
    ("date", re.compile(r"date|time|year|month|时间|日期", re.I),
     ["dateRange", "startDate"]),
    ("numeric", re.compile(r"^(?!.*band).*[Nn]umber|[Ff]actor|size|count|比例|系数", re.I),
     []),
]

# 参数名 → 中文说明（用于生成评测集的 instructions）
PARAM_DESC = {
    "productID": "数据产品 ID",
    "coverageID": "影像 Coverage ID",
    "bandName": "波段名称",
    "redBandName": "红光波段名称",
    "nirBandName": "近红外波段名称",
    "greenBandName": "绿光波段名称",
    "blueBandName": "蓝光波段名称",
    "swirBandName": "短波红外波段名称",
    "tirBandName": "热红外波段名称",
}


def classify_param(name: str, default=None, ptype: str = "") -> str:
    """
    判断参数绑定的资源类型。

    优先级：平台声明的 type > 参数名模式 > 默认值形态。

    实测平台 type 字段取值：Coverage / FeatureCollection / String /
    List[String] / Double / Integer / Boolean / Any 等。
    其中 Coverage 与 FeatureCollection 才是真正的「资源绑定」，
    其余属标量参数，不需要匹配。
    """
    n = name or ""
    d = str(default) if default is not None else ""
    t = str(ptype or "")

    # 1. 平台声明的资源类型最可靠
    if t == "Coverage":
        return "coverage"          # 影像引用（栅格数据）
    if t == "FeatureCollection":
        return "vector"            # 矢量要素集合
    if t == "List[Coverage]":
        return "coverage_list"
    if t == "List[FeatureCollection]":
        return "vector_list"

    # 2. 参数名模式
    for ptype2, pat, _ in PARAM_TYPE_RULES:
        if pat.search(n):
            return ptype2

    # 3. 默认值形态
    if re.fullmatch(r"\d{4}[-_]?\d{2}[-_]?\d{2}([_-]?[\w]+)?", d):
        return "date"
    if d in ("", "None", "null"):
        return "scalar"            # 标量参数，非资源绑定
    if re.fullmatch(r"-?\d+(\.\d+)?", d):
        return "numeric"
    return "scalar"


# ---------------------------------------------------------------- 扫描
def fetch_models() -> list[dict]:
    """拉取全平台算子清单。

    注意：平台接口忽略 pageNo（实测三页内容相同，currentPage 恒为 1），
    但 pageSize 生效 —— 必须单次大页拉全量并去重，
    旧版逐页循环会默默去重成第 1 页的 100 个（全量实为 489）。
    """
    import requests
    cfg = get_config()
    url = cfg.platform_base_url + "/model/listByTags4Catalog"
    r = requests.post(url, json={"pageNo": 1, "pageSize": 1000},
                      headers=cfg.platform_headers(),
                      timeout=cfg.platform_timeout)
    r.raise_for_status()
    d = r.json().get("data") or {}
    seen, out = set(), []
    for rec in d.get("records") or []:
        key = rec.get("functionName") or rec.get("name") or id(rec)
        if key not in seen:
            seen.add(key)
            out.append(rec)
    return out


def fetch_params(function_name: str) -> dict:
    """
    拉取单个算子的参数 schema。

    注意：接口返回的 data 是 **JSON 字符串**而非对象，
    需二次解析；参数数组字段名为 args。
    """
    import requests
    cfg = get_config()
    url = cfg.platform_base_url + "/model/getModelParamJson"
    try:
        r = requests.get(url, params={"functionName": function_name},
                         headers=cfg.platform_headers(),
                         timeout=cfg.platform_timeout)
        r.raise_for_status()
        d = r.json().get("data")
        if isinstance(d, str):
            d = json.loads(d)
        return d or {}
    except Exception:
        return {}


def cmd_scan(args):
    """扫描全平台算子参数。"""
    cfg = get_config()
    mods = fetch_models()
    print(f"算子总数: {len(mods)}")
    if cfg.has_credentials():
        print("凭据: 已配置（可访问私有资源）")
    else:
        print("凭据: 未配置（公开接口免鉴权，可正常扫描）")

    print(f"\n{'=' * 62}\n  扫描算子参数（耗时较长，约 {len(mods)} 次请求）\n{'=' * 62}")

    records = []
    for i, m in enumerate(mods, 1):
        fn = m.get("name")
        if args.filter and args.filter.lower() not in fn.lower():
            continue
        schema = fetch_params(fn)
        # 参数数组在 args 字段；description 是算子说明而非参数说明
        params = schema.get("args") or schema.get("params") or []
        if not params:
            continue
        for p in params:
            pname = p.get("name") or p.get("paramName")
            if not pname:
                continue
            records.append({
                "operator": fn,
                "operator_alias": m.get("alias"),
                "namespace": fn.split(".")[0],
                "param": pname,
                "param_alias": p.get("alias"),
                "type": p.get("type"),
                "default": p.get("default"),
                "optional": p.get("optional"),
                "desc": (p.get("description") or "")[:200],
                "resource_type": classify_param(pname, p.get("default"),
                                                 p.get("type")),
            })
        if i % 60 == 0:
            print(f"  {i}/{len(mods)}  已收集 {len(records)} 个参数")

    DATA.mkdir(exist_ok=True)
    out = DATA / "operator_params_all.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n已保存 {out.name}（{len(records)} 个参数）")

    if records:
        dist = collections.Counter(r["resource_type"] for r in records)
        print("\n=== 资源类型分布 ===")
        for t, c in dist.most_common():
            print(f"  {t:14} {c:5}")
    return records


def cmd_stats(args):
    """统计算子与参数类型分布 —— 论证扩展空间的依据。"""
    mods = fetch_models()
    ns = collections.Counter(m["name"].split(".")[0] for m in mods)
    print(f"=== 算子命名空间分布（{len(mods)} 个算子）===")
    for k, v in ns.most_common(12):
        print(f"  {k:18} {v:4}")

    p = DATA / "operator_params_all.json"
    if p.exists():
        recs = json.loads(p.read_text(encoding="utf-8"))
        dt = collections.Counter(r["resource_type"] for r in recs)
        print(f"\n=== 参数资源类型（{len(recs)} 个参数）===")
        for k, v in dt.most_common():
            print(f"  {k:14} {v:5}")

        # 哪些命名空间的参数最需要自动绑定
        by_ns = collections.Counter(r["namespace"] for r in recs
                                    if r["resource_type"] in ("band", "product_id"))
        print(f"\n=== 需绑定数据资源的算子分布（按命名空间）===")
        for k, v in by_ns.most_common(10):
            print(f"  {k:18} {v:5}")
    else:
        print("\n（未找到参数扫描结果，先运行 --scan）")


def cmd_build(args):
    """
    构建扩展评测集：产品 ID 绑定场景。

    与波段匹配的差异：候选集是「可用影像列表」而非「波段列表」，
    但任务结构相同 —— 候选集封闭、有真值、需要语义匹配。
    """
    cats = json.loads((DATA / "dataset_products.json").read_text(encoding="utf-8"))

    # dataset_products.json 结构：[{category, catalogs, products:[{id,name,...}]}]
    # category 与 catalogs 可能是字符串或对象，需兼容
    flat = []
    for c in cats:
        cat = c.get("category")
        cat_name = ""
        if isinstance(cat, dict):
            cat_name = cat.get("name") or cat.get("alias") or ""
        elif isinstance(cat, str):
            cat_name = cat
        if not cat_name:
            cals = c.get("catalogs")
            if isinstance(cals, list) and cals:
                first = cals[0]
                if isinstance(first, dict):
                    cat_name = first.get("name") or ""
                else:
                    cat_name = str(first)
        for p in c.get("products") or []:
            p["_category"] = cat_name
            flat.append(p)

    out = []
    for p in flat:
        desc = p.get("description") or ""
        sample = p.get("sampleCode") or ""
        cid = None
        for src in (sample, desc):
            m = re.search(r'coverageID="([A-Za-z0-9_]+)"', src)
            if m:
                cid = m.group(1)
                break
        out.append({
            "product_id": p.get("id"),
            "product_name": p.get("name"),
            "product_alias": p.get("alias"),
            "category": p.get("_category"),
            "mission": p.get("mission"),
            "resolution": p.get("resolution"),
            "band_count": p.get("band_count"),
            "sample_coverage_id": cid,
        })

    f = DATA / "product_id_candidates.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    have = sum(1 for x in out if x["sample_coverage_id"])
    print(f"已生成 {f.name}")
    print(f"  产品 {len(out)} 个，其中 {have} 个的样例代码含 coverageID")
    print()
    print("产品 ID 绑定任务的候选集构建方式：")
    print("  候选集 = 用户数据目录下的可用影像列表（运行时动态获取）")
    print("  真值   = 按产品类型/传感器/时间范围/云量的规则判定")
    print("  差异   = 候选集非固定，需先过滤再匹配")
    print("  价值   = 与波段共享同一问题结构，可验证方法可迁移性")


def main():
    ap = argparse.ArgumentParser(description="通用算子参数匹配器")
    ap.add_argument("--scan", action="store_true", help="扫描全平台算子参数")
    ap.add_argument("--stats", action="store_true", help="统计算子与参数分布")
    ap.add_argument("--build", action="store_true", help="构建扩展评测集")
    ap.add_argument("--filter", default="", help="只扫描名字含此串的算子")
    ap.add_argument("--task", default="product_id",
                    help="扩展任务类型：product_id / vector / threshold")
    a = ap.parse_args()

    if not any([a.scan, a.stats, a.build]):
        a.stats = True
    if a.stats:
        cmd_stats(a)
    if a.scan:
        cmd_scan(a)
    if a.build:
        cmd_build(a)


if __name__ == "__main__":
    main()

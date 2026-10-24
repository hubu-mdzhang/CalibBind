#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
遥感算子波段参数匹配 —— 方案验证测试数据构建脚本

数据来源：OGE 开放地球引擎生产平台（免鉴权接口）
  产品清单POST /api/data-product/list
  产品详情  GET  /api/data-product/get?productId=&type=
  算子清单  POST /api/model/listByTags4Catalog      （注意分页参数是 pageNum）
  算子schema GET  /api/model/getModelParamJson?functionName=

产出：
  dataset_products.json10 类数据产品（含真实波段标签 + 波长范围）
  dataset_operators.json    带波段参数的算子（含参数 schema + 光谱角色）
  dataset_matching.json     匹配测试集（product x operator笛卡尔积）
  DATA_DICTIONARY.md        数据字典与统计报告
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from config_loader import get_config

CFG = get_config()
API_BASE = CFG.platform_base_url
INTERVAL = CFG.platform_interval
OUT = Path(__file__).resolve().parent.parent / "data"
S = requests.Session()

# ---------------------------------------------------------------- 光谱角色定义
# 按波长范围(nm)定义，这是自动标注 ground truth 的物理依据
ROLE_WAVELENGTHS = {
    "大气校正": (400, 460),
    "蓝":     (450, 520),
    "绿":     (520, 600),
    "红":     (620, 700),      # v2: 上界由 750 收到 700，排除红边（S2 B05/B06 = 705/741nm）
    "近红外": (790, 920),      # v2: 下界由 770 提到 790，排除红边3（S2 B07 = 775nm）
    "短波红外1": (1550, 1750),
    "短波红外2": (2080, 2350),
    "热红外": (10600, 12500),
}
# 同角色多解时的裁决基准（物理惯例中心波长，非窗口中点）
ROLE_CENTER = {
    "大气校正": 443, "蓝": 480, "绿": 560, "红": 665, "近红外": 850,
    "短波红外1": 1650, "短波红外2": 2200, "热红外": 11000,
}

# 光谱角色关键词（用于从英文波段标签反推角色）
# 注意：Landsat 系列是 SR_Bx编号制，必须按产品系列区分，
#不能沿用 B1=蓝/B2=绿/B3=红 的通用编号（那是 Sentinel-2 的约定）
ROLE_KEYWORDS_COMMON = {
    # v2 修正：coastal/aerosol 属于大气校正带，不再误归「蓝」
    "大气校正": [r"^coastal$", r"aerosol"],
    "蓝":     [r"^blue$", r"^blue[\s_-]?reflectance$"],
    "绿":     [r"^green$", r"^green[\s_-]?reflectance$"],
    # v2 修正：移出 red_edge/red-edge —— 红边不是红波段
    "红":     [r"^red$", r"^red[\s_-]?reflectance$"],
    "近红外": [r"^nir$", r"narrow[\s_-]?nir", r"near[\s_-]?infrared"],
    "短波红外1": [r"^swir$", r"swir[\s_-]?1"],
    # v2 修正：MIR(2.1µm) 归短波红外2，不再归 1
    "短波红外2": [r"swir[\s_-]?2", r"^mir$", r"^mir[\s_-]?reflectance$"],
    "热红外": [r"^tirs?$", r"thermal", r"lwir", r"^st_"],
}

# v2：按代际拆分的编号制（原表把 TM 与 OLI 混用，导致 LT05 的 B6/B7 错位）
LANDSAT_NUM = {"b1": "蓝", "b2": "绿", "b3": "红", "b4": "近红外",
               "b5": "短波红外1", "b6": "热红外", "b7": "短波红外2"}
LANDSAT8_NUM = {"b1": "大气校正", "b2": "蓝", "b3": "绿", "b4": "红", "b5": "近红外",
                "b6": "短波红外1", "b7": "短波红外2", "b10": "热红外", "b11": "热红外"}
# Sentinel-2 MSI：B5~B7 红边、B9 水汽、B10 卷云均无任务角色；B11=SWIR1、B12=SWIR2
SENTINEL_NUM = {"b1": "大气校正", "b2": "蓝", "b3": "绿", "b4": "红",
                "b8": "近红外", "b8a": "近红外",
                "b11": "短波红外1", "b12": "短波红外2"}
# MODIS：B6=1628nm(SWIR1)、B7=2105nm(SWIR2)
MODIS_NUM = {"b1": "红", "b2": "近红外", "b3": "蓝", "b4": "绿",
             "b6": "短波红外1", "b7": "短波红外2"}
# 国产多光谱只映射确定的前四波段，其余不乱猜
GF_NUM = {"b1": "蓝", "b2": "绿", "b3": "红", "b4": "近红外"}


def _num_map(product_name: str, alias: str = "") -> dict:
    """按产品系列选择编号制映射表。"""
    tag = f"{product_name} {alias}".upper()
    # OLI 系（Landsat 8/9）与 TM/ETM+（Landsat 5/7）编号不同，必须先判 OLI
    if any(k in tag for k in ("LC08", "LC09", "LC8", "LC9", "OLI")):
        return LANDSAT8_NUM
    if any(k in tag for k in ("LANDSAT", "LT05", "LT5", "LE07", "LC_")):
        return LANDSAT_NUM
    if "SENTINEL" in tag or "S2A" in tag or "S2B" in tag:
        return SENTINEL_NUM
    if "MODIS" in tag or "MOD13" in tag or "MOD11" in tag or "MYD" in tag:
        return MODIS_NUM
    return GF_NUM


def infer_role(band_label: str, num_map: dict | None = None,
               spec_min: float = None, spec_max: float = None,
               band_name: str = None) -> str | None:
    """
    由波段标签 + 波段名 + 波长推断光谱角色。

    证据优先级（波长最可靠）：
      1. 波长范围 -> role_by_wavelength（平台提供的真实 nm 值，物理事实）
      2. 自解释关键词（bandName 优先于 bandNum：bandName 是产品自身的语义）
      3. 产品系列编号制（Landsat / Sentinel-2 / MODIS / 国产多光谱）
    """
    # 1. 波长优先（吸收波段与全色宽带波段直接判为无角色）
    if spec_min is not None and spec_max is not None:
        if _band_is_absorption(band_label, spec_min, spec_max):
            return None
        if _is_panchromatic(spec_min, spec_max):
            # 全色波段跨度过宽，不对应单一光谱角色。
            # 即使标签形如 B1，也不能套编号制当成蓝波段
            # （实例：LJ4I_HSI_5B 的 B1 为 450~900nm，平台描述即「全色波段」）
            return None
        r = role_by_wavelength(spec_min, spec_max)
        if r:
            return r
    # 2. 关键词（bandName 比 bandNum 更有语义；两者都试）
    for cand in (band_name, band_label):
        if not cand:
            continue
        s = cand.strip()
        if _band_is_absorption(s, spec_min or 0, spec_max or 0):
            return None
        for role, pats in ROLE_KEYWORDS_COMMON.items():
            for p in pats:
                if re.search(p, s, re.I):
                    return role
    # 3. 编号制（仅适用于波段数不多的多光谱产品）
    if band_label and num_map:
        m = re.fullmatch(r"(?:sr_|st_)?b(\d{1,2}a?)", band_label.strip(), re.I)
        if m:
            g = m.group(1).lower()
            # v2: 去零填充（S2 的 B01/B02 与编号表的 b1/b2 对齐）
            key = "b" + (str(int(g[:-1])) + "a" if g.endswith("a") else str(int(g)))
            if key in num_map:
                return num_map[key]
    return None


ROLE_ALIAS = {
    "红": ["red"], "蓝": ["blue"], "绿": ["green"], "近红外": ["nir"],
    "短波红外1": ["swir"], "短波红外2": ["swir2"], "热红外": ["tir", "thermal"],
    "大气校正": ["coastal", "cst"],
}


# 吸收波段（大气吸收/水汽吸收区），不承载地表反射率信息，不作为光谱角色候选
ABSORPTION_BANDS = {
    "cirrus", "水汽", "coastal_wv", "cirrus_wv",
}


def _band_is_absorption(band_label: str, lo: float, hi: float) -> bool:
    """
    判断是否为吸收/非反射率波段。
    Sentinel-2 B10(1365-1385nm) 是卷云波段、B9(930-950nm) 是水汽吸收带，
    MODIS 的 raz/szen/vzen/state 等是观测几何量，都不应映射为光谱角色。
    """
    lbl = (band_label or "").lower()
    if any(k in lbl for k in ABSORPTION_BANDS):
        return True
    # 标签自带的语义判定
    if re.search(r"cirrus|_qc|state_|_raz|_szen|_vzen|day_of_year|solar_zenith|view_zenith|"
                 r"relative_azimuth|azimuth|quality|uncertaint|solar|view|angle|"
                 r"rel_azimuth|brdf|cloud|shadow|ice|snow|water_mask|qa_", lbl):
        return True
    # 波长落在已知吸收窗口（用中心波长判断）
    c = (lo + hi) / 2
    for (a, b) in [(1350, 1400), (920, 960), (1800, 1950)]:
        if a <= c <= b:
            return True
    return False


def _is_panchromatic(lo: float, hi: float) -> bool:
    """
    全色/宽带波段判定：波段起点落在可见光短波端（≤550nm）且跨度 >120nm。

    不能只看「宽度 > 120nm」：SWIR（1550~1750，宽 200nm）与
    热红外（10600~11190nm）同样超宽，但它们对应明确的短波红外/热红外角色，
    若一并判为全色，会让 LST(热红外)、NDBI(SWIR) 的候选集凭空丢掉正确波段。

    v2 修正：原判据「中心 450~900nm」会把 Landsat-5 B4 近红外
    （760~900nm，宽 140nm，中心 830）误判为全色，导致该产品丢失「近红外」角色。
    真全色带的共同特征是**起点在蓝/紫端**（Landsat 8 全色 500~680、
    GF/LJ 全色 450~900），因此改用「起点 ≤550nm」判定。
    """
    if lo is None or hi is None:
        return False
    if (hi - lo) <= 120:
        return False
    return lo <= 550


def role_by_wavelength(lo, hi) -> str | None:
    """
    由波长范围判断光谱角色（标签匹配失败时的兜底）。
    只做「中心波长落入区间」的严格判定，不做模糊距离匹配，
    避免 930nm 水汽带被误判成近红外。
    """
    if lo is None or hi is None:
        return None
    c = (lo + hi) / 2
    for role, (a, b) in ROLE_WAVELENGTHS.items():
        if a <= c <= b:
            return role
    return None


# ---------------------------------------------------------------- 采集
def fetch_all_operators() -> dict:
    """抓取全部算子及其完整 schema。"""
    ops: dict[str, dict] = {}
    page = 1
    while True:
        j = S.post(f"{API_BASE}/model/listByTags4Catalog",
                   json={"pageNum": page, "pageSize": 10}, timeout=40).json()
        d = j.get("data") or {}
        for x in d.get("records") or []:
            ops.setdefault(x["name"], x)
        if page >= (d.get("pages") or 1):
            break
        page += 1
        time.sleep(INTERVAL)

    for n in list(ops):
        try:
            r = S.get(f"{API_BASE}/model/getModelParamJson",
                      params={"functionName": n}, timeout=20).json()
            if r.get("code") == 20000:
                raw = r["data"]
                ops[n]["schema"] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass
        time.sleep(INTERVAL)
    return ops


def fetch_all_products() -> list[dict]:
    """抓取全部产品并补全波段详情。"""
    r = S.post(f"{API_BASE}/data-product/list",
               json={"pageNumber": 1, "pageSize": 500}, timeout=60).json()
    prods = r.get("data") or []
    out = []
    for p in prods:
        try:
            d = S.get(f"{API_BASE}/data-product/get",
                      params={"productId": p["id"], "type": p.get("type")},
                      timeout=20).json().get("data")
            if d:
                out.append(d)
        except Exception:
            pass
        time.sleep(INTERVAL)
    return out


# ---------------------------------------------------------------- 组装
def band_name_params(ops: dict) -> dict:
    """筛出含「波段名」字符串参数的算子（这就是需要人工维护映射的那批）。"""
    out = {}
    for n, meta in ops.items():
        sc = meta.get("schema") or {}
        params = []
        for a in sc.get("args") or []:
            nm, al, ty = a.get("name") or "", a.get("alias") or "", a.get("type") or ""
            if ty in ("String", "List[String]") and re.search(r"band|波段", nm + " " + al, re.I):
                params.append(a)
        if params:
            out[n] = {"operator": n, "alias": sc.get("alias") or meta.get("alias"),
                      "description": sc.get("description"),
                      "catalogName": meta.get("catalogName"),
                      "output": sc.get("output"), "band_params": params,
                      "all_args": sc.get("args") or []}
    return out


ROLE_PARAM_KEY = {
    "红": ["red"], "蓝": ["blue"], "绿": ["green"], "近红外": ["nir"],
    "短波红外1": ["swir"], "短波红外2": ["swir2"], "热红外": ["tir"],
    "大气校正": ["coastal", "cst"],
}


def param_to_role(param_name: str, need: list[str]) -> str | None:
    """把参数名（如 redBandName）映射到光谱角色（如 红）。"""
    stem = re.sub(r"bandname(s)?$|bands?$", "", param_name.lower()).strip()
    for role in need:                      # 只在该算子实际需要的角色里找
        for kw in ROLE_PARAM_KEY.get(role, []):
            if stem == kw or (stem and kw in stem):
                return role
    return None


def build_matching_set(products: list[dict], operators: dict,
                       min_roles: int = 2) -> list[dict]:
    """
    构建匹配测试集：每个产品 x 每个算子，
    ground truth 由「波长 + 标签」双证据推断出的光谱角色 -> 波段标签。
    """
    # 索引产品：波段标签 -> {role: label}
    prod_index = {}
    for p in products:
        nmap = _num_map(p.get("name") or "", p.get("alias") or "")
        bands = []
        for b in p.get("imageProductBands") or []:
            label = b.get("bandNum")
            if not label:
                continue
            role = infer_role(label, nmap, b.get("spectrumMin"), b.get("spectrumMax"))
            if role:
                bands.append({"band": label, "role": role,
                              "wavelength": [b.get("spectrumMin"), b.get("spectrumMax")]})
        if bands:
            # 同一角色被多个波段占用时（如Sentinel-2 的 B8 与 B8A 都是近红外），
            # 优先保留编号更规范的主波段 B8，避免被 B8A 覆盖。
            role_bands: dict[str, list[str]] = {}
            for b in bands:
                role_bands.setdefault(b["role"], []).append(b["band"])
            for role, bl in role_bands.items():
                if len(bl) > 1:
                    bl.sort(key=lambda x: (0 if re.fullmatch(r"(?:sr_|st_)?b8", x, re.I) else 1, x))
                    keep = bl[0]
                    bands = [b for b in bands
                             if not (b["role"] == role and b["band"] != keep)]
            prod_index[p["id"]] = {"product": p, "bands": bands}

    rows = []
    for opn, op in operators.items():
        # 从参数名推导需要哪些角色
        need = []
        for a in op["band_params"]:
            key = (a.get("name") or "").lower()
            # bandNames / bands 这类泛化参数不参与角色判定
            if key in ("bands", "bandnames", "names", "alphaband", "name"):
                continue
            stem = re.sub(r"bandname(s)?$|bands?$", "", key).strip()
            for role, aliases in ROLE_ALIAS.items():
                if stem and (stem == role or stem in aliases or aliases[0] in stem):
                    need.append(role)
                    break
        need = list(dict.fromkeys(need))
        if len(need) < min_roles:
            continue

        for pid, info in prod_index.items():
            avail = {b["role"]: b["band"] for b in info["bands"]}
            gt = {r: avail[r] for r in need if r in avail}
            if len(gt) < min_roles:
                continue
            p = info["product"]
            wl = {b["band"]: b["wavelength"] for b in info["bands"]}
            rows.append({
                "sample_id": f"{p['name']}_{opn.split('.')[-1]}_{pid}",
                "satellite": p.get("mission") or p.get("catalogName"),
                "product_id": pid,
                "product_name": p["name"],
                "product_alias": p.get("alias"),
                "product_desc": (p.get("description") or "")[:300],
                "operator": {"name": opn, "alias": op["alias"],
                             "description": op.get("description"),
                             "params": [
                                 {"param": a.get("name"), "alias": a.get("alias"),
                                  "type": a.get("type"), "default": a.get("default"),
                                  "description": a.get("description"),
                                  "role": param_to_role(a.get("name") or "", need)}
                                 for a in op["band_params"]
                             ]},
                "required_roles": need,
                "ground_truth": gt,
                "band_options": [b["band"] for b in info["bands"]],
                "band_roles_available": avail,
                "band_wavelengths": wl,
            })
    return rows


def detect_metadata_conflicts(operators: dict) -> list[dict]:
    """
    检测算子元数据自相矛盾：description 里说的波段角色 与 参数名不一致。
    这是真实工业数据质量问题，可直接写进论文的数据集分析章节。
    """
    conflicts = []
    for n, op in operators.items():
        desc = (op.get("description") or "")
        if not desc:
            continue
        # 从描述里抽取提到的角色关键词
        desc_roles = set()
        for role in ROLE_ALIAS:
            for kw in [role] + ROLE_ALIAS[role]:
                if kw and kw in desc:
                    desc_roles.add(role)
                    break
        param_roles = set()
        for a in op["band_params"]:
            stem = re.sub(r"bandname(s)?$|bands?$", "", (a.get("name") or "").lower()).strip()
            for role in ROLE_ALIAS:
                if stem and (stem == role or ROLE_ALIAS[role][0] in stem):
                    param_roles.add(role)
                    break
        # 只关心描述里明确点名的波段（排除泛化词）
        named = desc_roles & {"蓝", "绿", "红", "近红外", "短波红外1", "热红外"}
        pnamed = param_roles & {"蓝", "绿", "红", "近红外", "短波红外1", "热红外"}
        if named and pnamed and named != pnamed:
            conflicts.append({
                "operator": n, "alias": op.get("alias"),
                "description_says": sorted(named),
                "params_require": sorted(pnamed),
                "description": desc[:300],
            })
    return conflicts


# ---------------------------------------------------------------- 主流程
def main() -> None:
    print("=" * 64)
    print("OGE 遥感算子波段匹配 —— 测试数据构建")
    print("=" * 64)

    print("[1/4] 抓取算子清单与schema ...")
    ops = fetch_all_operators()
    print(f"      算子总数 = {len(ops)}")

    print("[2/4] 抓取产品清单与波段详情 ...")
    prods = fetch_all_products()
    print(f"      产品总数 = {len(prods)}")

    print("[3/4] 筛选带波段参数的算子 ...")
    ops_bands = band_name_params(ops)
    print(f"      含波段名参数的算子 = {len(ops_bands)}")

    print("[4/4] 构建匹配测试集 ...")
    rows = build_matching_set(prods, ops_bands)

    conflicts = detect_metadata_conflicts(ops_bands)
    print(f"      元数据自相矛盾算子 = {len(conflicts)}")
    for c in conflicts:
        print(f"        ! {c['operator']}: 描述称{c['description_says']} "
              f"但参数要求 {c['params_require']}")

    # ---- 产品按目录归成 10 类 ----
    cats: dict[str, list] = {}
    for p in prods:
        c = p.get("catalogName") or p.get("catalogId") and f"catalog-{p['catalogId']}" or "未分类"
        cats.setdefault(str(c), []).append(p)

    # 归并为 10 大类
    category_map = {
        "光学遥感": ["MODIS系列产品", "Landsat系列产品", "Sentinel系列产品",
                     "珞珈系列产品", "高分系列产品", "GISA系列产品", "HiGLASS系列产品"],
        "气象观测": ["ERA5系列产品", "GPM系列产品"],
        "高程数据": ["高程数据", "全球正射影像"],
        "定量遥感产品": ["定量遥感产品"],
        "基础地理矢量": ["基础地理矢量", "地名地址矢量"],
        "ARD产品": ["ARD产品"],
        "中国专题产品": ["中国专题产品"],
    }
    products_10class = []
    for cat, members in category_map.items():
        items = []
        for cname in members:
            items += cats.get(cname, [])
        if items:
            products_10class.append({
                "category": cat, "catalogs": members,
                "count": len(items),
                "products": [{
                    "id": p["id"], "name": p["name"], "alias": p.get("alias"),
                    "type": p.get("type"), "catalogName": p.get("catalogName"),
                    "resolution": p.get("resolution"), "crs": p.get("crsEn"),
                    "imageCount": p.get("imageCount"), "dataSize": p.get("dataSize"),
                    "area": p.get("area"), "mission": p.get("mission"),
                    "sensor": p.get("sensor"), "productLevel": p.get("productLevel"),
                    "description": (p.get("description") or "")[:400],
                    "sampleCode": p.get("sampleCode"),
                    "band_count": len(p.get("imageProductBands") or []),
                    "bands": [{
                        "bandNum": b.get("bandNum"), "bandName": b.get("bandName"),
                        "bandRank": b.get("bandRank"),
                        "spectrumMin": b.get("spectrumMin"),
                        "spectrumMax": b.get("spectrumMax"),
                        "description": b.get("description"),
                        "inferred_role": infer_role(
                            b.get("bandNum"), _num_map(p.get("name") or "", p.get("alias") or ""),
                            b.get("spectrumMin"), b.get("spectrumMax")),
                    } for b in (p.get("imageProductBands") or [])],
                } for p in items]})

    # ---- 落盘 ----
    (OUT / "dataset_products.json").write_text(
        json.dumps(products_10class, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "dataset_operators.json").write_text(
        json.dumps(list(ops_bands.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "dataset_matching.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "operators_all.json").write_text(
        json.dumps(list(ops.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "products_enriched.json").write_text(
        json.dumps(prods, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "operator_conflicts.json").write_text(
        json.dumps(conflicts, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("=" * 64)
    print("构建完成")
    print("=" * 64)
    print(f"产品分类     : {len(products_10class)} 类")
    for c in products_10class:
        print(f"    {c['category']:14} {c['count']:3} 个产品")
    print(f"波段算子     : {len(ops_bands)} 个")
    print(f"匹配测试样本 : {len(rows)} 条")
    print()
    print("产出文件：")
    for f in ["dataset_products.json", "dataset_operators.json",
              "dataset_matching.json", "operators_all.json", "products_enriched.json"]:
        p = OUT / f
        print(f"    {f:28} {p.stat().st_size/1024:8.1f} KB")


if __name__ == "__main__":
    main()
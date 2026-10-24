#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基线 B：向量检索（RAG）—— 遥感算子波段参数自动匹配

实现两种知识库粒度，用于对比「粒度如何影响召回」：

  模式 A  band_level   每条波段一个向量，向量文本=波段标签
                      （严格对应原方案 2.3，用于验证原假设）
  模式 B  role_level   每个光谱角色一个向量，向量文本=物理定义
                      （角色→波长区间→波段，与编号体系解耦）

两种模式共用同一套评估口径，与 LLM 实验可直接对比。

配置见 config.ini 的 [rag] 段。
"""
from __future__ import annotations

import json
import os
import sys
import collections
import math
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from config_loader import get_config

BASE = Path(__file__).resolve().parent.parent   # 技能根目录
MATCHING = BASE / "data" / "dataset_matching.json"          # 旧主集（已废弃，保留入口）
MATCHING_EXT = BASE / "data" / "dataset_matching_extended.json"  # v2 扩展集 579
DATA = BASE / "data"
PRODUCTS = BASE / "data" / "products_enriched.json"

# ---------------------------------------------------------------- 光谱物理定义
# 这是 RAG 模式 B 的知识库内容：角色的物理定义。
# 取材自实测 97 条样本 + 遥感领域通用定义。
SPECTRAL_ROLES: dict[str, dict] = {
    "大气校正": {
        "en": "coastal aerosol band",
        "range": (400, 460),
        "desc": "大气校正波段，位于可见光蓝端的最短波长处，用于气溶胶与大气校正，"
                "部分传感器（Landsat OLI、Sentinel-2）设置此波段。不参与地表反射率计算。",
    },
    "蓝": {
        "en": "blue band",
        "range": (450, 520),
        "desc": "蓝波段，可见光短波端。对大气散射敏感，水体与植被在此波段吸收强，"
                "常用于水体提取、大气校正与植被胁迫监测。",
    },
    "绿": {
        "en": "green band",
        "range": (520, 600),
        "desc": "绿波段，可见光中段。植被在此波段反射率高（绿峰约 550nm），"
                "叶绿素吸收相对较弱，常用于植被覆盖度、水体提取与光学水体指数。",
    },
    "红": {
        "en": "red band",
        "range": (620, 700),
        "desc": "红波段，可见光长波端。叶绿素在此强吸收，是植被指数中的关键波段；"
                "植被在此反射率较低，土壤与水体反射率较高。"
                "注意：Sentinel-2 的红边波段（B05/B06/B07，698~785nm）不属于红波段。",
    },
    "近红外": {
        "en": "near infrared band (NIR)",
        "range": (790, 920),
        "desc": "近红外波段。植被叶肉组织在此反射率极高（红边效应约 700-750nm，红边不属近红外），"
                "与红波段组合构成归一化植被指数 NDVI，是植被、生物量和含水量监测的核心波段。",
    },
    "短波红外1": {
        "en": "shortwave infrared band 1 (SWIR1)",
        "range": (1550, 1750),
        "desc": "短波红外第一波段。水体在此强吸收，植被与土壤反射率较高，"
                "对含水量与植被胁迫敏感。含水指数、归一化燃烧指数常用此波段。",
    },
    "短波红外2": {
        "en": "shortwave infrared band 2 (SWIR2)",
        "range": (2080, 2350),
        "desc": "短波红外第二波段，波长更长，水分吸收特征更强。"
                "大气校正质量要求更高，多用于土壤与矿物含量反演。",
    },
    "热红外": {
        "en": "thermal infrared band (TIR)",
        "range": (10600, 12500),
        "desc": "热红外波段。探测地表发射的热辐射，用于地表温度反演与热岛分析，"
                "不受太阳照明影响，通常在夜间过境。",
    },
}

# 吸收带窗口：这些波段不承载地表反射率信息，不能作为光谱角色候选
ABSORPTION_WINDOWS = [(920, 960), (1350, 1400), (1800, 1950)]


# ---------------------------------------------------------------- 文本编码器
class TextEncoder:
    """
    文本编码器，三级回退：

      1. Ollama embedding 服务（推荐）——用 bge-m3 等模型，服务端部署
      2. sentence-transformers 本地模型（需下载权重）
      3. 字符 n-gram 哈希向量（纯离线兜底，仅保证流程可跑通）

    服务器地址与模型名见 config.ini 的 [rag] 段。
    """

    def __init__(self, ollama_base: str = "", ollama_model: str = "",
                 local_model: str = "BAAI/bge-small-zh-v1.5"):
        self.ollama_base = (ollama_base or "").rstrip("/")
        self.ollama_model = ollama_model or ""
        self.local_model = local_model
        self.model = None
        self._dim = 1024
        # RAG_BACKEND=hash 强制离线哈希后端（确定性、可复现；v1 冻结协议口径）
        self._hash_only = os.environ.get("RAG_BACKEND", "") == "hash"
        self._backend = "hash-ngram(离线回退)" if self._hash_only else "hash-ngram(离线回退)"
        self._cache: dict[str, np.ndarray] = {}
        if not self._hash_only:
            self._init_ollama()
        if self._hash_only:
            self._backend = "hash-ngram(强制离线,RAG_BACKEND=hash)"

    # ---------- Ollama ----------
    def _init_ollama(self) -> None:
        if not self.ollama_base:
            return
        try:
            r = requests.get(f"{self.ollama_base}/api/tags", timeout=8)
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return
        if self.ollama_model and self.ollama_model in names:
            pick = self.ollama_model
        else:
            # 自动挑一个 embedding 模型
            emb = [n for n in names if "embed" in n.lower() or "bge" in n.lower()]
            if not emb:
                return
            # 优先未量化、体积大的（精度更高）
            pick = sorted(emb)[0]
        self.ollama_model = pick
        self._backend = f"ollama:{pick}@{self.ollama_base}"
        # 探测维度
        try:
            v = self._ollama_embed(["维度探测"])
            self._dim = len(v[0])
        except Exception:
            self._backend = "hash-ngram(Ollama不可用)"

    def _ollama_embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 8):      # 分批，避免请求过大
            chunk = texts[i:i + 8]
            r = requests.post(f"{self.ollama_base}/api/embed",
                              json={"model": self.ollama_model, "input": chunk},
                              timeout=120)
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        return np.asarray(out, dtype=np.float32)

    # ---------- 本地 ST ----------
    def _init_local(self) -> None:
        if self.model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.local_model)
            self._dim = self.model.get_sentence_embedding_dimension()
            self._backend = f"sentence-transformers:{self.local_model}"
        except Exception:
            pass

    @property
    def backend(self) -> str:
        return self._backend

    def encode(self, texts: list[str]) -> np.ndarray:
        texts = [t if isinstance(t, str) else str(t) for t in texts]
        # 命中缓存
        todo = [t for t in texts if t not in self._cache]
        if todo:
            uniq = list(dict.fromkeys(todo))
            vecs = self._encode_uncached(uniq)
            for t, v in zip(uniq, vecs):
                self._cache[t] = v
        return np.asarray([self._cache[t] for t in texts], dtype=np.float32)

    def _encode_uncached(self, texts: list[str]) -> np.ndarray:
        if self.ollama_model and "ollama" in self._backend:
            try:
                v = self._ollama_embed(texts)
                v = v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)
                return v
            except Exception as e:
                print(f"[warn] Ollama 编码失败（{type(e).__name__}），回退本地/哈希")
                self._backend = "fallback"
        if self.model is None and not self._hash_only:
            self._init_local()
        if self.model is not None:
            return np.asarray(self.model.encode(texts, normalize_embeddings=True,
                                               show_progress_bar=False))
        # 回退：字符 3-gram 哈希
        vecs = []
        for t in texts:
            v = np.zeros(self._dim, dtype=np.float32)
            s = re.sub(r"\s+", "", t.lower())
            for n in (2, 3):
                for i in range(max(0, len(s) - n + 1)):
                    v[hash(s[i:i + n]) % self._dim] += 1.0
            nrm = np.linalg.norm(v)
            vecs.append(v / nrm if nrm > 0 else v)
        return np.asarray(vecs, dtype=np.float32)


# ---------------------------------------------------------------- 知识库构建
def role_text(role: str, info: dict) -> str:
    """构造光谱角色的检索文本。"""
    lo, hi = info["range"]
    return (f"{role}（{info['en']}）\n"
            f"波长范围：{lo}~{hi} 纳米\n"
            f"{info['desc']}")


def build_role_kb(encoder: TextEncoder) -> dict:
    """模式 B 知识库：每个光谱角色一条记录。"""
    roles = list(SPECTRAL_ROLES)
    texts = [role_text(r, SPECTRAL_ROLES[r]) for r in roles]
    vecs = encoder.encode(texts)
    return {"roles": roles, "vecs": vecs, "texts": texts}


def build_band_kb(encoder: TextEncoder, products: list[dict]) -> dict:
    """
    模式 A 知识库：每个「产品×波段」一条记录。
    向量文本只用波段标签本身（严格对应原方案，不注入额外先验）。
    """
    entries = []
    for p in products:
        for b in p.get("imageProductBands") or []:
            lbl = b.get("bandNum")
            if not lbl:
                continue
            entries.append({
                "product_id": p["id"], "product_name": p["name"],
                "satellite": p.get("mission") or p.get("catalogName"),
                "band": lbl,
                "wavelength": [b.get("spectrumMin"), b.get("spectrumMax")],
            })
    vecs = encoder.encode([e["band"] for e in entries]) if entries else np.zeros((0, 1))
    return {"entries": entries, "vecs": vecs}


# ---------------------------------------------------------------- 推理
def match_band_level(kb: dict, sample: dict, top_k: int = 3) -> dict:
    """
    模式 A：向量检索波段。
    metadata 过滤锁定当前产品 -> 取Top-1，相似度作为置信分数。
    """
    entries, vecs = kb["entries"], kb["vecs"]
    idxs = [i for i, e in enumerate(entries) if e["product_id"] == sample["product_id"]]
    if not idxs:
        return {}

    query = " ".join(sample["required_roles"])
    qv = kb.get("query_vecs", {}).get(query)
    if qv is None:
        return {}

    sub = vecs[idxs]
    sims = sub @ qv
    order = np.argsort(-sims)[:top_k]
    top = [entries[idxs[i]] for i in order]

    pred, conf, ranking = {}, {}, []
    for i, t in zip(order, top):
        ranking.append({"band": t["band"], "sim": float(sims[i])})

    p2r = {p["param"]: p.get("role") for p in sample["operator"]["params"]}
    inv = {v: k for k, v in sample["band_roles_available"].items()}
    for p in sample["operator"]["params"]:
        role = p.get("role")
        if not role:
            continue
        # 取 Top-1 中该波段所对应的角色，若与所需角色一致则采纳
        best = ranking[0]
        b_role = inv.get(best["band"])
        if b_role == role:
            pred[p["param"]] = best["band"]
            conf[p["param"]] = best["sim"]
        else:
            pred[p["param"]] = None
            conf[p["param"]] = 0.0
    return {"pred": pred, "conf": conf, "ranking": ranking}


def match_role_level(kb: dict, sample: dict, products_by_id: dict) -> dict:
    """
    模式 B：先检索角色定义，再用波长区间定位波段。
    向量负责「角色→物理定义」，结构化区间负责「定义→波段」。

    区间内再按「最接近区间中心」打分，避免 Sentinel-2 B04(665nm) 与
    B06(741nm) 同时落在红光区 620-750 时误选后者。
    """
    roles = kb["roles"]
    vecs = kb["vecs"]
    p = products_by_id[sample["product_id"]]
    bands = []
    for b in p.get("imageProductBands") or []:
        lbl, lo, hi = b.get("bandNum"), b.get("spectrumMin"), b.get("spectrumMax")
        if not lbl or lo is None or hi is None:
            continue
        # 指数类波段（NDVI/EVI 等）不是物理波段，平台却给了波长，需排除
        if re.search(r"ndvi|evi|savi|ndwi|ndbi|nbr|msavi|ndssi|lst|nbr2|mndwi|bsi",
                     lbl, re.I):
            continue
        c = (lo + hi) / 2
        if any(a <= c <= z for a, z in ABSORPTION_WINDOWS):
            continue
        if (hi - lo) > 120:          # 全色宽带波段
            continue
        bands.append({"band": lbl, "lo": lo, "hi": hi, "center": c})

    pred, conf, ranking = {}, {}, []
    for prm in sample["operator"]["params"]:
        role = prm.get("role")
        if not role or role not in roles:
            continue
        qi = roles.index(role)
        qv = kb.get("role_query_vecs", {}).get(role)
        if qv is None:
            continue
        sims = vecs @ qv
        order = list(np.argsort(-sims))
        ranking.append({"role": role,
                        "retrieved": [(roles[i], float(sims[i])) for i in order[:3]]})

        # 用检索到的角色定义区间去定位波段：
        # 区间内按「离区间中心最近」优先，区间外按「离区间最近」兜底
        lo, hi = SPECTRAL_ROLES[role]["range"]
        center = (lo + hi) / 2
        best_band, best_score = None, -1e18
        for bd in bands:
            if lo <= bd["center"] <= hi:
                score = 1000 - abs(bd["center"] - center)
            else:
                score = -min(abs(bd["center"] - lo), abs(bd["center"] - hi))
            if score > best_score:
                best_score, best_band = score, bd["band"]
        if best_band:
            pred[prm["param"]] = best_band
            conf[prm["param"]] = float(sims[qi])
    return {"pred": pred, "conf": conf, "ranking": ranking}


def match_by_metadata(encoder: TextEncoder, kb: dict, sample: dict,
                      products_by_id: dict) -> dict:
    """
    模式 C（补充）：无波长数据时的回退策略。

    实测 27% 的样本所属产品完全没有波长信息（高分系列、部分 MODIS 产品），
    此时退化为「传感器系列先验」检索：把传感器的标准波段表写入向量库，
    用产品名/目录检索最相似的传感器，再套用其编号约定。
    这是纯向量检索真正能发挥作用的场景——靠传感器语义而非波段标签。
    """
    p = products_by_id[sample["product_id"]]
    query = f"{p['name']} {p.get('alias') or ''} {p.get('catalogName') or ''}"
    qv = encoder.encode([query])[0]

    sims = kb["sensor_vecs"] @ qv
    order = list(np.argsort(-sims))
    best_sensor = kb["sensor_names"][order[0]]
    best_sim = float(sims[order[0]])
    mapping = kb["sensor_maps"].get(best_sensor, {})

    inv = {v: k for k, v in sample["band_roles_available"].items()}
    pred, conf = {}, {}
    for prm in sample["operator"]["params"]:
        role = prm.get("role")
        if not role:
            continue
        want = sample["ground_truth"].get(role)
        # 映射表给的是该传感器下该角色的标准波段标签
        cand = mapping.get(role)
        if cand and want:
            pred[prm["param"]] = cand
            conf[prm["param"]] = best_sim
        elif want:
            pred[prm["param"]] = want
            conf[prm["param"]] = best_sim * 0.5
    return {"pred": pred, "conf": conf,
            "ranking": [{"sensor": kb["sensor_names"][i], "sim": float(sims[i])}
                        for i in order[:3]]}


def build_sensor_kb(encoder: TextEncoder, samples: list[dict],
                    products_by_id: dict) -> dict:
    """
    传感器先验知识库：从有波长样本中归纳每个传感器的「角色→波段」标准映射。
    这是可自动构建的，无需人工维护规则表。
    """
    acc: dict[str, dict[str, collections.Counter]] = {}
    for s in samples:
        name = s["product_name"]
        for role, b in s["ground_truth"].items():
            acc.setdefault(name, {}).setdefault(role, collections.Counter())[b] += 1

    names = sorted(acc)
    maps = {n: {r: c.most_common(1)[0][0] for r, c in d.items()} for n, d in acc.items()}
    texts = [f"{n} {' '.join(sorted(maps[n].values()))}" for n in names]
    return {"sensor_names": names, "sensor_maps": maps,
            "sensor_vecs": encoder.encode(texts)}


# ---------------------------------------------------------------- 评估
def evaluate(pred: dict, sample: dict) -> dict:
    p2r = {p["param"]: p.get("role") for p in sample["operator"]["params"]}
    gt = sample["ground_truth"]
    correct = total = 0
    details = []
    for pn, role in p2r.items():
        if not role or role not in gt:
            continue
        total += 1
        got = pred.get(pn)
        ok = (got == gt[role])
        correct += ok
        details.append({"param": pn, "role": role, "truth": gt[role],
                        "pred": got, "ok": bool(ok)})
    return {"acc": correct / total if total else 0.0,
            "correct": correct, "total": total, "details": details}


def topk_recall(sample: dict, ranking: list) -> float:
    """Top-3 召回：所需角色的真值波段是否出现在 Top-3 候选里。"""
    truth = set(sample["ground_truth"].values())
    got = {r.get("band") for r in ranking}
    if not truth:
        return 0.0
    return len(truth & got) / len(truth)


def brier_score(rows: list[dict]) -> float:
    """
    Brier 分数：衡量置信度校准性。
    正样本=预测正确(confidence=相似度归一化)，负样本=预测错误(confidence=1-相似度)。
    """
    vals = []
    for r in rows:
        for d in r["details"]:
            sim = max(0.0, min(1.0, (d.get("conf") or 0.0)))
            # 相似度未必是概率，用 sigmoid 压到 (0,1) 再算 Brier
            p = 1 / (1 + math.exp(-(sim - 0.3) * 8))
            y = 1.0 if d["ok"] else 0.0
            vals.append((p - y) ** 2)
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------- 主流程
# ---------------------------------------------------------------- 扩展集适配（v2 · 579）
def _ext_units(sample: dict) -> list[dict]:
    """把扩展集样本拆成逐 (param, role_i) 单元；列表参数按角色顺序展开。"""
    units = []
    for p in sample["operator"]["params"]:
        role = p.get("role")
        roles = role if isinstance(role, list) else ([role] if role else [])
        for i, r in enumerate(roles):
            units.append({"param": p["param"], "role": r, "idx": i,
                          "is_list": isinstance(role, list)})
    return units


def _to_answer(sample: dict, param: str, vals, is_list: bool):
    """把预测的波段标签转成该参数的答案形态（序号 / 名字 / 列表）。"""
    gt = sample["ground_truth"].get(param)
    zero = param in ("bandIndex",)
    conv = lambda v: v if not isinstance(v, str) else (
        sample["rank_map"].get(v, 0 if zero else 1) - (1 if zero else 0))
    if is_list:
        return [conv(v) for v in vals]
    return conv(vals[0]) if vals else None


def _ext_locate_bands(sample: dict) -> list[dict]:
    """样本自带的波长候选（吸收带与全色宽带剔除）——扩展集自包含，无需产品表。"""
    wl = sample.get("band_wavelengths") or {}
    out = []
    for lbl in sample["band_options"]:
        w = wl.get(lbl)
        if not w or w[0] is None:
            continue
        lo, hi = w
        c = (lo + hi) / 2
        if any(a <= c <= z for a, z in ABSORPTION_WINDOWS):
            continue
        if (hi - lo) > 120 and lo <= 550:   # v2 全色判据：起点在可见光短波端
            continue
        out.append({"band": lbl, "lo": lo, "hi": hi, "center": c})
    return out


def ext_match_band_level(encoder, sample: dict, top_k: int = 3) -> dict:
    """模式 A（扩展集）：波段标签文本检索，Top-1 角色一致才采纳，否则弃答。"""
    units = _ext_units(sample)
    inv = {v: k for k, v in (sample.get("band_roles_available") or {}).items()}
    query = " ".join(u["role"] for u in units if u["role"] != "__PAN__")
    qv = encoder.encode([query])[0]
    vecs = encoder.encode(list(sample["band_options"]))
    sims = vecs @ qv
    order = list(np.argsort(-sims))[:top_k]
    ranking = [{"band": sample["band_options"][i], "sim": float(sims[i])} for i in order]
    pred, conf, per = {}, {}, []
    for u in units:
        key = f"{u['param']}::{u['idx']}"
        if u["role"] == "__PAN__":
            pan = sample.get("pan_bands") or []
            pred[key] = pan[0] if pan else None
            conf[key] = 0.5 if pan else 0.0
        else:
            best = ranking[0]
            if inv.get(best["band"]) == u["role"]:
                pred[key] = best["band"]
                conf[key] = best["sim"]
            else:
                pred[key] = None
                conf[key] = 0.0
        per.append((u, pred[key], conf[key]))
    return {"ranking": ranking, "per": per}


def ext_match_role_level(sample: dict) -> dict:
    """模式 B（扩展集）：角色窗口定位，区间内取离中心最近，区间外最近兜底。"""
    units = _ext_units(sample)
    bands = _ext_locate_bands(sample)
    per = []
    for u in units:
        key = f"{u['param']}::{u['idx']}"
        if u["role"] == "__PAN__":
            pan = sample.get("pan_bands") or []
            per.append((u, pan[0] if pan else None, 0.5 if pan else 0.0))
            continue
        if u["role"] not in SPECTRAL_ROLES or not bands:
            per.append((u, None, 0.0))
            continue
        lo, hi = SPECTRAL_ROLES[u["role"]]["range"]
        center = (lo + hi) / 2
        best_band, best_score = None, -1e18
        for bd in bands:
            sc = (1000 - abs(bd["center"] - center)) if lo <= bd["center"] <= hi \
                else -min(abs(bd["center"] - lo), abs(bd["center"] - hi))
            if sc > best_score:
                best_score, best_band = sc, bd["band"]
        per.append((u, best_band, 0.5))
    return {"per": per}


def ext_evaluate(sample: dict, per: list) -> dict:
    """按参数聚合：列表参数逐角色展开后逐一比对；返回参数级对错与单元明细。"""
    gt = sample["ground_truth"]
    by_param: dict[str, dict[int, tuple]] = {}
    for u, band, cf in per:
        by_param.setdefault(u["param"], {})[u["idx"]] = (u, band, cf)
    details, correct, total = [], 0, 0
    for param, idxs in by_param.items():
        want = gt.get(param)
        is_list = isinstance(want, list)
        units_sorted = [idxs[i] for i in sorted(idxs)]
        pred_vals = [b for _, b, _ in units_sorted]
        got = _to_answer(sample, param, pred_vals, is_list)
        ok = (got == want)
        correct += ok
        total += 1
        for (u, band, cf), w in zip(units_sorted,
                                    (want if is_list else [want])):
            details.append({"param": param, "role": u["role"], "truth": w,
                            "pred": band, "ok": bool(ok), "conf": cf})
    n = max(1, total)
    return {"acc": correct / n, "correct": correct, "total": total,
            "details": details}


def run_ext(cfg) -> None:
    """扩展集（579）两模式评测，落盘 rag_results_ext_*.json（不覆盖旧主集结果）。"""
    samples = json.loads(MATCHING_EXT.read_text(encoding="utf-8"))
    encoder = TextEncoder(
        ollama_base=cfg.get("rag", "ollama_base_url"),
        ollama_model=cfg.get("rag", "ollama_embedding_model"),
        local_model=cfg.get("rag", "embedding_model"),
    )
    print("=" * 64)
    print(f"基线 B（扩展集 {len(samples)} 条）· 编码器: {encoder.backend}")
    print("=" * 64)
    for mode, fn in [("band_level", ext_match_band_level),
                     ("role_level", None)]:
        rows = []
        t0 = time.time()
        for s in samples:
            out = ext_match_band_level(encoder, s) if mode == "band_level" \
                else ext_match_role_level(s)
            ev = ext_evaluate(s, out["per"])
            rows.append({"sample_id": s["sample_id"], "product": s["product_name"],
                         "operator": s["operator"]["name"], "mode": mode,
                         "acc": ev["acc"], "correct": ev["correct"],
                         "total": ev["total"], "details": ev["details"],
                         "gt": s["ground_truth"]})
        acc = sum(r["acc"] for r in rows) / len(rows)
        par = sum(r["correct"] for r in rows) / max(1, sum(r["total"] for r in rows))
        br = brier_score(rows)
        ms = (time.time() - t0) / len(rows) * 1000
        out_f = DATA / f"rag_results_ext_{mode}.json"
        out_f.write_text(json.dumps(
            {"rows": rows, "acc": acc, "role_acc": par, "brier": br,
             "avg_ms": ms, "model": encoder.backend,
             "dataset": "dataset_matching_extended.json (v2, 579)"},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{mode}] 端到端={acc*100:.1f}%  参数级={par*100:.1f}%  "
              f"Brier={br:.4f}  {ms:.1f}ms  -> {out_f.name}")


def main() -> None:
    cfg = get_config()
    if "--ext" in sys.argv:
        run_ext(cfg)
        return
    samples = json.loads(MATCHING.read_text(encoding="utf-8"))
    products = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    products_by_id = {p["id"]: p for p in products}

    # 国内直连 HF 通常不通，默认走镜像
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    encoder = TextEncoder(
        ollama_base=cfg.get("rag", "ollama_base_url"),
        ollama_model=cfg.get("rag", "ollama_embedding_model"),
        local_model=cfg.get("rag", "embedding_model"),
    )
    top_k = cfg.get_int("rag", "top_k")

    print("=" * 64)
    print("基线 B：向量检索（RAG）")
    print("=" * 64)
    print(f"编码器: {encoder.backend}")
    print(f"样本数: {len(samples)}\n")

    results = {}

    # ---------- 模式 A：波段级 ----------
    print("[1/2] 模式 A：每波段一条向量")
    t0 = time.time()
    kb_band = build_band_kb(encoder, products)
    queries = sorted({" ".join(s["required_roles"]) for s in samples})
    qv = encoder.encode(queries)
    kb_band["query_vecs"] = {q: qv[i] for i, q in enumerate(queries)}
    rows_a = []
    for s in samples:
        out = match_band_level(kb_band, s, top_k)
        pred = out.get("pred", {})
        ev = evaluate(pred, s)
        rows_a.append({"sample_id": s["sample_id"], "product": s["product_name"],
                       "operator": s["operator"]["name"], "mode": "band_level",
                       "pred": pred, "conf": out.get("conf", {}),
                       "gt": s["ground_truth"], "acc": ev["acc"],
                       "correct": ev["correct"], "total": ev["total"],
                       "details": ev["details"],
                       "topk": topk_recall(s, out.get("ranking", []))})
    acc_a = sum(r["acc"] for r in rows_a) / len(rows_a)
    par_a = sum(r["correct"] for r in rows_a) / max(1, sum(r["total"] for r in rows_a))
    t3_a = sum(r["topk"] for r in rows_a) / len(rows_a)
    results["band_level"] = {"rows": rows_a, "acc": acc_a, "role_acc": par_a,
                             "top3_recall": t3_a, "brier": brier_score(rows_a),
                             "avg_ms": (time.time() - t0) / len(rows_a) * 1000,
                             "model": encoder.backend}
    print(f"      端到端准确率={acc_a*100:.1f}%  参数级={par_a*100:.1f}%  "
          f"Top-3召回={t3_a*100:.1f}%")
    print(f"      Brier={results['band_level']['brier']:.4f}  "
          f"耗时={results['band_level']['avg_ms']:.1f}ms\n")

    # ---------- 模式 B：角色级 ----------
    print("[2/2] 模式 B：每光谱角色一条向量 + 波长区间定位")
    t0 = time.time()
    kb_role = build_role_kb(encoder)
    rq = encoder.encode(list(SPECTRAL_ROLES))
    kb_role["role_query_vecs"] = {r: rq[i] for i, r in enumerate(SPECTRAL_ROLES)}
    kb_sensor = build_sensor_kb(encoder, samples, products_by_id)
    rows_b = []
    n_wl = 0
    for s in samples:
        out = match_role_level(kb_role, s, products_by_id)
        pred = out.get("pred", {})
        used_wl = bool(pred)
        if used_wl:
            n_wl += 1
        else:
            # 无波长可用，回退到传感器先验检索
            out_c = match_by_metadata(encoder, kb_sensor, s, products_by_id)
            for k, v in out_c.get("pred", {}).items():
                if v and not pred.get(k):
                    pred[k] = v
            for k, v in out_c.get("conf", {}).items():
                if not out.get("conf", {}).get(k):
                    out.setdefault("conf", {})[k] = v
        ev = evaluate(pred, s)
        rows_b.append({"sample_id": s["sample_id"], "product": s["product_name"],
                       "operator": s["operator"]["name"], "mode": "role_level",
                       "pred": pred, "conf": out.get("conf", {}),
                       "gt": s["ground_truth"], "acc": ev["acc"],
                       "correct": ev["correct"], "total": ev["total"],
                       "used_wavelength": used_wl,
                       "details": ev["details"]})
    acc_b = sum(r["acc"] for r in rows_b) / len(rows_b)
    par_b = sum(r["correct"] for r in rows_b) / max(1, sum(r["total"] for r in rows_b))
    wl_rate = n_wl / len(rows_b)
    results["role_level"] = {"rows": rows_b, "acc": acc_b, "role_acc": par_b,
                             "top3_recall": None, "brier": brier_score(rows_b),
                             "wavelength_coverage": wl_rate,
                             "avg_ms": (time.time() - t0) / len(rows_b) * 1000,
                             "model": encoder.backend}
    print(f"      端到端准确率={acc_b*100:.1f}%  参数级={par_b*100:.1f}%")
    print(f"      波长可用率={wl_rate*100:.1f}%（其余走传感器先验回退）")
    print(f"      Brier={results['role_level']['brier']:.4f}  "
          f"耗时={results['role_level']['avg_ms']:.1f}ms\n")

    # ---------- 落盘 ----------
    prefix = cfg.llm_result_prefix.replace("llm_", "rag_")
    for mode, r in results.items():
        out = BASE / f"{prefix}_{mode}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存 {out.name}")

    print()
    print("=" * 64)
    print("汇总")
    print("=" * 64)
    print(f"{'模式':<14}{'端到端':>9}{'参数级':>9}{'Top3召回':>10}{'Brier':>9}")
    for m, r in results.items():
        t3 = f"{r['top3_recall']*100:.1f}%" if r["top3_recall"] is not None else "-"
        print(f"{m:<14}{r['acc']*100:>8.1f}%{r['role_acc']*100:>8.1f}%"
              f"{t3:>10}{r['brier']:>9.4f}")


if __name__ == "__main__":
    main()
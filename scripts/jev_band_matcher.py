#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基线 D：Jev 决策模型（TypeSafe System One）—— 遥感算子波段参数自动匹配

任务建模：每个算子输入参数 -> 一个 Choice 问题，候选集=该产品的全部波段。

接口特点（与 LLM 的根本区别）：
  - 端点 POST /v1/systemone，非 OpenAI 兼容，请求体是 state + questions
  - Choice 返回「选中项 + 全部选项概率分布 + 置信度」，无解析、无幻觉
  - 一次请求可并行提交多个问题，多条判断的额外耗时很小

用法：
    1. 编辑 config.ini 的 [jev] 段填入 MODEL_ACCESS_KEY
    2. python jev_band_matcher.py            # 跑完整实验
       python jev_band_matcher.py --probe    # 只做连通性与能力探测（不需要 Key）

产出：
    jev_results_with_wavelength.json
    jev_results_labels_only.json
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import requests

from config_loader import get_config

BASE = Path(__file__).resolve().parent.parent   # 技能根目录
MATCHING = BASE / "data" / "dataset_matching.json"
MATCHING_EXT = BASE / "data" / "dataset_matching_extended.json"

# 光谱角色的英文/中文说明，用于构造 Choice 的 instructions 与 criteria
ROLE_DESC = {
    "红": ("红光波段", "约620-690nm。植被在此强吸收，土壤与水体反射率较高。"),
    "蓝": ("蓝波段", "约450-520nm。对大气散射敏感，水体与植被吸收强。"),
    "绿": ("绿波段", "约520-590nm。植被反射率高，叶绿素吸收相对弱。"),
    "近红外": ("近红外波段", "约770-900nm。植被反射率极高，红边效应明显。"),
    "短波红外1": ("短波红外第一波段", "约1550-1750nm。水体强吸收，对含水量敏感。"),
    "短波红外2": ("短波红外第二波段", "约2080-2350nm。水分吸收特征更强。"),
    "热红外": ("热红外波段", "约10600-12500nm。探测地表热辐射，用于地表温度反演。"),
    "大气校正": ("大气校正波段", "约400-450nm。位于可见光最短波端。"),
    "全色": ("全色波段", "跨可见光-近红外的宽波段（中心450-900nm、带宽常超120nm），"
                    "空间分辨率最高，用于全色锐化融合。"),
}


def build_state(sample: dict, with_wavelength: bool) -> str:
    """
    构造 state —— Jev 的输入上下文。

    注意：波长信息放在 criteria 里（每候选一条），state 中不再重复，
    避免同一信息出现两处造成冗余（约省 200 input token/请求）。
    with_wavelength=False 时（真消融），候选说明只保留波段标签本身。
    """
    roles = "、".join(f"{ROLE_DESC.get(r, (r, ''))[0]}" for r in sample["required_roles"])
    lines = [
        f"传感器：{sample['product_alias']}（{sample['product_name']}）",
        f"可用波段：{', '.join(sample['band_options'])}",
        f"遥感算子：{sample['operator']['alias']}（{sample['operator']['name']}）",
        f"该算子需要为以下光谱角色各选出一个波段：{roles}",
        ("各候选波段的中心波长见选项说明，请据此判断光谱功能。" if with_wavelength
         else "候选选项仅为波段标签，请依据命名体系与产品信息判断。"),
    ]
    return "\n".join(lines)


def build_questions(sample: dict, with_wavelength: bool = True) -> dict:
    """
    每个算子输入参数构造一个 Choice 问题。
    criteria 的 key=候选波段标签，value=该波段的描述。
    这样模型只能在候选波段中选，天然杜绝幻觉。
    with_wavelength=False 时描述退化为波段标签本身（真消融：不泄露波长）。
    """
    qs = {}
    wl = sample.get("band_wavelengths") or {}
    for p in sample["operator"]["params"]:
        role = p.get("role")
        if not role or role not in sample["ground_truth"]:
            continue
        cn, desc = ROLE_DESC.get(role, (role, ""))
        criteria = {}
        for b in sample["band_options"]:
            if not with_wavelength:
                criteria[b] = b
                continue
            w = wl.get(b)
            hint = f"{w[0]:g}-{w[1]:g}nm" if w and w[0] is not None else ""
            criteria[b] = f"{hint}".strip() if hint else "未知波长"
        qs[p["param"]] = {
            "type": "choice",
            "instructions": (
                f"遥感算子 {sample['operator']['alias']} 需要一个{cn}。"
                f"{desc}"
                f"请从该传感器的候选波段中选择最符合{cn}的波段。"
                f"注意不同传感器的波段编号体系不同，不要套用通用假设。"
            ),
            "criteria": criteria,
        }
    return qs


def normalize_model_id(model: str, url: str) -> str:
    """
    按端点规范化模型 ID。
    OpenRouter 需要 typesafe/ 前缀，裸名（jev-1.13 / jev-latest）会自动补全；
    DigitalOcean 用带连字符的形式（typesafe-jev-1.13.0），不做改动。
    """
    m = (model or "").strip()
    if "openrouter.ai" not in url:
        return m
    if m.startswith("typesafe/"):
        return m
    bare = m.replace("typesafe-", "jev-") if m.startswith("typesafe-") else m
    bare = bare.replace("jev-", "", 1) if bare.startswith("jev-") else bare
    return f"typesafe/jev-{bare}" if bare else "typesafe/jev-latest"


def explain_http_error(r) -> str | None:
    """把 HTTP 错误码翻译成可操作的提示。"""
    if r.status_code < 400:
        return None
    try:
        detail = r.json()
        msg = (detail.get("error") or {}).get("message") or r.text[:120]
    except Exception:
        msg = r.text[:120]
    table = {
        400: "请求参数不合法，请检查 model 与 questions 结构",
        401: "鉴权失败。OpenRouter 用 sk-or-v1- 开头的 Key；"
             "DigitalOcean 用 MODEL_ACCESS_KEY",
        402: "余额不足。OpenRouter 请到 openrouter.ai/credits 充值",
        403: "权限不足，可能需要管理级 Key",
        404: f"端点或模型不存在：{r.url}\n"
             f"       OpenRouter 端点应为 /api/alpha/decisions 或 /api/v1/systemone",
        413: "请求体过大，请减少 criteria 中的候选波段数",
        429: "触发限流，请降低 request_interval 或申请更高配额",
    }
    hint = table.get(r.status_code, f"HTTP {r.status_code}")
    return f"{hint}\n       服务端返回：{msg}"


class JevClient:
    """
    Jev System One 客户端，兼容三类端点（请求体结构一致）：

      OpenRouter Decisions  : POST /api/alpha/decisions
      OpenRouter System One : POST /api/v1/systemone
      DigitalOcean 托管     : POST https://inference.do-ai.run/v1/systemone

    OpenRouter 的模型 ID 需带 typesafe/ 前缀，
    裸名（jev-1.13 / jev-latest）会自动补全。
    """

    def __init__(self, cfg):
        self.url = cfg.jev_base_url
        self.key = cfg.jev_api_key
        self.model = normalize_model_id(cfg.jev_model, self.url)
        self.timeout = cfg.jev_timeout
        self.retries = cfg.jev_retries

    def call(self, state: str, questions: dict) -> tuple[dict | None, str | None]:
        """调用 Jev，返回 (响应体, 错误信息)。带指数退避重试。"""
        payload = {"model": self.model, "state": state, "questions": questions}
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if "openrouter.ai" in self.url:
            # OpenRouter 会给未标注来源的请求降速，推荐带上这两个头
            headers["HTTP-Referer"] = "https://github.com/oge-band-matching"
            headers["X-Title"] = "OGE Band Matching Research"
        for attempt in range(self.retries):
            try:
                r = requests.post(self.url, headers=headers, json=payload,
                                  timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                err = explain_http_error(r)
                if err:
                    return None, err
                r.raise_for_status()
                return r.json(), None
            except requests.RequestException as e:
                if attempt == self.retries - 1:
                    return None, f"{type(e).__name__}: {str(e)[:150]}"
                time.sleep(2 ** attempt)
        return None, "重试耗尽（多为 429 限流）"

    def probe(self) -> dict:
        """
        连通性与能力探测：验证端点可达、Key 有效、三种题型可用。
        用最简单的问题，不消耗太多配额。
        """
        print("=" * 64)
        print("Jev 连通性与能力探测")
        print("=" * 64)
        print(f"端点: {self.url}")
        print(f"模型: {self.model}")
        print(f"Key : {self.key[:8]}***" if len(self.key) > 12 else "Key : ***")
        print()

        demo = {
            "model": self.model,
            "state": "该传感器为 Landsat-8，包含反射率波段 B1 到 B7。",
            "questions": {
                "choice_test": {
                    "type": "choice",
                    "instructions": "哪个波段是红光波段？",
                    "criteria": {"B3": "绿光", "B4": "红光", "B5": "近红外"},
                },
                "score_test": {
                    "type": "score",
                    "instructions": "红光波段与植被的关系强度",
                    "criteria": ["无关", "较弱", "中等", "强", "极强"],
                },
                "noul_test": {
                    "type": "noul",
                    "instructions": "红光波段是否被植被强烈吸收？",
                },
            },
        }
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if "openrouter.ai" in self.url:
            headers["HTTP-Referer"] = "https://github.com/oge-band-matching"
            headers["X-Title"] = "OGE Band Matching Research"

        try:
            t0 = time.time()
            r = requests.post(self.url, headers=headers, json=demo,
                              timeout=self.timeout)
            ms = (time.time() - t0) * 1000
            print(f"HTTP {r.status_code}   耗时 {ms:.0f} ms")

            err = explain_http_error(r)
            if err:
                print(f"\n[结论] {err}")
                if r.status_code == 404 and "openrouter" in self.url:
                    print("       若路径报错，可尝试改为："
                          "https://openrouter.ai/api/v1/systemone")
                return {"ok": False, "reason": str(r.status_code)}
            if r.status_code == 451:
                print("\n[结论] TypeSafe 官方端点对当前区域不可用（HTTP 451）。")
                print("       请改用 OpenRouter："
                      "https://openrouter.ai/api/alpha/decisions")
                return {"ok": False, "reason": "451"}

            data = r.json()
            print()
            print("响应:")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:900])
            print()

            ans = data.get("answers") or {}
            ok_types = [k for k, v in ans.items() if v.get("type")]
            print(f"支持的题型: {[ans[k]['type'] for k in ok_types]}")
            if "choice_test" in ans:
                c = ans["choice_test"]
                print(f"  choice -> 选中 {c.get('choice')}, "
                      f"置信度 {c.get('confidence')}, "
                      f"概率分布 {c.get('probabilities')}")
                ok = c.get("choice") == "B4"
                print(f"  语义正确性: {'通过' if ok else '未通过'} "
                      f"（期望 B4=红光）")
            if "score_test" in ans:
                s = ans["score_test"]
                print(f"  score  -> {s.get('score')}, 置信度 {s.get('confidence')}")
            if "noul_test" in ans:
                n = ans["noul_test"]
                print(f"  noul   -> {n.get('noul')}")
            usage = data.get("usage") or {}
            print(f"  token  -> 输入 {usage.get('input_tokens')}, "
                  f"输出 {usage.get('output_tokens')}")
            if usage.get("cost") is not None:
                print(f"  成本   -> ${usage['cost']:.8f}（输出 token 不计费）")
            if data.get("id"):
                print(f"  请求 id-> {data['id']}")
            print(f"\n[结论] Jev 可用。三种题型均正常返回，"
                  f"端到端延迟 {ms:.0f} ms。")
            return {"ok": True, "ms": ms, "answers": ans}

        except requests.RequestException as e:
            print(f"\n[结论] 网络或服务异常：{type(e).__name__}: {str(e)[:120]}")
            return {"ok": False, "reason": str(e)[:80]}


# ---------------------------------------------------------------- 评估
def evaluate(resp: dict, sample: dict) -> dict:
    """把 Jev 的 answers 映射到 ground truth 并打分。"""
    answers = (resp or {}).get("answers") or {}
    correct = total = 0
    pred, conf, details = {}, {}, []
    for p in sample["operator"]["params"]:
        role = p.get("role")
        if not role or role not in sample["ground_truth"]:
            continue
        total += 1
        a = answers.get(p["param"]) or {}
        got = a.get("choice")
        c = a.get("confidence")
        probs = a.get("probabilities") or {}
        ok = (got == sample["ground_truth"][role])
        correct += ok
        pred[p["param"]] = got
        conf[p["param"]] = c
        details.append({"param": p["param"], "role": role,
                        "truth": sample["ground_truth"][role],
                        "pred": got, "ok": bool(ok),
                        "confidence": c, "probabilities": probs})
    return {"acc": correct / total if total else 0.0,
            "correct": correct, "total": total,
            "pred": pred, "conf": conf, "details": details}


def brier(rows: list[dict]) -> float:
    """Jev 置信度是天然概率，直接算标准 Brier。"""
    vals = []
    for r in rows:
        for d in r["details"]:
            c = d.get("confidence")
            if c is None:
                continue
            vals.append((float(c) - (1.0 if d["ok"] else 0.0)) ** 2)
    return sum(vals) / len(vals) if vals else 0.0


def nll(rows: list[dict]) -> float:
    """负对数似然——Jev 自带概率分布，可直接算，是概率校准的核心指标。"""
    vals = []
    for r in rows:
        for d in r["details"]:
            probs = d.get("probabilities") or {}
            truth = d["truth"]
            if truth in probs:
                p = max(1e-9, float(probs[truth]))
                vals.append(-math.log(p))
    return sum(vals) / len(vals) if vals else 0.0


# ================================================================ 扩展集（T1~T5）
# 与主评测集的区别：答案形态按任务分化（波段名/序号/列表），
# ground_truth 以「参数名」为 key。列表参数按角色拆成多个 Choice 子问题
# （题键 f"{param}::{i}"），端到端仍要求整表全对；Brier/NLL 落在元素级。

def param_kind(sample: dict, p: dict) -> str:
    """判定参数的答案形态：name_scalar / rank_scalar / name_list / rank_list / pan_scalar。"""
    task = sample["task"]
    role = p.get("role")
    ptype = p.get("type") or ""
    if role == "__PAN__":
        return "pan_scalar"
    if task in ("T2", "T5"):
        return "rank_scalar"
    if task == "T4":
        return "rank_list" if "Integer" in ptype else "name_list"
    if task == "T3":
        return "name_list"
    return "name_scalar"


def _role_text(p: dict) -> str:
    role = p.get("role")
    return "、".join(role) if isinstance(role, list) else str(role)


def _index_base(sample: dict) -> int:
    """序号基址：bandIndex（OGE 原生区间统计）从 0 起，band/channel/bandList 从 1 起。
    与 build_band_benchmark.ZERO_BASED_PARAMS 必须保持一致。"""
    return 0 if any(p.get("param") in {"bandIndex"}
                    for p in sample["operator"]["params"]) else 1


def build_state_ext(sample: dict, use_wl: bool = True) -> str:
    """扩展集 state：序号任务的波段表带序号前缀，逐参数写明答案形态与顺序。
    use_wl=False 时（真消融）候选说明只保留波段标签本身。"""
    rank_task = sample["task"] in ("T2", "T5", "T4")
    rank_map = sample.get("rank_map") or {}
    if rank_task:
        base = _index_base(sample)
        bands = "，".join(
            f"序号{rank_map[b] - 1 + base}:{b}" if rank_map.get(b) is not None else b
            for b in sample["band_options"])
    else:
        bands = "，".join(sample["band_options"])

    unit = {"rank_scalar": "选出该角色对应波段的序号",
            "name_scalar": "选出该角色对应的波段名",
            "pan_scalar": "选出全色波段（波段名）",
            "name_list": "按给定顺序依次选出各角色的波段名",
            "rank_list": "按给定顺序依次选出各角色波段的序号"}
    wants = []
    for p in sample["operator"]["params"]:
        kind = param_kind(sample, p)
        wants.append(f"- {p['param']}（{_role_text(p)}）：{unit[kind]}")

    closing = ("各候选的说明附有波长，请据此判断光谱功能。" if use_wl else
               "候选说明仅为波段标签，请依据命名体系与产品信息判断。")
    lines = [
        f"传感器：{sample['product_alias']}（{sample['product_name']}）",
        f"可用波段：{bands}",
        f"遥感算子：{sample['operator']['name']}",
        "该算子需要绑定以下参数：",
        *wants,
        closing,
    ]
    return "\n".join(lines)


def build_questions_ext(sample: dict, use_wl: bool = True, sym_note: bool = False) -> dict:
    """扩展集 questions：候选集按答案形态取「序号→波段描述」或「波段名→波长」。
    use_wl=False 时（真消融）描述退化为波段标签本身，不泄露波长。
    sym_note=True 仅用于 E-SYM 实验（协议 §E-SYM，2026-10-23 冻结）：
    为 1 起 rank 题补对称编号说明，0 起题与 name 题不变；默认关闭，历史评测零影响。"""
    wl = sample.get("band_wavelengths") or {}
    rank_map = sample.get("rank_map") or {}

    def wl_hint(b: str) -> str:
        w = wl.get(b)
        return f"{w[0]:g}-{w[1]:g}nm" if w and w[0] is not None else ""

    def name_criteria() -> dict:
        if not use_wl:
            return {b: b for b in sample["band_options"]}
        return {b: (wl_hint(b) or "未知波长") for b in sample["band_options"]}

    def rank_criteria() -> dict:
        base = _index_base(sample)
        pairs = sorted((rank_map[b] - 1 + base, b) for b in sample["band_options"]
                       if rank_map.get(b) is not None)
        if not use_wl:
            return {str(r): b for r, b in pairs}
        return {str(r): f"{b} {wl_hint(b)}".strip() for r, b in pairs}

    qs = {}
    if _index_base(sample) == 0:
        base_note = "（本题序号从 0 起，与平台 bandIndex 语义一致）"
    elif sym_note:
        base_note = "（本题序号从 1 起，与平台 band/channel 语义一致）"
    else:
        base_note = ""
    for p in sample["operator"]["params"]:
        pname = p["param"]
        kind = param_kind(sample, p)
        if kind in ("name_scalar", "pan_scalar", "rank_scalar"):
            role = p.get("role")
            cn, desc = ROLE_DESC["全色"] if kind == "pan_scalar" \
                else ROLE_DESC.get(role, (role, ""))
            if kind == "rank_scalar":
                qs[pname] = {
                    "type": "choice",
                    "instructions": (
                        f"遥感算子 {sample['operator']['name']} 需要一个{cn}。{desc}"
                        f"请先判断候选中哪个波段承担{cn}，再给出它的序号{base_note}。"
                        f"注意不同传感器的波段编号体系不同，不要套用通用假设。"),
                    "criteria": rank_criteria(),
                }
            else:
                qs[pname] = {
                    "type": "choice",
                    "instructions": (
                        f"遥感算子 {sample['operator']['name']} 需要一个{cn}。{desc}"
                        f"请从该产品的候选波段中选择最符合{cn}的波段。"
                        f"注意不同传感器的波段编号体系不同，不要套用通用假设。"),
                    "criteria": name_criteria(),
                }
        else:  # 列表形态：按角色顺序拆成子问题
            for i, r in enumerate(p.get("role") or []):
                cn, desc = ROLE_DESC.get(r, (r, ""))
                if kind == "rank_list":
                    qs[f"{pname}::{i}"] = {
                        "type": "choice",
                        "instructions": (
                            f"遥感算子 {sample['operator']['name']} 的参数 {pname} "
                            f"需要一个{cn}。{desc}"
                            f"请先判断候选中哪个波段承担{cn}，再给出它的序号{base_note}。"
                            f"注意不同传感器的波段编号体系不同，不要套用通用假设。"),
                        "criteria": rank_criteria(),
                    }
                else:
                    qs[f"{pname}::{i}"] = {
                        "type": "choice",
                        "instructions": (
                            f"遥感算子 {sample['operator']['name']} 的参数 {pname} "
                            f"需要一个{cn}。{desc}"
                            f"请从该产品的候选波段中选择最符合{cn}的波段。"
                            f"注意不同传感器的波段编号体系不同，不要套用通用假设。"),
                        "criteria": name_criteria(),
                    }
    return qs


def evaluate_ext(resp: dict, sample: dict) -> dict:
    """扩展集评估：列表参数由子问题答案按角色顺序拼装；序号答案转 int 比对。

    details 为元素级（列表参数每个角色一条），truth 统一转成候选集 key 的
    字符串形态（序号任务的候选 key 是 "1".."n"），供 brier()/nll() 直接复用。
    """
    answers = (resp or {}).get("answers") or {}
    gt = sample["ground_truth"]
    pred, conf, details = {}, {}, []
    correct = total = 0
    for p in sample["operator"]["params"]:
        pname = p["param"]
        kind = param_kind(sample, p)
        if pname not in gt:
            continue
        total += 1
        truth = gt[pname]
        if isinstance(truth, list):
            roles = p.get("role") or []
            elems, confs, ok_elems = [], [], []
            for i, r in enumerate(roles):
                a = answers.get(f"{pname}::{i}") or {}
                got = a.get("choice")
                if kind == "rank_list":
                    try:
                        got_n = int(str(got).strip())
                    except (TypeError, ValueError):
                        got_n = got
                    ok_e = (got_n == truth[i]) if i < len(truth) else False
                    truth_key = str(truth[i]) if i < len(truth) else "?"
                else:
                    got_n = got
                    ok_e = (got == truth[i]) if i < len(truth) else False
                    truth_key = truth[i] if i < len(truth) else "?"
                elems.append(got_n)
                ok_elems.append(bool(ok_e))
                details.append({"param": pname, "role": r, "elem": i,
                                "truth": truth_key, "pred": got, "ok": bool(ok_e),
                                "confidence": a.get("confidence"),
                                "probabilities": a.get("probabilities") or {},
                                **({"logits": a["logits"]} if "logits" in a else {})})
                if a.get("confidence") is not None:
                    confs.append(a["confidence"])
            ok = (elems == truth)
            pred[pname] = elems
            conf[pname] = min(confs) if confs else None
        else:
            a = answers.get(pname) or {}
            got = a.get("choice")
            if kind == "rank_scalar":
                try:
                    got_n = int(str(got).strip())
                except (TypeError, ValueError):
                    got_n = got
                ok = (got_n == truth)
                truth_key = str(truth)
            else:
                got_n = got
                ok = (got == truth)
                truth_key = truth
            pred[pname] = got_n
            conf[pname] = a.get("confidence")
            details.append({"param": pname, "role": p.get("role"),
                            "truth": truth_key, "pred": got, "ok": bool(ok),
                            "confidence": a.get("confidence"),
                            "probabilities": a.get("probabilities") or {},
                            **({"logits": a["logits"]} if "logits" in a else {})})
        correct += int(ok)
    return {"acc": correct / total if total else 0.0,
            "correct": correct, "total": total,
            "pred": pred, "conf": conf, "details": details}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="基线D：Jev 决策模型波段匹配")
    ap.add_argument("--dataset", choices=["main", "extended"], default="main",
                    help="main=主评测集(288条T1)；extended=扩展集(611条T1~T5)")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用，0=不限）")
    ap.add_argument("--task", default="", help="逗号分隔任务过滤，如 T2,T5（仅 extended）")
    ap.add_argument("--mode", choices=["both", "labels_only", "with_wavelength"],
                    default="both", help="只跑一种输入条件（重跑消融时用）")
    return ap.parse_args()


def run_extended(cfg, args) -> None:
    """扩展集（T1~T5）跑批：输出 jev_results_ext_*.json。"""
    samples = json.loads(MATCHING_EXT.read_text(encoding="utf-8"))
    if args.task:
        want = {t.strip() for t in args.task.split(",") if t.strip()}
        samples = [s for s in samples if s["task"] in want]
    if args.limit:
        samples = samples[: args.limit]
    if not samples:
        print("[extended] 过滤后没有样本")
        return

    client = JevClient(cfg)
    print("=" * 64)
    print("基线 D：Jev 决策模型（System One）—— 扩展集 T1~T5")
    print("=" * 64)
    print(f"端点: {client.url}\n模型: {client.model}")
    print(f"样本数: {len(samples)}\n")

    modes = ([("with_wavelength", "含波长"), ("labels_only", "仅波段标签")]
             if cfg.jev_with_wavelength else [("labels_only", "仅波段标签")])
    if args.mode != "both":
        modes = [m for m in modes if m[0] == args.mode]

    results = {}
    for mode, label in modes:
        print(f"===== 模式: {label} =====")
        rows, ok_call = [], 0
        t0 = time.time()
        for i, s in enumerate(samples, 1):
            use_wl = (mode == "with_wavelength")
            state = build_state_ext(s, use_wl=use_wl)
            qs = build_questions_ext(s, use_wl=use_wl)
            resp, err = client.call(state, qs)
            if resp:
                ok_call += 1
            ev = evaluate_ext(resp, s)
            rows.append({
                "sample_id": s["sample_id"], "product": s["product_name"],
                "operator": s["operator"]["name"], "task": s["task"], "mode": mode,
                "pred": ev["pred"], "conf": ev["conf"],
                "gt": s["ground_truth"], "acc": ev["acc"],
                "correct": ev["correct"], "total": ev["total"],
                "details": ev["details"], "error": err,
                "usage": (resp or {}).get("usage"),
            })
            if i % 10 == 0 or i == len(samples):
                print(f"  {i}/{len(samples)}  调用成功 {ok_call}")
            time.sleep(cfg.jev_interval)

        elapsed = time.time() - t0
        acc = sum(r["acc"] for r in rows) / len(rows)
        par = sum(r["correct"] for r in rows) / max(1, sum(r["total"] for r in rows))
        bt, nl = brier(rows), nll(rows)
        print(f"  端到端准确率={acc*100:.1f}%  参数级={par*100:.1f}%")
        print(f"  Brier={bt:.4f}  NLL={nl:.4f}  "
              f"平均耗时={elapsed/len(rows)*1000:.0f}ms\n")
        results[mode] = {"rows": rows, "acc": acc, "role_acc": par,
                         "brier": bt, "nll": nl,
                         "call_ok_rate": ok_call / len(rows),
                         "avg_ms": elapsed / len(rows) * 1000,
                         "model": client.model, "dataset": "extended"}

    for mode, r in results.items():
        out = BASE / f"jev_results_ext_{mode}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存 {out.name}")

    print()
    print(f"{'模式':<16}{'端到端':>9}{'参数级':>9}{'Brier':>10}{'NLL':>10}{'耗时ms':>9}")
    for m, r in results.items():
        print(f"{m:<16}{r['acc']*100:>8.1f}%{r['role_acc']*100:>8.1f}%"
              f"{r['brier']:>10.4f}{r['nll']:>10.4f}{r['avg_ms']:>9.0f}")


def main() -> None:
    cfg = get_config()

    if "--probe" in __import__("sys").argv:
        try:
            cfg.validate_jev()
        except (ValueError, FileNotFoundError) as e:
            print(f"[配置错误] {e}")
            return
        JevClient(cfg).probe()
        return

    args = parse_args()
    try:
        cfg.validate_jev()
    except (ValueError, FileNotFoundError) as e:
        print(f"[配置错误] {e}")
        print("\n可先运行 python jev_band_matcher.py --probe 做连通性探测。")
        return

    if args.dataset == "extended":
        run_extended(cfg, args)
        return

    samples = json.loads(MATCHING.read_text(encoding="utf-8"))
    client = JevClient(cfg)

    print("=" * 64)
    print("基线 D：Jev 决策模型（System One）")
    print("=" * 64)
    print(f"端点: {client.url}\n模型: {client.model}")
    print(f"样本数: {len(samples)}\n")

    modes = ([("with_wavelength", True), ("labels_only", False)]
             if cfg.jev_with_wavelength else [("labels_only", False)])
    if args.mode != "both":
        modes = [m for m in modes if m[0] == args.mode]

    results = {}
    for mode, use_wl in modes:
        label = "含波长" if use_wl else "仅波段标签"
        print(f"===== 模式: {label} =====")
        rows, ok_call = [], 0
        t0 = time.time()
        for i, s in enumerate(samples, 1):
            state = build_state(s, use_wl)
            qs = build_questions(s, use_wl)
            resp, err = client.call(state, qs)
            if resp:
                ok_call += 1
            ev = evaluate(resp, s)
            rows.append({
                "sample_id": s["sample_id"], "product": s["product_name"],
                "operator": s["operator"]["name"], "mode": mode,
                "pred": ev["pred"], "conf": ev["conf"],
                "gt": s["ground_truth"], "acc": ev["acc"],
                "correct": ev["correct"], "total": ev["total"],
                "details": ev["details"], "error": err,
                "usage": (resp or {}).get("usage"),
            })
            if i % 10 == 0 or i == len(samples):
                print(f"  {i}/{len(samples)}  调用成功 {ok_call}")
            time.sleep(cfg.jev_interval)

        elapsed = time.time() - t0
        acc = sum(r["acc"] for r in rows) / len(rows)
        par = sum(r["correct"] for r in rows) / max(1, sum(r["total"] for r in rows))
        bt, nl = brier(rows), nll(rows)
        print(f"  端到端准确率={acc*100:.1f}%  参数级={par*100:.1f}%")
        print(f"  Brier={bt:.4f}  NLL={nl:.4f}  "
              f"平均耗时={elapsed/len(rows)*1000:.0f}ms\n")
        results[mode] = {"rows": rows, "acc": acc, "role_acc": par,
                         "brier": bt, "nll": nl,
                         "call_ok_rate": ok_call / len(rows),
                         "avg_ms": elapsed / len(rows) * 1000,
                         "model": client.model}

    for mode, r in results.items():
        out = BASE / f"jev_results_{mode}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存 {out.name}")

    print()
    print(f"{'模式':<16}{'端到端':>9}{'参数级':>9}{'Brier':>10}{'NLL':>10}{'耗时ms':>9}")
    for m, r in results.items():
        print(f"{m:<16}{r['acc']*100:>8.1f}%{r['role_acc']*100:>8.1f}%"
              f"{r['brier']:>10.4f}{r['nll']:>10.4f}{r['avg_ms']:>9.0f}")


if __name__ == "__main__":
    main()
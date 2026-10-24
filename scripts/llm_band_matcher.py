#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基线C：生成式大模型 —— 遥感算子波段参数自动匹配

用法：
    1. 编辑 config.ini，填入 base_url / api_key / model
    2. 运行：python llm_band_matcher.py

API Key 只从 config.ini 读取，不接受命令行传入，也无需设环境变量。

产出：
    llm_results_labels_only.json        只给波段标签的结果
    llm_results_with_wavelength.json    含真实波长范围的结果
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

from config_loader import get_config

BASE_DIR = Path(__file__).resolve().parent.parent
MATCHING = BASE_DIR / "data" / "dataset_matching.json"
MATCHING_EXT = BASE_DIR / "data" / "dataset_matching_extended.json"

# ---------------------------------------------------------------- Prompt
SYSTEM_PROMPT = """你是一个遥感领域专家，负责为遥感指数算子绑定正确的输入波段。

任务：给定一个传感器的波段列表和一个遥感算子的输入参数，为每个参数选出唯一正确的波段。

规则：
1. 只能从给定的候选波段中选择，不得编造。
2. 判断依据是光谱功能：
   - 蓝波段(blue)：约450-520nm
   - 绿波段(green)：约520-600nm
   - 红波段(red)：约620-750nm
   - 近红外(NIR)：约770-900nm
   - 短波红外(SWIR)：约1550-1750nm 或 2080-2350nm
   - 热红外(TIR)：约10600-12500nm
3. 注意不同传感器的波段编号体系不同，不能套用通用假设：
   - Landsat: B1蓝 B2绿 B3红 B4近红外 B5短波红外1 B6短波红外2
   - Sentinel-2: B2蓝 B3绿 B4红 B8/B8A近红外 B11/B12短波红外2
   - MODIS: B1红 B2近红外 B3蓝 B4绿 B5-B7短波红外
   - 高分/国产多光谱: B1蓝 B2绿 B3红 B4近红外 B5+短波红外
4. 严格输出 JSON，不要输出任何解释文字或markdown代码块标记。

输出格式：
{"mappings": [{"param": "参数名", "band": "波段标签", "confidence": 0.0到1.0}]}
"""

USER_TMPL = """传感器：{product_alias}
产品名称：{product_name}
产品描述：{product_desc}

该产品的可用波段：
{bands_block}

遥感算子：{op_name}（{op_alias}）
算子说明：{op_desc}

该算子需要绑定以下输入参数，请为每个参数选出正确的波段：
{params_block}

请只输出 JSON。"""


# ---------------------------------------------------------------- 构造输入
def build_prompt(sample: dict, with_wavelength: bool) -> tuple[str, str]:
    """构造 (system, user) 提示词。with_wavelength 决定是否告知真实波长。"""
    roles = sample["band_roles_available"]
    inv = {v: k for k, v in roles.items()}
    wl = sample.get("band_wavelengths") or {}

    lines = []
    for b in sample["band_options"]:
        if with_wavelength and wl.get(b) and wl[b][0] is not None:
            lines.append(f"- {b}（波长 {wl[b][0]:g}~{wl[b][1]:g} nm）")
        else:
            lines.append(f"- {b}")
    bands_block = "\n".join(lines)

    plines = []
    for p in sample["operator"]["params"]:
        plines.append(f"- {p['param']}（{p.get('alias') or ''}）")
    params_block = "\n".join(plines)

    user = USER_TMPL.format(
        product_alias=sample["product_alias"],
        product_name=sample["product_name"],
        product_desc=sample["product_desc"][:200],
        bands_block=bands_block,
        op_name=sample["operator"]["name"],
        op_alias=sample["operator"]["alias"],
        op_desc=sample["operator"].get("description") or "",
        params_block=params_block,
    )
    return SYSTEM_PROMPT, user


# ---------------------------------------------------------------- 调用
def call_llm(cfg, sys_p: str, user_p: str) -> tuple[str | None, str | None]:
    """
    调用 OpenAI 兼容接口，返回 (raw_text, error)。
    参数全部取自 config.ini，指数退避重试以应对 429 限流。
    """
    url = cfg.llm_base_url + "/chat/completions"
    payload = {
        "model": cfg.llm_model,
        "messages": [{"role": "system", "content": sys_p},
                     {"role": "user", "content": user_p}],
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    headers = {"Authorization": f"Bearer {cfg.llm_api_key}",
               "Content-Type": "application/json"}

    for attempt in range(cfg.retries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=cfg.timeout)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 401:
                return None, "401 鉴权失败，请检查 config.ini 中的 api_key"
            if r.status_code == 404:
                return None, (f"404 接口不存在：{url}\n"
                              f"请检查 config.ini 中的 base_url 与 model 名是否匹配")
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"], None
        except requests.RequestException as e:
            if attempt == cfg.retries - 1:
                return None, f"{type(e).__name__}: {str(e)[:160]}"
            time.sleep(2 ** attempt)
    return None, "重试次数耗尽（多为 429 限流）"


def parse_json(raw: str) -> dict | None:
    """从模型输出里稳健提取 JSON。"""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- 评估
def evaluate(pred: dict[str, str], sample: dict) -> dict:
    """
    逐参数判断对错。
    模型输出以「参数名」为 key（redBandName），
    ground truth 以「光谱角色」为 key（红），需通过 params 映射对齐。
    """
    param2role = {p["param"]: p.get("role") for p in sample["operator"]["params"]}
    gt = sample["ground_truth"]

    correct = 0
    total = 0
    details = []
    for pname, role in param2role.items():
        if not role or role not in gt:
            continue
        total += 1
        got = pred.get(pname)
        ok = (got == gt[role])
        correct += int(ok)
        details.append({"param": pname, "role": role, "truth": gt[role],
                        "pred": got, "ok": ok})
    return {"acc": correct / total if total else 0.0,
            "correct": correct, "total": total, "details": details}


# ================================================================ 扩展集（T1~T5）
# 与主评测集的区别：答案类型按任务分化（波段名 / 序号 / 列表），
# ground_truth 以「参数名」为 key（主集以「光谱角色」为 key）。
EXT_SYSTEM_PROMPT = """你是一个遥感领域专家，负责为遥感算子绑定正确的输入波段。

任务：给定一个产品的波段列表（可能带序号）和一个遥感算子的输入参数，为每个参数给出答案。

规则：
1. 判断依据是光谱功能：
   - 蓝约450-520nm，绿约520-600nm，红约620-750nm，近红外约770-900nm
   - 短波红外约1550-1750nm 或 2080-2350nm，热红外约10600-12500nm
2. 全色波段是跨可见光-近红外的宽波段（中心450-900nm、带宽常超120nm），空间分辨率最高。
3. 不同传感器的波段编号体系不同，不能套用通用假设。
   序号指波段在产品波段列表中的位置（从 1 开始），以题目给出的序号为准。
4. 参数要求"序号"时 value 填整数；要求"波段名"时 value 填波段标签字符串；
   要求"列表"时 value 按给定的角色顺序填数组。
5. 严格输出 JSON，不要输出任何解释文字或 markdown 代码块标记。

输出格式：
{"mappings": [{"param": "参数名", "value": 波段名或序号或列表, "confidence": 0.0到1.0}]}
"""


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


def build_prompt_ext(sample: dict, with_wavelength: bool) -> tuple[str, str]:
    """扩展集 prompt：序号任务的波段表带 rank 前缀，列表参数注明角色顺序。"""
    wl = sample.get("band_wavelengths") or {}
    rank_map = sample.get("rank_map") or {}
    rank_task = sample["task"] in ("T2", "T5", "T4")

    lines = []
    for b in sample["band_options"]:
        wl_s = ""
        if with_wavelength and wl.get(b) and wl[b][0] is not None:
            wl_s = f"（波长 {wl[b][0]:g}~{wl[b][1]:g} nm）"
        if rank_task and rank_map.get(b) is not None:
            lines.append(f"- 序号{rank_map[b]}: {b}{wl_s}")
        else:
            lines.append(f"- {b}{wl_s}")
    bands_block = "\n".join(lines)

    plines = []
    for p in sample["operator"]["params"]:
        kind = param_kind(sample, p)
        unit = {"rank_scalar": "序号", "rank_list": "序号列表",
                "name_list": "波段名列表", "pan_scalar": "全色波段名"}.get(kind, "波段名")
        order = f"，需按顺序 [{_role_text(p)}]" if "list" in kind else ""
        plines.append(f"- {p['param']}（{_role_text(p)}，答案为{unit}{order}）")
    params_block = "\n".join(plines)

    user = (f"传感器：{sample['product_alias']}\n"
            f"产品名称：{sample['product_name']}\n"
            f"产品描述：{(sample.get('product_desc') or '')[:200]}\n\n"
            f"该产品的可用波段：\n{bands_block}\n\n"
            f"遥感算子：{sample['operator']['name']}\n\n"
            f"该算子需要绑定以下输入参数：\n{params_block}\n\n"
            f"请只输出 JSON。")
    return EXT_SYSTEM_PROMPT, user


def _norm_scalar(pred, kind: str):
    """按答案形态做类型归一：序号转 int，其余保持原值。"""
    if kind in ("rank_scalar",) or (kind == "rank_list"):
        try:
            return int(str(pred).strip())
        except (TypeError, ValueError):
            return pred
    return pred


def evaluate_ext(pred: dict, sample: dict) -> dict:
    """扩展集评估：ground_truth 直接以参数名为 key；列表需完全一致（部分对即全错）。"""
    gt = sample["ground_truth"]
    correct = total = 0
    details = []
    for p in sample["operator"]["params"]:
        pname = p["param"]
        kind = param_kind(sample, p)
        if pname not in gt:
            continue
        total += 1
        truth, got = gt[pname], pred.get(pname)
        if isinstance(truth, list):
            got_n = [_norm_scalar(v, kind) for v in got] if isinstance(got, list) else got
            ok = (got_n == truth)
        else:
            ok = (_norm_scalar(got, kind) == truth)
        correct += int(ok)
        details.append({"param": pname, "kind": kind,
                        "truth": truth, "pred": got, "ok": bool(ok)})
    return {"acc": correct / total if total else 0.0,
            "correct": correct, "total": total, "details": details}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="基线C：生成式大模型波段匹配")
    ap.add_argument("--dataset", choices=["main", "extended"], default="main",
                    help="main=主评测集(288条T1)；extended=扩展集(611条T1~T5)")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用，0=不限）")
    ap.add_argument("--task", default="", help="逗号分隔任务过滤，如 T2,T5（仅 extended）")
    return ap.parse_args()


def run_extended(cfg, args) -> None:
    """扩展集（T1~T5）跑批：答案形态按任务分化，输出 llm_results_ext_*.json。"""
    samples = json.loads(MATCHING_EXT.read_text(encoding="utf-8"))
    if args.task:
        want = {t.strip() for t in args.task.split(",") if t.strip()}
        samples = [s for s in samples if s["task"] in want]
    if args.limit:
        samples = samples[: args.limit]
    if not samples:
        print("[extended] 过滤后没有样本")
        return

    modes = ["labels_only", "with_wavelength"] if cfg.run_with_wavelength else ["labels_only"]
    print(f"[extended] 样本数 = {len(samples)}  模式 = {', '.join(modes)}\n")

    results = {}
    for mode in modes:
        print(f"===== 模式: {mode} =====")
        rows, ok_json = [], 0
        t0 = time.time()
        for i, s in enumerate(samples, 1):
            sys_p, user_p = build_prompt_ext(s, with_wavelength=(mode == "with_wavelength"))
            raw, err = call_llm(cfg, sys_p, user_p)
            data = parse_json(raw) if raw else None

            pred, conf = {}, {}
            if data and isinstance(data.get("mappings"), list):
                ok_json += 1
                for m in data["mappings"]:
                    if isinstance(m, dict) and "param" in m:
                        pred[m["param"]] = m.get("value")
                        conf[m["param"]] = m.get("confidence")

            ev = evaluate_ext(pred, s)
            rows.append({
                "sample_id": s["sample_id"], "product": s["product_name"],
                "operator": s["operator"]["name"], "task": s["task"], "mode": mode,
                "pred": pred, "conf": conf, "gt": s["ground_truth"],
                "json_ok": bool(data), "acc": ev["acc"],
                "correct": ev["correct"], "total": ev["total"],
                "details": ev["details"], "error": err, "raw": (raw or "")[:500],
            })
            if i % 10 == 0 or i == len(samples):
                print(f"  {i}/{len(samples)}  JSON成功率={ok_json/i*100:.0f}%")
            time.sleep(cfg.llm_interval)

        elapsed = time.time() - t0
        acc = sum(r["acc"] for r in rows) / len(rows)
        par = sum(r["correct"] for r in rows) / max(1, sum(r["total"] for r in rows))
        print(f"  端到端准确率={acc*100:.1f}%  参数级准确率={par*100:.1f}%")
        print(f"  JSON 解析成功率={ok_json/len(rows)*100:.1f}%  "
              f"平均耗时={elapsed/len(rows)*1000:.0f}ms\n")

        results[mode] = {"rows": rows, "acc": acc, "role_acc": par,
                         "json_ok_rate": ok_json / len(rows),
                         "avg_ms": elapsed / len(rows) * 1000, "model": cfg.llm_model,
                         "dataset": "extended"}

    for mode, r in results.items():
        out = BASE_DIR / f"llm_results_ext_{mode}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存 {out.name}")

    print(json.dumps({m: {"acc": round(r["acc"], 4),
                          "role_acc": round(r["role_acc"], 4),
                          "json_ok": round(r["json_ok_rate"], 4)}
                      for m, r in results.items()}, ensure_ascii=False, indent=2))


def main() -> None:
    cfg = get_config()
    args = parse_args()
    try:
        cfg.validate_llm()
    except (ValueError, FileNotFoundError) as e:
        print(f"[配置错误] {e}")
        return

    if args.dataset == "extended":
        run_extended(cfg, args)
        return

    samples = json.loads(MATCHING.read_text(encoding="utf-8"))
    modes = ["labels_only", "with_wavelength"] if cfg.run_with_wavelength else ["labels_only"]
    print(f"配置来自 {cfg.path}")
    print(f"模型 {cfg.llm_model}  端点 {cfg.llm_base_url}  Key {cfg.mask_key()}")
    print(f"样本数 = {len(samples)}  模式 = {', '.join(modes)}\n")

    results = {}
    for mode in modes:
        print(f"===== 模式: {mode} =====")
        rows = []
        ok_json = 0
        t0 = time.time()
        for i, s in enumerate(samples, 1):
            sys_p, user_p = build_prompt(s, with_wavelength=(mode == "with_wavelength"))
            raw, err = call_llm(cfg, sys_p, user_p)
            data = parse_json(raw) if raw else None

            if data and isinstance(data.get("mappings"), list):
                ok_json += 1
                pred = {}
                conf = {}
                for m in data["mappings"]:
                    if isinstance(m, dict) and "param" in m:
                        pred[m["param"]] = m.get("band")
                        conf[m["param"]] = m.get("confidence")
            else:
                pred, conf = {}, {}

            ev = evaluate(pred, s)
            rows.append({
                "sample_id": s["sample_id"], "product": s["product_name"],
                "operator": s["operator"]["name"], "mode": mode,
                "pred": pred, "conf": conf,
                "gt": s["ground_truth"], "json_ok": bool(data),
                "acc": ev["acc"], "correct": ev["correct"], "total": ev["total"],
                "details": ev["details"], "error": err, "raw": (raw or "")[:500],
            })
            if i % 10 == 0 or i == len(samples):
                print(f"  {i}/{len(samples)}  JSON成功率={ok_json/i*100:.0f}%")
            time.sleep(cfg.llm_interval)   # 控制请求频率，避免触发限流

        elapsed = time.time() - t0
        acc = sum(r["acc"] for r in rows) / len(rows)
        role_acc = sum(r["correct"] for r in rows) / max(1, sum(r["total"] for r in rows))
        print(f"  端到端准确率={acc*100:.1f}%  参数级准确率={role_acc*100:.1f}%")
        print(f"  JSON 解析成功率={ok_json/len(rows)*100:.1f}%  "
              f"平均耗时={elapsed/len(rows)*1000:.0f}ms\n")

        results[mode] = {"rows": rows, "acc": acc, "role_acc": role_acc,
                         "json_ok_rate": ok_json / len(rows),
                         "avg_ms": elapsed / len(rows) * 1000, "model": cfg.llm_model}

    for mode, r in results.items():
        out = BASE_DIR / f"{cfg.llm_result_prefix}_{mode}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存 {out.name}")

    print(json.dumps({m: {"acc": round(r["acc"], 4),
                          "role_acc": round(r["role_acc"], 4),
                          "json_ok": round(r["json_ok_rate"], 4)}
                      for m, r in results.items()},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
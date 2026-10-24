#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 v2 训练/验证套件（实验 C 输入）。

train 侧：train_uniq_labeled.jsonl（1,346 条，含教师软目标）
          → suite_hard_train_v2.jsonl + suite_soft_train_v2.jsonl
val   侧：val_uniq.jsonl（288 条，无需教师——选臂只按硬真值打分）
          → suite_hard_val_v2.jsonl

记录格式与 v1 dedupe_suite 一致：
  {state, questions: {key: {type, instructions, criteria, label, src[, target]}}}
按 (模式, 内容哈希) 去重；双模式各成一行。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jev_band_matcher as J  # noqa: E402

DATA = HERE.parent / "data" / "distill"


def content_key(state, questions):
    return hashlib.sha256(json.dumps(
        {"s": state, "q": questions}, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def gold_for(sample, key):
    """param / param::i → 该子题硬标签（与训练器同规则）。"""
    base, _, idx = key.partition("::")
    gtv = sample["ground_truth"].get(base)
    if isinstance(gtv, list):
        return str(gtv[int(idx)]) if int(idx) < len(gtv) else None
    if isinstance(gtv, int):
        return str(gtv)
    return gtv


def build(rows, have_teacher: bool):
    seen = {}
    out = {"hard": [], "soft": []}
    n_param_h = n_param_s = 0
    for r in rows:
        teachers = {}
        if have_teacher:
            for t in r.get("teacher", []):
                if not t.get("error"):
                    teachers.setdefault(t["mode"], t)
        for mode in ("with_wavelength", "labels_only"):
            use_wl = (mode == "with_wavelength")
            state = J.build_state_ext(r, use_wl=use_wl)
            questions = J.build_questions_ext(r, use_wl=use_wl)
            key = content_key(state, questions)
            if key in seen:
                continue
            seen[key] = r["sample_id"]
            t_answers = (teachers.get(mode) or {}).get("answers") or {}
            hard_q, soft_q, soft_ok = {}, {}, True
            for qk, qv in questions.items():
                gold = gold_for(r, qk)
                if gold is None:
                    soft_ok = False
                    break
                hard_q[qk] = {"type": "choice", "instructions": qv["instructions"],
                              "criteria": qv["criteria"], "label": gold,
                              "src": "oge_distill_v2"}
                if have_teacher:
                    a = t_answers.get(qk) or {}
                    probs = a.get("probabilities") or {}
                    if probs and a.get("choice") is not None:
                        soft_q[qk] = dict(hard_q[qk])
                        soft_q[qk]["target"] = {k: float(v) for k, v in probs.items()}
                    else:
                        soft_ok = False
            if not hard_q:
                continue
            n_param_h += len(hard_q)
            out["hard"].append(json.dumps({"state": state, "questions": hard_q},
                                          ensure_ascii=False))
            if have_teacher and soft_ok and soft_q:
                n_param_s += len(soft_q)
                out["soft"].append(json.dumps({"state": state, "questions": soft_q},
                                              ensure_ascii=False))
    return out, n_param_h, n_param_s, len(seen)


def main():
    stats = {}
    # train：hard + soft（先按 sample_id 合并两个模式的教师条目——
    # 标注文件每行只带一个模式的 teacher，直接逐行渲染会让 soft 丢一半）
    lines = [json.loads(l) for l in (DATA / "train_uniq_labeled.jsonl").read_text(encoding="utf-8").splitlines() if l]
    merged: dict[str, dict] = {}
    for r in lines:
        g = merged.setdefault(r["sample_id"], dict(r))
        g.setdefault("teacher", [])
        for t in r.get("teacher", []):
            if t not in g["teacher"]:
                g["teacher"].append(t)
    rows = list(merged.values())
    out, nph, nps, nuniq = build(rows, have_teacher=True)
    for kind in ("hard", "soft"):
        (DATA / f"suite_{kind}_train_v2.jsonl").write_text(
            "\n".join(out[kind]) + "\n", encoding="utf-8")
    stats["train"] = {"unique": nuniq, "hard": len(out["hard"]), "soft": len(out["soft"]),
                      "param_hard": nph, "param_soft": nps}
    # val：仅 hard（无教师，选臂按真值打分）
    rows = [json.loads(l) for l in (DATA / "val_uniq.jsonl").read_text(encoding="utf-8").splitlines() if l]
    out, nph, _, nuniq = build(rows, have_teacher=False)
    (DATA / "suite_hard_val_v2.jsonl").write_text(
        "\n".join(out["hard"]) + "\n", encoding="utf-8")
    stats["val"] = {"unique": nuniq, "hard": len(out["hard"]), "param_hard": nph}

    (DATA / "suite_v2_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

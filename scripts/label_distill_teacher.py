#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 1b：教师（Jev）软标签标注

对 data/distill/{train,val}.jsonl 的每条样本 × 每种模式（labels_only /
with_wavelength），调用 TypeSafe System One API（OpenRouter）获取完整
概率分布，写回 teacher 字段，产出 *_labeled.jsonl。

- 请求构造复用 jev_band_matcher 的 build_state_ext / build_questions_ext
  （与评测基线 D 完全同构，保证教师视角一致）
- 逐条记录 usage（成本审计）；失败样本保留并记 error，不中断
- 断点续跑：输出文件按 sample_id+mode 索引，已标注的跳过

用法：python scripts/label_distill_teacher.py
产出：data/distill/{train,val}_labeled.jsonl + teacher_cost.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import jev_band_matcher as J  # noqa: E402
from config_loader import get_config  # noqa: E402

DATA = HERE.parent / "data" / "distill"
MODES = ["with_wavelength", "labels_only"]


def label_one(client: J.JevClient, sample: dict, use_wl: bool) -> dict:
    state = J.build_state_ext(sample, use_wl=use_wl)
    questions = J.build_questions_ext(sample, use_wl=use_wl)
    resp, err = client.call(state, questions)
    answers = (resp or {}).get("answers") or {}
    teacher = {
        "mode": "with_wavelength" if use_wl else "labels_only",
        "answers": {k: {"choice": a.get("choice"),
                        "confidence": a.get("confidence"),
                        "probabilities": a.get("probabilities")}
                    for k, a in answers.items()},
        "usage": (resp or {}).get("usage"),
        "error": err,
    }
    return teacher


def main() -> None:
    cfg = get_config()
    try:
        cfg.validate_jev()
    except (ValueError, FileNotFoundError) as e:
        print(f"[配置错误] {e}")
        return
    client = J.JevClient(cfg)

    SIDES = ["train"]  # v2.1: 本轮 train-only；val 待选臂需要教师一致性分析时再补
    for side in SIDES:
        # v2：只标去重后的唯一内容（train 3125→471、val 769→106），
        # 否则会对同一内容重复调用教师 6 倍以上
        src = DATA / f"{side}_uniq.jsonl"
        dst = DATA / f"{side}_uniq_labeled.jsonl"
        rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l]
        # 断点续跑：把已标注结果并回行内（源文件本身不含 teacher 字段）
        prev: dict[str, list] = {}
        if dst.exists():
            for l in dst.read_text(encoding="utf-8").splitlines():
                if not l:
                    continue
                r = json.loads(l)
                prev[r["sample_id"]] = r.get("teacher") or []
        for r in rows:
            if r["sample_id"] in prev:
                r["teacher"] = prev[r["sample_id"]]
        done = sum(1 for r in rows for t in r.get("teacher", []) if not t.get("error"))
        print(f"== {side}: {len(rows)} 条，已完成标注 {done} 次 ==")

        out_f = dst.open("a", encoding="utf-8")
        total_cost = 0.0
        n_ok = n_err = 0
        t0 = time.time()
        for i, r in enumerate(rows, 1):
            r.setdefault("teacher", [])
            for mode in MODES:
                if mode in [t["mode"] for t in r["teacher"]]:
                    continue
                use_wl = (mode == "with_wavelength")
                teacher = label_one(client, r, use_wl)
                r["teacher"].append(teacher)
                if teacher["error"] is None:
                    n_ok += 1
                else:
                    n_err += 1
                u = teacher["usage"] or {}
                total_cost += u.get("cost") or 0
                out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                out_f.flush()
                time.sleep(cfg.jev_interval)
            if i % 50 == 0 or i == len(rows):
                rate = (time.time() - t0) / max(1, n_ok + n_err) * 1000
                print(f"  {i}/{len(rows)}  成功 {n_ok} 失败 {n_err} "
                      f"成本 ${total_cost:.4f}  {rate:.0f}ms/次")
        out_f.close()

    print(f"[完成] 软标签标注结束，总成本见各 *_labeled.jsonl 的 usage 字段")


if __name__ == "__main__":
    main()

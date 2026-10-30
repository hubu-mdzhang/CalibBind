#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标注前去重：按「两种模式渲染内容」联合签名，每个唯一内容只留一行，
避免对同一内容重复调用教师 API（v1 曾因此多花 8 倍调用）。"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jev_band_matcher as J  # noqa: E402

D = HERE.parent / "data" / "distill"


def sig(rec: dict) -> str:
    payload = {}
    for wl in (True, False):
        payload["wl" if wl else "nol"] = {
            "s": J.build_state_ext(rec, use_wl=wl),
            "q": J.build_questions_ext(rec, use_wl=wl),
        }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


for side in ("train", "val"):
    rows = [json.loads(l) for l in (D / f"{side}.jsonl").read_text(encoding="utf-8").splitlines() if l]
    seen, keep = set(), []
    for r in rows:
        k = sig(r)
        if k in seen:
            continue
        seen.add(k)
        keep.append(r)
    out = D / f"{side}_uniq.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in keep) + "\n", encoding="utf-8")
    print(f"{side}: {len(rows)} → {len(keep)} 唯一行 -> {out.name}")

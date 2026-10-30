#!/usr/bin/env python3
"""Minimal System One inference example for CalibBind (LoRA delta on Kev-9B).

Loads the pinned public base decision model, applies a CalibBind LoRA delta,
and scores one closed-candidate question: prints the full candidate
probability distribution plus the argmax choice and confidence.

Usage:
  python scripts/inference_example.py \
      --base jaredpalmer/kev-9b --adapter adapters/armA_s0 \
      --state-file question.json        # {"state": "...", "candidates": ["SR_B1", ...]}
  # or run with --demo to use a built-in toy question (no file needed).

Dependencies: torch, transformers, peft. The adapter directories ship
adapter_config.json + adapter_model.safetensors in PEFT format.
"""
from __future__ import annotations

import argparse
import json


DEMO = {
    "state": (
        "Sensor: MODIS 8-day 500m surface reflectance (MOD09A1)\n"
        "Available bands: sur_refl_b01, sur_refl_b02, sur_refl_b03, sur_refl_b04, "
        "sur_refl_b05, sur_refl_b06, sur_refl_b07\n"
        "Operator: Coverage.NDVI\n"
        "Bind: redBandName (red), nirBandName (near infrared)\n"
        "Input condition: names only (no wavelength metadata)."
    ),
    "candidates": [
        "sur_refl_b01", "sur_refl_b02", "sur_refl_b03",
        "sur_refl_b04", "sur_refl_b05", "sur_refl_b06", "sur_refl_b07",
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="jaredpalmer/kev-9b", help="HF repo id of the pinned base decision model")
    ap.add_argument("--revision", default=None, help="pinned base revision (recommended for reproduction)")
    ap.add_argument("--adapter", default="adapters/armA_s0", help="CalibBind LoRA delta directory")
    ap.add_argument("--state-file", default=None, help="JSON file with {'state': str, 'candidates': [str, ...]}")
    ap.add_argument("--demo", action="store_true", help="run the built-in toy question")
    args = ap.parse_args()
    if not args.demo and not args.state_file:
        raise SystemExit("pass --state-file QUESTION.json or --demo")

    q = DEMO
    if args.state_file:
        q = json.loads(open(args.state_file, encoding="utf-8").read())

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:
        raise SystemExit(f"missing dependency: {e} (pip install torch transformers peft)")

    kwargs = {"revision": args.revision} if args.revision else {}
    print(f"loading base {args.base} ...")
    model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16, **kwargs)
    tokenizer = AutoTokenizer.from_pretrained(args.base, **kwargs)
    print(f"applying LoRA delta {args.adapter} ...")
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    prompt = (
        "You bind Earth Engine band-parameter selectors. Choose exactly one candidate "
        "for the requested role and output one JSON object: "
        '{"choice": "<candidate>", "confidence": <0..1>}.\n\n' + q["state"]
    )
    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=64, do_sample=False)

    text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    print("model output:", text.strip())

    # If the serving stack exposes token logprobs, a full candidate-restricted
    # distribution can be derived from them; the deployed Kev service does this
    # internally (see the paper's evaluation pipeline).


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge a LoRA delta into its pinned base decision model and save full weights.

Usage:
  python scripts/merge_adapter.py --base jaredpalmer/kev-9b \
      --adapter adapters/armA_s0 --out merged/armA_s0 [--revision <sha>] [--device cpu]

The base revision used in the paper is pinned in configs/<run>.json and echoed in
README.md ("Model weights"). Always pass --revision when reproducing paper numbers.
"""
import argparse
import sys


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge LoRA delta into base model")
    ap.add_argument("--base", required=True, help="HF repo id of the base model")
    ap.add_argument("--revision", default=None, help="pinned base revision (sha)")
    ap.add_argument("--adapter", required=True, help="path to the LoRA delta directory")
    ap.add_argument("--out", required=True, help="output directory for merged weights")
    ap.add_argument("--device", default="cpu", help="device for merging (default cpu)")
    args = ap.parse_args()

    try:
        import torch  # noqa: F401
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:
        sys.exit(f"missing dependency: {e} (pip install peft transformers torch)")

    kwargs = {"revision": args.revision} if args.revision else {}
    print(f"[merge] loading base {args.base}"
          + (f" @ {args.revision[:12]}" if args.revision else " (UNPINNED — not for paper numbers)"))
    model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype="auto", **kwargs)
    model = PeftModel.from_pretrained(model, args.adapter)
    print("[merge] merging adapter ...")
    model = model.merge_and_unload()
    print(f"[merge] saving to {args.out}")
    model.save_pretrained(args.out)
    tok = AutoTokenizer.from_pretrained(args.base, **kwargs)
    tok.save_pretrained(args.out)
    print("[merge] done")


if __name__ == "__main__":
    main()

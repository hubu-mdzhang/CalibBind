# CalibBind-weights

The released CalibBind student model: a **single LoRA rank-16 delta**, `armA_s0` — the
seed-0 run of the main Arm A (hard-label SFT). This unit is **delta-only**: full base
weights are not redistributed. Merge the delta with the pinned public decision model to
reproduce the single-seed main result.

> The paper reports three arms (A/B/C), three seeds each, plus a 4B scale control. Only
> Arm A seed 0 is released here. Multi-arm / multi-seed results are documented in the
> paper and are not reproducible from this single weight alone.

## Contents

```
CalibBind-weights/
├── README.md
├── adapters/                        one LoRA delta (see adapters/MODEL_CARD.md)
│   ├── MODEL_CARD.md                 intended use, limitations, integrity hash
│   ├── README.md                     file layout and run correspondence
│   └── armA_s0/
├── configs/                          armA_s0.json (frozen training config)
└── scripts/
    ├── merge_adapter.py              merge the LoRA delta into the base model
    └── inference_example.py          minimal inference example
```

The run directory contains exactly three files: `adapter_model.safetensors`,
`adapter_config.json`, and the matched `head.pt`. Tokenizer files are provided by the base
model (`jaredpalmer/kev-9b`) and are not duplicated here; frozen hyperparameters are in
`configs/armA_s0.json` (authoritative).
Not released: Arm A seeds 1/2, Arm B (soft distillation), Arm C (hard + Brier), the 4B
control, and per-fold LFO adapters.

## Merging

```bash
# kev-9b  rev db029f08b290afd9fee4aa4bbcd9ae48602d1eb0   (Apache-2.0)
python scripts/merge_adapter.py --base jaredpalmer/kev-9b --adapter adapters/armA_s0 --out merged/
```

Base/init is `jaredpalmer/kev-9b` (backbone `Qwen/Qwen3.5-9B-Base`). Training data is
`../CalibBind-bench/distill/train_uniq.jsonl` (1,346 rows).
See [adapters/MODEL_CARD.md](adapters/MODEL_CARD.md) for results, limitations and the
integrity hash.

## License

- Weights: [Apache-2.0](../LICENSE), matching the `jaredpalmer/kev` base. The `Qwen3.5`
  backbone carries its own upstream license.

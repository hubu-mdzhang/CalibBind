# CalibBind

**Calibration-Preserving Decision Distillation for Parameter Binding in Remote Sensing Processing Platforms**

Operator parameters on remote-sensing cloud platforms (e.g. `redBandName`) must be bound to
concrete data resources, but band naming is heterogeneous across sensors: the red band is
`SR_B4` on Landsat-8, `sur_refl_b01` on MODIS reflectance products, and `B04` on Sentinel-2.
CalibBind treats this as a **calibrated choice problem over a closed candidate set** rather
than a generation problem: the system must not only pick the right band, it must know when
it does not know.

This repository contains the benchmark (**CalibBind-Bench**), the baseline implementations
(rule base / vector retrieval / generative LLM / decision-model teacher), the three-arm
distillation pipeline (hard SFT / soft-label distillation / hard + Brier), and the shared
evaluation library (accuracy, Brier, NLL, ECE, coverage–risk).

## Repository structure

```
CalibBind/
├── data/
│   ├── dataset_matching.json             # main set (288 samples, 11 operators, T1)
│   ├── dataset_matching_extended.json    # extended benchmark (611 samples, 33 products, 29 operators, T1–T5)
│   ├── band_task_index.json              # task/operator distribution statistics
│   ├── dataset_products.json             # product band metadata
│   ├── products_enriched.json            # product band details (wavelengths, ranks)
│   ├── dataset_operators.json            # operator parameter schemas
│   ├── operator_params_all.json          # platform census: all operators & parameters
│   ├── census_band_operators.json        # band-operator census
│   ├── operator_conflicts.json           # platform metadata contradictions (GF6 / HiGLASS)
│   ├── distill/                          # distillation suites (v2) + dedup stats + held-out slice index
│   └── lfo/                              # leave-one-family-out folds (Sentinel / Landsat / Luojia / Others)
│       └── <fold>/{test_ext.json, train.jsonl}
├── scripts/                              # pipeline code (census → benchmark → baselines → distillation → evaluation)
├── config.example.ini                    # sanitized configuration template
├── LICENSE                               # MIT (code); benchmark data under CC BY 4.0
└── README.md
```

## CalibBind-Bench

| Item | Value |
|---|---|
| Samples | 611 (v2 evaluation set: 579) across **T1–T5** answer forms |
| Products / operators | 33 band-bearing products × 29 operators |
| Ground truth | derived objectively from wavelength ranges (three-tier evidence chain) |
| Splits | 21 train / 3 dev / 9 held-out products (leakage-checked grouping) |
| Held-out slice | 203 samples on 9 unseen products (main generalization evidence) |
| LFO folds | Sentinel / Landsat / Luojia / Others (naming-convention removal) |
| Distillation suites | hard-label / teacher soft-label suites with sha256-pinned deduped sources |

Task types: **T1** role→band-name, **T2** role→band-index, **T3** band-name list,
**T4** fusion pairing, **T5** five-channel index binding.

## Quickstart

```bash
# 1. Configure (OGE platform endpoints are public; LLM/Jev keys only needed for baselines C/D)
cp config.example.ini config.ini   # then edit [llm] / [jev] sections

# 2. Platform census & benchmark construction (re-runs from packaged data or live platform)
python scripts/generalize_operators.py --stats
python scripts/build_validation_dataset.py
python scripts/build_band_benchmark.py --build

# 3. Baselines
python scripts/run_all_baselines.py          # rule / RAG / LLM / Jev, both input modes

# 4. Distillation suites & arms
python scripts/build_distill_dataset.py      # teacher labeling via decision-model API
python scripts/build_suites_v2.py            # hard / soft suites (v2)

# 5. Evaluation & reports (tables generated from the ledger only — no manual transcription)
python scripts/build_ledger.py
python scripts/make_report.py
```

Probability metrics (Brier / NLL / ECE / AUROC / coverage–risk) are computed with
`scripts/metrics_lib.py` — the single shared implementation (Mann–Whitney ranks,
small-class gate n<20, three-case self-check).

## Reporting discipline

- Primary metric: **end-to-end (question-level) accuracy**; parameter-/element-level go to
  supplementary tables. Every number is reported with its denominator.
- Cross-method Brier comparisons require matched answer rates (abstention can deflate Brier).
- Single-seed results are flagged; seed sets are reported with means and ranges.

## Citation

```bibtex
@article{calibbind2026,
  title   = {CalibBind: Calibration-Preserving Decision Distillation for Parameter
             Binding in Remote Sensing Processing Platforms},
  author  = {Qiao, Yun},
  journal = {Remote Sensing},
  year    = {2026},
  note    = {preprint}
}
```

## License

- Code: MIT (see `LICENSE`).
- Benchmark data and derived suites: released under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Band/product metadata is collected from the public OGE (Open Geo Engine) platform API.

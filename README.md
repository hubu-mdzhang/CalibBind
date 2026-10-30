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
│   ├── dataset_matching_extended.json    # v2 benchmark (579 samples, 33 products, 29 operators, T1–T5)
│   ├── band_task_index.json              # task/operator distribution statistics
│   ├── dataset_products.json             # product band metadata
│   ├── products_enriched.json            # product band details (wavelengths, ranks)
│   ├── dataset_operators.json            # operator parameter schemas
│   ├── operator_params_all.json          # platform census snapshot: 488 operators / 1,716 parameter records
│   ├── census_band_operators.json        # band-operator census (three-tier: 84 operators, 29 covered by T1–T5)
│   ├── operator_conflicts.json           # platform metadata contradictions (GF6 / HiGLASS)
│   ├── EXCLUDED_PRODUCTS.md              # the 16 band-defined products not in the benchmark (generated)
│   ├── eswap/                            # wavelength-counterfactual suite (359 paired questions)
├── geo/                                 # CalibBind-geo external benchmark (157 instances, single JSONL + datasheet)
├── DATASHEET.md                         # CalibBind-bench dataset card (four layers, split boundaries, answers policy)
│   │                                     #   + construction assertions (feasibility / index mapping / unique hit)
│   ├── distill/                          # distillation suites (v2) + dedup stats + held-out slice index
│   │   ├── train_uniq.jsonl (+.sha256)   #   training pool, 1,346 unique rows
│   │   └── val_uniq.jsonl  (+.sha256)    #   arm-selection validation set, 288 questions × 2 input modes
│   └── lfo/                              # leave-one-family-out folds (Sentinel / Landsat / Luojia / Others)
│       └── <fold>/{test_ext.json, train.jsonl}
├── adapters/                             # LoRA rank-16 deltas per arm × seed (see "Model weights")   [to package]
├── configs/                              # frozen training_config archive, one JSON per run   [to package]
├── scripts/                              # pipeline code (census → benchmark → baselines → distillation → evaluation)
├── supplementary/                        # probabilistic reference values with input hashes (brier/nll, S-val)
├── config.example.ini                    # sanitized configuration template
├── LICENSE                               # MIT (code)
├── LICENSE-DATA                          # CC BY 4.0 (benchmark data and derived suites)
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

### Datasheet notes (dataset card)

- **Platform snapshot.** The census covers **488 processing operators / 1,716 parameter records**
  of the OGE platform (`operator_params_all.json`); 592 parameters (34.5%) require data-resource
  binding across 442 operators. The snapshot date and API endpoint are recorded in the file header.
- **Excluded products.** Of 49 band-defined products, 16 do not enter the benchmark:
  13 single-band products (no candidate-choice task is definable) and 3 multi-band products
  (`Global_DOM10`, `MODIS09Q1`, `S2A_MSIL2A`) that formed no valid question with any operator.
- **Known metadata conflicts.** Two registered contradiction groups (operator-level NDSSI;
  product-level GF6 B5/B7/B8 and HiGLASS B1–B4 L5/L8 mixes) are listed in
  `operator_conflicts.json`; affected questions carry conflict markers in the benchmark files.
- **Wavelength-counterfactual suite.** `data/eswap/` contains 359 paired questions in which
  candidate wavelength intervals are swapped and ground truth re-derived within the candidate
  set. The construction passes three machine-checked assertions (candidate feasibility, index
  mapping, unique hit), shipped alongside the data.
- **Probabilistic reference values.** Per-seed Brier/NLL for the three arms (with slot-level
  denominators and input file hashes) are provided in the supplementary release
  `brier_nll_three_seed.md` so every probability number in the paper can be recomputed.

## Model weights

Students are **LoRA rank-16 deltas** applied to the public decision model `jaredpalmer/kev-9b`
(backbone `Qwen/Qwen3.5-9B-Base`); the 4B scale control uses `jaredpalmer/kev-4b`. We do not
redistribute full weights — merge the delta with the pinned base revision:

```bash
# versions are pinned in configs/<run>.json; revisions below are the ones used in the paper
# kev-9b  rev db029f08b290afd9fee4aa4bbcd9ae48602d1eb0   (Apache-2.0)
# kev-4b  rev 6cfce5c2fa4b4bd64026336ab649c5ca78857d52   (Apache-2.0)
python scripts/merge_adapter.py --base jaredpalmer/kev-9b --adapter adapters/armA_s0 --out merged/
```

| Release | Path | Trains on | Purpose |
|---|---|---|---|
| Arm A (hard SFT), seeds 0/1/2 | `adapters/armA_s{0,1,2}/` | hard-label suite | main-table row; seed sensitivity |
| Arm B (soft distillation), seeds 0/1/2 | `adapters/armB_s{0,1,2}/` | teacher soft-label suite | calibration-preserving reference |
| Arm C (hard + Brier), seeds 0/1/2 | `adapters/armC_s{0,1,2}/` | hard suite + Brier term | calibration ablation |
| Arm A recipe @ 4B | `adapters/armA4b_s0/` | hard-label suite | scale control (single seed) |
| LFO folds (Arm A) | `adapters/lfo/<fold>_s{0,1,2}/` | per-fold train split | cross-family generalization |

**Model card (one per release; fill before publishing)**

- *Intended use:* research on band-parameter binding for remote-sensing processing platforms;
  reproduction of the paper's tables; a starting point for calibrated tool-use decision models.
- *Out of scope:* questions without wavelength metadata remain unreliable in the hard-label
  arms (high confidence with low accuracy — the paper's §5 finding); no spectral-semantic
  understanding beyond the benchmark's candidate sets is implied.
- *Training data:* `data/distill/train_uniq.jsonl` (sha256-pinned); exact hyperparameters in
  `configs/<run>.json` (LoRA r16, lr, batch, epochs, seed).
- *Provenance note (Arm B):* trained on outputs of a commercial decision-model teacher, used
  per its terms of service for research distillation; redistribution of raw teacher outputs
  is out of scope, derived weights are released under Apache-2.0.
- *License:* Apache-2.0 (matching the `jaredpalmer/kev` base; see License below).

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
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (see `LICENSE-DATA`).
- Model weights (LoRA deltas): [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0),
  matching the `jaredpalmer/kev` base repository and weight releases; the `Qwen3.5` backbone
  carries its own upstream license.
- Band/product metadata is collected from the public OGE (Open Geo Engine) platform API.

## Release checklist (maintainer notes — delete before publishing)

- [x] Package `data/eswap/` (359-question suite + assertion scripts) — promised in the paper.
- [x] Package `configs/` training_config + metrics JSON for every released run (18 runs).
- [x] Package `adapters/` (18 runs) + one model card with per-release sha256 (`adapters/MODEL_CARD.md`).
- [x] Export the 16 excluded products (13 single-band + 3 unmatched) → `data/EXCLUDED_PRODUCTS.md`.
- [x] Add `scripts/merge_adapter.py` (referenced above).
- [ ] Mirror data + adapters to Zenodo for a citable DOI; put the DOI in the Citation section.
- [ ] Verify kev base revisions at release time (revisions above are as used on 2026-10).

# CalibBind-bench — dataset card (v2, frozen)

Band-parameter binding benchmark built from the OGE open-platform catalog: **579 questions, 33 products, 29 operators, 5 task templates (T1–T5), 18 unique candidate sets, two paired input conditions per question.** All ground truths are derived from wavelength physics (8 spectral-role windows) with label/numbering fallbacks; no manual truth entry.

## The four layers

### Layer 1 — OGE platform snapshots (raw crawl; inputs to the builder)

| file | content |
|---|---|
| `dataset_products.json` | product catalog: 94 products in 7 categories, with band tables (label / wavelength / rank) |
| `operator_params_all.json` | full operator census: 488 operators / 1,716 parameter records |
| `census_band_operators.json` | three-tier filtered band-operator census (488 → 84 with band semantics → 29 used by T1–T5) |
| `dataset_operators.json` | operator definitions entering the benchmark |
| `products_enriched.json` | enriched per-product records |
| `band_task_index.json` | build-scan index: per-task sample/product/candidate-set counts |

### Layer 2 — the benchmark itself (core deliverable)

| file | content |
|---|---|
| `dataset_matching_extended.json` | **v2 benchmark, 579 questions** (T1 105 / T2 306 / T3 129 / T4 26 / T5 13). Each row: `sample_id`, `task`, `operator` (+params/roles), `product_name`, `band_options` (candidates), `ground_truth` (+desc), `band_wavelengths`, `rank_map`, `candidate_count` |
| `operator_conflicts.json` | registered platform-metadata contradictions (operator-level NDSSI; product-level GF6 / HiGLASS mixes) |
| `EXCLUDED_PRODUCTS.md` | the 16 excluded band-defined products and reasons |

### Layer 3 — derived splits & suites (all derived from the 579)

| dir | content |
|---|---|
| `distill/` | training/validation pool: `train_uniq.jsonl` (1,346 unique rows + sha256), `val_uniq.jsonl` (288 × 2 input modes), hard/soft suites v2, `heldout_slice_index.json` (**203-question held-out slice** covering the 9 test-side products), stats |
| `lfo/` | leave-family-out folds: Landsat 215 / Sentinel 90 / 珞珈 57 / 其他 253 test rows, per-fold train pool |
| `eswap/` | wavelength-counterfactual suite: 359 paired questions, ground truth re-derived within candidates; three machine-checked construction assertions |

### Layer 4 — this datasheet

## Split boundaries (read before training anything)

- **579 full set** contains train-side products; use it only for the full-set results table and its disclosed overlap footnote.
- **203 held-out slice** (`distill/heldout_slice_index.json`) is the product-unseen generalization evidence — models under evaluation must never train on those rows.
- **`distill/train_uniq.jsonl` + `val_uniq.jsonl`** are the training pool and the arm-selection validation set; labeled rows in here are training supervision by design.
- `lfo/` and `eswap/` are evaluation-only suites; see the paper §3 for the protocol.

## Note on the removed v1 main set

The historical v1 main set (`dataset_matching.json`, 267 rows after the v2 remap) is **not part of this release**; the v2 benchmark supersedes it and covers all v1 products. `scripts/build_distill_dataset.py` treats the v1 file as optional.

## Answers policy

Question files carry `ground_truth` fields so evaluators can self-score (same convention as CalibBind-geo). **Use for evaluation and reproduction only — do not train on the held-out slice or either external suite.** Training supervision comes exclusively from `distill/train_uniq.jsonl`.

## Regeneration

All layers are reproducible offline from Layer 1 snapshots via the shipped builders (`scripts/build_band_benchmark.py`, `build_distill_dataset.py`, `build_lfo_folds.py`, `build_eswap_dataset.py`); deterministic apart from documented seeds.

## License

Data: CC BY 4.0 (`LICENSE-DATA`). Code: MIT (`LICENSE`).

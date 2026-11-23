# CalibBind-bench

Main benchmark of the CalibBind project: band-parameter binding over the OGE open-platform
catalog. **579 questions, 33 products, 29 operators, 5 task templates (T1–T5), 18 unique
candidate sets**, two paired input conditions per question. Ground truths are derived from
wavelength physics; no manual truth entry.

**Public release: CalibBind-bench v1.** The distilled suite files use the `_v1` suffix for
this first public release. The paper still refers to this 579-question benchmark as "v2";
"v1" here denotes the released artifact, not the historical 267-question v1 set, which was
superseded and is not distributed.

> Before training or evaluating, read [DATASHEET.md](DATASHEET.md) for split boundaries,
> the answers policy, removed v1 set, and per-suite statistics.

## Contents

```
CalibBind-bench/
├── DATASHEET.md                      dataset card (v2, frozen)
├── EXCLUDED_PRODUCTS.md              16 excluded band-defined products and reasons
├── dataset_matching_extended.json    v2 benchmark, 579 questions (core, self-contained)
├── operator_conflicts.json           registered platform-metadata contradictions
├── distill/                          training pool & arm-selection validation
│   ├── train_uniq.jsonl             1,346 unique training rows
│   ├── val_uniq.jsonl               288 questions × 2 input modes
│   ├── suite_hard_train_v1.jsonl / suite_hard_val_v1.jsonl
│   ├── suite_soft_train_v1.jsonl
│   └── heldout_slice_index.json      203-question held-out slice (9 unseen products)
├── eswap/                            wavelength-counterfactual suite (359 paired questions)
│   ├── eswap_ds.json
│   └── README.md
├── lfo/                              leave-one-family-out folds
│   └── <Landsat|Sentinel|珞珈|其他>/{test_ext.json, train.jsonl}
└── scripts/                          standalone evaluation scripts
    ├── eval_band_benchmark.py        rule baselines over the 579 benchmark
    └── eswap_judge.py                scoring for the ESWAP counterfactual suite
```

The released `scripts/` are self-contained evaluation tools (Python standard library only).
Benchmark-construction scripts, API-backed baselines, and the raw OGE platform snapshots
they consumed are not part of this release — every benchmark row is self-contained, so no
snapshot is needed to evaluate a model.

## Evaluating

Both scripts read the shipped data directly and need no external keys or network:

```bash
python scripts/eval_band_benchmark.py              # rule baselines on the 579 benchmark
python scripts/eswap_judge.py --selftest           # self-check of the ESWAP scorer
python scripts/eswap_judge.py <results.jsonl>      # score model outputs on ESWAP
```

`eval_band_benchmark.py` accepts `--by-operator` for a per-operator breakdown.
Question files carry `ground_truth` for self-scoring; see DATASHEET for the policy on which
splits may be used for training.

## License

- Data and derived suites: [CC BY 4.0](../LICENSE-DATA).
- Code: [MIT](../LICENSE).

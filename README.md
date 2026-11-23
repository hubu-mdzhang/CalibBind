# CalibBind

**CalibBind: Decision Model-Driven Parameter Matching between Remote Sensing Data and Processing Operators**

Operator parameters on remote-sensing cloud platforms (e.g. `redBandName`) must be bound to
concrete data resources, but band naming is heterogeneous across sensors: the red band is
`SR_B4` on Landsat-8, `sur_refl_b01` on MODIS reflectance products, and `B04` on Sentinel-2.
CalibBind treats this as a **calibrated choice problem over a closed candidate set** rather
than a generation problem: the system must not only pick the right band, it must know when
it does not know.

This repository is the release bundle, organised into three self-contained units so that
data, external benchmarks, and model weights can be published and cited independently.

## Repository structure

```
CalibBind/
├── CalibBind-bench/     Main OGE benchmark and derived suites, with standalone evaluation scripts
│                        (579 questions, 33 products, 29 operators, T1–T5). CC BY 4.0 / MIT.
├── CalibBind-geo/       External GEE catalog-level benchmark (157 instances, 14 products).
│                        CC BY 4.0.
└── CalibBind-weights/   LoRA rank-16 student adapter (Arm A, seed 0) + frozen training config.
                         Apache-2.0. Weights are delta-only; the base model is not redistributed.
```

Each unit carries its own README describing contents, usage and licensing. Start there.

## Quick links

| Unit | What it contains | License |
|---|---|---|
| [CalibBind-bench](CalibBind-bench/README.md) | benchmark JSON, `distill/` `eswap/` `lfo/` suites, dataset card, evaluation scripts | data CC BY 4.0, code MIT |
| [CalibBind-geo](CalibBind-geo/README.md) | `calibbind_geo_v1.jsonl` + datasheet | data CC BY 4.0 |
| [CalibBind-weights](CalibBind-weights/README.md) | 1 LoRA delta (Arm A seed 0), training config, model card, merge/inference scripts | Apache-2.0 |

## Reporting discipline

- Primary metric: **end-to-end (question-level) accuracy**; parameter-/element-level go to
  supplementary tables. Every number is reported with its denominator.
- Cross-method Brier comparisons require matched answer rates (abstention can deflate Brier).
- Single-seed results are flagged; seed sets are reported with means and ranges.
- Ground-truth answers ship with the evaluation suites so results are self-scoreable.
  Use them for evaluation and reproduction only — training supervision comes exclusively
  from `CalibBind-bench/distill/train_uniq.jsonl`.

## Citation

```bibtex
@article{calibbind2026,
  title   = {CalibBind: Decision Model-Driven Parameter Matching between Remote Sensing
             Data and Processing Operators},
  author  = {Qiao, Yun},
  journal = {Remote Sensing},
  year    = {2026},
  note    = {preprint}
}
```

## License

- Code: MIT (see `LICENSE`).
- Benchmark data and derived suites: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
  (see `LICENSE-DATA`).
- Model weights (LoRA deltas): [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0),
  matching the `jaredpalmer/kev` base; the `Qwen3.5` backbone carries its own upstream license.
- Band/product metadata is collected from the public OGE (Open Geo Engine) platform API,
  with external catalog metadata from the public Google Earth Engine Data Catalog.

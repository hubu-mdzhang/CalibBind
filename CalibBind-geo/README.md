# CalibBind-geo

External catalog-level band-binding benchmark for Google Earth Engine (GEE), released as
a standalone unit so it can be cited and distributed independently of the OGE-based main
benchmark.

**157 evaluation instances** (60 base + 97 controlled variants) across **14 exact GEE
products**, each rendered under two paired input conditions (`names_only` / `full_catalog`).
Ground truths are derived from the official GEE Data Catalog band tables; the benchmark is
catalog-level and makes no claim of OGE equivalence.

## Contents

```
CalibBind-geo/
├── README.md
└── data/
    ├── calibbind_geo_v1.jsonl             one JSON object per instance
    └── calibbind_geo_v1_datasheet.md      full dataset card
```

The JSONL records, for each instance: `instance_id` with variant lineage, `dataset_id` /
`catalog_url`, task family (7 families: nir, swir, thermal, ndvi, ndwi, ndbi, ndssi
bindings), `candidate_set`, ordered `answer_roles` / `expected_answer`, per-candidate
`catalog_bands` metadata (description, wavelength_nm, source_reference, review status),
an `oge_disclosure` provenance note, and a `prompt_contract` with the fixed shuffle seed
(20261028) and template version.

## Integrity

- `calibbind_geo_v1.jsonl` sha256:
  `637296e40aacf827d2972f8cb990244afbbbfeb2780539b1d3ba3bad0dc739f2`
- Self-checks S1–S5 (uniqueness, truth membership, metadata review, candidate coverage,
  recorded hash) all pass; ground truth never enters prompts (machine-checked).

See the [datasheet](data/calibbind_geo_v1_datasheet.md) for full statistics and construction
evidence. Question files carry `ground_truth` for self-scoring — use for evaluation and
reproduction only.

## License

- Data: [CC BY 4.0](../LICENSE-DATA).
- Catalog metadata descriptions are quoted from the public Google Earth Engine Data Catalog
  for research use.

# CalibBind-geo v1 — dataset card

External catalog-level band-binding benchmark for Google Earth Engine: **157 evaluation instances** (60 base + 97 controlled variants) across **14 exact GEE products**, each rendered under two paired input conditions (`names_only` / `full_catalog`).

## File

- `calibbind_geo_v1.jsonl` — one JSON object per instance. sha256: `637296e40aacf827d2972f8cb990244afbbbfeb2780539b1d3ba3bad0dc739f2`

## Fields

| field | meaning |
|---|---|
| instance_id | unique instance id (base ids use the original case id; variants suffix `__<type><n>`) |
| base_instance_id / is_variant / variant_type | variant lineage (phrasing / role_distinction / distractor) |
| dataset_id / catalog_url | exact GEE collection id and its official catalog page |
| task / task_family | task wording and task family (7 families: nir, swir, thermal, ndvi, ndwi, ndbi, ndssi bindings) |
| candidate_set | candidate band names shown to the model |
| answer_roles / expected_answer | ordered roles and ordered ground truth (inside candidates) |
| catalog_bands | per-candidate official description, wavelength_nm, source_reference, review status — everything needed for the full_catalog condition |
| oge_disclosure | local source-row provenance; equivalence to OGE is NOT claimed |
| prompt_contract | fixed shuffle seed (20261028), template version (catalog-band-slot-aware-v1.0), per-condition candidate fields |

## Statistics

- base instances: 60 (by product: {'COPERNICUS/S2_HARMONIZED': 7, 'COPERNICUS/S2_SR_HARMONIZED': 4, 'LANDSAT/LC08/C02/T1': 5, 'LANDSAT/LC08/C02/T1_L2': 5, 'LANDSAT/LC09/C02/T1': 5, 'LANDSAT/LC09/C02/T1_L2': 5, 'LANDSAT/LT05/C02/T1': 5, 'MODIS/061/MOD09A1': 7, 'MODIS/061/MOD09Q1': 2, 'MODIS/061/MOD13A1': 2, 'MODIS/061/MOD13Q1': 2, 'MODIS/061/MYD09A1': 7, 'MODIS/061/MYD09Q1': 2, 'MODIS/061/MYD13A1': 2})
- task families (base): {'ndbi_swir1_nir_binding': 7, 'ndssi_blue_nir_binding': 10, 'ndvi_red_nir_binding': 14, 'ndwi_green_nir_binding': 7, 'single_band_nir': 7, 'single_band_swir': 10, 'single_band_thermal': 5}
- variants: 97 ({'distractor': 4, 'phrasing': 60, 'role_distinction': 33}); variants share the base semantic key and are disclosed, not treated as independent
- both conditions per instance are rendered from these fields with the pinned seed; ground truth never enters prompts (machine-checked)

## Construction and evidence

- Every displayed candidate carries reviewed description/wavelength metadata sourced from the official GEE Data Catalog band tables (BrowserSkill retrieval, 2026-10-29/30).
- Admission standard: exact GEE dataset id + official catalog evidence + reviewed per-candidate metadata + ordered truth. OGE provenance is disclosure only; no strict OGE-equivalence claim is made.
- Self-checks S1–S5 (uniqueness, truth membership, metadata review, candidate coverage, recorded hash) pass.

## License

- Data: CC BY 4.0. Code in the companion repository: MIT.
- Catalog metadata descriptions are quoted from the public Google Earth Engine Data Catalog for research use.

## Provenance note

This release consolidates the per-batch working artifacts (verified case batches v12/v13, variant file, test registry, band cache). No Earth Engine API, model, or serving calls were involved in building it.

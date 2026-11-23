# E-SWAP · wavelength counterfactual swap suite (359 questions)

A controlled counterfactual evaluation built from the 579-question full set: candidate
wavelength intervals are swapped in pairs and the reference answer is re-derived within the
candidate set from the swapped wavelengths. It tests whether model outputs follow physical
evidence rather than label strings or positional priors.

## Data

- `eswap_ds.json` — 359 questions (579 screened → 220 removed: 138 because the swap partner
  was outside the candidate set so the new truth was unselectable, the rest because the new
  truth was undefined). sha256 below.

## Evaluation

- `../scripts/eswap_judge.py` — scoring (includes a selftest).

The construction scripts (screening, swap-partner pairing, truth re-derivation) and the
construction audit (three assertion types — candidate feasibility, index mapping, unique
hit — passed with zero failures over 587 elements before freezing) are not part of this
release; the frozen result is recorded in the sha256 below.

## Result definitions (paper §4.2)

With-wavelength condition: 86.0% of outputs follow the new truth (926/1077); negative
control 1.8% (below the random p95 = 12.8%); index tasks 84.2% and name tasks 90.9% agree.
Note: the v1 suite (`eswap_ds_v1_invalid`, not distributed) had a construction defect (new
truth unselectable in 138/138 cases) and is void — do not mix it with v2.

## Provenance

```
eswap_ds.json  sha256[:12] = b9b5a107930e
```

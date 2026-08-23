# Model registry — birth certificates

One row per deployed model version. Details live in `<name>.meta.json`; metrics were
recorded to the claims ledger at acceptance and re-check against `out/models/eval.json`.

| model | version date | git (train code) | split (train/cal/test runs) | headline | baseline beaten |
|---|---|---|---|---|---|
| band_forecast | 2026-08-23 | see meta | 19 closed runs ≤178, temporal 70/10/20 | Brier 0.296, 335 held-out refreshes | climatology Brier 0.715 |

## Rejected at the gate (findings, not deliverables)

| model | date | why |
|---|---|---|
| death_risk v1 | 2026-08-23 | the constants-derived heuristic OUT-RANKED the GBM on held-out runs (AUC 0.937 vs 0.897; model ECE 0.003 — calibrated but behind on ranking). The hand-tuned survival constants encode more signal than v1 extracted. |
| mob_move v1 | 2026-08-23 | failed the dual criterion (exact 0.757 vs rule 0.744 ✓, toward-recall 0.168 vs 0.187 ✗). Bonus correction: the LEAK-FREE rule baseline is 0.744/0.187 — far below the published 0.81/0.892, which scored profiles built from the frames they predicted. |

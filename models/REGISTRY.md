# Model registry — birth certificates

One row per deployed model version. Details live in `<name>.meta.json`; metrics were
recorded to the claims ledger at acceptance and re-check against `out/models/eval.json`.

| model | version date | git (train code) | split (train/cal/test runs) | headline | baseline beaten |
|---|---|---|---|---|---|
| band_forecast | 2026-08-23 | see meta | 19 closed runs ≤178, temporal 70/10/20 | Brier 0.296, 335 held-out refreshes | climatology Brier 0.715 |
| band_forecast (retrain, identical coefficients) | 2026-08-23b | see meta | all closed runs ≤178, temporal 70/10/20 | Brier 0.282, 366 held-out refreshes | climatology Brier 0.675 |
| stint_survival v1 | 2026-08-23 | see meta | all closed runs ≤178, temporal 70/10/20 | AUC 0.956, ECE 0.044, 118,606 held-out positives | **honesty note:** the coded baseline (-stint_age) scored AUC 0.153 — the SIGN was backwards (old stints keep surviving: survivorship, not decay). The honest 1-D baseline is therefore 0.847, and 0.956 beats it by +0.109, well past the +0.03 gate. Deployed; SHADOW-ONLY (wired at 0.90.0, activates with this artifact). |
| move_fail v1 | 2026-08-23 | see meta | all closed runs ≤178, temporal 70/10/20 | AUC 0.844, ECE 0.035, 14,832 held-out bounces | stamina-only AUC 0.750 (+0.094). Offline/advisory only — nothing consumes it live. |
| income_spot v1 | 2026-08-23 | see meta | all closed runs ≤178, temporal 70/10/20 | AUC 0.906, ECE 0.045, 10,084 held-out pickups | greedy line-of-sight (n_items_w6) AUC 0.830 (+0.076). Offline/advisory only. |
| dph_profile v1 (table) | 2026-08-23 | see meta | all closed runs, no split (descriptive) | 18 kinds, 11,856 clean single-adjacent samples; per-kind p50/p90/max + elite split | floor ≥30 samples/kind. Future consumer: de-guess AVOID_COST=8. |
| terrain_regrowth v1 (table) | 2026-08-23 | see meta | all closed runs, no split (descriptive) | hazard by sighting gap: ≤50t 0.0009%, 51-200t 0.06%, 201-1000t 0.67%, 1000+t 3.6% | floor ≥200 revisits/bucket. A real decay curve — flat STALE_COST=3 overprices fresh-ish memory and underprices ancient memory. |

## Rejected at the gate (findings, not deliverables)

| model | date | why |
|---|---|---|
| death_risk v1 | 2026-08-23 | the constants-derived heuristic OUT-RANKED the GBM on held-out runs (AUC 0.937 vs 0.897; model ECE 0.003 — calibrated but behind on ranking). The hand-tuned survival constants encode more signal than v1 extracted. |
| death_risk v2 (retrain) | 2026-08-23b | heuristic still out-ranks (AUC 0.940 vs 0.898) — consistent with v1; the constants keep their crown. |
| mob_move v2 (retrain) | 2026-08-23b | still fails toward-recall (0.166 vs rule 0.186); exact 0.759 vs 0.746 alone is not the dual criterion. |
| mob_move v1 | 2026-08-23 | failed the dual criterion (exact 0.757 vs rule 0.744 ✓, toward-recall 0.168 vs 0.187 ✗). Bonus correction: the LEAK-FREE rule baseline is 0.744/0.187 — far below the published 0.81/0.892, which scored profiles built from the frames they predicted. |

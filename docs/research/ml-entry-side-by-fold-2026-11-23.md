# ml_entry side split by fold: does it persist? (2026-11-23)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-D3-UNLOCK-20261123` (Manager Session 2026-11-22a); measured 2026-11-23

**Gates this adds or changes: none.** Tier 1, descriptive. Changes no served model, config or order path. Any Tier-3 consequence is a proposal below.

## Question
The served ENTRY model (`ml_decision_entry_v1r20261122`, real money) shows longs n 220 at -0.526 R against shorts n 214 at +0.836 R on its 2026-11-08..11-21 grade window; the old model's live record splits the same way (IPW-ML-ENTRY-SIDE-SPLIT). Does that split persist across the development folds, or is it one regime?

## What was run (provenance: MEASURED)
`python3 scripts/research/ml_decision_entry.py side-by-fold --ext-folds --frozen r1122=... --frozen r1115=...` (new subcommand; every existing command and default is untouched, test `test_existing_defaults_untouched`). Population: the 60-perp frozen universe (manifest bp2-f4271084b120), 4-hourly decision rows 2020-07..2026-11-20 (791,234 labelled rows, table max ts 2026-11-20 23:00Z), registered recipe (20 features, LGB_PARAMS, 2/3 ATR bracket, 24 h time stop), tau 0.10 (served tau), one open position per symbol. Net R carries the full cost stack (fee 11 bps rt + slippage 3 bps + funding 1 bps per 8 h). **Arm that answers the question: `refit`**, the recipe refit per fold on rows before the fold (7-day + 25 h purge), the only out-of-sample arm. The frozen served and previous boosters were also scored per fold but were trained through 2026-10-30 / 2026-10-23, so they are **in-sample on every fold except the last weeks** and are reported only as flagged context (their +0.4..+0.7 R/decision on old folds is training fit, not edge). Folds 2025-10-01 onward are post-dev (sealed holdout window) and were read under a ledger claim (`ENTRY-v1-side-by-fold`, holdout_reads.jsonl; two entries, the first run was killed by a timeout before it finished).
Evidence record: `comms/research/ML-D3-UNLOCK-20261123/side_by_fold_summary.json` and `side_by_fold_table.md` (git sha in the record). Network: data via Binance Vision on a cloud runner (not the trainer VM; the data is public).

## Result: refit arm, per fold and side (n, mean net R, iid se; week-clustered se is in the JSON)
| fold | long n | long mean | long se | short n | short mean | short se | always-long | always-short |
|---|---|---|---|---|---|---|---|---|
| 2022-01..2022-07 | 6515 | -0.049 | 0.013 | 5506 | +0.084 | 0.015 | -0.103 | +0.004 |
| 2022-07..2023-01 | 4608 | -0.092 | 0.016 | 7145 | +0.011 | 0.013 | -0.107 | -0.054 |
| 2023-01..2023-07 | 3126 | +0.223 | 0.019 | 7771 | +0.010 | 0.013 | -0.084 | -0.067 |
| 2023-07..2024-01 | 2923 | -0.057 | 0.020 | 6106 | -0.098 | 0.014 | -0.093 | -0.108 |
| 2024-01..2024-07 | 3140 | -0.047 | 0.019 | 5224 | -0.000 | 0.016 | -0.133 | -0.002 |
| 2024-07..2025-01 | 2489 | +0.091 | 0.021 | 5562 | +0.031 | 0.015 | -0.082 | -0.045 |
| 2025-01..2025-07 | 2500 | -0.026 | 0.021 | 4886 | +0.056 | 0.016 | -0.116 | -0.009 |
| 2025-07..2025-10 | 492 | +0.074 | 0.051 | 3341 | -0.026 | 0.020 | -0.043 | -0.103 |
| *post-dev* 2025-10..2026-01 | 1006 | -0.137 | 0.033 | 2194 | -0.036 | 0.024 | -0.121 | +0.017 |
| 2026-01..2026-04 | 1064 | +0.077 | 0.034 | 1945 | +0.145 | 0.025 | -0.135 | +0.003 |
| 2026-04..2026-07 | 692 | -0.209 | 0.040 | 1910 | -0.041 | 0.025 | -0.113 | -0.034 |
| 2026-07..2026-10 | 445 | +0.670 | 0.047 | 1484 | -0.110 | 0.028 | -0.007 | -0.197 |
| 2026-10..2026-11-21 | 325 | -0.446 | 0.047 | 1024 | +0.125 | 0.036 | -0.291 | +0.179 |

"always-long / always-short" = mean net R of mechanically taking that side at every free slot (what the market did to that side, no model). Cost per taken decision is 0.045-0.078 R (fold means) against gross R of -0.03..+0.29 by side; cost is not what separates the sides.

## Reading
1. **The split does not persist across the dev folds.** On the 8 dev folds the pooled refit result is long n 25,793 mean **-0.0063** and short n 45,541 mean **+0.0082**; per-fold short-minus-long gap averages -0.006 (se across folds 0.042, t -0.15); long is negative in 5 of 8 folds, short positive in 5 of 8, short beats long in only 4 of 8. The long fold means include +0.223 (2023H1, week-clustered se about 0.09).
2. **It tracks the market regime.** Across the 13 folds the model's per-fold gap (short mean minus long mean) correlates **0.89** with the fold's always-short-minus-always-long gap (0.69 on the 8 dev folds alone; fitted slope 1.78, so the model amplifies the drift). The latest fold is a short-biased window (always-long -0.291, always-short +0.179) and the model's long side (n 325, -0.446) loses there, while 2026-07..10 is the mirror image (long n 445 +0.670, short n 1,484 -0.110). This is the regime explanation, not a persistent long-side deficit.
3. **The model's dev edge is about zero.** Pooled over the 8 dev folds the refit policy earns +0.003 R/decision (n 71,334, week-clustered se 0.018, MEASURED from the per-fold records); per-fold means run -0.084..+0.071. The +0.146 R/decision on the 2026-11-08..11-21 grade window is a short window that happened to favour the model's drift exposure; it is not a dev-fold edge.
4. **Caveats.** The refit arm is the recipe, not the served booster (a refit is not bit-reproducible, ledger note in the grade rule). Folds are 3-6 months, so 8 dev folds is a small count for a regime claim; the t -0.15 and the 0.89 correlation are reported, never gating. No cross-check against the live journal was done here beyond the numbers quoted from IPW-ML-ENTRY-SIDE-SPLIT.

## Consequences (proposals, not applied)
- **No Tier-3 change is supported by this record.** A static long-side-off gate fails on dev data (short-only pooled +0.008 vs both +0.003, a difference far below any detectable +0.05); long-side-off would also forgo the +0.67 R long fold of 2026-07..10. **Not proposing it.**
- The first-20 real-money check already registered on IPW-ML-ENTRY-SIDE-SPLIT stands unchanged (it detects a collapse, not the edge).
- Step 2: unit `research/queue/RQ-20261123-d3a1-01.yaml` (rule `RULE-ML-D3-SIDE-GATE-TREND-20261123`, registered before any run): a trend-aligned side gate (long iff the symbol's trailing 168 h return > 0, short iff < 0) vs both-sides over the dev folds. Power: marginal at +0.05 (see the unit), so INDETERMINATE is a live outcome, stated now.

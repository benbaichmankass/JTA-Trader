# Prop gate edge-sensitivity: rule V3 and the re-grade of every recorded V2 verdict

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane PROP-GATE-EDGE-SENSITIVE (Tier 1, evidence tooling; no config, roster, order or mode)

**Gates this adds or changes:** tightens the prop EV/survival gate (V2 -> V3: adds the edge CI clause). Dispatched by Manager Session 2026-10-31a with the operator's authority (PI-20261030-9KC5G3FG-0007); the prop superset rule already requires prop legs to clear at least the real-money bar.

Lane PROP-GATE-EDGE-SENSITIVE · 2026-10-31 · PI-20261030-9KC5G3FG-0007 · Tier 1 (evidence tooling; no roster, config or order path touched).

## Operator decisions (popups in Manager Session 2026-10-31a, ~08:50Z, verbatim)
- trend_donchian_eth_prop: **"Keep, and get more evidence"** -> the leg stays rostered on breakout_2 / tradeify_1 / velotrade_1 **below the V3 bar by operator choice**. The evidence is the pre-registered unit `research/queue/RQ-20261031-422a-01.yaml` (longest ETH history + config-exact twins, pooled with a month-cluster bootstrap; PASS -> V3 re-grade, FAIL -> pull-from-prop proposal to the operator, INCONCLUSIVE -> the n that settles it).
- V3 gate: **"Merge V3 (Recommended)"** -> this PR is approved to merge (the manager merges; landing hold).

## ⚠️ The currently rostered prop leg no longer passes (Tier-3 call for the operator)

`config/accounts.yaml` (re-parsed 2026-10-31): `breakout_2`, `tradeify_1` and `velotrade_1` each roster `trend_donchian_eth_prop`.
Under V3 it is **FAIL_EDGE on all three accounts, on both windows and both cost arms** (12 of 12 cells).
Its 3y edge is +0.055 R/trade (current-stack arm; n=517; 95% CI [-0.054, +0.164]); trailing-365d +0.022 R (n=165; CI [-0.181, +0.225]).

**Read this correctly: FAIL_EDGE means "edge not proven at 95%", not "edge is zero".** The point estimate is positive and, unlike the E4 ledger, the
zero-edge null EV for this leg is NEGATIVE (-$7 to -$49 per life on 3y), so V2's positive EV here comes from the point edge, not from the rule structure alone.
It still does not clear the superset bar that real-money legs face. I changed nothing; the manager puts it to the operator. Options for the operator: keep (the leg
is already live on those books), run more evidence, or pull.

## What was wrong, what V3 is

V2 (breach ceiling c = 1 - 2F/W, EV > 0 at every seed) is insensitive to edge. The E4 ledger shows it directly: its zero-edge null EV is **positive**
(+$9 to +$225 per life, table below), i.e. a ledger with exactly zero net edge PASSes V2 on every account.

**V3 = V2 AND the ledger's net-of-cost per-trade edge has its two-sided 95% CI lower bound > 0** (mean - 1.96·sd/√n under the cell's own cost arm via
`prop_ev_sim.build_trades`; trades treated as independent). V2 PASS with CI lower bound ≤ 0 → `FAIL_EDGE`; an unreadable edge → `INDETERMINATE`; V2 FAIL / INDETERMINATE unchanged.
Every row also reports the zero-edge null EV (same ledger, `gross_r` shifted so mean net R = 0, re-simulated once: seed 1, 1000 lives, the cells' protocol).
Rule text registered in `research/queue/RQ-20261029-9a2c-01.yaml` (`amendments:`). One implementation: `scripts/research/prop_gate.py`; the three `aggregate.py`
copies now call it and regenerate byte-identical `summary.json`.

## Self-test (committed): `tests/test_prop_gate_edge.py`
- A synthetic zero-edge ledger has CI lower bound < 0 and grades `FAIL_EDGE` from a V2 PASS on all 3 accounts (`breakout_2`, `tradeify_1`, `velotrade_1`) × both arms.
- A clearly positive-edge ledger (+0.6 R gross) has lower bound > 0 and still PASSes.
- Edge clause only downgrades; a missing edge never PASSes; the de-meaned ledger has zero net edge.
- Whole-simulator evidence for the zero-edge case is the null-EV column: the real E4 ledger de-meaned PASSes V2's EV test.

## Re-grade (54 rows have n ≥ 88 and a null run; 18 rows with n < 88 are INDETERMINATE and have no null)
Machine-readable: `regrade.json` (all 72 rows). Reproduce: `python3 docs/research/prop-gate-edge-regrade-2026-10-31/regrade.py [--nulls]`.

Summary of V2 PASS rows (population: all recorded V2 cells, both arms): every PASS in the E4 and `trend_donchian_eth_prop` (rerun) and `eth4h` 3y cells → FAIL_EDGE.
**Only `sol4h` 3y (n=115, edge +0.365 R, CI lower +0.011 R) survives**, with a lower bound barely above zero. `ethprop` (PROP-REPLACEMENT ledger) cells that were V2 PASS on the `ven` arm → FAIL_EDGE.
The older V1 records in `comms/prop_survival/*.json` (RULE-P5-GATE-BRK-PER-LEG, 2026-10-16) predate V2 and carry no edge estimate; the V2 re-grade of the same legs supersedes them.
Caveats: independence of trades flatters the CI (it can let a borderline PASS through, not wrongly fail a real edge); null EV is a single seed.

| source | leg | window | account | arm | n | old (v2) | edge mean R [95% CI] | null EV $/life | v3 |
|---|---|---|---|---|---|---|---|---|---|
| RQ-20261029- | trend_donchian_eth_prop | 365d | breakout_2 | cur | 165 | PASS | +0.022 [-0.181, +0.225] | -1.29 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 365d | breakout_2 | ven | 165 | PASS | +0.038 [-0.165, +0.241] | +0.82 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 365d | tradeify_1 | cur | 165 | PASS | +0.022 [-0.181, +0.225] | -46.70 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 365d | tradeify_1 | ven | 165 | PASS | +0.038 [-0.165, +0.241] | -46.25 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 365d | velotrade_1 | cur | 165 | PASS | +0.022 [-0.181, +0.225] | +2.74 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 365d | velotrade_1 | ven | 165 | PASS | +0.045 [-0.158, +0.247] | -0.44 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 3y | breakout_2 | cur | 517 | PASS | +0.055 [-0.054, +0.164] | -6.81 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 3y | breakout_2 | ven | 517 | PASS | +0.069 [-0.039, +0.178] | -7.83 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 3y | tradeify_1 | cur | 517 | PASS | +0.055 [-0.054, +0.164] | -49.18 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 3y | tradeify_1 | ven | 517 | PASS | +0.069 [-0.039, +0.178] | -60.71 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 3y | velotrade_1 | cur | 517 | PASS | +0.055 [-0.054, +0.164] | -12.72 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_eth_prop | 3y | velotrade_1 | ven | 517 | PASS | +0.075 [-0.034, +0.184] | -10.28 | FAIL_EDGE |
| RQ-20261029- | trend_donchian_sol_prop | 365d | breakout_2 | cur | 65 | INDETERMINATE | +0.043 [-0.276, +0.363] | — | INDETERMINATE |
| RQ-20261029- | trend_donchian_sol_prop | 365d | breakout_2 | ven | 65 | INDETERMINATE | +0.056 [-0.263, +0.375] | — | INDETERMINATE |
| RQ-20261029- | trend_donchian_sol_prop | 365d | tradeify_1 | cur | 65 | INDETERMINATE | +0.043 [-0.276, +0.363] | — | INDETERMINATE |
| RQ-20261029- | trend_donchian_sol_prop | 365d | tradeify_1 | ven | 65 | INDETERMINATE | +0.056 [-0.263, +0.375] | — | INDETERMINATE |
| RQ-20261029- | trend_donchian_sol_prop | 365d | velotrade_1 | cur | 65 | INDETERMINATE | +0.043 [-0.276, +0.363] | — | INDETERMINATE |
| RQ-20261029- | trend_donchian_sol_prop | 365d | velotrade_1 | ven | 65 | INDETERMINATE | +0.058 [-0.261, +0.377] | — | INDETERMINATE |
| RQ-20261029- | trend_donchian_sol_prop | 3y | breakout_2 | cur | 203 | FAIL | +0.087 [-0.099, +0.273] | -17.93 | FAIL |
| RQ-20261029- | trend_donchian_sol_prop | 3y | breakout_2 | ven | 203 | FAIL | +0.097 [-0.089, +0.283] | -17.75 | FAIL |
| RQ-20261029- | trend_donchian_sol_prop | 3y | tradeify_1 | cur | 203 | FAIL | +0.087 [-0.099, +0.273] | -105.51 | FAIL |
| RQ-20261029- | trend_donchian_sol_prop | 3y | tradeify_1 | ven | 203 | FAIL | +0.097 [-0.089, +0.283] | -108.25 | FAIL |
| RQ-20261029- | trend_donchian_sol_prop | 3y | velotrade_1 | cur | 203 | FAIL | +0.087 [-0.099, +0.273] | -43.81 | FAIL |
| RQ-20261029- | trend_donchian_sol_prop | 3y | velotrade_1 | ven | 203 | FAIL | +0.099 [-0.087, +0.285] | -47.50 | FAIL |
| prop-replace | eth4h | 365d | breakout_2 | cur | 51 | INDETERMINATE | -0.156 [-0.625, +0.312] | — | INDETERMINATE |
| prop-replace | eth4h | 365d | breakout_2 | ven | 51 | INDETERMINATE | -0.145 [-0.613, +0.323] | — | INDETERMINATE |
| prop-replace | eth4h | 365d | tradeify_1 | cur | 51 | INDETERMINATE | -0.156 [-0.625, +0.312] | — | INDETERMINATE |
| prop-replace | eth4h | 365d | tradeify_1 | ven | 51 | INDETERMINATE | -0.145 [-0.613, +0.323] | — | INDETERMINATE |
| prop-replace | eth4h | 365d | velotrade_1 | cur | 51 | INDETERMINATE | -0.156 [-0.625, +0.312] | — | INDETERMINATE |
| prop-replace | eth4h | 365d | velotrade_1 | ven | 51 | INDETERMINATE | -0.150 [-0.616, +0.317] | — | INDETERMINATE |
| prop-replace | eth4h | 3y | breakout_2 | cur | 132 | PASS | +0.284 [-0.068, +0.637] | -6.70 | FAIL_EDGE |
| prop-replace | eth4h | 3y | breakout_2 | ven | 132 | PASS | +0.294 [-0.059, +0.646] | -9.05 | FAIL_EDGE |
| prop-replace | eth4h | 3y | tradeify_1 | cur | 132 | PASS | +0.284 [-0.068, +0.637] | -56.56 | FAIL_EDGE |
| prop-replace | eth4h | 3y | tradeify_1 | ven | 132 | PASS | +0.294 [-0.059, +0.646] | -71.31 | FAIL_EDGE |
| prop-replace | eth4h | 3y | velotrade_1 | cur | 132 | PASS | +0.284 [-0.068, +0.637] | -23.31 | FAIL_EDGE |
| prop-replace | eth4h | 3y | velotrade_1 | ven | 132 | PASS | +0.288 [-0.063, +0.639] | -17.14 | FAIL_EDGE |
| prop-replace | ethprop | 365d | breakout_2 | cur | 165 | FAIL | -0.008 [-0.209, +0.192] | -4.44 | FAIL |
| prop-replace | ethprop | 365d | breakout_2 | ven | 165 | FAIL | +0.008 [-0.192, +0.209] | -3.79 | FAIL |
| prop-replace | ethprop | 365d | tradeify_1 | cur | 165 | FAIL | -0.008 [-0.209, +0.192] | -25.58 | FAIL |
| prop-replace | ethprop | 365d | tradeify_1 | ven | 165 | FAIL | +0.008 [-0.192, +0.209] | -40.11 | FAIL |
| prop-replace | ethprop | 365d | velotrade_1 | cur | 165 | FAIL | -0.008 [-0.209, +0.192] | +3.20 | FAIL |
| prop-replace | ethprop | 365d | velotrade_1 | ven | 165 | PASS | +0.015 [-0.185, +0.215] | -0.62 | FAIL_EDGE |
| prop-replace | ethprop | 3y | breakout_2 | cur | 515 | FAIL | +0.003 [-0.103, +0.109] | -7.72 | FAIL |
| prop-replace | ethprop | 3y | breakout_2 | ven | 515 | PASS | +0.017 [-0.088, +0.123] | -4.59 | FAIL_EDGE |
| prop-replace | ethprop | 3y | tradeify_1 | cur | 515 | FAIL | +0.003 [-0.103, +0.109] | -69.51 | FAIL |
| prop-replace | ethprop | 3y | tradeify_1 | ven | 515 | FAIL | +0.017 [-0.088, +0.123] | -69.64 | FAIL |
| prop-replace | ethprop | 3y | velotrade_1 | cur | 515 | FAIL | +0.003 [-0.103, +0.109] | -12.58 | FAIL |
| prop-replace | ethprop | 3y | velotrade_1 | ven | 515 | PASS | +0.023 [-0.083, +0.128] | -11.88 | FAIL_EDGE |
| prop-replace | sol4h | 365d | breakout_2 | cur | 34 | INDETERMINATE | -0.080 [-0.747, +0.588] | — | INDETERMINATE |
| prop-replace | sol4h | 365d | breakout_2 | ven | 34 | INDETERMINATE | -0.072 [-0.739, +0.595] | — | INDETERMINATE |
| prop-replace | sol4h | 365d | tradeify_1 | cur | 34 | INDETERMINATE | -0.080 [-0.747, +0.588] | — | INDETERMINATE |
| prop-replace | sol4h | 365d | tradeify_1 | ven | 34 | INDETERMINATE | -0.072 [-0.739, +0.595] | — | INDETERMINATE |
| prop-replace | sol4h | 365d | velotrade_1 | cur | 34 | INDETERMINATE | -0.080 [-0.747, +0.588] | — | INDETERMINATE |
| prop-replace | sol4h | 365d | velotrade_1 | ven | 34 | INDETERMINATE | -0.084 [-0.748, +0.580] | — | INDETERMINATE |
| prop-replace | sol4h | 3y | breakout_2 | cur | 115 | PASS | +0.365 [+0.011, +0.718] | -15.22 | PASS |
| prop-replace | sol4h | 3y | breakout_2 | ven | 115 | PASS | +0.371 [+0.018, +0.724] | -16.90 | PASS |
| prop-replace | sol4h | 3y | tradeify_1 | cur | 115 | PASS | +0.365 [+0.011, +0.718] | -99.22 | PASS |
| prop-replace | sol4h | 3y | tradeify_1 | ven | 115 | PASS | +0.371 [+0.018, +0.724] | -102.14 | PASS |
| prop-replace | sol4h | 3y | velotrade_1 | cur | 115 | PASS | +0.365 [+0.011, +0.718] | -45.27 | PASS |
| prop-replace | sol4h | 3y | velotrade_1 | ven | 115 | PASS | +0.364 [+0.011, +0.716] | -41.06 | PASS |
| e4-prop-sim- | e4 | 365d | breakout_2 | cur | 847 | PASS | -0.017 [-0.107, +0.072] | +48.72 | FAIL_EDGE |
| e4-prop-sim- | e4 | 365d | breakout_2 | ven | 847 | PASS | +0.004 [-0.085, +0.094] | +46.78 | FAIL_EDGE |
| e4-prop-sim- | e4 | 365d | tradeify_1 | cur | 847 | PASS | -0.017 [-0.107, +0.072] | +224.67 | FAIL_EDGE |
| e4-prop-sim- | e4 | 365d | tradeify_1 | ven | 847 | PASS | +0.004 [-0.085, +0.094] | +218.84 | FAIL_EDGE |
| e4-prop-sim- | e4 | 365d | velotrade_1 | cur | 847 | PASS | -0.017 [-0.107, +0.072] | +199.11 | FAIL_EDGE |
| e4-prop-sim- | e4 | 365d | velotrade_1 | ven | 847 | PASS | +0.014 [-0.076, +0.103] | +209.32 | FAIL_EDGE |
| e4-prop-sim- | e4 | full | breakout_2 | cur | 1619 | PASS | +0.009 [-0.057, +0.074] | +9.23 | FAIL_EDGE |
| e4-prop-sim- | e4 | full | breakout_2 | ven | 1619 | PASS | +0.028 [-0.037, +0.094] | +8.16 | FAIL_EDGE |
| e4-prop-sim- | e4 | full | tradeify_1 | cur | 1619 | PASS | +0.009 [-0.057, +0.074] | +29.68 | FAIL_EDGE |
| e4-prop-sim- | e4 | full | tradeify_1 | ven | 1619 | PASS | +0.028 [-0.037, +0.094] | +31.61 | FAIL_EDGE |
| e4-prop-sim- | e4 | full | velotrade_1 | cur | 1619 | PASS | +0.009 [-0.057, +0.074] | +37.66 | FAIL_EDGE |
| e4-prop-sim- | e4 | full | velotrade_1 | ven | 1619 | PASS | +0.037 [-0.028, +0.103] | +64.93 | FAIL_EDGE |
## Can the prop-roster-gate-guard be satisfied by a zero-edge leg?
Yes. `scripts/ci/check_prop_roster_gate.py` checks that a `comms/prop_survival/<leg>.json` has a numeric `ev_net_usd`, `p_breach`, `n_trades` and `decision_rule.verdict == "pass"`; it reads no
edge field. Not changed here (it would be a new gate: operator's permission required). Proposed to the operator: require `decision_rule.id` to be V3 (or an `edge_ci_lo > 0` field) on new records.

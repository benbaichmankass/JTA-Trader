# ml_entry on props — RULE-P5-GATE-BRK-PER-LEG-V3 (lane ML-ENTRY-PROP-GATE, 2026-11-02)

Rule registered before the run: `research/queue/RQ-20261102-5e1a-01.yaml` (commit 7b3591a, registered_at 2026-11-02T10:47:24Z). One run, nothing tuned.
Population: served ENTRY v1 + extend-only TP, held-out 2025-10-01..2026-09-30, ETHUSDT+SOLUSDT, n=381 (5-symbol replay reproduced the evidence record's +0.02713 R, n=907, to 1e-6).

| firm | ceiling c | EV median $ (worst seed) | B median/worst | edge mean R [95% CI] | zero-edge null EV $ | V3 (firm arm / current-stack arm) |
|---|---|---|---|---|---|---|
| breakout_2 | 0.889 | -13.55 (-14.4) | 0.775/0.784 | 0.01704 [-0.1057, 0.13978] | -16.65 | FAIL / FAIL |
| tradeify_1 | 0.75 | -83.7 (-86.88) | 0.682/0.712 | 0.01704 [-0.1057, 0.13978] | -101.39 | FAIL / FAIL |
| velotrade_1 | 0.73 | -26.75 (-29.18) | 0.578/0.597 | 0.02233 [-0.10039, 0.14505] | -39.66 | FAIL / FAIL |

Reading: EV is negative at every seed on every firm (V2 FAIL); the edge CI straddles zero widely (lower bound about -0.10 R), so V3 would FAIL_EDGE even if V2 had passed. The leg's actual EV sits near each firm's zero-edge null, i.e. the sim loses what a zero-edge book loses. ETH+SOL are the weakest part of the 5-symbol record (ETH -0.003, SOL +0.009 R at the fixed-TP/extend replay; ADA carries the pooled +0.027).
Caveats: trades treated as independent (flatters the edge); lev cap 5 used for all firms (tradeify caps SOL at 2x; implied leverage of a 2xATR1h stop at 0.5% risk is well under 2x, so the cap does not bind); sim sizes by the gate's `--sizing start`.
Outcome: no roster change. Record `comms/prop_survival/ml_entry.json` (verdict fail).

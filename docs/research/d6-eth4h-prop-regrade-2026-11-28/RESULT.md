# D6 prop re-grade: trend_donchian_eth_4h, stop 1.5 vs 1.0, on the prop accounts

> **Doc status:** `live` · category `evidence` · last verified `2026-11-28` · lane ML-PRIMARY (Tier 1 evidence; no config, roster, order or mode)

**Gates this adds or changes:** none (applies the existing prop gate, `RULE-P5-GATE-BRK-PER-LEG-V3`, to a proposed stop change).

## Why
A held Tier-3 PR proposes `atr_stop_mult 1.5 -> 1.0` on `trend_donchian_eth_4h`.
- **Selection:** `RQ-20261127-d6c2-01`, run 46056323510.
- **Disjoint confirmation:** `RQ-20261128-e4c1-01`, run 46098068644, PASS.

The leg also trades on the prop accounts `tradeify_1` and `velotrade_1`, so the change reaches them unchanged. Prop legs clear a superset, and the record in `comms/prop_survival/trend_donchian_eth_4h.json` was graded on the 1.5 stop. Manager Session 2026-11-28a asked for this re-grade before any merge.

## Method (like for like with the record it re-grades)
- **Ledgers:** the committed d6c2-01 arm ledgers. `B` is stop 1.5 (the live config) and `S10T4` is stop 1.0. The two arms differ **only** in `atr_stop_mult`: tp_r 4.0, trail 6.0 and measured-move width 0.5 are the same in both.
- **Windows:** both ledgers are cut to the trailing **3y** (entries from 2023-10-15) and **365d** (from 2025-10-15) windows ending at the run's end, 2026-10-15. `build_ledgers.py` does the cut.
- **Simulator:** `prop_ev_sim`, path mode, 5 seeds × 1000 lives, current-stack cost arm (fee 11, slippage 3 bps round trip, swap 0.0003/day prorated).
  - Each firm's own ruleset, risk_pct 0.005, lev cap 5, DD switch 0.8, funded-start fresh.
  - Parameters are copied from `docs/research/prop-replacement-2026-10-30/run_cells.sh`, the run behind the current record (`run_cells.sh`).
- **Grading:** `scripts/research/prop_gate.py` (`grade.py` -> `summary.json`).
  - **V2:** n ≥ 88, breach median and worst below the firm ceiling, EV median and worst above 0.
  - **V3:** V2 **and** a 95% CI lower bound on per-trade net edge above 0.
- Reproduce with `python3 build_ledgers.py`, then `run_cells.sh <leg> <win> <acct> cur <seed>` for each cell, then `python3 grade.py`, all from the repo root.

## Result

| leg | window | account | n | ceiling | p_breach med / worst | EV $ med / worst | edge R [95% CI] | V2 / V3 |
|---|---|---|---|---|---|---|---|---|
| stop 1.5 (live) | 3y | tradeify_1 | 134 | 0.75 | 0.131 / 0.145 | 224.78 / 222.12 | +0.291 [-0.066, +0.647] | PASS / **FAIL_EDGE** |
| stop 1.0 (proposed) | 3y | tradeify_1 | 141 | 0.75 | 0.214 / 0.220 | 479.28 / 445.76 | +0.387 [-0.071, +0.845] | PASS / **FAIL_EDGE** |
| stop 1.5 (live) | 3y | velotrade_1 | 134 | 0.73 | 0.115 / 0.135 | 146.57 / 126.75 | +0.291 [-0.066, +0.647] | PASS / **FAIL_EDGE** |
| stop 1.0 (proposed) | 3y | velotrade_1 | 141 | 0.73 | 0.347 / 0.357 | 174.55 / 159.67 | +0.387 [-0.071, +0.845] | PASS / **FAIL_EDGE** |
| stop 1.5 (live) | 365d | tradeify_1 | 53 | 0.75 | 0.838 / 0.846 | -113.02 / -113.36 | -0.190 [-0.643, +0.262] | INDETERMINATE |
| stop 1.0 (proposed) | 365d | tradeify_1 | 55 | 0.75 | 0.799 / 0.808 | -78.56 / -88.94 | -0.142 [-0.728, +0.445] | INDETERMINATE |
| stop 1.5 (live) | 365d | velotrade_1 | 53 | 0.73 | 0.787 / 0.797 | -50.09 / -51.16 | -0.190 [-0.643, +0.262] | INDETERMINATE |
| stop 1.0 (proposed) | 365d | velotrade_1 | 55 | 0.73 | 0.814 / 0.830 | -38.54 / -40.14 | -0.142 [-0.728, +0.445] | INDETERMINATE |

## Reading
- **Gate verdict: the proposed stop does not clear V3 on either firm.** The incumbent stop doesn't either, so the verdict is unchanged: FAIL_EDGE before and after.
  - Both stops pass V2 on the 3y window on both firms.
  - Neither stop's edge CI clears zero.
- **What the stop changes on prop:**
  - EV is higher on both firms: tradeify_1 roughly doubles ($225 -> $479 median) and velotrade_1 rises from $147 to $175.
  - Breach probability is also higher, most on velotrade_1 (0.115 -> 0.347 median, ceiling 0.73) and less on tradeify_1 (0.131 -> 0.214, ceiling 0.75).
- **On the 365d window,** both stops are below the n floor, with negative EV and breach above the ceiling on both firms. The 1.0 stop is slightly less negative in EV.
- **Roster membership is unaffected.** The leg is on these accounts only through the operator's 2026-11-05 baseline exception (min size, DD switch armed), recorded in the prop survival file. Whether that exception should carry the new stop is a scoping question for the operator; this record only reports the grade.
- **Caveats:** trades are treated as independent, which flatters the CI. The 3y window here overlaps the d6c2-01 selection window, so it shows prop survival on the proposed bracket, not fresh edge evidence. The disjoint evidence is e4c1-01.

# B3 evidence: 2-D vol-gate walk-forwards, ETH 15m heads + BTC advisory head (2026-10-29)

> **Doc status:** `unknown` · category `research` · lane `ML-VOLGATE-WF-ETH-BTC` (plan [`ml-live-promotion-plan-2026-10-29.md`](../../plans/ml-live-promotion-plan-2026-10-29.md) step B3, § 3 P2/P3) · Tier 1, evidence only. **No `regime_policy.yaml`, stage or config edit is made or proposed by this record.**

One JSON record per `(head, strategy, regime/vol cell)` sits beside this file (`<head>/<strategy>/<regime>_<vol>.json`); `summary.json` holds the per-leg verdicts and the re-verify table. Reproduce with `scripts/research/ml_volgate_b3.py` (runs one leg under one head's labels) then `scripts/research/ml_volgate_b3_records.py` (writes the records).

## What was measured (population stated)

| item | value |
|---|---|
| trades graded | each leg's own harness trades over **~4 years of Binance-vision candles** (`--days 1460`, window ending 2026-10-27), full per-leg counts in `summary.json`; the ETH legs drop trades after the labels end (below) and count them |
| cost basis | every trade's `net_r` is net of **fee + slippage + funding** as stamped by the harness (`cost_fee_r`, `cost_slippage_r`, `cost_funding_r`); each record carries `resolve_run_costs(symbol)` (fee 7.5 bps, slippage 3.0, funding 1.0 bps/8h) and a `cost_stack_attested` flag |
| cell rule | registered before the run (plan § 3 P2): `<dir>_stable_drag` = pooled < 0 AND strict majority of folds negative under **every** member of `FOLD_PANEL = (3, 4, 5)`, not fold-sensitive, ≥ 10 trades in that direction |
| book rule | gated book (all passing cells together) vs ungated, four 365-day folds: net ≥ ungated in ≥ 3 of 4 AND pooled maxDD ≤ ungated |
| fidelity | the harness flag, read per leg. `approximate` ⇒ **REFUSED** (plan § 7); the numbers stay in the record as `informational_only` and `would_be_if_not_refused` |
| labels | the head's `P(volatile) ≥ 0.5` (the live resolver's threshold) replayed by `ml_vol_label_replay.py replay` on the trainer; transitions only, as-of lookup, gz-verified on arrival |

## Caveats that apply to EVERY record (read before using any verdict)

1. **The replayed labels are not verified against the live gate.** `ml_vol_label_replay.py verify` needs the live `regime_ml_vol_shadow` audit rows, which live on the live VM, not the trainer; no ETH head is advisory, so the router writes no rows for it at all. All three heads are `live_verified: false`, and `in_sample: true` (the artifact saw the history it labels).
2. **The ETH labels end on 2026-07-18** (dataset `v901` is frozen). Trades after that bar are excluded and counted (`trades_excluded_after_labels_end`), never graded on a carried-forward label.
3. **Both ETH heads call ~78% of 15m bars "volatile"** at the live threshold (xasset 78.9%, selfonly 77.0%); the BTC head calls 8.0%. An ETH `volatile` cell is therefore most of the book and the `calm` cells are small. This is a measured property of the heads, not a harness artefact.
4. ETH heads: live AUC 0.675 (xasset) / 0.697 (selfonly), `live_parity` still `insufficient_data` (12 live rows, 20 needed) at the 06:47Z gate-check, so neither is `ready` for advisory.

## Per-leg verdicts

| head | leg | harness fidelity | verdict | detail |
|---|---|---|---|---|
| ETH xasset-v1 | `eth_pullback_2h` | faithful | **NO_CANDIDATE_CELL** | the leg only trades in the trending trend regime; no vol cell is a stable drag; book rule not triggered |
| ETH selfonly-v901ctrl | `eth_pullback_2h` | faithful | **NO_CANDIDATE_CELL** | same |
| ETH xasset-v1 | `trend_donchian_eth` | **approximate** (the harness does not apply the live exit head; its separate replay pass was not run here) | **REFUSED_UNFAITHFUL** | informational: `transitional/volatile` long −11.48 R / 53 trades, stable drag; book rule would pass (3/4 folds, maxDD 33.3 → 28.4 R) |
| ETH selfonly-v901ctrl | `trend_donchian_eth` | **approximate** | **REFUSED_UNFAITHFUL** | informational: `transitional/volatile` long −10.80 R / 53, and `trending/calm` long −3.63 R / 15; book rule would pass (3/4, 33.3 → 26.5 R) |
| BTC fc-pcv-v2 | `htf_pullback_trend_2h` | faithful | **REDUNDANT_WITH_1D_CELL** | three short cells are stable drags, but the existing 1-D table already has `short: off` for trending, transitional and chop, so authoring them removes no further order |
| BTC fc-pcv-v2 | `squeeze_breakout_4h` | faithful | **BOOK_RULE_FAIL** | the authored `trending/calm` short cell is still a stable drag (−2.45 R / 13), but gating it raises pooled maxDD 6.07 → 7.58 R |
| BTC fc-pcv-v2 | `fade_breakout_4h` | faithful | **NO_CANDIDATE_CELL** | 88 of 108 trades in `chop/calm`, no stable drag; other cells < 10 trades |
| BTC fc-pcv-v2 | `fvg_range_15m` | faithful | **REFUSED_COST_UNATTESTED** | the harness stamps none of the three cost terms (0 of 38 trades), so the cost stack cannot be attested; also no stable drag |
| BTC fc-pcv-v2 | `turtle_soup` | none | **REFUSED_NO_HARNESS** | no offline harness classifies this leg |
| BTC fc-pcv-v2 | `trend_donchian` | **approximate** | **REFUSED_UNFAITHFUL** | informational: `transitional/volatile` long −8.34 R / 13 is a stable drag, NOT an authored cell |
| BTC fc-pcv-v2 | `ict_scalp_5m` | faithful | **LEG_PASS (formal) — recommend NOT authoring** | see below |

### `ict_scalp_5m` needs a decision, not a cell

All six `calm` cells (both directions, every trend regime) are stable drags and the book rule passes by a wide margin (maxDD 192 → 12.8 R) — **because the ungated book is negative in every one of the four folds** (−38.7, −65.3, −45.5, −40.6 R; 528 trades; mean cost 0.34 R/trade, fee alone 0.26 R). Gating `calm` removes 453 of the 528 trades. That is not a regime filter, it is the leg switched off, and the evidence says the leg has no net edge on this harness at this cost stack. Plan Rule 1 (no cosmetic cells) does not apply (the book is not healthy), but authoring six router cells to hide a losing leg is the wrong instrument. Flagged to the manager as a **leg-level question** (retirement or redesign through the Stage-1/retirement-record path), not a Tier-3 router packet. The leg is rostered on `bybit_1` only.

## Re-verify of the authored `trend_vol` cells under the current BTC head (plan § 3 P3)

| authored cell | leg harness | verdict | n (gated dir) | pooled R (gated dir) | removal candidate? |
|---|---|---|---:|---:|---|
| trending/volatile long | `trend_donchian` (approx) | REFUSED_UNFAITHFUL; would be `FAIL_FOLD_SENSITIVE` | 20 | −0.93 | informational |
| transitional/calm long | `trend_donchian` (approx) | REFUSED_UNFAITHFUL; would be `FAIL_FOLD_SENSITIVE` | 61 | −4.35 | informational |
| chop/calm long | `trend_donchian` (approx) | REFUSED_UNFAITHFUL; would be `FAIL_NOT_STABLE_DRAG` | 106 | **+5.90** | informational; the cell blocks trades that net positive |
| trending/calm short | `squeeze_breakout_4h` | **CELL_PASS** (still a stable drag) | 13 | −2.45 | no (but see book rule above) |
| trending/volatile long + short | `ict_scalp_5m` | FAIL (long not a stable drag, short fold-sensitive) | 13 / 16 | +3.44 / −0.26 | **yes** |
| chop/volatile long + short | `ict_scalp_5m` | FAIL_FOLD_SENSITIVE both | 10 / 15 | −2.97 / −0.81 | **yes** |

Per the plan a cell that is no longer `stable_drag` gets a Tier-3 **removal** proposal. The `ict_scalp_5m` cells qualify on a faithful harness, but their samples are small (10 to 29 trades per cell) and the leg itself is the larger question above. The three `trend_donchian` cells cannot qualify until the harness is faithful.

## What this means for P2 / P3 (B7 input)

- **P2 (ETH heads): no cell is promotable from this record.** `eth_pullback_2h` has no candidate cell under either head. `trend_donchian_eth` shows a consistent `transitional/volatile` long drag under both heads, but its harness cannot replay the live exit head, so it is refused. **The unblock is a measurement, not a decision:** replay the exit head (`scripts/ml/exit_head_replay.py`, B4's corpus) on the tagged trades of that one cell and re-grade; if it still passes, it is a faithful P2 candidate. Until then there is no ETH head to promote on the strength of this record (a head with no passing cell changes no order: plan § 2, "promotion with no consumer").
- **P3 (BTC): no extension cell is promotable.** `htf_pullback_trend_2h` is already covered by the 1-D table; `fade_breakout_4h` and `fvg_range_15m` have nothing; `turtle_soup` has no harness; `ict_scalp_5m` is a leg-level question.
- **Open follow-ups** are on the checklist row `ML-VOLGATE-WF-ETH-BTC`.

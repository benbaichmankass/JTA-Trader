# Regime Tier-3 packets: P2-R3.c03 (eth_pullback_2h) and P2-R3.c04 (trend_donchian_sol), 2026-11-17

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `RESEARCH-OPS-20261117-1006` (manager ask `PI-20261117-ZFRREVN5-0005`); measured 2026-11-17

**Gates this adds or changes: none.** This doc holds two Tier-3 proposals for the manager. Nothing here is applied. The operator flips.

## Summary

| node | leg | lever | verdict | proposed change |
|---|---|---|---|---|
| P2-R3.c04-pass | trend_donchian_sol (bybit_1, testing) | `vol_skip_above_pctl: 0.9` (skip entries whose trigger-bar ATR percentile is above 0.9) | **READY** | one line in `config/strategies.yaml` (below) |
| P2-R3.c03-pass | eth_pullback_2h (bybit_1, testing) | `skip_hours: "20,21,22,23"` (no entries on trigger bars 20–23 UTC) | **NOT READY**: one of three windows was read against an exit the leg does not run | completed by unit `RQ-20261117-f5b3-01` |

## What the regime-selectivity skill does and does not cover here (axis fidelity)

Neither lever is a regime OFF-cell. `.claude/skills/regime-selectivity/SKILL.md` governs `(trend, vol)` cells in `config/regime_policy.yaml`, which the router enforces through the advisory vol head. Both levers here are **per-strategy entry filters** read inside the strategy unit:

- `trend_donchian.py:368` reads `vol_skip_above_pctl`. It ranks ATR within a trailing 200-bar window (`vol_pctl_window`, default 200). The harness does the same (`scripts/backtest_trend.py:583`, the same 200-bar rolling rank), and the unit comment says it mirrors the harness "bar-for-bar". The gate is fail-permissive: an unfilled window never skips.
- `htf_pullback_trend_2h.py:296` reads `skip_hours` on the trigger bar's UTC hour. The harness does the same (`scripts/backtest_pullback.py --skip-hours`, "UTC hours whose trigger bars never enter"). The live ETH builder (`strategy_signal_builders._htf_pullback_variant_builder`) passes the whole `config/strategies.yaml` block into `order_package`, so the key reaches the unit.

So:

- **The `config/regime_policy.yaml` diff is empty for both legs.** Neither leg appears in that file (grep, 2026-11-17).
- **`regime_cell_walkforward.py` does not apply.** It folds router `(trend, vol)` labels, and these filters do not use them. Rule 2's intent (the result must generalise out of sample) is checked instead on **disjoint calendar windows, each graded on 4 folds** under a rule registered before the run.
- **Rule 1 (no cosmetic cell) is checked as "does the filter add net R, not only cut drawdown".** Both filters add net R on every window read.

Cost basis for every number below: the harness's venue stack, net of fee 7.5 bps round trip + slippage 3 bps round trip + funding 1 bps per 8 h, resolved by `execution_costs.resolve_cost_policy`. All R figures are net.

## P2-R3.c04: trend_donchian_sol, `vol_skip_above_pctl: 0.9`. READY

The control arm in each read is the leg config-exact: long-only, atr 2.5 / trail 5.0, min_confidence 0.8. That matches today's live block. The leg declares no trail_decay. Structure exit was removed 2026-11-05, and the 47b6 reads come after that. The exit head is `annotate`, which observes only.

| unit | window | role | control n / net R | VH90 n / net R | ΔR | ΔmaxDD | fold wins | verdict |
|---|---|---|---|---|---|---|---|---|
| RQ-20261013-407c-21 | 2024-10-05..2026-10-04 | discovery (best of VH80/90/95) | 120 / +18.18 | 105 / +29.55 | +11.36 | −1.01 | 4/4 | PASS |
| RQ-20261016-65ff-04 | 2022-10-05..2024-10-04 | disjoint confirmation | 130 / +18.84 | 114 / +24.50 | +5.65 | −0.46 | 3/4 | PASS |
| RQ-20261031-7b6f-22 | 2020-07-01..2026-10-15 | full window, 6 folds | 380 / +63.18 | 329 / +81.39 | +18.21 | −1.02 | 5/6 | PASS |
| RQ-20261107-47b6-01 | 2020-07-01..2022-10-04 | pre-window | 129 / +32.17 | 109 / +33.13 | +0.95 | 0.00 | 2/4 | **FAIL** (bar 2.0 R) |
| RQ-20261107-47b6-02 | 2024-10-05..2026-10-26 | refreshed recent window | 122 / +14.11 | 107 / +25.61 | +11.50 | −1.02 | 4/4 | PASS |

VH90 per-fold net R on the 6-fold full window (7b6f-22): +17.68, +15.90, +8.82, +12.31, +16.62, +10.05. Every fold is positive, and the largest is 22% of the 81.39 total, inside the 50% cap. The control's last fold was +0.80, so most of the gain comes from 2025–26.

Reading:

- Across the three disjoint windows (2020-07..2022-10, 2022-10..2024-10, 2024-10..2026-10), VH90 adds +0.95, +5.65 and +11.50 R and never worsens drawdown.
- The earliest window is flat and fails its 2.0 R bar. The filter neither helps nor hurts there. It is a FAIL by the bar, not a loss.
- Multiple-testing denominator: VH90 was chosen as the best of 3 arms on the discovery window, and 7b6f-22 carried 2 arms. Six reads of the same lever value are listed above, all of them, including the failure.
- Rule 1: the ungated book is not all-folds-profitable on 2024-10..2026-10 (fold 3 −1.38 R and −5.70 R), and the filter adds net R rather than only cutting drawdown. Not cosmetic.

**Exact diff (`config/strategies.yaml`, block `trend_donchian_sol`, after `min_confidence: 0.80`):**

```diff
     min_confidence: 0.80
+    vol_skip_above_pctl: 0.9   # entry skip when the trigger-bar ATR percentile (trailing 200 bars) > 0.9 (Tier-3, P2-R3.c04; evidence RQ-20261013-407c-21, RQ-20261016-65ff-04, RQ-20261031-7b6f-22, RQ-20261107-47b6-01 FAIL flat, -02). ROLLBACK: delete this line.
```

`config/regime_policy.yaml`: **no change.**

**Accounts affected:** bybit_1 only (`mode: live`, Bybit demo, paper money). The leg is TESTING on the demo floor, with no real-money or mirror book. So this is a demo-floor configuration change with nothing to mirror.

**Pre-flip check:** the live candle frame must hold at least 200 1h bars, or the gate never fires (it is fail-permissive). After the flip, the first logged `vol_skip_above_pctl ... non-actionable` rejection on bybit_1 is the mechanical proof the gate works (Q6 parity).

## P2-R3.c03: eth_pullback_2h, `skip_hours: "20,21,22,23"`. NOT READY

The live exit is atr 2.5 / trail 5.0 plus `trail_decay_stall_bars 10 / trail_decay_tight_mult 2.5` (since 2026-08), with `adx_min 25`. Structure exit was removed 2026-11-05.

| unit | window | control carries the live trail_decay? | control n / net R | SL n / net R | ΔR | ΔmaxDD | fold wins | verdict |
|---|---|---|---|---|---|---|---|---|
| RQ-20261013-407c-13 | 2024-10-05..2026-10-04 | **no** (B argv has no decay flag) | 116 / +10.47 | 110 / +14.82 | +4.35 | −2.50 | 3/4 | PASS (discovery, best of SA/SU/SL) |
| RQ-20261016-65ff-03 | 2022-10-05..2024-10-04 | **no** | 106 / −2.04 | 102 / +5.89 | +7.92 | −3.46 | 4/4 | PASS |
| RQ-20261031-c6fc-04 | 2020-07-01..2026-10-15, 6 folds | yes (structure exit also on then) | 471 / −22.38 | 448 / −13.93 | +8.45 | −2.77 | 5/6 | **FAIL** (materiality 0.02 R × n = 9.42 R) |
| RQ-20261107-47b6-03 | 2020-07-01..2022-10-04 | **yes** (`--trail-decay-stall-bars 10 --trail-decay-tight-mult 2.5`) | 164 / +6.06 | 155 / +14.73 | +8.66 | −4.39 | 4/4 | PASS |
| RQ-20261107-47b6-04 | 2024-10-05..2026-10-26 | **yes** | 134 / +16.94 | 125 / +22.45 | +5.51 | −1.18 | 3/4 | PASS |

Why NOT READY:

- On 2026-10-16 the pullback argv builder dropped `--trail-decay-*`. The `exit_lever_ablation.py` docstring and self-test say so, and the B argv of 407c-13 and 65ff-03 carries no decay flag. By 2026-11-07 the flags were forwarded (47b6-03/-04).
- So, of the three disjoint windows, two (2020-07..2022-10 and 2024-10..2026-10) are measured against the live exit and both pass. The middle window 2022-10..2024-10 has only a read against a non-live exit.
- The full-window read c6fc-04 fails on materiality. It was run while structure_exit pivot=5 was still declared, so its incumbent is not today's either.
- The SL arm improved net R and drawdown in every read, and SL net stays negative over the 6-year c6fc-04 window (−13.93 R). The leg itself is weak; the filter makes it less weak.

**Unit authored to close the gap: `RQ-20261117-f5b3-01`.** It re-reads SL on 2022-10-05..2024-10-04 with the live exit forwarded, under the same 65ff-03 bar (ΔR ≥ 1.0, maxDD no worse, ≥ 3/4 folds). It also checks that B's argv carries the decay flags, and grades INDETERMINATE if not. It runs on the runner in about 25 min. PASS makes this packet READY. FAIL keeps it NOT READY, with the middle-window response recorded as exit-dependent.

**Diff to propose once f5b3-01 passes (`config/strategies.yaml`, block `eth_pullback_2h`, after `adx_min: 25`):**

```diff
     adx_min: 25             # ADX>=25 regime gate ...
+    skip_hours: "20,21,22,23"   # no entries on trigger bars 20-23 UTC (Tier-3, P2-R3.c03; evidence RQ-20261107-47b6-03, -04, RQ-20261117-f5b3-01 against the live trail_decay exit; earlier reads 407c-13 / 65ff-03 without decay, c6fc-04 FAIL materiality). ROLLBACK: delete this line.
```

`config/regime_policy.yaml`: **no change.** Accounts affected: bybit_1 only (demo floor, testing leg). The sibling `eth_pullback_prop_2h` is a separate leg and is not touched.

## Not done

- No VM read. The live candle-frame length for the SOL percentile window was not measured; it is listed as the pre-flip check.
- No packet was written for the related P2-R3.c01/c02 nodes (xrp/ada). They are outside this ask.

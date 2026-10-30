# PROP-REPLACEMENT: is there a prop leg to replace trend_donchian_eth_prop? (2026-10-30)

Lane PROP-REPLACEMENT (Tier 1 research; no config, no orders). Dispatched by Manager Session 2026-10-30c. Operator 2026-10-30: "Keep eth_prop until a replacement".

## Answer

**No candidate passes everything.** `trend_donchian_eth_4h` and `trend_donchian_sol_4h` pass Stage 0 and the v2 prop gate on the registered primary cell (current-stack arm, 3y window, all three accounts). **Both are negative on the trailing 365d**, and that window is INDETERMINATE under the rule (n 51 and 34, floor 88). RULE-P5-GATE-BRK-PER-LEG-V2 says a PASS whose sign flips on 365d is flagged CONTESTED, and maps CONTESTED to DE-RISK, not to an add. Neither leg has a verified Stage-1 soak count either. `trend_donchian_eth_prop` itself now FAILS the v2 primary cell on all three accounts when its ledger is rebuilt with the gap-fixed harness.

## Table (v2 = RULE-P5-GATE-BRK-PER-LEG-V2, 5 seeds x 1000 lives, one-leg book at the account's configured risk_pct, dd switch 0.8; B = per-attempt evaluation breach probability, ceiling c per firm)

Stage-0 columns: D1 = `RULE-D1-STAGE0-NET-OF-FULL-COST`, record's own window (STAGE0-REPRO-GAP, #21644); prop-stack = fee 8 / slip 3 / funding 5 bps per 24h, 1110d, `exit_lever_ablation --grade stage0` (the harness behind the v1 and v2 ledgers), rebuilt today with the gap-fixed harness.

| leg | Stage-0 old / gap-fixed (D1, own window; net R, n) | Stage-0 prop-stack gap-fixed (3y; net R, n, folds+) | v1 gate (old, record) | v2 primary: 3y, current stack, median B / worst B vs c; EV median / worst per life | v2 365d (n) | Stage-1 soak (bybit_1) | verdict |
|---|---|---|---|---|---|---|---|
| trend_donchian_eth_4h | +44.64 n135 / +28.95 n135 (pass) | +36.93, 132, 3/4 (pass) | pass: EV +95, p 0.63 (seed-max lifetime, not graded in v2) | breakout_2 0.248/0.279 vs 0.889, EV +$64.6/+$57.9 PASS; tradeify_1 0.142/0.159 vs 0.750, +$193/+$186 PASS; velotrade_1 0.122/0.135 vs 0.730, +$129/+$124 PASS | n=51 INDETERMINATE; net R -8.17; EV negative on all 3 accounts (-$17 to -$109) | contract `SOAK-stage1-bybit_1-trend_donchian_eth_4h` (n_needed 1, started 2026-06-18); latest committed snapshot 2026-10-04 reads "ready 17/10"; the leg is NOT on bybit_1's `strategies:` today (it is on bybit_2 and bybit_portfolio). Live count not verified (VM unreachable from this lane) | **CONTESTED, not an add** |
| trend_donchian_sol_4h | +36.86 n116 / +36.86 n116 (pass) | +41.18, 115, 3/4 (pass) | pass: EV +195, p 0.48 | breakout_2 0.067/0.075 vs 0.889, +$67.5/+$63.2 PASS; tradeify_1 0.028/0.034 vs 0.750, +$189/+$186 PASS; velotrade_1 0.013/0.018 vs 0.730, +$133/+$120 PASS | n=34 INDETERMINATE; net R -3.11; EV negative on all 3 accounts (-$14 to -$101) | contract `SOAK-stage1-bybit_1-trend_donchian_sol_4h` (n_needed 1, started 2026-10-27); on bybit_1 `strategies:` today; live count not verified | **CONTESTED, not an add** |
| trend_donchian_eth_prop (incumbent, like-for-like) | D1 365d: -0.25 n165 committed / -4.12 n165 gap-fixed (fail); WF-RECOST 516 +29.13 -> +2.32, 3/6, ex-max -7.30 (FAIL) | +6.38, 515, 3/4 (pass) | pass: EV +76, p 0.934 | breakout_2 0.650/0.667 vs 0.889, EV -$8.0/-$8.6 **FAIL**; tradeify_1 0.521/0.540 vs 0.750, -$54/-$64 **FAIL**; velotrade_1 0.439/0.459 vs 0.730, -$12/-$17 **FAIL** | n=165: FAIL on 5 of 6 account x arm cells (current stack all negative) | on bybit_1 and all 3 prop accounts today | **FAIL v2 on the gap-fixed ledger** |
| trend_donchian_sol_prop (not re-run) | D1 2170d: 395 +48.03 / +47.57 (pass) | +13.26, 202, 3/4 (pass) | pass: EV +39, p 0.595 | already FAIL on the old ledger (RQ-20261029-9a2c-01, `comms/prop_survival/v2/`); the gap-fixed ledger was not put through v2 | - | - | not a candidate (v2 FAIL, 2026-10-29) |

Venue-stack arm (firm commission/swap) is in `by_leg_account.json`; it moves the picture only for eth_prop (3y breakout_2 and velotrade_1 become PASS with EV +$1.2 and +$14.9, tradeify_1 still FAIL).

## Reading

1. **Gap-fixed ledgers are better for the 4h legs and worse for eth_prop.** eth_4h prop-stack 3y net R 31.01 (old ledger, n116) -> 36.93 (n132); sol_4h 43.29 (n116) -> 41.18 (n115); eth_prop 33.39 (n517) -> 6.38 (n515). The v2 PASS on eth_prop on 2026-10-29 was on the old ledger.
2. **The 4h legs' edge is in the first two years.** On the trailing 365d both are net negative at the prop-stack (eth_4h -8.17 R, n=51; sol_4h -3.11 R, n=34). #21644 saw the same for eth_4h at D1 (365d old/gap-fixed -9.57 / -12.43). n is far below the 88 floor, so this is "cannot tell", not "fails"; but the rule registered on 2026-10-29 names it CONTESTED and maps it to DE-RISK.
3. **sol_4h has the cleaner 3y survival** (B 0.01-0.07 against ceilings 0.73-0.89) than eth_4h (0.12-0.25), and the smaller recent loss. It is also the leg with the least live history (soak contract started 2026-10-27).
4. **Not differentiating, but worth knowing:** `check_tp_doctrine.py` marks eth_4h FAIL:entry_tp (tp_intent none, sentinel TP), the same status as eth_prop. The 4h legs run `decision_bar` unset (forming bar), the prop leg `closed` (PI-20261030-QEJFFIDN-0002).
5. **Config oddity (field beats comment).** `strategies.yaml` says eth_4h is live on "bybit_1/bybit_portfolio"; `accounts.yaml` lists it on bybit_2 and bybit_portfolio only, while `SOAKS.json` still carries a bybit_1 soak contract for it. Not changed here.

## If the operator wants a replacement anyway (NOT recommended by this lane as it stands)

The only defensible form under the registered rule is DE-RISK: add `trend_donchian_sol_4h` (preferred, better survival) to breakout_2 / tradeify_1 / velotrade_1 at half the account's configured risk_pct (0.00175 / 0.0025 / 0.0025, "half the current risk_pct" per `proposal_mapping`; the half-risk cells were NOT simulated here), after its Stage-1 soak count is confirmed on the VM, together with PR #21660. That is a Tier-3 roster + sizing change; revert = remove the leg from the three rosters. It would still trade a leg whose last 365d is negative on 34 trades. The alternative the data supports equally: wait for the 365d n to reach 88 (about 2.6 years at the current rate of 34 trades/yr for sol_4h) or re-test with a longer pinned window plus a walk-forward registered before the run.

## Not done / limits

- Live soak counts need the journal DB; this lane has no VM path (https to the duckdns host returned 000). The committed 2026-10-04 snapshot is stale.
- Half-risk cells not simulated (not in the registered rule's tested set).
- Windows: ledgers 2023-10-13 .. 2026-10-11 20:00 (data returned from 2023-10-16), the same as the v2 unit; the harness was fetched live on 2026-10-30.
- Reproduce: `exit_lever_ablation.py --leg <leg> --arm "P=--fee-bps-roundtrip=8;--slippage-bps-roundtrip=3;--funding-bps-per-window=5;--funding-window-hours=24" --days 1110 --start 2023-10-13 --end "2026-10-11 20:00" --grade stage0 ...`, 365d slice = entry_time >= 2025-10-11 20:00, then `run_cells.sh` and `aggregate.py` here.

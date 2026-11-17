# Promotion packet: why are paper legs that out-earn real money not promoted? (2026-11-17)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `AM-OPS-2`, dispatched by the manager on the operator's question below

Gates this adds or changes: none. Read-only analysis plus a proposal. It changes no config, bar, guard or mandate, and merges nothing.

## The question

Operator, 2026-11-17 ~16:24Z, verbatim (relayed by the manager): *"if we have things trading on paper accounts that are doing that well, that seem to be outperforming anything we actually have on Live Money, then why are they not being promoted?"*

## Short answer

1. **Paper R is not why a leg promotes, and most of it is not verified.** The ladder promotes on the Stage-0 record only (OPERATING-PLAN § 2: "a live or paper book never establishes edge"). On the paper book, 10 of the 17 legs below have fewer than a third of their R-trades `confirmed` (the rest are `unverified` or `contaminated`). For 10 of the 17 the venue-measured-only P&L is negative, or has no measured coverage. So the headline paper R mostly overstates what the venue would have paid (table in § 3).
2. **Only 3 legs pass the Stage-0 bar and are not barred for another reason** (`trend_donchian_eth_4h`, `trend_donchian_sol_4h`, `trend_donchian_eth_prop`). None can land today. Each stops at the same two mandate clauses, in this order: **R-AFFORD** (the committed account snapshot is stale: `bybit_2` 10.9 days, `alpaca_live` 16.2 days, bar 7 days) and **R-HOLDOUT** (no valid `holdout_confirmation` on the record).
3. **R-HOLDOUT is the structural blocker, and it cannot clear for the 4h legs until about June 2027 as written.** The only holdout unit that exists for these three (`RQ-20261106-5b7a-02`, `trend_donchian_eth_4h`) carries `not_before: 2027-06-07`, because the held-back span must reach 25 trades at the leg's measured 0.13 trades/day. `trend_donchian_sol_4h` and `trend_donchian_eth_prop` have no holdout unit at all. This is a decision for the operator (§ 6), not for this lane.
4. **The rest are blocked for stated reasons**: a standing operator exclusion (`uso_trend_1h`), a failed promotion clause (folds, n, fidelity), or a failed or missing Stage-0 record.

## 1 · Method and populations

- **Per-leg table:** `python3 scripts/ops/pipeline_map_numbers.py --stdout`, generated 2026-11-17 16:22Z at `ae4d2b6192`. Live read-state **read**; journal trust: known-divergent `bybit_2`, unrecorded `alpaca_live`. Paper-book trust: unrecorded `alpaca_options_paper`, `alpaca_paper`, `alpaca_portfolio`, `bybit_1`, `bybit_portfolio`, `ib_paper`.
- **Population of the live numbers:** `/api/bot/performance?window=all` (lifetime, so it includes trades from before a leg's current status). "Real money" is the route's top-level aggregate; "paper" is its `paper` block, pooled over every paper account the leg trades on. R basis counts come from `rProvenance` (`confirmedInitial`, `unverified`, `contaminated`). "Measured P&L sign" is `totalPnlMeasuredOnly` (venue-measured rows only), shown as sign and coverage; no dollar figures or balances are quoted.
- **Roster counts:** re-parsed from `config/accounts.yaml` today: `bybit_2` and `bybit_portfolio` = `[trend_donchian_xrp_4h, ada_pullback_2h, trend_donchian_sol_prop, ml_entry]`; `alpaca_live` and `alpaca_portfolio` = `[tqqq_trend_long_1d, ml_entry_eq_struct, slv_trend_1h, tlt_pullback_1h]`. 62 legs defined: production 8, testing 51, inactive 3.
- **Promotion verdicts:** `python3 scripts/ops/mandate_resolver.py --leg <leg> --from S1 --to S2 --account <acct> --json` for all 15 legs the manager listed, run 2026-11-17. The resolver stops at the **first** failing clause, so a clause after the one named here may still bind (the order is afford, holdout, cost fidelity, cap).
- **Limits of this read:** I did not refresh any account snapshot (it commits an equity reading; see § 6). The three extra legs (`trend_donchian_1h`, `claude_desk`) were added by me because their paper R is positive; they were not in the manager's list.

## 2 · The bar a leg has to clear (MD-PROMOTE-S1-S2, `config/mandates.yaml`)

n ≥ 30 · expectancy > 0 · fold majority · faithful fidelity (B1) · **holdout confirmation on the record, n ≥ 25** (operator 2026-10-16) · venue-symbol cost within 2.0 bps of the modelled slippage · **account affordability from a snapshot ≤ 7 days old** · **auto-promoted share ≤ 25% of the account's roster risk**. Soak step retired (operator 2026-11-12); mechanics are recorded as evidence, not required. DSR is a probation metric, not a gate (operator 2026-11-06, "Holdout governs; promote").

## 3 · Per-leg table

R = Σ realized R; conf = `confirmedInitial` / R-trades; meas = sign of venue-measured-only P&L (coverage). BT = Stage-0 net R OOS at the full cost stack, n OOS, folds positive, evidence date.

| Leg | BT (net R · n · folds · date) | Real money (lifetime) | Paper (lifetime, pooled) | Concrete reason not on real money | Next |
|---|---|---|---|---|---|
| `trend_donchian_eth_4h` | +30.91 · 135 · 3/4 · 2026-11-15 (closed bar, faithful) | n19 · R +4.66 · conf 6/19 · meas − (0.68) | n37 · R −6.02 · conf 10/37 · meas − (0.41) | Demoted 2026-11-06 on the DSR rule (PROD-LEGS-DSR-DECISION); that bar was then replaced by holdout (operator 2026-11-06 "Holdout governs; promote"). Clauses reached: R-AFFORD (snapshot 10.9 d). Next clause R-HOLDOUT: the 2026-10-16 confirmation (+19.23 R, n75) is on a superseded fingerprint (config gained `tp_revision`, `trail_decay_*`); re-run `RQ-20261106-5b7a-02` has `not_before 2027-06-07`. Prop-retest 2026-11-06: `FAIL_EDGE` (edge +0.212 R, CI [−0.127, +0.551]). | **(a)** |
| `trend_donchian_sol_4h` | +36.42 · 115 · 3/4 · 2026-11-13 (closed bar, faithful) | 0 trades | n23 · R +8.91 · conf 5/23 · meas + (0.39) | Pulled from real money 2026-11-06 ("Pull sol_4h, keep eth_4h"). Stale comment at `accounts.yaml:295` (SOAK-GATE1, 2026-10-05) lists it under `net_r_oos ≤ 0`; that was the then-current record, the 2026-11-13 closed-bar record passes. Clauses reached: R-AFFORD. No holdout unit exists. Prop-survival grade is FAIL (EV −$20, p_breach 0.05) but that gate binds prop accounts only; it trades on `tradeify_1` and `velotrade_1` by operator exception. | **(a)** |
| `trend_donchian_eth_prop` | +10.30 · 135 · 3/4 · 2026-11-14 (closed bar, faithful) | 0 trades | n14 · R +6.40 · conf 1/14 · meas − (0.86) | Never on `bybit_2`. Clauses reached: R-AFFORD. No holdout unit exists. Thin edge (E +0.076 R) and the paper R is 13 of 14 unverified/contaminated, with a negative venue-measured P&L at high coverage. Prop-survival record: p_breach 0.93 (prop accounts only). | **(a)** (weakest of the three) |
| `uso_trend_1h` | +18.94 · 58 · 4/4 · 2026-11-13 (faithful) | 0 trades | n24 · R +11.77 · conf 12/24 · meas + (0.46) | **Standing operator exclusion**, `accounts.yaml:1705`: "I don't wanna put USO on real money. I don't wanna make money from fossil fuels." (2026-08-29, survives any backtest). Mandate-wise it would reach R-AFFORD (`alpaca_live` snapshot 16.2 d) then R-HOLDOUT (no unit). | **(d)** unless the operator lifts the exclusion |
| `mgc_trend_1h` | +25.61 · 118 · **2/4** · 2026-09-24 | 0 trades | n4 · R +1.07 · conf 1/4 · meas none | R-FOLDS: 2 of 4 folds positive, not a majority. Record is 54 days old. Paper n4 is not evidence. | **(d)** (re-measure on the current harness is cheap) |
| `ief_pullback_1d` | +1.03 · **6** · 1/3 · 2026-10-22 | n1 · R −0.48 | n4 · R +5.90 · conf 2/4 · meas − (0.75) | R-B1-C5: fidelity `approximate` (omits `trail_decay_*`); n 6 < 30; 1 of 3 folds. Re-measure filed as PI-20261103-MB3OAWAX-0002. | **(d)** |
| `iaum_pullback_1d` | +10.68 · **8** · 4/4 · 2026-11-05 | n1 · R −1.47 | n3 · R +1.34 · conf 0/3 · meas + (1.00) | R-N: n 8 < 30 (a 1-day leg trades about 8 times a year). Holdout re-run `RQ-20261016-077e-08` is done but is not read before R-N. | **(d)** (n-below-power) |
| `trend_donchian` | −16.23 · 71 · 1/4 · 2026-10-28 (**approximate**: exit-head levers `exit_head_action/model/threshold` omitted) | n15 · R +7.64 · conf 5/15 · meas − (0.87) | n29 · R +23.71 · conf 4/29 · meas − (0.52) | R-B1-C4: Stage-0 verdict `fail`; removed from `bybit_2` by MD-S1-CUT-ON-STAGE0-FAIL (2026-10-05). Real-money R +7.64 is 5 confirmed of 15; the venue-measured P&L on those 15 is negative, so the positive R rests on unverified rows. The record is not a faithful replay (exit head omitted). | **(b)** |
| `trend_donchian_ada_4h` | −3.35 · 55 · 2/4 · 2026-11-13 (faithful) | 0 trades | n25 · R +10.74 · conf 5/25 · meas + (0.28) | Stage-0 fail; folds [+0.9, −3.2, +6.2, −7.3]. Paper R rests on 5 confirmed of 25, measured coverage 28%. | **(d)** |
| `trend_donchian_avax_4h` | −16.18 · 57 · 1/4 · 2026-11-13 (faithful) | 0 trades | n27 · R +6.38 · conf 6/27 · meas + (0.22) | Stage-0 fail, faithful. | **(d)** |
| `ict_scalp_sol_15m` | −12.50 · 87 · 1/4 · 2026-10-28 (faithful) | 0 trades | n51 · R +9.32 · conf 9/51 · meas − (0.41) | Stage-0 fail, faithful. | **(d)** |
| `ict_scalp_sol_5m` | −31.49 · 181 · 0/4 · 2026-10-28 (faithful) | 0 trades | n66 · R +9.29 · conf 20/66 · meas − (0.45) | Stage-0 fail, faithful; 0 of 4 folds. | **(d)** |
| `ict_scalp_eth_15m` | −2.92 · 76 · 2/4 · 2026-10-28 (faithful) | 0 trades | n46 · R +8.11 · conf 26/46 · meas − (0.59) | Stage-0 fail; the registered 730d escalation (n151, +0.43 R, 2/4 folds) grades `powered_verdict: fail`. Best-confirmed paper R of the group (26/46) but the venue-measured P&L is negative. | **(d)** |
| `trend_donchian_1h` (extra) | −10.57 · 184 · 2/4 · 2026-11-13 (faithful) | 0 trades | n9 · R +2.36 · conf 3/9 · meas − (0.78) | Stage-0 fail; paper n9. | **(d)** |
| `e4_oi_shock_1h` | no record under this name (`comms/strategy_evidence/e4_oi_shock.json` names `e4_oi_shock`: pooled 6 symbols, n856, +18.79 R, 3/5 folds, fidelity `research_harness_not_live_code`, **verdict `fail`**) | 0 trades | n31 · R +7.84 · conf 18/31 · meas + (0.90) | R-RECORD-MISSING: nothing is committed at `e4_oi_shock_1h.json`. The renamed-leg record exists but is a research harness, not the live code, and its own verdict is `fail`. | **(c)** |
| `ict_scalp_mgc_15m` | record `coverage_state: harness_failed` (2026-09-22): Yahoo serves ~60 d of 15m, the request was 365 d | 0 trades | n22 · R +8.24 · conf 15/22 · meas none | R-SOURCE-RUN-ABSENT: the harness never produced a run. The failure is the data window, not the symbol map. | **(c)** |
| `claude_desk` (extra) | no record (judgement-driven leg, no backtestable rule) | 0 trades | n11 · R +4.72 · conf 4/11 · meas + (0.91) | Not a backtestable leg; `execution: shadow` on `bybit_1`. | **(d)** |

**Counts:** (a) **3** · (b) **1** · (c) **2** · (d) **11** (17 legs: the manager's 15 plus `trend_donchian_1h` and `claude_desk`).

## 4 · (a) PROMOTE track: what is outstanding and the drafted diff

No (a) leg can merge today. For each, in order:

| Leg | 1. Refresh snapshot | 2. Holdout confirmation | 3. Then |
|---|---|---|---|
| `trend_donchian_eth_4h` | `bybit_2` ≤ 7 d | re-run `RQ-20261106-5b7a-02` (`not_before 2027-06-07`; see § 6 option 1) | resolver re-run, cost fidelity, cap |
| `trend_donchian_sol_4h` | `bybit_2` ≤ 7 d | author a `holdout_rerun` unit (none exists) | same |
| `trend_donchian_eth_prop` | `bybit_2` ≤ 7 d | author a `holdout_rerun` unit (none exists) | same |

**Cap arithmetic** (`mandate_resolver.py`, basis `uniform_account_risk_pct_share_of_roster`, 25%): with a 4-leg roster and 0 auto-promoted legs, adding one gives 1/5 = 20% (passes), two gives 2/6 = 33% (refused). So the **auto path admits one of the three**; any second or third needs the operator's explicit Tier-3 approval of a held PR.

**Drafted roster diff (do not merge; Tier 3).** `bybit_2` and `bybit_portfolio` change identically (ordered mirror equality, `tests/test_paper_portfolio_accounts.py`). Example for the single-leg auto path, leg order as it would be decided:

```diff
--- a/config/accounts.yaml   (bybit_2.strategies and bybit_portfolio.strategies, both)
-    strategies: [trend_donchian_xrp_4h, ada_pullback_2h, trend_donchian_sol_prop, ml_entry]
+    strategies: [trend_donchian_xrp_4h, ada_pullback_2h, trend_donchian_sol_prop, ml_entry, trend_donchian_eth_4h]
```

Then, if the operator approves beyond the cap, append `trend_donchian_sol_4h` and `trend_donchian_eth_prop` the same way. Each add also needs: the dated comment block with the operator quote and a revert line; `scripts/ci/check_tp_doctrine.py` BASELINE lines for any add that carries debt (the guard's baseline follows the roster); removal of the leg from `bybit_1` is **not** wanted (promotion moves a leg off general paper: `strategy-status-guard` refuses a leg on both books), so the add above must be paired with dropping the leg from `bybit_1` in the same edit. Verify with `strategy_status.py` and the three guards before the PR opens.

## 5 · (b) RE-TEST: drafted fidelity-check unit (not filed; no queue file is created by this packet)

Only `trend_donchian` qualifies: its record is `approximate` (exit-head levers omitted) and its real-money R is positive. The others in the "fail but positive paper" group are faithful replays whose failure is a failure, not a fidelity gap.

```yaml
# DRAFT, for the manager to file or discard. Question, not a promotion.
id: RQ-<next>
title: 'trend_donchian (BTCUSDT 1h): does the Stage-0 fail survive modelling the exit head the live leg runs?'
question: 'The 2026-10-28 record (-16.23 R, n71, 1/4 folds, full cost) omitted exit_head_action, exit_head_model and exit_head_threshold.
  If the live leg runs the exit head, replay it at the live parameters over the same window and the same cost stack and compare.'
decision_rule: 'PASS iff measured AND fidelity faithful AND net_r_oos > 0 AND 2*folds_positive > folds AND n >= 30, on the live config
  fingerprint, rule registered before the run. Anything else leaves the Stage-0 fail standing (kill, with the reason).'
power: 'n_oos 71 at 365 d; pooled test, one pre-registered config, no selection step.'
```

Expected value is low: the live real-money R (+7.64, 5 confirmed of 15) is carried by unverified rows and the venue-measured P&L on those trades is negative. The unit is cheap and settles the question once.

## 6 · Decisions and flags for the operator (the packet does not decide these)

1. **The holdout floor cannot clear for 4h legs until mid-2027.** `RQ-20261106-5b7a-02` has `not_before 2027-06-07` because the held-back span after 2026-10-18 must reach 25 trades at 0.13 trades/day. Any 4h or 1d leg inherits this. Options, for the operator: keep the bar and accept the wait; or re-register the holdout on a span no selection step read that ends earlier (a fresh pre-registration with one fixed configuration, not a loosened bar); or set a lower n floor for low-frequency legs. This is a change to a bar, so it is the operator's, and no lane should reword it.
2. **Snapshot freshness needs a committed equity reading.** R-AFFORD needs `comms/mandate_evidence/account_snapshot/<acct>.json` within 7 days; writing it commits an equity figure to the repo. This lane's standing rule is no balances in the repo, so the refresh was not run. The manager should decide whether the snapshot is exempt or whether the clause should read the sizer's answer without the stored figure.
3. **USO.** `uso_trend_1h` is the strongest-looking paper leg that is not on real money, and it is barred by the operator's own standing exclusion, not by evidence. It stays in (d) unless the operator lifts that.
4. **Keep the headline honest.** Paper R is a mechanics-and-cost check. Of the 17 legs, only 3 (`uso_trend_1h`, `e4_oi_shock_1h`, `claude_desk`) have at least a third of their paper R-trades confirmed together with a positive venue-measured P&L, and none of the three has a real-money path today (fossil exclusion, no usable record, shadow-only). `ict_scalp_eth_15m` and `ict_scalp_mgc_15m` are well confirmed (26/46, 15/22) but the first has a negative venue-measured P&L and the second has none measured.
5. **Stale comment** at `config/accounts.yaml:295` (the `trend_donchian_sol_4h` entry in the 2026-10-05 removal list) should be annotated as historical in a later Tier-1 comment edit. It is not changed here.

## 7 · Reproduce

```
python3 scripts/ops/pipeline_map_numbers.py --stdout
python3 scripts/ops/mandate_resolver.py --leg <leg> --from S1 --to S2 --account <bybit_2|alpaca_live|ib_live> --json
curl -sS 'https://ict-bot.duckdns.org/api/bot/performance?window=all'   # perStrategy and paper.perStrategy
```

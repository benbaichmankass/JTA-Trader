# Promotion rule: a grade-window-only number never promotes. Inventory, fix and ml_entry re-grade (2026-11-25)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `PROMOTION-RULE-GRADE-WINDOW` (session_01AFoLuLQx4b4w8jWqXS8bUY), dispatched by Manager Session 2026-11-25a · row `PROMOTION-RULE-GRADE-WINDOW`

**Gates this adds or changes:** none new. This memo applies the operator's decision. The rule is stated once, in [`OPERATING-PLAN § 2 "A number measured only over the grading window never promotes"`](../plans/OPERATING-PLAN-2026-09-21.md). The proposal in Part 3 is for the operator and is **not applied**.

Operator decision, 2026-11-23, reconfirmed 2026-11-25, verbatim: *"Promotion-rule fix THIS WEEK: a number measured only over the grading window must not promote. Then re-grade ml_entry under the fixed rule; any promotion or demotion proposal goes to the operator."*

## Part 1: where a number from the choosing window could clear a promotion bar

| # | Path | What chooses | What promoted | Grade-window-only? | Fix |
|---|---|---|---|---|---|
| 1 | **ENTRY replacement** (`RULE-ENTRY-PROMOTE-20261106` Am. 1–3, `scripts/research/ml_entry_candidate_grade.py`, `.github/workflows/ml-entry-retrain.yml`) | candidate vs served on the 14-day window `[S, run−1]` | the same comparison on the same window. It is also the headline in `ml/served/SERVED_MODELS.yaml` | **Yes.** All three swaps (v1r20261106, v1r20261115, v1r20261122) | **Am. 4 (this PR):** choose on the first 7 days, then pass "at least as good" with the same floors on the disjoint last 7 days. Only that number promotes and is the headline. Old records recompute to `no_disjoint_number` |
| 2 | **Live-bar swap rule** (OPERATING-PLAN § 2 live path, item 3) | the better of two variants on the same live trades | the winner's live bar on those same trades | **Yes**, whenever the swap is used. No swap has fired yet (`LIVE_BAR_PROMOTION` in `scripts/ci/check_roster_promotion_evidence.py` is empty) | Doc (this PR): the winner's live-bar pass comes from trades disjoint from the comparison |
| 3 | **Stage-0 records, `harness_timefolds`** (`scripts/ops/build_strategy_evidence.py`) | params tuned on history (not recorded) | the leg's pooled folds over the last N days | **Cannot be shown.** The producer itself says `net_r_oos` "is not a promise that params were chosen out of sample". 54 of 58 records read `param_selection_provenance: not_established`. **8 legs on real-money or prop rosters** rest on such a record: ada_pullback_2h, slv_trend_1h, tlt_pullback_1h, tqqq_trend_long_1d, trend_donchian_eth_4h, trend_donchian_sol_4h, trend_donchian_sol_prop, trend_donchian_xrp_4h (re-parsed from `config/accounts.yaml` 2026-11-25) | Doc (this PR): a NEW promotion needs a disjoint re-measure. The legs already on a roster are not moved by the rule alone. Each gets a re-measure on data after its params last changed (row `PROMOTION-RULE-PARAM-DISJOINT`) |
| 4 | **Live bar, single leg** (`scripts/research/live_bar.py`) | nothing is chosen on the live trades; the leg was put on the book before them | the leg's trades since it began | **No**, as long as no session picks a start date after looking. Separate defect: it keys on `strategy_name`, so it pools every served model of a leg (4 for ml_entry) against "the SAME leg configuration" (row `LIVE-BAR-KEY-BY-CONFIG`) | none for this rule |
| 5 | **TEMPLATE-cell sweeps** (`queue_grade.py`) | cell selection | a fresh-window confirmation or a pre-registered holdout | **No**, already compliant (operator 2026-10-16) | none |
| 6 | **Holdout reads under `holdout_lock`** (purged walk-forward, sealed holdout read once, ledger-deflated) | dev folds | the sealed holdout | **No** | none |
| 7 | **Sub-levers measured inside the evidence window**: ml_entry `tp_revision` margin 0.05 (`comms/strategy_evidence/ml_entry.json` says it was "chosen on dev OOS trades that include this window") | the margin | delta +0.0008 R | **Yes**, but nothing promotes on it: it is +0.0008 R of a +0.0371 record | stated. The 0.0371 holds on the fixed-TP arm too (+0.0263) |

Probe check (RULE ONE). The search for "promotes on a number" was positive-tested: it found every one of the five ENTRY grade records (`comms/research/ml_entry_grade/*`) and the live-bar path. The negatives in rows 4–6 are read from the code paths named, not from absence in a grep.

## Part 2: ml_entry re-graded under the fixed rule

### 2a. The three refit swaps: none has a disjoint number

`python3 scripts/research/ml_entry_candidate_grade.py recompute --evidence comms/research/ml_entry_grade/<run>/grade_evidence.json --tag _amendment4` (records committed beside each source):

| run | promoted | grade window (chose and promoted) | cand − served | verdict under Am. 4 |
|---|---|---|---|---|
| 42250040398 | v1r20261106 | 2026-10-23..11-05 | +0.0935 | `no_disjoint_number` |
| 43710344172 | v1r20261115 | 2026-11-01..11-14 | +0.0677 | `no_disjoint_number` |
| 45021344426 | v1r20261122 (served now) | 2026-11-08..11-21 | +0.0512 | `no_disjoint_number` |

The only disjoint read registered for any refit is RQ-20261119-b9d0-02 (the v1r20261115 forward read). It is `not_before 2026-12-02` for power, so it was **not** run early: running it would have spent its holdout-ledger read off-plan.

### 2b. What disjoint evidence exists (population and provenance on every line)

| Evidence | Population | Result | Provenance |
|---|---|---|---|
| Stage-0 record that put the leg on real money (`comms/strategy_evidence/ml_entry.json`, rule RULE-RQ20261103-5E04-01, bar mean ≥ 0) | c692-01 **frozen v1** booster, sealed held-out 2025-10-01..2026-09-29, 5 bybit_2 symbols, live exit; tau chosen on dev folds 2022-01..2025-09 only | **+0.0371 R/decision, n 907** (fixed-TP arm +0.0263, CI95 −0.042..+0.099) | MEASURED, **disjoint**: still clears its registered bar |
| Recipe, refit per fold on prior rows (ML-D3-UNLOCK-20261123 `side_by_fold_summary.json`) | 60 perps, 8 dev folds 2022-01..2025-10 | +0.0030 R/decision, n 71,334, week-clustered se 0.018 | MEASURED fold means. The pooled se assumes the folds are independent (ESTIMATED) |
| same | 5 post-dev folds 2025-10-01..2026-11-21 (out-of-time, read under a ledger claim) | **+0.0034 R/decision, n 12,089, se ≈ 0.033** (fold means −0.086..+0.121) | as above |
| Frozen v1, after its training | 60 symbols, 2026-10-23..11-05 (served arm of run 42250040398) | −0.0918, n 342 | MEASURED |
| Frozen v1 forward (RQ-20261118-f7c1-08, quoted from RQ-20261119-b9d0-02) | bybit_2 symbols, 2026-10-01..11-15 | −0.058, n 118 | MEASURED (quoted, not recomputed) |
| **Live after each decision, real money** (journal pull 2026-11-25 ~19Z; R on the declared signal-time risk, `live_bar.confirmed_r_rows`; venue-measured pnl on 58 of 58) | bybit_2 ml_entry closes 2026-11-03..11-24 | **n 58, ΣR −10.90, mean −0.188, 80% LCB −0.282.** By served model: v1 4 / +0.49; r1106 31 / −3.17; r1115 15 / −5.43; **r1122 8 / −2.77 (8 of 8 losers, all on 11-24)** | MEASURED |
| same, mirror | bybit_portfolio, the same packages | r1122 8 / −3.12; all 58 track bybit_2 | MEASURED |
| Live bar as `live_bar.py` would pool it | bybit_2 + alpaca_paper ml_entry, every served model | n 83, ΣR −8.98, LCB80 −0.193 → **fail** | MEASURED |

The dispatch says "lost 5/5 real-money trades 11-24". The journal shows **8 closes on bybit_2 on 11-24, all losers** (SOL, ADA, SOL, XRP, XRP, SOL, ETH, BTC; −0.015 to −0.728 R each). No ml_entry order package was created after 2026-11-24 16:01Z, up to the pull at ~19Z on 11-25. No config change explains this (`git log` on strategies/accounts/ml/served since 11-24 is empty). Below-tau silence is the likely reason, but I did not verify it from the decision audit.

### 2c. Reading

1. **Under the fixed rule, the leg keeps its real-money record**: the c692-01 held-out year is disjoint and clears its registered bar (≥ 0). **The served artifact does not**: v1r20261122 has no disjoint number, and neither did the two refits before it. The only ENTRY artifact with a disjoint promoting number is `ml_decision_entry_v1`, the frozen c692-01 booster.
2. **Out of time, the recipe's edge is not distinguishable from zero**: +0.003 R/decision over both the dev folds and the post-dev folds. The frozen v1 was negative in both of its post-training reads since October.
3. **Live real money is negative at n 58** (ΣR −10.9). The live bar is a promotion test, not a demotion trigger, and the operator has set no automatic demotion trigger. This record is evidence, not a trigger.

## Part 3: proposal for the operator (not applied)

**Recommendation: demote ml_entry to the demo floor (`bybit_1`). This means it leaves bybit_2, bybit_portfolio and the prop rosters (tradeify_1, velotrade_1) and keeps trading on bybit_1 for data. The iteration programme continues** (the RQ-20261124/25 f1a0 arms, one-bet-per-bar e1a7-02, regime-conditioned heads). A version comes back to real money when it clears its registered rule on disjoint data.

- Why: the only disjoint number that still passes (+0.037, n 907, a CI that spans 0) was measured on a frozen booster that is no longer served. That booster's own post-training reads since October are negative (−0.092 n 342, −0.058 n 118). The recipe's out-of-time edge is +0.003 ± 0.033, and real money is at −10.9 R over 58 trades.
- Revert: re-add the leg to the rosters (one YAML edit per account). Net effect on the books: removes ml_entry's 4–5 same-bar entries at `risk_pct` 0.015 each on bybit_2.
- Tier 3 (roster change). It also changes the prop rosters, so the operator decides.

**If you keep it on real money, the fixed rule still requires one change:** repoint `ml/served/ENTRY_SERVED.json` to `ml_decision_entry_v1`, the only artifact whose promoting number is disjoint. This is a one-line pointer edit, and revert is one line. Keeping v1r20261122 served is not consistent with the fixed rule.

Your 11-24 instruction was "I don't want a demotion recommendation; I want solutions". The 11-25 dispatch asks for keep / demote / other with evidence, so this memo makes a recommendation. The solutions from the 11-24 review are unchanged and keep running on the demo floor.

## Follow-ups filed

- Row `PROMOTION-RULE-PARAM-DISJOINT`: a disjoint re-measure, on data after each leg's params last changed, for the 8 rostered legs whose records read `not_established` (Part 1 row 3). Proposal for the roster guard: a sixth clause, applied only to new promotions, that a record states a disjoint basis. **Operator's call**, because it adds enforcement.
- Row `LIVE-BAR-KEY-BY-CONFIG`: `live_bar.py` keys on `strategy_name`, not on the leg configuration or served model (Part 1 row 4).
- Row `ML-ENTRY-PROMOTE-READ-REGIME` (by-side reporting beside the replacement verdict) still stands; Amendment 4 does not replace it.

## Reproduce

Live numbers: `scripts/ops/diag_fetch.sh 'journal?table=trades&limit=1000&offset=N'` (N = 0, 1000, 2000) and `'journal?table=order_packages&...'` (4 pages), then `live_bar.confirmed_r_rows` filtered to `strategy_name == ml_entry`, grouped by account and by `meta.model_id`. The raw pulls are not committed because they hold account-level fields. Fold pooling: `comms/research/ML-D3-UNLOCK-20261123/side_by_fold_summary.json` `folds[*].refit.all`.

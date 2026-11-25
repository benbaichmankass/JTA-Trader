# Weekly walkthrough 2026-11-25

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH**. A section another lane has not landed yet is simply absent. On a collision, the later lane merges `main` first.

<!-- PERF-REVIEW-PREP:START -->
# PERFORMANCE — /performance-review 2026-11-25: real money lost 7.7 R this week and `ml_entry` caused all of it. No rule can demote it. Separately, the live-bar promotion tool counts one decision several times, and that is what makes 3 of its 7 PASS legs look like they pass

> Skill: `.claude/skills/performance-review/SKILL.md`. This run covers the scoreboard, Layer 0, CHECKS C1–C14, ANALYSIS and decisions. **C12 (backlog drain) was only partly done.**
> See §4. **`/perf-followup` was not run.** It takes §3 as input. Windows: **7 d** (rolling, since 2026-11-18T18:25Z), **30 d**, **90 d**,
> lifetime.
>
> **Merged, deployed and observed are reported separately.** All trade figures are **OBSERVED** on the live read-only API (`/api/bot/performance` windows 7d/30d/all; the
> route rejects `90d` with HTTP 400) and on the diag journal (`journal?table=trades` 8,613 rows, ids up to 8613; `journal?table=order_packages`
> 7,369 rows). Reads were taken 2026-11-25 18:25–19:10Z. Config facts are **OBSERVED on repo `main`** at `4ab9993bf`, not on the VM. This PR changes
> this document only. **It changes no config and no code.** Public repo: no balances. The $ figures are P&L only.

## S. Scoreboard

| book | 7d | 30d | lifetime | source |
|---|---|---|---|---|
| **real money** (`bybit_2` + `alpaca_live`) | **−7.68 R** / 26 (expR −0.30, WR 23.1%) · $ −16.05 (cov 1.00) · PF 0.39 · **0 TP reached** (9 SL, 17 mid-bracket) | −11.11 R / 77 (expR −0.14) · $ −28.51 (cov 1.00) | −166.4 R / 542 · $ −169.16 (cov 0.81) | `/api/bot/performance`, R basis `declaredInitial` 26/26 |
| **mirror** (`*_portfolio`) | +33.09 R / 35 · $ **−6,250** (cov 0.80). **The R figure is an artefact** (§2 Q3). Without `slv_trend_1h`: **−7.80 R** | +33.45 R / 90 · $ −4,470 | −3.2 R / 237 · $ −39,774 (cov 0.68) | same, `paperPortfolio` |
| **paper** (API `paper`, includes the mirrors) | +32.40 R / 143 (expR +0.23) · $ +26,939 (cov 0.91) | +54.53 R / 417 | −77.5 R / 2053 | same, `paper` |

**Real money this week, by leg** (perf 7d; how each trade closed comes from the journal):

| leg | n | R | $ | closes |
|---|---|---|---|---|
| `ml_entry` (`bybit_2`) | 23 | **−8.21** | −17.59 | sl 12 · live_review_close 11 · tp 0. The 5 winners were all live-review closes |
| `ada_pullback_2h` | 2 | +1.03 | +2.78 | tp 1 (+2.21 R, opened 11-15) · sl 1 |
| `trend_donchian_sol_prop` | 1 | −0.51 | −1.25 | sl |

The other 6 real-money legs (`trend_donchian_xrp_4h`, `trend_donchian_eth_4h`, `slv_trend_1h`, `tlt_pullback_1h`, `tqqq_trend_long_1d`,
`ml_entry_eq_struct`) had **0 real-money closes** this week.

**Would a sceptical quant believe each real-money leg has edge?** The table answers from the offline record net of the full cost stack, with the C13 DSR and the live bar beside it.
The live bar is counted once per decision; §2 Q2 explains why the tool's own count is wrong.

| leg (book) | offline record | DSR | live bar (tool → one R per decision) | sceptic |
|---|---|---|---|---|
| `ml_entry` | +0.037 R/trade, n 907, clustered 2–5 per bar | not computed | FAIL n141 −19.48 R (real money alone: 24 entry bars, −10.90 R, lcb −0.81) | **No.** |
| `ada_pullback_2h` | +0.40, n 67 | 0.254 | PASS lcb +0.015 → **FAIL lcb −0.001** (51 decisions, +8.36 R) | No. The edge is plausible but has not been shown |
| `trend_donchian_sol_prop` | +0.093, n 538 | 0.332 | n_short (15, −11.73 R) | No |
| `trend_donchian_xrp_4h` | +0.076, n 46 | 0.023 | FAIL (26, +1.15) | No |
| `trend_donchian_eth_4h` | +0.229, n 135 | 0.286 | FAIL (59, −0.52) | No |
| `slv_trend_1h` (`alpaca_live`) | +0.59 at 5 bps; **S26 reprice FAIL** (2/4 folds) | 0.581 | PASS +37.49 → **FAIL +5.30, lcb −0.17** | **No.** The live pass comes from double counting |
| `tlt_pullback_1h` (`alpaca_live`) | +0.109 at 5 bps; **S26 reprice FAIL, −26.24 R, 0/4 folds**; 8-year window PASS at its own cost | **0.005** | n_short (16, −5.87) | **No.** |
| `tqqq_trend_long_1d` | +0.236, n 54 | 0.533 | n_short (1) | No. It is a mechanics probe |
| `ml_entry_eq_struct` | +0.49, n 207 (the record cites an Actions URL) | not computed | n_short (5, −0.04) | No |

No real-money leg would convince a sceptic. All of them are on real money by operator decision. **No leg currently clears the live bar when each decision is counted once.**
Only the paper legs `trend_donchian`, `trend_donchian_ada_4h`, `trend_donchian_sol_4h` and `e4_oi_shock_1h` do.

---

## 0. Prior calls (Layer 0)

| # | call (p) | check re-run now | result | did the action happen? |
|---|---|---|---|---|
| G1 | a per-bar cap cuts `ml_entry` drawdown without cutting net R (0.6) | RQ-20261118-f7c1-01 graded on the 907 record | **hit** on the rule as written: k=2 net +54.09 vs +33.68 R, maxDD 41.07 vs 62.81 (≤ 0.8×). But the gain is inside noise (diff CI [−21.3, +61.2]), forward f7c1-08 is INDETERMINATE (18 bars < 30, point estimate *against*), and top-1-per-bar e1a7-02 is INDETERMINATE (t 0.26) | yes (units ran). The cap stays off |
| G2 | at 26 bps, ≥ 1 of the 4 `alpaca_live` records goes ≤ 0 (0.5) | f2a4-05/06/07 results | **hit**: `tlt_pullback_1h` S26 **net −26.24 R, 0/4 folds**. `slv_trend_1h` S26 net +25.55 R but 2/4 folds (FAIL on the fold rule). `tqqq` not_applicable | **No.** The Tier-3 proposal it required was not filed. Carried forward as **PI-20261125-PREP1125-0002** (§3 D2) |
| G3 | C2's i.i.d. band is too narrow for clustered legs (0.8) | `live_vs_backtest.py --leg ml_entry --block-by-entry-bar` | **hit**: `n_entry_bars` is printed. `n_touched` is printed as null, with the stated reason that the route carries no close reason. The block band widens p5 from −8.57 to **−12.42 R** at n=27 | yes (#27186). PI-…-0004 closed this run |
| G4 | cross-book same-direction concentration predicts drawdown clustering (0.55) | perf-followup Track 4 | **unresolved**. On the backtest population it is not supported (ρ +0.118 goes with *better* next-24h R, descriptive). The pre-registered live-journal read has not run | partly. PI-…-0002 stays open |
| G5 | on a shallow clone, live_vs_backtest gives verdicts silently (0.9) | code read: #27050 | **unresolved**. It now *warns*. The rule asked for "deepen or non-verdict", and a warning is neither. Not re-run on a shallow clone | partly. PI-…-0005 noted |
| G6 | `hold_vs_close` has a denominator bug (0.85) | `live_review_grade.py --live --since 11-18T19Z --json` | rule reads **fixed** (hold mean 1.10, n20; per-version 1.13). But no grader fix is visible in git since 11-18, so this may just mean there were no bad rows | kept open one week |
| G7 | `slv_trend_1h` is not below its backtest (0.8) | `live_vs_backtest.py` (full-history clone) | mirror **ABOVE_BACKTEST** n10 +43.29 R pct 100: **hit by the rule** (not BELOW). **The read is an artefact**: 7 of the 10 rows are fragments of one decision (§2 Q3) | — |

`review_followthrough.py --source performance-review --window-days 7`: 15 filed in the last 7 d, 2 done, 0 killed, 13 open (13% closed within 7 d). Backlog: **34 open, 71%
due, median age 13 d**.
*Footer (housekeeping, not a health measure):* 7 calls · hit 5 (G1, G2, G3, G6, G7, each with the caveat above) · unresolved 2 · miss 0 · void 0 · Brier
**INDETERMINATE** (5 resolved < 10). Series of resolved calls: 10-28 1 · 11-04 1 · 11-11 2 · 11-18 5 · 11-25 5.

---

## 1. CHECKS (numbers only)

**C1 — per-leg scorecard, four windows.** Real money. R and $ come from `/api/bot/performance` (declared-initial R). The **90 d column comes from the journal ($ and n only)**
because the route rejects `window=90d`, so 90 d R is `could_not_look` from the route.

| leg | 7d n / R / $ | 30d n / R / $ | 90d n / $ (journal) | lifetime n / R / $ (cov) |
|---|---|---|---|---|
| `ml_entry` | 23 / **−8.21** / −17.59 | 59 / −9.84 / −27.49 | 59 / −27.49 | 59 / −9.84 / −27.49 (1.00) |
| `ada_pullback_2h` | 2 / +1.03 / +2.78 | 4 / +4.80 / +14.15 | 15 / +6.25 | 21 / +0.47 / −6.00 (1.00) |
| `trend_donchian_sol_prop` | 1 / −0.51 / −1.25 | 4 / −2.63 / −7.13 | 6 / −13.09 | 6 / −4.58 / −13.09 (1.00) |
| `trend_donchian_xrp_4h` | 0 | 3 / +0.40 / +1.39 | 5 / −6.66 | 10 / −0.54 / −6.73 (0.70) |
| `trend_donchian_eth_4h` | 0 | 3 / −1.55 / −4.34 | 13 / −26.56 | 19 / +4.66 / +4.71 (0.68) |
| `ml_entry_eq_struct` | 0 | 1 / −0.11 / −0.34 | 1 / −0.34 | 1 |
| `tlt_pullback_1h` | 0 | 0 | 1 / +0.55 | 1 / +1.29 / +0.55 (0.00) |
| `slv_trend_1h`, `tqqq_trend_long_1d` | 0 | 0 | 0 | 0 real-money closes |

**R per capital-day and giveback** (operator headline measures). Source: `giveback_census.py` on real-money journal rows filtered by `closed_at`, with the
position-telemetry dump (1,000 rows). **Lifetime is `could_not_look`**: telemetry covers only the newest 1,000 positions.

| window | real-money pooled n | net R / capital-day | peak R p50 | realised R mean | giveback R mean | giveback ÷ peak |
|---|---|---|---|---|---|---|
| 7 d | 26 | **−0.457** | 0.43 | −0.17 | 1.03 | 1.20 |
| 30 d | 73 | −0.137 | 0.45 | −0.08 | 0.91 | 1.09 |
| 90 d | 107 | −0.153 | 0.50 | −0.12 | 1.01 | 1.14 |

Per leg, 30 d: `ml_entry` n58, −0.457 R/cap-day, giveback share 1.16 · `ada_pullback_2h` n4, **+0.313** · `trend_donchian_xrp_4h` n2, +0.516 ·
`trend_donchian_sol_prop` n4, −1.746 · `trend_donchian_eth_4h` n2, −0.599. Giveback ÷ peak above 1 means that, on average, more was given back than the
peak gain: trades went green and then closed red.

**C2 — expected vs realised** (`live_vs_backtest.py`, default config cut, full-history clone):

| leg | real money | mirror | cut |
|---|---|---|---|
| `ml_entry` | **CONSISTENT** n27 −6.51 R pct 10.2 (block band: pct 19.7, p5 −12.42) | CONSISTENT n27 −6.70 pct 9.6 | 11-15T13:21Z |
| `ada_pullback_2h` | INSUFFICIENT_N n3 +3.91 pct 75.0 | same | 11-06 |
| `trend_donchian_xrp_4h` | INSUFFICIENT_N n2 +0.60 pct 62.4 | same | 11-06 |
| `trend_donchian_sol_prop` | INSUFFICIENT_N n2 −1.25 pct 36.8 | same | 11-06 |
| `ml_entry_eq_struct` | INSUFFICIENT_N n1 −0.11 | INSUFFICIENT_N n4 +0.07 pct 18.9 | 11-17 |
| `slv_trend_1h` | NO_LIVE_TRADES | **ABOVE_BACKTEST n10 +43.29 R pct 100 (artefact, §2 Q3)** | 11-12 |
| `trend_donchian_eth_4h`, `tqqq_trend_long_1d`, `tlt_pullback_1h` | NO_LIVE_TRADES | NO_LIVE_TRADES | 11-13 … 11-15 |

**C3 — decay (interim, no sequential instrument; row `PERF-CHECKS-SCORECARD`).** Real-money expR: 7 d −0.30, 30 d −0.14, lifetime −0.31.
For `ml_entry` (bybit_2 per entry bar, declared R), the 11 bars since 11-15 sum to −5.43 R, 6 of them losing. Every other leg has ≤ 3 post-cut closes.

**C4 — attribution.** Real-money closes in the 7 d window (journal, n=26): **sl 14, live_review_close 11, tp 1**. There were 0 reconciler, 0 operator and 0 watchdog closes. **Claude in-trade closes were 11 of 26.** The 2026-11-24 ml_entry review
(`docs/research/ml-entry-review-2026-11-24.md`) measured the whole flow on 26 closes: untouched bracket −16.94 R against −5.79 R realised. Active management
**added about 11 R**, so the loss sits at the signal stage.

**C5 — cost drift.** `realized_slippage.py` was **not re-run** this week (see §4), so last week's figures are not carried forward. The cost question is answered by
G2's reprice units (C2 row above, §2 Q4).

**C6 — baselines.**
- **Live review** (`live_review_grade.py --live --since 11-18T19Z`): 45 reviews on 27 packages, against 155 the week before. 11 altering calls, **2 priced**, 9 could
  not be priced (no_candles 7, replay_mismatch 2). Applied close: n2, mean dR **−0.54**, worst −1.36. Applied alarm: net dR −1.08 over 2 (rule needs ≥ 20).
  hold_vs_close (ESTIMATED): n20, mean +1.10. Hold calibration: UNDERCONFIDENT (n13). Every use rule: HOLD_SCOPE (0 packages).
- **Desk** (`desk_grade.py --live --since 11-18T19Z`): 9 decisions (5 propose_entry, 4 no_trade). 5 were priced: mean **+1.16 R**, CI95 [+0.21, +2.11]. Desk minus random +0.38 R
  [−1.09, +1.85]. Desk minus system +1.59 [+0.76, +2.42] against system closes over the same window (n40, mean −0.43). All of these are **INDETERMINATE (n=5 < 30)**.
- **Per role** (`claude_role_grade.py --live`): output is in the lane scratch. No row reached its gate n this week.

**C6b — LTR grade freshness** (`attention_watch.probe_ltr_grade`): **ok**. All 23 applied live-review close packages older than 24 h are graded.
The probe does not measure prop closes or the grader's run age.

**C7 — TP doctrine** (re-run): compliance by class is **real money 2/9** (`ml_entry`, `trend_donchian_eth_4h`), mirror 2/9, prop 4/6, paper 4/61.
Among the real-money legs, `trend_donchian_sol_prop` has an unreachable TP (6 R, reach 0.019) and fails tp_revision, and the other 6 fail tp_revision. TP-REACH floor: 4 below, 9 reachable,
45 unmeasured out of 58.

**C8 — data coverage.** `classify_paper_records.py` was **not run** (§4). `journalTrust`: read; `accountsKnownDivergent: ['bybit_2']`,
`accountsUnrecorded: []` (last week `alpaca_live` was unrecorded, so that has cleared). Journal R-basis coverage for real-money 7 d: 26/26 declared-initial.

**C9 — grading.** Fresh: newest `reviewed_at` 2026-11-25T04:13Z, 0.6 d old, against a 3 d limit, over 4,844 rows. The grade-vs-outcome cohort table was **not recomputed** (§4).

**C10 — research pipeline** (`research_disposition.py --unread-only`): dispositioned 154, **unread 21** (last week 20), superseded_unread 299,
corpus_unreadable 0. All of them are e35 results, most `accruing`. Research-ops owns these.

**C11 — books.** Paper-book tracker: **not appended this week** (§4). Real-money allocation benchmark: not computable. Prop trade quality: not run.

**C12 — backlog gate.** There were 34 open performance-review records at the start. **7 were re-checked** (the 7 open PREP1118 items: 1 closed done
[PI-…-0004], 6 noted with this run's observation). **count_untriaged = 27. C12 is INCOMPLETE** (§4).

**C13 — DSR probation** (`dsr_probation.py`): 9 production legs, 7 on probation, 2 not computed. **Iteration orphans (NO LIVE UNIT):
`tlt_pullback_1h` (DSR 0.005, 2nd week)** and `ml_entry_eq_struct` (not computed, 3rd week). Note that RQ-20261119-e11f-02 is a `tlt_pullback_1h` unit that ran
and **PASSED**, yet the ledger does not list it as a live unit for the leg.

**C14 — counterfactual CHECK table** (`cf_bulk_live.py run` + `cf_check_table.py`): 1,033 of 2,789 closed packages graded. Not graded: no_filled_leg 646, pairs
716, non-crypto 209, legs_not_closed 123, horizon 62. **Fidelity FAIL overall: 31.9% of packages are within 0.1 R** (n 1,028; median abs gap 0.286 R). Every leg is
`ESTIMATED_LOW_FIDELITY`, so **no counterfactual arm is read as a result.** Among the real-money legs, `ml_entry` (n47, fidelity 51%) shows actual −0.059 against replay −0.265 R/package, which
fits management helping. Its best arm, alt_sl0.75x_tp6R (+0.52, CI [+0.002, +1.06]), is the best of 27 arms in-sample: a lead, not a result.

---

## 2. ANALYSIS

I looked at 9 real-money legs closely and 15 legs on the live bar. At 5%, about 1 of them would look unusual by chance.

### Q1 — Judge `ml_entry`, which has no demotion trigger *(operator flag 11-24; real money; −8.21 R of the book's −7.68 R this week)*

**What the record says.** Offline it is +0.037 R/trade over n 907, with trades clustered 2–5 per bar, so the effective n is well below 907 and the 95% CI includes 0.
DSR is not computed. On real money it has made 58 trades with declared R over **24 entry bars, ΣR −10.90**, a per-bar mean of −0.454 and an 80% lower bound of −0.81. Pooled across
all accounts it has 141 trades, ΣR −19.48, and FAILS the live bar. This week it made 23 closes with **0 take-profits**: 12 stops, and 11 live-review closes that included all 5 winners.
**On 2026-11-24 it made 8 real-money closes from 3 entry bars (00Z, 04Z, 12Z), and all 8 lost**: 4 stops and 4 live-review closes, −2.78 R on the declared basis.
(The operator counted 5/5. I count 8 closes and 3 bars from the journal, and I cannot reproduce a population that gives 5.)

**Why no rule fires.**
- **C2 cannot fire.** A +0.037 R/trade record has a band that holds large losses: at n=27 the entry-bar block band is p5 **−12.42 R**, so −6.51 R reads
  CONSISTENT (pct 19.7). On this record the leg would need roughly −13 R inside 27 trades before C2 said BELOW. **C2 is the wrong demotion signal for a
  near-zero-edge clustered leg.** It can only ever say "luck-sized".
- **The live bar is a promotion test, not a demotion test.** Failing it changes nothing for a leg that is already on real money.
- **The operator said on 11-24: "I don't want a demotion recommendation… I want solutions."** The ml_entry review ranked those solutions:
  one bet per bar (e1a7-02, **INDETERMINATE**, t 0.26), regime inputs (e1a7-01, producer failed, partial read negative), book features (row), and a
  target lever (f1a0-33, queued). **Not one of them has passed yet.**

**Hypotheses for this week's −8.2 R:**
- *H-noise:* about 9 independent bars this week (23 trades), so −8.2 R is about −1.5 SD per bar. **Survives** (C2 pct 10–20).
- *H-regime:* the model trades against BTC's last 24 h in high vol, as the 11-24 review found (H5, SHAP). It predicts that this week's losing bars ran
  against the tape: the 11-20 16Z, 11-22 08Z and 11-24 12Z bars lost −2.2, −4.1 and −2.1 R. **Consistent; the 11-24 review already measured this.**
- *H-execution:* fills came in better than the reference (−0.04 R) and management added about 11 R. **Eliminated.**
- *H-model swap:* v1r20261122 has served since 11-24 00Z. Its 3 bars (−2.78 R) are too few to separate from noise.

**The finding is the missing trigger, not the week.** This is a near-zero-edge leg on real money. Its only automatic demotion signal (C2) cannot fire, and no
fix has passed. **p = 0.85** that without a trigger it stays on real money through December whatever its live R does. **Money:** at its 30 d rate (−9.84 R
over 59 closes) that is about −10 R a month on real money, and more again on the mirror and the prop legs (tradeify, velotrade), which take the same packages. → **D1**
(operator decision, a *rule* rather than a gate).

**The grade-window issue, part 1 (operator 11-25).** The ml_entry *model swap* rule (RULE-ENTRY-PROMOTE-20261106) promotes a retrain on its
**14-day grade window**. The promoted v1r20261122 read +0.146 on aggregate in that window, with the long side at −0.526 (n220) and the short side at +0.836. **That is a promotion that rests on
a number measured only over the grading window.** The operator's 11-25 fix must cover this rule, or record it as exempt. → **D1**.

**Also: since 2026-11-24 12:03Z ml_entry has emitted 0 crypto packages on any account** (about 30 h by 18:30Z; the only package is one alpaca_paper USO).
The config is live. The cause has not been read. → **D4** (health).

### Q2 — Which promotion cases rest on numbers that are inflated or measured only in the grading window? *(operator 11-25)*

**The live bar (`scripts/research/live_bar.py`, feed `comms/live_bar/latest.json`) counts rows, not decisions**, in two ways:
1. **Per account.** It pools the demo floor, mirror and real money "of the same leg", so one signal traded on `bybit_1`, `bybit_portfolio` and `bybit_2` counts 3 times.
2. **Per fragment.** The repeated-entry defect (PI-20261118-JFWRQYOV-0004) re-emits a package every ~7 minutes, and each fragment counts as a trade.

I re-scored every PASS leg and every real-money leg with **one R per decision** (symbol, side and 3 h entry bucket; R averaged across accounts):

| leg | tool | one R per decision | change |
|---|---|---|---|
| `slv_trend_1h` (real money) | PASS n37 +37.49 lcb +0.60 | **FAIL n25 +5.30 lcb −0.17** | the 11-18 short alone gives 7 fragments at ~+6.2 R each (+43.2 R) |
| `ada_pullback_2h` (real money) | PASS n82 +12.55 lcb +0.015 | **FAIL n51 +8.36 lcb −0.001** | 3 accounts pooled |
| `ict_scalp_sol_15m` (paper) | PASS n55 +11.04 lcb +0.015 | **FAIL n51 +8.29 lcb −0.033** | 4 fragment rows |
| `trend_donchian` | PASS n46 | PASS n29 +32.12 lcb +0.63 | holds |
| `trend_donchian_ada_4h` | PASS n37 | PASS n35 +12.16 lcb +0.18 | holds |
| `trend_donchian_sol_4h` | PASS n28 | PASS (unchanged) | holds |
| `e4_oi_shock_1h` | PASS n48 | PASS (unchanged) lcb +0.021 | holds. The committed feed of 11-24 read it as FAIL n42; it crossed the line this week |

- *H-tool-correct* (each account is an independent observation): a mirror trade **is the same market decision** at a different size. Its outcome can
  differ, because each account's in-trade management differs. On the 32 `ada_pullback_2h` / `trend_donchian` packages held on more than one account, the median R gap is
  0.155 and the largest is 11.3. So the copies are correlated draws of one entry decision, not independent evidence that the signal has edge. **Eliminated** as a
  reading of the n. Averaging R across accounts per decision keeps the management effect and drops the duplicate count.
- *H-ambiguous bucket* (the 3 h bucket merges two genuine decisions): it would predict merges on 4h/1d legs, where bars are ≥ 3 h apart. `trend_donchian_sol_4h` and `e4` lose
  0 rows, so the bucket is not merging distinct bars there. For 15m legs it could merge real re-entries, which would make my count **conservative** for `ict_scalp_sol_15m`. **p = 0.9**
  that the 3 flips are real.

**Grade-window legs, named:**
- **`slv_trend_1h`** (real money since 11-12). Its live record looks strong only because of duplicates. Its offline record fails the measured-cost reprice on folds. **Every** number
  in favour of it is either inflated or measured at 5 bps.
- **`ada_pullback_2h`** (real money). Its live pass depends on pooling. Its promotion rested on Stage-0 (n 67), not on the live bar, so nothing it rests on is
  window-only, but the live bar cannot be cited for it.
- **`ict_scalp_sol_15m`** (paper). The feed lists it as PASS, so it is a live-path promotion candidate, and on one R per decision it fails. Its sibling
  `ict_scalp_eth_15m` was promoted on the same path on 11-17 and reverted on 11-19 after its fidelity unit FAILED.
- **`ml_entry` model swaps.** These rest on a 14-day grade window (Q1).
→ **D3** (tooling fix to the live bar, which feeds the operator's promotion-rule fix).

### Q3 — Why does the mirror read +33 R this week while it lost $6,250? *(measurement)*

`slv_trend_1h` mirror 7 d: **+40.89 R over 9 rows, $ −1,094**, with rProvenance *contaminated* on 7 of the 9. The 2026-11-18 SLV short entered as 7 packages of 794 / 53 / 19 / 5
/ 2 / 2 / 2 shares. Each scores about +6.2 R on its own size, so a single +6 R decision becomes **+43 R**. Without the leg the mirror's 7 d R is **−7.80**, the same sign as
real money. The four SLV decisions since the 11-12 cut, on stored-stop R (ESTIMATED), are **+1.02, +1.82, −1.34, −1.02**. C2's ABOVE_BACKTEST pct 100 is the same rows.
Last week this review concluded that the defect "does not distort R" because the null-PnL repeat rows drop out (Q4 of 11-18). **That was wrong for the
fragments that did fill and close at TP.** → **D5**.

### Q4 — Do the Alpaca real-money legs survive their measured cost? *(G2; real money)*

- **`tlt_pullback_1h`.** S26 on the 2025-06 → 2026-11 window: **net −26.24 R, 0/4 folds** (f2a4-07). The same declared config on a **disjoint 8-year
  window**: **PASS, net +51.19 R, 4/4 folds**, but at that arm's own cost stack, not at 26 bps (e11f-02). *H-cost* predicts that the 8-year window also fails at
  S26. *H-regime* predicts that it passes, which would make the one-window FAIL the 2025–26 regime. **One cheap unit separates them.** The data leaves the demotion open
  on exactly that point, so **file the unit; no popup** (canonical § Data-backed decisions). DSR 0.005, live 16 trades pooled at −5.87 R.
- **`slv_trend_1h`.** S26 net +25.55 R, but only 2/4 folds (FAIL on the fold rule), and its live case is the Q2/Q3 artefact.
- **p = 0.6** that `tlt_pullback_1h` also fails at S26 on the 8-year window. **Money:** the account is tiny in dollars. The risk is a real-money leg with no edge at
  its true cost. → **D2**.

### Surprises (A4)

1. **The live bar double counts** (Q2). I found it because `slv_trend_1h` showed +43 R from 10 trades.
2. **Live-review activity fell by 3.4×** (155 reviews down to 45) while real money had its worst week of the month. Only 2 altering calls were priced, mean −0.54 R. With n=2
   this is not a finding about skill. The volume drop is unexplained and goes to the manager in the report line.
3. **`ml_entry` went silent after 11-24 12Z** (Q1, D4).
4. **The desk beat the system by +1.59 R** over 5 priced proposals, CI [+0.76, +2.42]. At n=5 against a gate of 30 this is a lead, not a result.
5. **`alpaca_options_paper` rows for `slv_trend_1h`**, including an adopted SLV put orphan (journal 8613, 11-25), sit inside the leg's live-bar population. An options
   book is not the same leg configuration. This is folded into D3.

---

## 3. Decisions (ranked by money; each carries a pre-registered check)

| # | call (p) | decision · tier | pre-registered check | ending · due_by |
|---|---|---|---|---|
| **D1** | `ml_entry` has no working demotion trigger and will stay on real money whatever its live R does (0.85). Its model swaps promote on a 14-day grade window | **operator decision**: grant, amend or refuse a demotion *rule*: "ml_entry leaves real money for the demo floor when, counted per entry bar on real money since the served model's promotion, n_bars ≥ 20, ΣR < 0 and lcb80 < 0". On today's numbers it fires (24 bars, −10.90 R, lcb −0.81). Also place RULE-ENTRY-PROMOTE-20261106 inside the 11-25 promotion-rule fix · Tier 3. **Gates this adds or changes: one demotion rule, only if the operator grants it** | next review: the trigger is recorded (granted, amended or refused), and the per-bar live bar is re-run | **PI-20261125-PREP1125-0003** (ask_operator) · due **2026-11-26** (Thursday planning) · roadmap L-ML-LIVE |
| **D2** | `tlt_pullback_1h` fails at S26 on the 8-year window too (0.6) | unit: re-run e11f-02's arm at S26/S53 · T1. If it fails, the next review files the demotion proposal with the diagnosis block (cause = cost) | rule registered before the run: PASS iff S26 net R > 0 and ≥ 3/4 folds, n ≥ 39 | **PI-20261125-PREP1125-0002** → perf-followup · due **2026-12-02** · L-LADDER |
| **D3** | the live bar counts accounts and fragments as decisions; 3 of 7 PASS legs flip to FAIL when each decision counts once (0.9) | tooling fix to `live_bar.py` (count decisions, print n_rows beside n_decisions, exclude options books, add a test, regenerate `latest.json`) · T1 · adds no gate | `live_bar.py --json` prints `n_decisions`. `slv_trend_1h` reads FAIL, or n_decisions ≤ 25 | **PI-20261125-PREP1125-0001** → manager assigns · due **2026-12-02** · L-LADDER |
| **D4** | `ml_entry` has been silent since 11-24 12Z (0 crypto packages in about 30 h) for a nameable reason (0.7) | health read of the decision log · T2 read | the cause is named (predictions below tau, or a defect) | **PI-20261125-PREP1125-0004** → health-review · due **2026-11-27** · L-ML-LIVE |
| **D5** | `/performance` and C2 sum repeated-entry fragments as separate R (0.95) | tooling · T1 | the route either collapses or flags fragment rows; mirror 7 d R moves within ±10 R of the ex-SLV figure | **PI-20261125-PREP1125-0005** → manager (with D3) · due **2026-12-02** · L-LADDER |
| — | carry G1 (forward cap read) | no action, because f7c1-08 binds at ≥ 30 forward bars | — | PI-20261118-PREP1118-0001 (noted) |
| — | G6 | no action, because the rule reads fixed but the cause is unconfirmed; one more week | — | PI-20261118-PREP1118-0006 (noted) |

**No Tier-3 change is enacted, and no demotion is proposed this week.** D1 is a rule for the operator to decide, as their 11-24 instruction requires. D2 can produce a
proposal next week. **Premortem on D1:** suppose the trigger fires, the regime turns, and the leg would have made money. That is why the trigger counts **since the served model's
promotion**, so a new model that passes offline gets a fresh count. It also leaves the leg trading on the demo floor, so its data keeps accruing (OPERATING-PLAN § 2,
"demotion stops at the floor"). **Premortem on D3:** deduplicating could merge two genuine 15m re-entries. That is why the check also prints n_rows, so the
merge stays visible.

`/perf-followup` hand-off: D2 is a Track 1 input. Q1's open question goes to Track 1 / ml-review: which fix passes first, e1a7-02 forward or f1a0-33.

**Proposal → row/unit → due_by**

| proposal | row / unit / decision | due_by |
|---|---|---|
| ml_entry demotion rule + the swap rule inside the 11-25 promotion-rule fix | PI-20261125-PREP1125-0003 (operator decision via the manager) | 2026-11-26 |
| tlt_pullback_1h at S26/S53 on the 8-year window | PI-20261125-PREP1125-0002 → perf-followup unit | 2026-12-02 |
| live bar counts decisions | PI-20261125-PREP1125-0001 | 2026-12-02 |
| ml_entry silence read | PI-20261125-PREP1125-0004 (health-review) | 2026-11-27 |
| performance route and C2 fragment handling | PI-20261125-PREP1125-0005 | 2026-12-02 |

## 4. Not done

- **C12 backlog drain is incomplete:** 27 of 34 open records were not re-checked this run. The 7 PREP1118 items were.
- **C5** `realized_slippage.py`, **C8** `classify_paper_records.py`, the **C9** grade-vs-outcome cohort table, the **C11** paper-book tracker append and prop
  trade quality were all not run. This was a matter of budget and order: the time went to Q1–Q3.
- **90 d R** per leg: the route rejects `window=90d`. The journal gives 90 d n and $ only.
- **Machine record** `comms/reviews/performance-review-20261125-*.json`: not written this run. The calls and checks above are the record. The next review grades
  them from this section.
- No blind-then-reveal grades, no M13 insights cross-check, and no Claude-channel ping. The manager is the reporting path.
<!-- PERF-REVIEW-PREP:END -->

<!-- PRACTICE-REFRESH:START -->
# PRACTICE REFRESH: the system learns regime but not trades, a cost gap is now measured, and two MGC legs on IB paper are rejected by the venue today

> Lane `PRACTICE-REFRESH-20261125` (Tier 1, read-only). Full record: [`docs/research/practice-review-2026-11-25.md`](../research/practice-review-2026-11-25.md).
> Canonical list revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
> Live reads 2026-11-25 ~18:20–18:30Z, direct HTTPS to the read-only API. **Nothing was queued or changed; every gap is a proposal.**

**TRADING:** 5 sources read (abstract or summary level), plus our own 3 graded units.
- **T3** is strengthened by our own measurement: the recorded cost understates the +1 h markout cost by **+3.78 bps/fill**, CI [+0.36, +7.34],
  n = 2,375 fills (paper and real money pooled; the real-money slice alone is indeterminate).
- **T15** is qualified by our own registered results: a pre-release book flatten **FAILED** (0/6 folds, 0/200 random controls), and decision > minutes
  on 5/5 symbols.
- **T2/T9** noted: practice picks the exit family by holding period.

**MODEL:** 4 new sources (abstract level).
- **M3** strengthened: leakage is a degree measured one switch at a time. Centered features and same-bar-open execution are the big
  inflators, and LLMs carry parametric look-ahead.
- **M5** strengthened: run the whole workflow on a synthetic null first.
- **M14** noted: one more self-reported LLM-trading gain.

**(a) Demo-floor data generation.**
- Population: 58 rostered leg × floor-account cells, journal fills 11-18T18:26Z → 11-25T18:26Z.
- **29/58 cells filled, 97 fills in all**: `bybit_1` 25/29 cells, `alpaca_paper` 3/18, `ib_paper` 1/11.
- The 29 quiet cells:
  - **4 blocked**: `ib_paper` MGC rejected by IBKR (`status=Inactive`, 73 today); `ml_entry_eq` sizing; the desk not trading either paper venue.
  - **3 quiet by design**: holding a position.
  - **22 cannot tell**: no eval line.
- 491 refusals, of which 347 are `bybit_1` slice-budget policy holds.

**(b) Is it learning?**
- Population: 100 trainer-registry rows (mirror 32 s old), the 11-25 build cycle, and the 7-day learning ledger.
- **24/100 models trained and scored, all of them regime or setup heads; 0 trade-decision models.**
- Teacher data: desk and live-review rows are produced and labelled, and the 1,511-row `claude_judgments` set is built daily. **Consumed: 0 all-time.**
- `review_journal`, `cross_asset`, `forecasts` and `macro` build 0 rows. `exit-policy-v1` has been untrained for 121 days.

## Gaps for Thursday

| # | Track | Gap | Proposal | due_by / decision |
|---|---|---|---|---|
| TG1 | TRADING | Harness cost stacks omit the measured markout term (T3) | Row `COST-STACK-MARKOUT-TERM`, report-only beside the current net. Close `MARKOUT-HARNESS` and `EVENT-SPAN-HISTORY` | 12-02; **operator** on making it the grading basis |
| TG2 | TRADING | The calendar weights FOMC minutes like a decision, and the 12-09 decision is timed 30 min late (T15; evidence now in) | `CALENDAR-FOMC-RELEASE-SPLIT` (Tier 2) | **operator OK before 12-08** |
| TG3 | TRADING | `ib_paper` MGC: 73 IBKR `status=Inactive` rejects today; 2 legs make no floor data | Owned by row `IB-MGC-INACTIVE-1125` (lane dispatched 18:35Z); evidence: 73 rejects | in flight |
| TG4 | TRADING | 22/58 floor cells cannot be classified | Raise `FLOOR-LIVENESS-CHECK` + `AUD-20261028-DEMO-FLOOR-NO-EVAL` | manager |
| TG5 | TRADING | 286 slice-budget re-emissions for 79 `bybit_1` fills | Note on `NETTED-SLICES`: log once per held slice per bar | 12-02 |
| TG6 | TRADING | `DESK-PAPER-ACCOUNTS` unproven for five refreshes; `VERDICT-LEFT-TAIL`, `DESK-REPEATABILITY` idle | Raise | manager |
| MG1 | MODEL | No one-switch execution-convention audit (t+1 open vs current) on the daily harnesses (M3) | Unit, rule registered first | 12-02 |
| MG2 | MODEL | `ml_bakeoff` never runs on a null (M5) | Row `ML-BAKEOFF-NULL-ARM` | 12-09 |
| MG3 | MODEL | Pre-cutoff teacher labels may train a student on memorized outcomes (M3, S91) | Note on `CJ-7-BACKFILL-SCOPE` + a pre/post-cutoff teacher-skill unit | 12-09 |
| MG4 | MODEL | Learning chain broken at H3/H4 for every trade-decision source, unchanged since 11-13; 4 zero-row families; `exit-policy-v1` | Raise `DESK-LABEL-JOIN`, `ML-LEDGER-COULD-NOT-LOOK`; row `ML-ZERO-ROW-FAMILIES` | 12-02 |
| MG5 | MODEL | `RESEARCH-TRIAL-CENSUS`, `PERF-FOLLOWUP-DEFLATION` idle since filing | Raise | manager |
<!-- PRACTICE-REFRESH:END -->

<!-- ML-FRONTIER-PREP:START -->
# MODEL track — /ml-review 2026-11-25: the real-money ML entry model `ml_entry` lost 9.8 R over its first 59 live trades, and the only number that put it on real money was measured on the same window that graded it

Lane `ML-FRONTIER-PREP-20261125` (dispatched by Manager Session 2026-11-25a). It runs `/ml-review` and `/frontier-research`.
It queues no new units: every proposal below is labelled **MODEL** or **TRADING** and mapped to a row, a unit or a named decision
(§ 3). The practice refresh is the sibling lane's job and is not repeated here.
Records: `comms/reviews/ml-review-20261125-200000.json` · `comms/ml-plan/20261125T2000Z-ML-FRONTIER-PREP.json` ·
[`docs/research/frontier-scan-2026-11-25.md`](../research/frontier-scan-2026-11-25.md).
Gates this adds or changes: none.

**Assessment: `investigate`.** The trainer cannot gate-check any of the 8 models that change orders, because none of them has a
trainer registry entry (C1). Serve parity for the real-money ML legs could not be read (C5).

## S. Scoreboard

Source: `GET /api/bot/performance?window=7d|30d|all`, read about 18:40Z. R is on the declared signal-time risk (`rCoverage` 1.0 on
every block below). $ figures are left to the PERFORMANCE section, which owns the book scoreboard.

| book | 7d trades · ΣR | 30d trades · ΣR | lifetime trades · ΣR |
|---|---|---|---|
| real money | 26 · **−7.68** | 77 · −11.11 | 542 · −166.38 |
| mirror (`paperPortfolio`) | 35 · +33.09 | 90 · +33.45 | 237 · −3.19 |
| paper (all) | 144 · +31.89 | 418 · +54.02 | 2,054 · −78.05 |

**The ML legs inside those books** (same source):

| leg | book | trades · ΣR · R/trade | would a sceptical quant believe this leg has edge? |
|---|---|---|---|
| `ml_entry` (Foxhound-1, D3 + Labrador-1b TP revision, D7) | real money (`bybit_2`) | 7d **23 · −8.21** · −0.357; lifetime 59 · **−9.84** · −0.167 | **No.** Stage-0 is +0.0371 R/trade over n=907 (iid t ≈ 1.03; no clustered se; DSR cannot be computed because no per-trade series is readable). It was measured on the held-out window that also graded it. See § 2 Q1. |
| `ml_entry` | mirror | 59 · −9.33 | same model as above |
| `ml_entry_eq_struct` (Foxhound-4, D3) | real money (`alpaca_live`) | 1 · −0.11 | **Marginal.** Stage-0 is +0.492 R/trade over n=207 with day-clustered t 2.06. The trial ledger has `param_selection_provenance: null`, so the same window question applies. |
| `ml_entry_v2` (Foxhound-2) | paper (`bybit_1`) | 30d 24 · −8.59 | No. It already failed W1 (−0.116 vs −0.041). |
| `ml_entry_eq` (Foxhound-3) | paper (`alpaca_paper`) | 30d 6 · −4.77 | No (the struct model beat it). |
| `trend_donchian_xrp_4h` under Beagle-1 reduce (D4) | real money | overlay resized 1 trade in the joined window | Yes on its record (V2 rule; blind holdout n 105, dR +0.033 per `config/overlay_policy.yaml`). The live read is n=1, which is mechanics only. |

This week `ml_entry` lost **8.21 R, more than the whole real-money book's 7.68 R**: the other real-money legs netted +0.53 R.

## 0. Prior calls (Layer 0)

Follow-through (`review_followthrough.py`, 3,059 pipeline items + 2,079 checklist rows): **ml-review**: 2 filed in the 7d cohort, 0
closed; backlog 14 open, 86% due, median age 36 d, 0 with no owner. **frontier**: 9 filed, 1 done; backlog 42 open, 93% due,
median 13 d, **6 with no owner**.

| call (2026-11-18) | p | check, re-run as written | grade | did the action happen |
|---|---|---|---|---|
| 1. RQ-20261118-dbf8-01 (CatBoost vs LightGBM on D3) PASSES | 0.30 | `research/results/RQ-20261118-dbf8-01/44382439615.jsonl`: **fail**. CatBoost paired vs raw −0.032 R, CI [−0.099, +0.035], k=13 folds; ens3 −0.0008. | **miss** | yes (unit ran) |
| 2. FRONTIER-LEVER-TABULAR is still `queued` | 0.55 | checklist row state = **`dropped`** (since 2026-10-23) | **void**: last week's call misread the row state | — |
| 3. ≥ 70% of ml_bakeoff results in the window target regime/direction labels | 0.65 | 3 of 3 results whose unit has an `ml_bakeoff` block (2a2e-11, b3c9-19, a10d-05) | **hit** (n=3, a thin denominator) | no capacity was re-pointed |
| 4. BTC fc-pcv-v2 still drifts (KS ≥ 0.20) | 0.65 | `/shadow/drift`: **KS 0.504, PSI 0.528**, ref n 3,336 / cur n 696 | **hit** | DRIFT-REMEDIATE row still `queued`, due today |
| 5. Serve-path diff names `fc_*` first | 0.50 | PI-20261118-ZZUFKM1F-0001 still `queued`, no diff landed | unresolved (void if none by 12-02) | no |
| 6. A D8 aadc-12 downstream read by 12-02 | 0.35 | none yet | unresolved | — |
| 7 (carried from 11-04). `ml_entry` bybit_2 mean realised pnl% ≤ 0 at n ≥ 30 | 0.55 | `/trades/closed?account_id=bybit_2&since=2026-11-01` (2 pages): **59 ml_entry closes, mean −0.488%/trade**; every row `measured`, and the account is `journalTrust: known_divergent` | **hit** | — |

Footer: 3 hit · 1 miss · 1 void · 2 unresolved. Brier over the 4 resolved calls is 0.134, which is `INDETERMINATE` below 10 resolved calls.

**Frontier calls (2026-11-18 scan):**
- **CatBoost** (kept): **hit**. It ran and gave an informative FAIL at a powered design.
- **TabICL** (kept): **miss**. dbf8-02 is still blocked, and its lever row is `dropped`, not queued.
- **Dropped heterogeneous stack**: hit. The ens3 arm landed −0.0008, CI spans 0.
- **Dropped TSFM-for-D2**: hit. The gate still holds, because the D2 parity PI is still open.
- **Dropped offline RL for exits**: hit. 4 more action-value FAILs this week (c7e3-01..04).
- **Moirai, licence-dropped**: hit.
- Mitra, distributional head, Kronos and TabPFN serving: unresolved.

## 1. CHECKS (numbers only)

**Headline numbers:** ML changes **12 of 85** rostered account-legs and **3 of 9** real-money legs (`ml_entry`, `ml_entry_eq_struct`,
`trend_donchian_xrp_4h` under D4 reduce; source: `config/accounts.yaml` × feed consumers × `config/overlay_policy.yaml`). **First broken C4
hop:** desk decisions **H2→H3**. 5 were labelled and 0 entered a dataset; for `live_review`, H3 is `could_not_look` (no consumed-ids ledger).

| # | state | numbers (population) |
|---|---|---|
| C1 trainer + registry | **finding** | trainer-vm-diag [#28843](https://github.com/benbaichmankass/JTA-Trader/issues/28843): timer active; last `cycle_end` 2026-11-25T08:08Z, rc 0; the 01:24Z cycle trained 2 models (conviction-meta-v1, setup-candidates-metalabel-p2pool-v2); 0 `manifest_oom_red_flag`; build rc 0. Stages advisory 3 / shadow 16 / candidate 80 / research_only 1, against a plan of 3 / 21 / 72 / 1 (unchanged for 3 weeks). Stage-guard: demote `btc-regime-15m-lgbm-fc-pcv-v2`, hold 99 of 100. **`gate-check` returns "no registry entry" for all 8 served models with a consumer**, so no gate packet or cost-gate exists for any order-changing model. Trainer disk 86% (83 of 97 G). |
| C2 freshness | finding | `ml_plan_status.py --plumbing` rc 1: 115 flags of 85 plan items, most of them `UNPLANNED` rows. TRAINING-STALENESS: 2 stale and 2 never-trained of 5 scanned (exit-policy-v1 121.9 d, setup-candidates-metalabel-paper-v1 121 d, both `dataset_absent`; mes-execution-quality waits for a source by design). |
| C3 business use | ok (lines below) | `ml_order_changers.py`: 8 models with a consumer, 7 with `order_effect=yes`. Foxhound-1 mean_net_r 0.0371, n 907, t 1.03, 3,453 trades to confirm. **Foxhound-1 refit v1r20261122 has NO POWER RECORD**, yet it is the served pointer. Foxhound-4 0.492, n 207, clustered se 0.239. Labrador-1b 0.0081, n 868, se —. Beagle-1 n 1,830, mean —. Labrador-2 (exit head) changes no order. Foxhound-2 −0.116. Foxhound-3 0.039. The D2 router heads are missing from the consumer feed (PI-20261118-EUWZZMDP-0002, still open). |
| C4 learning chain | finding | `ml_learning_ledger.py` (7 d): H1 desk 9 / live-review 45 · H2 5 / 83 · H3 **0** / — · H5 scored 163 · H6 promoted 0 · H7 order-changing legs 6 (3 real-money/prop; ESTIMATED). |
| C5 serve parity | **could-not-look** | gate-check `live_parity` can't run with no registry entries. The live-vs-replay parity job reported `could_not_check` for `ml_entry_eq_struct` in 6 daily LRP pipeline rows dated 11-09..11-15. The owner row ML-LIVE-PARITY-ML-LEGS is `in_flight`, due 11-14 (overdue). |
| C6 champion/challenger | finding | No trainer gate-check is possible (see C1). In-unit comparisons used the same folds, rows and costs: dbf8-01, f1a0-33 (Δ −0.0115 R, week-clustered t −1.22, **INDETERMINATE**), c7e3-01..06. **Every AM random control so far drew its placement with exit-time knowledge** (c7e3-06 controls mean +4,310 R against a HOLD book of −10,282 R on the same trades). The R4 "beats 95% of controls" clause is invalid on every earlier AM result. |
| C7 drift | finding | (a) Plan-only scan: success, 19 rows in the last hour, **0 drifted**. `/shadow/drift` reads BTC fc-pcv-v2 KS 0.504 for the **3rd consecutive weekly read** (11-11, 11-18, 11-25). The two instruments disagree (PI-20261118-EUWZZMDP-0003, re-confirmed). (b) LIVE-DECAY CUSUM (`live_decay_cusum.py`): `ml_entry` **no trip, S 4.25, peak 5.99, h 8.02, n 59**; `ml_entry_eq_struct` n 1, indeterminate. |
| C8 concentration | finding | `--diversity`: **CONCENTRATION gbdt 14 of 19 open family-tagged items (74%)**; manifests 79 of 108 gbdt; 8 served models `UNMAPPED` to a family. |
| C9 research landed | ok | 195 ML-tagged result records since 11-18T20Z (units with `iteration.subject_kind: ml_model`, `ml_bakeoff` or `ml_consumer`): fail 88 · indeterminate 54 · pass 32 · not_applicable 19 · no_action 2. ml_entry levers f1a0-01..33: 0 PASS. AM v2 c7e3-01..04 FAIL, 05 PASS (**invalid**, leak), 06 FAIL; c7e3-07/08/09 queued. |
| C10 DSR | finding | `dsr_probation.py`: `ml_entry` and `ml_entry_eq_struct` are both `not_computed` (no readable per-trade series); 7 of 9 production legs are on probation. |
| C11 overlay CUSUM | ok | `overlay_cusum_join.py --cusum` (overlay_shadow 121 rows × 177 closed trades since 11-17): `bybit_2` joined 5, reduced 1, S 0 / H 2.0, no alarm; `tradeify_1` `no_reduced_trades` (n=0, not a pass). |

**Weekly progress lines:**
1. Data coverage: `could_not_look`; no per-family share instrument was run this session.
2. Features in use: `could_not_look`.
3. Retrain freshness: the served ENTRY pointer is v1r20261122, 3 d old (INFERRED from its id; the trainer has no registry entry for it).
4. Live vs held-out: `ml_entry` live −0.167 R/trade (n 59, 5 symbols) against a held-out +0.0371 R/trade.

**D-slot coverage** (MEASURED; population: queued `research/queue/*.yaml` with an ML subject or consumer):
- D3 entry: 10 units (`ml_entry` 6, equity-native 2, struct 1, all-accounts 1).
- AM brackets: 5.
- D2 regime gate: 6. All are classifier-metric variants; the cost-net consumer test 78fc-08 is blocked.
- D4 overlay: 2.
- **D7 TP revision: 0.**
- **D8 exit head: 0.**
- D1: 3, but these are strategy-leg re-measures, not ML.

Research-ops' 11-24 alarm still stands for D7 and D8.

## 2. ANALYSIS

### Q1: The ml_entry evidence picture under the promotion-rule fix *(real money; −9.84 R lifetime)*

**What put it on real money.** RQ-20261103-5e04-01 / c692-06 (`comms/strategy_evidence/ml_entry.json`, `basis: heldout_window`):
- tau 0.10 was chosen on 8 purged dev folds (2022-01..2025-09).
- The model was frozen, then the held-out window **2025-10-01..2026-09-30** was scored once: **+0.0371 R/trade, n 907, ΣR +33.7**.
- iid se 0.0362 gives t 1.03. No clustered se exists, and the DSR is not computable (C10).

**What has happened to that window since.** f1a0-33's author records **27 ENTRY reads of the 2025-10 window** (INFERRED: I did not
recount them). The dev-fold base recipe earns only **+0.0030 R/decision over 71,334 decisions** (f1a0-33, MEASURED). That is an order of
magnitude below the held-out figure.

**Live.**
- 59 real-money trades, ΣR −9.84, −0.167 R/trade.
- At an assumed sd of 1.09 (the power record's figure), se ≈ 0.142. Live is then t ≈ −1.2 against zero, and z ≈ −1.4 against the
  Stage-0 mean (ESTIMATED).
- The live bar (≥ 20 trades, ΣR > 0, ~80% lower bound > 0) is **not met**.
- The registered demotion read (t ≤ −2 at n ≥ 100) is **not triggered**, and neither is the CUSUM (S 4.25 < h 8.02).

**Two hypotheses.**
- **(a) Noise around a small true edge.** The live loss is within 1.4 se of +0.037. On this alone, the CUSUM would stay quiet for
  months.
- **(b) The +0.037 is a selected number.** The held-out read was the window the pass was graded on, and the dev base sits at ≈ 0.
- **The discriminating test is a fresh window.** It replays decisions from 2026-10-01 onward through the frozen v1 recipe; the
  Binance Vision archives are public. It needs no new live trades.
- **Power is the catch.** 3,453 trades are needed to confirm at t = 2. A ~8-week fresh window gives about 150–250 decisions on 5
  symbols, so it can refute a large edge but cannot confirm +0.037.

**Under the operator's 11-25 rule ("a number measured only over the grading window must not promote"):**
- `ml_entry`'s only promoting number is that held-out read, so **it has no qualifying promotion evidence under either reading of the
  rule**: the held-out was the grading window, and the live bar fails.
- **It is the operator's call (Tier 3)** whether that means demote-to-floor, or keep as the D3 live baseline while a challenger is
  run. The 11-16 rule says a live baseline keeps trading until a challenger beats it.
- I propose the re-grade and its fresh-window read, not the action (P-1, P-2).
- **Rejected alternative:** waiting for live n ≥ 100. That is a future-month read where an in-hand window exists (research-ops
  "iterates on in-hand data").

**`ml_entry_eq_struct` has the same structure** (one held-out read, `param_selection_provenance: null`), but it is stronger
(clustered t 2.06) and has n=1 live. It goes into the same re-grade.

### Q2: What do this week's ML tests show, and what don't they show? *(D3, AM)*

**ml_entry.** 33 lever units (execution, sizing, funding, OI/taker inputs, timeframe, target) gave 0 PASS. The target lever f1a0-33
came back INDETERMINATE in the wrong direction (Δ −0.0115, t −1.22, 2 of 8 folds better).

Every arm sits on a recipe whose dev-fold base is +0.003 R. **A 33-unit null over one base is a statement about the base, not the
levers.** The levers can only move a near-zero mean by a few thousandths, and the registered MDE (+0.0068) is at that scale.

**AM v2.** Four action-value classes FAILED (c7e3-01..04). The c7e3-05 PASS is void: its random control placed actions at bars
chosen with knowledge of when the trade exits.

**c7e3-06 is the clean read.** The fixed age-5 tighten, vs HOLD on 275,378 dev trades:
- net R −11,613 vs −10,282 (worse by 0.0048 R/trade);
- CVaR5 cut 13.8%, below the 15% bar;
- max drawdown worse by 9.9%;
- 0 of 6 folds held.

It **fails R2 and R3 on its own**, independent of the leaky R4. So the FAIL stands. The leak does not rescue any earlier AM FAIL;
it only voids PASSes and the R4 clause.

ML-PRIMARY authored c7e3-08/09 (causal draws), and they are queued. I do not duplicate them.

**Is it learning?** H3 = 0 for desk labels while H2 = 5. Labels are produced but no dataset reads them, which is the same shape as
last week.

### Q3: Why do D7 and D8 have no next unit? *(Labrador-1b changes real-money exits; Labrador-2 changes none)*

**D7 (Labrador-1b).** Its power record has mean 0.0081 at n 868 with no se, so it cannot be read. Its owner row ML-ENTRY-TP-REVISION
is `landed_unproven` (due 12-01). Nobody owns the question "is the TP revision adding value on the same trades?"

**D8 (Labrador-2).**
- Its owner row ML-EXITHEAD-VALUE is `landed_unproven`, due 11-12 (overdue).
- 14 exit-head units graded this week (latest verdict per unit): 1 pass, 11 indeterminate, 1 fail, 1 not_applicable.
- No ETH out-of-sample read exists, and ETH is the one leg it could act on.

**Two hypotheses.**
- (a) The iteration loop only authors from a FAIL, and these slots produce INDETERMINATEs and `landed_unproven`s.
- (b) Capacity went to D3/AM.

The queue shows both: 15 queued units on D3+AM, 0 on D7/D8. **Proposals P-3 and P-4.**

### Q4: The trainer can't see the models that trade *(every order-changing model)*

All 8 served models fail `gate-check` with "no registry entry". So stage-guard, cost-gate and `live_parity` cover only the 100
housekeeping heads. Of those, 3 advisory D2 heads route nothing that the consumer feed can see.

Row ML-REGISTRY-SERVED-MODELS-NO-STAGE has been `queued` since its 11-14 due date. This is the single largest blind spot in C1/C5/C6.
**P-5.**

### Q5: Concentration and frontier *(capacity)*

gbdt holds 74% of open items. This week's 33 ml_entry levers and 6 AM units were all LightGBM.

The scan (`docs/research/frontier-scan-2026-11-25.md`) **keeps two methodology ideas, not models**:
- a reusable-holdout / held-out-read ledger (Dwork et al. 2015) for the promotion-rule fix;
- PBO/CSCV (Bailey et al.) as the deflation for configuration selection.

It drops the new TSFM/TFM releases (TabAbax, Kumo Tabular, TabPFN-3.5, TiRex-2, Toto 2.0, TimesFM-3), each with a named gate. Their
D3 benefit is capped by the near-zero base (Q2), and the tabular lever row is `dropped`.

**Surprises:**
1. The Foxhound-1 refit pointer has no power record.
2. `FRONTIER-LEVER-TABULAR` has been `dropped` since 10-23 while two reviews called it queued.
3. 15 open ML pipeline items point at owner rows that are `done` (10 of them at ML-HYGIENE).

## 3. Decisions (ranked by money; each carries a pre-registered check)

**Audit-outcome contract:** each proposal maps to a row, unit or named decision, with a `due_by`. No units are queued by this lane.

| # | proposal | label | maps to → due_by | p | check (resolves when) |
|---|---|---|---|---|---|
| P-1 | **Re-grade `ml_entry` and `ml_entry_eq_struct` under the operator's 11-25 promotion-rule fix.** Record whether each leg's promoting number was measured only over its grading window, and state the outcome as qualifying / not qualifying. | TRADING | **named operator decision**: the promotion-rule-fix row the manager opens (operator 11-25) → 2026-11-30 | 0.85 (that ml_entry is "not qualifying") | a committed re-grade record naming both legs (by 11-30) |
| P-2 | **Fresh-window read of frozen ml_entry v1** on 2026-10-01..latest Binance Vision decisions, 5 bybit_2 symbols, full cost stack. Register before the run: PASS iff mean net R > 0 at day-clustered t ≥ 2; FAIL iff mean < 0 at t ≤ −2; else INDETERMINATE, stated as underpowered for +0.037 (~200 decisions vs 3,453 to confirm). | MODEL | unit, to be authored by ML-PRIMARY on manager go → due 2026-12-02, roadmap L-ML-LIVE | 0.25 PASS · 0.20 FAIL · 0.55 INDET | result record exists by 12-02 |
| P-3 | **D7 next unit:** Labrador-1b revised-vs-held TP on the same trades, delta net R with day-clustered se, on the mirror and the replay. This fills the empty slot and the missing se. | MODEL | row ML-ENTRY-TP-REVISION (due 2026-12-01, L-ML-LIVE) → unit by 12-01 | 0.35 that delta > 0 at t ≥ 2 | a unit with `iteration.subject` D7 queued by 12-01 |
| P-4 | **D8 next unit:** ETH out-of-sample delta net R for Labrador-2, the declared read ("< 0 at n ≥ 30 → annotate"). | MODEL | row ML-EXITHEAD-VALUE (M25; due 11-12, overdue; re-date to 12-02) → unit by 12-02 | 0.30 positive | the unit or result exists by 12-02 |
| P-5 | **Register served models in the trainer registry** (or give gate-check a served-model path) so C1/C5/C6 can look at the 8 order-changing models. | MODEL | row ML-REGISTRY-SERVED-MODELS-NO-STAGE (queued, due 11-14; re-date 12-03) | 0.40 done by 12-03 | `gate-check ml-decision-entry-v1r20261122` returns a packet |
| P-6 | **Held-out read ledger:** count reads per (subject, window) from the research results so "spent window" is a number, not a claim. This is the instrument for the 11-25 rule (frontier keep #1). | MODEL | **named operator decision**: fold into the promotion-rule-fix row (P-1) → 2026-11-30 | 0.6 adopted | the rule text cites a read count |
| P-7 | **Re-route 15 ML pipeline items whose owner row is `done`** (10 at ML-HYGIENE, ML-ENTRY-RETRAIN-CADENCE ×2, ML-REGISTRY-LADDER-GAPS, ML-ADVISORY-SCOPE-GUARD, ML-QUEUE-DIVERSIFY). Each is either killed with a reason or re-pointed to a live row. | MODEL | manager (Thursday planning) → 2026-11-27 | 0.7 | `review_followthrough` ml-review backlog has no item on a `done` owner (by 11-27) |
| P-8 | **Void the R4 control clause on every AM result before c7e3-08/09.** This is a grading note, not a re-run, and it changes no FAIL. | MODEL | owner ML-PRIMARY (c7e3-08/09 already in flight) → 2026-11-27 | 0.8 | the AM programme plan or iteration block notes R4-void |
| P-9 | **DRIFT-REMEDIATE-btc-regime-15m-lgbm-fc-pcv-v2:** 3rd consecutive drift read. Apply `drift-remediation` (labelled macro-F1 held last week, so the regime-mix hypothesis comes first). | MODEL | existing row (due 2026-11-25) → re-date 2026-12-02 | 0.65 still KS ≥ 0.20 on 12-02 | `/shadow/drift` KS on 12-02 |

**Calls for next week's Layer 0:**
- P-2's verdict split as stated.
- `ml_entry` real-money ΣR stays < 0 at the 12-02 read (p 0.7; check `/performance?window=all` perStrategy).
- The CUSUM does not trip by 12-02 (p 0.85; check `live_decay_cusum.py --leg ml_entry`).

**Backlog drain** (hard gate): 55 open ML items (population: origin ml-review, routed_to ML*, or `[ml]`/`[refinement]`). All 55 are triaged
in the JSON: 0 resolved · 0 fixed_now · 15 owner-done (re-route P-7) · 40 kept_open with this run's re-validation. **count_untriaged
0.** Redated with this run's observation: ZZUFKM1F-0001, EUWZZMDP-0003, TX7TX2ZN-0002, DGUBH8UA-0002.

## 4. Not done

- C5 feature-row parity diff (no served registry entry; P-5).
- Weekly progress lines 1–2 (no instrument run).
- The practice refresh (sibling lane).
- No `send-ping` system-action was dispatched. The manager receives this report instead.
<!-- ML-FRONTIER-PREP:END -->

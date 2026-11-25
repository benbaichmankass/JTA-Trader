# Weekly walkthrough 2026-11-25

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH**. If another lane has not landed its section yet, that section is missing. When two lanes collide, the later one merges `main` first.

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

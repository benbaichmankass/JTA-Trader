# CJ-3 pilot r1 — blind-then-reveal grade: cost per grade, population, backfill scope

Row `CJ-3-BLIND-GRADE-PILOT` · roadmap `M25` · design `docs/plans/ml-claude-distillation-DESIGN.md` § 4.3 ·
lane `session_01FPWQvqvHnMBxAaa7w7Zyw1` · 2026-10-26. Every number below is MEASURED from the files in
this directory unless marked INFERRED. Feeds the operator's weekly teacher-label cap (Q1 "Pilot first,
then set") and row `CJ-7-BACKFILL-SCOPE`.

## 1. Cost per grade (MEASURED)

Source: `get_session` → `usage.cost_usd` (API-equivalent pricing) on each grader session once idle,
read 2026-10-26 ~17:46Z; recorded in `run.json`. One fresh **Sonnet** (`claude-sonnet-5-5`) session per
pass, 50 packets per session, so the per-session overhead (system prompt cache write) is inside the figure.

| pass | session | n rows | cost_usd | per grade |
|---|---|--:|--:|--:|
| blind | `session_013mvbtKmwcbcCMSRJur5Hzo` | 50 | 0.3582 | **$0.0072** |
| reveal (r1b, accepted) | `session_01WbXgVkFZwvSGBqtmGkoE2Q` | 50 | 0.4312 | **$0.0086** |
| **blind + reveal, per trade** | | 50 | 0.7894 | **$0.0158** |
| reveal r1 (REJECTED, see § 3) | `session_013oeqBGxvsY2Gv3ykzHzJQT` | 50 | 0.1848 | — |
| all-in incl. the rejected pass | | 50 | 0.9742 | $0.0195 |

Not measured: an Opus grader (no Opus run was made; its rate is UNKNOWN, not extrapolated), batches
larger than 50 (larger batches amortise the per-session overhead further: INFERRED), and the rate in
plan-allowance percent (spend_meter.py refuses that conversion; it is not a constant).

## 2. Population (MEASURED, journal read 2026-10-26 via `scripts/ops/diag_fetch.sh`)

`blind_grade.py select --since 2026-07-01 --n 50 --seed 20261026` → `selection.json`.

- Journal: 6,740 trades, 5,550 order packages. 2,274 closed non-backtest trades.
- Excluded (trade-level): 4,466 not closed · 718 pairs (2-leg) · 212 symbol outside the 7 crypto
  symbols the candle source covers · 376 no package row · 167 decided before 2026-07-01 ·
  179 fan-out siblings (one trade per package is graded) · 5 packages net R uncomputable.
- **Eligible: 617 packages**; partition checks: 968 − 167 − 179 − 5 = 617.
- **Sample: 50**, uniform random (seed 20261026), decisions 2026-07-04 → 2026-10-21. Mix: ict_scalp 32,
  trend_donchian 13, pullback 5; 5m 20 · 15m 12 · 4h 7 · 1h 6 · 2h 5. Outcomes: 20 of 50 net R > 0,
  mean net R +0.46, median −0.34. Account mix is mostly `bybit_1` paper (the population is).
- Candles: Binance spot public klines as a **proxy** for the Bybit perp path (Bybit's API is
  geo-blocked from the session sandbox, MEASURED 2026-10-26). Used for the masked bars and for MFE/MAE;
  net R is the journal's (`src.runtime.net_r_label`, package initial stop as the risk basis).
  `pnl_provenance` of the 50 is `estimated` (cost_source `estimate` 45, none 5): not broker-measured.

## 3. What happened (MEASURED)

- **Masking.** 50 of 50 packets built; `find_leaks` refused 3 builds during development, all
  ATR-normalised values that coincided with a low-priced market's raw price (ADA ~0.167). The rule now
  flags a raw-series leak structurally (3+ positional matches to one raw bar), and
  `tests/test_blind_grade.py` plants every leak class and shows it is caught.
- **Blind pass:** 50 valid rows, 50 distinct theses. Grades C 21 · D 19 · B 6 · F 4; mean p_win 0.33.
- **Reveal r1 REJECTED.** 0 of 50 grades changed and 41 distinct notes built from a few templates in
  37 s: the grader wrote a program that generated the rows. That is a rubric, not a judgement (design
  § 1.2), so it was kept only as `revealed_grades.r1.REJECTED.jsonl`, never ingested. Both briefs now
  forbid generating rows with code.
- **Reveal r1b accepted:** 50 rows, 50 distinct notes, 4 grades revised (all down one step: C→D 3,
  B→C 1). 13 `exit_quality: unknown`, mostly reconciliation closes the brief tells the grader not to judge.
- **Wiring, against the live journal.** The CJ-2 family (`ml/datasets/families/claude_judgments.py`)
  over the committed stores and a SQLite mirror of the same diag pulls emits 50 `blind_grade` rows as T0,
  excludes all 50 revealed rows as T1 by default, and its joined net R equals the packet net R within
  5e-5 on all 50. It found one bug, fixed in the same PR: revealed rows read as T0 because the stored
  cutoff is second-truncated while `closed_at` has microseconds; revealed rows are now T1 by kind.

## 4. Diagnostics only — NOT the validation (n = 50)

Spearman vs realised net R on the 50 (Fisher 95% CI): blind `expected_r` −0.12 [−0.38, +0.17] ·
`p_win` −0.23 [−0.48, +0.05] · `grade_score` −0.10 [−0.36, +0.19] · the strategy's own `confidence`
+0.02 [−0.26, +0.30]. `p_win` Brier 0.275 vs 0.240 for the base rate. **No signal at this n, in either
direction**, and a teacher worse than climatology here. The pre-registered test is CJ-4 (n ≥ 150, design
§ 3.3); these numbers do not pre-empt it and must not be quoted as its result.

## 5. Backfill scope (feeds the cap decision; the backfill was NOT run)

Counts MEASURED on the same journal read; cost INFERRED = count × the accepted pair rate $0.0158
(and × $0.0195 with a rejected-pass allowance).

| tier | packages | what it needs | cost @ $0.0158 | @ $0.0195 |
|---|--:|---|--:|--:|
| A: buildable today (7 crypto symbols, single-leg, any date) | **695** | nothing new | **$11.0** | $13.5 |
| B: + other single-leg symbols (MGC, SLV, QQQ, TLT, …) | +143 → 838 | a historical candle source for IB / Alpaca symbols | $13.2 | $16.3 |
| C: + the 74 packages missing a bracket or ATR | 912 single-leg | a packet without the ATR frame (not built) | $14.4 | $17.8 |
| D: + pairs | +714 → 1,626 | a 2-leg packet (not built) | $25.7 | $31.7 |

381 closed trades have no package row and cannot be blind-graded at all. New closes run at INFERRED
~70 single-leg packages a week (302 in 2026-09), about **$1.1/week**.

**Leakage caveats for the backfill:**
1. **LLM memory (design § 3.5.5).** Masking hides symbol, date and absolute price, but the grader may
   still recall regimes. The grader's knowledge cutoff is not known to this lane, so `pre_cutoff` is
   `null` on every pilot row. 78 of the 695 decisions predate 2026-07-01. Per the CJ-7 note, pre-cutoff
   rows may TRAIN a student but never VALIDATE one; the validation set must be post-cutoff.
2. **Residual fingerprints.** `open_exposure_at_decision` counts grow as the system added legs, so they
   are a weak proxy for the date; `atr_pct_of_entry` and the vol regime hint at the market's
   volatility. Neither reveals the outcome. Both stay, stated.
3. **Proxy candles.** Bars and MFE/MAE come from Binance spot, not the venue's perp.
4. **Grader scripting.** One of three passes generated its rows with code. Every backfill batch needs
   the distinct-text and changed-grade checks in § 3 before ingest.
5. **Estimated P&L.** The outcomes are mostly `estimated` provenance; CJ-4 should report the
   broker-measured subset separately.

## 6. Cap proposal for the operator (DECIDED by the operator, not by this lane)

Proposed: **$15 one-time** for tier A (695 packages, Sonnet, blind + reveal, with a ~35% allowance for
rejected batches), then **$3/week** for new closes (≈ 2.7× the INFERRED run rate). Tiers B–D wait until
CJ-4 says whether the Sonnet blind grade beats `confidence` at n ≥ 150; if it does not, the backfill
stops at tier A and that is the answer. An Opus pilot (50 packets, cost to be measured) is worth running
only if CJ-4 fails on Sonnet and the question becomes whether a stronger teacher helps.

# 1h ETF survivors: evidence check and one promotion proposal per leg (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Gates this adds or changes: none.** Evidence plus proposals. It changes no roster; every roster change named here is the manager's merge or the operator's call.

Lane OPDEC-20261112 (dispatched by Manager Session 2026-11-11a). Rows **PROMOTE-TLT-1H-REAL-MONEY** (operator decisions page m9,
verbatim *"Rebuild the evidence record, then promote when it passes"*) and **PR1111-SURVIVOR-PROMOTIONS** (p8, verbatim *"Yes: evidence
check, then a proposal per leg"*). Record: `docs/plans/thursday-planning-2026-11-12-answers.md`.

## What was measured, and on what

- **Stage-0 records rebuilt** with `scripts/ops/build_strategy_evidence.py` (the promotion-corpus harness; not `backtest_orb.py`, not
  `src/backtest/backtester.py`), yfinance 1h, pinned window `2025-06-02 14:00Z .. 2026-11-11 21:00Z`, 4 time-folds, 365 d OOS.
  Cost stack = the harness's venue-aware stack for Alpaca ETFs: **fee 0 (commission-free), slippage 5 bps round trip, funding 0**.
  ⚠️ The 5 bps is a **placeholder, not a measurement** (operator 2026-09-24; row E62 owns replacing it). It is a full stack in the
  C3 sense (every component declared), not fee-only.
- Every record now carries `holdout_confirmation`, copied unchanged from the committed holdout verdict whose
  `selected_config_fingerprint` equals the record's own fingerprint (dukascopy 1h, 2018-06..2026-10, latest 25% held back, read once).
- `scripts/ci/check_roster_promotion_evidence.py` clauses C1-C5 and the fingerprint identity: **all four records pass**
  (re-run `clause_verdicts` to check; this doc does not replace the guard).
- **By side**, because `alpaca_live` is a long-only cash book: `side_filter: long` and the venue reads `shorting_enabled: false`
  (`/api/diag/broker_account_status`, read 2026-11-12 08:24Z: cash and equity **$194.52**, multiplier 1).

| leg | 365 d net R (n), folds + | fee-only | holdout net R (n) | holdout LONG | holdout SHORT | 365 d LONG |
|---|---|---|---|---|---|---|
| tlt_pullback_1h | **+0.23 (101)**, 2/4 | +10.65 | +6.41 (146), RQ-20261104-003 | **-3.01 (60)** | +9.43 (86) | **-3.88 (46)** |
| qqq_pullback_1h | +8.04 (56), 1/4 | +10.33 | +11.35 (72), RQ-20261101-78fc-25 | +14.81 (44) | -3.46 (28) | +10.54 (35) |
| slv_trend_1h | +44.71 (69), 4/4 | +47.45 | +35.99 (104), RQ-20261101-78fc-18 | +27.64 (65) | +8.35 (39) | +30.26 (43) |
| uso_trend_1h | +24.25 (55), 4/4 | +25.86 | +29.00 (75), RQ-20261101-78fc-19 | +29.00 (75) | long-only | +24.25 (55) |

Populations: the per-trade rows in `comms/strategy_evidence/runs/2026-11-12/<leg>__trades.jsonl` (365 d) and
`comms/research/<unit>/<run>/arms/A__trades.jsonl` filtered to entries on or after the holdout boundary (holdout).

## The take-profit (TP doctrine)

`tlt_pullback_1h` and `slv_trend_1h` and `qqq_pullback_1h` run the 50 R sentinel; `uso_trend_1h` declares tp_r 4 (reach unmeasured).
For tlt, **RQ-20261112-5ab1-01** was registered (and pushed) before any run: `tp_prediction_derive.py`, dukascopy 1h 2018-06..2026-10-26,
n 579 / n_oos 232. **Verdict INDETERMINATE**: K* = **3.5 R**, reach IS 0.107 / OOS 0.112 (calibrated, gap 0.005), OOS delta vs the sentinel
-0.020 R/trade, CI95 [-0.082, +0.032] straddles the -0.05 margin. K* was chosen on IS trades that all entered by 2023-07-03, before the
holdout boundary; on the 146 held-back trades tp 3.5 nets +6.47 R vs +6.41 R for the sentinel. With tp 3.5 the 365 d record reads
+1.11 R (n 101, D1 pass, long side still -4.91 R over 47): `comms/research/RQ-20261112-5ab1-01/tp35_variant/`. By the unit's own rule a
non-PASS declares nothing: **3.5 R is the operator's to declare** (the tqqq 1.5 R precedent).

## One proposal per leg

### tlt_pullback_1h: **do not promote to alpaca_live. Put it on the alpaca_paper demo floor (operator b1).**
The record clears the registered rule (D1 +0.23 R, faithful, holdout confirmed), so on paper it "passes". But alpaca_live can trade only
its **long** side, and the long side loses on **both** windows (365 d -3.88 R over 46; holdout -3.01 R over 60). All of the leg's edge is
short, which alpaca_live cannot execute. A real-money roster PR would put money on the side the evidence says loses. The rule clears; the
evidence does not support this routing, so **no roster PR was opened**. The 365 d margin is also thin: one extra bp of slippage costs about
2 R (fee-only +10.65 vs +0.23 at 5 bps), so break-even slippage is about 5.1 bps against a placeholder of 5.
**Proposal:** (1) the operator's 11-11 b1 choice ("Put qqq and tlt on the paper floor now") stands for tlt: it is a TESTING leg on **no
book** today (a demo-floor breach) and goes on alpaca_paper with a refreshed TLT allocation record (HELD PR, manager merges);
(2) real money only on a book that can short (none today), or after a long-only variant clears its own registered holdout.
`alpaca_portfolio` alone is not a promotion: the mirror shadows live.

### qqq_pullback_1h: **evidence supports it; blocked on affordability, not edge.**
Both windows positive and the long side is the better side (holdout long +14.81 R / 44). Weakness: only 1 of 4 of the 365 d folds is positive (one fold carries +15.3 R); RULE-D1 has no fold-majority clause, the holdout's discovery rule did. But QQQ trades above the alpaca_live cash wall
($194.52 cannot buy one share; the 2026-08-25 sizer measurement already lists QQQ as refused). Rostering it on alpaca_live would journal
refusals, not trades. **Proposal:** stay on alpaca_paper (testing) until alpaca_live is funded above one QQQ share or a registered
affordability proxy leg exists; then a roster PR on this record (still needs its real TP: RQ-20261104-7fdb-01 is the open TP test).

### slv_trend_1h: **evidence is strong; blocked by a standing operator decision.**
4/4 folds, +44.71 R / 69 at 365 d, holdout +35.99 R / 104, long side +27.64 R / 65, SLV affordable. But `config/accounts.yaml`
(alpaca_live block) records a standing Tier-3 demote, operator 2026-08-24 (0 wins in 13 closed, -$5,375), with the note
*"slv_trend_1h IS NOT HERE AND MUST NOT BE PROPOSED BACK"*. That decision was made on live-book P&L, which the ladder now says never
establishes edge, but only the operator can lift it. **Proposal (a question, not a PR):** does the 2026-08-24 demote still stand,
given a faithful full-stack record and a confirmed holdout? If lifted: roster PR alpaca_live + alpaca_portfolio, `mechanics_paths`
already lists it, and its TP needs declaring first (sentinel today; no TP unit has run on it).

### uso_trend_1h: **evidence is strong; blocked by a standing non-financial operator constraint.**
4/4 folds, holdout +29.00 R / 75. `config/accounts.yaml` records operator 2026-08-29, verbatim *"I don't wanna put USO on real money. I
don't wanna make money from fossil fuels."*, as a STANDING constraint that *"survives any backtest result"*. **Proposal: none for real
money.** It stays a testing leg on alpaca_paper. The 11-11 programme review listed it as a promotion candidate without this constraint.

## Nothing demoted
No leg changes book here. Operator p2, verbatim: *"And don't let anything get demoted without me looking at it first"*: none of the
above removes a leg from any roster.

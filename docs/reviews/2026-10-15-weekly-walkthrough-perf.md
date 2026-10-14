# Weekly walk-through brief — PERFORMANCE (grading and numbers only)

> **Doc status:** `unknown` · category `unknown` · lane `PERF-REVIEW-PREP-20261014` · prepared 2026-10-14 for the Thursday 2026-10-15 walk-through · Tier 1.
> **Not run:** `/perf-followup` (happens after the walk-through). **Not done:** per-decision A–F grading, M13 insights cross-check, backlog drain — this brief is the numbers half only.

## 0. How to read this

- **Merged ≠ deployed ≠ observed.** Everything below is **OBSERVED** on the live read-only API/diag on 2026-10-14 (~19:00Z). Nothing here was merged or deployed except where §6 says so. The one code change (§6) is **authored in this PR — not merged, not deployed**.
- **Classes are never pooled.** `real_money` and `paper` are separate populations throughout; there is no "whole book" total across them (the census refuses one by design). "Whole book" below = each class pooled over its own strategies.
- **Provenance** (`src/runtime/provenance.py`): every $ figure is split MEASURED vs ESTIMATED using `pnlProvenance` from `/api/bot/trades/closed`. "Not measured" = ESTIMATED + UNVERIFIED + null. **R figures are ESTIMATED**: realised R is telemetry `open_r` on a `final` row, else `pnl ÷ (risk_per_unit × position_size)`, and **peak R is an ESTIMATED lower bound on MFE for 100% of rows** (`peak_provenance` ≠ `measured`).
- **Measurement lives at:** `GET /api/diag/position_telemetry?limit=5000` (595 rows, `updated_at` 2026-08-17 → 2026-10-14), `GET /api/diag/journal?table=trades` (2 pages of 1000, back to 2026-08-13), `GET /api/bot/trades/closed?since=2026-09-10` (642 rows), `scripts/research/giveback_census.py` (with the §6 fix), `python3 scripts/ci/check_tp_doctrine.py`. Read 2026-10-14.

## 1. Populations

| window | definition | closed non-backtest trades |
|---|---|--:|
| **W30** (primary) | `closed_at` ≥ 2026-09-14, status `closed` | paper **528**, real_money **21** |
| **W-review** | `closed_at` ≥ 2026-10-10T19:10Z (last review file `comms/reviews/performance-review-20261010-191000.json`) | paper 46, real_money 3 |

W-review is too thin to grade (real_money n=3, R-graded n=0); W30 is the working window. Prop (`breakout_1`, manual bridge) and the pairs legs have no R-graded rows here (see §5).

**R-graded coverage in W30:** only telemetry-joined closes have giveback/R — paper **189 of 528** (36%), real_money **5 of 21**. 383 telemetry rows had no closed trade in the window (open or older) and 18 had no usable peak. So **R and giveback speak for a minority of closes**; $ figures cover all of them.

## 2. Net P&L per capital-day — the headline

`$/day` = Σ net pnl ÷ Σ hold-days (trade-days; size-**unweighted**). `bps/notional-day` = Σ pnl ÷ Σ(|size × entry| × hold-days). `R/cap-day` = Σ realised R ÷ Σ hold-days over R-graded rows. pnl is the stored journal `pnl` (fees/funding treatment not separately verified this session).

### Class level, W30

| class | n | net P&L $ | of which not measured $ | measured-only $ | $/day | bps/notional-day | R-graded n | mean realised R | **R / cap-day** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| paper | 528 | −95,092 | −78,162 (MEASURED 323 · ESTIMATED 183 · UNVERIFIED 14 · null 8) | **−16,930** | −221 | −89 | 189 | +0.165 | **+0.107** |
| real_money | 21 | −42.86 | −8.27 (MEASURED 16 · ESTIMATED 5) | **−34.59** | −1.07 | −127 | 5 | −0.359 | **−0.078** |

⚠️ **Paper $ is not a decision number.** Two ib_paper futures legs carry −75.6k of the −95k, all ESTIMATED/UNVERIFIED (§7-1). Paper notionals are also inflated vs real money. Read the paper **R** column and the measured-only $, not the headline $.
⚠️ Real_money R-graded n = 5 — **insufficient_n** (`--min-n 10`); the sign is a description, not a verdict.

### Per strategy, W30 (sorted by |$|; `insufficient_n` = R-graded n < 10, listed not graded)

| class | strategy | n | net $ | not-measured $ | $/day | R-n | ΣR | **R/cap-day** | read |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| paper | ict_scalp_mgc_15m | 12 | −62,858 | −62,858 | −6,822 | 11 | −6.6 | −0.72 | measured |
| paper | mhg_pullback_1d | 1 | −12,750 | −12,750 | −921 | 1 | −0.6 | −0.04 | insufficient_n |
| paper | ict_scalp_avax_5m | 32 | +12,244 | +1,022 | +3,734 | 32 | +12.2 | **+3.71** | measured |
| paper | trend_donchian_avax_4h | 5 | +5,575 | +5,777 | +2,076 | 4 | +9.0 | +3.39 | insufficient_n |
| paper | ict_scalp_sol_15m | 12 | −4,621 | +404 | −925 | 12 | −3.4 | −0.68 | measured |
| paper | ada_pullback_2h | 21 | −4,537 | −1,878 | −217 | 11 | +3.9 | +0.42 | measured |
| paper | ict_scalp_sol_5m | 18 | −4,305 | −1,393 | −1,410 | 17 | −3.2 | −1.18 | measured |
| paper | gdx_pullback_1d | 2 | −4,052 | 0 | −78 | 1 | −0.7 | −0.03 | insufficient_n |
| paper | squeeze_breakout_4h | 6 | −3,460 | −3,458 | −2,582 | 3 | −1.6 | −1.22 | insufficient_n |
| paper | xrp_pullback_2h | 13 | −3,306 | −2,066 | −264 | 5 | +0.1 | +0.01 | insufficient_n |
| paper | slv_pullback_1d | 4 | −3,021 | 0 | −55 | 2 | −1.2 | −0.04 | insufficient_n |
| paper | trend_donchian_eth_4h | 9 | −3,012 | +954 | −193 | 5 | +0.1 | +0.01 | insufficient_n |
| paper | trend_donchian_sol | 7 | −2,418 | −166 | −698 | 7 | −0.5 | −0.13 | insufficient_n |
| paper | ict_scalp_eth_15m | 9 | −2,327 | +569 | −411 | 9 | +1.3 | +0.22 | insufficient_n |
| paper | ict_scalp_xrp_15m | 13 | −1,725 | −256 | −203 | 11 | −2.3 | −0.27 | measured |
| paper | ict_scalp_xrp_5m | 14 | +384 | +281 | +333 | 14 | +4.3 | +3.70 | measured |
| paper | pairs_sol_eth_a / _b | 64 / 64 | +148 / −112 | +117 / −155 | +12 / −9 | — | — | — | no telemetry R |
| paper | pairs_bnb_btc_a / _b | 82 / 82 | −44 / +29 | −51 / +40 | −4 / +3 | — | — | — | no telemetry R |
| real_money | ada_pullback_2h | 9 | −15.87 | −3.86 | −2.12 | 1 | −1.0 | −1.22 | insufficient_n |
| real_money | xrp_pullback_2h | 5 | −11.42 | −3.71 | −1.81 | 2 | −1.7 | −0.31 | insufficient_n |
| real_money | trend_donchian_eth_4h | 3 | −4.64 | +1.85 | −0.82 | 0 | — | — | no R |
| real_money | iaum_pullback_1d | 1 | −4.41 | 0 | −0.88 | 1 | −0.5 | −0.10 | insufficient_n |
| real_money | slv_pullback_1d | 1 | −3.96 | 0 | −0.36 | 0 | — | — | no R |
| real_money | trend_donchian_xrp_4h | 1 | −3.11 | −3.11 | −5.08 | 0 | — | — | no R |
| real_money | tlt_pullback_1h | 1 | +0.55 | +0.55 | +0.13 | 1 | +1.4 | +0.34 | insufficient_n |

Other paper legs (≤4 trades, ≈0 $) omitted; full rows in the generating script's output (not committed). ⚠️ **R/cap-day on short-hold scalps is inflated** by tiny Σhold-days (e.g. mes_trend_long_1d read 917 on a 2-day hold in the 90-day census) — compare within a hold-length class, never across.

## 3. Giveback — peak R vs realised R (`position_telemetry`)

Giveback = peak_r − realised_r per closed trade. Share = Σ max(giveback,0) ÷ Σ max(peak,0) over R-graded rows. **Peak is an ESTIMATED lower bound** (100% of rows), so true giveback is **≥** these.

| class | window | R-graded n | mean giveback R | giveback share of peak | deep (peak ≥ 1R) → closed ≤ 0 |
|---|---|--:|--:|--:|--:|
| paper | W30 | 189 | 0.91 | **85%** | 11.8% of 85 |
| real_money | W30 | 5 | 1.24 | 141% | 50% of 2 |
| paper | 90-day census (telemetry back to 08-17), min-n 10 | 308 | 0.97 | 89% | 14.5% of 138 |
| real_money | same, 90-day | 10 | 1.00 | 97% | 33% of 3 |

Reading: on the paper book, trades that reach ~0.9R median peak **keep roughly 15% of it**. Per-leg, the worst measured (n ≥ 10) givebacks in W30 are ict_scalp_mgc_15m (1.35R, share 180%), ict_scalp_sol_15m (1.02R, 138%), ict_scalp_sol_5m (0.82R, 135%), ict_scalp_xrp_15m (0.85R, 132%), ada_pullback_2h (1.06R, 75%); the lowest are trend_donchian_avax_4h (0.18R, 7%), ict_scalp_avax_5m (0.65R, 63%), ict_scalp_xrp_5m (0.73R, 70%). A share >100% means realised R was negative on average: the trade went up and then stopped out below entry. Real_money numbers are n=5/10 — descriptive only.

## 4. TP-rule compliance — `python3 scripts/ci/check_tp_doctrine.py` (re-run 2026-10-14, HEAD `9bcbdad4`)

Population: **50 routings / 26 distinct legs**, every account in `config/accounts.yaml`. This is **OBSERVED on the repo config** (merged state), not a live-VM read.

| class | routings | entry_tp FAIL | tp_revision FAIL | compliant |
|---|--:|--:|--:|--:|
| real_money | 7 | 4 | 7 | **0** |
| prop | 6 | 0 | 6 | **0** |
| mirror | 6 | 3 | 6 | **0** |
| paper | 31 | 19 | 31 | **0** |
| **all** | **50** | **26** | **50** | **0** |

(entry_tp FAIL = sentinel `tp_r: 50` or no real predictive TP at entry; tp_revision FAIL = TP not revised through the trade — most legs read `rule_undeclared` or `no_tp_verdict`.) Zero of 50 routings are compliant; the guard is a ratchet over a 50-line baseline. Per the doctrine, priority by money at stake is real-money and prop first (7 + 6 routings; real-money entry_tp failures: `iaum_pullback_1d`, `ief_pullback_1d`, `slv_pullback_1d` on alpaca_live and `trend_donchian_eth_4h` on bybit_2).

## 5. Gaps in this brief (said plainly)

- **Not graded:** per-decision A–F, M13 insights, backlog drain, paper-book tracker append, real-money allocation benchmark — outside "grading and numbers only".
- **Prop (`breakout_1`)** — no rows in the pulls; `trade_quality_review.py` not run.
- **Pairs legs** have P&L but no telemetry R, so they carry no giveback/R column.
- **Telemetry coverage** is 36% of paper closes; 261 of 595 telemetry rows have no `trade_id` (`summary.by_lifecycle.unknown_no_trade_id`). Giveback is a view of the joined minority.
- Journal `pnl` fee/funding treatment was not independently checked this session.

## 6. Census-script bug (found by this lane; fixed on `main` by another change)

`scripts/research/giveback_census.py` treated **any** non-empty `peak_state` as "no peak". Live telemetry writes `peak_state: "measured"` **with** a peak (397 rows) and `thin_window` only with `peak_r` null (198 rows), so the pre-fix census graded **0 of 595** rows (read on identical inputs, 2026-10-14) and `RQ-20261014-9807-01` would have returned `no_data`. An equivalent fix was already on `main` when this PR was merged forward; this PR therefore carries **no script change**. With that fix the census graded 318 rows over 90 days on the same inputs (this lane's tree held an equivalent patch). MERGED on `main`; **not yet observed** in a landed queue-unit result.

## 7. Candidate follow-ups (for the walk-through; NOT run, NOT filed)

1. **ib_paper MGC/MHG paper $ looks mis-sized or mis-valued.** `ict_scalp_mgc_15m` trades 34–150 micro contracts per ticket (e.g. trade 6610: 96 contracts, −23.3 pts ⇒ −$22,368, ESTIMATED), yet R is only −6.6 over 11 trades. Check the paper sizing/valuation path before any paper $ is used to grade IB legs.
2. **Giveback is the dominant leak on paper** — ~85% of peak R given back, 11.8% of ≥1R trades close ≤ 0. Input for the exit-refinement / Programme 01 levers; the census unit (`RQ-20261014-9807-01`) now has a working script to run once this lands.
3. **Negative-R measured scalps:** `ict_scalp_sol_5m` (−1.18 R/cap-day, n=17), `ict_scalp_sol_15m`, `ict_scalp_xrp_15m`, `ict_scalp_mgc_15m` — diagnose before any demote (cause: regime / cost / execution / overfit), per the "diagnose, don't demote" rule.
4. **Positive-R legs worth understanding, not promoting:** `ict_scalp_avax_5m` (n=32, +3.71) and `ict_scalp_xrp_5m` (n=14, +3.70). Paper only; no live record.
5. **Real-money is n≈5–10 everywhere** — nothing is gradeable; the question is data (accrual time), not a verdict.
6. **TP doctrine: 0/50 compliant** — queue exit-refinement units real-money-first; start with the 4 real-money `entry_tp` failures.
7. **Telemetry coverage 36%** — worth checking why 261 rows lack `trade_id` before leaning on giveback numbers.

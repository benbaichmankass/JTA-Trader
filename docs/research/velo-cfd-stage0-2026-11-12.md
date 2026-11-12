# VELO-CFD-STAGE0: the commodity legs on the spot/CFD series at Velotrade's full cost stack (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane VELO-CFD-STAGE0 (research lane of Manager Session 2026-11-11a) · pipeline PI-20261112-D6UC5YT4-0001 and -0003 · public data only; no order, no account id, no balance, no config touched.

**Gates this adds or changes: none.**

## 0. The answer

**No commodity leg passes Stage 0 on the CFD series at Velotrade's costs, so the registered book is empty and the plan is NOT_BUYABLE under the pre-registered rule.** The ETF-proxy BUYABLE of [`prop-frontier-2026-11-12.md`](prop-frontier-2026-11-12.md) § 5 does not survive a re-measure on the longer, 24-hour spot series.

| Leg (CFD underlying) | n | Net R/trade at Velotrade costs | 95% CI | Folds (net R, 4 equal-count) | Verdict |
|---|---|---|---|---|---|
| `slv_trend_1h` (silver) | 944 | −0.035 | [−0.173, +0.102] | +17.1, −47.1, −32.3, +28.8 | **FAIL** (2/4 folds) |
| `uso_trend_1h` (WTI) | 797 | −0.068 | [−0.160, +0.024] | +0.2, +0.5, −41.9, −13.3 | **FAIL** (2/4) |
| `gld_pullback_1h` (gold; leg is INACTIVE) | 1655 | −0.267 | [−0.342, −0.192] | −123.8, −124.2, −150.8, −43.4 | **FAIL** (0/4) |
| `gld_pullback_1d` (gold) | 71 | −0.093 | [−0.426, +0.240] | −13.1, −0.3, +3.6, +3.2 | **FAIL** (2/4) |
| `slv_pullback_1d` (silver, descriptive) | 88 | +0.015 | [−0.232, +0.262] | −3.1, +2.0, −4.0, +6.4 | **FAIL** (2/4; net R +1.3 total) |

Population: Dukascopy 1h bid candles 2019-01-01..2026-10-30 (XAG/USD 46,317 rows, XAU/USD 46,326, WTI 46,273; sha256 in `verdict.json`), each leg at its exact `config/strategies.yaml` parameters through the evidence builder's own `build_harness_cmd`, fidelity `faithful` with no omitted levers. Primary cost arm: commission 2 bps round trip (0.01%/side, 1P), 3 bps slippage standing in for the unpublished spread, overnight fee 0.05% of notional per 00:30 UTC rollover including weekends. Both stress arms (6 bps commission; 10 bps slippage) are worse for every leg.

Registered rule: [`comms/research/velo_cfd_stage0/rule.json`](../../comms/research/velo_cfd_stage0/rule.json), pushed in commit 861825d00 before any harness run (only the data fetch preceded it). Evidence: [`comms/research/velo_cfd_stage0/run-20261112/`](../../comms/research/velo_cfd_stage0/run-20261112/) (`verdict.json` + the five per-trade ledgers). Runner: `scripts/research/velo_cfd_stage0.py`.

## 1. Why the ETF-proxy screen said yes and this says no (checked, not assumed)

1. **Costs reconcile; this is not a cost double-count.** For `slv_trend_1h`: gross +0.110R/trade, minus commission and slippage → +0.041R (equals the harness's own net), minus Velotrade's overnight fee → −0.035R. For `gld_pullback_1d` the gross is **+0.352R/trade** and the commission/slippage arm still leaves +0.331R, but the median hold is 456 h (19 nights): **the overnight fee alone costs 0.425R per trade (0.445R of total cost) and turns it to −0.093R.** The firm's 0.05%/night is about 18% a year of notional. Long holds cannot carry it; this is the same mechanism the memo found for the equity legs, now shown for gold too.
2. **The earlier window agrees in sign and is weaker; the older years disagree.** At the primary arm, entries from 2025-06-01: `slv_trend_1h` +0.256 (n=167, ETF-proxy memo +0.68 on n=64), `uso_trend_1h` +0.005 (n=149; memo +0.45), `gld_pullback_1h` −0.115 (n=299; memo +0.11), `gld_pullback_1d` +0.079 (n=13; memo +0.89 on n=8), `slv_pullback_1d` +0.667 (n=13; memo +0.17). Entries **before** 2025-06-01 are negative on all five legs (−0.098, −0.085, −0.301, −0.132, −0.098). The legs' Stage-0 passes sit in the most recent 17 months; the 7 earlier years do not support them. That is what the memo's selection-on-overlapping-windows caveat predicted. Descriptive only: the window split was not part of the registered rule.
3. **The series differs from the ETF in one way that matters.** The ETF ledgers are US-cash-session bars; the spot series is 24 h, so the 1h legs trade 2–3× more often (167 vs 64 trades since 2025-06 on silver) at lower edge per trade. The live legs are session-gated. Whether a session-gated variant of the CFD legs recovers the edge is a new question and is **not answered here**: re-running it under this rule would be a post-hoc re-cut. It is filed as an iteration unit (§ 4).

## 2. The simulator (PROP-TRAILING-DD-SIM, PI-…-0003) and what it says here

`scripts/research/prop_ev_sim.py` now accepts `limits.drawdown_type` of `static` (default), `eod_trailing`, `closed_trailing` and `intraday_trailing`, with `trailing_lock_buffer_pct` / `trailing_lock_offset_usd`; an unknown type is refused. Verified: the static default is bit-identical to the previous file (EV −24.47 in both on a real two-leg Velotrade cell, seed 1), and six planted cases in `--self-test` (worked by hand) cover EOD vs closed vs intraday peak timing, the lock, a no-new-high negative control that must equal static, the back-compat pin and the typo refusal. A ruleset yaml that declares a trailing type now loads; no new ruleset was added because Blue Guardian's fee and prices were not read first-party (memo § 3).

**Velotrade's own drawdown is static (7% CLASSIC, 3% PRO), so the registered Velotrade run did not need the trailing code.** It was needed by Blue Guardian (closed-trade watermark, locks at start once +6% plus a 1% buffer) and Tradeify futures (EOD trailing). It was exercised here only as a descriptive what-if.

Descriptive simulator cells (CLASSIC 1-Step $5k, 0.5% risk, 182 days, 3 seeds × 1000 lives; **post-hoc, not rule arms**; the unfiltered five-leg book, because the registered book is empty):

| Cell | EV/purchase mean (worst seed) | Zero-edge null | P(pass eval) | P(breach, any phase) |
|---|---|---|---|---|
| Full 2019–2026 ledger, static 7% | −$47.14 (−$47.67) | −$0.87 | 0.087 | 0.970 |
| 2025-06+ ledger, static 7% | +$8.14 (+$5.40) | −$11.91 | 0.413 | 0.796 |
| Full ledger, closed-trailing 7% | −$50.55 | −$25.72 | 0.061 | 0.999 |
| Full ledger, EOD-trailing 7% | −$50.73 | −$24.45 | 0.060 | 0.999 |
| Full ledger, intraday-trailing 7% | −$51.15 | −$31.78 | 0.058 | 0.998 |

The book edge on the full ledger is −0.151R/trade (n=3,555, CI [−0.206, −0.095]). Even on the favourable recent window P(breach) is 0.80, far above the registered 0.25 ceiling. Swapping the static 7% floor for any trailing floor makes it strictly worse (EV −$3.4 to −$4.0 further, breach 0.998), which is the sensitivity the simulator was built to show.

## 3. What this does and does not settle

- **Settled, under the registered rule:** the commodity legs as configured do not clear Stage 0 on the CFD proxy series at Velotrade costs. The BUYABLE reading of the ETF-proxy screen is not supported; no purchase is indicated. This is information for the operator's purchase decision; it changes no roster and gates nothing.
- **Not settled:** Velotrade's own feed, spreads and session hours (PI-…-0002 VELO-INSTR-READ was **not** run: the run needs no instrument spec to fail, and the probe is a Tier-2 VM dispatch). A session-gated variant (§ 1.3). The equity-ETF legs (not run; each was already negative or inside noise at Velotrade's fee in the proxy screen). The per-leg `comms/prop_survival/<leg>.json` gate (SUPERSET), moot while no leg passes.
- **The cheap reading of the answer:** the structural obstacle is Velotrade's 0.05%/night overnight fee against multi-day holds. Any leg that stays in a plan has to earn that fee back per trade; the 1d gold leg earns +0.35R gross and pays 0.42R in overnight fee alone. A shorter-hold or fee-aware variant is the iteration, not a re-buy of the same legs.

## 4. Follow-ups (for the manager to file; the work store is not in this checkout)

| What | clears_when |
|---|---|
| **VELO-CFD-STAGE0 (PI-…-0001): close.** Result above; verdict NOT_BUYABLE (0 of 4 decisive legs PASS). | a `comms/research/velo_cfd_stage0/run-20261112/verdict.json` names each of the four legs (done). The item's `clears_when` asks for a `research/results` row: no queue unit was authored for this one-off screen (the sibling PROP-FRONTIER-RESEARCH precedent), so the manager decides whether a results row is wanted. |
| **PROP-TRAILING-DD-SIM (PI-…-0003): close.** `prop_ev_sim.py` accepts `drawdown_type: eod_trailing` without raising (self-tested). Blue Guardian re-screen is unblocked but waits on its prices (memo § 3 "prices not read"). | done. |
| **New iteration unit (research):** session-gated and fee-aware variants of the commodity legs on the CFD series (US-session entries; max hold ≤ N nights so the overnight fee is earned back), pre-registered, with the 0.05%/night fee as the binding cost. Subject-iteration of `slv_trend_1h` / `uso_trend_1h`, which were positive from 2025-06. | a registered unit's result row exists. |
| **VELO-INSTR-READ (PI-…-0002):** deprioritise. It was the second buy-point condition; with condition 1 failed it is moot until an iteration passes. | the iteration above passes. |

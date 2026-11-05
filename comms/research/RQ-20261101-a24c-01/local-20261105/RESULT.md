# RQ-20261101-a24c-01: harness built, session-local dry run (2026-11-05, lane ML-WEEK-1105). NOT a graded result.

**Verdict by the unit's own rule: INDETERMINATE.** Clause: "the forward window cannot be claimed (already read)". Frozen
ml_decision_entry_v1 already read 2026-10-01..31 as `ENTRY-v1-frozen-ref-b609` (comms/research/holdout_reads.jsonl,
2026-11-01T20:12:13Z, unit RQ-20261101-b609-01-v1ref). On that read, frozen v1 pooled forward mean was **-0.0405 R per decision**
(n=894, 49 symbols, flat 3 bps), and **+0.0417** on the 5 bybit_2 coins (n=62)
(comms/research/RQ-20261101-b609-01/local-20261101T2000Z/result.json). This run claimed nothing and read no forward outcome:
it ran against a COPY of the ledger, and the clause fires before any scoring.

**What the dev folds show (dev only, < 2025-10-01; the c692-01 recipe refit per fold, frozen tau 0.10):**
C* = 50 bps; U(C*) = 15 symbols; dev mean net R re-costed = **-0.143** (n 16,684). Every C was negative
(30: -0.198 n 860, inf: -0.181 n 59,483). C 10/15/20 admit no symbol: the lowest dev median round trip is BTC at 26.7 bps.

**The registered cost model is mis-specified (MEASURED, this run, cost_table on the cached Binance 1h klines).** On 1h crypto
bars, the Corwin-Schultz high-low estimator reads intrabar volatility as spread:

| symbol | CS 2026-09 (bps) | CS dev median | Bybit quoted, snapshot 2026-11-01 |
|---|---|---|---|
| BTCUSDT | 7.6 | 13.2 | 0.01 |
| ETHUSDT | 12.0 | 18.6 | 0.04 |
| XRPUSDT | 19.0 | 21.7 | 0.8 |
| SOLUSDT | 17.5 | 27.4 | 1.06 |
| AAVEUSDT | 27.7 | 30.7 | 0.74 |
| BANDUSDT | 20.4 | 30.7 | 25.85 |
| ZRXUSDT | 19.5 | 24.9 | 20.56 |

It overstates liquid coins by 100x to 1000x and is roughly right only on thin ones. So "every C negative" measures the estimator,
not the model. A run on any window under this cost model would FAIL every symbol for a reason unrelated to the model.

**Needs a manager decision before any graded run** (both are re-registrations before a run, not after a result):
1. A cost model that matches the venue, e.g. spread = the Bybit quoted spread (a snapshot series, or the committed snapshot
   with its error stated), floored at one tick, plus the registered square-root impact.
2. A fresh forward window (2026-11, earliest read 2026-12-01).

Harness: `scripts/research/ml_decision_entry.py universe-costed` (self-test in `--self-test`). Population: the 52 Bybit-listed
(snapshot) members of the 60 c692-01 reference symbols. 3 were dropped for no Binance 1d quote volume on 2026-11-01
(WAVES, STORJ, LRC), leaving 49 costed.

# ml_entry_eq — serve-parity spec for the equity-native ENTRY model (2026-11-06)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-ENTRY-ALL-ACCOUNTS` (row `docs/claude/work/checklist/ML-ENTRY-EQUITY-NATIVE.json`)

Gates this adds or changes: none (a spec; the Tier-2 implementation PR declares its own).

Manager Session 2026-11-05b, 2026-11-06 ~05:05Z: serve the equity-native model as a DISTINCT leg `ml_entry_eq` (crypto v1 keeps `ml_entry`), on
`alpaca_paper` ONLY (the testing / demo floor). Evidence: RQ-20261105-e9a1-02 (run 42143223941) — n 858, net +0.0392 R, iid t 0.9, month-clustered
t 0.3: a mechanics soak, not an edge claim; real money is the operator's call.

## 1. The artifact (built, `ml_entry_equity.py export`, unit RQ-20261106-e9a1-03)
`model.json` (schema `ml_entry_eq_model/1`): features (config B, 21 = 15 own + 6 cross-sectional), tau 0.20, long side, bracket (SL 2 / TP 3 ATR14,
24 bars, decision every 4 h), costs, `pool_symbols` (173), `pool_rule_sha256`, `booster_sha256`, `booster_txt.long`; plus `parity_fixture.json`
(60 training-tail feature vectors with the harness predictions). The export refits twice on the same rows: A (the confirm stage's exact params) and B (same params pinned deterministic: single thread, row-wise, fixed seeds;
LightGBM can differ run to run on identical data). It ships A when A's sha256 equals the confirm run's `af4835e29fe83c86…` (A IS the graded model), else B,
and records sha_match plus the A-vs-B prediction delta on 20000 training-tail rows (max/mean abs, rank correlation, decision agreement at tau). Either
way the served model is the COMMITTED booster, so serve parity is exact; the delta only measures how far it sits from the booster that was graded.

## 2. What the live builder must compute (all of it already defined in `scripts/research/ml_entry_equity.py`)
Per ETF at a decision close, on its own regular-session 1h bar sequence (Alpaca 1Hour, hour-aligned, RTH = open 09:00..15:00 ET): the 15 own features
(`ml_decision_entry.features_symbol` + hour/dow of the close), then ACROSS THE POOL at the same close: `xs_rank_ret24`, `xs_rank_ret168`,
`xs_rank_vol24`, `xs_rank_volz` (pct ranks), `breadth_up24`, `rel_vol` (vol24 / pool median vol24). Config B has NO market-proxy and NO crypto feature.
Decision: restricted LONG when predicted net R > tau; one position per symbol; entry next RTH open; the us_equity session gate at close and close + 24 h.

## 3. Parity by construction, then by test
* The feature code moves ONCE into `src/` (a pure module, no I/O; the research harness imports it from there) so the harness and the live leg cannot
  drift — the failure class behind the v1 serve-parity work.
* Tests: (a) the loaded booster reproduces `parity_fixture.json` predictions exactly; (b) a golden-frame test: harness `build_table` and the live
  builder return the same feature row for the same bars (a cross-section of >= 20 symbols); (c) pool-incomplete cases (see §4) refuse, never impute.

## 4. Keeping 173 symbols off the trade path and the exit path (MEASURED lesson, #23619)
MEASURED (RQ-20261106-d5a1-01 run 42145318852): one unpaced 173-symbol 1h pass through the live connector made 217 calls, 104 came back 429, 82
symbols returned empty. So the ranks must NEVER be built by fetching 173 symbols inside a signal tick.
* A separate, low-priority **pool snapshot refresher** (its own timer / thread, not the trade tick) runs once per closed RTH bar at the decision
  clock, fetches the pool's recent bars through the connector's #23619 non-blocking cooldown (a cooldown means "retry on the next pass", never a
  sleep), computes the 6 pool features for every ETF once, and writes ONE snapshot file (bar close, per-symbol feature rows, symbols covered).
* `ml_entry_eq`'s signal builder only READS that snapshot (a local file), exactly like any cached input: no network on the tick. A snapshot older than
  one decision bar, or covering fewer than `min_pool_symbols` (default 80% of the 173), is a per-trade refusal with a named reason
  (`pool_snapshot_stale` / `pool_incomplete`) — the pipeline keeps running (no halt), the trade is simply not taken.
* The EXIT-evaluation path (`order_monitor`) never calls the feature builder: the model's bracket is fixed at entry (no TP revision, no re-scoring),
  so an open `ml_entry_eq` package is evaluated by the existing generic bracket/stop logic on its own symbol's frame only. A test asserts
  `order_monitor` does not import or call the snapshot reader or any pool fetch.
* The refresher is the ONLY caller that makes the 173-symbol requests, shares the process-wide cooldown with the trading connector, and is paced
  below the data limit; if it falls behind it degrades to stale (refusals), never to blocking the tick.

## 5. Roster and universe
`config/strategies.yaml::ml_entry_eq` (own leg, `execution: live` for the testing floor), rostered on `alpaca_paper` ONLY; its traded set is its own
population record `comms/ml_universe/ml_entry_eq.json` (written by RQ-20261105-e9a1-02's PASS, leg key `ml_entry_eq`, never `ml_entry`). Account-level 1-share
minimum applies (no per-leg override). Fidelity caveat to carry: the harness models the fixed 2/3 ATR bracket, not the live `structure_exit`.

## 6. Order of work
1. Export unit (this PR) -> commit `ml/candidates/ml_entry_eq_v1/model.json` + fixture. 2. Shared pure feature module + parity tests. 3. Refresher +
snapshot reader + signal builder + roster, held Tier-2 PR for the manager's merge. 4. Soak: 1-2 clean paper trades prove the mechanics; cost and
live-vs-backtest are monitored, never the soak's exit (OPERATING-PLAN § 2).

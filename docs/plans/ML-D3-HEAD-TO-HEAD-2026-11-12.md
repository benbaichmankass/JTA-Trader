# D3 entry slot: head-to-heads, rules and demotion signals (2026-11-12)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane ML-PROGRAMME-CONSOLIDATION, step 3 D3 and step 4

**Gates this adds or changes:** none. Nothing here changes a roster, mode, tau or artifact. The demotion signals below are *declared reads*,
not switches; acting on one is the manager's and the operator's call under the existing tiers.

Spec: [`ML-CONSOLIDATION-2026-11-11.md`](ML-CONSOLIDATION-2026-11-11.md). Operator 2026-11-12 (verbatim, p3): *"things get promoted to real money
based on backtesting, shadow on paper is only for something that is demoted and in iteration, not a step on the way to real money"*. So every
comparison below is an offline replay; live/paper fills are monitoring.

## Retirement waves: already done, not redone here

The brief asked for a wave-1 and wave-2 retirement PR. Both already landed on `main` under row `ML-RETIRE-WAVES-20261111` (PRs #25001, #25051,
state `landed_unproven`) on the operator's 2026-11-11 answers a1 *"Retire the 28 with no active manifest now; the 44 after their manifests are
removed"* and a2 *"Accept as proposed"*. `ml/configs/retired/README.md` carries the 2026-11-11 rows, and top-level `ml/configs/` holds 25 manifests
at this head (`ls ml/configs/*.yaml | wc -l`). This lane therefore prepared **no** duplicate retirement PR and did **not** run the archive
system-action. Whether the registry archive ran (the row's done-when) is read from the trainer in the TRAINING_MANIFESTS reading, reported on the row.

## Pair 1, crypto: `ml-decision-entry-v1` (live) vs `ml-decision-entry-v2` (testing, bybit_1)

A pre-registered head-to-head on one window already exists and was read once: **RQ-20261101-b609-01** (rule: n >= 300 decisions and >= 10 symbols;
mean net R >= 0; mean >= the frozen v1's on the same W1 rows; one read, no variant after the result). Result recorded on the v2 artifact:
`w1_verdict: fail`, v2 **-0.1161** net R at n 320 vs frozen v1 **-0.0405** on the same rows. So v2 lost the comparison on its own window and
cost stack. It is a TESTING leg (Stage-1 demo floor), not live: **no live demotion is implied.** The one forward read, RQ-20261101-b610-01, is
`blocked` on a harness defect (reads window S instead of the count-closed fresh window); filed as row `ML-ENTRY-V2-FWD-UNBLOCK`. I wrote no new
v1-vs-v2 unit: a second one on W1 would be refused by the holdout lock and a different window is exactly b610's job.

`ml-decision-entry-v1` and `ml-decision-entry-v1r20261106` are one lineage behind the single served-model pointer (`ml/served/ENTRY_SERVED.json`,
currently the refit). That is a pointer, not an ensemble: one model is live per decision.

## Pair 2, equity: `ml_entry_eq` (v1, tau 0.20, alpaca_paper) vs `ml_entry_eq_struct` (ens5, tau 0.25, alpaca_live + alpaca_portfolio)

Unit **RQ-20261112-ef4c-09**, rule `RULE-RQ20261112ef4c09-EQ-H2H`, registered 2026-11-12 before any run. Harness: new subcommand
`ml_entry_equity.py h2h` (self-test passes; scores the two shipped `model.json` boosters, refits nothing). Same pool, same decision closes, same cost
stack (Alpaca, 5 bps provisional slippage + 0.5 bps regulatory); each model trades under its own live exit.

- **Statistic:** per decision bar in the union of the two trade sets, d = net R of the struct trade minus net R of the v1 trade (0 when a model
  does not trade the bar); mean d with a day-clustered t.
- **Window:** 2025-07-15 to the last complete month, train_end 2025-06-30 (the window both artifacts were graded on). It counts in the
  `ENTRY-EQ-H2H` ledger family.
- **PASS** (struct beats v1): n_union >= 100 and mean d > 0 and clustered t >= 1.3 and struct's own mean net R > 0. **FAIL:** n_union >= 100 and
  any of those fails. **INDETERMINATE:** n_union < 100.
- **Reported, never gating:** v1-only / struct-only / both-fire means (the consensus arm and the IWM/GDX class of bars where only v1 fires), and a
  same-exit control valuing both models' trades under the struct exit, so model and exit are separable.
- **What a FAIL means:** struct has no per-bar advantage over v1 on this window. It is a signal to the manager about a LIVE leg and is
  **reported, not applied**. A tau question for struct is already open as RQ-20261111-207f-02.

## Declared demotion signals per served artifact

Each is a read the ml-review CHECKS layer can compute; none is a mode flip and none fires by itself (Prime Directive, no self-halting).

| served artifact | where | demotion signal (declared 2026-11-12) |
|---|---|---|
| `ml-decision-entry-v1` / `v1r20261106` | bybit_2, bybit_portfolio, prop books | mirror net-of-cost mean net R over the trailing window the mirror already reports is below 0 with day-clustered t <= -2 at n >= 100 **and** the refit is not better on the same replay |
| `ml-decision-entry-v2` | bybit_1 (testing) | already failed W1; stays at the demo floor for the b610 forward read; retire on a b610 FAIL |
| `ml-entry-eq-struct-ens5-v1` | alpaca_live + alpaca_portfolio | RQ-20261112-ef4c-09 FAIL, or mirror net-of-cost mean net R < 0 at day-clustered t <= -2 at n >= 100 |
| `ml-entry-eq-v1` | alpaca_paper (testing) | RQ-20261112-ef4c-09 shows struct beats it (v1 retires unless its v1-only arm has mean net R > 0 at n >= 30) |
| `overlay-td-v1`, `ml-entry-tp-revision-v1`, `exit-head-donchian-1h-v1` | D4 / D7 / D8 | not declared here: no slot baseline exists to measure against (row `ML-SLOT-BASELINES-DECLARE`) |

## D2 regime bake-offs (wave-2 hold)

Eight pre-registered units, one per (symbol, timeframe) with a held REVIEW head: `RQ-20261112-ef4c-01` BTC 15m (v2 vs yz), `-02` BTC 1h (v2 vs yz),
`-03` ETH 1h, `-04` ETH 15m, `-05` MES 1d, `-06` BTC 5m, `-07` ETH 5m, `-08` SOL 5m. Each runs `scripts/research/ml_bakeoff.py` on ONE shard and
ONE purged 5-fold split (embargo 24, tail 60000 rows), log-loss, rule fixed before the run (head beats its baseline by >= +0.002 nats on the CV mean).
The 11 held heads are covered as: BTC 15m v2 + yz, BTC 1h v2 + yz, ETH 1h v1, ETH 15m selfonly, MES 1d v2, BTC 5m v2, ETH 5m v1, SOL 5m v1 = 10, plus
`eth-regime-15m-lgbm-xasset-v1` (needs the unpublished v901 shard; **not** covered, flagged below). Limits stated in each unit: the arms use the
head's numeric features (the categorical `vol_bucket` is left out, as in the c4f1 units), so a PASS is a feature-set read, not a replay of the
served artifact; the 5m shards are trainer-resident (not published); and the consumer test (does gating the leg improve net R after the full
cost stack) is a later step, not part of these units. A log-loss PASS is not edge.

**Open gap:** the xasset heads at 15m (v901 shard) have no published shard, so `eth-regime-15m-lgbm-xasset-v1` is not in a bake-off yet.

## Process audit (step 4), population stated

- **KEEP models in an iteration unit:** matched by model_id string across the 315 non-terminal `research/queue` units: 1 of 15 is named by a unit
  with an `iteration:` block. The match misses units that name a model only through a strategy leg, so it is a floor. Row `ML-KEEP-ITERATION-COVERAGE`.
- **Slot baselines:** declared only for D2 (four Mutts, majority-class predictors, no cost-net metric). Row `ML-SLOT-BASELINES-DECLARE`.
- **Family diversity** (`ml_plan_status.py --diversity`, 2026-11-12): gbdt 77 of 106 registered models (> 60%, reported by the tool, not failed);
  the tool counts manifest ids from before the wave-1 retirement lands in the registry, so re-read it after the archive. `rule_baseline` 14,
  `bayesian_probabilistic` 5, `deep_sequence` 1 (FAIL), `ssl_representation` 1 (FAIL); the families with graded history are mostly
  FAIL/INDETERMINATE. `UNMAPPED:None` has 8 live/shadow manifests: the trainer family map needs an entry (the tool says so).
- **Research SLO** (row text, 2026-11-10): survivors_per_month 0, trials_per_survivor 3457 against a target of 500. Not re-measured here.

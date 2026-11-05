# TICK-DURATION-115S: tick profile, fix, and staged plan (2026-11-04)

> **Doc status:** `live` · category `evidence` · last verified `2026-11-04` · owning row
> [`TICK-DURATION-115S`](../claude/work/checklist/TICK-DURATION-115S.json)

**Gates this adds or changes: none.** Two runtime changes, both cadence/cost
only. No trading decision, gate, switch or refusal is added or changed.

## 1. What the live tick spends (MEASURED)

Source: `GET /api/diag/tick_cost`, `generated_at` 2026-11-04T23:22:25Z, one
process started 21:44:14Z, **37 ticks**.

| quantity | value |
|---|---|
| tick (hook chain) mean / max | 100.8 s / 128.4 s |
| **cycle** (37 ticks over 5,891 s, process start → snapshot) | **159 s** |
| `run_one_tick` mean | 68.8 s |
| `pipeline.signal_build` | 851 calls (23.0 per tick) × 2.035 s = **46.8 s per tick** |
| candle fetches nested in it (`fetchby.signal_build`) | 1,459 × 130.6 ms = 5.15 s per tick (0.22 s per call) |
| ⇒ signal_build time that is NOT fetching | **~1.8 s per call, ~41.6 s per tick** |
| `pipeline.regime_bar_scoring` | 851 × 0.522 s = 12.0 s per tick |
| `order_monitor` (reconciliation half) | 28.4 s per tick |
| — `reconcile_open_trades` / `reconcile_orphan_exchange_positions` / `check_broker_naked_equity_positions` | 6.6 / 6.5 / 6.3 s |
| — `watchdog_stuck_strategies` / `check_broker_naked_bybit_positions` / `reconcile_netting_partial_closes` | 3.3 / 2.4 / 2.3 s |

Arithmetic check: 159 s cycle − 100.8 s tick = 58 s ≈ the 60 s sleep. **The loop
slept a full `TICK_INTERVAL_SECONDS` after every tick** (`src/main.py`, sleep
block), so the evaluation period was ~160 s, not ~115 s.

## 2. Where signal_build's 1.8 s goes (MEASURED, locally)

Harness: the real `multiplexed_intent_signal_builder`, this repo at `main`
b78decb3f, candle fetches stubbed with seeded frames (no venue I/O), cProfile
over 3 symbols (ETHUSDT, SPY, SOLUSDT; BTCUSDT unprofiled warm-up).

- **Before:** 16.7 s profiled. `load_strategy_config` = **43 calls, 15.1 s (90%)**:
  each call re-parsed the 217 KB `config/strategies.yaml` with pure-Python
  `yaml.safe_load` (~100–125 ms unprofiled here), ~14 times per symbol, via
  `_strategy_timeframe_seconds`, `_strategy_symbol_scope`, `_strategy_cfgs` and
  the builders.
- **After the fix:** 1.76 s profiled for the same 3 symbols (**9.5× less**). The
  remainder is a real HTTP read (`oi_feed`, 0.9 s), indicator compute and the
  deep copies (0.2 s for 43 calls).

INFERRED for the VM (not yet observed): signal_build ≈ 5.2 s fetch + ~0.3 s × 23
compute ≈ **12 s per tick, down from 46.8 s**; tick ≈ **66 s**. Monitor and
regime-scoring paths also parse config through the same loaders; how much they
gain is unmeasured until the new counters below report.

## 3. What this PR changes

1. **`src/utils/yaml_parse_cache.py`** — `yaml.safe_load` memoized by SHA-256 of
   the exact text. Callers still read the file on every call (an edit is seen on
   the next call, as before); a hit returns `copy.deepcopy` of the cached tree;
   parse errors are never cached; same loader (no `CSafeLoader` swap). Routed
   through it: `load_strategy_config`, `load_accounts`, `load_accounts_dict`,
   `strategy_registry._load_yaml_with_digest`. Instrumented as
   `config.yaml_parse` (real parses) and `config.yaml_cache_hit` on
   `/api/diag/tick_cost`.
2. **`src/main.py::tick_sleep_seconds`** — sleep to the next wall-clock multiple
   of `TICK_INTERVAL_SECONDS` (+ `TICK_ALIGN_OFFSET_SECONDS`, default 2 s), or
   only `TICK_MIN_SLEEP_SECONDS` (default 5 s) after a tick that overran it.
   With the 60 s interval every 5th boundary is a 5m close, so a tick that fits
   in the interval starts 2 s after every 5m close. INFERRED cycle at a 66 s
   tick: ~71 s (back-to-back + floor), down from 159 s.

## 4. Signals are unchanged (MEASURED)

Two fresh subprocesses, identical seeded candles, frozen clock, separate empty
`DATA_DIR`s, OI feed returning empty in both: arm **raw** monkeypatches the
loaders back to plain `yaml.safe_load`; arm **cached** runs this PR. Each arm
runs `multiplexed_intent_signal_builder` over **all 24 symbols** in the
`accounts.yaml` pull list at **8 frozen timepoints** (2026-11-04 00:00, 04:00,
08:00, 13:00, 14:00, 15:00, 16:00, 20:00Z), carrying state across timepoints in
one process, so debounce/ledger paths run identically in both arms.

**Result: 192 of 192 builds byte-identical** (JSON with sorted keys, every field
of every returned signal: side, price, entry/SL/TP, confidence,
`candidate_signal_packages`, `account_rounds`, meta). Population: 182 `none`,
**10 actionable `buy`** (ETHUSDT ×7, SPYM, SCHA, SPY), 0 errors. Cached arm: 2
real parses, 1,720 cache hits. A first single-timepoint pass (15:00Z, 24
symbols) was also identical. Limits, stated: seeded synthetic candles, not
recorded venue candles; no `sell` occurred in this population; the OI feed was
empty in both arms. The structural argument (§ 3: same pure function on the
same text, private copy per caller) covers what the sample does not.

Plus unit tests: `tests/test_yaml_parse_cache.py` (real configs equal a fresh
parse incl. key order; private copy per call; anchor aliasing preserved; an
edit with the same size AND mtime is seen; errors re-raised and not cached;
bounded; concurrent callers; each routed loader equals its pre-change parse)
and `tests/test_tick_pacing.py`.

## 5. Protective sweeps: cadence (Prime Directive)

No sweep is skipped, gated, reordered or moved. They still run once per tick
inside `run_reconciliation_tick`, in the same order. Their cadence is the cycle:
**159 s measured before → ~71 s INFERRED after** (faster, never slower; floor
5 s between ticks). `check_broker_naked_ib_positions` keeps its own 300 s gate.
Venue request rates: ≥1h candle frames (all IB frames) are cached up to
`CANDLE_CACHE_TTL_MAX_S` (300 s on the VM), so their refetch rate is bounded by
the TTL, not the loop; per-tick broker reads in the sweeps rise in proportion
to the cycle shortening (~2.2×), back toward the 60 s design cadence.

## 6. Why this does not yet hit the detector, and the staged plan

Detector: `tick_cost mean_ms < 30000` over ≥ 20 ticks. INFERRED after this PR:
~66 s. The rest needs order-path concurrency design, staged so each step is one
revertible PR:

- **Stage 2 — reconciliation half off the tick (−28 s).** Run
  `run_reconciliation_tick` on its own daemon thread at a 60 s cadence (pass
  ~28 s). **Not done here because it is unsafe as a plain move:** the reverse
  reconciler's default `ORPHAN_POSITION_POLICY` is `adopt` on first sight, and
  today it can never observe a fill the main thread has not yet journaled
  because both run on one thread. Package → trade row takes up to 7.6 s
  (audit F8, n=40). Concurrent, a pass inside that window adopts a duplicate.
  The design: one `journal_sync` lock held by `Coordinator.multi_account_execute`
  (place + journal) and by each reconciliation pass, which preserves today's
  invariant exactly. Cost: an entry can wait ≤ one pass (~28 s), only when a
  pass is in flight. Needs its own replay test on recorded ticks.
- **Stage 3 — `regime_bar_scoring` (12 s per tick).** Profile on the VM with the
  new counters first. It is labelled observe-only, but it publishes the
  in-process cache `ml_vol_verdict` reads, so moving it off-loop is a decision
  path question, not a free move.
- **Stage 4 — per-symbol fetch concurrency** (5.2 s per tick of fetches), only
  if stages 2–3 leave the tick above 30 s.

Projected after stages 2–3: ~66 − 28 − 12 ≈ **26 s** (INFERRED).

## 7. How to observe this landed

After deploy, `GET /api/diag/tick_cost` over ≥ 20 ticks of one process:
`pipeline.signal_build` mean ≲ 0.6 s (was 2.035 s); `config.yaml_parse` n ≈ a
handful per config edit, `config.yaml_cache_hit` n in the hundreds per tick;
tick `mean_ms` ≈ 60–70 s; cycle = (snapshot `generated_at` − `process_started_utc`)
/ `ticks_measured` ≈ 70 s (was 159 s).

## 8. Observed after deploy (MEASURED, 2026-11-05)

Merged as #23029 (`74b059c25`); trader running `3f61e8d32`, which contains it.
`/api/diag/tick_cost` at 02:26:47Z, **one process started 02:04:06Z, 23 ticks**:

| quantity | before (37 ticks, 2026-11-04) | after (23 ticks) |
|---|---|---|
| tick mean / max | 100.8 s / 128.4 s | **48.5 s / 82.6 s** |
| cycle (snapshot − process start) / ticks | 159 s | **59.2 s** |
| `run_one_tick` | 68.8 s | 20.9 s |
| `pipeline.signal_build` per call / per tick | 2.035 s / 46.8 s | **0.246 s / 5.66 s** |
| `pipeline.regime_bar_scoring` per tick | 12.0 s | 9.6 s |
| `order_monitor` per tick | 28.4 s | 26.2 s |
| `config.yaml_parse` / `config.yaml_cache_hit` | — | 2 / 6,591 (+459 off-loop) |

Better than § 2's inference (tick ~66 s, cycle ~71 s): the monitor and regime
paths also gained. `journalctl` since 02:04Z (complete scan, 11,823 lines): 0
`Tick failed`; the post-tick sleeps read 9–16 s, i.e. ticks start on the minute
grid. Heartbeat age 37 s at 02:28Z. Protective sweeps ran every tick, so their
cadence is now ~59 s.

**Detector not met** (48.5 s vs < 30 s). What remains is `order_monitor`
(26.2 s; row `TICK-STAGE2-RECONCILE-OFFTICK`) and `regime_bar_scoring` (9.6 s;
row `TICK-STAGE3-REGIME-SCORING`).

**New, contained, cause not established:** one sqlite `database is locked`
burst, 02:20:41–02:21:04Z. Three monitor sweeps and one `venue_protection_snapshot`
write each failed once and were retried on the next pass. A complete scan of
2026-11-04 21:44–23:22Z (21,226 lines) had none. Recorded on
`TICK-STAGE2-RECONCILE-OFFTICK`, whose design adds a DB-writing thread.

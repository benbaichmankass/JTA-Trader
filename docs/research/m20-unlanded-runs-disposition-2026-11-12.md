# M20 unlanded result runs — causes and dispositions (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Lane `RESEARCH-LOSS-M20-UNLANDED`, dispatched by AM-ML for Manager Session 2026-11-11a. Trigger: research-loss-detector run 43297292915
(`docs/claude/work/RESEARCH-LOSS-RECEIPT.json`), question B, **10 unlanded runs, all `m20-exit-lever-sweep.yml`**.
Population: the 10 runs named below, out of 108 completed runs of 7 research-result workflows since 2026-10-29 (the detector's own count).

## What was measured
Each run's failed job was read (job logs or the run's log archive), then mapped to its unit by `last_dispatched_at`
(each unit's stamp is within ~2 min of its run's `created_at`). **None of the 10 produced a result**: the failure is upstream
of the sweep's `verdicts.json`, so no artifact exists and there is nothing to re-land.

| run | date | leg | unit | failed job | disposition |
|---|---|---|---|---|---|
| 42256673587 | 2026-11-06 | `ml_entry_eq` | RQ-20261106-003 | `plan` | retired |
| 41983651204 | 2026-11-05 | `qld_trend_long_1d` | RQ-20261004-658 | `sweep` | re-armed |
| 41978235919 | 2026-11-05 | `ml_entry_v2` | RQ-20261105-002 | `plan` | retired |
| 41970551893 | 2026-11-05 | `ml_entry` | RQ-20261105-001 | `plan` | retired |
| 41763381661 | 2026-11-04 | `mes_trend_long_1d` | RQ-20261003-008 | `sweep` | re-armed |
| 41195608647 | 2026-10-31 | `turtle_soup` | RQ-20261031-018 | `plan` | retired |
| 41187215930 | 2026-10-31 | `e4_oi_shock_1h` | RQ-20261031-014 | `plan` | retired |
| 41068790597 | 2026-10-30 | `iaum_pullback_1d` | RQ-20260929-007 | `sweep` | re-armed |
| 40994427469 | 2026-10-30 | `fade_breakout_4h` | RQ-20261030-002 | `plan` | retired |
| 40978648245 | 2026-10-30 | `claude_desk` | RQ-20261029-014 | `plan` | retired |

## Cause 1 — 7 runs: the generator minted units for legs the sweep cannot route (still live on main until this PR)
`plan` fails with `::error::legs with no family/harness: [<leg>]`. Reproduced on main: `classify(leg)` is `None` for all seven
(`ml_entry_eq ml_entry_v2 ml_entry turtle_soup e4_oi_shock_1h fade_breakout_4h claude_desk`). The `m20-exit-lever` template drew from
`live_roster_legs` (every roster leg); the e35 template had already been fixed for the same class (`live_roster_legs_e35_sweepable`).
These were the only 7 queued m20 units on an unroutable leg (checked over all 101 m20 units: 44 queued routable, 7 queued unroutable,
25 done, 15 retired, 9 multi-leg or no leg).
**Fix:** new source `live_roster_legs_m20_sweepable` (asks the sweep's own `classify`), template switched; the 7 units retired with reason.

## Cause 2 — 3 runs: HoldoutLeak crash on thin legs (already fixed on main)
`Sweep this leg` crashed: `HoldoutLeak: discovery window ends at 2025-07-01, past the last discovery day 2022-11-10` (qld; run 41983651204 log).
The fallback split ignored the holdout cap. Fixed earlier on main under MECH-FOLLOWUPS-1105 b (`split_beyond_holdout`, contained per leg).
That fix had no test; this PR adds one (extract -> summarize on a `split_beyond_holdout` verdict lands a `measured` record).
**Expect, not assume:** a re-fire lands an `indeterminate / measured` record ("none is a gradeable cell"), **not** a sweep: these legs are too thin
(qld: 35 lifetime trades). The three units are re-armed (`last_dispatched_at: null  # re-armed ...`) so that record lands.
Observed only on a synthetic verdicts.json, not on a real re-run.

## Cause 3 — PI-20261112-TE74WG5Z-0005: a plan-time failure wrote no `producer_failed` row
`research_result` runs under `always()` but read legs only from `plan.outputs.legs`, empty when `plan` dies, so it exited 1 with
"no dispatched legs and no rows". **Fix:** `m20_sweep_result.fallback_dispatched_legs` reads the dispatch input, then the sentinel `legs:` line
(the two sources `plan` reads), so a plan-time failure now emits `producer_failed` per leg asked for. No census-default fallback by design.
**Not verified on a live run** (workflow change; takes effect on the next dispatch). The plan job still fails loudly.

## How the detector will see this
* Question B counts a run as landed only when `research/results/**/<run_id>.jsonl` exists. These 10 never will, so B stays red for them until each
  ages out of the 14-day lookback (2026-11-13 .. 2026-11-20), unless closed. `docs/claude/work/RESEARCH-LOSS-DISPOSITIONS.json` now records all 10
  (reason required; counted in the population line as "closed by a recorded disposition", not dropped). The next detector run after this lands should read B clean.
* Future plan-time failures should land a `producer_failed` row, so B will not flag them.

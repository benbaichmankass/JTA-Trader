# Monthly cost / infra review — 2026-10-05..2026-11-04

> **Doc status:** `live` · category `review` · lane `COST-INFRA-REVIEW` (job `cost-infra-review`, `config/reset_protocol.yaml`) · Gates: none. Report only; nothing was disabled, deleted or changed.

Provenance tags: **MEASURED** (read this session), **ESTIMATED** (derived), **UNKNOWN** (could not look — not zero).

## 1. Lane dollars — UNKNOWN
- `cost_usd` is not returned by `list_sessions`/`get_session` from a lane (checked: 100 sessions returned, fields contain no cost; the list spans only 2026-11-02..11-04, so even the month's lane *count* is UNKNOWN). `spend_meter.py --section-5` agrees: per-lane dollars `not_observed`.
- Weekly plan %: the only reading in the window is the 0.0 % reset reading of 2026-11-04T18:00Z; the earlier series is not in the window. No month figure can be stated; no ceiling-vs-actual comparison is possible. Filed as F1.
- Ceilings declared for the month's reset-protocol jobs (`ceiling_usd`): weekly 15+20+16+16+12+12+3 per week = 94/wk, monthly 30+10+8 (several marked PROPOSED). These are ceilings, not spend.

## 2. CI minutes — $0 in dollars; the cost is the 20-slot cap
- Repo is public (MEASURED, `gh api` visibility=public); 244 of 246 `runs-on` lines are `ubuntu-latest`, so hosted minutes are free. The binding cost is queueing: `comms/ci/compute-allocation-inventory-2026-11-03.json` (MEASURED/ESTIMATED as labelled there; 7-day window 2026-10-27..11-03, 60,244 runs): ~3,362 job-hours/week, **merge_path 2,211 h (66 %)** — `pytest-run` 1,184 h, `Guards` 798 h; automation 635 h; hosted cap observed 20; queue-wait q95 38.6 min (pytest-run) / 48.2 (Guards) / 87.1 (automation).
- **Scheduled cadence is not delivered (MEASURED).** `live-review-wake` is `*/5` (nominal ~8,640 runs/30 d, ESTIMATED); GitHub reports **41** runs in the window (all schedule). The cron estimate for the whole schedule set (61 entries, ~24.5k nominal runs/30 d) is therefore an upper bound; real delivery is a small fraction. Anything that relies on a tight cron cadence (live-review wake, 15-min watchdog) is not getting it. F2.

## 3. Routines/workflows that cost slots without being read
From the last ≤100 runs of each scheduled workflow in the window (page-limited sample, MEASURED; wall = updated−run_started):
| workflow | sample | red | wall min | note |
|---|---|---|---|---|
| research-watchdog | 100 sched | **69** | 505 | chronic red: alarm that fires every cycle |
| research-loss-detector | 62 | **17** | 1,529 (~25 min/run) | red + long for a "detector" |
| ml-data-export-kaggle | 22 | **17** | 222 | 17/22 red; last 3 of 6 green |
| mirror-orphan-watch | 27 | 9 | 118 | |
| research-slo | 24 | 4 | 1,122 (~47 min/run) | longest per-run of any schedule |
| counterfactual-grade-closed | 24 | 1 | 651 (~27 min, hourly) | |
| forecast-grade | 12 | 0 | 372 (~31 min, hourly) | |
| news-gdelt-panel | 19 | 1 | 410 (~22 min/day) | |
Red here may be a working alarm; I did not read their failure payloads (UNKNOWN whether the red is signal or breakage). A chronic-red alarm that no lane acts on is zero-information either way. F3.

## 4. VM / OCI footprint (compute_util_ledger, 31 days per host, MEASURED)
- Dollars: not billed on this evidence — tenancy shows 4/24 A1 in use; billing console not readable (UNKNOWN; operator reports no charges).
- **Trainer**: CPU p95 ≥ 90 % on 31/31 days (median 100 %), disk 44 % (10-13) → 81 % (11-04), +24 pp in the last 4 days.
- **IB gateway disk: 75 % (11-01) → 100 % (11-02) → 93–94 % now.** It carries equities/futures execution. F4 — the highest-urgency item in this report (existing TRAINER-DISK lane covers only the trainer).
- Live: CPU p95 ≥ 90 % on 10/31 days, median 83 %; disk 87 % (11-02) → 65 % (11-04), i.e. something was cleared.

## 5. Nothing-spends-API-credits check — PASS (static)
No `import anthropic`/`from anthropic` in any `.py` outside docs/tests (grep over repo; probe pattern also matches the `generator.py` mentions, so it can see positives); `generator.py` anthropic mode and `run-desk-judge` hard-refuse. UNVERIFIED: whether the VM `.env` still holds a funded `ANTHROPIC_API_KEY` (not readable by this lane) — F5, advisory only.

## Findings → disposition
F1 lane-dollar visibility → pipeline. F2 cron under-delivery → pipeline. F3 chronic-red/long-running routines → pipeline (kill-or-cadence proposal for the manager). F4 gateway disk → pipeline, flagged to manager for operator. F5 VM key residue → pipeline (operator Tier-2). CPU saturation of trainer/live → covered by F4's row note. No infra changed.

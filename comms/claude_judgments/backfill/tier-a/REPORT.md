# CJ-7 tier-A backfill: blind-then-reveal grades for 567 packages

Row `CJ-7-BACKFILL-SCOPE` · lane `CJ-7-BACKFILL` · 2026-10-26 · operator cap "$15 once + $3/week" (popup 2026-10-26 ~19:01Z).
Every figure is MEASURED from the files here unless marked INFERRED. Population and method: pilot REPORT
`comms/claude_judgments/pilot/cj3-pilot-r1/REPORT.md` § 2, same `blind_grade.py` select/packets/ingest, same briefs.

## 1. What was done

- Population: the pilot's 617 eligible packages (journal re-read 2026-10-26, identical counts to the pilot) minus the
  50 already graded = **567**. Note: the pilot's "tier A 695" counted any date; the operator's wording
  (decided >= 2026-07-01) gives 617 total. The 78 earlier packages were NOT graded.
- 12 masked batches (47-48 packets); `find_leaks` refused none. Fresh Sonnet grader per pass on an orphan branch
  holding only the brief and packets; blind first, reveal second.
- Ingested into `comms/claude_judgments/{blind,revealed}_grades.jsonl`: **567 blind, 496 revealed** new rows
  (stores now 617 / 546). `blind_grade.py validate`: 0 problems.
- **71 packets have no reveal grade** (batch 07 whole, batch 06 first 24): all sessions on them stopped with an
  API safeguard error (`reasoning_extraction`) before writing anything, 5 sessions, one bisection. Cause unknown.
  Their blind grades are valid and ingested.

## 2. Cost (MEASURED, `usage.cost_usd`)

| item | sessions | $ |
|---|--:|--:|
| blind passes | 12 | 6.4336 |
| reveal passes kept | 11 | 4.6834 |
| reveal sessions that stopped on the safeguard (no rows) | 8 | 1.2507 |
| **total** | 31 | **12.3677** (cap 15.00) |

Per grade: blind $0.0113 (n=567), reveal $0.0094 (n=496), vs the pilot's $0.0072 / $0.0086 at n=50.
The cap was not the stopping reason; the remaining 71 reveals are blocked by the safeguard, not by budget.
Rejected (code-generated) passes: **0**.

## 3. Quality gates applied to every pass

One row per packet in packet order; enums valid; blind theses 47/47 or 48/48 distinct per batch; reveal notes
likewise; at least three distinct grades in every batch; reveal changed 1-16 grades per batch (the pilot's rejected pass changed 0
with templated text; none of these had templated text). Graders' own summaries say rows were written by hand.

## 4. Diagnostic at n >= 150 (NOT CJ-4: not pre-registered, not a validation)

Spearman of the blind grade vs journal net R, Fisher 95% CI, over all 617 stored blind rows:

| score | rho [CI] |
|---|---|
| expected_r | -0.259 [-0.331, -0.184] |
| p_win | -0.391 [-0.456, -0.322] |
| grade_score | -0.233 [-0.306, -0.157] |
| strategy confidence | -0.020 [-0.099, +0.059] |

**Do not read that as "the teacher is anti-predictive."** It is driven by a label problem found on checking:
148 of the 617 packages have a stop distance under 1 ATR (`bracket.risk_atr < 1`), and in that cohort the journal's
net R is on a tiny risk basis: win rate 0.858, median net R +5.66, mean +35.9 (max 3,587), versus 0.275 / -0.83 /
-0.47 for the other 469. Several of the 148 have a stop on the wrong side of the entry in the masked frame,
which the graders flagged and graded down. The pattern is consistent with the package's recorded SL not being the
initial stop (INFERRED; root cause not established). Split by that post-hoc threshold:

| cohort | n | expected_r | p_win | grade_score | strategy confidence |
|---|--:|---|---|---|---|
| risk_atr >= 1 | 469 | +0.117 [+0.026, +0.205] | -0.028 [-0.118, +0.063] | +0.067 [-0.024, +0.157] | +0.025 [-0.066, +0.115] |
| risk_atr < 1 | 148 | -0.243 [-0.389, -0.085] | -0.245 [-0.391, -0.087] | -0.174 [-0.326, -0.013] | +0.040 [-0.122, +0.200] |

The threshold was chosen after seeing the artifact, so the clean-cohort row is itself exploratory. It shows weak
or no signal, as at n=50. `p_win` is miscalibrated in both cohorts (Brier 0.284 vs 0.243 for the base rate over
all 617). CJ-4 must define its net-R label exclusion BEFORE it reads any result (filed as a pipeline row).

## 5. Weekly cadence (proposed, NOT created): routine text

> Weekly CJ-7 forward grade. Pull `journal?table=trades` and `order_packages` (scripts/ops/diag_fetch.sh, pages of
> 1000). Run `blind_grade.py select --since 2026-07-01 --n 100000`, drop every `order_package_id` already in
> `comms/claude_judgments/blind_grades.jsonl`, and keep packages whose trade closed after the newest
> `closed_at` already graded. If none, stop. Build packets, run fresh-Sonnet grader sessions exactly as
> `comms/claude_judgments/backfill/tier-a/` did (orphan branch, 47-50 packets per session, blind then reveal), apply
> the § 3 gates, ingest, validate, land by self-landing PR. Read `usage.cost_usd` per session; STOP at $3 cumulative for
> the week and record where. Do not grade tiers B-D.

Expected load (INFERRED from the pilot's ~70 new single-leg closes a week): ~70 x ($0.0113 + $0.0094) = ~$1.5, plus a
few retries for the safeguard error: under the $3 cap. Tooling gap: `select` has no `--exclude-graded`; the routine
does it by set difference.

## 6. Pre-cutoff

`pre_cutoff` is `null` on every row: the grader's knowledge cutoff is not known to this lane. All 567 decisions are
2026-07-01 or later.

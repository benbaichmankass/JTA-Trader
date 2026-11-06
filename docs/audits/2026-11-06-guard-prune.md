# GUARD-PRUNE: every CI guard with its 90-day fire count, and proposed deletions

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Lane `GUARD-PRUNE` (dispatched by Manager Session 2026-11-05b, operator popup 2026-11-06 ~00:30Z). Row [`GUARD-PRUNE`](../claude/work/checklist/GUARD-PRUNE.json). Source: [`2026-11-01-from-scratch/AUDIT.md`](2026-11-01-from-scratch/AUDIT.md) §§ 6-8.
> **Gates this adds or changes: none.** Nothing is deleted by this document. **Deleting a guard needs the operator's approval of the list.**

## Verdict

- 130 guards are registered in `scripts/ci/run_guards.py` (all run inside the one `Guards` job). **68 fired at least once** in the window; **62 never did**.
- Of the 62: **27 proposed DELETE** (0 fires and no money, execution or evidence protection), **16 REVIEW** (0 fires, arguably protective of evidence or an operator ruling; the operator decides), **19 KEEP** (0 fires is the point: they guard orders, sizing, stores or secrets).
- That would take the registry from 130 to 103 on the first cut. The audit's target of ~15-20 money-protecting guards needs a second pass, below ("Guards that fire a lot but protect paperwork"), which this lane flags and does not propose to delete, because they fire.
- 16 further guard names appear in the logs but are no longer registered: the registry has already shrunk by deletion; nothing to do for those.

## How it was measured (population, and what could not be looked at)

- **Population.** Every `Guards` workflow run (`guards.yml`) with conclusion `failure`, created 2026-08-08 to 2026-11-06 (90 days), listed by one-day windows through the Actions API: **3,173 failed runs** (2,886 pull_request, 283 push to main, 3 dispatch, 1 schedule).
- **A "fire"** is one failed run whose job log carries `--- <guard>: FAIL`. A run can fire several guards; the counts sum to 3,602 over 3,173 runs. The `distinct branches` column counts head branches, so a PR re-pushed ten times is not read as ten catches.
- **Could not look: 496 of 3,173 failed runs (15.6%)**: the run log returns HTTP 404 (expired). All are dated 2026-09-01 to 2026-10-24 (471 in September, 25 in October). **Every count below is therefore a lower bound**, and September is the thinnest month. Parsed: 2,677 runs.
- **Not measured: the denominator per guard.** Only failed runs were read. Successful runs' logs were not fetched, so how often each guard was *relevant* (many are path-scoped and SKIP on most PRs) is unknown. A guard with 0 fires may simply never have been triggered by a diff. The run-total per window is capped by the API at 2,500, so no pass-rate is claimed.
- **A fire is not a catch of a real defect.** The log says the guard went red, not that the diff was wrong. Several top counts are paperwork the author had not yet filed. A zero is not proof of protection either: it is "never red in the readable population".
- Reproduction: list failed runs per day with `gh api repos/<repo>/actions/workflows/guards.yml/runs?status=failure&created=<day>..<next>`, download each `actions/runs/<id>/logs`, grep `^--- (\S+): FAIL`. Scripts and raw tallies were kept in the lane scratchpad and are not committed.

## Proposed deletions (the list for the operator)


### DELETE: 0 fires, no protective role

| guard | script | reason |
|---|---|---|
| `stale-in-flight` | `scripts/ci/check_stale_in_flight.py` | register hygiene for in_flight rows (its earlier name stale-in-flight-guard fired 7, 0 since the rename) |
| `attention-watch` | `scripts/ops/attention_watch.py` | tests for a work-system notifier script; protects nothing on the trade path |
| `blocker-watch` | `scripts/ops/blocker_watch.py` | tests for a register-hygiene watcher; the watcher itself can stay, its CI guard adds no protection |
| `review-followthrough` | `scripts/ops/review_followthrough.py` | tests for a follow-through report script; reporting, not protection |
| `retired-backlog-paths` | `scripts/ci/check_retired_backlog_paths.py` | bans naming registers that are archived; the registers are gone, nothing can resurrect them silently |
| `checklist-readers-guard` | `scripts/ci/check_checklist_readers.py` | refactor-completion guard (nothing reads the old monolith path); migration is done |
| `checklist-store-guard` | `scripts/ops/checklist.py` | register plumbing tests; no money or execution protection |
| `reset-protocol-guard` | `scripts/ops/reset_protocol.py` | validates the weekly-reset manager ritual; process |
| `soak-registered-guard` | `scripts/ci/check_soak_registered.py` | checks soak logs have alarms; soak is now 1-2 mechanical trades (soak-contract-guard covers the rule) |
| `spend-meter-guard` | `scripts/ops/spend_meter.py` | self-test of a spend-reporting script; reporting |
| `schedule-guard` | `scripts/ops/render_schedule.py` | renders a schedule page; presentation |
| `pytest-skip-attribution-guard` | `scripts/ci/summarize_pytest_skips.py` | summarises pytest skips; advisory, never gates |
| `arch-doc-guard` | `scripts/arch_doc_guard.py` | docstring says "soft-warning helper"; does not fail a PR |
| `guard-glob-coverage-detector` | `scripts/ci/check_guard_glob_coverage.py` | a guard about guards; checks other guards trigger on the files they read |
| `roadmap-status-glyph-guard` | `scripts/check_roadmap_status_glyphs.py` | cosmetic: status glyph leading a roadmap table cell |
| `programme-coverage` | `scripts/research/programme_coverage.py` | research-plan bookkeeping: does each plan question have a tree node |
| `harness-dispatch-no-fixture-default-guard` | `scripts/ci/check_harness_dispatch_no_fixture_default.py` | one-off E7 orphan-harness defect; fixed class, single script |
| `infra-workflows-single-owner` | `scripts/ci/check_infra_workflows_single_owner.py` | docstring says REPORT-ONLY; cannot fail a PR |
| `manifest-scope-constants` | `scripts/ci/guard_selftests.py` | script is the shared guard_selftests.py (self-tests); no gating logic of its own |
| `selftest-wiring-guard` | `scripts/ci/check_selftest_wiring.py` | a guard about guards; checks self-tests run |
| `diag-relay-render-guard` | `scripts/ops/diag_relay_render.py` | presentation of diag relay output |
| `lever-evidence-flag-guard` | `scripts/ops/lever_evidence_flag.py` | annotation flag on a lever-reachability file; research bookkeeping |
| `guard-selftest-coverage` | `scripts/ci/check_guard_selftest_coverage.py` | a guard about guards; measures self-test coverage |
| `lane-reconcile-guard` | `scripts/ops/lane_reconcile.py` | reconciles checklist rows against live lanes; process |
| `manager-pacing-guard` | `scripts/ci/check_manager_pacing.py` | asserts manager skill text still says "operating loop"; guards prose, not behaviour |
| `timestamp-comparison-guard` | `scripts/ci/guard_selftests.py` | script is the shared guard_selftests.py (self-tests); no gating logic of its own |
| `mfe-parity-instrument-guard` | `scripts/research/m31_mfe_parity.py` | tests one research script, m31_mfe_parity.py |

### REVIEW: 0 fires, protective role arguable (operator judges)

| guard | script | reason |
|---|---|---|
| `priority-fallback-distribution` | `scripts/ci/check_priority_fallback_distribution.py` | protects live arbitration order; 0 fires but touches the order path, keep unless operator says otherwise |
| `live-review-records-guard` | `scripts/ci/check_live_review_records.py` | schema for LTR records; delete only if the desk/LTR STOP in audit section 6 is adopted |
| `desk-records-guard` | `scripts/ci/check_desk_records.py` | schema for desk records; same condition as live-review-records-guard |
| `claude-judgments-guard` | `scripts/ci/check_claude_judgments_manifests.py` | ML manifest lint for the claude_judgments family; delete if that family is retired |
| `async-route-blocking-guard` | `scripts/ci/check_async_route_blocking.py` | protects the live API event loop (RISK-3); keep unless the API is rewritten |
| `matrix-bracket-values` | `scripts/ci/check_matrix_bracket_values.py` | one of four exit-matrix agreement guards; two siblings fired (6 and 5), this one never; consolidate the four |
| `candle-fixture-variance-guard` | `scripts/ci/check_candle_fixture_variance.py` | protects backtest evidence quality (degenerate candle files); research integrity |
| `corpus-row-floor-guard` | `scripts/ci/check_corpus_row_floor.py` | protects backtest evidence quality (thin corpora); research integrity |
| `news-feed-coverage-guard` | `scripts/ci/check_news_feed_coverage.py` | protects against a traded symbol with no news-feed disposition; borderline, low cost |
| `risk-basis-agreement` | `scripts/ci/check_risk_basis_agreement.py` | stops a backtest sizing at a different risk basis than live; evidence integrity |
| `cost-model-single-owner` | `scripts/ci/check_cost_model_single_owner.py` | one owner for fee constants; protects cost-stack evidence integrity (the audit KEEPs the cost module) |
| `tp-venue-cap-single-owner` | `scripts/ci/check_tp_venue_cap_single_owner.py` | single owner of the TP clamp; touches the order path |
| `no-action-rate-cap-guard` | `scripts/ci/check_no_action_rate_cap.py` | enforces an operator ruling (2026-10-29: no per-bar/per-window action caps); a rule guard, so the operator decides |
| `grading-freshness` | `scripts/ci/check_grading_freshness.py` | alert-only freshness of the graded hop (JC-SA-01); protects the trade-pipeline close-out loop; fold into scoreboard liveness |
| `grader-freshness` | `scripts/ci/check_grader_freshness.py` | belongs to row GRADE-EVERYTHING-CONTINUOUSLY; decide with that row |
| `training-population-guard` | `scripts/check_training_population.py` | ML integrity ("no decision head silently trains live-only"); keep while ML-DECISION-MODELS runs |

### KEEP: 0 fires, protects orders / sizing / stores / secrets

| guard | script | reason |
|---|---|---|
| `account-class-guard` | `scripts/check_account_class.py` | every account carries a valid class; stops a mislabelled real-money account |
| `roster-symbol-reachability` | `scripts/ci/check_roster_symbol_reachability.py` | a rostered leg's symbol must be reachable, or the leg silently never trades |
| `symbol-resolver-guard` | `scripts/ci/check_symbol_resolver.py` | single definition of which symbols an account trades |
| `canonical-db-resolver` | `scripts/check_canonical_db_resolver.py` | stops a second journal DB (the 2026-05-16 orphan-backfill failure) |
| `workflow-push-target-guard` | `scripts/ci/check_workflow_push_target.py` | no workflow pushes straight at a protected branch |
| `env-gate-guard` | `scripts/check_env_gate_in_diff.py` | enforces "no third gate / no default-off *_ENABLED flag" (CLAUDE.md two-gates rule) |
| `workflow-vm-literal-guard` | `scripts/ci/check_workflow_vm_literals.py` | no literal VM address in public workflow logs (security) |
| `json-extract-guard` | `scripts/ci/check_json_extract_guarded.py` | SQL json_extract must be json_valid-guarded; a bug class hit more than once |
| `json-notes-cap-guard` | `scripts/ci/check_json_notes_cap.py` | forbids char-slice truncation of json.dumps (malformed journal JSON) |
| `layer-guard` | `import-linter` | import-linter layering of the trader |
| `pairs-sizing-basis-guard` | `scripts/ci/check_pairs_sizing_basis.py` | pairs sleeve must size off the canonical risk basis |
| `strategy-decision-record` | `scripts/ci/check_strategy_decision_record.py` | strategy config changes carry a decision record (Tier-3 trail) |
| `prop-roster-gate-guard` | `scripts/ci/check_prop_roster_gate.py` | prop legs clear a superset of the real-money bar (operator 2026-10-15) |
| `strategy-status-guard` | `scripts/ci/check_strategy_status.py` | a leg is on exactly one of general paper / real money + mirror |
| `provenance-consumer-guard` | `scripts/check_provenance_consumers.py` | a provenance signal must have a consumer (measured/estimated/fabricated) |
| `qty-legalization-guard` | `scripts/check_qty_legalization_guard.py` | venue minimum quantity is single-homed (order sizing) |
| `soak-doctrine-guard` | `scripts/check_soak_doctrine.py` | no live doc/skill teaches a soak longer than 1-2 trades (operator 2026-10-15) |
| `strategy-risk-guard` | `scripts/check_strategy_risk_field_in_diff.py` | per-strategy risk field cannot be removed silently |
| `writer-conformance-guard` | `scripts/check_writer_conformance.py` | no non-canonical writer of canonical stores |

Notes on the DELETE rows: deleting a registry entry in `run_guards.py` does not delete its script or tests; the scripts that are also used elsewhere (`scripts/ops/*`) stay. `guard-liveness` (7 fires) is kept, so the audit-of-guards concern is not left unwatched. The three "guards about guards" and the two shared self-test holders would go together; `guard_selftests.py` keeps its other entries. Removing `soak-registered-guard`, `checklist-*` and `lane-reconcile-guard` ends CI enforcement of registers the work system still uses; if the operator prefers CI to keep owning those, move them to REVIEW.

## Guards that fire a lot but protect paperwork (flagged, NOT proposed for deletion)

These meet the audit's "process, not money" description yet fire, so by the lane's rule they are outside the deletion list. Their fire counts are friction, not protection; the operator may want to reconsider them under the audit's STOP "New guards, registers and process docs".

| guard | fires | distinct branches | what it enforces |
|---|--:|--:|---|
| `pr-landing-guard` | 776 | 603 | Every PR declares its TIER and how it intends to LAND — and the declaration is checked. WHY THIS EXISTS ------ |
| `roadmap-map-guard` | 233 | 201 | THE ROADMAP LOOP'S CHECKABLE ARTEFACT: milestone <-> checklist row <-> queue unit. WHY (operator, 2026-10-11,  |
| `soak-contract-guard` | 230 | 209 | soak-contract-guard — nothing enters a soak without a MECHANICAL definition of done. Operator, 2026-10-04: "we |
| `same-symbol-allocation-guard` | 198 | 5 | same-symbol-allocation-guard — legs sharing one (account, symbol) need a KNOWN allocation, not a name tiebreak |
| `document-index-guard` | 116 | 96 | document-index-guard — the register cannot silently stop being true. WHY. On 2026-09-07 a manager reported roa |
| `pipeline-guard` | 102 | 66 | THE FOLLOW-THROUGH PIPELINE — the thing that pulls work to a finish. WHY THIS EXISTS, in the operator's words  |
| `claim-basis-guard` | 92 | 76 | claim-basis-guard: a NEW backlog row asserting quantitative evidence must carry a parseable denominator (P2.5  |
| `operator-owed-guard` | 81 | 46 | operator-owed guard — a question handed to the operator may not be CARRIED FOREVER. ⚠️ THIS IS PART (d), THE P |
| `manager-scope-guard` | 92 | 62 | A manager commit that does a worker's item FAILS — named by commit and path. WHY THIS EXISTS, AND WHY IT IS NO |
| `research-tooling-selftests` | 75 | 72 | Every row in the ping queue must render to more than its event label. WHY THIS IS A GUARD AND NOT A TEST — the |
| `stated-population-guard` | 57 | 44 | A quantitative claim in a doc must state its population. ⚠️ 2026-09-22 (E45): this used to read "in a doc **or |
| `mandate-autoland-guard` | 44 | 24 | The ONE route by which a PR lands ITSELF while touching a real-money roster. Operator decision, 2026-09-25 ("B |

Observation: `same-symbol-allocation-guard` shows 198 fires, 193 of them on **push to main** from 5 branches (last 2026-11-01), i.e. a red main that stayed red across many runs, not 198 catches. Count by distinct branch before reading any fire count as protection.

## All guards that fired, by fires (registered at HEAD)

| guard | fires | distinct branches | on push to main | last fire |
|---|--:|--:|--:|---|
| `pr-landing-guard` | 776 | 603 | 0 | 2026-11-05 |
| `roadmap-map-guard` | 233 | 201 | 8 | 2026-11-05 |
| `soak-contract-guard` | 230 | 209 | 6 | 2026-11-05 |
| `ruff-lint` | 230 | 173 | 0 | 2026-11-05 |
| `same-symbol-allocation-guard` | 198 | 5 | 193 | 2026-11-01 |
| `document-index-guard` | 116 | 96 | 0 | 2026-11-05 |
| `pipeline-guard` | 102 | 66 | 21 | 2026-10-28 |
| `claim-basis-guard` | 92 | 76 | 0 | 2026-11-05 |
| `manager-scope-guard` | 92 | 62 | 0 | 2026-11-05 |
| `operator-owed-guard` | 81 | 46 | 10 | 2026-11-05 |
| `research-tooling-selftests` | 75 | 72 | 0 | 2026-11-05 |
| `silent-empty-guard` | 63 | 54 | 0 | 2026-11-05 |
| `stated-population-guard` | 57 | 44 | 0 | 2026-11-04 |
| `diagnostic-provenance-guard` | 57 | 46 | 0 | 2026-11-05 |
| `unwired-artifact-guard` | 55 | 48 | 0 | 2026-11-05 |
| `mandate-autoland-guard` | 44 | 24 | 21 | 2026-09-29 |
| `trainer-capture-watch-guard` | 36 | 28 | 3 | 2026-11-02 |
| `research-results-guard` | 29 | 7 | 0 | 2026-10-29 |
| `impossibility-claim-guard` | 28 | 22 | 0 | 2026-11-01 |
| `research-queue-autonomy-selftests` | 24 | 8 | 0 | 2026-10-13 |
| `trader-import-closure` | 19 | 18 | 0 | 2026-11-04 |
| `canonical-config-loaders` | 19 | 17 | 0 | 2026-11-02 |
| `research-queue-dispatch-liveness` | 19 | 14 | 6 | 2026-10-10 |
| `collapsed-state-guard` | 19 | 15 | 0 | 2026-10-28 |
| `cadence-liveness` | 15 | 14 | 1 | 2026-11-03 |
| `workflow-catalog` | 14 | 14 | 0 | 2026-11-05 |
| `strategy-coverage-guard` | 14 | 9 | 0 | 2026-11-01 |
| `artifact-caveat-guard` | 11 | 10 | 0 | 2026-10-04 |
| `research-queue-design-fields-guard` | 11 | 10 | 0 | 2026-11-05 |
| `signal-catalog-guard` | 10 | 5 | 6 | 2026-11-01 |
| `cron-failure-watch` | 10 | 10 | 0 | 2026-11-03 |
| `exit-coverage-matrix-guard` | 10 | 7 | 0 | 2026-10-30 |
| `research-script-run-guard` | 9 | 9 | 0 | 2026-11-03 |
| `exit-lever-map-guard` | 8 | 3 | 0 | 2026-11-02 |
| `prop-harness-full-costs-guard` | 8 | 2 | 7 | 2026-10-15 |
| `guard-liveness` | 7 | 6 | 0 | 2026-10-16 |
| `trainer-heavy-lock-guard` | 7 | 7 | 0 | 2026-11-05 |
| `daily-brief-guard` | 6 | 6 | 0 | 2026-11-05 |
| `matrix-corpus-agreement` | 6 | 4 | 0 | 2026-10-28 |
| `research-workflow-landing-guard` | 6 | 6 | 0 | 2026-11-01 |
| `research-queue-ml-consumer-guard` | 6 | 6 | 0 | 2026-11-04 |
| `matrix-config-agreement` | 5 | 4 | 0 | 2026-10-09 |
| `research-queue-decision-rule-guard` | 5 | 3 | 0 | 2026-10-21 |
| `harness-lever-coupling-guard` | 4 | 3 | 0 | 2026-10-18 |
| `new-table-wiring-guard` | 4 | 4 | 0 | 2026-11-05 |
| `tp-doctrine-guard` | 4 | 4 | 0 | 2026-10-29 |
| `automerge-trigger-guard` | 4 | 2 | 0 | 2026-09-24 |
| `roster-promotion-evidence-guard` | 4 | 3 | 0 | 2026-11-01 |
| `redate-guard` | 3 | 3 | 0 | 2026-10-28 |
| `skills-index` | 3 | 3 | 0 | 2026-10-27 |
| `shadowed-features-guard` | 3 | 3 | 0 | 2026-11-05 |
| `family-retirement-guard` | 3 | 3 | 0 | 2026-10-31 |
| `test-schema-fidelity-guard` | 2 | 2 | 0 | 2026-10-13 |
| `exit-mechanism-coverage-guard` | 2 | 2 | 0 | 2026-10-25 |
| `lever-reachability-guard` | 2 | 1 | 0 | 2026-09-22 |
| `action-input-wiring` | 1 | 1 | 0 | 2026-11-04 |
| `workflow-actor-guard` | 1 | 1 | 0 | 2026-10-30 |
| `push-back-trigger` | 1 | 1 | 0 | 2026-11-04 |
| `api-tier-policy-guard` | 1 | 1 | 0 | 2026-08-16 |
| `workflow-trigger-reachability` | 1 | 1 | 0 | 2026-10-05 |
| `canonical-doc-coherence` | 1 | 1 | 0 | 2026-10-25 |
| `diag-unit-allowlist-guard` | 1 | 1 | 0 | 2026-09-30 |
| `dry-run-guard` | 1 | 1 | 0 | 2026-08-24 |
| `lever-wiring-guard` | 1 | 1 | 0 | 2026-09-06 |
| `research-queue-id-bands` | 1 | 1 | 0 | 2026-10-11 |
| `prop-identity-guard` | 1 | 1 | 0 | 2026-10-07 |
| `secret-scan` | 1 | 1 | 0 | 2026-11-01 |
| `trend-engine-convergence-guard` | 1 | 1 | 0 | 2026-08-09 |

## Names in the logs that are no longer registered (already deleted or renamed)

| name | fires | note |
|---|--:|---|
| `artifact-validity-guard` | 301 | not in the registry at HEAD |
| `session-registry-guard` | 109 | not in the registry at HEAD |
| `session-brief-guard` | 70 | not in the registry at HEAD |
| `register-field-loss-guard` | 54 | not in the registry at HEAD |
| `register-id-guard` | 53 | not in the registry at HEAD |
| `open-items-guard` | 25 | not in the registry at HEAD |
| `probe-guard` | 19 | not in the registry at HEAD |
| `board-coherence` | 15 | not in the registry at HEAD |
| `manager-tooling-selftests` | 12 | not in the registry at HEAD |
| `digest-liveness-guard` | 9 | not in the registry at HEAD |
| `stale-in-flight-guard` | 7 | renamed to `stale-in-flight` |
| `wip-ceiling-guard` | 6 | not in the registry at HEAD |
| `backlog-unresolve-guard` | 4 | not in the registry at HEAD |
| `uncarried-spec-guard` | 2 | not in the registry at HEAD |
| `register-reserialization-guard` | 2 | not in the registry at HEAD |
| `one-live-workplan` | 1 | not in the registry at HEAD |

## What happens next

1. The lane sends the manager the DELETE list (and the REVIEW list) for an operator popup. **No guard is removed until the operator approves a list.**
2. After approval, one PR removes the approved registry entries (and their scripts only when nothing else imports them), with `guard-liveness` and the test suite as the check. Row `GUARD-PRUNE` closes when the approved list is applied.
3. The second pass toward ~15-20 guards is a separate decision about the high-fire paperwork guards above.

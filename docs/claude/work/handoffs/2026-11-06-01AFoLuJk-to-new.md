# Manager handoff: session_01AFoLuJk1UWVx895RmLTidH (Manager Session 2026-11-06a) → new manager

> **Doc status:** `unknown` · category `handoff` · last verified `2026-11-06` · rotation reason: manager context ~650k tokens; operator popup ~19:58Z, verbatim "Hand over after this window (Recommended)".

## Operator decisions in force (verbatim, 2026-11-06)

- **Pacing until the Wed 2026-11-11 18:00Z reset.** Verbatim: "Don't stop anything in progress, let's just get down to one lane and keep it working". Usage was 67% weekly at 19:56Z, and the app projects running out before the reset. Let the running lanes finish. After that, run ONE lane at a time. Keep running: desk wakes, live-review dispatch, merges, deploy checks.
- **ML focus.** Main goal: an ML entry on every live-money account, then live trade-management ML on every real-money account. Live-money infra fixes always stay in the mix.
- **Paper is not a gate.** The only gate for an ML or strategy going to real money is a proven edge in testing. The first 1–2 live trades are a verification watch, not a test. Mechanics are a separate account path.
- **Holdout governs real money; DSR is probation** (~19:35Z), verbatim: "3, but we need to use DSR as a metric ongoing performance review and iteration - non-dsr passing legs can trade live, but are sort of on probation with the goal of iterating u til we have a DSR proof version of the strategy/ml. The legs demotes today should stay in the iterative loop so we can rebase them, but don't need to pass DSR to go back on the roster". This is written into OPERATING-PLAN § 2 on PR #23935, which has not merged yet.
- **Soak is retired** (~18:50Z), verbatim in row SOAK-VOCAB-RETIRE. The statuses are testing / production / inactive. It must be a real rewire (449 files), not a rules edit. Scheduled AFTER the reset.
- **Self-healing Alpaca close** (~18:55Z), verbatim: "You can close. We can close all the positions on that account if needed to reset ... it can't depend on me ... the system needs to know how to handle it itself."
  - On PAPER: close-all plus an account_reset journal sweep, as the last rung.
  - On LIVE: never close-all; raise one red flag.
- **Replacing a live ML model** passes when the candidate does at least as well as the served model on the same window, net of costs, with ≥100 decisions on each side. The edge bar stays for new strategies. The freshness limit is 35 d.
- **Prop:** ~20:18Z the operator REVERSED the ~19:40Z pull, verbatim "Keep sol_4h on all prop books (Recommended)". The book sim showed sol_4h raises each prop book's pass odds (breakout_2 11.4% -> 20.0%). trend_donchian_sol_4h and trend_donchian_eth_4h stay on breakout_2, tradeify_1 and velotrade_1, both on probation. Every prop book is negative EV per attempt at live $10/leg size (a measured baseline).
- **Book concentration** goes to the performance review's portfolio track (note on PERFORMANCE-REVIEW).
- **Standing rules:**
  - free resources only; nothing spends Anthropic API credits; never raise the usage-credits toggle;
  - no new gates;
  - never place, amend or cancel orders by hand;
  - never reword a classifier-refused action: ask the operator for an auto-off window;
  - put the console link https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g in operator updates.

## What landed today (merged, deployed, and observed where stated)

- **Model swap.** #23859 (grade-and-replace path + rule amendments) and #23888. OBSERVED 18:46Z: `ml-decision-entry-v1r20261106`, data_through 2026-10-14, grade fresh. Still open: the next ml_entry package should carry that model_id.
- **Deployed:** #23784 (TQQQ alpaca_live probe), #23822 (deferred-close retry), #23783, #23857 (exit-pass close budget), #23853, #23845, #23812, #23880 (hooks shrink, board-post deleted, sp500 monthly), #23885/#23905/#23918 (Alpaca close ladder, partial), #23927 (soak backlog review).

## OPEN: in-flight, owner, next action

| Item | Owner | Next |
|---|---|---|
| GLD long, 39 sh, alpaca_paper, pkg-8106d5ee, trade 5209 | lane ALPACA-LIVE-MECHANICS (session_01AFoLuMHf3S6p6a31nk3okj) | The ladder (#23918) never escalates on 'flatten accepted but not flat'. The stop leg c928eda6 is CANCELED, so the position has NO stop. TP 2e843e04 is still 'new' @461.27, holding the shares. The lane is building the fix (escalate to rung 2/3; never leave a canceled stop). Then: merge (operator auto-off window), deploy, and re-run `scripts/ops/directed_action.py submit --package pkg-8106d5eef6fc425c --action close --scope alpaca_paper --quote "Close it now in RTH" --live --wait 150`. Rung 3 (paper close-all) is operator-authorized. |
| #23935 (3 promotions to bybit_2 + OPERATING-PLAN rule + DSR probation checks + sol_4h prop pull) | lane SOAK-BACKLOG (session_01AFoLuLc1pJxsUwY7JeXuWW) | Guards red: queue id bands (merge main), a producer swallow, capability index, a bracket_geometry record. The lane is fixing them. Merge needs an auto-off window. The bybit_2 affordability snapshot is already committed to the branch (no balance). After deploy: check the three legs on bybit_2 + bybit_portfolio and the strategy-status / mirror equality. |
| #23916 (soak grader false-fail fix + mechanics_fault_intake on an hourly runner) | lane SOAK-FLIP (session_01AFoLuMWMmVsDHdsNP34sqs) | CI was running at 20:14Z. Merge when green, in an auto-off window. |
| Velotrade min-days check for sol_4h | lane SOAK-BACKLOG | Simulator result pending; it goes into #23935. |
| 20:00Z desk wake (packet DP-20261106T2002Z-scan-1h) | manager | Missed while the manager was off auto mode. Run it late as soon as you are in auto mode, or skip to 22:00Z. |
| Desk short-hold lanes | manager | NOT started for desk trades: row DESK-V1-NO-PERBAR (offline S0: per-bar management loses). The operator was told and can override. |
| Due-gate bug: judgement_cadence fires for a slot before the package opened | unowned, low | Note on LTR-GRADER-COVERAGE when convenient. |
| e4 evidence filename mismatch (e4_oi_shock.json vs e4_oi_shock_1h.json) | LTR-GRADER-COVERAGE | Build the leg-named record with build_strategy_evidence.py. |
| live_review_outcomes prints '[rate] ...' to stdout, which breaks the packet JSON on the Alpaca-bar path | #23913 note | Fix later. |
| Research loss detector: 11 unlanded m20-exit-lever-sweep runs; 2 artifacts expire 11-09 | research-ops (next run) | Check that its record handles them before 11-09. |
| SOAK-VOCAB-RETIRE | after the reset | Inventory, rewire, guards and docs; done when grep finds soak only in archives. |
| ALPACA-CLOSE-BROKER-TRUTH: reconciler closes (trade 6926 IAUM) | row | Test on the next max_hold wave (#23822 deployed after 6926). |
| JOURNAL-LOCK-RESIDUAL | row | #23857 deployed. Observe exit_interval_soak < 60 s across an hourly :00 max_hold burst. The journal_sync.wait half remains. |
| COST-BROKER-SOURCED | lane idle | n=1 broker-costed real close; needs one more, then the --with-funding backfill (Tier 2). |
| GUARD-PRUNE | lane blocked | Waiting for the operator's OK in that lane's chat to push the 41-guard deletion. |

## Lanes (non-archived) at handover

- ALPACA-LIVE-MECHANICS (session_01AFoLuMHf3S6p6a31nk3okj): ladder escalation fix.
- SOAK-BACKLOG-PROMOTE (session_01AFoLuLc1pJxsUwY7JeXuWW): #23935 guards; velotrade simulation.
- SOAK-FLIP-FOLLOWUP (session_01AFoLuMWMmVsDHdsNP34sqs): #23916.
- LIVE-REVIEW warm lane (session_01AFoLuLTaooSYu2zcN9CFqx): send due packages via create_trigger + fire_trigger.
- Idle, archive once their rows close: JOURNAL-LOCK-RESIDUAL (session_01AFoLuJ8cjpa9cCtmE2EM4i), COST-BROKER-SOURCED, GUARD-PRUNE, FREE-CAPACITY-RESIZE, ML-ENTRY-EQ-WEIGHTS, research-ops 1449, LTR-MECH.

## Operating notes learned today

- Merges and live directed actions need the operator to switch auto mode off. `create_session` with permission_mode auto needs the manager to be IN auto mode, so desk wakes cannot start during an off-auto window. Keep windows short and avoid even-hour :00.
- Start a desk wake only from the `desk-wake` marker (packet landed), never from the clock: a wake started early answered the stale 15:02Z packet.
- The manager-scope guard fails manager-authored edits outside the manager surface. Add a dated, scoped entry in docs/claude/work/manager-scope-exception.yaml that quotes the operator. In auto mode the classifier refused that edit, so do it in an off-auto window.
- A held PR opened by a workflow or retargeted to main may never attach CI. Check that checks exist, not only that they are green.
- Squash merges make stacked PRs conflict; merge main into the branch and keep the PR's side for the files it owns.

# Operator asks audit, 2026-11-18

> **Doc status:** `evidence` · category `audit` · last verified `2026-11-18` · lane OPERATOR-ASKS-SWEEP-20261118 (Tier 1)
> **Gates this adds or changes: none.** A read-only audit. It creates no rows or units; the manager slots them.

## Method and limits (read first)
- **Population:** about 55 deduplicated asks drawn from 230 checklist rows (364 operator quotes), the most recent 1,000 of 4,795 work-store items (154 rows carrying quotes), `docs/claude/work/IDEAS.md`, `config/mandates.yaml` (one `proposed:` entry), the 2026-11-12 Thursday-planning answers, the 11-14 handoff, and the decision-transit log (last entries 2026-11-13). Weighted to the last six weeks.
- **Not covered:** the Drive ideas inbox was found (last modified 2026-10-26, about 251 KB) but not read in full; its synced bullets are the IDEAS.md rows. The work store older than its latest 1,000 items was not read (the checklist files cover those). The dashboard repo is not in this session, so UI delivery is marked unverified. `docs/reviews/*` follow-ups were not swept row by row.
- **Evidence standard:** DELIVERED means a file or config is on main (checked by `ls`/`grep` this session) or a row records an observation. A row state alone is a claim, so a landed_unproven row is IN PROGRESS here, not DELIVERED. Most 'delivered' statuses were not re-observed on the live VM.
- **Contradictions I could not settle:** none that chronology fails to resolve. Two near-misses: (1) the 11-14 'ML top priority, never stood down' vs the 11-17 'try not starting new items we do not really need before the reset': read as sequential (reset then ML first). (2) 'Park until after the reset' items (A03, A04) come due the moment the reset passes, in competition with the ML lane's top priority; the manager decides the order.

## Counts by status

- IN PROGRESS: 28
- NOT DELIVERED: 17
- DELIVERED: 7
- SUPERSEDED: 3
- Total: 55

## Ranked: not delivered or partly delivered

Rank 1 to 19 is my suggested order (money, then ML priority, then repeated or aged asks); the remainder follow in the same table.

| # | ask id | status | ask (short) | what is left | proposed home |
|---|---|---|---|---|---|
| 1 | A01 | NOT DELIVERED | "we might need to add like that some level of performance can push a strategy or an ML up  | Row queued, next_action dispatch_lane, explicitly post-reset. Live bar (>=20 closed live trades, CONFIRMED R, net of real costs, ~80% one-sided bound  | general lane (doctrine + packet); Tier-3 wording needs operator review |
| 2 | A06 | IN PROGRESS | "I want to make sure that we are focused on getting MLs that are decision makers live"; "a | ml_entry live on bybit_2; D5 re-entry trigger test FAILED (PI-20261117-ZFRREVN5-0001); overlay row landed_unproven. Most slots have no live baseline y | ML lane (top priority, never stood down) |
| 3 | A07 | NOT DELIVERED | "I want to push for the next ML to go live to be one the does active management, not posit | No active-management ML live. AM-REGRADE-BOOKSIM: no class passes the net-of-cost rule on the book simulator, advice_only unchanged. Operator: retest  | ML lane (retest after book simulator) |
| 4 | A22 | NOT DELIVERED | "Both in parallel" (working demotion signal for the 6 real-money legs) + "don't let anythi | Row queued since 11-15. | ML lane / general lane |
| 5 | A08 | NOT DELIVERED | "we also need to test dynamic sl features for the ml"; "we iterate in the data we have...  | Row still queued; structure-exit work (STRUCTURE-EXIT-ITERATE) is adjacent but not this ask. | ML lane |
| 6 | A02 | NOT DELIVERED | "I want to make sure that we are continuing to do some research that's related to regime c | Queued, plan fixed: (1) falsification test of losses around transitions with the definition registered first, (2) value-of-information scoping, (3) bu | research unit (falsification first); programme 02/03 |
| 7 | A03 | NOT DELIVERED | "Run it after the reset (Recommended)" (claude_desk judging, DESK-PACKET-REDESIGN arms B/C | Queued by design until after Wed 18:00Z reset. The desk is an orphan testing leg with no Stage-0 record and no runnable test without Claude judging. | general lane (plan sessions only; no API spend) |
| 8 | A40 | NOT DELIVERED | "every trade always must have BOTH brackets... nothing is supposed to remove brackets" | Queued since 10-26; related incident: alpaca_paper brackets gone at restart (ALPACA-PAPER-BRACKETS-GONE-1116 landed_unproven). | general lane (Tier 2) |
| 9 | A39 | NOT DELIVERED | "single-account mandates need to be implemented at the risk manager level, not the strateg | Queued. | general lane (Tier 2) |
| 10 | A12 | NOT DELIVERED | "one overarching AI of our own... always test which is better: one overall ML for all mark | Still queued; the plan for week of 11-02 was not executed. | ML lane (design + pre-registered units) |
| 11 | A42 | NOT DELIVERED | "we should add this back into the research pipeline... use it as part of training for exit | Driver not built. | ML lane |
| 12 | A37 | NOT DELIVERED | "two trades that are the same... on two different accounts should be counted in the review | Queued since 10-29. | general lane |
| 13 | A26 | NOT DELIVERED | "I want each of those items to have its own card... the whole catalog of strategies... and | Queued since 10-29. | UI-SPA lane |
| 14 | A29 | NOT DELIVERED | "queue up a research session for next week... anything on Hyperliquid or trading XYZ" ; 20 | Asked 10-27 for the next week, repeated 11-15; no scoping memo found in docs/research. | research unit (scoping) |
| 15 | A09 | NOT DELIVERED | "we need to be collecting data on far more symbols than that, even if we're not trading th | Queued; closes on a manifest listing all USD-M perps. Not verified as built. | ML lane / data infra |
| 16 | A10 | IN PROGRESS | "we should already have a data feed/features catalog"; "I don't see the signals catalog an | docs/reference/signal-catalog.yaml and feature-catalog-coverage JSON exist on main. docs/reference/data-catalog.yaml is MISSING (DATA-CATALOG queued). | general lane (data catalog); UI-SPA lane (visibility) |
| 17 | A11 | NOT DELIVERED | "I want us to create a routine... Elo score" (model leaderboard): "Maybe we should start u | Parked by manager with design notes (Bradley-Terry, same replay window and cost stack, never gates promotion). Revisit alongside ML-SLOT-REPORT (queue | ML lane (with slot report) |
| 18 | A04 | NOT DELIVERED | "Park until after the reset" (movement-capture; xsec-crypto) | Parked by instruction; due now that the reset has passed. | park-with-reason, revisit this week only if research-ops finds a meaningful next test |
| 19 | A28 | NOT DELIVERED | Overview: chart under trades, prop open trades in 'Real money' view | Operator: can wait until more lanes run. | park-with-reason (UI lane capacity) |
| 20 | A05 | IN PROGRESS | "Keep that also like as a tab on the work page... a sub tab for the investor deck with the | Deck refresh in flight; docs/pitch has build_deck.py and a .pptx but docs/pitch/slides.json is MISSING on main. Operator then scoped to: update once a | general lane (finish artifact; UI sub-tab after reset; needs dashboard repo) |
| 21 | A13 | IN PROGRESS | "how models are learning from each other's performance... the ML entry model learning from | Map delivered; instruments landed. The blind-grade teacher label failed CJ-4 (rho -0.183, n 707) and the alternative is queued. Operator: retire the p | ML lane (CJ-LABEL-ALTERNATIVE) |
| 22 | A14 | IN PROGRESS | "the full iterative dev plan built out, should be visible so I can monitor/track/edit" | docs/plans/ml-dev-plan.yaml exists on main. Observation that it is visible and editable in the UI is not established. | ML lane |
| 23 | A15 | IN PROGRESS | "detailed AI roadmap covering the dog-named models" (TOP PRIORITY); "MECE map of models to | Row open two weeks. No ml-roadmap-mece doc on main under that name; ml-dev-plan.yaml and ROADMAP.md may be its home. Not confirmed. | ML lane (close or fold into ML-DEV-PLAN) |
| 24 | A16 | IN PROGRESS | "get all of this into the roadmap and into the work que, the first couple of sessions shou | Blocked row, stale since 10-18. PI-20261118-JFWRQYOV-0001 measured the research runner at about 5% utilised, so the flow exists but starves. | general lane (runner throughput) + ML lane |
| 25 | A19 | IN PROGRESS | "The system needs to be able to do that on its own. I'm not doing it manually anymore. Eno | Server-side close built; phone path killed when operator uninstalled the app 11-12 (PHONE-EXEC-1B). Drill rows blocked; end-to-end observation on a re | general lane (observe one automatic prop close) |
| 26 | A20 | IN PROGRESS | "Build the one-time override button and fix the day-start reading first" (daily DD switch) | Landed, no observation recorded. | general lane (observe) |
| 27 | A23 | IN PROGRESS | "The manager needs to get these alerts and handle immediately"; report gaps as a number | Both open. | general lane |
| 28 | A24 | IN PROGRESS | "Accept the defaults (15 min; all classes; advice rows get a button...); I'll create the r | Open since 11-05. Operator owes the routine and token; not confirmed created. | general lane (+ operator token) |
| 29 | A33 | IN PROGRESS | "we should generally prefer specific infra like kaggle... leave the general use git resour | Kaggle GPU measured as having no diagnosis-backed ML work; torch device fix landed (ML-BAKEOFF-TORCH-DEVICE). | ML lane (feed GPU units) |
| 30 | A41 | IN PROGRESS | Structure-based SL+TP as default exit: "Build it now - ... the new default until we prove  | Landed; the first managed exit observation named in the row not confirmed; iterate row queued. | ML lane / research unit |
| 31 | A43 | IN PROGRESS | "exit strategies where once a trade passes a certain amount of R, the sl turns into a tigh | R-trigger lever exists; level-triggered part routed to programme nodes; LTR-ACTION-TIGHTEN-BE queued. | research unit (programme 01) |
| 32 | A45 | IN PROGRESS | "Revisit correlated signals between symbols as indicators" | Lead-lag lever only; wider cross-symbol features routed to programme review. Not confirmed authored. | research unit |
| 33 | A53 | IN PROGRESS | Catalog of every variable/signal with metrics and recurring review | signal-catalog.yaml and signal-catalog-review.md on main; the 20 review questions not triaged per the row. | research unit (triage questions) |
| 34 | A54 | IN PROGRESS | "Register the net-of-cost test for the close class now"; "Merge both/four on green"; SEC l | Lockdown and host changes done per rows; the frozen-run cancel is still queued; close-class test landed_unproven. | general lane |

## Full list

Quotes are verbatim excerpts (ellipses mark cuts). Source is a work-store/checklist row id or file path.

### A01 · NOT DELIVERED · 2026-11-17
- **Ask:** "we might need to add like that some level of performance can push a strategy or an ML up the promotion ladder, even if the backtest results... we need to take into account live performance." (+ 2nd rule: the better 2h variant "take over instead of the 4 hours")
- **Source:** work store PI-20261117-LSFHBH4A-0007
- **Evidence / owner / left:** Row queued, next_action dispatch_lane, explicitly post-reset. Live bar (>=20 closed live trades, CONFIRMED R, net of real costs, ~80% one-sided bound >0) and slot-swap rule are answered but not in doctrine or the promotion packet.
- **Home:** general lane (doctrine + packet); Tier-3 wording needs operator review

### A02 · NOT DELIVERED · 2026-11-17
- **Ask:** "I want to make sure that we are continuing to do some research that's related to regime categorization... we sometimes get stuck specifically when a regime is in fluctuation... that's next week, not now"
- **Source:** work store PI-20261117-LSFHBH4A-0004; REGIME-PROGRAM (op. 2026-10-11)
- **Evidence / owner / left:** Queued, plan fixed: (1) falsification test of losses around transitions with the definition registered first, (2) value-of-information scoping, (3) build. No result file found; REGIME-PROGRAM still queued since 10-11.
- **Home:** research unit (falsification first); programme 02/03

### A03 · NOT DELIVERED · 2026-11-17
- **Ask:** "Run it after the reset (Recommended)" (claude_desk judging, DESK-PACKET-REDESIGN arms B/C)
- **Source:** work store PI-20261117-NIVCJP7T-0006; DESK-18D-JUDGE-2
- **Evidence / owner / left:** Queued by design until after Wed 18:00Z reset. The desk is an orphan testing leg with no Stage-0 record and no runnable test without Claude judging.
- **Home:** general lane (plan sessions only; no API spend)

### A04 · NOT DELIVERED · 2026-11-17
- **Ask:** "Park until after the reset" (movement-capture; xsec-crypto)
- **Source:** work store PI-20261117-NIVCJP7T-0005 / -0004
- **Evidence / owner / left:** Parked by instruction; due now that the reset has passed.
- **Home:** park-with-reason, revisit this week only if research-ops finds a meaningful next test

### A05 · IN PROGRESS · 2026-11-17
- **Ask:** "Keep that also like as a tab on the work page... a sub tab for the investor deck with the slides so that I can go over them and leave comments"; deck "hardwired to a live source of information"
- **Source:** work store PITCH-DECK-V2 (in_flight, #26648), PI-20261117-LNGQ5KFO-0001/-0002
- **Evidence / owner / left:** Deck refresh in flight; docs/pitch has build_deck.py and a .pptx but docs/pitch/slides.json is MISSING on main. Operator then scoped to: update once as a commentable Artifact, add the UI sub-tab and weekly refresh after the reset.
- **Home:** general lane (finish artifact; UI sub-tab after reset; needs dashboard repo)

### A06 · IN PROGRESS · 2026-11-01
- **Ask:** "I want to make sure that we are focused on getting MLs that are decision makers live"; "a baseline ML live on real money for most decision slots this week... D5 (position aggregation) and D6 (bracket at entry) the priority" (2026-11-14)
- **Source:** ML-DECISION-MODELS (queued), MANAGER-HANDOFF-2026-11-14, ML-REAL-MONEY-OVERLAY
- **Evidence / owner / left:** ml_entry live on bybit_2; D5 re-entry trigger test FAILED (PI-20261117-ZFRREVN5-0001); overlay row landed_unproven. Most slots have no live baseline yet.
- **Home:** ML lane (top priority, never stood down)

### A07 · NOT DELIVERED · 2026-10-29
- **Ask:** "I want to push for the next ML to go live to be one the does active management, not position sizing"
- **Source:** ML-AM-NEXT-LIVE (queued)
- **Evidence / owner / left:** No active-management ML live. AM-REGRADE-BOOKSIM: no class passes the net-of-cost rule on the book simulator, advice_only unchanged. Operator: retest when the book simulator is ready.
- **Home:** ML lane (retest after book simulator)

### A08 · NOT DELIVERED · 2026-11-01
- **Ask:** "we also need to test dynamic sl features for the ml"; "we iterate in the data we have... we don't wait for new months of data"
- **Source:** ML-ENTRY-DYNAMIC-SL (queued since 11-06)
- **Evidence / owner / left:** Row still queued; structure-exit work (STRUCTURE-EXIT-ITERATE) is adjacent but not this ask.
- **Home:** ML lane

### A09 · NOT DELIVERED · 2026-11-01
- **Ask:** "we need to be collecting data on far more symbols than that, even if we're not trading them yet"
- **Source:** ML-FS-ARCHIVE-WIDE (queued)
- **Evidence / owner / left:** Queued; closes on a manifest listing all USD-M perps. Not verified as built.
- **Home:** ML lane / data infra

### A10 · IN PROGRESS · 2026-11-01
- **Ask:** "we should already have a data feed/features catalog"; "I don't see the signals catalog and features heat map here" (2026-11-12)
- **Source:** DATA-CATALOG, SIGNAL-CATALOG, FEATURES-CATALOG-UI-VERIFY, FEATURE-IMPACT-MAP
- **Evidence / owner / left:** docs/reference/signal-catalog.yaml and feature-catalog-coverage JSON exist on main. docs/reference/data-catalog.yaml is MISSING (DATA-CATALOG queued). UI visibility unverified: dashboard repo is not in this session.
- **Home:** general lane (data catalog); UI-SPA lane (visibility)

### A11 · NOT DELIVERED · 2026-11-01
- **Ask:** "I want us to create a routine... Elo score" (model leaderboard): "Maybe we should start using an Elo score... We don't need to implement it now."
- **Source:** docs/claude/work/IDEAS.md (2026-11-17)
- **Evidence / owner / left:** Parked by manager with design notes (Bradley-Terry, same replay window and cost stack, never gates promotion). Revisit alongside ML-SLOT-REPORT (queued).
- **Home:** ML lane (with slot report)

### A12 · NOT DELIVERED · 2026-10-27
- **Ask:** "one overarching AI of our own... always test which is better: one overall ML for all markets vs one ML per market... committee"
- **Source:** ML-ARCH-GENERALIST-VS-SPECIALIST (queued since 10-27)
- **Evidence / owner / left:** Still queued; the plan for week of 11-02 was not executed.
- **Home:** ML lane (design + pre-registered units)

### A13 · IN PROGRESS · 2026-11-16
- **Ask:** "how models are learning from each other's performance... the ML entry model learning from the LTR decision desk"
- **Source:** CROSS-MODEL-LEARNING (done), CML-HARNESS (landed_unproven), CJ-LABEL-ALTERNATIVE (queued)
- **Evidence / owner / left:** Map delivered; instruments landed. The blind-grade teacher label failed CJ-4 (rho -0.183, n 707) and the alternative is queued. Operator: retire the paused item once a replacement exists.
- **Home:** ML lane (CJ-LABEL-ALTERNATIVE)

### A14 · IN PROGRESS · 2026-11-12
- **Ask:** "the full iterative dev plan built out, should be visible so I can monitor/track/edit"
- **Source:** ML-DEV-PLAN (landed_unproven)
- **Evidence / owner / left:** docs/plans/ml-dev-plan.yaml exists on main. Observation that it is visible and editable in the UI is not established.
- **Home:** ML lane

### A15 · IN PROGRESS · 2026-11-04
- **Ask:** "detailed AI roadmap covering the dog-named models" (TOP PRIORITY); "MECE map of models to every trade-lifecycle decision"
- **Source:** ML-ROADMAP-MECE (in_flight since 11-04)
- **Evidence / owner / left:** Row open two weeks. No ml-roadmap-mece doc on main under that name; ml-dev-plan.yaml and ROADMAP.md may be its home. Not confirmed.
- **Home:** ML lane (close or fold into ML-DEV-PLAN)

### A16 · IN PROGRESS · 2026-10-11
- **Ask:** "get all of this into the roadmap and into the work que, the first couple of sessions should be high priority to get the work flow/infra sorted out" (ML research runner)
- **Source:** ML-RQ-RUNNER (blocked since 10-18)
- **Evidence / owner / left:** Blocked row, stale since 10-18. PI-20261118-JFWRQYOV-0001 measured the research runner at about 5% utilised, so the flow exists but starves.
- **Home:** general lane (runner throughput) + ML lane

### A17 · IN PROGRESS · 2026-11-04
- **Ask:** "if the ML passed on other coins, then it can trade other coins... roster is whatever data it trained on"; "the same entry model should be applied to alpaca as to bybit 2"
- **Source:** ML-ENTRY-ALL-ACCOUNTS, ML-UNIVERSE-RULE, ALPACA-LIVE-ACTIVITY-ML
- **Evidence / owner / left:** ml_entry_eq_struct is in alpaca_live and alpaca_portfolio rosters (config/accounts.yaml, 2026-11-08, operator verbatim). Universe rule is in CLAUDE.md. alpaca_live took nothing on mirror trades 11-17/11-18: operator accepted it as by design (PI-20261118-JFWRQYOV-0003).
- **Home:** ML lane (widening test on pass)

### A18 · DELIVERED · 2026-11-17
- **Ask:** "In general, I ask that we not trade fossil fuels."
- **Source:** FOSSIL-FUEL-EXCLUSION (done, #26618)
- **Evidence / owner / left:** config/values_exclusions.yaml on main with fossil_fuels decision. Row's closing observation (restart onto 50184098, USO bracket intact) not independently re-read here.
- **Home:** closed

### A19 · IN PROGRESS · 2026-11-12
- **Ask:** "The system needs to be able to do that on its own. I'm not doing it manually anymore. Enough is enough." (prop VM close)
- **Source:** PROP-VM-STRATEGY-EXIT-CLOSE, CAP-PROP-VM-CLOSE (landed_unproven); PHONE-DRILL-TP-CLOSE, CAP-PROP-LIVE-DRILL (blocked)
- **Evidence / owner / left:** Server-side close built; phone path killed when operator uninstalled the app 11-12 (PHONE-EXEC-1B). Drill rows blocked; end-to-end observation on a real prop close not confirmed.
- **Home:** general lane (observe one automatic prop close)

### A20 · IN PROGRESS · 2026-11-12
- **Ask:** "Build the one-time override button and fix the day-start reading first" (daily DD switch)
- **Source:** DD-SWITCH-OVERRIDE (landed_unproven)
- **Evidence / owner / left:** Landed, no observation recorded.
- **Home:** general lane (observe)

### A21 · IN PROGRESS · 2026-11-12
- **Ask:** "Yes: evidence check, then a proposal per leg" (tlt/qqq/slv/uso survivors); "I do want to promote silver"
- **Source:** PR1111-SURVIVOR-PROMOTIONS, PROMOTE-TLT-1H-REAL-MONEY
- **Evidence / owner / left:** tlt_pullback_1h promoted to alpaca_live 2026-11-14 (handoff; roster line in accounts.yaml). First live fill tracked by PI-20261114-TFZXAKEK-0003. slv_trend_1h is on alpaca_live roster; uso/qqq outcomes not established.
- **Home:** general lane

### A22 · NOT DELIVERED · 2026-11-12
- **Ask:** "Both in parallel" (working demotion signal for the 6 real-money legs) + "don't let anything get demoted without me looking at it first" (one-off)
- **Source:** PERF-F1-DEMOTION-SIGNAL (queued)
- **Evidence / owner / left:** Row queued since 11-15.
- **Home:** ML lane / general lane

### A23 · IN PROGRESS · 2026-11-12
- **Ask:** "The manager needs to get these alerts and handle immediately"; report gaps as a number
- **Source:** WORK-GAP-ALERTS (in_flight), PROPOSAL-ALERT-ROUTING (landed_unproven)
- **Evidence / owner / left:** Both open.
- **Home:** general lane

### A24 · IN PROGRESS · 2026-11-12
- **Ask:** "Accept the defaults (15 min; all classes; advice rows get a button...); I'll create the routine and token" (direct action path)
- **Source:** MANAGER-VM-DIRECT-OPS, TRADE-ACTION-DIRECT-PATH (in_flight)
- **Evidence / owner / left:** Open since 11-05. Operator owes the routine and token; not confirmed created.
- **Home:** general lane (+ operator token)

### A25 · IN PROGRESS · 2026-11-05
- **Ask:** "We also need to add some tabs to the console: 1. Weekly workplan tracker 2. ML Roadmap tracker 3. Performance tracker... 4. Systems/resource health"
- **Source:** UI-CONSOLE-TABS-DATA (in_flight), UI-CONSOLE-CONNECTOR, UI-CONSOLE-ARTIFACT
- **Evidence / owner / left:** The read-only MCP connector is live in this session (workplan, ml_roadmap, performance, system_health tools exist), which is evidence for the data side. Tab rendering is in a repo this session cannot see.
- **Home:** UI-SPA lane

### A26 · NOT DELIVERED · 2026-10-29
- **Ask:** "I want each of those items to have its own card... the whole catalog of strategies... and MLs"
- **Source:** UI-CATALOG-STRATEGIES-ML (queued)
- **Evidence / owner / left:** Queued since 10-29.
- **Home:** UI-SPA lane

### A27 · IN PROGRESS · 2026-10-29
- **Ask:** "live trade count and live P&L must be live on the dashboard"; "backlog it and we'll get back to it"
- **Source:** LIVE-NUMBERS-STREAMING, UI-TRADING-PUSH, UI-CHART-CRYPTO-LIVE
- **Evidence / owner / left:** Push/chart rows landed_unproven; streaming row queued. Operator said it is better but not there.
- **Home:** UI-SPA lane

### A28 · NOT DELIVERED · 2026-10-29
- **Ask:** Overview: chart under trades, prop open trades in 'Real money' view
- **Source:** UI-OVERVIEW-WORK-PROP, OVERVIEW-PROP-OPEN-TRADES (queued)
- **Evidence / owner / left:** Operator: can wait until more lanes run.
- **Home:** park-with-reason (UI lane capacity)

### A29 · NOT DELIVERED · 2026-10-27
- **Ask:** "queue up a research session for next week... anything on Hyperliquid or trading XYZ" ; 2026-11-15 "we were going to do some scoping"
- **Source:** VENUE-SCOPE-HYPERLIQUID, VENUE-SCOPE-HYPERLIQUID-TRADEXYZ (queued)
- **Evidence / owner / left:** Asked 10-27 for the next week, repeated 11-15; no scoping memo found in docs/research.
- **Home:** research unit (scoping)

### A30 · IN PROGRESS · 2026-10-08
- **Ask:** WEPE: "add the bigger build out to the roadmap, gated on the system successfully passing milestones"; "build that sleeve on backtesting not just live testing"
- **Source:** WEPE-BUILDOUT (blocked), NEWS-HIST-REPLAY
- **Evidence / owner / left:** Gated by design; 11-12 operator: "Park it until the news-veto result is confirmed". Backtestable news corpus row landed_unproven.
- **Home:** park-with-reason (gate: news-veto result)

### A31 · IN PROGRESS · 2026-10-26
- **Ask:** "News feed ... and calendar... should be routinely maintained and updated data feeds"; "expand the calendar's types of events"
- **Source:** DATA-FEEDS-NEWS-CALENDAR, CALENDAR-EVENT-TYPES (landed_unproven)
- **Evidence / owner / left:** Both landed; new defect: calendar refresh restarts the trader daily (ECON-CAL-DAILY-RESTART queued).
- **Home:** general lane

### A32 · IN PROGRESS · 2026-11-11
- **Ask:** "the futures intraday history, yeah, use IB's free history"
- **Source:** FUT-CME-INTRADAY-HIST (landed_unproven); ETF-HISTORY-PIPELINE (queued, built not run)
- **Evidence / owner / left:** ETF 1m pipeline never run against real data.
- **Home:** general/data lane

### A33 · IN PROGRESS · 2026-11-01
- **Ask:** "we should generally prefer specific infra like kaggle... leave the general use git resources free"
- **Source:** COMPUTE-PREFER-KAGGLE (queued); PI-20261117-ZQKSKUGH-0001
- **Evidence / owner / left:** Kaggle GPU measured as having no diagnosis-backed ML work; torch device fix landed (ML-BAKEOFF-TORCH-DEVICE).
- **Home:** ML lane (feed GPU units)

### A34 · IN PROGRESS · 2026-11-05
- **Ask:** "let's also keep backups on kaggle (on private)"
- **Source:** KAGGLE-BACKUPS (landed_unproven)
- **Evidence / owner / left:** Landed, first weekly run not observed here.
- **Home:** general lane (observe)

### A35 · SUPERSEDED · 2026-11-05
- **Ask:** Home node: "let's put a pin in that for now... We can drop that for now"
- **Source:** HOME-NODE (queued)
- **Evidence / owner / left:** Operator parked it in the same message; keep parked.
- **Home:** park-with-reason

### A36 · IN PROGRESS · 2026-10-29
- **Ask:** "We also seem to be spending an inordinate amount of time waiting for CI checks and for merges"
- **Source:** CI-THROUGHPUT-20261029 (landed_unproven)
- **Evidence / owner / left:** Landed 11-02; re-measure not recorded.
- **Home:** general lane (re-measure)

### A37 · NOT DELIVERED · 2026-10-29
- **Ask:** "two trades that are the same... on two different accounts should be counted in the review as one trade"
- **Source:** REVIEW-COUNT-BY-DECISION (queued)
- **Evidence / owner / left:** Queued since 10-29.
- **Home:** general lane

### A38 · IN PROGRESS · 2026-11-04
- **Ask:** Script-computed research SLOs measuring money decisions; standing decay monitor
- **Source:** PASS-TO-DECISION-SLO (queued), LIVE-DECAY-MONITOR (landed_unproven), RESEARCH-SLO-YIELD (landed_unproven)
- **Evidence / owner / left:** Partly landed; pass-to-decision still queued.
- **Home:** general lane

### A39 · NOT DELIVERED · 2026-11-09
- **Ask:** "single-account mandates need to be implemented at the risk manager level, not the strategy level"
- **Source:** LTR-ACCOUNT-SCOPED-ACTIONS (queued)
- **Evidence / owner / left:** Queued.
- **Home:** general lane (Tier 2)

### A40 · NOT DELIVERED · 2026-10-26
- **Ask:** "every trade always must have BOTH brackets... nothing is supposed to remove brackets"
- **Source:** BRACKETS-ALWAYS (queued)
- **Evidence / owner / left:** Queued since 10-26; related incident: alpaca_paper brackets gone at restart (ALPACA-PAPER-BRACKETS-GONE-1116 landed_unproven).
- **Home:** general lane (Tier 2)

### A41 · IN PROGRESS · 2026-11-03
- **Ask:** Structure-based SL+TP as default exit: "Build it now - ... the new default until we prove something else works better"; "We need to keep iterating on this idea"
- **Source:** STRUCTURE-EXITS-DEFAULT (landed_unproven), STRUCTURE-EXIT-ITERATE (queued)
- **Evidence / owner / left:** Landed; the first managed exit observation named in the row not confirmed; iterate row queued.
- **Home:** ML lane / research unit

### A42 · NOT DELIVERED · 2026-11-05
- **Ask:** "we should add this back into the research pipeline... use it as part of training for exit models" (vol_trail)
- **Source:** EXIT-VOLTRAIL-TRAINSET-DRIVER (queued)
- **Evidence / owner / left:** Driver not built.
- **Home:** ML lane

### A43 · IN PROGRESS · 2026-10-21
- **Ask:** "exit strategies where once a trade passes a certain amount of R, the sl turns into a tight trailing stop... FVGs... loss of momentum"; "not giving back our R"
- **Source:** IDEAS.md; programme 01
- **Evidence / owner / left:** R-trigger lever exists; level-triggered part routed to programme nodes; LTR-ACTION-TIGHTEN-BE queued.
- **Home:** research unit (programme 01)

### A44 · IN PROGRESS · 2026-10-21
- **Ask:** "Create a predictive ML that uses multivariate regressions to create an predicted price vector"
- **Source:** IDEAS.md; ML-F bake-off
- **Evidence / owner / left:** Routed as a baseline arm of the ML-F track; no result checked here.
- **Home:** ML lane

### A45 · IN PROGRESS · 2026-10-21
- **Ask:** "Revisit correlated signals between symbols as indicators"
- **Source:** IDEAS.md; FRONTIER-LEVER-LEADLAG
- **Evidence / owner / left:** Lead-lag lever only; wider cross-symbol features routed to programme review. Not confirmed authored.
- **Home:** research unit

### A46 · DELIVERED · 2026-10-21
- **Ask:** "deep open source research on how trading firms run their research operations"
- **Source:** RESEARCH-OPS-BENCHMARK-1016 (done)
- **Evidence / owner / left:** docs/research/research-ops-benchmark-2026-10-16.md (per IDEAS.md routing; file not re-opened here).
- **Home:** closed

### A47 · DELIVERED · 2026-10-21
- **Ask:** Manager skill: check rotation every compaction
- **Source:** IDEAS.md (done)
- **Evidence / owner / left:** Manager SKILL rotation check (per IDEAS.md); not re-read here.
- **Home:** closed

### A48 · DELIVERED · 2026-10-25
- **Ask:** Live-trade-review routine with a design doc first
- **Source:** LIVE-TRADE-REVIEW-DESIGN, LTR-0..11
- **Evidence / owner / left:** docs/plans/live-trade-review-DESIGN.md exists; scripts/ops/live_review_apply.py exists; first apply observed 2026-11-14 per handoff. Later iterations (A19, A39) continue.
- **Home:** closed

### A49 · SUPERSEDED · 2026-10-21
- **Ask:** Review the session-environment feature
- **Source:** SESSION-ENV-REVIEW (dropped 10-29)
- **Evidence / owner / left:** Dropped; reason and supporting data not confirmed in this sweep (p7 rule requires them).
- **Home:** general lane (confirm kill record has data)

### A50 · DELIVERED · 2026-11-04
- **Ask:** "Maybe it shouldn't be gated at a per symbol basis"; accounts configure strategies, not symbols
- **Source:** ML-UNIVERSE-RULE
- **Evidence / owner / left:** Stated in CLAUDE.md 'An account configures strategies, never symbols' (2026-11-04). Implementation row still in_flight (A17).
- **Home:** closed as a rule

### A51 · DELIVERED · 2026-10-29
- **Ask:** Take the drawdown limit off the paper testing accounts
- **Source:** PAPER-TESTING-DD-OFF (done)
- **Evidence / owner / left:** Row observed 2026-11-13 from live /api/bot/config (row text; not re-fetched).
- **Home:** closed

### A52 · DELIVERED · 2026-11-03
- **Ask:** Breed names for models; "change that to Labrador"
- **Source:** MODEL-NAMES (landed_unproven)
- **Evidence / owner / left:** docs/reference/model_names.yaml on main.
- **Home:** closed

### A53 · IN PROGRESS · 2026-09-30
- **Ask:** Catalog of every variable/signal with metrics and recurring review
- **Source:** SIGNAL-CATALOG (queued)
- **Evidence / owner / left:** signal-catalog.yaml and signal-catalog-review.md on main; the 20 review questions not triaged per the row.
- **Home:** research unit (triage questions)

### A54 · IN PROGRESS · 2026-11-12
- **Ask:** "Register the net-of-cost test for the close class now"; "Merge both/four on green"; SEC lockdown; force-cancel runs
- **Source:** CLOSE-CLASS-NOC-TEST, SEC-8001-LOCKDOWN (done), SEC-HOST-CHANGES-1112 (done), ACTIONS-FROZEN-RUNS-CANCEL (queued)
- **Evidence / owner / left:** Lockdown and host changes done per rows; the frozen-run cancel is still queued; close-class test landed_unproven.
- **Home:** general lane

### A55 · SUPERSEDED · 2026-11-17
- **Ask:** "I just wanted to make sure there wasn't a bug" (alpaca_live not placing mirror trades)
- **Source:** PI-20261118-JFWRQYOV-0003 (dropped)
- **Evidence / owner / left:** Operator confirmed by design; no change wanted. Note the row's idea of recording every silent non-placement was dropped with it, though SLV short showed no refusal entry.
- **Home:** closed (consider re-filing 'no silent drops' separately)

# Manager handover 2026-10-22: session_01CSwhZWiw15rVCkjsJ8Cpuh → (new)

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../../DOCUMENT-INDEX.md)

Discretionary rotation (manager SKILL § "Manager handover"): the old manager's context reached ~474k tokens at the
10:41Z rotation check (threshold ~300k). Boundary chosen: after the Thursday walk-through + planning and after the
operator's last Tier-3 decision of the morning (#19513) merged. The old manager stays responsible until V1–V5 pass.

## Live lanes

| lane | session | row | doing | owes |
|---|---|---|---|---|
| DECISION-BAR-MATCH | session_01B7EoDeNYn9AmiGkk7q6etd | DECISION-BAR-MATCH | #19513 merged as bfd0ac0d9 (decision_bar: closed on xrp_pullback_2h, ada_pullback_2h, trend_donchian_eth_prop; eth_4h/sol_prop evidence re-based onto forming). Verifying the deploy. | 3-line deploy report; Tier-1 PR: row → landed_unproven (observation: first live order package per switched leg decided on a closed bar), close PI-20261018-WCDIDFTE-0002 and PI-20261022-LOWUPW43-0001. Its classifier has refused commits twice today — if it sends a patch, the manager applies it (exception MGR-20261022-DECISION-BAR-SPLIT expires 2026-10-24). |
| assistant manager | session_011c3qoaBvGBioDWkPVToQSb | — | runs 4 routines (research-ops 4x/day, 6h lane check-in, Wed review prep, Sat health review) | its routine prompts name the old manager id — rewire (step 3b) |

No other lane is open (list_sessions mine=true at ~12:05Z: only DECISION-BAR-MATCH and the manager are non-archived besides the assistant manager).

## Open PRs that need the manager

None held right now. #19513 merged 11:47Z. Old stale PRs (#11933..#18557, #17895 ops-flags) are unchanged and not today's work.

## Operator decisions today (verbatim, all recorded on rows)

- Capacity 06:19Z: weekly 6%, session 4% (screenshot). Week priorities (all four): "Exits / giveback", "TP doctrine compliance", "ML: non-GBDT families", "Research pipeline health" — row WEEKLY-PLANNING.
- xrp_4h ADX trail: "Ship it (Recommended)", then revised after a disclosed omitted caveat: "bybit_1 now, real money after corroboration (Recommended)" — deployed f8a9b6fd7; real money waits on RQ-20261022-511e-01 (row OPERATOR-DECISIONS-1022, MOMENTUM-LEVERS-LIVE).
- Alpaca 1d pullback TP: "Declare 3.5R (Recommended)" — deployed (TP-DECLARE-ALPACA-PB1D).
- bybit_1 margin: "Cut its risk to ~0.75%" — deployed.
- ief to paper #19403: "Merge after the check (Recommended)" — merged 66cc9083e, deployed.
- eth_prop bar evidence: "No — match the bar (Recommended)"; then "Split: 3 to closed, 2 stay (Recommended)"; eth_prop TP: "Agree, keep 6R (Recommended)"; permission unblock: "Take me off auto mode (Recommended)" + chat "Off auto mode" — #19513 merged (DECISION-BAR-MATCH, TP-ETHPROP-2P5).
- Stale PRs: "Triage then close (Recommended)" — done (20 closed by RESEARCH-HEALTH-W43).
- Dormant milestones: "Apply all (Recommended)" — #19500 merged (M24/M15/M26/M36 retired; ML-NETR-RANKER; M41 scoping PI-20261022-J9X7ACR3-0001 due 2026-10-26).
- Manager calls (no operator ask): closed held ada vol_trail PRs #17193/#14053 (one-leg pass, siblings 0/9 — same corroboration standard).

## Triggers targeting the old session (pre-handover list, recurring)

| id | name | cron |
|---|---|---|
| trig_018ngif3PhDeuX8kC7opH1KF | Manager review (twice daily: 05:52Z after the 05:30Z report, 17:52Z) | 52 5,17 * * * |
| trig_01WqzQuoRq2VYoVAVL2JTbaq | Thursday review walk-through + weekly planning (with operator) | 17 6 * * 4 |
| trig_016R9fzAzLLimoumkHQ4WLaN | Weekly audit (Wed after reset): core + rotating deep pass | 31 18 * * 3 |
| trig_01Msq361BhpXv9wwkKPLnMYR | Weekly research programme review (Wed after reset, before Thursday planning) | 29 19 * * 3 |

One-shot: trig_0178qtBgZiFTSiys2cAR6MfC "Post-reset restart (weekly usage reset Wed ~17:59Z)" run_once_at 2026-10-28T18:07Z.
Pre-handover n (recurring + one-shot to recreate) = 5. Fired one-shot lane-report triggers targeting the old id are spent and need no recreation.

Assistant-manager routines whose prompts NAME the old id (rewire by message to the assistant manager — only it can edit them):
trig_01UnRpzN513KbMjvJWFAf911 (research-ops 4x/day), trig_01HxRVXSy6GGqWaWQXmGdJ97 (6h lane check-in),
trig_01LE61kLKDFKptEfTfZ7vnYS (Wed review prep), trig_013GU17584wu4HJYEkTF1KBk (Sat health review).
The daily research authoring lane (trig_01GxvEXT4hRBjQvx738Tobbs) finds the manager by title — no change needed.

## Watched

PR activity: none open (all of today's PRs merged). Ops-flags PR #17895 — the new manager subscribes (step 3c).

## Capacity

Weekly 6% at 06:19Z; reset 2026-10-28 17:59Z; sustainable 15.0 pp/day (spend_meter --capacity, 12:05Z). Lane spend today
roughly $135 across ~13 lanes (largest: OPERATOR-DECISIONS-1022 $22.64 vs $20 ceiling, PERF-FOLLOWUP $14.28/$15).

## Open observations (rows landed_unproven)

- OPERATOR-DECISIONS-1022 / TP-DECLARE-ALPACA-PB1D: first bybit_1 xrp_adx25 trade shows the ADX trail; next alpaca 1d entry carries a 3.5R TP; next bybit_1 entry sized at 0.75%.
- DECISION-BAR-MATCH: first closed-bar order package per switched leg (lane recording).
- BRK2-RISK-035: next breakout_2 phone ticket sized at 0.35% (risk_usd ≈ 17.5).
- RETIRE-GLOBAL-POSCAP: due 2026-10-22 12:00Z — the global-cap retirement check.
- RESEARCH-HEALTH-W43 / THEME-AUTHOR-1022: research SLO runnable_floor and theme_share on post-merge runs (theme share is a 7-day fires ratio; regime is the binding theme).
- PERF-FOLLOWUP-2026W43 (fd06 units), TP-DOCTRINE-W43 (bea9 units), ML-INSTRUMENTS-W43 (first non-GBDT graded result), corroboration RQ-20261022-511e-01.

## New manager — first actions

1. V1 read-back (below), then wait for the old manager's diff.
2. After V1–V5: run the 17:52Z manager review (Telegram summary, Ideas inbox, popups); handle DECISION-BAR-MATCH's deploy report and close-out.
3. Next week: weekly reset Wed 2026-10-28 17:59Z → post-reset restart 18:07Z → audits/reviews → Thursday 06:17Z walk-through.

## Handover checklist

- [ ] Handoff doc committed and merged to main (PR #__)
- [ ] New session created: <id / link>, Opus, tags manager + predecessor:session_01CSwhZWiw15rVCkjsJ8Cpuh
- [ ] Triggers recreated against the new session; old ones disabled (n recreated = __, pre-handover n = 5)
- [ ] Prompts naming the old id updated; checklist references updated and pushed
- [ ] New manager subscribed to the PRs it must watch, incl. the ops-flags PR
- [ ] V1 read-back diffed against the old manager's list; mismatches fixed: <evidence>
- [ ] V2 trigger audit: 0 enabled triggers on old id; recurring routines present, enabled, on new id: <list_triggers evidence>
- [ ] V3 id sweep: grep of prompts / charters / lane briefs for old id finds none (positive control shown): <evidence>
- [ ] V4 wake round-trips: (a) old->new <trigger id>  (b) assistant->new <evidence>  (c) lane ack <lane id>
- [ ] V5 operator told in one message: new link, what moved, what did not and why
- [ ] STAND DOWN: old manager's last message points to the new session; new manager has archived the old one after a wake landed in the new session

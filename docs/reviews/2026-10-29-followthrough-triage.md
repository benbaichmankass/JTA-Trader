# Review follow-through: triage pre-read for Thursday planning 2026-10-29

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Pre-read for planning (Thu 2026-10-29). Lane `REVIEW-FOLLOWTHROUGH`, dispatched by Manager Session 2026-10-27a. Tier 1, read-only: **nothing
> here is killed, closed or re-dated**. Every disposition below is a PROPOSAL; the operator decides in planning. Numbers MEASURED 2026-10-28
> on `main` @ `c24351c3` with `scripts/ops/pipeline.py` and `scripts/ops/review_followthrough.py`; re-run them, don't quote them.

## 1. What mature orgs do (the basis for the design)

| practice | what it says | tag |
|---|---|---|
| Google SRE Workbook, ch. 10 "Postmortem Culture" ([sre.google/workbook/postmortem-culture](https://sre.google/workbook/postmortem-culture/)) | Its worked bad example: every action item had *equal priority* and only one had a *tracking bug*, and "without a formal tracking process, postmortem action items are often forgotten". So each item needs an owner, a priority and a tracked ticket. | PRAC |
| Atlassian Incident Handbook, "Postmortems" ([atlassian.com/incident-management/handbook/postmortems](https://www.atlassian.com/incident-management/handbook/postmortems)) | Every postmortem is tracked as a Jira item until done and approved. Actions are split into *priority actions* (root cause) and *improvement actions*, and each is prioritised in the team's normal backlog against its SLOs. I could not confirm a specific deadline length (the page body did not render for me). | VEND |
| Scrum Guide 2020, Sprint Retrospective | "The most impactful improvements are addressed as soon as possible. They may even be added to the Sprint Backlog for the next Sprint." A retro output only counts once it goes into the next plan. | PRAC |
| Kanban WIP limits / Little's Law (L = λW) | With arrival rate fixed, the only way to shorten the time an item waits is to cap the work in progress. A plan above capacity grows the queue; it does not grow throughput. | ACAD (Little 1961) / PRAC |
| Quant research pipelines (López de Prado, "The 10 Reasons Most Machine Learning Funds Fail", *J. Portfolio Mgmt* 2018) | Research is an assembly line of specialised stations with hand-offs, not a set of individual "silos". An idea that nobody tests is not inventory. | ACAD |

**What the design takes from them:** one owner and one date per item (SRE, Atlassian). A tracked completion rate that the next review reads
first (SRE follow-up reviews, Atlassian approvals). Carry-over goes into the next plan before new work (Scrum). The plan is capped at capacity
(WIP / Little). Kill is a first-class outcome (`pipeline.py` already requires a `terminal_reason`).

## 2. The measurement (populations stated)

`python3 scripts/ops/pipeline.py --stats` on 2026-10-28 reads **2,344 items** over 6,290 records, with 0 unreadable:

- **1,011 open**: 606 routed and 405 queued;
- **505 due**;
- **54 unrouted**, the oldest 94 d (`BL-20260726-BRANCH-PROTECTION-DOC-STALE-4-CHECKS`), so the alarm is breached;
- closed: **838 killed vs 495 done**.

These match the manager's 07:46Z read.

`python3 scripts/ops/review_followthrough.py --window-days 28 --all-sources` reads two populations: the 2,344 pipeline items plus the 971
checklist rows. The source is classified from the id, origin and title text, because the store has no source field. In the table, **cohort** is
everything filed in the last 28 d. **Backlog** is everything open now. "≤7d" is the share of the cohort that was closed within 7 d of filing.

| source | cohort filed | done | killed | open | ≤7d | backlog open | due % | median age (d) | no owner |
|---|---|---|---|---|---|---|---|---|---|
| perf-followup | 24 | 11 | 0 | 13 | 33% | 13 | 31% | 6 | 3 |
| performance-review | 24 | 4 | 0 | 20 | 17% | 67 | 27% | 46 | 41 |
| frontier | 31 | 9 | 0 | 22 | 29% | 22 | 23% | 13 | 2 |
| ml-review | 15 | 3 | 0 | 12 | 13% | 23 | 48% | 24 | 6 |
| health-review | 24 | 10 | 0 | 14 | 42% | 336 | 26% | 65 | 275 |
| weekly-audit | 12 | 2 | 0 | 10 | 17% | 10 | 10% | 9 | 0 |
| programme-review | 16 | 1 | 1 | 14 | 12% | 15 | 13% | 12 | 0 |
| research-ops | 121 | 23 | 1 | 97 | 19% | 97 | 13% | 6 | 18 |
| ltr | 39 | 8 | 0 | 31 | 20% | 31 | 10% | 2 | 7 |
| desk | 60 | 5 | 1 | 54 | 10% | 54 | 6% | 1 | 36 |
| soak-watch | 73 | 2 | 28 | 43 | 40% | 43 | 70% | 24 | 6 |
| code-audit | 7 | 2 | 0 | 5 | 29% | 48 | 73% | 31 | 2 |
| system-audit | 12 | 5 | 1 | 6 | 50% | 19 | 84% | 29 | 0 |
| other (lanes, PR reviews, manager) | 1,020 | 306 | 60 | 654 | 31% | 803 | 42% | 13 | 92 |

**Cross-check.** The backlog-open column sums to 1,581. That equals 1,011 open pipeline items plus 570 open checklist rows (213 queued, 29
in_flight, 20 blocked, 308 landed_unproven).

**Reading (the lane's, not a measurement):**

- **No review source closes even half of what it filed within a week** (12–50% over the 28 d cohort).
- `health-review` carries the largest backlog: 336 open, median age 65 d, 275 with no owner. Most of it is the pre-reset `BL-*` backlog that
  was migrated on 2026-09-24 and has never been dispositioned since.
- The performance review's 41 no-owner items are the same pattern: its pre-reset `PB-*` items.

**What this script does not measure.** The research-ops claim "167/301 FAILs in 7 d have no next test" is about research *results*, not
filed follow-ups. That stays with `research-ops` and is not measured here.

**A bug found and fixed in this PR.** `pipeline.owner_of` did not parse the `routed_to: "checklist:<ROW>"` form. **40 routed items** (9 of
them due) therefore read as unowned, and they inflated the `/health-review` drain gate's `unrouted` class. The fix and a planted self-test case
are in `scripts/ops/pipeline.py`.

## 3. The 505 due and 54 unrouted, grouped

The two sets overlap: every unrouted item is due.

**By owner state** (owner resolved by `pipeline.owner_of` after the fix):

- 226 are routed to a **queued** checklist row;
- 189 are routed to a **landed_unproven** row;
- 54 are unrouted;
- 14 are routed to a row that is already **done**;
- 10 are routed to an owner that **does not resolve**;
- 7 are routed to a PR and 5 to a research unit.

Sum: 505.

**By due bucket:**

- 312 lapsed (checked once, cadence elapsed);
- 110 had a dated deadline that passed;
- 80 were never checked;
- 3 have no cadence.

**By age:**

- 42 are under 7 d;
- 88 are 7–14 d;
- 176 are 14–30 d;
- 134 are 30–60 d;
- 65 are over 60 d.

**Concentration.** The 415 items routed to live rows sit on **120 rows**. The top 10 rows hold 193 of them, and 65 rows hold exactly one each.

| row | state | due items |
|---|---|---|
| ORDER-AUDIT-3 | landed_unproven | 38 |
| ROUTE-PROP-TRACKING | queued (owner manager) | 26 |
| AUD-20261019-SOAK-ITEMS-LONG-EXIT | queued (owner manager) | 25 |
| ROUTE-CI-LANDING-FIXES | queued (owner manager) | 23 |
| ROUTE-RESEARCH-HARNESS-FIXES | queued (owner manager) | 20 |
| LIVE-PARITY | landed_unproven | 15 |
| GUARD-FIDELITY | queued (owner "unassigned") | 14 |
| ROUTE-LEG-EVIDENCE | queued (owner manager) | 11 |
| DOCS-DRIFT | queued (owner "unassigned") | 11 |
| PROTECTION-HARDENING | landed_unproven | 10 |

## 4. Proposed bulk dispositions (the operator decides)

| # | group | n | proposal | kind |
|---|---|---|---|---|
| T1 | Routed to a **done** row: SOAK-GATE1-REGRADE (6), PAIRS-GAPS (4), LTR-MECHANICS-VENUE-SNAPSHOT (2), PHONE-AMEND-REFUSED-1025 (1), LTR-2-RECORDS (1) | 14 | One Sonnet pass re-runs each `origin.rerun`. Close as `done` where the row's close covers the item, otherwise re-route to a live row. | keep-and-schedule (a) |
| T2 | **Soak items**, all 24 routed to `AUD-20261019-SOAK-ITEMS-LONG-EXIT`. 8 still state a ≥10-fill exit, against the mechanical-soak doctrine (OPERATING-PLAN § 2). Two duplicate pairs (turtle_soup, vwap on 10-04 vs 10-18). | 24 | Schedule the row this week. One lane rewrites each item to the mechanical 1–2-trade definition, or kills it as superseded by the doctrine. Merge the duplicate pairs and keep the 10-18 records. | (a) + merge |
| T3 | **Pre-reset health `BL-*` items**, unrouted, 60–94 d old (the alarm's oldest tail). | 39 | **Keep and schedule** (one lane) the ten that are money-path or data-correctness: DUPLICATE-PNL-NETTED-SIBLING-ROWS, BULK-RECONCILER-CLOSE-NO-EXIT-NO-PNL, ALPACA-BALANCE-NONE-WHILE-ACCOUNT-READS-ACTIVE, TP-CROSS-CLOSE-RECORDS-A-STALE-MARK, THE-TRAILING-AMEND-NEVER-PASSES-OCA-KEY, A-STRAY-OCA-LEG-FILLED-AND-THE-JOURNAL-NEVER-LEARNED, OPEN-TRADES-COLLAPSES-A-READ-FAILURE, IB-BREAKER-CANNOT-TELL-A-PEER-CLOSE, BYBIT-OPEN-ORDERS-UNDER-REPORTS-LEGS, XRP-DECLARED-TARGET-EXCEEDS-VENUE-CAP. For the other **29**, the lane re-runs `origin.rerun`. An item that no longer reproduces is killed with "stale pre-reset; origin.rerun no longer reproduces as of <date>". An item that reproduces is routed. | (a) ×10, kill-if-stale ×29 |
| T4 | **Recent unrouted**, 0–34 d: PI-20260924-SZ7MG8W7-0001, PI-20261021-K43EKTZA-0002, PI-20261022-HOPS2047-0001, PI-20261023-GGAWBEOX-0001, PI-20261024-4CGB8QKR-0001, PI-20261025-QBV5GOQX-0001, PI-20261026-4A80398B-0002, PI-20261026-7O3NWGHQ-0001, PI-20261026-R5NY8N6S-0001, PI-20261026-UNSVQMPZ-0001, PI-20261026-A7W7ZYW1-0001, PI-20261026-CDTDGVDN-0001, PI-20261026-01764UCV-0001, PI-20261027-VIPEZN1F-0001, PI-20261028-QFMQD2BK-0001 | 15 | Route each to its owning row this week (a). 4a80398b-0002 is addressed to *this* week's performance review: route it there. | (a) |
| T5 | **Owner does not resolve**: PI-SOAK-…slv_trend_1h, turtle_soup, vwap (routed_to holds prose), 1BPXEUJR-0001, 7E02E0F4-0001, JWMGXOTH-0003, FOYBZ9CV-0001, P3PFA1GK-0002, QOTFUEXV-0003, ALQWWPXT-0003 | 10 | Re-route to a row or unit id, or kill. The three soak items fold into T2. | (a) or (c) |
| T6 | **Routed to 120 live rows**: 226 on queued rows, 189 on landed_unproven rows. | 415 | **Disposition per row, not per item.** In planning, each owner row takes (a), (b) or (c), and its due items follow it. For a landed_unproven row the item *is* the row's proof, so both close together when the row's observation lands. Start with the 10 rows in § 3 (193 items). Owners "manager" or "unassigned" on a queued row get a lane, or the row is dated (b). | (a)/(b)/(c) per row |
| T7 | **Candidate duplicates** (first 50 chars of `what` identical — verify before merging; JC-SA-02 ×4 may be four different models): 6 groups, 14 items, e.g. JC-SA-02 ×4, live-vs-replay parity trend_donchian_{sol,eth}_prop, slv_trend_1h NEEDS-DATA | 14 | Merge: keep the newest record and kill the rest as "duplicate of <id>". The turtle_soup and vwap pairs are counted in T2. | merge |
| T8 | **Code-audit (09-27) and system-audit (09-29)** due items | 35 + 16 | All are routed to live rows, so they are inside T6. Flagged separately because their median age is 29–31 d: the rows ORDER-AUDIT-3, PROTECTION-HARDENING and GUARD-FIDELITY are where they sit. | inside T6 |

**Headline.** Of the 505 due items:

- 415 belong to 120 live rows, so planning faces **~120 row decisions plus ~90 item decisions**, not 505 item decisions;
- 39 are pre-reset health items, of which 10 are proposed to keep and 29 to kill if stale;
- 24 soak items reduce to one row's work;
- 14 sit on rows that are already done.

**Projected effect if T1–T5 and T7 are accepted:** the unrouted count goes to 0 and the oldest-unrouted alarm clears.

## 5. How this stays fixed

See the manager SKILL, § "Review follow-through: every review output gets ONE disposition in Thursday planning".

- Step 0 is this script's table.
- Carry-over comes first.
- Each item gets exactly one disposition: (a) scheduled, (b) dated, or (c) killed.
- A WIP cap equal to post-review capacity.
- Each review's Layer 0 runs `review_followthrough.py --source <review>` before it files anything new.

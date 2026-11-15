# UI redesign 2026-11: reconciliation of the 11-11 design doc against the operator's text

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**
> **Gates this adds or changes: none.** It removes two guards that the 11-11 doc proposed (`insight-link-guard`, `topic-map-guard`). Both are
> reported as numbers instead (operator 2026-10-29, "no new gates").

Written by the UI assistant manager (session_01AFoLuMr5RixbuwJtqED344) on 2026-11-12 at Manager Session 2026-11-11a's request.

**Why this exists.** [`ui-workplan-2026-11.md`](ui-workplan-2026-11.md) (PR #24818, 2026-11-11) designed nine rows. Its own § 0 says it was written
*without* the operator's wording ("inferred from the row ids"). This file checks each section against two sources: the governing spec, row
`UI-REDESIGN-2026-11` (operator 2026-11-09, addenda 1-5), and each row's own operator note in the work store
(`python3 scripts/ops/work.py --via direct get <ID>`, read 2026-11-12 ~09:15Z). **Where they disagree, the operator's text wins.** The 11-11 doc
is now `superseded` by this file. Its MEASURED findings (code paths, tables, routes) remain good reference. Its *behaviour* sections bind only
where this table says **stands**.

## Per section

| § | row | verdict | operator text that decides it | what changes |
|---|---|---|---|---|
| 1 | UI-OAUTH-SIGNIN | **stands** (approach A: enforce the existing Google + passkey gate) | Row note: "The API routes the SPA calls must also check the session ... a UI-only gate is not enough ... Tier 2 (touches the web API)." | The row says Tier 2, so the flip is Tier 2, not the doc's Tier 3 (field beats comment). The consumer inventory (PR #24855) and the four POST routes it names are prerequisites. Sequence it after SEC-8001-LOCKDOWN (clients move to HTTPS first). |
| 2 | PROP-UI-BRACKETS-CLOSED | **corrected** | Operator 2026-11-10, verbatim: "the prop trades don't have the brackets on the chart (or in the data - we need to fix this)" and "closed prop trades aren't showing up in the log". | The doc read it as "closed prop trades show final SL/TP" and missed both asks. The row asks for (1) OPEN prop trades to carry SL/TP/R in the open-trades payload and on the chart. Today the API has a stale SL in `/prop/status` that never reaches the payload, and a hand-moved stop is not recorded (LTR-ACCOUNT-SCOPED-ACTIONS). (2) CLOSED prop trades to be merged into the "Last closed trades" log; the panel prints "not included here yet". Manager direction 2026-11-12: prop closed trades are in the closed-trade snapshot v1, keyed by fill id from `prop_fills`. The doc's `/prop/fills` column work is a sub-step of (2). |
| 3 | UI-CHART-BRACKET-HISTORY | **stands** | Row: earlier SL/TP subtle, a marker on the bar of each update, the current/final bracket stays main, prop too. | It is folded into the snapshot/markers contract (`docs/reference/bot-api-reference.md` § "Trade chart snapshot + decision markers", PR #25205), which reuses this section's `levels`/`updates` shape. TP history for exchange packages stays `unrecorded`: the SPA shows "—" with that reason. `tp_moves` stays an optional Tier-2 follow-up. |
| 4 | PERF-PAGE-CATEGORY-TABLE | **corrected** | Row: one row per category "(live, prop, paper portfolio, paper testing)"; columns include "average trade duration, capital utilisation, return on time in trade, expectancy in R, profit factor, max drawdown". Spec PERFORMANCE: "date-range picker (calendar, start+end) instead of window buttons". | (a) The categories are the four books of UI-FOUR-BOOKS, named **Live money · Prop · Paper portfolio · Paper testing**, not `real_money/real_mirror/paper/prop`. This answers the doc's § 13 Q5 (four separate categories). (b) No 7d/30d/90d/all buttons: the route takes `start`/`end` dates (unknown or inverted → 400). (c) Add **max drawdown**, which the doc left out. The doc's metric definitions otherwise stand. |
| 5 | PERF-PAGE-PNL-CHART | **corrected** | Row: "X axis days (default 30, range selectable); one line per category; filter or break down by asset class, broker account and strategy; hover or click on a point shows the $ P&L behind the %". | The range comes from the Performance date-range picker, default the last 30 days, not window buttons. The doc's extra symbol and measured-only filters may stay. The % denominator (doc § 13 Q3) is still open; **default until the operator says otherwise: capital at range start** (doc's proposal), labelled on the axis. |
| 6 | INSIGHTS-LEDGER | **corrected** | Row: append-only insights linked to the work they became, "shown as a table beside the reports log", written by performance reviews and the manager. Manager skill § "The insights ledger": "A dangling link is reported by the route, never a CI gate." | The `kind: "insight"` pipeline items + `GET /api/bot/work/ledger` stand. **Strike `insight-link-guard`** (a new gate; the skill rules it out). The ledger is a Performance-page table. Not to be confused with the spec's "Remove Insights entirely": that is the old AI-Analyst Insights page (`/api/bot/insights/*`), which goes. |
| 7 | UI-MODELS-STRATEGIES-TABLES | **stands, under the spec** | Row: sortable, filterable tables; a row click opens the full card. Spec STRATEGIES & MODELS: models first, the model naming regime, hierarchy by family → versions, hit-rate for anything shadow or beyond, real data on Strategies. | Tables are the list view inside the spec's Strategies & Models page; the spec's ordering and hierarchy win where the doc is silent. Dashboard #238 already carries `ModelsTable` and a strategies table. |
| 8 | UI-SIDEBAR-COLLAPSE-DESKTOP | **stands; built** | Row: "collapsable on the desktop version like it is in the mobile version". | Dashboard #237 merged 2026-11-11 (hide/☰ toggle, localStorage). It matches the operator's "like mobile"; the doc's icon rail is not required. Open: observe it in a browser. |
| 10 | WORK-TOPIC-TAXONOMY | **stands, minus the guard** | Row: topics derived from the roadmap ref plus a topic map, no free text, backfill, chips and grouping in the console work queue. | **Strike `topic-map-guard`** (a new gate). Unmapped milestones and rows are a count on the work route, visible, not a CI failure. The consumer is the console Work queue (UI-CONSOLE-ARTIFACT C3) and the SPA Work page, which the spec makes the console's overview page. |
| 11 | build order | **superseded** | Spec scoping rule; the AM-UI plan. | Order now: dashboard #238 (Overview R1/R3/R2/M1) → M3 work cards → M2 health bar → M4 closed-trade cards (snapshot routes) → B1 decision markers → Performance (§ 4, § 5, § 6 here) → Strategies & Models (§ 7) → Admin → Work (§ 10). The OAuth enforce flip follows SEC-8001-LOCKDOWN. |
| 13, 16 | operator questions | **partly answered** | — | Q5 is answered by the four-books rule (above). Q1-Q4 stay open, each with the default stated in [`ui-workplan-2026-11-questions.md`](ui-workplan-2026-11-questions.md); the manager carries them to the decisions page. No lane waits on them. |

## For the SPA lane (what stands)

Follow `UI-REDESIGN-2026-11` first. From the 11-11 doc, use only: § 3's bracket overlay drawing, § 4's metric definitions (plus max drawdown, four
books, date range), § 7's table-then-card pattern, and § 9's cross-cutting rules (null → "—", read_state beside nullable counts, provenance on hover).
Prop open-trade brackets and prop closed trades in the closed log are **required**, not optional.

## Work queue tabs (SPA)

Added 2026-11-12 by a lane under AM-UI. Operator, 13:50Z, verbatim: *"also, the design specs i'm giving you here for the planning artifact
should also inform the design for the work que tabs in the UI"*. The planning artifact is the decisions page (claude.ai artifact
`3YvSRcb5eMSbTL8zmD9Bwt`, read 2026-11-12 ~14:30Z). It has five tabs, and the SPA Work page gets the same five. **The design comes from the
artifact. The data comes from the bot.** The artifact runs on hand-pushed snapshots in its own artifact database (collections `answers`,
`workplan`, `lanestatus`, `rd`, `rdreg`, `gates`, `gate_answers`, `plans`, `plan_edits`). The SPA reads bot routes instead, and the work store
(`src/runtime/work_store.py`, CLI `scripts/ops/work.py`, routes `/api/bot/work/items*`) is the source of truth.

**Gates this adds or changes: none.** No CI guard. Unmapped or dangling items are counts on the route (same rule as § 10).

### Rules for all five tabs

- A null field renders as "—", never `0` or "unknown". Every nullable count has a `read_state` beside it (`read` / `could_not_look` /
  `absent`). An unreadable source returns its list as `null` with a 503 or `present:false`, never as an empty list.
- Numbers carry provenance (`src/runtime/provenance.py`: MEASURED / ESTIMATED / FABRICATED / UNVERIFIED). Hover shows the source and `as_of`.
- **The client derives nothing the route does not publish.** Stage, state counts, "moved today", "changed in 7 days" and waiting/answered
  all come from the route. The artifact computes per-AM tiles and answered counts in the browser. In the SPA, the route computes them.
- **No confirm dialogs.** A choice saves when it is clicked, and "Clear" undoes it. The artifact's Gates "accept all" uses `confirm()`. The
  SPA does not.
- Filters go in the URL query string, so a filtered view can be linked. A remembered tab may use `localStorage` (try/catch). Nothing else does.
- **Writes from the SPA.** The two existing write families take service tokens a browser does not hold: `POST /work/decision` takes the
  `DASHBOARD_API_TOKEN` bearer, and `POST /work/items*` takes `X-Work-Store-Token`. The precedent for a browser write is `require_session`,
  which `POST /api/bot/trade-approvals/{token}` uses and which PR #25322 copies for `POST /api/bot/gates/{id}/decision`. Each new SPA write
  below is a `require_session` route that writes through the same store function as the existing token route. **A new write route is
  Tier 2.**

### Inventory measured 2026-11-12 ~14:40Z

The population is the routes declared on `main` @ `5a0bd82b9`, plus each one fetched from `https://ict-bot.duckdns.org`.

| route | on main | live | note |
|---|---|---|---|
| `GET /api/bot/work/decisions` | yes | 200 | `requestCount 0`, `unanswerableOperatorEdgeCount 8`. The planning questions live only in the artifact, not as `decision_requests`. |
| `POST /api/bot/work/decision` | yes | — (not called) | token route. The answer goes to transit and stays `in_transit` until a committer writes it into the work object. |
| `GET /api/bot/work/items` | yes | 200 | filters: `state`, `due`, `parent`, `since`, `kind`, `limit` ≤1000, `offset`. **No `owner` / `week_lane` / text filter.** `total` is present. |
| `GET /api/bot/work/items/{id}/events` | yes | — | the per-item history, which is the source for "moved today". |
| `POST /api/bot/work/items/{id}/note` · `/set` | yes | — (not called) | token routes with `If-Match`. |
| `GET /api/bot/work/topics` | yes | 200 | `read_state`, `topics`, `rows`, `unmapped`, `coverage` (WORK-TOPIC-TAXONOMY). |
| `GET /api/bot/work/snapshot` · `/scoreboard` · `/ledger` | yes | 200 | `/snapshot`: `openNow`, `next`, `waitingOnOperator`, `closedRecent`. |
| `GET /api/bot/work/brief` | yes | **502** | one fetch. Not this design's work; noted for whoever owns the brief route. |
| `GET /api/bot/gates[/{id}]`, `POST …/{id}/decision` | **no** (PR #25322, open, Tier 2 hold) | 404 | lane GATE-REGISTRY |
| `GET /api/bot/research/registry` | **no** (branch `rd-registry`, unmerged) | 404 | lane RD-REGISTRY, `src/runtime/rd_registry.py` |
| lane status / plans / plan edits | **no** | 404 | not built anywhere |

The `week_lane` field (surge / throttle) is in the item's `extra` on 172 items of a 1,000-item read. That read hit `limit=1000`. The store
holds more items: `/work/topics` counts `n_rows 1705`, a different cut that also includes pipeline items.

### Tab 1: Decisions

**Design.** Questions waiting on an answer come first, then answered ones. A `waiting | answered | all` filter, with counts from the route.
Each card shows the evidence, the options with the recommendation listed first and marked, and **always an "Other" free-text choice**. An
optional note goes beside the choice. The state chip shows `waiting` / `in transit` / `recorded`. In transit is not recorded: the
`answerState` field decides.

**Route.** `GET /api/bot/work/decisions` (exists). Use `requests[]` with `answerState`, and `summary.byAnswerState` and
`summary.waitingOnYouTotal` (null means unknown, rendered "—"). Read `writeGate.acceptsWrites` before enabling the buttons.
- **Missing (data, Tier 1):** the planning questions are not in the store, so the route reads 0. The manager writes each one as a
  `decision_requests` entry on its work object (fields `id`, `title`, `evidence`, `options[{key,label}]`, `recommended`). The artifact's
  `answers/{qid}` shape `{choice, note, updated_at}` maps to `{chosen, free_text}`.
- **"Other" on every question:** `work_decisions.py` already defaults `allowsFreeText` to true unless the author writes `false`. The SPA
  shows "Other" whenever that flag is true. Authors do not write `false` on planning questions.
- **Missing write (Tier 2):** `POST /api/bot/work/decision/session`, behind `require_session`. Same body and the same transit append as the
  token route. The 409-when-committed rule is unchanged.

### Tab 2: This week

**Design.** One brief status card per lane (per assistant manager): a headline, then *moved today / working now / stuck / next*. Filters:
AM, bucket (surge / throttle / standing / landed_unproven / added since planning), state, and search over id, title and note. Below the
cards is one row per task: state chip, id, title, updated (relative time, "—" if null), PRs, owner, and the latest note behind a disclosure.

**Route.**
- Rows: `GET /api/bot/work/items`. **Missing params (Tier 1, read-only):** `owner_prefix` (AM), `week_lane`, `q` (id/title/note), and
  `state=open`. Add a `counts` block by `owner × state` (the artifact computes this in the browser). Add `latest_note` per item, the newest
  `note` event, so the SPA does not fetch `/events` for every row.
- Lane cards: **missing**, `GET /api/bot/work/lanes` (Tier 1, read). Per AM it publishes `moved_today` (items with a state event since
  00:00Z, from the event log), `working_now` (`in_flight`), `stuck` (`blocked`, plus `blocked_on` set), and `next` (queued, by
  `priority_rank`). Each list carries ids with titles and a `read_state`. An optional `headline` and `as_of` come from the AM's own note on
  its parent row (the manager's prose, labelled as prose). The artifact's `lanestatus` doc is that prose today.
- **Related, not duplicated:** the console Work queue (UI-CONSOLE-ARTIFACT C3, bot #25164) and `src/console_connector/tabs.py::workplan`
  already build the week-lane totals and the by-owner counts. The new route reuses `console_connector.data.week_lane_totals` and does not
  re-implement it. Topic chips come from `GET /work/topics` (WORK-TOPIC-TAXONOMY).
- Writes: none in v1. The operator comments through Decisions or Plans.

### Tab 3: R&D registry

**Design.** One card per idea (strategy leg or hypothesis, ML model or idea). Each card has its **computed** stage (idea → queued → testing
offline → failed / iterating / passed-waiting → demo book → real money, or shadow/advisory for ML → retired; or stuck, with the reason), the
latest result (verdict, unit, date, n), test counts (run / passed / failed / indeterminate / open), and the next step. Views: ML ideas,
strategy ideas, **changed in the last 7 days**. Filter by stage, plus search.

**Route.** `GET /api/bot/research/registry` (branch `rd-registry`, unmerged; `src/runtime/rd_registry.py`). It is the artifact's `rdreg`
shape: `ideas[{id,name,track,kind,stage,why,lr{v,u,d,n,t},ev{r,n,f},c{units,passed,failed,indeterminate,open},next,last,books}]`,
`stages[{stage,label}]`, `changed{count,basis,items}`, and `summary.per_stage_per_track`.
- **Missing:** the route is not on `main` and not deployed. **Before the SPA binds, check** (not verified here) that `c.*` counts that could
  not be read come back as null with a `read_state`, not 0. `changed` is computed server-side over a stated window (`since` param, default 7d). The registry sets the stage; the
  client never does.
- Writes: none.

### Tab 4: Gates (becomes the Admin Gates panel)

**Design.** One row per gate: what it blocks, effect (PREVENTS-WRONG / BLOCKS-RIGHT / BOTH / NEITHER), where it is, who added it, its
authorization, and the cost of removing it. Choices: **keep / remove / report-only**, with the audit's recommendation shown (dashed outline,
"rec."). Order: **real money AND no authorization on record first**, then all real-money gates, then the rest. Filters: scope, answer state,
effect, search. A bulk "accept the recommendation for every waiting gate shown" button applies at once, with no confirm dialog, and reports
how many it set and how many it skipped (operator-preference rows with no recommendation).

**Route.** `GET /api/bot/gates` and `POST /api/bot/gates/{id}/decision` from **PR #25322 (lane GATE-REGISTRY)**. The POST already uses
`require_session`. The SPA panel is **dashboard PR #247**. This design does not add a route or a panel. It asks those two PRs for:
1. a sort key from the route (`real_money desc, authorization_class == none first`), so the client does not rank;
2. `recommendation` on each row (the audit's KEEP / REMOVE / MAKE-REPORT-ONLY);
3. no `confirm()` in #247's bulk action;
4. `hits` stays null with `hits_read_state` until `comms/gates/hit_probes.json` measures it.
The Work page's Gates tab is a link to the Admin panel, not a second copy.

### Tab 5: Plans

**Design.** Two lists: the **frontier sub-queue** (state, title, why it might beat what we have, consumer, baseline it must beat, family,
estimated cost) and the **ML development plan**, grouped by track (plan state, carried-by row and its state, next step, iteration steps,
closes-when). A third view, *my adds and edits*, shows each with status **new → relayed → applied** and the owner's reply. The operator can
**add an item** and **suggest an edit** on any item. The manager relays both to the owner (FRONTIER-RESEARCH for the queue, AM-ML for the
plan), and the owner marks them applied.

**Route.**
- Frontier queue: the work store already holds it as `FRONTIER-Q-*` items (7 in the 1,000-item read, owner lane FRONTIER-RESEARCH, roadmap
  `L-ML-LIVE`). They have **no common parent**, so `GET /work/items?parent=` cannot select them. **Missing (data, Tier 1):** set
  `parent_id: FRONTIER-RESEARCH` on them (or add an `id_prefix` param). The fields `why`/`baseline`/`family`/`est_cost` go in `extra.frontier`.
- ML development plan: `docs/plans/ml-plan-items.yaml`, checked by `scripts/ops/ml_plan_status.py`. **Missing (Tier 1, read):**
  `GET /api/bot/ml/plan`, which publishes the plan items joined to their carrying rows (`ref`, `ref_state`) with a `read_state`.
- Adds and edits: **missing.** They are work-store items of `kind: observation`, `parent_id` = the target item (or the plan root for an add),
  `extra.plan_edit = {section, item_id?, kind: add|edit, text, status, reply}`. Status changes through `POST /work/items/{id}/set`. The
  manager relays by setting `owner`; the owner closes with `terminal_reason: applied` or `declined: <why>`. **Missing write (Tier 2):**
  `POST /api/bot/work/plan-edits`, behind `require_session`, which calls the store's `add`. Read: `GET /work/items?kind=observation&parent=…`.

### Build order

Backend first within each tab. A tab ships only when its route is live. Before that the tab shows "not built yet", never an empty list.

1. **This week:** items filters + counts + `latest_note` (Tier 1), then `GET /work/lanes` (Tier 1), then the SPA tab. It needs nothing
   unmerged.
2. **Decisions:** planning questions written as `decision_requests` (Tier 1 data), then the SPA tab read-only, then
   `POST /work/decision/session` (Tier 2), then the answer buttons.
3. **R&D registry:** merge and deploy `rd-registry` with the null-count fix, then the SPA tab.
4. **Gates:** land #25322 (Tier 2, its own hold) and #247 with the four asks above. No new row beyond alignment.
5. **Plans:** frontier parent backfill + `GET /ml/plan` (Tier 1), then `POST /work/plan-edits` (Tier 2), then the SPA tab.

Rows: `UI-WQ-*` in the work store, parent `UI-REDESIGN-2026-11`, owner AM-UI, roadmap `M6`.

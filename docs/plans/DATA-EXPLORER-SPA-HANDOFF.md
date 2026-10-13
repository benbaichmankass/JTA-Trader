# Data Explorer SPA — handoff for the dashboard session

> **Doc status:** `historical` · category `history` · last verified `2026-10-13` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · handoff written by lane DATA-EXPLORER (checklist row `DATA-EXPLORER`); a record of the state on 2026-10-13, not maintained.

Target repo: `benbaichmankass/ict-trader-dashboard` (Svelte 5 + Vite, SPA under `webapp/`, ONE network chokepoint `webapp/src/lib/api.ts`, auth in `lib/auth.ts`, CI checkers `webapp/tests/*.mjs`; `auth-bearer.mjs` must stay green). Read that repo's `CLAUDE.md` first. Public repos: never commit secrets, IPs or balances. Deploy = merge to `main` (`pages.yml`), then verify the deployed bundle contains your strings **with a negative control**. A human must confirm it renders.

Operator ask (2026-10-13, verbatim): *"add a tab in the UI's data explorer to view the test that we've run and that are qued - basically, a searchable and filterable catalog of all the research tests that include the summary of the test, the results, the topic (roadmap priority) that they came from, the data used to run the test, etc. The signals catalog should also be a sub tab in the data explorer, as well as the trade log and the rest of our database, but we need to make sure that a) it's functioning (the tab is pretty dead right now), and b) that its designed in a way that is useful to me so that I can stay on top of our data"*
Structure (operator, same day): *"all the data tables should be accessible in the data explorer, but the structured and most important data should lead the tab (and there should be an overview of the explorer with summary and health stats on the database)"*.

## Sub-tabs (importance order)
1. **Overview** (landing) — per database (`trade_journal.db`, `trainer_store.db`): size, table count, WAL/integrity if readable; per key table rows, newest-row timestamp + age, STALE flag, 24h/7d growth; research-queue counts by status, stuck count, last 10 verdicts. **Needs a new session-gated endpoint (`/api/bot/db/overview`) that does NOT exist yet** — see "Not built". Until it exists, show the research-queue half from the catalog API and render the DB half as "not available yet", never zeros.
2. **Research catalog** (API built, PR #17869).
3. **Trades**, 4. **Signals**, 5. **Order packages** — use the existing routes (below).
6. **All tables** — the existing raw browser (`/api/bot/db/tables`, `/api/bot/db/table/{name}`), both DBs, nothing hidden.

Every sub-tab: search box, facet filters, sortable columns, row click → detail drawer, header "showing X of Y", `null` → "—", and **distinct "could not load" vs "empty" states** (a failed fetch must never look like zero rows; the catalog API returns `readState`/`present` for exactly this).

## Research catalog API (ungated Tier-1, public-repo data only)
`GET /api/bot/research/catalog` — query: `q`, repeatable-or-CSV facets `theme status verdict goal backend kind stuck`, `sort` (`id title theme status verdict priority lastActivity created`), `order` (`asc|desc`), `limit` (1..200, default 50), `offset`, `since` (ISO; drives "new since last visit"), `created_from`/`created_to` (`YYYY-MM-DD`).
Response: `present`, `readState` (`read|partial|unreadable`), `readErrors[]`, `total`, `matched`, `limit`, `offset`, `sort`, `order`, `facets{facet:{value:count}}` (a facet's counts ignore its own selection; the value `none` = null), `items[]`, `stayOnTop`, `generatedAt`, `roadmapAvailable`.
`stayOnTop`: `{since, sinceKnown, new:{count,items}|null, stuck:{count,items}, due:{count,items}, recentVerdicts[]}`. **`new` is `null` and `sinceKnown:false` on a first visit — render "first visit", not "0 new".** Keep last-seen per browser in localStorage (try/catch; must render without it) and send it as `since`.
Item: `id title summary whyItMatters kind cadence theme priority roadmap[{id,name,goal,goalName,status}] status(queued|due|dispatched|running|result|blocked|retired) fileStatus dueState(due|not_due|unknown) dueReason blockedReason stuck stuckReason rule{id,registeredAt,registeredBeforeRun,statistic,text}|null power{state,expectedN,minDetectableEffect}|null verdict readState resultNote metrics{scalars} resultCount dataUsed{workflow,harness,inputs,dataInputs,population,n,store} backend estMinutes createdAt lastDispatchedAt latestResultAt lastActivity links{unit,results[],run}`. Any field may be `null` → "—".
`GET /api/bot/research/catalog/{unit_id}` — `{present, id, unit, resultRows[] (≤20, newest first), resultRowsTruncated}`; `present:false` for an unknown id; 400 on a malformed id.
Columns: id · title · theme · roadmap goal/milestone · priority · status · verdict · n · last activity. Drawer: summary/question, why it matters, pre-registered rule, metrics, data used, backend + est. minutes, timestamps, links.
Live numbers 2026-10-13 (567 units): 456 result · 57 blocked · 37 dispatched · 7 queued · 4 due · 6 retired; 110 stuck. "Stuck" = blocked, or dispatched >6 h with no landed result row, or `grading.needs_review`; it does not distinguish a failed run from an unmerged result.

## Existing routes for the other sub-tabs (session-gated, `Authorization: Bearer`)
`GET /api/bot/db/tables`, `GET /api/bot/db/table/{name}` (money DB — fail-closed, keep it so). Trades/signals/order packages: look up the current shapes in `docs/reference/bot-api-reference.md` and `docs/api-tier-policy.md` (e.g. `trades_closed.py`, `order_packages.py`, `performance.py`); do not guess fields. Trades facets: account, strategy, symbol, open/closed, close reason, funding class, date; show provenance (`MEASURED/ESTIMATED/FABRICATED/UNVERIFIED`) beside any P&L, never fold `UNVERIFIED` into measured. Signals/Order packages: strategy, symbol, decision/status, account, date.

## Auth (why the tab is "dead" today)
`POST /api/auth/login` `{email,password}` → `200 {access_token}`; today it returns `500 auth_unavailable` because `JWT_SIGNING_KEY` / `ALLOWED_EMAIL` / `WEBAPP_PASSWORD_SHA256` are missing on the VM, so every `require_session` route is 401. The SPA has no login UI and no token store yet (see `docs/runbooks/restore-webapp-auth.md` §4): token store mirroring `config.ts`'s localStorage shape, one `Authorization: Bearer` line inside `get<T>()`, a login form (Settings tab can host it), and a 401 handler that surfaces the form. `/ws/market` is not gated. The ungated catalog routes must keep working with no token. Probe ladder and what each status proves: runbook §3.

## Not built (this lane)
`/api/bot/db/overview`; the SPA; the auth set-env run (waits on the operator's Actions secrets). Open items live on checklist row `DATA-EXPLORER`.

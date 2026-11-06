# Two surfaces: a live trading dashboard and a management console (design, 2026-11)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) ·
> **This is a DESIGN for operator approval. Nothing here is built, and nothing changes until the operator approves it.**
>
> Written 2026-11-04 by lane `UI-TWO-SURFACE-DESIGN`, dispatched by Manager Session 2026-11-04b (session_01AFoLuN7HERxg65eHjtmMYE) with
> the operator's authority. Row: `UI-LIVE-STACK-REDESIGN`. Related: `UI-OVERVIEW-HEALTH-CARDS`, `ALERT-LEDGER-TO-MANAGER`,
> [`WORK-STORE-DESIGN-2026-11.md`](WORK-STORE-DESIGN-2026-11.md) (PR #23020, D1–D9 approved ~23:37Z),
> [`docs/audits/2026-11-04-system-integration.md`](../audits/2026-11-04-system-integration.md) (#22954).
> Every count below is dated 2026-11-04. Re-read the source before quoting one.

## Gates this adds or changes

**No gate on trading, deploys, merges or pipelines.** Two access controls on new surfaces are disclosed here (canonical § "No new gates", rule d).

| # | Control | What it blocks, where | Why | How to remove it |
|---|---|---|---|---|
| G1 | **Console connector sign-in.** The new read-only JTA MCP connector (§ 2) asks for OAuth sign-in. Only the email in `ALLOWED_EMAIL` gets through, the same allowlist `src/web/api/auth.py` uses. | Anyone else using the connector, so the console artifact shows them nothing. It blocks no session, workflow or diag relay. Sessions keep reading `/api/diag/*` and `/api/bot/*` as they do today. | The connector serves the trade journal, P&L, account balances and the work register to a page that can be shared by link. Today those routes are open to anyone with the URL unless `SITE_AUTH_ENFORCE` is on. That flag defaults OFF (`src/web/api/auth.py:234`), and I did **not** verify its value on the VM. | Run the connector authless (one config line). The page then works for anyone who adds the connector. |
| G2 | **Upstream fetch budget.** The connector's cache fetches each live-VM route at most once per its TTL (15–60 s, § 2.3), however many viewers or tabs are open. | A connector read can be up to one TTL old. It cannot be fresher. | Audit F10: reads compete with the 115 s tick on the trader VM. The budget caps console load on that VM at a known number of requests a minute. | Set the TTLs to 0. Every viewer call then goes straight through. |

There is no new execution gate, no default-off flag and no approval step. The trading-dashboard changes (§ 4) replace polling with push and gate nothing.

## 0. The answer in one paragraph

Split by **what the operator does there**. The **trading dashboard** (the Svelte SPA, unchanged host, browser-direct through Caddy) keeps
what is watched second by second: health cards, open positions with their brackets, fills, urgent alerts and the live chart. It moves
from **polling to push**: one SSE stream fed by the alert ledger and the journal, and a chart that takes its prices **straight from the
provider in the browser**. The **management console** is a Claude artifact. It holds everything that is read, discussed and acted on
over hours: the work queue and decisions, the trade journal and package history, the data explorer, ML, strategies and the ladder,
research, and reports. The artifact runtime blocks `fetch` to our hosts, so the console gets its data through a **read-only JTA MCP
connector** that the page calls with the operator's own claude.ai credentials (`mcp.watchTool`, refetch at least every 30 s). **Host the
connector on the trainer VM, not the trader VM.** ML and research data are local there after WORK-STORE D7. Live-VM routes go through one
shared cache with a fixed fetch budget (G2), so console traffic on the trader VM is constant and does not grow with viewers. Notes go into
the page's own `db` as a durable inbox that the manager drains into the work store, with an optional immediate wake. "Ask Claude" uses the
`sample` capability, which spends the operator's plan usage and never API credits.

---

## 1. Inventory: the SPA today, and where each part goes

**Source:** `benbaichmankass/ict-trader-dashboard` @ `03f64a5` (2026-10-29), `webapp/src`. I read `lib/nav.ts`, `lib/api.ts`, `lib/ws.ts`
and each route's `api.*` calls. The population is **25 route files** (`routes/*.svelte`, including `SignIn` and `Devices`) and
**7 components that call the API**. The REST client has **one chokepoint** (`api.ts::getRaw`), so the route list below is complete for
REST: it is every path string in `api.ts`, and it does not depend on a grep across pages. Push is one socket, `lib/ws.ts` → `WS /ws/market`.

**Polling measured in code:** `Overview.svelte:380` polls every 15 s while the tab is visible, and `Positions.svelte:19` polls every 30 s.
The other pages fetch once on open. **`/ws/market` is a per-connection server loop, not a push** (`src/web/api/routers/market_ws.py`). Each
connected client gets its own 1 s loop that re-reads positions and re-fetches **candles from the brokers through the VM** (crypto every 2 s,
IB every 8 s). Load therefore grows with viewers, and tick-level data flows through the VM. Both break the operator's standing requirements.

### 1.1 Pages → surface

| SPA page (section) | `/api/bot/*` routes it calls | Goes to | Why |
|---|---|---|---|
| **Overview** | `stats`, `positions`, `performance`, `candles`, `trades/closed`, `strategies`, `accounts/balances`, `config`, `news/recent`, `pnl/history`, `prop/overview`, `reports`, `signals`, `work/snapshot` + `/ws/market` | **TRADING**, slimmed (§ 4) | Health cards, positions, the live chart and today's P&L stay. Its `work/snapshot`, `reports` and `news` cards go to the console. |
| Positions (Activity) | `positions` (30 s poll) | **TRADING** | Open positions with entry, SL, TP and uPnL |
| Accounts (Accounts) | `accounts/balances`, `config` | **TRADING** (balances + mode) | Watched live. The per-account trade log goes to the console journal. |
| Prop (Accounts) | `prop/status`, `prop/fills`, `prop/tickets`, `prop/overview`, `prop/reconcile` | **Split**: cushion, open tickets and fills go to TRADING; reconcile and history go to CONSOLE | The rule-distance cushion is live risk. Reconcile is review work. |
| Health (Admin) | `health/latest`, `health/services`, `notifications` | **TRADING**, as the UI-OVERVIEW-HEALTH-CARDS detail page | The operator reaffirmed system health on the trading dashboard (23:45Z) |
| Signals (Activity) | `signals` | **TRADING** (the live event stream); history goes to CONSOLE | The last few signals are live context. Older ones are review material. |
| Trades (Activity) | `trades/closed`, `config` | **CONSOLE** (journal); today's fills stay on TRADING | History and filters |
| Order Packages (Activity) | `order-packages`, `config` | **CONSOLE** | Decision-level history with model scores and the Claude grade |
| Performance, Insights, Reports (Performance) | `performance`, `insights/*`, `reports`, `reports/{id}`, `work/brief` | **CONSOLE** | Analysis, read over hours, and the material the operator wants to discuss with Claude |
| Strategies, Promotion, Exit Ladder, Backtesting, News, Signals Catalog (Strategies & Models) | `strategies`, `shadow/stats`, `exit-ladder/soak`, `backtests/sweeps`, `news/recent`, `research/catalog` | **CONSOLE** | Strategy, ladder and research flows |
| Models, GPU Spend (Strategies & Models) | `ml/registry`, `ml/status`, `gpu/spend` | **CONSOLE** | ML lifecycle |
| **Work** (+ Roadmap toggle) | `work`, `work/brief`, `work/checklist` (4.19 MB, F7), `work/decisions`, `work/schedule`, `roadmap` | **CONSOLE** | Work queue, plans and decisions: the main reason the console exists |
| Data Explorer (Admin) | `db/overview`, `db/tables`, `db/table/{name}`, `research/catalog`, `research/catalog/{id}`, plus the Explorer components over `order-packages`, `signals`, `trades/closed` | **CONSOLE** | Databases |
| Logs (Admin) | `logs` | **CONSOLE** | Log review. Urgent lines arrive on TRADING as alerts (§ 4). |
| Runbooks (Admin) | (static) | **CONSOLE** | Operating schematic |
| Learning (nav section, no route file) | (`learning` routes) | **CONSOLE** | Curriculum progress |
| SignIn, Devices | `/api/auth/*` | **TRADING** (stays) | Auth for the SPA itself |

**Count:** of 25 route files, **7 stay on TRADING** (Overview slimmed, Positions, Accounts, Health, Signals as a live feed, SignIn,
Devices), **1 splits** (Prop), and **17 move to CONSOLE**. Of the **40 distinct REST base paths** in `api.ts` (a parameterised path such as `reports/{id}` counted once), the trading dashboard keeps **13**
(`stats`, `positions`, `accounts/balances`, `config`, `health/latest`, `health/services`, `notifications`, `prop/status`, `prop/fills`,
`prop/tickets`, `prop/overview`, `signals`, `pnl/history`), plus the new stream (§ 4). `candles` is retired with T3. The console connector wraps the other **26**, plus the new work-store and alert
routes. It also re-reads a few shared ones, such as `config` and the `signals` history.

### 1.2 What the console adds that the SPA never had

- **Two-way communication.** Notes, comments and "ask Claude about this" (§ 3). The operator's request was "where I can communicate with
  them".
- **The work store's live register** (`/api/bot/work/items`, `/items/{id}/events`, WORK-STORE S1) instead of the 4.19 MB checklist dump.
- **The alert ledger history** (`/api/bot/alerts`, ALERT-LEDGER step 2). The trading dashboard shows only urgent, live alerts.

---

## 2. The console's data path under the artifact runtime

**The constraint (measured by the manager earlier tonight, and consistent with the runtime contract I read):** the artifact page cannot
`fetch` or open a WebSocket to `ict-bot.duckdns.org`. It also cannot iframe our pages. What it can do is declared capabilities, read from
the runtime contract 0.2.96 type definitions (`mcp.d.ts`, `db.d.ts`, `comments.d.ts`, `sample.d.ts`, `user.d.ts`):

- `mcp`: call the **viewer's** claude.ai connectors with the viewer's credentials. The page never holds a token. `watchTool(server, tool,
  input, handler, {refetchInterval})` replays the cache, then refetches. **The refetch interval has a floor of about 30 s.** Refetching
  pauses while the page is hidden and catches up on return. Calls with the same identity are coalesced, so N cards on one view cost one
  call. A view can hold at most 64 watches.
- `db`: documents kept outside the page, live through `onSnapshot`. Claude reads and writes them through `ArtifactData`. Collections and
  total size have caps (`quota_exceeded`).
- `comments`: write-only threads. `sendToClaude` posts a comment **and notifies Claude sessions watching the artifact**.
- `sample`: ask Claude with page-supplied data and page-side tools. It draws on the **viewer's own Claude usage**.

### 2.1 Options compared

| | **(a) Read-only JTA MCP connector** (recommended) | (b) Claude-written snapshots in the page's `db` | (c1) Republished artifact with embedded data | (c2) Static JSON on an allowed CDN |
|---|---|---|---|---|
| **How** | A small MCP server (streamable HTTP) wraps the `/api/bot/*` read routes and the work store as read-only tools. The page uses `watchTool` per card. | A manager or cron session reads the API and writes summary docs with `ArtifactData`. The page renders them with `onSnapshot`. | A session regenerates the HTML with the data inlined and publishes it. | Push data to a package on `cdn.jsdelivr.net/npm`, the only data-capable allowed origin. |
| **Freshness** | 30 s floor (watch) plus the cache TTL (15–60 s, G2). In practice under 90 s, and on demand for drill-downs. | As fresh as the last session that ran: hours. Nothing updates between sessions. | Hours, and the whole page reloads every time | Minutes to hours, and npm publish is not built for this |
| **Plan usage** | **None for reads.** Connector calls are tool calls, not model calls. The type definitions mention no usage for `mcp`. I have not measured this; the C2 closing check does. | Every refresh is a Claude session turn, paid from plan usage for each snapshot | Same as (b), and more | None |
| **VM load** | Bounded by the fetch budget: at most one fetch per route per TTL, from one host. Low and constant. | One read burst per session | Same | None |
| **Hosting** | One small process. Recommended host: trainer VM (§ 2.2). | None | None | npm account; public by construction |
| **Security** | OAuth sign-in to the connector, allowlisted to `ALLOWED_EMAIL` (G1). The server holds `DASHBOARD_API_TOKEN`, which `require_site_session` accepts **only for GET/HEAD** (`src/web/api/auth.py`, `_SAFE_METHODS`), so it is read-only at the credential level as well as in the tool list. No tool has `readOnlyHint: false`. | Data is copied into the artifact's store and readable by everyone the page is shared with | Same, and it lives in version history | **Public**. Rejected for P&L and balances. |
| **Failure modes** | Connector down: each card keeps its last-good data with `cache.storedAt` shown, and an error banner names the cause. Live VM slow (F10 brief cold 60.85 s): the cache serves last-good with `read_state: stale` and does not block. Token expiry: shell reconnect prompt (`needs_reauth`). | Silent staleness. A missed session means old numbers with nothing saying so. That is the collapsed-states trap unless every doc carries `as_of`. | Same | Same, plus it is public |
| **Verdict** | **Recommended** | **Fallback only**: the console's first page can run on it before the connector exists, with `as_of` on every doc | Rejected | Rejected |

Also considered: the `files` capability, which reads a Claude Code project's files. It reaches a project, not our VM or API, so it cannot
serve live data. Rejected.

### 2.2 Where the connector runs

| Host | For | Against | Verdict |
|---|---|---|---|
| **Trainer VM** (`ict-trainer-vm`) | It is not the trader's box (F10). After WORK-STORE **D7** the research results store is local, and the trainer mirror already fills `trainer_store.db`, so the ML, research, backtest and GPU tools read **locally** and put **zero** load on the trader VM. Live-VM routes go through the shared cache (G2): one requester, a fixed budget. | It needs public HTTPS: a Caddy site and a DNS name. I have **not verified** that the trainer VM accepts inbound 443 today (OCI security list). The work store is on the live VM (D1), so work reads still cross VMs. They are cheap SQLite reads behind the API, and the budget caps them. | **Recommended** |
| Live VM, as a separate low-priority process (`nice`, its own systemd unit, behind the existing Caddy) | No new DNS or ingress. The process sits next to the data. | It shares CPU and IO with the 115 s tick, which is what F10 warns about. It would also share the single uvicorn worker's DB if run in-process. | Fallback, if trainer ingress is refused |
| Hosted serverless (Cloudflare Workers or similar) | Off both VMs | A new vendor, an account and an egress allowlist. It would hold a credential to our API, and console data would depend on a third party. WORK-STORE § 2.1 rejected a hosted store on the same grounds. | Rejected |

### 2.3 Tools and cache budget (initial set; every tool is a GET)

| Tool | Upstream | Host-local? | Cache TTL |
|---|---|---|---|
| `work_items(state,due,parent,since,limit,cursor)`, `work_item_events(id)`, `work_brief()`, `work_decisions()` | `/api/bot/work/items`, `/items/{id}/events` (WORK-STORE S1), `/work/brief`, `/work/decisions` | live VM | 15 s |
| `alerts(since,kind,channel)` | `/api/bot/alerts` (ALERT-LEDGER step 2) | live VM | 15 s |
| `journal_trades(window,account,strategy,limit,cursor)`, `order_packages(...)`, `signals_history(...)` | `/trades/closed`, `/order-packages`, `/signals` | live VM | 60 s |
| `db_overview()`, `db_tables()`, `db_table(name,filters,limit,offset)` | `/db/*` (the gated `db_explorer` routes: the service token covers GETs) | live VM | 60 s |
| `strategies()`, `strategy_status()`, `config_roster()` | `/strategies`, `/config`, plus `scripts/ops/strategy_status.py` output served by the API | live VM | 60 s |
| `performance(window)`, `insight(name)`, `reports()`, `report(id)`, `prop_reconcile(account)` | `/performance`, `/insights/*`, `/reports*`, `/prop/reconcile` | live VM | 60 s |
| `ml_registry()`, `ml_status()`, `shadow_stats()`, `backtest_sweeps()`, `gpu_spend()`, `research_catalog(q)`, `research_unit(id)` | trainer stores (D7) | **trainer, local** | 30 s |
| `roadmap()` | `/roadmap` | live VM | 300 s |

**Every response carries `as_of` (the upstream fetch time), `read_state` (`read | stale | could_not_look`) and its population** (rows
scanned, truncated or not). This follows the collapsed-states rule: a failed upstream read never comes back as an empty list.

**Budget arithmetic (G2):** 14 live-VM endpoint identities × at most one fetch per TTL gives a worst case of about 14 × 4/min =
**56 requests/min** if every card is open at once at the 15 s TTL. For comparison, today **one** open Overview tab drives a 1 s positions
read loop plus a 15 s poll of about 14 routes, and that load scales with tabs. Paginated tool inputs make different identities, so the
data-explorer drill-downs are the variable part. They run on viewer clicks, not watches.

### 2.4 The page

- **Capabilities:** `{mcp: {servers: [{server: "JTA Trader", tools: [...]}]}, db: {rules: [...]}, user: {}, comments: {}, sample: {}}`.
  Add `downloads: true` for a CSV export of a journal view, if wanted.
- **Layout:** tabs for **Work** (queue, due, decisions, in-flight lanes with staleness), **Journal** (trades, packages, signals), **Data**
  (explorer), **ML**, **Strategies & ladder**, **Research**, **Reports**, and **Inbox** (§ 3).
- **Display arm:** `watchTool` for summaries, at `refetchInterval: 30_000` on Work and alerts and 120 s elsewhere. **Action arm:**
  `callTool` on click for drill-downs. Each card shows `cache.storedAt` and the upstream `as_of`, and `could_not_look` renders as such,
  never as 0. A missing field renders "—".
- **No tool argument shapes are guessed.** The connector's tool schemas are written in C1, and the page reads `describeTool` at view time.

---

## 3. Notes, comments, and "ask Claude about this"

### 3.1 How a note reaches the manager

| Path | Durable? | Wakes now? | Notes |
|---|---|---|---|
| **N1. Inbox doc in the page's `db`** (recommended, always on) | **Yes.** It survives manager rotation. | No | The "Note" button on any card writes `inbox/{id}` = `{text, anchor: {tab, card, item_id?}, created_at, by: user.id(), status: "new"}`. Rules: `inbox` read `admin`, write `interact`. **Manager skill, start of session and the 05:52Z/17:52Z reviews:** `ArtifactData list inbox where status == new`. Each note becomes a **dated item in the work store** (`work.py add`, WORK-STORE S3; until then `checklist.py add` with a `due_by`). The manager sets the note's `status: filed` and `item_id`, and the card shows the filed item. A note that needs no work is closed in the review with a stated reason. No third register: the inbox is a transport, like the alert ledger, and work lives only in the work store. |
| **N2. Comment + `sendToClaude`** (recommended for conversation) | Yes as a thread. The wake is only as durable as the watcher. | **Yes, if a manager session is watching the artifact** | The platform "notified Claude sessions watching the artifact". A watch ends with its session, so the **manager skill's start-of-session step re-watches the console** (`ArtifactComments` watch), the same pattern as subscribing to #17895. `canSendToClaude()` returning `no_session` tells the operator nobody is listening, and the page then offers N1. The manager replies in the thread. Anything that needs work becomes a work-store item. |
| N3. `fire_trigger` on a manager inbox trigger, through the viewer's built-in "Claude Code Remote" connector | Durable wake | **Yes, always** | The page calls `fire_trigger(<id>, text)` once per note, which wakes the persistent manager session. The trigger is rebound at manager rotation: the new manager recreates it and writes its id to `db` `config/inbox_trigger`. **Unverified:** that this connector's `fire_trigger` is callable from an artifact page as the viewer. Probe it at C4 before relying on it. **Optional** (decision U4). |
| ~~N4. A write tool on the JTA connector~~ | — | — | **Rejected for v1.** It breaks "read-only connector", and N1 already reaches the store through the manager, who owns the register. |

### 3.2 "Ask Claude about this"

- **Mechanism:** `sample` (declared `{sample: {}}`). Each card has an "Ask" button that sends the card's own data (already in the page),
  a short system brief (what the system is, provenance rules: MEASURED / ESTIMATED / UNVERIFIED, render null as "—"), and the question.
- **Tools for depth:** `sample(input, {tools})` passes **page functions** that call the JTA connector's read tools (`callTool`), so Claude
  can pull more rows, such as the leg's trades or the item's events, without the page pre-loading them. Read-only, because the connector
  is.
- **Cost:** the viewer's own plan usage. **No Anthropic API credits are spent**, so it complies with the binding "Nothing spends Anthropic
  API credits" rule. Calls run only on a click and use `modelTier: "default"`. `rate_limited` backs off and never loops.
- **Memoryless:** each answer stands alone. Anything worth keeping is turned into a note (N1) with one click ("Save as note"), and it then
  reaches the manager.

---

## 4. The trading dashboard: slimmed scope and the push design

### 4.1 Scope (what stays)

1. **Health cards** (UI-OVERVIEW-HEALTH-CARDS): trading per account, including when the connection was last verified; research and ML
   per resource; the work-queue summary; ML versions per book. They bind to store-served aggregates (WORK-STORE § 6) and arrive **as
   pushed frames**.
2. **Open positions** with brackets (SL/TP) and live uPnL, plus today's **fills** and **order packages** as they happen.
3. **Urgent alerts:** `channel == system` or `priority == high` from the alert ledger, the same filter that wakes the manager.
4. **The live chart** with the system's own markers: signals, entries, exits, and SL/TP lines that move as brackets move.
5. Account balances and mode, and the prop cushion with its open tickets.

### 4.2 Push: one broadcaster, many clients

```
alert ledger (alerts_ledger.jsonl)  ─┐
trade_journal.db (packages, trades,  ├─► broadcaster (ONE asyncio task in ict-web-api)
  fills, bracket changes)            │      reads each source's cursor once per 1 s
health snapshot (one 30 s task)     ─┘      (rowid / byte offset), builds frames
                                                │
                                                ▼
                      GET /api/bot/stream  (SSE; ?ticket= when SITE_AUTH_ENFORCE is on)
                      frames: {seq, ts, type: alert|package|trade|fill|bracket|position|health, payload}
                      reconnect: Last-Event-ID → backfill from a 10-min ring buffer, else the client re-snapshots via REST
```

- **Load is O(1) in viewers.** The per-connection loop in `market_ws.py` is replaced by one reader and a fan-out of the same bytes. One tab
  or ten cost the same DB reads.
- **SSE, not WebSocket.** It is one-way, which is all we need. `EventSource` reconnects with `Last-Event-ID` by itself, and it passes
  through Caddy as plain HTTP. Auth uses the existing single-use `ws-ticket` (`POST /api/auth/ws-ticket`) in the query, the pattern
  `require_site_session` already applies to `/ws/market`.
- **REST stays the authority on membership** (the lesson in `ws.ts`). On load and on a gap the client fetches `/positions` and
  `/accounts/balances` once. Frames then update rows. **The 15 s and 30 s polls are deleted.**
- **The event source is the alert ledger** from ALERT-LEDGER-TO-MANAGER, steps 1–2. The broadcaster tails it with a byte-offset cursor.
  When the ledger moves into `work_store.db` (WORK-STORE § 6, ALERT-LEDGER step 4), the cursor becomes a rowid with no frame change. For
  journal events the cursor is `MAX(rowid)` per table. The trader writes nothing new: the reads are cheap indexed range scans, done once
  per second in total, not once per client.
- **Health frames** come from one 30 s task that computes the cards (each with `read_state` and population) and pushes them only when
  they change.

### 4.3 Market data never touches the VM

- **Chart: one full charting library for EVERY symbol** (operator U3, 2026-11-05 ~00:36Z: *"Full library, but in phases so that we get
  crypto live fast"*). It is **TradingView Lightweight Charts** (`lightweight-charts`, Apache-2.0). It is already the SPA's only runtime
  dependency, and `components/LiveChart.svelte` already draws on it. Our own markers and price lines show signals, orders, fills and
  SL/TP brackets, from the pushed events. The end state is no longer "widget plus markers list". The chart is fed **from the provider in
  the browser**, in three phases:

  | Phase | Symbols | Browser-reachable feed | Cost (secondary sources, 2026-11-05: **UNVERIFIED**, re-check on the vendor page before buying) | Key in the browser? |
  |---|---|---|---|---|
  | **T3a, crypto (first, fast)** | every `*USDT` leg (Bybit) | Bybit **public** v5 WebSocket (`kline.*`, `tickers.*`) | **$0** | **No.** The public stream needs no key. |
  | **T3b, equities and ETFs** | Alpaca and IB stock/ETF legs | **Alpaca Market Data WebSocket**: the IEX feed on the free Basic plan, or full SIP on **Algo Trader Plus, about $99/month** | $0 (IEX) or about $99/mo (SIP) | **Yes**, because the stream authenticates with a key pair. Mitigation: a **dedicated, otherwise-empty Alpaca paper account** whose key is used only for data. A leaked key can reach only that empty paper book. The operator originates it. |
  | **T3c, futures** | IB futures legs (MES, MNQ, …) | **Massive (formerly Polygon) futures WebSocket**: about **$999/month per exchange plan** (CME, CBOT, NYMEX and COMEX are each separate) | about $999/mo per exchange | Yes. Same exposure as T3b. Massive has no empty-account mitigation, so the key would sit in the SPA bundle's runtime. |

  - **Futures alternative, recommended for when T3c is reached:** **Databento** CME real-time. It is usage-based plus pass-through CME
    license fees: roughly $16–33/month for a narrow ES/CL set in its 2023 launch pricing, so it is likely higher now. **UNVERIFIED.**
    Databento has **no browser WebSocket**, so it needs a thin **relay on the trainer VM** (one upstream connection, fanned out to the
    browser). That costs far less than Massive, keeps the key server-side, and still keeps ticks off the **trader** VM, which is the point
    of the 12:37Z requirement. The futures phase is a spend decision, put to the operator with fresh quotes when T3c starts.
  - **Why Lightweight Charts plus Bybit WS beats the widget for phase 1:** it is **faster**, not just better at the end.
    - The library is already installed and already renders candles and markers in `LiveChart.svelte`.
    - Bybit's public stream needs no key, no account and no relay.
    - Phase 1 swaps the candle source from `/ws/market` to the Bybit socket and binds markers to the stream. That is one component's data
      source.
    - The widget would add an iframe that cannot carry our markers, which is a dead end that T3b and T3c would replace anyway.
  - **Until each phase lands,** that phase's symbols keep today's chart: `lightweight-charts` on the `/ws/market` candles. Nothing goes dark
    while the phases roll out. `/ws/market` candles are retired only for the symbols a phase has moved, and fully after T3c.
- **uPnL is computed in the browser** from the position's entry and size and the provider's last price. The VM stops pushing a price
  every second. For instruments with no browser feed, the position frame carries the broker mark that `order_monitor` already records,
  at the tick's cadence.
- **`/ws/market` candles are retired** phase by phase, as each class of symbols moves. That removes the 2 s and 8 s broker candle fetches per connected client,
  and the IB pacing risk that `market_ws.py` documents.
- **What still goes through our stack:** signals, packages, orders, fills, bracket changes, alerts and health. These are only the
  system's own events, which matches the 12:37Z requirement.

### 4.4 What this does not fix

The trader's **115 s tick** (F8, `TICK-DURATION-115S`) limits how fresh any system event can be. Push delivers an event within about 1 s
of its DB write. It cannot make the write itself happen sooner.

---

## 5. Build order, rows, and what leaves the SPA

### 5.1 Steps

| Step | What | Tier | Depends on | Closing observation |
|---|---|---|---|---|
| **T1** | Broadcaster + `GET /api/bot/stream` (SSE), with journal and health frames | 2 (web API service) | — (journal frames); ALERT-LEDGER steps 1–2 (alert frames) | Two browsers open: the VM's DB read count per second is the same with 1 and with 2 clients, and a synthetic `send_route_test_ping` reaches both within 2 s |
| **T2** | SPA subscribes to the stream; 15 s and 30 s polls deleted | 1 (dashboard repo) | T1 | Caddy log: 0 `/api/bot/positions` requests from the SPA between loads over 1 h with a tab open |
| **T3a** | **Crypto chart live, first:** Lightweight Charts on the Bybit public WS, with signal, order, fill and bracket markers; `/ws/market` stops fetching candles for `*USDT` | 1 (SPA) + 2 (candle-loop change) | prices: none; live markers: T1 (until T1, markers come from a REST snapshot on load) | A crypto leg's chart ticks with the API's `/ws/market` candle fetches for `*USDT` at 0; a fill on that leg appears as a marker within 2 s of its journal row (once T1 is live) |
| **T3b** | Equities and ETFs on the Alpaca Market Data WS (IEX free, or SIP about $99/mo), with a dedicated empty paper-account data key that the operator originates | 1 (SPA) + operator key | T3a; the operator's key | An equity leg's chart updates intraday from the Alpaca stream; the key in use belongs to an account with no positions and no funds |
| **T3c** | Futures: Databento through a trainer-VM relay (recommended) or the Massive futures WS (about $999/mo per exchange); `/ws/market` candle loop retired entirely | 2 (relay) + an operator spend decision | T3b; fresh vendor quotes | `/ws/market` connections 0 for a day; VM broker-candle fetches attributable to the UI = 0 |
| **T4** | Health cards (`UI-OVERVIEW-HEALTH-CARDS`) as pushed frames | 1–2 | T1; WORK-STORE S4 for the work-queue card | Each card shows `read_state` and population; killing a source shows `could_not_look`, not 0 |
| **C1** | JTA MCP connector on the trainer VM: tools from § 2.3 (non-work tools first), cache budget, OAuth allowlist (G1), DNS + Caddy | 2 (new service + ingress on the trainer VM) | U1, U2; trainer ingress check | `claude.ai` lists the connector; `journal_trades` returns rows matching `/trades/closed` for the same window; live-VM request rate from the connector ≤ the G2 arithmetic over 1 h |
| **C2** | Console artifact v1: Journal, Data, ML, Strategies & ladder, Research, Reports | 1 | C1 (or (b) snapshots as a stopgap) | Operator opens it; every card shows `as_of`; a recorded check that a page-driven `mcp` read used no Claude plan usage |
| **C3** | Console Work tab on the work-store tools | 1 | WORK-STORE **S1** (`/work/items`) and **S4** (readers flipped) | An item written by a session appears on the Work tab within 45 s |
| **C4** | Inbox (N1) + comments (N2) + manager skill start-of-session step; N3 probe if U4 = yes | 1 | C2; WORK-STORE **S3** for `work.py add` (until then `checklist.py add`) | A note typed at T becomes a dated work-store item by the next manager start, with the item id shown on the note |
| **C5** | "Ask Claude" (sample) with connector-backed tools | 1 | C2 | An answer on a journal card cites rows fetched through a tool call |
| **R1** | Retire the 17 console pages from the SPA (§ 5.3) | 1 (dashboard repo) | C2–C4 observed for 7 days | SPA nav shows only the TRADING set; no `/work/checklist` requests in the Caddy log |

T-steps and C-steps are independent and can run in parallel. **C3 is the only step that waits on the work store.** The rest work against
routes that exist today, plus the alert ledger.

### 5.2 Rows (filed by this PR, queued; the operator approved the design 2026-11-05 ~00:36Z)

| Row | Steps | Tier | due_by | Roadmap |
|---|---|---|---|---|
| `UI-LIVE-STACK-REDESIGN` (existing) | this design → `landed_unproven` on merge; the operator decided U1–U6 on 2026-11-05 ~00:36Z; closes when this PR merges | 1 | 2026-11-10 | unmapped (as filed) |
| `UI-TRADING-PUSH` (new) | T1, T2 (the stream and the polls deleted) | 2 | 2026-11-18 | L-OPS |
| `UI-CHART-CRYPTO-LIVE` (new) | T3a | 1–2 | 2026-11-12 | L-OPS |
| `UI-CHART-EQUITIES-FEED` (new) | T3b | 1 | 2026-11-25 | L-OPS |
| `UI-CHART-FUTURES-FEED` (new) | T3c | 2 | 2026-12-09 | L-OPS |
| `UI-OVERVIEW-HEALTH-CARDS` (existing) | T4 | 1–2 | 2026-11-10 (as filed) | unmapped (as filed) |
| `UI-CONSOLE-CONNECTOR` (new) | C1 | 2 | 2026-11-13 | L-OPS |
| `UI-CONSOLE-ARTIFACT` (new) | C2, C3, C4, C5 | 1 | 2026-11-20 | L-OPS |
| `UI-SPA-RETIRE-CONSOLE-PAGES` (new) | R1 | 1 | 2026-11-27 | L-OPS |

### 5.3 What leaves the SPA (after R1's condition holds)

Work, Roadmap, Runbooks, Reports, Insights, Performance, Strategies, Models, GPU Spend, Exit Ladder, Backtesting, Promotion, News, Trades
(history), Order Packages, Data Explorer and Logs: **17 route files**. Also leaving: the Data Explorer's Explorer components, and the
`Learning` section and `Signals Catalog` placeholder, which are nav entries, not route files. Overview loses its work, reports and news cards. Prop loses reconcile and history.
`api.ts` drops **27 of 40** base paths (26 console, plus `candles`). **Nothing is deleted from the API**, because the connector reads the same routes. Only the
`/ws/market` candle loop is removed (T3).

---

## 6. Decisions for the operator (one popup): ANSWERED 2026-11-05 ~00:36Z

The operator's answers, verbatim, relayed by Manager Session 2026-11-04b (session_01AFoLuN7HERxg65eHjtmMYE):

| # | Answer, verbatim | Effect |
|---|---|---|
| U1, U2, U5 | *"Approve U1+U2+U5 (Recommended)"* | A read-only JTA connector, on the trainer VM, with email sign-in (G1). **The operator approved G1 and G2 as disclosed.** |
| U3 | *"Full library, but in phases so that we get crypto live fast"* | **Changes my recommendation.** Lightweight Charts with our own markers for every symbol, in phases T3a (crypto), T3b (equities) and T3c (futures). The widget is dropped as the end state (§ 4.3). |
| U4 | *"Yes, after a probe (Recommended)"* | N3 is built at C4 once a probe shows `fire_trigger` works from the page |
| U6 | *"Retire after 7 days (Recommended)"* | R1 as written |

The questions as they were put:

| # | Decision | Recommendation | Why |
|---|---|---|---|
| **U1** | The console's data path: a **read-only JTA MCP connector** that the artifact calls with your claude.ai sign-in, versus Claude-written snapshots in the artifact's store | **Connector (Recommended)** | Fresh to under 90 s, no plan usage per refresh, and load on the trader VM is capped. Snapshots are hours stale and spend plan usage on every refresh. |
| **U2** | Where the connector runs | **Trainer VM (Recommended)**; fallback: a low-priority process on the live VM if the trainer can't take inbound HTTPS | It keeps console reads off the trader's box (F10). ML and research data are local there after D7. |
| **U3** | Live chart for equities and futures (crypto uses Bybit's keyless browser feed either way) | **TradingView widget plus a markers list for now; revisit a browser-side feed key later (Recommended)**. Alternative: an Alpaca market-data key in the browser, with overlays. *(Superseded by the operator's answer above.)* | No keyless browser feed exists for IB or Alpaca symbols. A key in the browser is readable by anyone who opens the SPA. |
| **U4** | Notes: also wake the manager immediately through a `fire_trigger` button (N3), on top of the durable inbox and comments | **Yes, after a probe confirms it works from the page (Recommended)** | Without it, a note waits for the next manager start or a watching session. |
| **U5** | Connector access: an `ALLOWED_EMAIL` sign-in (G1) or authless | **Sign-in (Recommended)** | The page can be shared by link, and the data is P&L and balances. |
| **U6** | Retire the 17 console pages from the SPA once the console has run for 7 days | **Yes (Recommended)** | Two surfaces with the same pages drift apart. The trading dashboard becomes what you described: "mostly about the live data feed". |

---

## 7. Changes vs System Map v2

- The **Svelte dashboard box** splits in two. TRADING is fed by `/api/bot/stream` (SSE), with the chart fed by provider feeds in the
  browser. CONSOLE is a Claude artifact fed by the JTA connector on the trainer VM.
- A new edge, **artifact `db` inbox → manager → work store**, carries operator notes. The alert ledger edge into the SPA becomes the stream.
- `/ws/market` drops its candle loop.
- Unchanged: the trade journal, trainer store, work store (D1), alert ledger, brokers, IB gateway, Caddy, and CORS for the SPA.

## 8. Risks

- **Console reads the trader VM through the connector.** The budget (G2) caps it at about 56 requests/min. That is a cap, not zero. If the
  tick work (TICK-DURATION-115S) shows API reads matter, raise the TTLs. Moving the work store itself would reopen WORK-STORE D1, so it is
  not proposed.
- **Vendor prices in § 4.3 come from secondary sources** and are UNVERIFIED. T3b and T3c re-check them on the vendor's own page
  before any purchase.
- **Unverified items**, each closed by the step named: trainer VM inbound 443 (C1); whether `mcp` calls from a page spend plan usage (C2);
  `fire_trigger` from a page (C4); the VM's current `SITE_AUTH_ENFORCE` value (C1 reads it before choosing the stream's auth).
- **Two auth stacks.** The SPA keeps its passkey and device sessions. The connector uses OAuth to claude.ai. Both allowlist the same
  email, so revoking access means changing `ALLOWED_EMAIL`, which covers both.
- **Rollback:** every step is additive until R1. R1 is a revert in the dashboard repo, and the API routes stay throughout.

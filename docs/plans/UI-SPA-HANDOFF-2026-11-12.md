# SPA handoff: the trading-dashboard steps an SPA lane can start today

> **Doc status:** `historical` · category `history` · last verified `2026-11-12`
> Written 2026-11-12 by the UI standing lane, part 2 (session_01AFoLuMw1bWyUmi4HkqYBX8), dispatched by Manager Session 2026-11-11a.
> **Gates this adds or changes:** none.
> **Rows this executes:**
> - `UI-CHART-CRYPTO-LIVE` (T3a, due 11-12)
> - `UI-TRADING-PUSH` (T2, due 11-18)
> - `UI-OVERVIEW-HEALTH-CARDS` (T4, due 11-10)
> - `PI-20261112-Y8IHTRHC-0001` (surge SPA halves, due 11-15)
>
> Spec: [`UI-TWO-SURFACE-DESIGN-2026-11.md`](UI-TWO-SURFACE-DESIGN-2026-11.md) § 4. Gap evidence: [`docs/audits/2026-11-12-ui-spec-gap-audit.md`](../audits/2026-11-12-ui-spec-gap-audit.md).

**Why this exists.** These steps live in `benbaichmankass/ict-trader-dashboard`. This lane and the manager cannot attach that repo; that is operator decision m2. Everything the API side needs is built or in review here. This page is the exact work list, so an SPA lane can begin the moment access is granted. File paths come from the design's inventory of the SPA @ `03f64a5` (2026-10-29). Re-check each one before editing.

## 0. Order of work

1. **T3a, the crypto chart.** It needs nothing from the API, so start here. It is due today.
2. **T2, push.** It needs PR #25173 (`/api/bot/stream`) deployed.
3. **T4, health cards.** They need T2's stream client.
4. **The surge SPA halves.** Their backend routes are already live.

## 1. T3a: crypto chart live from Bybit, in the browser (`UI-CHART-CRYPTO-LIVE`)

Closing check: a `*USDT` leg's chart ticks while the API logs 0 `/api/bot/candles` and 0 `/ws/market` candle fetches for `*USDT` from the SPA. Once T2 is live, a fill marker appears within 2 s of its journal row.

**No API change is needed.** `market_ws.py` fetches candles only for the symbols in the client's `?symbols=` list. When the SPA stops listing `*USDT` symbols there, the VM fetches nothing for them.

| File | Change |
|---|---|
| `webapp/src/lib/bybitFeed.ts` (new) | Open one `WebSocket("wss://stream.bybit.com/v5/public/linear")` per tab. Send `{"op":"subscribe","args":["kline.<I>.<SYM>", "tickers.<SYM>"]}` for the symbols on screen. Interval map: 1m→`1`, 5m→`5`, 15m→`15`, 1h→`60`. Send `{"op":"ping"}` every 20 s. On close, reconnect with backoff of 1, 2, 4, up to 30 s. Expose `subscribe(sym, interval, onBar, onTick)`, which returns an unsubscribe function. Push each `kline` message's `data[]` item (`start, open, high, low, close, volume, confirm`) as a Lightweight-Charts bar `{time: start/1000, open, high, low, close}`. `tickers.lastPrice` drives the live price and in-browser uPnL. |
| `webapp/src/lib/bybitFeed.ts` (history) | Load the initial bars from `GET https://api.bybit.com/v5/market/kline?category=linear&symbol=<SYM>&interval=<I>&limit=200`. The `list` is newest first, `[start, o, h, l, c, vol, turnover]`. **UNVERIFIED: whether that endpoint sends CORS headers for a browser origin.** If it does not, load history once from our `/api/bot/candles?symbol=<SYM>&interval=<I>&limit=200` on chart open. That is one request per open, not a loop, and the stream takes over from there. |
| `webapp/src/components/LiveChart.svelte` | Pick the source by symbol: `*USDT` uses `bybitFeed`, everything else keeps `/ws/market` exactly as today. `series.update(bar)` on each kline. Markers and price lines are unchanged in this step; they come from the REST snapshot on load until T2. |
| `webapp/src/lib/ws.ts` | Build the `/ws/market` `symbols=` list **without** `*USDT` symbols. Positions still arrive on the socket. |
| uPnL (positions table, crypto rows) | `uPnL = (last − entry) × qty × (long ? 1 : −1)` using `tickers.lastPrice`. Label it "live (Bybit last)" and keep the broker mark beside it. When no tick has arrived, render "—", never `0`. |

The Bybit public stream needs no key, account or relay, and costs $0 (design § 4.3). Mainnet's public market-data stream serves the same prices the demo books trade on. Re-check that if a demo book's symbol list differs.

## 2. T2: subscribe to the stream, delete the polls (`UI-TRADING-PUSH`)

This needs PR **#25173** deployed. Closing check: 0 `/api/bot/positions` requests from the SPA between loads over 1 h with a tab open (count them in `journalctl -u ict-web-api`, which `/api/diag/journalctl` reads).

| File | Change |
|---|---|
| `webapp/src/lib/stream.ts` (new) | Opening the stream: when site auth is on, `POST /api/auth/ws-ticket` (the existing call `ws.ts` makes), then `new EventSource(API + "/api/bot/stream?ticket=" + t + (lastSeq ? "&last_event_id=" + lastSeq : ""))`. With auth off, open `/api/bot/stream` directly. Tickets are **single-use**: on `error`, `close()` and reopen with a fresh ticket, with backoff of 1, 2, 4, up to 30 s. Track `lastSeq` from every frame's `seq`. Export one Svelte store per frame type: `alert`, `package`, `trade`, `bracket`, `position`, `health`, `hello`. |
| re-snapshot | On `hello` with no `lastSeq`, or with `payload.gap === true`, call `GET /positions` and `GET /accounts/balances` once. REST stays the authority on which positions exist; frames only update rows. |
| `routes/Overview.svelte:380` | **Delete** the 15 s poll. `position` frames trigger a `/positions` refetch. `trade` and `package` frames prepend to today's fills and packages. `bracket` updates that position's SL/TP and the chart price lines. |
| `routes/Positions.svelte:19` | **Delete** the 30 s poll. Use the same frame handling. |
| urgent alerts strip (Overview header) | Show `alert` frames where `channel === "system"` or `priority === "high"`, newest first, last 24 h. |
| chart markers (`LiveChart.svelte`) | `trade` frames become entry and exit markers. `bracket` frames move the SL/TP `createPriceLine` lines. `package` frames become signal markers. |

Frame shape: `{seq, ts, type, payload}`. Payload keys are listed in `src/web/api/routers/stream.py` (`TRADE_COLS`, `PACKAGE_COLS`, and the alert keys). `GET /api/bot/stream/status` shows clients and the `read_state` of each source.

## 3. T4: health cards as pushed frames (`UI-OVERVIEW-HEALTH-CARDS`)

- Subscribe to the `health` store from `stream.ts`. The payload is the `/api/bot/health/latest` document, pushed when it changes; the server checks every 30 s.
- Each card shows its own `read_state` and population.
- A card whose source says `could_not_look` renders "could not look", never `0`.
- The work-queue card reads the work store's due view, `GET /api/bot/work/items?due=1&limit=1`, and shows its `total`. The store has been the register of record since WORK-STORE S4.
- **Watch out:** the row ages that `/api/bot/work/checklist` serves are stale until `WORK-ROW-AGE-STALE` lands.

## 4. Surge SPA halves (`PI-20261112-Y8IHTRHC-0001`)

The backend routes are merged and live, observed 2026-11-12 ~01:05Z and re-read 07:5xZ by this lane. Each PR body carries its SPA spec.

| Item | Route (live) | Backend PR | SPA work |
|---|---|---|---|
| Prop fills with bracket | `GET /api/bot/prop/fills` (bracket fields) | #24873 | Show SL/TP on the Prop fills table |
| Strategies with status | `GET /api/bot/strategies` (status testing / production / inactive) | #24924 | Status chip per strategy (`UI-CATALOG-STRATEGIES-ML`) |
| Bracket history | `GET /api/bot/brackets/history?prop_fill_id=` | #24893 | Bracket-move timeline per fill |
| P&L by category | `GET /api/bot/performance/categories`, `/performance/pnl-series` | #24893 | Category breakdown and P&L series chart |
| Work ledger | `GET /api/bot/work/ledger` | #24919 | Insight ledger list (0 `kind:insight` items exist today) |
| Work topics | `GET /api/bot/work/topics` | #24927 | Topic map of work items (150 KB, so page it) |
| Feature impact | `GET /api/bot/feature-impact/heatmap\|detail\|invest` | #24926 | Heatmap, plus drill-down on a cell |

Not built and not allowed without the operator's permission: `insight-link-guard` and `topic-map-guard` (decision m12).

## 5. What the SPA keeps, and what moves to the console

R1 (`UI-SPA-RETIRE-CONSOLE-PAGES`, 11-27) retires 17 pages once the console has run for 7 days (design § 5.3). The console now has these tabs:

- **Work:** the live store
- **Journal:** trades and packages
- **Reports**
- Data, ML roadmap, Performance, Research queue, Wake switches, System

Console URL: `https://claude.ai/artifact/YU4ZwddDFB1AD2xWV2oE3g`, v24.

# DESK-MAKER-FILLS — can the desk get maker fills on the Bybit perps, and what do they cost in adverse selection?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-MAKER-FILLS` (Tier 1, research), dispatched by Manager Session 2026-10-27a. Checklist row
`docs/claude/work/checklist/DESK-MAKER-FILLS.json` (roadmap `L-DESK`). Operator popup 2026-10-27 ~22:10Z: *"Maker fills (Recommended)"*
to *"Which structural lever should the desk edge work build first?"*. Pipeline row `PI-20261027-GV7WFI53-0001`.
Unit `research/queue/RQ-20261027-mk01-01.yaml`, rule `RULE-RQ20261027-MK01-01-MAKER-FILLS`, harness `scripts/research/desk_maker_fills.py`.

**The unit (rule, sample, thresholds) and the harness with its registered constants were committed and pushed before the registered run
(commit `1ab13e21`, 2026-10-27T23:20:51Z).** § 1–3 of this doc restate them and were written while the run was in progress, before its
result was read. Results are in § 4.

## 1. Inventory (what exists today)

### 1.1 Maker-capable paths in the order path — none

- **Entries are Market orders.** `src/units/accounts/execute.py` `_submit_order` (Bybit branch) builds
  `{"orderType": "Market", ...}` with `stopLoss` / `takeProfit` attached on the entry (position TP/SL). In `BYBIT_TPSL_MODE=partial` the
  attached legs are `tpOrderType: Market` / `slOrderType: Market`; under the default Full mode Bybit fires both as market orders too.
  So **the take-profit is a taker fill as well** — a resting reduce-only limit TP would be a second maker lever (not measured here).
- **Closes** (`close_open_position`) are `Market` + `reduceOnly`.
- **No post-only anywhere for Bybit.** `grep -rniE "post_?only|PostOnly|timeInForce" src/` finds only Alpaca `time_in_force`, Oanda `FOK`
  and order-status echoes; no Bybit call sets `timeInForce` or `PostOnly`. (Positive control: the same grep does find the Alpaca and Oanda
  uses, so the probe can see a hit.)
- **Measured consequence** (row `COST-STACK-BYBIT-TAKER-FEE`, lane DESK-EDGE-PROGRAM): 1,411 fills over `bybit_1` / `bybit_2` /
  `bybit_portfolio` (2026-07-31..10-27, truncated at 1,000 for `bybit_1`), **all `is_maker=false`, 5.50 bps per side in every fill**.
  Zero maker fills ever: the maker fee (2.0 bps per side, Bybit's published non-VIP derivatives schedule) is **UNVERIFIED** on our account.

### 1.2 Data that can measure maker fills

| source | what it holds | free / reachable from a lane | fidelity for this question |
|---|---|---|---|
| **Bybit `public.bybit.com/trading/<SYM>/`** | every linear trade of the day: timestamp (0.1 ms), aggressor side, size, price, `RPI` flag; daily `.csv.gz` back to 2020 for BTC | **free, keyless, reachable** (HTTP 200 from this container) | **the venue we trade.** No quotes: the touch must be inferred from prints. ~160 MB gz per day for the six symbols (BTC 58 MB, ETH 67 MB, XRP 17 MB, SOL 13 MB, AVAX 5 MB, ADA 3 MB on 2026-10-26) |
| Binance `data.binance.vision` futures/um `aggTrades` (+ `bookDepth`, `bookTicker` where published) | aggregated trades with maker flag; depth snapshots | free, reachable (HTTP 200) | a PROXY venue (different book, different queue); useful only as a cross-check |
| Bybit L2 order-book archive (`quote-saas.bybit.com`) | ob500 snapshots | **not reachable** from this container (proxy 502); not verified free | would allow a queue model; not needed for the trade-through rule |
| Bybit REST `api.bybit.com/v5/market/recent-trade` | last 1,000 trades | **403 from this container** | no history |
| Our own fills (`/api/bot/pnl/exchange/fills`) | 1,411 Bybit fills, all taker | via the diag relay | proves the path has never made a maker fill; cannot measure one |
| Our own orders | Market only | — | nothing to measure |

### 1.3 Is the Bybit DEMO venue's matching representative? — not established; do not assume

- Bybit's API docs (Demo Trading Service, `bybit-exchange.github.io/docs/v5/demo`) say the demo's *basic trading rules* match real trading
  and list only order retention (7 days) and a fixed rate limit as differences. They do **not** say whether a demo limit order queues
  behind real mainnet liquidity or fills when the mainnet price touches it.
- Third-party adapters (NautilusTrader) document that demo **public market data is mainnet's**; that says the prices are real, not that the
  matching is.
- **So the fill rate on `bybit_1` demo is UNVERIFIED as a proxy for mainnet.** It is settleable only empirically: post-only orders on demo,
  each compared with the mainnet public prints at the same timestamps. If demo fills a resting bid with no mainnet print at or through
  it, demo matching is optimistic (touch-fill, no queue). That comparison is part of probe (b)'s design (§ 2.2).

## 2. Measurement design

### 2.1 The quantity

For the same signal, a **taker** entry pays the far touch and the taker fee now. A **maker** entry rests a post-only limit at the near
touch; it fills only when the market comes to it (adverse selection: fills cluster on the entries that are about to go against you, and
the entries that run away never fill). Two policies for an unfilled maker order:

- **Policy F (fallback, graded):** cross as taker at T+W. Both arms then hold the same position to the same exit, so the exit cancels and
  the per-entry edge is just the entry-price difference plus the fee difference when the maker filled:
  `delta_F = (taker price − maker effective price) / mid_T × 1e4 + (5.5 − 2.0 if filled else 0)`. The unfilled entries pay the drift
  that ran away from them, so **adverse selection is inside `delta_F`**. This is the right decision statistic for a leg that must enter.
- **Policy S (skip, reported):** the filled maker entries' markouts at 1/5/15/60 min after the fill vs the taker entries' markouts from T.
  With both directions at every T the gross drift cancels, so the comparison isolates selection.

Fill rule (as dispatched): **STRICT** — some later print trades at least one tick **through** the limit within W. Under price-time
priority a print through our level means the whole level, our order included, was consumed, so no queue model is needed and the rule is
conservative. **OPTIMISTIC** (reported) — a print AT the limit.

### 2.2 The two candidates

| | (a) historical replay on Bybit trade prints | (b) live post-only probe on `bybit_1` DEMO |
|---|---|---|
| cost | $0 data; CPU minutes (download-bound, ~25 s per day for six symbols here); lane time to build ~1 h | a Tier-2/3 order-path change (post-only entry variant), a probe harness, and demo slots; no money at risk |
| time-to-n | the registered 40 days give 10,560 decision rows in one run | at ~1 probe per symbol per hour, 1,000 fills takes days–weeks, and only if demo fills at all like mainnet |
| fidelity | the venue's own prints; strict fill is conservative (no queue needed); blind to latency, a post-only reject on a book that moved, and queue position for the optimistic case; touch inferred (1-tick spread assumed, conservative for the maker) | real API path, real rejects and latency; **but demo matching fidelity is unknown** (§ 1.3), so its fill rate may say nothing about mainnet unless checked against mainnet prints |
| verdict | **build first** — cheap, fast, conservative, settles whether (b) is worth a Tier-2 change | only if (a) passes; its own first job is to measure demo-vs-mainnet fill agreement |

### 2.3 Registered rule (verbatim in the unit)

- Population: ADAUSDT, AVAXUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT; 40 days (every 9th day back from 2026-10-25: 2025-11-08..2026-10-25,
  spanning a year so no single window decides); decision times on the hour, hours 1..22 UTC; both directions. RPI prints dropped.
  Development day ADAUSDT 2026-10-26 is outside the sample.
- Primary arm: k = 0 (join the near touch), W = 5 min, STRICT fill, policy F. Fees 5.5 / 2.0 bps per side.
- **PASS** iff rows ≥ 1,000 AND measured days ≥ 30 AND pooled mean `delta_F` ≥ **+2.0 bps** AND its 95% day-block-bootstrap CI lower
  bound > 0 AND ≥ 4 of 6 symbols have mean > 0 → propose probe (b) and the post-only entry change for the `claude_desk` leg (Tier 2/3,
  to the manager). **FAIL** iff powered and not PASS. **INDETERMINATE** iff a floor is not met.
- Power: `delta_F` sd MEASURED 12.8 bps on the dev day (44 rows), 25 assumed for the higher-vol symbols → 967 independent rows detect
  +2.0 bps at one-sided α 0.05, power 0.8; the sample's 10,560 rows cover a day-clustering design effect up to ~10.
- Why +2.0 bps: a third of the one-way cost (12.3 bps per round trip measured ⇒ ~6.2 per entry); below that, the operational risk of a
  new order type (rejects, partial fills, missed entries) is not worth an order-path change.
- Secondary (reported, not graded): W = 1 / 15 min, k = 1 (one tick behind the touch), OPTIMISTIC fill, trend-aligned vs counter-trend
  split (sign of the 60-min return before T; the strategies' entries are mostly breakout-like), policy-S markouts.

## 3. What this does not do

Places nothing; changes no order path, `config/strategies.yaml`, `config/accounts.yaml` or risk logic. Not a promotion case. It does not
see latency or queue position, and it does not price a maker take-profit (a separate lever: TPs are market-triggered today).

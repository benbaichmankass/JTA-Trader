# DESK-MAKER-FILLS — can the desk get maker fills on the Bybit perps, and what do they cost in adverse selection?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-MAKER-FILLS` (Tier 1, research), dispatched by Manager Session 2026-10-27a. Checklist row
`docs/claude/work/checklist/DESK-MAKER-FILLS.json` (roadmap `L-DESK`). Operator popup 2026-10-27 ~22:10Z: *"Maker fills (Recommended)"*
to *"Which structural lever should the desk edge work build first?"*. Pipeline row `PI-20261027-GV7WFI53-0001`.
Unit `research/queue/RQ-20261027-a3f1-01.yaml`, rule `RULE-RQ20261027-A3F1-01-MAKER-FILLS`, harness `scripts/research/desk_maker_fills.py`.

**The unit (rule, sample, thresholds) and the harness with its registered constants were committed and pushed before the registered run
(commit `1ab13e21`, 2026-10-27T23:20:51Z).** It was registered as `RQ-20261027-mk01-01` / `RULE-RQ20261027-MK01-01-MAKER-FILLS` and renamed after the run to the ids below only because `research_result.py` requires a hex id segment; the rule text, sample and thresholds are byte-for-byte unchanged (`git diff 1ab13e21 -- research/queue/`). § 1–3 of this doc restate them and were written while the run was in progress, before its
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

## 4. Result — PASS at the threshold (MEASURED, registered run)

Record: `comms/research/desk_maker_fills/maker_fills_record-2026-10-27.json`; result row
`research/results/RQ-20261027-a3f1-01/local-2026-10-27.jsonl`. Run on the lane container after the registration commit was pushed;
all 240 symbol-day cells measured, 0 failed, 0 RPI prints present in the sample (the column exists; every value was 0).

**Population for every number below:** 6 symbols × 40 days (2025-11-08..2026-10-25, every 9th day) × 22 hourly decision times × both
directions = **10,560 rows** per arm. CIs resample whole days (40 clusters).

### 4.1 Primary arm (k = 0, W = 5 min, STRICT fill, policy F) — graded

| | value |
|---|---|
| pooled mean `delta_F` | **+2.03 bps per entry**, 95% CI **[+1.69, +2.33]** |
| fill rate (strict) | 88.7 %; median wait 3.5 s |
| `delta_F` when filled / unfilled | +4.59 / −18.04 bps (check: 0.887 × 4.59 + 0.113 × −18.04 = +2.03) |
| symbols with mean > 0 | 6 of 6 |
| verdict | **PASS** (rows 10,560 ≥ 1,000; days 40 ≥ 30; +2.03 ≥ +2.0; CI lo > 0; 6 ≥ 4) |

| symbol | median tick (bps) | fill rate | mean `delta_F` (bps) | 95% CI |
|---|---|---|---|---|
| ADAUSDT | 4.00 | 0.80 | +1.93 | [+1.30, +2.52] |
| AVAXUSDT | 1.07 | 0.88 | +1.52 | [+0.99, +1.98] |
| BTCUSDT | 0.01 | 0.91 | +2.04 | [+1.79, +2.28] |
| ETHUSDT | 0.04 | 0.94 | +2.45 | [+2.18, +2.68] |
| SOLUSDT | 1.11 | 0.89 | +2.13 | [+1.70, +2.52] |
| XRPUSDT | 0.72 | 0.90 | +2.13 | [+1.69, +2.53] |

### 4.2 Secondary arms (reported, NOT graded; pooled, 10,560 rows each)

| arm | strict fill | strict mean (bps) [CI] | optimistic fill | optimistic mean (bps) |
|---|---|---|---|---|
| W 1, k 0 | 0.76 | +1.69 [1.45, 1.91] | 0.90 | +3.15 |
| W 5, k 0 (primary) | 0.89 | +2.03 [1.69, 2.33] | 0.95 | +3.33 |
| W 15, k 0 | 0.93 | +1.88 [1.26, 2.37] | 0.97 | +3.21 |
| W 1, k 1 | 0.67 | +1.50 [1.27, 1.72] | 0.76 | +2.45 |
| W 5, k 1 | 0.84 | +1.99 [1.63, 2.32] | 0.89 | +3.00 |
| W 15, k 1 | 0.90 | +1.91 [1.14, 2.46] | 0.93 | +2.92 |

- **Trend-aligned vs counter-trend entries** (sign of the 60-min return before T, 5,002 rows each at W 5 k 0): +2.02 vs +2.05 bps. A
  breakout-like entry pays no extra selection at this cadence, as measured.
- **Policy S (skip unfilled), net markouts:** filled maker entries −3.7 / −3.8 / −4.0 / −4.3 bps at 5 / 1 / 15 / 60 min after the
  fill vs taker entries −6.1 bps (both directions pooled, so the gross drift cancels). Gross of the 2.0-bps maker fee, a filled maker
  entry is −1.7 bps at 5 min, where no selection would give about +0.4 bps (half the median 0.75-bps tick): **the adverse selection on a
  fill is about 2 bps**, and it is already inside `delta_F`. Skipping the unfilled 11 % also drops the entries that ran away, which are
  the signal's best ones when it has edge. **Policy F is the one to build.**
- **Where the edge comes from:** on BTC/ETH the tick is ~0.01–0.04 bps, so the edge is almost entirely the fee difference (3.5 bps × fill
  rate) less the runaway; on ADA (4-bps tick) the spread credit is large but so is the runaway (fill 0.80).

### 4.3 How fragile the PASS is (post-hoc, NOT a re-grade)

The margin over X is **0.03 bps**. The verdict stands as registered; these are the things a probe must measure before anyone relies on it:

- **Maker fee (UNVERIFIED on our account).** Recomputed from the committed rows: maker fee 2.5 → +1.59; 3.0 → +1.15; 3.5 → +0.70 bps.
  Positive at every plausible fee, but below X at any fee above 2.0.
- **Latency.** 25.9 % of primary rows fill within 1 s of T. An order that takes a few hundred ms to rest can miss some of those, and
  each miss becomes a fallback paying the runaway. The replay cannot see this; probe (b) can.
- **The 1-tick spread assumption** goes the other way: it understates the taker's real cost on a wider book.

### 4.4 What it is worth in R

About **2 bps per entry** (policy F). Using the DESK-EDGE-PROGRAM scaling (row `COST-STACK-BYBIT-TAKER-FEE`: 1.8 bps ≈ 0.04 R at a
1-sd 30-min bracket, ≈ 0.003 R at 48 h holds), that is **≈ +0.045 R per trade at short brackets and ≈ +0.003 R at multi-day holds**.
A maker take-profit (not measured) could roughly double it at short brackets. **It does not close the desk's S3 gap** (a random
entry nets −0.112 R pooled; the bar is about +0.36 R absolute). It is a real, durable cost cut for every Bybit leg, not an edge.

## 5. Proposal (Tier 2/3, for the manager — NOT applied by this lane)

The rule's PASS branch says: propose probe (b) and the post-only entry change for the `claude_desk` leg. Neither is applied here.

### 5.1 Probe (b): `bybit_1` DEMO post-only probe — measure demo fidelity and the real maker fee first

- **What:** for each `claude_desk` entry on `bybit_1` (demo), send the entry as `orderType: Limit`, `timeInForce: PostOnly`, price =
  the near touch from `get_tickers` (`bid1Price` for Buy, `ask1Price` for Sell), with the same `stopLoss` / `takeProfit` attached; if
  it is not filled within 5 min, cancel and send today's Market order (policy F). A PostOnly reject (Bybit cancels instead of taking)
  goes straight to the Market order.
- **Measure, per order:** filled? fill time, fill price, `execFee` / `isMaker` (this verifies the maker fee), reject count, and for
  each demo fill whether the **mainnet** public prints (`public.bybit.com`, next day) traded at or through the limit before the demo fill
  time.
- **Decision rule to register before the probe runs (proposal):** after ≥ 100 post-only orders, demo is *representative* iff the demo
  strict-fill rate sits within ±10 pp of the replay's strict rate on the same orders' timestamps AND ≥ 90 % of demo fills have a
  mainnet print at or through the limit by the demo fill time. Otherwise demo matching is optimistic and its fill rate is not evidence.
  The realized maker fee replaces the published 2.0 in a re-run of `desk_maker_fills.py` (same sample, new constant, recorded as a new
  run, not a re-grade).

### 5.2 The order-path change (exact shape)

- `src/units/accounts/execute.py` `_submit_order`, Bybit branch, opening orders only (not `reduce_only`, not spot): when the leg's
  config says `entry_order: post_only_touch`, replace `orderType: "Market"` with `orderType: "Limit"`, `price: <near touch, quantized
  with quantize_price>`, `timeInForce: "PostOnly"`; keep `stopLoss` / `takeProfit` / Partial-mode fields unchanged (Bybit V5 accepts TP/SL
  on a Limit entry).
- A fallback owner in `src/runtime/order_monitor.py`: a resting post-only entry older than 5 min is cancelled and re-sent as the Market
  order; the journal row records `entry_order`, the limit, the fallback flag and the fill's `isMaker`.
- `config/strategies.yaml`: `entry_order: post_only_touch` on the `claude_desk` leg only (Tier 3: a strategy parameter, not an
  `*_ENABLED` flag; the default stays Market). No change to `config/accounts.yaml` or risk logic.
- Tests: kwargs shape for Buy/Sell; reject → Market fallback; 5-min cancel-and-replace; reduce-only and spot unchanged.

**Recommendation:** run 5.1 first, on the demo leg, as the Tier-2 step. 5.2 beyond `bybit_1` waits for 5.1's demo-fidelity and
maker-fee readings, because the PASS margin is smaller than either unknown.

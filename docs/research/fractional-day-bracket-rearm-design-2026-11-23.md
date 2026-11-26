# Daily bracket re-arm for fractional (day-only) Alpaca positions — design, 2026-11-23

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `INDEX-LEVERAGED-ETF-ROSTER-20261123`

**Gates this adds or changes: none.** A design only; nothing is built. It does not halt anything (Prime Directive rule 7): a failed re-arm raises ONE red flag and the trader keeps running. Everything it depends on that is unproven is labelled and is settled by the paper probe (`.github/workflows/broker-fractional-probe.yml`, phases `open` and `premarket`).

Context: Alpaca fractional orders accept `time_in_force = day` only ([fractional page](https://docs.alpaca.markets/us/docs/fractional-trading), [orders page](https://docs.alpaca.markets/us/docs/orders-at-alpaca), read this session). `AlpacaClient.place` currently sends GTC brackets with whole shares; the GTC choice (PI-20260926-HJPL5ABP-0001) exists because day legs were cancelled at the entry day's close.

## 0a. MEASURED constraint that changes this design (2026-11-23, paper, run 45251691248)

Alpaca rejects a fractional bracket and a fractional OCO ("fractional orders must have order_class=simple", HTTP 422), and a live fractional DAY stop holds all the shares, so a fractional DAY limit take-profit is rejected with HTTP 403 ("insufficient qty available", `held_for_orders` 0.5). A fractional DAY stop alone is accepted. **So the venue can hold a stop OR a take-profit for a fractional position, never both.** Consequences: (1) the re-arm job places the stop only (loss protection wins); (2) the take-profit becomes a software-managed exit (the trader watches the TP price and cancels the stop / sells), which departs from "protection and target live at the venue" and from the TP doctrine as written; (3) the merged-OCO design cannot include a fractional package in a combined bracket. Whether a fractional stop can be swapped for a TP intraday without a naked gap is unmeasured.

## 0. Is overnight really worse? (INFERENCE, to be confirmed by the probe)

Per the orders page, only limit orders are accepted as extended-hours eligible, so a stop (GTC or day) does not trigger outside the regular session. A GTC stop and a day stop re-armed **before the open** therefore give the same gap protection: neither fires overnight, both are live for the opening print. The real difference is **operational**: GTC needs nothing each day; a day stop needs a re-arm that must succeed before the open, otherwise the position opens the day unprotected. So the design cost is reliability, not market exposure, provided that:
1. Alpaca accepts a fractional DAY stop placed outside regular hours and queues it for the open — **MEASURED 2026-11-24 13:02Z (run 45399132227): accepted, `status: new`, visible in the open-orders read-back; whether it then triggers correctly at the open is not measured**, and
2. the re-arm lands before 09:30 ET with read-back verified.

If (1) fails, the stop can only be placed at or after 09:30 ET, and the unprotected window is the open itself, which is the most gap-prone moment: then fractional needs a different answer (see § 6).

## 1. Shape

A **re-arm job** inside the existing reconciler cadence (not a new register or service):

1. **Window.** From a configured pre-market time (default 08:00 ET) until 09:29 ET, every 60 s, on trading days only (Alpaca `/v2/calendar`, so holidays and half-days are read, never assumed).
2. **Target set.** Every open fractional position on an Alpaca account (journal `trades` open rows joined to venue `/v2/positions`), plus every journal package whose protective legs are missing or `expired`/`canceled` at the venue.
3. **Desired legs.** From the package's stored `sl` / `tp` (TP doctrine: the real predictive TP, moved with the trade if the doctrine moved it; the reconciler's current value, never recomputed from entry).
4. **Idempotent place.** One client order id per (package, trading date, leg): `rearm-<pkg>-<YYYYMMDD>-<sl|tp>`. If a live order with that id exists, do nothing; if the venue rejects a duplicate id, treat as success. Safe to run every minute.
5. **Read-back.** After placing, `GET /v2/orders?status=open` and require: both legs present, correct side, qty equals the position qty (fractional, exact string), price equals desired, `time_in_force` day. The leg is "verified" only when read back; the journal records `rearm_verified_at`.
6. **Retry with diagnosis.** On reject or timeout: classify (`not_fractionable`, `price_band`, `insufficient_qty`, `market_closed_queue_unsupported`, `http_5xx`, `auth`) and retry with backoff to 09:29 ET; the diagnosis string goes in the journal row and the alert.
7. **ONE red flag.** If at 09:29 ET any target position lacks a verified stop: ONE alert (existing `silent_refusal_alert` / alert channel; deduped by date + account) naming the positions and the last diagnosis. No halting, no mode flip; the tick loop keeps running (and keeps trying every minute after the open).
8. **Same-session placement at entry.** A fractional entry during the session gets its day stop/TP immediately (separately placed after the fill, or as a fractional bracket if the probe shows Alpaca accepts one); the re-arm job is for the **next** day onward.

## 2. Interplay

- **Reconciler.** The re-arm job reuses the reconciler's position-snapshot read; it must not race the orphan/naked sweep: the sweep sees `expired` day legs after the close and today would re-arm them with GTC; for fractional positions it must skip (they cannot be GTC) and leave the next-morning job to act. A fractional-aware skip in the sweep is part of the build.
- **Merged-OCO design (PI-20261123-PDEC1123-0002, due 2026-11-26).** That design makes ONE combined bracket per netted Alpaca symbol. The re-arm job must target the merged leg per symbol, not per package. A fractional symbol position that nets with a whole-share position cannot share a GTC leg; the design must say so (day-only wins for the fractional part, or fractional packages are refused when a GTC netted position exists). The design lane should absorb this section.
- **TP doctrine.** The re-armed TP is the package's current real TP, not a default; `tp_r: 50` / rest-at-cap is non-compliant. Active management (advice-only classes) is untouched.

## 3. Failure modes

| Mode | Handling |
|---|---|
| Holiday / half-day | `/v2/calendar` read; no window on a holiday; on a half-day the next session's open is read from the calendar, not assumed 09:30 |
| Partial fill of the entry | stop/TP qty = filled qty (read from the position), updated each pass |
| Gap through the stop at the open | a day stop becomes marketable at the open and fills at the open print (the same as a GTC stop); nothing the re-arm can change; journal `exit_reason` as the existing stop path does |
| API outage at re-arm time | retries to 09:29, then the ONE flag; the job continues after the open (placing a stop at 09:30+ is still better than none) |
| Rejected as "not fractionable" or wrong tif | classify, flag once, and fall back to a whole-share round-down for the stop only if the venue allows a whole-share stop on a fractional position (UNVERIFIED; probe not designed for this) |
| Clock skew / duplicate run | idempotent client order ids make a double run a no-op |
| Stop placed pre-market is rejected | then the first safe placement is 09:30 ET, and the design reverts to: re-arm at the open, flag every day, and prefer whole shares (§ 6) |

## 4. What the probe must show before building

(a) fractional DAY market bracket accepted? (b) fallback separate day stop + limit and whether a fractional OCO is accepted; (c) fractional DAY stop accepted while the market is closed and visible as queued for the open. Also read the venue's order status string for (c) to know what "queued" looks like for the read-back.

## 5. Tier

Order-path / executor / reconciler change: Tier 2 to build, Tier 3 to put a fractional leg on real money. Nothing here is done.

## 6. If the probe fails (INFERENCE)

If (c) fails, fractional positions are unprotected at the venue from the open until the first re-arm. The alternatives are: (i) whole shares with more cash; (ii) a software-side stop (the trader watches and sells at market) which breaks the "protection lives at the venue" property the reconciler is built on; (iii) IBKR if its API can place fractional orders (unverified; see the fractional note).

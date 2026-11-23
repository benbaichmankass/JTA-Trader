# Fractional shares: Alpaca vs IBKR — research note, 2026-11-23

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `INDEX-LEVERAGED-ETF-ROSTER-20261123`

**Gates this adds or changes: none.** Research only; no code or config changed. Source = quoted from a page read this session; inference = my reasoning, labelled.

## 1. Alpaca

| Question | Answer | Source / inference |
|---|---|---|
| Order types with fractional qty or notional | market, limit, stop, stop-limit, **time_in_force = day only** ("Alpaca currently supports fractional trading for market, limit, stop & stop limit orders by setting `time_in_force` to `day`"); GTC, IOC, FOK, OPG, CLS = "No" for fractional in the orders-page fractional table | SOURCE: docs.alpaca.markets/us/docs/fractional-trading and /orders-at-alpaca (read this session) |
| qty vs notional | either; qty up to 9 decimals, notional up to 2 decimals USD; notional orders cannot be replaced | SOURCE, same pages |
| Extended hours | limit orders only (`day`); the same page also says fractional "can only be bought or sold with market orders during normal market hours" — the page contradicts itself; `extended_hours` with `qty` is not stated | SOURCE (contradictory); treat as UNVERIFIED |
| Bracket / OCO / OTO with fractional | **NOT STATED anywhere read.** Bracket/OCO/OTO require `time_in_force` day or gtc, and fractional GTC is "No" | SOURCE for each half; the combination is INFERENCE: a fractional bracket is at best day-only |
| Short selling with fractional | not supported ("All fractional sell orders are marked long") | SOURCE |
| Minimum notional | not stated on the pages read (only marketing: "as little as $1") | NOT STATED |
| `fractionable` per asset | "Not all assets are fractionable yet"; rejection reads "requested asset is not fractionable" | SOURCE |
| Settlement | not read this session; our cash account runs a T+1 gate (`ALPACA_CASH_SETTLEMENT_MODE`, `accounts.yaml` comment) | repo, not venue docs |

**MEASURED `fractionable` for SQQQ, SPXU, SPXS, SDOW, TZA, SH, PSQ, TQQQ, UPRO, SPXL, SSO, UDOW, TNA, QLD: UNVERIFIED.** No diag route reaches the Alpaca assets API (`alpaca/asset?...` answered 404; the Alpaca keys live on the VM). The exact read that settles it: `GET https://api.alpaca.markets/v2/assets/<SYMBOL>` per symbol (read-only; `AlpacaClient.asset_short_status` in `src/units/accounts/alpaca_client.py` already returns `{tradable, shortable, easy_to_borrow, fractionable}`), run from a workflow with the live key as a one-off read-only step. Not run here: it needs a new workflow step, and the manager said no new secrets.

## 2. IBKR

**All IBKR statements below are UNVERIFIED.** Both IBKR pages I tried to read (fractional-share-trading FAQ and the Campus fractional lesson) returned HTTP 403 to the fetcher. Search-result snippets (not page reads) said: fractional trading is supported "via FIX/CTCI but not via API at this time"; fractional offered on eligible US ETFs "where available"; limit-type orders listed, with a conflicting list elsewhere; an unmarketable fractional limit may not execute. If the snippet is right, IBKR's TWS API / IB Gateway **cannot place fractional shares at all**, which would end the IBKR route for our executor. It must be confirmed in the ib_paper account before any build: place one fractional order (e.g. 0.5 share SH) via `IBClient` on `ib_paper` and read the rejection or fill. That read is cheap and decisive.

Our state (repo): `ib_live` is `mode: dry_run`, empty roster, with the open finding BL-20260908-IB-LIVE-ENDPOINT-IS-STALE-AND-PROMOTION-WOULD-NOT-CONNECT (`ib_host/ib_port` point at 127.0.0.1:7496, not the isolated gateway VM); `ib_paper` is live. Moving the ETF book to IBKR live would need, at minimum (INFERENCE from the repo, not venue docs): the endpoint fix, funding, a decision on cash vs margin and PDT/settlement, an ETF-capable executor path (`IBClient.place` builds a native parent + TP limit + stop bracket with `parentId`), and an `ib_instruments` entry per ETF.

## 2b. What is actually deployed for IBKR (operator asked, 2026-11-23 ~18:55Z; MEASURED from the repo, not from the VM)

- The gateway VM runs the **gnzsnz/ib-gateway Docker image** (`deploy/ib-gateway.compose.yml`: IBC + Xvfb, headless), publishing only the **TWS socket API** (host loopback 4002 -> container 4004 for paper; live would be 4001 -> 4003). Nothing in `deploy/`, `src/`, `scripts/` or `docs/reference/` references the Client Portal Web API (`/iserver`, ibeam, CPAPI). The trader reaches it through `src/units/accounts/ib_client.py` (ib_insync, TWS socket) at `ib_host 10.0.0.251`, `ib_port 4002` for `ib_paper`.
- So **the code and the deploy both say "socket API, no web server."** If the operator has a web interface in mind, it is not in this repo: candidates are the IB Gateway/TWS login UI (VNC/Xvfb, not an order path), IBKR's web Client Portal for manual trading (a browser, not our code), or the Client Portal Web API, which is not deployed. I cannot read the live gateway VM from here (a one-off `vm-ops` read of `docker ps` and listening ports would settle it); that read was not run.
- **Does IBKR's Web API do fractional?** From search results (not page reads): IBKR's FAQ says fractional trading is "supported via FIX/CTCI but not via API at this time"; an Order Types page says the IB APIs "do not support fractional or cash quantity trading with exception to Cryptocurrencies and Forex"; an IBKR staff reply says Cash Quantity orders are unsupported for non-crypto via the API; the Client Portal API docs on GitHub were reported updated to remove fractional-share references. A Place Order page documents `cashQty`, so the picture is not fully consistent. Net (INFERENCE, UNVERIFIED because the IBKR pages returned 403 to the fetcher): fractional ETF orders are not available through either the TWS socket API or the Web API; the paper probe's IB step (`ib_fractional_probe.py`) is the decisive test for the socket path.

## 3. Our code

- **Alpaca executor today:** `AlpacaClient.place` sends a **market bracket with `time_in_force: gtc`** and floors qty to whole shares (`max(1, int(round(qty)))`). The GTC choice was made deliberately (PI-20260926-HJPL5ABP-0001): with `day`, Alpaca cancels the stop and target at the close of the entry day and multi-session holds went broker-naked overnight.
- **Consequence (INFERENCE from the two sources above):** a fractional order cannot be GTC, so a fractional entry has either a day-only bracket (if the venue even accepts a fractional bracket, which is not documented) or day-only separate stops. Either way the protective stop expires every close, which re-creates the 2026-09-24 failure. The smallest viable executor change would be: fractional entry (market, `day`) plus a **re-placed `day` stop (and TP) every session open** by the reconciler, accepting an overnight gap where the position is unprotected at the venue unless the stop is re-armed in the pre-market (no extended-hours stop for fractional is documented). That is a real protection regression, not a small change.
- **Intersection with PI-20261123-PDEC1123-0002** (read from `docs/claude/work/pipeline/20261123T085404893047Z-b6b973e3.json`): the operator chose "Design merged OCO": ONE combined bracket per netted Alpaca symbol, because Alpaca nets per symbol and a second package's TP is released to re-arm the first. Design due at Thursday planning (2026-11-26); nothing built. A fractional redesign of the bracket should be folded into that design rather than done separately: a merged bracket has the same day-only restriction if any package in it is fractional (INFERENCE).
- **IBKR executor:** `IBClient.place` builds integer-quantity brackets; I did not trace its qty type. Fractional there is gated by the API question in § 2, not by our code.

## 4. Recommendation (lean)

| Option | Unlocks | Build | Tier | Risk |
|---|---|---|---|---|
| **A. Whole shares + more cash** (operator is already looking at this) | every candidate whose share price fits the cash gate (~1.1 x price free cash; ~$279 covers UPRO/SPXL/SSO/TZA as measured) | none | none | none new; position sizes are 1 share, so 1 share may be most of the account |
| **B. Alpaca fractional** | all candidates that are `fractionable` (UNVERIFIED), any balance | executor + reconciler: fractional entry, day-only stop/TP re-armed each session; tests; the PI-…-0002 interaction | Tier 2 (order path) + Tier 3 (live account use) | HIGH: protective stops lose GTC (documented fractional restriction); bracket-with-fractional undocumented |
| **C. IBKR fractional** | unknown | connectivity fix, funding, executor change; and fractional-via-API may not exist | Tier 2/3 | UNKNOWN: pages not read; snippet says API unsupported |

**Recommended order (my judgement):** (1) do A now; (2) run the two decisive reads at no build cost: the Alpaca `fractionable` read for the 14 symbols and one fractional order on `ib_paper`; (3) build B only if (a) the symbols are fractionable and (b) a one-order test on `alpaca_paper` shows a fractional bracket with `day` is accepted and its legs behave; even then the day-only stop is a regression the operator should explicitly accept. C only if the IBKR API accepts fractional orders.

## 4b. Probe status (operator approval 2026-11-23 ~18:55Z)

`.github/workflows/broker-fractional-probe.yml` + `scripts/ops/broker_fractional_probe.py` + `scripts/ops/ib_fractional_probe.py` are written (PAPER ONLY, tiny size, always flattened, log is the only record) and held in the PR. A `workflow_dispatch` workflow cannot be dispatched until it is on `main`. After merge: dispatch `target=alpaca phase=assets` (reads `fractionable` for the 14 candidates), `phase=open` during US market hours, `phase=premarket` while closed, and `target=ib`. **None has run.** The design that depends on the results: `docs/research/fractional-day-bracket-rearm-design-2026-11-23.md`.

## 5. Not done
No test order was placed; no venue was queried; IBKR facts unread; Alpaca settlement not read; the merged-OCO design itself does not exist yet.

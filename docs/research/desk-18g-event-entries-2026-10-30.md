# DESK-18G — do entries triggered by a funding or open-interest shock beat a random entry?

> **Doc status:** `live` · category `research` · last verified `2026-10-30` · lane DESK-18G-EVENT-ENTRIES (Tier 1, research tooling only)

Operator 2026-10-30 ~21:40Z, popup answer verbatim "Event-driven entries". Unit `research/queue/blocked/RQ-20261030-e18g-01.yaml`
(rule `RULE-RQ20261030-E18G-01-DESK-EVENT-ENTRIES`) was committed and pushed (`e89911492`, 21:53Z) **before the first score**. Harness
`scripts/research/desk_event_entry_replay.py`; evidence `comms/research/RQ-20261030-e18g-01/local-2026-10-30/event_entry_result_dev.json`.

**Gates this adds or changes: none.** No config, roster, order or mode touched; no model spend (a mechanical rule arm, no LLM judge).

## Verdict: S3_NOT_CLEARED. E4 has a real but small edge (S3 +0.157 R, CI lower bound above 0); it is 0.09 R short of the bar. E3 loses.

Population: events inside the DEV window 2025-11-01..2026-09-15, six crypto USDT perps, Binance 1h candles, market entry at the next bar open after the
decision cutoff, bracket SL 1.5 / TP 3.0 ATR14, 24-bar time stop, full cost stack (driver `simulate`, unchanged). S3 per event = event net R minus the
mean of 200 random same-symbol, same-ATR%-decile cutoffs more than 24 bars from any event, with the event's own side. Weekly-cluster bootstrap,
10,000 draws, decisive CI 97.5% (two arms). Bar: S3 ≥ +0.25 R and CI lower bound > 0, n ≥ 30.

| arm | n (long/short) | mean net R | random null | **S3** | 97.5% CI | vs same-time side-averaged (95% CI) | MDE (iid / cluster) | clears |
|---|---|---|---|---|---|---|---|---|
| E3 funding-shock fade | 283 (248/35) | −0.356 | −0.137 | **−0.219** | [−0.379, −0.045] | −0.248 [−0.413, −0.078] | 0.20 / 0.21 | no |
| E4 OI-shock continuation | 763 (402/361) | −0.006 | −0.163 | **+0.157** | [+0.044, +0.276] | +0.076 [−0.007, +0.165] | 0.14 / 0.14 | no |

**Controls (RULE ONE) all held:** oracle side S3 +0.786 [+0.648, +0.919] (clears); anti-oracle −0.648; random side +0.079 [−0.018, +0.180] (does not clear); event
detectors return identical events on history truncated at 2026-04-01 (both classes). The instrument can see a positive.

## What this means

1. **E4's edge is real in sign, not in size.** It is the first arm in the DESK-18 family whose CI lower bound is above 0 (the desk's was −0.19). Its mean net
   R is about zero in absolute terms; it looks good because the random null is −0.16 in this bracket. The shortfall to the bar is 0.093 R, inside the CI.
2. **Part of it is event timing, not direction.** The same-time side-averaged baseline gives +0.076 [−0.007, +0.165] for the direction rule, and a random
   side read +0.079 (not significant). So roughly half the S3 is "a volatility shock is a better time to hold this bracket than a random hour"
   and the continuation direction adds an unproven remainder. Consistent with the 5-minute study (excess +9..+18 bps, below cost).
3. **E3 funding fade is a loser** (S3 −0.22, CI wholly negative; every symbol negative). 248 of 283 are longs (negative funding): fading crowding into a falling market.
4. **By symbol (E4, n 112–144 each, noise-level):** ADA +0.05, AVAX −0.02, BTC +0.11, ETH +0.27, SOL +0.17, XRP +0.38. Looked at after the score; not a finding.
5. **The goal (DESK-13) is not met.** Nothing here lets the desk trade the prop accounts. A DEV clear would only have opened one held-out run.

## Data inventory (point-in-time availability, MEASURED 2026-10-30)

| catalyst | history | point-in-time? | status |
|---|---|---|---|
| Funding settlements | Binance Vision monthly, 2020-09.. | yes (`fundingTime`) | scored (E3) |
| Open interest | Binance Vision daily metrics, 5-minute, from 2021-12 | yes with +5 min lag | scored (E4) |
| Exchange listings / delistings | 2017-07..2026-10 (`comms/research/desk_event_calendar/ann_*.json`) | yes | `no_edge` on the six majors (prior study); not re-run |
| Macro calendar (CPI/NFP/FOMC/PPI/PCE) | `comms/macro/econ_calendar_snapshots*.jsonl`, scheduled dates back to 1951 | schedule is public in advance, but only ~8 of 58 window rows were first observed before their date (the rest are backfill) | **not scored**: about 40 distinct dates in the window, MDE about 0.66 R against a 0.25 bar; direction would have to be the post-release reaction, which the 1h price packet already sees |
| News (GDELT hourly panel) | `comms/news_alpha/gdelt_panel`, 2023-10 onward, ingest-time stamped | yes by ingest time | **available, no trigger registered**; adding one after seeing these results would be a forking path |
| Token unlocks / upgrades | forward-only / hand-curated | no | not backfillable (prior study) |

## Stated limits (RULE ONE)

* Binance candles stand in for Bybit; no latency, queue or funding-at-entry modelling beyond the driver's cost stack.
* Entry is at least one 1h bar after the event is known (the engine decides at a bar close), so a fast-decaying edge is under-measured; the 5-minute study found the gross edge largest at 4h–24h.
* One bracket only (SL 1.5 / TP 3.0 ATR, 24 bars). A bracket or horizon sweep is a new registration; E4 at S3 +0.157 is the case for one.
* E3 was underpowered for +0.25 R by registration (MDE at the bar); its verdict is a clean negative, not a power failure.
* The random null is vol-matched by ATR% decile only, not by hour of day.
* Per-symbol events share market shocks; the weekly cluster handles it, and symbol-level numbers are not independent.

## Best next step

E4 is the only information-bearing lever so far, but its measured size (+0.157 R, 0.09 R under the bar) does not clear DESK-13. Two cheap, separate registrations
would test whether it can: (a) E4 with a 5-minute entry (the engine is 1h) and a 4h–24h horizon sweep, bar unchanged; (b) E4 combined with the
desk's own judgement as a filter, which needs fresh judged data. Neither is run here.

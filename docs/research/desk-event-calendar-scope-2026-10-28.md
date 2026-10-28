# DESK-EVENT-CALENDAR — can a point-in-time crypto event calendar be built cheaply and honestly, and does a free sample show an event-entry edge?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-EVENT-CALENDAR-SCOPE` (Tier 1, research only), dispatched by Manager Session 2026-10-27a. Checklist row `DESK-EVENT-CALENDAR` (roadmap `L-DESK`). Follows `docs/research/desk-edge-program-2026-10-27.md` § "structural levers" (event-driven entries). Nothing here builds a store, touches config, an order path or `src/`.

## 1. Pre-registration — committed BEFORE any forward return was computed

**Question.** For the six desk perps (ADA, AVAX, BTC, ETH, SOL, XRP), do entries triggered by a point-in-time-known event earn forward return, net of the measured Bybit taker round trip of **12.3 bps** (row `COST-STACK-BYBIT-TAKER-FEE`; `desk-edge-program` § 6), that also exceeds a volatility-matched random entry?

**Data.** Binance Vision USD-M perp 5-minute klines (the program's venue proxy for the Bybit perp), per-symbol first available month to 2026-09. Event sources and their announce-time fields are in § 2 (surveyed before this section was written; fetched, not assumed).

**Entry / exit.** Entry = open of the first 5-minute bar opening at or after `event_known_at + 5 min` (a 5-minute decision latency, the program's delay-5). Exit = open of the bar `h` after entry, `h` in {1h, 4h, 24h}. `gross_bps = dir * (exit/entry - 1) * 1e4`; `net_bps = gross_bps - 12.3`.

**Event classes — ONE rule each, fixed now (5 classes x 3 horizons = family of 15).**

| id | event (`known_at`) | symbols | direction | window |
|---|---|---|---|---|
| C1 | Binance new-listing announcement (catalog 48; `known_at` = article `releaseDate`) | all six | long | 2020-10-01..2026-09-30 |
| C2 | Binance delisting notice (catalog 161; `releaseDate`) | all six | short | 2022-02-17..2026-09-30 |
| C3 | Funding shock: a Binance USD-M funding settlement whose rate has z >= 2 in absolute value against the symbol's previous 90 settlements (`known_at` = `fundingTime`) | the symbol | against the funding sign (crowding fade) | per-symbol start..2026-09-30 |
| C4 | Open-interest shock: 1h change in `sumOpenInterest` with z >= 3 against the previous 7 days of 1h changes; at most one event per symbol per 6h; `known_at` = metrics row time + 5 min (rows describe the following window: `desk-edge-program` § 4.7) | the symbol | with the sign of the same hour's price return (continuation) | 2024-01-01..2026-09-30 |
| C5 | XRP escrow release: 00:00 UTC on the 1st of each month (Ripple's escrow, announced 2017-12; known in advance of every sample event) | XRP | short | 2020-10-01..2026-09-30 |

Protocol upgrades and token unlocks are **surveyed only** (§ 2); the study does not run them (no point-in-time store exists for them; reasons in § 2).

**Baseline (volatility-matched random entry; PR #20764's `S3_matched` is an unmerged draft, so this lane carries its own).** For each event x symbol x horizon, the baseline is the mean `dir * return_h` of all random 5-minute entry bars of the same symbol with (a) trailing-24h realized volatility (std of 5-minute log returns over the previous 288 bars) in the same decile (deciles over the symbol's whole sample: this uses the full-sample volatility distribution for matching only, never for choosing events), (b) the same UTC hour of day, (c) not within 24h of any event of the class. `excess_bps = gross_bps(event) - baseline_bps`. Both arms pay the same 12.3 bps, so the excess is cost-neutral and `net` is reported separately.

**Statistics.** Per class x horizon: n events (distinct `known_at` timestamps), n event-symbol rows, mean `net_bps`, mean `excess_bps`; 95% and Bonferroni-corrected (alpha 0.05/15) CIs by a day-cluster bootstrap (10,000 resamples; rows on the same UTC day are one cluster).

**Verdict per class x horizon (registered).**
- `candidate` = day-clusters >= 100 AND mean `net_bps` corrected CI lower bound > 0 AND mean `excess_bps` corrected CI lower bound > 0 AND both time halves (split at the sample's median event time) have mean `net_bps` > 0.
- `no_edge` = day-clusters >= 100 AND the corrected upper bound of `gross_bps` excess is < 12.3 bps (it cannot pay the cost).
- `insufficient_n` = day-clusters < 100; reported with time-to-n = (100 - clusters) / clusters-per-year.
- `inconclusive` otherwise.

**Controls (RULE ONE: the probe must find a positive).** (a) *Planted event:* 200 synthetic events placed at random bars with 30 bps added to the forward 4h return must read `candidate` at 4h; (b) *null:* 200 random events (no planting) must not read `candidate`. A failed control invalidates the run.

**What it cannot say.** Binance perps stand in for Bybit; 5-minute entry latency; listings/delistings concern OTHER tokens, so on the six majors they can only act as market-wide news (the listed token's own pump is outside the desk universe, a universe lever not tested here); a `no_edge` at one fixed direction is not a proof for the opposite direction or other horizons.

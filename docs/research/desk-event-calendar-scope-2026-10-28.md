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

## 2. Source survey (every row fetched from this environment on 2026-10-28; nothing assumed)

| class | free source | fetch from here | fields | history | known BEFORE the event? (point-in-time) | verdict |
|---|---|---|---|---|---|---|
| Listings | Binance CMS `.../cms/article/list/query?type=1&catalogId=48` | **yes** (200, keyless; 47 pages of 50) | `id, title, releaseDate` (ms) | 2,289 notices, 2017-07-21..2026-10-26 | **Yes.** `releaseDate` is the publish time. Checked on the latest "Will List" notice: published 2026-10-13 03:30 UTC, trading opens 08:00 UTC the same day (article body). Residual risk: the list shows the CURRENT stamp; a re-published article would be re-stamped, and 391 of 2,288 neighbouring pairs are out of order against `id` (old id schemes), so a spot-check, not a proof | PIT-safe, cheap (about 2 requests per page) |
| Delistings | same, `catalogId=161` | yes | same | 446 notices, 2022-02-17..2026-10-27 | Yes (same caveat); the notice gives the removal date days ahead | PIT-safe |
| Funding | Binance Vision `data/futures/um/monthly/fundingRate` | yes | `calc_time, interval, rate` | per-symbol start (2020-09..) | The settled rate is known at `calc_time`; the earlier predicted rate is not in the archive | PIT-safe as a derived signal; NOT a calendar |
| OI / positioning | Binance Vision `daily/metrics` (5-minute) | yes (6,030 files for 2024-01..2026-09) | `sum_open_interest`, value, long/short ratios | from 2021-12 per the program doc | Rows describe the window AFTER their stamp (`desk-edge-program` § 4.7); this lane adds 5 minutes | PIT-safe with the lag; NOT a calendar |
| Bybit-native funding/OI/announcements | `api.bybit.com/v5/...` | **no: 403 from the agent proxy** | — | — | — | needs a VM/runner-side fetch (`ict-bot-arm` is the Bybit venue) |
| Token unlocks | Tokenomist (`tokenomist.ai/<token>`) | page yes (200, 540 kB HTML) | next unlock, amount, "±1 day window" | **forward-looking only; event charts and claim history are Pro-gated** (page text: "Premium Feature … Upgrade to access detailed unlock event charts") | A schedule fetched today is NOT evidence of what was known then; vesting schedules are revised. Unlock history cannot be backfilled honestly | **Not PIT-backfillable.** Forward capture only |
| Unlocks (aggregators) | DefiLlama emissions | `pro-api.llama.fi/emissions` 500, `api.llama.fi/emissions` 402 | — | — | — | paid |
| XRP escrow | deterministic, announced 2017-12 | n/a (a rule) | 00:00 UTC on the 1st | 2017.. | **Yes** (schedule predates the whole sample) | The one PIT-safe unlock class; covered by C5 |
| Protocol upgrades | GitHub releases / EIP pages | `api.github.com` repos **denied by this session's repo scope**; `raw.githubusercontent.com` EIP text 200; Wayback timed out | release tag/date; fork dates in EIPs | per chain, years | Fork dates are announced weeks ahead, but the ANNOUNCEMENT date must come from a blog/forum post, which has no common free API | **Needs a runner-side fetch and hand curation**; n is tiny (a handful of dated forks per chain per year) |

Not verified here (stated, not assumed): per-asset unlock schedules for ADA, AVAX, BTC, ETH and SOL (Tokenomist's per-token pages were not parsed; only the structure was inspected), Bybit's own listing notices, and any announcement-time revision history.

## 3. Amendments after registration (stated before the verdicts were read)

1. **Controls.** The registered planted control (200 events, +30 bps net at 4h) read `inconclusive`, not `candidate`: the corrected 4h CI of 200 random events is [-50, +171] bps (real 2021 crash bars: 2021-05-19 and 2021-04-18 moves of 12-33% in 5 minutes are in the data, MEASURED). So the registered control was **under-powered**, not the classes. A +100 bps planting was added and reads `candidate` [+62, +278]; the null reads `inconclusive`. **Instrument valid for effects of about 100 bps at n = 200; the classes with ~1,000 clusters resolve about 25-35 bps (C1 4h corrected half-width).** No class rule was changed.
2. **C4 first run.** The first OI run produced 378 events because a zero-OI row overflowed the rolling z (a code bug, caught by the event count against the 2,319 of the re-run). Fixed; the rule is as registered.

## 4. Results (MEASURED; `comms/research/desk_event_calendar/study.json`, `scripts/research/desk_event_calendar_study.py`)

Population: Binance USD-M perp 5-minute bars, six symbols, cost 12.3 bps round trip, 5-minute entry latency, family 15. `n` = events / UTC-day clusters. `net` = gross - 12.3; `excess` = gross minus the vol-and-hour-matched random entry (cost-neutral).

| class | h | n ev / clusters | gross bps | net bps [95% CI] | excess bps [95% CI] | excess corrected CI (0.05/15) | verdict |
|---|---|---|---|---|---|---|---|
| C1 | 1h | 1749 / 1029 | -2.9 | -15.2 [-19, -12] | -4.2 [-8, -1] | [-10, +1] | no_edge |
| C1 | 4h | 1749 / 1029 | -2.5 | -14.8 [-23, -7] | -10.5 [-19, -2] | [-23, +1] | no_edge |
| C1 | 24h | 1747 / 1028 | -7.6 | -19.9 [-45, +6] | -37.5 [-64, -12] | [-76, -0] | no_edge |
| C2 | 1h | 438 / 368 | -1.1 | -13.4 [-21, -4] | -0.1 [-8, +9] | [-12, +15] | inconclusive |
| C2 | 4h | 438 / 368 | -2.3 | -14.6 [-32, +2] | +1.2 [-15, +18] | [-24, +27] | inconclusive |
| C2 | 24h | 438 / 368 | -41.1 | -53.4 [-95, -13] | -23.9 [-65, +16] | [-84, +36] | inconclusive |
| C3 | 1h | 1610 / 965 | +9.8 | -2.5 [-11, +8] | +9.6 [+1, +20] | [-3, +25] | inconclusive |
| C3 | 4h | 1610 / 965 | +7.8 | -4.5 [-19, +11] | +7.3 [-7, +23] | [-14, +31] | inconclusive |
| C3 | 24h | 1610 / 965 | -3.3 | -15.6 [-58, +28] | -9.1 [-51, +34] | [-75, +56] | inconclusive |
| C4 | 1h | 2273 / 837 | +9.4 | -2.9 [-10, +6] | +9.3 [+2, +18] | [-1, +22] | inconclusive |
| C4 | 4h | 2273 / 837 | +13.7 | +1.4 [-9, +13] | +13.6 [+3, +25] | [-2, +32] | inconclusive |
| C4 | 24h | 2269 / 836 | +17.0 | +4.7 [-19, +29] | +16.8 [-7, +40] | [-18, +51] | inconclusive |
| C5 | 1h | 71 / 71 | +14.7 | +2.4 [-20, +27] | +12.0 [-11, +37] | [-21, +49] | insufficient_n |
| C5 | 4h | 71 / 71 | -0.3 | -12.6 [-72, +36] | -1.6 [-60, +46] | [-98, +67] | insufficient_n |
| C5 | 24h | 71 / 71 | +20.3 | +8.0 [-111, +129] | +45.6 [-73, +169] | [-131, +232] | insufficient_n |

- **C1 (listing, long) is `no_edge` at all three horizons** (excess -4 / -10 / -37 bps against a cost of 12.3). **C2 (delisting, short)** nets -13 / -15 / -53 bps; excess spans 0. As expected, an announcement about ANOTHER token carries no news for the six majors.
- **No class is a `candidate`.** No corrected net CI lower bound is above 0 anywhere.
- **C3 funding fade** has excess +9.6 bps at 1h whose uncorrected 95% CI excludes 0 ([+0.9, +19.6]) but not after the family correction, and its net is negative (-2.5) after 12.3 bps; the time halves disagree.
- **C4 OI-shock continuation** is the only class with a consistently positive excess: +9.3 / +13.6 / +16.8 bps; the 1h and 4h uncorrected CIs exclude 0 ([+1.8, +17.9], [+2.7, +24.6]) and the corrected ones do not ([-1.0, +21.9], [-2.2, +31.8]). Net of the taker cost it is -2.9 / **+1.4** / +4.7 bps with CIs of +-10 to +-25. A gross edge of about 14 bps against 12.3 bps of cost is not a trade; a maker entry (PR #20760's measured +2.0 bps on entry, not yet merged and with an unchecked 2.0 bps fee) would move it to about +3 bps net. It is a hypothesis for a forward holdout, not a finding (filed below).
- **C5 XRP escrow short is `insufficient_n`** (71 months): 24h excess +45.6 bps with a 95% CI of [-73, +169]. **Time-to-n: 2.42 years to reach 100 clusters** (12 events a year), and even then the 24h CI half-width (about 120 bps at n = 71) shrinks only by about 15%.
- **What bounds n (macro-research invariant 4).** The listing/delisting and funding/OI sources take an arbitrary date range, so n is bounded by the market's event rate and not by forward accrual: the classes with enough n are already measured; the two that lack it (C5 and upgrades) are bounded by their event rate (12 and a few per year), not by the source.

## 5. Recommendation: SKIP the calendar store

1. **The only point-in-time-safe, fetchable, deep-history class is exchange listings/delistings, and it is about other tokens.** On the six desk perps it is `no_edge` (C1) or null (C2). A store for it would cost almost nothing (one keyless endpoint, 2,735 rows) and would hold no desk edge. If it is wanted for a universe lever it is already fetched (`comms/research/desk_event_calendar/ann_*.json`).
2. **Funding and OI shocks are derived signals, not calendar events.** They need no store; the edge program's P+ tier already contains funding (S3 +0.025/+0.042), and the OI-continuation excess here is below the cost.
3. **Unlocks cannot be backfilled honestly** (forward-only free data, Pro-gated history, revised schedules). A forward capture would take years to reach n and the six majors have few cliff unlocks (not verified per asset). XRP escrow is the one clean PIT class and it is `insufficient_n`.
4. **Upgrades** need runner-side fetch plus hand curation and have a tiny n.
5. **Cost and risk of building anyway:** a forward-only store for unlocks and upgrades is about a runner-day to build and 2+ years to reach n = 100; the data risks are re-stamped announcements (listing), revised vesting (unlocks), and Binance-as-Bybit proxy. None of these is worth it against measured effects of 0 to +14 bps gross.

## 6. Follow-ups filed (checklist rows, not memos)

- `DESK-EVENT-OI-FORWARD-CHECK` (queued): re-run this script on data after 2026-09-30 for C4, the one class worth a forward holdout; kill if the 4h corrected net lower bound is not above 0.
- `DESK-EVENT-LISTED-TOKEN-SCOPE` (queued, manager's call): the listed token itself is outside the desk universe; a universe lever with real cost risk on illiquid new listings.

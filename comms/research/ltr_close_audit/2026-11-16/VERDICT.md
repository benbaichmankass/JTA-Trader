# LTR-CLOSE-AUDIT 2026-11-16 — did the live review's applied closes beat holding?

Lane LTR-CLOSE-AUDIT-20261116 (Tier 1). Data: `audit.json` (this directory), produced by `scripts/research/ltr_close_audit.py --live`.
Provenance: close R = MEASURED (journal fills, initial-stop R basis); hold R = COMPUTED when it resolved (stop / TP / 24 h max-hold
time exit), ESTIMATED when still open (marked to market at the last 1h candle close, not a realised exit).

## Population
Journal trades with `exit_reason = live_review_close` closed 2026-11-05 → 2026-11-16 08:18Z, joined to the nearest `close` review of the
same package within ±900 s: **13 packages** (11 priced here; 2 `candles_start_after_review`: the 11-05 15m XRP closes, older than the
candle API's last-1000-bar window). One more applied close (trade 6789, ADA, 11-05) has **no review row at all**. Rows: 18 priced
trade-rows = real_money (bybit_2) 8, mirror_paper (bybit_portfolio) 8, paper (bybit_1) 2. Prop (tradeify_1 / velotrade_1) fills are
NOT in the journal trades table: the two prop close recommendations in the window (trend_donchian_eth_4h 11-15 16:01Z, ml_entry ETH
11-16 04:29Z) have no realised R and are `could_not_look`, not 0. No review row exists for a "SOL 11-15 15:08Z prop" close: not found
in main's `reviews.jsonl` or the rows branch (39 rows exist only on the rows branch; none is a close at that time).

## Result (delta = close − hold, net R; positive = the close helped)
| class | n rows | close R | hold R | delta | hold outcomes (TP / stop / 24h time exit / still open) |
|---|---|---|---|---|---|
| real_money | 8 | +2.16 | +2.31 | **−0.15** | 0 / 0 / 5 / 3 |
| mirror_paper | 8 | +2.21 | +2.31 | −0.11 | 0 / 0 / 5 / 3 |
| paper floor (bybit_1) | 2 | −1.04 | −2.17 | **+1.13** | 0 / 2 / 0 / 0 |

Real money splits in two. **Resolved holds (the five 11-15 ml_entry closes): close +1.14 R vs hold +0.06 R, delta +1.08 R (mean +0.22
R/package).** No hold hit TP; all five would have run to the 24 h time exit. **Still-open holds (the three 11-16 closes: SOL, SOL,
XRP): close +1.02 R vs hold mark +2.25 R, delta −1.22 R** (ESTIMATED; these holds can still move). So the operator's read is right
for the 11-15 basket and is NOT yet right overall: the 11-16 closes are currently costing ~0.4 R each against holding.

By trigger (real_money + paper rows, one per package): stall +0.25 (n3, all time-exit holds), adverse_r +0.16 (n1), structure_break +0.42
(n2: one stop saved +0.97 R, one open −0.13), judgement_cadence −0.04 (n2), conflicting_exposure −0.35 (n2: BTC +0.20, SOL −0.90 open).
n is 1–3 per trigger: descriptive, not a test.

Harness view (`live_review_counterfactual`, closes modelled at the next bar open after the review, recorded in `outcomes.jsonl`): the
five 11-15 closes mean +0.13 R. The difference from +0.22 is the 3–16 min between the review stamp and the executed close.

## Why no applied close was priced since 11-05 (root cause, measured)
The grader IS scheduled: `live-review-rows-mirror` runs `live_review_grade.py --live --write-outcomes` on every main push and hourly
(last 5 runs, 07:21–08:35Z 11-16, all `success`). It priced nothing for the recent closes because `price_review` refused them:
1. **`hold_replay_unresolved_before_close`**: an applied close is priced only if the hold replay hits a stop/TP; the replay had no
   `max_hold_min` model, so every ml_entry hold (24 h time stop) stayed "unresolved". 5/5 on 11-15 and 3/3 on 11-16. **Fixed here**
   (`hold_replay`): 5 of 8 now price; the 3 still-open ones stay honestly ungraded until their hold resolves.
2. **Attribution**: `applied_by_outcome` required the review stamp BEFORE the executed close; two rows are stamped 2–6 min AFTER
   (dda66b33, a2c1ef8b), so they read as unapplied → `replay_mismatch`. **Fixed** (±900 s).
3. **`no_package_row`**: the packages read was one page of 150 (66 of 782 reviews). **Fixed** (paged).
4. Silent by design: the pricing step is `continue-on-error` and `|| exit 0`, and nothing alarmed on a missing grade. **Added** the
   `ltr_grade` probe (`attention_watch.py`): breached when an applied close is ungraded > 24 h. It is breached on landing for
   trade 6789 (no review row; filed below) — a real finding, not noise.
Not fixed: prop closes are absent from the journal trades table (no realised R to anchor a grade).

## (C) Can a codified rule replicate the non-hold calls?
The 10 priced calls fired on: stall 3, conflicting_exposure 2, judgement_cadence 2, structure_break 2, adverse_r 1. From the 11-01 S0
(552 packages): no trigger passes; adverse_r closes lose to random; stall beats hold (+0.36 R) but not a random-time close, i.e. trades
bleed with time. The fresh rows agree on the one thing that is mechanical: the stall closes beat a 24 h time exit (+0.25 R, n3).
`conflicting_exposure` and `judgement_cadence` are not replayable offline (they need the book / the reviewer). So: a mechanical
stall/time-stop is plausible but UNPROVEN; two units are authored (`RQ-20261116-7c1a-01` time/stall stops, `-02` weak-leg close),
rules registered before any run, bar = "does not lose vs hold" (one-sided 95% lower bound ≥ −0.05 R, month-stable). Corpus: 263 closed
roster crypto packages (journal pages since 2026-07-29; smaller than the 11-01 S0's 552 because the journal's package window is
shorter). Not run in this lane.

## Stated biases
Hold uses the stop/TP the review saw: later swing-ratchet stop moves and ml_first_passage TP extensions are not replayed. A stop fills
at its price. Open holds are marks, not exits. n is small (13 packages). Spot candles for the S0 corpus vs perp fills.

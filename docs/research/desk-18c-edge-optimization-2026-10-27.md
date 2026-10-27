# DESK-18C-EDGE-OPT — where judged-1's edge is, and the fastest honest road to a D-S0 PASS

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-18C-EDGE-OPT` (Tier 1, research), dispatched by Manager Session 2026-10-27a. Operator, 2026-10-27 ~12:10Z, verbatim: *"Ok, let's see if we can optimize the edge here - perhaps more selectivity, or better packets, or something else - I still want to get this live as soon as possible."*
Instrument: `scripts/research/desk_gen_edge_decompose.py` (new; it imports the registered driver and edits none of it). Records and the slice table: `comms/research/desk_gen_replay/judged-1-decomposition/`. Units: `research/queue/blocked/RQ-20261027-e72b-01.yaml`, `-02.yaml`.

## 1. Bottom line

1. **Judged-1 contains no evidence of entry timing.** Population: the 732 filled proposals of judged-1 (1,498 packets, window 2025-11-01..2026-09-15, six crypto USDT perps, registered scoring reproduced exactly: n 732, S1 +0.1589, asserted equal to the driver's `score()`). S3 = **+0.006, CI [-0.19, +0.19]**. The mean of the random-entry draws with the desk's own geometry was **+0.153 R** against the desk's **+0.159**. The positive S1 is what a short with these brackets earned in this window, not what the desk's timing added.
2. **It is short-side drift, concentrated in a few weeks.** 723 of 732 proposals are shorts, all market entries, all horizon 48. They sit in folds 1-2 (219 + 459; fold 3 has 43, fold 4 has 11). Over 33 weeks, the 3 best (2026-W05, W10, W04) carry the result: dropping them gives **+0.003 R**, dropping 5 gives -0.083. Even-numbered weeks +0.034, odd +0.290.
3. **No slice survives the number of slices looked at.** 70 slice levels in the table plus 6 conjunction/alternative lines I computed while choosing = **76 examined**. The smallest raw p belongs to a conjunction chosen after seeing AVAX (S3 +0.385, CI [+0.10, +0.63], raw p about 0.004, times 76 about 0.3). Nothing is a finding; two a-priori-plausible clauses are carried forward as one configuration (C1) for a held-out test.
4. **The fastest honest road is to test C1 on a window judged-1 never saw, and in parallel let the forward set accrue.** Neither is likely to produce a real-money-eligible PASS soon (§ 6): judged-2 is the only thing that can produce a PASS this week and I put its chance below 20% (judgement, from the power table); the forward set is free but the live desk has proposed **0 times in 22 packets**.
5. **Flag for the manager (not this lane's to fix):** the live desk's mechanical soak needs 1-2 clean `claude_desk` trades; at 0 `propose_entry` of 22 recorded wakes (2026-10-26 13:50Z .. 2026-10-27 12:05Z, `desk/decisions` `comms/desk/decisions.jsonl`) the soak itself may not complete. Why the live desk, which sees the strategies' book, proposes nothing while the masked judge produced 0.49 filled proposals per packet (506 of 1,498 packets, 34%, had at least one) is the highest-value open question for "live as soon as possible".

## 2. Decomposition (population: the 732 filled judged-1 proposals; S1 mean net R; S3 paired vs random; 95% weekly-cluster CIs, 10,000 draws for the headline, 3,000 per slice)

| set | n | S1 | S2 per capital-day | S3 |
|---|---|---|---|---|
| all | 732 | +0.159 [-0.05, +0.36] | +0.314 [-0.12, +0.65] | +0.006 [-0.19, +0.19] |
| all, without the suspect batch (indices 1332-1365, 22 fills) | 710 | +0.185 [-0.03, +0.38] | +0.369 [-0.06, +0.71] | +0.034 [-0.16, +0.22] |
| the suspect batch alone | 22 | -0.693 [-1.01, -0.24] | -1.086 | -0.895 [-1.23, -0.41] |
| novelty new / new_no_leg (-04's subset) | 616 | +0.159 [-0.07, +0.37] | +0.312 | -0.000 [-0.21, +0.21] |
| same, without the suspect batch | 595 | +0.194 [-0.04, +0.40] | +0.383 | +0.036 [-0.18, +0.24] |

The suspect batch (judged from base-rate rows only) loses, but it is 22 rows; removing it lifts the point estimates and **changes no verdict**. Registered folds on the full set: -0.019 (n 219), +0.261 (459), +0.159 (43), -0.553 (11); folds with n >= 20 and a positive mean: 2 (< 3). Post-cutoff stratum (>= 2026-06-01): n 27, +0.249.

Slices worth stating (full table: `decomposition.json`; S1 / S3, CI in the file):

| slice | n | S1 | S3 | note |
|---|---|---|---|---|
| session `us` (cutoff hour 13..20) | 239 | +0.321 [+0.09, +0.54] | +0.163 [-0.06, +0.38] | spread over 31 weeks; a-priori plausible (the liquid hours) |
| stop >= 1.0 ATR | 562 | +0.242 [+0.01, +0.44] | +0.071 [-0.16, +0.27] | stop < 1 ATR: n 244, S1 -0.018, S3 -0.122; a-priori plausible (inside 1h noise) |
| no rostered leg (BTC, AVAX) | 175 | +0.472 | +0.285 [-0.01, +0.52] | 13 weeks, 87% AVAX, fold 2 only: **cannot meet the 3-of-4 folds clause** |
| AVAX | 152 | +0.527 [+0.22, +0.77] | +0.322 [+0.04, +0.55] | no a-priori story; ETH (n 8) -0.775, SOL (n 107) S3 -0.305 [-0.60, -0.02] |
| judge_prior / p_hit / expected_r_net terciles, low / mid / high | 116-407 | .18/.12/.14 · .28/.06/.14 · .08/.25/.14 | all within +-0.12 | **no gradient: the judge's own confidence carries no information** |
| tp_basis swing_level | 47 | -0.009 | -0.092 | base_rate_quantile 462 (+0.160), measured_move 223 (+0.193) |
| one vs two proposals per packet | 280 / 452 | +0.048 / +0.228 | -0.057 / +0.045 | nothing |
| htf_trend chop / transitional / trending | 239 / 151 / 342 | +0.217 / +0.127 / +0.133 | +0.07 / -0.02 / -0.03 | nothing |
| the judge's own base-rate row (h48, side) terciles, high / mid / low | 244 each | +0.198 / +0.412 / -0.133 | -0.02 / +0.23 / -0.19 | non-monotone: noise, or a regime proxy |

Not slicable: `side` (9 longs), `horizon` (all 48), `entry type` (all market), `confidence` (the judged file does not carry it).
Variance structure (one-way week ANOVA on d_i, population: judged-1 fills): between-week sd 0.36, within-week sd 1.51, **design effect 2.25** for the full set (US-session alone 1.0, stop floor alone 1.9). This is why 732 fills give an S3 interval of +-0.19 where iid arithmetic says +-0.11.

## 3. Selectivity: three rules, none of them evidence yet

| rule | in-sample (judged-1) | expected rate | power on a fresh set |
|---|---|---|---|
| **A. US session only** (cutoff hour 13..20 UTC) | n 239 of 732; S1 +0.321; S3 +0.163 [-0.06, +0.38] | masked judge: 0.48 fills per US packet = 3.8 a day over the 8 US-session packets; **live desk: 0 of 22 packets so far, rate unknown** | S3 +0.16 at n 470: power 0.33-0.58; +0.10: 0.16-0.27 |
| **B. stop >= 1.0 ATR14** | n 562; S1 +0.242; S3 +0.071 [-0.16, +0.27]; 73% of A's fills satisfy it | removes 27% of proposals | alone it is the weakest of the three |
| **C. propose only where no rostered leg trades the symbol** (BTC, AVAX) | n 175; S3 +0.285 [-0.01, +0.52] | 1 symbol in practice | **not carried forward**: one symbol, one fold, 13 weeks; the registered 3-of-4 folds clause cannot be met by a rule whose trades fall in one fold |

**Configuration C1 = A AND B** (in-sample n 175, S1 +0.426 [+0.19, +0.64], S3 +0.259 [+0.03, +0.47]; 0.35 fills per US packet; 2.8 a day, 19.6 a week if the live desk behaved like the masked judge, which it does not yet). Its fragility, measured: dropping its 3 best weeks leaves S3 +0.107, dropping 5 leaves +0.018; even weeks S3 +0.389, odd +0.122; folds 51/116/6/2 fills, so the in-sample C1 itself would fail the 3-of-4 clause. **The in-sample figures are upper bounds**: C1 was chosen from 76 looks. My working expectation for its true S3 is +0.05 to +0.15 (judgement, not measured).

## 4. Packets: proposals ranked by expected value (proposals for the manager; nothing here edits a brief or a builder)

1. **State-conditioned base rates.** The history rows are unconditional trailing means (n about 3,000). The judge's side choice follows them (base-rate mean at the proposed side's h48: min 0.31, median 0.94, max 1.56; 462 of 732 targets are `base_rate_quantile`), so it shorts whatever has been falling: a slow trend follower, which is regime beta and carries no timing. Add rows conditional on the current state (distance to swing in ATR buckets, 24h return bucket, vol percentile, session), each with n. Highest value; needs a builder change and a new judged set (about $90-100).
2. **Give longs a real hearing.** 9 longs in 732: the desk cannot earn S3 in rising regimes if it never trades them. Higher-timeframe structure (distance to the 1d / 1w high and low in ATR, position in the 30-day range) beside the existing 3-state `htf_trend`, which showed no gradient.
3. **Point-in-time funding.** `funding` is `could_not_look` in the historical packets. Binance publishes funding history, so a masked-replay column is buildable; crowding is the most plausible missing signal for perps. Moderate value, moderate build.
4. **Drop from the decision burden:** `judge_prior`, `p_hit`, `expected_r_net` (flat across terciles), the `swing_level` target basis (n 47, S1 -0.009). Keep them as records for the students; do not let them gate.
5. **Record `confidence`** in the masked proposal rows; judged-1 cannot say whether a confidence gate would help.
6. **Not buildable for a historical replay:** news calendar, order-book spread (`could_not_look` in a point-in-time sense). They help the live desk only, and are not replay-testable.

## 5. Confirm design (both units are `blocked`, registered before any run; landing hold)

- **`RQ-20261027-e72b-01` — judged-2, configuration C1.** Why not a fresh seed on judged-1's window: judged-1 already holds 499 US-session cutoffs of that window's roughly 2,500 US-session hourly closes, their 48-hour paths overlap most of the rest, and the 33 weeks that carry the result are the same weeks, so it would confirm nothing. The window is **2024-11-01 .. 2025-10-25** (time-disjoint; before the judge's knowledge cutoff, which the PASS label states). Schedule: 1,341 US-session packets (MEASURED: the generator returns 1,341), seed 20261028, 2-hour gap, batches of 250, stop once 600 valid proposals exist (counted before replay). **Cost: 1,341 x $0.0688 = $92** (judged-1: $103.14 for 1,498 packets, $0.0688; the pilot measured it). Expected C1 fills about 470; MDE 0.29 R at design effect 2 (0.21 at 1). **PASS** needs n >= 300, S1, S2 and S3 each > 0 with CI lower bound > 0, mean > 0 in >= 3 of 4 folds (n >= 20 each), and mean > 0 after dropping the 3 best weeks. **FAIL** at n >= 300 if S1 <= 0 or S3 <= 0. INDETERMINATE otherwise, with the next step a second disjoint window (2023-11..2024-10), never a lowered bar. The packets, mask-key, the C1 judge addendum, the scorer and the verdict writer are in the script; smoke-tested end to end on 12 packets of that window (`packets` then `confirm`, fold cut on the window, verdict `indeterminate`, n 6 < 300).
- **`RQ-20261027-e72b-02` — forward-shadow set.** Replays every `propose_entry` on `desk/decisions` on real candles with the same engine, S1/S2/S3 and a same-symbol random-entry pool; reads at n >= 100 (point estimates, then 200, 400). It cannot certify a small edge (MDE 0.45-0.64 R at n 100) and is the sign check the registered -03 text asks for. Smoke-tested on the 22 live rows (22 `no_trade`, n 0, `read_state: no_data`). The realised `bybit_1` fills are a separate read through the journal and are not this unit's statistic.

## 6. Which is fastest, and when (INFERRED; dates assume the manager dispatches on 2026-10-28)

| road | cost | earliest verdict | chance it PASSes (judgement) | what a PASS buys |
|---|---|---|---|---|
| judged-2 (C1) | $92 | about 2026-10-30 (judged-1's wall time is not in the artifacts I read; one day of judging is an assumption) | below 20% unless the true C1 S3 is above +0.15 | "masked-replay only, pre-cutoff window": **not real-money eligible by itself** |
| forward set, all proposals, n >= 100 | $0 | 24 packets a day, every proposal filling: rate 0.20 per packet -> 2026-11-17; 0.10 -> 2026-12-08; 0.05 -> 2027-01-18; 0.02 -> 2027-05-23; **observed 0 of 22** | cannot PASS alone (MDE 0.45-0.64 R) | the second leg of the registered D-S0 |
| both in parallel | $92 | max of the two: **2026-11-17 at the very best, more likely December or later** | | D-S0 for the filtered desk = e72b-01 PASS AND e72b-02 supports at n >= 100 |

**Run both, in parallel.** Judged-2 is the only road that can say anything this week, and a FAIL (S3 <= 0 on a window it never saw) is itself worth $92: it ends the current packet and judge as the thing to tune and points at § 4 item 1. The forward set costs nothing and its date is set by the live proposal rate, which is the number to measure first. Real-money eligibility additionally needs Gate 1 (1-2 clean desk trades), `MD-PROMOTE-S1-S2` and, for the prop accounts, the survival gate; none of those is shortened by anything here.

## 7. What was not verified

- Wall-clock time to judge a batch; whether the live packet's rate of `no_trade` is the book it shows, the skill_sha change mid-run (`9515b3b` then `8e1eb2b`), or a different judge setting (22 rows, 2 skill versions, not enough to say).
- The 0.35 C1 fills per US packet rate transfers to another window only if the judge shorts as readily there; judged-1's rate was set by a market in which shorts paid.
- The slice CIs are 3,000-draw weekly-cluster bootstraps; raw p-values quoted are normal approximations from the interval half-widths.
- The scored statistic (S3) compares with random entries of the same fold, so a judge that is merely short in bearish weeks scores positive S3 when the fold is mixed; a judged-2 window with both regimes tests that, which is another reason for a window judged-1 did not cover.

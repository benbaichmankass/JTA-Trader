# DESK-AM-REFOCUS: why desk/LTR judgement has not added value, and the judgement-desk design

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · row `DESK-AM-REFOCUS` · lane session_01AFoLuLYH6B5e8LJSBB8q9x (dispatched by Manager Session 2026-10-30c)

**Gates this adds or changes:** none. No `mode:`, no `execution:`, no `*_ENABLED` flag, no new apply path. Every in-trade class stays advice-only (`ARCHITECTURE-CANONICAL` § "Active management" clause 4); `MD-TRADE-DESK`'s armed scope is unchanged.

**The goal (operator, 2026-10-30, verbatim):** *"we want the desk to be going active management that also helps train the mls"* · *"It can look for entries too / It just should be assessing each trade and managing it, we don't need it just for applying mechanical rules - the system already does that"*.

Every number below is MEASURED from a committed file at `main` b159f7586 (2026-10-30 ~22:20Z), with its population. INFERRED and DECIDED statements are marked.

---

## 1. Diagnosis

### 1.1 The evidence we have never tested discretionary judgement

All three blind tests of Claude's management measured Claude reading a **masked chart**. They did not measure a trader using context.

| test | population | what the judge saw | result vs HOLD (net of the full cost stack) |
|---|---|---|---|
| RQ-20261026-bf56-02, in-trade (`comms/research/RQ-20261026-bf56-02/40710666532/verdict.json`) | 176 decision points, the first bar at ≥ +1R, from 370 Stage-0 trades on 4 real-money legs | masked packet (`comms/research/desk_replay/judged-1/PROTOCOL-in_trade.md`): no symbol, no date, prices rebased to 100, **the strategy's own trailed stop and TP NOT shown**, volume and calendar withheld; actions limited to `hold` or `tighten_sl` | −0.048 R, CI [−0.143, +0.041]; 129 of 176 were hold |
| RQ-20261026-bf56-03, exit (same dir, `-03/40733370814`) | the same 176 points | the same masked packet; actions limited to `hold`, `partial_close` or `close` | −0.091 R, CI [−0.198, −0.003]; 136 hold / 36 partial / 4 close |
| DESK-LIFECYCLE-S0 full run (`docs/research/desk-lifecycle-factorial-2026-10-28.md` § 2.1, § 7.5) | 938 trades, 3,156 check-ins | the last 48 masked 1h bars plus trade state. § 8 says: *"no symbol, no date … no historical system book and no news"* | Claude entries −0.159 R [−0.261, −0.041] (n 473); random entries −0.124 R (n 465). Tightens were 981 of 1,155 actions, at −0.097 R each |

The ML test fails for the same reason. Q-TM1 (RQ-20261029-7294-02, row `ML-AM-NEXT-LIVE`, 2,627 trades, 6 purged folds) lost −0.056 to −0.079 R per trade vs hold. Yet the out-of-sample hindsight action-value ceiling is **+0.86 R per trade**. The row's own diagnosis: *"the hindsight value exists, these features do not select it"*. The R1 state features are the common factor across four negative results.

**Reading (INFERRED from the table above).** The value is there in hindsight. It cannot be selected from trade state plus a masked chart, by Claude or by a GBDT. The masked replays deliberately removed what a discretionary trader adds: which asset, what the higher timeframe and the correlated book are doing, what is scheduled, the strategy's own exit plan, and how this leg has run live. A masked failure is therefore not evidence that informed judgement fails. It is evidence that judgement **without that information** fails, which is exactly what the mechanical rules already cover.

### 1.2 Inputs: the live LTR packet gives the reviewer no chart and no context

Population: the newest packet on `live-review/rows`, `comms/live_review/packets/LR-20261030T2056Z-pkg-92d1cafe559b4309.json` (`packet_version` 2, built by `scripts/ops/live_review_packet.py`). It is typical of the 151 packets on that branch.

- **The whole packet is 4,820 bytes, and 2,578 of them are the priced table.**
- **It carries no candles at all**: no bars, no swing levels, no higher-timeframe trend, and no level for the `momentum_flip` / `structure_break` that woke the review. The row's own flag says *"levels of momentum_flip and structure_break not in the packet"*.
- The context blocks are a 63-byte calendar, a 104-byte news score, `funding` `not_applicable`, and `correlated_open_packages: []`.
- `missing_inputs` lists `regime.vol_now`, `regime.cell_entry` and `context.live_vs_backtest`.

Across all 240 rows in `comms/live_review/reviews.jsonl` (2026-10-25 16:30Z to 10-30 20:59Z, 39 packages), the `missing_inputs` flags read:

| missing input | rows |
|---|---|
| `regime.vol_now` | 91 |
| live-vs-backtest | 102 (82 + 20 spellings) |
| `regime.cell_entry` | 71 |
| funding | 74 (53 + 16 + 5) |
| `priced_options` | 31 |

**The priced table prices only `hold` and `tighten_sl`.** Option sets over the 240 rows: 154 rows priced nothing, 57 priced only `hold`, and the rest priced `hold` plus tightens. `close`, `partial_close`, `move_tp` and `widen_sl` are never priced (filed earlier as PI-20261028-KD5SQ3JJ-0002).

The hold cell is also mis-conditioned. It is the leg's peak-then-pullback population, not the trade's current state. The newest row says so itself: *"table hold is the peak-then-pullback population, not conditioned on open_r -0.81"*.

### 1.3 Instructions: the brief turns judgement into restating the table

`REVIEWER-BRIEF.md` § 2 step 2: *"Price from the table, never by hand … A number not in the packet does not go in the row."* With no bars in the packet, the table is the only evidence a reviewer may cite.

No field asks for a forecast, and the row schema has no slot for one. Over the 240 `recommendation.reason` strings:

| words in the reason | rows |
|---|---|
| "expect" | 0 |
| "will " | 0 |
| "predict" | 1 |
| "hold cell" | 55 |
| "n=" | 78 |

So no call can be falsified on its own terms, only graded against hold after the fact.

**Advice-only plus an evidence base that says acting loses** (§ 1.1, the DESK-LIFECYCLE tightens) leaves "hold" as the safe answer. Actions over the 240 rows:

| action | rows |
|---|---|
| hold | 131 |
| no_recommendation | 55 |
| flag_mechanics | 33 |
| close | 15 |
| tighten_sl | 6 |
| move_tp, partial_close, widen_sl | 0 |

On the **43 rows touching a real-money or prop account: 33 hold, 7 no_recommendation, 3 flag_mechanics, and 0 judged bracket moves in 5 days.**

### 1.4 Cadence: the LTR looks when a mechanical rule fires, and the desk never manages at all

- **LTR triggers over the 240 rows:** manual 64, daily_floor 32, short_hold 27, adverse_r 24, giveback 17, r_milestone 16, new_peak 11, then the rest. Every non-manual trigger is a mechanical threshold, so the reviewer arrives after the rule has already seen the event.
- **Gap between successive reviews of one package**, excluding short-hold, n = 175 gaps: median 1.7 h, p75 6.0 h, p90 20.2 h. Reviews per package: median 4 over 39 packages.
- **The desk's 136 rows on `desk/decisions` are ALL `entry_generation`** (`comms/desk/decisions.jsonl`, 2026-10-26 13:50Z to 10-30 18:19Z). Zero are in-trade or exit. The desk does not assess any open trade; skill § 2 hands that role to the LTR.

### 1.5 Action set (entries): the 60-minute cap makes `no_trade` the right answer

Desk entries split 126 `no_trade` (93%) and 10 `propose_entry` over 136 rows.

`DESK-BRIEF.md` § 3.2 caps a live desk entry at `max_hold_min` ≤ 60 and requires pricing it on a row no longer than the hold. On the 1h scan that is the 1-bar row. The brief itself says that row is *"mostly negative net of cost: they make the hold priceable, not profitable"*, and that `no_trade` *"usually will be"* the answer. The newest row's rationale is exactly that: *"Every 1-bar (60 min) net-of-cost row on the desk-leg symbols is negative."*

Six proposals have been priced, n = 6 (`comms/desk/role_grade.json`): mean +0.57 R, but −0.40 R vs random, CI [−2.4, +1.6]. That is indeterminate.

### 1.6 What the live record does and does not show

There are 14 live LTR `close` outcomes in `comms/live_review/outcomes.jsonl`, with mean dR vs hold +0.91 R. All 14 are paper, none executed, and they come from **4 distinct packages**, mostly one `ict_scalp_xrp_15m` short-hold trade reviewed every 5 min. That is an anecdote, not evidence, and it is quoted only so nobody else quotes it as evidence.

### 1.7 Verdict on the four candidate causes

| cause | finding | weight (INFERRED) |
|---|---|---|
| **Inputs** | No chart, no higher timeframe, no correlated book, no live-vs-backtest, a near-empty calendar, and options priced only for hold/tighten with a mis-conditioned hold cell. The blind tests masked even more. | **primary** |
| **Instructions** | "Number only from the table", no forecast field, and advice-only on an "acting loses" evidence base. The result is table restatement and hold. | **primary** |
| **Cadence** | Wakes are mechanical-event-only and the desk never wakes on an open trade. Judgement arrives after the rule and is never scheduled. | secondary |
| **Action set** | In-trade enum is broad on paper but only hold/tighten are priced. Entries are capped at 60 min, so the cost stack dominates. | secondary (entries: primary) |

**What this does not show.** It does not show that informed judgement adds value. No test has given the judge the context, so that question is **open**. The design below is built so the live desk answers it, graded and pre-registered, rather than assuming it.

---

## 2. Design: the judgement desk

DECIDED by this lane within the dispatch. Items marked **operator** are preferences for the operator.

### 2.1 One desk, one in-trade function

The in-trade function stays the live trade review. It is the desk's in-trade role (`trading-desk` SKILL § 2, `MD-TRADE-DESK`), so there is still one schema, one apply path and one grade. What changes is **what it is asked and when**. No new store and no new mandate.

### 2.2 Cadence: a regular judgement slot for every open trade, plus the existing triggers

- **New due event `judgement_cadence`.** Every open package becomes due once its last review is older than `hours_by_timeframe[tf]`. The level is the slot start, so all packages share one slot and arrive in **one wake**. The existing mechanical triggers stay on (22:25Z scope correction: wakes stay ON).
- **Default cadence (proposed):** `1h`/`2h` legs every 4 h; `4h` legs every 8 h; `1d` legs every 24 h. 5m/15m short-hold trades keep their own lane.
- **One book wake per slot, not one session per package.** A `judgement_cadence` wake carries every due package's packet, and ONE reviewer reads them as a book and writes one row per package. The manager recipe changes to match.
- **Cost (INFERRED, from the measured $0.30–0.35 per Sonnet wake on a ~53 KB packet).** A 4-hourly book wake is 6 wakes/day. With ~15 open packages at ~10 KB each (MEASURED median 9.8 KB, § 2.3) the context is ~150 KB, so a wake is likely $0.50–0.80: **≈ $3–5/day**. Per-package sessions at the same cadence would be ≈ $30/day. **Operator:** whether 4 h is the right default for 1h/2h legs.
- **Comment budget.** The wake comment holds 60k chars. With today's ~10 KB packets plus tables, a book wake spans several comments; the poster splits them (Tier-2 increment).

### 2.3 The packet: what a trader looks at (`packet_version` 3, `context_v3`)

Built by `scripts/ops/live_review_packet.py`. Every block is a pure read of routes the generator already uses, plus `api/bot/performance/recent`.

| block | content | MEASURED on live data, 2026-10-30 ~23:10Z, 15 open packages |
|---|---|---|
| `chart` | last 16 closed bars on the leg timeframe; 3 swing highs and 3 swing lows with distance in ATR; high/low since entry | 14 of 15 (gld_pullback_1h: timeframe not in meta, named in `missing_inputs`) |
| `htf` | the next timeframe up (1h→4h, 2h/4h→1d, 1d→weekly built from daily): last 8 bars, swings, ADX trend label | 14 of 15 |
| `book` | every other open package, either side: symbol, direction, leg, open_r | 15 of 15 (14 others each) |
| `exit_plan` | entry, stop/TP now, the leg's declared exit levers, the package `exit_plan_state` — i.e. what HOLD actually does | 15 of 15 |
| `live_vs_backtest` | `scripts/research/live_vs_backtest.py` verdict for the leg, realMoney and mirror books | 15 of 15 read. Only Stage-2 legs have a verdict; testing legs read `NO_LIVE_TRADES` (a gap, § 4) |

Median packet 9.8 KB, of which `context_v3` is 4.0 KB. The v2 packet was ~5.8 KB.

**Still not in the packet (§ 4):**
- a live-vs-backtest read for paper legs;
- funding for perps (no route);
- the live volatility bucket;
- how similar trades played out *from this state*. The priced table is still mis-conditioned; it is quoted as evidence, never as the decision.

### 2.4 The brief: a reasoned view and a falsifiable forecast (`REVIEWER-BRIEF.md` § 2b)

The reviewer reads the market first, then writes a `forecast` with these fields:
- `thesis`;
- `direction` relative to the trade;
- `target_px` and `p_target`;
- `invalidation_px`;
- `horizon_bars` on `timeframe`;
- `evidence`.

The action must follow from the forecast, and HOLD is defined by `exit_plan`. **The validator requires a forecast** on every judged row reviewed from 2026-10-31T00:00Z (`scripts/ci/check_live_review_records.py::forecast_problems`). The short-hold lane is exempt.

This is a record-schema rule, **not an execution gate**: nothing trades or stops trading because of it.

### 2.5 Entries continue

The scan wake is unchanged (every 2 h, triggers capped at 4/day).

**Operator** (Tier 3, proposed, not changed): the live desk-entry cap `max_hold_min` ≤ 60 is why 93% of entry rows are `no_trade` (§ 1.5). A cap at the scan's 4-bar horizon (≤ 240 min) would let the desk price live entries on rows that are not dominated by the round-trip cost. That needs the DESK-13 evidence path for anything real-money. On demo it is the operator's call.

### 2.6 Training rows the ML heads can learn from

- **No new store.** The rows ARE `comms/live_review/reviews.jsonl` (canonical, mirrored from `live-review/rows`). The packet is joinable by `packet_sha`.
- `ml/datasets/families/claude_judgments.py` adds these columns (in the held Tier-2 PR: the landing guard names that file Tier-2):
  - `fc_direction`, `fc_p_target`, `fc_horizon_bars`;
  - `fc_target_r` and `fc_invalidation_r`, rebased to R from the mark at review time, + in the trade's favour;
  - `trigger_event`, so cadence and mechanical wakes can be told apart.
- **Labels:**
  - the action's `delta_r` vs hold (LTR-5);
  - the forecast outcome (§ 3).
- **What this links to:**
  - **ML-AM-NEXT-LIVE:** Q-TM1's diagnosis is "the features do not select the value". These rows add a teacher's view of *context* features: the forecast plus the v3 packet.
  - **AM-REGRADE-BOOKSIM / AM-RISK-ADJUSTED-RULE:** graduation of any class still goes only through `RULE-AM-RISK-ADJUSTED-V1` on the book simulator.
  - **LTR-* rows:** the same schema and route.

---

## 3. Pre-registered grade: RULE-DESK-AM-JUDGEMENT-V1

Registered 2026-10-30, **before any row carries a forecast**. Computed by `scripts/research/desk_am_judgement_grade.py`.

- **Population.** Live-review rows with a `forecast`, reviewed from 2026-10-31T00:00Z, on CLOSED packages.
- **Unit.** The order package. Its judged rows are averaged first, so one trade reviewed many times counts once.
- **Comparators, net of the full cost stack** (LTR-5 replay, `live_review_counterfactual.price_review`, stop-first inside a bar):
  - **HOLD** = the untouched strategy bracket and trail. `d_hold` = the call minus HOLD.
  - **MECH** = the same review re-priced as the mechanical rule: tighten to breakeven when in profit with the stop behind entry, else hold. This is bf56-02's B3 choice in all 4 folds. `d_mech` = `d_hold` minus MECH's own delta.
- **Statistic.** The mean of the package means of `d_hold`, with a 95% CI from a package bootstrap (10,000 draws, seed 20261031). The mean of `d_mech` is reported beside it.
- **PASS:** n_packages ≥ 30 AND the CI lower bound of `d_hold` > 0 AND mean `d_mech` > 0.
- **FAIL:** n_packages ≥ 30 AND (mean `d_hold` ≤ 0 OR the CI upper bound < 0).
- **Otherwise:** `indeterminate` at n ≥ 30, `accruing` below it.
- **Reported, never gating:**
  - each action class's mean `d_hold`;
  - forecast calibration: hit = target before invalidation within the horizon; Brier vs the 0.25 constant reference;
  - unresolved forecasts.
- **What a PASS does and does not do.** A PASS says informed judgement beats HOLD and the mechanical rule on live trades. It **graduates nothing**: each in-trade class still needs its own `RULE-AM-RISK-ADJUSTED-V1` test on the book simulator (`ARCHITECTURE-CANONICAL` § "Active management" clause 4). A FAIL means the context did not rescue the judgement, and the desk's in-trade wakes go back to the cost table for the operator.
- The numbers above (30, 10,000, the seed, the MECH rule, the forecast rule date) are not changed after any result.

---

## 4. Not done / known gaps (each filed)

- **Live-vs-backtest for testing legs.** `live_vs_backtest.py` judges only the realMoney/mirror books, so a paper leg reads `NO_LIVE_TRADES`.
- **Perp funding and the live vol bucket.** Unchanged, still named in `missing_inputs`.
- **The priced table's hold cell is not conditioned on the current state** (§ 1.2). Still open, PI-20261028-KD5SQ3JJ-0002 (pricing close/partial).
- **`judgement_cadence`, the multi-comment wake split and the manager's book-wake recipe** are the Tier-2 increment (held PR).

# Programme 03 — Strategy improvement: every leg pulls its own weight

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-14` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `P3-STRATEGY-PROGRAMME` (dispatched by Manager Session 2026-10-14 from the operator's weekly planning) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) row **P3** · roadmap `M21` + `M22` + `M27` + `L-LADDER` · **Tier-1 document: it proposes tests. Every config, roster or param change it leads to is Tier-3, needs an evidence record, and goes through the manager.**

Numbers marked MEASURED were measured in this lane on 2026-10-14 from the file or command named beside them. Re-run the command rather than quoting the figure. Seeds: [`.claude/skills/perf-followup/SKILL.md`](../../../.claude/skills/perf-followup/SKILL.md) (the four tracks), `comms/reviews/performance-review-20261010-191000.json` and its follow-up record `comms/perf_followup/perf-followup-20261010-191000.json`, `research/THEMES.yaml`, `research/queue/PLANNING.md`, `docs/roadmap/milestones.yaml`.

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

Population: units whose `grading.graded_at` is 2026-10-14..2026-10-21 and whose file names this programme (`programme:` or `programme_node.programme`), read from `research/queue/*.yaml` on main at 2026-10-21 ~18Z. Units with no programme field (486 of the 657 graded in the window) are counted in the research map, not here.

**Graded in the window: 2** (1 pass, 1 landed ungraded). Most of this programme's work is graded under the
live_strategy theme without a programme field (live_strategy graded 170 in the window: 49 pass, 33 fail, 38 indeterminate,
31 no_action_warranted, 19 open).

**What was learned**
- `trend_donchian_eth` (ETH 1h, on no roster) AS DECLARED cleared Stage 0 at power on 2022-10.. (RQ-20261018-003 PASS).
- The SOL same-symbol overlap read (RQ-20261018-001) landed 2026-10-21 and is ungraded; research-ops owns its disposition.
- Instrument-fidelity finding (Q5): ef5d-06/-07 passed ATR percentiles as 50/75/90 to flags compared against a 0-1 rank, so the
  gated arms measured only warm-up trades (ef5d-07: V50 = V75 = V90 = n 33, +5.70 R, identical). `backtest_trend.py` and
  `backtest_pullback.py` now refuse a percentile outside [0, 1]; live config already uses the 0-1 scale.

**Answered / unlocked / retired**
- Q2-C closed (470a-01, 470a-10 both FAILED their disjoint windows); Q4 closed (419b-02/-03 FAIL, -04 no_action_warranted);
  Q5 / Q7 carried by their build rows. Recorded in the tree's `questions:` map.
- P3-Q8 (breadth) authored as Stage A — five units below. P3-Q1 Stage B still waits on build row LIVE-BT-STAGE-B.

**Next 3–4 weeks (pre-registered this review)**
- RQ-20261021-7c2b-06..-10: each real-money/prop family AS DECLARED on six liquid perps no roster carries (BNB, DOGE, LINK, LTC,
  BCH, DOT), 2020-06..2026-10, pooled Stage 0 with breadth: `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `xrp_pullback_2h`,
  `ada_pullback_2h`, `trend_donchian_eth_prop` (1h). A passing CELL opens Stage B (overlap read, then a re-entry case for a
  bybit_1 soak); a family that fails all six is a symbol fit.

**Cross-programme feeds**
- → P5: passing 1h cells from 7c2b-10 go to the prop EV/survival gate (P5-Q6), conditional on the firm offering the symbol.
- ← P7: the daily-bar results feed the overlap read for any daily leg added beside the 4h book.

## 1. End goal and measure

**Goal.** Every leg on a roster earns its place **at the parameters it is configured with**. A leg that drags is tuned first and retired only if tuning fails (operator, 2026-09-27: retire a line only when its registered exhaustion condition fires). A tuning result reaches a config change only after it has survived a test it was not chosen on.

**Headline measure (operator, 2026-10-14).** **Net P&L per capital-day, in R and in $, per strategy, and capital-weighted at portfolio level.** Read separately for real money, mirror, prop and paper; never pooled across classes. Mirrors carry the real-money verdicts by roster equality (`tests/test_paper_portfolio_accounts.py`).

| measure | population | instrument | baseline |
|---|---|---|---|
| **Stage-0 net R per capital-day at configured params**, per routed leg | every (account, leg) routing on a live-mode account in `config/accounts.yaml`; each leg's committed evidence record plus the `__bt.json` it names | `python3 scripts/research/stage0_capital_day_census.py --n-floor 39 --fold-share 0.75 --out <dir>` (new, this lane; weekly unit `RQ-20261014-470a-11`) | **MEASURED 2026-10-14** (table below) |
| Live net R and $ per capital-day per leg and per book | provenance-trustworthy closes, net of fee, slippage and funding | row `HEADLINE-MEASURE-CAPITAL-DAY` (build, Tier-1 read path; owned by P2's lane) | **not served yet.** Nearest number: real-money expectancy −0.3231 R lifetime (n=431, 2026-09-21, before the roster cut) |
| Stage-0 pass rate at configured params | the same routings | the census above: share graded `pulls_weight` | real money **3 of 7** legs; prop **0 of 2**; mirror 3 of 6; paper 4 of 24 |
| Tuning-result survival | every P3 sweep PASS | share of rung-S0-C confirmations that read CONFIRMED | **0 measured.** The first two confirmations are `RQ-20261014-470a-01` and `-10` |
| perf-review grade per leg | the review window | `/performance-review` | the 2026-10-10 review; read by `/perf-followup` |

**Stage-0 census, MEASURED 2026-10-14** (`stage0_capital_day_census.py`, records on `main` at this branch's base). Capital-days are position-days at 1R. Each record covers its own window, so compare signs and grades across rows, not levels.

| class | leg | grade | n | net R | R / capital-day | folds + | window |
|---|---|---|--:|--:|--:|--:|--:|
| real | `trend_donchian_eth_4h` | pulls weight | 116 | +33.33 | 0.0861 | 4/4 | 1095 d |
| real | `ada_pullback_2h` | pulls weight | 57 | +19.25 | 0.1738 | 4/4 | 365 d |
| real | `trend_donchian_xrp_4h` | pulls weight | 46 | +8.14 | 0.1266 | 3/4 | 1460 d |
| real | `xrp_pullback_2h` | **drag** (2/4 folds) | 55 | +7.23 | 0.0318 | 2/4 | 365 d |
| real | `iaum_pullback_1d` | underpowered | 7 | +7.66 | 0.0370 | 3/4 | 365 d |
| real | `slv_pullback_1d` | underpowered | 11 | +2.48 | 0.0248 | 2/4 | 365 d |
| real | `ief_pullback_1d` | underpowered | 3 | +4.32 | 0.0167 | 2/3 | 365 d |
| prop | `trend_donchian_eth_prop` | **drag** (2/4 folds) | 163 | +9.32 | 0.1062 | 2/4 | 365 d |
| prop | `trend_donchian_sol_prop` | **drag** (2/4 folds) | 65 | +5.19 | 0.0765 | 2/4 | 365 d |

Paper (`bybit_1`, `ib_paper`, `alpaca_paper`, options paper): 24 legs; 4 pull weight, 2 drag (`xrp_pullback_2h`, `mgc_trend_1h` 2/4 folds), 15 underpowered (every 1d equity and futures leg: n 3–12 on 365 days), 3 no record (`trend_donchian_1h`, `ict_scalp_mgc_15m`, `splg_trend_long_1d`). The `slv_trend_1h` figure (1.0567 R per capital-day, n=68) is about 6× any other leg's and should be checked before anyone quotes it.

**Reading.** Every real-money and prop leg is net-positive at Stage 0. Here **"drag" means fold inconsistency, not a loss**: 2 of 4 folds positive. The three alpaca 1d legs cannot be graded at all on a 365-day record. That gives P3 three priorities, in this order: (a) re-measure the underpowered real-money legs at power; (b) tune `xrp_pullback_2h`, the weakest real-money leg per capital-day and the least fold-consistent; (c) confirm before changing anything.

## 2. Standing rules for this programme

1. **Configured params only.** Every arm is built by `regime_debt_matrix.build_harness_cmd` from `config/strategies.yaml`, plus the arm's tokens (`scripts/research/exit_lever_ablation.py`). The baseline arm reproduces the committed record as a positive control wherever a record exists on the window.
2. **Full cost stack, always.** Fee, slippage and funding go through `execution_costs.resolve_cost_policy()`. Two harnesses lack it and stay out of P3's corpus until fixed: `backtest_orb.py` and `src/backtest/backtester.py` (CLAUDE.md § D1). **New this lane: `backtest_pairs.py` with `hedge_beta: rolling` mis-scales R** (§ 3 Q5), so the M22 PASSes are not read as net-of-cost evidence until `PAIRS-R-SCALE` lands.
3. **A best-of-k PASS is a lead, not a finding (rung S0-C).** A sweep picks the best of k pre-registered arms on one window, so its winning dR carries selection inflation. Before any Tier-3 proposal, it must survive **one** fresh-window confirmation:
   - the passing arm alone vs the declared leg;
   - on the disjoint window immediately preceding the one it was chosen on;
   - the same bars, nothing re-selected, and the windows not pooled.

   CONFIRMED means a Tier-3 proposal note on the owning row. NOT CONFIRMED records the lead as a selection or period artifact. Every P3 sweep unit registers this in its rule.
4. **Material, consistent, no worse drawdown.** Each comparison is graded on a materiality bar in R over the window: 1.0 R for 2h pullbacks, 2.0 R for 4h Donchian, as the 2026-10-14 entry batch used. The candidate must also have dDD ≤ 0 and win at least 3 of 4 equal calendar folds, and the baseline needs n ≥ 39. Below 39 the result is `indeterminate`, never FAIL. The try-again move is a longer window, not a looser bar.
5. **Try again with a new hypothesis, not the same parameters** (perf-followup Track 1.3). A FAIL makes the axis `honest_negative` for that leg and window. An `indeterminate` re-asks the same arms on a longer window.
6. **Nothing here edits `config/`, `src/` or a roster.** A CONFIRMED result on an off-roster leg is an input to a re-entry case under `MD-PROMOTE-S0-S1`, built as a new evidence record at the new configured params.

## 3. Questions, in dependency order

```
Q1 per-leg weight (Stage-0 census + live capital-day) ─┬─▶ Q2 tune before retire (entry axes on the drag/underpowered legs)
                                                       │        └─▶ S0-C fresh-window confirmation ─▶ Tier-3 proposal
                                                       ├─▶ Q3 power: re-measure underpowered legs on long windows
Q4 lessons (perf-followup Track 2) ────────────────────┴─▶ Q6 extrapolate (Track 3): transfer a confirmed lever to siblings
Q5 instrument integrity (pairs R scale; ORB/backtester cost stack) ─▶ M22 / new families at Stage 0
Q7 portfolio (Track 4): overlap, concentration, leave-one-out ◀── PERF-FU-LEG-REPLAY (per-trade replay, build)
P1 feeds: giveback census RQ-20261014-9807-01 is Q1's live half; exit levers stay P1's.  P2 feeds: every P3 record is a label row.
```

| Q | question | why it sits here | existing work (do not duplicate) |
|---|---|---|---|
| **Q1** | What is each routed leg's net R per capital-day, at Stage 0 and live, per account class? | Every later question picks its legs from this table | **new `RQ-20261014-470a-11`** (weekly census); live half: row `HEADLINE-MEASURE-CAPITAL-DAY`; P1's `RQ-20261014-9807-01` (giveback and live capital-day) |
| **Q2** | Does a single entry-axis change (trend floor `adx_min`, depth `pullback_frac`, breakout strength `min_confidence`, re-entry `cooldown`) beat a real-money leg as declared, and does it survive S0-C? | The cheapest lever. The 2026-10-14 entry batch (`RQ-20261014-f0e2-*`, 13 units) measured mostly legs that are **not on a roster** (`sol_pullback_2h`, `eth_pullback_2h`): the real-money legs were barely touched | f0e2-01..13 (done/queued); M21 coverage matrix (`docs/research/entry-refinement-coverage.json`, last updated 2026-07-14); `M21-REGRADE-RETEST` (row); **new `470a-02..09`** |
| **Q2-C** | Do the 2026-10-14 PASSes survive a window they were not chosen on? | Both were best-of-3 on one leg and one window | **new `470a-01`** (f0e2-05, mandatory), **`470a-10`** (f0e2-10) |
| **Q3** | Can the underpowered real-money legs (`ief`/`slv`/`iaum_pullback_1d`, n 3–11) be graded at all? | A leg that cannot be graded cannot be tuned. 1d equity history goes back decades, so the limit is the window, not the data | weekly "walk-forward re-run" units (`RQ-20261003-011`, `RQ-20261004-660`, `RQ-20261005-016`, 365 d, `research-harness-dispatch.yml`); `RQ-20261006-061` (finite TP, P1); `RQ-20260831-002` (1830 d accrual on five other 1d legs). **Proposed W2 unit:** the three alpaca_live legs on a ≥ 10-year window (yfinance `period` is uncapped for 1d) through `exit_lever_ablation.py` |
| **Q4** | What do the window's trades say the system is good and bad at? | perf-followup Track 2; lessons L1–L11 of the 2026-10-10 run | `RQ-20261010-419b-02` (pullback short side), `-03` (trend long/short asymmetry), `-04` (portfolio); rows `PERF-FU-LEG-REPLAY`, `PERF-FU-REDUCE-PNL` |
| **Q5** | Do the instruments measure what they claim, net of cost? | A PASS from a mis-scaled harness is not evidence | **new finding (MEASURED):** pairs R scale; build row **`PAIRS-R-SCALE`**; blocked unit **`RQ-20261014-470a-12`**; D1 harnesses (ORB, `backtester.py`) |
| **Q6** | Does a confirmed lever transfer to sibling legs (same family, timeframe or symbol)? | perf-followup Track 3; one pre-fixed value tested on a new leg is selection-free | **new `470a-02/03`**: f0e2-05's `adx_min=22` on the two real-money 2h pullbacks, run beside `470a-01` so the two answers read together |
| **Q7** | Which legs are the same bet twice, and which removal or addition improves window and trailing net P&L per capital-day? | perf-followup Track 4; L3: the worst 10 of 82 days carry 67 % of negative-day R on `bybit_1` | `RQ-20261010-419b-04` (blocked on `PERF-FU-LEG-REPLAY`); `RQ-20261007-017` (Stage-0 ETF baskets) |
| **Q8** | New families and small timeframes at Stage 0 (M22 small-TF, M27 scalps) | Breadth after the roster is honest | M27: `RQ-20260928-001` (HTF bias, session-bound; blocked on `ICT-SCALP-HTF`), `RQ-20261007-004` (scalp revision 0/5); prop breadth units `RQ-20261010-353c-*`, `RQ-20261011-*` (P5's pool); frontier strategy scan (weekly) |

### Q5 — the pairs R-scale finding (MEASURED this lane, 2026-10-14)

`RQ-20261007-005..008` graded the four configured M22 pairs PASS at configured params, +51.8 to +102.4 R at n 273–304. The fee-only arm sat within 0.15 R of the full stack. Two independent measurements explain why:

- **The committed ledger.** For `pairs_sol_eth` (`comms/research/RQ-20261007-005/<run>/trades.jsonl`), the mean `cost_r` is **0.0014 R per pair trade** over 304 trades, with `risk_spread` ≈ 1.34.
- **Recomputed from raw candles.** SOL and ETH 1h for May 2026 (Binance Vision), using the harness's own `_rolling_beta` (15-bar window):
  - The spread `log A − β·log B` has a 15-bar std of **1.63** when β rolls, against **0.0021** with β held at the entry bar's value. That is ~775× more risk, because β moves by σ ≈ 0.61 and multiplies log ETH ≈ 7.8.
  - The 2-leg fee plus slippage (2 × 10.5 bps) therefore costs **0.0006 R** in the harness, against **~0.50 R** at the fixed-β risk.

What this does and does not establish:

- It **establishes** that the cost-in-R term is understated by roughly three orders of magnitude for `hedge_beta: rolling`.
- It does **not** establish the sign of the honest net. Gross R is measured in the same inflated units, and the z-score entries are driven by the same β noise.
- **So the four PASSes are unreadable, not negative.**

The fix is a Tier-1 harness change (row `PAIRS-R-SCALE`). After it lands, the re-measure is pre-registered as `blocked/RQ-20261014-470a-12`. Whether the live `pairs_executor` sizes on the same quantity is a question for that row, not something established here.

## 4. Test ladders — cheap and decisive first

**Q1 — weight.**
1. **Census (weekly).** Run `470a-11`. Every real-money or prop leg graded `drag` or `underpowered` must carry an open P3 unit, or a stated "no action, because", by the next weekly pass.
2. **Two-week escalation.** A real-money leg graded `drag` on two consecutive runs with no open unit is raised to the manager as a tune-before-retire case.
3. **Live half.** Once `HEADLINE-MEASURE-CAPITAL-DAY` serves it, read the live capital-day figure beside the Stage-0 one, per class. A leg whose live sign disagrees with its Stage-0 sign over n ≥ 20 closes is a cost-fidelity question (Gate 1), not an edge question.

**Q2 — tune before retire.**
1. **Single-axis sweeps** on the real-money legs (`470a-04/05/06/07/08/09`): three fixed arms each, at the rule in § 2.4.
2. **S0-C confirmation** of any PASS: a unit authored by the reading lane with the template in § 2.3. Its window:
   - the disjoint preceding window, from public Binance Vision history back to 2018 for the crypto legs;
   - for a 1460 d record, 2018-10 to 2022-10.
3. **Tier-3 proposal** with both records, sent through the manager. The mandate resolver is checked first. A leg still on its roster changes params only through a CONFIRMED record.
4. **Expensive rung.** Pairs of axes (a 3×3 grid) only on a leg where two single axes each confirm. A grid on a leg whose single axes failed is a search, not a test.

**Q2-C — confirmations due now.** `470a-01` (`eth_pullback_2h` A22) and `470a-10` (`trend_donchian_sol_4h` VH95). Their rules:

| verdict | meaning | what follows |
|---|---|---|
| PASS | CONFIRMED | a Tier-3 proposal note (re-entry case under `MD-PROMOTE-S0-S1`; both legs are off every roster) |
| FAIL | NOT CONFIRMED | the axis is `honest_negative` on both windows |
| indeterminate | underpowered | one re-ask on the window before, nothing else changed |

**Q3 — power.**
1. **W2 unit.** The three alpaca_live 1d legs on a ≥ 10-year Yahoo window through `exit_lever_ablation.py`. One arm-free baseline plus one placebo-equal arm, so the sweep grader runs, and the rule asserts the two are identical (`--same-as`). This produces a graded record at configured params.
2. **Census rule.** A leg still at n < 39 on ten years is reported `infeasible` at Stage 0 for its timeframe. That is a roster question for the manager, not a tuning one.

**Q5 — instrument integrity.**
1. **Build** `PAIRS-R-SCALE`.
2. **Re-measure** with `470a-12`. Its rule includes a positive control: mean `cost_r` < 0.01 R means the bug is still present and the result is indeterminate.
3. **Then** decide the M22 roster from that record, not from the sprint log (M22 `next`).

**Q6 — extrapolate.** `470a-02/03` test `adx_min=22` as one pre-fixed arm on `xrp_pullback_2h` (declared 25) and `ada_pullback_2h` (declared 28). Read them together with `470a-01`:

| `470a-01` | transfers | reading |
|---|---|---|
| PASS | PASS | a family property |
| PASS | FAIL | eth-specific |
| FAIL | PASS | the transfer PASS gets its own S0-C before anything else |

**Q7 — portfolio.** Leave-one-leg-out and per-symbol de-concentration (`RQ-20261010-419b-04`) wait on `PERF-FU-LEG-REPLAY`. When it lands, the rule reads **net R per capital-day of the book**, capital-weighted, not total R.

## 5. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-21) | **runnable now (11):** `470a-01` (confirm f0e2-05), `470a-10` (confirm f0e2-10), `470a-02/03` (A22 transfer), `470a-04/05` (pullback depth), `470a-06/07` (xrp_4h at power), `470a-08/09` (eth_4h cooldown, min_confidence), `470a-11` (census). Read `RQ-20261010-419b-01..04` as they land | `PAIRS-R-SCALE` (Tier-1 harness fix) | f0e2-05: CONFIRMED or not. Census baseline is in the brief |
| **W2** (to 10-28) | S0-C units for every W1 sweep PASS. Q3 unit for the three alpaca_live 1d legs on ≥ 10 years. `470a-12` once `PAIRS-R-SCALE` lands. Second census run | Proposal draft for any CONFIRMED real-money lever (no flip) | first Tier-3 proposal with two records, or "no lever confirmed" |
| **W3** (to 11-04) | Q2 on `trend_donchian_xrp_4h`'s remaining axes (`min_confidence`, side, `skip_hours`) if 06/07 read. Prop legs' fold inconsistency (2/4 on both): P5 picks the sizing half, P3 the entry half. Transfer of any CONFIRMED lever to the prop twins | `PERF-FU-LEG-REPLAY` (lane owned elsewhere) unblocks Q7 | M22 roster from the honest pairs record |
| **W4** (to 11-11) | Q7 leave-one-out on the replay. Census re-read: did any change move a leg's grade? (population: that leg's record after the change) | — | W5+ re-cut from the measured census |

### 5a. Machine tree, the W1 read and the audit revision (lane P3-STRATEGY-BACKLOG-1016, 2026-10-16)

The questions above are encoded in [`research/programmes/03-strategy-improvement.yaml`](../../../research/programmes/03-strategy-improvement.yaml), so `queue_replenish.py --authoring-queue` sees them.

- **W1 verdicts (closed, from `research/results/`):**
  - All entry sweeps on the real-money legs FAILED, or passed on one window and then failed confirmation.
  - **All four single-window best-of-3 PASSes failed their S0-C confirmation:** f0e2-05 → 470a-01, f0e2-10 → 470a-10, 470a-05 → RQ-20261015-4941-01, 470a-09 → RQ-20261015-4941-02.
  - Rule § 2.3 therefore changes for new work. **A new entry sweep registers its confirmation inside the unit:** 8 calendar folds over about 6 years, and a candidate must win at least 7 of 8 (the f01d style). It does not get a single-window lead followed by a separate S0-C unit. Audit: `docs/research/programmes/reviews/2026-10-16/03-STRATEGY.md` § 4.1.
  - f01d-02 (eth_prop, 8 folds) read INDETERMINATE / `control_failed`. That was ONE warm-up-boundary trade; all 163 record trades reproduced exactly. Build row `ABLATION-CONTROL-WARMUP`.
- **Runnable now: 22 units, `RQ-20261016-c56e-05..26`.**
  - **Q2, multi-fold, real money (05–09):** `ada_pullback_2h` (cooldown, `trend_lookback`), `trend_donchian_eth_4h` (`donchian`, side) and `trend_donchian_xrp_4h` (`min_confidence`).
  - **L-LADDER re-validation (10–13):** the four bybit_2 legs at Stage 0 on the disjoint window before their records.
  - **f01d-02 re-ask (14):** five years before the record, so no control is needed.
  - **Breadth (15):** `trend_donchian_sol_4h` on 2020–2023.
  - **Q3 power (16–26):** every alpaca 1d leg with a record, on about 15–18.5 years of Yahoo daily bars. GLD stands in as the power proxy for `iaum_pullback_1d`, which has identical params.
- **Withdrawn before merge (01–04):** the four `xrp_pullback_2h` single-window entry sweeps. The audit asks the operator to mark that leg's entry axes exhausted and route it to P1 exits.
- **Builds filed:**
  - `LIVE-BT-STAGE-B`: the xrp/ada live-below-backtest cause, and the mirror-vs-live close-count gap.
  - `GRADER-FAIL-WORDING`.
  - `P3-QUEUE-HYGIENE`: 10 duplicates and 12 generated units on legs with no roster, re-verified.

## 6. What this plan does not do

- It changes no config, roster, account or risk setting.
- It does not re-open the entry-time bracket ladder (answered `honest_negative` ×6 on 2026-08-10) or exit levers. Exit levers are P1's (M20/M31).
- It does not treat a paper or mirror book as evidence of edge.
- It does not quote a P&L figure from the four pairs PASSes.
- Stage-0 figures come from committed records whose windows differ. They are compared by sign and grade, never by level, until one window is re-run for all legs.

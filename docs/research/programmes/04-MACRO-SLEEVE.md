# Programme 04 — Macro sleeve: conviction axes that earn net return

> **Doc status:** `live` · category `evidence` · last verified `2026-10-14` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `P4-MACRO-PROGRAMME` (manager dispatch, weekly planning 2026-10-14) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) row P4 · roadmap `M28` + `M29` · skill [`.claude/skills/macro-research/SKILL.md`](../../../.claude/skills/macro-research/SKILL.md) · **Tier-1 document: it proposes tests; every config, sleeve or order-path change it leads to is Tier-3 with an evidence record.**

**Standing (operator):** the news layer and WEPE are **not retired** (NEWS-ALPHA-PROGRAM directive 2026-10-12; WEPE-BUILDOUT 2026-10-08). The research queue is fed only from programme plans; this is P4's.

## Programme review 2026-10-28 (lane PROGRAMME-REVIEW-20261028) — TRADING track

Population: research units with a result row generated 2026-10-21T19:30Z..2026-10-28T19:30Z (`research_ops_checks.py --kind programme_review --since 7d`, 1,480 units read, 0 unreadable): **445 units, 412 graded** (70 pass, 50 indeterminate, 292 fail), 285 with a programme field and 160 without (live_strategy 70, regime 27, ml_health 21, macro 20, infra 13, new_strategy_prop 8, none 1). This review assigns the 160 by what they ask, not by the field (map section). Every PASS below is a discovery until its confirmation unit passes. **Cost basis:** about 36 of the 70 PASS rows are crypto-harness runs charged 7.5 bps round-trip (MEASURED from each result's argv); only RQ-20261028-001 carried the measured Bybit-linear 11.0 bps. A lever A/B delta is nearly fee-neutral (both arms pay it); an absolute Stage-0 or breadth PASS is not.

**Graded in the window: 14 with `programme: P4`** (2 pass, 11 fail, 1 indeterminate), plus 20 unprogrammed `macro` units (1 pass, 19 fail), the calendar-event-type studies `4795`, `ed1c-20..26` and `RQ-20261026-901`, which this review assigns to P4.

**What was learned**
- **PPI m/m surprise -> equity-index drift is the one macro surprise that keeps surviving.** It held on ES=F over the full sample (`a1f3-17`, IC −0.287, t −3.52, n 140), in the later sub-period alone (`RQ-20261025-002`) and on SPY (`4795-01`). The pre-release placebo is null (`RQ-20261025-003` FAIL, as intended). It is weaker on RTY: the later sub-period FAILED (`RQ-20261020-002`) and the earlier one is INDETERMINATE. About 34 macro tests graded this week and 3 passed, all of them PPI on ES/SPY. That was last week's a-priori lead, so this is not a best-of-34 pick. The one same-question FAIL (`ed1c-21`, PPI in the NEWS-ALPHA zero-weight study) uses a different design; its rule should be read before anyone cites a contradiction.
- **Every other surprise family closed at its tested configuration:** retail sales, ISM manufacturing and services, JOLTS, UMich, durable goods, ADP, housing, regional Fed, industrial production, unemployment, claims (forward), and CPI to gold or TLT. Configurations are closed, not families (PLANNING § 1).
- It is still sub-cost as a standalone trade (`4a4c-06`, 2026-10-21). The useful form is a **tilt on a leg that already holds the index**, and one now exists: `spy_trend_long_1d` and `qqq_trend_long_1d` are rostered (`config/strategies.yaml`, read 2026-10-28).

**Next 3-4 weeks**

| # | node | decision | on PASS | on FAIL | cost | pre-mortem |
|---|---|---|---|---|---|---|
| 1 | `P4-Q2-ppi-rty-econ` (ready; re-point to SPY/QQQ, research-ops authors) | does the PPI surprise pay as an exposure-matched tilt on an existing long-index leg | Tier-3 packet: a release-day hold/skip rule on the 1d SPY/QQQ legs | PPI stays a monitor, not a lever | needs `MACRO-EVENT-RANKTILT` (lever row) | about 12 releases a year is too few at any n; first variant pools ES, SPY and QQQ |
| 2 | `P4-Q4-g2-rerun` | PM-implied vs consensus surprise | — | — | not before 2026-11-07 | — |

**Feeds.** P4 -> P3: a PPI tilt on the 1d equity trend legs (the soak book's healthiest evidence), which is the first concrete P4->P3 feed. No other macro unit is worth authoring this month: macro graded 34 units this week against a theme share of 2, so supply is ahead of value.

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

Population: units whose `grading.graded_at` is 2026-10-14..2026-10-21 and whose file names this programme (`programme:` or `programme_node.programme`), read from `research/queue/*.yaml` on main at 2026-10-21 ~18Z. Units with no programme field (486 of the 657 graded in the window) are counted in the research map, not here.

**Graded in the window: 20** — 7 pass, 13 fail.

**What was learned**
- The PPI m/m surprise -> equity-index drift holds: ES=F in BOTH sub-periods (RQ-20261014-4a4c-01/-02), the pre-release placebo
  is null on ES and NQ (-03, 7769-01 FAIL as intended), and it extends to NQ=F (-04) and RTY=F (7769-02). It does NOT extend to
  ZN=F (-05) or GC=F (7769-03).
- **As a trade it fails net of cost**: the PPI-surprise sign book on ES (enter release-day close, hold 3 days) FAILED
  (RQ-20261014-4a4c-06). The drift is real and too small to pay the cost stack on its own.
- The other inflation surprises do not move ES forward returns: core CPI, core PCE, AHE, ISM prices paid, import prices, GDP
  price index all FAILED (4a4c-07/-08, 7769-04..-07); CPI -> ZN forward also FAILED (7769-08).
- Positive controls PASS (NFP, CPI, claims move ZN on the release day: 1fa6-01..-03), so the instrument can see an effect when
  there is one. The expansion-regime sign flip for claims (1fa6-04) FAILED.

**Answered / unlocked / retired**
- Answered: P4-Q2's PPI line is a real but sub-cost effect; the inflation-surprise family beyond PPI is closed for ES forward
  returns on this history. P4-Q4 (G2 PM-implied surprise) stays n-bound: not before 2026-11-07 (node P4-Q4-g2-rerun).

**Next 3–4 weeks**
- 14 P4 units are queued (macro theme runnable 6+3 against a share of 2 — supply exceeds weight). No new macro unit authored.
- The open question worth asking next is a COMBINATION, not a new surprise: PPI surprise as a sizing/direction tilt on an
  existing ES/NQ position leg (where it pays no extra entry cost). File as a P4 node when an ES/NQ leg exists to tilt.

**Cross-programme feeds**
- → P3: none until an index-future leg is on a roster.

## 1. End goal and measure

**Goal.** A thesis-driven, weeks-horizon macro sleeve whose **conviction axes** each add net return through defined-risk instruments (debit verticals on `alpaca_options_paper`, `config/macro_theses.yaml::sleeve`), with every axis earning its place offline, against the naive floor, before it shapes a thesis.

**Measure (headline).** **Net return per conviction axis vs the naive floor** (all-long on the same dates at the same cost), offline first; the live read is `alpaca_options_paper` net R per axis once an axis trades. **Supporting:** event-surprise hit rate (sign agreement of surprise and post-release drift, per kind).

| measure | population | instrument | baseline (MEASURED 2026-10-14 unless marked) |
|---|---|---|---|
| valuation axis, zero cost | 1,104 thesis entries, 263 rebalance dates, GLD/IEF/SLV/SPY/TLT, 2005–2026, 30 d horizon | `comms/macro/thesis_p4_scorecard.json` (macro-valuation-backfill.yml) | calibration_rank −0.0037, edge_vs_baseline −0.0047 (MACRO-RESHAPE note; zero cost, i.e. the most favourable case) |
| valuation axis, realistic cost | same | `RQ-20260928-010` | **not measured** — blocked (§ 3, Q1) |
| event-surprise drift, per kind | resolved releases with a PIT survey consensus, 2015–2026, joined to daily closes | `scripts/research/macro_event_study_run.py` | **1 of 13** kinds PASS (ppi_mom → ES=F, n=139, h3 IC −0.281, t_eff −3.43); 12 FAIL (§ 2, Q2) |
| PM surprise vs consensus surprise | releases with a usable Kalshi ladder AND a consensus | `RQ-20261009-903` | FAIL at paired n=68 (h3 diff +0.054, CI spans 0) |
| live: `alpaca_options_paper` net R per axis | macro-thesis trades | `/api/bot/performance` | **no rows by construction**: the sleeve is `execution: shadow` with no options executor (P5 not wired, `thesis_tick.py`), and the account's roster today is three technical legs (`slv_trend_1h`, `slv_pullback_1d`, `gdx_pullback_1d`, read from `config/accounts.yaml`). The live measure starts only after Q7. |

Bars every rung uses: point-in-time consensus only (invariant 2); the full cost stack (`profile_loader.roundtrip_fee_bps_for` + `execution_costs.resolve_cost_policy`, or the sleeve's labelled debit-vertical proxy); beat the naive floor, not just a correlation bar (invariant 5); say what bounds n before waiting on accrual (invariant 4).

## 2. Questions, in dependency order

```
Q1 valuation axis at a real cost ─────────────┐ (closes the event-blind evidence honestly)
Q2 which release surprises carry a drift ──▶ Q3 event-scored conviction axis ──▶ Q6 M29 wake read ──▶ Q7 executor + soak
     (PPI lead → confirmation set)              (= MACRO-RESHAPE wire-and-rescore, offline half)
Q4 PM surprise / WEPE ledger ─────────────────▶ Q3 as a second input (WEPE G4) only after G2 passes + operator
Q5 news: veto + standalone edge (NEWS-ALPHA) ─▶ Q3 as an axis candidate on a PASS readout
```

| Q | question | why now | existing units (do not duplicate) |
|---|---|---|---|
| **Q1** | What does the valuation axis earn at a cost the sleeve would actually pay? | The only committed P4 evidence is zero-cost; PI-CAA05-0003 cannot close on it | `RQ-20260928-010` (re-scoped this lane, blocked on `MACRO-BACKFILL-E5`); `RQ-20260929-001` done, NOT_YET (band restriction does not clear the naive baseline) |
| **Q2** | Which scheduled-release surprises carry a **post-release** drift (entry at the release-day close) that survives a sub-period split, a placebo, a second instrument and the cost stack? | 13 kinds landed 2026-10-13/14; one PASS (ppi_mom). 1 of 39 tests at t −3.43 (two-sided p ≈ 0.0006) is under the BH rank-1 threshold 0.05/39 ≈ 0.0013, so it survives the family read — but it is one sample | landed: `RQ-20261013-1414-10/11/12`, `RQ-20261014-65cc-01..05`, `RQ-20261014-de02-02..06`; **new** `RQ-20261014-4a4c-01..08` |
| **Q3** | Does a confirmed drift make an M28 **conviction axis** on the sleeve's universe at the sleeve's cost, walk-forward, vs valuation-only and the floor? | Operator 2026-10-09: M28 "Keep exploring", commission a NEW axis; MACRO-RESHAPE's wire-and-rescore | `RQ-20260928-009` (event-wired rescore, blocked: no events input in the replay); **new** `blocked/RQ-20261014-4a4c-09` |
| **Q4** | Does a prediction-market-implied surprise beat the consensus surprise (WEPE G2), and is the history ledger a usable instrument (G3)? | G2 read FAIL at n=68; G3 instrument PASS (`RQ-20261012-904`: 830 questions, 82 market-matched, leakage clean) | `RQ-20261009-903` (FAIL), `RQ-20261012-904` (PASS) — no rerun until the paired n can move (PM-COLLECTOR accrual; quality read due 2026-11-07) |
| **Q5** | Does news carry edge — as the live veto (narrow, G1 FAIL) and standalone (returns/vol/volume, any asset)? | Operator 2026-10-12: far from a retire decision | `RQ-20261012-5bd1-01..14` (blocked on NEWS-ALPHA-HARNESS/-FEATURES/-CORPUS); readout due 2026-11-09 (row NEWS-ALPHA-PROGRAM) |
| **Q6** | Should M29 (system-dynamics) wake? | Operator 2026-09-28: dormant until an M28 axis reads out | no units by design; the read is Q3's record |
| **Q7** | Can the sleeve express a passed axis as debit verticals (mechanics, cost fidelity) on `alpaca_options_paper`? | Gate 1 → Stage 1; nothing passes Gate 1 today | none; the P5 executor is unbuilt; Tier-3 |

## 3. Test ladders — cheap and decisive first

### Q1 — valuation axis at a real cost
1. **Realistic-cost rescore** (`RQ-20260928-010`, rule registered 2026-09-28, unchanged). Cost decided this lane as a **labelled conservative proxy**: fee_frac 0.005 round trip, carry 0.0 (the harness models linear exposure, so a vertical's theta cannot honestly be charged as linear carry). Expected `KILLED_HONESTLY` → PI-CAA05-0003 closes `killed` with the number. **Blocked** because `macro-valuation-backfill.yml` takes no `research_unit` input and lands no E5 record, which `research_queue.grade_power` requires of an accruing unit (graded 2026-10-14). Build `MACRO-BACKFILL-E5` (Tier-1 CI) clears it.
2. **Measured options cost**: Alpaca's options fee schedule and PIT chain spreads for the 5 symbols, replacing the proxy (UNVERIFIED this session: no egress). Only matters if rung 1 or Q3 is not a clear kill.

### Q2 — release-surprise drift (`RQ-20261014-4a4c-01..08`, all runnable now on `research-script-run.yml`)
The parent: `RQ-20261014-de02-04` ppi_mom → ES=F, n=139, h1/h3/h5 IC −0.183/−0.281/−0.247 (t_eff −2.17/−3.43/−2.98). Base bar = the release-day close (`econ_event_study.make_forward_return`), so this is a drift tradeable after the print, not the intraday reaction.
1. **Stability** — `-01` (releases ≥ 2021-01-01, n≈68) and `-02` (< 2021, n≈71), negative IC with |t_eff| ≥ 2.0 at h3 or h5. Both PASS = stable; one = regime-concentrated (the axis carries a regime condition or is retired); neither = pooled artifact. Each half is underpowered at the observed effect (needs ~93), stated in the unit.
2. **Placebo** — `-03`: base bar moved −10 trading days so the window ends before the print. PASS here **kills** the parent.
3. **Second instrument / mechanism** — `-04` NQ=F, `-05` ZN=F (rates channel), |t_eff| ≥ 2.4.
4. **Net of cost vs the floor** — `-06`: sign book on ES (short on a hot print), 3-day hold, MES cost stack (7.5 bps fee default + 5.0 bps slippage = 12.5 bps round trip, recorded in the result), PASS iff mean net > 0 with t ≥ 2.0 **and** above the all-long book on the same windows. This is the first rung in the programme's own unit.
5. **Family breadth** — `-07` core_cpi_mom, `-08` core_pce_mom → ES=F (|t_eff| ≥ 2.4). The P4 event family is then 15 kinds × 3 horizons = 45 tests, read with BH; a new PASS starts its own rungs 1–4, it does not inherit the PPI confirmation.
6. **Expensive rung (W3+):** intraday reaction vs drift (needs intraday bars at release time; not built) — only if rungs 1–4 hold.

The three new arms (`--release-start/--release-end`, `--anchor-shift-td`, `--trade-horizon/--cost-symbol`) were added to `macro_event_study_run.py` by this lane with tests (`tests/test_macro_event_study_run.py`); every existing unit is unchanged (all default off).

### Q3 — event-scored conviction axis (`blocked/RQ-20261014-4a4c-09`)
Runs only if `-06` PASS, `-03` FAIL and at least one of `-01/-02` PASS; otherwise **retired** with that reason. Lever `MACRO-EVENT-AXIS-HARNESS` (Tier-1): an offline replay forming theses per (release, symbol) on GLD/IEF/SLV/SPY/TLT from the registered sign mapping, through `thesis_backtest.net_return` at the Q1 cost proxy, beside the valuation-only axis. Rule: pooled paired difference vs both comparators > 0 with the interval above 0 and ≥ 4 of 6 folds → Tier-3 proposal to add a `c_macro` input. This is the offline half of `RQ-20260928-009` / PI-CAA05-0002; it does not touch `thesis_tick.py`.

### Q4 — PM surprise / WEPE
1. G2 is FAIL at n=68 paired and the floor is 49, so it was a powered FAIL on the narrow question (IC vs consensus IC). **No rerun until** the collector's 2026-11-07 quality read and a paired n that can move the interval.
2. G3 (history ledger) PASSED as an instrument. G4 (forecasts as a sleeve feature, walk-forward) is **operator-gated** and needs its own unit; this programme does not author it before G2 passes.

### Q5 — news
Owned by NEWS-ALPHA-PROGRAM (14 pre-registered units, 600-test budget, sealed holdout). This programme only consumes its readout: a unit that PASSES on a macro-relevant target becomes a Q3 axis candidate with its own rung-1..4 set.

### Q6 / Q7
M29 wake is decided on Q3's record: PASS → one scoping unit asks whether the gas system-dynamics mispricing adds an NG axis; FAIL → M29 stays dormant with the record as the reason. Q7 is Tier-3 and starts only after a Q3 PASS: the P5 debit-vertical executor, then a Stage-1 soak on `alpaca_options_paper` for mechanics and cost fidelity (never edge).

## 4. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-21) | `RQ-20261014-4a4c-01..08` fire and land; grade each against its rule; record dispositions | `MACRO-BACKFILL-E5` (research_unit input + E5 landing on macro-valuation-backfill.yml) | PPI lead: confirmed, regime-conditioned, or killed |
| **W2** (to 10-28) | `RQ-20260928-010` once unblocked; `RQ-20261014-4a4c-09` if the confirmation clause holds; any new Q2 PASS gets its rung-1..4 set | `MACRO-EVENT-AXIS-HARNESS` if the clause holds | Q1 closes PI-CAA05-0003; Q3 run or retired |
| **W3** (to 11-04) | Q3 read-out; measured options cost (Q1 rung 2) if Q1/Q3 are not clear kills | — | M29 wake read (Q6) |
| **W4** (to 11-11) | NEWS-ALPHA first readout (due 11-09) read for axis candidates; PM collector quality read (11-07) | — | first Tier-3 axis proposal, or an honest "no axis passed"; W5+ re-cut from the measured state |

**What this plan does not do.** It changes no config, sleeve setting, roster or account; the sleeve stays `execution: shadow`. It does not wire `thesis_tick.py` events in production (PI-CAA05-0002's production half stays its own row). It does not treat `alpaca_options_paper` as evidence of edge. It does not lower a pre-registered bar: the realistic-cost unit's rule is byte-identical to its 2026-09-28 registration, and the 0.005 cost figure is a labelled proxy, not a measurement. Numbers marked MEASURED were read this session from the files and results named.

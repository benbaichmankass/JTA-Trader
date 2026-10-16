# Idea-family review: what was closed, and was it tested right? (2026-10-16)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane **IDEA-REVIEW-1016** (dispatched by the manager, operator directive 2026-10-16). Operator's gist:
*"We need to not be giving up on ideas because of one test that went bad… If an idea is viable, there
should be information that helps us understand how to do it better or what we might be doing wrong. If
there's no information, it's probably really not a viable idea."*

**Population.** Every research unit with a `fail` or `indeterminate` result landed under
`research/results/` from 2026-09-22 to 2026-10-16. That is 281 records. The near-identical generated
prop-fit and m20 sweeps were collapsed into their families, leaving the 17 family rows below. Each family was read
against its own records, meaning the unit YAML, the result row and `comms/research/<id>/verdict.json`,
and against outside evidence (papers, practitioner write-ups, market-structure facts). The outside
search was done this session by four read-only research agents and re-checked here where a claim
drove a unit.

Paper claims come from abstracts and bibliographic pages; the full texts were **not** read. Each
source is marked *primary* (the paper or model card) or *secondary* (a blog or summary).

**Verdicts:**
- **A (viable, tested wrong):** the outside evidence says the idea works under a condition we did
  not test. This gets a pre-registered re-test.
- **B (viable, not yet testable):** testing it needs data or a harness we do not have. This gets a
  checklist row with its first step.
- **C (no supporting evidence):** retire the idea, with the sources checked as the denominator.

## The table

| # | family (what we closed) | verdict | what our test did NOT test | key outside source(s) | filed |
|---|---|---|---|---|---|
| 1 | Macro survey-surprise event studies (13/14 FAIL; PPI lead lost to all-long) | **A** (+B intraday rung) | **The window.** Every unit's base bar was the release-day close, and every kind prints 12:30–19:00 UTC, so the announcement reaction sat *inside* the base bar. All 14 measured only the post-release drift that efficient-market evidence expects to be zero. Also untested: state conditioning, bonds as the primary instrument, a positive control. Found here: 69 of 140 PPI windows have CPI or FOMC within 5 days, so the PPI drift and the all-long floor are confounded with other announcements. | Balduzzi-Elton-Green 2001 (bond adjustment within ~1 min) [primary]; Andersen-Bollerslev-Diebold-Vega 2003 [primary]; Boyd-Hu-Jagannathan 2005 (sign flips with the business cycle) [primary] | units **1fa6-01..04** (release-day window; 01–03 are positive controls on ZN=F; 04 tests state dependence); rows **IR-MACRO-INTRADAY-EVENT-STUDY**, **IR-MACRO-ANNDAY-POOLED** + blocked **1fa6-10** |
| 2 | Announcement-day premium (never tested) | **A** | Never registered. Searched queue, docs, scripts, comms and skills for savor / announcement-day / pre-FOMC: only caveats. | Savor-Wilson 2013 (11.4 vs 1.1 bps) [primary]. Pre-FOMC drift (Lucca-Moench 2015) is excluded as a target: Kurov-Wolfe-Gilbert 2021 show it disappeared after 2015 [primary]. | blocked **1fa6-10** on **IR-MACRO-ANNDAY-POOLED** |
| 3 | M28 valuation read (calibration negative even at zero cost) | **A narrow** / **C** for 7–180 d timing | **Field finding:** `config/macro_valuation.yaml:27` declares TLT/IEF `higher_is_cheaper: false` ("high real yield ⇒ duration RICH"). For a bond, high yield *is* cheap, so the cheap score looks inverted, and pooling it with GLD/SLV can cancel a real effect. Also untested: per-symbol cuts, horizons ≥ 1 y, and cross-sectional value. | Asness-Moskowitz-Pedersen 2013 (value works cross-sectionally in bonds) [primary]; Campbell-Shiller 1998 (~10 y horizon) [primary]; Goyal-Welch 2008 (short-horizon OOS failure) [primary]; Asness et al. 2017 (value timing hard) [secondary page] | blocked **1fa6-09** on **IR-MACRO-VALUE-ORIENT**. Any orientation change is Tier-3. |
| 4 | Single-axis entry-parameter sweeps (all 4 single-window PASSes failed confirmation) | **A** | The design picked the best of 3 sparse points on **one** window, then confirmed it: a winner's curse by construction. About 11 in-sample PASSes came from about 40 selection units with no multiplicity correction. Neighbouring arms disagreed (470a-05: 0.382 +3.3 R, 0.618 +11.8 R, 0.75 +5.7 R). No plateau was ever required. | Bailey/Borwein/López de Prado/Zhu 2017 (PBO) [primary]; White 2000 [primary]; Hansen 2005 SPA [secondary summary]; Harvey-Liu 2015 [primary] | unit **1fa6-05** (dense-grid PLATEAU on ada_pullback_2h, 6 years); row **IR-SWEEP-PLATEAU-PBO-GRADER**. P3's c56e units already moved the other axes to 8-fold long windows. |
| 5 | Meta-labeling on thin entry columns (9d20-02, M19 S1 0928-002/003, 0930-601) | **B** (+A label) | Thin features: adx_at_entry was null on ~96% of rows. 4 folds give CIs of ±0.3 AUC. AUC > 0.5 together with a **negative** veto R is the signature of an unweighted win/loss label on a right-skewed payoff (it vetoes the rare large winners). Untested: an \|R\|-weighted or continuous label, and calibrated sizing. | Joubert 2022 JFDS (theory) [primary, content unverified]; Meyer-Barziy-Joubert 2023 JFDS (value is in calibrated sizing) [primary, abstract second-hand] | existing row **METALABEL-EMIT-FEATURES** (build PR #18536 open). When the blocked unit RQ-20261014-9d20-04 re-registers, it should add an \|R\|-weighted label scored on R lift, not AUC. |
| 6 | Entry-time giveback prediction (9d20-03) | **B** | We asked an in-trade question with entry-time columns. The prize is real: the 9d20-01 census PASSED (~0.93 R/trade oracle headroom on ict_scalp). | Kaminski-Lo 2014 [primary]; Lo-Remorov 2017 [primary]. Both say exit value depends on path / serial correlation. | existing row **EXIT-PATH-EMIT-OFFLINE** (build PR #18536) |
| 7 | In-trade exit state rungs (d6e7-02 FAIL, -04 indeterminate); exit heads | **A + B** | The money rung was gated behind a 0.002-nat proxy and **never ran**, even though d6e7-04 was positive in 4/4 folds with calibration slope 1.03. The exit heads were positive *gross* on ict_scalp 15m but negative net, because a truncation pays a round trip that is large relative to 1 R there. Never tested on 2h/4h legs, where that cost is small relative to 1 R. | Kaminski-Lo 2014; Lo-Remorov 2017 (exits lose to cost when tight) [primary] | unit **1fa6-06** (HTF legs, K = 3 R). P1's RQ-20261016-013 runs the pooled K = 2 money rung. **EXIT-PATH-EMIT-OFFLINE** covers the native-trail rung. |
| 8 | Fixed finite TPs on trend legs (eth_4h cab7-04; SOL prop 6→2 R) | **A** | We tested a *fixed* cap derived in-sample. It failed on calibration because the move ran further OOS (reach 0.34 IS vs 0.42 OOS). The doctrine's revisable / extend-only target is untested on eth_4h: RQ-20261007-080 was producer_failed and has been re-queued, and the 9807-03 m20 rows cannot be graded against a tp-calibration rule (RESEARCH-GRADE-PILE). | Hurst-Ooi-Pedersen (century of trend) [primary]; Potters-Bouchaud 2005 (trend P&L is right-skewed) [primary]. No source tests fixed targets directly (searched): this is inferred from the tail concentration. | no new unit. P1 (RQ-20261016-004/007/008/009) and RQ-20261007-080 own it. Flagged to the manager: the m20 tp-grade gap blocks every revisable-TP verdict. |
| 9 | Direction labels on price-only inputs | **B** (+1 hygiene A) | 5-bar sign label, no dead-band, 6 price columns; every learner loses to the prior on log-loss. **The macro-F1 "lift" over the prior in 1414-03 / 65cc-07 is a metric artifact:** the majority-class prior scores ~0.22 macro-F1 on 3 classes and a coin flip ~0.33, and the learner folds sat at 0.32–0.34. | Liu-Tsyvinski-Wu 2022 JF [primary]; Fieberg et al. 2025 JFQA (CTREND) [primary]; Kim-Hansen arXiv 2607.09426, order imbalance predicts 4–12 h (preprint) [primary, unreviewed] | row **IR-DIRECTION-LABEL-V2**. Cross-section stays on **FRONTIER-LEVER-XSEC-RUNNER**. Rule for all future direction units: grade on log-loss vs the prior (or vs a stratified baseline), never macro-F1 vs the prior. |
| 10 | HGB / ExtraTrees / MLP / CatBoost / TabPFN / logit vs LightGBM | **A** (fair answer to the wrong question) | Every arm swapped the *learner* on the same weak 6-column input; ties are the predicted outcome. The logit was misspecified (raw vol; hour and day-of-week as linear numbers). CatBoost, TabICL and TabPFN were `unavailable` (not installed) in most runs, which is not evidence. | Grinsztajn et al. 2022 [primary]; McElfresh et al. 2023 [primary]; Hollmann et al. 2025 Nature (TabPFN ≤10k rows) [primary]; Gu-Kelly-Xiu 2020 [primary] | unit **1fa6-08** (logit + HAR-RV vs LightGBM on log-loss: a tie closes the family lever for this target) |
| 11 | Regime vol-axis gating (hot/cold skips) and trend-axis gating | **A** | We tested **gating** (binary skip) many times. Trend earns *in* high vol ("crisis alpha"), so hot-tail skips cut its payoff. **Continuous vol-target sizing per leg under the current cost stack was never tested.** The only result (P1 book-level, 2026-06-26, +0.10–0.20 dSharpe) predates the cost stack and was never pre-registered. Exception worth noting: trend-axis headroom PASSED on the ict_scalp family (75b2-05). | Hurst-Ooi-Pedersen [primary]; Kim-Tse-Wald 2016 (TSMOM alpha is mostly vol scaling) [primary listing]; Cederburg et al. 2020 (vol management fails OOS broadly, except momentum) [primary]; Corsi 2009 [primary] | row **IR-VOL-TARGET-SIZING-STAGE0**; existing **REGIME-WEIGHT-VARIANTS**. **Note for the manager:** P2's held 65ff-06..19 are more vol/session/ADX *skips*, the design the literature predicts fails on trend legs. |
| 12 | Pairs (R-scale defect; SLV/GLD, TLT/IEF, XRP/ADA FAIL) | **A** (+B maker) | The defect voids only the **rolling-beta** M22 PASSes (RQ-20261007-005..009). The three new pairs ran fixed-beta defaults (lookback 20, taker) and lost on cost. The 2026-07-16 dollar ledger shows gross edge on SOL/ETH and BNB/BTC, net-negative on taker fees. Untested: formation-period selection, longer lookbacks, maker entries on both legs, intraday frequency, folds. | Gatev-Goetzmann-Rouwenhorst 2006 / Do-Faff 2010, 2012 (decaying but positive; cost-sensitive) [primary]; Fil-Kristoufek 2020 (crypto pairs: daily ≈ −0.07%/mo, 5m +11.6%/mo, cost-sensitive) [primary, abstract]; Leung-Nguyen 2019 [primary] | row **IR-PAIRS-RERUN-HARNESS** (verdict wrapper + 2-leg limit fill, then the XRP/ADA formation/fold unit). **PAIRS-R-SCALE** stays the gate for 470a-12. |
| 13 | ict_scalp (5m/15m) and "any profitable ≤1h crypto strategy" | **C** for the ICT concepts; **A** for one execution condition | The original edge was lookahead: +62.8 R before #15341, −3.26 R after. **The maker-entry test (502) and the ≤1h discovery sweep (504) both ran on the pre-fix harness**, so those conclusions are void. Their market-entry deficit (~−0.003 R/trade) is smaller than 502's maker advantage (~+0.023 R/trade), so the causal maker sign is open. | ICT concepts: searched for independent tests of FVG / order blocks / liquidity sweeps and found only vendor pages (e.g. tradezella.com) — **no peer-reviewed or independent evidence**. Documented intraday effects are other mechanisms: Shen-Urquhart-Wang intraday TSMOM [primary]; Quantpedia BTC 21–23 UTC [secondary]. | unit **1fa6-07** (502 re-run on the causal harness); row **IR-INTRADAY-SEASONALITY-HARNESS** for the documented clock effects |
| 14 | xrp/ada_pullback_2h underperforming live vs backtest | **A** (wrong reference; mechanics not investigated) | The bootstrap draws from 365-day evidence records (+0.13 / +0.34 R/trade, `param_selection_provenance: not_established`). The config-exact 1830 d replay is **−15.27 R / 297** (xrp) and **−7.36 R / 274** (ada). Live n is only 15–16, with 62.5% measured P&L (xrp). The fill/slippage/funding diff (PI-20261015-10152047-0001) has not run. | internal (the reference window and its selection) | row **IR-LVB-FULL-HISTORY-REF**. P3's c56e-10/11 re-validate both legs at power on the disjoint window. |
| 15 | Tradeify non-crypto prop fits | **B** | Priced on **regular-hours ETF candles** (yfinance SLV/SPY/QQQ/USO 1h, about 7 bars a day with overnight gaps), but the instruments are ~23 h CFDs. USO carries roll drag. The daily trend legs neither breach nor pass inside the evaluation window (EV is exactly −fee on every seed), which is a cadence mismatch, not evidence against trend. | Moskowitz-Ooi-Pedersen 2012 TSMOM (1–12 month horizons) [primary]; Hurst-Ooi-Pedersen [primary] | row **IR-TRADEIFY-NATIVE-SERIES** (continuous-futures 1h series SI=F / CL=F / ES=F / NQ=F into the corpus, then re-run the 24ca units; costs are on the done row TRADEIFY-INSTR-SPECS) |
| 16 | Prop Stage-0 breadth screens (trend/pullback/squeeze × alts × 5m–4h) | **A** (coverage + design) / **C** for 5m–15m taker | Trend at 1h on 3 years passed **10/13 alts**. The screen had no folds and no multiplicity correction. BTC/ETH/SOL ran on 180-day windows only. **There are no crypto daily bars in the corpus**, and daily-to-weekly is where the literature puts crypto trend. 5m–15m at taker cost failed massively (−783 to −878 R): that is the cost wall, retired as a configuration class. | Liu-Tsyvinski 2021 RFS (1–4 week TSMOM) [primary; the 3.16% figure is from their VoxEU column, not re-verified]; Borgards 2021 [primary]; Zarattini-Pagani-Barbon 2025 [secondary] | row **IR-CRYPTO-DAILY-TREND** |
| 17 | News veto / prediction-market surprise | **B** | 611/634 rows neutral, and the offline replay produced **0** veto episodes, so the signal was never exercised. The prediction-market surprise unit (903) had n = 68 paired releases. | Economic Modelling 2023 (headline-negativity effect on BTC) [primary] | note on the existing row **NEWS-ALPHA-CORPUS** (persistent GKG with tone) |

## Retired (C), with the denominator

| retired | the reason the IDEA (not the cell) is dead | searched |
|---|---|---|
| ICT concepts (fair-value gaps, order blocks, liquidity sweeps) **as an edge source** | No independent or peer-reviewed test exists. Our own causal rebuild failed powered: all four 5m legs −22.7 to −37.1 R with 0/4 folds positive, and the 15m legs at 1/4–2/4 folds. Its only positive was lookahead. **One condition stays open** (maker entries, unit 1fa6-07). If 1fa6-07 FAILs, the 15m family retires completely. Live legs are not touched by this record; a roster change is the manager's/operator's. | Web search for FVG / order block / liquidity sweep backtests, academic and independent: vendor pages only (TradeZella, Backtrex, TradingView scripts) |
| Time-series valuation timing at 7–180 d (M28 as built) | The literature predicts a null at these horizons: valuation forecasts at ~10 y (Campbell-Shiller), fails OOS short-horizon (Goyal-Welch), and value timing is hard (Asness et al.). Our null matches. What stays open is the bond orientation (1fa6-09) and horizons ≥ 1 y / cross-sectional value (IR-MACRO-VALUE-ORIENT). | Campbell-Shiller 1998; Goyal-Welch 2008; Asness et al. 2017; Erb-Harvey 2013 (gold real price reverts too slowly to time) |
| Taker-cost 5m/15m trend/pullback/squeeze on alts | Cost wall: −783 to −878 R on 5m. The intraday crypto evidence that exists is cost-sensitive and different in mechanism. Retired as a **configuration class** (taker, default params, ≤15m), not as "short timeframes". | Fil-Kristoufek 2020; Quantpedia intraday seasonality |
| Pre-FOMC drift as a target | Not one of ours. Recorded so nobody authors it: it disappeared after 2015. | Kurov-Wolfe-Gilbert 2021; Lucca-Moench 2015 |

## Hygiene found while reading (one line each; routed to the manager, not fixed here)

- **FRONTIER-LEVER-HARNESS-COSTS** reads `queued`, but `resolve_cost_policy` is wired into both harnesses
  (6 and 5 hits) and `tests/test_frontier_lever_harness_costs.py` exists. That makes blocked
  RQ-20261011-9da8-05/-06 promotable. The row's own note already says so.
- **75b2-20, 75b2-21, 65cc-09** carry `fail` results while `status: queued` (agent read; not re-checked here).
  **9807-03** is `queued` with a `needs_review` grade.
- **CatBoost / TabICL / TabPFN** are `unavailable` on the runners. Every arm that used them is a missing
  package, not a negative result.

## Proposed NEGATIVE-RESULT PROTOCOL (for RESEARCH-ENGINE-1016 / PR #18557 to mechanise)

A FAIL closes the **configuration** it measured. Retiring a **family** requires a review record
carrying all six items below. A record missing any of them leaves the family `open` with a named next
test.

1. **Test-design review.** Name the design flaw a skeptic would raise first, and say why it does not
   apply. The checks:
   - **Window vs mechanism.** Did the measurement window contain the effect? Family 1 failed this.
   - **Metric vs baseline.** Can the baseline be beaten by chance? The macro-F1-vs-prior case in
     family 9 is the example.
   - **Label vs payoff.** An unweighted label on a skewed payoff: family 5.
   - **Gate vs size.** Family 11.
   - **Harness validity at the time of the run.** Lookahead or a known defect: families 12 and 13.
   - **Reference distribution honesty.** Family 14.
2. **Breadth.** The negative must hold across at least 3 configurations on the family's main axis, at
   least 2 disjoint windows or ≥ 4 folds, and at least 2 instruments where the idea is not
   instrument-specific. Each must carry its n and its power. An `indeterminate` counts toward
   nothing.
3. **A positive control.** Name the test that *should* pass on the same instrument, data and join, and
   show it passing, or say why none exists. Without one, a family of FAILs cannot be told apart from a
   broken instrument (RULE ONE: a negative needs a denominator).
4. **Outside-evidence check.** At least 3 sources, primary where possible, with what each says about
   the conditions under which the idea works. Where none is found, list the searches. If the outside
   evidence names a condition we did not test, the verdict is **A**, never C.
5. **Not-tested list.** Name the horizon, instrument, conditioning variable, cost assumption, label,
   sizing, exit, regime and holding period that were NOT covered. Each is either covered by a queued
   unit or a row, or explicitly declared irrelevant with a reason.
6. **A stated reason the IDEA is dead.** One sentence about the mechanism, not about the cell, for
   example "the edge was lookahead and no independent test of the concept exists". "Every cell we ran
   failed" is not a reason; it is item 2.

**Cheap mechanics:**
- A unit can carry `family:` and `retires_family: false`, defaulting to false.
- A checker can refuse `status: retired` on a family node, or a "the family is dead" note, unless a
  review record with these six headings is linked.
- research-ops § D can add one line per FAIL: "configuration closed; family stays open: next test = …".

---
*Related:* units `research/queue/RQ-20261016-1fa6-01..08.yaml` and `research/queue/blocked/RQ-20261016-1fa6-09/10.yaml`;
rows `docs/claude/work/checklist/IR-*.json` and `IDEA-REVIEW-1016.json`.

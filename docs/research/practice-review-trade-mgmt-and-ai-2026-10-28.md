# Practice review: how real trading firms manage open trades, use AI, and run research (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `PRACTICE-RESEARCH-TRADE-MGMT-AI` (Tier 1, research only: web and repo reading, no builds), dispatched by Manager
Session 2026-10-27a. Checklist row `PRACTICE-RESEARCH-TRADE-MGMT-AI` (roadmap `L-DESK`). It feeds lane
`DESK-LIFECYCLE-S0` (the full-trade factorial test) and lane `ML-PROGRAMME-PLAN` (the ML trade-management programme).

**The operator's ask (2026-10-28 ~06:40Z, paraphrased by the manager):** find out how real firms do active trade
management and use AI in the trading pipeline, and base our designs on what real-world practice and evidence teach
instead of on ad hoc choices. Also, from the ideas inbox: research how trading firms run their research operations.

**Why now (from the dispatch, not re-verified by this lane):** the desk tests so far were designed ad hoc. One was an
entry-only test with fixed brackets (no edge over random). The other was a single check-in at +1R per trade on 4 legs
(n=176), which did not beat holding. The operator rejected the +1R design. Active management means frequent
time-based check-ins plus event triggers (R milestones, a change in volatility, momentum, levels).

**How to read the evidence weights.** Every claim cites a source and tags it:
- **[ACAD]** peer-reviewed or a working paper with a stated data sample. Weighted highest.
- **[PRAC]** a named practitioner writing about their own process (a book, a blog, a firm's own publication). Medium weight. It describes what people *do*, which is not proof that it works.
- **[VEND]** a vendor, educator or marketing page, trade press, or a secondary summary. Lowest weight. Used only where nothing better was found, and labelled.

Where this lane read only an abstract or a secondary summary, not the full paper, the entry says so. Section numbers
in the sources list (§ 9) match the bracketed tags `[S#]` used in the text.

---

## 0. Executive summary: the 10 findings that matter most for our decisions

1. **Exits are where professionals are measurably worst, and the standard test is a random counterfactual.**
   Institutional portfolio managers show real skill when they *buy*, but their *sell* decisions underperform a
   random-selling strategy (Akepanidtaworn, Di Mascio, Imas & Schmidt, *Journal of Finance* 2023, 783 portfolios,
   2000–2016) [S1, ACAD]. A 15-trader US prop team realised winners much faster than losers, and that cost them money
   (Garvey & Murphy, *FAJ* 2004) [S2, ACAD]. CBOT prop traders took more risk in the afternoon after morning losses,
   and the prices they set reverted (Coval & Shumway, *JF* 2005) [S3, ACAD]. **For us:** the prior on discretionary
   in-trade intervention is that it *destroys* value until a test shows otherwise. Every management arm needs a
   *matched random-intervention* control: same number and type of actions, at random times. That is the control these
   papers use, and it is the one our +1R test lacked.

2. **Whether a stop or an active exit adds value depends on the return process, so it is a per-instrument, per-regime
   question.** Under a random walk, a stop-loss rule always lowers expected return. With momentum (positive serial
   correlation) or regime switching, it can add value (Kaminski & Lo, *J. Financial Markets* 2014) [S4, ACAD]. Tight
   stops on US stocks lose to buy-and-hold *after trading costs*. Wide stops help only in specific regime structures
   (Lo & Remorov, *JFM* 2017, US stocks 1964–2014) [S5, ACAD]. A 10% stop on equity momentum cut the worst monthly loss
   from −49.8% to −11.3% *gross of costs* (Han, Zhou & Zhu, 1926–2011) [S6, ACAD; secondary summaries]. **For us:**
   management lift is conditional. The test must be stratified by leg and by regime, and it must be net of the full
   cost stack, because cost is the effect that kills tight management in the evidence.

3. **Systematic trend followers mostly do not "manage trades". The position is a function of the current forecast,
   re-evaluated on a fixed clock.** Carver (ex-AHL, systematic futures) runs a continuous system. It computes an
   optimal position, compares it with the current holding and trades the difference. In his framing, stops are
   subsumed by the signal: he prefers to close when the indicator flips sign [S7, PRAC]. A replication found that much
   of time-series momentum's alpha comes from *volatility scaling* rather than from the momentum signal (monthly
   alpha 1.27% with vol-scaled weights vs 0.41% without; Kim, Tse & Wald) [S8, ACAD; secondary summary]. **For us:**
   a *re-score* baseline belongs in the test: at each check-in, re-run the entry model and hold, cut or flip on its
   current output. So does a *vol-rescale* baseline. Both are cheap, stateless, and what the largest systematic
   managers actually run.

4. **When practitioners do use stops, the stop width scales with volatility and the intended holding period, never
   with the entry price.** Carver: stop = X × volatility, where X is set by how long you mean to hold. A breakeven stop
   is "nothing special … as far as the market is concerned". He uses profit targets only for mean-reversion systems and
   argues against time exits [S9, PRAC]. The Chandelier exit (LeBeau/Elder) trails 3 ATR off the 22-bar extreme
   [S10, VEND]. The Turtle rules (secondary sources) use a 2N (20-day ATR) initial stop, a 10- or 20-day channel exit,
   and add a unit every 0.5N [S11, VEND]. **For us:** the rule baselines in the factorial should be the
   volatility-scaled forms practitioners actually use. A fixed +1R milestone is not one of them.

5. **Judgment helps when it is rare, large and driven by new information. It hurts when it is frequent small
   tweaking.** Across forecasts from four supply-chain companies, large judgmental adjustments to a statistical forecast improved
   accuracy and small ones often damaged it (Fildes, Goodwin, Lawrence & Nikolopoulos, *IJF* 2009) [S12, ACAD; the
   analogue closest to "intervening in a model's trade" found with a real sample]. In execution, Schroders found that
   semi-automated algorithms with trader judgment on timing and size beat fully automated ones [S13, VEND/PRAC]. Across
   9,000+ hedge funds from 1996 to 2014, systematic and discretionary funds had similar risk-adjusted performance
   (Harvey, Rattray, Sinclair & Van Hemert, *JPM* 2017) [S14, ACAD]. **For us:** frequent check-ins are a fine
   *clock*, but the *action rate* should be event-gated. The test should measure lift separately for the "no change"
   majority and for the rare large actions.

6. **Prop desks hold a working trade until a stated "reason to sell" appears, and they cap giveback at the account or
   day level, not per trade.** SMB Capital's desk: "Trade2Hold … until a Reason2Sell" [S15, PRAC]. Steenbarger
   recommended a 25–30% daily give-back rule to SMB, enforced by the floor manager (the trader is done for the day)
   [S16, PRAC]. **For us:** the desk's in-trade role should name its reason from a closed list (level broken, momentum
   reversal, vol expansion against the position, thesis invalidated, time). That is what our schema v2 enums already
   do. Giveback limits belong to the account risk layer (our `daily_dd_switch`), not to a per-trade nudge.

7. **The exit-evaluation method practitioners use is a random-entry harness.** Keep the exits, sizing and costs, and
   replace the entries with random ones. Whatever survives is the exit's contribution, and market drift must be netted
   out (Tharp/Basso coin-flip experiment, secondary) [S17, VEND/PRAC]. **For us:** entry source belongs in the
   factorial as a factor (strategy entries vs random entries vs desk entries). That separates "management adds value"
   from "the entry had edge".

8. **ML at real firms is used most robustly as a *secondary* layer on top of a primary signal: meta-labelling and
   bet sizing, execution, and risk. It is rarely used end to end.** López de Prado: every successful quant firm he
   knows applies the "meta-strategy paradigm", a research assembly line with specialised stations, rather than lone
   researchers building whole strategies [S18, PRAC/ACAD]. Meta-labelling separates direction (the primary model) from
   sizing and filtering (the ML layer) [S19, ACAD/PRAC]. *(Section B expands this; draft.)*

9. **Research operations at serious shops are protocol-driven.** Arnott, Harvey & Markowitz (*JFDS* 2019): treat
   history as having no true out-of-sample set, do not tweak a model on live results, keep models simple, and reward
   process over results [S20, ACAD]. *(Section C expands this: deflated Sharpe, multiple testing, purged CV, kill
   criteria; draft.)*

10. **The published evidence that LLM agents can trade is thin, and the best of it is negative to mixed.** Alpha Arena
    Season 1 (real money, $10k per model, crypto perps on Hyperliquid, Oct–Nov 2025): 4 of 6 frontier models lost money,
    GPT-5 by more than 60%. The organiser called it exploratory, with no statistical controls [S21, VEND/trade press].
    FINSABER (arXiv 2505.07078) re-tested published LLM strategies over 20 years and 100+ symbols and found that the
    reported edge "deteriorates significantly": the strategies were too cautious in bull markets and too aggressive in
    bear markets [S22, ACAD]. **For us:** the desk is right to treat Claude as a *teacher whose labels are graded on
    outcomes*, not as a trusted source of edge. Its management decisions must clear the same random-intervention bar as
    any rule.

---

## A. Active trade management in practice

### A.1 What different kinds of firm actually do

| Firm type | How open positions are managed | Check-in cadence | What triggers action | Evidence for it |
|---|---|---|---|---|
| **Systematic trend follower / CTA** | No discrete "trade". The position is a continuous function of the forecast, scaled to volatility. The system trades the difference between the target and the current position [S7, PRAC]. Discrete-system variants use a volatility-scaled trailing stop [S9, PRAC] or channel exits (Turtles: a 10- or 20-day channel, 2N stop) [S11, VEND]. | A fixed clock. Carver's post does not state a frequency for his live system [S7]. Classic CTA and TSMOM research recomputes positions daily or monthly [S8, ACAD]. | The signal changes sign or size, or volatility changes (the rescale). No discretionary trigger. | Vol scaling explains much of TSMOM's alpha [S8]. Stops help under momentum and regime switching [S4, S5]. |
| **Discretionary prop desk (intraday equities)** | Hold while the trade "works" until a "Reason2Sell" appears. Add to winners when the thesis strengthens [S15, PRAC]. A daily give-back cap of 25–30% of peak P&L, enforced by a manager [S16, PRAC]. | Continuous screen-watching. **Decisions are event-triggered**, not taken on a fixed clock [S15]. | Price or level breaks, tape and momentum change, news. | Behavioural studies of exactly these traders show disposition and loss-chasing costs [S2, S3]. The practice partly exists to fight those biases. |
| **Market maker** | Inventory, not trades. Quotes skew to shed inventory. The urgency to flatten grows as the session end approaches (the Avellaneda–Stoikov reservation price r = S − q·γ·σ²·(T−t)) [S23, ACAD/VEND]. | Continuous and automated. | Inventory size, volatility, time to close. | Theory plus wide industry adoption. This lane found no public desk rulebook with hard holding-time limits (a negative result: one search, vendor results only). |
| **Institutional long-only PM** | Discretionary sells, often of positions with extreme past returns (about 50% more likely than for moderate ones) [S1, ACAD; secondary summary]. | Ad hoc. | Salience of past returns. That is the heuristic the paper identifies as costly. | **Sells underperform random sells** [S1]. |

### A.2 Specific management tools, and the evidence on each

- **Initial stop.** Practitioners set it from volatility: X × σ, or 2N in ATR terms [S9, S11]. Theory says a stop lowers
  expected return under a random walk and can raise it under momentum or regime switching [S4]. After costs, tight
  stops lose on US stocks [S5]. *Evidence: strong academic theory and moderate empirical support. Cost is decisive.*
- **Trailing stop.** Practitioners prefer a trailing stop to a fixed one because it caps the loss off the peak, not off
  the entry [S9, PRAC]. The Chandelier exit trails 3 ATR off the 22-bar extreme [S10]. Optimal-stopping theory treats
  the trailing stop plus a limit target as a double stopping problem with an analytic solution (Leung & Zhang, *Applied
  Math & Optimization*) [S24, ACAD]. *Evidence: theory plus practitioner consensus. Empirical out-of-sample support is
  mostly from blogs [VEND].*
- **Breakeven move.** Carver: the entry level is "nothing special … as far as the market is concerned" [S9, PRAC].
  This lane found no study showing that a breakeven move adds value net of cost. *Treat it as a known-weak baseline,
  worth including because retail and prop traders use it widely.*
- **Profit target.** Carver says no for trend systems (a 2× stop target would have missed a ~300% move in his example)
  and yes for mean-reversion systems, set from analysis [S9, PRAC]. For an Ornstein–Uhlenbeck spread, optimal
  take-profit and stop levels can be derived, and a wider stop implies a lower optimal take-profit (Leung & Li, *IJTAF*
  2015) [S25, ACAD]. *Our TP doctrine (a real predictive TP at entry that moves with the prediction) is consistent with
  this for mean-reverting legs. For trend legs, practice argues the TP should be far or absent and the trail should do
  the work. That is a tension to test, not to assume away.*
- **Partials / scaling out.** Scaling out raises the hit rate and trims the largest winners. It changes the shape of
  the distribution, not necessarily its mean [S26, VEND]. This lane found no academic study showing that partials add
  expectancy. *Evidence: weak. Test it as an arm. Do not adopt it on intuition.*
- **Scaling in / pyramiding.** The Turtles added a unit every 0.5N, up to 4 units [S11, VEND]. SMB adds to winners when
  the thesis strengthens [S15, PRAC]. Under momentum this is consistent with Kaminski & Lo's serial-correlation result
  [S4]. *Evidence: practitioner. Out of scope for a first test (it changes risk per trade, which is Tier 3).*
- **Time stop.** Practice is split. Carver argues against time exits [S9, PRAC]. CTA education material says trailing
  stops "often depend upon both time and price", and that some high-frequency CTAs exit on time rather than on stops
  [S27, VEND]. A blog backtest found a fixed 12-month hold beat several channel exits on equities [S28, VEND, single
  dataset]. *Evidence: weak and contradictory. It is a cheap arm to include.*
- **Giveback rule.** Practitioners set it at the *day or account* level (25–30% of peak daily P&L) [S16, PRAC], and prop
  firm rules use intraday trailing drawdown floors [S16, VEND]. A per-trade "never give back more than 60% of peak
  open profit" rule appears only as a blog comment [S16, VEND]. *Our account-level `daily_dd_switch` matches practice.
  A per-trade giveback exit is a hypothesis to test, not established practice.*

### A.3 Does discretionary in-trade intervention add or destroy value?

The evidence leans to **destroys, unless the intervention is rare, large and driven by new information**:

- **Destroys:** institutional sells underperform random sells [S1]. Prop traders' disposition effect is costly [S2].
  Loss-driven afternoon risk-taking moves prices that then revert [S3]. LLM agents flip positions under "prompt-induced
  hesitation" [S21].
- **Neutral or context-dependent:** Locke & Mann (*JFE* 2005, CME floor traders) found that traders held losers longer
  than winners, but a secondary summary reports no measurable cost in their sample. The least successful traders held
  losers longest [S29, ACAD; secondary only]. In an experiment with 193 professionals, the disposition effect was
  *profitable* on mean-reverting securities. A prompt that removed it helped on trending securities and hurt on
  mean-reverting ones (Guenther & Lordan, *Frontiers in Psychology* 2023) [S30, ACAD]. **So whether "letting winners
  run" is right depends on the return process.** That is the same conditionality as finding 2.
- **Adds:** large, information-backed adjustments to forecasts [S12]. Semi-automated execution with human timing
  [S13]. Systematic vs discretionary is roughly a tie at the fund level [S14].

This lane found no peer-reviewed study that measures discretionary *overrides of a systematic trading model's open
positions* directly (a negative result: three searches; the probe did find the adjacent override and judgmental-
adjustment literature, so the search could find positives). The judgmental-forecasting literature [S12] is the closest
analogue with a real sample.

### A.4 Design implications for us (section A)

1. **The +1R single check-in did not test "active management".** It tested one fixed, non-volatility-scaled milestone
   that no practitioner source uses as *the* management policy. Its failure says nothing about the management family.
   It closes only that configuration, in line with the family-retirement policy's "a FAIL closes the exact configuration
   tested".
2. **Every management arm needs two controls: hold-to-bracket, and a matched random intervention.** The random
   intervention fires the same *number and type* of actions as the arm, at random check-ins. Without it, a positive
   result can be the effect of "acting at all" (cutting variance or banking drift). With it, we measure whether the
   *timing* carries information. This is the counterfactual the strongest exit evidence uses [S1].
3. **Use the volatility-scaled rule baselines practitioners actually run**, not R milestones alone: a Chandelier
   trail at k ∈ {2, 3} × ATR(22) off the extreme, a channel exit, a re-score exit (re-run the entry model at each
   check-in), a vol-rescale, and a time stop. They are cheap, stateless and well documented.
4. **Separate the clock from the action rate.** Check in on every bar close of the trade's own timeframe (this
   mirrors a CTA's fixed clock), *plus* event triggers (R milestones at ±0.5R/±1R/+2R, an ATR ratio change, a level
   touch, a momentum reversal). Record *no action* as a decision. Report lift separately for the actions taken and for
   the decisions not to act (finding 5).
5. **Stratify by return process.** Tag each leg as trend or mean-reversion from its own Stage-0 serial-correlation
   profile. The evidence predicts that trailing and stop-tightening help trend legs and hurt mean-reversion legs
   [S4, S30].
6. **Net of the full cost stack, always.** Cost is the effect that flips tight stops from helpful to harmful [S5].

---

## B. AI/ML in the trading pipeline at real firms

*Draft in progress. This section, and sections C, D, the comparison table, the recommended designs and the full
sources list follow in the next push.*

## C. Research operations and evaluation methodology

*Draft in progress.*

## D. LLM and agentic trading: published results

*Draft in progress. See finding 10.*

---

## 9. Sources (draft; full list in the next push)

- [S1] Akepanidtaworn, Di Mascio, Imas & Schmidt, "Selling Fast and Buying Slow", *JF* 78(6) 2023. https://www.nber.org/papers/w29076 · https://papers.ssrn.com/abstract=3301277 · summary: https://www.institutionalinvestor.com/article/b1cnb33z8ml9rr/Portfolio-Managers-Are-Good-at-Buying-but-Stink-at-Selling [ACAD; read: abstract + secondary]
- [S2] Garvey & Murphy, "Are Professional Traders Too Slow to Realize Their Losses?", *FAJ* 2004. https://rpc.cfainstitute.org/research/financial-analysts-journal/2004/are-professional-traders-too-slow-to-realize-their-losses [ACAD; abstract]
- [S3] Coval & Shumway, "Do Behavioral Biases Affect Prices?", *JF* 60(1) 2005. https://ideas.repec.org/a/bla/jfinan/v60y2005i1p1-34.html [ACAD; abstract]
- [S4] Kaminski & Lo, "When Do Stop-Loss Rules Stop Losses?", *J. Financial Markets* 2014. https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf [ACAD; abstract]
- [S5] Lo & Remorov, "Stop-loss strategies with serial correlation, regime switching, and transaction costs", *JFM* 2017. https://dspace.mit.edu/handle/1721.1/107017 · https://www.cxoadvisory.com/equity-premium/stop-losses-on-stock-positions-in-depth [ACAD; abstract + secondary]
- [S6] Han, Zhou & Zhu, "Taming Momentum Crashes: A Simple Stop-Loss Strategy" (SSRN 2407199). https://www.cxoadvisory.com/technical-trading/stop-losses-to-avoid-stock-momentum-crashes/ · https://alphaarchitect.com/taming-the-momentum-roller-coaster-fact-or-fiction/ [ACAD; secondary summaries only]
- [S7] Carver, qoppac blog (stop-loss posts and comments). https://qoppac.blogspot.com/search?q=stop+loss [PRAC]
- [S8] Kim, Tse & Wald, replication of time-series momentum. https://quantpedia.com/deconstructing-the-time-series-momentum-strategy/ [ACAD; secondary summary]
- [S9] Carver, "What is the right way to set stop losses?", 2020-02-06. https://qoppac.blogspot.com/2020/02/what-is-right-way-to-set-stop-losses.html [PRAC; read in full; argued from examples, no backtest]
- [S10] Chandelier exit description. https://www.luxalgo.com/library/concept/chandelier-stop.md [VEND]
- [S11] Turtle rules, secondary. https://www.mql5.com/en/articles/23448 [VEND]
- [S12] Fildes, Goodwin, Lawrence & Nikolopoulos, "Effective forecasting and judgmental adjustments", *IJF* 2009. https://research.manchester.ac.uk/en/publications/effective-forecasting-and-judgmental-adjustments-an-empirical-eva/ [ACAD; abstract]
- [S13] Schroders execution study. https://www.globaltrading.net/man-vs-machine-the-schroders-story/2 [VEND/PRAC]
- [S14] Harvey, Rattray, Sinclair & Van Hemert, "Man vs. Machine", *JPM* 43(4) 2017. https://people.duke.edu/~charvey/Research/Published_Papers/P130_Man_vs_machine.pdf [ACAD]
- [S15] SMB Capital, Bellafiore blog ("Trade2Hold", "Reason2Sell"). https://www.smbtraining.com/blog/tag/smb-capital/page/8 [PRAC]
- [S16] SMB Capital, "A Rule for Giving Back Profits?" https://www.smbtraining.com/blog/a-4-the-trading-community-a-rule-for-giving-back-profits · prop-firm drawdown rules: https://newyorkcityservers.com/blog/prop-firm-daily-drawdown-rules [PRAC / VEND]
- [S17] Random-entry baselines (Tharp/Basso). https://www.luxalgo.com/library/concept/random-entry-baselines/ · https://elitetrader.com/et/threads/what-was-the-random-entry-chandelier-exit-study.216366/post-3112092 [VEND/PRAC, secondary]
- [S18] López de Prado, "The 10 Reasons Most Machine Learning Funds Fail", 2018. https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf [PRAC/ACAD]
- [S19] Meta-labelling overview. https://en.wikipedia.org/wiki/Meta-Labeling · https://hudsonthames.org/tag/meta-labeling/ [ACAD/PRAC, secondary]
- [S20] Arnott, Harvey & Markowitz, "A Backtesting Protocol in the Era of Machine Learning", *JFDS* 2019. https://papers.ssrn.com/abstract=3275654 · https://alphaarchitect.com/protocol-to-prevent-quants-gone-wild/ [ACAD; secondary summary of the checklist]
- [S21] Alpha Arena Season 1 results. https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/ · https://decrypt.co/345006/ai-crypto-trading-showdown-deepseek-grok-winning-gemini-implodes · https://iweaver.ai/blog/alpha-arena-ai-trading-season-1-results [VEND / trade press]
- [S22] Li, Kim, Cucuringu & Ma, "Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?" (FINSABER). https://arxiv.org/abs/2505.07078 [ACAD]
- [S23] Avellaneda–Stoikov market making; Guéant, Lehalle & Fernandez-Tapia. https://hal-ensta-paris.archives-ouvertes.fr/UPMC/hal-00675925v3 · https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/ [ACAD / VEND]
- [S24] Leung & Zhang, "Optimal Trading with a Trailing Stop", *Appl. Math. Optim.* https://arxiv.org/abs/1701.03960 [ACAD]
- [S25] Leung & Li, "Optimal Mean Reversion Trading with Transaction Costs and Stop-Loss Exit", *IJTAF* 2015. https://arxiv.org/abs/1411.5062 [ACAD]
- [S26] Scaling out. https://www.luxalgo.com/library/concept/scaling-out/ · https://www.trade-ideas.com/2023/08/30/the-true-impact-of-partial-profits/ [VEND]
- [S27] Trend following and trailing stops. https://www.pragcap.com/trend-following-and-trailing-stops/ [VEND]
- [S28] Time exit vs channel exit backtest. https://setup4alpha.substack.com/p/trailing-stop-vs-fixed-stop-tested [VEND]
- [S29] Locke & Mann, *JFE* 2005 (CME floor traders), via secondary. https://efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2009-Milan/papers/EFMA2009_0560_fullpaper.pdf [ACAD; secondary]
- [S30] Guenther & Lordan, "When the disposition effect proves to be rational", *Frontiers in Psychology* 2023. https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2023.1091922/full [ACAD]

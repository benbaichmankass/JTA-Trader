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

Where this lane read only an abstract or a secondary summary, not the full paper, the entry says so. The numbered sources list
(§ 9) matches the bracketed tags `[S#]` used in the text.

---

## Two research tracks (operator decision 2026-10-28, binding): how this review is organised

All research is one of two tracks. **TRADING** is how to trade better: strategies, entries, exits, active management,
sizing, costs, venues. **MODEL** is how to build a better AI trader: data, labels, features, training, evaluation,
model families, infra, the desk-as-teacher pipeline. Research-ops methodology applies to both.

| track | sections | canonical principles |
|---|---|---|
| **TRADING** | A (trade management practice), E (our live trade review vs practice), G.1 (the desk management test) | T1–T10 |
| **MODEL** | B (ML at real firms), C.4 (our model training and evaluation), D (LLM / agentic trading), G.2 (the ML trade-management programme) | M1–M10 |
| **RESEARCH-OPS (both)** | C.1–C.3, F (where we differ from practice), G.3 | R1–R6 |

The numbered canonical list that skills point at is
[`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
The weekly refresh is owned by `.claude/skills/frontier-research/SKILL.md` § "Practice & methodology refresh". It runs
on Wednesday after the weekly reset, in the ML-FRONTIER-PREP lane of the "Weekly review prep" routine, and each run
has one output section per track.

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
   sizing and filtering (the ML layer) [S19, ACAD/PRAC]. Documented production ML sits in execution, hedging and routing
   (Man AHL's ML execution router, JPMorgan LOXM and deep hedging) [S31, S34, S35]. LLMs are documented in *research*
   (Man's AlphaGPT, held to the same thresholds and committee as human signals), not in live trade decisions [S32, S37].
   **For us:** the ML trade-management programme should be a meta-model over the best rule, trained on the *priced
   outcome of every action* on the real path, not on imitation of Claude (§ B.6).

9. **Research operations at serious shops are protocol-driven.** Arnott, Harvey & Markowitz (*JFDS* 2019): treat
   history as having no true out-of-sample set, do not tweak a model on live results, keep models simple, and reward
   process over results [S20, ACAD]. Backtest Sharpe explained less than 2.5% of out-of-sample Sharpe across 888
   strategies, and the gap grew with the number of backtests (Wiecki et al. 2016) [S42, ACAD]. Pre-registration cuts
   p-hacking only when it includes a full analysis plan [S49, ACAD]. **For us:** our guard-enforced pre-registration,
   trial ledger and holdout already match or exceed documented practice (our 2026-10-16 benchmark). The gap is a
   standard *control set* for intervention tests, plus a declared practice precedent for each arm (§ C.3, § G.3).

10. **The published evidence that LLM agents can trade is thin, and the best of it is negative to mixed.** Alpha Arena
    Season 1 (real money, $10k per model, crypto perps on Hyperliquid, Oct–Nov 2025): 4 of 6 frontier models lost money
    (GPT-5 ended at $4,126 of $10,000). The organiser called it exploratory, with no statistical controls [S21, VEND/trade press].
    FINSABER (arXiv 2505.07078) re-tested published LLM strategies over 20 years and 100+ symbols and found that the
    reported edge "deteriorates significantly": the strategies were too cautious in bull markets and too aggressive in
    bear markets [S22, ACAD]. **For us:** the desk is right to treat Claude as a *teacher whose labels are graded on
    outcomes*, not as a trusted source of edge. Its management decisions must clear the same random-intervention bar as
    any rule.

---

## A. Active trade management in practice [TRADING]

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

## B. AI/ML in the trading pipeline at real firms [MODEL]

### B.1 Where firms say they actually use ML (public record only)

Public disclosure is selective, and firms talk about what is safe to talk about. Read this table as "documented uses",
not "all uses".

| Firm / source | Use | Human role | Evidence weight |
|---|---|---|---|
| **Man AHL**: ML listed as a 2014 milestone; a 2018 ML **execution router** that picks between internal algos, dealer algos and the human desk, and shifts flow toward routes that execute better [S31, PRAC/trade press] | Execution (a contextual-bandit-like router), plus "investment" uses that are not specified | The risk chief says ML models get the same daily checks as conventional ones. Humans intervene "mainly when a model's assumptions broke down during unusual events" [S31] | Trade press (Risk.net) quoting the firm. Savings not quantified ("too early") |
| **Man Group AlphaGPT** (2025): an agentic LLM research pipeline with an Idea Person, an Implementer and an Evaluator [S32, PRAC] | **Signal research**, not trading. Most successful so far in systematic equities | Every AI signal must pass "identical thresholds" to human research and have an economic rationale. Then the Investment Committee, code review, unit and integration tests, and full logging. The firm says "substantial human oversight" is still required [S32]. Press reports several dozen signals approved for live trading [S33, VEND] | Firm's own article (marketing-adjacent) plus press |
| **JPMorgan LOXM** (2017): deep RL equity **execution**, trained on billions of real and simulated trades [S34, VEND/trade press] | Execution (slicing large orders) | Kept inside the bank's electronic risk framework while learning [S34] | Bank's own claims. No independent verification |
| **JPMorgan deep hedging** (Buehler, Gonon, Teichmann & Wood, *Quant. Finance* 2019) [S35, ACAD]; production use on part of the Eurostoxx vanilla book reported in a Risk.net interview [S35, PRAC] | **Hedging / position management under frictions** | Not described | The method is peer-reviewed. Production use rests on one interview |
| **Bridgewater AIA Labs** (2024): an ML-driven fund, ~$2bn reported [S36, VEND/trade press] | Idea generation through to execution | Humans keep risk management, with a manual "kill switch". Accounts of the human role conflict [S36] | Trade press, inconsistent |
| **Balyasny, Man (ManGPT)**: firm-wide LLM assistants [S37, VEND/trade press] | Research productivity (for example, central-bank previews in 30 minutes instead of two days) | The analyst decides | Trade press |
| **Citadel (Griffin, Oct 2025)**: "for uncovering alpha it just falls short" [S37, trade press] | GenAI used for productivity, not alpha | — | A named practitioner's public statement |

**Pattern (INFERRED from the table, not a measured census):** documented production ML at large firms sits in
**execution, hedging and routing** (dense feedback, a short horizon, a clear cost metric) and in **research tooling**
(LLMs generating hypotheses that then face the same statistical gates as human ideas). This lane found **no public
record of a major firm letting an LLM make or manage live trade decisions**. Bridgewater's ML fund is the closest, and
it is not an LLM and keeps a human kill switch.

### B.2 Meta-labelling, bet sizing, and "ML as a second layer"

López de Prado's meta-labelling separates *direction* (a primary model or rule) from *whether and how much to bet*
(an ML classifier trained on the primary model's outcomes). It trades recall for precision and turns the classifier's
probability into a position size [S19, ACAD/PRAC]. A JFDS paper in the meta-labelling series reports that calibrating
the probabilities significantly improves fixed sizing functions [S19, ACAD; abstract via secondary]. The point for
trade management is that **an exit or management model is naturally a meta-model.** It sits on top of an existing
management rule (for example, "the Chandelier trail fires now; should we honour it?"), rather than learning management
from scratch. Our repo already has `src/research/meta_label.py` and `docs/research/M23-meta-labeling-DESIGN.md`.

### B.3 RL and imitation for exits: the academic state

- **Optimal-stopping theory** gives analytic exits for stylised processes: trailing stops [S24] and OU spreads with a
  stop-loss [S25]. These are good *baselines* and feature generators, not production policies.
- **Deep RL for exit timing**, one recent example (Wang, Ślepaczuk & Sakowski, arXiv 2610.13126, SPX short straddles):
  a supervised model trained on *ex-post optimal hold/exit labels* beat passive holding and fixed time and P&L exits
  out of sample. RL fine-tuning initialised from that supervised model added a little. **RL from scratch earned about
  0%** (0.18% vs ~37%) [S38, ACAD preprint; excerpt read; cost treatment not confirmed]. That is one preprint, but it
  matches a widely known pattern: supervised labels from priced alternatives first, RL (if ever) as fine-tuning.
- **Imitation learning (behaviour cloning)** suffers from compounding errors once the policy reaches states the
  expert never visited. DAgger fixes this by having the expert relabel the learner's own states, at the cost of many
  expert queries [S39, ACAD survey]. This lane found no peer-reviewed finance paper showing behaviour cloning of a
  trader working out of sample (a negative result: one search; the probe found the general literature). Combined with
  § A.3 (experts' exits underperform random ones), **pure imitation of a teacher's exits is the weakest design
  available.**

### B.4 How firms structure research → production (documented)

Idea → research under a protocol → evaluation against fixed thresholds → committee and code review → paper or house
capital → live at small size → scale, with live monitoring and the ability to roll back. Sources: Man AlphaGPT's gates
[S32]; the Arnott/Harvey/Markowitz protocol [S20]; Man AHL's academic board on running new models on house capital to
catch *broken* models rather than to test significance [S40, PRAC; via our 2026-10-16 benchmark]. Forward or paper
trading confirms the plumbing but "usually cannot distinguish a modest edge from luck" [S41, VEND].

### B.5 Known failure modes

- **Backtest overfitting and selection:** backtest Sharpe explains less than 2.5% of out-of-sample Sharpe across 888
  Quantopian strategies, and the gap grows with the number of backtests run (Wiecki et al. 2016) [S42, ACAD].
- **Decay:** published predictors earn 26% less out of sample and 58% less after publication (McLean & Pontiff,
  *JF* 2016) [S43, ACAD].
- **Look-ahead and memorisation in LLM-based research** (§ D).
- **Herding:** the Bank of England warns that AI used in trading may lead participants "inadvertently to take actions
  collectively" [S44, regulator via press].
- **The lone-quant "Sisyphus" pattern** instead of a research assembly line [S18].

### B.6 Design implications for us (section B)

1. **The ML trade-management programme should learn from *priced alternatives*, not from Claude's choices.** Our
   replay can price every action (hold, close, tighten, partial) on the real path, net of cost, at every check-in.
   Those counterfactual outcomes are better labels than any teacher's pick, and they are free of the teacher's biases
   (§ A.3). Claude's decisions are still valuable as *features and hypotheses*: what did it see that the rule did not?
   They should not be the target.
2. **Start as a meta-model on top of the best rule baseline** from the desk test (§ B.2), not as an end-to-end
   policy. Supervised first. RL only as fine-tuning, only after the supervised head clears its bar [S38].
3. **If any distillation of Claude is kept, filter it by outcome.** Distil only the decisions that beat the matched
   random intervention, and relabel the student's own visited states with priced alternatives (DAgger-style, at zero
   teacher cost) [S39].
4. **Our desk is ahead of documented industry practice.** No major firm is documented letting an LLM manage live
   positions. That is not a reason to stop. It is a reason to hold the desk to the strictest controls and to treat
   its live role as a label generator under the 1–2-trade mechanical soak doctrine, not as an established edge.

---

## C. Research operations and evaluation methodology [RESEARCH-OPS, both tracks; C.4 is MODEL]

**Most of this was benchmarked on 2026-10-16** in
[`docs/research/research-ops-benchmark-2026-10-16.md`](research-ops-benchmark-2026-10-16.md) (23 sources: López de
Prado, DSR, PBO, Harvey–Liu–Zhu, the Arnott et al. protocol, the Man AHL board, Winton's "Blinded by optimism",
WorldQuant, McLean–Pontiff, Quantopian, SPC/CUSUM, Stage-Gate, online FDR). This lane re-verified the headline
sources (S18, S20, S42, S43, S45–S48) and does not repeat that table. What it found since:

| benchmark gap (2026-10-16) | row | state (read 2026-10-28 from `docs/claude/work/checklist/`) |
|---|---|---|
| Multiple testing at programme level | `RESEARCH-TRIAL-LEDGER` | done (report-only ledger, DSR / haircut) |
| Should the promotion bar see N? | `PROMOTION-BAR-MULTIPLICITY` | done (promotion needs a holdout pass, R-HOLDOUT, #18626) |
| Confirmation on fresh data | `RESEARCH-CONFIRM-FRESH-WINDOW` | landed_unproven |
| Live decay monitor (CUSUM) | `LIVE-DECAY-MONITOR` | queued |
| Correlation with the existing book | `PROMOTION-CORRELATION-CHECK` | queued |
| Research outcome metrics | `RESEARCH-OUTCOME-METRICS` | queued |

### C.1 Core methodology, re-verified

- **Deflated Sharpe ratio**: corrects for selection under multiple testing and for non-normal returns (Bailey & López
  de Prado, *JPM* 2014) [S45, ACAD]. **PBO via CSCV**: the probability that the in-sample best ranks below the median
  out of sample (Bailey, Borwein, López de Prado & Zhu, *J. Comp. Finance* 2017) [S46, ACAD].
- **t > 3 hurdle** for new factors given the history of data mining (Harvey, Liu & Zhu, *RFS* 2016) [S47, ACAD]. Even
  t > 3 can give many false positives when true effects are rare, so report a Bayesianised p-value with prior odds
  (Harvey, AFA presidential address, *JF* 2017) [S48, ACAD].
- **Pre-registration works when it includes a full analysis plan.** Across 15,992 test statistics from economics
  RCTs, pre-registration *alone* did not reduce p-hacking. Pre-registration with a complete pre-analysis plan did
  (Brodeur, Cook, Hartley & Heyes) [S49, ACAD]. *Our units register a decision rule. Whether each also fixes the
  transforms, windows and exclusions is the "forking paths" residue the benchmark already noted.*
- **Purged k-fold, embargo and combinatorial purged CV**: remove training observations whose label windows overlap
  the test labels, embargo a buffer after each test block, and assemble many paths into a *distribution* of OOS Sharpe
  [S50, ACAD/PRAC]. **Triple-barrier labels**: profit barrier, stop barrier and time barrier, the first one touched sets
  the label [S50; primary source AFML 2018, not re-read here]. *For trade management, every check-in inside the same
  trade shares one price path. CV must group by trade, and purge across trades whose holding windows overlap.*
- **Kill criteria for a running strategy**: the triple-penance rule. Under IID returns, recovery from a drawdown takes
  on average about 3× as long as the drawdown took to accumulate, independent of Sharpe. Firms give higher-Sharpe PMs
  looser stop-outs, and positive autocorrelation changes the multiple (Bailey & López de Prado, *J. Risk* 2015) [S51,
  ACAD; secondary for the autocorrelation caveat].

### C.2 How firms evaluate exit and management policies specifically (the thin part of the literature)

This lane found **no published firm methodology dedicated to evaluating exit policies** (a negative result: four
searches across academic, practitioner and vendor sources; the probe did find entry and backtest methodology, so it
could find positives). What the sources *do* give, assembled:

1. **Hold the entries fixed and vary only the management.** This is the random-entry harness of Tharp and Basso
   [S17], and the logic of the counterfactual in Akepanidtaworn et al. [S1].
2. **Benchmark against a random counterfactual with the same action rate and timing distribution**: the random-sell
   benchmark [S1]. Our unit `RQ-20261027-8b01-03` already registers a "frequency-matched random-timing baseline". That
   is the right control.
3. **Benchmark against simple static rules chosen without seeing the test folds** [S20; RQ-20261027-8b01-03 does
   this].
4. **Count every management variant tried** (the trial ledger), deflate, and confirm on a fresh window [S45, S46;
   benchmark rows].
5. **Measure per unit of risk-time, not only per trade.** An early exit frees capital and risk budget. Per-trade R
   understates it, and holding to the bracket overstates it. *INFERRED from the CTA practice of continuous position
   targets [S7]. No source states it as a rule for exits.*
6. **Stratify by return process** (trend vs mean reversion), because the sign of a stop's value flips [S4, S30].

### C.3 Design implications for us (section C)

1. **Add a "practice precedent" field to every new test design** (operator ask, 2026-10-28): each arm cites the
   practitioner or academic source it comes from, or is labelled `novel`. A `novel` arm is allowed, but it is
   declared, so it cannot pass as "how it is done".
2. **Make the three controls standard for any intervention test**: hold-to-recorded-exit, matched random
   intervention, and best static rule selected without the test folds. We have all three in one unit. Make them the
   template.
3. **Group-by-trade CV with purging and embargo** for any model trained on check-in panels (§ B).
4. **Prioritise the three queued benchmark rows.** `LIVE-DECAY-MONITOR` matters most for a desk that trades live.

### C.4 Principles for our model training and evaluation [MODEL]

*Operator, 2026-10-28 (via the manager): "so that we're also building our own models correctly". The numbered,
one-line canonical form is
[`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md)
§ MODEL (M1–M10). This section gives the reasoning and checks our current pipeline against each principle.*

**How the "current pipeline" column was established.** This lane READ the code at `origin/main` 4329698a1 (MEASURED
by reading, not by running). It reads `ml/promotion/__init__.py` (documented WS4 gates), `ml/promotion/oos_edge.py`
(purged WF-CV vs a constant baseline), `ml/promotion/attribution.py` (win = pnl > 0, AUC / Brier vs the base rate),
`ml/datasets/labeling/triple_barrier.py`, and `ml/datasets/families/{setup,exit}_candidates.py`. Facts about coverage,
the data chain and what is or is not trained come from lane `ML-COVERAGE-AUDIT`
(`docs/research/ml-coverage-audit-2026-10-28.md` on branch `claude/ml-coverage-audit-20261028`, not yet on `main`
when read). They are cited, not re-measured.

| # | principle (sources) | current pipeline | verdict |
|---|---|---|---|
| M1 | Labels = the path-dependent, cost-net outcome of the exit policy actually traded [S50, S38] | Triple-barrier labelling exists (`setup_candidates`, `exit_candidates`, CUSUM-sampled). **`BarrierConfig.slippage` defaults to 0.0**, and no manifest under `ml/configs/` sets it (grep, 2026-10-28), so these labels are **gross**. The family's own docstring warns that candle barriers assume optimistic fills. The live-attribution label is binary win = pnl > 0, which ignores magnitude and cost | **Violation (partial):** labels are gross of cost, and the attribution label is binary |
| M2 | Purged, embargoed WF / CPCV, grouped by trade [S50] | **Have:** `ml.experiments.splitters.iter_folds` (purged and embargoed WF-CV) used by `oos_edge.py`; `ml_bakeoff.py` uses purged walk-forward folds with an embargo. Grouping by trade for multi-checkpoint panels is not verified (no exit-management panel model exists yet) | **Compliant**, with a watch item for future check-in panels |
| M3 | Leakage controls [S55, S53] | `leakage_test_passed` is a documented gate *string* in `PROMOTION_GATES` (evidence by reference). The frontier skill holds out bars after a pretrained model's release. Masked LLM packets are used in desk D-S0 units | **Partial:** the WS4 leakage gate is documentary, not computed |
| M4 | Pre-registered rule plus analysis plan [S20, S49] | **Have** for research units (`check_research_queue_decision_rule.py`; `ml_bakeoff` blocks registered before the run). The registry's training cycles (daily retrains) are not pre-registered experiments, and need not be | **Compliant** for experiments |
| M5 | Deflate for selection; fresh-window confirmation [S45–S48] | The `trial_ledger.py` counts configurations over the m20 corpus and E5 records that carry a backtest statistic. ML bake-off metrics (AUC, log-loss) are probably not counted (INFERRED from its population statement; not verified). There is no DSR or PBO in `ml/` (grep: 0 files) | **Gap:** ML experiment multiplicity is not deflated |
| M6 | Beat random and simple-rule baselines at the same decision points, net of cost [S1, S20, S42] | `oos_edge.py` baseline = a **constant per-group mean**. Attribution compares Brier with the constant base rate. The `paper → advisory` gate "transaction_cost_evaluation_complete" is a documented string. No random-action or simple-rule decision baseline exists in `ml/` (grep for random/shuffle baselines: 0 files) | **Violation:** the bar is a constant predictor on a predictive metric, not decision value vs rules and random, net of cost |
| M7 | Stratify by regime [S22, S4] | Regime features and regime cells exist (110 files mention regime). Stratified *evaluation* in the promotion gates is not verified | **Unverified** |
| M8 | Cadence and trigger set as factors for trade-management models [S12, S1] | No trade-management model exists yet. The desk and ML programme lanes are designing them (§ G.1, § G.2) | **Not yet applicable**; build it in from the start |
| M9 | Meta-model over the best rule; RL only as fine-tuning; no pure imitation [S19, S38, S39] | Meta-label manifests exist (`setup-candidates-metalabel-*`; `src/research/meta_label.py`). ML-COVERAGE-AUDIT reports that teacher-side desk and LTR records are "recorded → built into a dataset → never trained" (§ 1c of that audit). So nothing imitates the teacher yet, and nothing learns from it either | **Compliant by absence.** The risk is that the first desk student is built as imitation. § G.2 says how to avoid it |
| M10 | Promote on OOS decision value net of cost vs incumbent, rule and random; teacher agreement never gates; CUSUM after promotion [S1, S43] | The `live_agreement` gate uses win = pnl > 0 agreement. The legacy WS4 `advisory → live-approved` gate lists "shadow_mode_clean_soak_at_least_7d", a **calendar** soak in a documented gate string. That may conflict with the soak doctrine (1–2 mechanical trades, never a date); INFERRED, not ruled on here. `LIVE-DECAY-MONITOR` (CUSUM) is queued | **Violation (partial)** plus **possible doctrine conflict** to raise |

**Filed:** row `ML-TRAINING-PRINCIPLES-GAPS` (M1 gross labels, M5 ML multiplicity, M6 baselines and cost, M10 the
calendar-soak string). It composes with, and does not duplicate, `ML-COVERAGE-AUDIT`'s gap list (data chain, coverage,
the never-trained teacher records).

---

## D. LLM and agentic trading: published results [MODEL]

### D.1 Results, with an honest grade of the evidence

| Study | Setting | Result | Evidence quality |
|---|---|---|---|
| **Alpha Arena Season 1** (nof1, Oct–Nov 2025) [S21] | Real money: $10k each, 6 frontier LLMs, crypto perps on Hyperliquid, same prompt and data, about 2–3 weeks | Final balances from $10,000 (one outlet): Qwen3-Max $12,231, DeepSeek $10,489, Claude Sonnet 4.5 $5,799, Gemini 2.5 Pro $5,445, Grok 4 $4,208, GPT-5 $4,126. **4 of 6 lost.** Outlets disagree on the exact percentages. Frequent reversals and "prompt-induced hesitation" | **Weak**: one short window, one market regime, n=6, no controls. The organiser calls it exploratory. Its value is as an *existence proof of failure modes*, not a ranking |
| **FINSABER** (Li, Kim, Cucuringu & Ma; arXiv 2505.07078, listed for KDD 2026) [S22] | Re-tested published LLM timing strategies over 20 years and 100+ symbols | The reported edge "deteriorates significantly" under the broader test. Too conservative in bull markets, too aggressive in bear markets. The authors recommend regime-aware risk control over framework complexity | **Strongest available**: academic, broad, long, code public. Backtest, so exposed to look-ahead (below) |
| **TradingAgents** (Xiao et al., arXiv 2412.20138) [S52] | Multi-agent LLM "trading firm" (analysts, researchers, a risk team) | Beat buy-and-hold and rule baselines on 5 tech stocks, **Jan–Mar 2024 (3 months)**. Apple Sharpe above 8, which the authors partly attribute to the short window | **Weak**: 3 months, 5 stocks, inside model training windows |
| **LiveTradeBench** (UIUC, arXiv 2511.03628) [S53]; **StockBench** (arXiv 2510.02209); **AI-Trader** (arXiv 2512.10971) | *Live* or contamination-free streaming evaluation | 21 LLMs compared: top general-benchmark models were not necessarily the best traders, and models showed distinct risk styles (LiveTradeBench). Other tables not read | **Methodologically better** (no leakage). Results not yet decision-grade (short windows) |
| **Lopez-Lira & Tang**, "Can ChatGPT forecast stock price movements?" (arXiv 2304.07619 v6) [S54] | LLM news-headline sentiment → next-day returns | About 90% hit rate on the *non-tradable* initial reaction. Predicts subsequent drift for small stocks and negative news. **v6 (Oct 2025): strategy returns decline as LLM adoption rises.** An earlier draft's 400% (Oct 2021–Dec 2022) was gross of costs | **Moderate**: academic, post-cutoff headlines. The decay result is itself a warning |
| **Look-ahead and memorisation**: Glasserman & Lin (arXiv 2309.17322) [S55]; Look-Ahead-Bench (arXiv 2601.13770); Gao, Jiang & Yan (arXiv 2512.23847) | Do LLM backtests leak future information? | Glasserman & Lin: in-sample, a "distraction" effect (company knowledge) mattered more than look-ahead, and anonymising names helped. Later work finds clear in-sample vs out-of-sample gaps for commercial LLMs | **Strong methodological warning**: any LLM backtest inside the model's training window is suspect |
| **Industry use** [S32, S37] | Man AlphaGPT (research), BAM ChatGPT, ManGPT (productivity) | Griffin: GenAI "falls short" for alpha | Practitioner statements |

### D.2 Design implications for us (section D)

1. **Our masked, point-in-time replay packets (no symbol, date or absolute price, as in RQ-20261027-8b01-03) are the
   right defence against memorisation.** Practice and the academic warnings [S55] support them. Keep them mandatory
   for any D-S0 desk test whose window lies inside Claude's training data.
2. **Expect regime asymmetry.** FINSABER's "too cautious in bulls, too aggressive in bears" [S22] says the desk test
   must report results by trend regime, not pooled.
3. **Expect hesitation and churn.** Alpha Arena's failure mode (reversals, inactivity) [S21] maps directly onto
   in-trade management. The matched random-intervention control (§ A.4) is what detects it.
4. **Live, contamination-free evaluation is the credible frontier** [S53]. Our live shadow-proposal stream is a
   contamination-free evaluation by construction, so grade it as one.

---

## E. Our live trade review vs practice [TRADING]

*Scope addition from the operator via the manager, 2026-10-28 ~06:45Z. The LTR is live and applying actions
(`apply_mode: apply`, under MD-TRADE-DESK). **Every recommendation below is a PROPOSED change.** It would be Tier 2
(`config/live_trade_review.yaml` plus the due gate in `src/runtime/live_review_due.py`). None of it is applied by this
lane. Filed as row `LTR-PRACTICE-REDESIGN`.*

### E.1 What the LTR does today (MEASURED by this lane, reading `config/live_trade_review.yaml` and `src/runtime/live_review_due.py` at `origin/main` 4329698a1; it agrees with the manager's read)

| trigger | fires when | side |
|---|---|---|
| `r_milestone` | open R first reaches +1.0R, then every +1.0R | favourable only |
| `new_peak` | peak R is at least 0.5R above the last reviewed peak | favourable only |
| `giveback` | peak ≥ 1R and giveback ≥ max(0.5R, 30% of peak) | adverse, but only after a ≥1R peak |
| `near_target` | 0.5R or less to the TP | favourable only |
| `daily_floor` | 24h since the last review (all 12 listed accounts) | time, 24h |
| `swing` | \|close(t) − close(t−1)\| ≥ 2.0 × ATR(t−1) | **either side** (absolute value) |
| `vol_regime` | ATR now / ATR at entry ≥ 1.5 or ≤ 0.67 | either side |
| `funding` | a paid settlement ≥ 3× the backtest's assumption within 9h | cost |
| `calendar` | a scheduled event with impact ≥ 0.8 inside the next bar | event |
| `mechanics` | the journal trade is absent; the venue SL differs from the package by more than 0.25 ATR | plumbing |

Cooldown: at most one review per closed bar of the leg's timeframe (default 2h). `giveback` and `mechanics` are
exempt. Not evaluated: `mechanics_venue_tp`, `vol_regime_cell`.

**What is missing, against practice:**
1. **No time-based clock below 24h.** A trade sitting between −1R and +1R with no market event is never reviewed. The
   manager observed overnight on 2026-10-28 that hourly LTR passes found "nothing due" across 11 open packages every
   hour (manager-measured; not re-observed here). That is what an event-only, favourable-side trigger set produces when
   trades are in the dead zone.
2. **No adverse-side R trigger** (−0.5R, −0.75R), **no stall or time trigger**, and **no momentum or level trigger**.
   `swing` and `vol_regime` are symmetric and can catch a sharp adverse bar. A slow bleed toward the stop is not caught.
3. **The favourable side is over-weighted.** Four of the ten triggers fire only in profit. Yet the disposition-effect
   evidence says the costly human error is *holding losers and cutting winners* [S1, S2]. And whether cutting losers
   helps depends on the return process [S4, S30]. So adverse-side reviews are where both the risk and the information
   are. They must also be graded, because practice says intervention can destroy value (§ A.3).

### E.2 What practice uses for our holding times

| leg timeframe | practice anchor | proposed clock | proposed triggers |
|---|---|---|---|
| **5m–15m** (scalps) | Automated, MM-like inventory control. Humans handle exceptions only [S23, S13]. Event-triggered prop action [S15] | A **deterministic or ML pre-screen every closed bar**. Claude only on flagged exceptions, via the per-trade short-hold lane (DESK-SHORT-HOLD-LANE, ~$0.14 per decision measured by the manager; PRs #20559/#20560 held) | adverse −0.5R; stall (bars_held ≥ the leg's median winning duration with MFE < +0.5R); momentum flip; swing |
| **1h–4h** | A fixed clock at the position's bar close plus event action. CTA practice re-evaluates on a fixed clock [S7]; prop acts on events [S15] | **Pre-screen every closed bar of the leg.** Claude on flagged bars, batched per wake | current set **plus** adverse −0.5R and −0.75R (first crossing each); stall; momentum flip (close crosses the leg's own trend reference against the position, or the entry model re-scores below threshold); level touch (a packet level such as a prior swing or VWAP); vol_regime |
| **1d** | A CTA daily clock [S7, S8] | **Daily pre-screen at the bar close.** The existing 24h floor becomes the clock | current set plus adverse and stall |

### E.3 Keep cost bounded: three tiers (proposed)

- **Tier 0, due gate (exists, free).** The deterministic triggers, extended with the adverse, stall, momentum and level
  triggers above.
- **Tier 1, pre-screen (new, near-free).** On every closed bar of every open package, price the alternatives (hold,
  tighten to k·ATR, close, partial) from the leg's own Stage-0 history. `scripts/research/live_review_outcomes.py`
  already prices options this way for the review. Escalate to Claude only when (a) a Tier-0 trigger fires, or (b) the
  best alternative beats hold by more than a registered threshold net of cost. Later, an ML student replaces the
  pricing rule (ML programme § G.2).
- **Tier 2, Claude (exists).** **Batch** every escalated package into one session per wake, and review each package
  once for all the accounts carrying it (already the skill's package-level rule).
- **Budget arithmetic (INFERRED from the manager's numbers):** 11 open packages × 24 hourly bars = 264 checkpoints a
  day. At $0.25–0.35 per Claude review, reviewing every bar would cost ~$66–92 a day, and practice says most of those
  reviews should end in "no action" (T5). At a 5–10% escalation rate, it is ~$3–9 a day. Batching cuts it further. The
  escalation rate is a registered parameter, measured weekly.

### E.4 Grade each trigger type, so we learn which ones add value (proposed)

- **Record the trigger type on every review row**, including Tier-1 escalations and reviews that took no action.
- **Per trigger type, report:** action rate; mean paired dR of the actions taken vs hold-to-bracket, net of the full
  cost stack; and the same statistic for a **matched random checkpoint control**. For each fired trigger, price the
  same action rule at a random non-trigger checkpoint of a comparable open package [T1].
- **Rule (registered before the first read):** a trigger type whose actions do not beat both hold and its random
  control after a registered n (computed from the measured sd of paired dR, as in RQ-20261027-8b01-03) is demoted to
  pre-screen-only. It is not deleted: the data is kept (off the trade path is not off the data path). A trigger that
  beats both is kept, and its threshold becomes a candidate for tuning.
- **Separate the reviewer's value from the trigger's value.** Compare Claude's action to the Tier-1 pricing rule's
  recommendation at the same checkpoint. If Claude never beats the rule, the rule should act alone (T1, M9).
- **Cadence:** weekly, in the ML-FRONTIER-PREP lane's practice refresh (frontier-research § "Practice & methodology
  refresh") and in `/performance-review`'s desk section.

---

## F. What we are doing differently from practice, and is that justified

| # | What we do | What practice and evidence say | Justified? |
|---|---|---|---|
| 1 | Tested management as **one check-in at +1R** (n=176, 4 legs) | No practitioner source uses a fixed R milestone as *the* policy. Trend practice is a vol-scaled trail or continuous re-evaluation [S7, S9, S10, S11]. Prop practice is event-triggered [S15] | **No.** Replace with the § G.1 factorial. The +1R FAIL closes only that configuration |
| 2 | Entry-only test with **fixed brackets** | Exits can dominate outcomes. The random-entry harness exists precisely to separate them [S17] | **Partly.** Valid as an entry test. It says nothing about management |
| 3 | **TP doctrine**: a real predictive TP at entry on every leg, moved with the prediction | Trend practitioners use no fixed target and let the trail work. Targets are for mean reversion [S9]. OU theory derives optimal targets for mean-reverting spreads [S25] | **Justified for mean-reversion legs. Unproven for trend legs.** A replay arm "TP far, trail does the work" should measure the cost of the doctrine on trend legs. Any live change is Tier 3 and operator-owned; this lane proposes a *measurement* only |
| 4 | **An LLM (Claude) makes in-trade decisions** on live demo books | No documented major firm lets an LLM manage live positions. LLMs are used for research and productivity [S32, S37]. Live LLM trading evidence is negative to mixed [S21, S22] | **Justified only as designed**: a teacher-label generator, graded on outcomes, with a matched random control, at demo size. **Not justified** as a presumed source of edge |
| 5 | **1–2-trade mechanical soak**, edge decided offline | House capital catches broken models, not significance [S40]. Short paper trading cannot separate a modest edge from luck [S41]. Treat history as having no true OOS and do not tweak on live results [S20] | **Yes.** Consistent with practice |
| 6 | **Teacher agreement never gates the student**; gate on OOS net R | Grade on outcomes, not on imitation [S1, S39] | **Yes.** Go further: label from priced alternatives (§ B.6) |
| 7 | **Pre-registered decision rules** enforced by a guard; trial ledger; holdout before promotion | Arnott et al., Man AHL board, Harvey [S20, S40, S48]. Pre-analysis plans beat bare registration [S49] | **Yes, and stronger than most firms.** Residue: fix transforms and windows in the plan |
| 8 | **No self-halting**; an account-level daily DD switch (keep open, block new), armed per account | Prop desks stop a trader for the day at a 25–30% give-back [S16]. Bridgewater keeps a human kill switch [S36]. Market makers flatten into the close [S23] | **Yes.** The DD switch *is* the stop-for-the-day practice, applied per account. The difference (no pipeline halts) is an operator decision |
| 9 | **Partial close at a fixed 50%** in the desk's action enum | No evidence that partials add expectancy. They reshape the distribution [S26] | **Unproven.** Keep it as an arm, not a default |
| 10 | Desk check-in **hourly plus event triggers** | CTAs: a fixed daily clock. Prop: continuous watching with event-triggered action. MMs: continuous [A.1] | **Reasonable for 15m–1h legs**, if the clock is the trade's own bar and the action rate is measured (§ A.4.4) |
| 11 | ML capacity **78% GBDT** (2026-10-11 measurement, frontier skill) | Documented firm ML is diverse: bandit routing, deep RL hedging, meta-labelling [S31, S35, S19] | **Partly.** The diversity check exists. Exit and management models are where sequence and RL methods have documented use |
| 12 | **The LTR reviews on favourable-side and market events only.** No clock below 24h, no adverse R or stall trigger (§ E.1) | Fixed clock at the position's bar plus event-triggered action [S7, S15]. Losers are where the human error and the information are [S1, S2] | **No.** Proposed redesign in § E (Tier 2, row `LTR-PRACTICE-REDESIGN`) |
| 13 | **Model promotion measures predictive lift over a constant, with gross labels** (§ C.4) | Decision value net of cost vs rules and random, deflated for selection [S1, S20, S45] | **No.** Row `ML-TRAINING-PRINCIPLES-GAPS` |
| 14 | **Weekly frontier scan:** one full run in three weeks, the rest partial, the strategy half never run, and practice and methodology never covered (§ G.3) | Weekly outside-evidence refresh [R6] | **No.** Skill amended (Practice & methodology refresh). Row `FRONTIER-SCAN-COMPLETENESS` |

---

## G. Recommended designs [TRADING · MODEL · RESEARCH-OPS]

### G.1 The desk's first management test (for lane `DESK-LIFECYCLE-S0`)

A **paired factorial on fixed entries**, D-S0 masked blind replay, net of the full cost stack, pre-registered.

- **Entries (factor E), held fixed across all management arms:** E1 strategy entries (committed trades of the
  replayable legs); E2 matched random entries (same symbol, side, hour-of-day and ATR decile; the existing
  `desk_grade.py` random-baseline machinery); E3 desk entries as they accrue. *Precedent: random-entry harness [S17].*
- **Management (factor M), each applied to every entry:**

| arm | rule | precedent |
|---|---|---|
| M0 | hold to the recorded bracket (control) | — |
| M1 | **matched random intervention** for each active arm: same count and type of actions, at random check-ins | random-sell counterfactual [S1] |
| M2 | Chandelier trail, k ∈ {2, 3} × ATR(22) off the running extreme | [S10] |
| M3 | channel exit, N ∈ {10, 20} bars | Turtles [S11] |
| M4 | **re-score exit**: re-run the leg's entry model at each check-in; exit when the signal flips or falls below the entry threshold (only where the entry model is replayable point in time) | continuous CTA [S7] |
| M5 | time stop: exit at T bars if MFE < +0.5R; T = the leg's median winning duration, fixed from the training folds | [S27, S28]; contested |
| M6 | breakeven at +1R (known-weak; replicates the earlier result inside the new frame) | [S9] says it is "nothing special" |
| M7 | 50% partial at +1R, Chandelier on the rest | [S26]; unproven |
| M8 | Claude at **clock C** (every bar close of the trade's timeframe) **plus event triggers**: ±0.5R / ±1R / +2R crossings, ATR(14)/ATR(100) ratio crossing 1.5 or 0.67, a touch of a packet level, momentum sign flip | prop practice [S15]; `novel` as an LLM |
| M9 | Claude, event triggers only | [S15]; `novel` as an LLM |

- **Cadence (factor C) for M8 and its M1 control:** every bar vs every 4 bars vs event-only. That is the
  "check-in policy as a factor" the dispatch asked for.
- **Strata, registered:** trend vs mean-reversion leg (from the leg's Stage-0 lag-1 return autocorrelation or variance
  ratio, computed on training folds only) × volatility tercile at entry. *Precedent: [S4, S5, S30].*
- **Primary statistic:** paired dR = net R(arm) − net R(M0) per trade, net of the full cost stack, bootstrapped by
  trade. Also net R per capital-day (§ C.2.5). **Secondary:** capture ratio (realised / MFE), giveback from peak, MAE,
  and action rate. **Report lift separately for "acted" and "held" decisions** (finding 5).
- **Pass:** an arm passes only if it beats **both M0 and its M1 matched random control**, with Holm across arms
  within the family, on the training window, and then **re-passes once on a fresh window** (`RESEARCH-CONFIRM-FRESH-WINDOW`).
  Count every arm and parameter in the trial ledger.
- **Power:** compute the MDE from the measured sd of *paired dR*, not of raw R (paired differences are usually far
  less variable). The 8b-03 unit's honest limit (n=45 decision points, MDE 0.267R) shows that the number of decision
  points binds. Every check-in of every trade is a decision point for M8, which multiplies n. CV and the bootstrap must
  cluster by trade.
- **Cost of Claude arms:** on-plan only (no API credits). Size the M8/M9 sample to the plan budget and run the rule
  arms on the full population (they are free).

### G.2 The ML trade-management programme (for lane `ML-PROGRAMME-PLAN`)

1. **Panel:** one row per (trade, check-in), with point-in-time features (R so far, MFE/MAE, bars held, ATR ratio,
   distance to levels, momentum, regime, time of day) and **the priced outcome of every action** (hold, close,
   tighten to k·ATR, partial) on the real path, net of cost. This is a triple-barrier-style label from each check-in
   state [S50].
2. **Stage A, supervised meta-model over the best G.1 rule arm:** predict dR(action) − dR(rule) and act only where the
   predicted gain clears the cost-adjusted threshold. GBDT baseline plus one sequence model (family diversity).
   Calibrate the probabilities [S19].
3. **Stage B (only if A passes):** an RL policy *initialised from A* [S38]. Never RL from scratch.
4. **Claude's role:** a source of hypotheses and features (what it saw that the rule did not), plus outcome-filtered
   demonstrations. Never the regression target (§ B.6). Measure "does adding Claude's action as a feature improve A
   out of sample?" That question decides whether the teacher carries information.
5. **Validation:** group-by-trade purged CV with an embargo, CPCV for a distribution of OOS results, DSR via the
   trial ledger, a fresh-window confirmation [S45, S46, S50].
6. **Ladder:** student shadow → advisory → drives (desk design § 4.2), each step gated on paired dR vs M0 **and** vs
   the best rule arm **and** vs the matched random control, OOS, net of cost. Then live monitoring with a CUSUM
   (`LIVE-DECAY-MONITOR`).

### G.3 Our research-ops process

1. **A "practice precedent" field on every new unit and design arm** (`source:` URL + tag, or `novel`). This answers
   the operator's ask mechanically. A guard can come later; the field comes first.
2. **A standard control set for intervention tests**: M0 hold, M1 matched random, best static rule selected without
   the test folds. Templated from RQ-20261027-8b01-03.
3. **Pre-analysis plans, not only rules**: transforms, windows, exclusions and strata fixed at registration [S49].
4. **Finish the queued benchmark rows**: `LIVE-DECAY-MONITOR` first, then `PROMOTION-CORRELATION-CHECK` and
   `RESEARCH-OUTCOME-METRICS`.
5. **A standing WEEKLY practice and methodology refresh** (operator, 2026-10-28: "not one-off … at least once a
   week"). It is now a track in `.claude/skills/frontier-research/SKILL.md`, run on Wednesday after the weekly reset
   in the ML-FRONTIER-PREP lane of the "Weekly review prep" routine (no new cron). It has two output sections,
   TRADING and MODEL. It refreshes a dated `docs/research/practice-review-*.md`, revises the canonical list in
   `docs/reference/trading-and-model-practice-principles.md`, re-checks the desk tests, the LTR triggers and the ML
   training and evaluation design against it, and files every gap as a row or unit.
6. **Has the weekly frontier scan actually been running?** Not fully (MEASURED from the repo, 2026-10-28):
   - 2026-10-11: a full scan (`docs/research/frontier-scan-2026-10-11.md`; `comms/ml-plan/20261011T1900Z.json` has a `frontier` block).
   - 2026-10-14: partial. Brief § 3 says HF Hub plus web search; GitHub, Kaggle and SSRN not checked (`docs/reviews/2026-10-15-weekly-walkthrough-ml.md`).
   - 2026-10-18: partial. `comms/ml-plan/20261018T0700Z.json` frontier block, "not a full scan", 1 source.
   - 2026-10-21: partial. About 3 sources, "No strategy-frontier ideas … no pass on the strategy half was scoped" (`docs/reviews/2026-10-21-weekly-walkthrough.md` § 4).
   - Sunday 2026-10-25 (the old `/ml-review` step-9 slot): no frontier record found (`comms/ml-plan/20261025T0000Z-ML-READ-1025.json` has no `frontier` block; the probe found the block in the 10-11 and 10-18 records, so it can find positives). The next run is due Wednesday 2026-10-28 ~18:53Z. (10-11 and 10-18 were Sundays; 10-14 and 10-21 were the Wednesday prep lanes.)

   So: one full scan in about three weeks; the strategy half never ran; practice and methodology were never in scope.
   Filed as row `FRONTIER-SCAN-COMPLETENESS`.

---

## 9. Sources

Tag key: **[ACAD]** peer-reviewed or a working paper with a stated sample · **[PRAC]** a named practitioner or the
firm's own publication · **[VEND]** a vendor, educator, trade press or secondary summary. "Read:" says what this lane
actually read.


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
- [S31] Man AHL ML execution router and risk oversight. https://www.risk.net/awards/5368836/quant-hedge-fund-of-the-year-man-ahl · https://www.risk.net/asset-management/6532696/robo-traders-not-so-different-from-us-says-man-ahl-risk-chief · https://www.man.com/ahl [PRAC via trade press; read: search excerpts]
- [S32] Man Group, "What AI can do for alpha" (AlphaGPT). https://www.man.com/insights/what-ai-can-do-for-alpha [PRAC; read in full]
- [S33] Hedgeweek on AlphaGPT signals approved for live trading. https://hedgeweek.com/news/man-group-deploys-agentic-ai-for-quant-signal-discovery · https://aistreet.beehiiv.com/p/inside-man-group-s-alphagpt [VEND]
- [S34] JPMorgan LOXM. https://marketsmedia.com/j-p-morgan-ai-trading-global/ · https://www.bestpractice.ai/ai-case-study-best-practice/jpmorgan's_new_ai_program_for_automatically_executing_equity_trades_in_real-time_out-performed_current_manual_and_automated_methods_in_trial [VEND / trade press]
- [S35] Buehler, Gonon, Teichmann & Wood, "Deep Hedging", *Quant. Finance* 19(8) 2019. https://arxiv.org/abs/1802.03042 · production use: https://www.risk.net/node/7936936 [ACAD; PRAC interview]
- [S36] Bridgewater AIA Labs ML fund. https://www.thewealthadvisor.com/article/bridgewater-assc-looks-future-new-automated-ai-fund · https://www.hedgeco.net/news/03/2026/bridgewater-dalios-principles-to-algorithmic-intelligence-the-road-to-5billion.html [VEND / trade press; accounts conflict]
- [S37] Hedge-fund LLM use and Griffin's statement. https://www.bloomberg.com/news/articles/2024-08-14/hedge-funds-battle-to-turn-chatgpt-from-intern-to-analyst · https://news.bgov.com/new-york-brief/griffin-says-genai-fails-to-help-hedge-funds-beat-markets-1 · https://resonanzcapital.com/insights/ai-use-by-hedge-funds-made-tangible-from-lego-bots-to-alpha-assistants [trade press]
- [S38] Wang, Ślepaczuk & Sakowski, deep RL exit timing for SPX short straddles, arXiv 2610.13126. https://papers.cool/arxiv/2610.13126 [ACAD preprint; read: excerpt]
- [S39] Imitation-learning survey (behaviour cloning, DAgger), arXiv 2309.02473. https://arxiv.org/pdf/2309.02473 · https://web.stanford.edu/~srliu/homepage/notes/cs224r/02-imitation-learning/ [ACAD]
- [S40] Man AHL Academic Advisory Board, "Overfitting and its impact on the investor" (2015), as summarised in our benchmark. docs/research/research-ops-benchmark-2026-10-16.md § 1 S9 [PRAC; not re-read by this lane]
- [S41] Forward / paper-trading confirmation. https://www.luxalgo.com/library/concept/forward-paper-trading-confirmation.md [VEND]
- [S42] Wiecki, Campbell, Lent & Stauth, "All that Glitters Is Not Gold" (Quantopian, 2016; SSRN 2745220). https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/ · https://www.cxoadvisory.com/big-ideas/in-sample-vs-out-of-sample-performance-of-888-trading-strategies [ACAD; secondary summaries]
- [S43] McLean & Pontiff, "Does Academic Research Destroy Stock Return Predictability?", *JF* 2016. https://ivey.uwo.ca/media/3775549/pontiff.pdf [ACAD; abstract]
- [S44] Bank of England on AI and herding in trading. https://www.pymnts.com/news/artificial-intelligence/2025/bank-england-warns-higher-market-volatility-from-ai-driven-trading/ · https://BNNBloomberg.ca/ai-risks-amplifying-herd-like-behavior-in-trading-boe-says-1.2069897 [regulator via press]
- [S45] Bailey & López de Prado, "The Deflated Sharpe Ratio", *JPM* 40(5) 2014. https://papers.ssrn.com/abstract=2460551 [ACAD]
- [S46] Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting", *J. Comp. Finance* 20(4). https://papers.ssrn.com/abstract=2326253 [ACAD]
- [S47] Harvey, Liu & Zhu, "… and the Cross-Section of Expected Returns", *RFS* 29(1) 2016. https://www.nber.org/papers/w20592 [ACAD]
- [S48] Harvey, "The Scientific Outlook in Financial Economics", *JF* 72(4) 2017. https://people.duke.edu/~charvey/Research/Published_Papers/P131_The_scientific_outlook.pdf [ACAD]
- [S49] Brodeur, Cook, Hartley & Heyes, "Do Pre-Registration and Pre-Analysis Plans Reduce p-Hacking and Publication Bias?" https://siepr.stanford.edu/publications/working-paper/do-pre-registration-and-pre-analysis-plans-reduce-p-hacking-and [ACAD; abstract]
- [S50] Purged CV, embargo and CPCV (López de Prado, *Advances in Financial Machine Learning*, 2018). https://en.wikipedia.org/wiki/Purged_cross-validation · https://fynance.readthedocs.io/en/latest/generated/fynance.data.combinatorial_purged_cv.html [ACAD/PRAC via secondary; AFML itself not re-read]
- [S51] Bailey & López de Prado, "Stop-outs under serial correlation and the triple penance rule", *J. Risk* 2015. https://www.risk.net/journal-of-risk/2435335/stop-outs-under-serial-correlation-and-the-triple-penance-rule · https://escholarship.org/content/qt758637dr/qt758637dr.pdf [ACAD; abstract + secondary]
- [S52] Xiao, Sun, Luo & Wang, "TradingAgents", arXiv 2412.20138. https://arxiv.org/abs/2412.20138 [ACAD preprint]
- [S53] LiveTradeBench, arXiv 2511.03628. https://arxiv.org/abs/2511.03628 · StockBench https://arxiv.org/abs/2510.02209 · AI-Trader https://arxiv.org/abs/2512.10971 [ACAD preprints]
- [S54] Lopez-Lira & Tang, "Can ChatGPT Forecast Stock Price Movements?", arXiv 2304.07619 (v6). https://arxiv.org/abs/2304.07619v6 [ACAD; abstract]
- [S55] Glasserman & Lin, "Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis", arXiv 2309.17322. https://arxiv.org/abs/2309.17322 · Look-Ahead-Bench https://arxiv.org/abs/2601.13770 · Gao, Jiang & Yan https://arxiv.org/abs/2512.23847 [ACAD]

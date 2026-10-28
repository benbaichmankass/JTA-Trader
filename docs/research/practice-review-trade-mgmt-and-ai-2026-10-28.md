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

---

## 10. Weekly practice refresh — 2026-10-28 (lane `PRACTICE-REFRESH`, session_01AFoLuJpe2bJTErX7QGAmaS)

> Tier 1, read-only on production. Dispatched by Manager Session 2026-10-27a. **No units queued** (proposals only, per
> dispatch); two runtime bugs found while measuring are filed as checklist rows (§ 10.5). No config, src or Tier-2/3 change.
> This refresh ran the same day as the baseline (§§ 0–9), so it adds only **deltas**: new sources `[S56]`–`[S64]`, the
> re-check of live designs, and the two measurements the dispatch asked for.

### 10.1 Previous refresh read (the baseline's gaps and their state on `main` 37646efca)

| Gap filed by the baseline | Row | State | Note |
|---|---|---|---|
| Matched-random control set for intervention tests | `RESEARCH-INTERVENTION-CONTROL-SET` | `landed_unproven` | `scripts/research/intervention_controls.py` exists; no graded result observed yet |
| Desk lifecycle factorial | `DESK-LIFECYCLE-S0` | `in_flight` | — |
| ML training/eval vs M1–M10 | `ML-TRAINING-PRINCIPLES-GAPS` | `done` (#20869 merged a65ef0085) | cost-net labels and the gate are merged; the row says setup_candidates datasets are frozen gross and **0 exit_candidates datasets** exist, so no cost-net label has reached a model (PI-20261028-V8KBRR5H-0004) |
| One ML programme | `ML-PROGRAMME-PLAN` | `landed_unproven` | — |
| LTR practice redesign (pre-screen triggers) | `LTR-PRACTICE-REDESIGN` | `done` | the 4 pre-screen blocks are live in `config/live_trade_review.yaml` |
| Weekly frontier completeness | `FRONTIER-SCAN-COMPLETENESS` | `queued` | first refresh, so the two-refresh escalation rule does not fire yet |
| *(older, re-observed)* exit heads outside the registry | `BL-20260908-FOUR-EXIT-HEAD-ARTIFACTS-ARE-ABSENT-FROM-THE-REGISTRY…` | `queued` since 2026-09-08 | **Raised to the manager** (§ 10.4 M-G1): re-measured today, still true |

### 10.2 Sources checked this pass (what was actually read)

**TRADING** (9 searches, 5 fetches):
- [S56] Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert, "The Impact of Volatility Targeting", *JPM* 45(1) 2018, 14–33. https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf [ACAD/PRAC (4 of 6 authors at Man); **read: full text**] — 60+ assets, daily data from 1926. Vol scaling raises Sharpe for equities and credit, and for 60/40 and risk-parity portfolios. The effect is "negligible" for bonds, FX and commodities. It "consistently reduces the likelihood of extreme returns" across all assets. Mechanism: the leverage effect adds a momentum overlay. Sharpe is reported gross and net (costs 0.5–3.5 bp of notional); results are "very similar on a net basis".
- [S57] Longmore (Robot Wealth), "Reduce trading costs … with the no-trade region", 2025-06-09. https://robotwealth.com/reduce-trading-costs-and-boost-profits-with-the-no-trade-region-strategy/ [PRAC/VEND (firm sells courses); **read: full article**] — on a 7-ETF daily-rebalanced book, after-cost Sharpe went from about 0.7 to about 0.9 and turnover from about 50% to about 5%/yr. Choose the buffer on after-cost Sharpe, then widen it 25–50%, because the backtest optimum is too narrow. Evidence: n = 1 strategy.
- [S64] Martin & Schöneborn (mean-reverting assets, via search snippet): the optimal buffer width scales with the cube root of the cost [ACAD; **secondary only**].
- [S61] Donnelly, Lin & Lorig, "Optimal Liquidation of Perpetual Contracts", arXiv 2601.10812 (2026-01). https://arxiv.org/abs/2601.10812 [ACAD preprint; **abstract**] — closed-form liquidation schedule with funding payments in the objective, beside temporary and permanent impact and inventory risk.
- [S62] Sadaqat & Butt, "Stop-loss rules and momentum payoffs in cryptocurrencies", *J. Behavioral & Experimental Finance* 39 (2023). https://ideas.repec.org/a/eee/beexfi/v39y2023ics2214635023000473.html [ACAD; **abstract**] — 147 coins, 2015-01 to 2022-06. Stop-loss momentum beats plain momentum on return, Sharpe and alpha in all market states. The stop rule itself is not stated in the abstract.
- Checked, nothing new kept: Leung & Zhang trailing stop (already S24); setup4alpha 56-exit test (already S28; paywalled, headline only); StoneX / prop-firm trailing-stop explainers (educational, VEND); AdaptiveTrend arXiv 2602.11708 (self-reported Sharpe 2.41; VEND-grade claim, not kept); Carver's netting/buffering posts — **could-not-look** (search returned book listings only; qoppac not reached this pass).

**MODEL** (5 searches, 5 fetches):
- [S58] Zhang et al., "AlphaForgeBench", arXiv 2602.18481 (v2 2026-05-27). https://arxiv.org/abs/2602.18481 [ACAD preprint; **abstract + search snippet**] — LLMs acting as trading agents show "extreme run-to-run variance", even under deterministic decoding (7 models, daily BTC, 5 runs per setting, T = 0 vs 0.7, per snippet). They "flip actions irrationally between adjacent time steps". Single-run benchmarks are therefore unreliable. Proposed fix: LLMs write factors or strategies, and deterministic code executes them.
- [S59] Khatchadourian, "Replayable Financial Agents / DFAH", arXiv 2601.15322 (v4 2026-10-21). https://arxiv.org/abs/2601.15322 [ACAD preprint; **abstract**] — 2,957 recorded executions. In one configuration the decision repeated in 84% of cases but the ordered tool sequence in only 26%. Decision-level and trajectory-level consistency must be measured separately, and determinism is not accuracy.
- [S53, re-read] AI-Trader arXiv 2512.10971 [ACAD preprint; **abstract**] — live and uncontaminated. Of 6 LLMs, most posted poor returns and weak risk management, and "risk control determines cross-market robustness". This strengthens M6; it is not a new source.
- [S63] Kelly, Malamud & Zhou, "The Virtue of Complexity in Return Prediction", *JF* 79(1) 2024, 459–503. https://www.sfi.ch/en/publications/the-virtue-of-complexity-in-return-prediction · https://alphaarchitect.com/complexity-is-a-virtue-in-return-prediction/ [ACAD; **abstract + secondary**] — with shrinkage, models with more parameters than observations out-predict sparse ones on US equity-market returns. A published critique was searched for and **not found** this pass, so it is unconfirmed whether one exists.
- Checked, nothing new kept: purged-CV / CPCV explainers (LuxAlgo, Quantt; restate S50); QuantPedia "why ML funds fail" (restates S18); EvolveTrade arXiv 2609.17632 (3 seeds, performance focus).

### 10.3 Deltas (each is now in the canonical list, dated)

| Track | Principle | Delta | Source |
|---|---|---|---|
| TRADING | **T11 (new)** | Vol-scaled sizing: tails thin everywhere, but Sharpe rises only for risk assets. Evaluate per asset class | S56 |
| TRADING | **T12 (new)** | No-trade buffer around the target. Choose on after-cost results, then widen; it bounds the management action rate | S57, S64 |
| TRADING | T2 strengthened | crypto stop-loss momentum evidence (momentum regime ⇒ stops help), consistent with Kaminski–Lo | S62 |
| TRADING | T3 strengthened | for perps, funding over the hold is part of the exit's cost stack and moves the optimal schedule | S61 |
| MODEL | **M11 (new)** | Measure an LLM's decision repeatability (k ≥ 3 reruns) before grading its edge | S58, S59 |
| MODEL | M6 strengthened | live uncontaminated benchmark: LLM agents mostly fail on risk control | S53 |
| RESEARCH-OPS | R3 tension | "keep models simple" weakened as stated; OOS gates decide, not parameter count. Nothing removed | S63 |

No principle was removed.

### 10.4 Our live designs vs the list (every gap names its principle)

Population: the designs as they stand on `main` 37646efca. Read: `config/live_trade_review.yaml`; the SKILL.md of `live-trade-review`, `trading-desk`,
`exit-refinement`, `performance-review`, `perf-followup`, `health-review` and `ml-review`; `scripts/ci/check_tp_doctrine.py` (re-run); and the live
registry, shadow and trainer status (`/api/bot/ml/{registry,status}`, `/api/bot/shadow/stats`, ~19:05Z).

**TRADING**
- **T-G1 · T9 / TP doctrine — 0 of 77 routings compliant** (re-ran `python3 scripts/ci/check_tp_doctrine.py`. Population: 77 routings, 51 distinct legs,
  every account. FAIL counts by class: real-money entry_tp 2 / tp_revision 5 of 6; prop 6 / 6 of 6; mirror 2 / 4 of 5; paper 30 / 59 of 60.
  TP-REACH-FLOOR: 11 below floor, 9 reachable, 28 unmeasured, of 48 declared). This is not new debt (77 baselined lines), but it is the largest gap against the list.
  A live example from today: `htf_pullback_trend_2h` on bybit_1, package `pkg-73bc56325e5c4db1`, `tp_r: 50.0`.
- **T-G2 · T4 / T12 — the LTR's in-trade triggers are R-denominated, not volatility- or holding-period-denominated.** `r_milestone` (+1R steps), `new_peak`
  (+0.5R), `giveback` (0.5R / 30% of peak), `adverse_r` (−0.5R, −0.75R) and `stall` (`max_peak_r` 0.5) all key on R from entry. Only `swing`, `momentum_flip`
  and `structure_break` use ATR. Carver's point [S9] is that a level relative to entry has no standing for the market. The pre-screen grading (§ E.4) will
  test whether they survive, but **no ATR- or vol-unit variant is registered as a competing arm**, so the grading cannot show that the R form is the one that loses.
- **T-G3 · T7 — per-trade `giveback` remains an in-trade trigger.** The baseline says practice puts giveback limits at the account or day level. It is still
  a hypothesis arm, and it should be graded against `daily_dd_switch`, not only against hold.
- **T-G4 · T12 / R3 — the one-way book drops the opposing leg's intent and keeps no virtual per-leg record.** MEASURED: `mgc_trend_1h` on ib_paper produced 13
  rows in 7 d, all `rejected`: 7 `dry_run_no_order_placed` (`execution:shadow`, before 10-23) and 6 `intent_noop:flip_suppressed_hold_policy: desired long
  opposes current short (qty=14.0)`. The short belongs to `mgc_pullback_1d` (open since 10-19). Its 12 long signals in the window therefore generated no
  outcome data at all. Systematic practice nets at the instrument but tracks each subsystem's notional position. The Carver source for that was **not
  re-read this pass**, so the precedent is PRAC, unverified here. Proposed: a virtual per-leg ledger so a suppressed intent still yields a priced outcome row.
- **T-G5 · T1 — LTR closes still have no matched-random grade on record.** 2 `live_review_close` exits on bybit_1 in 7 d (ict_scalp_eth_15m, ict_scalp_xrp_15m).
  `RESEARCH-INTERVENTION-CONTROL-SET` is `landed_unproven`, so no observed grade exists yet.
- **T-G6 · R3 / demo floor — the demo floor generates far less data than its roster implies** (§ 10.6 (a)): 0 fills on alpaca_paper and 1 on ib_paper in 7 d.

**MODEL**
- **M-G1 · M10 — order-influencing exit heads live outside the registry.** MEASURED: `/api/bot/shadow/stats` lists 4 exit heads scoring
  (`exit-head-ict_scalp-5m-v1`, `exit-head-donchian-1h-v1`, `exit-head-donchian-peak-1h-v1`, `exit-head-ict_scalp-15m-v1`; 145 predictions + 1 insufficient_n in
  the retained 10-24→10-28 window). None is among the 97 registry rows. `src/runtime/exit_head_shadow.py` says E3 shipped, and `trend_donchian.monitor` returns
  the head's verdict, which closes a live position. `config/strategies.yaml` carries `exit_head_action: close` on 3 blocks. The registry's cost-net gate
  (#20869) therefore never sees the models that can close trades. **Already filed 2026-09-08 and still queued after 7 weeks → raised to the manager, not re-filed.**
- **M-G2 · M11 — the desk and LTR recommendations are never re-run for repeatability.** `live-trade-review` and `trading-desk` SKILL.md were probed for
  repeat / determinism / rerun. The only hits are unrelated (an operator EV-vs-variance preference; a desk_write retry). The probe can find a positive: it
  found 3 such hits in performance-review. One snapshot gives one recommendation, which is then applied under MD-TRADE-DESK. [S58] says that recommendation
  may flip on a rerun.
- **M-G3 · M1 / learning — retraining is happening on data that is not growing for the trade-level families** (§ 10.6 (b)). market_features retrains daily.
  setup_candidates (9 models, 65 runs in 7 d) retrains on a dataset the ML-TRAINING row measured as frozen gross (2026-06..08). trade_outcomes and
  conviction_meta have 0 scored predictions. The last cycle (08:22Z) trained 0 models (72 already done).
- **M-G4 · M5 — no deflation in the tuning loop.** `perf-followup` Track 1 re-tests underperformers with a bootstrap percentile (`live_vs_backtest.py`).
  A grep for deflat / DSR / PBO finds 0 hits in perf-followup and performance-review, and 1 in ml-review (the probe finds the ml-review hit, so it can see a
  positive). A re-tuned leg's variant count is not deflated.
- **M-G5 · M7 — the review skills stratify by regime unevenly.** Keyword probe: performance-review 14 hits, perf-followup 10, health-review 0, ml-review 2.
  ml-review's C-checks do not require a regime split of champion vs challenger.

**Review skills (both tracks)**
- **R-G1 · R6 — health-review has no per-leg × floor-account data-generation check.** H5 checks that signal → fill flows **in aggregate**. The 35 silent
  cells in § 10.6 (a), including two outright dead legs, were found by hand. The inverse check (an off-roster leg trading) is filed
  (PI-20260922-E32-…, `routed`); the forward check (an on-roster leg producing nothing, classified quiet or blocked) is not.
- **R-G2 · observability — a strategy builder that raises leaves no audit row.** `splg_trend_long_1d` raises every tick, and `audit_query` shows 0 rows for it
  (§ 10.5), so any audit-based liveness check reads a dead leg as quiet.

### 10.5 Filed this lane (checklist rows; builds, not research units)

- `IB-PAPER-ETF-LEGS-NO-ROWS` (Tier 2, queued, roadmap L-LADDER): spy/qqq/iwm_trend_long_1d and tlt_pullback_1d have **never** journaled an ib_paper row
  (fill or rejection) in ids 3767..6766 (2026-07-21..10-28). The same legs journal 34 rows on the Alpaca accounts. Config is clean; the root cause is open
  (journald has no entries from 10-06).
- `SPLG-TICKER-DEAD` (Tier 3, queued, L-LADDER): SPLG → SPYM on 2025-10-31 (State Street AP notice). Alpaca returns empty bars and the builder raises every
  tick. Exact proposed config change is on the row; also R-G2 and the `trend_donchian_1h` roster-hygiene note.

### 10.6 Measurements

**(a) DEMO-FLOOR DATA GENERATION.** Source: `/api/diag/journal?table=trades`, paged 3 × 1000 (`envelope=1`, stable id key; total_rows 6766). The 7-day
window (2026-10-21T19:00Z → 2026-10-28T19:00Z) lies inside page 0, whose oldest row is 2026-09-14. **Population: 57 leg × floor cells** from
`config/accounts.yaml` (re-parsed): bybit_1 31, alpaca_paper 15, ib_paper 11. Each quiet leg was then classified from `audit_query?strategy=<leg>` (7 d, latest
200 rows, plus long/short filters). A `rejected` row is not a fill.

| Account | Cells | Cells with ≥1 row | Fills (closed + open) | Rejected rows |
|---|---|---|---|---|
| bybit_1 | 31 | 19 | 20 | 7 |
| alpaca_paper | 15 | 1 | **0** | 3 |
| ib_paper | 11 | 2 | **1** | 14 |

Quiet or zero-fill cells, classified:
- **BLOCKED**
  - ib_paper spy/qqq/iwm_trend_long_1d and tlt_pullback_1d: no ib_paper row ever; row `IB-PAPER-ETF-LEGS-NO-ROWS`.
  - alpaca_paper `splg_trend_long_1d`: dead ticker; row `SPLG-TICKER-DEAD`.
  - ib_paper `mgc_trend_1h`: signals long, but the long is suppressed by the netted `mgc_pullback_1d` short (by design, but it produces no data; T-G4).
  - alpaca_paper `slv_trend_1h`: `execution:shadow` until 10-23, quiet since.
  - bybit_1 `risk_refused … available_usd=0.00` on 10-20 (2 legs) and 10-27 (3 legs: claude_desk, ict_scalp_5m, trend_donchian_eth). **Cleared:** none
    since 10-27 18:07Z, and 7 bybit_1 entries on 10-28 (`BYBIT1-MARGIN-STARVED` done). The sizing-basis question stays open on
    `BYBIT1-SIZING-COLLATERAL-BASIS` (Tier 3, queued).
  - bybit_1 `trend_donchian_sol`: 1 rejection `slice_ledger_divergent` on 10-28.
- **QUIET-BY-DESIGN** (the eval reasons are all "no setup" / "no breakout" / "regime not chop" / "no squeeze release"; no error reason seen):
  - alpaca_paper: spy, qqq, iwm, tqqq, qld and scha `_trend_long_1d`; tlt, ief, slv, gdx and iaum `_pullback_1d`; uso_trend_1h. gdx and iaum hold an open
    short from 10-16, and spy an open long from 08-03.
  - ib_paper: mes_trend_long_1d; mgc_pullback_1d and mhg_pullback_1d (both hold open shorts); gld_pullback_1d (on ib_paper since 10-25).
  - bybit_1: the 4h donchians (ada, avax, sol, xrp, xrp_adx25), squeeze_breakout_4h, fade_breakout_4h and fvg_range_15m (regime not chop), turtle_soup, and
    ict_scalp_sol_5m and ict_scalp_sol_15m (signals present, last fill 09-27 / 10-01).
  - **Retired, but still rostered:** bybit_1 `trend_donchian_1h` (`enabled: false` by record; it still sits in the `strategies:` list).
  - `claude_desk` on alpaca_paper and ib_paper: added 10-27 (`DESK-PAPER-ACCOUNTS`, `landed_unproven`). No desk row on either yet; too new to call blocked.

**(b) IS IT LEARNING?** Source: `/api/bot/ml/registry` (trainer mirror, age 72 s, 97 rows), `/api/bot/ml/status`, `/api/bot/shadow/stats` (retained
window 2026-10-24 → 10-28, 18,232 records), read ~19:05Z. The trainer-VM relay read (#20971) was queued behind the ML-REVIEW lane's pull. It returned at
19:09Z; its dataset read is § (b2) below (its own registry parse is not used: the `runs[]` keys differ from the script's guess). Population: 97 registered models by `dataset_ref.family`. "Runs 7 d"
counts registry `runs[]` entries since 2026-10-21T19Z.

| Family | Models | Stages | Retrained 7 d (models / runs) | New models 7 d | Scored live (shadow log) | Changes an order |
|---|---|---|---|---|---|---|
| market_features | 72 | 49 cand · 19 shadow · 3 advisory · 1 research | 52 / 364 | 0 | 22 heads, 16,213 preds, varying | 3 advisory (regime) |
| setup_candidates | 9 | 9 cand | 9 / 65 | 0 | 0 | no |
| conviction_meta | 4 | 4 cand | 3 / 21 | 0 | 0 | no |
| trade_outcomes | 4 | 4 cand | 1 / 7 | 0 | 0 | no |
| execution_quality | 1 | 1 shadow | 1 / 7 | 0 | 1 head, 1,874 preds, **constant** | no |
| setup_labels | 3 | 3 cand | 0 / 0 (last 10-21) | 0 | 0 | no |
| setup_labels_audit | 1 | 1 cand | 1 / 7 | 0 | 0 | no |
| account_context · corpus_panel · market_sequences | 1 · 1 · 1 | cand | 0 (last 07-03 .. 07-26) | 0 | 0 | no |
| *(not in registry)* exit heads | 4 | — | — | — | 3 varying + 1 insufficient_n, 145 preds | **yes — `exit_head_action: close`** (M-G1) |

Rows produced (H1) in the same 7 d: 60 trade rows, of which 28 closed, 5 open and 27 rejected. 39 trades closed (by `closed_at`) across all accounts
(bybit_1 20, bybit_portfolio 8, bybit_2 7, ib_paper 2, alpaca_paper 2). Trainer: `ict-trainer.timer` active, 2 cycles in 24 h, last cycle 08:22Z
`complete_with_refusals`, **trained 0** (72 already done), 98 dataset builds ok / 0 failed, 3 refusing manifests, `training_staleness`: 5 stale, 2 never trained.
**Reading:** the chain is alive for the market-bar regime family (retrain → shadow/advisory → orders). For every trade-level family (setup, conviction,
trade outcome) it breaks at **H5 scored**: they retrain, but nothing scores live and nothing changes an order. The order-influencing exit heads sit
outside the registry. A first broken hop at H3/H4 for cost-net labels is already measured by `ML-TRAINING-PRINCIPLES-GAPS` (0 exit_candidates datasets).

**(b2) Datasets on the trainer VM** (`trainer-vm-diag` #20971, run 40750315630, 19:09Z; `datasets-out/<family>`: file count, rows from
parquet metadata or line count, newest file mtime). Population: 23 dataset directories.

| Dataset | Rows | Newest file | Reading |
|---|---|---|---|
| market_features / market_raw | 4,324,903 / 6,452,149 | 2026-10-28 | growing; feeds the scoring regime heads |
| trade_outcomes · setup_labels | 2,909 · 2,909 | 2026-10-28 | rebuilt daily, but no model in these families scores live |
| conviction_meta | 1,644 | 2026-10-28 | rebuilt; 4 candidates, 0 scored |
| claude_judgments | 627 | 2026-10-28 | the desk/teacher record exists as a dataset; no registry family trains on it |
| **review_journal** | **0** | 2026-10-28 | **the LTR review rows reach no dataset**: H2 broken for the live-review source |
| **setup_candidates** | 42,328 | **2026-08-04** | **frozen 12 weeks**, yet 8 of its experiment dirs show 8 runs each in 7 d: retraining on unchanged data (M-G3) |
| **exit_head** | 166,793 | **2026-09-07** | **frozen 7 weeks**, while those heads can close trades (M-G1) |
| embeddings · corpus_panel · corpus_embeddings | 98,601 · 6,027 · 5,964 | 2026-07-01 .. 07-04 | frozen; their models last ran in July |
| backtest_results · backtest_trades*.db | 0 | — | empty |

Trainer services at 19:09Z: `ict-trainer.service` inactive (timer-driven, as designed); `ict-trainer-publish`, `-forecast` and `-git-sync` timers firing.
**Reading, refined:** across the four sources ML-PROGRAMME § 7 names, the first broken hop is:
- desk decisions: H3 (in a dataset: yes, `claude_judgments` 627), H4 (trained) **0**;
- live-review rows: H2/H3, **0 rows** in `review_journal`;
- trade closes: H4 yes (trade_outcomes, conviction_meta), H5 (scored) **0**;
- exit heads: H3 frozen since 09-07, and H6 promoted *outside* the registry.

### 10.7 Gaps for Thursday (proposed; nothing queued by this lane)

| # | Track | Gap | Principle | Proposed disposition |
|---|---|---|---|---|
| 1 | TRADING | ib_paper ETF legs silently produce no rows | R3 / demo floor | **Filed** `IB-PAPER-ETF-LEGS-NO-ROWS` (Tier 2): root-cause on the next US-open signal |
| 2 | TRADING | SPLG dead ticker | demo floor | **Filed** `SPLG-TICKER-DEAD` (Tier 3): operator yes/no on SPLG → SPYM |
| 3 | TRADING | A suppressed opposing intent leaves no outcome record | T12, R3 | Propose build row `VIRTUAL-LEG-LEDGER`: price each suppressed intent as a virtual position (no order), so netting stops costing data |
| 4 | TRADING | LTR triggers in R units only | T4, T12 | Propose a research unit: pre-registered ATR-unit twins of adverse_r / stall / giveback, graded beside the R form on the same prescreen.jsonl checkpoints |
| 5 | TRADING | Per-trade giveback not graded vs the account-level switch | T7 | Add `daily_dd_switch`-only as a control arm in the intervention control set |
| 6 | TRADING | TP doctrine 0/77 compliant | T9 | Already baselined debt. Propose that Thursday pick the 6 real-money routings first |
| 7 | TRADING | Vol-scaled sizing judged on pooled Sharpe | T11 | Propose a research unit: per-asset-class vol-target arm (crypto / equity ETF / futures), judged on tails and Sharpe net of cost |
| 8 | MODEL | Exit heads close trades from outside the registry | M10 | **Escalated** (BL-20260908-…, queued 7 weeks): decide register-and-gate vs `exit_head_action: none` |
| 9 | MODEL | Desk/LTR decision repeatability unmeasured | M11 | Propose a research unit: re-run k = 3 on a stored sample of LTR snapshots; report the flip rate, and refuse to apply a flipping recommendation |
| 10 | MODEL | Trade-level families retrain but never score; setup_candidates/exit_head datasets frozen (08-04 / 09-07); review_journal 0 rows | M1, M10 | Propose that `ML-PROGRAMME-PLAN` name the first trade-level family to reach shadow scoring, with a date-free done-condition |
| 11 | MODEL | No deflation in perf-followup re-tests | M5 | Propose a skill edit: Track 1 records the variant count and reports DSR/PSR (as `ml/promotion/cost_gate.json` now does) |
| 12 | MODEL | Learning ledger absent (`scripts/ops/ml_learning_ledger.py` missing; row `ML-LEARNING-LEDGER` not found) | R6 | Propose a build row: compute § 10.6 (b) mechanically every ml-review |
| 13 | BOTH | No per-leg floor liveness check; a raising builder leaves no audit row | R6 | Propose a health-review CHECK, H17 "every rostered leg × floor account: rows 7 d, classified quiet / blocked", plus a `<leg>_error` audit event |

### 10.8 Run record (`practice` block; the ml-review record `comms/ml-plan/<stamp>.json` is the ML-FRONTIER-PREP lane's file, so it is kept here for that lane to copy)

```json
{"practice": {
  "run": "session_01AFoLuJpe2bJTErX7QGAmaS", "finished_at": "2026-10-28",
  "previous_refresh_read": [
    {"gap": "RESEARCH-INTERVENTION-CONTROL-SET", "state": "landed_unproven"},
    {"gap": "DESK-LIFECYCLE-S0", "state": "in_flight"},
    {"gap": "ML-TRAINING-PRINCIPLES-GAPS", "state": "done"},
    {"gap": "ML-PROGRAMME-PLAN", "state": "landed_unproven"},
    {"gap": "LTR-PRACTICE-REDESIGN", "state": "done"},
    {"gap": "FRONTIER-SCAN-COMPLETENESS", "state": "queued"}],
  "trading": {"sources_checked": [
      {"url": "https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf", "tag": "ACAD", "read": "full"},
      {"url": "https://robotwealth.com/reduce-trading-costs-and-boost-profits-with-the-no-trade-region-strategy/", "tag": "PRAC", "read": "full"},
      {"url": "https://arxiv.org/abs/2601.10812", "tag": "ACAD", "read": "abstract"},
      {"url": "https://ideas.repec.org/a/eee/beexfi/v39y2023ics2214635023000473.html", "tag": "ACAD", "read": "abstract"},
      {"url": "Martin & Schoneborn buffer width (search snippet)", "tag": "ACAD", "read": "summary"},
      {"url": "qoppac.blogspot.com (Carver netting/buffering)", "tag": "PRAC", "read": "could-not-look"}],
    "deltas": ["T11 added", "T12 added", "T2 strengthened (crypto)", "T3 strengthened (funding)"],
    "gaps_filed": ["IB-PAPER-ETF-LEGS-NO-ROWS", "SPLG-TICKER-DEAD"], "none_because": null},
  "model": {"sources_checked": [
      {"url": "https://arxiv.org/abs/2602.18481", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2601.15322", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2512.10971", "tag": "ACAD", "read": "abstract"},
      {"url": "https://www.sfi.ch/en/publications/the-virtue-of-complexity-in-return-prediction", "tag": "ACAD", "read": "abstract"}],
    "deltas": ["M11 added", "M6 strengthened", "R3 tension noted"],
    "gaps_filed": [], "none_because": null},
  "principles_revised": ["T11: new", "T12: new", "T2: strengthened", "T3: strengthened", "M11: new", "M6: strengthened", "R3: tension noted"]}}
```

### 10.9 Sources added by this refresh

- [S56] Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert, "The Impact of Volatility Targeting", *JPM* 45(1) 2018. https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf [ACAD/PRAC; full text]
- [S57] Longmore, "No-trade region", Robot Wealth, 2025-06-09. https://robotwealth.com/reduce-trading-costs-and-boost-profits-with-the-no-trade-region-strategy/ [PRAC/VEND; full]
- [S58] Zhang et al., "AlphaForgeBench", arXiv 2602.18481. https://arxiv.org/abs/2602.18481 [ACAD preprint; abstract + snippet]
- [S59] Khatchadourian, "DFAH: replayable financial agents", arXiv 2601.15322. https://arxiv.org/abs/2601.15322 [ACAD preprint; abstract]
- [S60] *(reserved; AI-Trader is already S53)*
- [S61] Donnelly, Lin & Lorig, "Optimal Liquidation of Perpetual Contracts", arXiv 2601.10812. https://arxiv.org/abs/2601.10812 [ACAD preprint; abstract]
- [S62] Sadaqat & Butt, "Stop-loss rules and momentum payoffs in cryptocurrencies", *JBEF* 39 (2023). https://ideas.repec.org/a/eee/beexfi/v39y2023ics2214635023000473.html [ACAD; abstract]
- [S63] Kelly, Malamud & Zhou, "The Virtue of Complexity in Return Prediction", *JF* 79(1) 2024. https://www.sfi.ch/en/publications/the-virtue-of-complexity-in-return-prediction [ACAD; abstract + secondary]
- [S64] Martin & Schöneborn, buffer width ∝ cost^(1/3) for mean-reverting assets (via a search snippet; paper not opened) [ACAD; secondary]
- Rename evidence for `SPLG-TICKER-DEAD`: State Street AP notice, 2025-10-22. https://www.ssga.com/library-content/products/fund-docs/etfs/us/information-schedules/ap-notice/notice-to-aps-ticker-fund-name-and-benchmark-index-name-changes-10-31-25.pdf [PRAC; search summary]

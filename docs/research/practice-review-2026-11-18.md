# Practice refresh 2026-11-18 (lane `PRACTICE-REFRESH-20261118`)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Tier 1, read-only on production. Dispatched by the JTA Trader manager (session_01AFoLuHbhd9wFuGJfWRqyoV) under the weekly reset
> job `practice-refresh`, governed by [`.claude/skills/frontier-research/SKILL.md`](../../.claude/skills/frontier-research/SKILL.md)
> § "Practice & methodology refresh". This file holds **deltas only**. The baseline and the earlier refreshes (§§ 10–12, sources
> `[S1]`–`[S78]`) are in [`practice-review-trade-mgmt-and-ai-2026-10-28.md`](practice-review-trade-mgmt-and-ai-2026-10-28.md). The
> canonical list is [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
> Read on `main` `e66d3b333`, 2026-11-18 ~18:00–19:30Z.
>
> **Gates this adds or changes:** none. Every filed item is a queued row or a blocked unit; the rows are proposals, and nothing
> touches config, src, a roster or the order path.
>
> **This week's operator interest** (Ideas inbox, relayed by the manager): (1) how trading firms run research operations, as a
> model for our automated research flow; (2) book-level risk around macro events ("we carried 12+ same-direction shorts into FOMC
> tonight"). The dispatch did not ask for the floor or learning measurements of § 12.6, so this pass does not repeat them.

## 1. Previous refresh read (the gaps of § 12.7 and their state)

States come from the **work store** (`scripts/ops/work.py get`). The frozen checklist export under `docs/claude/work/checklist/`
is stale, and this pass first read some rows there wrongly: `ML-LEARNING-LEDGER` and `BOOK-SIM-REAL-SIZER` read `queued` in the
export but are `done` (11-13) in the store. The other sources are the pipeline store and `research/queue/`.

| # (§ 12.7) | Gap | State 2026-11-18 | Evidence |
|---|---|---|---|
| 1 | `trend_donchian_eth` closes on an in-sample-only exit head | **Resolved.** The leg is now `exit_head_action: annotate` (2026-11-12, data-backed Tier-3 de-risk) | `config/strategies.yaml` comment: `RQ-20261101-78fc-03` FAIL, OOS dR/trade −0.0612, below all 1,000 matched random truncations. **Loose end:** pipeline item `PI-20261029-IFMPNGJK-0004` (the OOS walk-forward) still reads `queued`, although that result supersedes it. Raised to the manager |
| 2 | Floor rejections leave no priced outcome | **Correction to § 12.1:** a row exists. `VIRTUAL-LEG-POSITIONS` is `queued`, owner AM-OPS. § 12.1 searched for the proposed name `VIRTUAL-LEG-LEDGER` and found nothing | work store |
| 3 | Four floor mechanics faults | Routed to the intake. `SOAK-FAULT-INTAKE` is `queued` (updated 11-17); the four items were not checked one by one | work store |
| 4 | Desk on alpaca_paper / ib_paper: no rows | **`landed_unproven` since 11-07, the fourth refresh running.** Raised again | work store |
| 5 | No markout cost measurement (T3) | **Filed now**: row `MARKOUT-HARNESS` + unit `RQ-20261118-a5b3-03` | probe `markout\|mark-out`: 0 hits in every SKILL.md and in every unit |
| 6 | Trade-level families never score | Not re-checked this pass (outside the time box) | — |
| 7 | No per-leg × floor liveness CHECK | **Filed now**: row `FLOOR-LIVENESS-CHECK` | proposed twice before, never filed |
| 8 | Desk/LTR repeatability unmeasured (M11) | **Filed now**: row `DESK-REPEATABILITY` | probe `repeatab\|flip.rate` in trading-desk and live-trade-review: 0 hits |
| 9 | No left-tail quantile in verdicts (T14) | **Filed now**: row `VERDICT-LEFT-TAIL` (reporting only) | probe: only exit-refinement among the skills |
| 10 | Regime heads: no HAR / amplitude / rank check (M12) | **Partly met.** `RQ-20261117-dc44-01` (done) tested HAR-RV as a *feature* of the yz regime head. A per-asset HAR *baseline* with amplitude and rank columns is still missing. Not filed here, so as not to fork the active D2 series; raised to the manager | queue unit |
| 11 | `ML-LEARNING-LEDGER` | **Done** 2026-11-13 | work store |
| 12 | The refresh has no intake | Met in practice this week: the dispatch says every kept idea becomes a unit or row | dispatch |
| (11-04) | Deflation in perf-followup (M5) | **Filed now**: row `PERF-FOLLOWUP-DEFLATION` | probe `deflat\|DSR\|PSR\|PBO` in perf-followup SKILL.md: 0 hits |

## 2. Sources checked (what was actually read)

**TRADING: book-level event risk** (5 searches, 2 fetches)
- [S79] Acadian Asset Management, "Measuring Macro Event Risks to Active Equity Portfolios", Sept 2024.
  https://acadian-asset.com/investment-insights/geopolitics-and-macro/measuring-macro-event-risks-to-active-equity-portfolios
  [PRAC (asset manager), **read in full** via fetch]. Method: proxy the event with a winner-minus-loser basket, beta-neutralize it,
  estimate every holding's beta to the basket with a **short-horizon statistical risk model** (standard style-factor models miss
  short-term macro shocks), then sum to a portfolio exposure. The decision is to weigh the cost and the expected-return loss of
  closing an event tilt against the risk, especially "where the manager lacks insight into the event". The results are illustrative
  and gross of fees.
- [S80] Rosa, "The Financial Market Effect of FOMC Minutes", FRBNY *Economic Policy Review*, Dec 2013.
  https://www.newyorkfed.org/research/epr/2013/0913rosa.html [ACAD; **search summary**]. Five-minute windows: minutes raise
  volatility across asset classes about as much as an ISM release, **less than the statement or payrolls**, and the effect has
  declined over time.
- [S81] Nechio & Wilson, "How Important Is Information from FOMC Minutes?", FRBSF Economic Letter 2016-37.
  https://www.frbsf.org/research-and-insights/publications/economic-letter/impact-of-fomc-minutes-on-bonds [ACAD; **read in
  full** via fetch]. 5-year Treasury, 2009–2016: about 6.5 bp average absolute move on statement days, a little under 5 bp on
  minutes days, about 3 bp on a typical day. The effect is largest when the minutes' tone diverges from the statement's.
  Descriptive only, with no significance tests.
- [S82] Crypto around FOMC [**summaries only**]. Corbet, Larkin, Lucey, Meegan & Yarovaya (2020) find spillovers that differ by
  coin (ACAD, abstract via summary). Jarboui & Mnif (2021, *J. Investment Compliance*) find a significant negative CAR four days
  after the first COVID FOMC (ACAD, paywalled abstract). A Vaasa thesis finds no uniform daily effect. Vendor and press pieces
  (Interdax, Amberdata, Cointelegraph) report higher volatility in the hour before and the hour of the release, and a pre-event
  run-up then weak post-event returns over 7–10 meetings, with no significance tests. **Reading: crypto event evidence is
  small-sample and mixed. Weight it as a reason to measure, not as a result.**
- Checked, nothing new kept: Hedgeweek's reports of pre-event de-risking (April 2025 tariffs) and JPM GMO's net-exposure cut are
  anecdotes. Man Group describes continuous vol scaling, not calendar de-risking (consistent with T11). The 2026 FOMC calendar
  (several aggregators) lists no meeting on 11-18; the Oct 27–28 minutes fall about three weeks later.

**RESEARCH-OPS / MODEL: how firms run research, and automated research** (4 searches, 2 fetches)
- [S83] Man Group / Man Numeric, AlphaGPT (Bloomberg 2025-07-10; Hedgeweek; AI Street interview with Ziang Fang).
  https://aistreet.beehiiv.com/p/inside-man-group-s-alphagpt [PRAC; **trade press read in full**; no primary paper found]. The
  pipeline is modelled on a research pod: an idea generator, a code implementer and an evaluator (significance, risk, economic
  sense), and the reasoning is logged. Several dozen signals have gone live. Rules: every idea needs a stated hypothesis and an
  economic rationale; **"flipping a signal after seeing results isn't allowed for humans or AI"**. Humans review every step and the
  code line by line, and an investment committee applies thresholds. Monitoring tools compare **live performance against the
  research result and track expected decay**. Named failure modes are look-ahead, multiple testing, hallucination and token cost.
- [S84] "AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay", arXiv 2502.16789
  (KDD '25). https://arxiv.org/abs/2502.16789 [ACAD; **summary + HTML abstract**]. LLM factor miners lean on prior knowledge and
  produce **homogeneous, crowded factors**. Remedies: an originality score from AST subtree overlap with existing factors,
  hypothesis-factor alignment, and a complexity limit (length, free parameters). Results are self-reported (CSI 500, S&P 500).
- [S85] Li, Yang, Yang, Xu, Wang, Liu & Bian, "R&D-Agent-Quant", arXiv 2505.15155 (NeurIPS 2025). https://arxiv.org/abs/2505.15155 [ACAD; **summary**].
  Research and development are separate stages; a **bandit scheduler** chooses the next direction; a run costs under $10.
- [S86] Huang & Fan, "Beyond Prompting: An Autonomous Framework for Systematic Factor Investing via Agentic AI", arXiv 2603.14288
  (2026). https://arxiv.org/abs/2603.14288 [ACAD preprint; **abstract**]. Claims a Sharpe of 3.11 from a closed loop with OOS
  validation and an economic-rationale rule. The abstract gives no trial count, no correction method and no costs. Kept as a
  **cautionary** example (M14, S78), not as evidence.
- [S87] "Hubble", arXiv 2604.09601 (2026) [ACAD preprint; **summary**]. Its top-5 in-sample factors were re-read on a fixed
  held-out window (2025-06 → 2026-03): range and vol factors held, the weakest trend factor decayed. The panel is 30 stocks with
  no costs.
- Checked, nothing new kept: KX vendor posts on signal decay (vendor). A lecture on continuous signal generation, monitoring and
  retirement matches R4. McLean & Pontiff (2016, about 32% post-publication decay) was seen only in secondary text and is
  already covered by R4 [S43]. QuantaAlpha (arXiv 2602.07085) uses a chronological split but no correction was visible.

## 3. Deltas (each one is now in the canonical list, dated 2026-11-18)

| Track | Principle | Delta | Source |
|---|---|---|---|
| TRADING | **T15 (new)** | Measure the **book's** combined exposure to each scheduled high-impact release, not each trade's: same-direction risk summed through a short-horizon correlation model. Weight releases by their measured effect (decision > minutes ≈ a mid-tier release > a normal day). Any pre-event action is an active-management class, graded against hold and a matched random action (T1, T13) net of cost | S79, S80, S81; S82 (mixed, small-sample) |
| RESEARCH-OPS | R2 strengthened | A practice precedent for our automated research line: generator → implementer → evaluator stations, logged reasoning, human review at code and committee | S83, S85 |
| RESEARCH-OPS | R4 strengthened | Firms monitor each live signal against **its own research result and its expected decay** | S83 |
| RESEARCH-OPS / MODEL | **R9 (new)** | Automated idea generation needs three controls: a hypothesis and rationale fixed before the result and never flipped; an **originality / near-duplicate control** so the trial count is true; and an evaluator independent of the generator. A self-reported agentic Sharpe with no trial count is a claim (M14) | S83, S84, S85; cautionary S86, S87 |
| MODEL | M4 note | Count near-duplicate hypotheses as trials of one family (see R9) | S84 |

No principle was removed.

## 4. Our live designs vs the list (every gap names its principle)

Population: designs on `main` `e66d3b333`: `src/news/news_events.py`, `config/economic_calendar.yaml`,
`scripts/macro/econ_calendar_data.py`, `comms/macro/econ_calendar_snapshots.jsonl`, `config/live_trade_review.yaml` (`calendar`
trigger), `src/runtime/allocator_corr.py` (per row `BOOK-CORR-VIEW-LTR`), `research/queue/` (2,398 RQ files: 1,994 done, 318
queued, 71 retired, 15 blocked, counted by `status`), and `scripts/research/queue_replenish.py`.

**TRADING**
- **T-G1 · T15: the book's exposure to a release is unmeasured.** The only event input on the trade path is
  `news_events.event_risk = impact × proximity`. It is **per symbol, applied at entry, reduce-only, never a blackout**. Nothing sums
  the open same-direction risk across legs and accounts before a release. The live-trade-review `calendar` trigger is per package.
  `BOOK-CORR-VIEW-LTR` (queued since 11-01) would give the packet a correlation view but has no event clock. This is exactly
  tonight's case: 12+ same-direction shorts read as 12 independent decisions. → unit `RQ-20261118-a5b3-01` (blocked on
  `EVENT-SPAN-HISTORY`) and a note appended to `BOOK-CORR-VIEW-LTR`.
- **T-G2 · T15 + data quality: the calendar mislabels FOMC releases. MEASURED.**
  - `econ_calendar_data.py` maps `fed interest rate|fomc|…` to kind `fomc`, impact 1.0. **Tonight's 19:00Z "fomc" entry is the FOMC
    MINUTES** (`evt-fomc-2026-11-18-us`, `event_name: "FOMC Minutes"`, `impact_score: 1.0`, source `bigdata:fxstreet`), weighted
    like a rate decision. S80 and S81 put minutes below statements.
  - On decision days the event id is keyed by kind and date. `evt-fomc-2026-12-09-us` carries four releases (decision, statement and
    projections at 19:00Z, press conference at 19:30Z), and `config/economic_calendar.yaml` keeps **one** line,
    `fomc 2026-12-09T19:30:00Z`. Under the 60-minute ramp, event_risk at the 19:00Z decision is 0.5, not 1.0.
  - The 10-28 decision has the same collision (18:00Z vs 18:30Z).
  - → row `CALENDAR-FOMC-RELEASE-SPLIT` (Tier 2 fix proposal) and unit `RQ-20261118-a5b3-02` (evidence for the weights).
- **T-G3 · T3:** no markout measurement. Carried from 11-11 (see § 1 #5). → `MARKOUT-HARNESS`, `RQ-20261118-a5b3-03`.
- **T-G4 · T14:** no left-tail reporting. Carried. → `VERDICT-LEFT-TAIL`.

**RESEARCH-OPS (our automated research line vs S83–S85)**
- **Matches practice:**
  - The hypothesis is fixed before the run (`decision_rule.registered_before_run`, guard `research-queue-decision-rule`): this is
    AlphaGPT's no-flip rule.
  - Separate stations: authoring (programme-review, research-ops), dispatch (`research-script-run.yml`) and a script-computed grade.
  - Live vs research: performance-review's "live vs its own backtest band" and the M13 holdout ledger.
  - An explicit cost-stack requirement, which S86 and S87 lack.
- **R-G1 · R9 / M4: no originality or near-duplicate control on hand-authored and LLM-authored units.** `queue_replenish.py`
  dedupes generated units by key only. Each decision rule declares its own `n_comparisons`. Some units disclose earlier reads of
  the same class (`RQ-20261117-43b6-03`: "cumulative 7"), but nothing checks the declared count against what the queue actually
  holds. With 2,398 units written mostly by LLM sessions, the homogeneity S84 describes is the expected failure. → row
  `RESEARCH-TRIAL-CENSUS`.
- **R-G2 · R4: the live-vs-research decay check exists per leg in performance-review, but not as an expected-decay prior.**
  Practice tracks *expected* decay (S83). **Not filed:** performance-review's band already gives the signal, and adding a prior
  haircut would change grading, which needs the operator. Recorded here as a question for the manager.

**MODEL:** M-G2 (repeatability) is filed as `DESK-REPEATABILITY`. M5 in perf-followup is filed as `PERF-FOLLOWUP-DEFLATION`.

## 5. Filed this lane (work store rows, all `queued`, owner manager; units in `research/queue/blocked/`)

| Item | Kind | Track | Unblocks or closes |
|---|---|---|---|
| `RQ-20261118-a5b3-01` | unit (blocked) | TRADING | Book-level pre-event flatten vs hold vs matched random, under RULE-AM-RISK-ADJUSTED-V1 (screen), with the event-spanning vs non-spanning mean and p10 reported |
| `RQ-20261118-a5b3-02` | unit (blocked) | TRADING | Event-class weights (decision vs minutes vs cpi vs nfp) from our own symbols' 2 h realized vol |
| `RQ-20261118-a5b3-03` | unit (blocked) | TRADING | Markout vs recorded cost |
| `EVENT-SPAN-HISTORY` | lever row, T1 | TRADING | -01, -02 |
| `CALENDAR-FOMC-RELEASE-SPLIT` | row, T2 proposal | TRADING | T-G2 |
| `MARKOUT-HARNESS` | lever row, T1 | TRADING | -03 |
| `RESEARCH-TRIAL-CENSUS` | row, T1 | RESEARCH-OPS | R-G1 |
| `FLOOR-LIVENESS-CHECK` | row, T1 | BOTH | carried 11-04 / 11-11 |
| `VERDICT-LEFT-TAIL` | row, T1 (reporting) | TRADING | carried |
| `DESK-REPEATABILITY` | row, T1 | MODEL | carried |
| `PERF-FOLLOWUP-DEFLATION` | row, T1 | RESEARCH-OPS | carried |
| `BOOK-CORR-VIEW-LTR` | note appended | TRADING | event clock added to scope |

**Dropped, with reasons:**
- A calendar blackout or auto-flatten before releases: it would be a gate and a self-acting risk rule (No new gates; T13 needs a
  test first). The question is unit -01.
- An expected-decay haircut in grading: needs the operator (R-G2).
- Copying AlphaGPT's human line-by-line code review: our analogue is CI guards plus the manager merge; there is no new evidence
  that it should change.
- R&D-Agent-Quant's bandit scheduler for choosing directions: interesting for queue ordering, but programme-review already ranks
  by value per cost, and no evidence shows a bandit beats that. **Not kept.** Revisit if `RESEARCH-TRIAL-CENSUS` shows effort
  piling onto a few subjects.

## 6. For the manager (not filed by this lane)

1. **Tonight:** the "FOMC" the book is short into is the **minutes** (S80/S81: a smaller event than a decision), but the trader weights it 1.0.
   The Dec 9 decision is mistimed by 30 min in the config. Fixing that is `CALENDAR-FOMC-RELEASE-SPLIT` (Tier 2, needs an OK). It is
   worth doing before Dec 9.
2. `PI-20261029-IFMPNGJK-0004` reads `queued` but is superseded by `RQ-20261101-78fc-03` (the annotate decision of 11-12). Close it
   with that terminal reason.
3. `DESK-PAPER-ACCOUNTS` has been `landed_unproven` through four refreshes.
4. M12's per-asset HAR baseline: fold it into the D2 series (`RQ-20261117-dc44-*`) rather than a separate unit.

## 7. Run record (`practice` block)

```json
{"practice": {
  "run": "PRACTICE-REFRESH-20261118", "finished_at": "2026-11-18",
  "previous_refresh_read": [
    {"gap": "trend_donchian_eth exit head", "state": "resolved: annotate 2026-11-12 (RQ-20261101-78fc-03 FAIL); PI-20261029-IFMPNGJK-0004 still queued, superseded"},
    {"gap": "VIRTUAL-LEG-POSITIONS", "state": "queued (exists; 11-11 said not filed under another name)"},
    {"gap": "SOAK-FAULT-INTAKE", "state": "queued"},
    {"gap": "DESK-PAPER-ACCOUNTS", "state": "landed_unproven since 11-07; raised"},
    {"gap": "ML-LEARNING-LEDGER", "state": "done 2026-11-13"},
    {"gap": "12.7 #5,#7,#8,#9 + 11.7 deflation", "state": "filed this lane"},
    {"gap": "12.7 #10 HAR", "state": "partly met by RQ-20261117-dc44-01; raised"}],
  "trading": {"sources_checked": [
      {"url": "https://acadian-asset.com/investment-insights/geopolitics-and-macro/measuring-macro-event-risks-to-active-equity-portfolios", "tag": "PRAC", "read": "full"},
      {"url": "https://www.newyorkfed.org/research/epr/2013/0913rosa.html", "tag": "ACAD", "read": "summary"},
      {"url": "https://www.frbsf.org/research-and-insights/publications/economic-letter/impact-of-fomc-minutes-on-bonds", "tag": "ACAD", "read": "full"},
      {"url": "https://www.emerald.com/insight/content/doi/10.1108/JOIC-12-2020-0048/full/html", "tag": "ACAD", "read": "summary"},
      {"url": "https://blog.amberdata.io/five-signals-of-fomc-impact-how-interest-rate-decisions-reshape-crypto-market-microstructure", "tag": "VEND", "read": "summary"}],
    "deltas": ["T15 added (book-level scheduled-event exposure; weight releases by measured effect)"],
    "gaps_filed": ["RQ-20261118-a5b3-01", "RQ-20261118-a5b3-02", "RQ-20261118-a5b3-03", "EVENT-SPAN-HISTORY", "CALENDAR-FOMC-RELEASE-SPLIT", "MARKOUT-HARNESS", "VERDICT-LEFT-TAIL", "FLOOR-LIVENESS-CHECK"],
    "none_because": null},
  "model": {"sources_checked": [
      {"url": "https://aistreet.beehiiv.com/p/inside-man-group-s-alphagpt", "tag": "PRAC", "read": "full (trade press)"},
      {"url": "https://arxiv.org/abs/2502.16789", "tag": "ACAD", "read": "summary"},
      {"url": "https://arxiv.org/abs/2505.15155", "tag": "ACAD", "read": "summary"},
      {"url": "https://arxiv.org/abs/2603.14288", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2604.09601", "tag": "ACAD", "read": "summary"}],
    "deltas": ["R2 strengthened", "R4 strengthened", "R9 added (automated-research controls)", "M4 note"],
    "gaps_filed": ["RESEARCH-TRIAL-CENSUS", "DESK-REPEATABILITY", "PERF-FOLLOWUP-DEFLATION"],
    "none_because": null},
  "principles_revised": ["T15: new", "R2: strengthened", "R4: strengthened", "R9: new", "M4: note"]}}
```

## 8. Sources added by this refresh

- [S79] Acadian Asset Management, "Measuring Macro Event Risks to Active Equity Portfolios", Sept 2024. https://acadian-asset.com/investment-insights/geopolitics-and-macro/measuring-macro-event-risks-to-active-equity-portfolios [PRAC; full]
- [S80] C. Rosa, "The Financial Market Effect of FOMC Minutes", FRBNY Economic Policy Review, Dec 2013. https://www.newyorkfed.org/research/epr/2013/0913rosa.html [ACAD; summary]
- [S81] F. Nechio & D. J. Wilson, "How Important Is Information from FOMC Minutes?", FRBSF Economic Letter 2016-37. https://www.frbsf.org/research-and-insights/publications/economic-letter/impact-of-fomc-minutes-on-bonds [ACAD; full]
- [S82] Crypto-FOMC evidence, mixed: Corbet et al. (2020); Jarboui & Mnif (2021) https://www.emerald.com/insight/content/doi/10.1108/JOIC-12-2020-0048/full/html; vendor: Amberdata (2025), Interdax (2020) [ACAD summaries + VEND]
- [S83] Man Group / Man Numeric AlphaGPT (Bloomberg 2025-07-10; AI Street interview). https://aistreet.beehiiv.com/p/inside-man-group-s-alphagpt [PRAC; trade press, full]
- [S84] AlphaAgent, arXiv 2502.16789 (KDD '25). https://arxiv.org/abs/2502.16789 [ACAD; summary]
- [S85] R&D-Agent-Quant, arXiv 2505.15155 (NeurIPS 2025). https://arxiv.org/abs/2505.15155 [ACAD; summary]
- [S86] Huang & Fan, arXiv 2603.14288 (2026). https://arxiv.org/abs/2603.14288 [ACAD preprint; abstract; cautionary]
- [S87] Hubble, arXiv 2604.09601 (2026). https://arxiv.org/abs/2604.09601 [ACAD preprint; summary]

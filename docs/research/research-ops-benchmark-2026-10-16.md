# Research-ops benchmark — 2026-10-16

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · lane `RESEARCH-OPS-BENCHMARK-1016` (dispatched by Manager Session 2026-10-16, `session_01VduHYzdaXe27wTDBLSu8ao`) · **Tier-1: nothing here changes a config, a roster, a mandate or an order path.**

**Operator, 2026-10-16 (gist):** *"Do some open-source research on how research operations for this kind of research is generally structured in organizations, so we can use it as a basis for our automated workflows and make sure we're not missing important aspects … Tell me if decisions are needed."*

**Scope.** This compares our research loop with published practice. It does **not** redesign today's fixes: programme trees + coverage guard, theme-weighted supply, authored-first dispatch, the daily authoring lane, the family-retirement protocol (`research-engine-1016-families`, unmerged at writing), and pipeline SLOs (lane RESEARCH-PIPELINE-SLO-1016). Those count as "have it" below. The loop as built is documented in [`research-loop-audit-2026-10-15.md`](research-loop-audit-2026-10-15.md); this doc is the outside view.

**How far each source was read.** `[F]` = full text read · `[f]` = page read through a summary · `[S]` = search abstract only. The URLs come from a web-research pass this session and none are invented. Claims tagged `[S]` are secondhand, so cite them as such.

## 1. Sources and the practices taken from them

| # | source | practices that carry over |
|---|---|---|
| S1 | López de Prado, "The 10 Reasons Most ML Funds Fail", *JPM* 2018 [S] (garp.org whitepaper; quantpedia summary [f]) | Research **factory** ("meta-strategy"): split the assembly line into stations, measure each station's quality on its own, and avoid the lone end-to-end "Sisyphus" quant. |
| S2 | Bailey & López de Prado, "The Deflated Sharpe Ratio", *JPM* 2014 [S] (ssrn 2460551) | Judge a winner against the expected **max** of N skill-less trials. This needs **every trial logged**, with N and the variance across trials. |
| S3 | Bailey, Borwein, López de Prado, Zhu, "Pseudo-Mathematics and Financial Charlatanism", *Notices AMS* 2014 [F] (carmamaths.org/jon/backtest.pdf) | Minimum backtest length grows with ln N. With 5 years of data, test at most ~45 independent configurations. Not reporting N "makes it impossible to assess the risk of overfitting". |
| S4 | Bailey et al., "Probability of Backtest Overfitting", *J. Comp. Finance* 2017 [S] (ssrn 2326253) | CSCV over the matrix of all trials. PBO = P(the in-sample best ranks below the median out of sample). |
| S5 | López de Prado & Lewis, *Quant. Finance* 2019 [S] | **Effective N**: cluster trials by return correlation. Correlated variants are not independent trials. |
| S6 | Harvey, Liu, Zhu, *RFS* 2016 [S] (nber w20592) | A new factor needs **t > 3**, and the hurdle rises as tests accumulate. |
| S7 | Harvey & Liu, "Backtesting", *JPM* 2015 [S] (duke.edu P120; man.com summary [f]) | The industry rule is a flat **50 % Sharpe haircut**. The correct haircut is nonlinear and grows with the number of tests (Bonferroni / Holm / BHY). Stress-test the assumed N. |
| S8 | Arnott, Harvey, Markowitz, "A Backtesting Protocol in the Era of ML", *JFDS* 2019 [F] (ssrn 3275654) | The 7-point protocol: (1) state the hypothesis before the data; (2) **track every model and variable tried, successful or not**; (3) fix data, transforms and winsorisation in advance; (4) the only true OOS is live, so **block OOS re-iteration** and include costs; (5) structural change, crowding, **minimal live tweaking**; (6) simplest model; (7) culture: "most tests fail" and reward science over winners. |
| S9 | Man AHL Academic Advisory Board, "Overfitting and its impact on the investor", 2015 [f] (man.com) | **Pre-register** the data partition, method and expectation. Use parameter heat-maps (an isolated peak is mining). **Track rejection rates per stage.** Log every trial, and even data access. Run new models on house capital to catch broken ones; that tests mechanics, not significance. |
| S10 | Roulston & Hand (Winton), "Blinded by optimism", 2016 [F] | **Meta-overfitting**: an organisation that selects on noise across many researchers or lanes. The best of 100 skill-free strategies has p ≈ 0.15 where one alone has p ≈ 0.002. |
| S11 | Kakushadze, "101 Formulaic Alphas" (WorldQuant), arXiv 1601.00991, 2016 [S]; BRAIN thresholds community-reported only [S] | Factory of many weak, low-correlation signals. A **self-correlation gate against the existing book** (≤ 0.7) before admission. |
| S12 | McLean & Pontiff, *JF* 2016 [S] | Returns are 26 % lower OOS and 58 % lower after publication. Plan for decay. |
| S13 | Wiecki et al. (Quantopian), "All that glitters…", 2016 [S] | Over 888 strategies, backtest Sharpe predicts OOS Sharpe with R² < 0.025. **More backtests per strategy means a larger gap**, so a count of backtests is an anti-metric. |
| S14 | Philips, Yashchin, Stein, "SPC to monitor active managers", *JPM* 2003 [S] | A **CUSUM** per live strategy against its expected mean, at a declared false-alarm rate, with a trip leading to review. |
| S15 | Khandani & Lo, "What happened to the quants in Aug 2007?" [S] | Monitor overlap with crowded and similar books as well as own P&L. |
| S16 | Sculley et al., "Hidden Technical Debt in ML Systems", NeurIPS 2015 [F] | Configs are small diffs, reviewed and asserted. Prediction-bias monitoring. Upstream SLOs. Reward deletion and reproducibility. |
| S17 | Breck et al., "The ML Test Score", 2017 [F] | Score = **min** of the four section sums (data, model, infra, monitor). Includes reproducible training, offline proxy ↔ live correlation, a simpler baseline that is not better, and known staleness impact. |
| S18 | MLflow tracking docs [S]; Kempner handbook on W&B reproducibility [S] | A run record = code hash, **data version/hash**, config, seed, environment and artifacts. The same record feeds DSR/PBO. |
| S19 | Nosek et al., "The preregistration revolution", *PNAS* 2018 [S]; Registered Reports [S] | Separate generation from testing. Approve the question and method before the data, then grade adherence rather than outcome. |
| S20 | Gelman & Loken, "garden of forking paths", 2013/2014 [S] | Data-dependent choices inflate false positives even with **one** test. |
| S21 | Benjamini–Hochberg 1995 [S]; Foster & Stine, alpha-investing, *JRSS-B* 2008 [S]; Javanmard & Montanari, LORD, *Ann. Stat.* 2018 [S] | **Online FDR** over a stream of hypotheses: an α-wealth ledger where each test spends and each discovery earns back. This fits an automated queue directly. |
| S22 | Cooper, Stage-Gate, 1990 [S]; Nagji & Tuff, 70/20/10, *HBR* 2012 [S] | Each gate has must-meet kill criteria set **at gate entry**, and Go/Kill/Hold/Recycle outputs. Kill early. Explicit core / adjacent / transformational allocation. |
| S23 | Google SRE Workbook: data pipelines, error-budget policy, postmortem culture [f] | Freshness / correctness / end-to-end SLOs. Alert on symptoms. An incident using > 20 % of the budget triggers a postmortem with an owned action. **Reward closing action items, not writing postmortems.** |

## 2. Gap table

Status values: **have** (an implementing file, skill or guard exists), **partial**, **none**. "Fix" names what this lane filed.

| area | practice (sources) | our status (MEASURED 2026-10-16 on `origin/main` 5d7aeffb unless marked) | risk of the gap | fix filed |
|---|---|---|---|---|
| Intake & triage | Hypothesis before data; a funnel from idea to unit; a scoping unit instead of a drop (S8.1, S19, S22) | **have.** `research/queue/PLANNING.md` § 1 (scoping unit, rule registered first), `IDEAS.md` intake, programme trees + coverage guard (today) | — | — |
| Pre-registration, per unit | Rule fixed before the run (S8, S9, S19) | **have.** `check_research_queue_decision_rule.py` requires `registered_before_run: true`, committed with the unit | — | — |
| **Multiple testing at programme level** | Log **every** trial and compute N / effective N. Deflate the winner (DSR / haircut / t > 3 / online FDR) (S2–S7, S10, S21) | **none at programme or ladder level.** Holm/BH appear inside individual units only (e.g. `RQ-20261014-65cc-*`). **52 of 53** `comms/strategy_evidence/*.json` records carry `param_selection_provenance: "not_established"` (1 null). The Stage-0 rule is `RULE-D1-STAGE0-NET-OF-FULL-COST` (net_r_oos > 0). `MD-PROMOTE-S0-S1` / `-S1-S2` bars are expectancy > 0, n ≥ 30, fold majority, with no term for how many configurations were tried. The m20 corpus alone holds 1,493 cell rows over 51 legs (up to 61 on one leg); `research/results/` holds 1,001 E5 rows in 622 dirs | **Highest.** At ~80 fires a day the factory **will** produce passes by chance (S10: best of 100 gives p ≈ 0.15), and the automated ladder promotes them on a bar that cannot see the selection | `RESEARCH-TRIAL-LEDGER` (measure) → `PROMOTION-BAR-MULTIPLICITY` (operator decision) |
| **Confirmation on fresh data / OOS reuse** | True OOS is used once; no re-iteration on the holdout; positives are replicated (S8.4, S4, S20) | **partial.** P3 already requires "a best-of-3 PASS opens exactly one fresh-window confirmation, no Tier-3 until CONFIRMED" (row `P3-STRATEGY-PROGRAMME`). Elsewhere `queue_grade.py` does the reverse: a template unit's first **FAIL** gets a confirmatory re-run over the same window (deterministic, so it repeats the same number), while a **PASS** closes `done`. Nothing records how often a leg's history window has been tested | False positives pass unreplicated while confirmation runner slots go to re-confirming nulls | `RESEARCH-CONFIRM-FRESH-WINDOW`; skill text (research-ops § D "pass →") |
| Reproducibility / tracking | Code hash + data hash + config + seed per run (S16–S18) | **partial.** E5 `produced_by` carries `commit_sha`, `run_id`, `workflow` and `tool`. There is no data fingerprint (candle file / window / shard hash), and no seed except in ML bake-offs (`n_seeds`) | A result cannot be re-derived once a shard is re-cut (`ML-SHARD-TRUNCATED` is a live example) | folded into `RESEARCH-TRIAL-LEDGER` (data fingerprint on the record) |
| Review cadence & readers | Someone reads every result against its rule; review the process at stage level (S9, S19) | **have** (after today). Mechanical grader (attested rules), research-ops 4×/day, `RESULTS-UNDISPOSITIONED`, weekly planning, perf-followup. One weakness: only 1 of 517 `done` units records a follow-up inside its `grading:` block (follow-ups may be recorded elsewhere, in ops records or notes; not measured) | Covered by today's disposition check | — |
| Kill / continue | Kill criteria fixed at gate entry; config-kill ≠ idea-kill (S22) | **have** (landing). Family-retirement protocol, policy v2 (A/B/C verdicts, six minimums, closure-language guard); `MD-KILL-QUESTION` | — | — |
| **Decay monitoring & re-research triggers** | A standing monitor per live strategy (CUSUM vs expected mean, declared false-alarm rate) whose trip opens research before demotion (S12, S14, S8.5) | **partial.** `MD-DEMOTE-S2-S1` (T3 ∧ net < 0 over two 20-trade windows) is a demotion, not an early-warning re-research trigger. `live_vs_backtest_verdict.py` exists, but only **2** weekly units use it (`RQ-20261015-8bbc-01/02`, xrp legs) against **8** legs on the `bybit_2` + `alpaca_live` rosters (parsed from `config/accounts.yaml`), and prop is not covered | Decay is found by the demotion rule after the money is lost, or by an ad-hoc unit | `LIVE-DECAY-MONITOR` |
| Research → production handoff | Evidence record, simple baseline, canary, rollback, train = serve (S17, S9) | **have.** Committed evidence records, `check_roster_promotion_evidence.py`, mechanical 1–2-trade soak, mirror = live, `train_parity.py`, Gate-2 demotion with auto-land | — | — |
| **Correlation with the existing book** | Admission gated on self-correlation / overlap with what already trades (S11, S15, S5) | **partial / unverified.** CLAUDE.md says a prop pass feeds `MD-PROMOTE-S1-S2` "after a portfolio-overlap check". `scripts/ops/mandate_resolver.py` contains no overlap or return-correlation computation (the only matches are "non-overlapping 20-trade windows"). perf-followup Track 4 does overlap research, but as research rather than a gate | Promotions stack correlated legs. The 25 % auto-promotion cap is by risk, not by correlation | `PROMOTION-CORRELATION-CHECK` |
| Capacity / compute planning | Separate queues by priority; capacity per backend; explicit core / adjacent / frontier mix (S22, S23) | **have.** `research_compute.yaml` backends and caps, value per cost ranking, bucket mix 30/25/20/15/10 (≈ 70/20/10 in spirit), utilisation files, theme supply | — | — |
| **Knowledge base / "what we learned"** | Searchable record of every trial including nulls; a lookup before re-testing (S3, S8.2, S23) | **partial.** Results, grading blocks, `families.<f>.history` (ML only), family reviews (landing), the disposition ledger (e35/m20/gld corpora only). Nothing answers "what has been tried on leg X / family Y, at what N" in one place, and no authoring rule says to look first | Re-testing the same idea inflates N unseen. The same lookup is the trial ledger | `RESEARCH-TRIAL-LEDGER` (one index serves both); skill text (PLANNING § 1) |
| **Research productivity metrics** | Rejection rate per stage, time-to-decision, realised live/backtest haircut of promoted legs, calibration of value estimates. Backtest counts are vanity (S9, S13, S17) | **partial.** We measure flow: fired/24h, runnable, results landed, utilisation, and SLOs (today). We do not measure outcomes. 211 queued/done units carry `value.confidence` (P(result changes a decision)), never compared with what happened. Of 517 `done` units, 106 are `indeterminate` (20.5 %; 30 % of the 359 with a verdict) and 158 carry no verdict in `grading:` | Optimising flow counts (Goodhart). Power-blind units consume slots | `RESEARCH-OUTCOME-METRICS` |
| Failure modes of factories | See the next table | | | |

**Failure modes of automated research factories, checked against us:**

| failure mode (source) | guard we have | open |
|---|---|---|
| Multiple-testing explosion / meta-overfitting (S3, S10) | per-unit rules only | **open** → trial ledger + bar decision |
| Forking paths (S20) | rule registered before run | transforms/windows not fixed in the rule on every harness; the fresh-window confirmation closes most of it |
| OOS re-use (S8.4) | — | **open** → fresh-window row |
| Crowded / correlated admissions (S11, S15) | 25 % risk cap; mirror = live | **open** → correlation row |
| Look-ahead / cost omission | full cost stack (D1), provenance vocabulary, point-in-time macro rules | two harnesses outside the cost stack (CLAUDE.md § D1; already tracked) |
| Starved / stalled pipeline unnoticed (S23) | watchdog, SLOs (today), computed floor | — |
| Vanity metrics (S13) | — | **open** → outcome-metrics row |
| One-strike idea kill (S22, operator 2026-09-27) | family-retirement protocol | — |
| Live tweaking (S8.5c) | Tier-3 gate, mechanical soak | — |

## 3. What we already do well, by the same yardstick

- **Pre-registration is enforced by a guard**, not by policy. S8 and S9 describe this as best practice, and most firms rely on culture for it.
- **Full cost stack at Stage 0, and "a live book never establishes edge".** This matches S8.4c and S9: house-capital trading catches broken models, not significance. The 1–2-trade mechanical soak is the S9 practice stated exactly.
- **Nulls are assets; config-kill ≠ idea-kill.** S8.7 ("most tests fail") and the family-retirement protocol with its outside-source denominator.
- **Station-level measurement of the factory** (S1): dispatcher, collector, grader, watchdog, utilisation and SLOs each have their own check.
- **Value × cost ranking across compute backends**, with an explicit bucket mix (S22).
- **Measurement honesty**: `MEASURED/ESTIMATED/UNVERIFIED`, and "could not look ≠ found nothing". S23's "stale is preferable to wrong" is the same idea.

## 4. Decisions for the operator

1. **Should the automated promotion bar account for how many configurations were tried?** (Tier 3, mandate bar; row `PROMOTION-BAR-MULTIPLICITY`.)
   - (a) **Measure first, report-only (recommended).** `RESEARCH-TRIAL-LEDGER` computes N, effective N and DSR / Harvey–Liu haircut for every evidence record and shows how many current Stage-0 passes survive. The decision comes back with that number.
   - (b) Adopt a deflated bar now (DSR > 0.95, or haircut net expectancy > 0) on `MD-PROMOTE-S0-S1` and `-S1-S2`.
   - (c) Keep expectancy > 0 and rely on the fresh-window confirmation alone.
2. **Replication policy for template cells** (row `RESEARCH-CONFIRM-FRESH-WINDOW`). Today a first FAIL is re-run over the same window and a PASS closes. Proposed: a PASS opens one confirmation on a disjoint / most-recent window before it can feed a Tier-3 proposal, and the same-window FAIL re-run is dropped for deterministic harnesses. A FAIL still never kills the family; that is the retirement protocol's job. **Recommend yes.** It touches the 2026-09-27 "never kill on one pass" rule only in form, because the refinement default lives in the family protocol now. It is your call because it changes how that rule is implemented.
3. **Programme-level false-discovery budget** (optional, later). Run an online-FDR α-wealth ledger (S21) per programme over the stream of units. **Recommend deferring** until the trial ledger has run for 2 weeks. Without the ledger there is nothing to spend against.

## 5. Reproduce

```bash
python3 - <<'EOF'   # evidence-record provenance
import json,glob,collections; c=collections.Counter()
for f in glob.glob('comms/strategy_evidence/*.json'):
    c[str(json.load(open(f)).get('param_selection_provenance'))]+=1
print(c)
EOF
grep -n "confirm" scripts/research/queue_grade.py | head        # FAIL→same-window rerun, PASS→done
grep -l live_vs_backtest research/queue/*.yaml                    # 2 units
grep -n -i "overlap\|correlat" scripts/ops/mandate_resolver.py    # no return-correlation check
wc -l docs/research/m20-sweep-corpus.jsonl; cat research/results/*/*.jsonl | wc -l
```

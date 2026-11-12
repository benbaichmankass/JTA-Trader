# ML deep audit: rosters, infrastructure, workflows (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Gates this adds or changes:** none. Two recommendations in § 6 would add or raise a gate; they are labelled and **not filed as work**.

Lane `ML-DEEP-AUDIT-FABLE` (row in the work store), dispatched by the ML assistant manager for Manager Session 2026-11-11a. Tier 1:
read and analyse. No runtime, config or model was changed. The sibling lane `ML-PROGRAMME-CONSOLIDATION` owns the keep/retire waves and
the D3 head-to-heads; this document audits the **structure**.

Provenance tags: **MEASURED** = read this session from the named source. **QUOTED** = taken from a committed record, not re-derived.
**ESTIMATED** = arithmetic on measured inputs, shown. **UNVERIFIED** = not checked this session.

## 0. The answer

1. **The ML research loop is mostly not pointed at money.** Of 234 ML research units authored since 2026-10-01 (ISO weeks 41 to 46),
   **150 (64%) are classifier-quality bake-offs for regime and direction heads**. No regime or direction head changes an order on a
   real-money or prop book. The two units in November that would judge a regime head by money are one `retired` unrun and one `blocked`.
2. **The registry ladder (`candidate → shadow → advisory`) is a second promotion path that no money model has used.** All four model
   lines that change real-money orders reached their books through the strategy ladder (registered rule, held-out PASS, served artifact,
   roster). The registry ladder has produced 3 advisory heads, all gating only BTC legs on `bybit_1` (paper). The weekly `/ml-review`
   checks C2, C3, C5, C6 and C7 key on "every shadow/advisory head", so the review's fixed checks watch the heads and not the money
   models. The operator's 2026-11-12 line ("shadow on paper is only for something that is demoted and in iteration, not a step on the way
   to real money") describes the strategy ladder; the registry ladder and two skills still teach the opposite.
3. **The survivor SLO is miscounted in both directions.** The old proxy reads 0 by construction. The open PR #25184 reads 40 per month,
   but its population contains **14 units whose own structured field says the held-out read did not confirm** (`not_replicated` 11,
   `underpowered` 3), and **14 re-validations of legs that were already trading**. **Zero of the 49 are ML units.** The three ML passes
   that did put a model on real money carry no `evidence_class` and are not counted at all.
4. **The money models' edges are too small to verify on the books they trade.** Foxhound-1's record is +0.037 R per decision at n=907
   (about t = 1.0 at the measured sd of 1.09 R). Confirming that edge live at t = 2 needs about 3,500 closes; `bybit_2` produced 14 in
   11 days. The lever that changes this is **breadth** (the tested 60-perp population, operator rule 2026-11-04), and its unit
   `RQ-20261101-a24c-01` has been blocked on a harness build since 2026-11-01.
5. **Prop ML is underpowered by construction, not unlucky.** Props trade ETH and SOL only. At n=381 (one held-out year, two symbols)
   the smallest edge detectable is about 0.14 R per trade; the pooled model's edge is about 0.03 to 0.04 R. About 40 arms of the same
   feature set on that population cannot find it. A prop ML needs a per-trade effect several times larger, which means new information
   (`PROP-ML-NEW-DATA`), not more arms.
6. **In-trade ML now has five negatives on one state representation** (the dispatch said four; `RQ-20261030-c7a1-01` has since graded
   FAIL). The hindsight ceiling is 0.86 R per trade (QUOTED), so the value exists and the R1 features do not select it.

A better structure, in one line: **one ladder, one inventory keyed on consumers, research capacity allocated by money at stake per slot,
and survivors counted as confirmed results that changed a book.** § 6 ranks the changes.

## 1. Every model on every roster

**Population:** all 106 rows of `GET /api/bot/ml/registry` read 2026-11-12 ~09:40Z (`inventory_read_state: ok`, mirror age 170 s:
98 registry rows + 8 served/candidate/overlay rows), joined to `config/accounts.yaml`, `config/strategies.yaml`,
`config/overlay_policy.yaml` and `config/regime_policy.yaml` at `main@ce4af2fc7`. Account classes are the feed's.

### 1.1 Models that can change an order (12)

| slot | model (name) | what it changes | books (class) | value added: figure · population · provenance |
|---|---|---|---|---|
| D3 | `ml-decision-entry-v1` / `v1r20261106` (Foxhound-1; one lineage, the pointer `ml/served/ENTRY_SERVED.json` serves the refit) | opens long/short | `bybit_2` (real money), `bybit_portfolio` (mirror), `breakout_2`, `tradeify_1`, `velotrade_1` (prop, ETH+SOL), `alpaca_paper` (13 ETFs) | **+0.0371 R/decision, n=907**, held-out 2025-10-01..2026-09-30, the 5 `bybit_2` symbols, `folds_positive: 1` (MEASURED: `comms/strategy_evidence/ml_entry.json`). Forward Oct-2026 −0.0193, n=868; 10-23..11-05 served −0.0918, n=342, se 0.059 (QUOTED: rows `ML-ENTRY-FINETUNE`, `ML-ENTRY-LIVE-MONITOR`). Live: 14 graded closes on `bybit_2`, state `insufficient_n` (MEASURED: `ml_entry_live_monitor_state`, 08:55Z). **Prop gate FAIL**: EV −13.55 USD, p_breach 0.875, n=381; it trades there under a recorded operator exception as a baseline (MEASURED: `comms/prop_survival/ml_entry.json`). ETF scope read FAIL (QUOTED: same evidence file, `RQ-20261101-bdc2-01`). |
| D3 | `ml-entry-eq-struct-ens5-v1` (Foxhound-4) | opens long, ETFs | `alpaca_live` (real money), `alpaca_portfolio` (mirror) | **+0.492 R/trade, n=207**, 2025-07-15..2026-10-31, 113 symbols; iid se 0.076, **month-clustered se 0.239 (t about 2.06)**; third read of the window; 75 of 207 trades fall in 2026-03; slippage provisional. Rule passed at `t_min 0.8528 × iid se` (MEASURED: `comms/strategy_evidence/ml_entry_eq_struct.json`). Live value: UNVERIFIED (no closes read). |
| D3 | `ml-decision-entry-v2` (Foxhound-2) | opens long/short | `bybit_1` (paper) | artifact records `w1_verdict: fail` (MEASURED: `ml/served/ml_decision_entry_v2/model.json`); −0.1161 R, n=320 (QUOTED: MECE § 3). Testing leg in iteration. |
| D3 | `ml-entry-eq-v1` (Foxhound-3) | opens long, ETFs | `alpaca_paper` | +0.0392 R pooled confirm, n=858 (QUOTED: row `ML-ENTRY-ALL-ACCOUNTS`). Testing leg. |
| D7 | `ml-entry-tp-revision-v1` (Labrador-1b) | extends Foxhound-1's TP at 4h check-ins | wherever `ml_entry` trades | +0.0081 R/trade, n=868, forward read (QUOTED: MECE § 3, `RQ-20261101-383f-01`). Live value: UNVERIFIED. |
| D4 | `overlay-td-v1` (Beagle-1) | qty ×0.5 below tau | `reduce`: `trend_donchian_xrp_4h` on `bybit_2` (real money) + mirror, `trend_donchian_eth_prop` on `bybit_1`. `annotate` elsewhere (no order change) | passed `RULE-ML-OVERLAY-NONINFERIOR-V2`, TD family pooled, n=1,830 (QUOTED: MECE § 3.0). One real-money leg. Live decision value: UNVERIFIED. |
| D8 | `exit-head-donchian-1h-v1` (Labrador-2) | — today | `annotate` on 3 `bybit_1` legs | **Changes no order now**: all three legs read `exit_head_action: annotate` (MEASURED: `strategies.yaml`). MECE (11-04) recorded `close` on `trend_donchian_eth`; that has since changed. BTC head failed B4, −0.0141 R/trade, n=1,041 (QUOTED). |
| D2 | `btc-regime-15m-lgbm-fc-pcv-v2` (Collie-5a) | drops intents in `trend_vol` off-cells | 3 BTC legs, all `bybit_1` (paper): `trend_donchian`, `ict_scalp_5m`, `squeeze_breakout_4h` | macro-F1 0.582 (QUOTED: consolidation addendum). No cost-net figure exists for any D2 head (`cost_gate_applicable` 0, QUOTED). Money read of the cells: `RQ-20261101-78fc-08`, `blocked` (MEASURED). `REGIME_ML_VERDICT_MODE` on the VM: UNVERIFIED since 2026-10-28. |
| D2 | `sol-regime-15m-lgbm-fc-pcv-v2` (Collie-5b), `mes-regime-5m-lgbm-v2` (Chihuahua-1d) | nothing | — | advisory stage with **no `trend_vol` cell naming a SOL or MES leg** (MEASURED: `regime_policy.yaml` cells name only the 3 BTC legs). Value added: none measurable. |
| D2 | `m27-derived-xrpusdt-5m-frozen` | vol-bucket off-cells | `ict_scalp_xrp_5m` on `bybit_1` | not a registry row. UNVERIFIED this session. |

**Coverage (MEASURED, re-parsed):** real-money legs with an ML input: 3 of 7 (`ml_entry` and `trend_donchian_xrp_4h` on `bybit_2`,
`ml_entry_eq_struct` on `alpaca_live`). Prop: `ml_entry` on all three accounts, under exception. The whole registry contributes 0 of
those.

### 1.2 Models that change nothing (94)

| group | n | stage (registry) | consumer | note |
|---|---|---|---|---|
| D2 regime heads, shadow | 16 | shadow | none | includes the 4 Mutt baselines (majority-class predictors, QUOTED) |
| D2 regime heads, candidate / research_only | 44 | candidate 43, research_only 1 | none | retire waves in the sibling lane's hands |
| D9 `execution-quality-baseline-v0` | 1 | candidate | none | constant scorer (QUOTED) |
| unassigned (direction, conviction-meta, setup-candidates, trade-outcome, baselines, SSL encoder) | 34 | candidate | none; 2 named by open units | |

Registry stage counts now: advisory 3 · shadow 16 · candidate 78 · research_only 1 (MEASURED: feed and `/api/bot/ml/status`).
`ml/configs/` holds 25 top-level manifests; 69 sit in `ml/configs/retired/` (MEASURED).

## 2. Is the loop pointed at money?

### 2.1 Where ML research units went

**Population:** queue units in `research/queue/RQ-*.yaml` (top level, 2,089 files; the 123 under subdirectories such as `blocked/` are
not in these counts) with an id date from 2026-10-01, classed by `ml_bakeoff` presence and title keywords. Keyword classing is
approximate; the bake-off classes are exact (a structured field).

| ISO week | regime/vol bake-off | direction bake-off | other bake-off | entry (D3) | overlay/meta-label (D4) | in-trade/exit ML (D7/D8) |
|---|---|---|---|---|---|---|
| W41 | 1 | 0 | 1 | 0 | 0 | 2 |
| W42 | 42 | 4 | 1 | 0 | 1 | 17 |
| W43 | 23 | 4 | 3 | 1 | 0 | 7 |
| W44 | 34 | 10 | 0 | 6 | 4 | 7 |
| W45 | 7 | 11 | 0 | 23 | 1 | 2 |
| W46 (to 11-12) | 13 | 1 | 0 | 6 | 1 | 1 |
| **total 234** | **120** | **30** | 5 | 36 | 7 | 36 |

- The question those 150 units ask is "does learner X beat the class prior on log-loss". All 34 held-out ML passes in the last 30 days
  are of this kind (`claim: model_quality`; 33 theme `ml_health`). **None is an edge claim.**
- The weekly frontier scan has dropped "regime/direction learner variants" for three weeks running with the reason
  `business_question: 0 real-money legs` (MEASURED: `comms/ml-plan/20261111T2000Z-ML-FRONTIER-PREP.json`). Units of that kind kept
  being authored: 32 in W45 and W46, and two more were registered today (#25161). **A review call does not reach the authoring side.**
- The same scan's two kept D3 ideas from 11-04 (taker-flow ENTRY, LambdaRank ENTRY) read `not-run … not registered` a week later, and
  this week's kept idea (K1 market-residual target) is "proposed, not queued". **Kept ideas for the money slot wait; dropped ideas for
  the no-money slot run.**
- No unit carries a slot: 0 of 2,089 have a `lifecycle_slot` field. `ML-SLOT-REPORT` (MECE P3) is still queued.

### 2.2 The survivor count

**Population:** units graded in the last 30 days (`grading.graded_at ≥ 2026-10-13`), 1,725 on this checkout; registered-rule passes
on held-out data with an edge claim, by the code on `main` (`research_slo.heldout_pass_census`): **49**.

| class (read from `grading.confirmation` and the title) | n | counts as a survivor? |
|---|---|---|
| verdict `pass`, `confirmation: not_replicated` | 11 | no: the unit's own held-out read failed |
| verdict `pass`, `confirmation: underpowered` | 3 | no |
| exit-lever sweep, `confirmation: confirmed` (a lever on an existing leg) | 13 | a lever result, not a new strategy |
| re-validation of an existing leg as declared (holdout re-runs, "ITERATION 1 … as declared") | 14 | no new capability; the leg keeps its place |
| held-out-selected exit / TP lever on an existing leg, no confirmation field | 5 | a lever result |
| exit-lever sweep with no note | 3 | unknown |
| **ML model or ML leg** | **0** | |

- Why 14 failures read `pass`: `queue_grade.py` grades the unit `pass` when the run's rows all pass, and writes the held-out outcome
  to a separate field (`grading.confirmation`). The census reads only `verdict`. Example: `RQ-20261016-d37f-03`, verdict `pass`,
  `confirmation: not_replicated`, note "A FAIL closes the configuration".
- PR #25184 (open, HOLD for the manager; not merged at 09:30Z) moves the alerting SLO to this census and reports **40 per month and
  70.6 trials per survivor**. It dedupes confirmations of counted parents but does not read `confirmation`. On this audit's read the
  defensible figures are: **confirmed lever results 13 to 18, new legs or models 0**.
- The three ML results that put a model on real money (`RQ-20261101-c692-01` entry, `RQ-20261101-383f-01` moving TP,
  `RQ-20261029-5785-02` overlay) have an empty `evidence_class`, so they fall in `unknown_holdout` (55 units) and are counted nowhere.
- What is still missing from either count is **conversion**: how many passes changed a roster or a config. This checkout is shallow
  (50 commits), so that join was not done here. UNVERIFIED.

### 2.3 The measured symptom, explained

`survivors_per_month 0` and `trials_per_survivor 3457` come from a proxy (Stage-0 pass AND DSR > 0.95 AND BHY haircut > 0) that cannot
fire: PR #25184 records BHY haircut 0.0 on every leg and best DSR 0.54. The number says nothing about research output. The replacement
says 40, which overstates it. Neither tells the operator the thing the SLO is for: **how many confirmed results reached a book**.

## 3. Why the money slots are stuck

### 3.1 D3 entry: the edge is below what the books can confirm (ESTIMATED)

- sd of net R per decision: 0.059 × √342 = **1.09 R** (from the 10-23..11-05 served read).
- Foxhound-1 record: se at n=907 = 1.09 / √907 = 0.036; t = 0.0371 / 0.036 = **about 1.0**. The operator's bar for this model was a point
  estimate ≥ 0 (2026-11-01), and it cleared that bar. This is a statement about what the record can support, not a dispute of the bar.
- To confirm +0.037 R at t = 2 needs (2 × 1.09 / 0.037)² = **about 3,470 closes**. `bybit_2` logged 14 graded closes in 11 days. The
  live monitor's first checkpoint is 50 closes, about four weeks out at this rate. It can catch a large negative (−0.2 R shows at about 120 closes); it
  cannot confirm the edge.
- The weekly forward grade of the retrain workflow (served vs candidate on the trailing window, n about 340 per two weeks, pooled
  population) is the faster signal and already exists. It is the usable demotion signal for the entry line.
- **Breadth is the lever.** The model passed on 60 perps and trades 5. Under the operator's population rule it should trade the passed
  population net of each symbol's costs. That multiplies decisions about twelvefold and is the only route to an edge the books can
  see. The unit that tests it, `RQ-20261101-a24c-01`, is `blocked` on a harness build (the universe-costed subcommand of
  `scripts/research/ml_decision_entry.py`); row `ML-ENTRY-UNIVERSE-LEVER` was due 2026-11-08 and is still queued.

### 3.2 Prop ML: no candidate after about 40 arms (ESTIMATED)

- Smallest detectable edge at n=381, one-sided 5%, 80% power: (1.645 + 0.84) × 1.09 / √381 = **0.139 R per trade**.
- The pooled entry model's edge is 0.03 to 0.04 R. On two symbols and one year it is undetectable, and the prop gate also needs
  positive EV after the firm's drawdown rules.
- About 40 graded arms over the same features on the same two symbols (QUOTED: row `ML-PROP-ITERATE`) is a search inside noise; each
  further arm raises the deflation bar without raising power. The meta-label filter on the prop legs' own trades failed at n=193
  (lift +0.008 R, CI −0.256..+0.263, QUOTED). The prop-specific entry `RQ-20261105-d256-01` has now graded **FAIL** (MEASURED).
- What can work: an effect several times larger per trade. That needs information the price features do not carry
  (`PROP-ML-NEW-DATA`: funding, OI, liquidations, depth), or more tradable symbols on the prop venue (a venue fact, not a model).

### 3.3 D7/D8 in-trade: five negatives on the R1 state

`d6e7-06`, `RQ-20260927-002`, `a7e1-01`, `7294-02` (QUOTED: row `ML-AM-NEXT-LIVE`) and now `RQ-20261030-c7a1-01` (MEASURED: status
`done`, verdict `fail`). The last one was the Stage-A calibration test designed to decide whether the family should move to the
feature block. It failed, so by its own registration the next step is **features, not another policy over R1**. Labrador-1b is the one
positive, and its measured size (+0.0081 R) is an order of magnitude below the 0.86 R hindsight ceiling.

## 4. Infrastructure findings

| # | finding | evidence | effect |
|---|---|---|---|
| I1 | **Two ladders.** The registry's `candidate → shadow → advisory` path, with `gate-check`, `stage-guard`, `shadow_soak` and `live_parity`, runs beside the strategy ladder. No model that changes a real-money order went through it. | § 1; skills `ml-review` (lines 261 to 263: "`shadow → advisory` is the live-trading gate") and `model-training` (lines 17 to 20) | tooling and review effort follow the registry; the operator's stated ladder has no shadow step |
| I2 | **A shadow-stage head could change an order.** `vol_detector.resolve_vol_specs` builds gate edges from shadow-stage heads. | row `REGIME-VOL-SPEC-ADVISORY-ONLY` (in flight; QUOTED) | a registry stage flip is an unguarded order-path change. A direct cost of I1 |
| I3 | **The nightly trainer cycle trains no money model.** Its 25 manifests are regime heads, baselines, conviction-meta, exit-policy, execution-quality and 2 meta-label sets. The entry models refit in a weekly GitHub workflow. | `ls ml/configs/*.yaml`; `/api/bot/ml/status` (`scanned: 25`); row `ML-ENTRY-RETRAIN-CADENCE` | the dedicated training VM (disk 81.4% used, MEASURED) serves the slot with no real-money consumer |
| I4 | **`REGIME_ML_VERDICT_MODE` is a default-off environment switch on an order path** (`off` / `shadow` / `use`). | `src/runtime/runtime_flags.py:174-176` | the shape CLAUDE.md § "The two execution gates" forbids. Its VM value was last read 2026-10-28. Reported; not changed here |
| I5 | **Served artifacts do not name their demotion signal**, and only the entry line has a candidate-to-served rule. | `ml/served/*/model.json` fields read; consolidation doc § D3 | Labrador-1b, the overlay and Foxhound-4 can decay without a registered trigger |
| I6 | **Champions and challengers are not scored on one shard.** | consolidation addendum (QUOTED) | D2 comparisons are not comparisons |
| I7 | **The live inventory now exists** (the consolidated feed, 106 rows with consumers), but the weekly review's checks do not read it. | feed read; skill C-table | the inventory gap MECE named is closed in data and open in process |
| I8 | **Evidence records omit power.** `ml_entry.json` has `expectancy_ci95: null`, `by_side: null`, `mean_gross_r: null`. | file read | a reader cannot tell a t = 1 record from a t = 3 record |

## 5. Workflow findings

| # | finding | evidence |
|---|---|---|
| W1 | `/ml-review` fixed checks are keyed on registry stage ("every shadow/advisory head"). The money models appear only where the analyst adds them. | `.claude/skills/ml-review/SKILL.md` lines 96 to 101, 117, 243 |
| W2 | The frontier scan's **drop** calls do not stop authoring, and its **keep** calls are not registered. | § 2.1 |
| W3 | The scan's own `business_question` gate is right and is applied only to its candidates, not to the queue's generators. | same record: `gate_failed: business_question` |
| W4 | Blockers on money-slot units sit for days while free capacity runs bake-offs: `a24c-01` blocked 11 days; `78fc-08` (do the BTC off-cells earn their keep) blocked. | § 3.1; unit files |
| W5 | The research SLO lane and the ML review do not share a definition of "result". The grader's `pass` means "rows passed", not "held-out confirmed". | § 2.2 |
| W6 | Row files under `docs/claude/work/checklist/` stop at 2026-11-06 for rows created later (for example `ML-RETIRE-WAVES-20261111` has no file); the live register is the work store behind `scripts/ops/work.py`. CLAUDE.md § "The follow-through pipeline" still lists "the work store" as retired. | `ls`, `work.py get` | 

W6 is outside this lane's scope; it is reported to the manager in the lane report, not fixed here.

## 6. Ranked structural recommendations

Expected value is stated as what changes for the operator. Cost is a session ceiling plus free runner time.

| rank | recommendation | expected value | cost | filed as |
|---|---|---|---|---|
| **1** | **Unblock breadth for the entry model.** Build the universe-costed subcommand so `RQ-20261101-a24c-01` runs: the passed 60-perp population, net of each symbol's own costs, filter fixed before the run. | The only route to an entry edge the real-money book can confirm (§ 3.1). Applies the operator's 2026-11-04 rule to the one real-money ML entry. Widening itself stays Tier 3. | Sonnet $8 build + runner | note on existing row **`ML-ENTRY-UNIVERSE-LEVER`** (re-ranked; no new row) |
| **2** | **One ladder for ML.** State once that a model reaches a book the way a strategy does (registered rule, held-out PASS net of cost, served artifact, roster, 1 to 2 mechanical trades). Re-key `/ml-review` C2 to C7 and the `model-training` skill on the consumer inventory (the feed), money models first. The registry `stage` becomes a label for trainer housekeeping, never a promotion step. Removes a path; adds none. | Ends the split in § 4 I1 and I2; the weekly review watches what trades; matches the operator's 2026-11-12 line. | Sonnet $10 (skills + doc, Tier 1); any tooling change is a separate Tier 2 proposal | new row **`ML-ONE-LADDER`** |
| **3** | **Count survivors as confirmed results that reached a book.** Census reads `grading.confirmation`; splits new leg or model / lever on an existing leg / re-validation; stamps `evidence_class` on the money ML units; adds a conversion column (pass → roster or config change). Report-only. | The SLO answers the operator's question. Today it reads 0 or 40 and neither is right (§ 2.2). | Sonnet $6 | new row **`RESEARCH-SLO-SURVIVOR-CONVERSION`**; pointer note on `AUD-20261019-RESEARCH-SLO-RED` (PR #25184) |
| **4** | **Judge the regime slot by money once, then size it.** One pre-registered consumer test: the regime gate on the real-money TD family pooled (MECE P9, due 11-14, never authored), plus unblocking `78fc-08`. Until it reads, the head bake-offs have no decision to feed. | Decides whether 64% of ML research units and the nightly trainer cycle have a customer. A PASS gives D2 its first real-money consumer; a FAIL frees the capacity. | Sonnet $5 to author + runner | new row **`ML-D2-CONSUMER-TEST`** |
| **5** | **Allocate ML research capacity by slot, by money at stake.** The slot report prints units authored per slot per week beside real-money legs per slot. Kept frontier ideas are registered in the scan's own PR. | Makes § 2.1's table a weekly line, so a drop call is visible against what was authored. | inside the existing row | note on existing row **`ML-SLOT-REPORT`** (adds two columns); frontier input F2 |
| **6** | **In-trade ML moves to the feature block.** No further policy units over the R1 state; next unit is a feature-value test on the action-value labels. | Stops a sixth negative on the same state (§ 3.3). | in the ML manager's hands | note on existing row **`ML-AM-NEXT-LIVE`**; frontier input F4 |
| **7** | **Prop ML: stop arm iteration on price features; the open line is new data.** State the power line (§ 3.2) in every prop ML registration. | Stops a search inside noise; points the prop effort at the only lever that can clear 0.14 R. | none | note on existing row **`ML-PROP-ITERATE`**; frontier input F3. The operator's instruction to keep iterating stands; this is the data for choosing the lever |
| **8** | **Power and demotion signal on every served artifact's record:** sd, se, t, clustered se where it exists, trades needed to confirm, named demotion signal. Report-only. | A reader can tell a t = 1 record from a t = 3 record (§ 4 I5, I8). | Sonnet $4 | folded into **`ML-ONE-LADDER`** (inventory columns) |
| **9** | **Re-point the nightly trainer cycle** after rank 4 reads: the heads with a consumer or an open unit, plus the money-model refits. | Trainer VM time and disk follow the money models. | Tier 2, after rank 4 | handed to the sibling lane as a note on **`ML-PROGRAMME-CONSOLIDATION`** |

**Labelled as gates, NOT filed (operator permission needed under "No new gates"):**

- **G1. Raise the real-money bar for an ML promotion** (for example month-clustered t ≥ 2, or a fresh window instead of a third read).
  Foxhound-4 reached `alpaca_live` on `t_min 0.8528 × iid se`; its clustered t is about 2.06 with 36% of trades in one month. This
  would raise a gate. Reported as a risk for the operator, with the numbers in § 1.1.
- **G2. Refuse to author a D2 or direction bake-off that names no consuming leg.** This would be a new authoring gate. The non-gate
  form is rank 5 (report the allocation) and rank 4 (get the money read).

**Sent to the manager, no action by this lane (no demotions here):**

- `ml_entry` trades three prop accounts on a FAIL prop gate under the recorded operator exception; the prop-specific entry
  `d256-01` has now also failed. The exception's premise (a measured baseline while a candidate is found) is worth restating to the
  operator with § 3.2.
- Foxhound-1's two forward reads are negative (−0.0193, n=868; −0.0918, n=342). Both are inside noise at sd 1.09 R. The refit is now
  served. Nothing here meets a demotion rule.
- `sol-regime-15m-lgbm-fc-pcv-v2` and `mes-regime-5m-lgbm-v2` sit at advisory with no leg they can change.
- `REGIME_ML_VERDICT_MODE` (§ 4 I4) and the stale CLAUDE.md line about the work store (§ 5 W6).

## 7. Inputs handed to the frontier scan

Filed as pipeline item `PI-20261112-IXCFGFWB-0001` (due with the next weekly scan).

- **F1. Search where the money is.** Entry (D3) is the slot with real-money and prop consumers. Scan for methods that raise
  **breadth** or **effect size** of a pooled cross-sectional entry model: cross-sectional ranking targets, market-residual targets
  (K1), cost-aware universe selection. Each kept idea is registered in the scan's PR, with its power line.
- **F2. Register last week's keeps.** K1, taker-flow ENTRY and LambdaRank ENTRY are kept and unregistered.
- **F3. Prop: look for large-effect, low-frequency signals on ETH and SOL** (funding extremes, liquidation clusters, basis), where a
  per-trade effect above 0.14 R is plausible. Price-feature arms are exhausted on this population.
- **F4. In-trade: look for state features, not policies.** Order-flow and path features at the check-in that predict action value;
  the Stage-A calibration test is the entry bar.
- **F5. Stop scanning learner families for the regime label** until rank 4 reads. The scan already drops these; say so once in the
  skill's standing notes instead of weekly.
- **F6. Every candidate states the smallest effect its population can detect** (sd about 1.09 R per decision for the entry line), so
  an idea whose expected effect is below that figure is dropped at triage.

## 8. What this lane did and did not verify

- **Verified this session:** the registry feed (106 rows) and trainer status; rosters, ML legs, overlay modes and regime cells from
  config at `main@ce4af2fc7`; `strategy_status.py` output for the four `ml_entry*` legs; the 49-unit census and its classes; the
  per-week unit table; PR #25184's state (open); the live monitor state; the evidence and prop-survival records named in § 1.1;
  unit states for `a24c-01`, `d256-01`, `c7a1-01`, `78fc-07`, `78fc-08`; `ml_plan_status.py --diversity` (gbdt 77 of 106).
- **Not verified:** any live P&L for Foxhound-4, Labrador-1b or the overlay; the VM's `REGIME_ML_VERDICT_MODE`; the trainer's
  `TRAINING_MANIFESTS` (the sibling lane is reading it); pass-to-roster conversion (shallow checkout); the QUOTED figures, which are
  copied from the named records; unit counts exclude 123 files under queue subdirectories.
- **Estimates** in § 3 use one sd (1.09 R, from one two-week window). A different window would move the figures; the orders of
  magnitude would hold for any sd between 0.8 and 1.4 R.

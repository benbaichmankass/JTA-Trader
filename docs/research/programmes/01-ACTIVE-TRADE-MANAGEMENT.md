# Programme 01 — Active trade management: brackets as predictions

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `RESEARCH-PROGRAMMES` (manager dispatch, weekly planning 2026-10-14) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap `M20` + `M31` · **Tier-1 document: it proposes tests; every flip it leads to is Tier-3 with an evidence record.**

> **2026-10-14 amendment (lane `IN-TRADE-EXIT-MODEL`, operator direction via the manager):** the exit line now has a stated **destination — Q8, the in-trade exit model**: at every bar of an open trade, P(SL before TP | state now), and an exit-now rule graded net of cost. Q1–Q7 are the rungs that feed it or ship alongside it; nothing below was removed. The operator's words are verbatim on checklist row `IN-TRADE-EXIT-MODEL`.

## 1. End goal and measure

**Goal.** Every leg's bracket is a prediction that is kept honest through the trade: the TP at entry is where the leg's own history says the move runs out, it is re-estimated every bar from current conditions and moved through the existing `{"tp"}` verdict path, and the SL is the point where we stop waiting — a rule, not a hope. The giveback (a trade that reaches deep profit, pulls back and stops out) shrinks because the TP is reachable and the stop tightens when the thesis dies.

**Measure (headline, operator 2026-10-14).** **Net R per capital-day per leg**, real money first, with the $ figure beside it; at portfolio level weighted by capital. Supporting measures, each with its population stated:

| measure | population | instrument | baseline (MEASURED 2026-10-14) |
|---|---|---|---|
| giveback R = peak R − realised R, per leg and per class | closed trades with a `position_telemetry` row and a readable `peak_r`, joined to `trades` on `order_package_id`, never pooled across account classes | `scripts/research/giveback_census.py` (new, this lane; unit `RQ-20261014-9807-01`, weekly) | **not yet measured** — the first run is the baseline; do not quote one until it lands |
| TP-doctrine compliance | every (account, leg) routing in `config/accounts.yaml` | `python3 scripts/ci/check_tp_doctrine.py --json` | **0 of 50** routings compliant at 07:28Z; real money + prop = 13 routings: real-money entry states 4 sentinel / 3 declared, producer state `no_tp_verdict` on 5 and `rule_undeclared` on 2; all 6 prop routings `declared` / `rule_undeclared` |
| TP amended mid-trade | closed trades since 2026-09-01 with an entry-time target | amend census (PLANNING.md § 5; GEOM-CENSUS row) | 0 of 748 TP amends vs 131 of 752 SL amends (2026-10-07; re-run, do not quote) |
| real-money expectancy | real-money closes | `/api/bot/performance` | −0.3231 R lifetime (n=431, 2026-09-21, pre-cut); latest window n=4 (G1 baseline) |

Doctrine: `docs/ARCHITECTURE-CANONICAL.md` § "TP doctrine" (four clauses). Gate for every lever: the exit-refinement P2 gate, Path A or Path B, then the yearly walk-forward; Path B's bar is decided (5 of 6 folds, maxDD within 0.35× base). Every harness run is net of the full cost stack via `execution_costs.resolve_cost_policy()`.

## 2. Questions, in dependency order

```
Q1 giveback census ──┬──▶ Q4 SL "stop waiting" (cells keyed to the measured giveback)
 (and capital-day)   └──▶ Q5 momentum-turn detector (labels: path rows from Q1 + the corpus)
Q2 entry TP from the leg's own MFE distribution, conditioned on vol & regime
   └──▶ Q3 per-bar TP revision rule (extend-on-thesis / retarget) ──▶ Q6 producer + live parity ──▶ Tier-3 flip
Q7 prop paths (TP amend on dxtrade / phone) ◀── Q6                       ▲
P2 AI trader: Q1/Q5 rows are M23 labels; a head-chosen TP is Q2's step 2 ┘

DESTINATION (Q8): per-bar path data ─▶ first-passage census ─▶ simple state model ─▶ rich (momentum) state model
                  ─▶ exit-now policy net of cost ─▶ harness-native confirmation ─▶ shadow ─▶ Tier-3 proposal
                  (Q4 and Q5 are special cases of Q8: a stop rule and a turn signal are both "exit when P(SL first) is high")
```

| Q | question | why it is first/next | existing units (do not duplicate) |
|---|---|---|---|
| **Q1** | How much R does each live leg give back between its peak and its close, and what is its net R per capital-day? | The pain point has never been a number per leg; every cell choice in Q3/Q4 keys on it | none — new `RQ-20261014-9807-01` |
| **Q2** | Where does each leg's own history say the move runs out — the entry-time TP as an MFE quantile, conditioned on entry volatility and regime? | Clause 1: a sentinel or venue-cap TP is not a prediction; `mi307` shows the real-money "declared" targets mostly rest at the cap and the predictive target sits at 2.0–2.5 R (INFERRED from the 2026-09-18 distribution) | unconditioned finite target: `RQ-20261010-419b-01` (eth_4h, queued), `RQ-20261006-061` (alpaca 1d, queued, expected `infeasible` per leg → family pooling follow-on), monthly E35 sweeps; head version `blocked/RQ-20261009-900/901`; **new conditioned version** `blocked/RQ-20261014-9807-02` |
| **Q3** | Does a per-bar revision rule (extend while the thesis holds; ATR-rescale; stall pull-in) beat the leg's bracket as it trades today, calibration first? | Clause 2; the landed 2026-10-08 runs already hold **PASS rows nobody has read**: `tp_extend` 6/24 cells on `xrp_pullback_2h` and 6/24 on `ada_pullback_2h` (`RQ-20261007-001`, OOS n=49 each), `tp_retarget` 2/9 on `trend_donchian_xrp_4h` (`RQ-20261007-003`, OOS n=31) — 0 ledger dispositions | `RQ-20261007-001/003` (landed), `RQ-20261007-080` (Donchian measured-move, queued); **new confirmation** `RQ-20261014-9807-03` |
| **Q4** | When do we stop waiting — a giveback / exhaustion stop keyed to the measured giveback, and a momentum-keyed time stop? | Clause 3: the trail says when the thesis failed; today the cells are fixed (`gb1R_afterMFE1R/2R`), not keyed to any leg's distribution | `RQ-20261007-042` (ADX-tightening trail), `RQ-20261007-043` (momentum-keyed time stop), monthly M20 sweeps; **new census-keyed cells** `blocked/RQ-20261014-9807-04` |
| **Q5** | Can a per-bar exhaustion signal (bars since peak, ADX falling, range contraction) predict that the rest of the path from here is negative — the "momentum turning" detector? | The operator's stated fix; it is a label study first (P(path from here < 0 | signal)) and only then a lever; the rows are M23 meta-labels for P2 | none; **new** `blocked/RQ-20261014-9807-05` (blocked on `ML-LEG-CORPUS`) |
| **Q6** | Does the live producer reproduce the harness decision (parity), observe-only, on the first confirmed leg? | TP-DOCTRINE B1 merged the verdict contract; no leg declares a rule; a flip is Tier-3 on an evidence record | rows `TP-DOCTRINE`, `GEOM-CENSUS`; soak `target_extension_soak` (B1 design) |
| **Q8 — destination** | **At every bar of an open trade, what is P(SL before TP \| state now) — and is there an exit-now rule (exit when E[R \| hold] < R_now − cost) that beats holding the bracket, net of the full cost stack, out of sample?** | The operator's stated destination (2026-10-14, row `IN-TRADE-EXIT-MODEL`): *"at any given moment, are we going to hit the stop loss before we hit the take profit? … improving them so that they turn from bad trades to good trades."* Entry-time giveback prediction (`RQ-20261014-9d20-01/-03`) is a cheap first rung, not the destination | **new** `RQ-20261014-d6e7-01..05` (runnable chain) + `blocked/RQ-20261014-d6e7-06`; builds `EXIT-PATH-EMIT-OFFLINE` (Tier-1, the priority), `EXIT-PATH-TELEMETRY-LIVE` (Tier-2 proposal) |
| **Q7** | Can the prop paths carry the same bracket (dxtrade REST TP amend plumbed; browser and phone not)? | Prop is the money at stake after real money; `RQ-20261007-002` found 0/24 extension cells on the 6R near-sentinel | rows `PROP-TRAIL-PHONE`, `PROP-EXIT-READ`; re-run `RQ-20261007-002` only after gradable prop closes |

## 3. Test ladders — cheap and decisive first, expensive last

Each rung names its decision rule in the unit; the rung's verdict is what unlocks or retires the next one. "Retire" means the question closes with a stated reason.

### Q1 — giveback census (`RQ-20261014-9807-01`, deterministic, weekly, trainer)
1. **Census over the synced journal, 90 d window** (one run, ~5 min). Rule: report; the record IS the deliverable. Per class with n ≥ 20: if `deep_then_loss` ≥ 0.25 or `giveback_share_of_peak` ≥ 0.5 on the real-money pool → Q4's census-keyed cells are the next rung on that class's legs; if neither, Q4 waits and Q3 goes first. Per-leg rows with n < 20 are listed as `insufficient_n`, never graded.
2. **Weekly re-run** keeps the number live; the manager's brief carries the real-money line. If the trainer's synced journal has no `position_telemetry` table the record reads `producer_failed` and the unit is a route fault (run it from a session on two diag pulls), never a verdict.

### Q2 — entry TP from the leg's own MFE distribution
1. **Unconditioned finite target on the E35 `tp_r` axis**, real-money sentinel legs (`RQ-20261010-419b-01`; `RQ-20261006-061`). Rule in each unit: a reachable finite cell passing IS/OOS at base OOS ≥ 39 → Tier-3 declare proposal; alpaca 1d is expected `infeasible` per leg → the follow-on is a family-pooled unit, not a lower bar.
2. **Calibration read of the declared targets** against realised exits and `peak_r` (`bracket_calibration_report.py --exits --mfe`, session-run on a diag pull). Rule: a declared target whose reach rate is < 0.20 on n ≥ 30 is a sentinel under another name and goes on the TP-doctrine debt list for that leg.
3. **Conditioned target** (`blocked/RQ-20261014-9807-02`): MFE quantile per leg × entry-vol tercile × ADX bucket from config-exact uncapped harness emits. Rule: PASS if the conditioned quantile's calibration error is lower than the unconditioned one in ≥ 2 of 3 vol terciles on every real-money stratum with n ≥ 30 per cell AND the conditioned bracket's OOS net R per capital-day is ≥ the unconditioned; retire the conditioning otherwise (the unconditioned quantile stays the answer, as `ml2-predictive-bracket-2026-09-06.md` found). Unblocks on `ML-LEG-CORPUS` (retained emits).
4. **Head-chosen per-trade target** (`blocked/RQ-20261009-900/901`) only if rung 3 passes — a head on top of a conditioning that added nothing is a variation, not a model.

### Q3 — per-bar TP revision
1. **Confirmation of the landed PASS cells on a fresh partition, calibration first** (`RQ-20261014-9807-03`, runner, ~1 h): the 6+6 `tp_extend` cells and the 2 `tp_retarget` cells, `split_mode=date`, a split the 2026-10-08 run did not use, with `--tp-report` calibration beside the base. Rule: CONFIRMED if the cell clears Path A or Path B on the fresh partition AND `tp_cal_cell` ≥ `tp_cal_base` on both IS and OOS AND the walk-forward wins ≥ 5 of 6 folds → Q6 on that leg (Tier-3 declare proposal with the record); "P&L without prediction" (gate cleared, calibration worse) is a FAIL by doctrine; otherwise INDETERMINATE and the cell waits for the monthly re-sweep.
2. **Measured-move revision** (`RQ-20261007-080`, queued) on the Donchian money legs — its rule is registered; read it when it lands.
3. **Scalps** (`RQ-20261007-004` landed 0/5 on all 7 scalp legs): retired for revision; the scalp family's question is the time stop (`RQ-20261013-407c-08/18`).
4. **Expensive rung:** a revision rule conditioned on the regime head's state (P2 feed) — only after rung 1 confirms at least one leg, because a conditioned rule on a leg where the plain rule fails is noise.

### Q4 — SL "stop waiting"
1. **Momentum-keyed stop and time stop** (`RQ-20261007-042/043`, queued) — read against their registered rules.
2. **Census-keyed giveback cells** (`blocked/RQ-20261014-9807-04`): `giveback_r` ∈ {p25, p50 of the leg's measured giveback}, `giveback_min_mfe_r` ∈ {1.0, p50 of peak}, plus `trail_decay` stall bars from the median `bars_since_peak`. Rule: Path B on `net_r_per_capital_day` with maxDD within 0.35× base, 5 of 6 folds → Tier-3 declare; retire the census-keyed idea for that leg if neither census cell beats the fixed `gb1R_afterMFE1R` cell. Unblocks on a `cells` input on the m20 sweep (build row proposed to the manager).
3. **Expensive rung:** cross-signal stop (regime flip + exhaustion) — only after a census-keyed cell confirms, and only through the regime-selectivity skill's rules.

### Q5 — momentum-turn detector (label study)
1. **Label study** (`blocked/RQ-20261014-9807-05`): on per-trade path rows (harness emits for the 7 real-money legs + live telemetry rows where final), does `bars_since_peak ≥ k` or an ADX fall of ≥ x from its peak predict `remaining_path_r < 0` with a lift over the base rate that clears a permutation null at p < 0.05 on n ≥ 300 trades? Rule: PASS → the signal becomes (a) a Q4 cell and (b) an M23 meta-label feature in the signals catalog; FAIL → retire as a stop trigger, keep as a catalog entry marked `no_lift`.
2. **Lever** (harness `--momentum-stale-*` already exists) only on a PASS.

### Q8 — the destination: the in-trade exit model (row `IN-TRADE-EXIT-MODEL`)

**Framing.** At every bar *t* of an open trade, estimate P(SL first | state_t) as a first-passage problem (outcomes: TP first, SL first, time-out), and exit at bar *t* when E[R | hold, state_t] < R_exit_now − cost. Graded by **net P&L per capital-day vs the fixed bracket** (the headline measure), net of the full cost stack, out of sample, per leg and pooled. **The free null:** for a driftless walk P(SL before TP from open R *x*) = (K − *x*)/(K + 1) (gambler's ruin) and E[R | hold] = *x* exactly, so any exit a policy takes is its model's information speaking. On bars that closed form is *not* a fair null (discrete passage, SL-first on a shared bar, the horizon) — `first_passage.py --self-test` shows a model "beating" it on a pure random walk — so every information claim is graded against a **calibrated distance-only reference** fitted on the same folds, and the policy exits only when the model's E[R | hold] is below the reference's by more than the extra exit cost.

**Why ML-S2 failed, and what is different.** Three exit heads failed offline on price features (`docs/plans/ml-plan-items.yaml` ML-S2: donchian −14.66 R OOS on `RQ-20260927-002`; S2-exit INDETERMINATE on `RQ-20260929-401`, SOL −4.30 / XRP +0.21 / ETH −1.16; XRP multi-fold FAIL `RQ-20261008-900`, 1 of 3 folds, pooled −1.94 R). They were LightGBM heads on a per-trade "does holding pay" target, one leg or family at a time, graded on ~20–120 OOS trades per fold. What Q8 changes: **(1) per-bar labels** — every bar of every trade is an event with a first-passage outcome, so the model learns *when* in a trade, not *which* trade; **(2) a ~3,000-trade corpus** (the committed crypto ledgers re-walked over public candles), pooled because a first-passage event in R is comparable across legs; **(3) a first-passage target with a closed-form null and a calibrated distance-only reference**, so "the model learned where the trade is" cannot pass as information; **(4) a linear model before a GBDT** — on the earlier n the GBDT had room to fit noise; a richer learner is earned by a linear PASS. What is **not** different: price-derived features are still most of the state; flow joins only through Programme 02 Q5.

**The binding gap — per-bar in-trade path data.** Harness `--emit-trades` rows are per-trade (`mfe_r`, a lagged lower bound); live `position_telemetry` is one upserted row per position; MAE is recorded nowhere. Two builds: **`EXIT-PATH-EMIT-OFFLINE`** (Tier-1, the priority — `--emit-paths` in the harnesses with the stop and target in force at every bar, so the leg *as it trades* is captured; it does not wait for live data) and **`EXIT-PATH-TELEMETRY-LIVE`** (Tier-2 proposal — an append-only per-bar history beside the upsert, for live parity and later shadow serving). **Consumers:** the exit-arm bandit `RQ-20261011-9da8-04` and the momentum-turn label study `blocked/RQ-20261014-9807-05` consume the **offline** emit (the bandit needs per-bar states under each ladder arm; 9807-05 needs per-bar ADX/ATR/open_r); 9807-05 reads the live history only as its parity check, never pooled. **Interim, not waiting:** `scripts/research/first_passage.py` re-walks the committed ledgers over public candles with a **fixed bracket** (initial SL at −1 R, TP at K R), which is enough to ask the operator's question of a plain bracket now.

| rung | test | rule (registered on the unit) | unlock / retire | unit |
|---|---|---|---|---|
| 8.1 | **First-passage label census**: P(TP/SL/time-out first) per K ∈ {1, 1.5, 2, 3} R vs K/(K+1); share of SL-first trades that first reached 0.5/0.75/0.9 K ("very close to the TP"); turn-oracle saving (best close before the SL, minus the extra exit cost); bar-level calibration of p0; fixed-bracket net R per capital-day | PASS at K = 2 if n_sl_first ≥ 300 and the oracle saving ≥ 0.25 R/trade; FAIL < 0.10 R | sizes the prize, funds 8.2/8.4; a random walk has headroom too, so it proves nothing about predictability | `RQ-20261014-d6e7-01` (runnable now) |
| 8.2 | **Simple state** (distance to TP/SL in ATR, bars in trade, open R, bars since peak, giveback) vs the calibrated distance-only reference, trade-weighted OOS log-loss, 4 purged time folds | PASS: gain ≥ 0.002 nats, CI > 0, ≥ 3/4 folds, calibration slope 0.7–1.3; FAIL: CI upper < 0.002 | PASS → 8.3 | `RQ-20261014-d6e7-02` (on 8.1 PASS) |
| 8.3 | **Exit-now policy on the simple model** vs holding the bracket, same OOS trades | PASS: ≥ +0.05 R/trade, CI > 0, ≥ 3/4 folds, capital-day guard, p0 sanity control < 5% exits; FAIL: CI upper < 0.05 R | PASS → 8.6 | `RQ-20261014-d6e7-03` (on 8.2 PASS) |
| 8.4 | **Rich state** — momentum in ATR, ADX and its slope, range contraction, close location, ATR-percentile regime — vs the same reference ("momentum suddenly turns") | as 8.2 | PASS → 8.5; runs on 8.1 PASS whatever 8.2 says | `RQ-20261014-d6e7-04` (on 8.1 PASS) |
| 8.5 | **Exit-now policy on the rich model** | as 8.3 | PASS → 8.6 | `RQ-20261014-d6e7-05` (on 8.4 PASS) |
| 8.6 | **Harness-native confirmation**: the passing policy against each real-money leg's *actual* exit (trailing, TP revision, stale), per family, 6-fold walk-forward | PASS: ≥ +0.05 R/trade, CI > 0, ≥ 5/6 folds, maxDD ≤ 1.35× | → exit-refinement P2 gate → observe-only shadow (needs `EXIT-PATH-TELEMETRY-LIVE` for parity) → Tier-3 proposal with the record | `blocked/RQ-20261014-d6e7-06` (on `EXIT-PATH-EMIT-OFFLINE` + 8.3/8.5 PASS) |
| 8.7 | Flow features (funding, OI, taker imbalance) and a GBDT/sequence learner | only after a linear PASS; through Programme 02 Q5 information classes | — | not filed (earned by 8.2/8.4) |

Q4 and Q5 are special cases of Q8 (a stop rule and a turn signal are each "exit when P(SL first) is high"); they stay as written and their verdicts are inputs, not competitors: a 9807-05 PASS signal enters 8.4's state.

### Q6 / Q7 — producer, parity, prop (builds, then one soak each)
Observe-only soak of the declared rule (`target_extension_soak`) on the confirmed leg for 1–2 executed trades (mechanics, not calendar time — `docs/CLAUDE-RULES-CANONICAL.md` § "Promotion evidence"), then the Tier-3 flip with the evidence record; mirror equality by test. Prop: dxtrade REST path first (TP amend plumbed), phone path via the server-computed amend ticket (BUILD B2).

## 4. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows, proposed to the manager) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-21) | **Q8:** `RQ-20261014-d6e7-01` first-passage census (runnable now); on its PASS `d6e7-02` and `d6e7-04` dispatch. `RQ-20261014-9807-01` first census run; `RQ-20261014-9807-03` confirmation; read `RQ-20261007-042/043/080`, `RQ-20261010-419b-01` as they land; disposition the 2026-10-08 PASS rows in the ledger | `GEOM-CELLS-INPUT` (a `cells` input on `m20-exit-lever-sweep.yml`; Tier-1); raise `ML-LEG-CORPUS` to the top of the ML lane (it unblocks 4 units); **`EXIT-PATH-EMIT-OFFLINE`** (Tier-1, `--emit-paths` on the trend + pullback harnesses first) | census baseline → is Q4 or Q3 the second rung per class |
| **W2** (to 10-28) | **Q8:** read `d6e7-02/04`; `d6e7-03/05` (policies) dispatch on their PASS; `RQ-20261014-9807-04` once cells exist; `RQ-20261014-9807-02` once emits are retained; alpaca 1d family-pooled finite-target unit (061's named follow-on) | TP-DOCTRINE B1: draft the declared rule for the first CONFIRMED leg (no flip) | first Tier-3 declare proposal, or an honest "no cell confirmed" |
| **W3** (to 11-04) | **Q8:** `d6e7-06` harness-native confirmation once the path emit lands and a policy passed; `RQ-20261014-9807-05` label study (on the offline path emit); second-leg confirmation on the monthly re-sweep | observe-only soak of the declared rule on the confirmed leg; prop dxtrade TP amend soak | parity read: harness decision == live decision on 1–2 trades |
| **W4** (to 11-11) | census re-read: did giveback move on the flipped leg (population: that leg's closes since the flip; expect `insufficient_n`, say so) | Tier-3 flip PR with the record; GEOM-CENSUS weekly rerun observed | second leg enters Q6; the programme's W5+ plan is re-cut from the measured state |

### 2026-10-16 re-cut — the running backlog (lane `P1-ATM-BACKLOG-1016`, operator: *"a lot of emphasis on trade management today"*)

The tree [`research/programmes/01-active-trade-management.yaml`](../../../research/programmes/01-active-trade-management.yaml) is the machine-read form of this section. Its header says what changed and why. Every runnable question below is a materialised, pre-registered unit, ordered by money at stake. Every follow-on is a node gated on its prerequisite's verdict, registered before that verdict exists.

**Why the re-cut (MEASURED 2026-10-16):**
- `check_tp_doctrine.py --json`: 0 of 54 routings are compliant.
- The fixed predictive-TP screen (RQ-20261015-cab7-01..06) returned INDETERMINATE on ada, xrp_pullback, xrp_4h, the pooled conditioned set and the alpaca 1d family. It FAILED on eth_4h. It was never run on the prop legs.
- Every m20 PASS cell on a real-money or prop leg sat on one IS/OOS split, with no folds and no materiality read. Six of those P1 units were ungradable as registered (RESEARCH-GRADE-PILE). They are closed INDETERMINATE in this PR, with the honest_negative legs their own rules allow.

| money | unit | node | question |
|---|---|---|---|
| bybit_2 | RQ-20261016-009 | P1-Q3-xrp-pb-tpx-confirm | the 6 tp_extend cells that passed twice, 6 calendar folds, ≥ 0.02 R/trade |
| bybit_2 | RQ-20261016-008 | P1-Q3-ada-pb-tpx-confirm | the 5 tp_extend cells that passed twice |
| bybit_2 | RQ-20261016-005 | P1-Q4-eth4h-momentum-confirm | adx20_k0_t2.5 / ms12_a20 / ms12_a25 on the sentinel leg |
| bybit_2 | RQ-20261016-006 | P1-Q4-eth4h-stalldecay-rerun | the operator's a1df-01 question, re-asked without the failed record control |
| bybit_2 | RQ-20261016-015 | P1-Q4-xrp4h-exit-confirm | momentum / giveback / tp_retarget cells over the whole history (68 trades, 4 folds) |
| bybit_2 + prop | RQ-20261016-004 | P1-Q2-solprop-derive | sol_prop's predictive TP (6R reached by 1.9%) |
| bybit_2 + prop | RQ-20261016-011 | P1-Q4-solprop-rrfloor-confirm | rrfloor0.5 at Bybit costs |
| alpaca_live | RQ-20261016-014 | P1-Q2-alpaca-1d-pooled | the 1d family's predictive TP on the longest dukascopy window, gld added |
| alpaca_live | RQ-20261016-016 | P1-Q4-slv1d-ms-confirm | ms8_a20 on slv 1d |
| prop | RQ-20261016-007 | P1-Q2-ethprop-derive | eth_prop's predictive TP (6R reached by 0.9%) |
| prop | RQ-20261016-010 | P1-Q4-ethprop-exit-confirm | 4 exit cells at the PROP cost stack |
| Q8 | RQ-20261016-013 | P1-Q8.4-indet-policy | the decisive money test on the rich state (supersedes d6e7-05) |
| Q8 | RQ-20261016-012 | P1-Q8.2-fail | the registered refinement: rich state at K = 3R |
| soak books | RQ-20261016-017..021 | P1-Q4-*-soak-confirm | gdx / gld / qqq / splg / spy m20 cells, priority 3 |

**Gated follow-ons:**
- Ten nodes are gated, each `after:` its unit: the Q6 declare/parity steps per confirmed leg, the prop EV/survival scoring, the harness-native K* confirmations and the K = 3R policy rung.
- Two ready `needs_authoring` nodes carry row PROP-EXIT-UNITS' prop questions, for research-ops.

**Not authored, with the reason:**
- ief, iwm and scha are below the 39-trade floor on the runner's history.
- A longer-window fixed TP for ada and xrp_pullback cannot reach power.
- The census-keyed stop cells (blocked/RQ-20261014-9807-04) stay blocked. Ledger-derived giveback reads negative on 20–50% of trades, because `mfe_r` is a lagged lower bound (MEASURED in the lane sandbox). They need EXIT-PATH-EMIT-OFFLINE.

**Builds filed:**
- ABLATION-TP-CALIBRATION: calibration-first for revision cells.
- QUEUE-GEN-ROSTER-SYNC: the generator minted 7 duplicate keys and never retires off-roster legs. 17 such sweep units were retired in this PR, each with a reason.

**Q8 decision points:** the 8.1 census sets whether the prize funds the model rungs; 8.2/8.4 say whether the state carries information beyond where the trade is; 8.3/8.5 say whether that information pays for its exits. A FAIL at any rung is written back to row `IN-TRADE-EXIT-MODEL` and to `ROADMAP.md` L-ATM with the number; the live-history proposal `EXIT-PATH-TELEMETRY-LIVE` is scheduled only when a policy PASS needs a shadow.

**What this plan does not do.** It changes no config, roster or account (all Tier-3 flips are proposals with records). It does not re-open the entry-time ladder answered `honest_negative` ×6 on 2026-08-10, nor the scalp revision question (0/5 ×7 legs). It does not treat a paper or mirror book as evidence of edge; mirrors carry the real-money verdicts by roster equality. Numbers above marked MEASURED were measured this session from the files named; the 2.0–2.5 R predictive-target figure is INFERRED from the 2026-09-18 MFE distribution and must be re-derived by Q2 before it is used.

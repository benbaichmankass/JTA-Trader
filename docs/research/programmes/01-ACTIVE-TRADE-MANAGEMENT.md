# Programme 01 — Active trade management: brackets as predictions

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-14` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `RESEARCH-PROGRAMMES` (manager dispatch, weekly planning 2026-10-14) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap `M20` + `M31` · **Tier-1 document: it proposes tests; every flip it leads to is Tier-3 with an evidence record.**

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
```

| Q | question | why it is first/next | existing units (do not duplicate) |
|---|---|---|---|
| **Q1** | How much R does each live leg give back between its peak and its close, and what is its net R per capital-day? | The pain point has never been a number per leg; every cell choice in Q3/Q4 keys on it | none — new `RQ-20261014-9807-01` |
| **Q2** | Where does each leg's own history say the move runs out — the entry-time TP as an MFE quantile, conditioned on entry volatility and regime? | Clause 1: a sentinel or venue-cap TP is not a prediction; `mi307` shows the real-money "declared" targets mostly rest at the cap and the predictive target sits at 2.0–2.5 R (INFERRED from the 2026-09-18 distribution) | unconditioned finite target: `RQ-20261010-419b-01` (eth_4h, queued), `RQ-20261006-061` (alpaca 1d, queued, expected `infeasible` per leg → family pooling follow-on), monthly E35 sweeps; head version `blocked/RQ-20261009-900/901`; **new conditioned version** `blocked/RQ-20261014-9807-02` |
| **Q3** | Does a per-bar revision rule (extend while the thesis holds; ATR-rescale; stall pull-in) beat the leg's bracket as it trades today, calibration first? | Clause 2; the landed 2026-10-08 runs already hold **PASS rows nobody has read**: `tp_extend` 6/24 cells on `xrp_pullback_2h` and 6/24 on `ada_pullback_2h` (`RQ-20261007-001`, OOS n=49 each), `tp_retarget` 2/9 on `trend_donchian_xrp_4h` (`RQ-20261007-003`, OOS n=31) — 0 ledger dispositions | `RQ-20261007-001/003` (landed), `RQ-20261007-080` (Donchian measured-move, queued); **new confirmation** `RQ-20261014-9807-03` |
| **Q4** | When do we stop waiting — a giveback / exhaustion stop keyed to the measured giveback, and a momentum-keyed time stop? | Clause 3: the trail says when the thesis failed; today the cells are fixed (`gb1R_afterMFE1R/2R`), not keyed to any leg's distribution | `RQ-20261007-042` (ADX-tightening trail), `RQ-20261007-043` (momentum-keyed time stop), monthly M20 sweeps; **new census-keyed cells** `blocked/RQ-20261014-9807-04` |
| **Q5** | Can a per-bar exhaustion signal (bars since peak, ADX falling, range contraction) predict that the rest of the path from here is negative — the "momentum turning" detector? | The operator's stated fix; it is a label study first (P(path from here < 0 | signal)) and only then a lever; the rows are M23 meta-labels for P2 | none; **new** `blocked/RQ-20261014-9807-05` (blocked on `ML-LEG-CORPUS`) |
| **Q6** | Does the live producer reproduce the harness decision (parity), observe-only, on the first confirmed leg? | TP-DOCTRINE B1 merged the verdict contract; no leg declares a rule; a flip is Tier-3 on an evidence record | rows `TP-DOCTRINE`, `GEOM-CENSUS`; soak `target_extension_soak` (B1 design) |
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

### Q6 / Q7 — producer, parity, prop (builds, then one soak each)
Observe-only soak of the declared rule (`target_extension_soak`) on the confirmed leg for 1–2 executed trades (mechanics, not calendar time — `docs/CLAUDE-RULES-CANONICAL.md` § "Promotion evidence"), then the Tier-3 flip with the evidence record; mirror equality by test. Prop: dxtrade REST path first (TP amend plumbed), phone path via the server-computed amend ticket (BUILD B2).

## 4. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows, proposed to the manager) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-21) | `RQ-20261014-9807-01` first census run; `RQ-20261014-9807-03` confirmation; read `RQ-20261007-042/043/080`, `RQ-20261010-419b-01` as they land; disposition the 2026-10-08 PASS rows in the ledger | `GEOM-CELLS-INPUT` (a `cells` input on `m20-exit-lever-sweep.yml`; Tier-1); raise `ML-LEG-CORPUS` to the top of the ML lane (it unblocks 4 units) | census baseline → is Q4 or Q3 the second rung per class |
| **W2** (to 10-28) | `RQ-20261014-9807-04` once cells exist; `RQ-20261014-9807-02` once emits are retained; alpaca 1d family-pooled finite-target unit (061's named follow-on) | TP-DOCTRINE B1: draft the declared rule for the first CONFIRMED leg (no flip) | first Tier-3 declare proposal, or an honest "no cell confirmed" |
| **W3** (to 11-04) | `RQ-20261014-9807-05` label study; second-leg confirmation on the monthly re-sweep | observe-only soak of the declared rule on the confirmed leg; prop dxtrade TP amend soak | parity read: harness decision == live decision on 1–2 trades |
| **W4** (to 11-11) | census re-read: did giveback move on the flipped leg (population: that leg's closes since the flip; expect `insufficient_n`, say so) | Tier-3 flip PR with the record; GEOM-CENSUS weekly rerun observed | second leg enters Q6; the programme's W5+ plan is re-cut from the measured state |

**What this plan does not do.** It changes no config, roster or account (all Tier-3 flips are proposals with records). It does not re-open the entry-time ladder answered `honest_negative` ×6 on 2026-08-10, nor the scalp revision question (0/5 ×7 legs). It does not treat a paper or mirror book as evidence of edge; mirrors carry the real-money verdicts by roster equality. Numbers above marked MEASURED were measured this session from the files named; the 2.0–2.5 R predictive-target figure is INFERRED from the 2026-09-18 MFE distribution and must be re-derived by Q2 before it is used.

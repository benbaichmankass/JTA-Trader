# TP doctrine W43: compliance drive, proposals and units (2026-10-22)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-22` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Lane `TP-DOCTRINE-W43` (session_017BJaq4hC2mKhEmPT76E6Xm), dispatched by the manager on 2026-10-22.
The operator's week priority is TP doctrine compliance. Doctrine:
[`docs/ARCHITECTURE-CANONICAL.md`](../ARCHITECTURE-CANONICAL.md) § "TP doctrine". Method:
[`.claude/skills/exit-refinement/SKILL.md`](../../.claude/skills/exit-refinement/SKILL.md) § "The TP doctrine binds every lever".

**Re-run the measurement before you quote any count here:** `python3 scripts/ci/check_tp_doctrine.py`.

## 1. Compliance now (MEASURED, `main` @ `66cc9083`, 2026-10-22)

Population: every (account, leg) routing in `config/accounts.yaml`, all 14 accounts whatever their `mode`.

| class | routings | `entry_tp` FAIL | `tp_revision` FAIL | compliant |
|---|--:|--:|--:|--:|
| real_money | 7 | 4 | 6 | 0 |
| prop | 6 | 6 | 6 | 0 |
| mirror | 6 | 3 | 5 | 0 |
| paper | 33 | 21 | 32 | 0 |
| **total** | **52** (26 distinct legs) | 34 | 49 | **0** |

The pre-read was 54 routings. The drop to 52 is #19403 (`ief_pullback_1d` left `alpaca_live` and
`alpaca_portfolio` today), not a guard change.

### Are the guard's counts right? (field beats comment)

- **Routing and leg counts reconcile.** I parsed `config/accounts.yaml` independently: bybit_1 7 + bybit_2 5 +
  bybit_portfolio 5 + ib_paper 9 + alpaca_paper 14 + alpaca_portfolio 1 + alpaca_live 2 +
  alpaca_options_paper 3 + 3 prop × 2 = **52**. The union of leg names is **26**. Both match the guard.
- **The class split matches the YAML.** `bybit_portfolio` and `alpaca_portfolio` carry `paper_role: portfolio`
  and grade as mirror. `breakout_1`, `ib_live` and `oanda_practice` have empty rosters, so they contribute no
  routings.
- **`trend_donchian_eth_4h` reads correctly.** It grades `entry_tp = sentinel`, `producer = produces_tp_verdict`.
  The measured-move `tp_revision` block is declared (`config/strategies.yaml`, since 2026-10-18), but the
  bracket it places at entry still carries `tp_r: 50`. Only the first revision replaces that level. So
  "entry sentinel, revision compliant" is the true state of the field, not a guard bug.
- **No bug found, but one leniency to report.** `grade_reach` fails entry_tp only on `below_floor`. A declared
  target that has no reach evidence (`unmeasured`), or too few trades (`thin`), or bounds straddling the floor
  (`unresolved`), still grades `entry_tp = declared` and passes. The doctrine text says unmeasured targets are
  "counted beside the verdict, never counted reachable". The guard does that in its summary line
  (`unmeasured=9`), but the per-routing dimension passes them anyway. Today that covers **9 paper
  routings**: `iwm_trend_long_1d`, `qqq_trend_long_1d` and `spy_trend_long_1d` (each on alpaca_paper and
  ib_paper), `scha_trend_long_1d`, `mgc_pullback_1d` (6 R, the same figure that fell below the floor on the
  Donchian prop legs) and `ict_scalp_mgc_15m`. Paper only, no money at stake. It becomes a real gap the day one
  of these legs is promoted. I reported this to the manager and did not change the guard: tightening a
  ratchet's grading is a doctrine decision.

## 2. The method finding behind most of the remaining debt

Every TP-lever unit run on these legs since 2026-10-16 asked a **replacement** question: beat the incumbent by
`0.02 R × n(A)` in 5 of 6 folds. That bar fits a P&L-motivated swap. The doctrine makes compliance itself the
motive, though, and the materiality bar makes compliance unreachable for any revision that is roughly
P&L-neutral. MEASURED from the committed verdicts:

| unit | leg | best TP cell | Δ net R | folds ≥ A | maxDD vs A | failed on |
|---|---|---|--:|--:|---|---|
| RQ-20261016-009 | xrp_pullback_2h (n 394) | X6 tp_extend | **+1.75** | **6/6** | equal | materiality only (bar 7.88 R) |
| RQ-20261016-009 | xrp_pullback_2h | X5 tp_extend | +1.25 | 6/6 | equal | materiality only |
| RQ-20261016-008 | ada_pullback_2h (n 449) | X4 tp_extend (4R anchor) | +0.51 | 5/6 | equal | materiality only (bar 8.98 R) |
| RQ-20261018-024 | trend_donchian_sol_prop (n 400) | T4 fixed 4R | +1.05 | 3/6 | better | folds + materiality |
| RQ-20261018-022 | trend_donchian_sol_prop | R2 stall-pull-in | +2.08 | 3/6 | better | folds + materiality |

These are **post-hoc reads of spent windows, not evidence.** The registered rules said FAIL and the thresholds
stand. Grading a known number under a new rule would be forking paths. The units in § 4 therefore re-ask the
compliance question in one of two ways:

- **out of sample by symbol**, on legs never used to select the cells; or
- with **arms never run** on the leg.

A disjoint pre-history was the first design. It is not available: the harness's candle source is Binance
**USD-M perps**, which start on 2020-01-06. MEASURED in the lane sandbox: xrp_pullback_2h's declared arm has
**21 trades** on 2020-01..2020-06, below the 39 floor. An earlier draft of this doc assumed spot candles from
2018. That was wrong, and the probe caught it before any unit was written on that premise.

In both cases the decision rule is registered before any candidate number exists. The compliance bar keeps
the programme's fold supermajority, the 0.35 drawdown tolerance and the 39-trade floor. The materiality term
is set to 0. Nothing else changes. Each PASS still has to clear the registered **doctrine read** before it
can be proposed:

- `tp_share`, the realised reach of the final target, must be ≥ 0.10;
- the lever must fire;
- net R per capital-day must not fall.

## 3. Proposals table: every failing leg, by money at stake

**Exclusions** (other lanes own them; not redone here):

- the alpaca 1d pullback family, tp_r 3.5 (`iaum`, `slv`, `ief`, `gdx`, `gld`, `tlt`; lane OPERATOR-DECISIONS-1022, row TP-DECLARE-ALPACA-PB1D);
- `trend_donchian_eth_prop` at tp 2.5 (DECISION-BAR-MATCH / TP-ETHPROP-2P5);
- the `trend_donchian_xrp_4h` trail (OPERATOR-DECISIONS-1022).

**Proposals settled by existing committed evidence, for the manager to execute: NONE new.** The only TP PASS on
a non-excluded leg is RQ-20261018-007 (eth_4h measured move, width 0.5), and it is already declared live
(TIER3-PACKETS-1018, 2026-10-18). Its doctrine read clears:

- clamped share 1374/3319 = 0.414, under 0.5;
- net R per capital-day 0.1936 against A's 0.1873.

The other passes are either excluded or on the stop side, not the TP:

- RQ-20261016-015 and RQ-20261019-017 are on xrp_4h (excluded; no producer either);
- RQ-20261016-005 is eth_4h momentum stops (stop side).

| # | leg | routings at stake | fails | evidence read (MEASURED) | disposition |
|---|---|---|---|---|---|
| 1 | `trend_donchian_sol_prop` | bybit_2 (real) + 3 prop + bybit_portfolio + bybit_1 | entry_tp (6 R, reach 1.9%) + tp_revision | K* 2.5 screen PASS (RQ-20261016-004); harness confirm FAIL (-006: K25 -4.67 R, 2/6); fixed 3R/4R FAIL (-024); stall-pull-in FAIL (-022). Measured move never run on this leg | **(b) unit `RQ-20261022-bea9-03`**: reachable 3 R entry + measured move (width 0.5 / 1.0), compliance bar, 2020-10..2026-10 (arms new to this window). Prop routings additionally wait on the prop EV/survival gate (P1-Q4-solprop-propcost) |
| 2 | `trend_donchian_eth_4h` | bybit_2 (real) + bybit_portfolio + bybit_1 | entry_tp only (50 R at entry) | static K* FAIL (cab7-04). The measured-move revision is live (RQ-20261018-007 PASS) and can compute a target at the signal bar | **BUILD, not research**: seed the entry TP from the declared rule at bracket construction. Pipeline `PI-20261022-PT76E6XM-0001` (Tier-3, harness arm plus guard grading included) |
| 3 | `xrp_pullback_2h` | bybit_2 (real) + bybit_portfolio + bybit_1 | tp_revision only (entry 3 R, reach 0.246) | tp_extend X5/X6 6/6 folds on the spent window, failed materiality (§ 2). Fixed 3R/4R FAIL (-020). cab7-02 indeterminate | **(b) units `RQ-20261022-bea9-01/-02/-04`**: X5/X6 against the same static 3R target on the sibling pullback_2h legs eth / sol / avax, 2020-07..2026-10, compliance bar 5/6 folds. Registered family read: the cell generalises iff the same cell passes on ≥ 2 of 3, and then it is xrp's evidence record. Needs the pullback-unit tp producer (TP-DOCTRINE B1) before any declare |
| 4 | `ada_pullback_2h` | bybit_2 (real) + bybit_portfolio + bybit_1 | tp_revision only (entry 4 R, reach 0.241) | X4 +0.51 R 5/6 on the spent window, failed materiality. 2.5R-anchored cells lost. Fixed 3R FAIL (-006). cab7-01 indeterminate | **follows the family read**: no new unit, because ada's own window is spent and its signal (+0.51 R, 5/6) is weaker than xrp's. If the 3R-anchored cell generalises, ada's registered follow-on is a 4R-anchored replay of that cell. If not, ada's route is the in-trade exit model (Programme 01 Q8). Same producer dependency |
| 5 | trend-long 1d sentinels: `qld`, `tqqq`, `splg` (alpaca_paper), `mes` (ib_paper) | paper | entry_tp + tp_revision | per-leg e35 bracket sweeps retired. No reach curve: mi307 has no rows for them | **deferred**: paper, lowest money. Next unit: a pooled `tp_prediction_derive.py` K* screen (the cab7-06 shape) |
| 6 | trend-long 1d declared: `spy`, `qqq`, `iwm` (alpaca_paper + ib_paper), `scha` | paper | tp_revision (entry `unmeasured`, see § 1) | none on TP revision | **deferred**: measured move is a Donchian rule and these are Donchian breakouts (`backtest_trend.py`), so it is the natural first arm. Per-leg 1d n is thin, so pool or accept INDETERMINATE |
| 7 | `mhg_pullback_1d`, `mgc_pullback_1d` (ib_paper) | paper | mhg entry + rev; mgc rev (6 R unmeasured) | none | **deferred**: the same unit family as the alpaca 1d pullback decision. Fold into that lane's follow-on rather than re-derive |
| 8 | `ict_scalp_mgc_15m` (ib_paper) | paper | tp_revision | none | **deferred** |
| 9 | shadow 1h trends: `slv_trend_1h`, `mgc_trend_1h`, `trend_donchian_1h` | paper, `execution: shadow` | entry_tp + tp_revision | none | **deferred**: shadow, no orders. Answer at promotion time (exit-refinement: "every NEW strategy answers the geometry question at wiring time") |

Rows 5 to 9 are paper or shadow. They are named here and handed back to the manager, not silently dropped.
This lane's $20 ceiling went to the real-money and prop rows first, as the doctrine's priority order requires.

## 4. Units authored (pre-registered, hashed ids, `status: queued`)

| id | leg | window | baseline → candidates | bar | baseline n (MEASURED) |
|---|---|---|---|---|--:|
| `RQ-20261022-bea9-01` | eth_pullback_2h (sibling) | 2020-07-01..2026-10-15 | S3 static 3R → X5, X6 tp_extend | net R > S3, ≥ 5/6 folds, DD ≤ 1.35×, n ≥ 39 | 375 |
| `RQ-20261022-bea9-02` | sol_pullback_2h (sibling) | same | same | same | 148 |
| `RQ-20261022-bea9-04` | avax_pullback_2h (sibling) | same | same | same | 422 |
| `RQ-20261022-bea9-03` | trend_donchian_sol_prop | 2020-10-01..2026-10-15 (arms never run) | A declared → tp_r 3.0 + measured move w0.5 / w1.0 | net R > A, ≥ 5/6 folds, DD ≤ 1.35× | 400 |

How the baseline n was measured:

- For the sibling units, I ran **only the baseline arm S3** in the lane sandbox. No candidate arm was run on
  any sibling, so each rule was registered before any candidate number existed.
- For sol_prop, n(A) = 400 comes from the committed RQ-20261018-006 arm A on the identical window and cost
  stack.

Every unit was checked with the `dispatch_queue.py --only <id>` dry run, and each returned `would_dispatch`
(§ 5).

## 5. Verification run in this lane

- `python3 scripts/ci/check_tp_doctrine.py`, re-run on `main` @ `66cc9083` (§ 1).
- Committed verdicts read: RQ-20261015-cab7-01/02/04, RQ-20261016-004/008/009, RQ-20261017-001/002,
  RQ-20261018-006/007/022/024, RQ-20261019-006/020. The § 2 numbers come from their `verdict.json`.
- Baseline-arm-only probes, lane sandbox: `exit_lever_ablation.py --grade stage0`, one baseline arm, no
  candidate arm.
  - xrp_pullback_2h: n=21 on 2020-01..2020-06 (perp data start). This killed the pre-window design.
  - S3 (static 3R) on 2020-07-01..2026-10-15: eth_pullback_2h n=375, sol_pullback_2h n=148,
    avax_pullback_2h n=422.
- `dispatch_queue.py --only RQ-20261022-bea9-0{1,2,3,4}` (dry run): all four `would_dispatch`,
  route=runner backend=github_runner.
- `check_research_queue_decision_rule.py`: OK.
- The row note for `TP-DOCTRINE-W43` was **not** written. The row is not on `main` yet: it lands with the
  manager's PR #19473, branch `mgr/weekly-planning-1022`. This doc is the record, and the report to the
  manager carries its path.
- Follow-up build filed in the pipeline: `PI-20261022-PT76E6XM-0001` (row 2, eth_4h entry-TP seeding).

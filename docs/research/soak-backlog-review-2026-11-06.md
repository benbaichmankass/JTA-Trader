# Soak-backlog review: every TESTING leg against its Stage-0 record (2026-11-06)

> **Doc status:** `live` · category `evidence` · last verified `2026-11-06` · lane `SOAK-BACKLOG-REVIEW` (dispatched by Manager Session 2026-11-06a)
> · findings appended to row [`SOAK-VOCAB-RETIRE`](../claude/work/checklist/SOAK-VOCAB-RETIRE.json)

**Gates this adds or changes: none.** No roster, config or record is edited. Nothing places an order.

## The question

The operator, 2026-11-06 ~18:55Z, said that legs which passed backtesting and are waiting on paper for a number of trades
should be on live money now, and that legs which have not passed go back into the iteration loop. The operator added: *"everything
that's already soaking probably passed a backtest, so it needs to be on live money now."* This review checks that last
sentence against the committed records, one leg at a time.

## Answer: no testing leg passes its Stage-0 bar today, so nothing is promoted

**Population:** every leg `scripts/ops/strategy_status.py` derives as `testing`, re-read from `config/accounts.yaml` and
`config/strategies.yaml` at `1d52e2294` (origin/main, 2026-11-06). That is **56 legs**: 53 on a general-paper book plus 3 unhomed
1h legs (`qqq/spy/tlt_pullback_1h`). Population printed by the script: 61 legs = inactive 3 + production 2 + testing 56.

| disposition | legs | what happens next |
|---|---:|---|
| **PASS** (full-cost record clears the registered rule and the holdout) | **0** | nothing to promote |
| **NEITHER**: passes every Stage-0 clause except the holdout | 6 | a holdout confirmation of the configuration the leg actually runs (§ A) |
| **NEITHER**: the harness did not model a lever the leg runs (`fidelity: approximate`) | 7 | a faithful re-run (5 of them are also n < 30) |
| **NEITHER**: the record's own rule passes but n < 30 closed (1d single-symbol legs) | 6 | a pooled population test (`RQ-20261106-018`, leg-corpus trend_1d) |
| **NEITHER**: no usable Stage-0 record | 5 | the record has to be measured first |
| **FAIL**: the rule failed, folds positive in only 2 of 4, or the holdout failed | 32 | iteration loop; every one has a live unit except the 3 unhomed 1h legs (§ C) |

Arithmetic check: 0 + 6 + 7 + 6 + 5 + 32 = 56. FAIL breaks down as: 23 with `decision_rule.verdict: fail`, 5 that pass their own rule
but are positive in only 2 of 4 folds at n ≥ 30 (`mgc_trend_1h`, `qqq_pullback_1h`, `uso_trend_1h`, `xrp_pullback_2h`, `trend_donchian_eth`),
2 with holdout `no_discovery` (`scha_trend_long_1d`, `ief_pullback_1d`), and 2 with no per-leg record: `e4_oi_shock_1h` (its strategy
record `e4_oi_shock.json` reads rule fail) and `ml_entry_v2` (W1 fresh-window read −0.1161 R at n = 320, RQ-20261101-b609-01).
23 + 5 + 2 + 2 = 32.

**The premise does not hold on the records.** Legs that "already passed a backtest and are only waiting for trades" do not exist.
The six closest legs all stop at one clause: the operator's 2026-10-16 holdout requirement (PROMOTION-BAR-MULTIPLICITY, *"Require
holdout"*). In every one of the six, the holdout confirmed a **different configuration** from the one the leg trades today (§ A).
A real-money promotion on any of them would rest on an unconfirmed configuration, so none is promoted. The bar is the operator's own,
not a new gate.

### How each leg was measured (reproducible)

`scripts/ops/mandate_resolver.py --leg <leg> --from S1 --to S2 --account <target>` was run for every testing leg. The target is
`bybit_2` for a `bybit_1` leg, `alpaca_live` for an `alpaca_paper` leg and `ib_live` for an `ib_paper` leg.

- **Run as-is**, most crypto legs stop at `R-SOAK-NOT-PASSED`. That is the soak clause the operator has retired, and it reads a soak
  snapshot dated **2026-10-04** (`comms/mandate_evidence/soak_state/2026-10-04.json`). That stop is not evidence about edge.
- **Run a second time with the soak/mechanics clause bypassed in-process**, plus affordability and cost fidelity, which are mechanical
  and monitoring clauses. This exposes the first failing **Stage-0** clause: B1 C1–C5 and identity, n ≥ 30, expectancy > 0 and equal
  to net/n, fold majority, then the holdout. The table's "first failing clause" column is that second run.
- **Mechanics** are reported separately, from `soak_state.mechanics_proven` as the resolver reads it.

Every record's harness is the per-family research harness (`pullback`, `trend`, `ict_scalp`, …) with cost stack
`{fees, slippage, funding}`. None is `scripts/backtest_orb.py` or `src/backtest/backtester.py`, so none is fee-only.

## A. The six holdout-blocked legs: closest to real money, and why each still is not there

| leg | Stage-0 record | holdout read | live config vs confirmed config | mechanics | path to real money |
|---|---|---|---|---|---|
| `ada_pullback_2h` | n 61, +31.46 R, 3/4, faithful | RQ-20261016-077e-04 **confirmed** C7, n_h 97, +24.08 R | C7 = live on the swept params, **but** `vol_skip_above_pctl: 0.95` (+ `decision_bar`) was added 2026-10-18 (`da294c415`): fingerprint `f651509c…` ≠ confirmed `a1ea6323…` | proven (own soak) | (a) clean holdout of today's config: **`RQ-20261106-5b7a-01`** (boundary 2026-10-19, `not_before` 2027-04-16); or (b) Tier-3: revert to the confirmed config, rebuild the record, promote |
| `trend_donchian_eth_4h` | n 135, +44.64 R, 3/4, faithful | 077e-02 **confirmed** C3, n_h 75, +19.23 R | `tp_revision` (TP doctrine) and `trail_decay_*` were added 2026-10-18 (`48490ab35`, `afdbb8a19`): `0613df05…` ≠ `e0b2c33a…` | proven (own soak) | (a) **`RQ-20261106-5b7a-02`** (`not_before` 2027-06-07); (b) is NOT clean: reverting drops the TP-doctrine `tp_revision` |
| `trend_donchian_xrp_4h` | n 46, +7.71 R, 3/4, faithful | 077e-03 **confirmed** C1 (atr 1.5, trail 4.0), n_h 25, +4.13 R | live is atr 2 / trail 5.0; nothing else differs | proven (own soak) | Tier-3: set C1, rebuild the record at C1 (it must still clear n ≥ 30 / folds), attach the holdout block, promote |
| `trend_donchian_sol_prop` | n 395, +48.03 R, 4/4, faithful | 077e-05 **confirmed** C5 (trail 4.5), n_h 96, +5.28 R | live trail 3.5; nothing else differs | proven (own soak) | same as xrp_4h; prop superset: `comms/prop_survival/trend_donchian_sol_prop.json` verdict `pass` (p_breach 0.595 on that ruleset) |
| `slv_trend_1h` | n 68, +53.14 R, 4/4, faithful | 5a03-02 **confirmed** C1 (atr 1.0), n_h 26, +18.28 R | live atr 1.5; **and** `tp_r` is the 50.0 sentinel (TP doctrine non-compliant) | proven (own soak) | existing clean-holdout unit `RQ-20261104-7fdb-02` (real TP, `not_before` 2027-03-16); the C1 stop is an open separate question |
| `trend_donchian_xrp_adx25` | n 46, +9.72 R, 3/4, faithful | **never run** | alias keys `trail_adx_*` last set 2026-10-22 (`f8a9b6fd7`) | not proven (no own soak; same Bybit path as xrp_4h) | **`RQ-20261106-5b7a-03`** (`not_before` 2028-08-21 at its measured held-back rate of ≈ 0.038 trades/day) |

**Why the new units wait.** Each of the three new holdout units starts its held-back span strictly after the leg's last parameter
choice. This is the `RQ-20261104-7fdb-02` precedent: a span every later parameter choice could already see is not "never-seen". At
each leg's measured held-back entry rate, reaching the floor of 25 to 30 trades takes until the dates above. **The fast path for
`trend_donchian_xrp_4h`, `trend_donchian_sol_prop` and `ada_pullback_2h` is a Tier-3 configuration change to the holdout-confirmed
configuration.** That is evidence-backed, but it is not this lane's call, because the units that produced those holdouts
pre-registered *"ON PASS with another arm selected: … evidence for a Tier-3 config proposal, never an edit here"*. Handed to the manager.

## B. Build mechanics first

None of these legs passes Stage 0, so nothing is held back by mechanics alone today. Under the operator's 2026-11-03 rule the build
track is independent of the edge track, so the missing pieces are listed here:

- **`ib_live` (IB futures):** `gld_pullback_1d`, `mgc_pullback_1d`, `mgc_trend_1h`, `mhg_pullback_1d`, `mes_trend_long_1d` and
  `ict_scalp_mgc_15m` trade only on `ib_paper`. `ib_live` has **no mirror account** (`ib_portfolio`; OPERATING-PLAN § 2 Q3: *"mirror
  when it gets a leg"*) and **no IB bracket path in `config/mechanics_paths.yaml`**. The resolver credits `gld_pullback_1d` as
  "proven" only through the *Alpaca* path, which is not the account it would trade on. Missing: an `ib_portfolio` account, and one
  clean small IB bracket trade registered as a path.
- **Bybit perp path not registered:** `config/mechanics_paths.yaml` has no Bybit entry. Several crypto legs have passed own soaks
  (`ada_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `trend_donchian_sol_prop`, `trend_donchian_eth_prop`,
  `xrp_pullback_2h`), and `ml_entry` trades on `bybit_2`, but a leg without its own passed soak reads "not proven" (e.g.
  `trend_donchian_xrp_adx25`). Registering `bybit_perp_bracket_v1` is a records edit for the first Bybit promoting PR.
- **Two crypto legs are alias/variant config only** (`trend_donchian_xrp_adx25`, `trend_donchian_sol_prop`): `delta: none` on that path.

## C. FAIL → the iteration loop (every leg and its live unit)

`python3 scripts/research/iteration_orphans.py` was run before and after this lane:

- **Before:** 15 testing legs were orphans with no live iteration unit.
- **The fix:** `queue_replenish.py --target 400 --write` expanded the pre-registered `roster-walkforward` template for 12 of them.
  Each unit carries a diagnosis from the leg's own attribution: `RQ-20261106-019` … `-036`, plus `-018`, the pooled leg-corpus
  trend_1d unit for the n < 30 group. The new holdout units also cover 3 legs.
- **After:** 3 orphans remain: **`qqq_pullback_1h`, `spy_pullback_1h`, `tlt_pullback_1h`**. These are the unhomed legs owned by
  `ALPACA-SLICES-REHOME-1H`. The template only expands *rostered* legs, so an unhomed testing leg can never get a generated iteration
  unit. That gap is filed to the pipeline.

The per-leg unit ids are in the table's last column.

## D. Other findings, filed

1. **Live prop legs do not clear the prop superset.** `trend_donchian_eth_4h` and `trend_donchian_sol_4h` sit on live prop rosters
   (`breakout_2`, `tradeify_1`, `velotrade_1`). Under RULE-P5-GATE-BRK-PER-LEG-V3, `eth_4h` reads `fail_edge` and `sol_4h` reads
   `contested` (`comms/prop_survival/*.json`). Neither clears the real-money Stage-0 bar either: `eth_4h` has no holdout of its
   current config, and `sol_4h` is `approximate` fidelity. `prop-roster-gate-guard` checks only diffs, so it cannot see this.
   **Flagged to the manager; not changed here** (removing a live prop leg is Tier 3).
2. **The resolver's soak clause still gates promotion**, and it reads a 33-day-old snapshot. `MD-PROMOTE-S1-S2` `bar.soak_passed:
   true` plus `bar.mechanics_proven` stop every crypto leg without an own soak at `R-SOAK-NOT-PASSED (state None)`. Appended to
   `SOAK-VOCAB-RETIRE`: the rewire has to retire this clause and the soak-state snapshot input. Mechanics should stay as a path
   record, not a soak.
3. **`iteration_orphans.leg_verdict` reads `ml_entry.json` for `ml_entry_v2` and `ml_entry_eq`**, through the stem fallback, and so
   labels both `pass_unconfirmed`. The real reads are a fail for v2 and indeterminate for eq. Filed.

## Per-leg table

Columns: target is the real-money account the resolver was asked about. "First failing clause" comes from the second run, with the
soak, affordability and cost-fidelity clauses bypassed. Mechanics come from the resolver's own `soak_state` read.

| leg | books | target | record (harness, fidelity) | n | net R | folds+ | rule verdict | holdout | first failing clause | mechanics on target | disposition | iteration unit(s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ada_pullback_2h | bybit_1 | bybit_2 | pullback, faithful | 61 | 31.4579 | 3/4 | pass | 077e-04 pass on 10-16 config; live changed 10-18 | NEEDS-DATA R-HOLDOUT | proven (own_soak) | NEITHER: holdout | RQ-20261105-007,RQ-20261106-5b7a-01 |
| avax_pullback_2h | bybit_1 | bybit_2 | pullback, approximate | 52 | -8.2515 | 2/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-008 |
| claude_desk | alpaca_paper, bybit_1, ib_paper | bybit_2, alpaca_live, ib_live | — | — | — | —/— | — | none | NEEDS-DATA R-RECORD-MISSING | not proven; ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: no record | RQ-20261026-e535-03 |
| e4_oi_shock_1h | bybit_1 | bybit_2 | — | — | — | —/— | — | none | NEEDS-DATA R-RECORD-MISSING | not proven | FAIL (record e4_oi_shock.json: rule fail) | RQ-20261101-78fc-11 |
| eth_pullback_2h | bybit_1 | bybit_2 | pullback, approximate | 56 | -5.6094 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-34,RQ-20261105-019 |
| eth_pullback_prop_2h | bybit_1 | bybit_2 | pullback, approximate | 65 | -9.249 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-20,RQ-20261105-020,RQ-20261106-019 |
| fade_breakout_4h | bybit_1 | bybit_2 | fade, faithful | 28 | -14.2839 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-52,RQ-20261105-021 |
| fvg_range_15m | bybit_1 | bybit_2 | fvg_range, faithful | 18 | -9.4121 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-53,RQ-20261105-022 |
| gdx_pullback_1d | alpaca_options_paper, alpaca_paper | alpaca_live | pullback, approximate | 10 | 1.2338 | 2/4 | pass | none | REFUSE R-B1-C5 | proven (path_soak alpaca_equity_bracket_v1) | NEITHER: fidelity + n < 30 | RQ-20261105-023 |
| gld_pullback_1d | ib_paper | ib_live | pullback, faithful | 8 | 10.5108 | 4/4 | pass | none | NEEDS-DATA R-N | proven (path_soak alpaca_equity_bracket_v1); ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: n < 30 | RQ-20261105-024 |
| htf_pullback_trend_2h | bybit_1 | bybit_2 | pullback, approximate | 90 | -19.6825 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-026,RQ-20261106-020 |
| iaum_pullback_1d | alpaca_paper | alpaca_live | pullback, faithful | 8 | 10.6758 | 4/4 | pass | 077e-08 indeterminate (n 24) | NEEDS-DATA R-N | proven (path_soak alpaca_equity_bracket_v1) | NEITHER: n < 30 | RQ-20261105-027 |
| ict_scalp_5m | bybit_1 | bybit_2 | ict_scalp, faithful | 146 | -42.456 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-44,RQ-20261105-028 |
| ict_scalp_avax_5m | bybit_1 | bybit_2 | ict_scalp, faithful | 186 | -48.6833 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-029 |
| ict_scalp_eth_15m | bybit_1 | bybit_2 | ict_scalp, faithful | 76 | -2.925 | 2/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-030 |
| ict_scalp_mgc_15m | ib_paper | ib_live | ict_scalp, None | — | — | —/— | — | none | REFUSE R-SOURCE-RUN-ABSENT | not proven; ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: no record | RQ-20261105-031,RQ-20261101-78fc-13 |
| ict_scalp_sol_15m | bybit_1 | bybit_2 | ict_scalp, faithful | 87 | -12.496 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-032 |
| ict_scalp_sol_5m | bybit_1 | bybit_2 | ict_scalp, faithful | 181 | -31.4854 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-033 |
| ict_scalp_xrp_15m | bybit_1 | bybit_2 | ict_scalp, faithful | 74 | -2.8065 | 2/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261105-034 |
| ict_scalp_xrp_5m | bybit_1 | bybit_2 | ict_scalp, approximate | 163 | -32.879 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-46,RQ-20261105-035 |
| ief_pullback_1d | alpaca_paper | alpaca_live | pullback, approximate | 6 | 1.0316 | 1/3 | pass | 077e-06 FAIL no_discovery | REFUSE R-B1-C5 | proven (own_soak) | FAIL | RQ-20261105-036 |
| iwm_trend_long_1d | alpaca_paper, ib_paper | alpaca_live, ib_live | trend, faithful | 8 | 2.1071 | 2/4 | pass | none | NEEDS-DATA R-N | proven (path_soak alpaca_equity_bracket_v1); ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: n < 30 | RQ-20261105-037,RQ-20261106-021 |
| mes_trend_long_1d | ib_paper | ib_live | trend, faithful | 5 | -1.0012 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven; ib_live has no mirror (ib_portfolio) and no registered IB path | FAIL | RQ-20261106-001,RQ-20261106-022 |
| mgc_pullback_1d | ib_paper | ib_live | pullback, approximate | 8 | 3.8725 | 3/4 | pass | none | REFUSE R-B1-C5 | not proven; ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: fidelity + n < 30 | RQ-20261106-002,RQ-20261106-023 |
| mgc_trend_1h | ib_paper | ib_live | trend, faithful | 118 | 25.612 | 2/4 | pass | none | REFUSE R-FOLDS | not proven; ib_live has no mirror (ib_portfolio) and no registered IB path | FAIL | RQ-20261106-004 |
| mhg_pullback_1d | ib_paper | ib_live | pullback, approximate | 10 | 4.0986 | 2/4 | pass | none | REFUSE R-B1-C5 | not proven; ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: fidelity + n < 30 | RQ-20261106-005 |
| ml_entry_eq | alpaca_paper | alpaca_live | — | — | — | —/— | — | none | NEEDS-DATA R-RECORD-MISSING | not proven | NEITHER: no record | RQ-20261106-003 |
| ml_entry_v2 | bybit_1 | bybit_2 | — | — | — | —/— | — | none | NEEDS-DATA R-RECORD-MISSING | not proven | FAIL (W1 read -0.1161 R, n 320) | RQ-20261105-002 |
| qld_trend_long_1d | alpaca_paper | alpaca_live | trend, faithful | 9 | 2.9844 | 3/4 | pass | none | NEEDS-DATA R-N | proven (path_soak alpaca_equity_bracket_v1) | NEITHER: n < 30 | RQ-20261101-78fc-37,RQ-20261106-006 |
| qqq_pullback_1h | — | alpaca_live | pullback, faithful | 55 | 10.8351 | 2/4 | pass | none | REFUSE R-FOLDS | not proven | FAIL | — (ORPHAN) |
| qqq_trend_long_1d | alpaca_paper, ib_paper | alpaca_live, ib_live | trend, faithful | 8 | 5.2971 | 2/4 | pass | none | NEEDS-DATA R-N | proven (path_soak alpaca_equity_bracket_v1); ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: n < 30 | RQ-20261106-007 |
| scha_trend_long_1d | alpaca_paper | alpaca_live | trend, faithful | 78 | 4.6442 | 5/8 | pass | 5a03-01 FAIL no_discovery | NEEDS-DATA R-HOLDOUT | proven (path_soak alpaca_equity_bracket_v1) | FAIL | RQ-20261106-008 |
| slv_pullback_1d | alpaca_options_paper, alpaca_paper | alpaca_live | pullback, approximate | 10 | 3.0026 | 2/4 | pass | 077e-07 pass, sel C1 ≠ live | REFUSE R-B1-C5 | proven (path_soak alpaca_equity_bracket_v1) | NEITHER: fidelity + n < 30 | RQ-20261106-009 |
| slv_trend_1h | alpaca_options_paper, alpaca_paper | alpaca_live | trend, faithful | 68 | 53.1431 | 4/4 | pass | 5a03-02 pass, sel C1 ≠ live | NEEDS-DATA R-HOLDOUT | proven (own_soak) | NEITHER: holdout | RQ-20261104-7fdb-02,RQ-20261106-010 |
| sol_pullback_2h | bybit_1 | bybit_2 | pullback, approximate | 17 | 6.9287 | 2/4 | pass | none | REFUSE R-B1-C5 | not proven | NEITHER: fidelity + n < 30 | RQ-20261106-011 |
| splg_trend_long_1d | alpaca_paper | alpaca_live | trend, None | — | — | —/— | — | none | REFUSE R-SOURCE-RUN-ABSENT | proven (path_soak alpaca_equity_bracket_v1) | NEITHER: no record | RQ-20261106-012 |
| spy_pullback_1h | — | alpaca_live | pullback, approximate | 75 | -8.5535 | 2/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | — (ORPHAN) |
| spy_trend_long_1d | alpaca_paper, ib_paper | alpaca_live, ib_live | trend, faithful | 11 | 2.3816 | 3/4 | pass | none | NEEDS-DATA R-N | proven (path_soak alpaca_equity_bracket_v1); ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: n < 30 | RQ-20261106-013 |
| squeeze_breakout_4h | bybit_1 | bybit_2 | squeeze, faithful | 14 | -2.8132 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-54,RQ-20261106-014 |
| tlt_pullback_1d | alpaca_paper, ib_paper | alpaca_live, ib_live | pullback, approximate | 134 | 12.6901 | 5/8 | pass | be01-01 indeterminate (n 22) | REFUSE R-B1-C5 | proven (own_soak); ib_live has no mirror (ib_portfolio) and no registered IB path | NEITHER: fidelity | RQ-20261106-015 |
| tlt_pullback_1h | — | alpaca_live | pullback, approximate | 94 | -6.7285 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | — (ORPHAN) |
| trend_donchian | bybit_1 | bybit_2 | trend, approximate | 71 | -16.226 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261106-017 |
| trend_donchian_1h | bybit_1 | bybit_2 | trend, approximate | 159 | -16.0939 | 1/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261106-024 |
| trend_donchian_ada_4h | bybit_1 | bybit_2 | trend, approximate | 43 | -6.3445 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261106-025 |
| trend_donchian_avax_4h | bybit_1 | bybit_2 | trend, approximate | 47 | -11.0224 | 0/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261106-026 |
| trend_donchian_eth | bybit_1 | bybit_2 | trend, approximate | 108 | 6.9034 | 2/4 | pass | none | REFUSE R-B1-C5 | not proven | FAIL | RQ-20261106-027 |
| trend_donchian_eth_4h | breakout_2, bybit_1, tradeify_1, velotrade_1 | bybit_2 | trend, faithful | 135 | 44.6385 | 3/4 | pass | 077e-02 pass on 10-16 config; live changed 10-18 | NEEDS-DATA R-HOLDOUT | proven (own_soak) | NEITHER: holdout | RQ-20261106-028,RQ-20261106-5b7a-02 |
| trend_donchian_eth_prop | bybit_1 | bybit_2 | trend, faithful | 165 | -0.2512 | 1/4 | fail | none | REFUSE R-B1-C4 | proven (own_soak) | FAIL | RQ-20261106-029 |
| trend_donchian_sol | bybit_1 | bybit_2 | trend, approximate | 58 | -2.8779 | 2/4 | fail | none | REFUSE R-B1-C4 | not proven | FAIL | RQ-20261101-78fc-30,RQ-20261106-030 |
| trend_donchian_sol_4h | breakout_2, bybit_1, tradeify_1, velotrade_1 | bybit_2 | trend, approximate | 116 | 36.8572 | 3/4 | pass | none | REFUSE R-B1-C5 | not proven | NEITHER: fidelity | RQ-20261106-031 |
| trend_donchian_sol_prop | bybit_1 | bybit_2 | trend, faithful | 395 | 48.0322 | 4/4 | pass | 077e-05 pass, sel C5 ≠ live | NEEDS-DATA R-HOLDOUT | proven (own_soak) | NEITHER: holdout | RQ-20261106-032 |
| trend_donchian_xrp_4h | bybit_1 | bybit_2 | trend, faithful | 46 | 7.712 | 3/4 | pass | 077e-03 pass, sel C1 ≠ live | NEEDS-DATA R-HOLDOUT | proven (own_soak) | NEITHER: holdout | RQ-20261106-033 |
| trend_donchian_xrp_adx25 | bybit_1 | bybit_2 | trend, faithful | 46 | 9.7183 | 3/4 | pass | none | NEEDS-DATA R-HOLDOUT | not proven | NEITHER: holdout | RQ-20261106-034,RQ-20261106-5b7a-03 |
| turtle_soup | bybit_1 | bybit_2 | — | — | — | —/— | — | none | REFUSE R-SOURCE-RUN-ABSENT | not proven | NEITHER: no record | RQ-20261101-78fc-12 |
| uso_trend_1h | alpaca_paper | alpaca_live | trend, faithful | 56 | 25.8924 | 2/4 | pass | none | REFUSE R-FOLDS | proven (path_soak alpaca_equity_bracket_v1) | FAIL | RQ-20261106-035 |
| xrp_pullback_2h | bybit_1 | bybit_2 | pullback, faithful | 53 | 6.5558 | 2/4 | pass | 077e-01 pass, sel C5 ≠ live | REFUSE R-FOLDS | proven (own_soak) | FAIL | RQ-20261106-036 |

## Revert

This lane edits no roster, config or record, so there is nothing to revert. The new queue units are reverted by deleting
`research/queue/RQ-20261106-018..036.yaml` and `RQ-20261106-5b7a-01..03.yaml`.

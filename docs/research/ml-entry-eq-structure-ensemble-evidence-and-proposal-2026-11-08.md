# ml_entry_eq structure ensemble — evidence record (RQ-20261107-98e3-06) and a Tier-3 PROPOSAL (2026-11-08)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · lane ML-ENTRY-EQ-STRUCTURE-RETEST
> Gates this adds or changes: none. **This is a proposal only. Nothing is wired, no config or roster changes; the operator decides.**

## 1. Evidence record

Unit `RQ-20261107-98e3-06`, run 42432561069 (record `comms/research/RQ-20261107-98e3-06/42432561069/`; the run's verdict string says `pass`). Model: config B, **mean of 5 pinned LightGBM fits** (seeds 1-5) on structure-exit labels (`pivot=5;sl_only`, SL 2 / TP 3 ATR14, 24-bar stop), refit on rows <= 2025-06-30 (purge 10 d), tau dev-selected over {0.20, 0.25}: **0.25** (dev OOF +0.1323, n 1691; tau 0.20 read +0.1035, n 3009). Window 2025-07-15..2026-10-31, the **third** read of it (after the fixed-bracket read and the single-seed structure read). Costs: fee 0, slippage 5 bps (PROVISIONAL), regulatory 0.5 bps round trip.

| | value |
|---|---|
| n / symbols | **207** trades / 113 symbols (pool 173) |
| mean net R (gross / cost) | **+0.4922** (+0.5427 / 0.0505) |
| iid se, t | 0.0758, **6.5** |
| month-clustered se, t | 0.2389, **2.06** |
| registered bar (true N=3, t_min 0.8528) | 0.8528 x 0.0758 = **0.065** |
| rule (a) mean >= bar / (b) dev OOF > 0 / (c) mean >= +0.04 | met / met (+0.1323) / met |

**Registered verdict: PASS**, and it would also clear N=4 (~0.08). The run itself recorded `n_tries 2` (t_min 0.5198) because the repo holdout ledger lacked the 98e3-01 read; the ledger rows were repaired in PR #24187. The pass does not depend on which N is used.

### What it does not say
- **Small n.** 207 trades; the month-clustered t is ~2.1, and a deflated CI bar is not cleared on the clustered se.
- **Confirm is ~4x dev.** +0.49 on the window against +0.13 dev OOF at the same tau: this reads more like a favourable window than a stronger model. The earlier reads on this window: fixed bracket +0.039 (n 858), single-seed structure +0.212 (n 570).
- **Concentration.** 2026-03 is 75 of 207 trades at +0.66; without it the mean is +0.396 (n 132), without 2026-01 and 2026-03 it is +0.42 (n 87). 11 months have trades, 9 are positive (2025-07 -1.25 n 3, 2025-12 -0.56 n 5, 2026-06/07 none).
- **Dev folds 2 and 3 are negative** (-0.11, -0.27 at tau 0.25), as in every configuration run; fold 3 is the 2024-H2 period.
- **Fit noise is the size of the effect.** Seed spread at tau 0.20 is 0.047 R (RQ-20261107-98e3-04); the 5-seed mean is +0.092.
- **Same window as three other reads** (declared). No fourth read is registered.

## 2. Proposal: a Stage-1 TESTING leg on alpaca_paper (not alpaca_live)

Stage 1 is a mechanics instrument, not a decision surface (CLAUDE.md); the edge is decided offline, and 06 is the held-out record. Proposed shape: **a new leg key `ml_entry_eq_struct` on `alpaca_paper` only** (the manager's earlier ruling for `ml_entry_eq` was the same: a distinct leg key, paper only). The existing `ml_entry_eq` (fixed bracket, tau 0.20) stays untouched. Real money (`alpaca_live` / `alpaca_portfolio`) is not proposed.

### 2.1 What it takes (every item is a change; none is made here)
1. **Export the ensemble as an artifact.** `export_stage` in `scripts/research/ml_entry_equity.py` ships ONE booster; it needs an ensemble mode (`--ensemble-seeds 1,2,3,4,5`, writes the 5 booster texts in `model.json`, sha = sha256 of the concatenated texts, the same rule `confirm_stage` used for the graded sha **0afc49948a41671a…**) plus a parity fixture. Pinned fits are deterministic, so the export should reproduce the graded sha; the runs so far show dev numbers moving by ~0.015 between two runs of the same ensemble (05 vs 06), so **reproduction is a test to pass, not an assumption**. New artifact dir `ml/candidates/ml_entry_eq_v3_struct_ens5/` (do not overwrite `ml_entry_eq_v1` or `..._v2_struct`).
2. **Serve it.** `src/units/strategies/ml_entry_eq.py`: `ARTIFACT` is one hard-coded path and `load_model`/`score` use one booster. Change: take the artifact path from the leg config, load N boosters, `score()` = their mean (`provenance: predict`, a regressed net R), verify the sha at load.
3. **Carry the structure exit.** `order_package` meta must pass `structure_exit` through when the leg declares it (as `ml_entry.py` does at lines ~190-191: `**({"structure_exit": cfg["structure_exit"]} if cfg.get("structure_exit") else {})`), and `monitor` (today the 24 h time stop only) must merge the SL-only structure verdict after the time-stop check, reusing `structure_verdict` / `merge_structure_sl` from `ml_entry.py`. Order monitor / sl_mover already apply `structure_exit` verdicts generically (`order_monitor._apply_update`, `src/runtime/structure_exit_live.py`).
4. **Register the leg** per `.claude/skills/new-strategy/SKILL.md`: a variant signal builder next to `ml_entry_eq_signal_builder` (`src/runtime/strategy_signal_builders.py`, ~line 6786), intent registration (`src/runtime/intents.py`, `intent_multiplexer.py`), refresher unchanged (same pool snapshot).
5. **Config** (`config/strategies.yaml`), additive:
   ```yaml
   ml_entry_eq_struct:
     model: ml-entry-eq-struct-ens5-v1
     signal_prefixes: [ml_entry_eq_struct]
     enabled: true
     execution: live            # paper money: alpaca_paper only
     timeframe: "1h"
     decision_bar: closed
     session: auto
     max_snapshot_age_h: 4.0
     structure_exit: "pivot=5;sl_only"
     artifact: ml/candidates/ml_entry_eq_v3_struct_ens5/model.json
     symbols: [SPY, QQQ, IWM, TLT, IEF, SLV, USO, GDX, TQQQ, QLD]   # the tick-cost rollout stage of ml_entry_eq; the model's tested population is the 173-ETF pool
     atr_period: 14
     atr_stop_mult: 2.0
     tp_r: 1.5                  # 3 ATR on a 2 ATR stop, the arm that was scored
   ```
   and `ml_entry_eq_struct` added to `alpaca_paper.strategies` in `config/accounts.yaml`. tau 0.25 lives in the artifact meta (dev-selected, fixed).
6. **Tests:** booster/ensemble parity against the fixture to 1e-9 (clone `tests/test_ml_entry_eq_struct_artifact.py`), the leg tests (`tests/test_ml_entry_eq_leg.py::test_monitor_is_a_time_stop_only` changes meaning for the new leg), a structure-SL-only monitor test, and the roster/equality tests for accounts.

### 2.2 Cost stack the evidence used
Fee 0, slippage 5 bps (PROVISIONAL, one number for every ETF), regulatory 0.5 bps round trip (`S.REGULATORY_BPS`). A real per-symbol slippage read exists only after fills; the paper leg is where it would first be measured.

### 2.3 The one-trade mechanics check (Stage-1 soak: 1-2 clean trades, never a sample size)
On the first `ml_entry_eq_struct` trade, verify and record: the entry fills at the next RTH open inside the bracket; SL at 2 ATR and TP at 3 ATR are resting at the venue (no zombie OCO); the structure verdict only **tightens** the stop (never looser than the entry stop) and a `structure_sl_cross` closes at price; the journal row carries the leg key and model id; realized slippage vs the 5 bps assumption. That is a mechanics check only; edge is not read from it.

### 2.4 Revert
Remove `ml_entry_eq_struct` from `alpaca_paper.strategies` (one line) and `enabled: false` on the leg; the existing `ml_entry_eq` leg is unchanged throughout.

### 2.5 Tier and approval
Strategy logic and an account roster addition are **Tier 3** (operator). The `MD-PROMOTE-S0-S1` mandate adds a leg to the soak book on a passing Stage-0 record plus a holdout confirmation; 06 is a registered holdout pass on the full cost stack, with the caveats in section 1. Whether those caveats are enough for a paper leg is the operator's call; I do not claim that they are.

## 3. The next evidence is forward data

`RQ-20261108-98e3-13` (not before 2027-04-01) scores the SAME frozen model once at the fixed tau on bars after 2026-10-31 only, expected n ~67 (range 30-100), INDETERMINATE below 60. Its rule is fixed today: PASS needs mean >= +0.10 and mean - 1.2816 x iid se > 0 (about +0.17 at n 67). It is underpowered for a modest edge: P(PASS) ~10% if the true edge is 0, ~59% at +0.20, ~99% at +0.49. A PASS there would carry far more weight than a fourth read of the old window, which is not registered.

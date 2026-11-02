# Alpaca promotion inventory — which paper legs can go to alpaca_live (2026-11-01)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ALPACA-LIVE-ACTIVITY-ML` (row `docs/claude/work/checklist/ALPACA-LIVE-ACTIVITY-ML.json`)

Gates this adds or changes: none. (`config/mechanics_paths.yaml` is an evidence input the resolver reads; registering a path
removes a paper-soak requirement, it adds none.)

Operator, 2026-11-01 ~10:35Z, verbatim: *"The paper portfolio decision is wrong - it should mirror the live account, as per the
definition of paper mirror. And we also need to try and get more of the shadowing startegies on alpaca turned on to live money"*.

## Result: no leg clears the existing bar today — MEASURED

Population: every Alpaca-eligible leg on a roster (re-parsed `config/accounts.yaml` + `config/strategies.yaml` at main 1c1478b55):
the 15 `alpaca_paper` legs. **No leg runs `execution: shadow`** on an Alpaca symbol (all are `live` on paper rosters); three 1h
legs are unhomed by record (`spy/qqq/tlt_pullback_1h`, row ALPACA-SLICES-REHOME-1H). Each leg was run through
`scripts/ops/mandate_resolver.py --leg <leg> --from S1 --to S2 --account alpaca_live` (MD-PROMOTE-S1-S2, the existing bar, unchanged)
with this PR's mechanics registration in the tree and alpaca_live's equity reading refreshed in the working tree only (not committed:
the dispatch keeps balances out of this public repo; the committed reading is 9.2 days old and would read R-AFFORD NEEDS-DATA first).

| leg | record | n OOS | net R OOS (net of fee 0 + slip 5 bps) | folds + | window d | fidelity | paper soak | resolver S1→S2 alpaca_live (path proven) |
|---|---|---|---|---|---|---|---|---|
| tlt_pullback_1d | yes | 134 | 12.6901 | 5/8 | 6200 | faithful | passed | NEEDS-DATA [R-HOLDOUT] — tlt_pullback_1d: the Stage-0 record carries no `holdout_confirmation` -- no configuration  |
| tqqq_trend_long_1d | yes | 118 | 26.2831 | 7/8 | 6200 | faithful | passed | NEEDS-DATA [R-HOLDOUT] — tqqq_trend_long_1d: the Stage-0 record carries no `holdout_confirmation` -- no configurati |
| scha_trend_long_1d | yes | 78 | 4.6442 | 5/8 | 6200 | faithful | unknown | NEEDS-DATA [R-HOLDOUT] — scha_trend_long_1d: the Stage-0 record carries no `holdout_confirmation` -- no configurati |
| slv_trend_1h | yes | 68 | 53.1431 | 4/4 | 365 | faithful | passed | NEEDS-DATA [R-HOLDOUT] — slv_trend_1h: the Stage-0 record carries no `holdout_confirmation` -- no configuration has |
| spy_trend_long_1d | yes | 11 | 2.3816 | 3/4 | 365 | faithful | unknown | NEEDS-DATA [R-N] — n_trades_oos=11 < 30 closed |
| qqq_trend_long_1d | yes | 8 | 5.2971 | 2/4 | 365 | faithful | unknown | NEEDS-DATA [R-N] — n_trades_oos=8 < 30 closed |
| iwm_trend_long_1d | yes | 8 | 2.1071 | 2/4 | 365 | faithful | unknown | NEEDS-DATA [R-N] — n_trades_oos=8 < 30 closed |
| qld_trend_long_1d | yes | 9 | 2.9844 | 3/4 | 365 | faithful | unknown | NEEDS-DATA [R-N] — n_trades_oos=9 < 30 closed |
| gdx_pullback_1d | yes | 10 | 1.2338 | 2/4 | 365 | faithful | unknown | NEEDS-DATA [R-N] — n_trades_oos=10 < 30 closed |
| uso_trend_1h | yes | 56 | 25.8924 | 2/4 | 365 | faithful | unknown | REFUSE [R-FOLDS] — positive in 2 of 4 folds -- not a majority |
| gld_pullback_1d | yes | 8 | 7.0946 | 3/4 | 365 | approximate | — | REFUSE [R-B1-C5] — fidelity='approximate' (not 'faithful'), omitted_levers=['trail_decay_stall_bars', 'trail_ |
| ief_pullback_1d | yes | 6 | 1.0316 | 1/3 | 365 | approximate | passed | REFUSE [R-B1-C5] — fidelity='approximate' (not 'faithful'), omitted_levers=['trail_decay_stall_bars', 'trail_ |
| slv_pullback_1d | yes | 10 | 3.0026 | 2/4 | 365 | approximate | unknown | REFUSE [R-B1-C5] — fidelity='approximate' (not 'faithful'), omitted_levers=['trail_decay_stall_bars', 'trail_ |
| splg_trend_long_1d | yes | — | — | None/None | 365 | harness_failed | unknown | REFUSE [R-SOURCE-RUN-ABSENT] — source_run None is not a committed file in the repo |
| claude_desk | **no** | — | — | — | — | — | unknown | n/a (discretionary desk; no Stage-0 harness) |

"paper soak" = `soak_state.soak_states()` on alpaca_paper (`passed` = >= 1 clean graded trade). With the path registered, the soak
clause no longer blocks any leg; the first blocking clause is shown. The live-vs-backtest read (`scripts/research/live_vs_backtest.py`)
was not run: no leg reached a clause where it would decide anything.

## What this PR does

1. **Registers `alpaca_equity_bracket_v1`** in `config/mechanics_paths.yaml` for the 15 Alpaca bracket legs (`delta: none`). Proven by
   passed alpaca_paper soaks (tlt_pullback_1d, tqqq_trend_long_1d, ief_pullback_1d, slv_trend_1h) and by alpaca_live's own 3 filled
   real-money brackets (09-17 SLV, 09-18 TLT, 09-23 IAUM; all closed by the venue stop leg). That is the operator's 2026-11-01 rule
   (OPERATING-PLAN § 2): proven mechanics go Stage 0 -> real money with no paper soak. `soak_state.mechanics_proven('spy_trend_long_1d')`
   now reads `proven, path_soak`.
2. **Promotes nothing**, because nothing clears the Stage-0 bar. No bar is lowered.

## Filed (docs/claude/work/pipeline/)

- **PI-20261101-RXABACKP-0001** — Stage-0 refresh at 6,200 days for spy/qqq/iwm/qld_trend_long_1d and gdx_pullback_1d (R-N), then holdout units.
- **PI-20261101-RXABACKP-0002** — tqqq / scha / slv_trend_1h: the holdout CONFIRMED a different configuration than the leg runs; each needs a
  Tier-3 parameter proposal before a `holdout_confirmation` block can exist.
- **PI-20261101-RXABACKP-0003** — resolver defect: R-HOLDOUT requires `fees > 0`; Alpaca's venue fee is 0.0, so no Alpaca leg can ever pass it.
- **PI-20261101-RXABACKP-0004** — the bda2-01 ETF screen's INDETERMINATE confirmation has no follow-up unit.

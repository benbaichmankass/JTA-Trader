# Prop-specific ENTRY candidate: pre-registered design (lane ML-PROP-ITERATE, 2026-11-02)

> Gates this adds or changes: none. It reuses RULE-P5-GATE-BRK-PER-LEG-V3 unchanged. Status: `needs_authoring` (programme node `P5-MLPROP-ENTRY-ETHSOL`); runnable once the three diagnostics (`P5-MLDIAG-*`) are read.

## Why
ml_entry v1 fails the prop gate on all three firms (PR #22360, `docs/research/ml-entry-prop-gate-2026-11-02/RESULT.md`): ETH+SOL n=381, mean net R +0.017 (95% CI -0.106..+0.140), EV below each firm's zero-edge null. ETH and SOL are the weak symbols of the five-symbol record; ADA carries the pooled +0.027 R. The model was trained pooled over 60 perps with a flat cost label. Hypothesis: a model whose label and selection objective match the prop book (two symbols, firm venue costs, firm drawdown limits) selects different trades than the pooled model.

## Candidate arms (all dev-OOS first; each arm = one lever vs v1)
- **A re-threshold**: the frozen pooled v1 scores, tau chosen on ETH+SOL dev folds only (grid 0.10..0.40). No retraining. Reads the `by_tau_threshold` diagnostic first; if edge does not rise monotonically with score, A is dropped with that reason.
- **B prop-cost label**: pooled training population, label = net R under the firm venue cost arm (`prop_gate.SIM[acct].ven`: 8/3 bps + swap for breakout_2/tradeify_1, 6/3 + swap for velotrade_1) instead of the flat 11/3 cost, ETH+SOL rows up-weighted (weight on a dev grid).
- **C two-symbol model**: trained on ETHUSDT+SOLUSDT only, same label as B. Smallest n; expected to overfit (about 380 trades a year), kept as the extreme of the specialist-vs-generalist axis (checklist `ML-ARCH-GENERALIST-VS-SPECIALIST`).
- **Firm-DD-aware objective** (applies to tau/threshold selection in A, B, C): choose the tau that maximises dev-OOS prop_ev_sim EV per life subject to B below the firm ceiling c at the worst seed, instead of maximising mean net R. Selection runs on dev-OOS ledgers only.

## Grading (registered now, before any run)
Per arm and firm: `ml_variant_prop_gate.py` on the arm's dev-OOS ETH+SOL ledger, RULE-P5-GATE-BRK-PER-LEG-V3 exactly (n>=88, V2 plus edge CI lower bound > 0). A PASS yields a held Tier-3 roster PR (operator conditional approval 2026-11-02). Arms and tau are selected on dev only; the 2025-10..2026-09 year is already spent on v1 and is not a selection set.

## Lever vs prop-specific ML (how the diagnostics choose)
- `P5-MLDIAG-DECOMP`: if the edge concentrates in a regime, side or hour block (CI lower bound above zero in a subset of adequate n), that is a SELECTION lever on v1 (arm A / regime abstention), not a new model.
- `P5-MLDIAG-RISKCURVE`: if no risk_pct gives EV>0 at every seed with B under the ceiling, sizing is not the lever.
- `P5-MLDIAG-MINEDGE`: the gap between the minimum edge clearing V2 and +0.017 R sizes what any variant must deliver; if it exceeds what the pooled five-symbol record shows (+0.027 R), the line needs a different symbol set or timeframe, not ETH/SOL tuning.
- B/C are worth authoring when DECOMP shows the cost components (commission 0.041 R of 0.067 R total cost at breakout_2) or symbol mix, not model rank, are the main loss.

## Missing pieces (why `needs_authoring`)
1. `scripts/research/ml_decision_entry.py`: a `--symbols` filter for training and a label priced with a chosen venue cost arm.
2. A dev-fold tau/objective selector calling `prop_ev_sim` on dev-OOS ledgers.
3. A dev-OOS ledger exporter (`ledger_ethsol.jsonl`, shape of `ml_entry_ethsol.jsonl`) for every arm, which is also the gap blocking every `P5-MLV-GATE-*` node.

## Caveats
Trades are treated as independent in the edge CI (flatters edge). Variants share one spent window, so each result reports `prior_ml_records_on_this_window`.

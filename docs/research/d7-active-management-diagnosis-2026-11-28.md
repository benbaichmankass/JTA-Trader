# D7 in-trade management: why five rounds failed, and a per-recipe redesign. Diagnosis + registered design (2026-11-28)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane ML-PRIMARY (session_01AFoLuLpCY5gABbqk3EBUeV) · row `ML-AM-NEXT-LIVE`

**Gates this adds or changes:** none. This is a research design.

**The incumbent stays.** The live D7 incumbent is Labrador-1b (TP extend-only, on ml_entry; `docs/plans/ml-week-plan-2026-11-19.md` § D7). It stays until a tested replacement beats it (OPERATING-PLAN § 2, "Each decision keeps its tested incumbent until a better one passes", operator 2026-11-28).

**Scope.** D7 means actions that keep the position open: move the SL, move the TP, or take a partial. D8 means closing the whole position (`docs/plans/ML-ROADMAP-MECE-2026-11.md` § "D7 In-trade management and D8 Exit now"). Manager 2026-11-28b at 09:40Z moved D7 to ML-PRIMARY "for a new D7 diagnosis + design (operator 11-28: redesign freely)".

## 1. The graded record (every number read from committed results, 2026-11-28)

| Unit | What it tested | Population | Result |
|---|---|---|---|
| tm-action-value iter 1–5, `c21d-04` | one-step action values on the action grid | money legs | all FAIL S-OFFLINE (week plan § D7) |
| `RQ-20261115-7e18-01` Stage B | act on per-action value (close, partial_close_50) | 2,627 money-leg trades | FAIL. +0.0033 R/trade vs HOLD, CI [−0.0070, +0.0131]. It acts on 5.4% of trades and holds 3/6 folds; the bar is +0.03. |
| `RQ-20261124-b5a1-01..05` (AM v2 Stage B) | head-driven target / tighten / loosen / bank / combined | 377,658 replayed trades across all crypto legs (dev 312,008, holdout 65,650) | all FAIL. Tighten: R2/R3/R4 fail, dd cut 0.04%. Combined: cuts CVaR 15% and holds 6/6 folds, but net R falls from −8,526 to −12,721 and it beats 0/100 controls. |
| `RQ-20261125-c7e3-09` | model-free fixed-age tighten vs HOLD + causal random | the same corpus | FAIL on dev and on holdout. It beats 40/100 causal controls on holdout. |

## 2. Diagnosis: three faults in how the experiment was set up, not in the action classes

**(a) The corpus has no edge, so "act earlier" wins by construction.**
- The AM v2 dev book is net **−8,526 R over 312,008 trades (−0.027 R/trade)**.
- The 100 matched random re-timings average **−4,955 R**, so random intervention beats HOLD by about +0.011 R/trade.
- On a negative-expectancy book, anything that shortens exposure looks good. A head trained there learns exposure reduction, not management skill, which is why no head beat its matched random control.
- The corpus is dominated by unrostered and generated configurations: the run-w corpus spans every crypto leg, and 169/175 generated sweeps FAIL their own tests.
- The edge D7 is meant to manage is not in that corpus.

**(b) The money-leg corpus has too little power.**
- 7e18-01 had 2,627 trades and acted on 5.4% of them, about 140 decisions.
- At the measured per-trade dR sd (about 1 R), the +0.03 bar is far above what 140 acted trades can resolve.

**(c) Pooling recipe families mixes effects of opposite sign.**
- c7e3-09's split by strategy (an ESTIMATE from the strategy cuts) shows tightening HURTS trend/pullback legs: trend_donchian −0.002 / −0.006 R/trade.
- The same split shows it HELPS mean-reversion fade_breakout: +0.002 R/trade, with a smaller drawdown, in both runs.
- A pooled policy averages these opposite effects toward zero.

**The contrast that names the fix: D8.**
- The D8 exit-now head trained on ONE rostered recipe (trend_donchian_eth_4h) replayed as twins on 60 perps: 11,511 trades, 9,590 OOS.
- It beat the causal matched random exit by **+0.089 R/trade over the control p95** (head +0.0524, p95 −0.0365; RQ-20261125-cf48-04).
- On a DISJOINT 60-perp universe it again beat it by +0.056 (head +0.0422, p95 −0.0142; RQ-20261126-1e75-01). That run missed only the separate +0.05 gain bar.
- There the random controls are NEGATIVE, because the recipe has positive skew and early exits hurt it. The head still adds value, so that is skill, not exposure reduction.
- One edge recipe at power, graded against a causal control, is the setup in which in-trade ML has shown skill.

## 3. Redesign: D7 v3, one recipe at a time on twin corpora

1. **Corpus.**
   - One rostered money-leg recipe per unit, replayed as twins on the bp2 60-perp universe. This is the cf48-04 method (`scripts/research/exit_head_kaggle_bakeoff.py --universe bp2 --leg-template <leg> --pool-folds`).
   - Order: trend_donchian_eth_4h first, because the harness exists; ada/xrp_pullback_2h second, which needs a leg-template build (B3).
2. **Actions.** These are D7 classes, which keep the position open, and are fired by the existing exit-now head's score so no new model is needed for round 1:
   - **A1 partial_50:** take half off when the head fires; the rest rides the declared exit.
   - **A2 be_tighten:** move the SL to breakeven when the head fires.
   - These are the two "keep it open" versions of the one in-trade signal that showed skill.
3. **Grading** (rule registered before any run, one unit, k = 2 arms, Šidák):
   - Mean net R per OOS trade vs HOLD (the declared exit) ≥ +0.02 R.
   - Beats the causal matched random version of the same action at p95, with 500 draws.
   - n_oos ≥ 3,000, and positive in ≥ 4 of 5 pooled folds.
   - **Net of cost per arm (B2).** A partial or SL move adds an exit side on the acted fraction, and the replay must charge it.
   - Dev = bp2 twins. The confirming read = the bp2 ranks 121–180 twins, a THIRD disjoint universe, because bp2_next60 was already read by 1e75-01. It is one read under the same rule.
4. **Why not fitted-Q now.** The week plan's next D7 task was a fitted-Q baseline on the action grid. It would still train on the edge-less pooled corpus (fault a) or the underpowered money-leg corpus (fault b). It comes after D7 v3 shows a per-recipe action that beats its causal control, and it would run on that recipe's twin corpus.
5. **Family split.** Tighten-type actions are tested only on trend and pullback recipes after A1/A2. The fade_breakout re-scope (c7e5-01, AM Q10) remains the mean-reversion line. The two are never pooled.

## 4. Builds this needs (Tier 1, research harness only; owner set by the manager)

- **B1. Replay modes** in `exit_head_label_bakeoff` for head-fired trades: `partial50` (half off at the fire bar's close, the rest on the declared exit) and `be_tighten` (the SL moves to entry at the fire bar). Each needs a matching causal random mode, the same age-draw design as `_causal_random_fold`. Est 0.5–1 day.
- **B2. Net of cost per arm.** Persist each trade's risk in bps (entry minus stop) in the rows. Charge fee + slippage on each extra exit side and funding on the actual hold, on the venue cost policy (`scripts/ml/exit_head_replay._apply_venue_cost_policy`). This also closes the D8 gap: cf48-04 / 1e75-01 were graded on gross R.
- **B3. Pullback leg template** (the pullback recipe's entry and exit replayed as twins), for the second money-leg family.
- **B4. A bp2 ranks 121–180 universe option** (`--universe bp2_third60`), disjoint from bp2 and bp2_next60.

## 5. What this does not do

It changes no served model, config or order path. It adds no gate. It promotes nothing: a PASS on the confirming read is a data-backed Tier-3 packet against Labrador-1b, applied by the manager or a mandate, never by a lane. Each unit is authored and registered when its build lands.

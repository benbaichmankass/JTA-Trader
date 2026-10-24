# Exit levers that failed their first test (2026-10-22 batch): diagnosis and variants (2026-10-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `EXIT-FAILED-LEVERS-DIAG` (Tier 1; dispatched by Manager Session 2026-10-24; operator order "3 then 2 then 1", this row second; rule 2026-10-22: a first-test fail is diagnosed, never killed). **Nothing here retires a lever.** Every claim is marked **MEASURED** (read from a committed result, trade file or the code) or **INFERRED**.

## The question

For each of the 21 exit levers that failed their first test, why did it fail, and what variant is worth testing next? Variants are the 22 queued units `RQ-20261024-f08c-01 … -22` (each dry-run `would_dispatch`).

## Method, and the one thing every lever shares

Populations: each ablation lever was read from `comms/research/<id>/*/verdict.json` and the arm trade files under `arms/` (window 2020-07-01 .. 2026-10-15, net of the harness cost stack: fee 7.5 bps round trip, slippage 3.0, funding 1.0 per 8h window; MEASURED in each verdict's `cost_stack`). Baseline trade counts: ada_pullback_2h 402, xrp_pullback_2h 394, trend_donchian_eth_prop 1085, trend_donchian_sol_prop 400, eth_4h 275, sol_4h 267, xrp_4h 68.

1. **The registered per-trade bar is far below what a single-leg test can resolve (MEASURED arithmetic).** The replace rule asks for `0.02 R x n`. An unpaired one-sample test at n=402 resolves about 0.14 sd (2.8/sqrt(n)), i.e. roughly 0.28 R/trade. Arms share most trades, so the paired difference is much tighter (paired sd per entry 0.06-0.50 R), but the effects the near-misses show are 0.002-0.013 R/entry with paired t 0.1-1.7. So most fails are **not** "a real effect was missed" and not "a real harm was found": at one leg's n a lever worth less than about 0.05 R/trade cannot be told apart from noise by any rule. The fold-majority gate (5 of 6) is what carries the verdict.
2. **Harness fill behaviour (code read, `scripts/backtest_pullback.py` lines 735-925; MEASURED by reading, direction INFERRED).** The stop test uses the trail as it stood at the START of the bar, and the ratchet advances after the test, so the bar's own high does not ratchet the stop it is tested against (no intrabar-ratchet bug of the live kind). But a stop or trail the bar trades through fills AT the stop price, not at a worse gap open, and lever exits (giveback, stale, flip) fill at the bar close. This is the behaviour pipeline item `PI-20261024-ZUPNKHZR-0001` flags. **That item is not on `main` at `2d3889df`** (searched `docs/claude/work` and `origin/main`), so this section rests on the code, not on the item's text. Direction: the artifact is worth more to an arm the more of its exits are stop/trail fills, so it flatters tight-trail arms (T15, F60, LS, LR, S40, M2) relative to the baseline. **Every one of those arms failed anyway, so the fails are robust to it (INFERRED).** It does not flatter the bank arms (the bank fills at its rung, a limit). It does mean a PASS from any trail arm must be re-run gap-adjusted before a Tier-3 note; each new unit says so.
3. **The bank/giveback fails share a structural cause (MEASURED).** From the A-arm trade files, the pool a bank or giveback could rescue is small: the share of stop exits that ever reached +1 R is 21% (ada), 9% (xrp), 0% (eth_prop, sol_prop: the profit is in the trail); the share reaching +1.5 R is 9.5% (ada) and 0% (xrp). The cost of such a lever falls on the target hits (127 of 402 on ada, 154 of 394 on xrp).

## The table

Classes: **P** wrong parameter region · **L** wrong legs / regime / objective · **U** underpowered (n or bar vs. effect) · **H** harness or cost artifact · **N** genuinely no effect at this design. "Fold" = folds at or above the incumbent. Verdict for every row: `fail`, graded `deterministic harness, all measured`.

| Lever (parent unit) | Leg, n | Class | Evidence | Variants |
|---|---|---|---|---|
| **eba2-02** path metrics at bar 12 predict giveback | eth_prop + sol_prop, 796 still open | **P** (k) + **U** (bar > baseline R2) | MEASURED: pooled OOS R2 0.0048 -> 0.0062 (+0.0014, 4/6 folds), log-loss +0.0016 (2/6); eth_prop alone R2 +0.0147 (4/6). 523 of 1085 eth_prop trades had exited by bar 12. The passing units (007, eba2-01, eba2-04) read at bar 6. The 0.02 R2 bar is 4x the whole baseline R2. | f08c-21 (k=6), f08c-22 (k=24) |
| **eba2-03** R-armed tight trail (arm 1.5/2.0/3.0 R, tight 2.5) | ada_pullback_2h, 402 | **P** | MEASURED dose-response: dR -23.37 / -20.05 / -1.81; take_profit exits 127 -> 101 / 105 / 119. Converges to zero as the arm approaches the 4R target. | f08c-01 (arm 2.5/3.0, tight 3.5/4.0) |
| **eba2-05** giveback 50-70% of peak, min peak 2.0 R | ada_pullback_2h, 402 | **P** | MEASURED: dR -11.1 / -13.7 / -16.2; take_profit 127 -> 106 / 99 / 85, 64-92 giveback stops. Only 47 of 402 trades (12%) reach 3.0 R. | f08c-02 (min peak 2.5/3.0) |
| **eba2-06** same lever | xrp_pullback_2h, 394 | **N** (leading) | MEASURED: dR -5.79 / -3.13 / -4.04 (bar 7.88). 19 of 203 stop exits ever reached 1 R, none 1.5 R: ~19 rescuable trades against 154 target hits. INFERRED: no effect at a 3R-capped design. | f08c-03 (loose giveback, tests this) |
| **eba2-09** swing/FVG level trail, wider mult | xrp_pullback_2h, 394 | **P** | MEASURED: S40 / S45 / F40 dR -15.21 / -8.64 / -6.64; maxDD 33.9 / 25.5 / 21.7 vs 16.2; trail_stop 30 -> 89 / 74. Gating at +1.5/+2.0 R (eba2-11) cut the loss to -3.7/-4.2. The level latches at the first touch of a k=3 pivot, early in the trade. | f08c-04 (pivot_k 5/8, gated) |
| **eba2-10** same, wider mult / FVG 120 | eth_prop, 1085 | **L** (objective) + **U** | MEASURED: S25 / S30 / F30 dR -12.47 / -2.79 / -2.50, maxDD 16.9 / 18.5 / 20.8 vs 22.0 (a drawdown shift). Paired S30: 169 of 1084 entries differ, mean dR/entry -0.0026, t -0.39. The R-gain bar (21.7 R) cannot score a prop leg's drawdown lever. | f08c-05 (DD-objective) |
| **eba2-12** far-rung bank 25%@3R, 33%@2R, +R-armed trail | ada_pullback_2h, 402 | **N** at this design | MEASURED: dR -3.48 / -21.28 / -32.88; n unchanged (402), same 127 target hits, so the loss is the halved target payoff. 21% of stops reached 1 R. INFERRED: banking needs an uncapped tail. | f08c-07 (bank + target 6R, with a no-bank control) |
| **eba2-13** same | xrp_pullback_2h, 394 | **U** (bar > effect) | MEASURED: P25 (25%@2.5R) dR +2.28, 5/6 folds, maxDD 16.27 vs 16.17; P33 +1.88, 3 folds. Bar 7.88 missed. Paired P25: 61 entries differ, +0.0058 R/entry, t 1.37. Same-sign small positives on capped legs (xrp_4h +0.32, sol_4h +0.87, sol_prop +0.29, a1f3-01/03/04); negative on ada and eth. | f08c-09 (rung/size scan as a LEAD), f08c-08 (shared with fd06-02) |
| **eba2-14** same | eth_prop, 1085 | **N** | MEASURED: P25 / P33 / PT dR -3.07 / -14.24 / -31.32, folds 1/0/1, maxDD 23.4 / 23.2 vs 22.0 (no drawdown cut). Of 70 trades reaching 3 R none finished more than 1 R below it (mean net +2.90 R); no stop exit reached 1 R. | f08c-10 (rung 4-5 R, tests the monotone trend) |
| **eba2-15** ADX-loss tight trail (ADX<20 etc.) | eth_4h, 275 | **P** (inert trigger) | MEASURED: M3 dR +1.56, 6/6 folds, but it changed **4 of 275 trades** (t 1.68). M4 / M5 dR -2.34 / +0.50. Sibling sol_4h (8961-01) M3 / M5 +3.24 / +3.53, 5 folds, t about 0.5. All below the 5.5 R bar. | f08c-13, f08c-14 (fresh legs ada_4h, avax_4h; bar 0.01 R/trade) |
| **b7e1-01** per-bar path state beyond stop room, w=6, X=1.5 | 6 mixed legs, 14327 states / 639 trades | **L** (wrong legs) | MEASURED: pooled ll_gain +0.0090 (5/6 folds, AUC 0.805 -> 0.813) vs the 0.01 bar. Per leg: **sol_4h PASSED** (+0.0268, 5/6 folds, AUC 0.664 -> 0.699); eth_pullback -0.0026, avax_pullback -0.0033; 3 legs indeterminate (54-90 reaching trades). | f08c-18 (Donchian-4h siblings, ~288 reaching trades) |
| **b7e1-02** same at w=12 | xrp/ada pullback + eth_4h, 10554 states / 373 trades | **P** (w) + overfit at small n | MEASURED: ll_gain -0.0009 (2/6), AUC 0.666 -> 0.653 (the full model is worse out of sample). xrp -0.0204, ada +0.0060. 137 / 142 reaching trades for 10 extra features. | f08c-19 (w=6, X=1.0) |
| **b7e1-03** same, prop legs, w=12, X=1.0 | eth_prop + sol_prop, 5210 states / 442 trades | **P** + overfit | MEASURED: ll_gain -0.0145 (2/6), AUC 0.844 -> 0.835; base rate 6.2%. stop_room_r alone has AUC 0.843, er_w alone 0.645 (6/6 folds same side) but adds nothing once stop room is in. | f08c-20 (w=6, X=1.5) |
| **fd06-01** bank 50% at +1.0/+1.5 R (± BE floor) | ada_pullback_2h, 402 | **N** at this design | MEASURED: dR -56.97 / -42.80 / -68.30. The B1E (BE floor) arm moved trail_stop exits 21 -> 122: the floor also kills runners. | f08c-07 |
| **fd06-02** same | xrp_pullback_2h, 394 | **N** at this design | MEASURED: dR -18.81 / -6.93 / -28.38, monotone toward zero as the rung moves out; 0 of 203 stops reached 1.5 R. Registered `expected_n` 90 was a stand-in; measured n is 394, so this was not underpowered. | f08c-08 (bank + target 5R, with a no-bank control), f08c-09 |
| **fd06-03** same | xrp_4h, **68** | **U** | MEASURED: dR -4.84 / -2.63 / -4.92 in 4 folds of about 17 trades; bar 1.36 R. The B1E arm mixes a bank with a BE floor (confound; the BE floor alone is already queued as `a1f3-06`). | f08c-16, f08c-17 (sibling legs with n 259-263); `a1f3-06` (existing) |
| **511e-01** ADX<25, tight 2.5 | sol_4h 267 (eth_4h row overwritten, `cmd-0.log` only) | **P** (too tight) | MEASURED: sol_4h M2 dR -7.78, folds 1/4, trail_stop 14 -> 55, maxDD 16.7 vs 12.8. eth_4h: harness printed `incumbent_stands` (no n or delta recoverable). The middle cell (ADX<25, tight 3.5-4.0) was never run. | f08c-11 (sol_4h), f08c-12 (eth_4h) |
| **003** level trail 1.75 x ATR | sol_prop, 400 | **L** (objective) + **P** | MEASURED: LS / LF / LR dR -8.62 / -3.65 / -28.16; maxDD 9.3 / 10.3 / 18.4 vs 12.1 (LS -23%); folds 3/3/1. | f08c-06 |
| **004** level trail 3.0 x ATR | xrp_pullback_2h, 394 | **P** | MEASURED: LS / LF / LR dR -13.78 / -5.73 / -28.72, maxDD 23.7 / 19.2 / 20.6 vs 16.2. | f08c-04 |
| **005** level trail 1.75 x ATR | eth_prop, 1085 | **L** (objective) | MEASURED: LS / LF dR +2.20 / +0.67, maxDD 16.5 / 16.0 vs 22.0 (-25% / -27%), folds 2/6; LR -61.98. Paired LS t 0.13: no R effect, a drawdown shift. | f08c-05 |
| **006** level trail 2.5 x ATR | xrp_4h, **68** | **U** + **H** (inert arm) | MEASURED: LF byte-identical to A (`lever_fired: False`), so one of three arms never ran; LS dR -0.49; LR -4.02. | f08c-15 (arms that fire), f08c-16, f08c-17 |

## Cross-cutting findings

* **Round-number levels (LR) are the worst arm in every leg tested** (MEASURED: eth_prop -61.98, sol_prop -28.16, xrp -28.72, ada -23.18, eth_4h -44.89, xrp_4h -4.02). A round number is touched constantly, so the latch fires almost immediately. The new variants drop LR; this is an arm-level lesson, not a retirement of the level-trail family.
* **Prop legs need a drawdown objective.** The R-gain bar is the wrong instrument for a lever that moves drawdown and not R (eth_prop and sol_prop LS cut maxDD about 25% at -8.6 to +2.2 R). `f08c-05/-06` use the `sweep` grade (dR within a stated give-up, dDD <= 0, >= 3 of 6 folds). A lead there is evidence only; the firm DD simulation still follows.
* **The ADX lever is inert or too tight, never in the middle.** ADX<20 touched 4 of 275 open trades; ADX<25 with 2.5 tripled the trail exits. The 0.01 R/trade bar on the new ADX units is registered before any of the four legs is read and is half the parents', because the measured effects (0.006-0.013 R/entry) could not pass 0.02.
* **Path-state value is leg-family specific.** The only passing path-state leg is a 4h Donchian trend leg. Pooling it with pullback legs sank the result.
* **Near misses worth a lead, not a promotion:** xrp far-rung bank (P25), ADX M3 on 4h legs, sol_4h FVG-120 (`a1f3-05` F30: dR +5.38 vs bar 5.34 but folds 3 of 6 needed 4).

## Variant index

| Unit | Leg(s) | Serves | Grade / bar |
|---|---|---|---|
| f08c-01 | ada_pullback_2h | eba2-03 | replace 0.02 R/trade, 5/6 |
| f08c-02 | ada_pullback_2h | eba2-05 | replace 0.02, 5/6 |
| f08c-03 | xrp_pullback_2h | eba2-06 | replace 0.02, 5/6 |
| f08c-04 | xrp_pullback_2h | eba2-09, 004 | replace 0.02, 5/6 |
| f08c-05 | trend_donchian_eth_prop | eba2-10, 005 | sweep dR >= -3.0, dDD <= 0, 3/6 |
| f08c-06 | trend_donchian_sol_prop | 003 | sweep dR >= -2.0, dDD <= 0, 3/6 |
| f08c-07 | ada_pullback_2h | eba2-12, fd06-01 | replace 0.02, 5/6 |
| f08c-08 | xrp_pullback_2h | fd06-02 (and eba2-13) | replace 0.02, 5/6 |
| f08c-09 | xrp_pullback_2h | eba2-13 | sweep dR >= 2.0, dDD <= 0, 4/6 (LEAD) |
| f08c-10 | trend_donchian_eth_prop | eba2-14 | replace 0.02, 5/6 |
| f08c-11 / -12 | sol_4h / eth_4h | 511e-01, eba2-15 | replace 0.01, 5/6 |
| f08c-13 / -14 | ada_4h / avax_4h | eba2-15 | replace 0.01, 5/6 |
| f08c-15 | trend_donchian_xrp_4h | 006 | replace 0.02, 3/4 |
| f08c-16 / -17 | ada_4h / avax_4h | 006, fd06-03 | replace 0.02, 5/6 |
| f08c-18 | Donchian 4h (eth, xrp, ada, avax) | b7e1-01 | path-state, ll_gain >= 0.01, 4/6 |
| f08c-19 | xrp / ada pullback | b7e1-02 | same bar |
| f08c-20 | eth_prop + sol_prop | b7e1-03 | same bar |
| f08c-21 / -22 | eth_prop + sol_prop | eba2-02 | R2 >= 0.02 or ll >= 0.01, 4/6 |

Every unit: `decision_rule.registered_before_run: true`, the full cost stack (the harness's venue-aware stack), a multi-fold design (4 or 6 calendar folds), roadmap `L-ATM`, theme `live_strategy`, power with the MEASURED n, no config change, and no overlap with a queued unit (queue grepped for the same leg and lever family; `a1f3-06` and `a1f3-09` were left as they are).

## What this does not establish

* None of the 22 variants has run. A variant's result is a new measurement, not a confirmation of a diagnosis here.
* Class assignments marked INFERRED are readings of the numbers above, not tests; the variants are the tests.
* The `PI-20261024-ZUPNKHZR-0001` text itself was not available; the harness behaviour it describes was checked in the code.

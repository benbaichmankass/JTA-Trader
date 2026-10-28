# LTR-TIGHTEN-OPTIMIZE: which stop-tightens lose, and does any tighten rule beat hold-to-bracket out of sample?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `LTR-TIGHTEN-OPTIMIZE` (Tier 1 research; the recommendation is a Tier-3 proposal). Dispatched by Manager
session_01AFoLuJi1vLTnYv9LbP6539. Checklist row `docs/claude/work/checklist/LTR-TIGHTEN-OPTIMIZE.json`.
Script `scripts/research/ltr_tighten_optimize.py`. Evidence `comms/research/ltr_tighten_optimize/`.

**Operator, 2026-10-28 ~19:45Z (relayed by the manager):** on stop-tightening, *"Investigate further and optimize
before turning off"*. Live LTR auto-applies stay UNCHANGED. This lane changes no config or live-review policy.

**Order of work (so the reader can check what was known when).** § 1 (Q1 slices) was computed first. § 2 (the Q2
registration) was committed and pushed **before any rule in the § 2 grid was replayed on any split.** Results are
appended in § 3 onwards, and labelled.

## 0. The data, and what it can and cannot answer

- **Corpus:** the DESK-LIFECYCLE-S0 full run (PR #20967, branch `claude/desk-lifecycle-s0`, head `da6f32d4`),
  `comms/research/desk_lifecycle/full-c4e/`. 520 registered pairs = 1,040 market entries (520 Claude desk entries + 520
  matched random partners) on six Binance USD-M perps (ADA, AVAX, BTC, ETH, SOL, XRP), 1h bars, each with its own
  bracket and a 48-bar time stop (contract C48). 938 trades were walked by Claude under check-in policy C4E (every 4
  bars plus event triggers). Entry bars 2025-W44 .. 2026-W36.
- **Cost:** the full stack via `src/runtime/execution_costs.py` as the driver applies it (fee 11.0 bps, slippage
  3.0 bps round trip, funding 1.0 bps per 8 h). A tighten that fills at its moved stop pays no extra slippage in the
  engine; every table below also reports a **+0.05 R per moved-stop exit** sensitivity.
- **Value of one tighten** = the managed trade's net R minus the same trade with that one answer replaced by `hold`
  (the driver's ablation). The re-priced value reproduces the committed `labels.jsonl` for **981 of 981** tightens
  exactly (asserted by the script).
- **What it cannot answer:**
  - *Leg family and timeframe.* The corpus is one family: desk/random entries, crypto perps, 1h. It has no Stage-0
    strategy legs and no other timeframes. Slicing by symbol and entry source is the nearest proxy. The strategy-leg
    version is filed as a queue unit (§ 6).
  - *Triggers `giveback` and `adverse`.* The C4E tags are `clock`, `mom_with` / `mom_against` (a 3-bar momentum
    flip), `break_*` (a 12-bar channel break), `r±X` (R milestones) and `atr_*` (a volatility change). There is no
    giveback tag, so giveback is sliced as a state (MFE − open R). The only adverse tag is `r-0.5`, and Claude made
    fewer than 10 tightens on it.

## 1. Q1: which tightens lose? (MEASURED)

**Population:** 981 Claude `tighten_sl` check-ins on the walked trades (517 on Claude entries, 464 on random entries),
32 ISO weeks. **CI:** weekly-cluster bootstrap, 95 %, 4,000 draws. File: `comms/research/ltr_tighten_optimize/slices.json`
(every cell, incl. the stop-slip sensitivity); per-tighten rows: `tighten_rows.jsonl`.

**All tightens: −0.097 R [−0.140, −0.047]** (−0.108 with the stop-slip sensitivity). 64 % change nothing (value 0),
22 % help (mean +0.58 R when they do) and 13 % hurt (mean −1.70 R when they do): a tighten that bites usually
stops out a trade that would have recovered to its TP.

| slice | cell | n | mean dR | 95 % CI |
|---|---|---|---|---|
| open R at action | < 0 | 20 | −0.203 | [−0.796, +0.128] |
| | 0 .. 0.5 | 135 | **−0.194** | [−0.333, −0.057] |
| | 0.5 .. 1 | 419 | **−0.129** | [−0.218, −0.039] |
| | 1 .. 2 | 379 | −0.032 | [−0.115, +0.050] |
| | ≥ 2 | 28 | +0.047 | [−0.125, +0.275] |
| new stop level | below breakeven | 331 | **−0.177** | [−0.279, −0.073] |
| | at breakeven | 142 | −0.083 | [−0.209, +0.045] |
| | BE .. +0.5 R | 237 | −0.079 | [−0.165, +0.013] |
| | ≥ +0.5 R | 271 | −0.021 | [−0.106, +0.066] |
| new-stop distance (ATR) | < 1 | 400 | **−0.089** | [−0.147, −0.025] |
| | 1 .. 2 | 529 | **−0.091** | [−0.173, −0.010] |
| | 2 .. 3 | 49 | **−0.232** | [−0.532, −0.030] |
| new-stop distance (R) | < 0.25 | 13 | +0.048 | [−0.119, +0.196] |
| | 0.25 .. 0.5 | 154 | **−0.133** | [−0.253, −0.028] |
| | 0.5 .. 1 | 674 | **−0.097** | [−0.154, −0.035] |
| | ≥ 1 | 140 | −0.069 | [−0.205, +0.072] |
| time in trade (bars) | 1–3 | 248 | **−0.098** | [−0.195, −0.012] |
| | 4–11 | 553 | **−0.111** | [−0.165, −0.051] |
| | 12–23 | 150 | −0.041 | [−0.125, +0.052] |
| | 24–47 | 30 | −0.101 | [−0.290, +0.039] |
| first tighten on the trade | yes | 503 | **−0.143** | [−0.225, −0.060] |
| | no (a re-tighten) | 478 | −0.048 | [−0.113, +0.019] |
| vol (30-day ATR% tercile) | low | 380 | **−0.128** | [−0.211, −0.051] |
| | mid | 339 | −0.040 | [−0.143, +0.060] |
| | high | 262 | **−0.125** | [−0.201, −0.051] |
| trend (48-bar move vs side) | with | 335 | **−0.145** | [−0.241, −0.059] |
| | flat | 535 | −0.064 | [−0.120, +0.005] |
| | against | 111 | −0.108 | [−0.223, +0.036] |
| trigger | time (clock) | 328 | **−0.083** | [−0.163, −0.004] |
| | first +0.5 R | 359 | **−0.123** | [−0.213, −0.036] |
| | first +1.0 R | 256 | −0.049 | [−0.145, +0.039] |
| | first +1.5 / +2.0 R | 92 / 24 | −0.027 / +0.055 | spans 0 |
| | momentum flip with / against | 254 / 61 | −0.074 / −0.103 | spans 0 |
| | structure break with the trade | 334 | −0.078 | [−0.160, +0.013] |
| | vol change | 60 | −0.085 | [−0.252, +0.066] |
| entry source | Claude / random | 517 / 464 | **−0.106 / −0.087** | both exclude 0 |
| symbol | ADA / AVAX / BTC / SOL | 497 / 241 / 38 / 122 | all negative | all exclude 0 |
| | XRP | 78 | +0.031 | [−0.111, +0.241] |

(Bold = the CI excludes 0. ETH had 5 tightens, below the n ≥ 10 reporting floor.)

**Read.**
1. **No tighten cell is significantly positive.** Of the 79 cells with n ≥ 10 in `slices.json` (single slices and
   three crosses), **0** have a CI above 0 and **29** have a CI below 0. About 2 of 79 would sit above 0 by chance alone.
2. **The losing tightens are the EARLY ones:** open R below +1 R, a new stop still below breakeven, the first
   tighten on a trade, the +0.5 R milestone, and the first 11 bars. These are the cells whose CIs exclude 0.
3. **Late tightens are roughly free:** open ≥ +1 R, a new stop ≥ +0.5 R, or a re-tighten. These sit at −0.05 to
   +0.05 R and every CI spans 0. "Free" is the most the data allows. No cell shows a tighten earning R.
4. **Distance does not rescue it.** Tightens 2–3 ATR from price lose as much as tight ones. What matters is how
   early (open R and stop level), not how far.
5. **With-trend tightens lose the most** (−0.145). That fits the practice principle (T2) that stops hurt in drift
   and help only in reversal.

## 2. Q2 REGISTRATION: is there a tighten rule that beats hold-to-bracket out of sample? (registered before any run)

**2.1 Population and splits.**
- **TRAIN** = every filled corpus entry (both sources) whose entry bar is before **2026-03-01 00:00Z**.
- **TEST** = every filled corpus entry with an entry bar on or after 2026-03-01, through the corpus end (2026-W36).
- **FRESH** = new random market entries in **2026-09-07 .. 2026-10-24** (after the corpus; 48 bars to close before
  the last candle on 2026-10-27). Up to 70 per symbol, at seeded cutoffs (seed 20261028) at least 4 bars apart. Each
  draws its geometry (side, stop in ATR, TP in R) from the corpus's own random partners.
- Rules need no judging, so every filled entry counts, judged or not.
- **Prior exposure, stated:**
  - Before this registration, the lane had seen the whole-corpus (train + test) results of the S0 driver's fixed
    rule arms in `score.json`. Every one was ≤ 0 or indistinguishable from 0 vs HOLD.
  - The lane had also seen the § 1 slices, which use Claude's tightens over the same weeks.
  - TEST is therefore *time-held-out* but not pristine. **FRESH is pristine:** no session has replayed any trade
    after 2026-W36 on this corpus. That is why FRESH is a co-requirement of PASS.

**2.2 Engine.** `desk_lifecycle_driver.run` with check-in policy **C1** (every bar close). A rule's action takes
effect from the next bar (the engine's rule). Costs and the bracket are as § 0. Every rule is tighten-only or
close-only: it never widens a stop, moves a TP or changes size. **dR** = the rule's net R minus HOLD's net R on the
same entry.

**2.3 The grid (61 rules, fixed here).**

| family | rule | parameters |
|---|---|---|
| hold | the bracket untouched | — |
| breakeven-after-X | once close ≥ X R, stop → +off R | X ∈ {0.5, 1, 1.5, 2}, off ∈ {0, 0.1} |
| ATR-trail-after-X | once MFE ≥ X R, stop → MFE − k·ATR(14) | X ∈ {0, 0.5, 1, 1.5, 2}, k ∈ {1.5, 2, 3, 4, 5} |
| structure-anchored | once MFE ≥ X R, stop → the n-bar low (long) / high (short) | X ∈ {0.5, 1, 1.5}, n ∈ {6, 12, 24} |
| MFE-giveback | once MFE ≥ X R, stop → (1 − f)·MFE | X ∈ {1, 1.5, 2}, f ∈ {0.3, 0.5, 0.7} |
| loss-cut-only | close at a close ≤ Y R after ≥ T bars held | Y ∈ {−0.5, −0.6, −0.75}, T ∈ {1, 4, 8} |

A tighten is valid only when it raises the stop and leaves it ≥ 0.10 R from the close (`MIN_GAP_R`).

**2.4 Selection and the decision rule.**
- **Selection (TRAIN only):** the ONE rule with the highest pooled mean dR. Ties go to the shorter name. HOLD is in
  the grid. If HOLD is selected, the primary verdict is **`no_rule`**: no tighten rule beats hold in-sample.
- **Graded (TEST and FRESH), a family of two, Bonferroni:**
  1. the TRAIN-selected rule;
  2. the pre-specified loss-cut `losscut(Y=-0.5, T=1)`. This is the one positive pocket S0's pilot and full run agree
     on in sign. It is graded whatever TRAIN selects.
- **Verdict per graded rule:**
  - **PASS** = TEST mean dR has a weekly-cluster **97.5 %** CI lower bound > 0, **and** FRESH mean dR > 0.
  - **FAIL** = the TEST 97.5 % CI upper bound < 0.
  - **INDETERMINATE** otherwise.
- **Reported, not graded:** the stop-slip sensitivity, each entry source separately, max drawdown, and every grid rule
  on TEST and FRESH (`*-allgrid.json`). These are for reading, not for choosing.
- **The script enforces the order.** `rules --split test|fresh` refuses to run without `--registration` (this file),
  and records its sha256 in the output.

## 3. Q2 results

*(appended after the run)*

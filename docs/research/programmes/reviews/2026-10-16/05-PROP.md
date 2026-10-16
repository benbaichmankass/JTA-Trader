## Programme 05 PROP: audit, 2026-10-16

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../../../DOCUMENT-INDEX.md`](../../../../DOCUMENT-INDEX.md) · manager programme audit 2026-10-16 (input to the backlog lanes and the 2026-10-20 programme review) · **Tier-1: nothing here changes a config, a roster or an order path.**

**1. Intent**
- Every prop decision (which legs, what size, what buffer) is judged on **E[net $ banked per account life]** from `prop_ev_sim`/`prop_ev_grid`, net of the full cost stack. How far an account sits from a drawdown line is not the measure (B6 frame, 05-PROP §1).
- Q1: what each live account is worth as configured. Q2: sizing challengers. Q3: per-leg $ risk on breakout_2. Q4: what the daily-DD switch costs. Q5: breadth (candidate pool, then head-to-head). Q6: live vs sim fidelity. Q7: TP amend on prop paths.
- Money served: the 3 live evaluations in `config/accounts.yaml`. Each runs `trend_donchian_eth_prop` + `trend_donchian_sol_prop` with `risk_pct` 0.005 and the DD switch armed: velotrade_1 (velotrade_classic_1step), tradeify_1 (tradeify_247_1step), breakout_2 (breakout_turbo_1step). breakout_1 is `dry_run` with an empty roster. Milestone L-PROP.

**2. What has been done** (all are 5 seeds × 4,000 lives unless stated; EV is the seed median)
- **Q1, baselines (graded 10-15). ANSWERED, but velotrade's is stale.** Pinned leg is the ETH-prop 730 d corpus, n=355.
  - f516-01 velotrade: EV $123, P(net>0) 0.29–0.33. This was priced at `risk_pct` 0.01, and the config moved to 0.005 in #18157. The current-config number is arm A of 1bf3-02: $171, P 0.44–0.47.
  - f516-02 tradeify: $178, P 0.38–0.39.
  - f516-03 breakout_2: $34, P 0.22–0.23.
  - All three are indeterminate: EV > 0 but P < 0.70.
- **Q2, sizing. ANSWERED.** f516-05 velotrade PASS (C075 $174 vs A $123). f516-06 tradeify FAIL (flat holds).
- **Q3, per-leg $ risk. ANSWERED (FAIL).** f516-04 mixed arm: EV $21, P 0.16–0.17.
- **Q4, DD switch. ANSWERED (FAIL, the setting stands).** f516-07: armed $123, 0.9 $126, off $126. The switch costs essentially nothing.
- **Q5, breadth. Mostly answered.**
  - f516-08 FAIL, decided on survival seeds. trend6 arm $380, +XRP arm $180.
  - Pool admission: f516-09 (tradeify) and f516-10 (velotrade) PASS for the 4h ETH+SOL pair (n=116 per leg, 1095 d).
  - Head-to-heads: 6504-01 velotrade PASS. 6504-02 tradeify FAIL even though EV is $884 vs $178, because p_alive falls 0.16 → 0.11. 1bf3-02 velotrade at 0.005 FAIL ($676 vs $171).
  - ee68-01 PASS: every C4H arm dominates.
  - Matched-risk controls on velotrade (book 1h vs 1h + C4H at the same risk):

    | risk | 1h book EV | with C4H pair | verdict |
    |---|---|---|---|
    | 0.0025 | −$10 | $310 | 8bbc-04 PASS |
    | 0.0035 | $72 | $550 | 8bbc-05 PASS |
    | 0.0045 | $141 | $652 | 8bbc-03 FAIL |

  - **Stage-0 at the prop venue cost stack (1bf3-03..06, 10-15): all PASS.**

    | leg | n | net R | positive folds |
    |---|---|---|---|
    | eth_4h | 116 | +31.0 | 4/4 |
    | sol_4h | 116 | +43.3 | 3/4 |
    | eth_prop | 517 | +33.4 | 3/4 |
    | sol_prop | 203 | +18.7 | 3/4 |

  - More folds: f01d-01 sol_prop PASS, 6 of 8 folds positive, n=394.
- **Tradeify non-crypto (24ca/ca42). Done, all fail or underpowered.**
  - 24ca-01 SLV fade FAIL: EV −$21, n=518.
  - ca42-01 SLV fade at 5:1 leverage: still fails (EV −$22). The row has landed but is ungraded.
  - 24ca-02 QQQ and 24ca-03 SPY daily trend: n=55, underpowered. EV is exactly −$120 on every seed with ev_se 0 and p_alive 1.0, meaning no life ever trades its way past the fee. This is degenerate (pace or the 2:1 leverage cap).
  - 24ca-04 SPY pullback 1h FAIL: EV −$101, n=313.
  - 24ca-05 USO: queued, never run.
- **Q6: OPEN, blocked. Q7: never had a unit in this programme.**

**3. Queue state**
- Attribution: theme `new_strategy_prop` (THEMES.yaml weight 6) or roadmap `L-PROP`, across `research/queue` and `research/queue/blocked`.
- Theme counts: **8 queued / 12 blocked / 340 done / 2 retired**.
- Of the 8 queued:
  - 2 already have result rows but are not graded: ca42-01 and f01d-02.
  - 2 are not prop-tradable at all: 0929-104 (funding carry on BNB) and 1007-017 (ETF basket).
  - 2 come from a broken template: 1016-002 and 1016-003.
  - So only **24ca-05 and 1007-002** are real prop work. 1007-002 is p1, but the plan says to re-run it only after Q6.
- Oldest queued: RQ-20260927-003 (ml_health; its result is producer_failed) and RQ-20260929-104.
- Blocked:
  - f516-11 (Q6): no gradable closes. PROP-EXIT-READ has been queued since 10-11.
  - 1007-031: its blocker text says velotrade_1 has "NO roster". That is stale; it now has one.
  - 9da8-05 and 9da8-06: blocked on harness cost gaps that CLAUDE.md says were fixed 10-11 (FRONTIER-LEVER-HARNESS-COSTS). Also stale.
  - 1007-240 (ORB has no cost stack), 1007-241 (no timeout input), 1007-018 and 1007-019 (Bybit funding returns 403, no basis instrument).
- **Operator's 2026-10-16 asks: no units exist yet.**
  - "matched-risk" matches only 8bbc-03..05, all velotrade. That search is the positive control: it shows the grep finds such units, so the absence elsewhere is real.
  - No tradeify_1 or breakout_2 matched-risk head-to-head exists.
  - No Tradeify new-strategy search exists: 24ca only mapped *existing* params onto 4 symbols. Nothing searches new families or untraded symbols.

**4. Misalignments and problems**
1. **The survival clause decides on noise.** `prop_ev_grid.py:160,183` requires p_alive ≥ incumbent on every seed. In 8bbc-03, seed 1 is 0.3960 vs 0.3965, while one seed's SE is about 0.008 and EV is $652 vs $141. Strict ≥ comparisons inside noise fail real effects; 1bf3-02 and f516-08 fail the same way.
2. **A result passed and nobody acted on it.** The C4H gain over the 1h book is consistent at every matched risk level, roughly +$320 to +$510 per life on velotrade. But **sol_4h is `execution: shadow` and routed to no account**, so under `prop-roster-gate-guard` only eth_4h could be added (it is live on bybit_1/2). No arm has ever priced "1h book + eth_4h alone". `comms/prop_survival/` contains only a README.
3. **Results that should have closed rows didn't.** f516-04 FAILed, and its rule says to kill the held proposal, yet PROP-PER-LEG-EV-GRID is still `queued` with a 10-11 note. The 1bf3 Stage-0 PASSes close the "open gap" that the PROP-BOOK-SEARCH-1095D note still lists.
4. **The template defect is still live.** `research/templates/prop-fit-breakout.yaml` still targets breakout_1 under Classic `breakout.yaml`. It generated RQ-20261016-002/003 today. 05-PROP §6 flagged this on 10-14.
5. **Integrity:** f01d-02 (eth_prop folds) is `control_failed`: the control arm does not reproduce the committed record, so nothing can be read from it. The 24ca-02/03 output is degenerate.
6. **Weight is not reaching prop work.** The theme is weighted 6, but non-prop units dilute it and only 2 real prop units are runnable.
7. **The plan text is stale.** 05-PROP §1 says velotrade is at 0.01 and "baseline not yet measured". The prop-gate README describes a "soak due" date, which is calendar language the soak doctrine forbids.

**5. Recommended next 5 days (to Tue 2026-10-20 review)**
1. **[research unit] velotrade_1 1h book + eth_4h only, at matched risk 0.0035 and 0.005.** This is the only gate-eligible version of the C4H gain. First step: copy RQ-20261015-8bbc-05.yaml and drop the `trend_donchian_sol_4h` `--trades` from the C arm.
2. **[build row] Fix the prop_ev_grid survival clause** so it compares within a tolerance (for example ≥ incumbent − 2·SE) or pools seeds; register the rule first, then re-grade 8bbc-03, 6504-02 and 1bf3-02. First step: add a test at `prop_ev_grid.py:160` that reproduces the 8bbc-03 seed-1 case.
3. **[research unit] Matched-risk C4H head-to-heads for tradeify_1 and breakout_2**, as the operator asked: 3 risk levels each, under each account's own ruleset. First step: clone 8bbc-03/04/05 and swap the `--ruleset` and cost flags to the f516-02/03 values.
4. **[research unit] Tradeify new-strategy search (operator ask).** Cover the untraded crypto symbols with the 1h–4h trend harness, which batch 1 showed is the pace that survives cost, plus the SILVER and XYZ100 families beyond existing params. First step: author one unit per (symbol, family) at Tradeify costs.
5. **[build row] PROP-EXIT-READ (REST path).** It unblocks Q6/Q7. First step: dispatch a lane on the velotrade_1 `closed_on_terminal` case.
6. **[decision for operator]** Add eth_4h to velotrade_1 once item 1 PASSes and its `comms/prop_survival/` record exists.

**STOP or retire:**
- Retire RQ-20261016-002/003 and fix the template.
- Kill PROP-PER-LEG-EV-GRID, citing f516-04 as the terminal reason.
- Retire 0929-104 and 1007-017 from this theme.
- Grade ca42-01 now; that closes the SLV line.

CONFIDENCE: I verified directly from the unit YAMLs, the result jsonl files, `accounts.yaml`, `strategies.yaml`, the checklist JSON and the grader code: unit counts, verdicts, EVs and n, routings, blocker text, and the template defect. I did not verify open PRs (the `gh` call failed) or whether any gradable prop closes exist since 10-11. The 24ca degeneracy cause and the SE figure (computed as √(p(1−p)/4000), about 0.008) are inferred.
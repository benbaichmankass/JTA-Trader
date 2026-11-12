# w9 gate breakdown — four candidate gates, built as reports (2026-11-12)

**Gates this adds or changes: none.** Lane `ML-ADVISORY-SCOPE-GUARD` (w9 bundle), Tier 1.


**Decision this serves.** Operator, decisions page w9, 2026-11-12: *"Build them as reports only (no gate)"*; note: *"I want a break down of each one so that I can decide on each gate if its necessary or not."* The manager turns each check below into its own decisions-page question.

**What was built.** One report script, `scripts/ci/report_w9_gates.py` (`--check <name>|all`, `--json`, `--history N`, `--self-test`). It **never exits 1**: a hit is a line in the report; an unreadable source is `read_state: could_not_look` and still exits 0 (exit 2 is only a failed `--self-test`). It runs in CI as the `w9-gate-reports` entry in `run_guards.py` (report mode, always passes). Its positive/negative controls run in `tests/test_report_w9_gates.py`. Populations are re-parsed from `config/accounts.yaml` and `config/strategies.yaml` on every run; nothing below is a hard-coded count.

**Population and reproduction.** "Risk-bearing" = `account_class` is not `paper` (the `roster-promotion-evidence-guard` predicate, fail closed). Numbers below were measured at `origin/main` 2026-11-12 by `python3 scripts/ci/report_w9_gates.py --history 60`; re-run for current values.

**History window, stated once.** This container's clone is shallow; after deepening, the oldest reachable commit is **2026-10-29**. "History" below is therefore the **33 commits from 2026-10-29 to 2026-11-12 that touched `config/accounts.yaml` / `config/strategies.yaml` (+ `regime_policy.yaml` for check 1)**. It says nothing about before 10-29. Check 2 reads `src/` and was not replayed (a checkout per commit is not cheap).

## Summary

| # | Row | Hits at HEAD | Over the 33-commit window | Cost of a false block | Verdict input for the operator |
|---|---|---|---|---|---|
| 1 | `ML-ADVISORY-SCOPE-GUARD` | **0 / 9** legs (5 carry a `trend_vol` cell, all 5 have an evidence file) | 0 of 33 commits | Low: an unrelated roster/ML PR is held until a record path is cited | Catches a *future* act; today's guard-worthy surface is already clean. Its evidence test is existence-only (see §1). |
| 2 | `LEVER-LIVE-CONSUMER-PARITY` | **3 / 30** lever keys harness-tested with no live consumer (2 are probably false positives) | not replayed | Lowest: it is a listing; a block would only force a `no_consumer` verdict line | Informational value is real (the audit's `trail_level_tight_mult` case); blocking value is small. |
| 3 | `PROP-GATE-RECOST-AND-FLOOR` | **3 / 9** prop routings fail the registered floor (all `ml_entry`, EV < 0) — all 3 carry the operator's baseline exception | **24 of 33** commits had ≥1 hit (`ml_entry`, and `trend_donchian_eth_prop` at p_breach 0.934 before it left the rosters) | **Highest**: it gates live prop money, and a false block strands a leg the operator has decided to run | The one check that has a live, repeated hit. Whether it should be a gate depends on how the operator exception interacts with it (see §3). |
| 4 | `RM-AM-STANDARD-GUARD` | **2 / 9** legs (`ml_entry`, `ml_entry_eq_struct`: no trail, no coverage row) | 25 of 33 commits had ≥1 hit | Medium: it blocks adding a real-money leg until a trail + matrix row exist | Hits are exactly the ML legs, which have no trail by design — see §4. |

---

## 1. `ML-ADVISORY-SCOPE-GUARD` — ML influence on a real-money/prop leg without a Gate-2 record

**What it would catch.** A roster leg on a risk-bearing account that (a) carries `advisory_policy.mode: downsize`, (b) carries `exit_head_action: close`, or (c) is the target of a `trend_vol` cell in `config/regime_policy.yaml` — with no Gate-2 evidence record. Spec source: plan `docs/plans/ml-live-promotion-plan-2026-10-29.md` § 6 I6. It keys on roster membership, not on the `mode`/`execution` fields (CLAUDE.md: CI is asymmetric).

**Hits over the current repo state.** Population: **9 risk-bearing roster legs**. `advisory_policy` is `downsize` on **0**; `exit_head_action: close` on **0** (the 3 `exit_head_action` declarations in `strategies.yaml` are all `annotate`). **5 of 9** legs are named by a `trend_vol` cell (`trend_donchian_eth_4h`, `trend_donchian_sol_4h`, `trend_donchian_sol_prop`, `trend_donchian_xrp_4h`, `trend_donchian_xrp_adx25`, via the `trend_donchian` family key). All 5 have a `comms/strategy_evidence/<leg>.json`, so the guard as specced reports **0 hits**.

**Over history.** 33 commits, 2026-10-29 → 11-12: **0 commits with a hit**; the population grew from 7 to 9 legs over the window.

**Findings the number hides.**
- *The evidence test is a proxy.* "A Gate-2 evidence record path" is implemented as "`comms/strategy_evidence/<leg>.json` exists". That file proves the leg cleared the roster-promotion bar, not that the ML *effect* (downsize/close) did. A stricter version needs a per-effect record that does not exist today; that is a design decision, not a script fix.
- *The `trend_vol` cells are not ML.* They are a hand-authored regime table (Tier-3, already operator-gated) that predates the ML work. Including them makes the guard fire on a non-ML mechanism that already has its own gate. Dropping clause (c) would leave the guard covering only the two ML levers, both currently unused on real money.
- *Cell matching is by name.* `policy.py` keys by strategy name, so a cell matches a leg when the key equals the leg or is a `<key>_` prefix of it. A strategy renamed away from the prefix would silently fall out.

**Cost of a false block.** Low and bounded: it would trigger on a PR touching roster/ML config, and the remedy is citing a record path. It does not touch a running order. The risk is the opposite — cry-wolf friction on the 5 `trend_donchian` legs if clause (c) stays.

**Is a gate necessary?** Today's measured surface is clean, so the gate would be preventive only. The plan's own sentence ("All five act only on legs rostered on `bybit_1` alone") is currently true. A gate earns its keep only if ML-influence PRs are expected to arrive at a rate that the existing roster-promotion-evidence guard and Tier-3 review do not already cover.

---

## 2. `LEVER-LIVE-CONSUMER-PARITY` — every harness-tested exit lever has a live consumer, or says it does not

**What it would catch.** A lever key a backtest harness can sweep and "pass" that nothing on the live path reads, so a harness PASS cannot reach real money. Origin: `docs/reviews/2026-10-29-system-conformance-audit.md` § 1.5 (`trail_level_tight_mult`, `be_floor_r`).

**Hits over the current repo state.** Population: **30 lever-shaped keys** = 22 declared in `config/strategies.yaml` (regex `^(trail|be_|tp_|stale|giveback|partial|exit_|breakeven|chandelier)`) plus 8 config-shaped keys that `scripts/backtest_*.py` / `src/backtest/*.py` read but no leg declares. Consumer rule: the key appears as a quoted string in `src/**/*.py` outside `src/backtest/` and `bracket_advisor.py`. Result: **27 have a consumer; 3 are `no_consumer` while harness-tested**:
- `be_floor_lock_r` (read by `backtest_pullback.py`; 0 live consumers),
- `trail_level_min_r` (2 harness files; 0 live consumers),
- `trail_adx_fired_bars` (2 harness files; 0 live consumers).
Also `no_consumer` but **not harness-tested** (not a hit): `tp_source`, `trail_atr_mult` (each declared on one leg).

**False positives to expect.** `trail_adx_fired_bars` looks like a harness *output counter*, not a config lever. `trail_level_min_r` may be reached through a differently-spelled key. A string match is also **not proof** the value is read on the order path: `be_floor_r` shows a consumer (`src/prop/prop_trail.py`) yet the audit records it as `UNMODELLED` in the replay — those are different questions, and this check only answers "is the key read somewhere live".

**A gap the audit named that this does not show.** `trail_level_tight_mult` (the audit's example) is **not** in the 30: no harness file quotes it, so the harness key extractor never sees it. The check lists levers by what the code *names*, not by what the harness *accepts* (CLI flags are not parsed).

**Over history.** Not replayed (reads `src/`; one checkout per commit).

**Cost of a false block.** Lowest of the four. The check is a listing; a block would only force someone to add a `no_consumer` verdict row for a key. No order path is touched.

**Is a gate necessary?** Its value is as a standing listing the operator or a review reads, not as a refusal: a lever with no consumer is a *to-build* row, not a reason to stop an unrelated PR. As a report it already earns its place; as a gate it would block PRs unrelated to the lever.

---

## 3. `PROP-GATE-RECOST-AND-FLOOR` — enforce the registered prop breach floor

**What it would catch.** `check_prop_roster_gate.record_problems` today only checks fields exist and `verdict == pass` (or the operator baseline exception). This report applies the *registered* rule `RULE-P5-GATE-BRK-PER-LEG-V2` (`research/queue/RQ-20261029-9a2c-01.yaml`): `n ≥ 88`, per-firm breach ceiling `c = 1 − 2F/W` (derived from the ruleset: breakout_turbo 0.889, tradeify_247 0.750, velotrade_classic 0.730), and EV > 0 at the **worst** seed. It reads the per-account cell (`accounts` or `per_firm`) when the record has one; otherwise the record's headline `p_breach`, which is the seed-max *lifetime* field and over-reads breach.

**Hits over the current repo state.** Population: **9 `(prop account, leg)` routings** (3 live prop accounts × 3 legs; the one dry-run prop account has an empty roster). **3 hits, all `ml_entry`** (one per prop account), each failing **EV only**: worst-seed EV −$14.40 (breakout_2), −$86.88 (tradeify_1), −$29.18 (velotrade_1); per-attempt eval breach is *under* each ceiling (0.784 / 0.712 / 0.597) and edge CI95 lower bound is −0.106 R. **All 3 carry `operator_exception: baseline`** (decided 2026-11-08), so the existing guard admits them and a floor gate with no exemption path would not.
`trend_donchian_eth_4h` and `trend_donchian_sol_4h` **pass the floor** on all three firms (EV positive, breach below ceiling) but are graded `fail_edge` and `contested` under the V3 edge rule, which this report does *not* gate — the floor and the edge CI are different tests; the operator should know the floor alone would have waved both through.

**Over history.** 33 commits, 2026-10-29 → 11-12 (records read at each commit): **24 of 33 had ≥1 hit**; the legs that hit were `ml_entry` and `trend_donchian_eth_prop`. The latter is the audit's case (p_breach **0.934** vs ceiling 0.889 on a record that predates the 11 bps re-cost, row `PROP-GATE-RERUN-20261029`); it has since left the rosters. Population caveat: the oldest 3-routing commits predate the 4h/ML legs.

**Cost of a false block.** **Highest of the four — this is the check that touches live prop money.** A false block here strands a leg on an account the operator has chosen to keep trading (the 11-08 `ml_entry` baseline quote: *"…not let those accounts sit idle"*), or blocks a demotion-adjacent roster edit. Because the record's `p_breach` is seed-max lifetime, running the floor on headline fields (the `PROP-GATE-RECOST-AND-FLOOR` spec as worded) would **over-block**: the pre-fix headline for `ml_entry` read 0.875, over two of the three ceilings, while the per-attempt number the rule actually registers is 0.597–0.784, under all three.

**Is a gate necessary?** It has produced a hit on most commits in the window, so it is the only check with real recurring signal. But all current hits are operator-excepted, so a gate would either duplicate the exception path or contradict an operator decision. The sharper question for the operator is whether the exemption should be allowed to cover a *negative-EV* leg at all, rather than whether a second guard is needed.

---

## 4. `RM-AM-STANDARD-GUARD` — basic active management as a standard for real-money legs

**What it would catch.** A risk-bearing roster leg lacking: (a) a declared trail with a computable activation R, (b) a TP-doctrine grade or a dated visible exemption line, (c) a row in `docs/research/exit-refinement-coverage.json`. (b) reuses `check_tp_doctrine.scan()` and its `BASELINE_2026_10_06` lines as the "dated visible exemption"; (c) matches matrix rows by strategy prefix + symbol + timeframe.

**Hits over the current repo state.** Population: **9 risk-bearing roster legs**. **2 hits**: `ml_entry` (4 routings: bybit_2 + the 3 prop accounts) and `ml_entry_eq_struct` (alpaca_live) — both **no trail declared and no coverage row**. Their TP-doctrine state is `compliant` or a baseline line, so clause (b) is clean for all 9. Clause (a) is split: **3 explicit** activation R (`trend_donchian_sol_4h`, `trend_donchian_xrp_4h`, `trend_donchian_xrp_adx25`), **4 implicit** (a chandelier trail that runs from entry; reported as `activation_implicit`, deliberately **not** a hit), **2 none**. The row note says "7 of 7 legs declare a trail" on 2026-10-28; at HEAD that is **7 of 9** because the ML legs are now rostered.

**Over history.** 33 commits: **25 had ≥1 hit** (`ml_entry`, `ml_entry_eq_struct`), 8 had none (the population grew from 7 legs, all clean, to 9). The TP-doctrine axis (b) was **not replayed** historically, so the history is clauses (a) and (c) only.

**Cost of a false block.** Medium. The two hit legs are ML-entry legs the operator chose to run on real money and prop accounts; they set their exit through the entry model's own bracket, so "no trail" is by design, not omission. A gate as worded would have blocked the 11-08 `ml_entry` prop roster decision, or forced a trail onto a leg whose edge was measured without one (a Tier-3 change by another route).

**Is a gate necessary?** The guard is the right shape for a *new, ordinary* trend leg (the standard the operator described), and 7 of 7 non-ML legs already comply. The open design question is the ML-entry class: either the standard carries a named ML exemption (a visible dated line, the `tp-doctrine-guard` baseline pattern), or the ML legs must get a trail. That is the operator's call; the report cannot settle it.

---

## Limits of this report (said once)
- Counts are measured over the populations named above, at one commit; re-run, do not quote.
- Check 1's "evidence record" and check 4's "coverage match" are existence/name proxies, listed under each check.
- Check 3 ignores the V3 edge CI (reported in the JSON as `edge_ci95_lower_r`, not graded) and cannot grade a record that has no per-account cell beyond its headline.
- History is the 33 commits 2026-10-29 → 11-12 reachable in this container; nothing before that was measured.
- A report is not a detector for itself: if the script silently read an empty roster, `read_state` would say `could_not_look`, never `0 hits`.

## Reproduce
```
python3 scripts/ci/report_w9_gates.py --history 60            # all four, with the window above
python3 scripts/ci/report_w9_gates.py --check prop-floor --json
python3 scripts/ci/report_w9_gates.py --self-test             # positive + negative controls
```

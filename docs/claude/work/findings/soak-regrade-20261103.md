# Soak regrade under the 2026-11-01 rule — 2026-11-03

> **Doc status:** `unknown` · category `unknown` · last verified `never` · lane SOAK-REGRADE (dispatched by Manager Session 2026-11-03a) · measured 2026-11-03 against `origin/main` @ the commit this file lands on.

Gates this adds or changes: none.

## Population
- **50 TESTING legs** — `python3 scripts/ops/strategy_status.py` (60 legs: testing 50, production 7, inactive 3).
- **72 soak contracts** — `docs/claude/work/SOAKS.json` (as_of 2026-11-01; 65 `mechanical`, 7 `not_soaking`).
- Stage-0 verdict = `scripts/ops/mandate_resolver.py --leg L --from S1 --to S2 --account <real-money acct>` run once **as-is** and once with the soak/mechanics clauses **bypassed in-process** (so the Stage-0 clauses — record, source_run, B1 C1–C5, R-N ≥ 30, expectancy, fold majority, holdout, affordability — decide). Real-money account per book: bybit_1/prop → bybit_2, alpaca_paper/portfolio → alpaca_live, ib_paper → ib_live.
- Iteration coverage = `python3 scripts/research/iteration_orphans.py --json`.

## Counts
| class | n | legs |
|---|---|---|
| **READY** (Stage 0 PASS + mechanics proven) | **0** | — |
| **ONE-TRADE** (Stage 0 PASS, new mechanics) | **0** | — |
| **ITERATE** (Stage 0 FAIL / NEEDS-DATA / none) | **50** | all testing legs (47 on a roster, 3 on none). Iteration coverage: 40 covered, 10 orphan → 10 pipeline items filed (PI-20261103-6GNSZYUN-0001…0010) |
| **STALE-CONTRACT** | **0** | every SOAKS.json contract already has `n_needed` 1–2 (71 × 1, 1 × 2), the canonical checklist and no calendar field; `soak-contract-guard` and `soak-doctrine-guard` green; no open checklist row sets a soak to a sample size or date (grep of `docs/claude/work/checklist/*.json`, 8 regex hits read by hand, all false positives) |

**Why zero READY, by deciding clause (bypassed run, 54 leg×account pairs over the 47 rostered legs):** RULE-D1 verdict `fail` (R-B1-C4) 21 · R-N (OOS n < 30) 10 · R-HOLDOUT (no `holdout_confirmation` anywhere in `comms/strategy_evidence/`) 6 · fidelity `approximate` (R-B1-C5) 6 · no evidence record 5 · source_run absent 3 · fold majority 2 · affordability snapshot missing 1. Not one pair reaches FIRE. **The rule change did not leave anything stranded on paper that is ready to go live: what holds every leg back is Stage 0, not the soak.**

**Closest to READY** (RULE-D1 pass, faithful, full cost stack, mechanics proven, blocked ONLY by R-HOLDOUT): `tlt_pullback_1d` (n 134, +12.69R, 5/8 folds; holdout unit RQ-20261023-be01-01 exists), `slv_trend_1h` (n 68, +53.14R, 4/4), `tqqq_trend_long_1d`, `scha_trend_long_1d` (n 78, +4.64R), and on crypto `trend_donchian_sol_4h`, `trend_donchian_xrp_adx25` (also need a crypto mechanics proof: no bybit path is registered in `config/mechanics_paths.yaml`). A holdout pass flips the first four to READY with no soak.

## Problems found (said, filed)
1. **Soak snapshot is 30 days stale** (`comms/mandate_evidence/soak_state/2026-10-04.json`; resolver max age 7 d) — the resolver reads every un-dispositioned soak as state `None`. Already filed as checklist row `MANDATE-EVIDENCE-SNAPSHOT-CRON` (queued). Did not change any class here (Stage 0 decides first).
2. **6 IB-paper legs have no soak contract** (claude_desk, ict_scalp_mgc_15m, mes_trend_long_1d, mgc_pullback_1d, mgc_trend_1h, mhg_pullback_1d): `soak_state.py --backfill` has not been run since ib_paper joined the demo floor. Noted in PI-…-0005; harmless while Stage 0 blocks them.
3. **3 TESTING legs on no roster** (qqq_pullback_1h, spy_pullback_1h, tlt_pullback_1h) violate "Stage 1 is the demo floor"; strategy-status-guard reports them as UNHOMED. qqq_pullback_1h filed (PI-…-0006); the other two are `covered` by an iteration unit.
4. **ml_entry_v2** has no own evidence record; `iteration_orphans.py` reads `ml_entry.json` for it while the resolver reads `ml_entry_v2.json` (missing) — inconsistent subject→record mapping (PI-…-0010).

## Per-leg table (ITERATE = all; orphans filed this session)
| leg | books | Stage-0 (iteration_orphans) | resolver, soak bypassed | mechanics | soak contracts | class | iteration |
|---|---|---|---|---|---|---|---|
| `avax_pullback_2h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `claude_desk` | alpaca_paper, bybit_1, ib_paper | indeterminate | bybit_2: NEEDS-DATA R-RECORD-MISSING; alpaca_live: NEEDS-DATA R-RECORD-MISSING; ib_live: NEEDS-DATA R-RECORD-MISSING | not proven | alpaca_paper/stage1 n1 open; bybit_1/stage1 n1 open; bybit_1/shadow n1 open | ITERATE | covered |
| `e4_oi_shock_1h` | bybit_1 | fail | bybit_2: NEEDS-DATA R-RECORD-MISSING | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `eth_pullback_2h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `eth_pullback_prop_2h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `fade_breakout_4h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `fvg_range_15m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `gdx_pullback_1d` | alpaca_options_paper, alpaca_paper | indeterminate | alpaca_live: NEEDS-DATA R-N | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | orphan → PI-20261103-6GNSZYUN-0007 |
| `gld_pullback_1d` | alpaca_portfolio, ib_paper | indeterminate | alpaca_live: REFUSE R-B1-C5; ib_live: REFUSE R-B1-C5 | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 KILLED; ib_paper/stage1 n1 open | ITERATE | covered |
| `htf_pullback_trend_2h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `ict_scalp_5m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; -/shadow n1 open | ITERATE | covered |
| `ict_scalp_avax_5m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `ict_scalp_eth_15m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `ict_scalp_mgc_15m` | ib_paper | indeterminate | ib_live: REFUSE R-SOURCE-RUN-ABSENT | not proven | none | ITERATE | covered |
| `ict_scalp_sol_15m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `ict_scalp_sol_5m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 KILLED | ITERATE | covered |
| `ict_scalp_xrp_15m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `ict_scalp_xrp_5m` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `ief_pullback_1d` | alpaca_paper | indeterminate | alpaca_live: REFUSE R-B1-C5 | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 PASS | ITERATE | covered |
| `iwm_trend_long_1d` | alpaca_paper, ib_paper | indeterminate | alpaca_live: NEEDS-DATA R-N; ib_live: NEEDS-DATA R-N | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | covered |
| `mes_trend_long_1d` | ib_paper | fail | ib_live: REFUSE R-B1-C4 | not proven | none | ITERATE | covered |
| `mgc_pullback_1d` | ib_paper | indeterminate | ib_live: NEEDS-DATA R-N | not proven | none | ITERATE | covered |
| `mgc_trend_1h` | ib_paper | pass_unconfirmed | ib_live: REFUSE R-FOLDS | not proven | ib_paper/shadow n1 REFUSE | ITERATE | orphan → PI-20261103-6GNSZYUN-0005 |
| `mhg_pullback_1d` | ib_paper | indeterminate | ib_live: REFUSE R-B1-C5 | not proven | none | ITERATE | covered |
| `ml_entry_v2` | bybit_1 | pass_unconfirmed | bybit_2: NEEDS-DATA R-RECORD-MISSING | not proven | bybit_1/stage1 n1 open | ITERATE | orphan → PI-20261103-6GNSZYUN-0010 |
| `qld_trend_long_1d` | alpaca_paper | indeterminate | alpaca_live: NEEDS-DATA R-N | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | covered |
| `qqq_pullback_1h` | — | pass_unconfirmed | — (on no roster; not resolvable) | not proven | alpaca_paper/stage1 n1 KILLED | ITERATE | orphan → PI-20261103-6GNSZYUN-0006 |
| `qqq_trend_long_1d` | alpaca_paper, ib_paper | indeterminate | alpaca_live: NEEDS-DATA R-N; ib_live: NEEDS-DATA R-N | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | covered |
| `scha_trend_long_1d` | alpaca_paper | pass_unconfirmed | alpaca_live: NEEDS-DATA R-HOLDOUT | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | orphan → PI-20261103-6GNSZYUN-0003 |
| `slv_pullback_1d` | alpaca_options_paper, alpaca_paper | indeterminate | alpaca_live: REFUSE R-B1-C5 | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | orphan → PI-20261103-6GNSZYUN-0008 |
| `slv_trend_1h` | alpaca_options_paper, alpaca_paper | pass_unconfirmed | alpaca_live: NEEDS-DATA R-HOLDOUT | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open; alpaca_paper,alpaca_options_paper/shadow n1 PASS | ITERATE | orphan → PI-20261103-6GNSZYUN-0002 |
| `sol_pullback_2h` | bybit_1 | indeterminate | bybit_2: NEEDS-DATA R-N | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `splg_trend_long_1d` | alpaca_paper | indeterminate | alpaca_live: REFUSE R-SOURCE-RUN-ABSENT | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | covered |
| `spy_pullback_1h` | — | fail | — (on no roster; not resolvable) | not proven | alpaca_paper/stage1 n1 KILLED | ITERATE | covered |
| `spy_trend_long_1d` | alpaca_paper, ib_paper | indeterminate | alpaca_live: NEEDS-DATA R-N; ib_live: NEEDS-DATA R-N | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | covered |
| `squeeze_breakout_4h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `tlt_pullback_1d` | alpaca_paper, ib_paper | pass_unconfirmed | alpaca_live: NEEDS-DATA R-HOLDOUT; ib_live: NEEDS-DATA R-AFFORD | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 PASS | ITERATE | orphan → PI-20261103-6GNSZYUN-0001 |
| `tlt_pullback_1h` | — | fail | — (on no roster; not resolvable) | not proven | alpaca_paper/stage1 n1 KILLED | ITERATE | covered |
| `tqqq_trend_long_1d` | alpaca_paper | pass_unconfirmed | alpaca_live: NEEDS-DATA R-HOLDOUT | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 PASS | ITERATE | covered |
| `trend_donchian` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `trend_donchian_1h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; bybit_1/shadow n1 open | ITERATE | covered |
| `trend_donchian_ada_4h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; -/shadow n1 open | ITERATE | covered |
| `trend_donchian_avax_4h` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open; -/shadow n1 open | ITERATE | covered |
| `trend_donchian_eth` | bybit_1 | indeterminate | bybit_2: REFUSE R-B1-C5 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `trend_donchian_eth_prop` | breakout_2, bybit_1, tradeify_1, velotrade_1 | fail | bybit_2: REFUSE R-B1-C4 | own PASS | bybit_1/stage1 n1 PASS | ITERATE | orphan → PI-20261103-6GNSZYUN-0009 |
| `trend_donchian_sol` | bybit_1 | fail | bybit_2: REFUSE R-B1-C4 | not proven | bybit_1/stage1 n1 open | ITERATE | covered |
| `trend_donchian_sol_4h` | bybit_1 | pass_unconfirmed | bybit_2: NEEDS-DATA R-HOLDOUT | not proven | bybit_1/stage1 n1 open; -/shadow n1 open | ITERATE | covered |
| `trend_donchian_xrp_adx25` | bybit_1 | pass_unconfirmed | bybit_2: NEEDS-DATA R-HOLDOUT | not proven | bybit_1/stage1 n2 open | ITERATE | covered |
| `turtle_soup` | bybit_1 | indeterminate | bybit_2: REFUSE R-SOURCE-RUN-ABSENT | not proven | bybit_1/stage1 n1 open; -/shadow n1 open | ITERATE | covered |
| `uso_trend_1h` | alpaca_paper | pass_unconfirmed | alpaca_live: REFUSE R-FOLDS | path:alpaca_equity_bracket_v1 | alpaca_paper/stage1 n1 open | ITERATE | orphan → PI-20261103-6GNSZYUN-0004 |

## Two independent tracks (manager relay 2026-11-03 ~09:45Z: MECHANICS × EDGE, promoted when both green, in either order)

MECHANICS from `mandate_resolver._mechanics_proven` (SOAKS.json PASS dispositions + newest soak snapshot, which is stale 2026-10-04 so live passes may be missing) over `config/mechanics_paths.yaml`; EDGE from the soak-bypassed resolver run above (pass = FIRE).

| | EDGE pass | EDGE iterate |
|---|---|---|
| **MECHANICS proven** | **0** | **15** |
| **MECHANICS one-trade-pending** | **0** | **35** |
| **MECHANICS new-code-unbuilt** | **0** | **0** |

- **proven (15):** gdx_pullback_1d, gld_pullback_1d, ief_pullback_1d, iwm_trend_long_1d, qld_trend_long_1d, qqq_trend_long_1d, scha_trend_long_1d, slv_pullback_1d, slv_trend_1h, splg_trend_long_1d, spy_trend_long_1d, tlt_pullback_1d, tqqq_trend_long_1d, trend_donchian_eth_prop, uso_trend_1h.
- **one-trade-pending (35):** code is built and on a roster but has no own passed soak or registered proven path: avax_pullback_2h, claude_desk, e4_oi_shock_1h, eth_pullback_2h, eth_pullback_prop_2h, fade_breakout_4h, fvg_range_15m, htf_pullback_trend_2h, ict_scalp_5m, ict_scalp_avax_5m, ict_scalp_eth_15m, ict_scalp_mgc_15m, ict_scalp_sol_15m, ict_scalp_sol_5m, ict_scalp_xrp_15m, ict_scalp_xrp_5m, mes_trend_long_1d, mgc_pullback_1d, mgc_trend_1h, mhg_pullback_1d, ml_entry_v2, qqq_pullback_1h, sol_pullback_2h, spy_pullback_1h, squeeze_breakout_4h, tlt_pullback_1h, trend_donchian, trend_donchian_1h, trend_donchian_ada_4h, trend_donchian_avax_4h, trend_donchian_eth, trend_donchian_sol, trend_donchian_sol_4h, trend_donchian_xrp_adx25, turtle_soup.
- **new-code-unbuilt: 0.** Every testing leg's order path already exists (all 47 rostered legs run; the 3 unhomed ones ran before their soaks were KILLED). **Build priority list: empty.** The highest-value *mechanics* action is not a build: register a Bybit perp bracket path in `config/mechanics_paths.yaml` from the existing PASS soaks (ada_pullback_2h, trend_donchian_eth_4h, trend_donchian_sol_prop, trend_donchian_xrp_4h, xrp_pullback_2h, trend_donchian_eth_prop on bybit_1). That would move most crypto legs from one-trade-pending to proven by path. That entry goes in the promoting PR (per the registry header), so it is listed, not landed here. Second: refresh the soak snapshot (row MANDATE-EVIDENCE-SNAPSHOT-CRON), since several one-trade-pending legs may already have passed on the VM.
- **Promotion-ready (both green): 0.** No promotion PR is opened.

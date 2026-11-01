# alpaca_live — why it is quiet, and an ML decision model for it (2026-11-01)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ALPACA-LIVE-ACTIVITY-ML` (row `docs/claude/work/checklist/ALPACA-LIVE-ACTIVITY-ML.json`, roadmap `L-ML-LIVE`)

Gates this adds or changes: none.

Operator, 2026-11-01 ~10:30Z, verbatim: *"Also, we need to add a work item for this week to undetstand why there is no
activity on Alapaca live - we need ot have some trading activity going on there for us to learn from, I also want to make
sure we have MLs live on that account by the end of the week"*.

## A. Why alpaca_live is quiet — MEASURED 2026-11-01 ~10:35Z

Sources (all read this session through `scripts/ops/diag_fetch.sh`, served by the Caddy host): `alpaca_order_history?account_id=alpaca_live&after=2026-09-01` (the broker's own record),
`audit_query?strategy=iaum_pullback_1d&side={buy,sell}&since=2026-09-01` (the `signals` dual-write), `journal?table=order_packages&limit=1000`
(newest 1,000 packages, 2026-09-14..11-01), `broker_account_status?account_id=alpaca_live`; config re-parsed from `config/accounts.yaml` at `main` 1c1478b55.

**Verdict: correct-quiet, no fault — and structurally near-idle.** Every stage works; the roster gives it almost nothing to do.

| stage | measured | population |
|---|---|---|
| account | `ACTIVE`, not trading-blocked, `shorting_enabled: false`, multiplier 1 (cash), flat | broker read 10:35Z |
| roster | **1 leg**: `iaum_pullback_1d` (daily, gold proxy). `side_filter: long` | `config/accounts.yaml` |
| roster history | was 3 legs on 09-23 (`iaum`, `ief_pullback_1d`, `slv_pullback_1d`); `ief` moved to paper 10-22 (#19403, operator 10-21); `slv` demoted 10-24 (#19888, Stage-0 FAIL at power on 4 units) | `git log config/accounts.yaml` |
| evaluation | the leg evaluated every session through 2026-10-30 (newest eval row 10-30 19:57Z) | audit rows |
| long setups | **0 since 2026-09-24** (≈27 sessions). The last: 09-23 (filled) | `side=buy` audit rows since 09-24: 0 |
| short setups | 3 (10-16, 10-19, 10-20 IAUM), each dispatched to alpaca_live only (alpaca_paper held an open IAUM package) and refused by `side_filter: long` (cash account): packages `rejected` | audit `open_package_scoped` + `pipeline_result`; order_packages |
| venue orders since 09-01 | **3 bracket entries, all filled**: SLV 09-17 (1 sh), TLT 09-18 (1 sh), IAUM 09-23 (2 sh); 0 rejected | broker order history |
| exits | all 3 by the stop leg: TLT 09-22; SLV and IAUM 09-28 at the open (IAUM gapped through its stop) | broker legs |
| mirror | `alpaca_portfolio` `strategies: []` — B2 strict equality: alpaca_live's roster minus the IAUM affordability proxy is empty | `config/accounts.yaml`, `tests/test_paper_portfolio_accounts.py` |

**Why, in order of weight:**
1. **Roster size: one leg.** Two of three legs left the roster in late October, one on a Stage-0 FAIL. Nothing replaced them.
2. **The one leg's long setup is rare.** `iaum_pullback_1d` needs a trend-pullback-confirmation on a daily bar; it produced 0 long setups in ~27 sessions while gold sold off (its 3 setups in that span were shorts).
3. **Long-only cash book.** Venue shorting is disabled; every short setup is a refusal by design (3 since 09-24, 7 in the 09-15..10-23 window measured by ALPACA-SILENCE-1025).
4. **Daily cadence.** At most one decision per symbol per session.
5. **Affordability.** The book is small; whole-share sizing at 2% risk refuses most setups on high-priced ETFs (the MD-PROMOTE resolver measures 30 of 118 TQQQ setups sizing, 69 of 71 TLT; below).
6. **Not a cause:** data (every session evaluated), risk refusals on alpaca_live (none in the sample), buying power (the account is flat), service faults (none).

### Dispositions

- **PI-20261025-ALQWWPXT-0003** (near-idle roster, decision for the operator): already routed 10-25 to row ALPACA-LIVE-ROSTER-SCREEN on the operator's popup *"Yes: queue a roster screen (Recommended)"*. This row supersedes that route; its answer is section B plus the screen read below.
- **PI-20261025-ALQWWPXT-0002** (alpaca_paper buying-power starvation): **already `killed`** 2026-10-29 ("bulk reset 2026-10-29: value unknown (operator)"). Not reopened; it is a paper-soak question, not why alpaca_live is quiet.
- **RQ-20261025-bda2-01** (12-ETF long-only daily Donchian screen): **landed (#20194) and ran** (run 40256550846), graded **PASS** 2026-10-26 on arm T30 (pooled n=277, net +57.5 R, 4/6 folds, 4 of 8 powered cells). But **no Holm survivor** in any arm, so under its own rule it **nominates nothing**; 4 of 12 cells (SPLG, XLF, XLP, XLU) had no measurement (fetch fault, recorded). Its confirmation **RQ-20261026-47a9-01** (2022-2026) graded **INDETERMINATE** 2026-10-28. Its rule says *"extend the window or add instruments, never lower a floor"*; **no follow-up unit exists** (grep `47a9-01` in `research/queue/`: only itself). Filed as a pipeline item (below).

### Could an existing passing Stage-0 record add flow now? — MEASURED, no

Each `alpaca_paper` leg was graded against the CI five-clause roster bar (`check_roster_promotion_evidence.clause_verdicts`, account `alpaca_live`) and through `scripts/ops/mandate_resolver.py --from S1 --to S2 --account alpaca_live` with a fresh affordability reading (the equity reading was refreshed in the working tree only and NOT committed; the committed one is 9.2 days old):

- 11 of 15 paper legs clear the five-clause bar (fails: `ief`/`slv_pullback_1d` approximate fidelity, `splg` harness_failed, `claude_desk` no record).
- The resolver returns **NEEDS-DATA for every one**: `spy/qqq/iwm/qld/scha_trend_long_1d`, `gdx_pullback_1d`, `uso_trend_1h` on **R-SOAK-NOT-PASSED**; `tlt_pullback_1d`, `slv_trend_1h`, `tqqq_trend_long_1d` on **R-HOLDOUT** (no `holdout_confirmation` block).
- Two findings behind that, filed below:
  1. **The operator's 2026-11-01 rule is not wired yet.** "Proven mechanics go straight to real money" lives in `config/mechanics_paths.yaml`, which is `legs: {}`; the resolver still asks every leg for its own soak. alpaca_live's long-bracket path is proven by 3 filled entries with venue stop exits (09-17, 09-18, 09-23).
  2. **R-HOLDOUT cannot pass a commission-free leg.** It requires `cost_stack.fees > 0`; Alpaca ETF fee is 0.0 by the venue resolver. And `tqqq_trend_long_1d`'s holdout (RQ-20261023-be01-02, `confirmed`, n=34, +3.20 R) **selected a different configuration** (Donchian 20, not the record's 30), so the record's own config is unconfirmed. Writing a holdout block for TQQQ needs a Tier-3 parameter change first.

So no roster ADD is proposed from existing records: none clears the promotion bar today, and forcing one would bypass R-HOLDOUT.

## B. THE ENTRY model on alpaca_live — `RQ-20261101-bdc2-01`

Operator, 2026-11-01 ~10:40Z, verbatim: *"really, the same entry model should be applied to alpaca as to bybit 2 - we're trying to
consolidate so we have overall-context models, in addtion to the per-symbol models, and I'm not sure when we decided that there was a
distinction between bybit and the other accounts on this, but that's wrong - the supra-symbol mls are for all symbols on all accounts. If we
find evidence for per-category MLs later on, than we'll build those later on, but that was never the design spec for the models I asked for
this morning"*. An Alpaca-specific model this lane drafted before that message was **withdrawn unpushed and never run**.

So B1 is ONE read of the frozen served model (`ml-decision-entry-v1`, the c692-01 final fit, τ 0.10; artifact sha256 recorded) on
alpaca_live's `symbols:`, like c692-06 did for bybit_2. Registered in `research/queue/RQ-20261101-bdc2-01.yaml` and pushed **before** the
run; scorer `scripts/research/ml_entry_alpaca_score.py` (no fitting; imports the c692 feature and label code).

| the account's constraint | applied as an EXECUTION rule |
|---|---|
| cash account, no shorting | the served `decide()` picks the side; a SHORT decision opens nothing (both-sides read reported for the mirror) |
| market hours | Yahoo 1h REGULAR-session bars; decide at RTH bar closes on the model's clock (UTC close hour % 4 == 0, i.e. 16:xx and 20:xx UTC, ~2 a session); entry next RTH open, overnight gaps real |
| horizon | 24 bars (the model's `horizon_h`, counted in bars) ≈ 3.4 sessions |
| costs | fee 0.0 (commission-free venue resolver), slippage 5.0 bps round trip (`resolve_cost_policy`, provisional), regulatory 0.5 bps (SEC §31 + FINRA TAF, rounded up), funding 0 |
| features | the model's 20 on the equity's own bar sequence; the 5 cross-sectional / BTC features are defined by the model against its 60-perp reference and are read at the latest closed perp bar. **No feature is missing** (no funding/OI input), so no missing-feature handling exists to choose |

Bar: the operator's (held-out mean net R per LONG decision ≥ 0, point estimate), floor n ≥ 30 (c692-06's). Reported beside it, never
gating: the October forward monitoring (RQ-20261101-383f-03, lane ML-ENTRY-TP-REVISION) read LONGS n=137 at −0.308 R on crypto perps.

**Result:** section C (after the run).

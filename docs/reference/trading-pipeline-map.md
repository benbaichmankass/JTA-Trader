# Trading pipeline map — every step, technical and trading, side by side

> **Doc status:** `live` · category `lookup` · last verified `2026-11-14` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md)

> **Generated 2026-11-25 18:37Z** from `docs/reference/trading-pipeline-map.skeleton.md` by `src/runtime/pipeline_map.py`. Edit the skeleton, never this output; the generated blocks are rebuilt from their sources on every build.

**Gates this adds or changes:** none. This is a map, not a rule; it adds no CI guard, gate or required check.

**What this is.** One page that walks the live trading pipeline from market data to the research loop. Each stage
has two halves: **TECHNICAL** (which code runs it, where it lives, which service and VM run it, which broker) and
**TRADING** (which pieces make decisions there, how each works, its status and its track record). The operator asked
for it on 2026-11-14 so the system is easy to review; it is shown on the dashboard's **Work** tab
(`GET /api/bot/work/pipeline-map`).

**How to read it, and its limits.**

- **Code and config are the truth; this page is a claim about them** (RULE ONE: field beats comment). If the code
  disagrees with this page, the code wins: fix the skeleton. The drift checks at the end catch a path that moved.
- **This page is GENERATED.** The hand-written part is only this skeleton,
  `docs/reference/trading-pipeline-map.skeleton.md` (stage order, what each stage does, which modules run it).
  Every block marked "generated" is rebuilt from its source of truth by `src/runtime/pipeline_map.py`:
  `config/accounts.yaml`, `config/strategies.yaml`, `scripts/ops/strategy_status.py`,
  `comms/strategy_evidence/`, the journal's performance route, `ml/served/SERVED_MODELS.yaml`,
  `config/mandates.yaml`, `config/live_trade_review.yaml`, the `deploy/` unit files,
  `config/trader_import_closure.txt` and `scripts/ci/check_tp_doctrine.py`. The Work tab builds it live
  (`GET /api/bot/work/pipeline-map`); the committed `docs/reference/trading-pipeline-map.md` is a snapshot
  that `scripts/ops/pipeline_map_numbers.py` writes. Every number carries an "as of", a population and a
  provenance label (`src/runtime/provenance.py`); an unreadable source reads "—" with its read state, never 0.
- **Structure the v2 view reads** (`GET /api/bot/work/pipeline-map` field `structured`, built by
  `pipeline_map.build_structured`). The Work tab draws one straight vertical spine of these steps, technical
  elements to the LEFT and trading elements to the RIGHT, with the loops on the side. It is PARSED from this file,
  so keep the shape: each step is a `## N · Title` heading followed by a `| TECHNICAL | TRADING |` table with one row
  (technical = backticked modules, files, units and routes; trading = `**Name**: text` rules, which become the
  openable right-hand elements; if a cell has no bold rule it shows as one note). The loops are the DASHED edges
  (`X -. "label" .-> Y`) of the mermaid flow below; node labels must stay `N · Name`. Generated trading elements
  (legs, ML models, accounts, DD switch state, mandates) are attached by `pipeline_map.STEP_SOURCES`
  (step number to source of truth). Add a step by adding a heading and a node; no UI change is needed.
- **The skeleton checks itself.** The "Drift checks" block at the end lists any module path the skeleton cites
  that no longer exists, any rostered leg with no definition, and any enabled leg on no book.
- **A live book never establishes edge.** Backtest evidence (offline, Stage 0) and live results are shown in
  separate columns. Live results check mechanics and cost only (OPERATING-PLAN § 2).
- **Upkeep.** The weekly doc-freshness check (`.claude/skills/doc-freshness/SKILL.md` § "Weekly core-doc
  currency") re-runs the generator and compares the skeleton with the week's merged work. When a merged change alters a
  stage below, update the skeleton in the same PR or a follow-up (a habit, not a gate).
- **Deeper sources.** [`docs/ARCHITECTURE-CANONICAL.md`](../ARCHITECTURE-CANONICAL.md) § "End-to-End Trade
  Pipeline", § "TP doctrine", § "Active management", § "Prop ticket flow";
  [`docs/plans/OPERATING-PLAN-2026-09-21.md`](../plans/OPERATING-PLAN-2026-09-21.md) § 2 (the ladder and statuses).
  The older [`docs/TRADE-PIPELINE.md`](../TRADE-PIPELINE.md) is unverified (status `unknown`) and is superseded by
  this page for orientation.

## Where things run

| Host | What runs there |
|---|---|
| **`ict-bot-arm`** (live VM) | `ict-trader-live.service` runs `python -m src.main` (the trader: data, signals, routing, risk, orders, order monitor, reconcile, live-review rows watcher). `ict-web-api.service` runs `uvicorn src.web.api.main:app` on :8001 (read paths for the dashboard). `caddy.service` serves HTTPS `ict-bot.duckdns.org` and proxies to :8001. `ict-git-sync` pulls `main` about every 5 minutes (`scripts/deploy_pull_restart.sh`). The prop executor (`ict-prop-executor.service`, `scripts/ops/prop_executor_tick.sh`), the fills pullers and the liveness watchdog run here too. |
| **`ict-trainer-vm`** | ML lifecycle: `ict-trainer.service` runs `scripts/ops/run_training_cycle.sh`; units under `deploy/trainer/` (candle refresh, forecast, lifecycle, promotion readiness, publish). Research and backtest workflows dispatched to it. |
| **`ict-ib-gateway`** | IB Gateway only, on the private subnet; the trader reaches it from the live VM. |
| **GitHub Actions** | Research harness runs, evidence records, live-review routines, system actions, diag relays. |
| **Brokers** | Bybit (crypto), Alpaca (US equities and ETFs), Interactive Brokers (futures and equity ETFs), OANDA (FX and metals, practice), prop firms through the prop executors. |
| **Dashboard** | `benbaichmankass/ict-trader-dashboard`, a Svelte SPA on GitHub Pages that calls the API browser-direct through Caddy (CORS is load-bearing). |

<!-- BEGIN GEN:where -->
**Every systemd unit in the repo and what it runs** (source: `deploy/*.service`, `deploy/trainer/*.service`; 56 units; a unit file in the repo is not proof it is enabled on the VM: `/api/diag/services` is the runtime truth).

| Unit | Host | Runs |
|---|---|---|
| `ict-alpaca-fills-pull` | live VM (`ict-bot-arm`) | `python -u scripts/pull_alpaca_fills.py --all-alpaca-accounts --days 7` |
| `ict-claude-bridge` | live VM (`ict-bot-arm`) | `python3 -u -B -m src.bot.claude_bridge` |
| `ict-claude-decision-bot` | live VM (`ict-bot-arm`) | `python3 -u -B -m src.bot.claude_decision_bot` |
| `ict-db-integrity` | live VM (`ict-bot-arm`) | `python -u scripts/db_integrity_alert.py` |
| `ict-desk-build@` | live VM (`ict-bot-arm`) | `python3 -u -B scripts/ops/desk_build_job.py %i` |
| `ict-devnull-guard` | live VM (`ict-bot-arm`) | `/bin/sh -c 'if [ ! -c /dev/null ] \|\| [ "$(stat -c %%t:%%T /dev/null 2>/dev/null)" != "1:3" ]; then rm -f /d…` |
| `ict-env-check` | live VM (`ict-bot-arm`) | `python3 scripts/startup_env_check.py` |
| `ict-exchange-fills-pull` | live VM (`ict-bot-arm`) | `python -u scripts/ops/pull_bybit_transaction_log.py --all-bybit-accounts --days 7` |
| `ict-exchange-funding-pull` | live VM (`ict-bot-arm`) | `python -u scripts/pull_exchange_funding.py --all-bybit-accounts --days 7` |
| `ict-git-sync` | live VM (`ict-bot-arm`) | `bash scripts/deploy_pull_restart.sh` |
| `ict-health-snapshot` | live VM (`ict-bot-arm`) | `python -u scripts/write_health_snapshot.py` |
| `ict-heartbeat` | live VM (`ict-bot-arm`) | `python3 -u scripts/daily_heartbeat.py` |
| `ict-hourly-snapshot` | live VM (`ict-bot-arm`) | `python3 scripts/send_hourly_now.py` |
| `ict-ib-executions-pull` | live VM (`ict-bot-arm`) | `python -u scripts/pull_ib_executions.py --all-ib-accounts --days 2` |
| `ict-ib-gateway-reset` | live VM (`ict-bot-arm`) | `/usr/bin/docker restart ib-gateway` |
| `ict-ib-gateway-watchdog` | live VM (`ict-bot-arm`) | `python3 -u scripts/check_ib_gateway.py --probe-account ib_paper \` |
| `ict-insights-generator-strategies` | live VM (`ict-bot-arm`) | `scripts/ops/run_insights_strategies_cycle.sh` |
| `ict-insights-generator` | live VM (`ict-bot-arm`) | `scripts/ops/run_insights_cycle.sh` |
| `ict-liveness-watchdog` | live VM (`ict-bot-arm`) | `python3 -u scripts/check_heartbeat.py --interval 60 --grace 5 --auto-restart-after 3 --max-restarts 5 --coold…` |
| `ict-mes-ibkr-pull` | live VM (`ict-bot-arm`) | `bash scripts/ops/pull_mes_ibkr_history.sh` |
| `ict-ml-decision-shadow` | live VM (`ict-bot-arm`) | `python -u scripts/ops/ml_decision_shadow.py` |
| `ict-notify-failure@` | live VM (`ict-bot-arm`) | `python3 -u scripts/ops/notify_unit_failure.py %i` |
| `ict-ops-runner` | live VM (`ict-bot-arm`) | `python3 -u -B scripts/ops/ops_runner.py` |
| `ict-phone-capture-purge` | live VM (`ict-bot-arm`) | `bash scripts/ops/phone_capture_purge.sh` |
| `ict-prop-executor` | live VM (`ict-bot-arm`) | `bash scripts/ops/prop_executor_tick.sh` |
| `ict-prop-executor@` | live VM (`ict-bot-arm`) | `bash scripts/ops/prop_executor_tick.sh` |
| `ict-prop-feed` | live VM (`ict-bot-arm`) | `bash scripts/ops/prop_feed_tick.sh` |
| `ict-prop-feed@` | live VM (`ict-bot-arm`) | `bash scripts/ops/prop_feed_tick.sh` |
| `ict-research-results-gate` | live VM (`ict-bot-arm`) | `scripts/ops/run_research_results_gate.sh` |
| `ict-security-watch` | live VM (`ict-bot-arm`) | `python -u scripts/ops/security_watch.py` |
| `ict-shadow-log-rotate` | live VM (`ict-bot-arm`) | `python3 scripts/ops/rotate_shadow_log.py --gzip` |
| `ict-smoke-once` | live VM (`ict-bot-arm`) | `bash scripts/run_smoke_once.sh` |
| `ict-telegram-bot` | live VM (`ict-bot-arm`) | `python3 -u -B -m src.bot.telegram_query_bot` |
| `ict-trader-live` | live VM (`ict-bot-arm`) | `python3 -u -B -m src.main` |
| `ict-trainer-disk-alarm` | live VM (`ict-bot-arm`) | `python -u scripts/ops/trainer_disk_alarm.py` |
| `ict-trainer-git-sync` | live VM (`ict-bot-arm`) | `bash scripts/ops/trainer_git_sync.sh` |
| `ict-web-api-watchdog` | live VM (`ict-bot-arm`) | `python3 -u scripts/check_web_api.py --auto-restart --restart-after 2 --max-restarts 3 --cooldown-min 10` |
| `ict-web-api` | live VM (`ict-bot-arm`) | `python3 -m uvicorn src.web.api.main:app --host 127.0.0.1 --port 8001 --timeout-graceful-shutdown 5` |
| `ict-work-digest` | live VM (`ict-bot-arm`) | `python3 scripts/ops/work_digest_now.py` |
| `ict-work-report` | live VM (`ict-bot-arm`) | `python3 scripts/ops/work_report.py` |
| `ict-work-store-import` | live VM (`ict-bot-arm`) | `python3 scripts/ops/work_store_import.py --apply` |
| `ict-candle-refresh` | trainer VM (`ict-trainer-vm`) | `-python -u scripts/ops/extend_data_from_lake.py --data-dir data --lake datasets-out/market_raw --apply` |
| `ict-drift-retrain` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_drift_retrain.sh` |
| `ict-keeper-dispatch` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/keeper_dispatch.sh` |
| `ict-ltr-wake-dispatch` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/keeper_dispatch.sh` |
| `ict-notify-failure@` | trainer VM (`ict-trainer-vm`) | `python3 -u scripts/ops/notify_unit_failure.py %i` |
| `ict-offload-drain` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_offload_drain.sh` |
| `ict-orderflow-capture` | trainer VM (`ict-trainer-vm`) | `python -m scripts.ml.orderflow_capture \` |
| `ict-pm-snapshot` | trainer VM (`ict-trainer-vm`) | `python -u scripts/macro/pm_snapshot_collect.py` |
| `ict-promotion-readiness` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_promotion_readiness.sh` |
| `ict-trainer-catchup` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_training_cycle.sh` |
| `ict-trainer-forecast` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_forecast_producer.sh` |
| `ict-trainer-lifecycle` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_lifecycle_schedule.sh` |
| `ict-trainer-publish` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/publish_trainer_mirror.sh` |
| `ict-trainer` | trainer VM (`ict-trainer-vm`) | `bash scripts/ops/run_training_cycle.sh` |
| `jta-console-connector` | trainer VM (`ict-trainer-vm`) | `python -m src.console_connector.server` |
<!-- END GEN:where -->

## The flow

```mermaid
flowchart TD
  A["1 · Data in<br/>candles, feeds, ML features"] --> B["2 · Signal builders<br/>one per strategy leg"]
  B --> C["3 · Strategy legs and ML heads<br/>emit intents"]
  C --> D["4 · Intent layer<br/>multiplexer + regime router + election"]
  D --> E["5 · Per-account routing<br/>accounts.yaml rosters + the two execution gates"]
  E --> F["6 · RiskManager and sizing<br/>daily DD switch, exposure, slices"]
  F --> G["7 · Order package + bracket<br/>SL + predictive TP (TP doctrine)"]
  G --> H["8 · Venue execution<br/>Bybit · Alpaca · IB · OANDA · prop executors"]
  H --> I["9 · Live management<br/>order monitor, trailing, active management, live-trade-review desk"]
  I --> J["10 · Close and reconcile<br/>venue P&L, pnl_basis, mirrors"]
  J --> K["11 · Grading, evidence, research<br/>promotion ladder"]
  K -. "new evidence changes rosters and params" .-> C
  K -. "retrained and promoted models" .-> C
  J -. "the mirror's net-of-cost window demotes a leg to the demo floor" .-> E
```

## 1 · Data in

| TECHNICAL | TRADING |
|---|---|
| Connectors in `src/exchange/`: `bybit_connector.py`, `alpaca_connector.py`, `ib_connector.py`, `oanda_connector.py`. Helpers in `src/runtime/market_data.py` route each symbol to its source by `config/instruments.yaml`. Runs inside `ict-trader-live.service` on `ict-bot-arm`; IB bars come through `ict-ib-gateway`. Trainer-side candles: `deploy/trainer/ict-candle-refresh.service`. ML features for the entry heads: `src/runtime/ml_decision_features.py`, `src/runtime/ml_entry_eq_features.py`. Open interest: `src/runtime/oi_feed.py`. News: `src/news/news_pipeline.py`. | No decisions here, but data quality decides everything downstream. Rules that apply: off the trade path is not off the data path (a feature removed from trading keeps its data collection, `docs/reference/shadowed-features.yaml`); `accounts.yaml::symbols` is a data-pull list, never a gate. Track record: — (not a decision-maker). |

## 2 · Signal builders

| TECHNICAL | TRADING |
|---|---|
| `src/runtime/strategy_signal_builders.py` (one builder per strategy family, e.g. `turtle_soup_signal_builder`, `ict_scalp_signal_builder`). `src/runtime/pipeline.py::strategy_builders` maps legs to builders and `multiplexed_signal_builder` runs them each tick. Builders stamp regime, trend alignment and conviction inputs on the signal (`_stamp_regime`, `conviction_stamp`) and log shadow ML predictions (`_emit_shadow_preds`). Equity builders gate on `src/runtime/market_hours.py`. Runs in `ict-trader-live.service`. | A builder turns candles into a candidate setup for one leg: direction, entry, stop, target and the stamps the later stages read. A per-leg side filter can suppress one direction (`_resolve_side_filter`). Track record: per leg, in the generated table below. |

## 3 · Strategy legs and ML heads

| TECHNICAL | TRADING |
|---|---|
| Strategy modules in `src/units/strategies/`: `trend_donchian.py`, `htf_pullback_trend_2h.py`, `fvg_range_15m.py`, `turtle_soup.py`, `ict_scalp.py`, `squeeze_breakout_4h.py`, `fade_breakout_4h.py`, `e4_oi_shock_1h.py`, `hf_displacement_cont.py`, `hf_vwap_revert.py`, `vwap.py`, `macro_thesis/`, the ML legs `ml_entry.py`, `ml_entry_v2.py`, `ml_entry_eq.py`, the Claude desk `claude_desk.py`, and the pairs sleeve (`pairs_engine.py`, `pairs_executor.py`, its own gate `config/pairs.yaml`). Leg config and params: `config/strategies.yaml`. Served ML artifacts: `ml/served/` (the entry pointer is `ml/served/ENTRY_SERVED.json`, read by `src/runtime/ml_entry_served.py`; the model inventory and stages are `ml/served/SERVED_MODELS.yaml`). Models are trained on `ict-trainer-vm` (`ml/` package, `python -m ml ...`) and published to the repo. | **Rule legs**: trend (Donchian breakout), pullback in trend (2h/1d), fair-value-gap range, liquidity sweep reversal (turtle soup), ICT scalp, squeeze and fade breakouts, OI-shock, VWAP. Each trades the symbol its own evidence measured. **ML legs**: `ml_entry` (crypto entry classifier: a served model scores each candidate and trades above a threshold), `ml_entry_v2`, `ml_entry_eq` / `ml_entry_eq_struct` (equities). An ML leg trades the population its pooled test passed on. **Claude desk**: `claude_desk` (judgement-driven entries, paper). **Status** (testing / production / inactive) is derived from roster membership by `scripts/ops/strategy_status.py`, never declared. **Track record**: backtest and live per leg in the generated table; ML headline metrics with provenance in `ml/served/SERVED_MODELS.yaml`. |

<!-- BEGIN GEN:ml -->
**Served ML models** (source: `ml/served/SERVED_MODELS.yaml`; 10 models; the entry pointer `ml/served/ENTRY_SERVED.json` serves `ml_decision_entry_v1r20261122`). Headline metrics are the registry's own, with its provenance and population.

| Model | Stage | Headline metric | Value | n | Window | Verdict | Provenance | Source |
|---|---|---|---|---|---|---|---|---|
| `ml-decision-entry-v1r20261122` | advisory | promotion_grade_mean_net_r_per_trade | +0.1457 | 434 | 2026-11-08..2026-11-21 | pass | MEASURED | `comms/research/ml_entry_grade/45021344426/grade_evidence.json` |
| `ml-decision-entry-v1` | advisory | heldout_mean_net_r_per_trade | +0.0371 | 907 | 2025-10-01..2026-09-29 | pass | MEASURED | `comms/strategy_evidence/ml_entry.json` |
| `ml-decision-entry-v1r20261106` | advisory | promotion_grade_mean_net_r_per_trade | +0.0018 | 281 | 2026-10-23..2026-11-05 | pass | MEASURED | `comms/research/ml_entry_grade/42250040398/verdict_amended_2.json` |
| `ml-decision-entry-v1r20261115` | advisory | promotion_grade_mean_net_r_per_trade | +0.1692 | 366 | 2026-11-01..2026-11-14 | pass | MEASURED | `comms/research/ml_entry_grade/43710344172/grade_evidence.json` |
| `ml-decision-entry-v2` | advisory | w1_mean_net_r_per_trade | -0.1161 | 320 | W1 forward read | fail | MEASURED | `comms/research/RQ-20261101-b609-01/local-20261101T2000Z/result.json` |
| `ml-entry-eq-v1` | advisory | confirm_mean_net_r_per_trade | +0.0392 | 858 | 2025-07-15..2026-10-31 | pass | MEASURED | `research/results/RQ-20261105-e9a1-02/42143223941.jsonl` |
| `ml-entry-eq-struct-ens5-v1` | advisory | confirm_mean_net_r_per_trade | +0.4922 | 207 | 2025-07-15..2026-10-31 | pass | MEASURED | `comms/strategy_evidence/ml_entry_eq_struct.json` |
| `ml-entry-tp-revision-v1` | advisory | mean_delta_net_r_per_trade_vs_fixed_tp | +0.0008 | 907 | 2025-10-01..2026-09-30 | — | MEASURED | `comms/research/RQ-20261101-383f-01/evidence_extend_only_c692-06_population.json` |
| `overlay-td-v1` | advisory | noninferiority_verdict | — | 1830 | 2020-07-01..2026-10-15 | pass | MEASURED | `comms/research/RQ-20261029-5785-02/40869516819/verdict.json` |
| `exit-head-donchian-1h-v1` | advisory | oos_recovered_r_per_trade | -0.0141 | 1041 | 2022-10-29..2026-07-10 (3 folds) | fail | MEASURED | `research/results/RQ-20260927-002/36302273043.jsonl` |
<!-- END GEN:ml -->

## 4 · Intent layer: multiplexer, regime router, election

| TECHNICAL | TRADING |
|---|---|
| `src/runtime/intent_multiplexer.py::_collect_intents` gathers each leg's intent and skips a leg on symbols outside its `symbols:`. `src/runtime/intents.py::gate_intents` applies the regime router once per tick (`src/runtime/regime/policy.py`, `detector.py`, `vol_detector.py`, `ml_vol_verdict.py`; cells in `config/regime_policy.yaml`). `src/runtime/arbitration_fanout.py::plan_per_account_election` then has every account elect from its own candidates via `intents.elect_from_gated`; `src/runtime/pipeline.py::_dispatch_rounds` routes each account its winner. Slice accounts: `src/runtime/allocator_ev.py::intent_allocation_score` (over `src/runtime/conviction.py::compute_conviction`; weights `config/slice_allocation.yaml`). Runs in `ict-trader-live.service`. | **Regime router**: drops intents in (regime, strategy, direction) cells marked `off`; only cells that lose money and generalize should exist (skill `regime-selectivity`). **Decider**: one net position per symbol per account; today a static-priority election (highest priority wins; same direction takes the max size). **Slices** (`position_model: slices`, e.g. `bybit_1`): several legs share a symbol, each with its own slice and bracket; the risk budget is split by allocation score. Track record: regime cells carry their own walk-forward evidence (`scripts/research/regime_cell_walkforward.py`); election history in `src/runtime/election_track_record.py`. |

## 5 · Per-account routing and the two execution gates

| TECHNICAL | TRADING |
|---|---|
| `src/core/coordinator.py::Coordinator.multi_account_execute` fans an elected signal to every account whose roster carries the leg, with a symbol-to-exchange guard. Rosters and account `mode:` are in `config/accounts.yaml`; leg `execution:` is in `config/strategies.yaml`; both fold into one `effective_dry`. Served on `/api/bot/config`. | **The only two gates**: account `mode: live \| dry_run` (written only by the operator-gated `set-account-mode` action) and leg `execution: live \| shadow` (shadow logs packages, sends nothing). There is no third gate. **The books**: Stage 1 demo floor (`bybit_1`, `alpaca_paper`, `ib_paper`): every testing leg trades there. Stage 2 real money plus its mirror (`bybit_2` + `bybit_portfolio`, `alpaca_live` + `alpaca_portfolio`). Prop accounts (`account_class: prop`) clear a superset bar. An account configures strategies, never symbols. |

<!-- BEGIN GEN:accounts -->
**Accounts** (source: `config/accounts.yaml`; names only, no ids or balances; 14 accounts).

| Account | Class | Exchange | Mode (gate 1) | Position model | Daily DD switch | Legs on roster |
|---|---|---|---|---|---|---|
| `bybit_1` | paper | bybit | live | slices | disarmed | 29 |
| `bybit_2` | real_money | bybit | live | slices | armed | 5 |
| `bybit_portfolio` | paper | bybit | live | slices | armed | 5 |
| `ib_paper` | paper | interactive_brokers | live | — (default) | disarmed | 11 |
| `ib_live` | real_money | interactive_brokers | dry_run | — (default) | armed | 0 |
| `oanda_practice` | paper | oanda | dry_run | — (default) | disarmed | 0 |
| `alpaca_paper` | paper | alpaca | live | — (default) | disarmed | 18 |
| `alpaca_portfolio` | paper | alpaca | live | — (default) | armed | 4 |
| `alpaca_live` | real_money | alpaca | live | — (default) | armed | 4 |
| `alpaca_options_paper` | paper | alpaca | live | — (default) | disarmed | 3 |
| `breakout_1` | prop | breakout | dry_run | — (default) | disarmed | 0 |
| `breakout_2` | prop | breakout | live | — (default) | armed | 0 |
| `tradeify_1` | prop | breakout | live | — (default) | armed | 3 |
| `velotrade_1` | prop | breakout | live | — (default) | armed | 3 |
<!-- END GEN:accounts -->

## 6 · RiskManager and sizing

| TECHNICAL | TRADING |
|---|---|
| `src/units/accounts/risk.py::RiskManager.approve` (per trade) and `approve_amend` (for in-trade changes). Daily drawdown switch: `src/units/accounts/daily_dd_switch.py`, configured per account at `accounts.yaml::<acct>.risk.daily_dd_switch`. Prop rules: `src/units/accounts/prop_risk.py`, `src/prop/prop_risk_gate.py`, `src/prop/prop_sizing.py`. Counters: `src/runtime/risk_counters.py`. Slice admission: `src/runtime/positions.py::admit_slice`. Conviction and advisory sizing: `src/runtime/conviction_sizing.py`, `src/runtime/advisory_sizing.py`, news sizing `src/runtime/news_sizing.py`. Runs in `ict-trader-live.service`. | **Sizing**: per-account `risk_pct` of equity to the stop, capped by gross exposure (`GROSS_EXPOSURE_CAP`). **Daily DD switch**: the one sanctioned automatic off; when armed it blocks NEW entries after a day loss of 3% (non-prop) or 0.8 × the firm's daily limit (prop) and keeps open positions with their brackets; disarmed by default. <!-- population-ok: configured thresholds of the daily DD switch (accounts.yaml), not a measurement --> **No halting**: a refusal is per trade; the trader never flips its own mode. Track record: refusals are logged per trade (`runtime_logs/signal_audit.jsonl` on the live VM); — for P&L (not a P&L maker). |

## 7 · Order package and bracket (SL + predictive TP)

| TECHNICAL | TRADING |
|---|---|
| `src/runtime/orders.py::safe_place_order` validates size and prerequisites; `src/runtime/validation.py`. Bracket construction and calibration: `src/runtime/bracket_advisor.py`, `src/runtime/bracket_calibration.py`, `src/runtime/exit_plan.py`, `src/runtime/structure_levels.py`; TP venue cap `src/runtime/tp_venue_cap.py`; ML entry TP policy `src/runtime/ml_entry_tp_policy.py`. Packages land in `trade_journal.db` (order packages and trades). Compliance measurement: `scripts/ci/check_tp_doctrine.py`. | **TP doctrine**: every bracket carries a REAL predictive take-profit at entry, and the prediction is revised through the trade; a trailing exit does not exempt a leg (ARCHITECTURE-CANONICAL § "TP doctrine"). **Default exit**: a dynamic, structure-based SL and TP (§ "Active management"). Track record: compliance counts in the generated block (re-run the guard; never quote counts forward). |

## 8 · Venue execution

| TECHNICAL | TRADING |
|---|---|
| `src/units/accounts/execute.py::_submit_order` dispatches by exchange: Bybit (`pybit`, `src/runtime/bybit_ccxt.py`), Alpaca bracket orders (`src/units/accounts/alpaca_client.py`), IB native brackets (`src/units/accounts/ib_client.py`, via `ict-ib-gateway`), OANDA (`src/units/accounts/oanda_client.py`). Prop: `src/prop/prop_executor.py`, `src/prop/breakout_executor.py`, `src/prop/phone_executor.py`, driven by `ict-prop-executor.service`; one state machine per executor type (ARCHITECTURE-CANONICAL § "Prop ticket flow"). Accounts registry: `src/units/accounts/integrator.py`. | No discretion: an approved package is sent as built. Mechanics are what Stage 1 checks (1–2 clean trades). Track record: execution cost and slippage are measured after the fact (`src/runtime/execution_costs.py`, `src/runtime/trade_costs.py`); — here. |

## 9 · Live management

| TECHNICAL | TRADING |
|---|---|
| `src/runtime/order_monitor.py` (`run_monitor_tick`, `run_exit_evaluation_tick`) runs each strategy's monitor every tick inside `ict-trader-live.service`: partial closes, SL moves (`src/runtime/sl_mover.py`), trailing (`src/runtime/trail_vol.py`, `src/runtime/trail_decay.py`, `src/runtime/trail_cross.py`), TP revision (`src/runtime/tp_revision.py`), structure exits (`src/runtime/structure_exit_live.py`), regime-flip exits (`src/runtime/regime_flip_exit.py`), exit heads (`src/runtime/exit_head_apply.py`), protection re-assert (`src/runtime/protection_reassert.py`). Prop trails: `src/prop/prop_trail.py`. **Live-trade-review desk**: a reviewer (skill `.claude/skills/live-trade-review/SKILL.md`, priced by `scripts/research/live_review_outcomes.py`) writes one row per package to the `live-review/rows` branch and `comms/live_review/reviews.jsonl`; `src/runtime/live_review_rows_watch.py` (inside the trader) sees a new row and runs `scripts/ops/live_review_dispatch.py`, which hands over to `scripts/ops/live_review_apply.py`; each account decides through `RiskManager.approve_amend` and the venue is read back. Mandates: `config/mandates.yaml` (`MD-TRADE-DESK`). | **Strategy monitors** apply each leg's own exit rules (break-even, partials, trailing). **Active management**: any evidence-backed move of either bracket; each action class is advice-only until its own net-of-cost test passes (ARCHITECTURE-CANONICAL § "Active management"). **The desk**: decides the best trade action NOW for each open package (hold, close, partial, move TP, widen SL, resize), priced from the leg's own Stage-0 history; in-trade classes in `rows_lib.ADVICE_ONLY_ACTIONS` are logged, not sent. **Daily DD switch** (stage 6) blocks new entries only. Track record: desk rows and outcomes in `comms/live_review/reviews.jsonl`; exit-lever evidence per leg via skill `exit-refinement`; — as a single number. |

<!-- BEGIN GEN:mandates -->
**Granted mandates** (source: `config/mandates.yaml` `mandates:`; 23 granted; 1 proposed, not shown). A mandate decides what may be CHANGED without asking, never what runs.

| Mandate | Kind | Grants | Granted | Auto-land |
|---|---|---|---|---|
| `MD-OBSERVABILITY-IN-A-GATED-PATH` | — | land_without_asking | 2026-09-24 | — |
| `MD-DEPLOY-AN-APPROVED-MERGE` | — | deploy_and_verify | 2026-09-24 | — |
| `MD-DERISK-ONLY-ROSTER-CUT` | — | derisk_only | 2026-09-24 | — |
| `MD-STRIP-A-ZERO-MEASURED-LEVER` | — | strip_inert_lever | 2026-09-24 | — |
| `MD-PREFER-THE-VERIFIABLE-SIDE` | — | resolve_stale_branch_conflict | 2026-09-24 | — |
| `MD-PROMOTE-S0-S1` | — | add a leg to the Stage-1 soak book on a passing Stage-0 record | 2026-09-24 | — |
| `MD-PROMOTE-S1-S2` | — | add a leg to a REAL-MONEY roster on Stage-0 evidence plus Stage-1 cost fidelity | 2026-09-24 | — |
| `MD-DEMOTE-S2-S1` | — | demote a Stage-2 leg when the mirror goes net-negative net-of-cost | 2026-09-24 | yes |
| `MD-DEMOTE-S1-OFF` | — | drop a RETIRED Stage-1 leg whose realized cost diverges from its harness assumption (AMENDED 2026-10-27, demo-floor rule -- a leg that is n… | 2026-09-24 | — |
| `MD-KILL-QUESTION` | — | close a research question that failed its own pre-registered rule | 2026-09-24 | — |
| `MD-LAND-RESEARCH-RESULT` | — | land_without_asking | 2026-09-27 | — |
| `MD-PROP-JOURNAL-FROM-OPERATOR` | — | prop_journal_write | 2026-09-27 | — |
| `MD-PAPER-PROTECTIVE-REPAIR` | — | place_missing_protective_on_paper | 2026-09-27 | — |
| `MD-SOAK-EXIT-CELL-PATHB` | — | declare a passing stop-multiplier (atr_stop_mult) cell on a leg that sits ONLY on Stage-1 soak rosters | 2026-09-30 | — |
| `MD-S1-CUT-ON-STAGE0-FAIL` | — | remove a RETIRED Stage-1 leg from its Stage-1 paper roster when its Stage-0 evidence record fails (AMENDED 2026-10-27, demo-floor rule -- a… | 2026-10-04 | — |
| `MD-EXEC-DEV-TEST-TRADES` | — | open_and_close_exec_test_trades_on_prop_accounts | 2026-10-18 | — |
| `MD-LIVE-TIGHTEN-SL` | — | tighten the protective stop of an OPEN order package on every account that carries it | 2026-10-25 | — |
| `MD-TRADE-DESK` | — | every trade action of the Claude trading desk (tighten_sl, close, partial_close, move_tp, widen_sl, change_size, add_entry) on every accoun… | 2026-10-26 | — |
| `MD-DEMO-FLOOR-BUILD` | — | merge_and_deploy_demo_floor_tier2_3_changes_without_per_pr_popup | 2026-10-27 | — |
| `MD-LTR-ADA-AUTO` | ltr_auto_apply | the live reviewer's recommendation on order package pkg-465a5d7d27644027 (the ADA short) is applied automatically by the VM, every in-trade… | 2026-10-29 | — |
| `MD-LTR-XRP-PC-20261109` | ltr_auto_apply | the live reviewer's partial_close (size_fraction 0.5) on order package pkg-633f05fad1ee4c1d (trend_donchian_xrp_4h XRPUSDT short) is applie… | 2026-11-09 | — |
| `MD-LTR-PAPER-AUTO` | ltr_auto_apply | every in-trade live-review call (close, tighten, move TP and every other in-trade class) on a package carried by a Stage-1 demo-floor paper… | 2026-11-01 | — |
| `MD-LTR-PROP-AUTO` | ltr_auto_apply | every live-review close, partial close or stop-tighten call on a package carried by a live prop account (tradeify_1, velotrade_1; breakout_… | 2026-11-12 | — |

**Live trade review config** (`config/live_trade_review.yaml`): apply_mode `apply`, accounts `{}`.
<!-- END GEN:mandates -->

## 10 · Close and reconcile

| TECHNICAL | TRADING |
|---|---|
| `src/runtime/order_monitor.py::run_reconciliation_tick` (off-tick loop `src/runtime/reconcile_loop.py`) matches journal rows to the venue; `src/runtime/venue_pnl.py::match_venue_record` takes the venue's realized P&L and flags gaps; `pnl_basis` records which source a trade's P&L came from. Venue fills: `src/runtime/exchange_fills_puller.py`, `src/runtime/exchange_fills_alpaca.py`, `src/runtime/exchange_fills_ib.py`, run by `ict-exchange-fills-pull` (`scripts/ops/pull_bybit_transaction_log.py`), `ict-alpaca-fills-pull`, `ict-ib-executions-pull`; funding `ict-exchange-funding-pull`. Broker truth: `src/runtime/broker_truth.py`. Closed-flat check: `src/runtime/closed_flat_invariant.py`. Prop: `src/prop/prop_reconcile.py`. Store: `trade_journal.db` (`src/units/db/database.py`). Read on `/api/bot/performance`, `/api/bot/pnl*`. | **Venue P&L is the truth** for a closed trade; computed P&L is a fallback, labelled by provenance (`MEASURED` / `ESTIMATED` / `FABRICATED` / `UNVERIFIED`, never folded together). **Mirrors**: the real-money mirror (`bybit_portfolio`, `alpaca_portfolio`) takes the same legs as live; its net-of-cost window is the demotion signal. Track record: the journal trust state (divergent or unrecorded accounts) is printed in the generated block. |

## 11 · Grading, evidence and the research loop

| TECHNICAL | TRADING |
|---|---|
| Evidence records: `comms/strategy_evidence/<leg>.json` (Stage-0 backtest, net of the full cost stack, rule registered before the run). Research questions: `research/queue/` (skill `research-ops`). Grading: `comms/claude_strategy_scores.jsonl` (skill `performance-review`), follow-ups through skill `perf-followup`. Trainer lifecycle and promotion readiness: `deploy/trainer/ict-trainer-lifecycle.service`, `deploy/trainer/ict-promotion-readiness.service`. Status: `scripts/ops/strategy_status.py`. Builds: `docs/claude/work/checklist/`; follow-through: `docs/claude/work/pipeline/` (one record per file, via `scripts/ops/pipeline.py`). | **Promotion ladder** (OPERATING-PLAN § 2): Stage 0 backtest (edge decided offline, net of full cost) → real money; a demoted leg goes back to the demo floor and keeps trading there for data while it is iterated; retirement only by record (`enabled: false`). Prop legs clear a superset. A live or paper book never establishes edge. Track record: the generated table below. |

## Per-leg status and track record (generated)

<!-- BEGIN GEN:legs -->
**Population:** 62 legs in `config/strategies.yaml` — production 9, testing 50, inactive 3 (status DERIVED by `scripts/ops/strategy_status.py`).

**Read this table in two halves.** *Backtest* is the offline Stage-0 evidence record (the only thing that establishes edge; provenance `measured` when the record's `coverage_state` is measured). *Live* is the journal's realized R from `/api/bot/performance?window=all` (lifetime window, so it can include trades from before a leg's current status): it checks mechanics and cost, **never edge**. Live real money = the route's top-level real-money aggregate; live paper = its `paper` block. Live read-state: **read**; journal trust: known-divergent ['bybit_2'], unrecorded ['alpaca_live'].

| Leg | Status | Books | Exec (gate 2) | Backtest net R OOS (full cost) | n OOS | Folds + | Cost basis | Stage-0 verdict | Evidence as of | Live real money (R) | Live paper (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ada_pullback_2h` | production | bybit_2, bybit_portfolio | live | +27.09 `measured` | 67 | 4/4 | full | pass | [2026-11-06](../../comms/strategy_evidence/ada_pullback_2h.json) | n=21 · ΣR +0.47 · E[R] +0.02 · R basis: confirmed 7, unverified 9, contaminated 5 | n=54 · ΣR +11.38 · E[R] +0.21 · R basis: confirmed 13, unverified 30, contaminated 11 |
| `ml_entry` | production | alpaca_paper, bybit_2, bybit_portfolio, tradeify_1, velotrade_1 | live | +33.68 `measured` | 907 | 1/1 | full | pass | [2026-11-04](../../comms/strategy_evidence/ml_entry.json) | n=59 · ΣR -9.84 · E[R] -0.17 · R basis: confirmed 11, unverified 47, contaminated 1 | n=85 · ΣR -5.91 · E[R] -0.07 · R basis: confirmed 16, unverified 66, contaminated 3 |
| `ml_entry_eq_struct` | production | alpaca_live, alpaca_portfolio | live | +101.89 `measured` | 207 | — | full | pass | [2026-11-08](../../comms/strategy_evidence/ml_entry_eq_struct.json) | n=1 · ΣR -0.11 · E[R] -0.11 · R basis: unverified 1 | n=4 · ΣR +0.07 · E[R] +0.02 · R basis: unverified 4 |
| `slv_trend_1h` | production | alpaca_live, alpaca_options_paper, alpaca_portfolio | live | +54.52 `measured` | 92 | 3/4 | full | pass | [2026-11-13](../../comms/strategy_evidence/slv_trend_1h.json) | 0 trades | n=36 · ΣR +32.95 · E[R] +0.92 · R basis: confirmed 19, unverified 6, contaminated 11 |
| `tlt_pullback_1h` | production | alpaca_live, alpaca_portfolio | live | +8.17 `measured` | 75 | 3/4 | full | pass | [2026-11-14](../../comms/strategy_evidence/tlt_pullback_1h.json) | n=1 · ΣR +1.29 · E[R] +1.29 · R basis: contaminated 1 | n=15 · ΣR -7.16 · E[R] -0.48 · R basis: confirmed 9, unverified 1, contaminated 5 |
| `tqqq_trend_long_1d` | production | alpaca_live, alpaca_paper, alpaca_portfolio | live | +12.77 `measured` | 54 | 5/8 | full | pass | [2026-11-13](../../comms/strategy_evidence/tqqq_trend_long_1d.json) | 0 trades | n=1 · ΣR -1.00 · E[R] -1.00 · R basis: confirmed 1 |
| `trend_donchian_eth_4h` | production | bybit_2, bybit_portfolio, tradeify_1, velotrade_1 | live | +30.91 `measured` | 135 | 3/4 | full | pass | [2026-11-15](../../comms/strategy_evidence/trend_donchian_eth_4h.json) | n=19 · ΣR +4.66 · E[R] +0.24 · R basis: confirmed 6, unverified 10, contaminated 3 | n=37 · ΣR -6.02 · E[R] -0.16 · R basis: confirmed 10, unverified 19, contaminated 8 |
| `trend_donchian_sol_prop` | production | bybit_2, bybit_portfolio | live | +49.81 `measured` | 538 | 4/4 | full | pass | [2026-11-12](../../comms/strategy_evidence/trend_donchian_sol_prop.json) | n=6 · ΣR -4.58 · E[R] -0.76 · R basis: confirmed 1, unverified 5 | n=9 · ΣR -7.15 · E[R] -0.79 · R basis: confirmed 3, unverified 6 |
| `trend_donchian_xrp_4h` | production | bybit_2, bybit_portfolio | live | +3.48 `measured` | 46 | 3/4 | full | pass | [2026-11-06](../../comms/strategy_evidence/trend_donchian_xrp_4h.json) | n=10 · ΣR -0.54 · E[R] -0.05 · R basis: confirmed 6, unverified 3, contaminated 1 | n=13 · ΣR -0.79 · E[R] -0.06 · R basis: confirmed 6, unverified 6, contaminated 1 |
| `avax_pullback_2h` | testing | bybit_1 | live | -15.74 `measured` | 95 | 1/4 | full | fail | [2026-11-13](../../comms/strategy_evidence/avax_pullback_2h.json) | 0 trades | n=13 · ΣR -7.01 · E[R] -0.54 · R basis: confirmed 1, unverified 11, contaminated 1 |
| `claude_desk` | testing | alpaca_paper, bybit_1, ib_paper | live | — | — | — | — | — | — | 0 trades | n=14 · ΣR +7.10 · E[R] +0.51 · R basis: confirmed 4, unverified 9, contaminated 1 |
| `e4_oi_shock_1h` | testing | bybit_1 | live | — | — | — | — | — | — | 0 trades | n=48 · ΣR +8.84 · E[R] +0.18 · R basis: confirmed 18, unverified 30 |
| `eth_pullback_2h` | testing | bybit_1 | live | +1.39 `measured` | 83 | 3/4 | full | pass | [2026-11-13](../../comms/strategy_evidence/eth_pullback_2h.json) | n=19 · ΣR -2.47 · E[R] -0.13 · R basis: confirmed 3, unverified 15, contaminated 1 | n=39 · ΣR -2.85 · E[R] -0.07 · R basis: confirmed 4, unverified 31, contaminated 4 |
| `eth_pullback_prop_2h` | testing | bybit_1 | live | -6.57 `measured` | 81 | 2/4 | full | fail | [2026-11-13](../../comms/strategy_evidence/eth_pullback_prop_2h.json) | 0 trades | n=8 · ΣR +1.18 · E[R] +0.15 · R basis: confirmed 1, unverified 3, contaminated 4 |
| `fade_breakout_4h` | testing | bybit_1 | live | -14.28 `measured` | 28 | 0/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/fade_breakout_4h.json) | n=7 · ΣR -0.84 · E[R] -0.12 · R basis: confirmed 1, unverified 6 | n=6 · ΣR -2.47 · E[R] -0.41 · R basis: unverified 6 |
| `fvg_range_15m` | testing | bybit_1 | live | -9.41 `measured` | 18 | 0/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/fvg_range_15m.json) | 0 trades | n=1 · ΣR -0.01 · E[R] -0.01 · R basis: unverified 1 |
| `gdx_pullback_1d` | testing | alpaca_options_paper, alpaca_paper | live | +1.23 `measured` | 10 | 2/4 | full | pass | [2026-10-22](../../comms/strategy_evidence/gdx_pullback_1d.json) | 0 trades | n=4 · ΣR -1.68 · E[R] -0.42 · R basis: confirmed 2, unverified 1, contaminated 1 |
| `gld_pullback_1d` | testing | ib_paper | live | +10.51 `measured` | 8 | 4/4 | full | pass | [2026-11-05](../../comms/strategy_evidence/gld_pullback_1d.json) | 0 trades | n=3 · ΣR +1.95 · E[R] +0.65 · R basis: confirmed 1, unverified 1, contaminated 1 |
| `htf_pullback_trend_2h` | testing | bybit_1 | live | -23.37 `measured` | 105 | 0/4 | full | fail | [2026-11-13](../../comms/strategy_evidence/htf_pullback_trend_2h.json) | n=6 · ΣR -3.95 · E[R] -0.66 · R basis: confirmed 3, unverified 3 | n=27 · ΣR -26.07 · E[R] -0.97 · R basis: unverified 27 |
| `iaum_pullback_1d` | testing | alpaca_paper | live | +10.68 `measured` | 8 | 4/4 | full | pass | [2026-11-05](../../comms/strategy_evidence/iaum_pullback_1d.json) | n=1 · ΣR -1.47 · E[R] -1.47 · R basis: confirmed 1 | n=2 · ΣR +0.14 · E[R] +0.07 · R basis: unverified 1, contaminated 1 |
| `ict_scalp_5m` | testing | bybit_1 | live | -28.91 `measured` | 90 | 0/4 | full | fail | [2026-11-20](../../comms/strategy_evidence/ict_scalp_5m.json) | n=35 · ΣR +4.94 · E[R] +0.14 · R basis: confirmed 6, unverified 20, contaminated 9 | n=71 · ΣR -2.83 · E[R] -0.04 · R basis: confirmed 6, unverified 49, contaminated 16 |
| `ict_scalp_avax_5m` | testing | bybit_1 | live | -48.68 `measured` | 186 | 0/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/ict_scalp_avax_5m.json) | 0 trades | n=95 · ΣR -7.25 · E[R] -0.08 · R basis: confirmed 21, unverified 32, contaminated 42 |
| `ict_scalp_eth_15m` | testing | bybit_1 | live | -2.92 `measured` | 76 | 2/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/ict_scalp_eth_15m.json) | 0 trades | n=48 · ΣR +7.61 · E[R] +0.16 · R basis: confirmed 26, unverified 10, contaminated 12 |
| `ict_scalp_mgc_15m` | testing | ib_paper | live | — | — | — | — | — | [2026-09-22](../../comms/strategy_evidence/ict_scalp_mgc_15m.json) | 0 trades | n=22 · ΣR +8.24 · E[R] +0.37 · R basis: confirmed 15, contaminated 7 |
| `ict_scalp_sol_15m` | testing | bybit_1 | live | -12.50 `measured` | 87 | 1/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/ict_scalp_sol_15m.json) | 0 trades | n=54 · ΣR +12.69 · E[R] +0.23 · R basis: confirmed 9, unverified 30, contaminated 15 |
| `ict_scalp_sol_5m` | testing | bybit_1 | live | -16.64 `measured` | 116 | 1/4 | full | fail | [2026-11-19](../../comms/strategy_evidence/ict_scalp_sol_5m.json) | 0 trades | n=69 · ΣR +6.58 · E[R] +0.10 · R basis: confirmed 20, unverified 25, contaminated 24 |
| `ict_scalp_xrp_15m` | testing | bybit_1 | live | -2.81 `measured` | 74 | 2/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/ict_scalp_xrp_15m.json) | 0 trades | n=52 · ΣR -9.50 · E[R] -0.18 · R basis: confirmed 12, unverified 23, contaminated 17 |
| `ict_scalp_xrp_5m` | testing | bybit_1 | live | -32.88 `measured` | 163 | 0/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/ict_scalp_xrp_5m.json) | 0 trades | n=52 · ΣR -37.27 · E[R] -0.72 · R basis: confirmed 7, unverified 25, contaminated 20 |
| `ief_pullback_1d` | testing | alpaca_paper | live | +1.03 `measured` | 6 | 1/3 | full | pass | [2026-10-22](../../comms/strategy_evidence/ief_pullback_1d.json) | n=1 · ΣR -0.48 · E[R] -0.48 · R basis: confirmed 1 | n=4 · ΣR +5.90 · E[R] +1.48 · R basis: confirmed 2, contaminated 2 |
| `iwm_trend_long_1d` | testing | alpaca_paper, ib_paper | live | +2.11 `measured` | 8 | 2/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/iwm_trend_long_1d.json) | 0 trades | n=4 · ΣR -1.07 · E[R] -0.27 · R basis: confirmed 1, unverified 3 |
| `mes_trend_long_1d` | testing | ib_paper | live | -1.00 `measured` | 5 | 1/4 | full | fail | [2026-09-24](../../comms/strategy_evidence/mes_trend_long_1d.json) | 0 trades | n=4 · ΣR -1.16 · E[R] -0.29 · R basis: unverified 4 |
| `mgc_pullback_1d` | testing | ib_paper | live | +3.87 `measured` | 8 | 3/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/mgc_pullback_1d.json) | 0 trades | n=2 · ΣR +2.93 · E[R] +1.46 · R basis: confirmed 1, contaminated 1 |
| `mgc_trend_1h` | testing | ib_paper | live | +25.61 `measured` | 118 | 2/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/mgc_trend_1h.json) | 0 trades | n=6 · ΣR +5.57 · E[R] +0.93 · R basis: confirmed 1, unverified 2, contaminated 3 |
| `mhg_pullback_1d` | testing | ib_paper | live | +4.10 `measured` | 10 | 2/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/mhg_pullback_1d.json) | 0 trades | n=6 · ΣR -2.63 · E[R] -0.44 · R basis: confirmed 2, unverified 3, contaminated 1 |
| `ml_entry_eq` | testing | alpaca_paper | live | — | — | — | — | — | — | 0 trades | n=6 · ΣR -4.77 · E[R] -0.80 · R basis: unverified 6 |
| `ml_entry_v2` | testing | bybit_1 | live | — | — | — | — | — | — | 0 trades | n=24 · ΣR -8.59 · E[R] -0.36 · R basis: confirmed 3, unverified 18, contaminated 3 |
| `qld_trend_long_1d` | testing | alpaca_paper | live | +2.98 `measured` | 9 | 3/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/qld_trend_long_1d.json) | 0 trades | n=2 · ΣR -1.41 · E[R] -0.70 · R basis: confirmed 1, unverified 1 |
| `qqq_pullback_1h` | testing | alpaca_paper | live | +5.49 `measured` | 73 | 3/4 | full | pass | [2026-11-13](../../comms/strategy_evidence/qqq_pullback_1h.json) | 0 trades | n=24 · ΣR -19.46 · E[R] -0.81 · R basis: confirmed 13, unverified 7, contaminated 4 |
| `qqq_trend_long_1d` | testing | alpaca_paper, ib_paper | live | +5.30 `measured` | 8 | 2/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/qqq_trend_long_1d.json) | 0 trades | n=3 · ΣR -0.91 · E[R] -0.30 · R basis: confirmed 3 |
| `scha_trend_long_1d` | testing | alpaca_paper | live | +1.65 `measured` | 28 | 4/8 | full | pass | [2026-11-13](../../comms/strategy_evidence/scha_trend_long_1d.json) | 0 trades | n=2 · ΣR -2.00 · E[R] -1.00 · R basis: confirmed 2 |
| `slv_pullback_1d` | testing | alpaca_options_paper, alpaca_paper | live | +3.00 `measured` | 10 | 2/4 | full | pass | [2026-10-22](../../comms/strategy_evidence/slv_pullback_1d.json) | n=1 · ΣR -1.03 · E[R] -1.03 · R basis: confirmed 1 | n=4 · ΣR -4.21 · E[R] -1.05 · R basis: confirmed 4 |
| `sol_pullback_2h` | testing | bybit_1 | live | +3.19 `measured` | 34 | 2/4 | full | pass | [2026-11-13](../../comms/strategy_evidence/sol_pullback_2h.json) | 0 trades | n=15 · ΣR -2.61 · E[R] -0.17 · R basis: confirmed 3, unverified 9, contaminated 3 |
| `splg_trend_long_1d` | testing | alpaca_paper | live | — | — | — | — | — | [2026-09-24](../../comms/strategy_evidence/splg_trend_long_1d.json) | 0 trades | 0 trades |
| `spy_pullback_1h` | testing | alpaca_paper | live | -8.55 `measured` | 75 | 2/4 | full | fail | [2026-09-29](../../comms/strategy_evidence/spy_pullback_1h.json) | 0 trades | n=17 · ΣR -8.40 · E[R] -0.49 · R basis: confirmed 8, unverified 4, contaminated 5 |
| `spy_trend_long_1d` | testing | alpaca_paper, ib_paper | live | +2.38 `measured` | 11 | 3/4 | full | pass | [2026-09-24](../../comms/strategy_evidence/spy_trend_long_1d.json) | 0 trades | n=1 · ΣR -0.40 · E[R] -0.40 · R basis: unverified 1 |
| `squeeze_breakout_4h` | testing | bybit_1 | live | -2.81 `measured` | 14 | 1/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/squeeze_breakout_4h.json) | n=1 · ΣR -1.11 · E[R] -1.11 · R basis: unverified 1 | n=10 · ΣR -3.36 · E[R] -0.34 · R basis: confirmed 1, unverified 9 |
| `tlt_pullback_1d` | testing | alpaca_paper, ib_paper | live | -6.96 `measured` | 45 | 2/8 | full | fail | [2026-11-13](../../comms/strategy_evidence/tlt_pullback_1d.json) | 0 trades | n=10 · ΣR -1.05 · E[R] -0.11 · R basis: confirmed 4, unverified 2, contaminated 4 |
| `trend_donchian` | testing | bybit_1 | live | -16.23 `measured` | 71 | 1/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/trend_donchian.json) | n=15 · ΣR +7.64 · E[R] +0.51 · R basis: confirmed 5, unverified 9, contaminated 1 | n=30 · ΣR +23.29 · E[R] +0.78 · R basis: confirmed 4, unverified 24, contaminated 2 |
| `trend_donchian_1h` | testing | bybit_1 | live | -10.57 `measured` | 184 | 2/4 | full | fail | [2026-11-13](../../comms/strategy_evidence/trend_donchian_1h.json) | 0 trades | n=16 · ΣR +1.84 · E[R] +0.11 · R basis: confirmed 3, unverified 8, contaminated 5 |
| `trend_donchian_ada_4h` | testing | bybit_1 | live | -3.35 `measured` | 55 | 2/4 | full | fail | [2026-11-13](../../comms/strategy_evidence/trend_donchian_ada_4h.json) | 0 trades | n=28 · ΣR +10.41 · E[R] +0.37 · R basis: confirmed 6, unverified 22 |
| `trend_donchian_avax_4h` | testing | bybit_1 | live | -16.18 `measured` | 57 | 1/4 | full | fail | [2026-11-13](../../comms/strategy_evidence/trend_donchian_avax_4h.json) | 0 trades | n=31 · ΣR +4.60 · E[R] +0.15 · R basis: confirmed 6, unverified 23, contaminated 2 |
| `trend_donchian_eth` | testing | bybit_1 | live | +6.90 `measured` | 108 | 2/4 | full | pass | [2026-10-28](../../comms/strategy_evidence/trend_donchian_eth.json) | 0 trades | n=41 · ΣR -4.55 · E[R] -0.11 · R basis: confirmed 9, unverified 24, contaminated 8 |
| `trend_donchian_eth_prop` | testing | bybit_1 | live | +10.30 `measured` | 135 | 3/4 | full | pass | [2026-11-14](../../comms/strategy_evidence/trend_donchian_eth_prop.json) | 0 trades | n=16 · ΣR +7.19 · E[R] +0.45 · R basis: confirmed 1, unverified 8, contaminated 7 |
| `trend_donchian_sol` | testing | bybit_1 | live | -2.88 `measured` | 58 | 2/4 | full | fail | [2026-10-28](../../comms/strategy_evidence/trend_donchian_sol.json) | 0 trades | n=13 · ΣR -2.20 · E[R] -0.17 · R basis: confirmed 2, unverified 9, contaminated 2 |
| `trend_donchian_sol_4h` | testing | bybit_1, tradeify_1, velotrade_1 | live | +36.42 `measured` | 115 | 3/4 | full | pass | [2026-11-13](../../comms/strategy_evidence/trend_donchian_sol_4h.json) | 0 trades | n=24 · ΣR +7.81 · E[R] +0.33 · R basis: confirmed 5, unverified 16, contaminated 3 |
| `trend_donchian_xrp_adx25` | testing | bybit_1 | live | +9.72 `measured` | 46 | 3/4 | full | pass | [2026-10-28](../../comms/strategy_evidence/trend_donchian_xrp_adx25.json) | n=1 · ΣR -1.00 · E[R] -1.00 · R basis: unverified 1 | n=3 · ΣR -1.34 · E[R] -0.45 · R basis: unverified 2, contaminated 1 |
| `turtle_soup` | testing | bybit_1 | live | — | — | — | — | — | [2026-09-22](../../comms/strategy_evidence/turtle_soup.json) | 0 trades | n=3 · ΣR -3.37 · E[R] -1.12 · R basis: unverified 2, contaminated 1 |
| `uso_trend_1h` | testing | alpaca_paper | live | +18.94 `measured` | 58 | 4/4 | full | pass | [2026-11-13](../../comms/strategy_evidence/uso_trend_1h.json) | 0 trades | n=23 · ΣR +13.02 · E[R] +0.57 · R basis: confirmed 12, unverified 5, contaminated 6 |
| `xrp_pullback_2h` | testing | bybit_1 | live | +6.56 `measured` | 53 | 2/4 | full | pass | [2026-11-05](../../comms/strategy_evidence/xrp_pullback_2h.json) | n=20 · ΣR -12.10 · E[R] -0.60 · R basis: confirmed 6, unverified 13, contaminated 1 | n=40 · ΣR -5.69 · E[R] -0.14 · R basis: confirmed 9, unverified 30, contaminated 1 |
| `gld_pullback_1h` | inactive | — | live | +32.84 `measured` | 90 | 3/4 | full | pass | [2026-09-28](../../comms/strategy_evidence/gld_pullback_1h.json) | 0 trades | n=14 · ΣR -22.19 · E[R] -1.58 · R basis: confirmed 6, unverified 8 |
| `vwap` | inactive | — | shadow | — | — | — | — | — | — | n=318 · ΣR -145.85 · E[R] -0.46 · R basis: unverified 318 | n=29 · ΣR -32.95 · E[R] -1.14 · R basis: unverified 29 |
| `xauusd_trend_1h` | inactive | — | live | — | — | — | — | — | — | 0 trades | 0 trades |

**Active legs with NO evidence record** (4): `claude_desk`, `e4_oi_shock_1h`, `ml_entry_eq`, `ml_entry_v2`. A leg without a committed record has no Stage-0 evidence on file — it is not a pass.

**Evidence records naming no leg in `config/strategies.yaml`** (matched on the record's `strategy` field): `comms/strategy_evidence/e4_oi_shock.json` (`e4_oi_shock`). Each is a renamed leg (fix the record's `strategy` field) or a research record.

**TP doctrine compliance** (`scripts/ci/check_tp_doctrine.py`):

```
population: 85 routings / 59 distinct legs, every account in config/accounts.yaml
  real_money routings= 9  entry_tp FAIL= 1  tp_revision FAIL= 7  compliant= 2
  prop       routings= 6  entry_tp FAIL= 2  tp_revision FAIL= 2  compliant= 4
  mirror     routings= 9  entry_tp FAIL= 1  tp_revision FAIL= 7  compliant= 2
  paper      routings=61  entry_tp FAIL=27  tp_revision FAIL=57  compliant= 4
```
<!-- END GEN:legs -->

## Drift checks (generated)

<!-- BEGIN GEN:checks -->
Checked 114 module/config paths cited by the skeleton (63 of them are in the trader's import closure, `config/trader_import_closure.txt`); 59 rostered legs against 62 defined legs.

✅ No drift found: every cited path exists, every rostered leg is defined, every enabled leg is on a book.
<!-- END GEN:checks -->

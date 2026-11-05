# JTA console connector: tool names and response schemas

> **Doc status:** `unknown` · category `lookup` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Gates this adds or changes: **none.** The sign-in (Google OAuth, operator decision "Open 443 + Google OAuth (Recommended)") already
exists; this doc only says which tools sit behind it. Code: `src/console_connector/{server,data,tabs}.py`; tests:
`tests/console_connector/`. Row `UI-CONSOLE-TABS-DATA` (dispatch of 2026-11-05).

Every tool is read-only (`readOnlyHint: true`), cached once per TTL for all viewers, and returns the same envelope:

| field | meaning |
|---|---|
| `as_of` | ISO-8601 UTC, when the payload was built |
| `read_state` | `read` · `partial` (some sections could not be read) · `stale` · `could_not_look` · `auth_required` |
| `population` | what was scanned (row counts, windows, limits, truncation). **Render a null as "—", never 0** |
| `provenance` | `register` = git commit of the checkout; `source`; `measure` (MEASURED / ESTIMATED never folded) |
| `error` / `reason` | present whenever a read failed; a failed read is never an empty list |

A section inside `sections` repeats `read_state` + `population` for itself; the top-level state is `read` only if all are.

## Availability (CONSOLE_CONNECTOR_AUTH)

| tool | needs `CONSOLE_CONNECTOR_AUTH=google` | why |
|---|---|---|
| `hello`, `work_rows`, `inbox`, `work_items`, `workplan`, `ml_roadmap` | no | public repo registers only |
| `performance`, `system_health`, `data_query` | **yes** | P&L, journal rows, live-VM state |

Without `google` the three gated tools are **absent from `tools/list`** and a direct `tools/call` returns
`{as_of, read_state: "auth_required", tool, population: {rows_scanned: null}, reason}` without reading anything (not cached).
The value must be exactly `google`.

## Tools

### `workplan` `{limit?: 1..200 = 40}` (TTL 60 s)
`weekly_planning` (the WEEKLY-PLANNING row, slim), `overdue[]`, `due_this_week[]` (next 7 days), `priority[]` (rows with a
`priority_rank`, by rank), `state_counts{}`, `by_owner{}`, `by_lane{}` (live rows), `usage{read_state, latest_by_window{weekly,session,..},
capacity{state, weekly_pct, days_to_reset, lanes, ...}}` from `USAGE-READINGS.jsonl` + `spend_meter.capacity` (live_open is not fed, so the
reserve is the roster bound: `capacity.reserve_basis.exposure = "exposure_unknown"`). Row fields as `work_rows`: `id title state owner lane
tier due_by overdue age_hours blocked_on[] prs priority_rank roadmap note_tail`.

### `ml_roadmap` `{limit?: 1..200 = 60}` (TTL 120 s)
`sections.milestones.items[]` (`id goal name status week_priority target reviewed where next`; goal G4 or `L-ML*`),
`sections.plan_status.items[]` (`ml_plan_status.analyse`: `id track plan ref ref_state flags[]`), `sections.rows.items[]` (live
`ML-*`/`REGIME-*`/`EXIT-HEAD*`/`TP-PREDICT*`/`FUNDING-OI*` checklist rows: slim row + `next`).

### `performance` `{}` (TTL 300 s, sign-in)
* `sections.legs.books.{real_money,paper,paper_portfolio}`: `totals{7d,30d,all}` and `legs{<leg>:{7d,30d,all:{trades wins winRate totalPnl
  totalPnlMeasured totalPnlEstimated totalR expectancyR rTradeCount pnlCoverage pnlMeasuredCount pnlEstimatedCount}}}`. A window that
  failed is `null` (with `sections.legs.errors`), never zeros. Source `/api/bot/performance?window=`. Prop legs have no book of their
  own on that route.
* `sections.live_vs_backtest.rows[]`: `scripts/research/live_vs_backtest.py` output per (account, leg, realMoney|mirror): `verdict n p5 p50 p95
  live_r live_percentile backtest_n backtest_fidelity evidence_record ...`.
* `sections.ml_models.models[]`: `model_id deployment_bucket model_family status target_deployment_stage linked_strategies metrics{scalars}`
  and `shadow{stage count score_mean score_min score_max score_read_state first_seen last_seen soak_days}` from `/api/bot/ml/registry` +
  `/api/bot/shadow/stats`. Shadow scores are model outputs (ESTIMATED), not realized P&L.

### `system_health` `{}` (TTL 60 s, sign-in)
`sections`: `services`, `timers`, `version`, `tick_cost`, `status{heartbeat, vm_health, exit_loop_health}` (each `{read_state, value|error}`
from `/api/diag/*`), `restarts_today{count, causes[], unit, since_utc}` (trader journal lines since 00:00Z),
`vm_resources.vms.{trainer,live,gateway}{cpu memory disk}` (trainer = psutil here, live = diag status, **gateway = could_not_look**:
isolated, no read path), `lanes_and_spend{in_flight_lanes[], count, usage{...as workplan}}`. The diag token is `DIAG_READ_TOKEN` from
the connector host's environment, sent in **both** `X-Diag-Token` and `Authorization: Bearer` (same value) so it works before and after
#23273.

### `data_query` (TTL 30 s, sign-in)
Args: `table` (omit for the catalog), `account`, `leg`, `symbol`, `since` (inclusive), `until` (exclusive), `time_column`, `order`
(`asc|desc`, default `desc`), `limit` (<= 500, default 100), `offset`. **No free SQL**; every value is a bound parameter and every
identifier is checked against the live schema.
* Allowlist: the **same** `_TABLE_ALLOWLIST` and `_REDACTED_COLUMNS` as `db_explorer.py` (default-deny), plus a deny-by-exact-name pattern
  for credential-looking columns (`token secret password api_key ...`; `input_tokens`-style counts stay). Columns are projected explicitly.
* Filters map to the table's own columns (`account` -> `account_id`, `leg` -> `strategy_name`, `symbol`); a filter the table has no column
  for is **refused with an error**, never dropped. Default time column: `trades.closed_at`, `order_packages.created_at`,
  `signals.logged_at_utc`, `balance_snapshots.ts`.
* Response: `columns[]`, `rows[]`, `filters_applied{arg: column}`, `order`, `population{table db matched_total returned limit limit_max offset
  limit_state truncated}`; the catalog form returns `catalog[{table, db, columns}]` and `unavailable_dbs`.
* Databases are opened `mode=ro` and read from the connector host's own files, resolved by `src.utils.paths` (`TRADE_JOURNAL_DB`,
  `TRAINER_STORE_DB`). The live journal is not on the trainer; the trainer holds the `sync_trainer_data.sh` snapshot at
  `$DATA_DIR/trade_journal.db`, so the unit needs `TRADE_JOURNAL_DB` pointed at it. `provenance.db_file` and `provenance.db_file_age_s`
  say which file answered and how old it is. A missing file reports `could_not_look` for that database, never an empty table.

### `inbox` (changed)
Items in `decisions_checklist` and `asks_pipeline` gain `options: string[] | null`: the source `blocked_on` edge / row / pipeline item's
`options` (or `choices`) labels. Null when the source carries none (today none do), so render a dash.

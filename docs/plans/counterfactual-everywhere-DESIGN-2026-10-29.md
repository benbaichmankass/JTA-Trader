# Counterfactual everywhere — design (phase A)

> **Doc status:** `live` · category `plan` · last verified `2026-10-29` · lane `COUNTERFACTUAL-EVERYWHERE` (Tier 1, design only; nothing is built here)
> Operator, 2026-10-29 ~19:15Z, verbatim: *"it has to be part of how we test things, not just how we do a performance review. Like, it has to drive everything ... And we should get it run on as much data as we can."* The run uses **no Claude and no API credits**.

## Gates this adds or changes

**Gates: none by default.** Everything below is additive, reads only, and lands as data.

Two optional gates are named so the operator can see them. **Neither is in the build rows' scope. Each needs the operator's explicit permission before it ships** (canonical § "No new gates without the operator's permission").

| # | Gate (proposed, NOT adopted) | What it would block | Where | Why it is tempting | How to remove |
|---|---|---|---|---|---|
| G-A | CI refusal of a Stage-0 evidence record that carries no counterfactual arms | a backtest result reaching a promotion corpus | a new check beside `scripts/ci/` evidence guards | makes "graded on arms" mandatory | delete the check |
| G-B | A Gate-1 clause requiring a strategy's exit rule to beat `original_brackets` on arms | Stage-0 → Stage-1 move | OPERATING-PLAN § 2 | makes the arms a decision rule, not advice | remove the clause |

Not gates, and why: the arms are emitted **by default** in the Stage-0 wrapper (a flag `--no-cf` opts out; there is no default-off flag, so nothing is hidden). The hourly live job already exists. Read-only consumers (performance-review, LTR, desk) *use* a record when it exists and print "—" when it does not; none waits for one.

---

## 0. What exists today (verified 2026-10-29, `origin/main` `5571ecfec`)

* `scripts/research/counterfactual_grader.py`, `SCHEMA_VERSION = 2`, 724 lines. `grade_package(pkg, legs_in, bars, reviews, actions, equity, venue, horizon)` is **pure**: it takes a package, its closed legs and a **bar list**, and returns one record (arms: `actual`, `replayed_actual`, `original_brackets`, `alt_brackets` 4 SL × 5 TP = 20, `less_management`, `more_management`, `random_control` N=300; plus `post_exit` with horizon, `mfe_r`, `mae_r`, `tp_reach`, `wider_sl_arms`, `verdict`).
* Live input is wired only through `grade_live` → `fetch_candles` (`/api/bot/candles`, limit 1000, "1m ~16h, 5m ~3.5d, 15m ~10d") and `load_sources` (**latest 150 packages**, 2×1000 trade rows). `.github/workflows/counterfactual-grade-closed.yml` runs hourly `:17`, cap 20 per run, one self-landing PR.
* Output so far: **3** files in `comms/research/counterfactual_grades/` (2 records + `actions/`). **MEASURED, not extrapolated.**
* **Two structural facts that shape the whole design:**
  1. The pure core needs only *bars*. The live path's candle source cannot reach back beyond ~10 days, so a **bulk run over history cannot use `fetch_candles`**; it needs a historical bar source (§ 3.3).
  2. Backtest trade rows carry **no TP and no bars**. The arms that matter (`original_brackets`, `alt_brackets`, `more_management`, `random_control`, `post_exit`) need only `side, entry, sl, entry_time, exit_time` and a bar path, so they are computable. `actual` is the harness's own `net_r`.

---

## 1. Consumer contracts

Common record: the **per-trade record** of § 4 (backtest) and the existing package record (live). Every number carries provenance (`MEASURED | ESTIMATED | FABRICATED | UNVERIFIED`); `null` means "could not look", rendered "—", never 0.

### 1.1 Stage-0 strategy R&D
* **Inputs:** a harness run (`backtest_trend.py` and the per-strategy harnesses via `harness_stage0.py`), the leg's bar frame, its declared cost policy.
* **Outputs:** per trade, the § 4 record; per cell/leg, an aggregate block `cf_summary` in `summary.json`: for each arm family, mean net R, bootstrap CI (grouped by trade), fold-positive count, `p_random_ge_actual` pooled, and the post-exit verdict mix (`exit_saved_r` / `exited_early` / `neutral` / `null`).
* **Decision it changes:** whether a *strategy exit rule or bracket* is graded as better than the leg's `original_brackets` and than the best static alt-bracket — i.e. it replaces "does the rule beat hold on one path" with "does it beat hold, best-static and matched-random on the same path, net of the full cost stack". It sits *beside* the existing fold/Holm grade (`grade_arm`); it does not replace it. A rule is registered **before** the run (queue-unit `decision_rule`). Selection bias: the best-static arm is picked on train folds only (`intervention_controls.best_static`, `excludes_test_folds: true`).
* **Does not:** decide promotion by itself (Gate 1 is unchanged; G-B above is the only way arms would bind it).

### 1.2 ML training labels
Labels are computed from arms/`post_exit` **as of a decision time `t_d` ≤ exit**; features are as-of `t_d`.

| Head (programme doc names) | Label from | Why valid |
|---|---|---|
| Exit / in-trade policy (Q-TM1, Q-TM2, `exit-head-donchian-*`, `exit-policy-v1`) | per-bar *continuation value* = `net_r` of the hold arm (`original_brackets`) minus the action arm (`more_management` stop-at-BE/lock/ATR trail variants) from the state at `t_d`; the `post_exit.verdict` as the trade-level cross-check | arms are the counterfactual values the head is trying to predict; same cost stack as the money test |
| TP / remaining-move (Q-TM9, REMAINING-MOVE-HEAD) | `post_exit.tp_reach{reached, bars}` and `mfe_r` (competing risk: TP vs wider-SL survival) | direct target |
| Bracket advisor (BRACKET-ADVISOR-SHADOW) | `argmax` over `alt_brackets` net R, with the full table kept so a cost-sensitive loss can use all 20 cells | the whole row is the label, not just the winner |
| Take/skip (Q-SEL1) | `original_brackets.net_r` | entry quality at the leg's own bracket |
| Vol/regime heads | **none** — not trade-management labels; they join as *features* | per ML programme T5 |

**Leakage rules (binding on every consumer of these labels):**
1. `post_exit.*` (`mfe_r`, `mae_r`, `tp_reach`, `wider_sl_arms`, `verdict`) is **hindsight by construction**. It is a label only; it is never a feature, and it is never available to a live decision.
2. Every arm uses bars up to `exit + horizon` (`post_exit.horizon.seconds`). Time-ordered folds must **purge** train rows whose `[entry, exit + horizon]` overlaps a test row's window and embargo by the horizon. Trades on one leg overlap in bars: bootstrap and CV group by **trade and time block**, never by bar.
3. `random_control` and `best_static` are fitted on train folds only.
4. Rows from the 5× re-run duplication (§ 3.1) are de-duplicated on (strategy, symbol, entry_time, direction, sl) before any split, or the same path lands in train and test.
5. `resolved: false` arms are excluded from labels (the grader already refuses them in verdicts).

**Contract:** the label table is `comms/research/cf_labels/<corpus>/<shard>.parquet|jsonl` with `trade_key, t_entry, t_exit, horizon_end, label_name, value, resolved, provenance`; the bench (TM-BENCH) joins on `trade_key`. This doc does not retrain anything.

### 1.3 Desk and LTR pricing (folds in `LTR-COUNTERFACTUAL-PRICING`)
* **Inputs:** a live-review row (`comms/live_review/reviews.jsonl`: 152 rows, 10-25..29, `applied=false` on all 152; `outcomes.jsonl` 52 rows, all `hold/no_recommendation/flag_mechanics` with `cf_method: no_path_change` — from the row note, MEASURED 2026-10-29) and the open package's path so far.
* **Outputs:** per review row, a **priced counterfactual per option class** (tighten, BE, partial, tp_extend, close, hold) computed as the grader's `more_management` / `less_management` arms with the action applied at the review's timestamp (`actions/<pkg>.json` declared form), net of cost, with `delta_vs_replayed_actual`. Written to `outcomes.jsonl` with `cf_method: grader_arm` (not `no_path_change`).
* **Decision it changes:** the per-class **priced count** that graduation needs (n ≥ 20 per class, mandates ~1138) accrues from every review, independent of whether an action was applied. It also gives the reviewer a priced prior (the leg's own corpus arms) *before* it recommends.
* **Overlap checked:** `scripts/research/live_review_outcomes.py` already prices options against the Stage-0 corpus; the grader replaces the `no_path_change` fallback once a post-review path exists. Check `RM-AM-EXIT-ML-WIRING` first (row note) — this design reuses, not duplicates, whichever of the two prices the same arm.
* **Does not:** apply anything (advice-only classes stay advice-only).

### 1.4 AM graduation rule `RULE-AM-RISK-ADJUSTED-V1` (folds in `AM-REGRADE-BOOKSIM`)
* **Inputs:** per-account **$ books** from § 1.6 (`basis='book_usd_sim'`), one per arm; the baseline is `replayed_actual` / hold; the candidates are the five classes `tighten_sl, move_tp, partial_close, close, widen_sl`; controls are **causal** matched-random draws (`intervention_controls` B2 `mode='causal'`; the legacy draw is not allowed — row note PI-20261029-IFMPNGJK-0003).
* **Output:** `am_risk_adjusted.grade_risk_adjusted(books, basis='book_usd_sim')` → `graduation_eligible=True`, one verdict per class.
* **Decision it changes:** only a `book_usd_sim` verdict can graduate a class; the per-trade R screen stays a screen (`graduation_eligible=False`). One PR per class that passes, no popup, operator notified (grant 2026-10-29). Graduation remains **Tier 3** and unchanged: removing a class from `advice_only` and `rows_lib.ADVICE_ONLY_ACTIONS` together.
* **Prior:** per-trade R screen, `RQ-20261029-1f39-02`, n=473/465 pairs, no class passes. The re-grade is not expected to flip it; it is the measurement of record.

### 1.5 Weekly `/performance-review`
* **Inputs:** `comms/research/counterfactual_grades/*.json` for packages closed in the window.
* **Outputs (a fixed CHECK, one table):** per leg and window — graded n / closed n (the denominator), mean `delta_vs_replayed_actual` by family (original brackets, best alt bracket, less/more management), `p_random_ge_replayed_actual`, post-exit verdict mix, fidelity gap (`abs_gap_r`) with a stated tolerance, and `could_not_grade` reasons. Missing → "—".
* **Decision it changes:** which legs get a PERF-FOLLOWUP bracket/management research unit; the review's call is a queue row with a pre-registered check, as today. Reads only; produces no gate.

### 1.6 Book-level $ with the real sizer (folds in `BOOK-SIM-REAL-SIZER`)
* **Input:** the pooled arm book (§ 3 corpora) plus each account's roster from `config/accounts.yaml` (re-parse, never quote counts), `RiskManager.position_size`, caps, `execution_costs.resolve_cost_policy()`.
* **Measured gap (row note):** `scripts/backtest_system.py` simulates one netted book on one symbol and *mirrors* the sizer; `nbook_portfolio.py` is N books on one tick stream with the mirrored sizer; neither models `daily_dd_switch` or a multi-symbol roster (bybit_2: 5 legs, 4 symbols).
* **Design rule:** the book sim **imports** `RiskManager.position_size` instead of copying `_risk_qty`, and takes arm outcomes as per-trade `net_r` (arms are linear in size, so `$ = net_r × risk_usd`, grader docstring). Output per account and per book: net $, % of account, max drawdown, worst-5% (CVaR), written with provenance.
* **Does not model:** margin and lot rounding (stated bias). A discrepancy between the imported sizer and the venue's real fills is a reported residual, not hidden.

---

## 2. Decision-rule principle for every run below
Each queue unit carries `decision_rule.registered_before_run: true` (guard `check_research_queue_decision_rule.py`), `practice_precedent:` and, since each tests an intervention, `intervention_controls:` (hold_to_bracket, causal matched_random draws ≥100, best_static on train folds, `bootstrap_group: trade`). A unit states what it does not do. A FAIL closes the configuration, never the family.

---

## 3. The bulk run (no Claude, no API credits)

### 3.1 Corpora and measured n

All counts **MEASURED 2026-10-29** by reading every file matching `*trades*.jsonl*` under `comms/` and `research/` of `origin/main@5571ecfec`; probe verified against a positive (first row of a known file parsed with all keys).

| Corpus | Population | n |
|---|---|---|
| Backtest trade files | files | **3,521** (3,510 non-empty; 11 empty = real zero-trade samples) |
| | `comms/research/RQ-*/…` rows | 1,336,631 |
| | `comms/strategy_evidence/runs/…` rows (200 files, 32 run dirs) | 17,198 |
| | `comms/strategy_evidence/ltr_corpus/…` rows | 426 |
| | **total rows** | **1,354,255** (parse errors: 0) |
| | rows with entry, sl, direction, exit_time (replayable geometry) | **1,352,955** (99.90%) |
| | distinct (strategy, symbol, entry_time, direction) | **271,090** (5.0× duplication: re-runs of one leg with different exit configs) |
| | **distinct replay jobs** (… + sl) | **352,063** — the unit of work; arms other than `actual`/`replayed_actual` are independent of the exit rule |
| | symbols / strategy labels | 51 / 19; entry years 1998–2026, 98.5% from 2020–2026 |
| `research/results/` | `trades.jsonl` files | **0** (the directory holds `RQ-*` result records, not trade files; the brief's path is a name mismatch, so the glob above covered `comms/` + `research/`) |
| Exit-head paths corpus | trades, 6 legs, 50,926 bar-states | **2,627** (cited from `ML-PROGRAMME-2026-10-28` § H1, **not re-measured here**; phase B re-counts it) |
| Closed live + paper order packages | graded now | **3** records (MEASURED). Closed-package total and per-account split: **UNKNOWN here** — the VM is not read in this lane; phase B's first step is the `journal?table=order_packages` count, and the grader's `limit=150` window is a defect for a backfill (§ 3.3) |
| `trade_outcomes` | rows | 2,875 (programme doc, not re-measured) |

Populations overlap (the paths corpus and trade_outcomes are subsets of backtest/live rows). **Do not add them.** The unit of count in every report is "distinct replay jobs".

### 3.2 Compute plan
* **Per-job cost, MEASURED on this container:** `simulate()` = 0.047 ms (early exit) to 0.174 ms (400 bars, no exit); ~340 simulations per trade (20 alt + ≈10 management + 4 ATR + 300 random + post-exit wider-SL arms). **≈ 16–60 ms per trade** pure compute → 352,063 jobs ≈ **1.6–5.9 CPU-hours** for the core. Bar loading, JSON and `post_exit` overhead are not measured; budget **×3** → **≤ ~18 CPU-hours**, labelled ESTIMATED.
* **Where:** GitHub-hosted runners, matrix-sharded by `(corpus, symbol)`; each shard caps at 6 h (the job limit) and at 20k jobs; ≈ 20–40 shards. The trainer VM (`ict-trainer-vm`) is the fallback for shards that need resident data. Neither calls Claude.
* **Cost:** runner minutes. If the repo's minutes are included, the incremental cash cost is **$0**; if billed, 18 CPU-hours ≈ 1,080 min × the Linux rate — **compute it from the repo's plan before dispatch (UNKNOWN here)**. No Anthropic spend. Lane cost to build is the checklist ceilings in § 5.
* **Outputs:** `comms/research/cf_bulk/<run_id>/<corpus>/<shard>.jsonl.gz` (one § 4 record per replay job, gzip), `<run_id>/manifest.json` (counts: input, replayable, graded, `could_not_grade` by reason, hash of the input file list), `<run_id>/summary.json`. Estimated size **~0.3–1.0 GB uncompressed per 100k jobs (UNVERIFIED)**; the repo is not the place for that, so large shards land as **GitHub Actions artifacts / the trainer VM data dir** and only `manifest.json` + `summary.json` + the per-leg aggregates are committed. Decide the exact split in phase B after one shard's real size.
* **Idempotent and resumable:** a shard is keyed by input-file hash + `SCHEMA_VERSION`; re-running a finished shard is a no-op. A shard failure is a recorded state and a retry, never a halt (Prime Directive 7).

### 3.3 Price source for history (the blocker to resolve first)
* **Backtest corpora:** bars come from the same CSV the run used (`scripts/ops/fetch_backtest_candles.py`: `binance_vision` for `*USDT`, Yahoo/other for non-crypto). Replay on the leg's **own timeframe** (that is the resolution the original result was computed at) — arms are therefore directly comparable to the stored `net_r`. A finer 1m replay for crypto from Binance Vision monthly files is **phase D**, optional, and only to quantify the coarse-bar bias.
* **Live/paper backfill:** `fetch_candles` cannot reach back; use the same Binance Vision/Yahoo fetcher, keyed by symbol and `[t_entry, t_close + horizon]`. The `limit=150` package window in `load_sources` must become paged (`offset`) for the backfill. Coverage that cannot be priced is `could_not_grade: no_bars`, counted in the manifest, never dropped.
* Non-crypto intraday history is thin (Yahoo 1m ≈ 7 d); those jobs grade on daily/hourly bars with that stated in `path.resolution_by_tf`.

### 3.4 Queue units (each with a rule registered before the run)

| Unit (to mint with `scripts/research/next_rq_id.py --fetch`) | Question | Decision rule (registered before run) | Not |
|---|---|---|---|
| **CF-BULK-BT** | On all 352,063 distinct backtest replay jobs, does *any* family of arms beat `original_brackets` by ≥ +0.05 net R per trade in ≥ 4 of 6 time folds, with bootstrap-by-trade 95% CI excluding 0 and `p_random_ge_actual` ≤ 0.10, per leg with n ≥ 100? | per-leg PASS/FAIL/INDETERMINATE at that rule; Holm across legs; indeterminate when n < 100 | not a promotion case; not a parameter change |
| **CF-BULK-POSTEXIT** | Per leg, is the `exited_early` share of `post_exit.verdict` ≥ 0.40 (the exit rule leaves R on the table) or ≤ 0.15 (exits save R)? | the two thresholds above, n ≥ 100 resolved verdicts, unresolved excluded and reported | not an exit change |
| **CF-BULK-LIVE** | Over every closed live + paper package whose horizon has passed, is replayed-actual within a stated fidelity gap of the journal outcome (`abs_gap_r` ≤ 0.10 on ≥ 80% of graded) — i.e. is the engine good enough to price live decisions? | fidelity rule; failing legs flagged, their arms marked ESTIMATED | not a P&L claim |
| **CF-BULK-LABELS** | Do the arm-derived labels reproduce the exit-head paths corpus on the 2,627 overlapping trades (label agreement ≥ 95% on the hold-vs-trail sign)? | agreement ≥ 0.95 else the label definition is revised, not the corpus | trains nothing |
| **CF-BOOKSIM-REGRADE** (= `AM-REGRADE-BOOKSIM`) | Under `RULE-AM-RISK-ADJUSTED-V1` on `book_usd_sim`, which action classes pass? | the rule itself, causal controls | per class, one PR if pass |

Each is `compute: cpu_long` or `cpu_light`, goes through `dispatch_queue.py`, and lands a verdict record under `comms/research/<RQ>/…` by the existing collector.

---

## 4. Harness integration

### 4.1 Where the grader is called
* **Inside the harness, not the wrapper**, because only the harness has the bar frame and the trade list. In `scripts/backtest_trend.py`, the trade-emit block (the `json.dumps({... "net_r": round(t.r_multiple - cb["total_cost_r"], 4), "mfe_r": t.mfe_r, ...})` call, around line 1195–1215, inside the loop that writes `--emit-trades`) gets, per trade, `**cf_fields(t, df, cost_policy)`.
* New module `scripts/research/cf_harness.py` (pure) exports `cf_fields(trade, bars, cost_policy, horizon_cfg, n_random) -> dict`. It maps a harness `Trade` to the grader's `pkg/legs/bars` shape and calls `counterfactual_grader.grade_package` (lifted to be importable without the live fetch code; `grade_live` stays where it is). Bars are `df.loc[entry_time : exit_time + horizon]`.
* `harness_stage0.py` already runs the harness as a subprocess per cell (`run_cell` → `build_argv`) and reads `emit`/`jout`. It adds `--cf` to `extra` by default (opt-out `--no-cf`), and `summarize_arm` gains a `cf_summary` block (§ 1.1). **No change to `grade_arm`'s verdict logic.**
* The per-strategy harnesses other than `backtest_trend.py` (`backtest_squeeze`, `backtest_fade`, `backtest_ict_scalp`, `run_backtest_vwap`) call the same `cf_fields`; phase C does trend first, then the rest by the same hook (`rdm.classify(cfg)` families).
* **Deliberately not touched:** `scripts/backtest_orb.py` (fee only) and `src/backtest/backtester.py` (own cost dict, no funding) stay out of any promotion corpus (CLAUDE.md); the bulk run skips files whose cost fields are absent (`cost_funding_r` missing → `cf_cost: fee_only`, ESTIMATED, flagged).

### 4.2 Per-trade record (schema `cf_trade/1`)
The harness row is extended; existing keys are unchanged (so every current reader keeps working).

```json
{
  "...existing harness keys...": "strategy, symbol, entry_time, exit_time, direction, entry, sl, exit_reason, gross_r, net_r, net_r_fee_only, mfe_r, cost_*_r, ...",
  "cf": {
    "schema": "cf_trade/1",
    "grader_schema_version": 2,
    "trade_key": "sha1(strategy|symbol|entry_time|direction|sl)",
    "status": "graded | could_not_grade",
    "reason": "null | no_bars | geometry_missing | cost_fee_only | ...",
    "path": {"bars": 0, "timeframe": "2h", "first_bar": "...", "last_bar": "...", "horizon_end": "..."},
    "cost": {"basis": "full|fee_only", "provenance": "MEASURED|ESTIMATED"},
    "arms": {
      "replayed_actual_net_r": 0.0,
      "original_brackets": {"net_r": 0.0, "resolved": true, "exit_reason": "stop"},
      "alt_brackets": [{"sl_mult": 1.0, "tp_r": 3.0, "net_r": 0.0, "resolved": true}],
      "less_management": [], "more_management": [{"arm_id": "be_at_1r", "net_r": 0.0, "resolved": true}]
    },
    "random_control": {"n": 300, "class": "tighten", "mean_r": 0.0, "p10_r": 0.0, "p50_r": 0.0, "p90_r": 0.0, "p_random_ge_replayed_actual": 0.0, "mode": "causal"},
    "post_exit": {"horizon_seconds": 0, "horizon_source": "leg_max_hold|tf_default", "horizon_reached": true, "mfe_r": 0.0, "mae_r": 0.0, "tp_reach": {"reached": false, "bars": null, "seconds": null}, "wider_sl_arms": [], "verdict": {"verdict": "exit_saved_r|exited_early|neutral|null", "r_diff": 0.0, "resolved": true}},
    "fidelity": {"replayed_actual_net_r": 0.0, "actual_net_r": 0.0, "abs_gap_r": 0.0},
    "provenance": "MEASURED|ESTIMATED"
  }
}
```

Rules: `null` for anything not looked at; `abs_gap_r` is quoted against `net_r`; the arm list is the grader's `arms` list unchanged (a compact view for the bulk store, the full record for ≤ 20k-trade cells). One record = one trade; a package-level live record stays as is.

### 4.3 Required harness fixes before the bulk run is trustworthy
* **Random control must be causal** (B2 `mode='causal'`); the legacy draw used the trade's own remaining length. Grader `random_control` draws "uniformly in time and level between the live stop and the market" — phase B verifies it does not look at the exit time, and fixes it if it does (**filed as the first build row, not assumed**).
* **Fidelity first:** `replayed_actual` must agree with the harness `net_r` on a sample before any arm is believed (CF-BULK-LIVE and a backtest analogue, `abs_gap_r` on 1,000 random jobs).

---

## 5. Phased build — checklist rows

Rows only; created with `scripts/ops/checklist.py add`. Ranks are relative to the parent (rank 1) and follow the register's convention (lower = sooner). Models and ceilings follow the repo's table; all Tier 1 except the one noted.

| Row id | Phase | Rank | Tier | Model | Ceiling | Delivers | Blocked on |
|---|---|---|---|---|---|---|---|
| `CF-B0-ENGINE-LIFT` | B0 | 1 | 1 | sonnet | $6 | lift `grade_package`/`simulate` into an importable `cf_core` (no live fetch), historical bar source with paging for packages, causal `random_control` verified, fidelity check on 1,000 backtest jobs | — |
| `CF-B1-BULK-BACKTEST` | B1 | 1 | 1 | sonnet | $8 | shard workflow + `cf_bulk` runner, manifest/summary, idempotent shards; runs CF-BULK-BT and CF-BULK-POSTEXIT on the 352,063 jobs | CF-B0 |
| `CF-B2-BULK-LIVE` | B2 | 2 | 1 | sonnet | $6 | live+paper backfill (paged packages, historical bars), CF-BULK-LIVE and the closed-package count, grader fidelity report | CF-B0 |
| `CF-C1-HARNESS-HOOK` | C | 1 | 1 | sonnet | $8 | `cf_fields` in `backtest_trend.py`, `--cf` default-on in `harness_stage0.py`, `cf_summary` in `summarize_arm`, tests; other harnesses follow in `CF-C2` | CF-B0 |
| `CF-C2-HARNESS-REST` | C | 3 | 1 | sonnet | $8 | the same hook in the four other harnesses | CF-C1 |
| `CF-D1-LABELS` | D | 2 | 1 | sonnet | $8 | `cf_labels` table + leakage purge/embargo helper; CF-BULK-LABELS | CF-B1 |
| `CF-D2-LTR-PRICING` | D | 2 | 1 | sonnet | $8 | priced option arms into `outcomes.jsonl` (replaces `LTR-COUNTERFACTUAL-PRICING`; that row is closed as folded) | CF-B0, check `RM-AM-EXIT-ML-WIRING` |
| `CF-D3-BOOKSIM` | D | 2 | 1 | opus | $15 | `BOOK-SIM-REAL-SIZER` re-based on imported `RiskManager.position_size`, per-account $ books from arms | CF-B1 |
| `CF-D4-PERFREVIEW-TABLE` | D | 3 | 1 | sonnet | $4 | the § 1.5 CHECK in `scripts/research/` + a line in the performance-review skill | CF-B2 |
| `AM-REGRADE-BOOKSIM` (existing, **Tier 3**) | E | 3 | 3 | opus | $15 | retarget `blocked_on` to `CF-D3-BOOKSIM`; the regrade itself unchanged | CF-D3 |

Tier-3 decisions (graduation of any class; G-A/G-B above) are **not** in these rows' scope and need the operator.

---

## 6. What I did not verify
* The closed-package count and per-account split on the VM (not read in this lane).
* The runner billing plan and the real size of a bulk shard.
* Whether the grader's `random_control` draw is causal; the exit-head paths corpus count (quoted from the programme doc).
* The 5× duplication is inferred from distinct-key counts, not from reading each run's config.

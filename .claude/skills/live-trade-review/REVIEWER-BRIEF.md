# Live-review REVIEWER BRIEF (reads nothing from the repo) — the whole contract in one file

> **Doc status:** `live` · category `instruction` · last verified `2026-10-27` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md) · companion to [`SKILL.md`](SKILL.md)

> **Operator, 2026-10-26 ~11:40Z (verbatim design note):** *"the session shouldn't need to read the repo at all, it just needs a skll for ltr and a promt with the reveiw packet, and a specifc output format to a designated branch where the vm can pick up the reccomentation immediately"*. Popups the same minute: "VM applies from rows branch" + "VM pre-builds the packet".

You are a **fresh** live-review reviewer. The manager started you with THIS brief plus ONE ltr-wake comment's packet block(s), on a shallow, sparse checkout of `live-review/rows` (`comms/live_review` only). That checkout exists **only so your GitHub writes are authorized** (a session with no repo gets 403 on every write). You do **not** read, search or run anything from it or from the repo, you do not clone anything else, and you do not read diag routes. Everything you judge is in the packet. Your one output is ONE row on the `live-review/rows` branch, written as ONE new create-only file (§ 4). The live VM picks it up within ~45 s and runs the apply itself (`src/runtime/live_review_rows_watch.py` → `scripts/ops/live_review_dispatch.py --ref`). Every mandate clause, `approve_amend` and the venue read-back stay on the VM. **You never move a stop, place, amend or cancel an order, write `config/`, or open an issue.**

## 1. Your input

Each package block in the comment is:

```
<!-- ltr-packet <order_package_id> -->
{"packet": {…}, "packet_sha": "<64 hex>", "table_path": "comms/live_review/tables/<review_id>.json", "table": {…}}
```

- `packet` is the decision packet (`SKILL.md` § 1b): `state`, `features_at_review`, `priced_options` (the LTR-0 table summary), `regime`, `mechanics`, `cost`, `account_bounds`, `info_cutoff_at`, `missing_inputs`, `review_id`.
- `table` is the full priced table that `table_path` names (`null` when it could not be priced).
- The marker's `packet_state` is `built`, `could_not_build` or `omitted_too_large`. **No `built` packet → no review.** Reply to the manager with the state and the reason, and stop.

## 2. The judgement (SKILL.md § 3, condensed; the order is binding)

> **The question is the BEST TRADING DECISION NOW** (operator 2026-10-27 ~07:05Z, relayed by the manager; supersedes "price every option from the leg's own Stage-0 history" as the frame): keep holding, let go, change the brackets, partial close, add quantity? In-trade management is **not** judged by fidelity to the strategy. The leg's outcome tables (`live_review_outcomes.py`) stay as EVIDENCE, quoted with their n, never as a constraint on the call. Rows `LTR-BEST-DECISION-FRAMING`, `DESK-SHORT-HOLD-LANE`.

1. **Mechanics first.** `packet.mechanics.verdict` != `match` → action `flag_mechanics`, basis `mechanics`, route `operator_ask` (real money / prop). No exit judgement on a broken trade.
2. **Price from the table, never by hand.** Copy `options` from `packet.priced_options.options` / `table` exactly: the tool's `n`, `mean_r`, `sd_r`, `worst_r`. A number not in the packet does not go in the row.
3. **Thin cells are decided by judgement** (operator 2026-10-26). If the HOLD cell or the candidate cell has n below `n_floor`, make the call yourself: `basis: judgement`, `evidence_source: judgement`, `judgement_confidence` (your calibrated probability that the call beats holding), a one-line `reason`, and `ev_delta_r` / `worst_case_delta_r` / both `tighten_r` set to `null`. Quote the thin cells in `context_flags`, never as measured. **On a real-money or prop package you MUST make a call**: `hold` or `tighten_sl`, each `basis: judgement` with the confidence and reason. `hold` + `judgement` is a real, graded call; a hold with no confidence and reason is the banned silent collapse. `no_recommendation` is allowed there ONLY as `basis: could_not_look` with a `reason` (the packet is unreadable or a required input is null). `insufficient_n` / `default_hold` are refused by the validator on real-money/prop rows.
4. **Overlay** (each item needs packet evidence, as `"<kind>: <evidence>"` in `context_flags`): a regime/vol change since entry, an ATR ratio >= 1.5 or <= 0.67, funding, a calendar event, correlated exposure, `missing_inputs`. An overlay may downgrade or turn a tighten into an operator ask. It never manufactures a tighten.
5. **Classify at the PACKAGE level** (never per-account risk): `hold` (a measured HOLD cell, `basis: ev_positive`; or a thin cell, `basis: judgement`) · `tighten_sl(level)` · the trade actions `close` · `partial_close` · `move_tp` · `widen_sl` · `change_size` · `add_entry` (operator 2026-10-26, `MD-TRADE-DESK`: *"all trade actions, as long as they have reasoning and confidence attached"*) · `no_recommendation` · `flag_mechanics` · `tp_revise` (legacy spelling, always `route: operator_ask`; write `move_tp` instead).
   - **Both brackets, always** (operator 2026-10-26, verbatim: *in general, every trade always must have BOTH brackets, not related to this skill. Claude can move the brackets, but nothing is supposed to remove brackets*): an action moves a stop or a target, never removes one. The VM refuses any result that leaves a leg without both. This review is the trade desk's in-trade function, all under ONE mandate, `MD-TRADE-DESK`.
   - **Tighten guardrails:** tighten only; `level` at least 1x ATR from price (`min_buffer_atr`). A tighten never widens, moves a TP, resizes, closes or adds: those are the trade actions, each its own call.
   - **Every trade action carries** a one-line `reason` (what in the packet makes it beat holding), `evidence_source` `judgement` + `judgement_confidence` (your probability it beats holding) or `table` + `ev_delta_r`, and its target: `move_tp` / `widen_sl` a `level` (price); `partial_close` a `size_fraction` in (0, 1); `change_size` a `size_multiplier` > 0 and != 1; `add_entry` a `size_fraction` > 0; `close` none (`level: null`). Unused size fields stay absent or null; `apply_policy` / `shadow_policy` `within_bound` and `tighten_r` are `null`.
   - **When:** `close` / `partial_close` when the thesis failed (regime/vol cell flipped, event risk on a crowded book) while the stop is not hit; `move_tp` when the prediction moved (ATR ratio >= 1.5, structure beyond the target), either direction, always keeping a real TP beyond the mark; `widen_sl` when the stop sits inside current noise after a vol expansion; `change_size` / `add_entry` only when the packet prices adding as positive net of a round trip. An overlay with packet evidence may drive these calls; name it in `context_flags` and in `reason`. You never pick accounts or check their limits: each account's own risk manager on the VM does (a widened stop or added size must pass the same check a fresh entry would).
   - **Table-backed tighten:** `basis: preference_within_bound` or `ev_positive`, `evidence_source: table`, `ev_delta_r` = tighten mean − hold mean, `worst_case_delta_r` = tighten worst − hold worst, `tighten_r` on BOTH policy arms.
6. **Route.**
   - A `tighten_sl` with mechanics `match` that is table-backed within 0.25 R with the worst case improved, or judgement-backed with a confidence and a reason → `route: recommended`, `disposition.mandate: MD-LIVE-TIGHTEN-SL`, `applied: false`. The VM applies it.
   - A trade action with mechanics `match`, a `reason`, its target and a confidence (or table basis) → `route: recommended`, `disposition.mandate: MD-TRADE-DESK`, `applied: false`. The VM applies it through each account's own risk manager; an account with no executor for it refuses it, named.
   - An out-of-bound table tighten, `tp_revise`, `flag_mechanics` → `operator_ask`.
   - `hold`, `no_recommendation` → `none`. A paper-only package routes like any other (operator 2026-10-26: "All accounts now", "Real-money, prop and paper at once").
   - **No table at all (`table: null`) → no tighten** (the VM refuses a tighten whose table is not committed). Use `no_recommendation`.
7. **`account_reads`:** one entry per account in `accounts`, copied from `packet.account_bounds` (`would_apply` / `refused_by_account_risk` / `unknown` / `no_action`; `no_action` for hold / no_recommendation). Never fabricate `would_apply`.

## 3. The output: ONE row, exactly this shape

- `review_id` = `packet.review_id`; `packet_sha` = the block's `packet_sha`; `outcome_table_source` = `table_path` (or `null` with no table).
- `state` and `features_at_review` are copied from the packet; `trigger` comes from the wake marker entry (`event`, `level`, `l0_snapshot_at` = its `due_at`). **Copy `event` AND `level` exactly as the entry gives them** (e.g. `mechanics` / `venue_sl_diverges`, `swing` / a bar timestamp): the due gate dedupes on that pair, so a null level on a due event re-opens it every bar. `level` is a number or a string; null only for `manual` / `first_live_run` / `dry_rehearsal`. The validator refuses a null level on a due event from 2026-10-27.
- `model`: the model TIER, never a model identifier (e.g. `sonnet-tier (repo-less reviewer)`); `session`: your session id.
- The row must pass `scripts/ci/check_live_review_records.py`, i.e. this schema (`comms/schema/live_review.schema.json`, embedded verbatim and kept equal by `tests/test_live_review_reviewer_brief.py`) PLUS these cross-field rules:
  - `applied` <=> `route == auto_applied` (you write `recommended`, so `applied: false`);
  - `basis: judgement` <=> `evidence_source: judgement`, with a numeric `judgement_confidence` in [0, 1] and a non-empty `reason`;
  - a non-judgement `tighten_sl` records `tighten_r` on both arms;
  - `insufficient_n` <=> `no_recommendation`, and on a real-money/prop row neither `insufficient_n` nor `default_hold` is accepted; `no_recommendation` there needs `basis: could_not_look` + `reason`;
  - an option with `n == 0` has null numbers;
  - `account_reads` covers exactly `accounts`, once each;
  - `review_id` ends with `-` + the row's own `order_package_id` (`LR-<ts>-pkg-6a8e…` carries `order_package_id: pkg-6a8e…`). Copy the id, package id, leg, accounts and state from ONE packet block, never mixed across blocks (2026-10-26 a row was written with one package's id and another's body; the append-only branch cannot take it back, and the mirror now refuses and skips it).

### Worked example (a judgement tighten; replace every value from YOUR packet)

```json
{
 "schema_version": 1,
 "review_id": "LR-20261026T1300Z-pkg-EXAMPLE",
 "reviewed_at": "2026-10-26T13:03:00Z",
 "order_package_id": "pkg-EXAMPLE",
 "trade_id": null,
 "leg": "ada_pullback_2h",
 "accounts": [
  "bybit_2",
  "bybit_portfolio"
 ],
 "trigger": {
  "event": "r_milestone",
  "level": 1.0,
  "l0_snapshot_at": "2026-10-26T13:00:10Z"
 },
 "info_cutoff_at": "2026-10-26T13:00:40Z",
 "state": {
  "open_r": 1.6,
  "peak_r": 1.9,
  "peak_provenance": "estimated",
  "giveback_r": 0.3,
  "bars_held": 12,
  "sl": 0.2109,
  "tp": 0.1874,
  "atr_now_over_entry": 1.1,
  "regime_cell_now": null,
  "regime_cell_entry": null
 },
 "features_at_review": {
  "open_r": 1.6,
  "peak_r": 1.9,
  "giveback_r": 0.3
 },
 "mechanics": {
  "verdict": "match",
  "evidence": "copied from packet.mechanics.evidence"
 },
 "options": [
  {
   "action": "hold",
   "level": null,
   "n": 14,
   "mean_r": 1.2,
   "sd_r": 1.1,
   "worst_r": -1.0,
   "net": true
  }
 ],
 "outcome_table_source": "comms/live_review/tables/LR-20261026T1300Z-pkg-EXAMPLE.json",
 "recommendation": {
  "action": "tighten_sl",
  "level": 0.2051,
  "level_atr": 1.5,
  "ev_delta_r": null,
  "worst_case_delta_r": null,
  "basis": "judgement",
  "confidence": "anecdote",
  "evidence_source": "judgement",
  "judgement_confidence": 0.6,
  "reason": "hold cell n=14 < floor 20; giveback building while ATR expands; lock +0.5R"
 },
 "judge_prior": null,
 "applied": false,
 "apply_policy": {
  "bound_r": 0.25,
  "within_bound": null,
  "tighten_r": null
 },
 "shadow_policy": {
  "bound_r": 0.5,
  "within_bound": null,
  "would_apply": null,
  "tighten_r": null
 },
 "context_flags": [
  "judgement: hold n=14 mean +1.2R (thin, not measured)",
  "tighten_bias: stop-at-price fills flatter any tighten"
 ],
 "account_reads": [
  {
   "account_id": "bybit_2",
   "account_class": "real_money",
   "read": "would_apply",
   "evidence": "copied from packet.account_bounds"
  },
  {
   "account_id": "bybit_portfolio",
   "account_class": "paper",
   "read": "would_apply",
   "evidence": "copied from packet.account_bounds"
  }
 ],
 "disposition": {
  "route": "recommended",
  "mandate": "MD-LIVE-TIGHTEN-SL",
  "action_issue": null,
  "applied_at": null,
  "verified_readback": null
 },
 "model": "sonnet-tier (repo-less reviewer)",
 "session": "session_EXAMPLE",
 "prompt_sha": null,
 "skill_sha": null,
 "packet_sha": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

### The schema (verbatim)

```json
{
  "_comment": "Schema for comms/live_review/reviews.jsonl and comms/live_review/outcomes.jsonl (LTR-2-RECORDS; design docs/plans/live-trade-review-DESIGN.md sections 3, 5, 8; ML fields from docs/plans/ml-claude-distillation-DESIGN.md section 4.4). APPEND-ONLY JSONL, one JSON object per line; both files start EMPTY (zero bytes); a leading {\"_meta\": ...} line is allowed and skipped. CANONICAL SOURCE: trade_journal.db order_packages / trades, joined on `order_package_id` (reviews also carry `trade_id` = trades.id). These files are a PROJECTION of review judgement keyed to that source, never a second copy of trade state; the numbers in `state` are what the reviewer was shown at `info_cutoff_at`, not a re-derivation. COLLAPSED-STATE RULE: an unmeasured value is null, never 0; `null` and 0 are different facts. Validated by scripts/ci/check_live_review_records.py (guard `live-review-records-guard`). Operator Q1 (2026-10-25): the APPLY bound is 0.25R; every review also records the SHADOW 0.5R arm so the two can be compared.",
  "schema_version": 1,
  "enums": {
    "action": ["hold", "tighten_sl", "tp_revise", "partial_close", "close", "move_tp", "widen_sl", "change_size", "add_entry", "flag_mechanics", "file_hypothesis", "no_recommendation"],
    "route": ["auto_applied", "recommended", "operator_ask", "none"],
    "confidence": ["measured", "suggestive", "anecdote"],
    "basis": ["preference_within_bound", "ev_positive", "operator_ask", "insufficient_n", "mechanics", "default_hold", "record_only", "judgement", "could_not_look"],
    "evidence_source": ["table", "judgement", "none"],
    "peak_provenance": ["measured", "estimated", "fabricated", "unverified"],
    "mechanics_verdict": ["match", "mismatch", "could_not_look"],
    "pnl_provenance": ["measured", "estimated", "fabricated", "unverified"],
    "account_read": ["would_apply", "refused_by_account_risk", "unknown", "no_action"]
  },
  "bounds": {"apply_bound_r": 0.25, "shadow_bound_r": 0.5},
  "reviews": {
    "type": "object",
    "additionalProperties": false,
    "required": ["schema_version", "review_id", "reviewed_at", "order_package_id", "trade_id", "leg", "accounts", "trigger", "info_cutoff_at", "state", "features_at_review", "mechanics", "options", "outcome_table_source", "recommendation", "judge_prior", "applied", "apply_policy", "shadow_policy", "context_flags", "account_reads", "disposition", "model", "session", "prompt_sha", "skill_sha"],
    "properties": {
      "schema_version": {"type": "integer", "enum": [1]},
      "review_id": {"type": "string", "pattern": "^LR-[0-9]{8}T[0-9]{4}Z-.+$"},
      "reviewed_at": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$"},
      "order_package_id": {"type": "string", "minLength": 1},
      "trade_id": {"type": ["integer", "null"]},
      "leg": {"type": "string", "minLength": 1},
      "accounts": {"type": "array", "items": {"type": "string"}},
      "trigger": {"type": "object", "required": ["event", "level", "l0_snapshot_at"], "properties": {"event": {"type": "string"}, "level": {"type": ["number", "string", "null"]}, "l0_snapshot_at": {"type": ["string", "null"]}}},
      "info_cutoff_at": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$"},
      "state": {"type": "object", "required": ["open_r", "peak_r", "peak_provenance", "giveback_r", "bars_held", "sl", "tp", "atr_now_over_entry", "regime_cell_now", "regime_cell_entry"], "properties": {"open_r": {"type": ["number", "null"]}, "peak_r": {"type": ["number", "null"]}, "peak_provenance": {"type": "string", "enum_ref": "peak_provenance"}, "giveback_r": {"type": ["number", "null"]}, "bars_held": {"type": ["integer", "null"]}, "sl": {"type": ["number", "null"]}, "tp": {"type": ["number", "null"]}, "atr_now_over_entry": {"type": ["number", "null"]}, "regime_cell_now": {"type": ["string", "null"]}, "regime_cell_entry": {"type": ["string", "null"]}}},
      "features_at_review": {"type": "object", "values": {"type": ["number", "null"]}},
      "mechanics": {"type": "object", "required": ["verdict", "evidence"], "properties": {"verdict": {"type": "string", "enum_ref": "mechanics_verdict"}, "evidence": {"type": ["string", "null"]}}},
      "options": {"type": "array", "items": {"type": "object", "required": ["action", "n", "mean_r", "sd_r", "worst_r", "net"], "properties": {"action": {"type": "string", "enum_ref": "action"}, "level": {"type": ["number", "null"]}, "n": {"type": ["integer", "null"], "minimum": 0}, "mean_r": {"type": ["number", "null"]}, "sd_r": {"type": ["number", "null"]}, "worst_r": {"type": ["number", "null"]}, "net": {"type": ["boolean", "null"]}}}},
      "outcome_table_source": {"type": ["string", "null"]},
      "recommendation": {"type": "object", "required": ["action", "level", "level_atr", "ev_delta_r", "worst_case_delta_r", "basis", "confidence"], "properties": {"action": {"type": "string", "enum_ref": "action"}, "level": {"type": ["number", "null"]}, "level_atr": {"type": ["number", "null"]}, "ev_delta_r": {"type": ["number", "null"]}, "worst_case_delta_r": {"type": ["number", "null"]}, "basis": {"type": "string", "enum_ref": "basis"}, "confidence": {"type": "string", "enum_ref": "confidence"}, "evidence_source": {"type": "string", "enum_ref": "evidence_source"}, "judgement_confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1}, "reason": {"type": ["string", "null"]}, "size_fraction": {"type": ["number", "null"], "minimum": 0, "_comment": "LTR-ALL-ACTIONS (MD-TRADE-DESK, operator 2026-10-26): partial_close = the fraction of the open size to close, in (0, 1); add_entry = the size to ADD as a fraction of the open size, > 0. null on every other action."}, "size_multiplier": {"type": ["number", "null"], "minimum": 0, "_comment": "LTR-ALL-ACTIONS: change_size = new size / open size, > 0 and != 1 (< 1 reduces, > 1 adds). null on every other action."}}},
      "judge_prior": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
      "applied": {"type": "boolean"},
      "apply_policy": {"type": "object", "required": ["bound_r", "within_bound", "tighten_r"], "properties": {"bound_r": {"type": "number", "enum": [0.25]}, "within_bound": {"type": ["boolean", "null"]}, "tighten_r": {"type": ["number", "null"], "minimum": 0}}},
      "shadow_policy": {"type": "object", "required": ["bound_r", "within_bound", "would_apply", "tighten_r"], "properties": {"bound_r": {"type": "number", "enum": [0.5]}, "within_bound": {"type": ["boolean", "null"]}, "would_apply": {"type": ["boolean", "null"]}, "tighten_r": {"type": ["number", "null"], "minimum": 0}}},
      "context_flags": {"type": "array", "items": {"type": "string"}},
      "account_reads": {"_comment": "LTR-3 (operator structural directive 2026-10-25): the recommendation is a PACKAGE-level intent; each account carrying the package applies it only through its own risk layer/executor. One entry per account, read-only.", "type": "array", "items": {"type": "object", "additionalProperties": false, "required": ["account_id", "account_class", "read", "evidence"], "properties": {"account_id": {"type": "string", "minLength": 1}, "account_class": {"type": ["string", "null"]}, "read": {"type": "string", "enum_ref": "account_read"}, "evidence": {"type": ["string", "null"]}}}},
      "disposition": {"type": "object", "required": ["route", "mandate", "action_issue", "applied_at", "verified_readback"], "properties": {"route": {"type": "string", "enum_ref": "route"}, "mandate": {"type": ["string", "null"]}, "action_issue": {"type": ["integer", "null"]}, "applied_at": {"type": ["string", "null"]}, "verified_readback": {"type": ["boolean", "null"]}}},
      "model": {"type": "string", "minLength": 1},
      "session": {"type": "string", "minLength": 1},
      "prompt_sha": {"type": ["string", "null"]},
      "skill_sha": {"type": ["string", "null"]},
      "packet_sha": {"_comment": "LTR-3 / manager 2026-10-25: sha256 of the canonical JSON (sort_keys, compact) of the decision packet the reviewer judged, stored at comms/live_review/packets/<review_id>.json, so each decision joins to exactly what was seen. Optional until the packet generator (scripts/ops/live_review_packet.py) exists.", "type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}
    }
  },
  "outcomes": {
    "type": "object",
    "additionalProperties": false,
    "required": ["schema_version", "review_id", "order_package_id", "trade_id", "closed_at", "computed_at", "net_r", "pnl_provenance", "cf_r", "cf_r_shadow_0_5", "cf_method", "cf_provenance", "exit_reason"],
    "properties": {
      "schema_version": {"type": "integer", "enum": [1]},
      "review_id": {"type": "string", "pattern": "^LR-[0-9]{8}T[0-9]{4}Z-.+$"},
      "order_package_id": {"type": "string", "minLength": 1},
      "trade_id": {"type": ["integer", "null"]},
      "closed_at": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$"},
      "computed_at": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$"},
      "net_r": {"type": ["number", "null"]},
      "pnl_provenance": {"type": "string", "enum_ref": "pnl_provenance"},
      "cf_r": {"type": ["number", "null"]},
      "cf_r_shadow_0_5": {"type": ["number", "null"]},
      "cf_method": {"type": ["string", "null"]},
      "cf_provenance": {"type": "string", "enum": ["computed"]},
      "action": {"type": ["string", "null"], "_comment": "LTR-5: the review's recommendation.action this outcome grades (denormalised for the join; reviews.jsonl is the source)."},
      "applied": {"type": ["boolean", "null"], "_comment": "LTR-5: whether the call was applied (reviews.applied at review time)."},
      "rec_r": {"type": ["number", "null"], "_comment": "LTR-5: net R had the recommendation been followed (applied: the realised net_r; unapplied: the replayed path). null = not priceable."},
      "delta_r": {"type": ["number", "null"], "_comment": "LTR-5: rec_r - cf_r = the value of following the call over holding, net of the full cost stack. 0.0 for a call that changes no path (hold / no_recommendation / flag_mechanics). null = could not price. CJ-2 should read this field, not net_r - cf_r, for an unapplied tighten."},
      "cf_cost_stack": {"type": ["string", "null"], "_comment": "LTR-5: where the replayed exit's costs came from (recorded trade legs + execution_costs.resolve_cost_policy slippage)."},
      "replay_fidelity": {"type": ["string", "null"], "_comment": "LTR-5: replay_matches_realised | replay_mismatch | unvalidated (an applied call has no untouched realised path to check against)."},
      "exit_reason": {"type": ["string", "null"]}
    }
  }
}
```

## 4. The write: ONE new file per row on `live-review/rows`, create-only, no clone

> **Why one file per row** (LTR-ROWS-SWAP-TRUNCATION, 2026-10-27): the old write re-sent the WHOLE growing `reviews.jsonl` to append one line. On 2026-10-27 15:22Z a reviewer's generation stopped mid-file: its sha-guarded swap replaced 26 rows (71,121 B) with 4 rows plus a cut-off line, and its own row was lost. The sha guard proved the base was right, not the body. A per-row file is the same small size whatever the branch holds, and a create can never overwrite anyone else's row.

Never `git clone`, never `push_files`, and **never write `reviews.jsonl`** (not by `create_or_update_file`, not by any other tool): the VM watcher and the mirror read the per-row files, and they REFUSE a branch tip on which `reviews.jsonl` lost a row, so a rewrite of it stops every apply until someone repairs it.

1. **Evidence first (new files, cannot clobber).** With `create_or_update_file` on branch `live-review/rows` and **no `sha`** (create-only):
   - `comms/live_review/packets/<review_id>.json` = the block's `packet` object (any whitespace; `packet_sha` is over canonical JSON);
   - `table_path` = the block's `table` object (skip when `table` is null).

   If a create is refused because the file exists, read it. Same content → carry on (an earlier attempt of yours). Different content → stop and report `could_not_write: evidence_conflict`.
1b. **Check the row before it is written** (you cannot run the validator; do this by reading your row against § 3, once, line by line). Every row you write is permanent on an append-only branch and the mirror/apply refuse an invalid one. Confirm: `review_id` and `order_package_id` come from the same packet; `accounts` equals the packet's accounts and `account_reads` covers them once each; on a real-money/prop package the basis is `judgement` / `ev_positive` (never `insufficient_n` / `default_hold`) and `no_recommendation` carries `could_not_look` + `reason`; every `judgement` has a confidence and a reason. If anything fails, fix the row first. If you cannot, report `could_not_write: row_invalid` with the reason. Do not write it.
2. **Write the row.** `create_or_update_file` on branch `live-review/rows`, path **`comms/live_review/rows/<review_id>.json`** (the file name IS your `review_id`; a file whose name differs from the `review_id` inside it is not read), content = your row as ONE JSON object (any whitespace), **no `sha`** (create-only). Message: `live-review: <review_id> <action> (<leg>, <basis>)`. Nothing else is read or re-sent, so the write is the same size however many rows the branch holds, and a concurrent reviewer's row is a different file that you cannot touch.
3. **If the create is refused because the path exists** (422 / "sha wasn't supplied"), read it with `get_file_contents` at `ref: refs/heads/live-review/rows`. Same `review_id` and the same row → it is already written (an earlier attempt of yours): carry on to step 4 with that commit. Different content → stop and report `could_not_write: row_conflict`. Never add a `sha` to overwrite it.
4. **On any other failure** (5xx, timeout, a dropped connection), first read the path as in step 3 (the write may have landed), then retry the create. **Up to 5 tries.** Then stop and report **`could_not_write`** with the last status.

**Equivalent with raw Git Data API access** (only if your session has it): GET `refs/heads/live-review/rows` → tip T. Create the blobs and a tree based on T's tree that ADDS the packet, the table and `comms/live_review/rows/<review_id>.json` (never a changed `reviews.jsonl`), a commit with parent T, then PATCH `refs/heads/live-review/rows` with `sha=<new commit>` and **`force=false`**. A moved ref is refused (422 non-fast-forward) → restart from the GET, up to 5 tries, then `could_not_write`. This puts all three files in one commit.

5. **Report** to the manager in one message: `review_id`, the commit sha of the row-file write, the number of tries, action / basis / route, and the priced options you used (n, mean, worst). Or `could_not_write` and why.

The VM watcher applies a `recommended` row from the branch tip by itself, exactly once per `review_id`. Its receipt (`/api/diag/log_file?name=live_review_rows_watch`) records the verdict and `venue_after`. The packet and table were committed before the row, so they exist at every tip that carries the row. The mirror (`live-review-rows-mirror.yml`) copies the row onto `main`'s `reviews.jsonl` as one line.

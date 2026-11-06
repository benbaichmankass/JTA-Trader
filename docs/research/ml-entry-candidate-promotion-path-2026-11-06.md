# ML entry: candidate → served artifact — trace and proposed path (2026-11-06)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · HELD for the manager/operator (Tier 2 serving path, Tier 3 model replacement) · rows `ML-ENTRY-RETRAIN-CADENCE`, `ML-ENTRY-LIVE-MONITOR`

**Gates this adds or changes:** none new. This automates the evidence rule that already governs a real-money model change (a committed record, a named harness, stated n, net of the full cost stack, a rule registered before the run, `holdout_lock` deflation). It does not add a switch; it reads the same evidence a human would. Landing it is still the operator's call.

## 1. Trace: is there a path from `candidate_model.json` to the served model?

**No.** Verified in the repo at `396ee6050`:

- The trader loads exactly one file: `ARTIFACT = ml/served/ml_decision_entry_v1/model.json` (`src/units/strategies/ml_entry.py:34`), cached by mtime (`load_model`, line 42). `bybit_2` and `bybit_portfolio` both roster `ml_entry` (`config/accounts.yaml`), which resolves to `config/strategies.yaml::ml_entry.model: ml-decision-entry-v1`.
- `scripts/research/ml_entry_retrain.py` writes only `out/candidate_model.json` and `out/freshness.json`. The workflow (`ml-entry-retrain.yml`, `contents: read`) uploads `out/` as a 90-day Actions artifact. Nothing reads that artifact back, nothing writes `ml/served/`, nothing grades the candidate.
- So today the weekly retrain produces a fresher model that **can never be served**; the served model's `data_through` keeps ageing (409.9 d at 15:45Z, limit 22 d) and the monitor's freshness line will stay `stale` forever. That is the gap.
- The only way a new artifact reaches the trader is a commit to `ml/served/...` on `main` followed by deploy (git-sync + the combined trader restart). The mtime cache means a replaced file is picked up without code changes.

Two schema facts that matter for any swap (checked, not assumed): the candidate's `booster_txt` has the same `{long, short}` keys the loader reads; the candidate's `model_id` is `ml-decision-entry-v1-cand-<run_date>`, which differs from the served `ml-decision-entry-v1`, and `ml_entry` copies `meta.model_id` into package meta (`ml_entry.py:180`), so a swap must set the id deliberately (see § 3).

## 2. The smallest path

One new script `scripts/research/ml_entry_candidate_grade.py` and one added workflow step. Nothing else changes; the trader code is untouched.

**Grade.** Each weekly run grades the **previous** week's candidate `C(T-7)` (not today's, which has no data after its own train end):

1. Window = `[C(T-7).train_end_exclusive, T-1]`, about 15 days. This is strictly after the candidate's training data, so it is clean by construction (`holdout_lock.check_window_disjoint`). A same-day candidate cannot be graded: its clean window is about 8 days, which is under the registered `N_FLOOR = 300` (the c692-01 pooled rate of roughly 31 taken decisions per day gives about 250 in 8 days, about 465 in 15 days; **an estimate from the c692-01 n=11,240, not measured on this window**).
2. Score the candidate **and the served artifact on the same rows** with the registered policy (`ml_decision_entry.policy`, tau 0.1 carried, one position per symbol, 2/3 ATR / 24 h) and the full cost stack (`label_symbol` net R: 11 bps fee, 3 bps slippage, funding; the per-symbol re-cost from `universe_costed` where its inputs exist). Claim the read first with `holdout_lock.claim_read(model_id, start, end, unit, reader)` so the deflated bar applies (family ENTRY).
3. Verdict by the **existing** `ml_decision_entry.verdict` (n ≥ 300, symbols ≥ 10, `point_ok` at the deflated bar), plus one registered non-inferiority line: candidate mean net R per decision ≥ the served artifact's on the same window. **Both** must hold.

**Act.**

- **PASS:** the workflow opens a **draft PR** that replaces `ml/served/ml_decision_entry_v1/model.json` with the graded candidate (id set to `ml-decision-entry-v1`, `candidate: false`, evidence and the ledger row cited in `evidence` / `provenance`, `tau` unchanged), plus a landing hold. It never merges. Merge is the manager's, with the operator's recorded decision, unless a mandate in `config/mandates.yaml` already covers it (a session may propose one; only the operator grants it).
- **FAIL / INDETERMINATE:** nothing is written. The old artifact keeps serving. One flag is raised (the existing `claude-run-failure-alert` path plus the monitor's freshness ping), stating the window, n, both means and the bar.
- No halting and no retry loop: the next Sunday tries again.

**Permissions.** The workflow needs `contents: write` + `pull-requests: write` for the PASS branch only (a draft PR from a bot branch). That is the Tier-2 change.

## 3. Open items to settle before building (not assumed)

1. **Candidate id/version.** Overwrite `ml_decision_entry_v1` in place (one file, the loader unchanged) or version it as `v1.1` (needs a loader/config change). Recommended: overwrite in place; git history is the version record and rollback is a revert.
2. **Cost stack parity.** Confirm the gate reuses the same cost stack as the c692 evidence so the candidate and served are compared on one stack; the served-vs-candidate comparison is paired, so a stack error affects both equally, but the absolute bar does not.
3. **Prior evidence on the served model is weak.** `strategies.yaml` records ml_entry as an operator-kept baseline (DSR 0.839 < 0.95 at N=1; frozen v1 failed some later reads). A candidate passing "mean ≥ 0 at the deflated bar and ≥ served" is a low bar. That is deliberate (it is the registered rule, not a new one), but the operator should know a PASS is not proof of edge.
4. **The first real fetch has not been proven from a sandbox.** See the run result on the row.

## 4. Evidence the gate would use

Window dates, n, n_symbols, mean net R and se for candidate and served (same rows), the deflated bar and `n_tries` from the ledger, exit-reason mix, ex-max-symbol mean, and by-month, all of which `ml_decision_entry.summarize` already emits. The `holdout_reads.jsonl` row is the committed record.

## 5. Not built

This PR is the proposal only. No script, workflow permission or `ml/served` file changes are in it.

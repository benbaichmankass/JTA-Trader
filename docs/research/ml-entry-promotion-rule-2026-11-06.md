# RULE-ENTRY-PROMOTE-20261106: when a retrained ENTRY candidate may replace the served artifact

> **Doc status:** `proposal` · category `research` · REGISTERED 2026-11-06, BEFORE the first grading run (this file's commit precedes every commit that contains grader code or an evidence record; `git log` is the proof) · rows `ML-ENTRY-RETRAIN-CADENCE`, `ML-ENTRY-LIVE-MONITOR` · decisions by Manager Session 2026-11-06a (conventional defaults)

**Gates this adds or changes:** none new. This writes down, as a rule fixed before the run, the bar a real-money ENTRY artifact change already has to clear (the c692-01 registered rule, the `holdout_lock` deflation, the full cost stack). It decides what may be CHANGED, not what RUNS, and it is landed as a held PR; nothing swaps without a human merge.

## The rule

A candidate is the artifact the registered recipe (`scripts/research/ml_decision_entry.py`, c692-01: same 20 features, `LGB_PARAMS`, tau carried from the served artifact, SL 2 / TP 3 ATR, 24 h horizon) produces when refit **as of** a date S, with training rows purged and embargoed exactly as `ml_decision_entry.purge_train` does (rows before S minus 7 days minus 25 h). It is graded on the window `[S, run_date - 1]`, which starts after its training data by construction.

Both the candidate and the served artifact are scored on the SAME rows, with the registered policy (`ml_decision_entry.policy`: best side if predicted net R > tau, one open position per symbol until its exit bar), with net R from `ml_decision_entry.label_symbol`: the full cost stack (taker fee 11.0 bps round trip, slippage 3.0 bps, funding 1.0 bps per 8 h window crossed, via `src/runtime/execution_costs`). The fee-only harnesses (`scripts/backtest_orb.py`, `src/backtest/backtester.py`) are excluded from this corpus.

The candidate PASSES only if **all** hold on that window:

1. **Registered held-out rule (c692-01).** n taken decisions >= 300 on >= 10 distinct symbols, AND mean net R per taken decision clears the `holdout_lock` point bar for the N-th read of the ENTRY family on an overlapping window: mean >= `point_t_min(N)` x its standard error (N = 1 is mean >= 0). The read is CLAIMED in the ledger BEFORE any window outcome is scored, which sets N.
2. **Not worse than the served model.** Candidate mean net R per taken decision >= the served artifact's on the same window.

Otherwise:

- n or symbols under the floor: verdict `insufficient_n`. The served model is kept and one flag is raised.
- either test fails: verdict `fail`. The served model is kept and one flag is raised.
- A PASS opens a DRAFT PR that adds a NEW versioned artifact directory and repoints the one served-model pointer. The old directory stays for a one-line revert. Nothing merges itself.

The served model's own weak evidence (DSR 0.839 < 0.95 at N=1) is NOT a reason to lower this bar.

## What this rule does not say, on purpose

- **It does not require "CI lower bound > 0".** The registered c692-01 rule (`research/queue/RQ-20261101-c692-01.yaml`, `decision_rule.rule`) is "PASS IF held-out mean net R per decision >= 0 (point estimate, the operator bar)", and `ml_decision_entry.verdict` implements it that way; the bootstrap CI is "reported, not gating". The grader REPORTS the deflated CI lower bound beside the verdict but does not gate on it. A CI-lower-bound > 0 bar is a different, stricter rule than the one the served recipe was registered under: the served recipe's own pooled held-out mean was +0.0073 R per decision (n 11,240), which a sd near 1 R puts well inside its own CI. Adopting that stricter bar would be a new rule and needs the operator.
- **It does not grade the newest candidate.** The newest candidate has no clean window yet (its window would start at the run date). Each weekly run grades the as-of-(run_date - WINDOW_DAYS) refit, WINDOW_DAYS = 14, so the graded artifact is about 3 weeks behind the newest data. That is the price of grading on data the candidate has not seen.
- **Deflation counts only COMMITTED reads.** The ledger is `comms/research/holdout_reads.jsonl`. A non-pass weekly run leaves its read in the run artifact only, so a candidate could in principle be re-read across overlapping weekly windows without the count rising. This under-counts N. It is filed, not hidden (see the row note).

## Naming

The manager asked for `ml_decision_entry_v<N+1>`. `ml_decision_entry_v2` already exists (the R2 recipe on `bybit_1`), so promoted artifacts are named `ml_decision_entry_v1r<YYYYMMDD>` (a dated revision of the v1 recipe) with `model_id` `ml-decision-entry-v1r<YYYYMMDD>`.

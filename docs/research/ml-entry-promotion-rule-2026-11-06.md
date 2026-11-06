# RULE-ENTRY-PROMOTE-20261106: when a retrained ENTRY candidate may replace the served artifact

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · REGISTERED 2026-11-06, BEFORE the first grading run (this file's commit precedes every commit that contains grader code or an evidence record; `git log` is the proof) · rows `ML-ENTRY-RETRAIN-CADENCE`, `ML-ENTRY-LIVE-MONITOR` · decisions by Manager Session 2026-11-06a (conventional defaults)

**Gates this adds or changes:** none new. This writes down, as a rule fixed before the run, the bar a real-money ENTRY artifact change already has to clear (the c692-01 registered rule, the `holdout_lock` deflation, the full cost stack). It decides what may be CHANGED, not what RUNS, and it is landed as a held PR; nothing swaps without a human merge.

## AMENDMENT 1 (2026-11-06 ~16:58Z, OPERATOR DECISION, relayed by Manager Session 2026-11-06a): replacing a LIVE model needs only "at least as good"

Operator, verbatim: **"New rule for replacing an already-live model: the retrained version goes live if, on the same post-training window and net of all costs, it does at least as well as the live one. The edge bar stays for brand-new strategies."** Popup answer: **"Graded retrain now (Recommended)"**. The operator's reasoning, in chat: *"the whole point of retraining is to improve it, so if the retraining improved the outcome, then shouldn't we be using the retrain?"*

Honest provenance: this amendment is made AFTER the first grading read (run 42250040398, verdict `insufficient_n` under the first registration, candidate n 281). It is the operator's rule, not a session's, and it is committed BEFORE the first read's verdict is recomputed under it. It changes the PASS test only; it does NOT change the data, the window, the recipe, the cost stack or the sample-size floor.

## AMENDMENT 2 (2026-11-06, relayed by Manager Session 2026-11-06a; trigger message queued 16:57:53Z, received and committed after the first Amendment-1 recompute): the sample floor for a REPLACEMENT is n >= 100 per side

The manager's words: *"The operator's popup showed 'n 281 vs 342' explicitly and chose 'Graded retrain now'. So this swap is approved on today's read as it stands, with n=281 known. ... the n floor applies to the absolute/edge read; a replacement verdict needs n >= 100 on each side, which today's 281/342 meets."* The operator's verbatim words are those in Amendment 1; **the number 100 is the manager's formulation of the floor the operator approved, not an operator quote**.

Honest provenance, so the record cannot be misread: Amendment 1 (commit `172c15eb2`) left the replacement floor at 300 and the recompute under it (`verdict_amended.json`, head `fae0e380c`) read `insufficient_n` at candidate n 281. This amendment was committed AFTER that recompute. It lowers a floor after the n was seen. That is the operator's call to make as the owner of the rule and the manager says it was made with the numbers on screen; this record does not claim it was fixed before the data was read. The first recompute stays in the repo beside the second.

Amended rule for a REPLACEMENT: PASS iff **both** models have n >= **100** taken decisions (and >= 10 distinct symbols, unchanged: today 48 and 49) on the same post-train window AND candidate mean net R >= served mean net R. The n >= 300 floor still applies to the ABSOLUTE read, to the deflated bar reported as information, and to any BRAND-NEW strategy, leg or recipe. Below 100 on either side -> `insufficient_n`.

### The rule as amended (supersedes "The rule" below it, kept for the record)

Same candidate, same window, same scoring of both artifacts on the SAME rows with the registered policy and the full cost stack (fee 11.0 bps round trip, slippage 3.0 bps, funding 1.0 bps per 8 h; the fee-only harnesses stay excluded).

A REPLACEMENT of an already-served artifact PASSES iff **all** hold on that window:

1. **Sample floor, applied to BOTH models.** n taken decisions >= 300 on >= 10 distinct symbols for the candidate AND for the served artifact. The floor is unchanged (`N_FLOOR` 300, `SYMBOL_FLOOR` 10) and is NOT waived by this amendment.
2. **At least as good.** Candidate mean net R per taken decision >= the served artifact's on the same window.

Reported as information, no longer gating a replacement: the absolute deflated point bar (`holdout_lock`), the deflated CI lower bound, and the difference's standard error. The read is still CLAIMED in the holdout ledger before scoring. A BRAND-NEW strategy, leg or recipe (nothing served to replace) keeps the registered edge bar (point bar deflated by the ledger) and is not covered by this amendment.

Otherwise: below the floor on either model -> `insufficient_n` (served model kept, one flag); candidate worse than served -> `fail` (served model kept, one flag). A PASS opens a DRAFT promotion PR with a landing hold; a human merges.

### Superseded text: the first registration of "The rule" (kept verbatim for the record)


A candidate is the artifact the registered recipe (`scripts/research/ml_decision_entry.py`, c692-01: same 20 features, `LGB_PARAMS`, tau carried from the served artifact, SL 2 / TP 3 ATR, 24 h horizon) produces when refit **as of** a date S, with training rows purged and embargoed exactly as `ml_decision_entry.purge_train` does (rows before S minus 7 days minus 25 h). It is graded on the window `[S, run_date - 1]`, which starts after its training data by construction.

Both the candidate and the served artifact are scored on the SAME rows, with the registered policy (`ml_decision_entry.policy`: best side if predicted net R > tau, one open position per symbol until its exit bar), with net R from `ml_decision_entry.label_symbol`: the full cost stack (taker fee 11.0 bps round trip, slippage 3.0 bps, funding 1.0 bps per 8 h window crossed, via `src/runtime/execution_costs`). The fee-only harnesses (`scripts/backtest_orb.py`, `src/backtest/backtester.py`) are excluded from this corpus.

The candidate PASSES only if **all** hold on that window:

1. **Registered held-out rule (c692-01).** n taken decisions >= 300 on >= 10 distinct symbols, AND mean net R per taken decision clears the `holdout_lock` point bar for the N-th read of the ENTRY family on an overlapping window: mean >= `point_t_min(N)` x its standard error (N = 1 is mean >= 0). The read is CLAIMED in the ledger BEFORE any window outcome is scored, which sets N.
2. **Not worse than the served model.** Candidate mean net R per taken decision >= the served artifact's on the same window.

Otherwise:

- n or symbols under the floor: verdict `insufficient_n`. The served model is kept and one flag is raised.
- either test fails: verdict `fail`. The served model is kept and one flag is raised.
- A PASS opens a DRAFT PR that adds a NEW versioned artifact directory and repoints the one served-model pointer. The old directory stays for a one-line revert. Nothing merges itself.

(Superseded by Amendment 1: a replacement no longer has to clear the absolute bar; the manager's earlier line that the served model's weak evidence is no reason to lower it was overtaken by the operator's decision.)

## What this rule does not say, on purpose

- **It does not require "CI lower bound > 0".** The registered c692-01 rule (`research/queue/RQ-20261101-c692-01.yaml`, `decision_rule.rule`) is "PASS IF held-out mean net R per decision >= 0 (point estimate, the operator bar)", and `ml_decision_entry.verdict` implements it that way; the bootstrap CI is "reported, not gating". The grader REPORTS the deflated CI lower bound beside the verdict but does not gate on it. A CI-lower-bound > 0 bar is a different, stricter rule than the one the served recipe was registered under: the served recipe's own pooled held-out mean was +0.0073 R per decision (n 11,240), which a sd near 1 R puts well inside its own CI. Adopting that stricter bar would be a new rule and needs the operator.
- **It does not grade the newest candidate.** The newest candidate has no clean window yet (its window would start at the run date). Each weekly run grades the as-of-(run_date - WINDOW_DAYS) refit, WINDOW_DAYS = 14, so the graded artifact is about 3 weeks behind the newest data. That is the price of grading on data the candidate has not seen.
- **Deflation counts only COMMITTED reads.** The ledger is `comms/research/holdout_reads.jsonl`. A non-pass weekly run leaves its read in the run artifact only, so a candidate could in principle be re-read across overlapping weekly windows without the count rising. This under-counts N. It is filed, not hidden (see the row note).

## Naming

The manager asked for `ml_decision_entry_v<N+1>`. `ml_decision_entry_v2` already exists (the R2 recipe on `bybit_1`), so promoted artifacts are named `ml_decision_entry_v1r<YYYYMMDD>` (a dated revision of the v1 recipe) with `model_id` `ml-decision-entry-v1r<YYYYMMDD>`.

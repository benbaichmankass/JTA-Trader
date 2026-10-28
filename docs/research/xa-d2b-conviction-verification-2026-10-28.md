# MB-20260618-XA-D2B — M16 D2/D2b conviction sizing: verification (2026-10-28)

> **Doc status:** `live` · category `research` · last verified `2026-10-28` · lane `XA-D2B-VERIFY` (dispatched by Manager Session 2026-10-27a)

**Disposition: KILLED as framed** ("verify c_reg is populated"). `c_reg` cannot be populated because its enabler is unwired; the feature it would feed is not applying and its parent milestone is re-scoped. One Tier-1 observability fix ships (the soak log now carries the component inputs).

## Population (RULE ONE)
Live `order_packages` via the diag relay, `journal?table=order_packages&limit=400`: **n = 400** rows, `created_at` 2026-07-29 → 2026-10-28T20:18Z. Of these **92 carry a stamped `meta.conviction` block**; 308 carry none (non-crypto/ICT-scalp/gold legs with no `shadow_model_ids` path; read-state = *no stamp*, not zero conviction). Measured from the journal, not from the soak log, because the soak log never carried components.

## (1) Is conviction sizing applying today?
**No.** `meta.conviction_apply_decision` on the 46 packages that carry it:

| mode stamped | direction | resized | window |
|---|---|---|---|
| `apply` | reductive | 16 of 17 `True` | 2026-09-21, then 2026-10-02 → 2026-10-11 |
| `annotate` | reductive | 0 of 29 `True` | 2026-10-12 → 2026-10-28 (latest 14:04Z today) |

So reductive apply WAS live (qty cut to ~30–70% of risk-based qty on the stamped crypto legs) and **was switched to `annotate` between 2026-10-11T00:03Z and 2026-10-12T23:06Z**. The CLAUDE/ROADMAP line "reductive apply LIVE on bybit_1" and the since-last 2026-08-25 report are stale on the current mode. Who flipped it, and why, is not in the repo (`set-env` is a system-action; shallow clone cannot show history) → UNKNOWN. `CONVICTION_SIZING_ACCOUNTS` live value: **UNMEASURED** — a `get-env` read (issue #21041) had no reply when this was written; re-run `get-env env_key: ALL` to close it. The stamped mode is the effective value in the running process (settings overlay then env), so the headline stands without it.

## (2) Components
Of the 92 stamped rows, `inputs_used` keys: `c_strat` only **21**; `c_setup + c_strat` **70** (all ≤ 2026-10-21, the retired `setup-quality-baseline-v0`); `c_setup + c_strat + c_wr` **1**; **`c_reg` = 0 of 92**. `conviction` values: min 0.1034, max 1.0, 62 distinct of 92 — non-degenerate, but since 2026-10-22 every row is `c_strat` alone (i.e. conviction == the strategy's own confidence).

`c_reg` is dropped even though regime heads ARE scored on the packages (`eth-regime-1h-lgbm-xasset-v1` on 45, `eth-regime-1h-lgbm-v1` on 45, BTC regime heads on 4 each). **Root cause:** `build_conviction_inputs` only emits `c_reg` when a fitted `regime_alignment` calibrator exists for the head. The only fitter, `scripts/ml/fit_regime_alignment_calibrators.py`, is referenced by **nothing outside its own tests and module** (scoped search of `scripts/ .github/ ml/ src/ tests/`) — no workflow, cron or ops wrapper runs it, so the calibrator artifact section never exists and the fall-through drops `c_reg` by design. It was never broken at runtime; it was never wired. (The coverage audit's "not established" in § 1b of `ml-coverage-audit-2026-10-28.md` is now MEASURED: not established because nothing builds it.)

## (3) Why KILL rather than wire it
- The enabler would feed a lens (weight 0.15) into a sizing path that is currently `annotate` (no resize).
- M16 is DORMANT/re-scoped; the one registered within-leg sizing test `RQ-20260930-601` graded FAIL (rho 0.019, p 0.197, n_eval 2328). Building a 4th lens under a failed premise buys nothing a later session cannot re-derive from this note.
- No learned model reaches conviction on any leg since 2026-10-22; D2b's own trigger ("verify c_reg sane") has no input to verify.
**Re-entry test:** reopen only if `RQ-20260930-602` (blocked on ≥ 500 more eval trades) passes AND the operator re-arms `apply`; then wire `fit_regime_alignment_calibrators.py` into the trainer cycle (Tier-2: changes conviction values the apply path reads).

## Tier-1 fix shipped
`src/runtime/conviction_sizing.py`: both soak-log writers (`kind` annotate rows and `kind: apply` rows) now append `inputs_used`, `weights_used`, `blend_note`, `provenance` from `pkg.meta['conviction']`; `inputs_used: null` is the read-state for "no stamp" (never `{}`). Logging only — the returned qty path is untouched; 41 tests in `tests/runtime/test_conviction_sizing.py` + `test_conviction_apply.py` pass, including two new ones. Merge-safe, but the file is on the sizing path → manager to merge.

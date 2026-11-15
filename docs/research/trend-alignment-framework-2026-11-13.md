# Trend alignment at entry — registered definition (TREND-ALIGN-V1)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Row **TREND-ALIGNMENT-FEATURE** (operator ask relayed by the manager 2026-11-13 06:50Z, lane session_01AFoLuJZ69XcyrjnD8na8ao).
The operator asked to track, beyond long vs short, whether each trade goes **with** or **against** the prevailing trend, then
see whether strategies trade better one way or the other, and possibly use it as an ML feature.

**Gates this adds or changes: none.** This is a label and a measurement. Nothing trades, filters or sizes on it. Any future
use as a gate or filter needs its own pre-registered test (OPERATING-PLAN § 2) and is Tier 3.

## Registration

- **Definition id:** `TREND-ALIGN-V1`. Registered **2026-11-13**.
- **Committed alone and before any outcome was read.** This file is the first commit of the row. When it was written, no
  trade had been labelled and no R had been grouped by any label. The backfill (step 2) and the per-leg analysis (step 4)
  come in later commits and cite this id.
- **Any change** to a threshold, timeframe, input or label rule is a new id (`TREND-ALIGN-V2`, ...) with its own
  registration date. Results graded under V1 stay graded under V1.

## What it reuses (no new trend definition is invented)

| Piece | Source of record | Used as |
|---|---|---|
| Wilder DMI / ADX-14 (alpha = 1/14, EWM) | `src/runtime/regime/detector.py::wilder_adx` (the regime router's trend axis) | strength (ADX) and the +DI / −DI series it computes internally |
| Trend floor `TREND_MIN_ADX = 25` (chop < 20, transitional 20–25) | same file; mirrored in `config/regime_policy.yaml` THRESHOLDS | the neutral band |
| Direction = sign(+DI − −DI) above the trend floor | `docs/research/M-regime-direction-filter-DESIGN.md` (`trending_up` / `trending_down`); `scripts/research/ml_entry_htf_trend_split.py` PRIMARY (`D = sign(+DI14 - -DI14)`) | trend direction |
| Warm-up floor `_MIN_BARS = 30` | `src/runtime/regime/detector.py` | minimum closed bars before a label exists |

The regime trend axis on its own is ADX **magnitude** only, so it is direction-blind (a strong down-move reads as `trending`
too). The direction comes from the DMI the same function already computes. That is the reuse the M-regime-direction-filter
design proposed and that `ml_entry_htf_trend_split.py` registered for 4h. V1 applies it per timeframe, at trade entry.

## The definition

**Inputs, per trade:** `entry_time` (UTC, the fill time of the entry), `side` (+1 long, −1 short), `symbol`, and the leg's
own `timeframe` (from `config/strategies.yaml`, re-parsed at run time, never quoted).

**Timeframes:** two, each computed separately.
1. **LEG** — the leg's own timeframe (e.g. 15m, 1h, 2h, 4h, 1d).
2. **D1** — daily bars (UTC day).

**Point in time (no lookahead).** For timeframe T, use only bars whose **close time ≤ entry_time**: a bar with open time `o`
closes at `o + T` and is usable only if `o + T ≤ entry_time`. The bar still forming at entry is never used, not even its
open. Inputs are OHLC of closed bars only. ADX, +DI and −DI are computed over the closed-bar history, and the value at the
last usable bar is read.

**Per timeframe T, with `adx`, `pdi`, `mdi` read at that bar:**

| Label | Condition |
|---|---|
| `with_trend` | `adx ≥ 25` AND `sign(pdi − mdi) == side` |
| `counter_trend` | `adx ≥ 25` AND `sign(pdi − mdi) == −side` |
| `neutral` | `adx < 25` (the neutral band: chop < 20 and transitional 20–25), OR `pdi == mdi` |
| *missing* (`null` + reason) | an input the label needs is absent (reasons below) |

**The neutral band** is `adx < TREND_MIN_ADX (25)`. Below that floor, direction is noise by the router's own definition. The
raw `adx` and the router's `regime_label(adx)` (`chop` / `transitional` / `trending`) are recorded beside every label, so an
analysis can split chop from transitional without a new definition.

**Missing is never filled.** A label whose inputs are absent is `null` with a reason, never `neutral` and never 0. Reasons
form a closed set:
- `no_candles`: no candle source for this symbol / timeframe in the backfill's feed.
- `insufficient_history`: fewer than 30 closed bars at or before entry.
- `adx_nan`: the DMI is undefined at that bar (e.g. a zero true range).
- `no_entry_time` / `no_side`: the trade row does not carry them.
- `no_timeframe`: the leg is not in `config/strategies.yaml` (retired or renamed), so LEG cannot be resolved. D1 is still
  computed.

**Recorded per trade, per timeframe:** `label`, `missing_reason`, `adx`, `pdi`, `mdi`, `regime_label`, `bar_close_used`
(the close time of the bar read), `n_bars_used`.

**Primary and secondary.**
- The **primary** label is **LEG**: the trend the strategy itself trades on.
- **D1** is the **secondary** label, reported beside it.
- A derived `agreement` field is also reported: `both_with`, `both_counter`, `split` (one with, one counter), or `other`
  (any neutral or missing).
- Neither secondary nor `agreement` replaces the primary. An analysis that wants to grade on D1 or on `agreement` must say
  so in its own registered rule.

## What it does not do

- It is not a strategy signal, filter or gate, and it changes no config. It does not place, block or size an order.
- It measures alignment with ONE definition of trend (Wilder DMI above ADX 25). A null result refutes this definition on
  these legs, not the idea of trend alignment. Alternatives (EMA20 vs EMA50, Donchian state, a midline slope) are reported
  alternatives in `ml_entry_htf_trend_split.py` and would be a V2 with its own registration.
- It does not by itself establish edge. A live or paper book's P&L split by label is a description, never a promotion basis
  (CLAUDE.md § promotion ladder). The per-leg test (step 4) is net of the full cost stack, with a rule registered before
  its run.

## Next steps (each its own commit, citing `TREND-ALIGN-V1`)

1. **This file**: definition registered, committed alone.
2. **Backfill.** Label every closed trade read-only from the journal (diag relay) and/or committed corpora. Report n by
   leg and book, plus the missing counts by reason.
3. **Tag new trades at entry** in order-package meta. This touches the trader path, so it is Tier 2 and HELD for the
   manager (`landing: hold`, `tier_2_3_needs_approval`).
4. **Per-leg analysis** as a `research/queue` unit: R net of the full cost stack by label, with n, CIs and the decision
   rule registered before the run.
5. **Candidate ML feature** through the normal ablation path, as a separate unit with its own baseline.

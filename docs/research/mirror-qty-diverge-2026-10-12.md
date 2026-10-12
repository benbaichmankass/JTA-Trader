# MIRROR-QTY-DIVERGE — evidence record (2026-10-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Evidence for PR #17696 (checklist row `MIRROR-QTY-DIVERGE`, Tier 3, landed
under the 2026-09-27 data-backed standing authorization). All figures were
MEASURED on 2026-10-12 by lane session_01Vtqkf7hNHtVFYZLfDSWfcG from
`/api/diag/journal?table=trades` (all 6,578 rows, paged), `/api/diag/exchange_positions`,
`/api/diag/bybit_open_orders` and `/api/bot/pnl/exchange/fills?days=90`.

## The package — pkg-63b56da53bfe4d64 (`xrp_pullback_2h` short, 2026-10-09T06:02Z)

| | bybit_2 (real money) | bybit_portfolio (mirror) |
|---|---|---|
| journal row | 6544 | 6545 |
| held before (trend_donchian_xrp_4h short) | 56.9 (row 6528: filled 61.6, less reduce legs 6533 3.3 + 6539 1.4) | 17267.2 (row 6529) |
| risk-sized target | 57.4 | 17428.1 (= 303.6 × 57.4) |
| intent-mode delta sent | **0.5 XRP** (~$0.70) | **160.9 XRP** |
| journal `position_size` | 57.4 (the TARGET — wrong) | 160.9 (the delta) |
| outcome | `exchange_rejected`, Bybit 110094 "minimum order value 5USDT" | filled; still open 2026-10-12 |

Entry 1.3964, SL 1.45509643, TP 1.2581564 on both rows. The `trend_donchian`
SL fired 06:40/06:42Z on both accounts; the mirror's 160.9 survived on its own
Partial bracket (SL `ff373556` @1.4551, TP `550f3806` @1.2582 — both verified
`Untriggered` at the venue 2026-10-12). The 303.6× target ratio equals ADA's
(166397 / 548); the "2.8×" first reported compared a target (57.4) to a delta
(160.9). Neither account is mis-sized: both carry `risk_pct 0.015`, `leverage 3`.

## Root cause (code on main before #17696)

1. `src/core/coordinator.py:2639` — the intent sub-min delta guard compares the
   delta to the venue minimum QTY (0.1 XRP) only; Bybit's minimum ORDER VALUE
   (`lotSizeFilter.minNotionalValue`, 5 USDT) was read nowhere in the order path.
2. Nothing at dispatch made a Stage-2 mirror follow its primary's venue outcome
   (the monocle gate couples only whether the pair may open).
3. `src/core/coordinator.py:2875` — the exception handler journalled `sized_qty`
   (target) instead of the qty sent.
4. `.github/workflows/mirror-orphan-watch.yml` — `check | tee` under the default
   `bash -e` shell: run 38169088768 (2026-10-11) printed
   `ORPHAN bybit_2->bybit_portfolio XRPUSDT short size=160.9` and concluded success.

## Frequency — the mirror's whole life (2026-07-16T18:01Z → 2026-10-12)

Population: every order package that produced a row on bybit_2 or bybit_portfolio
after bybit_portfolio's first row. Mirror filled, bybit_2 did not place: **9**.

| package | symbol | bybit_2 row / cause | mirror row |
|---|---|---|---|
| pkg-63b56da53bfe4d64 | XRPUSDT | 6544 — 110094 min order value | 6545 (open) |
| pkg-d5fed2cd90bb4230 | BTCUSDT | 4366 — 110007 | 4367 |
| pkg-a4b80bf85be340df | BTCUSDT | 4359 — 110007 | 4360 |
| pkg-ea4fd1e7b54d45a2 | BTCUSDT | 4339 — 110007 | 4340 |
| pkg-950aecf2f2a74b8b | BTCUSDT | 4328 — 110007 | 4329 |
| pkg-1ed646ed921241d2 | BTCUSDT | 4325 — 110007 | 4326 |
| pkg-df54afb502234494 | BTCUSDT | 4302 — 110007 | 4303 |
| pkg-791662b0231d4328 | BTCUSDT | 4252 — 110007 | 4253 |
| pkg-b77460b04d5a4417 | BTCUSDT | 4013 — 110007 | 4014 |

Other counts over the same population: both filled 75; bybit_2 filled and the
mirror did not 9 (zero balance 2, netting guard 3, flip hold 3, INTRADAY_DRAWDOWN 1).
bybit_2 `exchange_rejected` rows whose sent qty ≠ journal size: 2 of 10 (6544;
4047 270.062 vs 270.0, step alignment). Filled bybit_2 rows vs venue fills
(window from 2026-07-14T11:54Z): 76 match, 8 differ only by later reduce legs,
7 unjoined. alpaca_live: 0 exchange rejections; its 49 mirror-only packages are
all alpaca_live dry-run / zero-balance / sized-0 refusals (two legacy ones,
TLT 5912 and IEF 4195, already decided 2026-10-05 in
`config/mirror_window_exclusions.yaml`).

## The change and its revert

PR #17696: a mirror places a package only if its primary placed it in the same
dispatch (primaries ordered first; primary-placed/mirror-failed raises an ERROR
alert); an opening delta below the venue minimum order value is a benign
`intent_sub_min_notional_delta` noop; `exchange_rejected` rows journal the qty
sent; `mirror-orphan-watch` gets `set -o pipefail`. Over the mirror's life the
gate would have suppressed the 9 packages above.

**Revert:** `git revert` the #17696 merge commit. No config, account or state
change is involved.

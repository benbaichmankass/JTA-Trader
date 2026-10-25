# Amend parity — can every live account update an open position's SL/TP? (2026-10-25)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `AMEND-PARITY-ALL-ACCOUNTS`, dispatched by Manager Session 2026-10-25.
Operator directive (2026-10-25 ~19:00Z, close paraphrase relayed by the
manager): *there must be a mechanism to update an open trade, the same for all
accounts; a broker integration is placing the trade AND updating it in real
time; where that is missing, take care of it now.*

## Population

Every account in `config/accounts.yaml` (14 entries, parsed on this branch,
2026-10-25). The inventory covers all 14; the question is binding on the 11
with `mode: live` and on the dry-run real-money/prop accounts that could be
flipped live (`ib_live`, `breakout_1`). The mechanical answer is
`tests/test_amend_parity_guard.py::amend_path_for`, which this table was read
from (MEASURED: run on this branch, every live account resolves a path; only
`oanda_practice` resolves none).

## Inventory

| account | mode / class | venue | executor | modify-open path (file:line on this branch) | who calls it today | exercised live? | gaps |
|---|---|---|---|---|---|---|---|
| `bybit_2` | live / real_money | Bybit linear perp | `execute.py` order path | `src/units/accounts/execute.py:3047` `modify_open_order` → `set_trading_stop`, or `amend_order` on a tracked Partial leg (`:2988`) | order-monitor trail (`src/runtime/order_monitor.py:2522` `_send_modify_to_exchange`); `scripts/ops/amend_position_sl.py` (system-action `amend-position-sl`); LTR-6R `_exec_bybit` (PR #20139, not merged) | Yes — row `AMEND-SL-ACTION` records the first manual use, ADA SL → 0.2053 (2026-10-24). Trail amends not re-read this session | none found |
| `bybit_portfolio` | live / paper (mirror) | Bybit | same | same | same | not re-read this session | none found |
| `bybit_1` | live / paper | Bybit | same | same | trail | not re-read this session | none found |
| `alpaca_live` | live / real_money | Alpaca equities | `execute.py` | `execute.py:3317` alpaca branch → `src/units/accounts/alpaca_client.py:1967` `modify_protective` (PATCH the resting leg's `stop_price` / `limit_price`, qty-scoped) | order-monitor trail only. `amend_position_sl.py` refuses non-Bybit; LTR-6R refuses `no_amend_path` | **Once.** MEASURED, diag #20148 (`alpaca_order_history`, 2026-08-01→2026-10-25, 6 top-level orders, not truncated): exactly one leg carries `replaces` — the TLT OCO stop `3ac4048d…` replaced `f3715f25…` on 2026-09-22 and filled at 81.74. No position is open now (`alpaca_open_orders`, 19:02Z: 0 positions, 0 orders) | (1) **no read-back** after the PATCH — Alpaca has 2xx-accepted ineffective operations before (`PI-20261002-APBY4NTV-0001`); (2) **no tighten-only** check at the seam; (3) **a partially filled bracket is not distinguished**; (4) no path for the review apply / manual amend. **Built in this PR**: `src/units/accounts/alpaca_amend.py` |
| `alpaca_portfolio` | live / paper (mirror) | Alpaca | same | same | trail (roster is empty today: 0 strategies) | n/a | same as `alpaca_live`; same fix |
| `alpaca_paper` | live / paper | Alpaca | same | same | trail | **Yes, many.** Diag #20148: replace chains such as QQQ stop 730.90 → 734.57 → 735.88 → 736.81 → 737.87 → 738.42 → 739.03 → 739.99 (2026-10-02..05), each `replaces` / `replaced_by` linked — this confirms Alpaca's PATCH-replaces-the-order semantics the new executor relies on. (The 2026-10-01+ read was cut by the comment budget; the replace count is not stated for that reason.) | GLD OCO wedge (`PI-20261002-APBY4NTV-0001`): stop `held` ~$34 through the market. The new executor refuses that shape (`venue_stop_through_market`) instead of patching it |
| `alpaca_options_paper` | live / paper | Alpaca options (debit verticals) | `alpaca_options_exec` | the `alpaca` cap applies by exchange, but a vertical carries no bracket stop/target leg for `modify_protective` to PATCH | INFERRED from the options express path; not verified this session | not verified | INFERRED gap, paper only: options exits are managed as a spread close, not a leg amend. Row `AMEND-PARITY-ALPACA-OPTIONS` |
| `ib_paper` | live / paper | IB futures | `execute.py` | `execute.py:3237` IB branch → `src/units/accounts/ib_client.py:2188` `modify_protective` (cancel the trade's own OCA group + re-arm a fresh GTC OCA at merged levels) | trail | not re-read this session | cancel-then-replace leaves a naked window by construction (no in-place modify on IB) |
| `ib_live` | dry_run / real_money | IB | same | same | — | no | none beyond `ib_paper` |
| `tradeify_1` | live / prop | DXtrade (browser) | `src/prop/prop_executor.py` (VM) | `src/prop/platform/dxtrade.py:8735` `modify_bracket` | `src/prop/prop_trail.py:517` (SL) / `:611` (TP); `prop_executor.py:2965` | not re-read this session (venue-flat 2026-10-25 16:21Z per row `PHONE-AMEND-REFUSED-1025`) | the review's floor hand-off is LTR-8 (`sl_floor` in `plan_trail`), tracked there |
| `velotrade_1` | live / prop | DXtrade REST API | `prop_executor.py` | `src/prop/platform/dxtrade_api.py:531` `modify_bracket` (one conditional PUT per leg) | `prop_trail.py`; `scripts/prop/velotrade_api_roundtrip.py:167` | not re-read this session | same as `tradeify_1` |
| `breakout_1` | dry_run / prop | DXtrade | `prop_executor.py` | `dxtrade.py:8735` | — | no | — |
| `breakout_2` | live / prop | Breakout terminal via the operator's phone | `src/prop/phone_executor.py` | `src/prop/phone_trail.py` `plan_amends` → `claim_amend` → `record_amend_result` (one-slot amend channel the phone app executes) | phone trail | **Path exists, live amends have failed**: row `PHONE-AMEND-REFUSED-1025` (6 exit amends on 2026-10-24/25: 3 `sheet_not_open`, 3 refused on qty 0.40 vs 0.40899796); fix in PR #20122 (hold) | being fixed under `PHONE-AMEND-REFUSED-1025` / `BREAKOUT-SL-AMEND-CLICK` |
| `oanda_practice` | dry_run / paper | OANDA | `execute.py` | **none** — `EXCHANGE_MANAGEMENT_CAPS["oanda"]` = close + open_positions only | — | — | **gap**, dry-run only. Row `AMEND-PARITY-OANDA`. The parity guard now fails CI if this account is flipped live first |

## What this PR builds

1. **`src/units/accounts/alpaca_amend.py`** — the Alpaca tighten executor.
   `tighten(client, symbol, direction, qty, new_sl, new_tp, apply)`:
   reads position + this trade's legs (scoped by share count; same-size
   siblings refuse as ambiguous), refuses a looser or equal stop, a stop that
   would trigger, a stop already through the market (the GLD wedge shape),
   a partially filled parent, a flat or naked position; treats any read
   failure or a leg mid-replace as `could_not_look`; PATCHes; then reads the
   venue back and returns `applied` only when the replacing leg rests at the
   level (else `apply_failed`, including "PATCH 2xx but the old leg still
   rests"). It returns the OCO leg ids before and after. Rounds in the
   tightening direction only.
   `exec_trade_leg(db, trade, level, …)` is the LTR-6R seam: same result
   vocabulary and the same journal write-back (`trades.stop_loss`,
   `notes.sl_amends`, `notes.sl_floor`) as `live_review_apply._exec_bybit`,
   written only after the read-back matches.
   Read-only CLI: `python3 -m src.units.accounts.alpaca_amend --account alpaca_live [--trade-id N --new-sl X]` (there is no `--apply`).
2. **`tests/test_amend_parity_guard.py`** — the parity guard over the real
   config (rules in its docstring), with a planted-positive self-check.
3. **`new-broker` skill step 4b** — a modify-open-position path is part of
   every broker integration.

## Dry run on the positions open now

MEASURED, diag #20148, 2026-10-25 19:02Z: `alpaca_live` holds **0 positions
and 0 orders**, so a dry run over the open positions changes nothing. The CLI
itself needs the account's keys and runs on the VM; it has not been run there
(not verified).

## Wiring into LTR-6R (#20139) — DONE in this PR, stacked on #20139

Manager decision 2026-10-25 19:13Z: this lane wires it. #20139 was still open,
so #20150 merges #20139's branch and adds the wiring on top (it lands after,
or with, #20139). `scripts/ops/live_review_apply.py::run` now routes an
Alpaca TRADE leg to `_exec_alpaca`, which is:

```python
elif cls == "alpaca":
    from src.units.accounts import alpaca_amend
    res = alpaca_amend.exec_trade_leg(db, leg["row"], v.level, source=lri.PROVENANCE,
                                      mandate=intent.mandate, review_id=intent.review_id,
                                      evidence=intent.evidence_path, bar=intent.bar_ts)
```

That needs `order_monitor`'s `held_by_floor` from #20139 to be live too:
without it, the trail could PATCH an Alpaca stop back looser than the review's
floor on its next move.

## Not done here, stated

* The monitor trail's own Alpaca call (`modify_protective`) still has no
  read-back. Manager decision 2026-10-25: not in this PR; filed as row
  `AMEND-PARITY-ALPACA-TRAIL-READBACK` (Tier 3) with the diff sketch.
* Live exercise of the IB and prop-VM modify paths was not re-read this
  session.

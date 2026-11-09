# Alpaca wedged OCO — the self-healing close ladder

> **Doc status:** `live` · category `instruction` · last verified `2026-11-09` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

**Gates this adds or changes:** none. This documents an automatic escalation inside the existing close path
(`AlpacaClient.close`); nothing new can block a close.

The system resolves this on its own. No step here is a manual operator action. Operator direction, 2026-11-06
~18:55Z, relayed by Manager Session 2026-11-06a, verbatim:

> "You can close. We can close all the positions on that account if needed to reset. We just need to make sure
> that the problem is clearly documented with the solution so that the system can do that on its own. Like, if you
> need to reset the account in order to make it work, that's fine, but it can't depend on me, like, going in to fix
> these things manually, because the system needs to know how to handle it itself. That's why I'm insisting that
> the system figure out how to fix it on its own."

## Symptom

A close of an Alpaca position fails on every tick with:

> `insufficient qty available for order (requested: N, available: 0)`

The failure message carries the share-hold marker `[share_hold=cancel_accepted_ineffective: …]` or
`[share_hold=broker_cancel_wedged: …]`. The position's protective OCO still lists as live, with the take-profit
`new` and the stop `held`, and it holds every share.

**The case behind this runbook:** alpaca_paper GLD, 39 shares long (trade 5209, `pkg-8106d5eef6fc425c`).
- Its OCO legs were submitted on 2026-08-27: take-profit `2e843e04` at 461.27, stop `891ddff0` at 416.09.
- The stop never triggered, even though the mark fell to about 372.
- Every close since then failed. This was read on 2026-11-06 from `/api/diag/alpaca_open_orders`.

## Root cause

Alpaca **accepts** a cancel of the OCO legs (HTTP 2xx) and they never move. The shares stay
`held_for_orders`, so every flatten is refused for insufficient quantity.

Two documented facts make the ladder below necessary:
- **The single-position close has no cancel option.** `DELETE /v2/positions/{symbol}` takes only `qty` or
  `percentage`. `cancel_orders` exists only on the **close-all** endpoint
  (docs.alpaca.markets/reference/deleteopenposition-1 and `.../deleteallopenpositions-1`, read 2026-11-06).
- **OCO legs can be replaced, but only as a valid pair.** "Like bracket orders, order replacement is supported to
  update limit_price and stop_price" (docs.alpaca.markets/docs/orders-at-alpaca). Alpaca validates the two legs
  together on every replace. A long needs the take-profit limit above the stop; a short needs it below (live
  refusal 17:40Z: `take_profit.limit_price must be > stop_loss.stop_price`). A limit parent refuses `stop_price`
  (`limit orders must not have stop_price`). Each replace issues a **new** leg id, and the replaced leg keeps
  appearing in the nested listing as `replaced` (live 18:50Z: `891ddff0` became `c928eda6`).

## The ladder (`AlpacaClient.close`, regular hours, whole-symbol close)

| Rung | What the system does | Ends when |
|---|---|---|
| 1. Cancel and flatten | Cancels the symbol's orders, waits for `qty_available`, sends `DELETE /v2/positions/{sym}`, and retries once with the old `?cancel_orders=true`. | The position is flat, or the broker still holds the shares. |
| 2. Exit through the OCO | Re-reads the **current** legs (resting status only; a leg named by another leg's `replaces` is dropped). If the current stop is already on the valid side of a marketable take-profit, it reprices **only the take-profit** (mark ∓1%). Otherwise it moves the stop first (mark ∓5%), waits until a re-read shows the new stop settled (not `pending_replace`), then moves the take-profit. The pair rule is checked before every PATCH. The take-profit fills and Alpaca's OCO cancels the stop. | The confirm gate sees the position flat, or a step is refused (named in the message). |
| 3a. **Paper** account reset | Only when the share hold reads as a broker wedge (`cancel_accepted_ineffective` / `broker_cancel_wedged`; never on a transient hold), it sends `DELETE /v2/positions?cancel_orders=true`, Alpaca's documented close-all. `execute.journal_account_reset` then closes every **other** open journal trade on that account with `exit_reason='account_reset'` (notes `closed_by: alpaca_account_reset`, `exit_price_source: pending_broker_fill`), and closes each package left with no open trade (`close_reason='account_reset'`). | The confirm gate sees the symbol flat. Strategies re-enter on their own signals; nothing is re-opened by hand. |
| 3b. **Live** account | Close-all is **never** automated on real money, because it would flatten unrelated real positions. The system raises **one** red flag (`outcomes.report`, op `close_ladder_exhausted_live`, deduplicated by fingerprint) naming the stuck order ids and the step that failed. The failure message carries `[close ladder exhausted on a LIVE account …]`. | A person decides. |

**Two ways into the ladder.** The flatten can be *refused* ("insufficient qty"), which goes into rung 2 from the
give-up branch. Or it can be *accepted but never fill* (live 2026-11-06 20:11Z/20:13Z). In that case the cancel
pass had removed the stop (`c928eda6`) while the take-profit `2e843e04` still held all 39 shares. When the confirm
gate sees the position still open **and** a current resting closing-side order holds the whole position, that is
the same wedge: rung 2 runs at once, then rung 3, all in the same call (`AlpacaClient._escalate_not_flat`).
Accepted-but-not-flat with nothing holding the shares is an ordinary retry.

**A third way in: rung 2 "repriced" but the broker never acted** (live 2026-11-09 15:06Z, GLD, ALPACA-CLOSE-REPRICE-NO-RESET).
After the flatten was refused, rung 2 reported the take-profit repriced (`result.scope = oco_target_reprice`). Alpaca
accepted the PATCH and ignored it: the take-profit still read 461.27 and the position stayed open. The flat-confirm gate
used to skip the escalation for that scope, so rung 3 never ran. Now `AlpacaClient._escalate_after_ineffective_reprice`
runs when the gate sees the position still open after an `oco_target_reprice`: on **paper** it goes on to rung 3a (the
close-all and the `account_reset` journal sweep); on **live** it raises the one red flag (`close_ladder_exhausted_live`,
reason `reprice_not_flat`) and never closes all. Operator, 2026-11-09 ~15:12Z, popup answer "Small Tier-2 code fix now".

**A cancelled stop is never the end state.** On paper the ladder ends flat (rung 2 or the rung 3 reset). On live,
or if a paper reset fails, the failure message says `POSITION HAS NO STOP`, and the live red flag is raised as
`accepted_not_flat_stopless`. While a wedged take-profit holds every share, no new protective order can be placed:
`place_protective` would hit the same insufficient-qty refusal. So the remedy is closing the position (paper) or a
person (live), and the system says which.

The **flat-confirm gate** decides every rung: a close is reported only when the position is gone from
`GET /v2/positions`. Outside regular hours the close is deferred (`retCode 2`, retried next session) or goes through
the extended-hours limit path. The ladder runs in regular hours.

## Where to read the outcome

- **The close result:** `result.scope` is `oco_target_reprice` or `account_reset` on success, and
  `result.closed_symbols` is set on a reset. `close_open_position` returns `account_reset` with the journal
  trades and packages it closed.
- **The journal:** trades with `exit_reason='account_reset'`, and packages with `close_reason='account_reset'`.
- **The failure message:** `[share_hold=…]`, `[oco target exit <state>: <detail>]`, and on paper
  `[account reset <state>: …]` or on live `[close ladder exhausted on a LIVE account …]`.

## Open question for a narrower live remedy

Alpaca documents no per-symbol cancel-and-close. The narrowest documented live levers are rung 2 itself and the
account-wide close-all. A narrower remedy would need either a documented single-order force-cancel or an Alpaca
support action. Until one exists, live stops at the red flag.

Records: row ALPACA-LIVE-MECHANICS; row PAPER-MECHANICS-20261104; PRs #23885, #23905 and the ladder PR.

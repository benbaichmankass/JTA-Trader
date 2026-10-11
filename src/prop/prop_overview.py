"""Aggregate prop-book view for the SPA Overview "Prop" executive summary.

WHY (DASH-PROP-OVERVIEW, 2026-10-10). The Overview's Prop book rendered every
card as "—" and "No open prop trades" while the journal held an OPEN
velotrade_1 trade and fresh equity for two accounts. The SPA's ExecSummary
hard-coded the prop branch to null/[] ("lives on the Prop tab") and the only
prop endpoints were per-account (`/status`) or raw (`/fills`), so the
Overview had nothing to ask. This is the one read that answers it, computed
from the canonical prop journal (``prop_fills`` / ``prop_account_status``) —
no new store.

Contract (never collapse "unread" into 0):
  * ``equity.total_usd`` sums ONLY accounts whose latest snapshot is fresh
    (``status_freshness == "ok"``); ``null`` when none is. Stale / absent
    accounts are listed with their state and EXCLUDED from the sum.
  * ``open_trades`` are open/filled fill rows with no closing row for the same
    ticket/external id. ``placed`` (a resting limit) is not an open trade.
  * ``realized`` covers closed fills whose ``closed_at`` (else ``reported_at``)
    is inside the window; ``pnl`` null rows are counted in ``closed_unpriced``
    and excluded from P&L / win rate. ``win_rate`` / ``profit_factor`` are null
    when there is nothing to compute them over.
  * Unrealized P&L (UI-UPGRADE-1, 2026-10-11) is projected from the SAME
    ``prop_account_status`` snapshots the equity comes from: the executors write
    the venue's own ``unrealized`` there on every status pass (measured
    2026-10-11: tradeify_1 -13.31 with equity - balance = -13.31). Each account
    carries one of four ``unrealized_state`` values, never collapsed:
      - ``venue_snapshot``  fresh snapshot with a number -> MEASURED;
      - ``no_open_trades``  fresh snapshot, no number, and the journal holds no
                            open trade on it -> 0.0, ESTIMATED (an inference
                            from our own journal, not a venue read);
      - ``not_reported``    fresh snapshot, no number, open trades -> null;
      - ``stale``           no fresh snapshot -> null (we could not look).
    The book total is a sum only when EVERY account is in one of the first two
    states; otherwise it is null and ``accounts_unknown`` says how many are
    missing. Until then the overview served ``unrealized_pnl: null`` always.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7),
           "30d": timedelta(days=30), "all": None}
_OPEN = {"open", "filled"}
_CLOSED = {"closed"}
_FILL_LIMIT = 500


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def prop_account_ids(accounts: Dict[str, Any]) -> List[str]:
    """Live prop accounts. A ``retired: true`` account (breakout_1, operator
    2026-10-09: it "shouldn't be coming up again") is excluded -- its equity and
    its never-closed historical fill rows are not this book's."""
    from src.prop.prop_identity import is_prop_account, is_retired_account
    return [aid for aid, a in (accounts or {}).items()
            if isinstance(a, dict) and is_prop_account(a) and not is_retired_account(a)]


def _key(f: Dict[str, Any]) -> Optional[tuple]:
    if f.get("external_order_id"):
        return (f["account_id"], "ext", str(f["external_order_id"]))
    if f.get("ticket_id"):
        return (f["account_id"], "tkt", str(f["ticket_id"]))
    return None


def split_fills(fills: List[Dict[str, Any]]):
    """-> (open_rows, closed_rows). A trade with a closing row is not open."""
    closed = [f for f in fills if str(f.get("status", "")).lower() in _CLOSED]
    closed_keys = set()
    for f in closed:
        k = _key(f)
        if k:
            closed_keys.add(k)
        if f.get("ticket_id"):
            closed_keys.add((f["account_id"], "tkt", str(f["ticket_id"])))
    open_rows = []
    for f in fills:
        if str(f.get("status", "")).lower() not in _OPEN:
            continue
        k = _key(f)
        tk = (f["account_id"], "tkt", str(f["ticket_id"])) if f.get("ticket_id") else None
        if (k and k in closed_keys) or (tk and tk in closed_keys):
            continue
        open_rows.append(f)
    return open_rows, closed


def _account_unrealized(row: Dict[str, Any], open_rows: List[Dict[str, Any]]) -> tuple:
    """-> (value, state, provenance) for one account row. See the module doc."""
    if row.get("status_freshness") != "ok":
        return None, "stale", "unverified"
    if row.get("_unrealized_raw") is not None:
        return row["_unrealized_raw"], "venue_snapshot", "measured"
    if not any(f.get("account_id") == row["account_id"] for f in open_rows):
        return 0.0, "no_open_trades", "estimated"
    return None, "not_reported", "unverified"


def _unrealized_block(acct_rows: List[Dict[str, Any]],
                      open_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    known, unknown, total = 0, 0, 0.0
    for row in acct_rows:
        val, state, prov = _account_unrealized(row, open_rows)
        row["unrealized"] = round(val, 2) if val is not None else None
        row["unrealized_state"] = state
        row["unrealized_provenance"] = prov
        if val is None:
            unknown += 1
        else:
            known += 1
            total += val
    for row in acct_rows:
        row.pop("_unrealized_raw", None)
    return {
        "total_usd": round(total, 2) if acct_rows and unknown == 0 else None,
        "accounts_known": known,
        "accounts_unknown": unknown,
        "source": "prop_account_status.unrealized (venue-reported by the prop executors)",
    }


def _trade_unrealized(f: Dict[str, Any], acct_rows: List[Dict[str, Any]],
                      open_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A trade's uPnL is the account's venue number only when it is the
    account's ONLY open trade; with two or more the venue number cannot be
    split honestly, so it is null."""
    acct = next((r for r in acct_rows if r["account_id"] == f.get("account_id")), None)
    siblings = sum(1 for o in open_rows if o.get("account_id") == f.get("account_id"))
    if acct and acct.get("unrealized_state") == "venue_snapshot" and siblings == 1:
        return {"unrealized_pnl": acct["unrealized"], "unrealized_provenance": "measured",
                "unrealized_as_of": acct.get("reported_at")}
    return {"unrealized_pnl": None, "unrealized_provenance": "unverified",
            "unrealized_as_of": None}


def build_overview(window: str = "7d", *, accounts: Optional[Dict[str, Any]] = None,
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    from src.prop import prop_journal, prop_reconcile

    if window not in WINDOWS:
        window = "7d"
    now = now or datetime.now(timezone.utc)
    if accounts is None:
        from src.config.accounts_loader import load_accounts_dict
        accounts = load_accounts_dict()
    ids = prop_account_ids(accounts)

    acct_rows, total, fresh_n = [], 0.0, 0
    all_fills: List[Dict[str, Any]] = []
    for aid in ids:
        snap = prop_journal.latest_account_status(aid)
        rd = prop_reconcile.compute_rule_distance(aid, snap)
        fresh = rd.get("status_freshness")
        eq = (snap or {}).get("equity")
        counted = fresh == "ok" and isinstance(eq, (int, float))
        if counted:
            total += float(eq)
            fresh_n += 1
        ur = (snap or {}).get("unrealized")
        acct_rows.append({
            "account_id": aid, "mode": (accounts[aid] or {}).get("mode"),
            "equity": eq if isinstance(eq, (int, float)) else None,
            "status_freshness": fresh, "status_age_hours": rd.get("status_age_hours"),
            "counted_in_total": counted,
            "_unrealized_raw": float(ur) if isinstance(ur, (int, float)) else None,
            "reported_at": (snap or {}).get("reported_at"),
        })
        all_fills.extend(prop_journal.list_fills(account_id=aid, limit=_FILL_LIMIT))

    open_rows, closed = split_fills(all_fills)
    unrealized = _unrealized_block(acct_rows, open_rows)
    cutoff = None if WINDOWS[window] is None else now - WINDOWS[window]
    in_win = []
    for f in closed:
        ts = _parse(f.get("closed_at")) or _parse(f.get("reported_at"))
        if cutoff is None or (ts is not None and ts >= cutoff):
            in_win.append(f)
    priced = [f for f in in_win if isinstance(f.get("pnl"), (int, float))]
    wins = [f["pnl"] for f in priced if f["pnl"] > 0]
    losses = [f["pnl"] for f in priced if f["pnl"] < 0]
    gl = -sum(losses)
    realized = {
        "window": window,
        "total_pnl": round(sum(f["pnl"] for f in priced), 2) if priced else None,
        "closed_trades": len(in_win), "closed_priced": len(priced),
        "closed_unpriced": len(in_win) - len(priced),
        "win_rate": (len(wins) / len(priced)) if priced else None,
        "profit_factor": (sum(wins) / gl) if gl > 0 else None,
    }
    open_trades = [{
        "id": f.get("id"), "account_id": f.get("account_id"), "symbol": f.get("symbol"),
        "side": f.get("direction"), "qty": f.get("qty"), "entry_price": f.get("entry_price"),
        "sl": f.get("sl"), "tp": f.get("tp"), "ticket_id": f.get("ticket_id"),
        "opened_at": f.get("opened_at") or f.get("reported_at"),
        "status": f.get("status"),
        **_trade_unrealized(f, acct_rows, open_rows),
    } for f in open_rows]
    return {
        "generated_at": now.isoformat(),
        "equity": {
            "total_usd": round(total, 2) if fresh_n else None,
            "accounts_counted": fresh_n, "accounts_total": len(ids),
            "accounts": acct_rows,
        },
        "open_trades": open_trades,
        "realized": realized,
        "unrealized_pnl": unrealized["total_usd"],
        "unrealized": unrealized,
        "population": (f"{len(ids)} prop accounts; equity summed over {fresh_n} with a fresh "
                       f"operator-reported snapshot; realized over {len(in_win)} closed fills "
                       f"in {window} (last {_FILL_LIMIT} fills per account)"),
    }

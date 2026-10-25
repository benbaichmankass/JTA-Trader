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
      - ``no_open_trades``  fresh snapshot, no number, the journal holds no
                            open trade AND the journal can vouch for flat (a
                            VM-executed account, whose executor journals fills
                            from the terminal) -> 0.0, provenance ``journal``
                            (never ``estimated``);
      - ``not_reported``    fresh snapshot, no number, and open trades OR a
                            PHONE-executed account (its journal depends on
                            write-backs that can be lost: breakout_2 held two
                            live positions the journal never saw,
                            2026-10-12) -> null, never 0;
      - ``stale``           no fresh snapshot -> null (we could not look).
    The book total is a sum only when EVERY account is in one of the first two
    states; otherwise it is null and ``accounts_unknown`` says how many are
    missing. Until then the overview served ``unrealized_pnl: null`` always.

  * PROP-TRACKING (operator 2026-10-12, verbatim: "we need to be able to track
    the prop trades - no upnl isn't a solution to the issue"). Two additions:
      - **per-trade MEASURED from the venue's Positions list.** The phone
        executor now posts the terminal's open positions (symbol, side, size,
        entry, mark, uPnL) in its snapshot (``raw.positions``, clean reads
        only); an open trade that is the only journal row for its symbol+side
        takes that position's uPnL, provenance ``measured``.
      - **a labelled ESTIMATE when no venue figure exists** (until the new APK
        is installed, or when a read is not clean): ``(mark - entry) x qty``,
        signed by side, with the mark from the bot's own candle feed for the
        symbol (``src.runtime.local_pnl.last_mark_price``; source labelled from
        the instrument profile's exchange). Provenance ``estimated``,
        trade/account state ``mark_estimate``. An estimate is NEVER summed into
        ``total_usd``: it is in ``total_incl_estimates_usd`` beside
        ``accounts_estimated``, so the measured total stays honest.
"""
from __future__ import annotations

import json
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


def _is_phone_account(account_id: str) -> bool:
    """True for a phone-executed account. An unreadable config answers True: when we cannot tell, the journal
    must not vouch for flat (None is the honest outcome)."""
    try:
        from src.prop import phone_executor
        return bool(phone_executor.is_phone_account(account_id))
    except Exception:  # noqa: BLE001  # allow-silent: "could not look" must not read as flat
        logger.warning("prop_overview: phone-account lookup failed for %s", account_id, exc_info=True)
        return True


def _account_unrealized(row: Dict[str, Any], open_rows: List[Dict[str, Any]],
                        trade_u: Optional[Dict[Any, Dict[str, Any]]] = None) -> tuple:
    """-> (value, state, provenance) for one account row. See the module doc."""
    if row.get("status_freshness") != "ok":
        return None, "stale", "unverified"
    if row.get("_unrealized_raw") is not None:
        return row["_unrealized_raw"], "venue_snapshot", "measured"
    mine = [f for f in open_rows if f.get("account_id") == row["account_id"]]
    if not row.get("_phone_executed") and not mine:
        return 0.0, "no_open_trades", "journal"
    # PROP-TRACKING fallback: every open trade carries a figure (measured per position or a mark estimate) ->
    # their sum, labelled as an estimate whenever any term is one. A phone account with NO journal-open trade
    # stays not_reported: the journal cannot vouch for flat, and there is nothing to estimate.
    us = [(trade_u or {}).get(f.get("id")) for f in mine]
    if mine and all(u and u.get("unrealized_pnl") is not None for u in us):
        val = sum(u["unrealized_pnl"] for u in us)
        if all(u["unrealized_provenance"] == "measured" for u in us):
            return val, "venue_positions", "measured"
        return val, "mark_estimate", "estimated"
    return None, "not_reported", "unverified"


def _unrealized_block(acct_rows: List[Dict[str, Any]],
                      open_rows: List[Dict[str, Any]],
                      trade_u: Optional[Dict[Any, Dict[str, Any]]] = None) -> Dict[str, Any]:
    known, unknown, estimated, total, est_total = 0, 0, 0, 0.0, 0.0
    for row in acct_rows:
        val, state, prov = _account_unrealized(row, open_rows, trade_u)
        row["unrealized"] = round(val, 2) if val is not None else None
        row["unrealized_state"] = state
        row["unrealized_provenance"] = prov
        if val is None:
            unknown += 1
        elif prov == "estimated":
            estimated += 1
            est_total += val
        else:
            known += 1
            total += val
    for row in acct_rows:
        row.pop("_unrealized_raw", None)
        row.pop("_phone_executed", None)
        row.pop("_venue_positions", None)
    return {
        # MEASURED/journal only: an estimate never enters this figure
        "total_usd": round(total, 2) if acct_rows and unknown == 0 and estimated == 0 else None,
        # the same plus the labelled mark estimates; null while any account is still unknown
        "total_incl_estimates_usd": round(total + est_total, 2) if acct_rows and unknown == 0 else None,
        "accounts_known": known,
        "accounts_estimated": estimated,
        "accounts_unknown": unknown,
        "source": "prop_account_status.unrealized (venue-reported by the prop executors); per-position venue "
                  "uPnL from the phone's Positions read; mark_estimate = (Bybit mark - entry) x qty, ESTIMATED",
    }


def _venue_positions(snap: Optional[Dict[str, Any]], fresh: Any) -> Optional[List[Dict[str, Any]]]:
    """The venue's open positions from a FRESH snapshot's clean Positions read, else None (not read)."""
    if fresh != "ok" or not snap:
        return None
    raw = snap.get("raw")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or raw.get("positions_state") != "read" or not isinstance(raw.get("positions"), list):
        return None
    return raw["positions"]


def _mark_source(symbol: str) -> str:
    """Where the estimate's mark came from: the instrument profile's exchange (the same routing
    ``market_data.connector_for_symbol`` uses for ``local_pnl.last_mark_price``), never a hard-coded venue."""
    try:
        from src.core.profile_loader import load_instrument_profiles
        ex = getattr((load_instrument_profiles() or {}).get(str(symbol).upper()), "exchange", None)
    except Exception:  # noqa: BLE001  # allow-silent: an unread profile is labelled, not guessed
        logger.warning("prop_overview: instrument profile read failed for %s", symbol, exc_info=True)
        ex = None
    return f"{str(ex).lower() if ex else 'bot_feed'}_last_close_5m"


def _mark_estimate(f: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """(mark - entry) x qty, signed by side, mark from the bot's own Bybit feed. ESTIMATED: a different venue's
    price, no fees, no funding. None when any term is missing (never 0)."""
    entry, qty = f.get("entry_price"), f.get("qty")
    side = str(f.get("direction") or "").lower()
    sign = 1 if side in ("long", "buy") else -1 if side in ("short", "sell") else 0
    if not isinstance(entry, (int, float)) or not isinstance(qty, (int, float)) or not sign or not f.get("symbol"):
        return None
    try:
        from src.runtime.local_pnl import last_mark_price
        mark = last_mark_price(f["symbol"])
    except Exception:  # noqa: BLE001  # allow-silent: no estimate is the honest outcome; logged
        logger.warning("prop_overview: mark read failed for %s", f.get("symbol"), exc_info=True)
        mark = None
    if not isinstance(mark, (int, float)) or mark <= 0:
        return None
    return {"unrealized_pnl": round((float(mark) - float(entry)) * float(qty) * sign, 2),
            "unrealized_provenance": "estimated", "unrealized_state": "mark_estimate",
            "unrealized_mark": float(mark), "unrealized_mark_source": _mark_source(f["symbol"]),
            "unrealized_as_of": datetime.now(timezone.utc).isoformat()}


def _trade_unrealized(f: Dict[str, Any], acct_rows: List[Dict[str, Any]],
                      open_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One open trade's uPnL, best source first:
      1. the account's venue number when it is the account's ONLY open trade (``venue_snapshot``);
      2. the venue's own Positions row for this symbol+side when this is the only journal row on it
         (``venue_position``, MEASURED);
      3. a mark estimate (``mark_estimate``, ESTIMATED);
      4. null (``not_reported``)."""
    acct = next((r for r in acct_rows if r["account_id"] == f.get("account_id")), None)
    siblings = sum(1 for o in open_rows if o.get("account_id") == f.get("account_id"))
    if acct and acct.get("_unrealized_raw") is not None and acct.get("status_freshness") == "ok" and siblings == 1:
        return {"unrealized_pnl": round(acct["_unrealized_raw"], 2), "unrealized_provenance": "measured",
                "unrealized_state": "venue_snapshot", "unrealized_as_of": acct.get("reported_at")}
    side = "long" if str(f.get("direction") or "").lower() in ("long", "buy") else "short"
    sym = str(f.get("symbol") or "").upper()
    same = [o for o in open_rows if o.get("account_id") == f.get("account_id")
            and str(o.get("symbol") or "").upper() == sym
            and ("long" if str(o.get("direction") or "").lower() in ("long", "buy") else "short") == side]
    vp = [p for p in ((acct or {}).get("_venue_positions") or [])
          if str(p.get("symbol") or "").upper() == sym and p.get("direction") == side]
    if len(same) == 1 and len(vp) == 1 and isinstance(vp[0].get("upnl"), (int, float)):
        return {"unrealized_pnl": round(float(vp[0]["upnl"]), 2), "unrealized_provenance": "measured",
                "unrealized_state": "venue_position", "unrealized_mark": vp[0].get("mark"),
                "unrealized_as_of": acct.get("reported_at")}
    est = _mark_estimate(f)
    if est is not None:
        return est
    return {"unrealized_pnl": None, "unrealized_provenance": "unverified",
            "unrealized_state": "not_reported", "unrealized_as_of": None}


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
            "_phone_executed": _is_phone_account(aid),
            "_venue_positions": _venue_positions(snap, fresh),
            "reported_at": (snap or {}).get("reported_at"),
        })
        all_fills.extend(prop_journal.list_fills(account_id=aid, limit=_FILL_LIMIT))

    open_rows, closed = split_fills(all_fills)
    # MD-EXEC-DEV-TEST-TRADES: an OPEN test position is real money and stays visible; a CLOSED one is not performance
    from src.prop.exec_test_trades import exclude_exec_test
    closed = exclude_exec_test(closed, fills=True)
    trade_u ={f.get("id"): _trade_unrealized(f, acct_rows, open_rows) for f in open_rows}
    for row in acct_rows:   # the venue's own position count: a check on the journal, visible beside it
        vps = row.get("_venue_positions")
        row["venue_open_positions"] = len(vps) if vps is not None else None
    unrealized = _unrealized_block(acct_rows, open_rows, trade_u)
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
        **trade_u[f.get("id")],
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
        "unrealized_pnl_incl_estimates": unrealized["total_incl_estimates_usd"],
        "unrealized": unrealized,
        "population": (f"{len(ids)} prop accounts; equity summed over {fresh_n} with a fresh "
                       f"operator-reported snapshot; realized over {len(in_win)} closed fills "
                       f"in {window} (last {_FILL_LIMIT} fills per account)"),
    }

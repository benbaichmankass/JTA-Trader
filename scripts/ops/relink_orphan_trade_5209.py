#!/usr/bin/env python3
"""Re-link orphan-adopted trade 5209 to its true package. **Tier-2 DB writeback (journal only).**

WHAT IS WRONG (GLD-ORPHAN-5209, 2026-11-01; manager decision (a), data-backed)
--------------------------------------------------------------------------------
alpaca_paper holds GLD long 39 sh with OCO legs SL 416.09 / TP 461.27, submitted 2026-08-27. Those are
trade 5126's brackets exactly (``pkg-8106d5eef6fc425c``: 39 sh, SL 416.08857143, TP 461.27228). 5126 was
closed 2026-08-28 as ``exchange_flat_reconciled`` while the shares were still held. On 2026-08-29 the
reverse reconciler re-adopted them as trade 5209 onto ``pkg-6a8e3fb325464be3``, the newest gld_pullback_1h
package within the entry-price tolerance. alpaca_paper's own row in that package (5166) was REJECTED, and
its SL/TP (414.53875 / 461.32723) disagree with the venue.

THE REPAIR (three conditional writes, each re-checking the expected current value; all or nothing)
* trade 5209: ``order_package_id`` pkg-6a8e -> pkg-8106; ``stop_loss`` / ``take_profit_1`` -> pkg-8106's
  (= the resting venue legs); prior values kept in ``notes.relink_repair``;
* pkg-8106: ``closed``/``exchange_flat_reconciled`` -> ``open``, ``close_reason`` NULL,
  ``linked_trade_id`` 5209 (a package closed under an open leg is managed by nobody, audit F-39);
* pkg-6a8e: ``open`` -> ``closed``, ``close_reason`` ``sl`` (its one filled leg, alpaca_portfolio 5167,
  closed ``sl``); prior status / close_reason in ``meta.relink_repair``.
PRECONDITION: fresh venue evidence (``--venue``, the VM's own /api/diag/alpaca_open_orders captured in this
run) shows alpaca_paper GLD long 39 with the SL 416.09 and TP 461.27 legs resting; otherwise REFUSED.
PLACES, MODIFIES AND CANCELS NOTHING at the venue. The GLD position is left to its OCO (manager decision
(b)). Idempotent: a repaired state is a no-op. DRY-RUN unless ``--apply``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

TRADE_ID = 5209
FALSE_PKG, TRUE_PKG = "pkg-6a8e3fb325464be3", "pkg-8106d5eef6fc425c"
ACCOUNT, SYMBOL, QTY = "alpaca_paper", "GLD", 39.0
VENUE_SL, VENUE_TP = 416.09, 461.27
FALSE_PKG_CLOSE_REASON = "sl"  # alpaca_portfolio 5167, the package's one filled leg, closed sl
TOL = 0.006  # cents


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def venue_check(doc) -> tuple:
    """(ok, why) from an /api/diag/alpaca_open_orders document."""
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts"), list):
        return False, "venue payload unusable"
    acct = next((a for a in doc["accounts"] if a.get("account_id") == ACCOUNT), None)
    # collapsed-state: orders_read — every other read state (could_not_look, not_alpaca, ...) is a REFUSAL here
    if not acct or acct.get("read_state") != "orders_read":
        return False, f"{ACCOUNT} venue read_state={acct and acct.get('read_state')} (could not look)"
    res = acct.get("result") or {}
    pos = [p for p in res.get("positions") or [] if p.get("symbol") == SYMBOL]
    if len(pos) != 1 or str(pos[0].get("side")) not in ("buy", "long") or abs((_f(pos[0].get("qty")) or 0) - QTY) > 1e-9:
        return False, f"venue {SYMBOL} position is {pos!r}, expected one long of {QTY:g}"
    legs = [o for o in res.get("orders") or [] if o.get("symbol") == SYMBOL and str(o.get("side")) == "sell"]
    sl = [o for o in legs if o.get("order_type") in ("stop", "stop_limit") and abs((_f(o.get("stop_price")) or 0) - VENUE_SL) <= TOL]
    tp = [o for o in legs if o.get("order_type") == "limit" and abs((_f(o.get("limit_price")) or 0) - VENUE_TP) <= TOL]
    if len(sl) != 1 or len(tp) != 1:
        return False, f"venue legs do not match: {len(sl)} stop @ {VENUE_SL}, {len(tp)} limit @ {VENUE_TP}"
    return True, f"venue {ACCOUNT} {SYMBOL} long {QTY:g}, SL {VENUE_SL} / TP {VENUE_TP} resting"


def state(conn) -> dict:
    t = conn.execute("SELECT id, status, account_id, symbol, position_size, order_package_id, stop_loss, "
                     "take_profit_1, notes FROM trades WHERE id = ?", (TRADE_ID,)).fetchone()
    pk = {r["order_package_id"]: r for r in conn.execute(
        "SELECT order_package_id, status, close_reason, linked_trade_id, sl, tp, meta FROM order_packages "
        "WHERE order_package_id IN (?, ?)", (FALSE_PKG, TRUE_PKG))}
    return {"trade": t, "false": pk.get(FALSE_PKG), "true": pk.get(TRUE_PKG)}


def plan(s) -> tuple:
    """(status, why): plan | noop | refused."""
    t, fp, tp = s["trade"], s["false"], s["true"]
    if t is None or fp is None or tp is None:
        return "refused", "trade 5209 or a package row not found"
    if (t["status"], t["account_id"], t["symbol"]) != ("open", ACCOUNT, SYMBOL) or abs((_f(t["position_size"]) or 0) - QTY) > 1e-9:
        return "refused", f"trade 5209 is {t['status']}/{t['account_id']}/{t['symbol']}/{t['position_size']}, not open {ACCOUNT} {SYMBOL} {QTY:g}"
    if t["order_package_id"] == TRUE_PKG and tp["status"] == "open" and fp["status"] == "closed":
        return "noop", "already repaired"
    if t["order_package_id"] != FALSE_PKG:
        return "refused", f"trade 5209 links {t['order_package_id']!r}, expected {FALSE_PKG}"
    if (tp["status"], tp["close_reason"]) != ("closed", "exchange_flat_reconciled"):
        return "refused", f"{TRUE_PKG} is {tp['status']}/{tp['close_reason']}, expected closed/exchange_flat_reconciled"
    if fp["status"] != "open":
        return "refused", f"{FALSE_PKG} is {fp['status']}, expected open"
    if abs((_f(tp["sl"]) or 0) - VENUE_SL) > TOL or abs((_f(tp["tp"]) or 0) - VENUE_TP) > TOL:
        return "refused", f"{TRUE_PKG} sl/tp {tp['sl']}/{tp['tp']} do not match the venue legs {VENUE_SL}/{VENUE_TP}"
    return "plan", "relink 5209 -> pkg-8106; reopen pkg-8106; close pkg-6a8e (sl)"


def _obj(raw) -> dict:
    try:
        d = json.loads(raw) if raw else {}
    except ValueError:
        d = {"_unparsed_prior": str(raw)[:500]}
    return d if isinstance(d, dict) else {"_prior": d}


def apply(conn, s, reason: str) -> int:
    t, fp, tp = s["trade"], s["false"], s["true"]
    at = datetime.now(timezone.utc).isoformat()
    rec = {"at": at, "by": "system-action relink-orphan-trade-5209", "reason": reason, "row": "GLD-ORPHAN-5209"}
    notes = _obj(t["notes"])
    notes["relink_repair"] = dict(rec, from_package=FALSE_PKG, from_sl=t["stop_loss"], from_tp=t["take_profit_1"])
    m_true, m_false = _obj(tp["meta"]), _obj(fp["meta"])
    m_true["relink_repair"] = dict(rec, prior_status=tp["status"], prior_close_reason=tp["close_reason"],
                                   prior_linked_trade_id=tp["linked_trade_id"])
    m_false["relink_repair"] = dict(rec, prior_status=fp["status"], prior_close_reason=fp["close_reason"])
    n = 0
    n += conn.execute("UPDATE trades SET order_package_id=?, stop_loss=?, take_profit_1=?, notes=? "
                      "WHERE id=? AND status='open' AND order_package_id=?",
                      (TRUE_PKG, tp["sl"], tp["tp"], json.dumps(notes), TRADE_ID, FALSE_PKG)).rowcount
    n += conn.execute("UPDATE order_packages SET status='open', close_reason=NULL, linked_trade_id=?, meta=?, "
                      "updated_at=? WHERE order_package_id=? AND status='closed' AND close_reason='exchange_flat_reconciled'",
                      (TRADE_ID, json.dumps(m_true), at, TRUE_PKG)).rowcount
    n += conn.execute("UPDATE order_packages SET status='closed', close_reason=?, meta=?, updated_at=? "
                      "WHERE order_package_id=? AND status='open'",
                      (FALSE_PKG_CLOSE_REASON, json.dumps(m_false), at, FALSE_PKG)).rowcount
    if n != 3:
        conn.rollback()
        print(f"LOST-RACE: {n}/3 conditional writes matched; rolled back, nothing written")
        return 1
    conn.commit()
    return 0


def show(tag, s) -> None:
    t, fp, tp = s["trade"], s["false"], s["true"]
    print(f"{tag} trade 5209: " + ("missing" if t is None else
          f"{t['status']} pkg={t['order_package_id']} sl={t['stop_loss']} tp={t['take_profit_1']}"))
    for name, p in ((TRUE_PKG, tp), (FALSE_PKG, fp)):
        print(f"{tag} {name}: " + ("missing" if p is None else
              f"{p['status']}/{p['close_reason']} linked={p['linked_trade_id']} sl={p['sl']} tp={p['tp']}"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--venue", required=True, help="fresh /api/diag/alpaca_open_orders JSON captured in this run")
    ap.add_argument("--reason", default="")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        ok, why = venue_check(json.load(open(a.venue)))
    except (OSError, ValueError) as exc:
        ok, why = False, f"venue payload unreadable ({type(exc).__name__})"
    print(f"VENUE {'ok' if ok else 'REFUSED'}: {why}")
    conn = sqlite3.connect(a.db if a.apply else f"file:{a.db}?mode=ro", uri=not a.apply)
    conn.row_factory = sqlite3.Row
    try:
        before = state(conn)
        show("BEFORE", before)
        st, pwhy = plan(before)
        print(f"PLAN {st}: {pwhy}")
        if st == "refused" or (st == "plan" and not ok):
            return 2
        if st == "noop" or not a.apply:
            return 0
        rc = apply(conn, before, a.reason)
        show("READBACK", state(conn))
        return rc
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

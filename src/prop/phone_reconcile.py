"""Breakout PHONE executor: the journal reconciled against the terminal's own Positions list (PROP-TRACKING).

WHY (operator, 2026-10-12, verbatim): *"we need to be able to track the prop trades - no upnl isn't a solution
to the issue"*. breakout_2 held two live positions the journal never saw (BREAKOUT-UNRECORDED, journaled by hand
as fills 106/107), and a close on the terminal (SL/TP hit, manual close) wrote nothing back, so a journal row
could stay "open" forever. The phone now reads the terminal's Positions and Closed orders views on every account
read (``tools/phone-executor``: ``positionsRead`` / ``closedRead``) and posts them inside ``account_status``;
this module turns that into journal truth. Pure journal writes through :func:`src.prop.prop_report.ingest_report`
(the one fill chokepoint); no order is placed, cancelled or amended here.

Rules (each one is a way a reconcile can lie, refused):

* **Only a CLEAN read reconciles.** ``positions_state == "read"`` is the phone saying the Positions table was
  found, every row parsed (symbol, side, size), the tab's own count agreed, and an empty list carried positive
  evidence of flat. Anything else (``no_table``, ``unparsed``, ``empty_unconfirmed``, ``not_read``...) changes
  nothing: "we could not look" is never "the position is gone".
* **A journal-open row absent from the venue is CLOSED, never left open** -- but only once it has been absent on
  :data:`MISS_READS` consecutive clean reads at least :data:`MISS_MIN_S` apart (one glitched read must not close a
  live trade), and never within :data:`GRACE_S` of being journaled. The exit comes from the Closed orders read
  (one unused closing-side row for the symbol, size within :data:`QTY_TOL`); with none, or more than one, the row
  is closed with ``exit_price`` null and reason ``closed_unpriced`` and the operator is pinged. A later priced
  close corrects it in place (``prop_journal.insert_fill``'s VELO-CLOSE-RECON branch).
* **A venue position with no journal row is JOURNALED, as unconfirmed.** If a ``placed`` working order of the same
  symbol and side exists, the position is that order having filled (``open`` on its ticket). Otherwise it is an
  ``open`` row on a synthetic id (``venue-<account>-<symbol>-<side>-<entry>``, no ticket row, so it can never
  advance an unrelated ticket) with reason ``unconfirmed`` and ONE operator ping.
* Provenance: venue values are ``MEASURED`` (read off the venue's own terminal); a close with no readable exit is
  ``UNVERIFIED``. P&L is the venue's realized figure or null -- never computed here (fee-blind).
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.runtime.provenance import MEASURED, UNVERIFIED

logger = logging.getLogger(__name__)

MISS_READS = 2        # consecutive clean reads a journal-open row must be absent from before it is closed
MISS_MIN_S = 60       # ...spanning at least this long
GRACE_S = 120         # a row journaled this recently is never closed (the venue list may lag the submit)
QTY_TOL = 0.02        # relative size tolerance when matching a venue position / a closing order to a journal row
_MAX_ROWS = 40
_LOCK = threading.Lock()
_DEAD = re.compile(r"cancel|reject|expire|fail", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num(v: Any, *, signed: bool = True) -> Optional[float]:
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v) if (signed or v >= 0) else None


def _side(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    return "long" if s in ("long", "buy") else "short" if s in ("short", "sell") else None


def _norm(s: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def bot_symbol(account_id: str, venue_text: Any) -> Optional[str]:
    """The terminal's symbol text ("ETH", "ETHUSD", "ETH-PERP") -> the bot symbol of a DECLARED phone instrument.
    None when it names none of them (never guessed: an unknown instrument is reported, not journaled)."""
    from src.prop import phone_executor

    s = _norm(venue_text)
    s = re.sub(r"PERP$", "", s)
    if not s:
        return None
    insts = phone_executor.phone_config(account_id).get("instruments") or {}
    for bot, inst in insts.items():
        venue = _norm((inst or {}).get("venue"))
        base = re.sub(r"(USDT|USDC|USD)$", "", venue)
        if s in (_norm(bot), venue, base):
            return str(bot).upper()
    return None


def clean_positions(account_id: str, rows: Any) -> List[Dict[str, Any]]:
    """Validate the phone's Positions rows. Raises ValueError on a structurally bad row (the report is refused,
    so a half-read list can never reconcile). Unknown instruments keep ``symbol: None`` and their venue text."""
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        raise ValueError("account_status.positions must be a list of at most %d rows" % _MAX_ROWS)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("account_status.positions row must be an object")
        side = _side(r.get("side"))
        qty = _num(r.get("qty"), signed=False)
        if side is None or qty is None or qty <= 0:
            raise ValueError("account_status.positions row needs side and a positive qty")
        venue = re.sub(r"[^A-Za-z0-9 ./-]", "", str(r.get("symbol") or ""))[:24]
        out.append({"symbol": bot_symbol(account_id, venue), "venue_symbol": venue, "direction": side, "qty": qty,
                    "entry": _num(r.get("entry"), signed=False), "mark": _num(r.get("mark"), signed=False),
                    "upnl": _num(r.get("upnl"))})
    return out


def clean_closed(account_id: str, rows: Any) -> List[Dict[str, Any]]:
    """Validate the phone's Closed orders rows (tolerant: a row that cannot be used is dropped, not fatal)."""
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows[:_MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        side = _side(r.get("side"))
        sym = bot_symbol(account_id, r.get("symbol"))
        if side is None or sym is None:
            continue
        out.append({"symbol": sym, "side": side, "qty": _num(r.get("qty"), signed=False),
                    "price": _num(r.get("price"), signed=False), "pnl": _num(r.get("pnl")),
                    "type": str(r.get("type") or "")[:30], "status": str(r.get("status") or "")[:20],
                    "time": str(r.get("time") or "")[:40]})
    return out


def account_unrealized(positions: List[Dict[str, Any]]) -> Optional[float]:
    """The account's unrealized P&L from a CLEAN Positions read: the venue's own per-position figures summed, 0.0
    when the venue says flat, None when any position carries no figure (a partial sum is not the account's)."""
    if not positions:
        return 0.0
    vals = [p.get("upnl") for p in positions]
    if any(v is None for v in vals):
        return None
    return round(sum(vals), 2)


# ── state (debounce + used closing orders), one small file per account beside the phone diag files ─────────────
def _state_path(account_id: str) -> Path:
    from src.prop import phone_executor

    return phone_executor._diag_path(account_id).with_name(
        f"prop_phone_recon_{re.sub(r'[^a-z0-9_]', '', account_id)}.json")


def _load_state(account_id: str) -> Dict[str, Any]:
    try:
        st = json.loads(_state_path(account_id).read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(account_id: str, st: Dict[str, Any]) -> None:
    path = _state_path(account_id)
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(path)
    except OSError:  # allow-silent: logged; the debounce restarts (fails toward NOT closing), never a false close
        logger.warning("phone_reconcile: state write failed for %s", account_id, exc_info=True)


def _row_id(f: Dict[str, Any]) -> str:
    return str(f.get("id"))


def _close_sig(c: Dict[str, Any]) -> str:
    return f"{c['symbol']}|{c['side']}|{c.get('qty')}|{c.get('price')}|{c.get('time')}"


def _qty_close(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= QTY_TOL * max(abs(a), abs(b))


def _pick_exit(row: Dict[str, Any], closed: List[Dict[str, Any]], used: set) -> tuple:
    """-> (closing order or None, n candidates). The closing side is the opposite of the position."""
    want = "short" if _side(row.get("direction")) == "long" else "long"
    cands = [c for c in closed if c["symbol"] == str(row.get("symbol") or "").upper() and c["side"] == want
             and c.get("price") is not None and not _DEAD.search(c.get("status") or "")
             and _qty_close(c.get("qty"), _num(row.get("qty"))) and _close_sig(c) not in used]
    return (cands[0] if len(cands) == 1 else None), len(cands)


def _close_reason(row: Dict[str, Any], c: Optional[Dict[str, Any]]) -> str:
    if c is None:
        return "closed_unpriced"
    typ = (c.get("type") or "").lower()
    if re.search(r"take|tp\b|profit", typ):
        return "tp"
    if re.search(r"stop|sl\b|loss", typ):
        return "sl"
    px = c["price"]
    for lvl, name in ((_num(row.get("tp")), "tp"), (_num(row.get("sl")), "sl")):
        if lvl and abs(px - lvl) <= 0.0025 * lvl:
            return name
    return "venue_close"


def _ping(msg: str, send=None) -> None:
    from src.prop import phone_executor

    phone_executor._ping(msg, send)


def reconcile(account_id: str, positions: List[Dict[str, Any]], closed: List[Dict[str, Any]], *,
              now: Optional[datetime] = None, send=None) -> Dict[str, Any]:
    """Reconcile the account's journal against ONE clean venue Positions read. Returns a summary (also kept in the
    snapshot's raw by the caller). Never raises past a logged warning: the account_status itself is already stored."""
    from src.prop import prop_journal
    from src.prop.prop_overview import split_fills
    from src.prop.prop_report import ingest_report

    now = now or _now()
    out: Dict[str, Any] = {"closed": [], "closed_unpriced": [], "pending_close": [], "opened": [],
                           "unconfirmed": [], "unmapped": [], "matched": 0}
    with _LOCK:
        fills = prop_journal.list_fills(account_id=account_id, limit=500)
        open_rows, closed_rows = split_fills(fills)
        open_rows = [f for f in open_rows if f.get("account_id") == account_id]
        st = _load_state(account_id)
        missing = st.get("missing") if isinstance(st.get("missing"), dict) else {}
        used = set(st.get("used_closes") or [])

        venue = [p for p in positions if p.get("symbol")]
        out["unmapped"] = [p["venue_symbol"] for p in positions if not p.get("symbol")]
        claimed: set = set()   # venue positions accounted for by journal rows

        # 1. journal-open rows vs the venue list (grouped by symbol + side: the venue nets same-side entries)
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for f in open_rows:
            groups.setdefault((str(f.get("symbol") or "").upper(), _side(f.get("direction"))), []).append(f)
        new_missing: Dict[str, Any] = {}
        for key, rows in groups.items():
            hit = next((i for i, p in enumerate(venue) if (p["symbol"], p["direction"]) == key and i not in claimed), None)
            if hit is not None:
                claimed.add(hit)
                out["matched"] += len(rows)
                jq = sum(_num(f.get("qty")) or 0.0 for f in rows)
                if not _qty_close(jq, venue[hit]["qty"]):
                    # a partial close or an add the journal did not see: reported in the summary, never auto-resized
                    out.setdefault("qty_mismatch", []).append({"symbol": key[0], "side": key[1],
                                                               "journal_qty": jq, "venue_qty": venue[hit]["qty"]})
                continue
            for f in rows:
                rid = _row_id(f)
                opened = _parse(f.get("opened_at")) or _parse(f.get("reported_at"))
                if opened is not None and (now - opened).total_seconds() < GRACE_S:
                    continue
                m = missing.get(rid) or {"first": now.isoformat(), "n": 0}
                m["n"] = int(m.get("n", 0)) + 1
                first = _parse(m.get("first")) or now
                if m["n"] < MISS_READS or (now - first).total_seconds() < MISS_MIN_S:
                    new_missing[rid] = m
                    out["pending_close"].append(rid)
                    continue
                if not (f.get("ticket_id") or f.get("external_order_id")):
                    # split_fills keys a close on ticket/external id; a row with neither cannot be closed by any
                    # report. Kept visible, flagged once, never silently left looking open-and-fine.
                    new_missing[rid] = m
                    if not m.get("flagged"):
                        m["flagged"] = True
                        _ping(f"📱 phone {account_id}: journal row {rid} ({f.get('symbol')} {f.get('direction')}) is "
                              f"not on the terminal's Positions list but has no ticket/order id to close it under. "
                              f"CHECK and report the close.", send)
                    continue
                c, n = _pick_exit(f, closed, used)
                reason = _close_reason(f, c)
                report = {
                    "kind": "fill", "status": "closed", "account_id": account_id,
                    "ticket_id": f.get("ticket_id"), "external_order_id": f.get("external_order_id"),
                    "symbol": f.get("symbol"), "direction": f.get("direction"), "qty": f.get("qty"),
                    "entry_price": f.get("entry_price"), "sl": f.get("sl"), "tp": f.get("tp"),
                    "exit_price": c["price"] if c else None, "pnl": c.get("pnl") if c else None,
                    "closed_at": now.isoformat(), "reason": reason,
                    "source": "phone_reconcile", "provenance": MEASURED if c else UNVERIFIED,
                    "reconcile": {"absent_reads": m["n"], "first_absent": m["first"], "exit_candidates": n,
                                  "closing_order": c},
                }
                try:
                    ingest_report(report)
                except Exception:  # noqa: BLE001  # allow-silent: logged + kept pending; the next read retries
                    logger.warning("phone_reconcile: close write failed %s row %s", account_id, rid, exc_info=True)
                    new_missing[rid] = m
                    continue
                if c:
                    used.add(_close_sig(c))
                    out["closed"].append({"id": rid, "exit": c["price"], "reason": reason})
                else:
                    out["closed_unpriced"].append(rid)
                    _ping(f"📱 phone {account_id}: {f.get('symbol')} {f.get('direction')} (journal row {rid}) is no "
                          f"longer on the terminal's Positions list; journaled CLOSED without an exit price "
                          f"({n} matching closing orders read). Report the exit if you can see it.", send)

        # 2. venue positions with no journal row
        placed = [f for f in fills if str(f.get("status") or "").lower() == "placed" and f.get("ticket_id")
                  and not any(o.get("ticket_id") == f.get("ticket_id") for o in open_rows + closed_rows)]
        for i, p in enumerate(venue):
            if i in claimed:
                continue
            w = next((f for f in placed if (str(f.get("symbol") or "").upper(), _side(f.get("direction")))
                      == (p["symbol"], p["direction"])), None)
            base = {"kind": "fill", "status": "open", "account_id": account_id, "symbol": p["symbol"],
                    "direction": p["direction"], "qty": p["qty"], "entry_price": p.get("entry"),
                    "opened_at": now.isoformat(), "source": "phone_reconcile", "provenance": MEASURED,
                    "venue_position": p}
            if w is not None:
                placed.remove(w)
                rep = {**base, "ticket_id": w["ticket_id"], "sl": w.get("sl"), "tp": w.get("tp"),
                       "reason": "filled: the placed working order is now on the terminal's Positions list"}
                bucket = "opened"
            else:
                ent = p.get("entry")
                rep = {**base, "ticket_id": f"venue-{account_id}-{p['symbol']}-{p['direction']}-"
                                            f"{'na' if ent is None else format(ent, 'g')}",
                       "reason": "unconfirmed: on the terminal's Positions list with no journal row"}
                bucket = "unconfirmed"
            try:
                ingest_report(rep)
            except Exception:  # noqa: BLE001  # allow-silent: logged; the next clean read retries it
                logger.warning("phone_reconcile: open write failed %s %s", account_id, p, exc_info=True)
                continue
            out[bucket].append(f"{p['symbol']} {p['direction']}")
            if bucket == "unconfirmed":
                _ping(f"📱 phone {account_id}: {p['symbol']} {p['direction']} qty {p['qty']:g} is OPEN on the terminal "
                      f"with no journal row; journaled as UNCONFIRMED (entry {p.get('entry')}). CHECK it is ours.", send)
        for vs in out["unmapped"]:
            if vs not in (st.get("unmapped_flagged") or []):
                st.setdefault("unmapped_flagged", []).append(vs)
                _ping(f"📱 phone {account_id}: the terminal shows a position in '{vs}', which is not a declared phone "
                      f"instrument; NOT journaled. CHECK the terminal.", send)

        st["missing"] = new_missing
        st["used_closes"] = sorted(used)[-200:]
        st["last_read"] = now.isoformat()
        _save_state(account_id, st)
    return out

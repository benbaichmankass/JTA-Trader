"""Pure builders for ``GET /api/bot/brackets/history`` (UI-CHART-BRACKET-HISTORY, backend half).

One normalised shape for the chart overlay -- the level in force (main line) plus every earlier level (subtle line)
and one marker per update -- built from the two stores that record bracket moves:

* exchange accounts: ``order_packages.meta.sl_moves`` (``sl_mover.stamp_sl_move``; SL ONLY, capped at ``MAX_SL_MOVES``,
  written since 2026-11-06). **There is no TP history anywhere for these packages** (``tp_moves`` is a separate Tier-2
  row), so ``tp_history`` says ``unrecorded`` and the TP level is the package's current ``tp`` -- never a fabricated line.
* prop: ``prop_fills.amendments`` (``prop_journal.amend_fill_levels``; SL and TP, before/after, with ``at``).

Rules: null stays null ("no record" is never ``[]``/0); a level whose start is not known is ``ESTIMATED`` and starts at
the open time; ``read_state`` is ``partial`` whenever history may be missing (cap hit / package predates the stamp).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SL_MOVES_STAMPED_SINCE = datetime(2026, 11, 6, tzinfo=timezone.utc)
SL_MOVES_CAP = 20  # == src.runtime.sl_mover.MAX_SL_MOVES (asserted in tests)
_INTERVAL_S = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
               "1d": 86400}


def parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def bar_ts(ts: Optional[datetime], interval: str) -> Optional[str]:
    """``ts`` floored to the chart interval, so the SPA can place the marker on the right bar."""
    step = _INTERVAL_S.get(interval)
    if ts is None or step is None:
        return None
    return _iso(datetime.fromtimestamp(int(ts.timestamp()) // step * step, tz=timezone.utc))


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None
    return v


def _level(kind, price, from_ts, to_ts, source, detail, provenance) -> Dict[str, Any]:
    return {"kind": kind, "price": price, "from_ts": _iso(from_ts), "to_ts": _iso(to_ts), "source": source,
            "detail": detail, "provenance": provenance}


def _chain(kind: str, initial: Optional[float], opened: Optional[datetime], steps: List[Dict[str, Any]],
           initial_prov: str) -> List[Dict[str, Any]]:
    """Levels for one kind from an initial price + ordered ``steps`` ({ts, to, source, detail}); to_ts None = in force."""
    levels: List[Dict[str, Any]] = []
    cur_price, cur_from, cur_src, cur_detail, cur_prov = initial, opened, "open", "", initial_prov
    for s in steps:
        levels.append(_level(kind, cur_price, cur_from, s["ts"], cur_src, cur_detail, cur_prov))
        cur_price, cur_from, cur_src, cur_detail, cur_prov = s["to"], s["ts"], s["source"], s["detail"], "MEASURED"
    levels.append(_level(kind, cur_price, cur_from, None, cur_src, cur_detail, cur_prov))
    return levels


def _marker(kind: str, ts: datetime, frm: Any, to: Any, source: Any, detail: Any, interval: str) -> Dict[str, Any]:
    return {"ts": _iso(ts), "kind": kind, "from": frm, "to": to, "source": source, "detail": detail,
            "bar_ts": bar_ts(ts, interval)}


def build_package_history(pkg: Dict[str, Any], interval: str = "1h") -> Dict[str, Any]:
    """Bracket history of one ``order_packages`` row (``entry/sl/tp/created_at/status/meta``)."""
    meta = _json(pkg.get("meta")) if pkg.get("meta") is not None else None
    meta = meta if isinstance(meta, dict) else {}
    opened = parse_ts(pkg.get("created_at"))
    raw = meta.get("sl_moves")
    moves = [m for m in raw if isinstance(m, dict) and parse_ts(m.get("ts"))] if isinstance(raw, list) else []
    moves.sort(key=lambda m: parse_ts(m["ts"]))
    cur_sl, cur_tp = _num(pkg.get("sl")), _num(pkg.get("tp"))
    capped = len(moves) >= SL_MOVES_CAP
    predates = opened is None or opened < SL_MOVES_STAMPED_SINCE
    steps = [{"ts": parse_ts(m["ts"]), "to": _num(m.get("to")), "source": m.get("source"), "detail": m.get("detail") or ""}
             for m in moves]
    # the level before the first recorded move is that move's "from" (a fact); with no moves it is the current sl
    initial_sl = _num(moves[0].get("from")) if moves else cur_sl
    sl_levels = _chain("sl", initial_sl, opened, steps, "ESTIMATED" if capped else "MEASURED")
    tp_levels = [_level("tp", cur_tp, opened, None, "open", "", "MEASURED" if cur_tp is not None else "UNVERIFIED")]
    reasons = []
    if capped:
        reasons.append("sl_moves_capped_at_%d" % SL_MOVES_CAP)
    if predates and not moves:
        reasons.append("predates_sl_move_stamp_2026-11-06")
    return {
        "account_class": "exchange", "order_package_id": pkg.get("order_package_id"),
        "symbol": pkg.get("symbol"), "direction": pkg.get("direction"), "closed": str(pkg.get("status")) != "open",
        "opened_at": _iso(opened),
        "read_state": "partial" if reasons else "measured", "partial_reasons": reasons,
        "tp_history": "unrecorded",  # no per-move TP store exists for exchange packages (tp_moves is a separate row)
        "levels": sl_levels + tp_levels,
        "updates": [_marker("sl", s["ts"], m.get("from"), s["to"], s["source"], s["detail"], interval)
                    for s, m in zip(steps, moves)],
    }


def build_prop_history(opener: Dict[str, Any], interval: str = "1h") -> Dict[str, Any]:
    """Bracket history of one prop trade from its OPENING ``prop_fills`` row (``sl``/``tp`` final, ``amendments``)."""
    opened = parse_ts(opener.get("opened_at")) or parse_ts(opener.get("reported_at"))
    raw = _json(opener.get("amendments")) if opener.get("amendments") else None
    amends = [a for a in raw if isinstance(a, dict) and parse_ts(a.get("at"))] if isinstance(raw, list) else None
    final_sl, final_tp = _num(opener.get("sl")), _num(opener.get("tp"))
    sl_steps: List[Dict[str, Any]] = []
    tp_steps: List[Dict[str, Any]] = []
    updates: List[Dict[str, Any]] = []
    sl0, tp0 = final_sl, final_tp
    if amends:
        amends.sort(key=lambda a: parse_ts(a["at"]))
        sl0 = _num(amends[0].get("sl_before")) if _num(amends[0].get("sl_before")) is not None else final_sl
        tp0 = _num(amends[0].get("tp_before")) if _num(amends[0].get("tp_before")) is not None else final_tp
        for a in amends:
            ts = parse_ts(a["at"])
            src = (a.get("source") or {}) if isinstance(a.get("source"), dict) else {}
            who = (src.get("reported") or {}).get("source") if isinstance(src.get("reported"), dict) else None
            detail = src.get("reason") or ""
            for kind, steps, b, n in (("sl", sl_steps, a.get("sl_before"), a.get("sl")),
                                      ("tp", tp_steps, a.get("tp_before"), a.get("tp"))):
                if _num(n) is not None and _num(n) != _num(b):
                    steps.append({"ts": ts, "to": _num(n), "source": who or "prop_amend", "detail": detail})
                    updates.append(_marker(kind, ts, _num(b), _num(n), who or "prop_amend", detail, interval))
    return {
        "account_class": "prop", "prop_fill_id": opener.get("id"), "ticket_id": opener.get("ticket_id"),
        "account_id": opener.get("account_id"), "symbol": opener.get("symbol"), "direction": opener.get("direction"),
        "opened_at": _iso(opened),
        # an amend that never reached prop_journal is invisible: "measured" means "every journaled amend", said plainly
        "read_state": "no_record" if (final_sl is None and final_tp is None and not amends) else "measured",
        "partial_reasons": [] if amends is not None else ["no_amendments_record"],
        "tp_history": "recorded" if amends is not None else "unrecorded",
        "levels": _chain("sl", sl0, opened, sl_steps, "MEASURED" if sl0 is not None else "UNVERIFIED")
        + _chain("tp", tp0, opened, tp_steps, "MEASURED" if tp0 is not None else "UNVERIFIED"),
        "updates": sorted(updates, key=lambda u: u["ts"]),
    }

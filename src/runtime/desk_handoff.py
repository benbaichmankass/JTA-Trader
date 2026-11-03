"""The desk hand-off protocol (row DESK-HANDOFF-PROTOCOL): every desk-opened position has ONE owner chain.

Operator, popup 2026-10-30 ~22:30Z, verbatim: *"We can lift it completely if we have a protocol for trade desk
hand-offs"* -- the 60-minute max-hold cap on ``claude_desk`` entries goes, on the condition that a trade opened
by one desk wake is owned by every later wake that touches it. Each wake is a fresh session, so the ownership
lives in the records, never in a session's memory:

(a) the opening desk row (``desk/decisions``, written by ``desk_write.py``) carries the thesis, a falsifiable
    ``forecast`` (direction, target, p, invalidation, horizon) and the ``exit_plan`` in its ``proposal``;
(b) every later live-review row on that package (the short-hold lane, a mechanical trigger, the 4h
    ``judgement_cadence`` book review) is built from a packet that carries :func:`handoff_block`, and it must
    CONFIRM, REVISE (with a reason) or EXIT, linking ``handoff.prior_decision_id`` to the newest record in the
    chain (the validator, ``scripts/ci/check_live_review_records.py::handoff_problems``, checks the link
    against the committed packet);
(c) ``claude_desk`` packages are on the ``judgement_cadence`` slot (the leg name has no timeframe suffix, so
    ``live_review_due.timeframe_seconds`` reads the 2h default, which has a 4h slot; its accounts are on the
    ``daily_floor`` list) -- pinned by ``tests/test_desk_handoff.py``;
(d) :func:`orphans` is the ``desk_orphan`` probe in ``scripts/ops/attention_watch.py``: an open desk package
    with no desk decision inside cadence + slack is ONE flag, never a gate;
(e) a hand-off read that fails is ``read_state: could_not_look``: the reviewer still judges, the position
    keeps its venue SL/TP, nothing halts.

Pure functions only; the I/O is in the callers (the packet builder and the probe).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

DESK_LEG = "claude_desk"
VERDICTS = ("confirm", "revise", "exit")
#: (c)/(d): the judgement_cadence slot for a desk package (config/live_trade_review.yaml, 2h default -> 4h)
#: plus the slack a wake needs to post, spawn and write (one cadence wake measured ~10-25 min end to end).
CADENCE_HOURS = 4.0
SLACK_HOURS = 1.0


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _meta(pkg: Dict[str, Any]) -> Dict[str, Any]:
    m = pkg.get("meta")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = None
    return m if isinstance(m, dict) else {}


def opening_record(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The hand-off-relevant part of the desk row that opened the position (None when no row)."""
    if not isinstance(row, dict):
        return None
    p = row.get("proposal") or {}
    return {
        "decision_id": row.get("decision_id"),
        "judged_at": row.get("judged_at"),
        "symbol": p.get("symbol"), "side": p.get("side"), "timeframe": p.get("timeframe"),
        "entry": (p.get("entry") or {}).get("level"),
        "stop": (p.get("stop") or {}).get("level"), "tp": (p.get("tp") or {}).get("level"),
        "thesis": p.get("thesis"),
        "forecast": p.get("forecast"),   # absent on rows written before the protocol: named in missing
        "exit_plan": p.get("exit_plan"),
        "max_hold_min": p.get("max_hold_min"),
        "expected_r_net": p.get("expected_r_net"),
    }


def chain_link(r: Dict[str, Any]) -> Dict[str, Any]:
    rec, fc, ho = r.get("recommendation") or {}, r.get("forecast") or {}, r.get("handoff") or {}
    return {"review_id": r.get("review_id"), "reviewed_at": r.get("reviewed_at"),
            "action": rec.get("action"), "verdict": ho.get("verdict"), "reason": ho.get("reason") or rec.get("reason"),
            "forecast": {k: fc.get(k) for k in ("direction", "target_px", "p_target", "invalidation_px", "horizon_bars",
                                                "timeframe")} if fc else None}


def handoff_block(pkg: str, meta: Dict[str, Any], desk_rows: Optional[Iterable[Dict[str, Any]]],
                  reviews: Optional[Iterable[Dict[str, Any]]], *, chain_tail: int = 4) -> Dict[str, Any]:
    """The packet's ``desk_handoff`` block for a desk-opened package. Pure.

    ``desk_rows`` / ``reviews`` are None when they could not be read (-> ``could_not_look``, never an empty chain).
    ``prior_decision_id`` is the newest record in the position's chain: the newest live-review row on the package,
    else the opening desk decision. The validator requires the reviewer to copy it into ``handoff``."""
    did = meta.get("decision_id")
    missing: List[str] = []
    opening = None
    if desk_rows is None:
        missing.append("desk/decisions not readable")
    else:
        opening = opening_record(next((r for r in desk_rows if r.get("decision_id") == did), None)) if did else None
        if opening is None:
            missing.append(f"opening desk row {did!r} not found" if did else "package meta has no decision_id")
        elif not opening.get("forecast"):
            missing.append("opening desk row predates the hand-off protocol (no forecast / exit_plan)")
    chain: Optional[List[Dict[str, Any]]] = None
    if reviews is None:
        missing.append("live-review rows not readable")
    else:
        mine = sorted((r for r in reviews if r.get("order_package_id") == pkg),
                      key=lambda r: str(r.get("reviewed_at") or ""))
        chain = [chain_link(r) for r in mine]
    prior = None
    if chain:
        prior = chain[-1]["review_id"]
    elif chain is not None and opening is not None:
        prior = opening["decision_id"]
    read_state = "read" if (opening is not None and chain is not None) else "could_not_look"
    return {
        "read_state": read_state,
        "protocol": "DESK-HANDOFF-PROTOCOL",
        "opening": opening,
        "chain_length": None if chain is None else len(chain),
        "chain_tail": None if chain is None else chain[-chain_tail:],
        "prior_decision_id": prior,
        "missing": missing,
        "instruction": "CONFIRM, REVISE (with a reason) or EXIT this position against the opening thesis and the "
                       "newest view in the chain; copy prior_decision_id into handoff.prior_decision_id.",
    }


def last_decision_at(pkg: Dict[str, Any], reviews: Iterable[Dict[str, Any]]) -> Optional[datetime]:
    """When the desk last decided about this package: the newest review of it, else the package's open time
    (the opening desk decision is what opened it)."""
    pid = str(pkg.get("order_package_id"))
    times = [_ts(r.get("reviewed_at")) for r in reviews if str(r.get("order_package_id")) == pid]
    times = [t for t in times if t is not None]
    opened = _ts(_meta(pkg).get("entry_time") or pkg.get("created_at"))
    if opened is not None:
        times.append(opened)
    return max(times) if times else None


def trigger_first_bound(cfg: Optional[Dict[str, Any]] = None) -> Tuple[float, bool]:
    """``(cadence_hours, skip_closed_markets)`` for the orphan probe. With the trigger-first gate on
    (``judgement_cadence.min_move_atr`` set, TRIGGER-FIRST-REVIEWS 2026-10-31) a quiet package is deliberately not
    reviewed on the 4h slot, so the guaranteed look is the ``daily_floor`` (hours), and a closed-market package is
    not an orphan at all. Gate off or config unreadable: the old 4h bound, markets not exempted."""
    try:
        from src.runtime.live_review_due import load_config  # noqa: PLC0415
        ev = (cfg or load_config())["events"]
        if (ev.get("judgement_cadence") or {}).get("min_move_atr") is not None:
            return float((ev.get("daily_floor") or {}).get("hours", 24)), True
    except Exception:  # noqa: BLE001  # allow-silent: unreadable config = the stricter, older bound
        pass
    return CADENCE_HOURS, False


def orphans(open_pkgs: Iterable[Dict[str, Any]], reviews: Iterable[Dict[str, Any]], now: datetime, *,
            cadence_hours: float = CADENCE_HOURS, slack_hours: float = SLACK_HOURS,
            skip_closed_markets: bool = False) -> List[Dict[str, Any]]:
    """Open desk packages with no desk decision inside cadence + slack. Pure; a flag, never a gate.
    ``skip_closed_markets``: a package whose market is closed at *now* gets no scheduled slot (trigger-first) and is
    not listed.

    A package whose last decision time cannot be read is listed with ``last_decision_at: None`` (could not look
    is never read as owned)."""
    bound = timedelta(hours=cadence_hours + slack_hours)
    reviews = list(reviews)
    out = []
    for p in open_pkgs:
        if str(p.get("strategy_name") or p.get("strategy") or "") != DESK_LEG:
            continue
        if skip_closed_markets:
            from src.runtime.live_review_due import package_market_state  # noqa: PLC0415
            if not package_market_state(p.get("symbol"), now)[0]:
                continue
        last = last_decision_at(p, reviews)
        if last is None or now - last > bound:
            out.append({"order_package_id": p.get("order_package_id"), "symbol": p.get("symbol"),
                        "last_decision_at": last.isoformat() if last else None,
                        "age_h": round((now - last).total_seconds() / 3600, 2) if last else None})
    return out

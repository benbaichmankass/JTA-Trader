"""claude_desk — the Claude trading desk's own leg (DESK-17, design § 3.7).

The desk does not have an order path. It proposes; this leg turns each ACCEPTED proposal into ONE
order package that flows through the same ``intent multiplexer -> Coordinator.multi_account_execute``
path as every other leg, so the account's ``mode:``, the leg's ``execution:``, roster membership and
each account's own ``RiskManager`` decide what happens, exactly as for any leg.

Where proposals come from
-------------------------
``scripts/ops/desk_intake.py`` (DESK-4) validates every desk decision row and appends one line per
accepted ``propose_entry`` to ``runtime_logs/desk/accepted_proposals.jsonl``:
``{at, decision_id, intent_id, packet_id, packet_sha, ref, proposal}``. It only does so once
``MD-TRADE-DESK.functions.entry_generation.blocked_until`` is cleared AND this leg is in
``config/strategies.yaml`` — today the mandate field blocks, so the queue is empty and this leg
emits nothing.

What this module decides (pure; the builder in ``strategy_signal_builders`` does the I/O)
---------------------------------------------------------------------------------------
* **Both brackets, always.** A proposal without a finite stop level AND a finite TP level is
  refused ``both_brackets_required`` (operator 2026-10-26). The geometry must be coherent
  (long: stop < entry < tp; short: tp < entry < stop) or it is refused ``bracket_geometry``.
* **The bracket is the proposal's.** entry / sl / tp are the proposal's levels, never re-derived
  from a class default, so the TP is the desk's own prediction (``tp.basis`` + ``tp.p_hit``).
* **No size.** The proposal carries none and the package carries none; each account's
  ``RiskManager`` sizes it. ``confidence`` is the leg's declared ``confidence`` (default 0.5); the
  RiskManager's confidence scalar can only size DOWN from the account basis.
* **One package per proposal.** A proposal whose ``decision_id`` already sits on a ``claude_desk``
  order package is consumed. Consumption is read from the journal, not from a side file, so a
  proposal debounced, regime-dropped or out-voted before a package was minted is retried on later
  bars until it expires.
* **Expiry.** A proposal not consumed within ``entry.good_till_bars`` bars of its timeframe from
  acceptance is ``expired_unfilled`` — an outcome, not an error.
* **Entry type.** Only ``market`` today. A ``limit`` / ``stop`` entry is refused
  ``entry_type_unsupported`` and recorded (the multiplexer path places at the signal price; a
  resting-entry adapter is follow-up work, filed on row DESK-17).

* **Max hold.** A proposal's ``max_hold_min`` (required and <= 60 on a live row: the short-hold kind,
  operator 2026-10-27 *"get in and get out quickly"*) rides in the package meta; ``monitor()`` closes the
  trade at market once that many minutes have passed since the package opened (reason ``max_hold``).

Otherwise ``monitor()`` returns ``None``: the venue bracket is the plan, and the desk's in-trade decisions
(``tp_revise`` / ``tighten_sl`` / ``close`` / ``partial_close``) reach a desk trade through the
per-account amend path (``scripts/ops/live_review_apply.py``, dispatched by desk intake), not
through this module.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

NAME = "claude_desk"
SIGNAL_LOGIC = "desk"
ROOT = Path(__file__).resolve().parents[3]

PROBE_CONFIDENCE = 0.05  # DESK-18E mechanics probe: the package confidence scalar, i.e. the smallest the sizing scalar allows to ask for
R_BRACKETS = "both_brackets_required"
R_GEOMETRY = "bracket_geometry"
R_SIDE = "side_invalid"
R_ENTRY_TYPE = "entry_type_unsupported"
R_SYMBOL = "symbol_missing"
R_EXPIRED = "expired_unfilled"

_TF = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$", re.I)
_TF_S = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def queue_path() -> Path:
    """Where desk intake appends accepted proposals (``desk_intake.log_dir()``)."""
    return ROOT / "runtime_logs" / "desk" / "accepted_proposals.jsonl"


def ledger_path() -> Path:
    """This leg's own outcome record: one line per (decision_id, outcome)."""
    return ROOT / "runtime_logs" / "desk" / "desk_leg.jsonl"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def norm_symbol(s: Any) -> str:
    return str(s or "").upper().replace("/", "").strip()


def timeframe_seconds(tf: Any) -> Optional[int]:
    m = _TF.match(str(tf or ""))
    return int(m.group(1)) * _TF_S[m.group(2).lower()] if m else None


def proposal_problem(proposal: Any) -> Optional[str]:
    """None when the proposal can become a package; else the named refusal. Pure."""
    p = proposal if isinstance(proposal, dict) else {}
    stop = _num((p.get("stop") or {}).get("level")) if isinstance(p.get("stop"), dict) else None
    tp = _num((p.get("tp") or {}).get("level")) if isinstance(p.get("tp"), dict) else None
    missing = [k for k, v in (("stop", stop), ("tp", tp)) if v is None or v <= 0]
    if missing:
        return f"{R_BRACKETS}:missing_{'+'.join(missing)}"
    if not norm_symbol(p.get("symbol")):
        return R_SYMBOL
    side = p.get("side")
    if side not in ("long", "short"):
        return f"{R_SIDE}:{side}"
    entry = p.get("entry") if isinstance(p.get("entry"), dict) else {}
    etype = entry.get("type")
    if etype != "market":
        return f"{R_ENTRY_TYPE}:{etype}"
    level = _num(entry.get("level"))
    if level is None or level <= 0:
        return f"{R_GEOMETRY}:entry_level_missing"
    ok = stop < level < tp if side == "long" else tp < level < stop
    if not ok:
        return f"{R_GEOMETRY}:{side} entry={level} stop={stop} tp={tp}"
    return None


def expires_at(row: Dict[str, Any]) -> Optional[datetime]:
    """Acceptance time + good_till_bars x timeframe. None when either is unreadable."""
    p = row.get("proposal") or {}
    at = _ts(row.get("at"))
    tf = timeframe_seconds(p.get("timeframe"))
    bars = (p.get("entry") or {}).get("good_till_bars") if isinstance(p.get("entry"), dict) else None
    if at is None or tf is None or not isinstance(bars, int) or isinstance(bars, bool) or bars < 1:
        return None
    return at + timedelta(seconds=tf * bars)


def order_package(cfg: dict, row: Dict[str, Any]) -> Dict[str, Any]:
    """One accepted-proposal row -> the ``{symbol, direction, entry, sl, tp, confidence, meta}``
    dict every unit returns. Raises ``ValueError`` (named) for a proposal that cannot trade."""
    p = row.get("proposal") if isinstance(row, dict) else None
    why = proposal_problem(p)
    if why:
        raise ValueError(why)
    conf = _num((cfg or {}).get("confidence"))
    conf = 0.5 if conf is None else max(0.0, min(1.0, conf))
    probe = bool(row.get("mechanics_probe"))
    if probe:  # DESK-18E: minimum size via the documented confidence scalar (it only sizes DOWN); the RiskManager still sizes it
        conf = min(conf, PROBE_CONFIDENCE)
    return {
        "symbol": norm_symbol(p["symbol"]),
        "direction": p["side"],
        "entry": float(p["entry"]["level"]),
        "sl": float(p["stop"]["level"]),
        "tp": float(p["tp"]["level"]),
        "confidence": conf,
        "meta": {
            "signal_logic": SIGNAL_LOGIC,
            "decision_id": row.get("decision_id"),
            "intent_id": row.get("intent_id"),
            "packet_id": row.get("packet_id"),
            "packet_sha": row.get("packet_sha"),
            "desk_ref": row.get("ref"),
            "accepted_at": row.get("at"),
            "timeframe": p.get("timeframe"),
            "horizon_bars": p.get("horizon_bars"),
            "good_till_bars": p["entry"].get("good_till_bars"),
            "stop_basis": p["stop"].get("basis"),
            "tp_basis": p["tp"].get("basis"),
            "tp_p_hit": p["tp"].get("p_hit"),
            "expected_r_net": p.get("expected_r_net"),
            "novelty": p.get("novelty"),
            "venue_class": p.get("venue_class"),
            "max_hold_min": p.get("max_hold_min"),
            "mechanics_probe": probe,
        },
    }


def read_queue(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every parseable row of the accepted-proposals queue; a missing file is an empty queue."""
    q = path or queue_path()
    try:
        text = q.read_text()
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("decision_id"):
            out.append(r)
    return out


def consumed_decision_ids(packages: Iterable[Dict[str, Any]]) -> set:
    """decision_ids already carried by a claude_desk order package (journal ``meta`` JSON)."""
    out = set()
    for pkg in packages or []:
        meta = pkg.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = None
        if isinstance(meta, dict) and meta.get("decision_id"):
            out.add(str(meta["decision_id"]))
    return out


def select(rows: List[Dict[str, Any]], *, symbol: str, consumed: set, now: datetime,
           cfg: Optional[dict] = None) -> Tuple[Optional[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
    """(package for this tick's symbol or None, [(row, terminal outcome)]). Pure.

    Oldest unconsumed, unexpired, valid proposal on ``symbol`` wins; the multiplexer debounce and the
    one-open-package-per-strategy-per-symbol gate keep a second one waiting for a later bar. Rows on
    other symbols are left for their own tick. A refused or expired row is reported once per call;
    the builder records it once (the ledger dedupes)."""
    sym = norm_symbol(symbol)
    chosen: Optional[Dict[str, Any]] = None
    terminal: List[Tuple[Dict[str, Any], str]] = []
    seen = set()
    for row in rows:
        did = str(row.get("decision_id"))
        if did in consumed or did in seen:
            continue
        seen.add(did)
        p = row.get("proposal") if isinstance(row.get("proposal"), dict) else {}
        if norm_symbol(p.get("symbol")) != sym:
            continue
        why = proposal_problem(p)
        if why:
            terminal.append((row, why))
            continue
        exp = expires_at(row)
        if exp is None or now >= exp:
            terminal.append((row, R_EXPIRED if exp is not None else f"{R_EXPIRED}:expiry_unreadable"))
            continue
        if chosen is None:
            chosen = order_package(cfg or {}, row)
    return chosen, terminal


def record(outcomes: List[Tuple[Dict[str, Any], str]], *, now: datetime,
           path: Optional[Path] = None) -> int:
    """Append each (decision_id, outcome) to the leg ledger once. Returns lines written. Never raises."""
    if not outcomes:
        return 0
    lp = path or ledger_path()
    try:
        done = {(r.get("decision_id"), r.get("outcome")) for r in read_queue(lp)}
        lp.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with lp.open("a") as fh:
            for row, outcome in outcomes:
                key = (row.get("decision_id"), outcome)
                if key in done:
                    continue
                done.add(key)
                fh.write(json.dumps({"at": now.isoformat(), "decision_id": row.get("decision_id"),
                                     "intent_id": row.get("intent_id"), "outcome": outcome},
                                    separators=(",", ":")) + "\n")
                n += 1
        return n
    except OSError:
        return 0


R_MAX_HOLD = "max_hold"


def max_hold_verdict(open_pkg: Any, now: datetime) -> Optional[Dict[str, Any]]:
    """``{"action": "close", "reason": "max_hold"}`` once ``meta.max_hold_min`` minutes have passed since the
    package opened; None otherwise (no max hold, or an unreadable open time -- the bracket still holds). Pure."""
    pkg = open_pkg if isinstance(open_pkg, dict) else {}
    meta = pkg.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    meta = meta if isinstance(meta, dict) else {}
    mh = meta.get("max_hold_min")
    if not isinstance(mh, int) or isinstance(mh, bool) or mh < 1:
        return None
    opened = _ts(meta.get("entry_time") or pkg.get("created_at"))
    if opened is None or now - opened < timedelta(minutes=mh):
        return None
    return {"action": "close", "reason": R_MAX_HOLD}


def monitor(cfg, candles_df, open_pkg):  # noqa: ARG001 -- canonical signature
    """Only the max-hold time stop: the proposal's venue bracket is the plan, and the desk's own
    in-trade/exit decisions reach the trade through the per-account amend path (desk intake ->
    live_review_apply), never through a monitor verdict."""
    return max_hold_verdict(open_pkg, datetime.now(timezone.utc))

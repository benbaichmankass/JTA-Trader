"""Live trade review -- L0 due computation (docs/plans/live-trade-review-DESIGN.md s1-2).

Which OPEN order packages are due for a review right now, and why.

PURE READ. It takes the open telemetry rows, the review log and the declared
thresholds (``config/live_trade_review.yaml``) and returns the due list. It
writes nothing, adds no writer to the exit loop and cannot refuse a trade.

Two read states, never collapsed (CLAUDE.md "a count that reads 0 may mean we
could not look"):

* ``looked`` -- ``due_count`` is a real number; ``0`` means nothing is due.
* ``could_not_look`` -- ``due_count`` / ``open_count`` are ``None`` and
  ``reason`` says why. A gate must NOT treat this as "nothing due".

Dedupe: each event is keyed on ``(order_package_id, event, level)`` against
``comms/live_review/reviews.jsonl``. Cooldown: at most one review per closed bar
of the leg's timeframe, except the events in ``cooldown_exempt``.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

CONFIG_REL = os.path.join("config", "live_trade_review.yaml")
REVIEWS_REL = os.path.join("comms", "live_review", "reviews.jsonl")

_TF_RE = re.compile(r"_(\d+)(m|h|d)$")
_TF_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    import yaml
    if path is None:
        from src.utils.paths import repo_root
        path = os.path.join(repo_root(), CONFIG_REL)
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    due = raw.get("due")
    if not isinstance(due, dict) or not isinstance(due.get("events"), dict):
        raise ValueError(f"{path}: missing due.events")
    return due


def timeframe_seconds(strategy: Optional[str], default_tf: str) -> int:
    """Leg timeframe from its name suffix (``ada_pullback_2h`` -> 7200)."""
    m = _TF_RE.search(strategy or "") or _TF_RE.search("_" + default_tf)
    return int(m.group(1)) * _TF_SECONDS[m.group(2)] if m else 7200


def bar_start(now: datetime, tf_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % tf_seconds, tz=timezone.utc)


def read_reviews(path: Optional[str] = None) -> Dict[str, Any]:
    """Read the review log. ``state`` in absent / read / unreadable.

    ``absent`` is a real answer (no review has ever been recorded) and is not
    folded into ``unreadable`` (the file exists but cannot be opened).
    """
    if path is None:
        from src.utils.paths import repo_root
        path = os.path.join(repo_root(), REVIEWS_REL)
    if not os.path.exists(path):
        return {"state": "absent", "rows": [], "bad_lines": 0}
    rows: List[Dict[str, Any]] = []
    bad = 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    bad += 1
    except OSError as exc:
        return {"state": "unreadable", "rows": [], "bad_lines": 0, "error": str(exc)}
    return {"state": "read", "rows": rows, "bad_lines": bad}


def _review_index(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per package: fired (event, level) keys, last review time, max reviewed peak."""
    idx: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pkg = r.get("order_package_id")
        if not pkg:
            continue
        slot = idx.setdefault(str(pkg), {"fired": set(), "last": None, "peak": None})
        trig = r.get("trigger") or {}
        slot["fired"].add((str(trig.get("event")), _lvl(trig.get("level"))))
        ts = _parse_ts(r.get("reviewed_at") or trig.get("l0_snapshot_at"))
        if ts and (slot["last"] is None or ts > slot["last"]):
            slot["last"] = ts
        pk = _f((r.get("state") or {}).get("peak_r"))
        if pk is not None and (slot["peak"] is None or pk > slot["peak"]):
            slot["peak"] = pk
    return idx


def _lvl(level: Any) -> str:
    """Canonical level key, so 1, 1.0 and "1" dedupe as one."""
    x = _f(level) if not isinstance(level, str) or re.fullmatch(r"-?[\d.]+", level) else None
    return f"{x:g}" if x is not None else str(level)


def _bucket(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def candidate_events(row: Dict[str, Any], prior: Dict[str, Any],
                     cfg: Dict[str, Any], now: datetime,
                     floor_accounts: Set[str]) -> List[Tuple[str, Any, str]]:
    """``(event, level, why)`` for every event that currently holds, deduped."""
    ev = cfg["events"]
    out: List[Tuple[str, Any, str]] = []
    open_r, peak_r = _f(row.get("open_r")), _f(row.get("peak_r"))
    giveback, to_tp = _f(row.get("giveback_r")), _f(row.get("r_to_target"))

    m = ev.get("r_milestone") or {}
    first, step = float(m.get("first_r", 1.0)), float(m.get("step_r", 1.0))
    if open_r is not None and open_r >= first:
        lvl = first + _bucket(open_r - first, step)
        out.append(("r_milestone", lvl, f"open_r {open_r:.2f} crossed +{lvl:g}R"))

    n = ev.get("new_peak") or {}
    if peak_r is not None and prior["peak"] is not None:
        if peak_r >= prior["peak"] + float(n.get("step_r", 0.5)):
            out.append(("new_peak", _bucket(peak_r, float(n.get("step_r", 0.5))),
                        f"peak_r {peak_r:.2f} vs last reviewed {prior['peak']:.2f}"))

    g = ev.get("giveback") or {}
    if peak_r is not None and giveback is not None \
            and peak_r >= float(g.get("min_peak_r", 1.0)):
        need = max(float(g.get("min_giveback_r", 0.5)),
                   float(g.get("giveback_frac_of_peak", 0.3)) * peak_r)
        if giveback >= need:
            out.append(("giveback", _bucket(peak_r, 0.5),
                        f"gave back {giveback:.2f}R of {peak_r:.2f}R peak (need {need:.2f})"))

    t = ev.get("near_target") or {}
    if to_tp is not None and 0 <= to_tp <= float(t.get("max_r_to_target", 0.5)):
        out.append(("near_target", 0, f"{to_tp:.2f}R to target"))

    d = ev.get("daily_floor") or {}
    if str(row.get("account_id")) in floor_accounts:
        age = None if prior["last"] is None else now - prior["last"]
        if age is None or age >= timedelta(hours=float(d.get("hours", 24))):
            out.append(("daily_floor", now.strftime("%Y-%m-%d"),
                        "never reviewed" if age is None
                        else f"last review {age.total_seconds() / 3600:.1f}h ago"))
    return out


def compute_due(rows: List[Dict[str, Any]], reviews: List[Dict[str, Any]],
                cfg: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Due packages from OPEN telemetry rows. Pure; no I/O."""
    now = now or datetime.now(timezone.utc)
    idx = _review_index(reviews)
    floor_accounts = set((cfg["events"].get("daily_floor") or {}).get("accounts") or [])
    exempt = set(cfg.get("cooldown_exempt") or [])
    stale_after = timedelta(minutes=float(cfg.get("stale_telemetry_minutes", 30)))
    default_tf = str(cfg.get("default_timeframe", "2h"))

    due: List[Dict[str, Any]] = []
    cooled = 0
    for row in rows:
        pkg = str(row.get("order_package_id"))
        prior = idx.get(pkg, {"fired": set(), "last": None, "peak": None})
        tf = timeframe_seconds(row.get("strategy"), default_tf)
        in_cooldown = prior["last"] is not None and prior["last"] >= bar_start(now, tf)
        events = []
        for name, level, why in candidate_events(row, prior, cfg, now, floor_accounts):
            if (name, _lvl(level)) in prior["fired"]:
                continue
            if in_cooldown and name not in exempt and name != "daily_floor":
                continue
            events.append({"event": name, "level": level, "why": why})
        if not events:
            if in_cooldown:
                cooled += 1
            continue
        upd = _parse_ts(row.get("updated_at"))
        due.append({
            "order_package_id": pkg,
            "trade_id": row.get("trade_id"),
            "leg": row.get("strategy"),
            "account_id": row.get("account_id"),
            "symbol": row.get("symbol"),
            "direction": row.get("direction"),
            "timeframe_seconds": tf,
            "bar_start": bar_start(now, tf).isoformat(),
            "events": events,
            "state": {k: row.get(k) for k in (
                "open_r", "peak_r", "peak_state", "giveback_r", "bars_held",
                "r_to_stop", "r_to_target", "rr_from_here")},
            "telemetry_updated_at": row.get("updated_at"),
            "telemetry_stale": bool(upd is None or now - upd > stale_after),
        })
    return {"due": due, "due_count": len(due), "suppressed_by_cooldown": cooled}


def live_review_due(db_path: Optional[str] = None,
                    config_path: Optional[str] = None,
                    reviews_path: Optional[str] = None,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """The route payload. Never raises."""
    now = now or datetime.now(timezone.utc)
    env: Dict[str, Any] = {
        "generated_at": now.isoformat(), "read_state": "could_not_look",
        "reason": None, "open_count": None, "due_count": None, "due": [],
        "reviews_state": None, "events_not_evaluated": [],
    }
    try:
        cfg = load_config(config_path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        env["reason"] = f"config_unreadable: {type(exc).__name__}: {exc}"
        return env
    env["events_not_evaluated"] = list(cfg.get("not_evaluated") or [])
    env["thresholds_source"] = CONFIG_REL.replace(os.sep, "/")

    rv = read_reviews(reviews_path)
    env["reviews_state"] = rv["state"]
    env["review_bad_lines"] = rv["bad_lines"]
    if rv["state"] == "unreadable":
        # Dedupe is unreliable without the log; a gate would re-fire everything.
        env["reason"] = f"reviews_unreadable: {rv.get('error')}"
        return env

    try:
        from src.runtime.position_telemetry import read_records
        tel = read_records(db_path=db_path, limit=1000)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        env["reason"] = f"telemetry_unavailable: {type(exc).__name__}: {exc}"
        return env
    if tel.get("error"):
        env["reason"] = f"telemetry_error: {tel['error']}"
        return env
    if not tel.get("present"):
        env["reason"] = "telemetry_table_absent"
        return env

    open_rows = [r for r in tel.get("rows", []) if r.get("lifecycle") == "open"]
    res = compute_due(open_rows, rv["rows"], cfg, now)
    env.update(res)
    env["open_count"] = len(open_rows)
    env["read_state"] = "looked"
    env["oldest_due_bar_start"] = min(
        (d["bar_start"] for d in res["due"]), default=None)
    return env

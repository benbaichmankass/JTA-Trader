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

Market triggers (LTR-1B-MARKET-TRIGGERS): ``swing`` and ``vol_regime`` read the
per-bar ``position_path_history`` the exit loop writes; ``funding`` reads the
``exchange_funding`` store; ``calendar`` reads ``config/economic_calendar.yaml``;
``mechanics`` (journal half) reads telemetry rows whose trade is absent. Each
package says per event whether it looked: an event it could not evaluate is
listed in ``events_could_not_look`` with the reason, never silently dropped.
"""
from __future__ import annotations

import ast
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

CONFIG_REL = os.path.join("config", "live_trade_review.yaml")
REVIEWS_REL = os.path.join("comms", "live_review", "reviews.jsonl")
CALENDAR_REL = os.path.join("config", "economic_calendar.yaml")

#: Events computed from market inputs (history / funding / calendar).
MARKET_EVENTS = ("swing", "vol_regime", "funding", "calendar")

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


# ---------------------------------------------------------------------------
# Market triggers (LTR-1B). Pure functions over inputs read by the loaders
# below. Each returns (events, could_not_look) so a skipped event is visible.
# ---------------------------------------------------------------------------

def _base_of(symbol: Any) -> str:
    base = str(symbol or "").upper().split("/")[0]
    for suffix in ("USDT", "PERP", "USD"):
        if base.endswith(suffix) and base != suffix:
            return base[: -len(suffix)]
    return base


def _is_perp(symbol: Any) -> bool:
    try:
        from src.runtime.execution_costs import is_perp
        return bool(is_perp(symbol))
    except Exception:  # noqa: BLE001  # allow-silent: heuristic fallback, mirrors is_perp's own
        return str(symbol or "").upper().endswith("USDT")


def _funding_assumption_bps(symbol: Any) -> Optional[float]:
    try:
        from src.runtime.execution_costs import funding_bps_per_window_for
        return float(funding_bps_per_window_for(symbol))
    except Exception:  # noqa: BLE001  # allow-silent: surfaced as could_not_look by the caller
        return None


def market_events(row: Dict[str, Any], ctx: Optional[Dict[str, Any]],
                  cfg: Dict[str, Any], now: datetime,
                  tf_seconds: int) -> Tuple[List[Tuple[str, Any, str]], List[Dict[str, str]]]:
    """``(events, could_not_look)`` for swing / vol_regime / funding / calendar."""
    ev = cfg["events"]
    out: List[Tuple[str, Any, str]] = []
    cnl: List[Dict[str, str]] = []

    def miss(name: str, reason: str) -> None:
        cnl.append({"event": name, "reason": reason})

    if ctx is None:
        for name in MARKET_EVENTS:
            miss(name, "market inputs not read")
        return out, cnl

    # -- swing / vol_regime: the per-bar path history ------------------------
    hist = ctx.get("history")
    if hist is None:
        reason = f"history_unavailable: {ctx.get('history_reason') or 'unknown'}"
        miss("swing", reason)
        miss("vol_regime", reason)
    else:
        pts = [h for h in hist if _f(h.get("last_price")) is not None]
        sw = ev.get("swing") or {}
        if len(pts) < 2:
            miss("swing", f"{len(pts)} history bar(s) with a price; need 2")
        else:
            prev, cur = pts[-2], pts[-1]
            atr = _f(prev.get("atr")) or _f(cur.get("atr"))
            if not atr or atr <= 0:
                miss("swing", "no ATR on the last two history bars")
            else:
                move = abs(_f(cur["last_price"]) - _f(prev["last_price"]))
                k = float(sw.get("atr_multiple", 2.0))
                if move >= k * atr:
                    out.append(("swing", str(cur.get("bar_ts")),
                                f"close-to-close {move:.6g} >= {k:g} x ATR {atr:.6g}"))

        vr = ev.get("vol_regime") or {}
        atrs = [h for h in hist if (_f(h.get("atr")) or 0) > 0]
        bars_held = _f(row.get("bars_held"))
        first_ts = _parse_ts(atrs[0].get("bar_ts")) if atrs else None
        last_ts = _parse_ts(atrs[-1].get("bar_ts")) if atrs else None
        if not atrs or first_ts is None or last_ts is None:
            miss("vol_regime", "no history bar with an ATR")
        elif bars_held is None:
            miss("vol_regime", "bars_held unknown: cannot place the entry bar")
        else:
            entry_bar = last_ts - timedelta(seconds=bars_held * tf_seconds)
            late = (first_ts - entry_bar).total_seconds()
            if late > tf_seconds + 60:
                miss("vol_regime", f"history starts {late / tf_seconds:.1f} bars after entry")
            else:
                a0, a1 = _f(atrs[0]["atr"]), _f(atrs[-1]["atr"])
                ratio = a1 / a0
                up, dn = float(vr.get("expand_ratio", 1.5)), float(vr.get("contract_ratio", 0.67))
                if ratio >= up:
                    out.append(("vol_regime", "expand", f"ATR now/entry {ratio:.2f} >= {up:g}"))
                elif ratio <= dn:
                    out.append(("vol_regime", "contract", f"ATR now/entry {ratio:.2f} <= {dn:g}"))

    # -- funding: crypto perps only ------------------------------------------
    sym = row.get("symbol")
    if _is_perp(sym):
        fd = ctx.get("funding") or {"state": "could_not_look", "reason": "funding not read"}
        fc = ev.get("funding") or {}
        assumption = _funding_assumption_bps(sym)
        if fd.get("state") != "read":
            miss("funding", str(fd.get("reason") or "funding not read"))
        elif assumption is None or assumption <= 0:
            miss("funding", "no backtest funding assumption for symbol")
        elif fd.get("row") is not None:
            fr = fd["row"]
            rate_bps = _f(fr.get("rate_bps"))
            paid = (_f(fr.get("funding_usd")) or 0.0) < 0
            mult = float(fc.get("assumption_multiple", 3.0))
            if rate_bps is None:
                miss("funding", "settlement row carries no funding rate")
            elif paid and abs(rate_bps) >= mult * assumption:
                out.append(("funding", str(fr.get("funding_time")),
                            f"paid at {abs(rate_bps):.2f} bps vs {assumption:g} bps assumed "
                            f"(>= {mult:g}x)"))

    # -- calendar --------------------------------------------------------------
    cal = ctx.get("calendar") or {"state": "could_not_look", "reason": "calendar not read"}
    cc = ev.get("calendar") or {}
    if cal.get("state") != "read":
        miss("calendar", str(cal.get("reason") or cal.get("state")))
    else:
        base = _base_of(sym)
        classes = {str(c).lower() for c in (cal.get("classes") or {}).get(base) or []}
        if not classes:
            miss("calendar", f"no event classes declared for {base}")
        else:
            horizon = now + timedelta(seconds=tf_seconds)
            min_impact = float(cc.get("min_impact", 0.8))
            for e in cal.get("events") or []:
                et, imp = _parse_ts(e.get("time")), _f(e.get("impact"))
                cls = str(e.get("class", "")).lower()
                if et and imp is not None and cls in classes and imp >= min_impact \
                        and now <= et <= horizon:
                    out.append(("calendar", f"{cls}@{et.isoformat()}",
                                f"{cls} (impact {imp:g}) at {et.isoformat()} within the next bar"))
    return out, cnl


def compute_due(rows: List[Dict[str, Any]], reviews: List[Dict[str, Any]],
                cfg: Dict[str, Any], now: Optional[datetime] = None,
                market: Optional[Dict[str, Dict[str, Any]]] = None,
                mechanics_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Due packages from OPEN telemetry rows. Pure; no I/O.

    ``market`` maps order_package_id -> the inputs ``market_events`` reads; a
    package missing from it reports every market event as could_not_look.
    ``mechanics_rows`` are telemetry rows the exit loop still writes whose
    trade row is absent (the journal half of the ``mechanics`` event).
    """
    now = now or datetime.now(timezone.utc)
    idx = _review_index(reviews)
    floor_accounts = set((cfg["events"].get("daily_floor") or {}).get("accounts") or [])
    exempt = set(cfg.get("cooldown_exempt") or [])
    stale_after = timedelta(minutes=float(cfg.get("telemetry_max_age_minutes", 30)))
    default_tf = str(cfg.get("default_timeframe", "2h"))

    due: List[Dict[str, Any]] = []
    cooled = 0
    cnl_total = 0
    for row in rows:
        pkg = str(row.get("order_package_id"))
        prior = idx.get(pkg, {"fired": set(), "last": None, "peak": None})
        tf = timeframe_seconds(row.get("strategy"), default_tf)
        in_cooldown = prior["last"] is not None and prior["last"] >= bar_start(now, tf)
        events = []
        mk, cnl = market_events(row, (market or {}).get(pkg), cfg, now, tf)
        if cnl:
            cnl_total += 1
        for name, level, why in candidate_events(row, prior, cfg, now, floor_accounts) + mk:
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
            "events_could_not_look": cnl,
        })

    mech_on = bool((cfg["events"].get("mechanics") or {}).get("journal_trade_absent", True))
    for row in (mechanics_rows or []) if mech_on else []:
        pkg = str(row.get("order_package_id"))
        prior = idx.get(pkg, {"fired": set(), "last": None, "peak": None})
        if ("mechanics", _lvl("journal_trade_absent")) in prior["fired"]:
            continue
        upd = _parse_ts(row.get("updated_at"))
        if upd is None or now - upd > stale_after:
            continue  # not being written now: a finished row, not a live mismatch
        tf = timeframe_seconds(row.get("strategy"), default_tf)
        due.append({
            "order_package_id": pkg, "trade_id": row.get("trade_id"),
            "leg": row.get("strategy"), "account_id": row.get("account_id"),
            "symbol": row.get("symbol"), "direction": row.get("direction"),
            "timeframe_seconds": tf, "bar_start": bar_start(now, tf).isoformat(),
            "events": [{"event": "mechanics", "level": "journal_trade_absent",
                        "why": f"exit loop writing telemetry for trade {row.get('trade_id')} "
                               "but the trades table has no such row"}],
            "state": {k: row.get(k) for k in ("open_r", "peak_r", "r_to_stop", "r_to_target")},
            "telemetry_updated_at": row.get("updated_at"),
            "telemetry_stale": False,
            "events_could_not_look": [],
        })
    return {"due": due, "due_count": len(due), "suppressed_by_cooldown": cooled,
            "packages_with_events_could_not_look": cnl_total}


def read_calendar(path: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The economic calendar, read fresh (no cache: git-sync updates the file).

    ``state`` read / could_not_look. A calendar whose newest event is already
    past is STALE and reads could_not_look: an empty future is not known.
    """
    import yaml
    now = now or datetime.now(timezone.utc)
    if path is None:
        from src.utils.paths import repo_root
        path = os.path.join(repo_root(), CALENDAR_REL)
    if not os.path.exists(path):
        return {"state": "could_not_look", "reason": "calendar_absent"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        return {"state": "could_not_look", "reason": f"calendar_unreadable: {type(exc).__name__}"}
    events = [e for e in (raw.get("events") or []) if isinstance(e, dict)]
    times = [t for t in (_parse_ts(e.get("time")) for e in events) if t]
    newest = max(times) if times else None
    if newest is None or newest < now:
        return {"state": "could_not_look", "newest_event": newest.isoformat() if newest else None,
                "reason": f"calendar_stale: newest event {newest.isoformat() if newest else 'none'}"}
    return {"state": "read", "events": events, "newest_event": newest.isoformat(),
            "classes": {str(k).upper(): v for k, v in (raw.get("symbol_event_classes") or {}).items()}}


def _rate_bps(raw: Any) -> Optional[float]:
    """Funding rate in bps from a stored settlement's raw venue record."""
    doc = raw
    if isinstance(raw, str):
        try:
            doc = json.loads(raw)
        except ValueError:
            try:
                doc = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                return None
    if not isinstance(doc, dict):
        return None
    for key in ("feeRate", "fundingRate", "funding_rate"):
        v = _f(doc.get(key))
        if v is not None:
            return v * 1e4
    return None


def read_funding(account_id: Any, symbol: Any, now: datetime, window_hours: float,
                 db_path: Optional[str] = None) -> Dict[str, Any]:
    """Latest funding settlement for (account, symbol) within the window.

    could_not_look when the store is absent, or when the account has no
    settlement at all in 24 h (the puller is not writing for it), so "no
    settlement for this symbol" is only reported once we know the store is live.
    """
    if db_path is None:
        try:
            from src.runtime.exchange_fills_store import get_fills_db_path
            db_path = str(get_fills_db_path())
        except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
            return {"state": "could_not_look", "reason": f"funding_store_path: {type(exc).__name__}"}
    if not os.path.exists(db_path):
        return {"state": "could_not_look", "reason": "funding_store_absent"}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            day = (now - timedelta(hours=24)).isoformat()
            n = conn.execute("SELECT COUNT(*) FROM exchange_funding WHERE account_id = ? "
                             "AND funding_time >= ?", (str(account_id), day)).fetchone()[0]
            if not n:
                return {"state": "could_not_look",
                        "reason": f"no funding settlement for {account_id} in 24h (puller not writing?)"}
            since = (now - timedelta(hours=window_hours)).isoformat()
            r = conn.execute("SELECT funding_usd, funding_time, raw FROM exchange_funding "
                             "WHERE account_id = ? AND symbol IN (?, ?) AND funding_time >= ? "
                             "ORDER BY funding_time DESC LIMIT 1",
                             (str(account_id), str(symbol), _ccxt_symbol(symbol), since)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"state": "could_not_look", "reason": f"funding_store_error: {exc}"}
    if r is None:
        return {"state": "read", "row": None}
    return {"state": "read", "row": {"funding_usd": r[0], "funding_time": r[1],
                                     "rate_bps": _rate_bps(r[2])}}


def _ccxt_symbol(symbol: Any) -> str:
    """``ADAUSDT`` -> ``ADA/USDT:USDT`` (ccxt's linear-perp form, which the puller stores)."""
    s = str(symbol or "").upper()
    return f"{s[:-4]}/USDT:USDT" if s.endswith("USDT") and "/" not in s else s


def read_market_context(open_rows: List[Dict[str, Any]], cfg: Dict[str, Any], now: datetime,
                        db_path: Optional[str] = None, funding_db_path: Optional[str] = None,
                        calendar_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Per package: path history, funding and the (shared) calendar. Never raises."""
    cal = read_calendar(calendar_path, now)
    win = float((cfg["events"].get("funding") or {}).get("window_hours", 9))
    out: Dict[str, Dict[str, Any]] = {}
    for row in open_rows:
        pkg = str(row.get("order_package_id"))
        ctx: Dict[str, Any] = {"calendar": cal, "history": None, "history_reason": None}
        try:
            from src.runtime.position_path_history import read_history
            h = read_history(db_path=db_path, order_package_id=pkg, limit=2000)
            if h.get("error"):
                ctx["history_reason"] = f"history_error: {h['error']}"
            elif not h.get("present"):
                ctx["history_reason"] = "history_table_absent"
            else:
                ctx["history"] = h.get("rows") or []
        except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
            ctx["history_reason"] = f"{type(exc).__name__}: {exc}"
        if _is_perp(row.get("symbol")):
            ctx["funding"] = read_funding(row.get("account_id"), row.get("symbol"), now, win,
                                          funding_db_path)
        out[pkg] = ctx
    return out


def live_review_due(db_path: Optional[str] = None,
                    config_path: Optional[str] = None,
                    reviews_path: Optional[str] = None,
                    now: Optional[datetime] = None,
                    funding_db_path: Optional[str] = None,
                    calendar_path: Optional[str] = None) -> Dict[str, Any]:
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
    mech_rows = [r for r in tel.get("rows", []) if r.get("lifecycle") == "unknown_trade_absent"]
    market = read_market_context(open_rows, cfg, now, db_path, funding_db_path, calendar_path)
    res = compute_due(open_rows, rv["rows"], cfg, now, market=market, mechanics_rows=mech_rows)
    env.update(res)
    env["open_count"] = len(open_rows)
    cal = next(iter(market.values()), {}).get("calendar") if market else None
    env["calendar_state"] = (cal or {}).get("state")
    env["calendar_newest_event"] = (cal or {}).get("newest_event")
    env["read_state"] = "looked"
    env["oldest_due_bar_start"] = min(
        (d["bar_start"] for d in res["due"]), default=None)
    return env

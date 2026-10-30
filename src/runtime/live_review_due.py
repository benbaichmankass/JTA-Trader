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
``mechanics`` (journal half) reads telemetry rows whose trade is absent;
``mechanics`` (venue half, LTR-MECHANICS-VENUE-SNAPSHOT) fires level
``venue_sl_diverges`` when the resting stop the exit loop's broker sweeps last
read at the venue (``venue_protection_snapshot``) differs from
``order_packages.sl`` by more than the registered ``venue_sl_tolerance_atr`` x
ATR. Each package says per event whether it looked: an event it could not evaluate is
listed in ``events_could_not_look`` with the reason, never silently dropped.

Telemetry-less packages (LTR-DUE-TELEMETRY-LESS): ``position_telemetry`` covers
only the donchian/pullback family, so an open package of another leg has no
telemetry row. The open set is therefore the UNION of the open telemetry rows
and the journal's open ``order_packages`` / ``trades`` (the same sources
``scripts/ops/live_review_packet.py --all-open`` unions, minus the prop-ticket
HTTP read), and every package outside telemetry is listed in
``telemetry_less`` with ``telemetry_state: telemetry_absent`` and the four
telemetry events in ``events_could_not_look``. ``daily_floor`` and the market
events need no telemetry and still evaluate for them.

Pre-screen (LTR-PRACTICE-REDESIGN, operator Tier-2 OK 2026-10-28): ``adverse_r``
(first crossing of each registered negative R level), ``stall`` (bars held past
the leg's timeframe threshold with no +0.5R progress), ``momentum_flip`` (k
closed bars against the position, net >= m x ATR) and ``structure_break`` (a
close beyond the since-entry extreme against the position). Each is evaluated on
every pass for every open package, only when configured; the history checks are
edge-triggered episodes with their own ``cooldown_bars``. Every evaluation is
returned in ``prescreen`` (one record per package, flagged or not) for the VM
wake poster to log; this module still writes nothing.
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

#: Events that need a position_telemetry row; unevaluable for a telemetry-less package.
TELEMETRY_EVENTS = ("r_milestone", "new_peak", "giveback", "near_target")

#: Events computed from market inputs (history / funding / calendar).
MARKET_EVENTS = ("swing", "vol_regime", "funding", "calendar")

#: Pre-screen events (LTR-PRACTICE-REDESIGN): evaluated only when configured.
#: The per-package auto mandate's review cadence (src/runtime/ltr_auto_mandate.py::CADENCE_EVENT).
CADENCE_EVENT = "mandate_cadence"
PRESCREEN_EVENTS = ("adverse_r", "stall", "momentum_flip", "structure_break")

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
    ordered = sorted(rows, key=lambda r: _parse_ts(r.get("reviewed_at"))
                     or datetime.min.replace(tzinfo=timezone.utc))
    for r in ordered:
        pkg = r.get("order_package_id")
        if not pkg:
            continue
        slot = idx.setdefault(str(pkg), {"fired": set(), "last": None, "peak": None, "mech": None})
        trig = r.get("trigger") or {}
        answered = _mechanics_answer(r)
        if answered is not None:
            slot["mech"] = answered
        elif (r.get("mechanics") or {}).get("verdict") == "match":
            slot["mech"] = None  # a later review read the mismatch as cleared
        slot["fired"].add((str(trig.get("event")), _lvl(trig.get("level"))))
        ts = _parse_ts(r.get("reviewed_at") or trig.get("l0_snapshot_at"))
        if ts and (slot["last"] is None or ts > slot["last"]):
            slot["last"] = ts
        pk = _f((r.get("state") or {}).get("peak_r"))
        if pk is not None and (slot["peak"] is None or pk > slot["peak"]):
            slot["peak"] = pk
    return idx


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_NUM_TOL = 2e-5  # relative; `%g` in a `why` string keeps 6 significant digits
VENUE_LEVEL, JOURNAL_LEVEL = "venue_sl_diverges", "journal_trade_absent"


def _mechanics_answer(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What mechanics evidence a review row answered, or ``None`` if it answered none.

    A row answers when it was triggered by a mechanics event or recommends
    ``flag_mechanics``. Rows written before ``trigger.level`` could carry a string
    (the schema said number|null) have a null level, so the level is inferred
    from the evidence; a mechanics-triggered row that says nothing more answers
    both mechanics levels. ``numbers`` are the prices the row quotes, which is
    what a later due computation compares against to see whether the evidence
    changed.
    """
    trig = r.get("trigger") or {}
    mech = r.get("mechanics") or {}
    event, level = trig.get("event"), trig.get("level")
    if event != "mechanics" and (r.get("recommendation") or {}).get("action") != "flag_mechanics":
        return None
    text = str(mech.get("evidence") or "")
    low = text.lower()
    levels: Set[str] = set()
    if event == "mechanics" and isinstance(level, str) and not _NUM_RE.fullmatch(level):
        levels.add(level)
    if re.search(r"venue\s+(sl|stop)", low):
        levels.add(VENUE_LEVEL)
    if re.search(r"trade absent|no such row|trades? table|journal trade", low):
        levels.add(JOURNAL_LEVEL)
    if not levels and event == "mechanics":
        levels = {VENUE_LEVEL, JOURNAL_LEVEL}
    if not levels:
        return None
    nums = [float(m) for m in _NUM_RE.findall(text)]
    st = r.get("state") or {}
    nums += [x for x in (_f(st.get("sl")), _f(st.get("tp"))) if x is not None]
    return {"levels": levels, "numbers": nums}


def _mechanics_fired(prior: Dict[str, Any], level: str, current: Optional[List[float]] = None) -> bool:
    """Has the latest unresolved mechanics review already answered ``level``?

    Re-surfaces on CHANGE, never on repetition: when ``current`` (the prices the
    due event is made of) names a price the answered row never quoted, the
    evidence moved and the package is due again.
    """
    ans = prior.get("mech")
    if not ans or level not in ans["levels"]:
        return False
    if current and ans["numbers"]:
        return all(any(abs(c - n) <= _NUM_TOL * max(abs(c), abs(n), 1e-12) for n in ans["numbers"])
                   for c in current)
    return True


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


def _venue_atr(ctx: Dict[str, Any], venue: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """``(atr, source)`` for the venue tolerance: newest path-history bar, else
    the package's own entry ATR. Never a guess: neither -> ``(None, None)``."""
    for h in reversed(ctx.get("history") or []):
        a = _f(h.get("atr"))
        if a and a > 0:
            return a, "position_path_history"
    a = _f(venue.get("meta_atr"))
    if a and a > 0:
        return a, "package_entry_atr"
    return None, None


def venue_events(row: Dict[str, Any], ctx: Optional[Dict[str, Any]], cfg: Dict[str, Any],
                 now: datetime, sig_out: Optional[List[float]] = None
                 ) -> Tuple[List[Tuple[str, Any, str]], List[Dict[str, str]]]:
    """``(events, could_not_look)`` for the mechanics VENUE half.

    Compares each account's last venue read of the package's resting stop to
    ``order_packages.sl``. Three snapshot states stay distinct: ``measured`` is
    graded; ``none_resting`` (flat / no stop leg) is NOT graded here -- the
    naked sweeps own it, and it is not reported as a miss because the venue WAS
    read; ``could_not_look`` (and a stale or package-moved snapshot) is listed
    in ``events_could_not_look``, never folded into "no divergence".
    Only evaluated when the tolerance is registered in the config. ``sig_out``, when
    given, receives the venue and package stop prices of every divergent account:
    the evidence ``compute_due`` compares against the last answered review.
    """
    mc = (cfg["events"].get("mechanics") or {})
    tol_atr = _f(mc.get("venue_sl_tolerance_atr"))
    out: List[Tuple[str, Any, str]] = []
    cnl: List[Dict[str, str]] = []
    if tol_atr is None:
        return out, cnl

    def miss(reason: str) -> None:
        cnl.append({"event": "mechanics", "reason": f"venue_sl: {reason}"})

    venue = (ctx or {}).get("venue")
    if venue is None:
        miss("venue snapshot not read")
        return out, cnl
    if venue.get("state") != "read":
        miss(str(venue.get("reason") or "venue snapshot unreadable"))
        return out, cnl
    snaps = venue.get("snapshots") or []
    if not snaps:
        miss("no venue snapshot row for this package (no broker sweep has read it yet)")
        return out, cnl
    pkg_sl = _f(venue.get("pkg_sl"))
    if pkg_sl is None:
        miss("package sl unreadable")
        return out, cnl
    atr, atr_src = _venue_atr(ctx or {}, venue)
    if atr is None:
        miss("no ATR (neither position_path_history nor the package's entry ATR)")
        return out, cnl
    tol = tol_atr * atr
    max_age = timedelta(minutes=float(mc.get("venue_snapshot_max_age_minutes", 60)))
    bad: List[str] = []
    for sn in snaps:
        acct = str(sn.get("account_id"))
        state = sn.get("read_state")
        if state == "none_resting":
            continue  # looked, nothing resting: the naked sweeps own it
        # collapsed-state: measured -- this is `venue_protection_snapshot.read_state`, not
        # `position_telemetry.peak_state`; the guard matches the bare word. The three
        # read states are branched on separately: none_resting above, measured here,
        # and every other value (could_not_look, unknown) is listed as a miss below.
        if state != "measured":
            miss(f"{acct}: {sn.get('read_reason') or state or 'unknown_state'}")
            continue
        read_at = _parse_ts(sn.get("read_at"))
        if read_at is None or now - read_at > max_age:
            miss(f"{acct}: snapshot older than {max_age.total_seconds() / 60:g} min")
            continue
        v_sl, ref = _f(sn.get("venue_sl")), _f(sn.get("ref_sl"))
        if v_sl is None:
            miss(f"{acct}: measured row carries no venue_sl")
            continue
        if ref is not None and abs(pkg_sl - ref) > tol:
            miss(f"{acct}: package sl moved since the venue read ({ref:g} -> {pkg_sl:g})")
            continue
        gap = abs(v_sl - pkg_sl)
        if gap > tol:
            if sig_out is not None:
                sig_out += [v_sl, pkg_sl]
            bad.append(f"{acct} venue stop {v_sl:g} vs package sl {pkg_sl:g} "
                       f"(gap {gap:.6g} > {tol_atr:g} x ATR {atr:.6g} [{atr_src}])")
    if bad:
        out.append(("mechanics", "venue_sl_diverges", "; ".join(bad)))
    return out, cnl


# ---------------------------------------------------------------------------
# Pre-screen (LTR-PRACTICE-REDESIGN, practice review § E.2-E.4). Four cheap
# deterministic checks evaluated on every pass for every open package, from the
# telemetry row and the closed bars of position_path_history. A check that holds
# FLAGS the package (a due event, so a wake); every evaluation, flagged or not,
# is returned as a ``prescreen`` record so each trigger type can be graded later
# against hold and a matched random checkpoint. An event absent from the config
# is not evaluated at all (rollback = delete it from the YAML).
# ---------------------------------------------------------------------------

def _side(direction: Any) -> Optional[int]:
    d = str(direction or "").lower()
    return 1 if d in ("long", "buy") else -1 if d in ("short", "sell") else None


def stall_bars(cfg_stall: Dict[str, Any], tf_seconds: int) -> int:
    """Stall threshold in bars for a leg of this timeframe (registered map, else default)."""
    by = cfg_stall.get("bars_by_timeframe") or {}
    for key, bars in by.items():
        m = _TF_RE.search("_" + str(key))
        if m and int(m.group(1)) * _TF_SECONDS[m.group(2)] == tf_seconds:
            return int(bars)
    return int(cfg_stall.get("default_bars", 6))


def _episode(conds: List[bool], cooldown: int) -> Optional[int]:
    """Index of the bar that opened the episode still holding on the last bar.

    An episode opens on a bar where the condition turns true, at least ``cooldown``
    bars after the previous opened episode; ``None`` when the last bar is not in one.
    Edge-triggered, so a condition that stays true keeps ONE level (one wake).
    """
    start: Optional[int] = None
    last_open: Optional[int] = None
    for i, c in enumerate(conds):
        if not c:
            start = None
            continue
        if start is None and (i == 0 or not conds[i - 1]):
            if last_open is None or i - last_open >= cooldown:
                start = last_open = i
    return start if conds and conds[-1] else None


def _control_u(pkg: str, bar_ts: Any) -> float:
    """A uniform draw in [0, 1) fixed by (package, bar) -- the matched random
    checkpoint is chosen by this number, so it is registered before any outcome."""
    import hashlib
    h = hashlib.sha256(f"{pkg}|{bar_ts}".encode()).hexdigest()
    return int(h[:12], 16) / float(16 ** 12)


def prescreen(row: Dict[str, Any], prior: Dict[str, Any], ctx: Optional[Dict[str, Any]],
              cfg: Dict[str, Any], now: datetime, tf_seconds: int
              ) -> Tuple[List[Tuple[str, Any, str]], List[Dict[str, str]], Optional[Dict[str, Any]]]:
    """``(events, could_not_look, record)`` for adverse_r / stall / momentum_flip /
    structure_break. ``record`` is ``None`` when no pre-screen event is configured."""
    ev = cfg["events"]
    names = [n for n in PRESCREEN_EVENTS if isinstance(ev.get(n), dict)]
    if not names:
        return [], [], None
    out: List[Tuple[str, Any, str]] = []
    cnl: List[Dict[str, str]] = []
    checks: Dict[str, Dict[str, Any]] = {}

    def miss(name: str, reason: str) -> None:
        cnl.append({"event": name, "reason": reason})
        checks[name] = {"read": "could_not_look", "flagged": None, "reason": reason}

    def looked(name: str, holds: bool, level: Any = None, why: Optional[str] = None,
               emit: bool = True, **vals: Any) -> None:
        # ``flagged`` = the check holds on this pass; whether it is newly DUE (not yet
        # answered by a review) is the due list's dedupe, applied in compute_due.
        checks[name] = {"read": "looked", "flagged": holds, "level": level, "why": why, **vals}
        if holds and emit:
            out.append((name, level, why))

    open_r, peak_r, held = _f(row.get("open_r")), _f(row.get("peak_r")), _f(row.get("bars_held"))
    tel_reason = "telemetry_absent" if row.get("telemetry_absent") else None

    if "adverse_r" in names:
        levels = sorted((float(x) for x in (ev["adverse_r"].get("levels") or [])), reverse=True)
        if open_r is None:
            miss("adverse_r", tel_reason or "open_r unknown")
        else:
            crossed = [lv for lv in levels if open_r <= lv]
            deepest = crossed[-1] if crossed else None
            done = [float(lv) for e, lv in prior["fired"] if e == "adverse_r" and _f(lv) is not None]
            # A reviewed deeper level covers the shallower one (first crossing of each).
            covered = deepest is not None and any(d <= deepest + 1e-9 for d in done)
            looked("adverse_r", deepest is not None, deepest,
                   f"open_r {open_r:.2f} crossed {deepest:g}R" if deepest is not None else None,
                   emit=not covered, value=open_r)

    if "stall" in names:
        sc = ev["stall"]
        need = stall_bars(sc, tf_seconds)
        max_peak = float(sc.get("max_peak_r", 0.5))
        if held is None or peak_r is None:
            miss("stall", tel_reason or "bars_held / peak_r unknown")
        else:
            hit = held >= need and peak_r < max_peak
            lvl = int(held // need) * need if hit else None
            looked("stall", hit, lvl,
                   f"{held:g} bars held (>= {need}) with peak_r {peak_r:.2f} < {max_peak:g}"
                   if hit else None, value=held, threshold_bars=need)

    hist = (ctx or {}).get("history")
    side = _side(row.get("direction"))
    closed = [h for h in (hist or [])[:-1] if _f(h.get("last_price")) is not None]
    bar_ts = closed[-1].get("bar_ts") if closed else None
    hist_names = [n for n in ("momentum_flip", "structure_break") if n in names]
    for name in hist_names:
        c = ev[name]
        if hist is None:
            miss(name, f"history_unavailable: {(ctx or {}).get('history_reason') or 'not read'}")
        elif side is None:
            miss(name, f"direction unknown ({row.get('direction')!r})")
        elif name == "momentum_flip":
            k, min_atr = int(c.get("bars", 3)), float(c.get("min_atr", 1.0))
            if len(closed) < k + 1:
                miss(name, f"{len(closed)} closed history bar(s); need {k + 1}")
                continue
            px = [_f(h["last_price"]) for h in closed]
            conds = [False] * len(px)
            for i in range(k, len(px)):
                atr = _f(closed[i].get("atr"))
                steps = [side * (px[j] - px[j - 1]) for j in range(i - k + 1, i + 1)]
                conds[i] = bool(atr and atr > 0 and all(s < 0 for s in steps)
                                and -sum(steps) >= min_atr * atr)
            st = _episode(conds, int(c.get("cooldown_bars", 3)))
            lvl = str(closed[st].get("bar_ts")) if st is not None else None
            looked(name, st is not None, lvl,
                   f"{k} closed bars against the position, net >= {min_atr:g} x ATR (since {lvl})"
                   if st is not None else None)
        else:  # structure_break
            mb, buf = int(c.get("min_bars", 3)), float(c.get("buffer_atr", 0.1))
            if len(closed) < mb + 1:
                miss(name, f"{len(closed)} closed history bar(s); need {mb + 1}")
                continue
            px = [_f(h["last_price"]) for h in closed]
            conds = [False] * len(px)
            ext = side * px[0]  # the since-entry extreme against the position, in side terms
            for i in range(1, len(px)):
                atr = _f(closed[i].get("atr"))
                conds[i] = bool(i >= mb and atr and atr > 0 and side * px[i] < ext - buf * atr)
                ext = min(ext, side * px[i])
            st = _episode(conds, int(c.get("cooldown_bars", 3)))
            lvl = str(closed[st].get("bar_ts")) if st is not None else None
            looked(name, st is not None, lvl,
                   f"close broke the since-entry {'low' if side > 0 else 'high'} close by > "
                   f"{buf:g} x ATR (since {lvl})" if st is not None else None)

    pkg = str(row.get("order_package_id"))
    last = (hist or [None])[-1] if hist else None
    record = {
        "evaluated_at": now.isoformat(), "order_package_id": pkg, "trade_id": row.get("trade_id"),
        "leg": row.get("strategy"), "account_id": row.get("account_id"), "symbol": row.get("symbol"),
        "direction": row.get("direction"), "timeframe_seconds": tf_seconds,
        "closed_bar_ts": bar_ts,
        "state": {"open_r": open_r, "peak_r": peak_r, "bars_held": held,
                  "giveback_r": _f(row.get("giveback_r")), "r_to_stop": _f(row.get("r_to_stop")),
                  "r_to_target": _f(row.get("r_to_target")),
                  "mae_r": _f((last or {}).get("mae_r")), "atr": _f((last or {}).get("atr")),
                  "last_price": _f(row.get("last_price")) or _f((last or {}).get("last_price"))},
        "telemetry_state": "telemetry_absent" if row.get("telemetry_absent") else "present",
        "checks": checks,
        "flagged": sorted(n for n, c in checks.items() if c.get("flagged")),
        # Pricing the alternatives per bar needs the leg's committed candles replayed
        # (live_review_outcomes.py): not cheap enough for every pass. The record keeps
        # the state that tool takes (open_r, peak_r, bars_held, side), so a grader
        # prices each checkpoint offline.
        "pricing": {"state": "not_priced", "reason": "state recorded; priced offline by the grader"},
        "control_u": round(_control_u(pkg, bar_ts), 6),
    }
    return out, cnl, record


_DIGITS_RE = re.compile(r"\d+(?:\.\d+)?")


def _reason_kind(reason: Any) -> str:
    """The reason with its numbers masked, so 'starts 2.0 bars' and 'starts 47.0 bars'
    group as one cause and a symbol-specific tail does not split the count."""
    text = str(reason or "unknown")
    text = re.sub(r"declared for \S+$", "declared for <symbol>", text)
    return _DIGITS_RE.sub("N", text)


def _coverage_entry(row: Dict[str, Any], tf_seconds: int,
                    cnl: List[Dict[str, str]],
                    prescreen_names: Iterable[str] = ()) -> Dict[str, Any]:
    """One open package's evaluation coverage, due or not.

    ``events_looked`` names the events that WERE evaluated (a quiet one means
    "looked, nothing fired"); ``events_could_not_look`` the ones that could not
    be, with the reason. The two never overlap, so a reader can tell a quiet
    package from a blind one. ``funding`` only counts for perps (n/a otherwise).
    """
    missed = {c["event"] for c in cnl}
    universe = list(MARKET_EVENTS) + ["mechanics"] + list(prescreen_names)
    if not row.get("telemetry_absent"):
        universe = list(TELEMETRY_EVENTS) + universe
    if not _is_perp(row.get("symbol")):
        universe.remove("funding")
    return {
        "order_package_id": row.get("order_package_id"), "leg": row.get("strategy"),
        "account_id": row.get("account_id"), "symbol": row.get("symbol"),
        "telemetry_state": "telemetry_absent" if row.get("telemetry_absent") else "present",
        "events_looked": [n for n in universe if n not in missed],
        "events_could_not_look": cnl,
    }


def summarize_could_not_look(coverage: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per event: how many open packages could not be evaluated and why (masked
    reason -> packages). ``packages`` is the denominator."""
    by_event: Dict[str, Dict[str, Any]] = {}
    for c in coverage:
        seen: Set[Tuple[str, str]] = set()
        for m in c["events_could_not_look"]:
            kind = _reason_kind(m.get("reason"))
            if (m["event"], kind) in seen:
                continue
            seen.add((m["event"], kind))
            slot = by_event.setdefault(m["event"], {"packages": 0, "reasons": {}})
            slot["reasons"][kind] = slot["reasons"].get(kind, 0) + 1
        for ev in {m["event"] for m in c["events_could_not_look"]}:
            by_event[ev]["packages"] += 1
    return {"packages": len(coverage), "by_event": by_event}


def compute_due(rows: List[Dict[str, Any]], reviews: List[Dict[str, Any]],
                cfg: Dict[str, Any], now: Optional[datetime] = None,
                market: Optional[Dict[str, Dict[str, Any]]] = None,
                mechanics_rows: Optional[List[Dict[str, Any]]] = None,
                cadence: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Due packages from OPEN telemetry rows. Pure; no I/O.

    ``cadence`` maps order_package_id -> {mandate, minutes} for packages a per-package auto mandate
    scopes (``ltr_auto_mandate.cadence``; MD-LTR-ADA-AUTO, operator 2026-10-29). Each such OPEN package
    gets the event ``mandate_cadence`` once per ``minutes`` slot, level = the slot's start (UTC ISO), so
    the VM wake poster builds + commits its packet and wakes a reviewer on that cadence after the bar
    boundary. Deduped like every event (a review answering the slot; a review already made this bar).

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
    coverage: List[Dict[str, Any]] = []
    screened: List[Dict[str, Any]] = []
    ps_names = [n for n in PRESCREEN_EVENTS if isinstance(cfg["events"].get(n), dict)]
    for row in rows:
        pkg = str(row.get("order_package_id"))
        prior = idx.get(pkg, {"fired": set(), "last": None, "peak": None, "mech": None})
        tf = timeframe_seconds(row.get("strategy"), default_tf)
        in_cooldown = prior["last"] is not None and prior["last"] >= bar_start(now, tf)
        events = []
        mk, cnl = market_events(row, (market or {}).get(pkg), cfg, now, tf)
        venue_sig: List[float] = []
        vk, vcnl = venue_events(row, (market or {}).get(pkg), cfg, now, sig_out=venue_sig)
        pk, pcnl, prec = prescreen(row, prior, (market or {}).get(pkg), cfg, now, tf)
        if prec is not None:
            screened.append(prec)
        mk, cnl = mk + vk + pk, cnl + vcnl + pcnl
        if row.get("telemetry_absent"):
            cnl = [{"event": n, "reason": "telemetry_absent"} for n in TELEMETRY_EVENTS] + cnl
        if cnl:
            cnl_total += 1
        coverage.append(_coverage_entry(row, tf, cnl, ps_names))
        cad = (cadence or {}).get(pkg)
        if cad:
            slot = bar_start(now, int(cad["minutes"]) * 60).isoformat()
            mk = mk + [(CADENCE_EVENT, slot, f"{cad['mandate']}: auto-apply review every {cad['minutes']} min")]
        for name, level, why in candidate_events(row, prior, cfg, now, floor_accounts) + mk:
            if name == "mechanics" and level == VENUE_LEVEL:
                # Not the plain fired-set: a repeat of the SAME divergence is quiet, a
                # changed one is due again. Rows with a null level are covered too.
                if _mechanics_fired(prior, VENUE_LEVEL, venue_sig):
                    continue
            elif (name, _lvl(level)) in prior["fired"]:
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
            "telemetry_state": "telemetry_absent" if row.get("telemetry_absent") else "present",
            "telemetry_updated_at": row.get("updated_at"),
            "telemetry_stale": None if row.get("telemetry_absent")
            else bool(upd is None or now - upd > stale_after),
            "events_could_not_look": cnl,
        })

    mech_on = bool((cfg["events"].get("mechanics") or {}).get("journal_trade_absent", True))
    for row in (mechanics_rows or []) if mech_on else []:
        pkg = str(row.get("order_package_id"))
        prior = idx.get(pkg, {"fired": set(), "last": None, "peak": None, "mech": None})
        if ("mechanics", _lvl(JOURNAL_LEVEL)) in prior["fired"] \
                or _mechanics_fired(prior, JOURNAL_LEVEL):
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
            "telemetry_state": "present",
            "telemetry_updated_at": row.get("updated_at"),
            "telemetry_stale": False,
            "events_could_not_look": [],
        })
    return {"due": due, "due_count": len(due), "suppressed_by_cooldown": cooled,
            "packages_with_events_could_not_look": cnl_total,
            "event_coverage": coverage,
            "could_not_look_summary": summarize_could_not_look(coverage),
            "prescreen": screened}


def read_journal_open(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Open packages per the journal: ``order_packages.status`` and ``trades.status`` open.

    ``state`` read / could_not_look (a missing table or file is NOT an empty
    set). One row per (package, account) where the trade row names one, else
    one per package.
    """
    try:
        if db_path is None:
            from src.utils.paths import trade_journal_db_path
            db_path = str(trade_journal_db_path())
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            pk = conn.execute("SELECT order_package_id, strategy_name, symbol, direction "
                              "FROM order_packages WHERE status = 'open'").fetchall()
            tr = conn.execute("SELECT id, order_package_id, strategy_name, symbol, direction, "
                              "account_id FROM trades WHERE status = 'open' "
                              "AND order_package_id IS NOT NULL AND order_package_id != ''").fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        return {"state": "could_not_look", "reason": f"journal_open_unreadable: {type(exc).__name__}: {exc}"}
    out: Dict[str, Dict[str, Any]] = {}
    for r in pk:
        out[str(r["order_package_id"])] = {
            "order_package_id": str(r["order_package_id"]), "strategy": r["strategy_name"],
            "symbol": r["symbol"], "direction": r["direction"], "account_id": None,
            "trade_id": None, "source": "order_packages"}
    for r in tr:
        d = out.setdefault(str(r["order_package_id"]), {
            "order_package_id": str(r["order_package_id"]), "strategy": r["strategy_name"],
            "symbol": r["symbol"], "direction": r["direction"], "source": "trades"})
        d["account_id"] = r["account_id"]
        d["trade_id"] = r["id"]
        d["source"] = "order_packages+trades" if d.get("source") == "order_packages" else d["source"]
    return {"state": "read", "packages": list(out.values())}


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


def read_venue_context(pkgs: List[str], db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Per package: its ``venue_protection_snapshot`` rows plus the package's own
    ``sl`` / ``tp`` / entry ATR. Never raises; every package gets an entry, and a
    read that failed is ``could_not_look`` with the reason, never an empty set.
    """
    out: Dict[str, Dict[str, Any]] = {}

    def fail(reason: str) -> Dict[str, Dict[str, Any]]:
        return {p: {"state": "could_not_look", "reason": reason} for p in pkgs}

    if not pkgs:
        return out
    try:
        if db_path is None:
            from src.utils.paths import trade_journal_db_path
            db_path = str(trade_journal_db_path())
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        return fail(f"venue_snapshot_unreadable: {type(exc).__name__}: {exc}")
    try:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='venue_protection_snapshot'").fetchone():
            return fail("venue_snapshot_table_absent")
        marks = ",".join("?" * len(pkgs))
        snaps: Dict[str, List[Dict[str, Any]]] = {}
        for r in conn.execute(f"SELECT * FROM venue_protection_snapshot WHERE order_package_id IN ({marks})", pkgs):
            snaps.setdefault(str(r["order_package_id"]), []).append(dict(r))
        try:
            levels = {str(r["order_package_id"]): r for r in conn.execute(
                f"SELECT order_package_id, sl, tp, meta FROM order_packages WHERE order_package_id IN ({marks})", pkgs)}
        except sqlite3.Error as exc:
            return fail(f"package_levels_unreadable: {exc}")
    except sqlite3.Error as exc:
        return fail(f"venue_snapshot_error: {exc}")
    finally:
        conn.close()
    for p in pkgs:
        lv = levels.get(p)
        if lv is None:
            out[p] = {"state": "could_not_look", "reason": "package_not_in_order_packages"}
            continue
        meta_atr = None
        try:
            m = json.loads(lv["meta"]) if lv["meta"] else {}
            meta_atr = _f(m.get("atr")) if isinstance(m, dict) else None
        except (ValueError, TypeError):
            meta_atr = None  # allow-silent: an unreadable meta is "no entry ATR", reported as such downstream
        out[p] = {"state": "read", "snapshots": snaps.get(p, []), "pkg_sl": _f(lv["sl"]),
                  "pkg_tp": _f(lv["tp"]), "meta_atr": meta_atr}
    return out


def read_market_context(open_rows: List[Dict[str, Any]], cfg: Dict[str, Any], now: datetime,
                        db_path: Optional[str] = None, funding_db_path: Optional[str] = None,
                        calendar_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Per package: path history, funding and the (shared) calendar. Never raises."""
    cal = read_calendar(calendar_path, now)
    win = float((cfg["events"].get("funding") or {}).get("window_hours", 9))
    out: Dict[str, Dict[str, Any]] = {}
    try:
        venue = read_venue_context([str(r.get("order_package_id")) for r in open_rows], db_path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look per package
        venue = {str(r.get("order_package_id")): {"state": "could_not_look",
                 "reason": f"venue_context: {type(exc).__name__}: {exc}"} for r in open_rows}
    for row in open_rows:
        pkg = str(row.get("order_package_id"))
        ctx: Dict[str, Any] = {"calendar": cal, "history": None, "history_reason": None,
                               "venue": venue.get(pkg)}
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
        "open_count_complete": False, "telemetry_less": [],
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
    jo = read_journal_open(db_path)
    env["journal_open_state"] = jo["state"]
    env["journal_open_reason"] = jo.get("reason")
    have = {str(r.get("order_package_id")) for r in open_rows}
    less = [dict(p, telemetry_absent=True, lifecycle="open")
            for p in jo.get("packages", []) if p["order_package_id"] not in have]
    market = read_market_context(open_rows + less, cfg, now, db_path, funding_db_path, calendar_path)
    try:
        from src.runtime import ltr_auto_mandate
        cad = ltr_auto_mandate.cadence(now=now)
    except Exception:  # noqa: BLE001  # allow-silent: no cadence = no auto-mandate wake; every other event stands
        cad = {}
    env["mandate_cadence"] = cad
    res = compute_due(open_rows + less, rv["rows"], cfg, now, market=market, mechanics_rows=mech_rows,
                      cadence=cad)
    env.update(res)
    env["open_count"] = len(open_rows) + len(less)
    env["open_count_complete"] = jo["state"] == "read"
    env["telemetry_less"] = [{
        "order_package_id": r["order_package_id"], "trade_id": r.get("trade_id"),
        "leg": r.get("strategy"), "account_id": r.get("account_id"), "symbol": r.get("symbol"),
        "direction": r.get("direction"), "telemetry_state": "telemetry_absent",
        "events_could_not_look": [{"event": n, "reason": "telemetry_absent"} for n in TELEMETRY_EVENTS],
    } for r in less]
    cal = next(iter(market.values()), {}).get("calendar") if market else None
    vsn = [sn for c in market.values() for sn in ((c.get("venue") or {}).get("snapshots") or [])]
    env["venue_snapshot"] = {
        "rows": len(vsn),
        **{st: sum(1 for sn in vsn if sn.get("read_state") == st)
           for st in ("measured", "none_resting", "could_not_look")},
        "packages_without_row": sum(
            1 for c in market.values()
            if (c.get("venue") or {}).get("state") == "read" and not (c["venue"].get("snapshots"))),
        "packages_unreadable": sum(
            1 for c in market.values() if (c.get("venue") or {}).get("state") != "read"),
    }
    env["calendar_state"] = (cal or {}).get("state")
    env["calendar_newest_event"] = (cal or {}).get("newest_event")
    env["read_state"] = "looked"
    env["oldest_due_bar_start"] = min(
        (d["bar_start"] for d in res["due"]), default=None)
    return env

#!/usr/bin/env python3
# wiring: manual-only - called by scripts/ops/desk_scan_packet.py (the desk session's scan-packet builder); no schedule of its own.
"""DESK-16B-NEAR-SIGNALS -- which rostered legs are within one bar of a signal.

Design: docs/plans/claude-trading-desk-DESIGN.md (scan packet / system_book / novelty). Consumer:
scripts/ops/desk_scan_packet.py (`build_scan_packet(near_signals=...)`), whose guard
(scripts/ci/check_desk_records.py) refuses a near-signal item that is not 0|1 bars from a signal.

READ-ONLY, OFF THE ORDER PATH. It imports the strategy units' own ``order_package(cfg, candles_df)``
(pure functions of a candle frame) and the live builders' own side-filter resolver; it writes
nothing and calls no builder (the builders fetch candles and append to the signal audit log).

HOW "WITHIN ONE BAR" IS DECIDED -- by the unit's own signal logic, not a re-implementation:
  bars_to_signal 0  the unit returns a package on the latest CLOSED bar.
  bars_to_signal 1  it does not, but it WOULD if the next bar closed up to NEAR_ATR_MAX x ATR(14)
                    above/below the last close. The probe appends one synthetic bar (open = last
                    close, close = last close +/- m x ATR, no wicks, median recent volume, stamped
                    one timeframe later) for m in PROBE_ATR and re-runs the same unit.
  The probe size is a stated constant, not a forecast: it is "a next bar of that size would fire it".

COULD-NOT-LOOK IS NEVER "NOT NEAR". A leg is reported in ``unlooked`` BY NAME, with a reason, when its
unit is unknown, its candles are missing/short, its signal needs an input the probe cannot supply (an
HTF bias frame, a local regime off-cell gate), or the unit raised something other than a
"non-actionable" ValueError. ``near_signals_read_state`` is ``read`` only when EVERY rostered leg x
symbol was looked at (the schema has no partial state); the denominator is always stated.

NOT reproduced (the builders apply them AFTER the unit): the regime router, market-hours gates, the
decision-bar ledger, and the ACCOUNT-level side_filter (accounts.yaml). A near-signal here is "the leg's signal logic fires", the pre-router fact.

Usage:
  desk_near_signals.py [--legs a,b] [--candles-dir DIR] [--json]      # live: public candle route
  desk_near_signals.py --self-test
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd  # noqa: E402

import desk_scan_packet as dsp  # noqa: E402  (bars, closed_before, atr_series, candles readers)

NEAR_ATR_MAX = 1.5                    # a next bar this many ATR from the last close counts as "within one bar"
PROBE_ATR = (0.5, 1.0, 1.5)           # probed in order; the first that fires is the one reported
MIN_BARS = 120                        # fewer closed bars than this and the leg is unlooked, not "quiet"
UNIT_ORDER = (("ict_scalp", "ict_scalp"), ("pullback", "htf_pullback_trend_2h"), ("trend", "trend_donchian"))
# `need at least N candles` / `candles_df is required` are ValueErrors that mean "could not evaluate",
# not "no signal": they must not read as a quiet leg.
_CANNOT_EVALUATE = ("need at least", "candles_df is required", "undefined on the latest bar")

Bar = Dict[str, float]


def unit_for(leg: str) -> Optional[str]:
    """The strategy unit (src/units/strategies/<unit>.py) a leg runs on, by the builders' own families:
    trend_donchian (every *trend* leg), htf_pullback_trend_2h (every *pullback* leg), ict_scalp."""
    for key, unit in UNIT_ORDER:
        if leg.startswith(key) if key == "ict_scalp" else key in leg:
            return unit
    return None


def rostered_legs(accounts_cfg: Dict[str, dict], strategies_cfg: Dict[str, Any]) -> List[dict]:
    """[{leg, symbol, timeframe, cfg}] -- one row per (leg, symbol) over every account that trades, in
    accounts.yaml order. A leg disabled in strategies.yaml (`enabled: false`) cannot fire and is left out;
    `execution: shadow` legs stay in (they run and log). Opted-out accounts contribute nothing."""
    seen, out = set(), []
    for _, a in accounts_cfg.items():
        if not isinstance(a, dict) or a.get("configured") is False:
            continue
        for leg in a.get("strategies") or []:
            c = strategies_cfg.get(leg)
            if not isinstance(c, dict) or c.get("enabled") is False:
                continue
            for sym in c.get("symbols") or []:
                if (leg, sym) not in seen:
                    seen.add((leg, sym))
                    out.append({"leg": leg, "symbol": sym, "timeframe": str(c.get("timeframe") or "1h"), "cfg": c})
    return out


def _frame(bars: Sequence[Bar]) -> pd.DataFrame:
    df = pd.DataFrame({
        "timestamp": [datetime.fromtimestamp(b["time"], tz=timezone.utc) for b in bars],
        "open": [b["open"] for b in bars], "high": [b["high"] for b in bars],
        "low": [b["low"] for b in bars], "close": [b["close"] for b in bars],
        "volume": [float(b.get("volume") or 0.0) for b in bars]})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _synthetic_next(df: pd.DataFrame, tf_sec: int, move: float) -> pd.DataFrame:
    last = df.iloc[-1]
    c = float(last["close"]) + move
    nxt = {"timestamp": pd.Timestamp(last["timestamp"]) + pd.Timedelta(seconds=tf_sec), "open": float(last["close"]),
           "high": max(float(last["close"]), c), "low": min(float(last["close"]), c), "close": c,
           "volume": float(df["volume"].tail(20).median())}
    return pd.concat([df, pd.DataFrame([nxt])], ignore_index=True)


def _eval(order_package: Callable, cfg: dict, df: pd.DataFrame) -> Tuple[Optional[dict], Optional[str]]:
    """(package, None) = fires; (None, None) = non-actionable; (None, reason) = could not evaluate."""
    try:
        return order_package(cfg, candles_df=df), None
    except ValueError as exc:
        msg = str(exc)
        return (None, msg[:160]) if any(k in msg for k in _CANNOT_EVALUATE) else (None, None)
    except Exception as exc:  # allow-silent: becomes an unlooked leg with this reason, never a quiet one
        return None, f"{type(exc).__name__}: {str(exc)[:140]}"


def look_at_leg(row: dict, bars: Optional[Sequence[Bar]], cutoff: datetime,
                resolve_unit: Callable[[str], Any] = None, side_filter: Callable[[dict], str] = None) -> dict:
    """{"items": [near_signal item...], "unlooked": reason|None, "probe": {...}} for one (leg, symbol)."""
    leg, sym, tf, ycfg = row["leg"], row["symbol"], row["timeframe"], row["cfg"]

    def unlooked(why: str) -> dict:
        return {"items": [], "unlooked": why, "probe": None}

    unit = unit_for(leg)
    if unit is None:
        return unlooked(f"no strategy unit known for leg {leg!r}")
    if ycfg.get("htf_trend_filter_enabled"):
        return unlooked("its signal needs an HTF bias frame the probe does not fetch")
    if ycfg.get("off_cells") and ycfg.get("vol_spec"):
        return unlooked("a local regime off-cell gate applies after the unit; not reproduced")
    if tf not in dsp.TF_SECONDS:
        return unlooked(f"timeframe {tf!r} unsupported")
    closed = dsp.closed_before(bars, tf, cutoff) if bars else []
    if len(closed) < MIN_BARS:
        return unlooked(f"{len(closed)} closed {tf} candles (< {MIN_BARS})" if bars else f"no {tf} candles for {sym}")
    atr = dsp.atr_series(closed)[-1]
    if not atr or atr <= 0:
        return unlooked("ATR(14) undefined on the latest bar")
    order_package = (resolve_unit or (lambda u: importlib.import_module(f"src.units.strategies.{u}").order_package))(unit)
    if side_filter is None:
        from src.runtime.strategy_signal_builders import _resolve_side_filter as side_filter
    gate = side_filter(ycfg)                      # the builders' own directional gate: long | short | both
    allowed = {"long": ("long",), "short": ("short",)}.get(gate, ("long", "short"))
    cfg = {"symbol": sym, "timeframe": tf, **ycfg, "strategy_label": leg}
    df = _frame(closed)
    item = lambda side, n, pkg=None: {  # noqa: E731
        "order_package_id": None, "leg": leg, "symbol": sym, "side": side, "timeframe": tf, "status": "near_signal",
        "bars_to_signal": n, "entry": dsp._r6(pkg.get("entry")) if pkg else None,
        "sl": dsp._r6(pkg.get("sl")) if pkg else None, "tp": dsp._r6(pkg.get("tp")) if pkg else None}

    pkg, bad = _eval(order_package, cfg, df)
    if bad:
        return unlooked(bad)
    probe = {"unit": unit, "side_filter": gate, "atr": dsp._r6(atr), "near_atr_max": NEAR_ATR_MAX}
    if pkg and pkg.get("direction") in allowed:
        return {"items": [item(pkg["direction"], 0, pkg)], "unlooked": None, "probe": probe}
    sec, found = dsp.TF_SECONDS[tf], {}
    for m in PROBE_ATR:
        for sgn in (1.0, -1.0):
            nxt, bad = _eval(order_package, cfg, _synthetic_next(df, sec, sgn * m * atr))
            if bad:
                return unlooked(f"next-bar probe: {bad}")
            if nxt and nxt.get("direction") in allowed and nxt["direction"] not in found:
                found[nxt["direction"]] = m
    probe["trigger_move_atr"] = found
    return {"items": [item(side, 1) for side in sorted(found) if found[side] <= NEAR_ATR_MAX], "unlooked": None, "probe": probe}


def near_signals(rows: Sequence[dict], candles: Dict[Tuple[str, str], Optional[Sequence[Bar]]], cutoff: datetime,
                 **kw: Any) -> dict:
    """{"items": [...], "unlooked": [{leg, symbol, reason}], "n_looked", "n_rostered", "read_state", "missing"}.
    `candles[(symbol, timeframe)]`. read_state is `read` only when every (leg, symbol) was looked at."""
    items, unlooked, looked = [], [], 0
    for r in rows:
        res = look_at_leg(r, candles.get((r["symbol"], r["timeframe"])), cutoff, **kw)
        if res["unlooked"]:
            unlooked.append({"leg": r["leg"], "symbol": r["symbol"], "reason": res["unlooked"]})
        else:
            looked += 1
            items += res["items"]
    n = len(rows)
    state = "read" if n and not unlooked else "could_not_look"
    why = (f"{looked} of {n} rostered leg x symbol looked; not looked: "
           + "; ".join(f"{u['leg']}/{u['symbol']} ({u['reason']})" for u in unlooked)) if unlooked else (
        "no rostered legs" if not n else None)
    return {"items": items if state == "read" else [], "found_but_withheld": 0 if state == "read" else len(items),
            "unlooked": unlooked, "n_looked": looked, "n_rostered": n, "read_state": state,
            "missing": None if state == "read" else why,
            "denominator": f"{looked} of {n} rostered leg x symbol looked (near = unit fires on the last closed bar, "
                           f"or on a next bar closing <= {NEAR_ATR_MAX} ATR away)"}


# ----------------------------------------------------------------------------- IO (CLI)

def collect(rows: Sequence[dict], candles_dir: Optional[Path] = None) -> Dict[Tuple[str, str], Optional[list]]:
    """One candle read per (symbol, timeframe) the rostered legs need."""
    need: Dict[str, List[str]] = {}
    for r in rows:
        need.setdefault(r["timeframe"], [])
        if r["symbol"] not in need[r["timeframe"]]:
            need[r["timeframe"]].append(r["symbol"])
    out: Dict[Tuple[str, str], Optional[list]] = {}
    for tf, syms in need.items():
        got = dsp.candles_from_dir(candles_dir, syms, tf) if candles_dir else dsp.candles_from_api(syms, tf, limit=1000)
        if not candles_dir:  # the route serves some futures daily series only at a smaller limit (MGC 1d: 200 yes, 300 and 1000 no_data)
            for s in [s for s in syms if not got.get(s)]:
                got.update(dsp.candles_from_api([s], tf, limit=200))
        out.update({(s, tf): got.get(s) for s in syms})
    return out


def live_near_signals(cutoff: datetime, candles_dir: Optional[Path] = None, legs: Optional[Sequence[str]] = None) -> dict:
    acc, strat = dsp._load_cfg()
    rows = rostered_legs(acc, strat)
    if legs:
        rows = [r for r in rows if r["leg"] in set(legs)]
    return near_signals(rows, collect(rows, candles_dir), cutoff)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--legs", help="comma list: restrict to these legs")
    ap.add_argument("--candles-dir", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    res = live_near_signals(datetime.now(timezone.utc).replace(second=0, microsecond=0), a.candles_dir,
                            a.legs.split(",") if a.legs else None)
    if a.json:
        print(json.dumps(res, indent=1, sort_keys=True))
    else:
        print(f"desk_near_signals: {res['denominator']}; read_state={res['read_state']}")
        for i in res["items"]:
            print(f"  near  {i['leg']:28s} {i['symbol']:9s} {i['timeframe']:3s} {i['side']:5s} bars_to_signal={i['bars_to_signal']}")
        for u in res["unlooked"]:
            print(f"  UNLOOKED  {u['leg']}/{u['symbol']}: {u['reason']}")
    return 0


# ----------------------------------------------------------------------------- self-test

def _self_test() -> int:
    ok = True

    def expect(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        ok &= bool(cond)

    sec = dsp.TF_SECONDS["1d"]
    t0 = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    flat = [{"time": t0 + i * sec, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0} for i in range(200)]
    # a spike 10 points above (and a dip below) the tape, older than the ATR window but inside the 20-bar channel,, puts both breakout levels far (5 ATR)
    # from the last close; the tape is otherwise flat
    for i in range(181, 184):
        flat[i] = dict(flat[i], high=110.0)
    for i in range(184, 186):
        flat[i] = dict(flat[i], low=90.0)
    cutoff = datetime.fromtimestamp(t0 + 200 * sec, tz=timezone.utc)
    ycfg = {"enabled": True, "timeframe": "1d", "symbols": ["SYN"], "donchian": 20, "atr_period": 14, "atr_stop_mult": 2.0,
            "trail_mult": 4.0, "tp_r": 2.0, "min_confidence": 0.0}
    row = {"leg": "syn_trend_1d", "symbol": "SYN", "timeframe": "1d", "cfg": ycfg}

    res = look_at_leg(row, flat, cutoff)
    expect("a flat tape is looked at and quiet (no near-signal, not unlooked)", res["unlooked"] is None and res["items"] == [])
    # a close just under the channel high: a next bar within the probe breaks it -> within one bar, long
    px = flat[:-1] + [dict(flat[-1], close=108.0, high=108.5)]
    res = look_at_leg(row, px, cutoff)
    expect("a close just under the channel is a long near-signal, bars_to_signal 1, unit-derived",
           [(i["side"], i["bars_to_signal"]) for i in res["items"]] == [("long", 1)] and res["unlooked"] is None)
    # a bar that already broke out: the unit fires on the last closed bar
    brk = flat[:-1] + [dict(flat[-1], close=112.0, high=112.0)]
    res = look_at_leg(row, brk, cutoff)
    expect("a bar that already broke the channel is bars_to_signal 0 with the unit's levels",
           [(i["side"], i["bars_to_signal"]) for i in res["items"]] == [("long", 0)] and res["items"][0]["sl"] is not None)
    # the builders' own directional gate: a long-only leg never reports a short
    dn = flat[:-1] + [dict(flat[-1], close=88.0, low=88.0)]
    both = look_at_leg(row, dn, cutoff)
    lo = look_at_leg(dict(row, cfg=dict(ycfg, long_only=True)), dn, cutoff)
    expect("long_only suppresses the short side exactly as the builders' resolver does",
           [i["side"] for i in both["items"]] == ["short"] and lo["items"] == [])
    # could-not-look is named, never a quiet leg
    expect("too few candles is UNLOOKED with a reason, not quiet", look_at_leg(row, flat[:50], cutoff)["unlooked"] is not None)
    expect("missing candles is UNLOOKED", look_at_leg(row, None, cutoff)["unlooked"] is not None)
    expect("an unknown unit is UNLOOKED by name", "no strategy unit" in look_at_leg(dict(row, leg="mystery_leg"), flat, cutoff)["unlooked"])
    expect("an HTF-filtered ict_scalp leg is UNLOOKED",
           look_at_leg({"leg": "ict_scalp_x", "symbol": "SYN", "timeframe": "1d", "cfg": dict(ycfg, htf_trend_filter_enabled=True)},
                       flat, cutoff)["unlooked"] is not None)
    # the forming bar never counts: a bar that has not closed by the cutoff is dropped
    forming = flat + [{"time": t0 + 200 * sec - 10, "open": 100, "high": 110, "low": 100, "close": 110, "volume": 1}]
    expect("the forming bar is dropped before the unit sees it", look_at_leg(row, forming, cutoff)["items"] == [])
    # the aggregate: read only when every leg x symbol was looked at; denominator stated
    r2 = near_signals([row, dict(row, leg="syn2_trend_1d", symbol="NONE")], {("SYN", "1d"): px}, cutoff)
    expect("a partial look is could_not_look, withholds the found items, names the gap and the denominator",
           r2["read_state"] == "could_not_look" and r2["items"] == [] and r2["found_but_withheld"] == 1
           and r2["n_looked"] == 1 and r2["n_rostered"] == 2 and "syn2_trend_1d/NONE" in r2["missing"])
    r3 = near_signals([row], {("SYN", "1d"): px}, cutoff)
    expect("a complete look is read with the items and 'N of N'", r3["read_state"] == "read" and len(r3["items"]) == 1
           and r3["denominator"].startswith("1 of 1"))
    expect("an empty roster is could_not_look, not read-and-empty", near_signals([], {}, cutoff)["read_state"] == "could_not_look")
    expect("unit families follow the builders", [unit_for(x) for x in ("spy_trend_long_1d", "gld_pullback_1d", "ict_scalp_mgc_15m", "xyz")]
           == ["trend_donchian", "htf_pullback_trend_2h", "ict_scalp", None])
    # every item passes the desk guard's near-signal rules
    import check_desk_records as cdr

    expect("items satisfy the guard (status near_signal, no package id, bars_to_signal 0|1)",
           all(i["status"] == "near_signal" and i["order_package_id"] is None and i["bars_to_signal"] in (0, 1) for i in r3["items"] + res["items"]))
    del cdr
    print("desk_near_signals self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

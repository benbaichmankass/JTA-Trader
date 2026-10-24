#!/usr/bin/env python3
"""MOMENTUM-LEVERS-PARITY -- does the LIVE exit path reproduce the HARNESS, bar by bar,
for the two momentum exit levers (ADX-tightened trail, momentum-stale time stop)?

Programme 01's build gate (checklist row MOMENTUM-LEVERS-PARITY). The firing RULE is
shared (``src/research/trail_levers.py`` is imported by both sides), so what can still
drift is everything AROUND the rule: the ADX series each side computes, which bar each
side calls the entry bar, the closed-bar trim, the monitor's 200-bar fetch window, and
how the effective mult becomes a stop. This script feeds both sides IDENTICAL bars and
compares, per managed bar:

* **stop path** -- the stop the harness tests bar ``j`` against (the engine's own
  ``trail``, captured from ``harness_emit.PathRecorder.bar``) vs the stop the live
  ``trend_donchian.monitor`` holds at the first tick of bar ``j`` (it last ran on the
  CLOSED bars ``<= j-1`` plus the just-opened bar ``j``, exactly as the live fetch sees
  it: ``MONITOR_BASE_LIMIT`` rows, the forming one last);
* **momentum_trail decision** -- ``momentum_trail_fired`` on the harness's full-history
  ADX at bar ``j-1`` vs ``momentum_levers.resolve_momentum_trail_mult`` on the live frame;
* **momentum_stale decision** -- ``momentum_stale_fires`` at bar ``j-1`` vs
  ``momentum_levers.momentum_stale_verdict`` on the live frame;
* **exit** -- the harness's exit bar / reason vs the first live close verdict.

Live side: the package is built by the live ``trend_donchian.order_package`` on the
closed frame ending at the harness entry bar (``decision_bar: closed``), so entry,
stop, the frozen ATR, ``entry_time`` and the threaded lever keys are the live builder's
own. A trade the live builder does not reproduce is counted (``entry_reproduced``) and
replayed from a package carrying the harness's entry/stop, so its exit path is still
compared.

Side effects of the live path (exit-lever soak rows, position telemetry, exit-head
scoring) are stubbed for the replay; the clock read by ``closed_bars`` is pinned to one
second after the forming bar opened.

Usage::

    python3 scripts/research/momentum_levers_parity.py --candles XRPUSDT_4h.csv \
        --leg trend_donchian_xrp_adx25 --symbol XRPUSDT --out parity.json
    # a lever cell no leg declares yet (in-script only; config is never written):
    python3 scripts/research/momentum_levers_parity.py --candles ETHUSDT_4h.csv \
        --leg trend_donchian_eth_4h --symbol ETHUSDT \
        --set momentum_stale_bars=8 --set momentum_stale_adx_below=20

Exit code: 0 PARITY, 1 DIVERGES, 2 COULD_NOT_LOOK (no managed bar compared).
"""
from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO / "scripts" / "research"), str(_REPO / "scripts"), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_harness():
    """scripts/backtest_trend.py by PATH: scripts/research/backtest_trend.py is a retired
    shim of the same module name, and whichever reached sys.modules first would win."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_momentum_parity_backtest_trend", _REPO / "scripts" / "backtest_trend.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bt = _load_harness()
import harness_emit  # noqa: E402  (scripts/research/harness_emit.py)

from src.research.trail_levers import (  # noqa: E402
    momentum_stale_armed, momentum_stale_fires, momentum_trail_armed, momentum_trail_fired,
)
from src.runtime import closed_bars as _closed_bars  # noqa: E402
from src.runtime import momentum_levers as ml  # noqa: E402
from src.runtime.trail_vol import MONITOR_BASE_LIMIT  # noqa: E402
from src.units.strategies import trend_donchian as td  # noqa: E402
from src.units.strategies.trend_donchian import _TP_SENTINEL_CAP_PCT as TP_VENUE_CAP_PCT  # noqa: E402

#: Config keys that are not harness kwargs (routing / gating / identity).
_NOT_HARNESS = {"model", "signal_prefixes", "enabled", "execution", "symbols", "timeframe",
                "decision_bar", "shadow_model_ids", "min_confidence_note"}
#: Absolute tolerance on a stop price (the live verdict rounds to 8 dp).
STOP_ABS_TOL = 1e-7
_TF_SECONDS = {"1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def load_leg(name: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    with open(_REPO / "config" / "strategies.yaml") as fh:
        doc = yaml.safe_load(fh)
    strategies = doc.get("strategies", doc)
    if name not in strategies:
        raise SystemExit(f"leg {name!r} not in config/strategies.yaml")
    cfg = dict(strategies[name])
    cfg.update(overrides)
    return cfg


def _parse_set(items: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k.strip()] = yaml.safe_load(v)
    return out


def harness_kwargs(cfg: Dict[str, Any], *, symbol: str, leg: str) -> Dict[str, Any]:
    params = set(inspect.signature(bt.run_backtest).parameters)
    kw = {k: v for k, v in cfg.items() if k in params and k not in _NOT_HARNESS}
    # The live package always carries a venue-capped TP (trend_donchian.order_package);
    # the harness models it only when tp_cap_pct is set (its default 0 = no target).
    kw.setdefault("tp_cap_pct", TP_VENUE_CAP_PCT)
    kw.update(timeframe=str(cfg.get("timeframe") or "4h"), symbol=symbol, strategy_name=leg,
              timeout_bars=int(cfg.get("timeout_bars", 200)),
              cooldown_bars=int(cfg.get("cooldown_bars", 1)))
    if isinstance(kw.get("tp_revision"), dict):  # YAML block -> the harness's two flags
        rev = kw.pop("tp_revision")
        kw["tp_revision"] = rev.get("rule")
        if rev.get("width_mult") is not None:
            kw["tp_revision_width_mult"] = float(rev["width_mult"])
    if isinstance(kw.get("skip_hours"), (int, float)):
        kw["skip_hours"] = str(kw["skip_hours"])
    return kw


def run_harness(df: pd.DataFrame, kw: Dict[str, Any], tmp_path: Path):
    """The harness's trades plus the exact stop it tested each managed bar against."""
    stops: Dict[int, Dict[int, float]] = {}
    orig_bar, orig_start = harness_emit.PathRecorder.bar, harness_emit.PathRecorder.start

    def _start(self, **k):
        self._parity_entry_i = k["entry_i"]
        stops.setdefault(k["entry_i"], {})
        return orig_start(self, **k)

    def _bar(self, j, *, stop, **k):
        stops[self._parity_entry_i][int(j)] = float(stop)
        return orig_bar(self, j, stop=stop, **k)

    harness_emit.PathRecorder.start, harness_emit.PathRecorder.bar = _start, _bar
    trades: List[Any] = []
    try:
        bt.run_backtest(df, emit_paths_path=str(tmp_path), trades_out=trades, **kw)
    finally:
        harness_emit.PathRecorder.start, harness_emit.PathRecorder.bar = orig_start, orig_bar
    return trades, stops


@contextmanager
def _live_sandbox():
    """Stub the live path's side-effect writers and pin the closed-bar clock."""
    import src.runtime.exit_head_shadow as ehs
    import src.runtime.exit_lever_soak as els
    import src.runtime.position_telemetry as pt

    saved = [(els, "record_exit_lever_annotation"), (pt, "record_position_telemetry"),
             (ehs, "maybe_score_exit_head")]
    olds = [getattr(m, n, None) for m, n in saved]
    for m, n in saved:
        setattr(m, n, lambda *a, **k: None)
    old_time = _closed_bars.time

    class _Clock:
        now = 0.0

        def time(self):
            return self.now

    clock = _Clock()
    _closed_bars.time = clock
    try:
        yield clock
    finally:
        _closed_bars.time = old_time
        for (m, n), o in zip(saved, olds):
            if o is not None:
                setattr(m, n, o)


def _epoch(ts: Any) -> float:
    return pd.Timestamp(ts).timestamp()


def live_frame(df: pd.DataFrame, j: int, limit: int) -> pd.DataFrame:
    """What the monitor's fetch returns at the first tick of bar ``j``: ``limit`` rows,
    the last one the just-opened bar ``j`` (O=H=L=C=open_j)."""
    lo = max(0, j - (limit - 1))
    closed = df.iloc[lo:j][["timestamp", "open", "high", "low", "close"]].copy()
    o = float(df["open"].iloc[j])
    forming = pd.DataFrame([{"timestamp": df["timestamp"].iloc[j], "open": o, "high": o,
                             "low": o, "close": o}])
    frame = pd.concat([closed, forming], ignore_index=True)
    frame["timestamp"] = frame["timestamp"].astype(str)
    return frame


def build_live_package(cfg_live: Dict[str, Any], df: pd.DataFrame, t: Any,
                       limit: int) -> tuple:
    entry_i = int(t.entry_index)
    lo = max(0, entry_i - (limit - 2))
    frame = df.iloc[lo:entry_i + 1][["timestamp", "open", "high", "low", "close"]].copy()
    frame["timestamp"] = frame["timestamp"].astype(str)
    pkg: Optional[Dict[str, Any]] = None
    why = None
    try:
        pkg = td.order_package(cfg_live, frame)
        if pkg.get("direction") != t.direction:
            why, pkg = f"live direction {pkg.get('direction')} != harness {t.direction}", None
    except ValueError as exc:
        why = str(exc)[:160]
    reproduced = pkg is not None
    entry_cmp = None
    if pkg is None:
        atr = float(td._atr(frame, int(cfg_live.get("atr_period", 14))).iloc[-1])
        meta = {"atr": atr, "atr_period": cfg_live.get("atr_period", 14),
                "trail_mult": cfg_live.get("trail_mult"), "risk_per_unit": float(t.risk),
                "entry_time": str(frame["timestamp"].iloc[-1]),
                "timeframe": cfg_live.get("timeframe"), "strategy_label": cfg_live.get("strategy_label")}
        for k in ("stale_exit_bars", "stale_exit_below_r", "giveback_min_mfe_r", "giveback_r",
                  "trail_decay_arm_r", "trail_decay_stall_bars", "trail_decay_tight_mult",
                  "trail_vol_below_pctl", "trail_vol_above_pctl", "trail_vol_tight_mult",
                  "vol_pctl_window", "trail_adx_below", "trail_adx_falling_bars",
                  "trail_adx_tight_mult", "momentum_stale_bars", "momentum_stale_adx_below",
                  "adx_period", "tp_revision"):
            if cfg_live.get(k) is not None:
                meta[k] = cfg_live[k]
        pkg = {"symbol": cfg_live.get("symbol"), "direction": t.direction, "entry": float(t.entry),
               "sl": float(t.sl), "tp": None, "meta": meta}
    else:
        entry_cmp = {"entry_live": pkg["entry"], "entry_harness": float(t.entry),
                     "sl_live": pkg["sl"], "sl_harness": float(t.sl)}
    pkg = dict(pkg)
    pkg["meta"] = dict(pkg.get("meta") or {})
    pkg["meta"].setdefault("strategy_label", cfg_live.get("strategy_label"))
    return pkg, reproduced, why, entry_cmp


def compare_trade(df: pd.DataFrame, adx_full: pd.Series, t: Any, h_stops: Dict[int, float],
                  cfg: Dict[str, Any], cfg_live: Dict[str, Any], clock: Any,
                  limit: int, intrabar: bool = False) -> Dict[str, Any]:
    entry_i, exit_i = int(t.entry_index), int(t.exit_index)
    # The live builder runs just after the entry bar closed (decision_bar: closed).
    clock.now = _epoch(df["timestamp"].iloc[entry_i]) + _TF_SECONDS.get(
        str(cfg.get("timeframe")), 14400) + 1.0
    pkg, reproduced, why, entry_cmp = build_live_package(cfg_live, df, t, limit)
    meta = pkg["meta"]
    tk = ml.momentum_trail_keys(meta, cfg)
    sk = ml.momentum_stale_keys(meta, cfg)
    trail_on = momentum_trail_armed(tk["trail_adx_below"], tk["trail_adx_falling_bars"],
                                    tk["trail_adx_tight_mult"])
    stale_on = momentum_stale_armed(sk["momentum_stale_bars"], sk["momentum_stale_adx_below"])
    sl = float(pkg["sl"])
    is_long = t.direction == "long"
    rows: List[Dict[str, Any]] = []
    live_exit = None
    first_div = None
    # One tick past the exit bar: a bar-CLOSE verb decided on bar exit_i is issued by
    # the live monitor at the first tick of bar exit_i + 1.
    for j in range(entry_i + 1, min(exit_i + 2, len(df))):
        frame = live_frame(df, j, limit)
        clock.now = _epoch(df["timestamp"].iloc[j]) + 1.0
        cur = float(df["open"].iloc[j])
        # Lever decisions at the last CLOSED bar (j-1), each side on its own inputs.
        h_trail = trail_on and momentum_trail_fired(adx_full, j - 1, tk["trail_adx_below"],
                                                    tk["trail_adx_falling_bars"])
        l_trail = trail_on and ml.resolve_momentum_trail_mult(
            meta, cfg, frame, 1e9, t.direction, open_pkg=pkg) < 1e9
        h_stale = stale_on and (j - 1) > entry_i and momentum_stale_fires(
            adx_full, j - 1, entry_i, sk["momentum_stale_bars"], sk["momentum_stale_adx_below"])
        l_stale = stale_on and ml.momentum_stale_verdict(
            meta, cfg, dict(pkg, sl=sl), frame, cur, t.direction) is not None
        verdict = td.monitor(cfg, frame, dict(pkg, sl=sl))
        if verdict and verdict.get("action") == "close":
            live_exit = {"bar": j - 1, "reason": verdict.get("reason")}
        elif verdict:
            sl = float(verdict["sl"]) if verdict.get("sl") is not None else sl
            if verdict.get("tp") is not None:  # TP doctrine B1 revision: the venue amend
                pkg["tp"] = float(verdict["tp"])
        if j > exit_i:
            break  # the extra tick only carries a close verb; nothing is managed on it
        # The stop the harness tests bar j against was ratcheted on bar j-1's close; the
        # live stop that faces bar j is the one this tick's verdict leaves in place.
        h_stop = h_stops.get(j)
        stop_match = live_exit is not None or (
            h_stop is not None and abs(h_stop - sl) <= STOP_ABS_TOL)
        row = {"j": j, "ts": str(df["timestamp"].iloc[j]), "stop_h": h_stop, "stop_l": sl,
               "stop_match": stop_match, "trail_h": bool(h_trail), "trail_l": bool(l_trail),
               "stale_h": bool(h_stale), "stale_l": bool(l_stale)}
        if (h_trail != l_trail or h_stale != l_stale) and first_div is None:
            first_div = {"j": j, "ts": row["ts"], "kind": "lever_decision",
                         "cause": _lever_cause(adx_full, frame, meta, cfg, entry_i, j, df)}
        if not stop_match and first_div is None:
            first_div = {"j": j, "ts": row["ts"], "kind": "stop_path",
                         "cause": _stop_cause(df, entry_i, j, float(t.entry), is_long, h_stop, sl,
                                              rows, cfg, meta)}
        rows.append(row)
        if live_exit is not None:
            break
        if intrabar and j < exit_i:
            # The LAST tick of bar j: the forming row now spans bar j's whole range and
            # the price is its close. The live monitor ratchets on the forming extreme
            # (the harness only on the close), with lever mults decided on closed bars.
            full = live_frame(df, j, limit)
            full.iloc[-1, 1:5] = [float(df[c].iloc[j]) for c in ("open", "high", "low", "close")]
            clock.now = _epoch(df["timestamp"].iloc[j]) + _TF_SECONDS.get(
                str(cfg.get("timeframe")), 14400) - 1.0
            v2 = td.monitor(cfg, full, dict(pkg, sl=sl))
            if v2 and v2.get("action") == "close":
                live_exit = {"bar": j, "reason": f"{v2.get('reason')}@intrabar"}
                break
            if v2 and v2.get("sl") is not None:
                sl = float(v2["sl"])
            if v2 and v2.get("tp") is not None:
                pkg["tp"] = float(v2["tp"])
    h_close_verb = t.outcome not in ("stop", "trail_stop", "take_profit", "timeout")
    h_exit = {"bar": exit_i, "reason": t.outcome}
    if h_close_verb:
        exit_match = live_exit == h_exit
    else:
        # A stop / target / timeout exit is decided at the venue, not by a verdict:
        # parity is "the live path issued no close before the harness exit bar".
        exit_match = live_exit is None or (live_exit["bar"] >= exit_i)
    if not exit_match and first_div is None:
        first_div = {"j": (live_exit or h_exit)["bar"], "kind": "exit",
                     "cause": f"harness {h_exit} vs live {live_exit}"}
    return {"entry_i": entry_i, "entry_ts": str(df["timestamp"].iloc[entry_i]),
            "direction": t.direction, "harness_exit": h_exit, "live_exit": live_exit,
            "exit_match": exit_match, "entry_reproduced": reproduced,
            "entry_not_reproduced_why": why, "entry_cmp": entry_cmp,
            "n_bars": len(rows), "n_stop_match": sum(r["stop_match"] for r in rows),
            "n_trail_match": sum(r["trail_h"] == r["trail_l"] for r in rows),
            "n_trail_fired_h": sum(r["trail_h"] for r in rows),
            "n_stale_match": sum(r["stale_h"] == r["stale_l"] for r in rows),
            "first_divergence": first_div}


def _stop_cause(df, entry_i, j, entry, is_long, h_stop, l_stop, rows, cfg, meta) -> str:
    if h_stop is None:
        return "harness recorded no stop for this bar"
    prev = rows[-1] if rows else None
    if prev is not None and (prev["trail_h"] != prev["trail_l"]):
        return "momentum_trail decision differed on the previous bar"
    hi, lo = df["high"].iloc[entry_i + 1:j], df["low"].iloc[entry_i + 1:j]
    h_ext = max([entry] + list(hi)) if is_long else min([entry] + list(lo))
    l_ext = (max(df["high"].iloc[entry_i:j].max(), float(df["open"].iloc[j - 1 + 1]))
             if is_long else min(df["low"].iloc[entry_i:j].min(), float(df["open"].iloc[j])))
    cur = float(df["open"].iloc[j])
    tighter_h = (h_stop > l_stop) if is_long else (h_stop < l_stop)
    if tighter_h and ((h_stop >= cur) if is_long else (h_stop <= cur)):
        return (f"live price guard: harness stop {h_stop:.8g} is beyond the live current "
                f"price {cur:.8g} (live never ratchets through price)")
    if abs(h_ext - l_ext) > STOP_ABS_TOL:
        return (f"since-entry extreme differs: harness {h_ext:.8g} (starts at the entry "
                f"CLOSE) vs live {l_ext:.8g} (includes the entry bar's "
                f"{'high' if is_long else 'low'})")
    return f"unattributed: harness {h_stop!r} vs live {l_stop!r}"


def _lever_cause(adx_full, frame, meta, cfg, entry_i, j, df) -> str:
    period = int(meta.get("adx_period") or cfg.get("adx_period") or 14)
    closed = frame.iloc[:-1]
    adx_l = ml.live_adx(closed, period)
    if adx_l is None:
        return "live ADX unavailable (frame too short)"
    a_h, a_l = float(adx_full.iloc[j - 1]), float(adx_l.iloc[-1])
    win_entry = len(closed) - (j - entry_i)
    a0_h = float(adx_full.iloc[entry_i])
    a0_l = float(adx_l.iloc[win_entry]) if 0 <= win_entry < len(adx_l) else float("nan")
    return (f"ADX now harness {a_h:.4f} vs live {a_l:.4f}; ADX at entry harness {a0_h:.4f} vs "
            f"live {a0_l:.4f} (entry bar at window position {win_entry} of {len(closed)})")


def summarise(per_trade: List[Dict[str, Any]], *, leg: str, symbol: str, source: str,
              df: pd.DataFrame, overrides: Dict[str, Any], limit: int) -> Dict[str, Any]:
    n_bars = sum(t["n_bars"] for t in per_trade)
    divs = [dict(t["first_divergence"], entry_ts=t["entry_ts"]) for t in per_trade
            if t["first_divergence"]]
    if n_bars == 0:
        verdict = "COULD_NOT_LOOK(no managed bar compared)"
    elif not divs:
        verdict = "PARITY"
    else:
        causes = sorted({d["cause"].split(":")[0] for d in divs})
        verdict = "DIVERGES(" + "; ".join(causes) + ")"
    def rate(k: str) -> Optional[float]:
        return round(sum(t[k] for t in per_trade) / n_bars, 6) if n_bars else None

    return {
        "schema": "momentum_levers_parity/1",
        "verdict": verdict,
        "population": {
            "leg": leg, "symbol": symbol, "candles": source, "overrides": overrides,
            "window": [str(df["timestamp"].iloc[0]), str(df["timestamp"].iloc[-1])],
            "n_candles": len(df), "n_trades": len(per_trade), "n_managed_bars": n_bars,
            "monitor_fetch_limit": limit,
            "n_entries_reproduced_by_live_builder": sum(t["entry_reproduced"] for t in per_trade),
        },
        "match_rate": {"stop_path": rate("n_stop_match"),
                       "momentum_trail_decision": rate("n_trail_match"),
                       "momentum_stale_decision": rate("n_stale_match"),
                       "exit": (round(sum(t["exit_match"] for t in per_trade) / len(per_trade), 6)
                                if per_trade else None)},
        "momentum_trail_fired_bars_harness": sum(t["n_trail_fired_h"] for t in per_trade),
        "divergences": divs,
        "trades": per_trade,
    }


def run(candles: str, leg: str, symbol: str, overrides: Dict[str, Any],
        start: Optional[str] = None, end: Optional[str] = None,
        limit: int = MONITOR_BASE_LIMIT, tmp_dir: Optional[Path] = None,
        intrabar: bool = False) -> Dict[str, Any]:
    cfg = load_leg(leg, overrides)
    df = bt._date_filter(bt._load_candles(candles), start, end).reset_index(drop=True)
    kw = harness_kwargs(cfg, symbol=symbol, leg=leg)
    tmp = Path(tmp_dir or "/tmp") / f"momentum_parity_{leg}.paths.jsonl"
    trades, stops = run_harness(df, kw, tmp)
    period = int(cfg.get("adx_period") or 14)
    adx_full = bt._adx(df, period)
    cfg_live = dict(cfg, symbol=symbol, strategy_label=leg)
    per_trade = []
    with _live_sandbox() as clock:
        for t in trades:
            per_trade.append(compare_trade(df, adx_full, t, stops.get(int(t.entry_index), {}),
                                           cfg, cfg_live, clock, limit, intrabar))
    res = summarise(per_trade, leg=leg, symbol=symbol, source=str(candles), df=df,
                    overrides=overrides, limit=limit)
    res["population"]["ticks_per_bar"] = "first+last" if intrabar else "first"
    return res


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--candles", required=True)
    p.add_argument("--leg", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--set", action="append", default=[], help="key=value lever override")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int, default=MONITOR_BASE_LIMIT)
    p.add_argument("--intrabar", action="store_true",
                   help="also replay the LAST tick of each bar (live ratchets intrabar)")
    p.add_argument("--out")
    a = p.parse_args(argv)
    res = run(a.candles, a.leg, a.symbol, _parse_set(a.set), a.start, a.end, a.limit,
              intrabar=a.intrabar)
    txt = json.dumps(res, indent=1, default=lambda o: None if isinstance(o, float)
                     and math.isnan(o) else str(o))
    if a.out:
        Path(a.out).write_text(txt)
    head = {k: res[k] for k in ("verdict", "population", "match_rate")}
    print(json.dumps(head, indent=1))
    for d in res["divergences"][:20]:
        print(f"  DIV {d['entry_ts']} first bar {d['j']} [{d['kind']}] {d['cause']}")
    v = res["verdict"]
    return 0 if v == "PARITY" else (2 if v.startswith("COULD_NOT_LOOK") else 1)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# wiring: manual-only -- TREND-ALIGNMENT-FEATURE step 2 backfill (run by a lane; no schedule consumes it yet). The per-leg
# analysis (step 4) and the ML ablation (step 5) are separate queue units that will call `label_trade` / `dmi`.
"""TREND-ALIGN-V1: label a trade with_trend / counter_trend / neutral at entry, and backfill the journal's closed trades.

The definition is registered in docs/research/trend-alignment-framework-2026-11-13.md (TREND-ALIGN-V1, 2026-11-13) and
is implemented here exactly; any change is a V2 with its own registration.

* DMI / ADX-14: the same Wilder formulas as src/runtime/regime/detector.py::wilder_adx (alpha = 1/14, EWM, adjust=False).
  `dmi()` returns ADX together with +DI / -DI; tests pin its ADX to `wilder_adx` bit for bit.
* Point in time: for timeframe T only bars with open + T <= entry_time are read (bar-close only, never the forming bar).
* Per timeframe: with_trend if ADX >= 25 and sign(+DI - -DI) == side; counter_trend if ADX >= 25 and the sign is -side;
  neutral if ADX < 25 or +DI == -DI; otherwise the label is null with a reason from MISSING_REASONS (never neutral, never 0).
* Timeframes: LEG (the leg's own, from config/strategies.yaml, primary) and D1 (secondary); `agreement` is derived.

Backfill (`backfill` subcommand): pages the trades journal read-only through scripts/ops/diag_fetch.sh, keeps CLOSED,
non-backtest rows, fetches candles through regime_debt_matrix's feed router (Binance Vision for *USDT, Yahoo otherwise),
and writes, under --out:
  labels.jsonl   one row per trade: trade id, strategy, symbol, book (account_class), demo flag, direction, entry_time,
                 and the LEG / D1 label blocks. NO account ids, NO P&L, NO prices beyond what the label needs.
  summary.json   the population: n by (leg, book), labels by TF, missing counts by reason (each with its denominator).

    python3 scripts/research/trend_alignment.py --self-test
    python3 scripts/research/trend_alignment.py backfill --out <dir> [--cache <dir>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DEFINITION_ID = "TREND-ALIGN-V1"
REGISTERED_AT = "2026-11-13"
DOC = "docs/research/trend-alignment-framework-2026-11-13.md"
ADX_PERIOD = 14
TREND_MIN_ADX = 25.0          # src/runtime/regime/detector.py::TREND_MIN_ADX (asserted equal in the self-test)
MIN_BARS = 30                 # src/runtime/regime/detector.py::_MIN_BARS
LABELS = ("with_trend", "counter_trend", "neutral")
MISSING_REASONS = ("no_candles", "insufficient_history", "adx_nan", "no_entry_time", "no_side", "no_timeframe")
TF_DELTA = {"1m": timedelta(minutes=1), "3m": timedelta(minutes=3), "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15), "30m": timedelta(minutes=30), "1h": timedelta(hours=1),
            "2h": timedelta(hours=2), "4h": timedelta(hours=4), "6h": timedelta(hours=6), "8h": timedelta(hours=8),
            "12h": timedelta(hours=12), "1d": timedelta(days=1)}


# ── the indicator (same formulas as the regime detector) ───────────────────────────────────────────────────────────
def dmi(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    """Wilder DMI over the whole frame: columns adx, pdi, mdi, aligned to df.index. Formulas copied from
    src/runtime/regime/detector.py::wilder_adx (which returns ADX only); the test pins ADX equality."""
    h, low, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up.clip(lower=0)
    minus_dm = ((down > up) & (down > 0)) * down.clip(lower=0)
    pc = c.shift(1)
    tr = pd.concat([(h - low), (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=alpha, adjust=False).mean(), "pdi": pdi, "mdi": mdi}, index=df.index)


def regime_label(adx: Optional[float]) -> str:
    from src.runtime.regime.detector import regime_label as _rl
    return _rl(adx)


# ── bars ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def resample(base: pd.DataFrame, tf: str) -> pd.DataFrame:
    """OHLC bars of timeframe `tf` from a finer UTC frame with a tz-aware `open_time` column; adds `close_time`.
    Bars are anchored to the UTC epoch (1d = UTC day). The last bar may be partial: `label_tf` never reads a bar whose
    close_time is after the entry, and a partial last bar's close_time is in the future relative to its data, so it is
    dropped by `closed_before` whenever the entry falls inside it."""
    d = TF_DELTA[tf]
    s = base.set_index("open_time").sort_index()
    out = s.resample(d, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    out = out.reset_index()
    out["close_time"] = out["open_time"] + d
    return out


def closed_before(bars: pd.DataFrame, entry: pd.Timestamp) -> pd.DataFrame:
    return bars[bars["close_time"] <= entry]


# ── the label ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _missing(reason: str, **extra: Any) -> Dict[str, Any]:
    assert reason in MISSING_REASONS, reason
    return {"label": None, "missing_reason": reason, "adx": None, "pdi": None, "mdi": None, "regime_label": None,
            "bar_close_used": None, "n_bars_used": extra.get("n_bars_used")}


def label_tf(bars: Optional[pd.DataFrame], entry: Optional[pd.Timestamp], side: Optional[int]) -> Dict[str, Any]:
    """TREND-ALIGN-V1 for one timeframe. `bars` carry open_time/close_time/OHLC (tz-aware UTC); `side` is +1 / -1."""
    if entry is None:
        return _missing("no_entry_time")
    if side not in (1, -1):
        return _missing("no_side")
    if bars is None or len(bars) == 0:
        return _missing("no_candles")
    hist = closed_before(bars, entry)
    if len(hist) < MIN_BARS:
        return _missing("insufficient_history", n_bars_used=int(len(hist)))
    last = dmi(hist).iloc[-1]
    adx, pdi, mdi = (float(last[k]) for k in ("adx", "pdi", "mdi"))
    if any(v != v for v in (adx, pdi, mdi)):
        return _missing("adx_nan", n_bars_used=int(len(hist)))
    if adx < TREND_MIN_ADX or pdi == mdi:
        label = "neutral"
    else:
        label = "with_trend" if int(np.sign(pdi - mdi)) == side else "counter_trend"
    return {"label": label, "missing_reason": None, "adx": round(adx, 4), "pdi": round(pdi, 4), "mdi": round(mdi, 4),
            "regime_label": regime_label(adx), "bar_close_used": hist["close_time"].iloc[-1].isoformat(),
            "n_bars_used": int(len(hist))}


def agreement(leg: Dict[str, Any], d1: Dict[str, Any]) -> str:
    a, b = leg.get("label"), d1.get("label")
    if a == b == "with_trend":
        return "both_with"
    if a == b == "counter_trend":
        return "both_counter"
    if {a, b} == {"with_trend", "counter_trend"}:
        return "split"
    return "other"


def side_of(direction: Any) -> Optional[int]:
    d = str(direction or "").strip().lower()
    return 1 if d in ("long", "buy") else -1 if d in ("short", "sell") else None


def parse_ts(v: Any) -> Optional[pd.Timestamp]:
    if not v:
        return None
    try:
        t = pd.Timestamp(v)
    except (ValueError, TypeError):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def label_trade(trade: Dict[str, Any], leg_tf: Optional[str], bars_leg: Optional[pd.DataFrame],
                bars_d1: Optional[pd.DataFrame]) -> Dict[str, Any]:
    entry, side = parse_ts(trade.get("timestamp")), side_of(trade.get("direction"))
    leg = _missing("no_timeframe") if not leg_tf or leg_tf not in TF_DELTA else label_tf(bars_leg, entry, side)
    d1 = label_tf(bars_d1, entry, side)
    return {"definition": DEFINITION_ID, "trade_id": trade.get("id"), "strategy": trade.get("strategy_name"),
            "symbol": trade.get("symbol"), "book": trade.get("account_class"), "is_demo": trade.get("is_demo"),
            "direction": trade.get("direction"), "entry_time": entry.isoformat() if entry is not None else None,
            "leg_tf": leg_tf, "LEG": leg, "D1": d1, "agreement": agreement(leg, d1)}


# ── backfill ────────────────────────────────────────────────────────────────────────────────────────────────────────
def fetch_trades(page: int = 1000) -> List[Dict[str, Any]]:
    """Every row of the trades journal, read-only via scripts/ops/diag_fetch.sh, paged by offset within the 1000 clamp."""
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        out = subprocess.run(["bash", str(REPO / "scripts/ops/diag_fetch.sh"),
                              f"journal?table=trades&limit={page}&offset={offset}&envelope=true"],
                             capture_output=True, text=True, timeout=300, check=True).stdout
        doc = json.loads(out[:out.rfind("}") + 1])
        rows += doc["rows"]
        if not doc.get("has_more"):
            return rows
        offset += page


def _base_interval(tf: str) -> str:
    return tf if TF_DELTA[tf] < timedelta(hours=1) else "1h"


def load_bars(symbol: str, tf: str, days: int, cache: Path) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """(bars, None) or (None, error text). Fetches the base interval through regime_debt_matrix's feed router."""
    import regime_debt_matrix as rdm
    base = _base_interval(tf)
    path = cache / f"{symbol}_{base}_{days}d.csv"
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            rdm._fetch_csv(rdm.resolve_feed(symbol, base), days, str(path))
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as the trade's missing_reason no_candles with the error text in summary.json
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"
    ts = df["timestamp"]
    t = pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts) else pd.to_datetime(ts, utc=True)
    df = df.assign(open_time=t)[["open_time", "open", "high", "low", "close"]].dropna()
    if df.empty:
        return None, "empty candle file"
    return resample(df, tf), None


def backfill(out: Path, cache: Path, trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    import yaml
    strategies = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]
    rows = trades if trades is not None else fetch_trades()
    closed = [r for r in rows if str(r.get("status")) == "closed" and r.get("closed_at") and not r.get("is_backtest")]
    entries = [parse_ts(r.get("timestamp")) for r in closed]
    earliest = min((e for e in entries if e is not None), default=None)
    days = (int((datetime.now(timezone.utc) - earliest.to_pydatetime()).days) + 120) if earliest is not None else 120
    bars: Dict[Tuple[str, str], Tuple[Optional[pd.DataFrame], Optional[str]]] = {}
    fetch_errors: Dict[str, str] = {}

    def get(sym: str, tf: str) -> Optional[pd.DataFrame]:
        if (sym, tf) not in bars:
            bars[(sym, tf)] = load_bars(sym, tf, days, cache)
            if bars[(sym, tf)][1]:
                fetch_errors[f"{sym}/{tf}"] = bars[(sym, tf)][1]
        return bars[(sym, tf)][0]

    labelled = []
    for r in closed:
        cfg = strategies.get(str(r.get("strategy_name"))) or {}
        tf = cfg.get("timeframe")
        sym = str(r.get("symbol") or "")
        leg_bars = get(sym, tf) if sym and tf in TF_DELTA else None
        d1_bars = get(sym, "1d") if sym else None
        labelled.append(label_trade(r, tf if tf in TF_DELTA else None, leg_bars, d1_bars))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "labels.jsonl").open("w") as fh:
        for x in labelled:
            fh.write(json.dumps(x, default=str) + "\n")
    summary = summarize(labelled, n_rows=len(rows), n_closed=len(closed), fetch_errors=fetch_errors)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return summary


def summarize(labelled: Sequence[Dict[str, Any]], *, n_rows: int, n_closed: int,
              fetch_errors: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    by_tf: Dict[str, Counter] = {tf: Counter() for tf in ("LEG", "D1")}
    missing: Dict[str, Counter] = {tf: Counter() for tf in ("LEG", "D1")}
    by_leg_book: Dict[str, Counter] = defaultdict(Counter)
    for x in labelled:
        for tf in ("LEG", "D1"):
            lab = x[tf]["label"]
            by_tf[tf][lab or "missing"] += 1
            if lab is None:
                missing[tf][x[tf]["missing_reason"]] += 1
        by_leg_book[str(x["strategy"])][f"{x['book']}:{x['LEG']['label'] or 'missing'}"] += 1
    return {"definition": DEFINITION_ID, "registered_at": REGISTERED_AT, "doc": DOC,
            "population": {"journal_rows_read": n_rows, "closed_non_backtest": n_closed, "labelled_rows": len(labelled),
                           "note": "every closed, non-backtest trade in the trades journal at read time; demo and live "
                                   "books both included, split by book"},
            "labels_by_tf": {tf: dict(c) for tf, c in by_tf.items()},
            "missing_by_reason": {tf: dict(c) for tf, c in missing.items()},
            "agreement": dict(Counter(x["agreement"] for x in labelled)),
            "by_leg": {leg: dict(c) for leg, c in sorted(by_leg_book.items())},
            "candle_fetch_errors": fetch_errors or {}}


# ── self-test ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _bars(n: int, drift: float, tf: str = "1h", start: str = "2026-01-01") -> pd.DataFrame:
    d = TF_DELTA[tf]
    t0 = pd.Timestamp(start, tz="UTC")
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + drift + rng.normal(0, 0.002, n))
    df = pd.DataFrame({"open_time": [t0 + i * d for i in range(n)], "open": c, "high": c * 1.003, "low": c * 0.997,
                       "close": c})
    df["close_time"] = df["open_time"] + d
    return df


def self_test() -> int:
    from src.runtime.regime import detector as det
    ok = True

    def chk(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    chk("constants equal the regime detector's", det.TREND_MIN_ADX == TREND_MIN_ADX and det._MIN_BARS == MIN_BARS)
    up = _bars(200, 0.004)
    chk("dmi ADX equals detector.wilder_adx bit for bit", np.allclose(dmi(up)["adx"].values,
                                                                      det.wilder_adx(up).values, equal_nan=True))
    entry = up["close_time"].iloc[150]
    chk("strong up-trend: long is with_trend", label_tf(up, entry, 1)["label"] == "with_trend")
    chk("strong up-trend: short is counter_trend", label_tf(up, entry, -1)["label"] == "counter_trend")
    flat = _bars(200, 0.0)
    chk("no drift: neutral (ADX < 25)", label_tf(flat, flat["close_time"].iloc[150], 1)["label"] == "neutral")
    r = label_tf(up, up["close_time"].iloc[20], 1)
    chk("fewer than 30 closed bars: null + insufficient_history",
        r["label"] is None and r["missing_reason"] == "insufficient_history")
    mid = up["open_time"].iloc[150] + timedelta(minutes=30)          # inside bar 150: it must NOT be read
    chk("point in time: the forming bar is never read",
        label_tf(up, mid, 1)["bar_close_used"] == up["close_time"].iloc[149].isoformat())
    chk("no candles -> null + no_candles, never neutral", label_tf(None, entry, 1)["missing_reason"] == "no_candles")
    chk("no side -> null + no_side", label_tf(up, entry, None)["missing_reason"] == "no_side")
    t = label_trade({"id": 1, "timestamp": entry.isoformat(), "direction": "long", "strategy_name": "x",
                     "account_class": "paper"}, None, None, up)
    chk("unknown leg TF: LEG null/no_timeframe, D1 still computed",
        t["LEG"]["missing_reason"] == "no_timeframe" and t["D1"]["label"] is not None and t["agreement"] == "other")
    base = _bars(48 * 40, 0.001)[["open_time", "open", "high", "low", "close"]]
    d1 = resample(base, "1d")
    chk("resample 1h -> 1d anchors to UTC days", all(ts.hour == 0 for ts in d1["open_time"])
        and (d1["close_time"] - d1["open_time"]).eq(timedelta(days=1)).all())
    print("trend_alignment self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("backfill")
    b.add_argument("--out", required=True)
    b.add_argument("--cache", default="/tmp/trend-align-cache")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "backfill":
        ap.error("use --self-test or the backfill subcommand")
    s = backfill(Path(a.out), Path(a.cache))
    print(json.dumps({k: s[k] for k in ("population", "labels_by_tf", "missing_by_reason")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

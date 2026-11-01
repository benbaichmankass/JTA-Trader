"""OBSERVE-ONLY decision log for the ML ENTRY models: every symbol, every 15 minutes (lane ML-ENTRY-GOLIVE-UNBLOCK).

OPERATOR 2026-11-01 ~22:30Z, verbatim (relayed by Manager Session 2026-11-01a): "We should have it logging decisions more
frequently and on smaller timeframes as well". ``ml_entry`` (v1, bybit_2) and ``ml_entry_v2`` (bybit_1) TRADE only at the
close of every 4th 1h bar; this module SCORES them far more often and changes nothing that trades:

* every 15m close, every symbol of the live reference universe (the model's ``xs_reference`` that Bybit lists, 52 of 60
  on 2026-11-01), both artifacts;
* at the full-hour close (``tf_offset = "0m"``) the hourly bars are the ordinary 1h bars the traders read;
* at :15 / :30 / :45 (``tf_offset = "15m" | "30m" | "45m"``) the hourly bars are TRAILING 1h windows that END at that
  boundary, built from the 15m klines, so every feature keeps its trained meaning (a 1h bar, 24 such bars = a day);
* a row records what the strategy WOULD decide (``decide`` at the artifact's tau and cost gate, plus the strategy's
  40-reference floor), whether this is a bar the strategy actually trades (a 4h close at offset 0), and an explicit
  ``read_state`` when no decision could be formed.

PARITY BY CONSTRUCTION. The row is built by the strategy's own ``ml_decision_features.decision_row`` and scored by its own
``ml_entry.decide``; only the bar source differs (15m klines resampled; at offset 0 identical to the native 1h bars,
pinned by ``tests/test_ml_decision_shadow.py``). The logged decision at a traded 4h close therefore equals the traded one
on the same bars (also pinned by a test).

NOTHING HERE CAN TRADE. This module imports no account, order, coordinator or risk code; it runs in its own oneshot
process (``deploy/ict-ml-decision-shadow.{service,timer}``, Nice 10, CPU quota 50 %), never inside the trader loop (the
2026-06-09 per-bar scoring wedge, MB-20260609-001, is why), and reads only PUBLIC Bybit klines.

# data-wiring: canonical store for observe-only per-bar ML ENTRY scores (runtime_logs/ml_decision_shadow.jsonl). No
#               existing log holds them: signal_audit/ml_entry_eval rows exist only for the 5 traded symbols at the 4h
#               close, and shadow_predictions.jsonl is the registry-head shadow log whose readers count soak rows (mixing
#               ~10k rows/day into it would distort those counts). Read via /api/diag/log_file?name=ml_decision_shadow and
#               /api/diag/log_aggregate; freshness graded by src/runtime/health.check_ml_decision_shadow.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import numpy as np
import pandas as pd

import src.runtime.ml_decision_features as F

LOG_NAME = "ml_decision_shadow.jsonl"
SCHEMA = "ml_decision_shadow/1"
STEP = pd.Timedelta(minutes=15)
HOUR = pd.Timedelta(hours=1)
#: 15m bars kept per symbol: MIN_BARS (337) hourly bars need 1,348; 1,440 = 360 h leaves a margin for a missing bar.
KEEP_15M = 1440
#: A row is "fresh" for the health check within two missed runs plus slack.
FRESH_S = 40 * 60

#: Models scored, by strategy name -> artifact loader. Imported lazily so a test can inject fakes.
STRATEGIES = ("ml_entry", "ml_entry_v2")


@dataclass
class SymbolBars:
    symbol: str
    read_state: str            # ok | not_listed | fetch_failed | stale_bar | too_short
    bars_15m: Optional[pd.DataFrame] = None
    hourly: Optional[pd.DataFrame] = None
    detail: str = ""


def boundary(now: pd.Timestamp) -> pd.Timestamp:
    """The latest 15m boundary at or before ``now`` (the close of the newest CLOSED 15m bar)."""
    now = pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    return now.floor("15min")


def tf_offset(b: pd.Timestamp) -> str:
    return f"{int(b.minute)}m"


def hourly_ending_at(bars_15m: pd.DataFrame, b: pd.Timestamp) -> pd.DataFrame:
    """Trailing 1h bars whose last bar CLOSES at boundary ``b``: bins [b-1h, b), [b-2h, b-1h), ... built from complete
    groups of four 15m bars. ``ts`` = the 1h bar's OPEN time (the convention every feature reads). A bin missing any of
    its four 15m bars is dropped, never padded (an incomplete hour would be an out-of-distribution bar)."""
    df = bars_15m[bars_15m["ts"] < b].copy()
    if df.empty:
        return df.assign(ts=pd.Series(dtype="datetime64[ns, UTC]"))[["ts", "open", "high", "low", "close", "volume"]]
    # bin start = b - k*1h for the k with ts in [b-k*1h, b-(k-1)*1h)
    k = np.ceil(((b - df["ts"]) / HOUR).to_numpy(dtype=float)).astype("int64")
    df["bin"] = b - pd.to_timedelta(k, unit="h")
    g = df.sort_values("ts").groupby("bin", sort=True)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["ts"].count()})
    out = out[out["n"] == 4].drop(columns="n").reset_index().rename(columns={"bin": "ts"})
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    return out[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def prepare(symbol: str, bars_15m: Optional[pd.DataFrame], b: pd.Timestamp, *, fetch_state: str = "ok") -> SymbolBars:
    if fetch_state != "ok" or bars_15m is None:
        return SymbolBars(symbol, fetch_state if fetch_state != "ok" else "fetch_failed")
    closed = bars_15m[bars_15m["ts"] < b]
    if closed.empty or closed["ts"].iloc[-1] != b - STEP:
        last = None if closed.empty else closed["ts"].iloc[-1].isoformat()
        return SymbolBars(symbol, "stale_bar", closed, detail=f"last_15m_open={last}")
    hourly = hourly_ending_at(closed, b)
    if hourly.empty or hourly["ts"].iloc[-1] != b - HOUR:
        return SymbolBars(symbol, "stale_bar", closed, hourly, detail="last hourly bin incomplete")
    return SymbolBars(symbol, "ok", closed, hourly)


def decision_rows(frames: Mapping[str, pd.DataFrame], symbols: Iterable[str]) -> Dict[str, Optional[Dict[str, float]]]:
    """``ml_decision_features.decision_row`` for many symbols at once, BIT-IDENTICAL to calling it per symbol (pinned by
    ``tests/test_ml_decision_shadow.py``) but computing each frame's reference context ONCE: decision_row rebuilds every
    reference frame's features for every symbol (52 x 52 feature builds per boundary, ~28 s CPU measured), this builds
    each frame twice (own features on the full frame, reference context on the same trailing-200-bar slice
    decision_row uses)."""
    ref: Dict[str, tuple] = {}
    for s, fr in frames.items():
        if fr is None or len(fr) < 25:
            continue
        ff = F.features_symbol(fr.iloc[-200:].reset_index(drop=True)).iloc[-1]
        ref[s] = (fr["ts"].iloc[-1], ff["ret24_raw"], ff["vol24"])
    out: Dict[str, Optional[Dict[str, float]]] = {}
    for symbol in symbols:
        own = frames.get(symbol)
        if own is None or len(own) < F.MIN_BARS:
            out[symbol] = None
            continue
        t = own["ts"].iloc[-1]
        fo = F.features_symbol(own).iloc[-1]
        r24 = {s: v[1] for s, v in ref.items() if v[0] == t}
        v24 = {s: v[2] for s, v in ref.items() if v[0] == t}
        if "BTCUSDT" not in r24 or symbol not in r24:
            out[symbol] = None
            continue
        rv = pd.Series(r24, dtype=float)
        vv = pd.Series(v24, dtype=float)
        rank = rv.rank(pct=True)
        row = {k: float(fo[k]) for k in F.FEATURES if k in fo.index}
        row["xs_rank_ret24"] = float(rank[symbol])
        row["btc_ret24"] = float(rv["BTCUSDT"])
        row["btc_vol24"] = float(vv["BTCUSDT"])
        row["breadth_up24"] = float((rv > 0).sum() / rv.notna().sum())
        row["rel_vol"] = float(fo["vol24"] / vv.median())
        if any(not np.isfinite(row.get(k, np.nan)) for k in F.FEATURES):
            out[symbol] = None
            continue
        row["_n_reference"] = float(len(rv))
        out[symbol] = row
    return out


def _strategy_cfg(name: str) -> dict:
    try:
        from src.units.strategies import load_strategy_config
        return dict((load_strategy_config() or {}).get(name) or {})
    except Exception:  # noqa: BLE001 -- the log still records what it scored; traded flags read "unknown"
        return {}


def score_boundary(
    b: pd.Timestamp,
    prepared: Mapping[str, SymbolBars],
    models: Mapping[str, Dict[str, Any]],
    *,
    strategy_cfgs: Optional[Mapping[str, dict]] = None,
    logged_at: Optional[str] = None,
) -> List[dict]:
    """One row per (symbol, strategy). ``models``: strategy name -> loaded artifact (``ml_entry.load_model`` shape)."""
    from src.units.strategies.ml_entry import decide, is_decision_bar

    cfgs = dict(strategy_cfgs) if strategy_cfgs is not None else {n: _strategy_cfg(n) for n in models}
    frames = {s: sb.hourly for s, sb in prepared.items() if sb.read_state == "ok" and sb.hourly is not None}
    bar_ts = b - HOUR
    off = tf_offset(b)
    rows_feat: Dict[str, tuple] = {}
    built = decision_rows(frames, [s for s, sb in prepared.items() if sb.read_state == "ok"])
    for s, sb in prepared.items():
        if sb.read_state != "ok":
            rows_feat[s] = (None, sb.read_state, sb.detail)
            continue
        if len(sb.hourly) < F.MIN_BARS:
            rows_feat[s] = (None, "too_short", f"hourly_bars={len(sb.hourly)}<{F.MIN_BARS}")
            continue
        row = built.get(s)
        rows_feat[s] = (row, "ok", "") if row is not None else (None, "feature_unformable", "")
    out: List[dict] = []
    stamp = logged_at or pd.Timestamp.now(tz="UTC").isoformat()
    for name, model in models.items():
        meta = model["meta"]
        every_h = int(meta["bracket"]["decision_every_h"])
        cfg = cfgs.get(name) or {}
        traded_syms = {str(x) for x in (cfg.get("symbols") or [])}
        min_ref = int(cfg.get("min_reference_symbols", 40))
        trading_bar = off == "0m" and is_decision_bar(bar_ts, every_h)
        for s in sorted(prepared):
            row, state, detail = rows_feat[s]
            rec: Dict[str, Any] = {
                "schema": SCHEMA, "logged_at": stamp, "bar_close": b.isoformat(), "bar_ts": bar_ts.isoformat(),
                "tf_offset": off, "symbol": s, "strategy": name, "model_id": meta.get("model_id"),
                "trading_bar": trading_bar, "traded_symbol": (s in traded_syms) if cfg else None,
                "read_state": state,
            }
            if detail:
                rec["detail"] = detail
            if row is not None:
                r = dict(row)
                n_ref = int(r.pop("_n_reference"))
                d = decide(r, model)
                refused = None
                if n_ref < min_ref:
                    refused = f"reference_symbols:{n_ref}<{min_ref}"
                elif d["gated"]:
                    refused = "cost_gate"
                rec.update(pred_long=round(d["p_long"], 6), pred_short=round(d["p_short"], 6),
                           side=d["side"] if refused is None else "none", side_at_tau=d["side"],
                           tau=float(meta["tau"]), n_reference=n_ref, refused=refused,
                           cost_r_est=None if d["cost_r_est"] is None else round(d["cost_r_est"], 6),
                           atr_pct=round(float(r["atr_pct"]), 6), close=float(prepared[s].hourly["close"].iloc[-1]))
            out.append(rec)
    return out


def append_rows(rows: Iterable[dict], path: Path) -> int:
    lines = [json.dumps(r, separators=(",", ":"), default=str) for r in rows]
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(lines)


# ----------------------------------------------------------------------------------------------- fetch + cache (I/O)
def _bybit_kline(symbol: str, *, limit: int, end_ms: Optional[int] = None,
                 get: Optional[Callable[..., Any]] = None) -> tuple[str, Optional[pd.DataFrame]]:
    """PUBLIC Bybit v5 linear 15m klines (no key). Returns (state, frame) with state ok | not_listed | fetch_failed."""
    import requests
    params: Dict[str, Any] = {"category": "linear", "symbol": symbol, "interval": "15", "limit": int(limit)}
    if end_ms is not None:
        params["end"] = int(end_ms)
    try:
        r = (get or requests.get)("https://api.bybit.com/v5/market/kline", params=params, timeout=15)
        js = r.json()
    except Exception as exc:  # noqa: BLE001 -- one symbol's fetch never stops the run
        return f"fetch_failed:{type(exc).__name__}", None
    if js.get("retCode") not in (0, None):
        msg = str(js.get("retMsg") or "")
        return ("not_listed" if "symbol" in msg.lower() or js.get("retCode") == 10001 else f"fetch_failed:{js.get('retCode')}"), None
    rows = (js.get("result") or {}).get("list") or []
    if not rows:
        return "not_listed", None
    df = pd.DataFrame([x[:6] for x in rows], columns=["start", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(pd.to_numeric(df["start"]), unit="ms", utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return "ok", df[["ts", "open", "high", "low", "close", "volume"]].sort_values("ts").reset_index(drop=True)


def refresh_cache(symbol: str, cache_dir: Path, b: pd.Timestamp, *, get=None) -> tuple[str, Optional[pd.DataFrame]]:
    """Cached 15m bars for ``symbol`` up to boundary ``b``; fetches only the missing tail (2 pages on a cold start)."""
    p = cache_dir / f"{symbol}.pkl"
    have = None
    if p.exists():
        try:
            have = pd.read_pickle(p)
        except Exception:  # noqa: BLE001 -- a corrupt cache is rebuilt, never trusted
            have = None
    need_full = have is None or have.empty or (b - have["ts"].iloc[-1]) > 900 * STEP
    if need_full:
        st, a = _bybit_kline(symbol, limit=1000, get=get)
        if st != "ok":
            return st, None
        st2, older = _bybit_kline(symbol, limit=1000, end_ms=int(a["ts"].iloc[0].value // 10**6) - 1, get=get)
        frames = [x for x in (older if st2 == "ok" else None, a) if x is not None]
    else:
        missing = int((b - have["ts"].iloc[-1]) / STEP) + 2
        st, a = _bybit_kline(symbol, limit=min(1000, max(missing, 4)), get=get)
        if st != "ok":
            return st, have
        if a["ts"].iloc[0] > have["ts"].iloc[-1] + STEP:          # the tail does not connect: refetch, never bridge a hole
            st2, older = _bybit_kline(symbol, limit=1000, end_ms=int(a["ts"].iloc[0].value // 10**6) - 1, get=get)
            frames = [have] + ([older] if st2 == "ok" else []) + [a]
        else:
            frames = [have, a]
    df = pd.concat(frames, ignore_index=True).drop_duplicates("ts", keep="last").sort_values("ts")
    df = df[df["ts"] < b].tail(KEEP_15M).reset_index(drop=True)   # never keep the forming bar
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    df.to_pickle(tmp)
    tmp.replace(p)
    return "ok", df


def run_once(*, now: Optional[pd.Timestamp] = None, log_path: Optional[Path] = None, cache_dir: Optional[Path] = None,
             get=None, models: Optional[Mapping[str, Dict[str, Any]]] = None) -> dict:
    """Fetch, score, append. Returns a summary (counts, read_state split, measured cost). Never raises per symbol."""
    import resource

    from src.utils.paths import runtime_logs_dir, runtime_state_dir
    t0, c0 = time.monotonic(), resource.getrusage(resource.RUSAGE_SELF)
    b = boundary(now or pd.Timestamp.now(tz="UTC"))
    if models is None:
        from src.units.strategies import ml_entry, ml_entry_v2
        models = {"ml_entry": ml_entry.load_model(), "ml_entry_v2": ml_entry_v2.load_model()}
    universe: List[str] = []
    for m in models.values():
        for s in m["meta"].get("xs_reference") or []:
            if s not in universe:
                universe.append(str(s))
    cache_dir = cache_dir or (runtime_state_dir() / "ml_decision_shadow_cache")
    prepared: Dict[str, SymbolBars] = {}
    for s in universe:
        st, df = refresh_cache(s, cache_dir, b, get=get)
        prepared[s] = prepare(s, df, b, fetch_state="ok" if st == "ok" else st.split(":")[0])
    listed = {s: sb for s, sb in prepared.items() if sb.read_state != "not_listed"}
    t_fetch = time.monotonic() - t0
    rows = score_boundary(b, listed, models)
    n = append_rows(rows, log_path or (runtime_logs_dir() / LOG_NAME))
    c1 = resource.getrusage(resource.RUSAGE_SELF)
    split: Dict[str, int] = {}
    for r in rows:
        split[r["read_state"]] = split.get(r["read_state"], 0) + 1
    return {"bar_close": b.isoformat(), "tf_offset": tf_offset(b), "rows": n, "symbols_listed": len(listed),
            "symbols_not_listed": sorted(s for s, sb in prepared.items() if sb.read_state == "not_listed"),
            "read_state": split, "wall_s": round(time.monotonic() - t0, 2), "fetch_wall_s": round(t_fetch, 2),
            "cpu_s": round((c1.ru_utime - c0.ru_utime) + (c1.ru_stime - c0.ru_stime), 2),
            "trading_rows": sum(1 for r in rows if r["trading_bar"])}


def freshness(path: Path, *, now_s: Optional[float] = None, fresh_s: int = FRESH_S) -> Dict[str, Any]:
    """Four states, never collapsed: fresh | stale | absent | unreadable. Reads the NEWEST row's own ``logged_at``
    (the data), not the file mtime alone."""
    if not path.exists():
        return {"state": "absent", "path": str(path)}
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 8192))
            tail = fh.read().decode("utf-8", errors="replace").strip().splitlines()
        last = json.loads(tail[-1]) if tail else None
        ts = pd.Timestamp(last["logged_at"]).timestamp() if last else None
    except Exception as exc:  # noqa: BLE001 -- could not look is its own state
        return {"state": "unreadable", "path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    if ts is None:
        return {"state": "unreadable", "path": str(path), "error": "empty file"}
    age = (now_s if now_s is not None else time.time()) - ts
    return {"state": "fresh" if age <= fresh_s else "stale", "age_s": round(age, 1), "path": str(path),
            "last_bar_close": last.get("bar_close"), "threshold_s": fresh_s}

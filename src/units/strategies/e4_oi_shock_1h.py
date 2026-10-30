"""e4_oi_shock_1h -- the E4 open-interest-shock continuation rule as a live leg (row E4-DEMO-LEG).

THE RULE, FROZEN (research/queue/blocked/RQ-20261030-e18g-02.yaml; the replay
``scripts/research/desk_event_entry_replay.py::detect`` E4 branch + ``GEOM``; PR #21720):
  detector  the 1h change of open interest (a 12-row lag on the 5-minute grid, the two rows exactly
            3600 s apart) has z >= 3 against the previous 2016 such changes (7 days), the window
            spanning at most 7.5 days; at most one event per symbol per 6 h (on known_at).
  known_at  metrics row time + 5 min (live: also no earlier than the trader first held the row --
            ``src/runtime/oi_feed.py::known_at``).
  cutoff    the first 1h boundary at or after known_at. The decision is taken on the 1h bar that
            CLOSES at the cutoff; the entry is a market order at the next open.
  side      the sign of that last closed 1h bar's return (close / previous close - 1); 0 -> no trade.
  bracket   from the cutoff close: SL 1.5 x ATR14, TP 3.0 x ATR14 (R:R 2), ATR14 = SMA of the true
            range over 14 bars (``desk_scan_packet.atr_series``). Time stop: the close of the 24th
            bar after the entry (``monitor``).
EVIDENCE   held-out 2024-11-01..2025-10-25, six USDT perps, 856 events: S3 vs a same-model random
           entry +0.184 R, 95 % weekly-cluster CI +0.092..+0.274, net of the full cost stack;
           absolute mean net R +0.022 R (PR #21720).
TP          a real predictive level: the frozen rule's 3.0 ATR target (declared as ``tp_r: 2.0`` on the
            1.5 ATR stop, so the TP doctrine scan reads it) is the level the replay scored (its hits are
            what the S3 measures); ``monitor`` never retargets it -- a TP revision is a different rule,
            untested (row E4-DEMO-LEG; tp-doctrine baseline line).

Pure: no account, mode, exchange or order knowledge. The builder
(``strategy_signal_builders.e4_oi_shock_1h_signal_builder``) supplies the closed 1h frame and the
stored OI rows.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence

NAME = "e4_oi_shock_1h"
HOUR = 3600

DEFAULTS: Dict[str, Any] = {
    "oi_z": 3.0, "oi_window": 2016, "oi_lag_rows": 12, "oi_cooldown_s": 6 * 3600,
    "oi_max_window_span_s": 7.5 * 86400, "atr_period": 14, "sl_atr": 1.5, "tp_r": 2.0,
    "horizon_bars": 24, "confidence": 0.5,
}


def _p(cfg: Optional[dict], k: str) -> Any:
    v = (cfg or {}).get(k)
    return DEFAULTS[k] if v is None else v


def ceil_hour(x: float) -> int:
    return int(math.ceil(x / HOUR) * HOUR)


def detect_events(rows: Sequence[Sequence[Any]], cfg: Optional[dict] = None,
                  known_at=None) -> List[Dict[str, Any]]:
    """E4 events over stored OI rows ``[[ts, oi, seen, bf], ...]`` (ascending), each
    ``{ts, known, cutoff, z}``. Same arithmetic as the replay's E4 branch (cumulative sums,
    population variance of the previous ``oi_window`` changes, a not-ok change counts as 0 in the
    window). ``known_at(row)`` defaults to ``oi_feed.known_at``."""
    if known_at is None:
        from src.runtime import oi_feed
        known_at = oi_feed.known_at
    lag, w = int(_p(cfg, "oi_lag_rows")), int(_p(cfg, "oi_window"))
    zmin, cool, span = float(_p(cfg, "oi_z")), float(_p(cfg, "oi_cooldown_s")), float(_p(cfg, "oi_max_window_span_s"))
    rows = [r for r in rows if r and float(r[1]) > 0]
    n = len(rows)
    if n <= w + lag:
        return []
    t = [float(r[0]) for r in rows]
    oi = [float(r[1]) for r in rows]
    ch = [0.0] * n
    ok = [False] * n
    for i in range(lag, n):
        ch[i] = oi[i] / oi[i - lag] - 1
        ok[i] = (t[i] - t[i - lag]) == HOUR
    cs, cs2 = [0.0] * n, [0.0] * n
    a = b = 0.0
    for i in range(n):
        a += ch[i]
        b += ch[i] * ch[i]
        cs[i], cs2[i] = a, b
    out: List[Dict[str, Any]] = []
    last = -1e18
    for i in range(w + lag, n):
        if not ok[i] or t[i] - t[i - w] > span:
            continue
        m = (cs[i - 1] - cs[i - w - 1]) / w
        v = (cs2[i - 1] - cs2[i - w - 1]) / w - m * m
        if v <= 0:
            continue
        z = (ch[i] - m) / math.sqrt(v)
        known = known_at(rows[i])
        if z >= zmin and known - last >= cool:
            out.append({"ts": int(t[i]), "known": float(known), "cutoff": ceil_hour(known), "z": round(z, 3)})
            last = known
    return out


def atr_sma(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int) -> Optional[float]:
    """ATR at the LAST bar: SMA of the true range over the last ``period`` bars (TR from bar 1 on)."""
    if len(close) < period + 1:
        return None
    trs = [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
           for i in range(len(close) - period, len(close))]
    a = sum(trs) / period
    return a if a > 0 and math.isfinite(a) else None


def _frame_cols(candles_df: Any):
    from src.runtime.closed_bars import _epoch_seconds
    ts = [_epoch_seconds(x) for x in candles_df["timestamp"].tolist()]
    return (ts, [float(x) for x in candles_df["high"].tolist()], [float(x) for x in candles_df["low"].tolist()],
            [float(x) for x in candles_df["close"].tolist()])


def order_package(cfg: dict, candles_df: Any = None, oi_rows: Optional[Sequence[Sequence[Any]]] = None) -> dict:
    """One package when an E4 event's cutoff is the close of ``candles_df``'s last bar (the frame must
    hold CLOSED 1h bars only). Raises ``ValueError`` on a non-actionable bar (no event at this
    cutoff, a flat bar, no ATR)."""
    if candles_df is None or len(candles_df) < int(_p(cfg, "atr_period")) + 2:
        raise ValueError("insufficient_1h_bars")
    if not oi_rows:
        raise ValueError("no_oi_rows")
    ts, h, lo, c = _frame_cols(candles_df)
    if ts[-1] is None:
        raise ValueError("bar_time_unreadable")
    cutoff = int(ts[-1]) + HOUR
    events = [e for e in detect_events(oi_rows, cfg) if e["cutoff"] == cutoff]
    if not events:
        raise ValueError("no_e4_event_at_cutoff")
    ev = events[-1]
    if c[-2] <= 0:
        raise ValueError("bad_prev_close")
    ret = c[-1] / c[-2] - 1
    if ret == 0:
        raise ValueError("flat_last_bar_no_side")
    atr = atr_sma(h, lo, c, int(_p(cfg, "atr_period")))
    if atr is None:
        raise ValueError("atr_undefined")
    side = 1.0 if ret > 0 else -1.0
    ref = c[-1]
    sl = ref - side * float(_p(cfg, "sl_atr")) * atr
    tp = ref + side * float(_p(cfg, "tp_r")) * float(_p(cfg, "sl_atr")) * atr   # 2 R x 1.5 ATR = the frozen 3.0 ATR
    horizon = int(_p(cfg, "horizon_bars"))
    return {
        "symbol": cfg.get("symbol"),
        "direction": "long" if side > 0 else "short",
        "entry": ref, "sl": sl, "tp": tp,
        "confidence": float(_p(cfg, "confidence")),
        "meta": {
            "strategy_name": NAME, "timeframe": "1h", "rule": "RULE-RQ20261030-E18G-02 (E4 frozen)",
            "decision_cutoff": cutoff, "oi_event_ts": ev["ts"], "oi_event_known_at": ev["known"],
            "oi_event_z": ev["z"], "last_bar_return": ret, "atr14": atr,
            "sl_atr": float(_p(cfg, "sl_atr")), "tp_r": float(_p(cfg, "tp_r")),
            "tp_atr": float(_p(cfg, "tp_r")) * float(_p(cfg, "sl_atr")),
            "horizon_bars": horizon, "time_stop_at": cutoff + horizon * HOUR,
            "tp_basis": "frozen E4 rule: 3.0 x ATR14 from the cutoff close, the level the held-out replay scored "
                        "(RQ-20261030-e18g-02, PR #21720)",
            "oi_source": "bybit /v5/market/open-interest 5min (replay: Binance Vision sumOpenInterest)",
        },
    }


def _now() -> float:
    return time.time()


def monitor(cfg: dict, candles_df: Any, open_pkg: dict) -> Optional[dict]:
    """The 24-bar time stop: close once the 24th 1h bar after the entry has closed (the replay exits at
    that bar's close). The resting SL/TP are the rest of the plan; no trail, no retarget. Never raises."""
    try:
        meta = open_pkg.get("meta") or {}
        stop_at = meta.get("time_stop_at")
        if stop_at is None:
            cut = meta.get("decision_cutoff")
            if cut is None:
                return None
            stop_at = float(cut) + int(_p(cfg, "horizon_bars")) * HOUR
        if _now() >= float(stop_at):
            return {"action": "close", "reason": "e4_time_stop_24h"}
    except Exception:  # noqa: BLE001
        return None
    return None

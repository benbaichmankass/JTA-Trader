# wiring: ensure_started() is called from src/main.py's per-iteration housekeeping block (non-blocking: it only starts the daemon thread once)
"""Pool-snapshot refresher for the ``ml_entry_eq`` leg (spec docs/research/ml-entry-eq-serve-spec-2026-11-06.md § 4; Tier 2).

WHY A SEPARATE THREAD: the leg's pool features need EVERY ETF's recent bars at the decision close, and one unpaced 173-symbol pass through the live
connector MEASURED 217 calls with 104 x 429 (#23619). So the pass never runs on the trade tick and never on the exit-evaluation path. This daemon
thread is the ONLY caller that makes the 173 requests: one ``get_ohlcv`` per symbol, paced (``PACE_S``), through the connector's process-wide
non-blocking cooldown (a ``rate_limited`` answer means "this symbol is missing from THIS pass", never a sleep inside the connector). The thread sleeps
between passes; the tick and the monitor thread are unaffected. It writes ONE snapshot per decision close with ``write_snapshot``; the signal builder
reads it with ``read_snapshot`` (a local file). If the refresher falls behind, readers see a stale or incomplete snapshot and refuse the trade
(named reasons) -- the pipeline keeps running, nothing halts.

Feed: SIP (``feed="sip"``), the feed the model was trained and confirmed on. The connector's default (IEX) is NOT used here: IEX volume is a fraction
of consolidated volume and would shift the volume features.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from src.runtime import ml_entry_eq_features as F

logger = logging.getLogger(__name__)

PACE_S = 0.6                 # seconds between symbol requests (~100/min, half the data limit; the trader's own calls ride the same key)
LIMIT_BARS = 900             # 1Hour bars incl. extended hours: ~48 sessions, > MIN_BARS (337) RTH bars with margin
SETTLE_S = 150               # wait this long after a decision close before the pass (the closed bar must be published)
RETRY_S = 120                # pause before re-trying the symbols a pass could not read
POLL_S = 240
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def snapshot_path() -> Path:
    env = os.environ.get("ML_ENTRY_EQ_SNAPSHOT")
    if env:
        return Path(env)
    from src.utils.paths import data_dir
    return Path(data_dir()) / "ml_entry_eq" / "pool_snapshot.json"


def _frame(raw: Any) -> Optional[pd.DataFrame]:
    if raw is None or len(raw) == 0:
        return None
    df = raw.rename(columns={"timestamp": "ts"})[["ts", "open", "high", "low", "close", "volume"]].copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return F.rth_filter(df)


def refresh_once(pool: list, fetch: Callable[[str], Any], now: pd.Timestamp, path: Path, *, sleep: Callable[[float], None] = time.sleep,
                 pace_s: float = PACE_S, have: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
    """One pass: fetch each pool symbol (paced), cut every frame at the latest decision close, build and write the snapshot. ``have`` carries frames
    from an earlier pass of the same close so a retry fetches only the symbols still missing. Returns {bar_close, covered, missing, wrote}."""
    have = have if have is not None else {}
    for i, s in enumerate(pool):
        if s in have:
            continue
        df = _frame(fetch(s))
        if df is not None and len(df) >= F.MIN_BARS:
            have[s] = df
        if i < len(pool) - 1:
            sleep(pace_s)
    if not have:
        return {"bar_close": None, "covered": 0, "missing": list(pool), "wrote": False}
    ref = have.get("SPY") if "SPY" in have else next(iter(have.values()))
    bc = F.latest_decision_close(ref, now)
    if bc is None:
        return {"bar_close": None, "covered": len(have), "missing": [s for s in pool if s not in have], "wrote": False}
    cut = {s: d[F.rth_close_ts(d["ts"]) <= bc] for s, d in have.items()}
    snap = F.build_snapshot(cut, pool_size=len(pool), bar_close=bc)
    snap["feed"] = "sip"
    snap["built_at"] = pd.Timestamp(now).isoformat()
    F.write_snapshot(path, snap)
    return {"bar_close": snap["bar_close"], "covered": snap["covered"], "missing": [s for s in pool if s not in snap["symbols"]], "wrote": True}


def _due(path: Path, pool_n: int, now: pd.Timestamp, ref_close: Optional[pd.Timestamp]) -> bool:
    """A pass is due when the latest decision close (+ settle) has no complete-enough snapshot yet."""
    if ref_close is None or now < ref_close + pd.Timedelta(seconds=SETTLE_S):
        return False
    snap, why = F.read_snapshot(path, now, max_age_h=1e9)
    if snap is None:
        return True
    return pd.Timestamp(snap["bar_close"]) < ref_close


def poll_state(raw: Any, ref_df: Optional[pd.DataFrame], ref_close: Optional[pd.Timestamp], now: pd.Timestamp, path: Path) -> str:
    """WHY this poll does or does not start a pass, as one short token (logged by ``_loop`` whenever it changes; before 2026-11-09 a poll with no
    reference bar was completely silent -- row ML-ENTRY-EQ-REFRESHER-SILENT)."""
    if raw is None or len(raw) == 0:
        return "spy_fetch_none_or_empty"
    if ref_df is None or len(ref_df) == 0:
        return "spy_frame_empty_after_rth_filter raw_rows=%d raw_last=%s" % (len(raw), raw["timestamp"].iloc[-1] if "timestamp" in raw else "?")
    if ref_close is None:
        return "no_decision_close rth_rows=%d rth_last_open=%s" % (len(ref_df), ref_df["ts"].iloc[-1])
    if now < ref_close + pd.Timedelta(seconds=SETTLE_S):
        return "settling ref_close=%s" % ref_close
    snap, why = F.read_snapshot(path, now, max_age_h=1e9)
    if snap is None:
        return "due snapshot_%s ref_close=%s" % (why, ref_close)
    if pd.Timestamp(snap["bar_close"]) < ref_close:
        return "due snapshot_bar_close=%s ref_close=%s" % (snap["bar_close"], ref_close)
    return "current snapshot_bar_close=%s ref_close=%s covered=%s/%s" % (snap["bar_close"], ref_close, snap.get("covered"), snap.get("pool_size"))


def _make_fetch() -> Callable[[str], Any]:
    from src.exchange.alpaca_connector import AlpacaMarketData
    md = AlpacaMarketData(feed="sip")
    return lambda s: md.get_ohlcv(s, "1h", limit=LIMIT_BARS)


def _loop() -> None:  # pragma: no cover -- thread body; refresh_once is the tested unit
    from src.runtime.ml_entry_eq_features import FEATURES_B  # noqa: F401
    from src.units.strategies import ml_entry_eq as L
    fetch = _make_fetch()
    have: Dict[str, pd.DataFrame] = {}
    have_close: Optional[pd.Timestamp] = None
    last_state: Optional[str] = None
    while True:
        try:
            now = pd.Timestamp.now(tz="UTC")
            pool = L.pool_symbols()
            ref = fetch("SPY")
            ref_df = _frame(ref)
            ref_close = F.latest_decision_close(ref_df, now) if ref_df is not None else None
            state = poll_state(ref, ref_df, ref_close, now, snapshot_path())
            if state != last_state:                     # one line per CHANGE of reason, never one per poll
                logger.info("ml_entry_eq_refresher poll: %s", state)
                last_state = state
            if ref_close != have_close:
                have, have_close = {}, ref_close        # a new decision close: start the pass from scratch
            if _due(snapshot_path(), len(pool), now, ref_close):
                res = refresh_once(pool, fetch, now, snapshot_path(), have=have)
                logger.info("ml_entry_eq_refresher bar_close=%s covered=%s/%s wrote=%s", res["bar_close"], res["covered"], len(pool), res["wrote"])
                if res["wrote"] and res["covered"] < F.MIN_COVERAGE * len(pool):
                    time.sleep(RETRY_S)                  # the missing symbols are fetched again on the next loop, same close
                    continue
        except Exception:  # noqa: BLE001 -- the refresher must never die; the snapshot just goes stale (named refusals)
            logger.exception("ml_entry_eq_refresher pass failed")
        time.sleep(POLL_S)


def ensure_started() -> bool:
    """Start the daemon thread once per process (idempotent, non-blocking). False when the leg is not enabled or it is already running."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        try:
            from src.units.strategies import load_strategy_config
            _cfg = load_strategy_config()
            if not any(bool((_cfg.get(k) or {}).get("enabled", False)) for k in ("ml_entry_eq", "ml_entry_eq_struct")):
                return False
        except Exception:  # noqa: BLE001
            return False
        _thread = threading.Thread(target=_loop, name="ml-entry-eq-refresher", daemon=True)
        _thread.start()
        return True

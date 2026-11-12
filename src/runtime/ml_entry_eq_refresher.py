# wiring: ensure_started() is called from src/main.py's per-iteration housekeeping block (non-blocking: it only starts the daemon thread once)
"""Pool-snapshot refresher for the ``ml_entry_eq`` leg (spec docs/research/ml-entry-eq-serve-spec-2026-11-06.md § 4; Tier 2).

WHY A SEPARATE THREAD: the leg's pool features need EVERY ETF's recent bars at the decision close, and one unpaced 173-symbol pass through the live
connector MEASURED 217 calls with 104 x 429 (#23619). So the pass never runs on the trade tick and never on the exit-evaluation path. This daemon
thread is the ONLY caller that makes the 173 requests: one ``get_ohlcv`` per symbol, paced (``PACE_S``), through the connector's process-wide
non-blocking cooldown (a ``rate_limited`` answer means "this symbol is missing from THIS pass", never a sleep inside the connector). The thread sleeps
between passes; the tick and the monitor thread are unaffected. It writes ONE snapshot per decision close with ``write_snapshot``; the signal builder
reads it with ``read_snapshot`` (a local file). If the refresher falls behind, readers see a stale or incomplete snapshot and refuse the trade
(named reasons) -- the pipeline keeps running, nothing halts.

LATENCY (row ML-EQ-ENTRY-TIMING, operator 2026-11-11 "Approve the fix"; Tier 2; changes no decision): packages used to land ~15.6 min after the
decision close (MEASURED n=2, 2026-11-09 20:00Z close): a free-running ``POLL_S`` poll started the pass up to 4 min late, and the pass made 173 paced
900-bar requests (~11 min). Now (a) the loop wakes at the next ``close + SETTLE_S`` instead of free-running, and polls fast just after an RTH decision
close until the pass runs; (b) :class:`BarCache` keeps every symbol's raw frame between passes (persisted beside the snapshot, so a trader restart does
not re-seed) and reads only the newest bars with ONE multi-symbol request (``AlpacaMarketData.get_bars_multi``). The frame each symbol hands
``refresh_once`` is the one ``get_ohlcv(limit=LIMIT_BARS)`` would have returned (same bars, same window, same cut), so the snapshot is byte-identical
(``tests/test_ml_entry_eq_refresher_batched.py`` replays both paths). Any symbol the cache cannot prove current (no cache, a gap, an overlap bar that
changed -- e.g. a split re-adjusting history -- or a failed batch) is read the OLD way, ``get_ohlcv`` per symbol. No symbol is dropped by this change.

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
FAST_POLL_S = 15             # poll interval just after an RTH decision close, until that close's pass has run (row ML-EQ-ENTRY-TIMING)
FAST_WINDOW_S = 20 * 60      # how long after an RTH decision close the fast poll lasts
OVERLAP_BARS = 32            # newest cached bars re-read on every incremental fetch (and compared, to catch re-adjusted history)
TRUST_TAIL = 2               # the newest cached bars may have been partial when read: they are replaced, never compared
INC_MAX_DAYS = 10            # a cache older than this is re-seeded instead of caught up
RESEED_H = 20.0              # an idle refresher re-reads the whole window once the cache is older than this (bounds deep-history drift)
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
    archive_snapshot(path, snap)
    return {"bar_close": snap["bar_close"], "covered": snap["covered"], "missing": [s for s in pool if s not in snap["symbols"]], "wrote": True}


HISTORY_KEEP = 120           # dated snapshot copies kept (~60 RTH days at 2 decision closes a day)


def archive_snapshot(path: Path, snap: Dict[str, Any], keep: int = HISTORY_KEEP) -> Optional[Path]:
    """Keep a DATED copy of each decision close's snapshot beside the live one (``history/<bar_close>.json``) so a live-vs-replay parity check can
    re-score the exact inputs the live decision saw (row ML-ENTRY-EQ-STRUCT-FULL-POOL: the 2026-11-11 weekly parity could not check the ML legs).
    A later pass of the same close overwrites its copy (the most complete one wins). Bounded: the oldest beyond ``keep`` are deleted. Never raises."""
    try:
        bc = snap.get("bar_close")
        if not bc:
            return None
        hist = Path(path).parent / "history"
        dest = hist / (pd.Timestamp(bc).strftime("%Y%m%dT%H%MZ") + ".json")
        F.write_snapshot(dest, snap)
        for old in sorted(hist.glob("*.json"))[:-keep]:
            old.unlink(missing_ok=True)
        return dest
    except Exception:  # noqa: BLE001 -- the archive is observability; it must never break the live snapshot
        logger.exception("ml_entry_eq_refresher: snapshot archive failed")
        return None


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


def _make_md() -> Any:
    from src.exchange.alpaca_connector import AlpacaMarketData
    return AlpacaMarketData(feed="sip")


def _make_fetch(md: Any = None) -> Callable[[str], Any]:
    md = md if md is not None else _make_md()
    return lambda s: md.get_ohlcv(s, "1h", limit=LIMIT_BARS)


def bar_cache_path() -> Path:
    return snapshot_path().parent / "bar_cache.pkl"


def _window_start(now: pd.Timestamp) -> pd.Timestamp:
    """The ``start`` the per-symbol ``get_ohlcv(limit=LIMIT_BARS)`` uses at ``now`` (the connector's own lookback rule)."""
    from datetime import timedelta

    from src.exchange import alpaca_connector as AC
    minutes = AC._TIMEFRAME_MINUTES["1h"]
    span = timedelta(minutes=minutes * LIMIT_BARS * AC._INTRADAY_CALENDAR_FACTOR)
    st = pd.Timestamp(now).to_pydatetime() - span - timedelta(days=AC._LOOKBACK_BUFFER_DAYS)
    return pd.Timestamp(st.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


class BarCache:
    """Raw 1h frames (``get_ohlcv`` columns, extended hours included) per symbol, kept between passes (row ML-EQ-ENTRY-TIMING).

    ``update`` brings every pool symbol current with as few venue calls as it can, and ``get`` hands ``refresh_once`` exactly the frame
    ``get_ohlcv(symbol, "1h", limit=LIMIT_BARS)`` would return now: the newest ``LIMIT_BARS`` bars at or after the connector's lookback start.
    A symbol it cannot prove current is fetched per symbol (the pre-change path), so coverage is never below the old pass. Never raises."""

    def __init__(self, md: Any, path: Optional[Path] = None, *, now_fn: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
                 sleep: Callable[[float], None] = time.sleep, pace_s: float = PACE_S):
        self.md = md
        self.path = path
        self.now_fn = now_fn
        self.sleep = sleep
        self.pace_s = pace_s
        self.frames: Dict[str, pd.DataFrame] = {}
        self.seeded_at: Optional[pd.Timestamp] = None
        self.current: Dict[str, pd.DataFrame] = {}     # this pass's frames (what ``get`` serves)
        self.stats: Dict[str, Any] = {}
        if path is not None:
            self._load()

    # -- persistence (a restart must not cost a full re-seed: the live trader restarted ~40 times on 2026-11-12 alone) --
    def _load(self) -> None:
        try:
            if self.path is not None and Path(self.path).exists():
                raw = pd.read_pickle(self.path)
                self.frames = {str(k): v for k, v in (raw.get("frames") or {}).items()}
                self.seeded_at = raw.get("seeded_at")
        except Exception:  # noqa: BLE001 -- a bad cache file is a re-seed, never a crash
            logger.exception("ml_entry_eq_refresher: bar cache unreadable (%s); re-seeding", self.path)
            self.frames, self.seeded_at = {}, None

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(self.path) + ".tmp")
            pd.to_pickle({"frames": self.frames, "seeded_at": self.seeded_at}, tmp)
            os.replace(tmp, self.path)
        except Exception:  # noqa: BLE001
            logger.exception("ml_entry_eq_refresher: bar cache write failed (kept in memory)")

    @staticmethod
    def _cut(df: pd.DataFrame, floor: pd.Timestamp) -> pd.DataFrame:
        out = df[df["timestamp"] >= floor]
        return out.iloc[-LIMIT_BARS:].reset_index(drop=True)

    def _merge(self, old: pd.DataFrame, new: pd.DataFrame) -> Optional[pd.DataFrame]:
        """``old`` caught up with ``new`` (bars from the overlap start onward), or None when ``old`` cannot be proven contiguous with the venue's
        current answer (a gap, or an overlap bar that changed)."""
        if new is None or len(new) == 0 or len(old) <= OVERLAP_BARS:
            return None
        first = new["timestamp"].iloc[0]
        if first != old["timestamp"].iloc[-OVERLAP_BARS]:
            return None                                              # the overlap's first bar is not where the cache has it: a gap or a vanished bar
        cmp_end = old["timestamp"].iloc[-TRUST_TAIL] if len(old) > TRUST_TAIL else old["timestamp"].iloc[0]
        a = old[(old["timestamp"] >= first) & (old["timestamp"] < cmp_end)].set_index("timestamp")
        b = new[new["timestamp"] < cmp_end].set_index("timestamp")
        cols = ["open", "high", "low", "close", "volume"]
        if not a.index.equals(b.index):
            return None                                              # a bar appeared or vanished inside the overlap
        if len(a) and not (a[cols].astype(float).to_numpy() == b[cols].astype(float).to_numpy()).all():
            return None                                              # history re-adjusted (split) or corrected: re-read it whole
        keep = old[old["timestamp"] < first]
        return pd.concat([keep, new], ignore_index=True).drop_duplicates("timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)

    def update(self, pool: list, now: Optional[pd.Timestamp] = None, *, reseed: bool = False) -> Dict[str, Any]:
        now = pd.Timestamp(now if now is not None else self.now_fn())
        floor = _window_start(now)
        pool = [str(s) for s in pool]
        stale_before = now - pd.Timedelta(days=INC_MAX_DAYS)
        inc, seed = [], []
        for s in pool:
            df = self.frames.get(s)
            if reseed or df is None or len(df) <= OVERLAP_BARS or df["timestamp"].iloc[-OVERLAP_BARS] < stale_before:
                seed.append(s)
            else:
                inc.append(s)
        current: Dict[str, pd.DataFrame] = {}
        fallback: list = []
        calls = 0
        if inc:
            start = min(self.frames[s]["timestamp"].iloc[-OVERLAP_BARS] for s in inc)
            got, _st = self.md.get_bars_multi(inc, "1h", _iso(start))
            calls += 1
            for s in inc:
                old = self.frames[s]
                new = got.get(s)
                if new is not None:
                    new = new[new["timestamp"] >= old["timestamp"].iloc[-OVERLAP_BARS]].reset_index(drop=True)
                m = self._merge(old, new) if new is not None else None
                if m is None:
                    fallback.append(s)
                else:
                    current[s] = self._cut(m, floor)
        if seed:
            got, _st = self.md.get_bars_multi(seed, "1h", _iso(floor))
            calls += 1
            for s in seed:
                if s in got and len(got[s]):
                    current[s] = self._cut(got[s], floor)
                else:
                    fallback.append(s)
        for i, s in enumerate(fallback):                             # the pre-change path, per symbol, paced
            raw = self.md.get_ohlcv(s, "1h", limit=LIMIT_BARS)
            calls += 1
            if raw is not None and len(raw):
                current[s] = raw.reset_index(drop=True)
            if i < len(fallback) - 1:
                self.sleep(self.pace_s)
        for s, df in current.items():
            self.frames[s] = df
        if seed and len(seed) == len(pool) and len(current) >= len(pool) * 0.5:
            self.seeded_at = now
        elif self.seeded_at is None and current:
            self.seeded_at = now
        self.current = current
        self.stats = {"incremental": len(inc), "seeded": len(seed), "per_symbol": len(fallback), "covered": len(current), "calls": calls}
        self._save()
        return self.stats

    def get(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.current.get(str(symbol))

    def needs_reseed(self, now: pd.Timestamp) -> bool:
        return self.seeded_at is None or (pd.Timestamp(now) - pd.Timestamp(self.seeded_at)) > pd.Timedelta(hours=RESEED_H)


def refresh_batched(pool: list, cache: BarCache, now: pd.Timestamp, path: Path, have: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
    """One pass through the cache: bring every symbol current (few venue calls), then run the UNCHANGED ``refresh_once`` over the cached frames
    (no pacing: nothing is fetched inside it). Same return shape, plus ``fetch`` (the cache's call counts) and ``took_s``."""
    t0 = time.monotonic()
    need = [s for s in pool if not (have and s in have)]
    stats = cache.update(need, now) if need else {}
    res = refresh_once(pool, cache.get, now, path, sleep=lambda _x: None, pace_s=0.0, have=have)
    res["fetch"] = stats
    res["took_s"] = round(time.monotonic() - t0, 1)
    return res


def _is_rth_decision_close(c: pd.Timestamp) -> bool:
    et = pd.Timestamp(c).tz_convert("America/New_York")
    mins = et.hour * 60 + et.minute
    return et.dayofweek < 5 and 9 * 60 < mins <= 16 * 60 and F.is_decision_close(c)


def next_sleep_s(now: pd.Timestamp, ref_close: Optional[pd.Timestamp]) -> float:
    """Seconds until the next poll (row ML-EQ-ENTRY-TIMING (a)): wake at the next candidate decision close + ``SETTLE_S`` instead of free-running
    ``POLL_S``; and for ``FAST_WINDOW_S`` after an RTH decision close whose bar the reference frame does not show yet, poll every ``FAST_POLL_S``."""
    now = pd.Timestamp(now)
    hour = now.floor("h")
    last = hour - pd.Timedelta(hours=int(hour.hour) % 4)                 # the latest candidate close (UTC hour % 4 == 0) at or before now
    if (_is_rth_decision_close(last) and now - last < pd.Timedelta(seconds=FAST_WINDOW_S)
            and now >= last + pd.Timedelta(seconds=SETTLE_S) and (ref_close is None or pd.Timestamp(ref_close) < last)):
        return float(FAST_POLL_S)
    wake = last + pd.Timedelta(seconds=SETTLE_S)
    if wake <= now:
        wake = last + pd.Timedelta(hours=4) + pd.Timedelta(seconds=SETTLE_S)
    return float(max(1.0, min(float(POLL_S), (wake - now).total_seconds())))


def _loop() -> None:  # pragma: no cover -- thread body; refresh_once is the tested unit
    from src.runtime.ml_entry_eq_features import FEATURES_B  # noqa: F401
    from src.units.strategies import ml_entry_eq as L
    md = _make_md()
    fetch = _make_fetch(md)
    cache = BarCache(md, bar_cache_path())
    have: Dict[str, pd.DataFrame] = {}
    have_close: Optional[pd.Timestamp] = None
    last_state: Optional[str] = None
    while True:
        ref_close = None
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
                res = refresh_batched(pool, cache, now, snapshot_path(), have=have)
                logger.info("ml_entry_eq_refresher bar_close=%s covered=%s/%s wrote=%s took_s=%s lag_s=%s fetch=%s", res["bar_close"], res["covered"],
                            len(pool), res["wrote"], res["took_s"],
                            round((pd.Timestamp.now(tz="UTC") - ref_close).total_seconds(), 1) if ref_close is not None else None, res["fetch"])
                if res["wrote"] and res["covered"] < F.MIN_COVERAGE * len(pool):
                    time.sleep(RETRY_S)                  # the missing symbols are fetched again on the next loop, same close
                    continue
            elif state.startswith("current") and cache.needs_reseed(now):
                st = cache.update(pool, now, reseed=True)  # idle: re-read the whole window off the close, so drift in old bars is bounded
                logger.info("ml_entry_eq_refresher bar cache re-seeded: %s", st)
        except Exception:  # noqa: BLE001 -- the refresher must never die; the snapshot just goes stale (named refusals)
            logger.exception("ml_entry_eq_refresher pass failed")
        try:
            time.sleep(next_sleep_s(pd.Timestamp.now(tz="UTC"), ref_close))
        except Exception:  # noqa: BLE001
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

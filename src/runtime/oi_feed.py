"""Live point-in-time open-interest feed (Bybit linear perps, 5-minute grid) -- row E4-DEMO-LEG.

The E4 leg (``src/units/strategies/e4_oi_shock_1h.py``) needs, at every 1h decision, the
last ~7 days of 5-minute open interest for its symbol, each row stamped with WHEN WE KNEW IT.
Nothing on the trader recorded open interest before this (2026-10-30: the only OI readers
were off-VM research/ML fetchers -- scripts/macro/crypto_signals_data.py,
scripts/ml/fetch_funding_oi.py), so this module is the feed and its store.

SOURCE  ``GET /v5/market/open-interest?category=linear&symbol=<S>&intervalTime=5min`` -- Bybit's
        keyless public endpoint, newest first, at most 200 rows a page, paged back with
        ``endTime``. Market data is mainnet even for the demo account (the demo venue has no
        own OI). The research rule was scored on Binance Vision ``sumOpenInterest``: a
        DIFFERENT venue's open interest (stated divergence, row E4-DEMO-LEG).

STORE   ``runtime_logs/oi_feed/<SYMBOL>.json`` -- ``{"symbol", "rows": [[ts, oi, seen, bf], ...]}``
        ascending by ``ts`` (venue row time, epoch s), ``oi`` (contracts, base coin), ``seen``
        (epoch s this process first held the row) and ``bf`` (1 = taken by the warm-up
        backfill, i.e. history fetched after the fact; 0 = seen live). Rewritten atomically,
        pruned to ``KEEP_S``. Control/data state for one leg, served read-only through
        ``/api/diag/log_file?name=oi_feed_<symbol>`` -- not a journal table.
STATUS  ``runtime_logs/oi_feed/status.json`` -- per symbol: newest row, its age, row count,
        span, last refresh, last error and ``read_state`` (``fresh`` / ``stale`` /
        ``could_not_look``). Read by ``scripts/ops/oi_feed_freshness.py`` (the freshness check)
        through ``/api/diag/log_file?name=oi_feed_status``.

POINT IN TIME  A row's ``known_at`` is the research rule's ``metrics time + 5 min`` (``ts + 300``)
        when the trader held it no later than ``DECISION_WAIT_S`` after the 1h cutoff that time
        maps to -- the E4 builder waits that long for the hour's last row before it decides, and
        decides at that wall-clock moment, so using a row it holds then is not lookahead. A live
        row first seen later than that is ``known_at = seen``: it rolls to a later cutoff (a row
        the trader saw late is used late, never early). Backfilled rows keep ``ts + 300``; they
        only ever feed the z window and the cooldown chain of past hours, never a past decision.

Never raises out of ``refresh`` (a failed fetch is a ``could_not_look`` status, retried on the
next tick -- no halting); never writes anything but its own files.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

BASES: Sequence[str] = ("https://api.bybit.com", "https://api.bytick.com")
BAR_S = 300
PAGE = 200
#: The detector needs 2016 changes of a 12-row lag, i.e. 2028 rows = 7 d 1 h of 5-min history,
#: plus the 6 h cooldown chain before it; warm up to this span and keep a margin beyond it.
WARMUP_S = 7 * 86400 + 8 * 3600
KEEP_S = 9 * 86400
MAX_BACKFILL_PAGES = 16
#: Newest row older than this -> ``stale`` (the venue publishes a row every 5 min).
STALE_AFTER_S = 20 * 60
MIN_REFRESH_S = 50.0
#: How long after a 1h boundary the E4 decision waits for the hour's last OI row (see POINT IN TIME).
DECISION_WAIT_S = 240.0

_LOCK = threading.Lock()
_LAST_REFRESH: Dict[str, float] = {}
_UNFILLABLE: Dict[str, set] = {}

Getter = Callable[[str, float], Any]


def store_dir() -> Path:
    env = os.environ.get("OI_FEED_DIR")
    if env:
        return Path(env)
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / "oi_feed"


def store_path(symbol: str) -> Path:
    return store_dir() / f"{symbol.upper()}.json"


def status_path() -> Path:
    return store_dir() / "status.json"


def known_at(row: Sequence[Any]) -> float:
    """When a stored row became usable (see the module docstring, POINT IN TIME)."""
    ts, _oi, seen, bf = row[0], row[1], row[2], row[3]
    base = float(ts) + BAR_S
    if int(bf or 0) or seen is None:
        return base
    cutoff = math.ceil(base / 3600.0) * 3600.0
    return base if float(seen) <= cutoff + DECISION_WAIT_S else float(seen)


# ----------------------------------------------------------------------------- fetch
def _http_get_json(url: str, timeout: float) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "jta-trader-oi-feed/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- fixed https bases
        return json.loads(resp.read().decode("utf-8"))


def parse_page(payload: Any) -> List[tuple]:
    """``[(ts_s, oi), ...]`` ascending from one v5 open-interest body; [] on anything unreadable."""
    try:
        if int(payload.get("retCode", -1)) != 0:
            return []
        lst = (payload.get("result") or {}).get("list") or []
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in lst:
        try:
            ts = int(r["timestamp"]) // 1000
            oi = float(r["openInterest"])
        except (KeyError, TypeError, ValueError):
            continue
        if oi > 0:
            out.append((ts, oi))
    return sorted(set(out))


def fetch_page(symbol: str, *, end_s: Optional[float] = None, limit: int = PAGE,
               getter: Optional[Getter] = None, timeout: float = 10.0) -> List[tuple]:
    """One page of 5-minute open interest ending at ``end_s`` (default: now). Raises when every
    base fails -- the caller turns that into a ``could_not_look`` status."""
    q = {"category": "linear", "symbol": symbol.upper(), "intervalTime": "5min", "limit": int(limit)}
    if end_s is not None:
        q["endTime"] = int(end_s * 1000)
    get = getter or _http_get_json
    last_err: Optional[str] = None
    for base in BASES:
        url = f"{base}/v5/market/open-interest?{urllib.parse.urlencode(q)}"
        try:
            payload = get(url, timeout)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            continue
        rows = parse_page(payload)
        if rows:
            return rows
        last_err = f"empty or refused body from {base} (retCode {getattr(payload, 'get', lambda *_: None)('retCode')})"
    raise RuntimeError(last_err or "no base answered")


# ----------------------------------------------------------------------------- store
def load(symbol: str) -> List[list]:
    """Stored rows ``[[ts, oi, seen, bf], ...]`` ascending; [] when absent or unreadable."""
    p = store_path(symbol)
    try:
        doc = json.loads(p.read_text())
        rows = [list(r) for r in doc.get("rows") or [] if isinstance(r, (list, tuple)) and len(r) == 4]
        return sorted(rows, key=lambda r: r[0])
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("oi_feed: %s unreadable (%s) -- rebuilding from the venue", p, exc)
        return []


def _atomic_write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(doc, separators=(",", ":")))
    os.replace(tmp, path)


def merge(rows: List[list], fetched: List[tuple], *, seen: float, backfill: bool) -> int:
    """Add fetched ``(ts, oi)`` rows not already stored (first sight wins). Returns rows added."""
    have = {int(r[0]) for r in rows}
    added = 0
    for ts, oi in fetched:
        if int(ts) in have:
            continue
        rows.append([int(ts), float(oi), float(seen), 1 if backfill else 0])
        have.add(int(ts))
        added += 1
    rows.sort(key=lambda r: r[0])
    return added


def grade(rows: List[list], now: float, err: Optional[str]) -> Dict[str, Any]:
    """Status of one symbol's store. ``could_not_look`` when there is nothing to read; never 0-as-fresh."""
    if not rows:
        return {"read_state": "could_not_look", "n_rows": 0, "newest_ts": None, "newest_age_s": None,
                "oldest_ts": None, "span_s": None, "warm": False, "last_error": err}
    newest, oldest = int(rows[-1][0]), int(rows[0][0])
    age = now - (newest + BAR_S)
    return {"read_state": "fresh" if age <= STALE_AFTER_S else "stale", "n_rows": len(rows),
            "newest_ts": newest, "newest_age_s": round(age, 1), "oldest_ts": oldest,
            "span_s": newest - oldest, "warm": newest - oldest >= WARMUP_S - 3600,
            "n_live": sum(1 for r in rows if not int(r[3] or 0)), "last_error": err}


def _write_status(symbol: str, st: Dict[str, Any], now: float) -> None:
    p = status_path()
    try:
        doc = json.loads(p.read_text()) if p.exists() else {}
    except Exception:  # noqa: BLE001
        doc = {}
    syms = doc.get("symbols") if isinstance(doc.get("symbols"), dict) else {}
    syms[symbol.upper()] = dict(st, refreshed_at=round(now, 1))
    _atomic_write(p, {"schema": "oi_feed_status/1", "source": "bybit /v5/market/open-interest 5min",
                      "stale_after_s": STALE_AFTER_S, "updated_at": round(now, 1), "symbols": syms})


def refresh(symbol: str, *, now: Optional[float] = None, getter: Optional[Getter] = None,
            force: bool = False) -> Dict[str, Any]:
    """Bring ``symbol``'s store up to date (warm-up backfill when short, else the newest page).

    Rate-limited to one venue round-trip per ``MIN_REFRESH_S`` per symbol per process. Returns the
    status dict (with ``rows`` attached for the caller). Never raises."""
    sym = symbol.upper()
    now = time.time() if now is None else float(now)
    with _LOCK:
        rows = load(sym)
        if not force and now - _LAST_REFRESH.get(sym, -1e18) < MIN_REFRESH_S:
            st = grade(rows, now, None)
            st["rows"] = rows
            return st
        _LAST_REFRESH[sym] = now
        err: Optional[str] = None
        try:
            fresh = fetch_page(sym, limit=50 if rows else PAGE, getter=getter)
            merge(rows, fresh, seen=now, backfill=not rows)
            # Warm-up: page back until the span covers WARMUP_S (venue history, marked bf=1).
            pages = 0
            while rows and rows[-1][0] - rows[0][0] < WARMUP_S and pages < MAX_BACKFILL_PAGES:
                older = fetch_page(sym, end_s=rows[0][0] - 1, getter=getter)
                pages += 1
                if not merge(rows, older, seen=now, backfill=True):
                    break
            # A hole (process down longer than the 50-row page): fill it from the venue, marked as
            # backfill. A hole the venue itself has is remembered and not re-asked every tick.
            gap_end = _first_gap_end(rows, since=now - WARMUP_S, skip=_UNFILLABLE.get(sym, set()))
            pages = 0
            while gap_end is not None and pages < MAX_BACKFILL_PAGES:
                older = fetch_page(sym, end_s=gap_end, getter=getter)
                pages += 1
                if not merge(rows, older, seen=now, backfill=True):
                    _UNFILLABLE.setdefault(sym, set()).add(gap_end)
                gap_end = _first_gap_end(rows, since=now - WARMUP_S, skip=_UNFILLABLE.get(sym, set()))
        except Exception as exc:  # noqa: BLE001 -- no halting: report, retry next tick
            err = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("oi_feed: %s refresh failed: %s", sym, err)
        rows = [r for r in rows if r[0] >= now - KEEP_S]
        try:
            if rows:
                _atomic_write(store_path(sym), {"symbol": sym, "schema": "oi_feed_rows/1",
                                                "columns": ["ts", "oi", "seen", "bf"], "rows": rows})
            st = grade(rows, now, err)
            _write_status(sym, st, now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("oi_feed: %s store write failed: %s", sym, exc)
            st = grade(rows, now, err or f"store_write: {exc}")
        if st["read_state"] == "stale":
            logger.error("oi_feed: %s STALE -- newest open-interest row %ss old (bound %ss); E4 cannot see a "
                         "shock it has not been sent", sym, st["newest_age_s"], STALE_AFTER_S)
        st["rows"] = rows
        return st


def _first_gap_end(rows: List[list], *, since: float, skip: Optional[set] = None) -> Optional[float]:
    """End (epoch s) of the NEWEST hole of more than one bar inside ``[since, newest]`` not in
    ``skip``, for a backfill page to end on; None when the span is contiguous."""
    for k in range(len(rows) - 1, 0, -1):
        if rows[k][0] < since:
            break
        if rows[k][0] - rows[k - 1][0] > BAR_S and float(rows[k][0] - 1) not in (skip or set()):
            return float(rows[k][0] - 1)
    return None

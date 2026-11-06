"""Read-only Alpaca market-data client for the token-free research runner (row ML-ENTRY-ALL-ACCOUNTS, unit RQ-20261104-a41f-01).

Operator 2026-11-05 ~10:05Z, verbatim: "there's no reason not to pull data for testing from the broker connections as long as it
doesn't interfere with trading". The three conditions that make that true are enforced HERE, in code, not by convention:

(a) READ-ONLY, ALLOWLISTED. Only ``GET`` on exactly ``ALLOWED`` (host, path) pairs is ever sent: historical stock bars and the
    asset list. Any other method, host, path or scheme raises ``ReadOnlyViolation`` BEFORE a socket is opened. There is no order,
    account, position or stream endpoint in the list, and no way to pass a URL in from a unit's command line.
(b) PAPER/DATA KEY FIRST. ``from_env`` reads ``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY`` (the paper pair; market data is the
    same data) and falls back to the ``_LIVE`` pair only when the paper pair is absent. ``key_kind`` records which was used. The
    research-script-run workflow wires the paper pair only.
(c) BACK OFF ON 429. HTTP 429 and 5xx wait ``Retry-After`` (else 2**attempt, capped 60s) and retry; calls are also paced at
    ``min_interval`` seconds, far under the 200/min data limit, so a research run can never throttle the live trader (which uses
    its own key and its own rate bucket in any case).

A key value is never printed, logged or put in an exception message.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

DATA_HOST = "data.alpaca.markets"
TRADING_READ_HOST = "paper-api.alpaca.markets"
BARS_PATH = "/v2/stocks/bars"
ASSETS_PATH = "/v2/assets"
# The WHOLE surface. Adding a line here is a code change that a test (test_alpaca_readonly) pins.
ALLOWED = frozenset({(DATA_HOST, BARS_PATH), (TRADING_READ_HOST, ASSETS_PATH)})


class ReadOnlyViolation(RuntimeError):
    """A request outside the read-only allowlist was attempted."""


def check_request(method: str, url: str) -> None:
    sp = urlsplit(url)
    if str(method).upper() != "GET":
        raise ReadOnlyViolation(f"only GET is allowed, got {method!r}")
    if sp.scheme != "https":
        raise ReadOnlyViolation(f"only https is allowed, got {sp.scheme!r}")
    if (sp.hostname, sp.path) not in ALLOWED:
        raise ReadOnlyViolation(f"endpoint not on the read-only allowlist: {sp.hostname}{sp.path}")


class AlpacaReadOnly:
    def __init__(self, key_id: str, secret: str, key_kind: str = "paper", session: Any = None,
                 sleep: Callable[[float], None] = time.sleep, min_interval: float = 0.4, max_retries: int = 8):
        if not (key_id and secret):
            raise ValueError("Alpaca data keys missing")
        if session is None:
            import requests
            session = requests.Session()
        self._s, self._sleep = session, sleep
        self._h = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret,
                   "User-Agent": "jta-trader-research (read-only market data)"}
        self.key_kind, self.min_interval, self.max_retries = key_kind, float(min_interval), int(max_retries)
        self._next, self._lock = 0.0, threading.Lock()   # one shared pacing clock: N threads never exceed 1/min_interval calls/s
        self.calls, self.n_429, self.n_bars = 0, 0, 0

    @classmethod
    def from_env(cls, **kw) -> "AlpacaReadOnly":
        k, s = os.environ.get("ALPACA_API_KEY_ID"), os.environ.get("ALPACA_API_SECRET_KEY")
        if k and s:
            return cls(k, s, "paper", **kw)
        k, s = os.environ.get("ALPACA_API_KEY_ID_LIVE"), os.environ.get("ALPACA_API_SECRET_KEY_LIVE")
        if k and s:
            return cls(k, s, "live", **kw)
        raise RuntimeError("no Alpaca data keys in env (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY)")

    def get(self, host: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"https://{host}{path}"
        check_request("GET", url)
        for attempt in range(self.max_retries):
            with self._lock:
                now = time.monotonic()
                start = max(now, self._next)
                self._next = start + self.min_interval
            if start - now > 0:
                self._sleep(start - now)
            r = self._s.get(url, headers=self._h, params=params, timeout=120)
            with self._lock:
                self.calls += 1
            if r.status_code == 429 or r.status_code >= 500:
                with self._lock:
                    self.n_429 += r.status_code == 429
                ra = (getattr(r, "headers", None) or {}).get("Retry-After")
                try:
                    delay = float(ra) if ra is not None else float(min(60, 2 ** attempt))
                except ValueError:
                    delay = float(min(60, 2 ** attempt))
                self._sleep(max(delay, 0.0))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"alpaca GET {path} -> HTTP {r.status_code}: {str(r.text)[:160]}")
            return r.json()
        raise RuntimeError(f"alpaca GET {path}: still throttled/unavailable after {self.max_retries} attempts")

    def assets(self) -> List[Dict[str, Any]]:
        return list(self.get(TRADING_READ_HOST, ASSETS_PATH, {"status": "active", "asset_class": "us_equity"}))

    def bars(self, symbols: List[str], timeframe: str, start: str, end: str, feed: str = "sip",
             adjustment: str = "split") -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        tok = None
        while True:
            p = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start, "end": end, "limit": 10000,
                 "adjustment": adjustment, "feed": feed}
            if tok:
                p["page_token"] = tok
            j = self.get(DATA_HOST, BARS_PATH, p)
            for s, bl in (j.get("bars") or {}).items():
                out.setdefault(s, []).extend(bl)
                with self._lock:
                    self.n_bars += len(bl)
            tok = j.get("next_page_token")
            if not tok:
                return out

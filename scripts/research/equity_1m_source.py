#!/usr/bin/env python3
"""US-equity 1m + daily bars for the forming-bar replay -- row EQ-FORMING-BAR-REPLAY (2026-11-13).

WHY. Live ``tqqq_trend_long_1d`` decides on the FORMING daily bar (the runtime default, no ``decision_bar`` key), but
``scripts/backtest_trend.py --decision-bar forming`` could read only Binance 1m archives, so every Stage-0 number for an
equity leg measured CLOSED-bar decisions. This module supplies the missing input: the symbol's 1m bars AND its daily bars
from ONE source, written as the CSVs the harness reads (``--data`` and ``--minutes-1m-csv``), with the history window
DECLARED from what the source actually returned.

SOURCE. Alpaca market data through ``scripts/research/alpaca_readonly.py`` (GET-only allowlist; the paper key pair the
``research-script-run`` workflow passes; keys never in the repo, never printed). ``--feed`` defaults to ``iex``, the feed
the LIVE connector reads (``src/exchange/alpaca_connector.py``: ``ALPACA_DATA_FEED`` default ``iex``), so the replayed
decision sees the bars live sees. ``sip`` is available for a sensitivity read. Yahoo serves ~30 days of 1m, which cannot
cover a backtest, so it is not offered.

ALIGNMENT, MEASURED NOT ASSUMED. The forming bar's running high/low must be built from the minutes the venue's daily
bar aggregates. Whether Alpaca's 1Day bar covers the cash session only or the extended session is checked on the data:
both minute sets are aggregated per day and compared with the 1Day high/low, and the set with the higher exact-match
share is used (rule fixed here, before any replay, on price alignment only -- it never sees a trade). The shares are
written to ``source.json`` either way.

OUTPUT (``--out-dir``):
  ``<SYM>_1d.csv``  timestamp (session DATE at 00:00Z -- the Yahoo convention the harness's 1d resample leaves unchanged),
                    open, high, low, close, volume -- Alpaca 1Day bars, split-adjusted.
  ``<SYM>_1m.csv``  timestamp (UTC), open, high, low, close, volume -- the chosen minute set, split-adjusted.
  ``source.json``   feed, key kind, requested and RETURNED window, row counts, per-year 1m coverage, alignment shares.

Tier 1: research data fetch, read-only. ``--self-test`` runs offline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

US_TZ = "America/New_York"
RTH_OPEN, RTH_CLOSE = 570, 960        # minute of the ET day: 09:30, 16:00
#: Two prices "match" within this relative tolerance (float round-trip through JSON, not a price-alignment allowance).
MATCH_TOL = 1e-6


def bars_frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """Alpaca bar dicts {t,o,h,l,c,v,...} -> timestamp/open/high/low/close/volume, UTC, sorted, de-duplicated."""
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low",
                                            "c": "close", "v": "volume"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def session_date_daily(d1: pd.DataFrame) -> pd.DataFrame:
    """Alpaca 1Day bars (stamped at ET midnight, i.e. 04:00/05:00Z) restamped to the session DATE at 00:00Z."""
    out = d1.copy()
    et_day = out["timestamp"].dt.tz_convert(US_TZ).dt.tz_localize(None).dt.normalize()
    out["timestamp"] = et_day.dt.tz_localize("UTC")
    return out.drop_duplicates("timestamp", keep="last").reset_index(drop=True)


def _minute_of_et_day(ts: pd.Series) -> pd.Series:
    et = ts.dt.tz_convert(US_TZ)
    return et.dt.hour * 60 + et.dt.minute


def _et_date(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(US_TZ).dt.tz_localize(None).dt.normalize().dt.tz_localize("UTC")


def alignment(daily: pd.DataFrame, m1: pd.DataFrame) -> Dict[str, Any]:
    """Share of days whose 1Day high AND low equal the aggregate of each candidate minute set."""
    mm = _minute_of_et_day(m1["timestamp"])
    sets = {"rth": m1[(mm >= RTH_OPEN) & (mm < RTH_CLOSE)], "all": m1}
    d = daily.set_index("timestamp")
    out: Dict[str, Any] = {}
    for name, sub in sets.items():
        if sub.empty:
            out[name] = {"days_compared": 0, "match_share": None}
            continue
        g = sub.assign(day=_et_date(sub["timestamp"])).groupby("day").agg(high=("high", "max"), low=("low", "min"))
        j = g.join(d[["high", "low"]], rsuffix="_d", how="inner")
        if j.empty:
            out[name] = {"days_compared": 0, "match_share": None}
            continue
        tol = MATCH_TOL * j["high_d"].abs()
        ok = ((j["high"] - j["high_d"]).abs() <= tol) & ((j["low"] - j["low_d"]).abs() <= tol)
        out[name] = {"days_compared": int(len(j)), "days_matched": int(ok.sum()),
                     "match_share": round(float(ok.mean()), 4)}
    shares = {k: (v.get("match_share") or -1.0) for k, v in out.items()}
    # Ties go to "rth": the narrower set never lets an out-of-session print move a decision.
    out["chosen"] = "rth" if shares["rth"] >= shares["all"] else "all"
    return out


def select_minutes(m1: pd.DataFrame, chosen: str) -> pd.DataFrame:
    if chosen == "all":
        return m1.reset_index(drop=True)
    mm = _minute_of_et_day(m1["timestamp"])
    return m1[(mm >= RTH_OPEN) & (mm < RTH_CLOSE)].reset_index(drop=True)


def coverage_by_year(daily: pd.DataFrame, m1: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """Per calendar year: daily bars, and daily bars with at least one 1m bar (a day without minutes cannot be replayed)."""
    days_with_1m = set(_et_date(m1["timestamp"]).unique()) if len(m1) else set()
    out: Dict[str, Dict[str, int]] = {}
    for ts in daily["timestamp"]:
        y = str(ts.year)
        row = out.setdefault(y, {"daily_bars": 0, "days_with_1m": 0})
        row["daily_bars"] += 1
        row["days_with_1m"] += int(ts in days_with_1m)
    return out


def build(client: Any, symbol: str, start: str, end: str, feed: str, out_dir: Path) -> Dict[str, Any]:
    d1 = bars_frame(client.bars([symbol], "1Day", start, end, feed=feed).get(symbol, []))
    m1_all = bars_frame(client.bars([symbol], "1Min", start, end, feed=feed).get(symbol, []))
    daily = session_date_daily(d1) if len(d1) else d1
    if daily.empty or m1_all.empty:
        raise RuntimeError(f"{symbol} {feed}: the source returned daily={len(daily)} 1m={len(m1_all)} rows")
    align = alignment(daily, m1_all)
    m1 = select_minutes(m1_all, align["chosen"])
    # The replay window: from the first session that has 1m bars (the daily history before it only feeds the
    # 199-bar lookback; the harness enters nowhere without minutes) to the last daily bar.
    out_dir.mkdir(parents=True, exist_ok=True)
    p1d, p1m = out_dir / f"{symbol}_1d.csv", out_dir / f"{symbol}_1m.csv"
    daily.to_csv(p1d, index=False)
    m1.to_csv(p1m, index=False)
    meta = {
        "symbol": symbol, "feed": feed, "adjustment": "split", "source": "alpaca market data (read-only client)",
        "key_kind": getattr(client, "key_kind", None),
        "requested": {"start": start, "end": end},
        "returned": {"daily_first": str(daily["timestamp"].min().date()), "daily_last": str(daily["timestamp"].max().date()),
                     "m1_first": str(m1["timestamp"].min()), "m1_last": str(m1["timestamp"].max())},
        "rows": {"daily": int(len(daily)), "m1_fetched": int(len(m1_all)), "m1_kept": int(len(m1))},
        "alignment": align,
        "coverage_by_year": coverage_by_year(daily, m1),
        "files": {"daily": p1d.name, "m1": p1m.name},
        "client": {"calls": getattr(client, "calls", None), "n_429": getattr(client, "n_429", None)},
    }
    (out_dir / "source.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


# ── self-test (offline) ─────────────────────────────────────────────────────

class _FakeClient:
    key_kind, calls, n_429 = "fake", 0, 0

    def __init__(self, daily: List[dict], minutes: List[dict]):
        self._d, self._m = daily, minutes

    def bars(self, symbols, timeframe, start, end, feed="iex", adjustment="split"):
        self.calls += 1
        self.requests = getattr(self, "requests", []) + [(timeframe, start, end, feed, adjustment)]   # the self-test asserts these
        return {symbols[0]: self._d if timeframe == "1Day" else self._m}


def _self_test() -> int:
    import tempfile

    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)

    # Two sessions across the DST change (2024-03-08 EST, 2024-03-11 EDT). Pre-market prints set a higher high that
    # the RTH-only daily bar does NOT include -> alignment must pick "rth".
    minutes, daily = [], []
    for day, utc_open in (("2024-03-08", "14:30"), ("2024-03-11", "13:30")):
        t0 = pd.Timestamp(f"{day} {utc_open}", tz="UTC")
        pre = t0 - pd.Timedelta(minutes=60)
        minutes.append({"t": pre.isoformat(), "o": 10, "h": 99.0, "l": 9.5, "c": 10, "v": 1})
        hs = []
        for k in range(390):
            h = 10 + (k % 7) * 0.1
            hs.append(h)
            minutes.append({"t": (t0 + pd.Timedelta(minutes=k)).isoformat(), "o": 10, "h": h, "l": 9.9, "c": 10.05, "v": 5})
        et_mid = pd.Timestamp(day, tz=US_TZ).tz_convert("UTC")
        daily.append({"t": et_mid.isoformat(), "o": 10, "h": max(hs), "l": 9.9, "c": 10.05, "v": 1950})
    with tempfile.TemporaryDirectory() as td:
        fc = _FakeClient(daily, minutes)
        meta = build(fc, "TEST", "2024-03-01", "2024-03-12", "iex", Path(td))
        check("the source is asked for 1Day and 1Min over the requested window, feed and split adjustment",
              fc.requests == [("1Day", "2024-03-01", "2024-03-12", "iex", "split"),
                              ("1Min", "2024-03-01", "2024-03-12", "iex", "split")])
        check("alignment picks rth when the daily bar excludes extended-hours prints", meta["alignment"]["chosen"] == "rth")
        check("rth match share is 1.0", meta["alignment"]["rth"]["match_share"] == 1.0)
        check("all-minutes match share is 0.0 (the pre-market 99.0 high)", meta["alignment"]["all"]["match_share"] == 0.0)
        d = pd.read_csv(Path(td) / "TEST_1d.csv")
        check("daily restamped to session date 00:00Z on both sides of DST",
              list(d["timestamp"]) == ["2024-03-08 00:00:00+00:00", "2024-03-11 00:00:00+00:00"])
        m = pd.read_csv(Path(td) / "TEST_1m.csv")
        check("kept minutes are the 2 x 390 cash-session bars", len(m) == 780 and meta["rows"]["m1_fetched"] == 782)
        check("coverage counts both days", meta["coverage_by_year"]["2024"] == {"daily_bars": 2, "days_with_1m": 2})
        # The harness-side alignment agrees: forming_bar_entries maps the first RTH minute to column 570 of its date.
        import forming_bar_entries as fbe
        bars = pd.read_csv(Path(td) / "TEST_1d.csv")
        bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
        mats = fbe.minute_matrices(fbe.load_1m_csv(str(Path(td) / "TEST_1m.csv")), bars, 1440, session="us_equity")
        check("minute 570 of each session holds its first bar (EST and EDT)",
              all(not pd.isna(mats["last_c"][i, 570]) and pd.isna(mats["run_h"][i, 569]) for i in range(2)))
        check("running high at the close equals the daily high",
              all(abs(mats["run_h"][i, 959] - d["high"][i]) < 1e-9 for i in range(2)))
    try:
        build(_FakeClient([], []), "EMPTY", "2024-01-01", "2024-01-02", "iex", Path(tempfile.mkdtemp()))
        check("empty source raises", False)
    except RuntimeError:
        check("empty source raises (never writes an empty dataset)", True)
    print("self-test passed")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbol")
    ap.add_argument("--start", default="2015-12-01", help="ISO date; Alpaca 1m begins 2016 (the earliest it returns is declared)")
    ap.add_argument("--end", help="ISO date (exclusive upper bound passed to the API)")
    ap.add_argument("--feed", choices=("iex", "sip"), default="iex")
    ap.add_argument("--out-dir")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.symbol and a.end and a.out_dir):
        ap.error("--symbol, --end and --out-dir are required")
    from alpaca_readonly import AlpacaReadOnly
    meta = build(AlpacaReadOnly.from_env(), a.symbol, a.start, a.end, a.feed, Path(a.out_dir))
    print(json.dumps({k: meta[k] for k in ("symbol", "feed", "returned", "rows", "alignment")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

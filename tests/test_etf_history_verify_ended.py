import unittest.mock as mk
from datetime import datetime, timezone, timedelta

import pandas as pd

from scripts.ops import etf_history_verify as v
from scripts.ops.fetch_etf_history import ended_symbols

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


def _m(days_ago):
    return {"status": "ok", "rows": 10, "first": "2020-01-01T00:00:00+00:00",
            "last": (NOW - timedelta(days=days_ago)).isoformat(), "feed": "sip"}


def _run(ca):
    u = {"us_equity_bars": {"core": ["AAA", "BBB"], "timeframes": ["1m"]}}
    manifest = {"series": {"AAA/1m": _m(30), "BBB/1m": _m(30)}, "corporate_actions": {"ended": ca}}
    with mk.patch.object(v.du, "equity_symbols", return_value=["AAA", "BBB"]), \
            mk.patch.object(v.du, "delisted_symbols", return_value=[]):
        return {r["symbol"]: r for r in v.classify(u, manifest, ["1m"], NOW, 5.0, False)}


def test_ended_by_corporate_action_not_red_live_stale_still_red():
    rows = _run({"AAA": {"kind": "name_change", "date": "2026-09-01"}})
    assert rows["AAA"]["verdict"] == "ended" and not rows["AAA"]["red"]
    assert rows["BBB"]["verdict"] == "STALE" and rows["BBB"]["red"]


def test_ended_symbols_extracts_ending_kinds_only():
    ca = pd.DataFrame([{"kind": "merger", "symbol": "WBD", "ex_date": "2026-10-01"},
                       {"kind": "cash_dividend", "symbol": "SPY", "ex_date": "2026-10-01"}])
    assert ended_symbols(ca) == {"WBD": {"kind": "merger", "date": "2026-10-01"}}

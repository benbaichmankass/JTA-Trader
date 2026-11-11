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
    ca = pd.DataFrame([{"kind": "stock_merger", "symbol": "WBD", "ex_date": "2026-10-01"},
                       {"kind": "cash_dividend", "symbol": "SPY", "ex_date": "2026-10-01"}])
    assert ended_symbols(ca) == {"WBD": {"kind": "stock_merger", "date": "2026-10-01"}}


def test_fetch_corporate_actions_realistic_alpaca_payload():
    from scripts.ops import fetch_etf_history as f
    seen = {}

    def get(path, params):
        seen.update(params)
        return {"corporate_actions": {
            "cash_dividends": [{"symbol": "SPY", "rate": 1.7, "ex_date": "2026-09-19", "record_date": "2026-09-20", "payable_date": "2026-09-30"}],
            "name_changes": [{"old_symbol": "SPLG", "new_symbol": "SPYM", "process_date": "2026-10-01"}],
            "cash_mergers": [{"acquiree_symbol": "KVUE", "acquirer_symbol": "KMB", "rate": 3.5, "process_date": "2026-10-02", "effective_date": "2026-10-03"}],
            "stock_mergers": [{"acquiree_symbol": "WBD", "acquirer_symbol": "PSKY", "process_date": "2026-10-04"}],
            "worthless_removals": [{"symbol": "ZZZ", "process_date": "2026-10-05"}]},
            "next_page_token": None}

    ca = f.fetch_corporate_actions(get, ["SPLG"], NOW - timedelta(days=30), NOW)
    assert "merger" not in seen["types"].split(",")  # invalid Alpaca type rejects the whole request
    assert len(ca) == 5
    ended = f.ended_symbols(ca)
    assert set(ended) == {"SPLG", "KVUE", "WBD", "ZZZ"}
    assert ended["SPLG"]["kind"] == "name_change" and ended["KVUE"]["date"] == "2026-10-03"


def test_verify_flags_corporate_actions_unavailable():
    u = {"us_equity_bars": {"core": ["AAA"], "timeframes": ["1m"]}}
    with mk.patch.object(v.du, "equity_symbols", return_value=["AAA"]), \
            mk.patch.object(v.du, "delisted_symbols", return_value=[]):
        for ca in ({"rows": 0, "ended": {}}, {"error": "x"}, {"rows": 5, "ended": {}, "failed_batches": 2}):
            manifest = {"series": {"AAA/1m": _m(30)}, "corporate_actions": ca}
            r = v.classify(u, manifest, ["1m"], NOW, 5.0, False)[0]
            assert r["verdict"] == "STALE" and r["red"] and r["ca_unavailable"]
        ok = {"series": {"AAA/1m": _m(30)}, "corporate_actions": {"rows": 5, "ended": {}}}
        assert not v.classify(u, ok, ["1m"], NOW, 5.0, False)[0]["ca_unavailable"]

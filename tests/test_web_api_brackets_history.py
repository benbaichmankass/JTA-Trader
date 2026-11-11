"""GET /api/bot/brackets/history (UI-CHART-BRACKET-HISTORY backend half): levels + markers, honest about gaps."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.runtime import sl_mover
from src.web.api import brackets_history as bh
from src.web.api import main as api_main
from src.web.api.routers import brackets_history as router
from tests.fixtures.real_schema_db import insert_order_package, make_canonical_db


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "trade_journal.db"
    make_canonical_db(path)
    monkeypatch.setattr(router, "_DB_PATH", path)
    return path


def test_cap_constant_matches_the_writer():
    assert bh.SL_MOVES_CAP == sl_mover.MAX_SL_MOVES


def test_package_with_one_move_old_level_subtle_new_level_main_one_marker(db, client):
    meta = sl_mover.stamp_sl_move({}, 0.18747, 0.186646, "structure_exit", "trail", )
    meta["sl_moves"][0]["ts"] = "2026-11-06T08:00:00+00:00"
    insert_order_package(db, order_package_id="pkg-1", symbol="ADAUSDT", direction="long", entry=0.19, sl=0.186646,
                         tp=0.2, created_at="2026-11-06T06:10:00Z", status="open", meta=json.dumps(meta))
    d = client.get("/api/bot/brackets/history", params={"order_package_id": "pkg-1", "interval": "1h"}).json()
    sl = [l for l in d["levels"] if l["kind"] == "sl"]
    assert [(l["price"], l["to_ts"] is None) for l in sl] == [(0.18747, False), (0.186646, True)]
    assert sl[0]["to_ts"] == sl[1]["from_ts"] == "2026-11-06T08:00:00+00:00"
    assert len(d["updates"]) == 1 and d["updates"][0]["bar_ts"] == "2026-11-06T08:00:00+00:00"
    assert (d["updates"][0]["from"], d["updates"][0]["to"]) == (0.18747, 0.186646)
    assert d["read_state"] == "measured" and d["tp_history"] == "unrecorded"
    tp = [l for l in d["levels"] if l["kind"] == "tp"]
    assert len(tp) == 1 and tp[0]["price"] == 0.2 and tp[0]["to_ts"] is None


def test_marker_bar_is_floored_to_the_interval(db, client):
    meta = sl_mover.stamp_sl_move({}, 1.0, 2.0, "strategy_monitor")
    meta["sl_moves"][0]["ts"] = "2026-11-07T09:47:30+00:00"
    insert_order_package(db, order_package_id="pkg-2", created_at="2026-11-07T08:00:00Z", meta=json.dumps(meta))
    for iv, want in (("15m", "2026-11-07T09:45:00+00:00"), ("1h", "2026-11-07T09:00:00+00:00"),
                     ("4h", "2026-11-07T08:00:00+00:00")):
        d = client.get("/api/bot/brackets/history", params={"order_package_id": "pkg-2", "interval": iv}).json()
        assert d["updates"][0]["bar_ts"] == want


def test_old_package_without_record_is_partial_main_lines_only_no_markers(db, client):
    insert_order_package(db, order_package_id="pkg-old", created_at="2026-10-01T00:00:00Z", meta=None)
    d = client.get("/api/bot/brackets/history", params={"order_package_id": "pkg-old"}).json()
    assert d["updates"] == [] and d["read_state"] == "partial"
    assert "predates_sl_move_stamp_2026-11-06" in d["partial_reasons"]
    assert sorted(l["kind"] for l in d["levels"]) == ["sl", "tp"]


def test_post_stamp_package_with_no_moves_is_measured_not_partial(db, client):
    insert_order_package(db, order_package_id="pkg-new", created_at="2026-11-08T00:00:00Z", meta="{}")
    d = client.get("/api/bot/brackets/history", params={"order_package_id": "pkg-new"}).json()
    assert d["read_state"] == "measured" and d["updates"] == []


def test_capped_trail_is_partial_and_first_level_is_estimated(db, client):
    meta: dict = {}
    for i in range(25):
        meta = sl_mover.stamp_sl_move(meta, 100 + i, 101 + i, "strategy_monitor")
        meta["sl_moves"][-1]["ts"] = f"2026-11-08T{i % 24:02d}:00:00+00:00"
    insert_order_package(db, order_package_id="pkg-cap", created_at="2026-11-07T00:00:00Z", meta=json.dumps(meta))
    d = client.get("/api/bot/brackets/history", params={"order_package_id": "pkg-cap"}).json()
    assert d["read_state"] == "partial" and any(r.startswith("sl_moves_capped") for r in d["partial_reasons"])
    assert [l for l in d["levels"] if l["kind"] == "sl"][0]["provenance"] == "ESTIMATED"
    assert len(d["updates"]) == 20


def test_selector_and_interval_errors(db, client):
    assert client.get("/api/bot/brackets/history").status_code == 400
    assert client.get("/api/bot/brackets/history", params={"order_package_id": "x", "prop_fill_id": 1}).status_code == 400
    assert client.get("/api/bot/brackets/history", params={"order_package_id": "x", "interval": "zz"}).status_code == 400
    assert client.get("/api/bot/brackets/history", params={"order_package_id": "nope"}).status_code == 404


def test_prop_amendments_give_sl_and_tp_steps_and_null_amendments_say_so():
    am = [{"at": "2026-11-04T18:03:54+00:00", "sl_before": 2356.86, "sl": 2373.4, "tp_before": 2666.4, "tp": 2666.4,
           "source": {"reason": "trail", "reported": {"source": "prop_trail"}}},
          {"at": "2026-11-04T18:08:40+00:00", "sl_before": 2373.4, "sl": 2386.4, "tp_before": 2666.4, "tp": 2600.0,
           "source": {"reason": "trail+tp", "reported": {"source": "prop_trail"}}}]
    op = {"id": 5, "account_id": "tradeify_1", "ticket_id": "t", "symbol": "ETHUSDT", "direction": "long",
          "opened_at": "2026-11-04T10:00:00+00:00", "sl": 2386.4, "tp": 2600.0, "amendments": json.dumps(am)}
    d = bh.build_prop_history(op, "1h")
    sl = [l for l in d["levels"] if l["kind"] == "sl"]
    tp = [l for l in d["levels"] if l["kind"] == "tp"]
    assert [l["price"] for l in sl] == [2356.86, 2373.4, 2386.4] and [l["price"] for l in tp] == [2666.4, 2600.0]
    assert [(u["kind"], u["to"]) for u in d["updates"]] == [("sl", 2373.4), ("sl", 2386.4), ("tp", 2600.0)]
    assert d["tp_history"] == "recorded" and d["read_state"] == "measured"
    bare = bh.build_prop_history({"id": 6, "opened_at": "2026-11-04T10:00:00+00:00", "sl": None, "tp": None,
                                  "amendments": None})
    assert bare["read_state"] == "no_record" and bare["updates"] == [] and bare["tp_history"] == "unrecorded"
    assert all(l["price"] is None for l in bare["levels"])


def test_prop_route_resolves_a_closing_row_to_its_opener(monkeypatch, client):
    from src.prop import prop_journal
    rows = {7: {"id": 7, "status": "closed", "account_id": "a", "ticket_id": "t", "external_order_id": None}}
    opener = {"id": 3, "status": "open", "account_id": "a", "ticket_id": "t", "symbol": "ETHUSDT", "direction": "long",
              "opened_at": "2026-11-04T10:00:00+00:00", "sl": 10.0, "tp": 20.0, "amendments": None}
    monkeypatch.setattr(prop_journal, "get_fill", lambda i: rows.get(i))
    monkeypatch.setattr(prop_journal, "get_opening_fill", lambda a, t, e: opener)
    d = client.get("/api/bot/brackets/history", params={"prop_fill_id": 7}).json()
    assert d["prop_fill_id"] == 3 and d["account_class"] == "prop"
    assert client.get("/api/bot/brackets/history", params={"prop_fill_id": 99}).status_code == 404

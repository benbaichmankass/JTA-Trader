"""LTR-11-PACKET: the decision-packet generator, against the hand-built golden packets.

``build_packet`` is a pure function of a ``Snapshot``; each fixture below reproduces, from raw-read
shapes, the state a golden packet in ``comms/live_review/packets/`` was assembled from, and the test
asserts the generator yields the golden's fields from it.
"""
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lrp", REPO / "scripts/ops/live_review_packet.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["lrp"] = L  # dataclasses resolves annotations through sys.modules
_spec.loader.exec_module(L)

GOLD = {json.loads(f.read_text())["order_package_id"]: json.loads(f.read_text())
        for f in (REPO / "comms/live_review/packets").glob("*.json")}
NOW = datetime(2026, 10, 25, 16, 16, 30, tzinfo=timezone.utc)
# The goldens land with PR #20121 (the skill + comms/live_review/); until then the golden-dependent cases skip.
needs_gold = pytest.mark.skipif(not GOLD, reason="comms/live_review/packets goldens not on this branch yet")
ADA, MGC, ETH, GDX = "pkg-465a5d7d27644027", "pkg-011a7bf85ee54a6f", "pkg-2c3f338d9477499b", "pkg-23929c3f526440c3"


def _tel(g, acct, final=False):
    f, st = g["features_at_review"], g["state"]
    return {"order_package_id": g["order_package_id"], "strategy": g["leg"], "account_id": acct,
            "lifecycle": "closed" if final else "open", "open_r": f["open_r"], "peak_r": f["peak_r"],
            "giveback_r": f["giveback_r"], "bars_held": st["bars_held"], "bars_since_peak": f.get("bars_since_peak"),
            "r_to_stop": f["r_to_stop"], "r_to_target": f["r_to_target"], "peak_provenance": "estimated"}


def _pkg(g, symbol, direction, status="open", meta=None):
    st = g["state"]
    return {"order_package_id": g["order_package_id"], "strategy_name": g["leg"], "symbol": symbol,
            "direction": direction, "entry": "1.0", "sl": str(st["sl"]), "tp": str(st["tp"]), "status": status,
            "close_reason": None, "meta": json.dumps(meta or {})}


def _snap(**reads):
    s = L.Snapshot()
    s.reads.update(reads)
    s.read_at = {k: "2026-10-25T16:16:30Z" for k in reads}
    return s


def _bybit(acct_orders):
    return {"accounts": [{"account_id": a, "read_state": "orders_read", "result": {"positions": [
        {"symbol": "ADAUSDT", "side": "Sell", "size": 1.0}], "orders": [
        {"symbol": "ADAUSDT", "stop_order_type": "PartialStopLoss", "trigger_price": 0.2109},
        {"symbol": "ADAUSDT", "stop_order_type": "PartialTakeProfit", "trigger_price": 0.1874}]}} for a in acct_orders]}


def _build(pkg, snap, **kw):
    return L.build_packet(pkg, snap, NOW, price=False, **kw)


@needs_gold
def test_ada_reproduces_golden_fields():
    g = GOLD[ADA]
    s = _snap(telemetry={"rows": [_tel(g, "bybit_2")]}, bybit_orders=_bybit(["bybit_2", "bybit_portfolio", "bybit_1"]))
    s.packages[ADA] = _pkg(g, "ADAUSDT", "short")
    s.trades = [{"order_package_id": ADA, "account_id": a, "status": "open", "account_class": c}
                for a, c in (("bybit_portfolio", "paper"), ("bybit_1", "paper"))]
    p = _build(ADA, s)
    for k in ("open_r", "peak_r", "giveback_r", "bars_held", "sl", "tp", "peak_provenance"):
        assert p["state"][k] == g["state"][k], k
    for k in ("open_r", "peak_r", "giveback_r", "bars_since_peak", "r_to_stop", "r_to_target"):
        assert p["features_at_review"][k] == g["features_at_review"][k], k
    assert p["mechanics"]["verdict"] == g["mechanics"]["verdict"] == "match"
    assert [(a["account_id"], a["account_class"]) for a in p["account_bounds"]] == [
        ("bybit_2", "real_money"), ("bybit_1", "paper"), ("bybit_portfolio", "paper")]
    assert {a["account_id"] for a in p["account_bounds"]} == {a["account_id"] for a in g["account_bounds"]}


@needs_gold
def test_ada_venue_stop_off_the_package_is_a_mismatch():
    g = GOLD[ADA]
    bad = _bybit(["bybit_2"])
    bad["accounts"][0]["result"]["orders"][0]["trigger_price"] = 0.2150
    s = _snap(telemetry={"rows": [_tel(g, "bybit_2")]}, bybit_orders=bad)
    s.packages[ADA] = _pkg(g, "ADAUSDT", "short")
    p = _build(ADA, s)
    assert p["mechanics"]["verdict"] == "mismatch" and "venue SL" in p["mechanics"]["evidence"]


@needs_gold
def test_mgc_ib_stop_and_target_match():
    g = GOLD[MGC]
    ib = {"accounts": [{"account_id": "ib_paper", "read_state": "orders_read", "orders": [
        {"symbol": "MGC", "action": "BUY", "order_type": "STP", "aux_price": 4270.0},
        {"symbol": "MGC", "action": "BUY", "order_type": "LMT", "lmt_price": 3767.0}]}]}
    s = _snap(telemetry={"rows": [_tel(g, "ib_paper")]}, ib_orders=ib)
    s.packages[MGC] = _pkg(g, "MGC", "short")
    p = _build(MGC, s)
    assert p["mechanics"]["verdict"] == "match"
    assert [a["account_id"] for a in p["account_bounds"]] == ["ib_paper"]
    assert p["account_bounds"][0]["read_if_amend"] == "unknown"  # no IB apply path


@needs_gold
def test_gdx_rejected_trade_rows_are_not_carrying_accounts():
    g = GOLD[GDX]
    al = {"accounts": [{"account_id": "alpaca_paper", "read_state": "orders_read", "result": {"positions": [], "orders": [
        {"symbol": "GDX", "side": "buy", "order_class": "bracket", "order_type": "limit", "limit_price": 78.25},
        {"symbol": "GDX", "side": "buy", "order_class": "bracket", "order_type": "stop", "stop_price": 89.19}]}}]}
    s = _snap(telemetry={"rows": [_tel(g, "alpaca_paper")]}, alpaca_orders=al)
    s.packages[GDX] = _pkg(g, "GDX", "short")
    s.trades = [{"order_package_id": GDX, "account_id": "alpaca_options_paper", "status": "rejected"}]
    p = _build(GDX, s)
    assert [a["account_id"] for a in p["account_bounds"]] == [a["account_id"] for a in g["account_bounds"]]
    assert p["mechanics"]["verdict"] == "match"


@needs_gold
def test_eth_prop_closed_package_with_open_prop_position_is_a_mismatch():
    g = GOLD[ETH]
    raw = {"positions": [{"symbol": "ETHUSDT", "direction": "short"}]}
    status = {"status": {"raw": json.dumps(raw)}, "phone_events": [
        {"kind": "heartbeat", "reason": "amend prop-manual-2e786ef17c05a6 REFUSED: sheet volume 0.4 = ticket qty 0.* (sheet close: escape)"}]}
    trail = {"amend_id": "prop-manual-2e786ef17c05#a6", "amend_status": "refused", "fails": 6,
             "last_plan_action": "exit", "last_plan_why": "trail crossed"}
    tickets = {"tickets": [{"order_package_id": ETH, "account_id": "breakout_2", "status": "filled", "close_reason": "sl_cross", "phone_trail": trail},
                           {"order_package_id": ETH, "account_id": "tradeify_1", "status": "closed", "close_reason": "sl_cross", "phone_trail": None},
                           {"order_package_id": ETH, "account_id": "velotrade_1", "status": "closed", "close_reason": "sl_cross", "phone_trail": None}]}
    s = _snap(prop_tickets=tickets, **{"prop_status:breakout_2": status})
    s.packages[ETH] = _pkg(g, "ETHUSDT", "short", status="closed",
                           meta={"regime": "chop", "vol_regime": "calm", "timeframe": "4h"})
    s.packages[ETH]["close_reason"] = "sl_cross"
    s.trades = [{"order_package_id": ETH, "account_id": "bybit_1", "status": "closed"}]
    p = _build(ETH, s)
    assert p["mechanics"]["verdict"] == g["mechanics"]["verdict"] == "mismatch"
    assert p["regime"]["cell_entry"] == g["regime"]["cell_entry"] == "chop/calm"
    assert [a["account_id"] for a in p["account_bounds"]] == [a["account_id"] for a in g["account_bounds"]]
    b = {a["account_id"]: a for a in p["account_bounds"]}
    assert b["breakout_2"]["read_if_amend"] == "refused_by_account_risk" == [x for x in g["account_bounds"] if x["account_id"] == "breakout_2"][0]["read"]
    # the phone refusal reason, a wanted-but-missing input of the hand run, is now filled
    assert "sheet volume 0.4" in b["breakout_2"]["phone_amend"]["refusal_reason"]
    assert b["tradeify_1"]["read_if_amend"] == "unknown"
    assert ETH in L.open_package_ids(s)  # a filled prop ticket makes the package open even though the package is closed


@needs_gold
def test_unreachable_inputs_are_null_with_a_reason_never_zero():
    g = GOLD[ADA]
    s = _snap(telemetry={"rows": [_tel(g, "bybit_2")]}, bybit_orders=_bybit(["bybit_2"]))
    s.packages[ADA] = _pkg(g, "ADAUSDT", "short", meta={"timeframe": "2h", "atr": 0.0047})
    s.candles["ADAUSDT|2h"] = {"candles": [], "error": "no_data"}
    p = _build(ADA, s)
    fields = {m["field"] for m in p["missing_inputs"]}
    assert {"context.funding", "regime.vol_now", "regime.atr_now_over_entry"} <= fields
    assert p["context"]["funding"] is None and p["state"]["atr_now_over_entry"] is None
    assert all(m["reason"] for m in p["missing_inputs"])


@needs_gold
def test_missing_telemetry_is_null_not_zero():
    g = GOLD["pkg-6a8e3fb325464be3"]
    s = _snap(telemetry={"rows": []})
    s.packages[g["order_package_id"]] = _pkg(g, "GLD", "long", status="open")
    p = _build(g["order_package_id"], s)
    assert p["state"]["open_r"] is None and p["features_at_review"]["giveback_r"] is None
    assert p["state"]["peak_provenance"] == "unverified"


@needs_gold
def test_read_failure_is_recorded_not_swallowed():
    g = GOLD[ADA]
    s = _snap(telemetry={"rows": [_tel(g, "bybit_2")]})
    s.errors["bybit_orders"] = "diag exit 3"
    s.packages[ADA] = _pkg(g, "ADAUSDT", "short")
    p = _build(ADA, s)
    assert p["mechanics"]["verdict"] == "could_not_look"
    assert any(m["field"] == "read:bybit_orders" for m in p["missing_inputs"])


@needs_gold
def test_packet_sha_matches_every_golden_row():
    rows = [json.loads(x) for x in (REPO / "comms/live_review/reviews.jsonl").read_text().splitlines() if x.strip().startswith("{")]
    checked = 0
    for r in rows:
        if r.get("packet_sha"):
            pk = json.loads((REPO / "comms/live_review/packets" / f"{r['review_id']}.json").read_text())
            assert L.packet_sha(pk) == r["packet_sha"]
            checked += 1
    assert checked >= 9


@needs_gold
def test_generated_packet_passes_the_validators_sha_check():
    spec = importlib.util.spec_from_file_location("clrr", REPO / "scripts/ci/check_live_review_records.py")
    v = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v)
    g = GOLD[ADA]
    s = _snap(telemetry={"rows": [_tel(g, "bybit_2")]}, bybit_orders=_bybit(["bybit_2"]))
    s.packages[ADA] = _pkg(g, "ADAUSDT", "short")
    p = _build(ADA, s)
    d = Path(__import__("tempfile").mkdtemp())
    (d / f"{p['review_id']}.json").write_text(json.dumps(p, indent=1, sort_keys=True))
    assert v.packet_problems({"review_id": p["review_id"], "packet_sha": L.packet_sha(p)}, d) == []
    assert p["packet_version"] == 2 and p["info_cutoff_at"] == "2026-10-25T16:16:30Z"
    # golden v1 keys are a subset of the v2 keys
    assert set(GOLD[ADA]) - {"assembled_by"} <= set(p)


def test_atr_is_the_sma_of_true_range_and_forming_bar_is_dropped():
    bars = [{"time": 1000 * i, "open": 1, "high": 2, "low": 1, "close": 1.5} for i in range(20)]
    assert L.atr_sma(bars, 14) == 1.0  # TR = max(h-l=1, |h-pc|=0.5, |l-pc|=0.5)
    assert L.atr_sma(bars[:10], 14) is None
    last = {"time": int(NOW.timestamp()) - 3600, "open": 1, "high": 1, "low": 1, "close": 1}  # 2h bar opened 1h ago: forming
    assert L._closed_bars([last], "2h", NOW) == []
    assert L._closed_bars([{**last, "time": int(NOW.timestamp()) - 7200}], "2h", NOW)


def test_calendar_distinguishes_no_events_from_stale_and_no_classes():
    assert L._calendar("XRPUSDT", NOW)["state"] == "no_event_classes_for_symbol"
    c = L._calendar("ETHUSDT", NOW)  # the committed file's newest event is long past: 'no events' is NOT known
    assert c["state"] == "stale" and c["events_next_24h"] == []


@needs_gold
def test_packets_carry_no_account_numbers_or_ips():
    g = GOLD[MGC]
    ib = {"accounts": [{"account_id": "ib_paper", "read_state": "orders_read", "orders": [
        {"symbol": "MGC", "action": "BUY", "order_type": "STP", "aux_price": 4270.0, "account": "DUQ0000000"}]}]}
    s = _snap(telemetry={"rows": [_tel(g, "ib_paper")]}, ib_orders=ib)
    s.packages[MGC] = _pkg(g, "MGC", "short")
    txt = json.dumps(_build(MGC, s))
    assert "DUQ" not in txt and not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", txt)


def test_open_set_is_the_union_of_sources():
    s = _snap(telemetry={"rows": [{"order_package_id": "a", "lifecycle": "open"}, {"order_package_id": "b", "lifecycle": "closed"}]},
              prop_tickets={"tickets": [{"order_package_id": "c", "status": "filled"}, {"order_package_id": "d", "status": "closed"}]})
    s.packages["e"] = {"order_package_id": "e", "status": "open"}
    s.trades = [{"order_package_id": "f", "status": "open"}]
    assert L.open_package_ids(s) == ["a", "c", "e", "f"]

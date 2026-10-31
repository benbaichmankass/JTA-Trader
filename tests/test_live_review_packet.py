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
@pytest.mark.skipif(not (REPO / "scripts/ci/check_live_review_records.py").exists(), reason="validator lands with PR #20121")
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
    assert p["packet_version"] == 3 and p["info_cutoff_at"] == "2026-10-25T16:16:30Z"
    # golden v1 keys are a subset of the v2 keys
    assert set(GOLD[ADA]) - {"assembled_by"} <= set(p)


def test_atr_is_the_sma_of_true_range_and_forming_bar_is_dropped():
    bars = [{"time": 1000 * i, "open": 1, "high": 2, "low": 1, "close": 1.5} for i in range(20)]
    assert L.atr_sma(bars, 14) == 1.0  # TR = max(h-l=1, |h-pc|=0.5, |l-pc|=0.5)
    assert L.atr_sma(bars[:10], 14) is None
    last = {"time": int(NOW.timestamp()) - 3600, "open": 1, "high": 1, "low": 1, "close": 1}  # 2h bar opened 1h ago: forming
    assert L._closed_bars([last], "2h", NOW) == []
    assert L._closed_bars([{**last, "time": int(NOW.timestamp()) - 7200}], "2h", NOW)


def test_calendar_distinguishes_no_events_from_stale_and_no_classes(tmp_path, monkeypatch):
    assert L._calendar("XRPUSDT", NOW)["state"] == "no_event_classes_for_symbol"
    # the stale case runs on a fixture calendar whose newest event is in the past: 'no events' is NOT known
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "economic_calendar.yaml").write_text(
        'symbol_event_classes:\n  ETH: [fomc]\nevents:\n  - {class: fomc, time: "2026-07-29T18:30:00Z", impact: 1.0}\n')
    monkeypatch.setattr(L, "REPO", tmp_path)
    c = L._calendar("ETHUSDT", NOW)
    assert c["state"] == "stale" and c["events_next_24h"] == []


def test_committed_calendar_is_no_longer_stale_at_the_packet_cutoff():
    # DATA-FEEDS-NEWS-CALENDAR: the scheduled refresh keeps the committed file ahead of the cutoff.
    assert L._calendar("ETHUSDT", NOW)["state"] == "read"


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


# ----------------------------------------------------------------------------- context_v3 (DESK-AM-REFOCUS)

def _bars(closes, t0=1_700_000_000, step=7200):
    return [{"time": t0 + i * step, "open": c, "high": c + 1.0, "low": c - 1.0, "close": c} for i, c in enumerate(closes)]


def test_swings_finds_the_pivots_newest_first():
    closes = [10, 11, 12, 13, 12, 11, 10, 9, 10, 11, 12, 11, 10]
    sw = L.swings(_bars(closes), k=2, lookback=60)
    assert [h["px"] for h in sw["highs"]] == [13.0, 14.0]   # high = close + 1
    assert sw["lows"][0]["px"] == 8.0 and sw["lows"][0]["bars_ago"] == 5


def test_chart_block_is_compact_and_null_without_bars():
    assert L.chart_block([], 1.0) is None
    c = L.chart_block(_bars(list(range(40))), 2.0)
    assert len(c["bars_ohlc"]) == L.CHART_BARS and c["bars_ohlc"][-1][4] == 39.0
    assert all(x["dist_atr"] is not None for x in c["swings"]["highs"] + c["swings"]["lows"])


def test_since_entry_reads_only_bars_after_the_open():
    b = _bars([10, 20, 12, 13, 14])
    se = L.since_entry(b, b[2]["time"], 1.0)
    assert se["bars"] == 3 and se["high"] == 15.0 and se["low"] == 11.0
    assert L.since_entry(b, None, 1.0) is None


def test_book_lists_other_open_packages_on_both_sides():
    s = _snap(telemetry={"rows": [
        {"order_package_id": "pkg-a", "lifecycle": "open", "strategy": "x", "symbol": "ADAUSDT", "direction": "short", "open_r": 0.5},
        {"order_package_id": "pkg-b", "lifecycle": "open", "strategy": "y", "symbol": "XRPUSDT", "direction": "long", "open_r": -0.2}]})
    book = L.book_block(s, "pkg-a")
    assert book == [["XRPUSDT", "long", "y", -0.2]]


def test_packet_carries_context_v3_and_names_what_it_could_not_read():
    s = _snap(telemetry={"rows": []})
    s.packages["pkg-z"] = {"order_package_id": "pkg-z", "strategy_name": "ada_pullback_2h", "symbol": "ADAUSDT",
                           "direction": "short", "entry": "1.0", "sl": "1.1", "tp": "0.8", "status": "open",
                           "close_reason": None, "meta": json.dumps({"timeframe": "2h", "atr_stop_mult": 1.5})}
    s.candles["ADAUSDT|2h"] = {"candles": [], "error": "no_data"}
    p = _build("pkg-z", s)
    c3 = p["context_v3"]
    assert c3["chart"] is None and c3["htf"] is None and c3["live_vs_backtest"] is None
    assert c3["exit_plan"]["sl_now"] == 1.1 and c3["exit_plan"]["declared"] == {"atr_stop_mult": 1.5, "timeframe": "2h"}
    names = {m["field"] for m in p["missing_inputs"]}
    assert {"context_v3.chart", "context_v3.htf", "context_v3.live_vs_backtest"} <= names


def test_weekly_drops_the_unfinished_week():
    t0 = int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp())   # a Monday
    daily = [{"time": t0 + i * 86400, "open": i, "high": i + 2, "low": i - 2, "close": i + 1} for i in range(16)]
    w = L.weekly(daily)
    assert len(w) == 2 and w[0]["open"] == 0 and w[0]["close"] == 7 and w[0]["high"] == 8 and w[1]["low"] == 5


def _desk_snap():
    s = _snap(telemetry={"rows": []})
    s.packages["pkg-d"] = {"order_package_id": "pkg-d", "strategy_name": "claude_desk", "symbol": "BTCUSDT",
                           "direction": "long", "entry": "100", "sl": "97", "tp": "106", "status": "open",
                           "close_reason": None, "meta": json.dumps({"timeframe": "1h", "decision_id": "DD-20261025T1500Z-scan-1h-1"})}
    s.candles["BTCUSDT|1h"] = {"candles": [], "error": "no_data"}
    return s


def test_a_desk_package_packet_carries_the_handoff_block(monkeypatch):
    """DESK-HANDOFF-PROTOCOL (b): every wake on a desk-opened position gets the opening record and the chain."""
    row = {"decision_id": "DD-20261025T1500Z-scan-1h-1", "proposal": {"symbol": "BTCUSDT", "side": "long",
           "forecast": {"target_px": 106.0}, "exit_plan": "brackets", "entry": {"level": 100}, "stop": {"level": 97},
           "tp": {"level": 106}}}
    monkeypatch.setattr(L, "_desk_rows", lambda: [row])
    p = _build("pkg-d", _desk_snap())
    dh = p["desk_handoff"]
    assert dh["opening"]["decision_id"] == row["decision_id"] and dh["opening"]["exit_plan"] == "brackets"
    assert dh["prior_decision_id"] in (row["decision_id"],) or dh["prior_decision_id"].startswith("LR-")


def test_a_desk_packet_whose_record_cannot_be_read_says_so(monkeypatch):
    monkeypatch.setattr(L, "_desk_rows", lambda: None)
    p = _build("pkg-d", _desk_snap())
    assert p["desk_handoff"]["read_state"] == "could_not_look"
    assert "desk_handoff" in {m["field"] for m in p["missing_inputs"]}


def test_a_strategy_package_packet_has_no_handoff_block(monkeypatch):
    monkeypatch.setattr(L, "_desk_rows", lambda: [])
    s = _desk_snap()
    s.packages["pkg-d"]["strategy_name"] = "ada_pullback_2h"
    assert "desk_handoff" not in _build("pkg-d", s)


def test_previous_review_carries_the_prior_forecast_verbatim():
    """LTR-PREV-FORECAST: the prior row's forecast (thesis inside) reaches the next reviewer, original keys unchanged."""
    fc = {"thesis": "bounce stalls under 98.5", "direction": "with_trade", "target_px": 92.32, "p_target": 0.42,
          "invalidation_px": 98.54, "horizon_bars": 6, "timeframe": "4h", "evidence": ["chart.swings"]}
    row = {"review_id": "LR-1", "reviewed_at": "2026-10-31T10:00:00Z", "forecast": fc,
           "recommendation": {"action": "hold", "route": "none", "reason": "x" * 1000}}
    pr = L.previous_review_block(row)
    assert pr["forecast"] == fc
    assert (pr["review_id"], pr["reviewed_at"], pr["action"], pr["route"]) == ("LR-1", "2026-10-31T10:00:00Z", "hold", "none")
    assert len(pr["reason"]) == L.PREV_REASON_MAX


def test_previous_review_without_a_forecast_is_an_explicit_null():
    for row in ({"review_id": "LR-0", "recommendation": {"action": "hold"}},
                {"review_id": "LR-0", "forecast": None, "recommendation": {"action": "hold"}}):
        pr = L.previous_review_block(row)
        assert "forecast" in pr and pr["forecast"] is None and pr["reason"] is None


def test_packet_previous_review_is_the_newest_row_with_its_forecast(monkeypatch):
    from src.runtime import live_review_due as lrd
    old = {"order_package_id": "pkg-d", "review_id": "LR-a", "reviewed_at": "2026-10-31T08:00:00Z", "forecast": {"thesis": "old"}}
    new = {"order_package_id": "pkg-d", "review_id": "LR-b", "reviewed_at": "2026-10-31T09:00:00Z",
           "forecast": {"thesis": "new"}, "recommendation": {"action": "hold", "reason": "r"}}
    monkeypatch.setattr(lrd, "read_reviews_merged", lambda path: {"rows": [new, old]})
    monkeypatch.setattr(L, "_desk_rows", lambda: [])
    s = _desk_snap()
    s.packages["pkg-d"]["strategy_name"] = "ada_pullback_2h"
    pr = _build("pkg-d", s)["context"]["previous_review"]
    assert pr["review_id"] == "LR-b" and pr["forecast"] == {"thesis": "new"}


def test_sibling_slice_legs_are_not_read_as_this_packages_bracket():
    """PI-20261031-TD4QC5GP-0004: two qty-scoped Partial legs on one symbol; last-leg-wins filed a false mismatch."""
    acct = {"accounts": [{"account_id": "bybit_1", "read_state": "orders_read", "result": {
        "positions": [{"symbol": "XRPUSDT", "side": "Sell", "size": 3.0}],
        "orders": [
            {"symbol": "XRPUSDT", "order_id": "mine-sl", "stop_order_type": "PartialStopLoss", "trigger_price": 1.2521},
            {"symbol": "XRPUSDT", "order_id": "mine-tp", "stop_order_type": "PartialTakeProfit", "trigger_price": 1.2421},
            {"symbol": "XRPUSDT", "order_id": "sib-sl", "stop_order_type": "PartialStopLoss", "trigger_price": 1.257},
            {"symbol": "XRPUSDT", "order_id": "sib-tp", "stop_order_type": "PartialTakeProfit", "trigger_price": 1.2185}]}}]}
    s = _snap(bybit_orders=acct)
    v = L._venue_exit_prices(s, "bybit_1", "bybit", "XRPUSDT", "short", "mine-sl", "mine-tp")
    assert (v["sl"], v["tp"], v["ambiguous"]) == (1.2521, 1.2421, False)
    v = L._venue_exit_prices(s, "bybit_1", "bybit", "XRPUSDT", "short", None, None)
    assert (v["sl"], v["tp"], v["ambiguous"]) == (None, None, True)

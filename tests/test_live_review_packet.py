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

NOW = datetime(2026, 10, 25, 16, 16, 30, tzinfo=timezone.utc)
# The hand-built goldens are the packets of ONE review, the one at NOW (LR-20261025T1616Z-*). The directory
# also holds every later production packet (20 for the MGC package alone, written by the live-review wake),
# and several of those carry a moved level (MGC SL 4270.03 -> 4160.33 after the 2026-10-31 tighten). Keying
# an unsorted glob("*.json") by package id let the LAST file in directory order win, which varies between
# checkouts, so CI read a 4160 SL against the fixture's 4270 STP about 1 run in 3 and failed
# test_mgc_ib_stop_and_target_match with 'mismatch' (CI-MGC-IB-STOP-TARGET-INTERMITTENT). Pin to the review.
GOLDEN_REVIEW = f"LR-{NOW:%Y%m%dT%H%M}Z"
GOLD = {json.loads(f.read_text())["order_package_id"]: json.loads(f.read_text())
        for f in sorted((REPO / "comms/live_review/packets").glob(f"{GOLDEN_REVIEW}-*.json"))}
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


# --------------------------------------------------------------------------- LTR-PACKET-FIXES (2026-11-01)
# Two packages on ONE symbol in ONE account: each packet must read its OWN orders, never the sibling's.
# Measured case: ib_paper held MGC pkg-011a (qty 14, oca-protect-t6673, STP 4160.3 / LMT 3767.0) and pkg-d76f
# (qty 1, oca-protect-t6803, STP 3938.1 / LMT 3596.2); symbol matching read pkg-d76f's levels as pkg-011a's.

A_PKG, B_PKG = "pkg-aaaa000000000001", "pkg-bbbb000000000002"


def _two_pkg_snap(**reads):
    s = _snap(**reads)
    for pid, sl, tp, tid, q in ((A_PKG, "4160.32857143", "3766.9909", 6673, 14.0),
                                (B_PKG, "3938.07142857", "3596.1613", 6803, 1.0)):
        s.packages[pid] = {"order_package_id": pid, "strategy_name": "mgc_pullback_1d", "symbol": "MGC",
                           "direction": "short", "entry": "4000", "sl": sl, "tp": tp, "status": "open", "meta": "{}"}
        s.trades.append({"id": tid, "order_package_id": pid, "account_id": "ib_paper", "status": "open",
                         "symbol": "MGC", "position_size": q, "account_class": "paper"})
    return s


def _ib_two():
    return {"accounts": [{"account_id": "ib_paper", "read_state": "orders_read", "orders": [
        {"symbol": "MGC", "action": "BUY", "order_type": "STP", "aux_price": 4160.3, "oca_group": "oca-protect-t6673"},
        {"symbol": "MGC", "action": "BUY", "order_type": "LMT", "lmt_price": 3767.0, "oca_group": "oca-protect-t6673"},
        {"symbol": "MGC", "action": "BUY", "order_type": "STP", "aux_price": 3938.1, "oca_group": "oca-protect-t6803"},
        {"symbol": "MGC", "action": "BUY", "order_type": "LMT", "lmt_price": 3596.2, "oca_group": "oca-protect-t6803"}]}]}


@pytest.mark.parametrize("pkg", [A_PKG, B_PKG])
def test_ib_two_packages_on_one_symbol_each_read_their_own_oca_group(pkg):
    p = _build(pkg, _two_pkg_snap(ib_orders=_ib_two()), cfg={"ib_paper": {"exchange": "interactive_brokers",
                                                                           "account_class": "paper"}})
    assert p["mechanics"]["verdict"] == "match", p["mechanics"]
    assert "matched by oca_group" in p["account_bounds"][0]["evidence"]


def test_ib_own_group_off_the_package_is_still_a_mismatch():
    ib = _ib_two()
    ib["accounts"][0]["orders"][0]["aux_price"] = 4300.0  # pkg A's OWN stop moved: a real mismatch must not hide
    p = _build(A_PKG, _two_pkg_snap(ib_orders=ib), cfg={"ib_paper": {"exchange": "interactive_brokers"}})
    assert p["mechanics"]["verdict"] == "mismatch" and "venue SL 4300.0" in p["mechanics"]["evidence"]


def test_ib_siblings_without_keyed_groups_are_ambiguous_never_a_mismatch():
    ib = _ib_two()
    for o in ib["accounts"][0]["orders"]:
        o["oca_group"] = "oca-protect-" + o["oca_group"][-4:]  # legacy reqId groups: no trade key
    s = _two_pkg_snap(ib_orders=ib)
    v = L._venue_exit_prices(s, "ib_paper", "interactive_brokers", "MGC", "short", trade_id=6673, siblings=1)
    assert (v["sl"], v["tp"], v["ambiguous"], v["position"]) == (None, None, True, True)
    p = _build(A_PKG, s, cfg={"ib_paper": {"exchange": "interactive_brokers"}})
    # never a mismatch from a leg that is not this package's -- and, since SHARED-BRACKET-FIX (2026-11-04), never
    # a "match" either: no level was compared, so the only honest verdict is could_not_look
    assert p["mechanics"]["verdict"] == "could_not_look" and "venue SL" not in p["mechanics"]["evidence"]
    assert "levels not compared" in p["mechanics"]["evidence"]


def test_ib_single_package_legacy_group_still_reads_by_symbol():
    ib = {"accounts": [{"account_id": "ib_paper", "read_state": "orders_read", "orders": [
        {"symbol": "MGC", "action": "BUY", "order_type": "STP", "aux_price": 4160.3, "oca_group": "oca-protect-5"},
        {"symbol": "MGC", "action": "BUY", "order_type": "LMT", "lmt_price": 3767.0, "oca_group": "oca-protect-5"}]}]}
    v = L._venue_exit_prices(_snap(ib_orders=ib), "ib_paper", "interactive_brokers", "MGC", "short", trade_id=6673)
    assert (v["sl"], v["tp"], v["ambiguous"]) == (4160.3, 3767.0, False)


def _alpaca_two():
    return {"accounts": [{"account_id": "alpaca_paper", "read_state": "orders_read", "result": {
        "positions": [{"symbol": "USO", "side": "buy", "qty": 400.0}], "orders": [
            {"symbol": "USO", "order_id": "tp-a", "order_type": "limit", "order_class": "bracket", "side": "sell",
             "qty": 301.0, "limit_price": 180.28, "parent_id": None},
            {"symbol": "USO", "order_id": "sl-a", "order_type": "stop", "order_class": "bracket", "side": "sell",
             "qty": 301.0, "stop_price": 167.93, "parent_id": "entry-a"},
            {"symbol": "USO", "order_id": "tp-b", "order_type": "limit", "order_class": "bracket", "side": "sell",
             "qty": 99.0, "limit_price": 190.0, "parent_id": None},
            {"symbol": "USO", "order_id": "sl-b", "order_type": "stop", "order_class": "bracket", "side": "sell",
             "qty": 99.0, "stop_price": 160.0, "parent_id": "entry-b"}]}}]}


def test_alpaca_two_packages_on_one_symbol_read_by_parent_id_and_qty():
    s = _snap(alpaca_orders=_alpaca_two())
    a = L._venue_exit_prices(s, "alpaca_paper", "alpaca", "USO", "long", broker_order_id="entry-a", qty=301.0, siblings=1)
    b = L._venue_exit_prices(s, "alpaca_paper", "alpaca", "USO", "long", broker_order_id="entry-b", qty=99.0, siblings=1)
    assert (a["sl"], a["tp"], a["ambiguous"]) == (167.93, 180.28, False)
    assert (b["sl"], b["tp"], b["ambiguous"]) == (160.0, 190.0, False)


def test_alpaca_siblings_with_no_id_or_qty_link_are_ambiguous():
    s = _snap(alpaca_orders=_alpaca_two())
    v = L._venue_exit_prices(s, "alpaca_paper", "alpaca", "USO", "long", siblings=1)
    assert (v["sl"], v["tp"], v["ambiguous"]) == (None, None, True)


def test_bybit_sole_leg_is_not_taken_as_ours_when_a_sibling_holds_the_symbol():
    acct = {"accounts": [{"account_id": "bybit_1", "read_state": "orders_read", "result": {
        "positions": [{"symbol": "XRPUSDT", "side": "Sell", "size": 3.0, "stop_loss": 1.3}],
        "orders": [{"symbol": "XRPUSDT", "order_id": "sib-sl", "stop_order_type": "PartialStopLoss", "trigger_price": 1.257}]}}]}
    v = L._venue_exit_prices(_snap(bybit_orders=acct), "bybit_1", "bybit", "XRPUSDT", "short", siblings=1)
    assert (v["sl"], v["tp"], v["ambiguous"]) == (None, None, True)
    v = L._venue_exit_prices(_snap(bybit_orders=acct), "bybit_1", "bybit", "XRPUSDT", "short")
    assert (v["sl"], v["ambiguous"]) == (1.257, False)


def test_a_closed_package_is_not_an_orphan_when_a_sibling_package_holds_the_symbol():
    s = _two_pkg_snap(ib_orders=_ib_two())
    s.packages[A_PKG]["status"] = "closed"
    s.trades[0]["status"] = "closed"
    p = _build(A_PKG, s, cfg={"ib_paper": {"exchange": "interactive_brokers"}})
    assert p["mechanics"]["verdict"] == "match", p["mechanics"]
    assert "sibling package(s) " + B_PKG in p["mechanics"]["evidence"]


def test_account_bounds_name_the_real_apply_paths():
    assert L.apply_paths("alpaca") == ["close", "move_tp", "tighten"]
    assert L.apply_paths("bybit") == ["close", "move_tp", "reduce", "tighten", "widen_sl"]
    assert L.apply_paths("interactive_brokers") == []
    s = _snap(alpaca_orders=_alpaca_two())
    s.packages[A_PKG] = {"order_package_id": A_PKG, "strategy_name": "uso_trend_1h", "symbol": "USO", "direction": "long",
                         "entry": "170", "sl": "167.93", "tp": "180.28", "status": "open", "meta": "{}"}
    s.trades = [{"id": 1, "order_package_id": A_PKG, "account_id": "alpaca_paper", "status": "open", "symbol": "USO",
                 "broker_order_id": "entry-a", "position_size": 301.0, "account_class": "paper"}]
    b = _build(A_PKG, s, cfg={"alpaca_paper": {"exchange": "alpaca", "account_class": "paper"}})["account_bounds"][0]
    assert b["apply_paths"] == ["close", "move_tp", "tighten"] and b["read_if_amend"] == "would_apply"
    assert "no apply path" not in b["evidence"]


def test_tighten_classes_match_the_apply_dispatch():
    """TIGHTEN_CLASSES mirrors live_review_apply.run()'s tighten dispatch; a new branch there must be added here."""
    src = (REPO / "scripts/ops/live_review_apply.py").read_text()
    dispatched = set(re.findall(r'elif cls == "(\w+)":\n\s+res = _exec_\w+\((?:db|leg)', src))
    dispatched |= {"phone"} if re.search(r'else:  # phone\n\s+res = _exec_phone\(', src) else set()
    assert dispatched == set(L.TIGHTEN_CLASSES)
    assert 'if v.ok and (cls == "other"' in src  # IB / other: the tighten is refused, so it is not a path


def test_missing_evidence_record_is_a_named_state_not_a_traceback():
    priced, why = L._price("no_such_leg_xyz", "short", {"open_r": 0.1, "peak_r": 0.2}, 2.0, "LR-x", False)
    assert priced is None and why.startswith("evidence_missing")
    assert L.priced_state(None, why, True) == "evidence_missing"
    assert L.priced_state(None, "live_review_outcomes failed: boom", True) == "could_not_price"
    assert L.priced_state(None, None, False) == "not_priced"


def test_packet_carries_the_generator_state():
    p = _build(A_PKG, _two_pkg_snap(ib_orders=_ib_two(), generator={"state": "stale_vs_origin_main", "head": "x"}),
               cfg={"ib_paper": {"exchange": "interactive_brokers"}})
    assert p["generator"]["state"] == "stale_vs_origin_main"
    assert any(m["field"] == "generator" for m in p["missing_inputs"])
    assert L.generator_state()["state"] in ("current", "stale_vs_origin_main", "could_not_look")


def test_a_closed_package_is_not_read_as_an_open_position_held_by_its_sibling():
    """2026-11-02: pkg-4fd943 (ict_scalp_xrp_5m, bybit_1) closed at its SL while sibling pkg-7bb5b257 (e4_oi_shock_1h)
    still held XRPUSDT; the packet read the closed package as 'position True, SL/TP None'. It must read it as closed."""
    closed, sib = "pkg-closed000000001", "pkg-sibling00000002"
    acct = {"accounts": [{"account_id": "bybit_1", "read_state": "orders_read", "result": {
        "positions": [{"symbol": "XRPUSDT", "side": "Sell", "size": 50.0}],
        "orders": [
            {"symbol": "XRPUSDT", "order_id": "sib-sl", "stop_order_type": "PartialStopLoss", "trigger_price": 2.61},
            {"symbol": "XRPUSDT", "order_id": "sib-tp", "stop_order_type": "PartialTakeProfit", "trigger_price": 2.31}]}}]}
    s = _snap(bybit_orders=acct)
    s.packages[closed] = {"order_package_id": closed, "strategy_name": "ict_scalp_xrp_5m", "symbol": "XRPUSDT",
                          "direction": "short", "entry": "2.5", "sl": "2.55", "tp": "2.40", "status": "closed",
                          "close_reason": "sl", "meta": "{}"}
    s.trades = [
        {"id": 1, "order_package_id": closed, "account_id": "bybit_1", "status": "closed", "symbol": "XRPUSDT",
         "sl_order_id": "own-sl", "tp_order_id": "own-tp", "account_class": "paper"},
        {"id": 2, "order_package_id": sib, "account_id": "bybit_1", "status": "open", "symbol": "XRPUSDT",
         "sl_order_id": "sib-sl", "tp_order_id": "sib-tp", "account_class": "paper"}]
    p = _build(closed, s, cfg={"bybit_1": {"exchange": "bybit", "account_class": "paper"}})
    b = p["account_bounds"][0]
    assert b["own_position"] is False and "position False" in b["evidence"]
    assert "belongs to " + sib in b["evidence"] and b["read_if_amend"] == "unknown"
    assert p["mechanics"]["verdict"] == "match" and "sibling package(s) " + sib in p["mechanics"]["evidence"]


# --------------------------------------------------------------------------- SHARED-BRACKET-FIX (2026-11-04)
# Packet LR-20261104T0244Z-pkg-1bb434d29c654597 read "match" with the evidence "levels not compared": bybit_1
# BTCUSDT held a sibling's legs (79165.4 / 70960.6) and none of this package's own ids. A packet that compares no
# level must never say match, and an ambiguous Bybit read compares the package level against every resting leg.

SCALP, DONCH = "pkg-1bb434d29c654597", "pkg-4e74f4bdc6d44735"


def _btc_snap(orders, size=0.59):
    acct = {"accounts": [{"account_id": "bybit_1", "read_state": "orders_read", "result": {
        "positions": [{"symbol": "BTCUSDT", "side": "Sell", "size": size, "position_idx": 2}], "orders": orders}}]}
    s = _snap(bybit_orders=acct)
    for pid, sl, tp, tid, q, sl_id, tp_id in (
            (SCALP, "77332.52695", "76602.83928571", 6855, 0.549, "db0ef1ff", "901541e3"),
            (DONCH, "79165.39", "70960.5976", 6784, 0.59, "8ca52700", "2e8e6ea2")):
        s.packages[pid] = {"order_package_id": pid, "strategy_name": "x", "symbol": "BTCUSDT", "direction": "short",
                           "entry": "77448.7", "sl": sl, "tp": tp, "status": "open", "meta": "{}"}
        s.trades.append({"id": tid, "order_package_id": pid, "account_id": "bybit_1", "status": "open",
                         "symbol": "BTCUSDT", "position_size": q, "account_class": "paper",
                         "sl_order_id": sl_id, "tp_order_id": tp_id})
    return s


_DONCH_LEGS = [
    {"symbol": "BTCUSDT", "side": "Buy", "order_id": "8ca52700", "stop_order_type": "PartialStopLoss", "trigger_price": 79165.4},
    {"symbol": "BTCUSDT", "side": "Buy", "order_id": "2e8e6ea2", "stop_order_type": "PartialTakeProfit", "trigger_price": 70960.6}]


def test_btc_0244z_packet_shape_is_a_mismatch_not_a_match():
    p = _build(SCALP, _btc_snap(list(_DONCH_LEGS)))
    m = p["mechanics"]
    assert m["verdict"] == "mismatch", m
    assert "no resting BTCUSDT SL leg at the package level 77332.52695" in m["evidence"]
    assert "79165.4" in m["evidence"]


def test_sibling_with_its_own_legs_still_matches():
    p = _build(DONCH, _btc_snap(list(_DONCH_LEGS)))
    assert p["mechanics"]["verdict"] == "match", p["mechanics"]


def test_ambiguous_read_with_a_leg_at_the_package_level_is_not_a_mismatch():
    legs = list(_DONCH_LEGS) + [
        {"symbol": "BTCUSDT", "side": "Buy", "order_id": "other-sl", "stop_order_type": "PartialStopLoss", "trigger_price": 77332.5},
        {"symbol": "BTCUSDT", "side": "Buy", "order_id": "other-tp", "stop_order_type": "PartialTakeProfit", "trigger_price": 76602.8}]
    m = _build(SCALP, _btc_snap(legs, size=1.139))["mechanics"]
    assert m["verdict"] == "match", m
    assert "own SL leg id is not resting, but a BTCUSDT SL leg rests at the package level" in m["evidence"]


def test_other_book_legs_are_not_this_packages_protection():
    """Hedge book: Sell-side legs act on the LONG book and are never compared with a short package's levels."""
    legs = [dict(o, side="Sell", trigger_price=77332.5 if "Stop" in o["stop_order_type"] else 76602.8,
                 order_id="long-" + o["order_id"]) for o in _DONCH_LEGS]
    m = _build(SCALP, _btc_snap(legs))["mechanics"]
    assert m["verdict"] == "mismatch" and "with NO resting SL leg" in m["evidence"], m


def test_bybit_position_with_no_tp_leg_is_a_mismatch():
    legs = [_DONCH_LEGS[0]]
    m = _build(DONCH, _btc_snap(legs))["mechanics"]
    assert m["verdict"] == "mismatch" and "NO resting TP leg" in m["evidence"], m


# --- PACKET-HEALTH (operator 2026-11-05): computed, never typed -------------------------------------------------

def _opts(*pairs):
    return [{"action": "hold", "n": 9, "mean_r": 1.0, "state": "measured"}] + [
        ({"action": "tighten", "state": st, "reason": rs, "n": 0, "mean_r": None} if mean is None
         else {"action": "tighten", "state": st, "n": 20, "mean_r": mean}) for st, rs, mean in pairs]


def _pk(options=None, **kw):
    p = {"priced_options": {"options": options} if options is not None else None,
         "priced_options_state": "priced" if options is not None else "could_not_price",
         "generator": {"state": "current"}, "mechanics": {"verdict": "match", "evidence": "ok"},
         "account_bounds": [{"account_id": "a"}], "state": {"open_r": 1.0},
         "context_v3": {"chart": {}, "htf": {}, "live_vs_backtest": {}}}
    p.update(kw)
    return p


def test_packet_health_ok_when_nothing_is_wrong():
    g = L
    assert g.packet_health(_pk(_opts(("measured", None, 0.5), ("invalid_level", None, None)))) == {"status": "ok", "defects": []}


def test_all_options_unpriced_for_one_reason_is_degraded_never_ok():
    g = L
    h = g.packet_health(_pk(_opts(*[("could_not_look", "no_candles", None)] * 5)))
    assert h["status"] == "degraded"
    assert {"field": "priced_options.options", "reason": "all_options_unpriced:no_candles", "count": 5, "denominator": 5} in h["defects"]
    assert {"field": "priced_options.candles", "reason": "candles_missing", "count": 5, "denominator": 5} in h["defects"]


def test_the_0700z_eth_packet_shape_is_degraded():
    """3 no_candles + 2 invalid_level, every tighten option unpriced (LR-20261105T0700Z-pkg-b76b0655d305485e)."""
    g = L
    h = g.packet_health(_pk(_opts(*([("could_not_look", "no_candles", None)] * 3 + [("invalid_level", None, None)] * 2))))
    assert h["status"] == "degraded"
    assert any(d["reason"] == "all_options_unpriced:invalid_level+no_candles" and d["count"] == 5 for d in h["defects"])
    assert any(d["reason"] == "candles_missing" and (d["count"], d["denominator"]) == (3, 5) for d in h["defects"])


def test_rungs_above_price_on_a_losing_trade_are_inapplicable_not_a_defect():
    """2026-11-13 (LTR-GRADER-COVERAGE): a losing long whose R rungs all sit at/above price read 'degraded' though
    nothing was missing. Those rungs are counted as inapplicable; real gaps beside them still degrade."""
    g = L
    rung = ("invalid_level", "stop_level_not_below_price", None)
    h = g.packet_health(_pk(_opts(*[rung] * 4)))
    assert h["status"] == "ok" and h["defects"] == []
    assert h["inapplicable_options"] == {"reason": "stop_level_not_below_price", "count": 4, "denominator": 4}
    h = g.packet_health(_pk(_opts(rung, rung, ("could_not_look", "no_candles", None), ("could_not_look", "no_candles", None))))
    assert h["status"] == "degraded"
    assert {"field": "priced_options.options", "reason": "all_options_unpriced:no_candles", "count": 2, "denominator": 2} in h["defects"]
    assert {"field": "priced_options.candles", "reason": "candles_missing", "count": 2, "denominator": 2} in h["defects"]
    assert h["inapplicable_options"]["count"] == 2


def test_other_defects_carry_a_reason_count_and_denominator():
    g = L
    h = g.packet_health(_pk(None, generator={"state": "stale_vs_origin_main"},
                            mechanics={"verdict": "match", "evidence": "1 account(s) could not be read"},
                            account_bounds=[{"account_id": "a"}, {"account_id": "b"}],
                            context_v3={"chart": None, "htf": {}, "live_vs_backtest": {}}))
    got = {(d["reason"], d["count"], d["denominator"]) for d in h["defects"]}
    assert ("could_not_price", 1, 1) in got and ("generator_stale", 1, 1) in got
    assert ("venue_read_unreachable", 1, 2) in got and ("context_null:chart", 1, 1) in got
    assert h["status"] == "degraded"


def test_a_packet_that_saw_nothing_is_could_not_look():
    g = L
    h = g.packet_health(_pk(None, mechanics={"verdict": "could_not_look", "evidence": "x"}))
    assert h["status"] == "could_not_look"


# --- LTR-MECH-PROP-MIRROR-BRACKET (2026-11-05) ------------------------------------------------------------------
# LR-20261105T1228Z-pkg-3245fc73e2f64536 read "mismatch: this package's own SL/TP leg is not resting" for
# trend_donchian_eth_prop on bybit_1. Venue order history: its own SL leg b372d2f8 (trigger 2408.18, qty 14.12)
# rested from 2026-11-04T15:00:31Z and FILLED at 2026-11-05T12:27:21Z; Bybit OCO-cancelled its TP. The L0 snapshot
# was 12:27:45Z. The bracket was intact and fired; the packet had no way to see that.

ETHP, ETHD, ETHE = "pkg-3245fc73e2f64536", "pkg-b76b0655d305485e", "pkg-e3a1aff66ea74ecc"


def _eth_snap(history=None, prop_status="open", tel_open=False):
    acct = {"accounts": [{"account_id": "bybit_1", "read_state": "orders_read", "result": {
        "positions": [{"symbol": "ETHUSDT", "side": "Buy", "size": 10.42, "position_idx": 1}],
        "orders": [
            {"symbol": "ETHUSDT", "side": "Sell", "order_id": "ecc0e4a1", "stop_order_type": "PartialStopLoss", "trigger_price": 2384.63},
            {"symbol": "ETHUSDT", "side": "Sell", "order_id": "c93a1351", "stop_order_type": "PartialTakeProfit", "trigger_price": 2509.58},
            {"symbol": "ETHUSDT", "side": "Sell", "order_id": "a2e7b2aa", "stop_order_type": "PartialStopLoss", "trigger_price": 2367.11},
            {"symbol": "ETHUSDT", "side": "Sell", "order_id": "31fdf2d8", "stop_order_type": "PartialTakeProfit", "trigger_price": 2677.03}]}}]}
    reads = {"bybit_orders": acct}
    if tel_open:
        reads["telemetry"] = {"rows": [{"order_package_id": ETHP, "account_id": "bybit_1", "lifecycle": "open"}]}
    if history is not None:
        reads[L._bybit_history_key("bybit_1", "ETHUSDT")] = history
    s = _snap(**reads)
    for pid, st, sl, tp, tid, q, sl_id, tp_id in (
            (ETHP, prop_status, "2408.177", "2614.91664", 6886, 14.12, "b372d2f8", "51f83d61"),
            (ETHD, "open", "2367.11035714", "2677.03212", 6888, 0.11, "a2e7b2aa", "31fdf2d8"),
            (ETHE, "open", "2384.6282142857144", "2509.5835714285718", 6890, 10.31, "ecc0e4a1", "c93a1351")):
        s.packages[pid] = {"order_package_id": pid, "strategy_name": "x", "symbol": "ETHUSDT", "direction": "long",
                           "entry": "2400", "sl": sl, "tp": tp, "status": "open", "meta": "{}"}
        s.trades.append({"id": tid, "order_package_id": pid, "account_id": "bybit_1", "status": st,
                         "symbol": "ETHUSDT", "position_size": q, "account_class": "paper",
                         "created_at": "2026-11-04T15:00:32+00:00",
                         "exit_reason": "netting_attributed" if st == "closed" else None,
                         "closed_at": "2026-11-05T12:27:38+00:00" if st == "closed" else None,
                         "sl_order_id": sl_id, "tp_order_id": tp_id})
    return s


def _hist(sl_status, tp_status, sl_cancel="UNKNOWN", tp_cancel="CancelByOCOTpCanceledBySlTriggered"):
    return {"read_state": "order_history_read", "result": {"records": [
        {"order_id": "b372d2f8", "order_status": sl_status, "cancel_type": sl_cancel, "trigger_price": "2408.18",
         "avg_price": "2408.02" if sl_status == "Filled" else "", "updated_time": "1793881641052"},
        {"order_id": "51f83d61", "order_status": tp_status, "cancel_type": tp_cancel, "trigger_price": "2614.92",
         "avg_price": "", "updated_time": "1793881641052"}]}}


def _cfg():
    return {"bybit_1": {"exchange": "bybit", "account_class": "paper"}}


def test_eth_prop_fired_sl_is_not_a_lost_bracket():
    m = _build(ETHP, _eth_snap(_hist("Filled", "Deactivated")), cfg=_cfg())["mechanics"]
    assert m["verdict"] == "match", m
    assert "own SL leg b372d2f8 FILLED at the venue at 2026-11-05T12:27:21Z" in m["evidence"]
    assert "CancelByOCOTpCanceledBySlTriggered" in m["evidence"]
    assert "NETTED across 3 open packages" in m["evidence"]


def test_eth_prop_cancelled_own_legs_on_an_open_trade_are_a_mismatch():
    m = _build(ETHP, _eth_snap(_hist("Deactivated", "Deactivated", "CancelByUser", "CancelByUser")),
               cfg=_cfg())["mechanics"]
    assert m["verdict"] == "mismatch", m
    assert "own SL leg b372d2f8 is Deactivated (CancelByUser)" in m["evidence"]
    assert "removed at the venue, not consumed" in m["evidence"]


def test_eth_prop_without_history_keeps_the_mismatch_and_names_netting():
    m = _build(ETHP, _eth_snap(None), cfg=_cfg())["mechanics"]
    assert m["verdict"] == "mismatch", m
    assert "NETTED across 3 open packages" in m["evidence"]


def test_sibling_with_its_own_resting_legs_still_matches_on_the_netted_book():
    m = _build(ETHD, _eth_snap(None), cfg=_cfg())["mechanics"]
    assert m["verdict"] == "match", m
    assert "NETTED" in m["evidence"]


def test_telemetry_open_does_not_override_a_closed_journal_row():
    s = _eth_snap(None, prop_status="closed", tel_open=True)
    s.packages[ETHP]["status"] = "open"  # the package cascade lags too
    m = _build(ETHP, s, cfg=_cfg())["mechanics"]
    assert m["verdict"] == "match", m
    assert "journal trade 6886 is closed (netting_attributed" in m["evidence"]


def test_collect_reads_history_only_where_an_own_leg_is_not_resting():
    s = _eth_snap(None)
    calls = []

    def diag(path):
        calls.append(path)
        return _hist("Filled", "Deactivated")
    L._read_consumed_bybit_legs(s, {ETHP, ETHD, ETHE}, diag)
    assert len(calls) == 1 and calls[0].startswith("bybit_raw_order_history?account_id=bybit_1&symbol=ETHUSDT")
    calls.clear()
    L._read_consumed_bybit_legs(s, {ETHD, ETHE}, diag)
    assert calls == []

def test_leg_applied_sl_uses_the_floor_only_when_it_is_tighter():
    """MECH-FOLLOWUPS-1105 (a): an account-scoped apply leaves the package SL stale by design; the leg's
    notes.sl_floor is the level its venue stop should hold."""
    tr = {"notes": json.dumps({"sl_floor": {"level": 1.2466357, "source": "live_review_mandate"}})}
    assert L._leg_applied_sl(tr, "short", 1.2711)[0] == 1.2466357
    assert "not moved by design" in L._leg_applied_sl(tr, "short", 1.2711)[1]
    assert L._leg_applied_sl(tr, "long", 1.2000)[0] == 1.2466357          # long: a higher floor is tighter
    assert L._leg_applied_sl(tr, "short", 1.2400) == (1.2400, None)         # floor looser than the package: ignored
    assert L._leg_applied_sl({"notes": "{}"}, "short", 1.2711) == (1.2711, None)
    assert L._leg_applied_sl(None, "short", 1.2711) == (1.2711, None)
    assert L._leg_applied_sl(tr, "short", None) == (None, None)


@needs_gold
def test_ada_venue_stop_at_the_legs_applied_floor_is_a_match_not_a_mismatch():
    g = GOLD[ADA]
    bad = _bybit(["bybit_2"])
    bad["accounts"][0]["result"]["orders"][0]["trigger_price"] = 0.2080     # package sl 0.2109, venue 0.2080
    s = _snap(telemetry={"rows": [_tel(g, "bybit_2")]}, bybit_orders=bad)
    s.packages[ADA] = _pkg(g, "ADAUSDT", "short")
    s.trades = [{"id": 1, "account_id": "bybit_2", "symbol": "ADAUSDT", "status": "open", "order_package_id": ADA,
                 "direction": "short", "position_size": 1.0, "entry_price": 1.0, "stop_loss": 0.2080,
                 "notes": json.dumps({"sl_floor": {"level": 0.2080, "source": "live_review_mandate"}})}]
    p = _build(ADA, s)
    assert "venue SL" not in p["mechanics"]["evidence"]


def test_a_synthetic_prop_ticket_row_is_not_an_account(monkeypatch):
    """/api/bot/prop/tickets returns order_package-sourced rows with null ticket_id/account_id; they are not accounts
    (pkg-f76bb92289d143e5 showed a phantom account with a blank exchange: venue_read_unreachable 1/2)."""
    pkg = "pkg-synth"
    s = L.Snapshot()
    s.packages[pkg] = {"order_package_id": pkg, "status": "open", "direction": "short"}
    s.trades = [{"id": 1, "order_package_id": pkg, "account_id": "bybit_1", "status": "open"}]
    s.reads["prop_tickets"] = {"tickets": [
        {"order_package_id": pkg, "ticket_id": None, "account_id": None, "status": "open", "source": "order_package"},
        {"order_package_id": pkg, "ticket_id": "T9", "account_id": "tradeify_1", "status": "filled", "source": "ticket"}]}
    accts = L._accounts_for(L._package_view(s, pkg), {"bybit_1": {"exchange": "bybit", "account_class": "paper"}})
    assert [a["account_id"] for a in accts] == ["bybit_1", "tradeify_1"]       # the real ticket stays; no None entry
    assert all(a["account_id"] for a in accts)


def test_price_returns_a_named_state_when_the_outcomes_stdout_is_not_json(monkeypatch):
    """LR wake 2026-11-06T01:56Z: an exit-0 outcomes run with non-JSON stdout raised out of the builder (could_not_build)."""
    monkeypatch.setattr(L, "LTR_CORPUS_DIR", L.LTR_CORPUS_DIR)
    leg = next(f.stem for f in (REPO / "comms/strategy_evidence").glob("*.json"))

    class _R:
        returncode, stdout, stderr = 0, "[corpus] using fallback\n{}", "warn: x"
    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: _R())
    tel = {"open_r": 0.1, "peak_r": 0.5}
    priced, why = L._price(leg, "long", tel, 2.0, "LR-x", False)
    assert priced is None and "not JSON" in why and "[corpus] using fallback" in why


def test_wake_build_bundle_keeps_the_traceback_frame_not_just_the_exception(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lrw", REPO / "scripts/ops/live_review_wake.py")
    W = importlib.util.module_from_spec(spec)
    sys.modules["lrw"] = W
    spec.loader.exec_module(W)

    class _R:
        returncode = 1
        stdout = ""
        stderr = ("Traceback (most recent call last):\n  File \"scripts/ops/live_review_packet.py\", line 994, in _price\n"
                  "    table = json.loads(out.stdout)\n  File \"json/decoder.py\", line 355, in raw_decode\n"
                  "    raise JSONDecodeError\njson.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)")
    monkeypatch.setattr(W.subprocess, "run", lambda *a, **k: _R())
    out = W.build_bundle("pkg-x")
    assert out["state"] == "could_not_build"
    assert "live_review_packet.py" in out["reason"] and "line 994" in out["reason"] and "column 2" in out["reason"]


def _prop_mech(positions, sl=89.10464286, tp=78.96364, direction="short", status_read=True):
    """LTR-PACKET-READ-REACH 2026-11-11: one prop account (velotrade_1, SOL short, filled ticket) against an
    emitted (live) prop-only package."""
    pkg = "pkg-propcmp"
    s = L.Snapshot()
    if status_read:
        s.reads["prop_status:velotrade_1"] = {"status": {"raw": json.dumps({"positions": positions})}}
    view = {"package": {"order_package_id": pkg, "status": "emitted"}, "trades": [], "telemetry": [], "tickets": []}
    accts = [{"account_id": "velotrade_1", "account_class": "prop", "exchange": "velotrade",
              "ticket": {"order_package_id": pkg, "account_id": "velotrade_1", "status": "filled"}}]
    return L._mechanics(s, view, accts, sl, tp, direction, "SOLUSDT")[0]


def test_prop_venue_tp_off_the_package_is_a_mismatch():
    """The live miss: velotrade_1 SOL TP 76.535 at the venue vs package 78.964 read "match"."""
    m = _prop_mech([{"symbol": "SOLUSDT", "direction": "short", "sl": 89.105, "tp": 76.535}])
    assert m["verdict"] == "mismatch"
    assert "venue TP 76.535 != package TP 78.96364" in m["evidence"]
    assert "venue SL" not in m["evidence"]          # the SL agrees within tolerance


def test_prop_venue_levels_agreeing_is_a_match():
    m = _prop_mech([{"symbol": "SOLUSDT", "direction": "short", "sl": 89.1046, "tp": 78.9636}])
    assert m["verdict"] == "match"


def test_prop_position_without_sl_tp_cells_is_could_not_look_not_match():
    m = _prop_mech([{"symbol": "SOLUSDT", "direction": "short", "qty": 1.0}])
    assert m["verdict"] == "could_not_look"
    assert "venue SL not in the Positions read" in m["evidence"]
    assert "venue TP not in the Positions read" in m["evidence"]


def test_prop_netted_rows_are_not_attributed():
    rows = [{"symbol": "SOLUSDT", "direction": "short", "sl": 89.1, "tp": 78.9}] * 2
    m = _prop_mech(rows)
    assert m["verdict"] == "could_not_look" and "not attributable" in m["evidence"]


def test_no_carrying_account_is_could_not_look_not_a_vacuous_match():
    """LR-20261111T0002Z-pkg-50f5eed272f64197: zero account_bounds, verdict "match" ("agree with every readable
    account" over zero accounts)."""
    s = L.Snapshot()
    view = {"package": {"order_package_id": "pkg-x", "status": "emitted"}, "trades": [], "telemetry": [], "tickets": []}
    m = L._mechanics(s, view, [], 89.1, 78.96, "short", "SOLUSDT")[0]
    assert m["verdict"] == "could_not_look"
    assert "nothing compared" in m["evidence"]


@needs_gold
def test_goldens_are_the_pinned_review_not_a_later_packet():
    """CI-MGC-IB-STOP-TARGET-INTERMITTENT: every golden comes from the review at NOW, whatever later packets for
    the same package sit in the directory (and in whatever order the filesystem lists them)."""
    assert all(g["review_id"].startswith(GOLDEN_REVIEW) for g in GOLD.values()), sorted(g["review_id"] for g in GOLD.values())
    later = [f for f in (REPO / "comms/live_review/packets").glob(f"*-{MGC}.json")
             if not f.name.startswith(GOLDEN_REVIEW)]
    assert later, "the directory no longer holds a later MGC packet; this guard has nothing to guard"
    assert GOLD[MGC]["state"]["sl"] == pytest.approx(4270.02857143)

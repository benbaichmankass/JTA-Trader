"""PNL-GROSS-VS-VENUE-6817: the venue's net closed P&L is ``pnl`` (operator decision w11).

decision: 2026-11-12 operator decisions page w11 "Yes: store the venue's net closed P&L where
trusted"; note "Store the venue's always, it is the single source of truth and if we have a gap
we need to understand why".

Shapes from the 2026-11-12 measurement: bybit_1 trade 6817 (XRPUSDT long 74160, journal gross
-786.096, venue closed_pnl -888.3026); a bybit_2 ml_entry close whose pnl was already the venue
net figure but whose net R was costed twice.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest

from src.runtime import order_monitor as om
from src.runtime import venue_pnl as vp
from src.runtime.net_r_label import _NET_PNL_BASES, net_r_for_trade
from src.units.db.database import _migrate_add_pnl_basis


@pytest.fixture(autouse=True)
def _fresh_read_cache():
    """The cross-tick read cache is module state: every test starts with it empty."""
    om._VENUE_PNL_READ_CACHE.clear()
    yield
    om._VENUE_PNL_READ_CACHE.clear()


def _db(tmp_path):
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, exit_price REAL, pnl REAL, pnl_percent REAL, notes TEXT, "
        "setup_type TEXT, status TEXT, is_backtest INTEGER, created_at TEXT, closed_at TEXT, "
        "sl_order_id TEXT, tp_order_id TEXT, broker_order_id TEXT, fee_taker_usd REAL, "
        "fee_maker_usd REAL, funding_paid_usd REAL, stop_loss REAL)")
    assert _migrate_add_pnl_basis(c.cursor()) is True
    assert _migrate_add_pnl_basis(c.cursor()) is False, "idempotent"
    c.commit()
    c.close()

    class _D:
        def connect(self):
            k = sqlite3.connect(path)
            k.row_factory = sqlite3.Row
            return k
    return _D(), path


def _add(path, **kw):
    now = _dt.datetime.now(_dt.timezone.utc)
    row = dict(id=6817, account_id="bybit_1", symbol="XRPUSDT", direction="long",
               position_size=74160.0, entry_price=1.2582, exit_price=1.2476, pnl=-786.096,
               notes=json.dumps({"exit_price_source": "exchange_fill", "pnl_source": "local_compute"}),
               setup_type="ict_scalp_xrp_15m", status="closed", is_backtest=0,
               created_at=(now - _dt.timedelta(hours=30)).isoformat(),
               closed_at=(now - _dt.timedelta(hours=28)).isoformat(),
               sl_order_id="e043d46b", tp_order_id="9826d97e", broker_order_id=None,
               fee_taker_usd=102.64, fee_maker_usd=None, funding_paid_usd=None, stop_loss=1.2400)
    row.update(kw)
    c = sqlite3.connect(path)
    c.execute(f"INSERT INTO trades ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
              list(row.values()))
    c.commit()
    c.close()
    return row


def _get(path, tid):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone())
    c.close()
    return r, json.loads(r["notes"] or "{}")


CFGS = {"bybit_1": {"account_id": "bybit_1", "exchange": "bybit", "demo": True},
        "bybit_2": {"account_id": "bybit_2", "exchange": "bybit", "demo": False},
        "alpaca_paper": {"account_id": "alpaca_paper", "exchange": "alpaca"}}


def _reader(records, calls=None, state="rows_returned"):
    def read(cfg, *, symbol, start_ms, end_ms):
        if calls is not None:
            calls.append((cfg["account_id"], symbol))
        return {"query_state": state, "records": records}
    return read


def test_demo_row_stores_the_venue_net_figure_and_keeps_ours_beside_it(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path)
    closed_ms = om._isoformat_to_ms(row["closed_at"])
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3026",
           "updated_time": str(closed_ms + 5000)}
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([rec]))
    assert s["venue_net"] == 1
    r, n = _get(path, 6817)
    assert r["pnl"] == pytest.approx(-888.3026)
    assert r["pnl_basis"] == "venue_net"
    # ours: (1.2476 - 1.2582) * 74160 - 102.64 = -888.736
    assert r["pnl_computed"] == pytest.approx(-888.736, abs=1e-3)
    assert r["pnl_gap_usd"] == pytest.approx(-888.3026 + 888.736, abs=1e-3)
    assert not vp.is_gap(r["pnl"], r["pnl_computed"]), "0.43 USD is inside 1% of 888"
    assert n["venue_pnl_match"] == "order_id" and n["pnl_source"] == "bybit_closed_pnl"
    assert n["pnl_source_prior"] == "local_compute"


def test_a_netting_gap_is_recorded_not_reconciled(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path)
    closed_ms = om._isoformat_to_ms(row["closed_at"])
    # venue averaged the entry with a sibling: a much worse closed_pnl than ours
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-1500.0",
           "updated_time": str(closed_ms)}
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([rec]))
    r, _ = _get(path, 6817)
    assert r["pnl"] == -1500.0, "the venue's figure is stored even when it disagrees"
    assert s["gaps"] == 1 and vp.is_gap(r["pnl"], r["pnl_computed"])


def test_qty_time_match_when_no_order_id_and_ambiguity_refuses(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path, sl_order_id=None, tp_order_id=None)
    t = om._isoformat_to_ms(row["closed_at"])
    one = {"order_id": "x1", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3", "updated_time": str(t)}
    assert vp.match_venue_record([one], own_order_ids=[], qty=74160, closed_at_ms=t,
                                 close_side="sell")[1] == "qty_time"
    two = dict(one, order_id="x2")
    assert vp.match_venue_record([one, two], own_order_ids=[], qty=74160, closed_at_ms=t,
                                 close_side="sell") == (None, "ambiguous")
    wrong_side = dict(one, side="Buy")
    assert vp.match_venue_record([wrong_side], own_order_ids=[], qty=74160, closed_at_ms=t,
                                 close_side="sell") == (None, "none")


def test_unmatched_is_retried_then_recorded_after_24h(tmp_path):
    db, path = _db(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc)
    _add(path, id=1, closed_at=(now - _dt.timedelta(hours=2)).isoformat())
    _add(path, id=2, closed_at=(now - _dt.timedelta(hours=30)).isoformat())
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([]))
    assert s["retry"] == 1 and s["unmatched"] == 1
    assert _get(path, 1)[0]["pnl_basis"] is None
    r2, n2 = _get(path, 2)
    assert r2["pnl_basis"] == "venue_unmatched" and r2["pnl"] == -786.096, "nothing invented"


def test_a_failed_read_writes_nothing(tmp_path):
    db, path = _db(tmp_path)
    _add(path)
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=lambda *a, **k: None)
    assert s["retry"] == 1 and _get(path, 6817)[0]["pnl_basis"] is None


def test_alpaca_fill_exit_is_venue_fills_net_and_estimates_are_marked(tmp_path):
    db, path = _db(tmp_path)
    _add(path, id=10, account_id="alpaca_paper", symbol="IWM", direction="long", position_size=2275,
         entry_price=283.68, exit_price=279.450338, pnl=-9622.48, fee_taker_usd=0.0,
         notes=json.dumps({"exit_price_source": "broker_leg_fill"}))
    _add(path, id=11, account_id="alpaca_paper", symbol="SPY", direction="long", position_size=1,
         entry_price=700, exit_price=701, pnl=1.0,
         notes=json.dumps({"exit_price_source": "candle_at_close"}))
    calls = []
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([], calls))
    assert calls == [], "no Bybit read for an Alpaca row"
    assert _get(path, 10)[0]["pnl_basis"] == "venue_fills_net"
    assert _get(path, 11)[0]["pnl_basis"] == "computed_estimate"


def test_net_r_does_not_cost_a_venue_net_row_twice():
    # bybit_2 ml_entry trade 7079: pnl -2.602 is the venue's net figure, taker fee 0.1677 recorded
    base = {"id": 7079, "pnl": -2.602, "fee_taker_usd": 0.16769423, "cost_source": "broker",
            "entry_price": 1.10, "stop_loss": 1.08, "position_size": 100, "contract_value_usd": 1.0}
    old = net_r_for_trade(base)
    new = net_r_for_trade(dict(base, pnl_basis="venue_net"))
    assert new["net_pnl_usd"] == pytest.approx(-2.602)
    assert old["net_pnl_usd"] == pytest.approx(-2.602 - 0.16769423), "unclassified rows unchanged"
    assert net_r_for_trade(dict(base, pnl_basis="computed_estimate"))["net_pnl_usd"] == \
        pytest.approx(old["net_pnl_usd"])


def test_net_bases_agree():
    assert _NET_PNL_BASES == vp.NET_BASES


def test_gap_report_lists_gaps_and_unmatched(tmp_path):
    from scripts.ops.venue_pnl_gaps import find_items
    rows = [
        {"id": 1, "status": "closed", "account_id": "bybit_1", "pnl_basis": "venue_net",
         "pnl": -1500.0, "pnl_computed": -888.7, "pnl_gap_usd": -611.3},
        {"id": 2, "status": "closed", "account_id": "bybit_1", "pnl_basis": "venue_net",
         "pnl": -888.3, "pnl_computed": -888.7, "pnl_gap_usd": 0.4},
        {"id": 3, "status": "closed", "account_id": "bybit_2", "pnl_basis": "venue_unmatched", "pnl": 1.0},
        {"id": 4, "status": "closed", "account_id": "bybit_1", "pnl_basis": None, "pnl": 5.0},
    ]
    out = find_items(rows)
    assert out["n_gap"] == 1 and out["n_unmatched"] == 1 and out["n_classified"] == 3


def test_gap_report_modes_and_check():
    import datetime as dtm
    from scripts.ops.venue_pnl_gaps import select
    now = dtm.datetime.now(dtm.timezone.utc).isoformat()
    rows = [
        {"id": 1, "status": "closed", "account_id": "bybit_1", "account_class": "paper",
         "pnl_basis": "venue_net", "pnl": -1500.0, "pnl_computed": -888.7, "closed_at": now},
        {"id": 2, "status": "closed", "account_id": "bybit_2", "account_class": "real_money",
         "pnl_basis": "venue_net", "pnl": -10.0, "pnl_computed": -2.0, "closed_at": now},
        {"id": 3, "status": "closed", "account_id": "bybit_2", "account_class": "real_money",
         "pnl_basis": "venue_unmatched", "pnl": 1.0, "closed_at": now},
    ]
    real = select(rows, mode="real")
    assert [i["item_id"] for i in real["items"]] == ["VPG-2", "VPG-3"]
    demo = select(rows, mode="demo")
    assert demo["groups"] == {"bybit_1|gap": [1]}
    assert select(rows, mode="demo", account="bybit_portfolio", kind="gap")["items"] == []


def test_gap_report_check_exit_codes(tmp_path):
    from scripts.ops.venue_pnl_gaps import main
    f = tmp_path / "j.json"
    f.write_text(json.dumps([{"id": 1, "status": "closed", "account_id": "bybit_1",
                              "account_class": "paper", "pnl_basis": "venue_net",
                              "pnl": -1500.0, "pnl_computed": -888.7}]))
    assert main(["--journal-json", str(f), "--mode", "demo", "--check"]) == 1
    assert main(["--journal-json", str(f), "--mode", "demo", "--account", "bybit_portfolio",
                 "--check"]) == 0


def test_could_not_look_retries_and_leaves_the_row_untouched(tmp_path):
    # The venue read failed: "we did not look" must never read as "no record".
    db, path = _db(tmp_path)
    _add(path)
    before, _ = _get(path, 6817)
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([], state="could_not_look"))
    assert s["retry"] == 1 and s["venue_net"] == 0 and s["unmatched"] == 0
    r, _ = _get(path, 6817)
    assert r["pnl"] == before["pnl"] and r["pnl_basis"] != "venue_net"


def test_no_rows_is_a_real_answer_not_a_retry_of_the_read(tmp_path):
    # The venue answered with no records: that is "we looked and found nothing",
    # handled by the match step (retry inside the unmatched window, never a venue figure).
    db, path = _db(tmp_path)
    _add(path)
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([], state="no_rows"))
    assert s["venue_net"] == 0
    assert s["retry"] + s["unmatched"] == 1
    r, _ = _get(path, 6817)
    assert r["pnl_basis"] != "venue_net"


def test_the_replaced_figure_is_kept_and_long_close_notes_are_not_cut_to_500(tmp_path):
    """Review of #25270 (2026-11-14): the overwrite kept no trace of the prior pnl, and every classified row's notes were
    re-written with a 500-character cap, cutting the close paths' 2000-capped notes (closed_by, exit sources)."""
    db, path = _db(tmp_path)
    long_notes = {"exit_price_source": "exchange_fill", "pnl_source": "local_compute",
                  "closed_by": "netting_own_leg_fill", "closed_reason": "x" * 1200}
    row = _add(path, notes=json.dumps(long_notes))
    closed_ms = om._isoformat_to_ms(row["closed_at"])
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3026",
           "updated_time": str(closed_ms + 5000)}
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([rec]))
    r, n = _get(path, 6817)
    assert n["pnl_prior"] == pytest.approx(-786.096) and r["pnl"] == pytest.approx(-888.3026)
    assert n["closed_by"] == "netting_own_leg_fill" and n["closed_reason"] == "x" * 1200


def test_a_row_the_sweep_adds_nothing_to_keeps_its_notes_byte_for_byte(tmp_path):
    db, path = _db(tmp_path)
    raw = json.dumps({"exit_price_source": "broker_leg_fill", "closed_reason": "y" * 900}, separators=(",", ":"))
    _add(path, account_id="alpaca_paper", symbol="SPY", notes=raw)
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([]))
    r, _ = _get(path, 6817)
    assert r["pnl_basis"] == "venue_fills_net" and r["notes"] == raw


def test_rows_still_waiting_do_not_starve_the_older_backlog(tmp_path):
    """2026-11-14 17:36Z deploy: the 4 newest unmatched rows re-read their windows every tick and took the
    whole 4-read budget, so older rows sat budget_deferred (8 classified, then none, 87 left). A window read
    within the TTL is served from the last result, so the budget reaches the older rows on the next tick."""
    db, path = _db(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc)
    for i in range(4):          # newest: four different close-hours, no venue record yet (retry)
        _add(path, id=100 + i, sl_order_id=f"none-{i}", tp_order_id=None,
             closed_at=(now - _dt.timedelta(hours=1 + i)).isoformat())
    old = []
    for i in range(2):          # older: their own close order IS in the venue records
        r = _add(path, id=200 + i, sl_order_id=f"own-{i}", tp_order_id=None,
                 closed_at=(now - _dt.timedelta(hours=8 + i)).isoformat())
        old.append(r)
    calls = []

    def read(cfg, *, symbol, start_ms, end_ms):
        calls.append(start_ms)
        recs = []
        for i, r in enumerate(old):
            ms = om._isoformat_to_ms(r["closed_at"])
            if start_ms <= ms <= end_ms:
                recs.append({"order_id": f"own-{i}", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3",
                             "updated_time": str(ms)})
        return {"query_state": "rows_returned" if recs else "no_rows", "records": recs}

    s1 = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=read)
    assert s1["budget_deferred"] >= 1 and all(_get(path, 200 + i)[0]["pnl_basis"] is None for i in range(2))
    s2 = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=read)
    assert all(_get(path, 200 + i)[0]["pnl_basis"] == "venue_net" for i in range(2)), (s1, s2)
    assert all(_get(path, 100 + i)[0]["pnl_basis"] is None for i in range(4))   # still waiting, untouched


def test_a_failed_read_is_never_held_in_the_cache(tmp_path):
    db, path = _db(tmp_path)
    _add(path)
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=lambda *a, **k: None)
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_reader([], state="could_not_look"))
    assert om._VENUE_PNL_READ_CACHE == {}


def _bybit_like_reader(records):
    """Filters on created_time, as /v5/position/closed-pnl does (MEASURED 2026-11-14, record 084e4c9f)."""
    def read(cfg, *, symbol, start_ms, end_ms):
        hits = [r for r in records if start_ms <= int(r["created_time"]) <= end_ms]
        return {"query_state": "rows_returned" if hits else "no_rows", "records": hits}
    return read


def test_a_trade_held_longer_than_the_close_window_is_still_found(tmp_path):
    """Trade 7054: TP order (the closing record) created at ENTRY 11-11 12:02, filled 11-14 16:46. The old
    close-2h..+3h window could never see it; the window now starts before the row's own entry."""
    db, path = _db(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc)
    row = _add(path, created_at=(now - _dt.timedelta(hours=58)).isoformat())   # held 30 h, closed 28 h ago
    opened_ms, closed_ms = om._isoformat_to_ms(row["created_at"]), om._isoformat_to_ms(row["closed_at"])
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-888.3026",
           "avg_entry_price": "1.2582", "avg_exit_price": "1.2476",
           "created_time": str(opened_ms + 60_000), "updated_time": str(closed_ms)}
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_bybit_like_reader([rec]))
    r, n = _get(path, 6817)
    assert r["pnl_basis"] == "venue_net" and r["pnl"] == pytest.approx(-888.3026)
    assert n["venue_avg_entry"] == 1.2582 and n["venue_qty"] == 74160.0
    assert "pnl_gap_reason" not in n                   # inside tolerance: no gap, no reason


def test_gap_reason_netting_vs_entry_fill(tmp_path):
    db, path = _db(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc)
    a = _add(path, id=1)                               # entry 1.2582, venue says position avg 1.30
    _add(path, id=2, sl_order_id="sib-sl", tp_order_id="sib-tp", entry_price=1.40,   # sibling open at the same time
         created_at=(now - _dt.timedelta(hours=40)).isoformat(), closed_at=(now - _dt.timedelta(hours=1)).isoformat(),
         pnl=None)
    b = _add(path, id=3, account_id="bybit_2", sl_order_id="b-sl", tp_order_id="b-tp")  # alone on its account
    recs = [{"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "-3400.0",
             "avg_entry_price": "1.30", "avg_exit_price": "1.2476",
             "created_time": str(om._isoformat_to_ms(a["created_at"])), "updated_time": str(om._isoformat_to_ms(a["closed_at"]))},
            {"order_id": "b-sl", "side": "Sell", "qty": "74160", "closed_pnl": "-1500.0",
             "avg_entry_price": "1.2660", "avg_exit_price": "1.2476",
             "created_time": str(om._isoformat_to_ms(b["created_at"])), "updated_time": str(om._isoformat_to_ms(b["closed_at"]))}]
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_bybit_like_reader(recs))
    assert _get(path, 1)[1]["pnl_gap_reason"] == "netting_position_avg_entry"
    assert _get(path, 3)[1]["pnl_gap_reason"] == "entry_fill_differs"


def test_backfill_adds_gap_notes_to_rows_classified_before_and_never_touches_pnl(tmp_path):
    db, path = _db(tmp_path)
    row = _add(path, pnl=1331.0, pnl_basis="venue_net", pnl_computed=409.73, pnl_gap_usd=921.27,
               notes=json.dumps({"venue_pnl_match": "order_id", "pnl_prior": 421.12}))
    rec = {"order_id": "e043d46b", "side": "Sell", "qty": "74160", "closed_pnl": "1331.0",
           "avg_entry_price": "1.03", "avg_exit_price": "1.2476",
           "created_time": str(om._isoformat_to_ms(row["created_at"])), "updated_time": str(om._isoformat_to_ms(row["closed_at"]))}
    s = om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_bybit_like_reader([rec]))
    r, n = _get(path, 6817)
    assert s.get("backfilled") == 1 and n["venue_avg_entry"] == 1.03 and n["pnl_prior"] == 421.12
    assert n["pnl_gap_reason"] == "entry_fill_differs"
    assert (r["pnl"], r["pnl_computed"], r["pnl_gap_usd"], r["pnl_basis"]) == (1331.0, 409.73, 921.27, "venue_net")
    om._sweep_venue_net_pnl(db, cfgs=CFGS, bybit_reader=_bybit_like_reader([rec]))   # already backfilled: once
    assert _get(path, 6817)[1] == n

"""NETTING-RECONCILER-CLOSE-REASON (2026-11-05).

bybit_1 trade 6886 (pkg-3245fc73e2f64536, trend_donchian_eth_prop ETHUSDT long
14.12, position_model: slices). The venue's own Partial SL b372d2f8 (trigger
2408.18, qty 14.12) FILLED at 2026-11-05T12:27:21Z, avg 2408.02, and Bybit
cancelled its TP 51f83d61 by OCO. The netting reconciler closed the row
``netting_attributed`` at the 1-minute candle 2409.82: it read only that the
tracked SL was no longer resting (``leg_gone``) and never asked the venue which
leg ended the row. These tests pin the fix: a row whose OWN leg filled closes
with that leg's reason at the venue avg price; attribution stays the fallback.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from src.runtime import order_monitor as om

from tests.test_shared_bracket_fix import _ACC, _Clock, _LiveDB, _venue

_FILL_MS = str(int(_dt.datetime(2026, 11, 5, 12, 27, 21,
                                tzinfo=_dt.timezone.utc).timestamp() * 1000))


def _seed(db, *, tid, qty, sl_id, tp_id, strategy, entry=2379.36,
          created="2026-11-04T15:00:32+00:00"):
    c = sqlite3.connect(db.path)
    c.execute(
        "INSERT INTO trades (id,account_id,symbol,direction,position_size,"
        "entry_price,created_at,timestamp,setup_type,strategy_name,sl_order_id,"
        "tp_order_id,status,is_backtest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'open',0)",
        (tid, "bybit_1", "ETHUSDT", "long", qty, entry, created, created,
         strategy, strategy, sl_id, tp_id),
    )
    c.commit()
    c.close()


def _arm(monkeypatch, venue_ref, orders, *, mode="apply", soak=None, cascades=None,
         calls=None):
    om._NETTING_DIVERGENCE_SEEN.clear()
    om._NETTING_OWN_LEG_CACHE.clear()
    monkeypatch.setenv("NETTING_ATTRIBUTION_MODE", mode)
    monkeypatch.delenv("NETTING_ATTRIBUTION_ACCOUNTS", raising=False)
    monkeypatch.setenv("RECONCILER_CLOSE_CONFIRM_SECONDS", "60")
    monkeypatch.setattr("src.bot.data_loaders.list_accounts", lambda: [_ACC])
    monkeypatch.setattr("src.units.accounts.clients.bybit_client_for", lambda acc: object())
    monkeypatch.setattr(om, "_bybit_position_protection", lambda *a, **k: venue_ref[0])
    monkeypatch.setattr(om, "_netting_soak_row",
                        lambda **kw: (soak if soak is not None else []).append(kw))
    monkeypatch.setattr(
        om, "_cascade_close_linked_package",
        lambda db, tid, close_reason=None, caller=None:
            (cascades if cascades is not None else []).append((tid, close_reason)))
    monkeypatch.setattr(om, "is_active_close", lambda *a, **k: False)

    def _status(cfg, oid):
        if calls is not None:
            calls.append(oid)
        return orders.get(oid, {"order_id": oid, "status": "not_found",
                                "filled_qty": 0.0, "avg_price": 0.0,
                                "exec_time": None})

    monkeypatch.setattr("src.units.accounts.clients.account_order_status", _status)

    def _bar(sym, iso, budget=None):
        # collapsed-state: anchored — a test fake of the anchor source; deferred / no_anchor are pinned in tests/test_netting_attribution.py
        return (2409.82, "anchored")

    monkeypatch.setattr("src.runtime.exit_anchor.bar_close_at", _bar)


def _filled(oid, qty, px):
    return {"order_id": oid, "status": "Filled", "filled_qty": qty,
            "avg_price": px, "exec_time": _FILL_MS}


def _run_confirmed(db, clock):
    om._reconcile_netting_partial_closes(db)  # first observation
    clock.tick(61)
    return om._reconcile_netting_partial_closes(db)  # confirmed


# --------------------------------------------------- 1. the 6886 shape
def test_own_sl_fill_closes_as_sl_at_venue_price_not_netting(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=6886, qty=14.12, sl_id="b372d2f8", tp_id="51f83d61",
          strategy="trend_donchian_eth_prop")
    _seed(db, tid=6887, qty=7.0, sl_id="sib-sl", tp_id="sib-tp",
          strategy="other_eth")
    clock = _Clock(monkeypatch)
    cascades = []
    venue = [_venue(7.0, "long", {"sib-sl"})]
    _arm(monkeypatch, venue, {"b372d2f8": _filled("b372d2f8", 14.12, 2408.02),
                              "51f83d61": {"status": "Cancelled"}},
         cascades=cascades)

    s = _run_confirmed(db, clock)

    r = db.row(6886)
    assert r["status"] == "closed"
    assert r["exit_reason"] == "sl"
    assert r["exit_price"] == 2408.02
    assert r["closed_at"].startswith("2026-11-05T12:27:21")
    assert '"exit_price_source": "exchange_fill"' in r["notes"]
    assert '"exit_reason_source": "venue_bracket_order"' in r["notes"]
    assert db.row(6887)["status"] == "open"  # the sibling backs the venue's 7.0
    assert cascades == [(6886, "sl")]
    assert s["closed_own_leg"] == 1 and s["closed"] == 0
    assert (_ACC["account_id"], "ETHUSDT", "long") not in om._NETTING_DIVERGENCE_SEEN


def test_own_tp_fill_closes_as_tp(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=2.0, sl_id="sl-1", tp_id="tp-1", strategy="a")
    clock = _Clock(monkeypatch)
    _arm(monkeypatch, [_venue(0.0, "", set())],
         {"tp-1": _filled("tp-1", 2.0, 2500.5)})
    _run_confirmed(db, clock)
    r = db.row(1)
    assert (r["exit_reason"], r["exit_price"]) == ("tp", 2500.5)


# ------------------------------------------- 2. attribution stays the fallback
def test_no_own_fill_falls_back_to_netting_attribution(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=2.0, sl_id="sl-1", tp_id="tp-1", strategy="a")
    clock = _Clock(monkeypatch)
    _arm(monkeypatch, [_venue(0.0, "", set())],
         {"sl-1": {"status": "Cancelled", "filled_qty": 0, "avg_price": 0},
          "tp-1": {"status": "Cancelled", "filled_qty": 0, "avg_price": 0}})
    s = _run_confirmed(db, clock)
    r = db.row(1)
    assert (r["exit_reason"], r["exit_price"]) == ("netting_attributed", 2409.82)
    assert s["closed"] == 1 and s["closed_own_leg"] == 0


def test_mixed_key_own_leg_row_is_sl_and_residual_is_attributed(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=2.0, sl_id="sl-1", tp_id="tp-1", strategy="a")
    _seed(db, tid=2, qty=3.0, sl_id="sl-2", tp_id="tp-2", strategy="b",
          created="2026-11-04T16:00:00+00:00")
    clock = _Clock(monkeypatch)
    _arm(monkeypatch, [_venue(0.0, "", set())],
         {"sl-1": _filled("sl-1", 2.0, 2408.02)})
    _run_confirmed(db, clock)
    assert db.row(1)["exit_reason"] == "sl"
    assert db.row(2)["exit_reason"] == "netting_attributed"


def test_fill_qty_mismatch_is_not_an_own_leg_fill(tmp_path, monkeypatch):
    """A Filled leg whose qty is not this row's size (>5 % off) is not identity."""
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=2.0, sl_id="sl-1", tp_id="tp-1", strategy="a")
    clock = _Clock(monkeypatch)
    _arm(monkeypatch, [_venue(0.0, "", set())],
         {"sl-1": _filled("sl-1", 1.0, 2408.02)})
    _run_confirmed(db, clock)
    assert db.row(1)["exit_reason"] == "netting_attributed"


def test_row_with_resting_sl_is_never_asked(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=2.0, sl_id="sl-1", tp_id="tp-1", strategy="a")
    _seed(db, tid=2, qty=3.0, sl_id="sl-2", tp_id="tp-2", strategy="b")
    clock = _Clock(monkeypatch)
    calls = []
    _arm(monkeypatch, [_venue(3.0, "long", {"sl-2"})],
         {"sl-1": _filled("sl-1", 2.0, 2408.02)}, calls=calls)
    _run_confirmed(db, clock)
    assert "sl-2" not in calls and "tp-2" not in calls
    assert db.row(2)["status"] == "open"


# ------------------------------------------------------- 3. annotate mode
def test_annotate_mode_records_own_leg_basis_and_writes_nothing(tmp_path, monkeypatch):
    db = _LiveDB(tmp_path / "j.db")
    _seed(db, tid=1, qty=2.0, sl_id="sl-1", tp_id="tp-1", strategy="a")
    clock = _Clock(monkeypatch)
    soak = []
    calls = []
    _arm(monkeypatch, [_venue(0.0, "", set())],
         {"sl-1": _filled("sl-1", 2.0, 2408.02)}, mode="annotate", soak=soak,
         calls=calls)
    _run_confirmed(db, clock)
    assert db.row(1)["status"] == "open"
    assert [k["attribution_basis"] if "attribution_basis" in k else k["basis"]
            for k in soak] == ["own_leg_fill"]
    assert soak[0]["anchor_price"] == 2408.02
    # A positive venue read is cached: re-evaluating the same key next tick
    # does not ask the broker again.
    n = len(calls)
    clock.tick(5)
    om._reconcile_netting_partial_closes(db)
    assert len(calls) == n

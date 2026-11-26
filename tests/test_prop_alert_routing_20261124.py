"""Prop alert noise (operator 2026-11-24): machine-account SL/TP crosses wait a
grace and fire only with no close recorded; routine prop fills/closes go to the
alerts ledger, anomalies to Telegram."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.prop import breakout_notify, prop_sl_tp_alert as mod

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def _pos(account="velotrade_1"):
    return {"key": f"{account}|ETHUSDT|buy", "account_id": account, "symbol": "ETHUSDT",
            "direction": "buy", "sl": 100.0, "tp": 200.0, "entry_price": 150.0}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_state_path", lambda: str(tmp_path / "state.json"))
    monkeypatch.delenv("PROP_SL_TP_ALERT_DISABLED", raising=False)
    box = {"positions": [_pos()], "price": 150.0, "machine": True}
    monkeypatch.setattr(mod, "find_open_prop_positions", lambda now=None: list(box["positions"]))
    monkeypatch.setattr(mod, "_fetch_current_price", lambda sym, st: box["price"])
    monkeypatch.setattr(breakout_notify, "_machine_executed", lambda a: box["machine"])
    sent = []

    def run(now):
        return mod.run_prop_sl_tp_alert(now=now, settings={},
                                        emitter=lambda p, lvl, px: sent.append((p, lvl, px)))
    return box, sent, run


def test_machine_cross_then_close_within_grace_no_alert(env):
    box, sent, run = env
    box["price"] = 99.0                      # SL crossed
    run(T0)
    assert sent == []                        # recorded, not alerted
    box["positions"] = []                    # executor recorded the close
    run(T0 + timedelta(minutes=3))
    run(T0 + timedelta(minutes=30))
    assert sent == []


def test_machine_cross_no_close_after_grace_one_alert(env):
    box, sent, run = env
    box["price"] = 99.0
    run(T0)
    run(T0 + timedelta(minutes=9))
    assert sent == []
    run(T0 + timedelta(minutes=11))
    assert [(s[1], s[2]) for s in sent] == [("sl", 99.0)]
    assert sent[0][0]["missed_close_minutes"] == 11
    run(T0 + timedelta(minutes=20))          # one-shot per level
    assert len(sent) == 1


def test_machine_alert_fires_even_if_price_fetch_fails_after_grace(env):
    box, sent, run = env
    box["price"] = 99.0
    run(T0)
    box["price"] = None
    run(T0 + timedelta(minutes=12))
    assert len(sent) == 1 and sent[0][2] == 99.0


def test_manual_account_alerts_immediately(env):
    box, sent, run = env
    box["machine"] = False
    box["price"] = 99.0
    run(T0)
    assert [(s[1]) for s in sent] == ["sl"]
    assert "missed_close_minutes" not in sent[0][0]


def test_tp_level_has_the_same_grace(env):
    box, sent, run = env
    box["price"] = 201.0
    run(T0)
    assert sent == []
    run(T0 + timedelta(minutes=10))
    assert [s[1] for s in sent] == ["tp"]


def test_kill_switch_still_works(env, monkeypatch):
    box, sent, run = env
    monkeypatch.setenv("PROP_SL_TP_ALERT_DISABLED", "1")
    box["price"] = 99.0
    assert run(T0)["disabled"] is True and sent == []


def test_missed_close_message_says_no_close_recorded():
    msg = breakout_notify.render_sl_tp_alert_message(
        dict(_pos(), missed_close_minutes=11), "sl", 99.0)
    assert "NO CLOSE RECORDED" in msg and "HIT?" not in msg
    assert "HIT?" in breakout_notify.render_sl_tp_alert_message(_pos(), "sl", 99.0)


# ── fill routing ────────────────────────────────────────────────────────────
@pytest.fixture
def route(monkeypatch, tmp_path):
    from src.runtime import alerts_ledger, telegram_channels, telegram_policy

    monkeypatch.setattr(alerts_ledger, "ledger_path", lambda *a, **k: tmp_path / "ledger.jsonl")
    sends, box = [], {"machine": True, "ticket": None}
    monkeypatch.setattr(telegram_channels, "send",
                        lambda kind, text, **k: sends.append((kind, text)) or True)
    monkeypatch.setattr(breakout_notify, "_machine_executed", lambda a: box["machine"])
    monkeypatch.setattr(telegram_policy, "load_policy",
                        lambda *a, **k: {"prop": {"routine_fills": "ledger_only", "fill_late_minutes": 10}})
    from src.prop import prop_journal
    monkeypatch.setattr(prop_journal, "get_ticket", lambda tid: box["ticket"])
    return sends, box, tmp_path / "ledger.jsonl"


def _fill(**kw):
    base = {"account_id": "velotrade_1", "symbol": "ETHUSDT", "direction": "buy", "qty": 0.1,
            "entry_price": 100.0, "status": "open", "ticket_id": "t1",
            "opened_at": "2026-11-24T12:03:00+00:00"}
    base.update(kw)
    return base


def _ledger(path):
    return path.read_text().splitlines() if path.exists() else []


def test_routine_fill_goes_to_ledger_not_telegram(route):
    sends, box, ledger = route
    box["ticket"] = {"signal_time": "2026-11-24T12:00:00+00:00"}
    breakout_notify.emit_prop_fill(_fill(), push=False)
    assert sends == []
    rows = _ledger(ledger)
    assert len(rows) == 1 and "routine_prop_fill" in rows[0]


def test_routine_close_goes_to_ledger(route):
    sends, box, ledger = route
    breakout_notify.emit_prop_fill(_fill(status="closed", exit_price=110.0, pnl=5.0, reason="tp"), push=False)
    assert sends == [] and len(_ledger(ledger)) == 1


def test_late_fill_is_an_anomaly(route):
    sends, box, ledger = route
    box["ticket"] = {"signal_time": "2026-11-24T12:00:00+00:00"}
    breakout_notify.emit_prop_fill(_fill(opened_at="2026-11-24T12:58:00+00:00"), push=False)
    assert [k for k, _ in sends] == ["prop_alert"] and "58 min" in sends[0][1]
    assert _ledger(ledger) == []


def test_close_without_exit_or_pnl_is_an_anomaly(route):
    sends, box, ledger = route
    breakout_notify.emit_prop_fill(_fill(status="closed", exit_price=None, pnl=None), push=False)
    assert [k for k, _ in sends] == ["prop_alert"] and "no exit price / P&L" in sends[0][1]


def test_unknown_ticket_is_not_an_anomaly(route):
    sends, box, ledger = route
    box["ticket"] = None
    breakout_notify.emit_prop_fill(_fill(), push=False)
    assert sends == []


def test_manual_account_fills_still_send_one_by_one(route):
    sends, box, ledger = route
    box["machine"] = False
    breakout_notify.emit_prop_fill(_fill(), push=False)
    assert [k for k, _ in sends] == ["prop_fill"]


def test_unreadable_policy_fails_open(route, monkeypatch):
    sends, box, ledger = route
    from src.runtime import telegram_policy
    monkeypatch.setattr(telegram_policy, "load_policy", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    breakout_notify.emit_prop_fill(_fill(), push=False)
    assert [k for k, _ in sends] == ["prop_fill"]


def test_shipped_policy_enables_the_rule():
    from src.runtime import telegram_policy
    assert telegram_policy.prop_fill_policy() == {"fill_late_minutes": 10.0}


def test_anomaly_and_routine_kinds_route_as_designed():
    from src.runtime import telegram_channels as tc
    assert tc.channel_for("prop_alert") == tc.SYSTEM and "prop_alert" in tc.UNMUTABLE
    assert tc.channel_for("prop_fill") == tc.TRADES


# ── unfilled signal ─────────────────────────────────────────────────────────
def test_machine_ticket_expiring_unfilled_alerts_once(monkeypatch):
    from src.prop import prop_expiry_prompt as pe, prop_reconcile
    now = T0
    t = {"ticket_id": "t9", "account_id": "tradeify_1", "status": "emitted", "symbol": "SOLUSDT",
         "direction": "buy", "valid_until": (now - timedelta(minutes=30)).isoformat()}
    old = dict(t, ticket_id="t8", valid_until=(now - timedelta(hours=9)).isoformat())
    monkeypatch.setattr(prop_reconcile, "find_unacted_tickets", lambda **k: [t, old])
    monkeypatch.setattr(pe, "_flows", lambda: {"tradeify_1": "phone"})
    monkeypatch.setattr(pe, "_expire", lambda tk, why: 1)
    got = []
    st = pe.run_prop_expiry_prompts(now=now, unfilled_emitter=lambda tk: got.append(tk["ticket_id"]))
    assert got == ["t9"] and st["machine_expired"] == 2

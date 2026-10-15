"""TELEGRAM-CHANNELS parts C + content split (operator, 2026-10-11).

Pins: the ONE cadence gate (each choice, per-update independence, persistence,
off, catch-up); muting (alert kinds refused, broken store over-sends); the ONE
menu (render + callbacks); the WORK section buckets; the TRADES snapshot
against a fixture journal (won / lost / unpriced / open, provenance never
folded); the content split (no section on two channels); the 4096 fit.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.runtime import telegram_channels as tc
from src.runtime import telegram_settings as ts

T0 = datetime(2026, 10, 11, 8, 0, 30, tzinfo=timezone.utc)


# ── cadence gate ────────────────────────────────────────────────────────────

def test_defaults_are_todays_behaviour_hourly_and_nothing_muted():
    assert all(ts.cadence(u) == "1h" for u in ts.PERIODIC)
    assert ts.is_due("system_health", T0)[0]
    assert not ts.is_muted("trade_opened")


@pytest.mark.parametrize("choice,due_hours", [
    ("1h", set(range(24))), ("4h", {0, 4, 8, 12, 16, 20}), ("12h", {0, 12}), ("24h", {0}),
    ("off", set())])
def test_each_cadence_choice_fires_on_its_aligned_slots(choice, due_hours):
    ts.set_cadence("trades_snapshot", choice, by="test")
    fired = set()
    for h in range(24):
        now = T0.replace(hour=h)
        due, _ = ts.is_due("trades_snapshot", now)
        if due:
            fired.add(h)
            ts.mark_sent("trades_snapshot", now)
    assert fired == due_hours


def test_a_slot_is_served_once():
    assert ts.is_due("manager_update", T0)[0]
    ts.mark_sent("manager_update", T0)
    assert not ts.is_due("manager_update", T0 + timedelta(minutes=5))[0]


def test_a_missed_slot_is_caught_up_once():
    ts.set_cadence("system_health", "4h", by="test")
    ts.mark_sent("system_health", T0)                                  # 08:00 served
    assert not ts.is_due("system_health", T0.replace(hour=11))[0]
    # 12:00 timer missed (down) — 13:00 is past period + grace: catch up
    assert ts.is_due("system_health", T0.replace(hour=13))[0]


def test_cadence_is_per_update_and_independent():
    ts.set_cadence("system_health", "24h", by="test")
    ts.set_cadence("trades_snapshot", "4h", by="test")
    now = T0.replace(hour=4)
    assert ts.is_due("trades_snapshot", now)[0]
    assert ts.is_due("manager_update", now)[0]           # untouched -> hourly
    ts.mark_sent("system_health", T0.replace(hour=0))
    assert not ts.is_due("system_health", now)[0]


def test_settings_persist_across_a_restart(tmp_path, monkeypatch):
    ts.set_cadence("manager_update", "12h", by="test")
    ts.set_group_muted("trades", "opened", True, by="test")
    import importlib
    importlib.reload(ts)                                 # a fresh process reads the file
    assert ts.cadence("manager_update") == "12h"
    assert ts.is_muted("trade-open") and ts.is_muted("trade_opened")
    raw = json.loads(open(ts._path()).read())
    assert raw["updated_by"] == "test"


def test_window_is_since_last_send_else_one_period():
    ts.set_cadence("trades_snapshot", "4h", by="test")
    assert ts.window_start("trades_snapshot", T0) == T0 - timedelta(hours=4)
    ts.mark_sent("trades_snapshot", T0 - timedelta(hours=4))
    assert ts.window_start("trades_snapshot", T0) == T0 - timedelta(hours=4)


# ── muting ──────────────────────────────────────────────────────────────────

def test_alert_kinds_can_never_be_muted():
    for k in tc.UNMUTABLE:
        with pytest.raises(ValueError):
            ts.set_muted(k, True, by="test")
    # even a hand-edited store cannot silence them
    p = ts._path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"muted": sorted(tc.UNMUTABLE)}))
    assert all(tc.enabled(k) for k in tc.UNMUTABLE)


def test_no_toggle_group_contains_an_alert_kind():
    for ch, groups in ts.TOGGLES.items():
        for _g, (_label, kinds) in groups.items():
            for k in kinds:
                assert k not in tc.UNMUTABLE
                assert tc.EVENT_CHANNEL[k] == ch, (k, ch)


def test_every_periodic_update_routes_to_its_channel():
    for u, (ch, _n) in ts.PERIODIC.items():
        assert tc.channel_for(u) == ch


def test_muting_takes_effect_in_enabled_and_an_unreadable_store_over_sends():
    ts.set_group_muted("manager", "pr_merged", True, by="test")
    assert not tc.enabled("pr_merged")
    ts._path().write_text("{not json")
    assert ts.load()["read_state"] == "unreadable"
    assert tc.enabled("pr_merged")


# ── the ONE menu ────────────────────────────────────────────────────────────

def _buttons(markup):
    return [b for row in markup["inline_keyboard"] for b in row]


@pytest.mark.parametrize("channel", ["system", "trades", "manager"])
def test_menu_renders_cadence_and_types_for_each_channel(channel):
    from src.bot import notification_settings_menu as m

    text, mk = m.render(channel)
    data = [b["callback_data"] for b in _buttons(mk)]
    assert all(len(d.encode()) <= 64 for d in data)       # Telegram's callback cap
    upd = next(u for u, (c, _) in ts.PERIODIC.items() if c == channel)
    for choice in ts.CADENCES:
        assert f"ns:c:{upd}:{choice}" in data
    for g in ts.TOGGLES[channel]:
        assert f"ns:t:{channel}:{g}" in data
    assert "cannot be muted" in text or not any(
        tc.EVENT_CHANNEL.get(k) == channel for k in tc.UNMUTABLE)


def test_menu_callbacks_change_the_store_and_rerender():
    from src.bot import notification_settings_menu as m

    ch, toast = m.apply("ns:c:system_health:4h", by="t")
    assert (ch, ts.cadence("system_health")) == ("system", "4h") and "every 4h" in toast
    _, mk = m.render("system")
    assert any(b["text"] == "• 4h" for b in _buttons(mk))
    ch, toast = m.apply("ns:t:trades:opened", by="t")
    assert ts.is_muted("trade_opened") and toast.endswith("off")
    m.apply("ns:t:trades:opened", by="t")
    assert not ts.is_muted("trade_opened")
    assert m.apply("ns:open:manager", by="t")[0] == "manager"
    for bad in ("ns:c:system_health:7h", "ns:t:trades:alert", "ns:c:nope:1h", "xx:1", "ns:zz:a:b"):
        with pytest.raises(ValueError):
            m.apply(bad, by="t")


def test_every_bot_mounts_the_same_menu():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path, ch in (("src/bot/telegram_query_bot.py", '"system"'),
                     ("src/bot/claude_bridge.py", '"trades"'),
                     ("src/bot/claude_decision_bot.py", '"manager"')):
        src = (root / path).read_text()
        assert "notification_settings_menu import register" in src, path
        assert "_register_settings(app" in src or "_register_settings(application" in src
        assert ch in src


# ── WORK section buckets ────────────────────────────────────────────────────

def _row(state, title="t", **kw):
    return {"state": state, "title": title, "blocked_on": kw.get("blocked_on", []),
            "why": kw.get("why", "—"), "observation": kw.get("observation"),
            "updated_at": kw.get("updated_at")}


def test_work_section_buckets_against_a_fixture():
    from scripts.ops import work_section as w

    prev = {"at": "2026-10-11T07:00:00+00:00",
            "rows": {"A": "in_flight", "B": "landed_unproven", "C": "queued", "D": "queued",
                     "E": "blocked", "F": "queued"},
            "items": {"P1": "queued", "P2": "routed"}}
    snap = {"checklist_state": "read", "pipeline_state": "read",
            "rows": {"A": _row("landed_unproven", "ship A"),
                     "B": _row("done", "B", observation="seen live"),
                     "C": _row("dropped", why="superseded by X"),
                     "D": _row("blocked", blocked_on=["PR #1"]),
                     "E": _row("blocked", blocked_on=["Y"]),
                     "F": _row("in_flight", "doing F"), "G": _row("queued", "next G")},
            "items": {"P1": {"state": "killed", "reason": "duplicate"},
                      "P2": {"state": "done", "reason": "fixed"}}}
    d = w.build(prev=prev, now=T0, snap=snap,
                git={"merged_prs": 3, "reverts": ["Revert \"bad thing\""]})
    b = d["buckets"]
    assert b[w.SHIPPED] == ["A — ship A"]
    assert "B — seen live" in b[w.VERIFIED] and "P2 (pipeline) — fixed" in b[w.VERIFIED]
    assert set(b[w.FAILED]) == {"C (dropped) — superseded by X", "P1 (killed) — duplicate",
                                'revert — Revert "bad thing"'}
    assert b[w.BLOCKED] == ["🆕 D — on PR #1", "E — on Y"]
    assert b[w.UPCOMING][0].startswith("▶ F") and b[w.UPCOMING][1].startswith("· G")
    body = w.render_body(d)
    assert "Merged PRs in window: 3" in body and "of 7 rows" in body


def test_work_section_could_not_look_is_not_nothing_new():
    from scripts.ops import work_section as w

    d = w.build(prev=None, now=T0, git={"merged_prs": None, "reverts": None},
                snap={"rows": {}, "items": {}, "checklist_state": "unreadable (OSError)",
                      "pipeline_state": "read"})
    assert "NOT READ" in w.headline(d)
    assert "could not look" in w.render_body(d)


# ── TRADES snapshot against a fixture journal ───────────────────────────────

def _journal(tmp_path):
    db = tmp_path / "j.db"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE trades (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT,
        direction TEXT, entry_price REAL, exit_price REAL, stop_loss REAL, position_size REAL,
        exit_reason TEXT, pnl REAL, status TEXT, notes TEXT, is_backtest BOOLEAN,
        strategy_name TEXT, account_id TEXT, order_package_id TEXT, closed_at TEXT,
        created_at TEXT, protection_repair_last_at TEXT, protection_repair_last_kind TEXT)""")
    ins = ("INSERT INTO trades (symbol,direction,entry_price,exit_price,stop_loss,position_size,"
           "exit_reason,pnl,status,notes,is_backtest,strategy_name,account_id,closed_at,created_at,"
           "protection_repair_last_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)")
    m = json.dumps({"exit_price_source": "bybit_closed_pnl"})
    t_in, t_old = "2026-10-11T07:30:00+00:00", "2026-10-10T07:30:00+00:00"
    rows = [
        ("BTCUSDT", "long", 100, 110, 95, 1, "tp", 10.0, "closed", m, "trend", "bybit_2", t_in, t_old, None),
        ("ETHUSDT", "short", 100, 104, 102, 1, "sl", -4.0, "closed", m, "fade", "bybit_2", t_in, t_old, None),
        ("SOLUSDT", "long", 10, 9, 8, 1, "reconciler", -1.0, "closed", "{}", "sq", "bybit_1", t_in, t_old, None),
        ("XRPUSDT", "long", 1, None, 0.9, 5, None, None, "open", "{}", "pb", "bybit_1", None, t_in, t_in),
        ("ADAUSDT", "long", 1, None, 0.9, 5, None, None, "rejected", "{}", "pb", "bybit_1", None, t_in, None),
        ("DOGEUSDT", "long", 1, 2, 0.5, 1, "tp", 99.0, "closed", m, "x", "bybit_1", t_old, t_old, None),
    ]
    c.executemany(ins, rows)
    c.execute("""CREATE TABLE prop_fills (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT,
        direction TEXT, pnl REAL, reason TEXT, closed_at TEXT)""")
    c.execute("INSERT INTO prop_fills (account_id,symbol,direction,pnl,reason,closed_at) "
              "VALUES ('velotrade_1','ETHUSD','long',25.0,'tp',?)", (t_in,))
    c.commit()
    c.close()
    return str(db)


def test_trades_snapshot_buckets_and_never_folds_unpriced(tmp_path):
    from src.runtime import trades_snapshot as tsn

    since = T0 - timedelta(hours=1)
    data = tsn.gather(since, T0, db_path=_journal(tmp_path))
    assert data["read_state"] == "read"
    assert len(data["closed"]) == 3 and len(data["open"]) == 1 and len(data["rejects"]) == 1
    head, secs = tsn.build_sections(data, accounts=[])
    # measured: +10 -4 (bybit_2) + 25 prop = +31; the unpriced -1 is NOT summed
    assert "realized +$31.00 measured" in head
    assert "2W/1L/1 unpriced" in head
    body = {s.summary.split(" — ")[0]: s.body for s in secs}
    assert "bybit_1: +$0.00 measured (n=0) · 1 unpriced (not summed)" in body["Realized P&L by account"]
    assert "TOTAL: +$31.00 measured · 1 unpriced, NOT summed" in body["Realized P&L by account"]
    closed = body["Closed"]
    assert "🟢 won trend BTCUSDT long · R +2.00 · +$10.00 · exit tp" in closed
    assert "🔴 lost fade ETHUSDT short" in closed and "exit sl" in closed
    assert "⚪ unpriced sq SOLUSDT long · R — · $ — · exit reconciler" in closed
    assert "velotrade_1: prop ETHUSD long · +$25.00 · exit tp (prop report)" in closed
    assert "DOGE" not in closed                                     # outside the window
    assert "XRPUSDT long @ 1.0 · uPnL — (account not read)" in body["Open positions"]
    assert "REJECTED ADAUSDT" in body["Notable"] and "XRPUSDT" in body["Notable"]


def test_trades_snapshot_uses_broker_unrealised_when_the_account_was_read(tmp_path):
    from src.runtime import trades_snapshot as tsn

    data = tsn.gather(T0 - timedelta(hours=1), T0, db_path=_journal(tmp_path))
    acc = [{"account_id": "bybit_1", "positions": [
        {"symbol": "XRPUSDT", "side": "Buy", "size": 5, "entry_price": 1.0, "unrealised_pnl": 0.75}]}]
    _, secs = tsn.build_sections(data, accounts=acc)
    pos = next(s.body for s in secs if s.summary.startswith("Open positions"))
    assert "uPnL +$0.75" in pos and "account not read" not in pos


def test_trades_snapshot_could_not_look_is_not_no_trades(tmp_path):
    from src.runtime import trades_snapshot as tsn

    data = tsn.gather(T0 - timedelta(hours=1), T0, db_path=str(tmp_path / "missing.db"))
    head, secs = tsn.build_sections(data)
    assert "NOT READ" in head and "NOT 'no trades'" in secs[0].body


# ── content split + 4096 fit ────────────────────────────────────────────────

def _report():
    from src.runtime.hourly_report import READ_OK

    return {
        "now_utc": T0, "since": T0 - timedelta(hours=1),
        "ticks": {"ticks_ok": 4, "ticks_err": 0, "signals_total": 2,
                  "signals_by_strategy": {"trend": 2}, "last_tick_ts": T0.isoformat()},
        "strategies": [{"strategy": "trend", "signals_today": 2, "open_pos": 1, "pnl": 5.0}],
        "outcomes": {"top_errors": []}, "training": {"present": False},
        "trades": {"placed": [], "closed": [], "realized_pnl": 0.0},
        "accounts": [{"account_id": "bybit_2", "balance": 1000.0, "delta_1h": 5.0, "api_ok": True,
                      "read_state": READ_OK, "open_positions": 1}],
        "health": {"overall": "ok", "tick_age_s": 30, "tick_stale": False, "tick_interval_s": 900,
                   "warn_count": 0, "error_count": 0, "critical_count": 0,
                   "checks": [SimpleNamespace(name="heartbeat", status="ok", detail="fresh")]},
    }


def test_health_check_carries_no_performance_and_snapshot_no_health(tmp_path):
    from src.runtime import trades_snapshot as tsn
    from src.runtime.hourly_report import render_system_health

    extras = {"running_sha": "abc1234567", "disk_sha": "abc1234567", "restart_pending": False,
              "alert_ledgers": ["losing_streak"], "wedges_lines": ["Standing close wedges: none"]}
    sys_txt = render_system_health(_report(), extras)
    for perf in ("Strategies (today)", "Trades —", "bal $", "PnL", "$1,000"):
        assert perf not in sys_txt, perf
    for health in ("Health —", "Errors —", "Account reachability", "Deploy &amp; alerts",
                   "Restart pending: no", "losing_streak", "Standing close wedges"):
        assert health in sys_txt, health
    data = tsn.gather(T0 - timedelta(hours=1), T0, db_path=_journal(tmp_path))
    tr_txt = tsn.render(data, since=T0 - timedelta(hours=1), now=T0)
    for health in ("Health —", "Errors —", "Restart pending", "Training", "reachability"):
        assert health not in tr_txt, health


def test_manager_update_no_longer_carries_the_wedge_block():
    """The standing close-wedge block (old 'Work — what changed' tail) moved to SYSTEM."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_wdn_split", root / "scripts/ops/work_digest_now.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from scripts.ops import work_section as w
    work = w.build(prev=None, now=T0, git={"merged_prs": 0, "reverts": []},
                   snap={"rows": {}, "items": {}, "checklist_state": "read", "pipeline_state": "read"})
    msg = mod.compose_update("2026-10-11T08", {"block": "🟢 none", "priority": "normal"},
                             "Standing close wedges: LEGACY", {}, {"error": "x"}, work)
    assert "LEGACY" not in msg and "Work — blocked · didn't work" in msg


def test_every_periodic_update_fits_4096(tmp_path):
    from src.runtime import trades_snapshot as tsn
    from src.runtime.hourly_report import render_system_health
    from scripts.ops import work_section as w

    rep = _report()
    rep["health"]["checks"] = [SimpleNamespace(name=f"c{i}", status="warn", detail="x" * 120)
                               for i in range(80)]
    assert len(render_system_health(rep, {"wedges_lines": ["w" * 100] * 50})) <= 4096
    data = tsn.gather(T0 - timedelta(hours=1), T0, db_path=_journal(tmp_path))
    data["closed"] = data["closed"] * 200
    data["opened"] = data["closed"]
    assert len(tsn.render(data, since=T0 - timedelta(hours=1), now=T0)) <= 4096
    rows = {f"R{i}": _row("queued", "y" * 90) for i in range(300)}
    d = w.build(prev=None, now=T0, git={"merged_prs": 1, "reverts": []},
                snap={"rows": rows, "items": {}, "checklist_state": "read", "pipeline_state": "read"})
    assert len(w.render_body(d)) < 4096

"""TELEGRAM-TRIM (operator 2026-11-04): the one Telegram delivery policy.

Pins: (A) recurring posts are off and no alert kind can be listed as recurring;
(B) the trades channel carries ONE ping per order-package event, classed from
config/accounts.yaml fields (real money + mirror note; paper-portfolio only for
legs real money does not trade; testing paper never); (C) every suppressed
message is recorded; (D) testing-paper rejections are ledger-only. Everything
fails OPEN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.runtime import telegram_channels, telegram_policy as tp

REPO = Path(__file__).resolve().parents[1]

ACCTS = {
    "rm": {"account_class": "real_money", "strategies": ["leg_a", "proxy_leg"]},
    "rm_mirror": {"account_class": "paper", "paper_role": "portfolio",
                  "strategies": ["leg_a", "underlying_leg", "paper_only_leg"]},
    "test_paper": {"account_class": "paper", "strategies": ["leg_a"]},
    "prop1": {"account_class": "prop", "type": "prop", "strategies": ["leg_p"]},
}


@pytest.fixture
def pairs(monkeypatch):
    monkeypatch.setattr(tp, "_mirror_pairs", lambda: {"rm_mirror": "rm"})
    monkeypatch.setattr(tp, "_proxy_underlying",
                        lambda: {"rm_mirror": {"proxy_leg": "underlying_leg"}})


def _pol():
    return tp.load_policy()


# ── the committed policy file ─────────────────────────────────────────────

def test_policy_file_loads_and_names_the_recurring_posts():
    pol = _pol()
    assert set(pol["recurring_off"]) == {
        "system_health", "trades_snapshot", "hourly_report", "daily_heartbeat", "manager_update",
        "pr_merged", "prop_monitor"}
    assert pol["trades"]["testing_paper"] == "suppress"
    assert pol["trades"]["real_money"] == "send" and pol["trades"]["prop"] == "send"
    assert pol["trades"]["unknown_account"] == "send"
    assert pol["rejections"]["testing_paper"] == "ledger_only"


def test_recurring_kinds_are_known_kinds_and_never_alerts():
    raw = yaml.safe_load((REPO / "config/telegram_policy.yaml").read_text())
    for k in raw["recurring_off"]:
        assert k in telegram_channels.EVENT_CHANNEL, k
        assert k not in telegram_channels.UNMUTABLE, k


def test_an_alert_listed_as_recurring_voids_the_list(tmp_path):
    p = tmp_path / "pol.yaml"
    p.write_text("recurring_off: [system_health, alert]\n")
    assert tp.load_policy(p)["recurring_off"] == []


def test_unreadable_policy_sends_everything(tmp_path):
    pol = tp.load_policy(tmp_path / "missing.yaml")
    assert pol == {}
    assert not tp.recurring_off("system_health", pol)
    d = tp.trade_decision("trade-open", account="test_paper", strategy="leg_a", policy=pol,
                          accounts=ACCTS)
    assert d.send


def test_policy_carries_the_operator_quote():
    text = (REPO / "config/telegram_policy.yaml").read_text()
    assert "For each trade package I should get one update" in text
    assert "Gates this adds or changes" in text


# ── account classification: fields, never names ───────────────────────────

def test_account_class_from_fields():
    assert tp.account_class("rm", ACCTS) == tp.REAL_MONEY
    assert tp.account_class("rm_mirror", ACCTS) == tp.PAPER_PORTFOLIO
    assert tp.account_class("test_paper", ACCTS) == tp.TESTING_PAPER
    assert tp.account_class("prop1", ACCTS) == tp.PROP
    assert tp.account_class("nope", ACCTS) == tp.UNKNOWN
    assert tp.account_class(None, ACCTS) == tp.UNKNOWN


def test_live_accounts_yaml_classes():
    """Over every account in config/accounts.yaml: the class is derived from
    account_class / paper_role, and each testing-paper account is paper with no
    portfolio role."""
    accts = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    for name, cfg in accts.items():
        cls = tp.account_class(name)
        ac = cfg.get("account_class")
        if ac == "real_money":
            assert cls == tp.REAL_MONEY, name
        elif ac == "prop":
            assert cls == tp.PROP, name
        elif cfg.get("paper_role") == "portfolio":
            assert cls == tp.PAPER_PORTFOLIO, name
        else:
            assert cls == tp.TESTING_PAPER, name


# ── B. trades decisions ─────────────────────────────────────────────────────

def test_testing_paper_is_suppressed(pairs):
    d = tp.trade_decision("trade-open", account="test_paper", strategy="leg_a",
                          policy=_pol(), accounts=ACCTS)
    assert not d.send and d.reason == "testing_paper_suppressed"


def test_real_money_sends_with_mirror_note(pairs):
    d = tp.trade_decision("trade-open", account="rm", strategy="leg_a", package_id="p1",
                          policy=_pol(), accounts=ACCTS)
    assert d.send and d.note == "real money + mirror (rm_mirror)"


def test_real_money_proxy_leg_notes_the_mirror_underlying(pairs):
    d = tp.trade_decision("trade-open", account="rm", strategy="proxy_leg",
                          policy=_pol(), accounts=ACCTS)
    assert d.send and d.note == "real money + mirror (rm_mirror)"


def test_portfolio_leg_also_on_real_money_is_covered(pairs):
    for leg in ("leg_a", "underlying_leg"):   # direct, and the proxy's underlying
        d = tp.trade_decision("trade-close", account="rm_mirror", strategy=leg,
                              policy=_pol(), accounts=ACCTS)
        assert not d.send and d.reason == "covered_by_real_money_ping", leg


def test_portfolio_only_leg_sends_once(pairs):
    d = tp.trade_decision("trade-open", account="rm_mirror", strategy="paper_only_leg",
                          policy=_pol(), accounts=ACCTS)
    assert d.send and d.note.startswith("paper portfolio only")


def test_prop_sends_as_live(pairs):
    assert tp.trade_decision("trade-open", account="prop1", strategy="leg_p",
                             policy=_pol(), accounts=ACCTS).send


def test_unknown_account_sends(pairs):
    assert tp.trade_decision("trade-update", account="desk-intake", strategy="x",
                             policy=_pol(), accounts=ACCTS).send


def test_high_priority_flag_bypasses_the_filter(pairs):
    d = tp.trade_decision("trade-close", account="test_paper", strategy="orphan_adopt",
                          priority="high", policy=_pol(), accounts=ACCTS)
    assert d.send and d.reason == "priority_bypass"


def test_one_ping_per_package_event_across_paths_and_accounts(pairs, monkeypatch):
    monkeypatch.setattr(tp, "_accounts", lambda path=None: ACCTS)
    kw = dict(strategy="leg_p", package_id="pkg-1", now=1000.0)
    # journal-observer path + enqueue path, two prop accounts' worth
    a = tp.should_send_trade("trade_opened", "x", account="prop1", **kw)
    b = tp.should_send_trade("trade-open", "x", account="prop1", **kw)
    assert a.send and not b.send and b.reason == "duplicate_package_event"
    # a different event on the same package is its own ping
    assert tp.should_send_trade("trade-close", "x", account="prop1", **kw).send


def test_update_bursts_bucket(pairs, monkeypatch):
    monkeypatch.setattr(tp, "_accounts", lambda path=None: ACCTS)
    kw = dict(account="rm", strategy="leg_a", package_id="pkg-2")
    assert tp.should_send_trade("trade-update", "x", now=0.0, **kw).send
    assert not tp.should_send_trade("trade-update", "x", now=60.0, **kw).send
    assert tp.should_send_trade("trade-update", "x", now=11 * 60.0, **kw).send


def test_suppressed_trade_is_recorded(pairs, monkeypatch, tmp_path):
    monkeypatch.setattr(tp, "_accounts", lambda path=None: ACCTS)
    d = tp.should_send_trade("trade-open", "🟢 OPEN body", account="test_paper",
                             strategy="leg_a", symbol="BTCUSDT", package_id="pkg-3")
    assert not d.send
    rows = [json.loads(x) for x in tp.suppressed_log_path().read_text().splitlines()]
    assert rows[-1]["delivered"] == "suppressed_by_policy"
    assert rows[-1]["account"] == "test_paper" and rows[-1]["package_id"] == "pkg-3"
    assert rows[-1]["account_class"] == tp.TESTING_PAPER


def test_claim_store_failure_sends(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("not a dir")
    assert tp.claim("k", directory=blocker / "sub")


# ── D. rejections ──────────────────────────────────────────────────────────

def test_rejection_ledger_only_for_testing_paper_only():
    pol = _pol()
    assert tp.rejection_ledger_only("test_paper", accounts=ACCTS, policy=pol)
    for a in ("rm", "rm_mirror", "prop1", "unknown"):
        assert not tp.rejection_ledger_only(a, accounts=ACCTS, policy=pol), a


# ── wiring: the chokepoints consult the policy ─────────────────────────────

def test_channels_send_records_recurring_instead_of_sending(monkeypatch):
    sent = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setattr(telegram_channels, "route_for",
                        lambda kind: (telegram_channels.SYSTEM, type("R", (), {
                            "token": "t", "chat_id": "c", "deliverable": True,
                            "describe": lambda self: "R"})()))
    assert telegram_channels.send("system_health", "hourly health") is False
    assert sent == []
    rows = [json.loads(x) for x in tp.suppressed_log_path().read_text().splitlines()]
    assert rows[-1]["kind"] == "system_health" and rows[-1]["reason"] == "recurring_off"
    # an alert still goes
    assert telegram_channels.send("alert", "boom") is True and len(sent) == 1


def test_execution_failure_on_testing_paper_is_ledger_only(monkeypatch, tmp_path):
    from src.runtime import execution_diagnostics as ed

    monkeypatch.setattr(ed, "PENDING_PINGS_DIR", tmp_path / "pp")
    monkeypatch.setattr(ed, "OPERATOR_ALERTS_LOG", tmp_path / "oa.jsonl")
    monkeypatch.setattr(tp, "_accounts", lambda path=None: ACCTS)
    assert ed.enqueue_execution_failure(account="test_paper", strategy="s", symbol="X",
                                        side="buy", qty=1, reason="venue said no") is None
    assert not (tmp_path / "pp").exists() or not list((tmp_path / "pp").iterdir())
    row = json.loads((tmp_path / "oa.jsonl").read_text().splitlines()[-1])
    assert row["route"] == "ledger_only" and row["account"] == "test_paper"
    led = json.loads(tp.suppressed_log_path().read_text().splitlines()[-1])
    assert led["kind"] == "execution_alert" and led["delivered"] == "suppressed_by_policy"
    assert led["reason"] == "rejection_testing_paper_ledger_only" and led["account"] == "test_paper"
    assert ed.enqueue_execution_failure(account="rm", strategy="s", symbol="X",
                                        side="buy", qty=1, reason="venue said no") is not None


def test_trade_open_enqueue_honours_policy(monkeypatch, tmp_path, pairs):
    from src.runtime import execution_diagnostics as ed

    monkeypatch.setattr(ed, "PENDING_PINGS_DIR", tmp_path / "pp")
    monkeypatch.setattr(tp, "_accounts", lambda path=None: ACCTS)
    assert ed.enqueue_trade_open(account="test_paper", strategy="leg_a", symbol="X",
                                 side="long", qty=1, package_id="pk") is None
    p = ed.enqueue_trade_open(account="rm", strategy="leg_a", symbol="X", side="long",
                              qty=1, package_id="pk")
    assert p is not None and "real money + mirror (rm_mirror)" in json.loads(p.read_text())["body"]
    # the mirror's own open of the same leg is covered by the real-money ping
    assert ed.enqueue_trade_open(account="rm_mirror", strategy="leg_a", symbol="X",
                                 side="long", qty=1, package_id="pk") is None


def test_producers_pass_the_package_id():
    """Every lifecycle producer that has a package in scope passes it — without
    it the dedupe falls back to a time bucket."""
    ex = (REPO / "src/units/accounts/execute.py").read_text()
    i = ex.index("enqueue_trade_open(\n")
    assert "package_id=pkg_id" in ex[i:i + 1200]
    om = (REPO / "src/runtime/order_monitor.py").read_text()
    assert om.count("package_id=pkg_id") >= 2
    db = (REPO / "src/units/db/database.py").read_text()
    assert db.count('"order_package_id": row["order_package_id"]') == 3


def test_health_snapshot_workflow_pings_only_off_green():
    wf = (REPO / ".github/workflows/health-snapshot.yml").read_text()
    assert "steps.status.outputs.level != 'ok'" in wf


def test_dry_run_report_covers_every_sender_and_marks_recurring_off():
    from scripts.ops import telegram_policy_report as rep

    table = rep.sender_table(tp.load_policy())
    for path, kinds in telegram_channels.SENDERS.items():
        for k in kinds:
            assert any(r.startswith(f"{path} | {k} |") for r in table), (path, k)
    assert all("OFF" in r for r in table if r.split(" | ")[1] in tp.load_policy()["recurring_off"])
    assert not any("OFF" in r for r in table if r.split(" | ")[1] in telegram_channels.UNMUTABLE)


def test_suppressed_rows_land_in_the_alert_ledger_and_never_wake_the_manager():
    """ALERT-LEDGER-TO-MANAGER fold: one event log, delivered=suppressed_by_policy."""
    from src.runtime import alerts_ledger

    assert tp.record_suppressed("system_health", "hourly health", reason="recurring_off")
    tp.record_suppressed("trade-open", "x", reason="testing_paper_suppressed", account="a",
                         package_id="p", priority_hint=None)
    res = alerts_ledger.read()
    rows = res["rows"]
    assert {r["delivered"] for r in rows} == {"suppressed_by_policy"}
    assert {r["channel"] for r in rows} == {"system", "trades"}
    assert rows[-1]["account"] == "a" and rows[-1]["package_id"] == "p"
    assert not any(alerts_ledger.wakes_manager(r) for r in rows)
    # a high-priority kind suppressed still does not wake
    assert not alerts_ledger.wakes_manager(alerts_ledger.build_row(
        "alert", "system", "x", delivered="suppressed_by_policy"))
    assert alerts_ledger.wakes_manager(alerts_ledger.build_row("alert", "system", "x", delivered="telegram_ok"))

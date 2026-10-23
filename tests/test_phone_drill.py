"""The phone REHEARSAL drill (PHONE-EXEC-OBSERVABLE-1018): request / pending / claim / result, the pass streak as the
live sheet-edit gate, the claim timeout, the system-action wiring and the routes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.prop import phone_drill as pd
from src.prop import phone_executor as pe
from src.prop import prop_journal

TOKEN = "t" * 43
OTHER = "u" * 43


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()},
        {"device_id": "p2", "account_id": "breakout_2", "token_sha256": hashlib.sha256(OTHER.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    monkeypatch.setattr(pe, "_bybit_last", lambda sym: None)
    monkeypatch.setenv("DIAG_READ_TOKEN", "diag-secret")
    sent: list = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: sent.append(m) or True)
    return sent


def _dev(tok: str = TOKEN) -> pe.PhoneDevice:
    return pe.authenticate("Bearer " + tok)


def _placed(tid: str = "prop-manual-abc") -> None:
    now = datetime.now(timezone.utc)
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": "breakout_2", "strategy": "trend_donchian_eth_prop", "symbol": "ETHUSDT",
        "direction": "short", "entry": 2405.89, "sl": 2452.65, "tp": 2300.0, "qty": 0.52,
        "valid_until": (now + timedelta(minutes=10)).isoformat(), "status": "placed",
        "meta": {"phone_trail": {"resting_sl": 2431.59}}})


def _result(did: str, ok: bool, run_id: str = "drill-x-20261018T120000Z", failed: str = "sheet"):
    steps = [{"step": "positions_read", "ok": True, "why": "rows=1"}, {"step": failed, "ok": ok, "why": "" if ok else "no sheet"}]
    return {"drill_id": did, "run_id": run_id, "pass": ok, "steps": steps, "captures": 7, "app_version": "1b.270", "exec_js": "2026-10-18.1"}


def test_request_pending_claim_result_and_the_gate(_iso):
    sent = _iso
    assert pd.status("breakout_2")["present"] is False
    assert pd.pending("breakout_2") is None
    assert pd.claim(_dev()) == {"ok": True, "drill": None}
    with pytest.raises(ValueError):
        pd.request_drill("bybit_2")
    r = pd.request_drill("breakout_2", by="phone-drill#1")
    did = r["drill"]["id"]
    assert r["existing"] is False and did.startswith("drill-")
    assert pd.request_drill("breakout_2")["existing"] is True, "idempotent while one is outstanding"
    assert pd.pending("breakout_2")["id"] == did
    _placed()
    c = pd.claim(_dev())
    d = c["drill"]
    assert d["id"] == did and d["symbol"] == "ETHUSDT" and d["venue_symbol"] == "ETHUSD" and d["direction"] == "short"
    assert d["qty"] == 0.52 and d["resting_sl"] == 2431.59 and d["price_step"] == 0.01, "the position the server expects rides the claim"
    assert pd.pending("breakout_2") is None, "a claimed drill no longer waits"
    assert pd.claim(_dev())["drill"] is None, "one attempt per request"
    assert pd.record_result(_dev(OTHER), _result(did, True)) == {"ok": False, "why": "drill was claimed by another device"}
    out = pd.record_result(_dev(), _result(did, True))
    assert out["ok"] is True and out["result"] == "pass" and out["passes"] == 1 and out["sheet_edit"]["enabled"] is False
    assert len(sent) == 1 and "PASS" in sent[0] and "1/3" in sent[0] and "phone_capture?account_id=breakout_2&run_id=drill-x-20261018T120000Z" in sent[0]
    assert "ARMED" not in sent[0]
    assert pd.record_result(_dev(), _result(did, True))["ok"] is False, "a result for a cleared drill is refused"
    st = pd.status("breakout_2")
    assert st["pending"] is None and st["results"][0]["failed_steps"] == [] and st["sheet_edit"] == {"enabled": False, "source": "drills", "passes": 1, "needed": 3}
    # two more passes arm the gate; a fail resets it
    for i in range(2):
        did = pd.request_drill("breakout_2")["drill"]["id"]
        pd.claim(_dev())
        pd.record_result(_dev(), _result(did, True))
    assert pd.sheet_edit("breakout_2")["enabled"] is True and pd.consecutive_passes("breakout_2") == 3
    assert "ARMED" in sent[-1]
    did = pd.request_drill("breakout_2")["drill"]["id"]
    pd.claim(_dev())
    out = pd.record_result(_dev(), _result(did, False, failed="sheet"))
    assert out["result"] == "fail" and out["sheet_edit"]["enabled"] is False and out["passes"] == 0
    assert "FAIL" in sent[-1] and "failed: sheet" in sent[-1] and "live sheet edit off" in sent[-1]
    assert pd.status("breakout_2")["results"][0]["failed_steps"] == ["sheet"]


def test_config_pin_wins_over_the_streak(monkeypatch, tmp_path: Path):
    plat = tmp_path / "platforms.yaml"
    plat.write_text(yaml.safe_dump({"phone_accounts": {"breakout_2": {"platform": "breakout_phone", "sheet_edit": True, "instruments": {}}}}))
    monkeypatch.setattr(pe, "PLATFORMS_PATH", plat)
    assert pd.sheet_edit("breakout_2") == {"enabled": True, "source": "config", "passes": 0}
    cfg = pe.phone_claim_config("breakout_2")
    assert cfg["sheet_edit"] is True and cfg["sheet_edit_source"] == "config"
    plat.write_text(yaml.safe_dump({"phone_accounts": {"breakout_2": {"platform": "breakout_phone", "sheet_edit": False, "instruments": {}}}}))
    assert pd.sheet_edit("breakout_2")["enabled"] is False


def test_claim_config_fails_closed_when_the_gate_cannot_be_read(monkeypatch):
    monkeypatch.setattr(pd, "sheet_edit", lambda a: (_ for _ in ()).throw(OSError("disk")))
    cfg = pe.phone_claim_config("breakout_2")
    assert cfg["sheet_edit"] is False and cfg["sheet_edit_source"] == "error"


def test_claim_timeout_records_unreported_and_resets_the_streak():
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    for _ in range(3):
        did = pd.request_drill("breakout_2", now=now)["drill"]["id"]
        pd.claim(_dev(), now=now)
        pd.record_result(_dev(), _result(did, True), now=now)
    assert pd.consecutive_passes("breakout_2") == 3
    did = pd.request_drill("breakout_2", now=now)["drill"]["id"]
    pd.claim(_dev(), now=now)
    assert pd.expire("breakout_2", now=now + timedelta(minutes=5)) is None, "inside the claim window: nothing"
    row = pd.expire("breakout_2", now=now + timedelta(minutes=11))
    assert row["id"] == did and row["result"] == "unreported"
    assert pd.pending("breakout_2", now=now + timedelta(minutes=12)) is None and pd.consecutive_passes("breakout_2") == 0
    # an unclaimed request older than a day is dropped quietly
    pd.request_drill("breakout_2", now=now)
    assert pd.pending("breakout_2", now=now + timedelta(days=2)) is None and pd.status("breakout_2")["pending"] is None


def test_result_body_is_validated_and_scrubbed():
    did = pd.request_drill("breakout_2")["drill"]["id"]
    pd.claim(_dev())
    with pytest.raises(ValueError):
        pd.record_result(_dev(), {"drill_id": "../x", "pass": True})
    body = _result(did, False)
    body["steps"] = [{"step": "Bad Step!", "ok": "yes", "why": "see https://x.y and 123456789"}, "junk"]
    body["run_id"] = "../../etc"
    out = pd.record_result(_dev(), body)
    r = pd.status("breakout_2")["results"][0]
    assert out["ok"] is True and r["run_id"] is None and r["steps"] == [{"step": "adtep", "ok": None, "why": "see * and *"}]


def test_routes_and_the_system_action_wiring(_iso):
    from src.web.api.main import app
    c = TestClient(app)
    h = {"Authorization": "Bearer " + TOKEN}
    assert c.get("/api/bot/prop/phone/pending", headers=h).json()["drill"] is None
    pd.request_drill("breakout_2")
    p = c.get("/api/bot/prop/phone/pending", headers=h).json()
    assert p["drill"]["id"].startswith("drill-")
    assert c.post("/api/bot/prop/phone/drill/claim", headers={"Authorization": "Bearer " + "x" * 43}).status_code == 401
    d = c.post("/api/bot/prop/phone/drill/claim", headers=h).json()["drill"]
    assert d["id"] == p["drill"]["id"]
    claim = c.post("/api/bot/prop/phone/claim", json={"accepts": ["amend"]}, headers=h).json()
    assert claim["config"]["sheet_edit"] is False and claim["config"]["sheet_edit_source"] == "drills"
    assert c.post("/api/bot/prop/phone/drill/result", json={"drill_id": "bad id", "pass": True}, headers=h).status_code == 400
    r = c.post("/api/bot/prop/phone/drill/result", json=_result(d["id"], True), headers=h).json()
    assert r["ok"] is True and r["passes"] == 1
    assert c.get("/api/diag/phone_drill?account_id=breakout_2").status_code == 401
    st = c.get("/api/diag/phone_drill?account_id=breakout_2", headers={"Authorization": "Bearer diag-secret"}).json()
    assert st["results"][0]["result"] == "pass" and st["passes_to_arm"] == 3
    # the app's own "drill" event is accepted and quiet (the result ping is the one message)
    before = len(_iso)
    e = c.post("/api/bot/prop/phone/event", json={"event": "drill", "reason": "drill-x PASS (12 steps, 9 captures)"}, headers=h).json()
    assert e == {"ok": True, "pinged": False} and len(_iso) == before
    # heartbeat keeps the new keys
    pe._write_heartbeat("breakout_2", "s", {"exec_js": "2026-10-18.1", "exec_src": "remote", "captures": 12, "drill_last": "drill-x PASS", "nope": 1})
    hb = pe.last_heartbeat("breakout_2")["state"]
    assert hb == {"exec_js": "2026-10-18.1", "exec_src": "remote", "captures": 12, "drill_last": "drill-x PASS"}
    root = Path(__file__).resolve().parents[1]
    wf = (root / ".github" / "workflows" / "system-actions.yml").read_text()
    assert "          - phone-drill\n" in wf and 'phone-drill)                        SCRIPT="phone_drill_action.sh" ;;' in wf
    assert "|phone-drill|" in wf, "tier-1 allowlist"
    sh = (root / "scripts" / "ops" / "phone_drill_action.sh").read_text()
    assert "load_runtime_env" in sh and "phone_drill.py" in sh and "--request" in sh
    assert "| `phone-drill` | 1 |" in (root / "docs" / "claude" / "system-actions.md").read_text()


def test_cli_request_and_status(capsys):
    from scripts.prop.phone_drill import main as cli
    assert cli(["--request", "--account", "breakout_2", "--source", "phone-drill#9"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True and out["drill"]["by"] == "phone-drill#9"
    assert cli(["--request", "--account", "bybit_2"]) == 1
    assert cli(["--status", "--account", "breakout_2"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["pending"]["status"] == "requested"


@pytest.fixture
def _test_trade_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A phone account whose bounds allow a test trade on ETHUSDT (MD-EXEC-DEV-TEST-TRADES)."""
    from src.prop import exec_test_trades as et
    plat = tmp_path / "platforms.yaml"
    plat.write_text(yaml.safe_dump({"phone_accounts": {"breakout_2": {"platform": "breakout_phone", "instruments": {
        "ETHUSDT": {"venue": "ETHUSD", "qty_step": 0.01, "price_step": 0.01}}}}}))
    monkeypatch.setattr(pe, "PLATFORMS_PATH", plat)
    acc = tmp_path / "accounts.yaml"
    acc.write_text(yaml.safe_dump({"accounts": {"breakout_2": {"mode": "live"}}}))
    monkeypatch.setattr(pe, "ACCOUNTS_PATH", acc)
    monkeypatch.delenv("PROP_PHONE_MODE_BREAKOUT_2", raising=False)
    monkeypatch.setattr(pe, "_unserved_dry_test_request", lambda acct: None)
    monkeypatch.setattr(pe, "_bybit_last", lambda sym: 2500.0)
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 0.0, "limit_usd": 120.0, "fraction": 0.0, "tripped": False})
    return et


def test_test_trade_drill_writes_the_ticket_at_claim_and_journals_the_close(_iso, _test_trade_env):
    et, sent = _test_trade_env, _iso
    with pytest.raises(ValueError, match="symbol_not_declared"):
        pd.request_drill("breakout_2", test_trade="BTCUSDT")
    assert pd.status("breakout_2")["pending"] is None, "a refused request writes nothing"
    r = pd.request_drill("breakout_2", by="phone-drill#7", test_trade="ethusdt")
    did = r["drill"]["id"]
    assert r["drill"]["test_trade"] == {"symbol": "ETHUSDT", "qty": 0.01}
    assert prop_journal.list_tickets(account_id="breakout_2") == [], "the ticket is written at CLAIM, not at request"
    d = pd.claim(_dev())["drill"]
    tt = d["test_trade"]
    assert tt["ticket_id"].startswith("exec-test-") and tt["symbol"] == "ETHUSDT" and tt["confirm"] is True and tt["qty"] == 0.01
    assert tt["venue_symbol"] == "ETHUSD" and tt["direction"] == "long" and tt["sl"] < tt["entry"] < tt["tp"] and tt["close_by"]
    assert (d["venue_symbol"], d["direction"], d["qty"], d["resting_sl"], d["price_step"]) == ("ETHUSD", "long", 0.01, tt["sl"], 0.01)
    assert prop_journal.get_ticket(tt["ticket_id"])["strategy"] == "exec_test"
    # the phone then claims the entry ticket as any other: served LIVE on a live account
    e = pe.claim_next(_dev())
    assert e["ticket_id"] == tt["ticket_id"] and e["submit"] == "live"
    body = _result(did, True)
    body["test_trade"] = {"ticket_id": tt["ticket_id"], "placed": True, "amended_sl": tt["sl"] + 1, "closed": True,
                          "exit_price": 2506.0, "entry_price": 2505.0}
    out = pd.record_result(_dev(), body)
    assert out["ok"] is True and out["result"] == "pass" and out["test_trade"]["state"] == "closed"
    row = pd.status("breakout_2")["results"][0]
    assert row["test_trade"]["ticket_id"] == tt["ticket_id"] and row["test_trade"]["amended_sl"] == tt["sl"] + 1
    assert prop_journal.get_ticket(tt["ticket_id"])["status"] == "closed"
    fills = prop_journal.list_fills(account_id="breakout_2")
    assert len(fills) == 1 and fills[0]["status"] == "closed" and fills[0]["ticket_id"] == tt["ticket_id"]
    assert et.is_exec_test_fill(fills[0]) and fills[0]["exit_price"] == 2506.0
    assert f"Test trade {tt['ticket_id']}: closed" in sent[-1] and "CLOSE IT BY HAND" not in sent[-1]
    assert et.count_today("breakout_2") == 1
    assert pd.status("breakout_2")["test_trades_overdue"] == []


def test_test_trade_left_open_alerts_once_and_a_refusal_at_claim_is_a_failed_drill(_iso, _test_trade_env, monkeypatch):
    et, sent = _test_trade_env, _iso
    did = pd.request_drill("breakout_2", test_trade="ETHUSDT")["drill"]["id"]
    tt = pd.claim(_dev())["drill"]["test_trade"]
    pe.claim_next(_dev())
    body = _result(did, False, failed="close_click")
    body["test_trade"] = {"ticket_id": tt["ticket_id"], "placed": True, "amended_sl": None, "closed": False}
    out = pd.record_result(_dev(), body)
    assert out["result"] == "fail" and out["test_trade"]["state"] == "OPEN_UNCLOSED"
    assert "CLOSE IT BY HAND" in sent[-1] and "ETHUSDT long 0.01" in sent[-1]
    assert prop_journal.list_fills(account_id="breakout_2") == [], "nothing journaled as closed"
    # a claimed test drill that never reports: the timeout alerts with the ticket id
    now = datetime.now(timezone.utc)
    did2 = pd.request_drill("breakout_2", test_trade="ETHUSDT", now=now)["drill"]["id"]
    tt2 = pd.claim(_dev(), now=now)["drill"]["test_trade"]
    row = pd.expire("breakout_2", now=now + timedelta(minutes=11))
    assert row["id"] == did2 and row["result"] == "unreported" and row["test_trade"]["ticket_id"] == tt2["ticket_id"]
    assert "never reported" in sent[-1] and tt2["ticket_id"] in sent[-1]
    # a bound that moved between request and claim: the drill fails before any ticket is written
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 100.0, "limit_usd": 120.0, "fraction": 100 / 120, "tripped": False})
    with pytest.raises(ValueError, match="day_loss_past_bound"):
        pd.request_drill("breakout_2", test_trade="ETHUSDT")
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": 0.0, "limit_usd": 120.0, "fraction": 0.0, "tripped": False})
    did3 = pd.request_drill("breakout_2", test_trade="ETHUSDT")["drill"]["id"]
    monkeypatch.setattr(et, "_day_loss", lambda a, n: {"loss_usd": None, "limit_usd": None, "fraction": None})
    c = pd.claim(_dev())
    assert c["drill"] is None and c["refused"][0].startswith("day_loss_unreadable")
    r = pd.status("breakout_2")["results"][0]
    assert r["id"] == did3 and r["result"] == "fail" and r["failed_steps"] == ["test_trade_bounds"] and r["test_trade"]["ticket_id"] is None
    assert "refused before any ticket" in sent[-1]
    n_before = len(prop_journal.list_tickets(account_id="breakout_2"))
    assert n_before == 2, "two tickets from the two claimed drills; none from the refusal"
    assert pd.consecutive_passes("breakout_2") == 0


def test_an_unplaced_test_ticket_is_expired_so_the_normal_poll_never_opens_it_later(_iso, _test_trade_env):
    et = _test_trade_env
    did = pd.request_drill("breakout_2", test_trade="ETHUSDT")["drill"]["id"]
    tt = pd.claim(_dev())["drill"]["test_trade"]
    assert prop_journal.get_ticket(tt["ticket_id"])["status"] == "emitted"
    body = _result(did, False, failed="test_ticket_claim")
    body["test_trade"] = {"ticket_id": tt["ticket_id"], "placed": False, "closed": False}
    out = pd.record_result(_dev(), body)
    assert out["test_trade"]["state"].startswith("not_placed")
    assert prop_journal.get_ticket(tt["ticket_id"])["status"] == "expired"
    assert pe.claim_next(_dev()) is None, "nothing left for the entry poll to pick up"
    assert et.count_today("breakout_2") == 0
    # the same for a claimed test drill that never reports
    now = datetime.now(timezone.utc)
    pd.request_drill("breakout_2", test_trade="ETHUSDT", now=now)
    tt2 = pd.claim(_dev(), now=now)["drill"]["test_trade"]
    pd.expire("breakout_2", now=now + timedelta(minutes=11))
    assert prop_journal.get_ticket(tt2["ticket_id"])["status"] == "expired"


def test_test_trade_cli_and_action_wiring(capsys, _test_trade_env):
    from scripts.prop.phone_drill import main as cli
    assert cli(["--request", "--account", "breakout_2", "--test-trade", "BTCUSDT"]) == 1
    assert "symbol_not_declared" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]
    assert cli(["--request", "--account", "breakout_2", "--test-trade", "ETHUSDT"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["drill"]["test_trade"]["symbol"] == "ETHUSDT"
    root = Path(__file__).resolve().parents[1]
    assert "--test-trade" in (root / "scripts" / "ops" / "phone_drill_action.sh").read_text()
    assert "phone-drill symbol" in (root / ".github" / "workflows" / "system-actions.yml").read_text()
    assert "MD-EXEC-DEV-TEST-TRADES" in (root / "docs" / "claude" / "system-actions.md").read_text()

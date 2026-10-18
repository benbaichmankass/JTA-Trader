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

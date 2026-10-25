"""Phone step-capture store (PHONE-EXEC-OBSERVABLE-1018): bounded writes, server-side redaction, the 7-day TTL,
and the routes (per-device POST, diag-token reads)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.prop import phone_captures as pc
from src.prop import phone_executor as pe

TOKEN = "t" * 43
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    monkeypatch.setenv("DIAG_READ_TOKEN", "diag-secret")
    yield


def _body(**over):
    b = {"run_id": "amend-prop-manual-abc-a7-20261018T1300Z", "flow": "amend", "step": "sheet_open", "seq": 3,
         "ok": False, "note": "no sheet after child_entry/native; see https://x.y/z and 123456789",
         "ticket_id": "prop-manual-abc", "app_version": "1b.270", "page": "fg",
         "png_b64": base64.b64encode(PNG).decode(), "png_type": "image/png",
         "dom": {"t": "div", "x": "Position – 7f3a9c", "c": [{"t": "span", "x": "uPnL 20.88 USD"},
                                                             {"t": "a", "a": {"href": "/en/account/A1B2C3/trade"}},
                                                             {"t": "span", "x": "2,461.52"}]}}
    b.update(over)
    return b


def test_store_writes_meta_image_dom_and_scrubs(tmp_path: Path):
    r = pc.store_capture("breakout_2", _body())
    assert r["ok"] is True and r["stored"] is True
    assert r["capture"]["image"] == "003-sheet_open.png" and r["capture"]["dom"] == "003-sheet_open.dom.json"
    assert r["capture"]["ok"] is False, "the step's own result rides the meta, apart from the write's ok"
    run_dir = pc.captures_root() / "breakout_2" / "amend-prop-manual-abc-a7-20261018T1300Z"
    assert str(run_dir).startswith(str(tmp_path)), "captures live beside the journal on the data volume, never in the repo"
    assert (run_dir / "003-sheet_open.png").read_bytes() == PNG
    meta = json.loads((run_dir / "003-sheet_open.json").read_text())
    assert "https" not in meta["note"] and "123456789" not in meta["note"] and meta["ticket_id"] == "prop-manual-abc"
    dom = (run_dir / "003-sheet_open.dom.json").read_text()
    assert "7f3a9c" not in dom and "Position – ID" in dom, "the sheet subtitle's position id is masked server-side"
    assert "20.88 USD" not in dom and "#.## USD" in dom, "a money amount is masked server-side"
    assert "A1B2C3" not in dom and "/account/ACCT" in dom, "the account path segment is masked"
    assert "2,461.52" in dom, "a plain price is kept (the device decides what is money; fixtures replace numbers)"


def test_store_refuses_malformed_bodies():
    for bad in ({"run_id": "../x"}, {"step": "Bad Step"}, {"flow": "other"}, {"seq": "3"}, {"ok": "yes"},
                {"png_b64": "not base64!!"}, {"png_type": "image/gif"},
                {"png_b64": base64.b64encode(b"GIF89a....").decode(), "png_type": "image/png"}):
        with pytest.raises(ValueError):
            pc.store_capture("breakout_2", _body(**bad))
    with pytest.raises(ValueError):
        pc.store_capture("Bad Account", _body())


def test_store_bounds_size_steps_and_runs(monkeypatch):
    with pytest.raises(ValueError):
        pc.store_capture("breakout_2", _body(dom="x" * (pc.MAX_DOM_BYTES + 1)))
    monkeypatch.setattr(pc, "MAX_STEPS_PER_RUN", 2)
    for i in range(2):
        assert pc.store_capture("breakout_2", _body(seq=i, run_id="r-1"))["ok"] is True
    assert pc.store_capture("breakout_2", _body(seq=9, run_id="r-1")) == {"ok": False, "why": "run already holds 2 steps"}
    monkeypatch.setattr(pc, "MAX_RUNS_PER_ACCOUNT", 2)
    pc.store_capture("breakout_2", _body(run_id="r-2"))
    acct = pc.captures_root() / "breakout_2"
    os.utime(acct / "r-1", (1, 1))  # r-1 is the oldest
    assert pc.store_capture("breakout_2", _body(run_id="r-3"))["ok"] is True
    assert sorted(p.name for p in acct.iterdir() if p.is_dir()) == ["r-2", "r-3"], "the oldest run is dropped inside the cap"


def test_purge_removes_runs_older_than_ttl_and_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(pc, "maybe_purge", lambda *a, **k: False)  # the explicit purge is what this test measures
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    pc.store_capture("breakout_2", _body(run_id="old-run"), now=now - timedelta(days=8))
    pc.store_capture("breakout_2", _body(run_id="edge-run"), now=now - timedelta(days=6, hours=23))
    pc.store_capture("breakout_2", _body(run_id="new-run"), now=now)
    out = pc.purge_expired(now=now)
    assert out["removed"] == ["breakout_2/old-run"] and out["kept"] == 2
    assert pc.list_runs("breakout_2")["count"] == 2
    assert pc.purge_expired(now=now + timedelta(days=30))["kept"] == 0


def test_opportunistic_purge_runs_at_most_hourly(monkeypatch):
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    pc.store_capture("breakout_2", _body(run_id="old-run"), now=now - timedelta(days=9))
    marker = pc.captures_root() / ".last_purge"
    assert marker.exists()
    os.utime(marker, (now.timestamp(), now.timestamp()))
    assert pc.maybe_purge("breakout_2", now=now + timedelta(minutes=30)) is False, "within the hour: not re-run"
    assert pc.maybe_purge("breakout_2", now=now + timedelta(hours=2)) is True
    assert pc.list_runs("breakout_2")["count"] == 0


def test_list_get_and_read_file():
    assert pc.list_runs("breakout_2") == {"account_id": "breakout_2", "present": False, "runs": [], "ttl_days": 7}
    pc.store_capture("breakout_2", _body(seq=1, step="positions_tab", ok=True, png_b64=None, dom=None))
    pc.store_capture("breakout_2", _body(seq=2, step="row_target", ok=True))
    pc.store_capture("breakout_2", _body(seq=3, step="sheet_open", ok=False))
    lst = pc.list_runs("breakout_2")
    assert lst["present"] is True and lst["count"] == 1
    s = lst["runs"][0]
    assert (s["flow"], s["steps"], s["failed"], s["images"], s["doms"], s["ticket_id"], s["app_version"]) == \
        ("amend", 3, ["sheet_open"], 2, 2, "prop-manual-abc", "1b.270")
    run = pc.get_run("breakout_2", s["run_id"])
    assert [m["step"] for m in run["steps"]] == ["positions_tab", "row_target", "sheet_open"]
    assert run["steps"][0]["image"] is None and run["steps"][1]["image"] == "002-row_target.png"
    data, ctype = pc.read_file("breakout_2", s["run_id"], "002-row_target.png")
    assert data == PNG and ctype == "image/png"
    _, ctype = pc.read_file("breakout_2", s["run_id"], "003-sheet_open.dom.json")
    assert ctype == "application/json"
    assert pc.read_file("breakout_2", s["run_id"], "999-nope.png") is None
    assert pc.get_run("breakout_2", "no-such-run") is None
    for bad in ("../../etc/passwd", "003-sheet_open.json.bak", "x.png"):
        with pytest.raises(ValueError):
            pc.read_file("breakout_2", s["run_id"], bad)
    assert pc.latest_run_ref("breakout_2")["run_id"] == s["run_id"]
    assert pc.latest_run_ref("nobody") is None


def _client() -> TestClient:
    from src.web.api.main import app
    return TestClient(app)


def test_routes_device_post_and_diag_reads():
    c = _client()
    r = c.post("/api/bot/prop/phone/capture", json=_body(), headers={"Authorization": "Bearer " + TOKEN})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert c.post("/api/bot/prop/phone/capture", json=_body(), headers={"Authorization": "Bearer " + "x" * 43}).status_code == 401
    assert c.post("/api/bot/prop/phone/capture", json=_body(step="Bad"), headers={"Authorization": "Bearer " + TOKEN}).status_code == 400
    assert c.get("/api/diag/phone_captures?account_id=breakout_2").status_code == 401
    h = {"Authorization": "Bearer diag-secret"}
    lst = c.get("/api/diag/phone_captures?account_id=breakout_2", headers=h).json()
    assert lst["present"] is True and lst["runs"][0]["steps"] == 1
    rid = lst["runs"][0]["run_id"]
    run = c.get(f"/api/diag/phone_capture?account_id=breakout_2&run_id={rid}", headers=h).json()
    assert run["steps"][0]["step"] == "sheet_open" and run["steps"][0]["image"] == "003-sheet_open.png"
    f = c.get(f"/api/diag/phone_capture_file?account_id=breakout_2&run_id={rid}&name=003-sheet_open.png", headers=h)
    assert f.status_code == 200 and f.headers["content-type"].startswith("image/png") and f.content == PNG
    assert c.get(f"/api/diag/phone_capture_file?account_id=breakout_2&run_id={rid}&name=../x", headers=h).status_code == 400
    assert c.get(f"/api/diag/phone_capture_file?account_id=breakout_2&run_id={rid}&name=009-x.png", headers=h).status_code == 404
    assert c.get("/api/diag/phone_capture?account_id=breakout_2&run_id=nope", headers=h).status_code == 404
    st = c.get("/api/bot/prop/status?account_id=breakout_2").json()
    assert st["phone_captures_last"]["run_id"] == rid, "/prop/status points at the latest capture run"


def test_capture_post_runs_the_purge_opportunistically(monkeypatch):
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    pc.store_capture("breakout_2", _body(run_id="old-run"), now=now - timedelta(days=60))
    marker = pc.captures_root() / ".last_purge"
    os.utime(marker, (1, 1))  # the last purge was long ago on any clock: the POST (real clock) must run one
    c = _client()
    r = c.post("/api/bot/prop/phone/capture", json=_body(run_id="fresh"), headers={"Authorization": "Bearer " + TOKEN})
    assert r.status_code == 200
    names = sorted(p.name for p in (pc.captures_root() / "breakout_2").iterdir() if p.is_dir())
    assert names == ["fresh"], "the 9-day-old run is purged by the POST path (no timer needed)"


def test_purge_cli_and_timer_unit_are_wired():
    root = Path(__file__).resolve().parents[1]
    svc = (root / "deploy" / "ict-phone-capture-purge.service").read_text()
    tmr = (root / "deploy" / "ict-phone-capture-purge.timer").read_text()
    assert "scripts/ops/phone_capture_purge.sh" in svc and "Type=oneshot" in svc
    assert "Unit=ict-phone-capture-purge.service" in tmr and "OnCalendar=" in tmr
    sh = (root / "scripts" / "ops" / "phone_capture_purge.sh").read_text()
    assert "load_runtime_env" in sh and "phone_capture_purge.py" in sh
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    pc.store_capture("breakout_2", _body(run_id="old-run"), now=now - timedelta(days=9))
    assert pc.main(["--purge"]) == 0
    assert pc.list_runs("breakout_2")["count"] == 0

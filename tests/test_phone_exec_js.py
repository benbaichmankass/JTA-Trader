"""The signed remote exec.js contract (PHONE-EXEC-OBSERVABLE-1018, piece 4): version pin, message, the signature
store, fail-closed serving, the routes and the CI workflow's wiring."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.prop import phone_exec_js as pj
from src.prop import phone_executor as pe

TOKEN = "t" * 43
JS = '(function () {\n  var EXEC_VERSION = "2026-10-18.1";\n  if (window.__ex && window.__ex.version === EXEC_VERSION) return;\n  window.__ex = {version: EXEC_VERSION};\n})();\n'
SIG = base64.b64encode(b"s" * 64).decode()


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "dash-secret")
    monkeypatch.setenv("DIAG_READ_TOKEN", "diag-secret")
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    root = tmp_path / "repo"
    (root / pj.EXEC_JS_REL).parent.mkdir(parents=True)
    (root / pj.EXEC_JS_REL).write_text(JS)
    monkeypatch.setattr("src.utils.paths.repo_root", lambda: str(root))
    return root


def _sha(text: str = JS) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_version_pin_message_and_tree_read(_iso):
    assert pj.version_of(JS) == "2026-10-18.1"
    assert pj.version_of('var EXEC_VERSION = "latest";') == ""
    assert pj.message("2026-10-18.1", "abc") == "metis-exec-js\n2026-10-18.1\nabc"
    t = pj.read_tree()
    assert (t["version"], t["sha256"], t["bytes"]) == ("2026-10-18.1", _sha(), len(JS.encode()))
    (_iso / pj.EXEC_JS_REL).write_text("var x = 1;")
    assert pj.read_tree() is None, "an unpinned script is never served"


def test_bundle_fails_closed_until_the_signature_matches_the_tree(_iso):
    assert pj.bundle() == {"ok": False, "why": "unsigned", "version": "2026-10-18.1"}
    assert pj.status()["served"] is False and pj.status()["signature"] is None
    with pytest.raises(ValueError):
        pj.store_signature({"version": "latest", "sha256": _sha(), "sig": SIG})
    with pytest.raises(ValueError):
        pj.store_signature({"version": "2026-10-18.1", "sha256": "zz", "sig": SIG})
    with pytest.raises(ValueError):
        pj.store_signature({"version": "2026-10-18.1", "sha256": _sha(), "sig": base64.b64encode(b"x" * 10).decode()})
    r = pj.store_signature({"version": "2026-10-18.1", "sha256": "a" * 64, "sig": SIG, "signer": "ci run 1", "commit": "ABC123"})
    assert r["ok"] is True and r["match"] is False and r["stored"]["commit"] == "abc123" and r["note"]
    assert pj.bundle()["why"] == "signature_mismatch", "a signature for other bytes serves nothing"
    r = pj.store_signature({"version": "2026-10-18.1", "sha256": _sha(), "sig": SIG})
    assert r["match"] is True and r["note"] is None
    b = pj.bundle()
    assert (b["ok"], b["version"], b["sha256"], b["sig"], b["js"]) == (True, "2026-10-18.1", _sha(), SIG, JS)
    assert pj.bundle(have="2026-10-18.1") == {"ok": True, "unchanged": True, "version": "2026-10-18.1", "sha256": _sha()}
    assert pj.bundle(have="2026-10-17.9")["js"] == JS
    st = pj.status()
    assert st["served"] is True and "sig" not in st["signature"] and st["signature"]["sha256"] == _sha()
    # the tree moves on (a newer exec.js pulled by git-sync before CI signed it): served = false again
    (_iso / pj.EXEC_JS_REL).write_text(JS.replace("2026-10-18.1", "2026-10-19.1"))
    assert pj.bundle()["why"] == "signature_mismatch" and pj.bundle()["signed_version"] == "2026-10-18.1"
    assert pj.status()["served"] is False


def test_routes(_iso):
    from src.web.api.main import app
    c = TestClient(app)
    dev = {"Authorization": "Bearer " + TOKEN}
    assert c.get("/api/bot/prop/phone/exec.js", headers={"Authorization": "Bearer " + "x" * 43}).status_code == 401
    assert c.get("/api/bot/prop/phone/exec.js", headers=dev).json()["why"] == "unsigned"
    body = {"version": "2026-10-18.1", "sha256": _sha(), "sig": SIG}
    assert c.post("/api/bot/prop/phone/exec-js-signature", json=body).status_code == 401
    assert c.post("/api/bot/prop/phone/exec-js-signature", json=body, headers=dev).status_code == 401, "a device token never publishes a signature"
    r = c.post("/api/bot/prop/phone/exec-js-signature", json=body, headers={"Authorization": "Bearer dash-secret"})
    assert r.status_code == 200 and r.json()["match"] is True
    assert c.post("/api/bot/prop/phone/exec-js-signature", json={"version": "x"}, headers={"Authorization": "Bearer dash-secret"}).status_code == 400
    b = c.get("/api/bot/prop/phone/exec.js?have=2026-10-17.1", headers=dev).json()
    assert b["ok"] is True and b["js"] == JS and b["sig"] == SIG
    assert c.get("/api/bot/prop/phone/exec.js?have=2026-10-18.1", headers=dev).json()["unchanged"] is True
    assert c.get("/api/diag/phone_exec_js").status_code == 401
    st = c.get("/api/diag/phone_exec_js", headers={"Authorization": "Bearer diag-secret"}).json()
    assert st["served"] is True and st["tree"]["version"] == "2026-10-18.1"


def test_unset_dashboard_token_refuses_the_publish(monkeypatch, _iso):
    monkeypatch.delenv("DASHBOARD_API_TOKEN")
    from src.web.api.main import app
    c = TestClient(app)
    r = c.post("/api/bot/prop/phone/exec-js-signature", json={"version": "2026-10-18.1", "sha256": _sha(), "sig": SIG},
               headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503, "never an anonymous signature write"


def test_the_real_exec_js_is_pinned_and_the_workflows_agree():
    root = Path(__file__).resolve().parents[1]
    src = (root / pj.EXEC_JS_REL).read_text()
    if "__ex.snapshot" not in src and "snapshot:" not in src:
        pytest.skip("the version pin lands with the app shell (claude/phone-exec-shell, PR 2); enforced once it merges")
    assert pj.version_of(src), "the bundled exec.js must carry var EXEC_VERSION (RemoteJs / the signer read it)"
    sign = (root / ".github" / "workflows" / "phone-exec-js-sign.yml").read_text()
    for needle in ("PHONE_EXEC_JS_SIGNING_KEY", "openssl genpkey -algorithm ed25519", "pkeyutl -sign", "-rawin",
                   "printf 'metis-exec-js\\n%s\\n%s'", "/api/bot/prop/phone/exec-js-signature", "DASHBOARD_API_TOKEN",
                   "tools/phone-executor/app/src/main/assets/exec.js"):
        assert needle in sign, needle
    apk = (root / ".github" / "workflows" / "phone-executor-apk.yml").read_text()
    assert "exec_pubkey.b64" in apk and "PHONE_EXEC_JS_SIGNING_KEY" in apk and "tail -c 32" in apk
    assert "exec_pubkey.b64" in (root / "tools" / "phone-executor" / ".gitignore").read_text()
    assert "phone-exec-js-sign.yml" in (root / "docs" / "github-actions-workflows.md").read_text()

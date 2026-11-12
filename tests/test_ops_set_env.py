"""OPS-SET-ENV: the direct ops channel's allowlisted env flip (operator 2026-11-12)."""
from src.runtime import ops_actions as ops


def test_phone_kill_switch_validates():
    p, errs = ops._v_set_env({"key": "PROP_PHONE_MODE_BREAKOUT_2", "value": "off",
                              "service": "ict-web-api", "env_file": "shared"})
    assert errs == [] and p["service"] == "ict-web-api.service"


def test_unlisted_key_and_bad_value_refused():
    assert ops._v_set_env({"key": "BYBIT_API_KEY", "value": "x", "service": "none"})[1]
    assert ops._v_set_env({"key": "PROP_PHONE_MODE_BREAKOUT_2", "value": "maybe", "service": "none"})[1]
    assert ops._v_set_env({"key": "PROP_PHONE_MODE_X", "value": "off", "service": "ict-ops-runner"})[1]
    assert ops._v_set_env({"key": "PROP_PHONE_MODE_X", "value": "off", "service": "none", "env_file": "/etc/x"})[1]


def test_registered_and_runner_wired():
    assert ops.REGISTRY["set-env"].tier == 2 and "run_set_env" in ops.RUNNERS


def test_phone_pending_is_quiet_when_kill_switch_off(monkeypatch):
    import asyncio
    from src.prop import phone_executor as pe
    from src.web.api.routers import prop as r
    monkeypatch.setenv("PROP_PHONE_MODE_BREAKOUT_2", "off")
    monkeypatch.setattr(r, "_phone_device", lambda a: type("D", (), {"account_id": "breakout_2"})())
    monkeypatch.setattr(pe, "expire_stale_claims", lambda a: [])
    out = asyncio.run(r.phone_pending(accepts="", authorization="x"))
    assert out == {"ok": True, "pending": 0, "status_age_hours": None, "drill": None, "kill_switch": "off"}

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

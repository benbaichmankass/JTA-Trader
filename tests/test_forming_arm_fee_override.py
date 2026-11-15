"""--fee-bps must reach the forming-arm cost stack (EVIDENCE-FORMING-ARMS-REALMONEY).

as_traded_stage0.py runs decision_bar_holdout.py in a SUBPROCESS, so patching execution_costs in the
parent had no effect and an 11.0 bps rerun silently priced at 7.5.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "research")]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "research" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


vs = _load("vol_skip_forming_bar_replay")
ats = _load("as_traded_stage0")


def test_default_is_unchanged():
    vs.FEE_BPS_OVERRIDE = None
    mod = SimpleNamespace()
    assert vs._set_costs(mod, "SOLUSDT")["fee_bps_roundtrip"] == 7.5 == mod.FEE_BPS_ROUNDTRIP


def test_module_override_takes_effect_and_is_reported():
    vs.FEE_BPS_OVERRIDE = 11.0
    try:
        mod = SimpleNamespace()
        assert vs._set_costs(mod, "SOLUSDT")["fee_bps_roundtrip"] == 11.0 == mod.FEE_BPS_ROUNDTRIP
    finally:
        vs.FEE_BPS_OVERRIDE = None


def test_explicit_argument_beats_module_override_and_zero_is_honoured():
    vs.FEE_BPS_OVERRIDE = 11.0
    try:
        mod = SimpleNamespace()
        assert vs._set_costs(mod, "SOLUSDT", 0.0)["fee_bps_roundtrip"] == 0.0
    finally:
        vs.FEE_BPS_OVERRIDE = None


def test_as_traded_stage0_passes_fee_to_the_subprocess(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        raise RuntimeError("stop after capturing the command")

    monkeypatch.setattr(ats.subprocess, "run", fake_run)
    args = SimpleNamespace(out=str(tmp_path), arms_dir=None, research_unit="u", fetch=False, end=None,
                           leg=["trend_donchian_sol_prop"], fee_bps=11.0)
    try:
        ats.run(args)
    except RuntimeError:
        pass
    cmd = seen["cmd"]
    assert cmd[cmd.index("--fee-bps") + 1] == "11.0"
    args.fee_bps = None
    seen.clear()
    try:
        ats.run(args)
    except RuntimeError:
        pass
    assert "--fee-bps" not in seen["cmd"]

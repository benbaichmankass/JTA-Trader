"""Report-only guards (operator gate decisions, 2026-11-12).

decision: operator 2026-11-12 decisions page, Gates tab — sixteen run_guards
guards: MAKE REPORT-ONLY (record comms/gates/gate_decisions_2026-11-12.json).
They keep running and print their findings as warnings; the job exits 0.
CI-env-gate-guard was KEPT, so it stays blocking.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("run_guards_rm", REPO / "scripts/ci/run_guards.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

REPORT_ONLY = {
    "account-class-guard", "canonical-config-loaders", "cost-model-single-owner",
    "exit-coverage-matrix-guard", "matrix-bracket-values", "matrix-config-agreement",
    "pairs-sizing-basis-guard", "prop-identity-guard", "qty-legalization-guard",
    "risk-basis-agreement", "roster-promotion-evidence-guard", "roster-symbol-reachability",
    "strategy-coverage-guard", "strategy-decision-record", "strategy-risk-guard",
    "tp-venue-cap-single-owner",
}


def test_exactly_the_operator_named_guards_are_report_only():
    got = {g["name"] for g in rg.GUARDS if rg.is_report_only(g)}
    assert got == REPORT_ONLY
    # report-only, not deleted: every one is still in the registry
    assert REPORT_ONLY <= {g["name"] for g in rg.GUARDS}


def test_kept_guard_stays_blocking():
    env = [g for g in rg.GUARDS if g["name"] == "env-gate-guard"]
    assert env and not rg.is_report_only(env[0])


def _run(monkeypatch, tmp_path, guards):
    monkeypatch.setattr(rg, "GUARDS", guards)
    monkeypatch.setattr(rg, "arm_register_merge_driver", lambda: None)
    diff = tmp_path / "pr.diff"
    diff.write_text("")
    return rg.main(["--all", "--event-name", "push", "--pr-diff", str(diff)])


FAIL = [sys.executable, "-c", "import sys; print('finding'); sys.exit(1)"]


def test_report_only_failure_exits_zero_and_warns(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, [{"name": "demo-report", "when": None,
                                       "mode": "report", "steps": [FAIL]}])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::warning::demo-report" in out and "REPORT-ONLY" in out


def test_blocking_failure_still_exits_one(monkeypatch, tmp_path):
    rc = _run(monkeypatch, tmp_path, [{"name": "demo-block", "when": None, "steps": [FAIL]}])
    assert rc == 1

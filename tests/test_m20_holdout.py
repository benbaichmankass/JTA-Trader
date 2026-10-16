"""Pre-registered holdout for the m20 sweep (operator decision 2026-10-16, "Holdout re-run").

Planted/clean pairs:
  * LOOKAHEAD: a discovery read that reaches into the held-back span is REFUSED (planted); an
    open-ended read is capped at the boundary and walk-forward folds are clipped (clean).
  * NOISE vs REAL: over many seeds, a leg whose cells are pure noise rarely confirms on the
    holdout (planted noise -> not_replicated), while a leg with a real per-trade effect confirms
    (clean). Selection uses the sweep's own Path A gate (`beats`) on the discovery span only.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import m20_fleet_exit_sweep as sweep
from m20_holdout import (
    HoldoutGuard,
    HoldoutLeak,
    confirm_cells,
    leg_confirmation,
    plan_holdout,
)


def _stamps(n, start_year=2018):
    return [f"{start_year + i * 8 // n}-{(i % 12) + 1:02d}-15T00:00:00" for i in range(n)]


# ── boundary placement ──────────────────────────────────────────────────────────────────────────
def test_plan_uses_share_then_grows_to_floor_then_caps():
    p = plan_holdout(_stamps(200), 0.25, 25)
    assert p["state"] == "ok" and p["holdout_trades_planned"] >= 50
    p = plan_holdout(_stamps(74), 0.25, 25)            # 25% = 18.5 < floor -> grows to 25 (~34%)
    assert p["state"] == "ok" and p["holdout_trades_planned"] >= 25 and p["share_used"] <= 0.40
    p = plan_holdout(_stamps(50), 0.25, 25)            # floor needs 50% > 40% cap -> underpowered
    assert p["state"] == "underpowered" and p["share_used"] <= 0.40 + 1e-9
    assert plan_holdout([], 0.25, 25)["boundary"] is None


# ── lookahead guard: planted / clean ────────────────────────────────────────────────────────────
def test_planted_lookahead_read_is_refused_by_run_cell(monkeypatch):
    called = []
    monkeypatch.setattr(sweep.subprocess, "run", lambda *a, **k: called.append(a) or None)
    monkeypatch.setattr(sweep, "_HOLDOUT", HoldoutGuard())   # main() installs it under --holdout-frac
    sweep._HOLDOUT.begin("2025-01-01")
    try:
        with pytest.raises(HoldoutLeak):
            sweep.run_cell("h.py", ["--x"], start="2024-01-01", end="2026-01-01")   # ends past boundary
        with pytest.raises(HoldoutLeak):
            sweep.run_cell("h.py", ["--x"], start="2025-03-01")                    # starts inside it
    finally:
        sweep._HOLDOUT.end()
    assert called == []   # refused BEFORE any harness ran


def test_clean_discovery_reads_are_capped_and_folds_clipped(monkeypatch):
    seen = []

    def fake_run_cell(harness, args, start=None, end=None):
        s, e = sweep._HOLDOUT.window(start, end)
        seen.append((s, e))
        return {"net_total_r": 1.0, "max_drawdown_r": 1.0, "total_trades": 30}

    monkeypatch.setattr(sweep, "run_cell", fake_run_cell)
    monkeypatch.setattr(sweep, "_HOLDOUT", HoldoutGuard())
    sweep._HOLDOUT.begin("2024-06-01")
    try:
        g = HoldoutGuard()
        g.begin("2024-06-01")
        assert g.window("2023-01-01", None) == ("2023-01-01", "2024-05-31")   # open end -> day before boundary
        with pytest.raises(HoldoutLeak):
            g.window("2023-01-01", "2024-06-01")                              # the boundary day itself is held back
        wf = sweep.walkforward("h.py", ["--b"], ["--c"], lambda r: None, "leg", "cell", require_dd=True)
    finally:
        sweep._HOLDOUT.end()
    assert all(e is None or e <= "2024-05-31" for _s, e in seen)
    assert any(f.get("why") == "held_back_for_holdout" for f in wf["folds"])
    assert not sweep._HOLDOUT.active


def test_confirm_phase_refuses_a_read_before_the_boundary():
    g = HoldoutGuard()
    g.begin("2024-06-01")
    g.confirm()
    with pytest.raises(HoldoutLeak):
        g.window("2023-01-01", None)
    assert g.window("2024-06-01", None) == ("2024-06-01", None)


# ── noise fails the holdout, a real effect passes ───────────────────────────────────────────────
def _book(rs):
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"net_total_r": round(eq, 6), "max_drawdown_r": round(dd, 6), "total_trades": len(rs)}


def _leg(seed, effect, n_cells=12, n=240):
    rng = random.Random(seed)
    dates = [f"{2016 + i * 9 // n}-{(i * 7) % 12 + 1:02d}-{(i * 3) % 27 + 1:02d}" for i in range(n)]
    dates.sort()
    base = [rng.gauss(0.05, 1.0) for _ in range(n)]
    cells = {}
    for c in range(n_cells):
        # every cell perturbs exits: noise only, or noise + a real per-trade improvement (cell 0)
        bump = effect if c == 0 else 0.0
        cells[f"c{c}"] = [b + rng.gauss(0, 0.25) + bump for b in base]
    return dates, base, cells


def _run(dates, series, start=None, end=None):
    return _book([r for d, r in zip(dates, series) if (not start or d >= start) and (not end or d < end)])


def _one_leg(seed, effect):
    dates, base, cells = _leg(seed, effect)
    plan = plan_holdout(dates, 0.25, 25)
    b = plan["boundary"]
    disc = [d for d in dates if d < b]
    split = disc[len(disc) // 2]
    selected = []
    for tag, s in cells.items():   # discovery: IS/OOS gate INSIDE the discovery span only
        if sweep.beats(_run(dates, s, end=split), _run(dates, base, end=split)) and \
                sweep.beats(_run(dates, s, split, b), _run(dates, base, split, b)):
            selected.append({"cell": tag, "args": tag})
    conf = confirm_cells(selected, lambda a, start: _run(dates, base if a is None else cells[a], start),
                         sweep.beats, b, 25)
    return leg_confirmation(len(selected), conf["cells"])


def test_noise_leg_mostly_fails_the_holdout_and_real_effect_passes():
    noise = [_one_leg(s, 0.0) for s in range(60)]
    real = [_one_leg(s, 0.35) for s in range(60)]
    noise_discoveries = [v for v in noise if v != "no_discovery"]
    assert len(noise_discoveries) >= 10                     # noise DOES produce single-window passes ...
    noise_confirm = sum(v == "confirmed" for v in noise_discoveries) / len(noise_discoveries)
    real_confirm = sum(v == "confirmed" for v in real) / len(real)
    assert noise_confirm <= 0.5, noise_confirm              # ... which the holdout mostly refuses
    assert real_confirm >= 0.9, real_confirm                # a real effect survives it
    assert real_confirm - noise_confirm >= 0.4


def test_sweep_import_does_not_load_the_holdout_module_and_its_stub_is_inert():
    """The sweep sits in the web-api brief's in-process closure: m20_holdout must load only under
    --holdout-frac (tests/test_deploy_pull_restart_runtime_gate.py)."""
    import subprocess
    code = ("import sys; sys.path.insert(0, 'scripts/research'); "
            "import m20_fleet_exit_sweep as m; print('m20_holdout' in sys.modules, m._HOLDOUT.active)")
    out = subprocess.run([sys.executable, "-c", code],
                         cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["False", "False"], out.stdout + out.stderr


def test_confirmation_states():
    assert leg_confirmation(0, []) == "no_discovery"
    assert leg_confirmation(2, [{"holdout_verdict": "holdout_fail"}, {"holdout_verdict": "holdout_pass"}]) == "confirmed"
    assert leg_confirmation(1, [{"holdout_verdict": "holdout_fail"}]) == "not_replicated"
    assert leg_confirmation(1, [{"holdout_verdict": "holdout_underpowered"}]) == "underpowered"

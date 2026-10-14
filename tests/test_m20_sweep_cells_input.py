"""GEOM-CELLS-INPUT: a `cells=<json>` run evaluates EXACTLY those cells.

The census-keyed unit (RQ-20261014-9807-04) needs giveback / trail-decay cells
keyed to each leg's own measured distribution. The fixed grid cannot express
them, so `--cells` replaces it; empty must leave today's grid untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import m20_fleet_exit_sweep as sweep  # noqa: E402

LEG = "xrp_pullback_2h"
CELLS = [
    {"leg": LEG, "lever": "giveback_stop", "tag": "gb_p25",
     "params": {"giveback_r": 0.6, "giveback_min_mfe_r": 1.0}},
    {"leg": LEG, "lever": "trail_decay", "tag": "decay_stall7",
     "params": {"trail_decay_stall_bars": 7, "trail_decay_tight_mult": 2.0}},
]


def _plan_cells(monkeypatch, capsys, *extra):
    monkeypatch.setattr(sweep, "resolve_data",
                        lambda sym, tf, d: ("x.csv", False, None))
    rc = sweep.main(["sweep", "--list", "--only", LEG, *extra])
    out = capsys.readouterr().out
    return rc, out


def _listed_tags(out: str) -> list[str]:
    line = next(ln for ln in out.splitlines() if ln.strip().startswith("RUN"))
    return eval(line.split("cells=", 1)[1])


def test_cells_run_exactly_those_cells(monkeypatch, capsys):
    rc, out = _plan_cells(monkeypatch, capsys, "--cells", json.dumps(CELLS))
    assert rc == 0, out
    assert _listed_tags(out) == ["gb_p25", "decay_stall7"]


def test_empty_cells_keeps_the_full_grid(monkeypatch, capsys):
    rc0, out0 = _plan_cells(monkeypatch, capsys)
    rc1, out1 = _plan_cells(monkeypatch, capsys, "--cells", "")
    assert rc0 == rc1 == 0
    assert out0 == out1
    assert len(_listed_tags(out0)) > 2


def test_args_are_the_declared_flags():
    got = sweep.explicit_cells_for(sweep.parse_cells_spec(
        json.dumps(CELLS), {LEG}), LEG, "pullback")
    assert got[0] == ("gb_p25", "giveback_stop",
                      ["--giveback-r", "0.6", "--giveback-min-mfe-r", "1"])
    assert got[1][2] == ["--trail-decay-stall-bars", "7",
                         "--trail-decay-tight-mult", "2"]


@pytest.mark.parametrize("bad", [
    [{"leg": "no_such_leg", "lever": "giveback_stop", "tag": "t",
      "params": {"giveback_r": 1}}],
    [{"leg": LEG, "lever": "no_such_lever", "tag": "t", "params": {"x": 1}}],
    [{"leg": LEG, "lever": "giveback_stop", "tag": "t", "params": {"bogus": 1}}],
    [{"leg": LEG, "lever": "giveback_stop", "tag": "t", "params": {}}],
    [{"leg": LEG, "lever": "giveback_stop", "tag": "t",
      "params": {"giveback_r": "0.5"}}],
    {"not": "a list"},
])
def test_unknown_or_malformed_is_refused(bad, monkeypatch, capsys):
    rc, out = _plan_cells(monkeypatch, capsys, "--cells", json.dumps(bad))
    assert rc == 2
    assert "--cells refused" in out


def test_invalid_json_and_lever_off_combo_refused(monkeypatch, capsys):
    rc, _ = _plan_cells(monkeypatch, capsys, "--cells", "{nope")
    assert rc == 2
    rc, out = _plan_cells(monkeypatch, capsys, "--cells", json.dumps(CELLS),
                          "--without-declared-lever", "stale_stop")
    assert rc == 2 and "cannot be combined" in out


def test_trail_decay_refused_on_a_family_without_the_lever():
    spec = sweep.parse_cells_spec(json.dumps(
        [{"lever": "trail_decay", "tag": "d",
          "params": {"trail_decay_arm_r": 2}}]), {LEG})
    with pytest.raises(ValueError, match="not carried"):
        sweep.explicit_cells_for(spec, "some_leg", "scalp")


def test_workflow_declares_and_forwards_cells():
    text = (REPO / ".github/workflows/m20-exit-lever-sweep.yml").read_text()
    doc = yaml.safe_load(text)
    on = doc.get("on", doc.get(True))
    assert "cells" in on["workflow_dispatch"]["inputs"]
    assert '--cells "${CELLS}"' in text
    assert "parse_cells_spec" in text

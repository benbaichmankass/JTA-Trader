"""scripts/research/runnable_hours.py: the runnable-hours-per-backend measurement (row COMPUTE-IDLE-TRAINER-GPU-W48)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
_spec = importlib.util.spec_from_file_location("runnable_hours", REPO / "scripts" / "research" / "runnable_hours.py")
rh = importlib.util.module_from_spec(_spec)
sys.modules["runnable_hours"] = rh
_spec.loader.exec_module(rh)


def _unit(tmp_path: Path, uid: str, **kw) -> None:
    d = {"id": uid, "status": "queued", "cadence": "once", "compute": "needs_vm_data",
         "routing": {"needs_trainer_resident_data": True, "needs_gpu": False, "peak_memory_gb": 2.0, "est_minutes": 30},
         "run": {"command": ["python3", "x.py"], "workflow": "research-script-run-trainer.yml"}}
    d.update(kw)
    (tmp_path / f"{uid}.yaml").write_text(yaml.safe_dump(d))


def test_counted_population():
    assert rh.counted({"status": "queued", "cadence": "once"})
    assert rh.counted({"status": "queued"})
    assert not rh.counted({"status": "done", "cadence": "once"})
    assert not rh.counted({"status": "queued", "cadence": "weekly"})
    assert not rh.counted({"status": "queued", "cadence": "once", "blocked_on": ["x"]})
    assert not rh.counted({"status": "queued", "cadence": "once", "result": {"v": 1}})


def test_measure_sums_hours_per_first_choice_backend(tmp_path):
    _unit(tmp_path, "RQ-T-1")                                    # 30 min on the trainer
    _unit(tmp_path, "RQ-T-2", routing={"needs_trainer_resident_data": True, "est_minutes": 90})
    _unit(tmp_path, "RQ-DONE", status="done")                    # not counted
    _unit(tmp_path, "RQ-WEEKLY", cadence="weekly")               # not counted
    m = rh.measure(tmp_path)
    assert m["units_read"] == 4
    assert m["unplaced"] == [] and m["unreadable"] == []
    assert sum(v["units"] for v in m["backends"].values()) == 2
    assert round(sum(v["est_hours"] for v in m["backends"].values()), 1) == 2.0   # 0.5 + 1.5


def test_an_unplaceable_unit_is_counted_not_dropped(tmp_path):
    _unit(tmp_path, "RQ-BAD", compute=None, run={"command": ["python3", "x.py"]})   # no workflow, no compute
    m = rh.measure(tmp_path)
    assert [u["id"] for u in m["unplaced"]] == ["RQ-BAD"]
    assert m["backends"] == {}


def test_an_unreadable_unit_is_counted_not_dropped(tmp_path):
    (tmp_path / "RQ-BROKEN.yaml").write_text("id: [unterminated\n")
    m = rh.measure(tmp_path)
    assert len(m["unreadable"]) == 1 and m["units_read"] == 0


def test_render_and_exit_code_zero(tmp_path, capsys):
    _unit(tmp_path, "RQ-T-1")
    assert rh.main(["--queue-dir", str(tmp_path), "--target-hours", "336"]) == 0
    out = capsys.readouterr().out
    assert "runnable hours per backend" in out and "gap to 336 h" in out

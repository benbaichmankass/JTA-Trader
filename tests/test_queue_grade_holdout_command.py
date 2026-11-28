"""queue_grade COMMAND-LEVEL holdout (RESEARCH-UNBLOCK-BUILDS-W48, 2026-11-25).

A roster-walkforward `exit_lever_ablation.py --grade sweep` PASS on research-script-run.yml used to open a
forward-wait confirmation `blocked` (no window input on the generic runner). Planted/clean pairs:
  * a sweep PASS opens a holdout RE-RUN (`--grade sweep_holdout`, dispatches now), not a blocked unit;
    a non-sweep grade or another script keeps the old forward-wait path;
  * an already-blocked forward-wait confirmation is re-armed: the re-run is opened and the blocked unit
    retired as superseded, in ONE grade, only while the parent's latest grade is a PASS;
  * --verify reproduces the re-arm (the M retirement and the A re-run).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from scripts.research import queue_grade as qg

PID = "RQ-20300101-001"
CMD = ["python3", "scripts/research/exit_lever_ablation.py", "--leg", "leg_x", "--arm", "A=", "--arm",
       "x_hi=x=2", "--days", "1830", "--grade", "sweep", "--baseline", "A", "--delta-r", "4.0", "--folds", "4",
       "--fold-majority", "3", "--n-floor", "39", "--out", "{out_dir}"]


def _parent(cmd=None, verdict=None):
    u = {"id": PID, "title": "Walk-forward lever sweep of leg_x: next lever entry (generated, weekly)",
         "status": "queued", "cadence": "weekly", "kind": "experiment", "theme": "live_strategy", "priority": 2,
         "roadmap": ["L-LADDER"], "question": "Does a lever setting beat the configured one?",
         "power": {"expected_n": 39},
         "decision_rule": {"id": "RULE-X", "statistic": "sweep", "rule": "PASS iff ...", "registered_at": "2030-01-01",
                           "registered_before_run": True},
         "run": {"workflow": "research-script-run.yml", "command": list(cmd or CMD), "timeout_minutes": 60,
                 "inputs": {"research_unit": PID}},
         "lands": {"store": "research/results/", "min_rows": 1},
         "generated": {"family": "roster-walkforward", "key": "roster-walkforward:leg=leg_x,lever_key=entry"},
         "last_dispatched_at": "2030-01-01T00:00:00+00:00"}
    if verdict:
        u["grading"] = {"auto": True, "verdict": verdict, "graded_at": "2030-01-01"}
    return yaml.safe_dump(u, sort_keys=False)


def _rows(r: Path, uid: str, verdict: str):
    d = r / "research" / "results" / uid
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.jsonl").write_text(json.dumps({"verdict": verdict, "read_state": "measured",
                                           "generated_at": "2030-01-01T06:00:00Z", "measurement": {}}) + "\n")


def _repo(tmp_path):
    (tmp_path / "research" / "queue").mkdir(parents=True)
    return tmp_path


def test_holdout_command_rewrites_only_a_sweep_on_the_generic_runner():
    hc, frac = qg.holdout_command({"workflow": "research-script-run.yml", "command": CMD}, "RQ-C")
    assert frac == "0.25" and hc[hc.index("--grade") + 1] == "sweep_holdout"
    assert hc[-4:] == ["--holdout-frac", "0.25", "--research-unit", "RQ-C"]
    assert [t for t in hc if t not in ("sweep_holdout", "--holdout-frac", "0.25", "--research-unit", "RQ-C")] == \
        [t for t in CMD if t != "sweep"]
    other = [t if t != "sweep" else "parity" for t in CMD]
    assert qg.holdout_command({"workflow": "research-script-run.yml", "command": other}, "RQ-C") is None
    assert qg.holdout_command({"workflow": "research-script-run-trainer.yml", "command": CMD}, "RQ-C") is None
    script = ["python3", "scripts/research/leg_corpus_s1.py", "--grade", "sweep"]
    assert qg.holdout_command({"workflow": "research-script-run.yml", "command": script}, "RQ-C") is None
    own = CMD + ["--holdout-frac", "0.3"]
    assert qg.holdout_command({"workflow": "research-script-run.yml", "command": own}, "RQ-C") is None


def test_sweep_pass_opens_a_holdout_rerun_not_a_blocked_unit(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    _p, (cid, ctext) = qg.grade_unit_full(r, PID, _parent(), "2030-01-02")
    cu = yaml.safe_load(ctext)
    assert cu["status"] == "queued" and "not_before" not in cu and "blocked_reason" not in cu
    assert cu["confirmation"]["mode"] == "holdout_rerun" and cu["confirmation"]["holdout_frac"] == "0.25"
    cmd = cu["run"]["command"]
    assert cmd[cmd.index("--grade") + 1] == "sweep_holdout" and cmd[cmd.index("--research-unit") + 1] == cid
    assert cu["run"]["inputs"] == {"research_unit": cid}     # no workflow input the generic runner lacks


def test_non_holdout_capable_pass_keeps_the_forward_wait_block(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    cmd = [t if t != "exit_lever_ablation.py" else t for t in CMD]
    cmd[1] = "scripts/research/leg_corpus_s1.py"
    _p, (cid, ctext) = qg.grade_unit_full(r, PID, _parent(cmd=cmd), "2030-01-02")
    cu = yaml.safe_load(ctext)
    assert cu["status"] == "blocked" and "no input that confines" in cu["blocked_reason"]


def _blocked_forward(r: Path, pid_text: str) -> tuple[str, str]:
    """The blocked forward-wait unit the OLD grader authored for this parent (built from the pre-build path)."""
    u = yaml.safe_load(pid_text)
    u["run"]["command"] = [t for t in u["run"]["command"]]
    saved = dict(qg._HOLDOUT_COMMANDS)
    qg._HOLDOUT_COMMANDS.clear()
    try:
        fid = qg.confirm_unit_id(PID, "2030-01-01")
        text = qg.confirmation_unit(u, {"cells_swept": 4}, fid)
    finally:
        qg._HOLDOUT_COMMANDS.update(saved)
    assert "status: blocked" in text
    (r / "research" / "queue" / f"{fid}.yaml").write_text(text)
    return fid, text


def test_blocked_forward_wait_is_rearmed_while_the_parent_passes(tmp_path):
    r = _repo(tmp_path)
    (r / "research" / "queue" / f"{PID}.yaml").write_text(_parent(verdict="pass"))
    fid, ftext = _blocked_forward(r, _parent(verdict="pass"))
    new, (cid, ctext) = qg.grade_unit_full(r, fid, ftext, "2030-02-01")
    u, cu = yaml.safe_load(new), yaml.safe_load(ctext)
    assert u["status"] == "retired" and u["grading"]["superseded_by"] == cid == qg.holdout_rerun_id(PID, "2030-02-01")
    assert cu["status"] == "queued" and cu["confirmation"]["of"] == PID and cu["confirmation"]["mode"] == "holdout_rerun"
    # the grade is idempotent with the re-run on disk (what --verify re-derives); a different file under
    # the id (hand-edited / collision) is never overwritten
    (r / "research" / "queue" / f"{cid}.yaml").write_text(ctext)
    assert qg._rearm_forward_wait(r, yaml.safe_load(ftext), ftext, "2030-02-01") == (new, (cid, ctext))
    (r / "research" / "queue" / f"{cid}.yaml").write_text(ctext + "# edited\n")
    assert qg._rearm_forward_wait(r, yaml.safe_load(ftext), ftext, "2030-02-01") is None


def test_blocked_forward_wait_left_alone_when_the_parent_no_longer_passes(tmp_path):
    r = _repo(tmp_path)
    for v in ("fail", None):
        (r / "research" / "queue" / f"{PID}.yaml").write_text(_parent(verdict=v))
        fid, ftext = _blocked_forward(r, _parent(verdict=v))
        assert qg._rearm_forward_wait(r, yaml.safe_load(ftext), ftext, "2030-02-01") is None, v


def _git(r, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(r), check=True, capture_output=True)


def test_verify_reproduces_the_rearm(tmp_path):
    r = _repo(tmp_path)
    (r / "research" / "queue" / f"{PID}.yaml").write_text(_parent(verdict="pass"))
    fid, _ = _blocked_forward(r, _parent(verdict="pass"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "g")
    res = qg.run(r, graded_at="2030-02-01", write=True)
    assert [s["confirms"] for s in res["spawned"]] == [fid]
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "grade")
    assert qg.verify(r, "main") == []
    # planted: a hand-edited re-run does not reproduce
    cid = res["spawned"][0]["id"]
    p = r / "research" / "queue" / f"{cid}.yaml"
    p.write_text(p.read_text().replace("sweep_holdout", "sweep"))
    _git(r, "commit", "-q", "-am", "tamper")
    assert any("does not reproduce" in x for x in qg.verify(r, "main"))


# ---- STAGE-0 holdout (RESEARCH-NO-WAIT-FOR-DATA, 2026-11-28) ----------------------------------------------------
S0 = ["python3", "scripts/research/exit_lever_ablation.py", "--leg", "leg_x", "--arm", "A=", "--days", "1830",
      "--grade", "stage0", "--baseline", "A", "--delta-r", "0", "--folds", "4", "--fold-majority", "3",
      "--n-floor", "39", "--out", "{out_dir}"]


def test_stage0_pass_gets_a_one_run_holdout_boundary_from_its_own_span():
    from datetime import datetime, timezone
    after = datetime(2026, 11, 26, 14, 11, tzinfo=timezone.utc)
    for wf in (None, "research-script-run.yml"):
        hc, frac = qg.holdout_command({"workflow": wf, "command": S0}, "RQ-C", after)
        assert frac == "0.25" and hc[hc.index("--grade") + 1] == "stage0"           # same grade, same rule
        assert hc[-4:] == ["--stage0-holdout-start", "2025-08-26", "--research-unit", "RQ-C"]   # end - 25% of 1830 d
        assert hc[:len(S0)] == S0                                                     # every PASS flag kept
    # no end known -> no boundary (forward-wait path keeps its old behaviour)
    assert qg.holdout_command({"workflow": None, "command": S0}, "RQ-C") is None
    # a run that already declares its own split, a trainer run, or another script is left alone
    own = S0 + ["--stage0-holdout-start", "2025-01-01"]
    assert qg.holdout_command({"workflow": None, "command": own}, "RQ-C", after) is None
    assert qg.holdout_command({"workflow": "research-script-run-trainer.yml", "command": S0}, "RQ-C", after) is None
    other = list(S0)
    other[1] = "scripts/research/leg_corpus_s1.py"
    assert qg.holdout_command({"workflow": None, "command": other}, "RQ-C", after) is None
    # an explicit --start sets the span
    st = S0 + ["--start", "2022-11-26"]
    hc, _ = qg.holdout_command({"workflow": None, "command": st}, "RQ-C", after)
    assert hc[hc.index("--stage0-holdout-start") + 1] == "2025-11-26"


def test_blocked_stage0_forward_wait_is_rearmed(tmp_path):
    r = _repo(tmp_path)
    ptext = _parent(cmd=S0, verdict="pass")
    (r / "research" / "queue" / f"{PID}.yaml").write_text(ptext)
    u = yaml.safe_load(ptext)
    saved = dict(qg._STAGE0_HOLDOUT)
    qg._STAGE0_HOLDOUT.clear()
    try:
        fid = qg.confirm_unit_id(PID, "2030-01-01")
        ftext = qg.confirmation_unit(u, {"cells_swept": 1}, fid)
    finally:
        qg._STAGE0_HOLDOUT.update(saved)
    assert "status: blocked" in ftext
    new, (cid, ctext) = qg.grade_unit_full(r, fid, ftext, "2030-02-01")
    cu = yaml.safe_load(ctext)
    assert yaml.safe_load(new)["status"] == "retired" and cu["confirmation"]["mode"] == "holdout_rerun"
    assert "--stage0-holdout-start" in cu["run"]["command"] and "not_before" not in cu


def test_producer_health_family_opens_no_confirmation_and_retires_a_blocked_one(tmp_path):
    r = _repo(tmp_path)
    p = yaml.safe_load(_parent(verdict="pass"))
    p["generated"] = {"family": "leg-corpus-s1", "key": "leg-corpus-s1:family=trend_4h"}
    ptext = yaml.safe_dump(p, sort_keys=False)
    assert not qg.template_cell(p)                                         # no confirmation is ever opened
    (r / "research" / "queue" / f"{PID}.yaml").write_text(ptext)
    fid, ftext = _blocked_forward(r, ptext)                                # one authored before the exemption
    new, child = qg.grade_unit_full(r, fid, ftext, "2030-02-01")
    u = yaml.safe_load(new)
    assert child is None and u["status"] == "retired" and "producer-health" in u["grading"]["note"]

"""The runner fingerprint (row ML-FS-RECIPE, 2026-11-06): which machine and library build a research run executed on.

MEASURED 2026-11-06: the 1h baseline in the timeframe units took exactly two outcomes across runner runs on one data pin (class A:
b620/b626, class B: b625/b622/b624). The cause was unverifiable because the manifests recorded nothing about the runner. These tests
pin that the record exists, is stable per machine, differs between machines, never reads secrets, and can never fail a run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import runner_fingerprint as RF  # noqa: E402
from scripts.research import script_run  # noqa: E402

X86 = "processor\t: 0\nmodel name\t: AMD EPYC 7763\nflags\t\t: fpu sse4_2 avx avx2 fma\n"
OSR = 'PRETTY_NAME="Ubuntu 24.04 LTS"\n'


def test_self_test_runs_clean():
    RF._self_test()


def test_same_machine_same_class_and_different_cpu_different_class():
    a = RF.fingerprint(cpuinfo_text=X86, os_release_text=OSR, env={})
    b = RF.fingerprint(cpuinfo_text=X86, os_release_text=OSR, env={"ImageVersion": "20261102.1"})
    other = RF.fingerprint(cpuinfo_text=X86.replace("AMD EPYC 7763", "Intel Xeon 8272CL"), os_release_text=OSR, env={})
    assert a["class_id"] == b["class_id"], "the image build number is recorded but must not split a hardware class"
    assert a["class_id"] != other["class_id"]


def test_the_simd_flags_that_change_kernels_are_part_of_the_class():
    plain = RF.fingerprint(cpuinfo_text=X86, os_release_text=OSR, env={})
    wide = RF.fingerprint(cpuinfo_text=X86 + "flags\t\t: avx512f\n", os_release_text=OSR, env={})
    assert plain["cpu_simd"] == ["avx", "avx2", "fma", "sse4_2"]
    # only the FIRST cpu's flags line is read, so a second flags line must not change the answer
    assert wide["class_id"] == plain["class_id"]
    avx512 = RF.fingerprint(cpuinfo_text=X86.replace("fma", "fma avx512f"), os_release_text=OSR, env={})
    assert "avx512f" in avx512["cpu_simd"] and avx512["class_id"] != plain["class_id"]


def test_an_unreadable_field_is_none_and_listed_never_zero():
    fp = RF.fingerprint(cpuinfo_text="", os_release_text="", env={})
    assert fp["cpu_model"] is None and fp["cpu_simd"] is None and fp["os"] is None
    assert {"cpu_model", "cpu_simd", "os"} <= set(fp["unread"])
    assert fp["read_state"] == "partial"


def test_only_the_named_environment_keys_are_read_and_the_record_is_json():
    fp = RF.fingerprint(cpuinfo_text=X86, os_release_text=OSR, env={"GITHUB_TOKEN": "s3cr3t", "ImageOS": "ubuntu24", "HF_TOKEN": "hf_x"})
    blob = json.dumps(fp)
    assert "s3cr3t" not in blob and "hf_x" not in blob
    assert fp["image"] == {"ImageOS": "ubuntu24", "ImageVersion": None, "RUNNER_OS": None, "RUNNER_ARCH": None, "RUNNER_ENVIRONMENT": None}
    assert set(RF.LIBS) == set(fp["libs"])


def test_the_live_fingerprint_reads_this_machine():
    fp = RF.fingerprint()
    assert fp["read_state"] in ("read", "partial") and isinstance(fp["class_id"], str) and len(fp["class_id"]) == 12
    assert isinstance(fp["cores_logical"], int) and fp["cores_logical"] >= 1


def _plan(tmp_path):
    (tmp_path / "scripts" / "research").mkdir(parents=True)
    (tmp_path / "scripts" / "research" / "s.py").write_text("print('ok')\n")
    q = tmp_path / "q"
    q.mkdir()
    (q / "RQ-20260101-001.yaml").write_text(yaml.safe_dump({
        "id": "RQ-20260101-001", "title": "t", "question": "q", "status": "queued", "cadence": "once",
        "run": {"workflow": script_run.WORKFLOW, "command": ["python3", "scripts/research/s.py"],
                "inputs": {"research_unit": "RQ-20260101-001"}},
        "decision_rule": {"id": "R", "registered_at": "2026-01-01"},
        "lands": {"store": "research/results/"}}))
    p = script_run.plan("RQ-20260101-001", run_id="t", queue_dir=q, repo=tmp_path)
    assert p.ok, p.errors
    return p


def test_the_shared_run_manifest_carries_the_runner(tmp_path):
    p = _plan(tmp_path)
    m = script_run.execute(p, repo=tmp_path)
    assert m["all_ok"] is True
    assert m["runner"]["read_state"] in ("read", "partial") and len(m["runner"]["class_id"]) == 12
    on_disk = json.loads((tmp_path / p.out_dir / "run-manifest.json").read_text())
    assert on_disk["runner"]["class_id"] == m["runner"]["class_id"]


def test_a_fingerprint_failure_never_fails_the_run(tmp_path, monkeypatch):
    p = _plan(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("no cpuinfo today")
    monkeypatch.setattr("importlib.util.spec_from_file_location", boom)
    m = script_run.execute(p, repo=tmp_path)
    assert m["all_ok"] is True, "recording the runner must never fail a research run"
    assert m["runner"]["read_state"] == "could_not_look" and "no cpuinfo today" in m["runner"]["error"]


def test_the_timeframe_result_records_the_runner_too():
    import ml_entry_timeframe as T
    assert T.RF is RF
    src = (REPO / "scripts" / "research" / "ml_entry_timeframe.py").read_text()
    assert src.count('"runner": RF.fingerprint()') == 2, "both the unit result and the baseline result must carry the runner"

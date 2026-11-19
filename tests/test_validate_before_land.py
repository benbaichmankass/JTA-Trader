"""AM-OPS-9: self-landing research producers validate their OWN generated tree before they land anything.

Producer-side validation; enforces the existing never-land-red rule; respects the operator's 2026-11-12
PYTEST-RUN-REQUIRED: REPORT-ONLY decision; adds no merge-side gate.

Two halves:
  1. scripts/ci/validate_before_land.py: pass -> ok=true; a failing target -> ok=false, exactly one pipeline item,
     exit 0; an open item -> no second filing; a failed filing never raises; --baseline-ref only forgives
     failures that also fail on the base.
  2. Each of the three producers (replenish, results batch, dispatch stamps) runs the validation step BEFORE its
     commit-to-main step, and that step is gated on the validation's ok output.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/ci/validate_before_land.py"
COMMIT = "./.github/actions/commit-to-main"
SENTENCE = ("Producer-side validation; enforces the existing never-land-red rule; respects the operator's "
            "2026-11-12 PYTEST-RUN-REQUIRED: REPORT-ONLY decision; adds no merge-side gate.")


def _mod():
    spec = importlib.util.spec_from_file_location("validate_before_land", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["validate_before_land"] = m  # @dataclass resolves its module through sys.modules
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def vbl():
    return _mod()


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A tmp dir with one passing and one failing test file, a temp pipeline store and a GITHUB_OUTPUT file."""
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2, 'planted'\n")
    out = tmp_path / "gh_output"
    out.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(tmp_path)
    return {"dir": tmp_path, "out": out, "store": tmp_path / "pipeline"}


def _outputs(path: Path) -> dict:
    return dict(ln.split("=", 1) for ln in path.read_text().splitlines() if "=" in ln)


def _records(store: Path) -> list:
    return [json.loads(p.read_text()) for p in sorted(store.glob("*.json"))] if store.exists() else []


# ── 1. the validation step ───────────────────────────────────────────────────────────────────


def test_a_passing_target_proceeds_and_files_nothing(vbl, sandbox):
    rc = vbl.main(["--producer", "p", "--pytest", str(sandbox["dir"] / "test_ok.py"), "--store", str(sandbox["store"])])
    assert rc == 0
    assert _outputs(sandbox["out"]) == {"ok": "true"}
    assert _records(sandbox["store"]) == []


def test_a_failing_target_lands_nothing_files_exactly_one_item_and_exits_0(vbl, sandbox):
    rc = vbl.main(["--producer", "research-queue-replenish",
                   "--pytest", str(sandbox["dir"] / "test_ok.py"), "--pytest", str(sandbox["dir"] / "test_bad.py"),
                   "--store", str(sandbox["store"])])
    assert rc == 0, "a failing validation must not turn the run red (no halting)"
    assert _outputs(sandbox["out"]) == {"ok": "false"}, "ok=false is what keeps commit-to-main from running"
    recs = _records(sandbox["store"])
    assert len(recs) == 1
    it = recs[0]
    assert it["what"].startswith("PRODUCER VALIDATION FAILED [research-queue-replenish]")
    assert any(t.endswith("test_bad.py::test_bad") for t in it["failing_tests"]), it["failing_tests"]
    assert "planted" in it["log_tail"]
    assert it["next_action"] == "check_observation" and it["state"] == "queued" and it["owner"] == "manager"
    assert it["roadmap"] == ["unmapped"] and it["roadmap_unmapped_reason"]
    assert it["due_when"]["kind"] == "date"
    assert it["origin"]["kind"] == "audit" and it["origin"]["by"] == "research-queue-replenish"
    assert it["origin"]["ref"] and "validate_before_land.py" in it["origin"]["rerun"]
    # the item itself passes the pipeline validator and the soak-contract guard's observation rule
    sys.path.insert(0, str(REPO / "scripts" / "ops"))
    sys.path.insert(0, str(REPO / "scripts" / "ci"))
    import pipeline
    import check_soak_contracts
    pipeline.validate(it)
    assert check_soak_contracts.observation_problems(it["observation"]) == []
    assert it["observation"]["due_by"] == it["due_when"]["due_date"]


def test_an_open_item_means_no_second_filing(vbl, sandbox):
    args = ["--producer", "p", "--pytest", str(sandbox["dir"] / "test_bad.py"), "--store", str(sandbox["store"])]
    assert vbl.main(args) == 0
    assert vbl.main(args) == 0
    assert len(_records(sandbox["store"])) == 1, "deduplicated by the stable title prefix"
    # another producer is a different key
    assert vbl.main(["--producer", "q", *args[2:]]) == 0
    assert len(_records(sandbox["store"])) == 2


def test_a_closed_item_does_not_block_a_new_filing(vbl):
    assert vbl.open_duplicate([{"id": "A", "what": vbl.title_prefix("p") + ": x", "state": "done"}], "p") is None
    assert vbl.open_duplicate([{"id": "A", "what": vbl.title_prefix("p") + ": x", "state": "routed"}], "p") == "A"


def test_a_failed_filing_is_printed_never_raised(vbl, sandbox, monkeypatch, capsys):
    sys.path.insert(0, str(REPO / "scripts" / "ops"))
    import pipeline

    def boom(*a, **k):
        raise RuntimeError("work store refused (HTTP 401)")

    monkeypatch.setattr(pipeline, "append", boom)
    rc = vbl.main(["--producer", "p", "--pytest", str(sandbox["dir"] / "test_bad.py"), "--store", str(sandbox["store"])])
    assert rc == 0
    assert _outputs(sandbox["out"]) == {"ok": "false"}
    out = capsys.readouterr().out
    assert "not filed: RuntimeError: work store refused (HTTP 401)" in out


def test_an_internal_error_is_a_fail_not_a_red_run(vbl, sandbox, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(vbl, "validate", boom)
    assert vbl.main(["--producer", "p", "--pytest", "x"]) == 0
    assert _outputs(sandbox["out"]) == {"ok": "false"}


def test_no_checks_is_not_a_pass(vbl, sandbox):
    assert vbl.main(["--producer", "p", "--no-file"]) == 0
    assert _outputs(sandbox["out"]) == {"ok": "false"}


def test_baseline_forgives_only_failures_that_also_fail_on_the_base(vbl, sandbox, monkeypatch):
    bad = str(sandbox["dir"] / "test_bad.py")
    first = vbl.run_checks([bad], [], sandbox["dir"]).failing
    assert len(first) == 1 and first[0].endswith("test_bad.py::test_bad")
    monkeypatch.setattr(vbl, "baseline_failures", lambda *a, **k: list(first))
    r = vbl.validate("p", [bad], [], baseline_ref="BASE", file=False)
    assert r.ok and "pre-existing" in r.note
    monkeypatch.setattr(vbl, "baseline_failures", lambda *a, **k: [])
    assert not vbl.validate("p", [bad], [], baseline_ref="BASE", file=False).ok, "a NEW failure still blocks"
    monkeypatch.setattr(vbl, "baseline_failures", lambda *a, **k: None)
    assert not vbl.validate("p", [bad], [], baseline_ref="BASE", file=False).ok, "an unreadable base blocks"


def test_profiles_name_real_test_files(vbl):
    for name, prof in vbl.PROFILES.items():
        assert prof["pytest"], name
        for t in prof["pytest"]:
            assert (REPO / t).is_file(), f"{name}: {t}"
    assert "tests/test_research_queue.py" in vbl.PROFILES["research-queue"]["pytest"]
    assert "python3 scripts/ci/check_research_results.py" in vbl.PROFILES["research-results"]["commands"]


def test_self_test_passes():
    cp = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True, cwd=REPO)
    assert cp.returncode == 0, cp.stdout + cp.stderr


# ── 2. each producer validates BEFORE it lands ────────────────────────────────────────────────

#: workflow, job, the commit-to-main step it gates, the producer name, the profile
PRODUCERS = [
    ("research-queue-replenish.yml", "replenish", "Land the new units on main",
     "research-queue-replenish", "research-queue"),
    ("research-queue-dispatch.yml", "land", "Land the batch of runner results on main",
     "research-queue-dispatch/results", "research-results"),
    ("research-queue-dispatch.yml", "land", "Land the dispatch stamps on main",
     "research-queue-dispatch/stamps", "research-queue-stamps"),
]


def _steps(wf: str, job: str) -> list:
    return yaml.safe_load((REPO / ".github/workflows" / wf).read_text())["jobs"][job]["steps"]


def _validation_step_for(steps: list, producer: str) -> int:
    hits = [i for i, s in enumerate(steps)
            if "validate_before_land.py" in str(s.get("run", "")) and f"--producer {producer}" in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected one validation step for {producer}, found {len(hits)}"
    return hits[0]


@pytest.mark.parametrize("wf,job,land,producer,profile", PRODUCERS, ids=[p[3] for p in PRODUCERS])
def test_each_producer_validates_before_its_commit_to_main_step(wf, job, land, producer, profile):
    steps = _steps(wf, job)
    li = [i for i, s in enumerate(steps) if s.get("name") == land]
    assert len(li) == 1, land
    li = li[0]
    assert steps[li].get("uses") == COMMIT
    vi = _validation_step_for(steps, producer)
    assert vi < li, f"{producer}: validation (step {vi}) must run BEFORE the landing (step {li})"
    v = steps[vi]
    assert f"--profile {profile}" in v["run"]
    vid = v.get("id")
    assert vid, "the validation step needs an id so the landing can read its verdict"
    assert f"steps.{vid}.outputs.ok == 'true'" in str(steps[li].get("if", "")), (
        f"{land} must be gated on the validation verdict, or a FAIL still lands")
    # the validation runs whenever the landing could (its condition is contained in the landing's)
    assert str(v.get("if", "")).strip() in str(steps[li].get("if", ""))
    # no other commit-to-main step sits between the validation and its landing ungated
    # (the stamps validation follows the receipt landing; that one carries no research/ data)
    assert "continue-on-error" not in v, "the step itself never fails the run; it needs no swallow"
    # pytest is installed in the job before the validation runs
    assert any('pip install --quiet "pytest' in str(s.get("run", "")) for s in steps[:vi])


@pytest.mark.parametrize("wf,count", [("research-queue-replenish.yml", 1), ("research-queue-dispatch.yml", 2)])
def test_every_added_comment_carries_the_no_new_gate_statement(wf, count):
    text = (REPO / ".github/workflows" / wf).read_text()
    flat = " ".join(ln.strip().lstrip("#").strip() for ln in text.splitlines() if ln.strip().startswith("#"))
    assert flat.count(SENTENCE) >= count


def test_the_ordering_check_is_not_vacuous():
    """Plant the landing BEFORE its validation; the ordering assertion must refuse it."""
    steps = _steps("research-queue-replenish.yml", "replenish")
    vi = _validation_step_for(steps, "research-queue-replenish")
    li = next(i for i, s in enumerate(steps) if s.get("name") == "Land the new units on main")
    steps.insert(vi, steps.pop(li))
    vi2 = _validation_step_for(steps, "research-queue-replenish")
    li2 = next(i for i, s in enumerate(steps) if s.get("name") == "Land the new units on main")
    assert not vi2 < li2

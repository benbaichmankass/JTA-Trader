"""KAGGLE-CPU-ROUTE (2026-10-14): published-data units run in a Kaggle CPU kernel; CPU-only bake-offs never route to GPU quota."""
import glob
import json
from pathlib import Path

import pytest
import yaml

from scripts.research import collect_runner_results as col
from scripts.research import compute_router as cr
from scripts.research import kaggle_run, script_run

REPO = Path(__file__).resolve().parents[1]
CFG = cr.load_config()
PUB = {"needs_gpu": False, "needs_trainer_resident_data": False, "published_data": "metis-market-data", "est_minutes": 20}
DS = {"kind": "jsonl", "groups": {"BTCUSDT_1h": {"path": "datasets-out/market_features/BTCUSDT/1h/v002/data.jsonl"}}}


def unit(compute, learners=("lightgbm", "prior"), routing=None):
    return {"id": "RQ-20300110-001", "status": "queued", "cadence": "once", "theme": "ml_health", "priority": 2,
            "compute": compute, "routing": dict(PUB if routing is None else routing),
            "ml_bakeoff": {"dataset": DS, "learners": {k: {"kind": k} for k in learners}}}


def test_published_data_unit_prefers_kaggle_cpu_not_the_runner_data_twin():
    for cls in ("cpu_light", "auto"):
        r = cr.plan(unit(cls), CFG)
        assert r.ok and r.backend == "kaggle_cpu" and r.workflow == "research-script-run-kaggle-cpu.yml", r
    # a unit that does not claim published data is untouched
    plain = unit("cpu_light", routing={"needs_gpu": False, "est_minutes": 20})
    plain["ml_bakeoff"] = None
    assert cr.plan(plain, CFG).backend == "github_runner"


def test_kaggle_cpu_is_not_gated_on_gpu_quota_and_has_its_own_capacity():
    assert "quota" not in CFG["backends"]["kaggle_cpu"]
    st = cr.BackendState(quota_hours=0.0)                       # GPU quota exhausted
    r = cr.resolve(unit("auto"), CFG, st)
    assert r.ok and not r.wait and r.backend == "kaggle_cpu"
    st2 = cr.BackendState(quota_hours=None)                     # GPU quota unreadable
    assert not cr.resolve(unit("auto"), CFG, st2).wait
    st3 = cr.BackendState(quota_hours=30.0, inflight={"kaggle": 1})   # the GPU slot being busy does not block CPU
    assert not cr.resolve(unit("auto"), CFG, st3).wait
    st4 = cr.BackendState(quota_hours=30.0, inflight={"kaggle_cpu": 1})
    w = cr.resolve(unit("auto"), CFG, st4)
    assert w.ok and w.wait and "kaggle_cpu at capacity" in w.reason


def test_cpu_only_bakeoff_cannot_be_gpu_preferred():
    r = cr.plan(unit("gpu_preferred"), CFG)
    assert not r.ok and "GPU quota" in r.error
    assert not cr.plan(unit("gpu"), CFG).ok
    # a genuine GPU request is untouched
    g = unit("gpu", routing={"needs_gpu": True, "est_minutes": 60})
    g["ml_bakeoff"] = None
    assert cr.plan(g, CFG).backend == "kaggle"


def test_no_queued_cpu_bakeoff_routes_to_the_gpu_backend():
    """The population check behind the finding: every queue unit whose placement is Kaggle GPU must truly need a GPU."""
    bad = []
    for f in sorted(glob.glob(str(REPO / "research" / "queue" / "RQ-*.yaml"))):
        e = yaml.safe_load(Path(f).read_text()) or {}
        if e.get("status") not in ("queued", "running", None):
            continue
        p = cr.plan(e, CFG)
        if p.ok and p.backend == "kaggle" and not (e.get("routing") or {}).get("needs_gpu") and cr.cpu_only_bakeoff(e):
            bad.append(e["id"])
    assert not bad, f"CPU-only bake-offs placed on the metered Kaggle GPU backend: {bad}"


def test_the_4591_and_de02_bakeoffs_now_route_to_kaggle_cpu():
    ids = [f"RQ-20261014-4591-0{i}" for i in range(1, 7)] + ["RQ-20261014-de02-01"]
    for uid in ids:
        e = yaml.safe_load((REPO / "research" / "queue" / f"{uid}.yaml").read_text())
        p = cr.plan(e, CFG)
        assert p.ok and p.cls == "cpu_light" and p.backend == "kaggle_cpu", (uid, p)


def test_cpu_bundle_uses_its_own_slugs_and_no_gpu(tmp_path):
    uid = "RQ-20261014-4591-01"
    out = tmp_path / "b"
    info = kaggle_run.bundle(uid, "1", "someone", out, repo=REPO, accelerator="cpu")
    assert info["kernel_slug"] == "metis-research-run-cpu" and info["published_data"] == ["metis-market-data"]
    meta = json.loads((out / "dataset-metadata.json").read_text())
    assert meta["id"] == "someone/metis-research-bundle-cpu"
    km = json.loads((tmp_path / "b-kernel" / "kernel-metadata.json").read_text())
    assert km["enable_gpu"] == "false" and km["enable_internet"] == "false" and km["id"] == "someone/metis-research-run-cpu"
    assert km["dataset_sources"] == ["someone/metis-research-bundle-cpu", "someone/metis-market-data"]
    gpu = kaggle_run.bundle(uid, "1", "someone", tmp_path / "g", repo=REPO)       # default unchanged
    assert gpu["kernel_slug"] == "metis-research-run"
    assert json.loads((tmp_path / "g-kernel" / "kernel-metadata.json").read_text())["enable_gpu"] == "true"
    with pytest.raises(SystemExit):
        kaggle_run.bundle(uid, "1", "someone", tmp_path / "x", repo=REPO, accelerator="tpu")


def test_cpu_workflow_keeps_the_runner_contract_and_is_wired():
    p = REPO / ".github/workflows/research-script-run-kaggle-cpu.yml"
    wf = yaml.safe_load(p.read_text())
    on = wf.get("on") or wf.get(True)
    assert sorted(on["workflow_dispatch"]["inputs"]) == ["power_state", "research_unit"]
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["group"] == "research-script-run-kaggle-cpu"
    text = p.read_text()
    assert text.count("secrets.") == 1 and "KAGGLE_API_TOKEN" in text
    assert "--accelerator cpu" in text and "kaggle quota" not in text and "metis-research-run-cpu" in text
    assert "research-script-run-kaggle-cpu-${{ inputs.research_unit }}" in text
    assert script_run.KAGGLE_CPU_WORKFLOW in script_run.WORKFLOWS
    assert script_run.KAGGLE_CPU_WORKFLOW in col.COLLECTED_WORKFLOWS
    m = col._ARTIFACT_RE.match("research-script-run-kaggle-cpu-RQ-20261014-4591-01-123456")
    assert m and m.group(1) == "RQ-20261014-4591-01" and m.group(2) == "123456"
    assert col._ARTIFACT_RE.match("research-script-run-kaggle-RQ-20261014-4591-01-1").group(1) == "RQ-20261014-4591-01"

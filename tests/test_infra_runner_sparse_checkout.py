"""Every job that can run on the self-hosted `jta-infra` runner checks out sparse + blobless (PI-20261103-RAM7EH86-0003).

WHY: on 2026-11-03 a full depth-1 checkout measured 6.6-8.6 GB per job on the 97 GB trainer, the disk hit 100% and a
real-money flatten died (system-actions 41650362029); after #22652, one full clone still took free disk 19.5 -> 11.7 GB
(floor 15 GB). comms/research is 5.0 GB of the 5.6 GB tracked tree. A job routed to the runner (runs-on references
INFRA_RUNS_ON / jta-infra) must therefore never fall back to a full checkout.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
MARKERS = ("INFRA_RUNS_ON", "jta-infra")
HEAVY = ("/comms/research", "/comms/macro")


def _infra_checkouts():
    for p in sorted(WF.glob("*.y*ml")):
        doc = yaml.safe_load(p.read_text())
        for job_name, job in (doc.get("jobs") or {}).items():
            if not any(m in str(job.get("runs-on", "")) for m in MARKERS):
                continue
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("actions/checkout"):
                    yield p.name, job_name, step.get("with") or {}


def violations_for(with_: dict) -> list[str]:
    out = []
    sparse = str(with_.get("sparse-checkout", "") or "").strip()
    if not sparse:
        out.append("no sparse-checkout (full checkout)")
        return out
    lines = [ln.strip() for ln in sparse.splitlines() if ln.strip()]
    single_file = len(lines) == 1 and not lines[0].startswith(("/*", "*"))
    if not single_file and with_.get("filter") != "blob:none":
        out.append("sparse set without filter: blob:none (the pack would still carry every blob)")
    if any(ln in ("/*", "*") for ln in lines):
        for heavy in HEAVY:
            excluded = any(ln.startswith("!" + heavy) for ln in lines)
            if not excluded:
                out.append(f"'/*' sparse set does not exclude {heavy}")
            reincluded = [ln for ln in lines if ln.startswith(heavy) and not ln.endswith(".json")]
            if reincluded:
                out.append(f"re-includes heavy paths: {reincluded}")
    return out


def test_every_infra_checkout_is_sparse_and_blobless():
    found = list(_infra_checkouts())
    # was 6 until B13 moved 3 research workflows to hosted
    assert len(found) >= 4, f"probe found too few infra checkouts ({len(found)}): the denominator is wrong"
    bad = [f"{wf}:{job}: {v}" for wf, job, w in found for v in violations_for(w)]
    assert not bad, "\n".join(bad)


def test_dispatch_profile_keeps_the_manifests_the_collector_dedupes_on():
    doc = yaml.safe_load((WF / "research-queue-dispatch.yml").read_text())
    steps = doc["jobs"]["dispatch"]["steps"]
    w = next(s["with"] for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    lines = [ln.strip() for ln in w["sparse-checkout"].splitlines() if ln.strip()]
    assert "/comms/research/RQ-*/**/*.json" in lines, "run-manifest.json / record-inputs.json must stay materialized"
    assert w.get("fetch-depth") == 0


def test_guard_catches_a_full_checkout():
    assert violations_for({})
    assert violations_for({"sparse-checkout": "/*\n!/comms/research/\n!/comms/macro/"})          # no filter
    assert violations_for({"filter": "blob:none", "sparse-checkout": "/*\n!/comms/macro/"})      # research not excluded
    assert not violations_for({"filter": "blob:none",
                               "sparse-checkout": "/*\n!/comms/research/\n!/comms/macro/"})
    assert not violations_for({"sparse-checkout": "scripts/ops/system_action_route.py"})        # single-file sparse


def test_kaggle_runners_materialize_bundle_paths():
    for name in ("research-script-run-kaggle.yml", "research-script-run-kaggle-cpu.yml"):
        text = (WF / name).read_text()
        assert "git sparse-checkout add" in text and "bundle_paths" in text, name

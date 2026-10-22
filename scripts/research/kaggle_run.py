#!/usr/bin/env python3
# wiring: .github/workflows/research-script-run-kaggle.yml (the Kaggle GPU runner)
"""Orchestration helpers for ``research-script-run-kaggle.yml`` -- the Kaggle GPU twin of the token-free runner.

The workflow shells out to the ``kaggle`` CLI; the parts that need judgement live here so they are testable:

  bundle    build the private-dataset bundle (repo.tar.gz + spec.json + dataset-metadata.json) and the kernel dir
  gate      read ``kaggle quota`` text and decide go / no-go against the floor in scripts/research/research_compute.yaml
  info      the unit's timeout, for the poll loop

CONTRACT (identical to research-script-run.yml / -trainer.yml): the workflow's only inputs are
``research_unit`` and ``power_state``; the command is read from the unit file on the checked-out ref and
re-checked by ``script_run.plan`` here AND inside the kernel; results come back to
``comms/research/<unit>/<run_id>/`` and are derived into ``record-inputs.json`` by ``script_run.py
--derive-record``, so the SAME collector lands them and research-ops reads them identically.

PUBLIC DATA ONLY. The bundle is the tracked files of scripts/, src/, config/, ml/ plus the unit file -- the
repo is public, and nothing from a VM, a database or a secret is ever added. ``run.bundle_paths`` may add
tracked files under comms/ docs/research/ research/ data/ only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from scripts.research import compute_router as cr  # noqa: E402
from scripts.research import script_run  # noqa: E402

DATASET_SLUG = "metis-research-bundle"
KERNEL_SLUG = "metis-research-run"
#: KAGGLE-CPU-ROUTE (2026-10-14): the CPU twin has its OWN bundle-dataset and kernel slugs, so a CPU run and a GPU run can be in
#: flight together without one re-versioning the dataset the other kernel is mounting (the stale-mount defect, 2026-10-13).
SLUGS = {"gpu": (DATASET_SLUG, KERNEL_SLUG), "cpu": (DATASET_SLUG + "-cpu", KERNEL_SLUG + "-cpu")}
BUNDLE_ROOTS = ("scripts", "src", "config", "ml")
EXTRA_ROOTS = ("comms", "docs/research", "research", "data")
MAX_BUNDLE_MB = 200


def _tracked(paths: List[str], repo: Path) -> List[str]:
    out = subprocess.run(["git", "ls-files", "--", *paths], cwd=repo, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p]


def bundle(unit: str, run_id: str, username: str, out: Path, *, repo: Path = _REPO, sha: str = "",
           accelerator: str = "gpu", wheels: Optional[Path] = None) -> Dict[str, Any]:
    if accelerator not in SLUGS:
        raise SystemExit(f"accelerator must be one of {sorted(SLUGS)}, not {accelerator!r}")
    dataset_slug, kernel_slug = SLUGS[accelerator]
    p = script_run.plan(unit, run_id=run_id, repo=repo, queue_dir=repo / "research" / "queue")
    if not p.ok:
        raise SystemExit("kaggle bundle refused: " + "; ".join(p.errors))
    import yaml
    raw = yaml.safe_load((repo / "research" / "queue" / f"{unit}.yaml").read_text(encoding="utf-8")) or {}
    extra = (raw.get("run") or {}).get("bundle_paths") or []
    for e in extra:
        if not isinstance(e, str) or ".." in e or e.startswith("/") or \
                not any(e == r or e.startswith(r + "/") for r in EXTRA_ROOTS):
            raise SystemExit(f"run.bundle_paths entry {e!r} must be a repo-relative path under {EXTRA_ROOTS}")
    # ML-DATA-OFF-TRAINER: a unit that reads published ML data gets that private dataset mounted beside the bundle.
    published = []
    name = (raw.get("routing") or {}).get("published_data")
    if name:
        pcfg = cr.load_config().get("published_data") or {}
        if name not in pcfg:
            raise SystemExit(f"routing.published_data {name!r} is not declared in research_compute.yaml::published_data")
        problem = cr.published_problem(raw, cr.load_config())
        if problem:
            raise SystemExit("kaggle bundle refused: " + problem)
        published.append(pcfg[name]["kaggle_dataset"])
    files = sorted(set(_tracked([*BUNDLE_ROOTS, f"research/queue/{unit}.yaml", *extra], repo)))
    out.mkdir(parents=True, exist_ok=True)
    tgz = out / "repo.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        for f in files:
            tf.add(repo / f, arcname=f)
    size_mb = tgz.stat().st_size / 1e6
    if size_mb > MAX_BUNDLE_MB:
        raise SystemExit(f"bundle is {size_mb:.0f} MB > {MAX_BUNDLE_MB} MB cap -- trim run.bundle_paths")
    # ML-NONGBDT-RUNNERS: internet is off in the kernel, so the non-GBDT learner packages (tabicl / tabpfn / einops / skrub,
    # all pure-python wheels the Kaggle image lacks) travel in the bundle; kernel_main.py installs them with --no-index.
    n_wheels = 0
    if wheels is not None and Path(wheels).is_dir():
        # flat in the bundle root: `kaggle datasets version` skips sub-directories unless --dir-mode is given
        for w in sorted(Path(wheels).glob("*.whl")):
            shutil.copy2(w, out / w.name)
            n_wheels += 1
    (out / "spec.json").write_text(json.dumps({"unit": unit, "run_id": run_id, "commit_sha": sha}) + "\n")
    (out / "dataset-metadata.json").write_text(json.dumps({
        "title": dataset_slug, "id": f"{username}/{dataset_slug}", "licenses": [{"name": "CC0-1.0"}],
        "isPrivate": True}) + "\n")
    kdir = out.parent / (out.name + "-kernel")
    kdir.mkdir(parents=True, exist_ok=True)
    kmain = (repo / "scripts/research/kaggle_unit/kernel_main.py").read_text()
    marker = "EXPECTED = None  # BUNDLE-INJECTED"
    if marker not in kmain:
        raise SystemExit("kernel_main.py lost its BUNDLE-INJECTED expectation line")
    kmain = kmain.replace(marker, "EXPECTED = " + json.dumps({"unit": unit, "run_id": run_id}), 1)
    (kdir / "kernel_main.py").write_text(kmain)
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{username}/{kernel_slug}", "title": kernel_slug, "code_file": "kernel_main.py",
        "language": "python", "kernel_type": "script", "is_private": "true", "enable_gpu": "true" if accelerator == "gpu" else "false",
        "enable_tpu": "false", "enable_internet": "false",
        "dataset_sources": [f"{username}/{dataset_slug}", *[f"{username}/{d}" for d in published]],
        "competition_sources": [],
        "kernel_sources": [], "model_sources": []}, indent=1) + "\n")
    return {"accelerator": accelerator, "dataset_slug": dataset_slug, "kernel_slug": kernel_slug, "published_data": published, "files": len(files), "wheels": n_wheels, "bundle_mb": round(size_mb, 2), "timeout_minutes": p.timeout_minutes,
            "kernel_dir": str(kdir)}


def gate(quota_text: str, est_minutes: float) -> Dict[str, Any]:
    cfg = cr.load_config()
    q = cfg["backends"]["kaggle"]["quota"]
    parsed = cr.parse_quota(quota_text, q.get("resource", "GPU"))
    need = max(est_minutes, 5.0) / 60.0
    floor = float(q.get("floor_hours", 0.0))
    if parsed["remaining"] is None:
        return {"go": False, "why": "kaggle quota unreadable -- not routed blind", **parsed}
    if parsed["remaining"] - need < floor:
        return {"go": False, "why": f"{parsed['remaining']:.2f} h left - unit ~{need:.2f} h < floor {floor:g} h "
                                    f"(refreshes {parsed['refresh']})", **parsed}
    return {"go": True, "why": "within quota", **parsed}


STALE_RC = 20      # verify: the fetched result is another run's (retry after the dataset version settles)
MISSING_RC = 21    # verify: no manifest at all (kernel died; not a staleness case)


def verify_result(result_dir: Path, unit: str, run_id: str) -> Dict[str, Any]:
    """Does what `kaggle kernels output` returned belong to THIS run? {rc, reason}."""
    ke = result_dir / "kernel-exit.json"
    try:
        kx = json.loads(ke.read_text()) if ke.exists() else {}
    except ValueError:
        kx = {}
    if isinstance(kx, dict) and kx.get("stale_spec"):
        return {"rc": STALE_RC, "reason": f"kernel mounted a stale dataset version: {kx.get('mounted')} (expected {kx.get('expected')})"}
    mf = result_dir / "run-manifest.json"
    if not mf.exists():
        return {"rc": MISSING_RC, "reason": "no run-manifest.json in the kernel output"}
    try:
        m = json.loads(mf.read_text())
    except ValueError:
        return {"rc": MISSING_RC, "reason": "run-manifest.json is not valid JSON"}
    bad = script_run.manifest_mismatch(m, unit, run_id)
    if bad:
        return {"rc": STALE_RC, "reason": "; ".join(bad)}
    return {"rc": 0, "reason": "ok"}


def _self_test() -> int:
    t = ("resource  used   remaining  total   refreshAt            \n"
         "--------  -----  ---------  ------  -------------------  \n"
         "GPU       0.02h  29.98h     30.00h  2026-10-17T00:00:00  \n"
         "TPU       0.00h  20.00h     20.00h  2026-10-17T00:00:00  \n")
    g = gate(t, 60)
    assert g["go"] and g["remaining"] == 29.98, g
    low = t.replace("29.98h", " 2.10h")
    assert not gate(low, 60)["go"], gate(low, 60)
    assert not gate("garbage", 60)["go"] and gate("garbage", 60)["remaining"] is None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        u, r = "RQ-20261013-0b07-03", "222"
        assert verify_result(d, u, r)["rc"] == MISSING_RC
        (d / "run-manifest.json").write_text(json.dumps({"unit": u, "run_id": "222"}))
        assert verify_result(d, u, r)["rc"] == 0
        (d / "run-manifest.json").write_text(json.dumps({"unit": "RQ-20261013-0b07-01", "run_id": "111"}))
        assert verify_result(d, u, r)["rc"] == STALE_RC          # the 2026-10-13 defect
        (d / "run-manifest.json").write_text(json.dumps({"unit": u, "run_id": "222"}))
        (d / "kernel-exit.json").write_text(json.dumps({"stale_spec": True}))
        assert verify_result(d, u, r)["rc"] == STALE_RC          # the kernel's own refusal wins
    print("kaggle_run self-test OK")
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("bundle")
    b.add_argument("--unit", required=True)
    b.add_argument("--run-id", required=True)
    b.add_argument("--username", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--sha", default="")
    b.add_argument("--accelerator", choices=sorted(SLUGS), default="gpu")
    b.add_argument("--wheels", default="", help="dir of *.whl to ship in the bundle (learner packages the kernel image lacks)")
    g = sub.add_parser("gate")
    g.add_argument("--quota-file", required=True)
    g.add_argument("--unit", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--dir", required=True)
    v.add_argument("--unit", required=True)
    v.add_argument("--run-id", required=True)
    sub.add_parser("self-test")
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        return _self_test()
    if a.cmd == "verify":
        res = verify_result(Path(a.dir), a.unit, a.run_id)
        print(f"VERIFY rc={res['rc']}: {res['reason']}")
        return res["rc"]
    if a.cmd == "bundle":
        print(json.dumps(bundle(a.unit, a.run_id, a.username, Path(a.out), sha=a.sha, accelerator=a.accelerator, wheels=Path(a.wheels) if a.wheels else None)))
        return 0
    if a.cmd == "gate":
        import yaml
        raw = yaml.safe_load((_REPO / "research" / "queue" / f"{a.unit}.yaml").read_text(encoding="utf-8")) or {}
        est = cr.est_hours(raw) * 60.0
        res = gate(Path(a.quota_file).read_text(errors="replace") if Path(a.quota_file).exists() else "", est)
        print(json.dumps(res))
        return 0 if res["go"] else 10
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

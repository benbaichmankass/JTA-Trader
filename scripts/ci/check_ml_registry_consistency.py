#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::ml-registry-consistency-guard (--self-test, then the scan).
"""ml-registry-consistency-guard (lane ML-REGISTRY-CONSOLIDATE, 2026-11-09). A repo-consistency check, NOT a trading gate.

Fails when (1) a model id referenced by a config consumer (strategies.yaml model / exit_head_model / tp_revision,
overlay_policy.yaml artifact) is absent from the GET /api/bot/ml/registry feed or its repo artifact is missing,
(2) a model that is served or consumed at shadow or above has no docs/reference/model_names.yaml entry, or has slot
"unassigned", (3) a breed/model `slot:` is not D1..D10. Reads the real route against the repo tree and an empty mirror.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def scan(root: Path) -> list[str]:
    from src.runtime import ml_serving_inventory as inv
    errs: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["RUNTIME_LOGS_DIR"], os.environ["ICT_REPO_ROOT"] = tmp, str(root)
        from src.web.api.routers import training_center as tc
        feed = {r["model_id"]: r for r in tc.get_registry()["rows"]}
    breeds, models = inv.load_names(root)
    for mid, ref in inv.referenced_model_ids(root).items():
        row = feed.get(mid)
        if row is None:
            errs.append(f"{mid}: referenced by {ref['strategies']} but absent from the registry feed")
            continue
        p = row.get("artifact_path")
        if p and not p.startswith("runtime_logs/") and not (root / p).exists():
            errs.append(f"{mid}: artifact_path {p} does not exist")
    for mid, row in feed.items():
        if row.get("source") == "registry" or row.get("pointer_sibling"):
            continue
        if row.get("stage_from_config") in ("live", "testing", "shadow"):
            m = models.get(mid)
            if not (isinstance(m, dict) and m.get("name")):
                errs.append(f"{mid}: served/consumed ({row['stage_from_config']}) with no model_names.yaml entry")
            elif row.get("slot") == inv.UNASSIGNED:
                errs.append(f"{mid}: named but slot unassigned (add slot: to its breed or entry)")
    for label, d in list(breeds.items()) + list(models.items()):
        s = d.get("slot") if isinstance(d, dict) else None
        if s is not None and s not in inv.SLOTS:
            errs.append(f"{label}: slot {s!r} not in D1..D10")
    return errs


def self_test() -> int:
    import shutil
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        shutil.copytree(REPO / "config", t / "config", ignore=shutil.ignore_patterns("data_universe", "research"))
        shutil.copytree(REPO / "ml" / "served", t / "ml" / "served")
        shutil.copytree(REPO / "ml" / "candidates", t / "ml" / "candidates")
        shutil.copytree(REPO / "ml" / "overlay", t / "ml" / "overlay")
        (t / "docs" / "reference").mkdir(parents=True)
        shutil.copy(REPO / "docs/reference/model_names.yaml", t / "docs/reference/model_names.yaml")
        assert scan(t) == [], scan(t)  # control: clean copy passes
        n = t / "docs/reference/model_names.yaml"
        n.write_text(n.read_text().replace("  ml-entry-eq-struct-ens5-v1:", "  zz-removed:"))
        assert any("ens5" in e and "no model_names" in e for e in scan(t)), "missing-name plant not caught"
        n.write_text(n.read_text().replace("slot: D4", "slot: D99", 1))
        assert any("D99" in e for e in scan(t)), "bad-slot plant not caught"
        shutil.rmtree(t / "ml" / "candidates" / "ml_entry_eq_v3_struct_ens5")
        assert any("does not exist" in e for e in scan(t)), "missing-artifact plant not caught"
    print("self-test ok (3 planted faults caught, clean copy passes)")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    problems = scan(REPO)
    for e in problems:
        print("FAIL", e)
    print(f"ml-registry-consistency: {len(problems)} problem(s)")
    raise SystemExit(1 if problems else 0)

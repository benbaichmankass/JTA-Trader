"""TRAINER-REGISTRY-RETENTION: run ARTIFACT dirs are pruned to served + newest K + young + referenced; registry JSON is never touched."""
from __future__ import annotations

import json
import os
import time

from scripts.ops import trainer_run_retention as R

OLD = time.time() - 40 * 86400


def _run(root, model, run, age=OLD, size=10):
    d = root / model / run
    d.mkdir(parents=True)
    f = d / "model_state.json"
    f.write_text("x" * size)
    os.utime(f, (age, age))
    os.utime(d, (age, age))
    return d


def _world(tmp_path, served_run="20260601T000000Z"):
    exp, reg = tmp_path / "experiments-runs", tmp_path / "registry-store"
    reg.mkdir()
    runs = [f"202606{d:02d}T000000Z" for d in range(1, 21)]          # 20 daily runs, all old
    for r in runs:
        _run(exp, "m1", r)
    (reg / "m1.json").write_text(json.dumps({"model_id": "m1",
                                             "model_state_path": f"/home/u/ml/experiments-runs/m1/{served_run}/model_state.json"}))
    return exp, reg, runs


def test_keeps_served_newest_k_and_prunes_the_rest(tmp_path):
    exp, reg, runs = _world(tmp_path)
    rows, s = R.plan(exp, reg, [], keep_last=5, min_age_days=14)
    st = {x["run_id"]: (x["status"], x["reasons"]) for x in rows}
    assert st[runs[0]] == ("kept", ["served"])                       # the incumbent, older than the newest K
    assert all(st[r][0] == "kept" and "newest" in st[r][1] for r in runs[-5:])
    assert [r for r in runs if st[r][0] == "gc_candidate"] == runs[1:15]
    assert s["candidates"] == 14 and s["registry_read"] is True and s["served_models"] == 1


def test_young_and_referenced_runs_are_kept(tmp_path):
    exp, reg, runs = _world(tmp_path)
    _run(exp, "m1", "20260520T000000Z", age=time.time())             # young
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "evidence.md").write_text(f"source: experiments-runs/m1/{runs[3]}/metrics.json")
    rows, _ = R.plan(exp, reg, [docs], keep_last=5, min_age_days=14)
    st = {x["run_id"]: x for x in rows}
    assert st["20260520T000000Z"]["reasons"] == ["young"]
    assert st[runs[3]]["reasons"] == ["ref"]


def test_unreadable_registry_keeps_everything_and_apply_deletes_nothing(tmp_path):
    exp, reg, _runs = _world(tmp_path)
    (reg / "broken.json").write_text("{not json")
    _rows, s = R.plan(exp, reg, [], keep_last=1, min_age_days=14)
    assert s["registry_read"] is False and s["candidates"] == 0
    assert R.main(["--experiments-root", str(exp), "--registry-root", str(reg), "--ref-roots", "--keep-last", "1", "--apply"]) == 2
    assert len(list((exp / "m1").iterdir())) == 20


def test_unparseable_run_ids_are_never_pruned(tmp_path):
    exp, reg, _ = _world(tmp_path)
    _run(exp, "m1", "scratch-run")
    rows, _ = R.plan(exp, reg, [], keep_last=1, min_age_days=14)
    assert next(x for x in rows if x["run_id"] == "scratch-run")["reasons"] == ["unknown"]


def test_apply_deletes_only_candidates_and_never_touches_registry(tmp_path):
    exp, reg, runs = _world(tmp_path)
    before = (reg / "m1.json").read_text()
    rows, _s = R.plan(exp, reg, [], keep_last=5, min_age_days=14)
    assert R.apply(rows, exp) == 14
    left = sorted(p.name for p in (exp / "m1").iterdir())
    assert left == [runs[0]] + runs[-5:]
    assert (reg / "m1.json").read_text() == before


def test_apply_refuses_a_path_outside_the_root(tmp_path):
    exp, _reg, _ = _world(tmp_path)
    outside = tmp_path / "elsewhere" / "x" / "20260101T000000Z"
    outside.mkdir(parents=True)
    assert R.apply([{"status": "gc_candidate", "path": str(outside)}], exp) == 0 and outside.exists()

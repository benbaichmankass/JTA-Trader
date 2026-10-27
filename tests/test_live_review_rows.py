"""LTR-ROWS-SWAP-TRUNCATION: src/runtime/live_review_rows.py reads legacy + per-row files on a real git tree,
and the mirror's history read sees an earlier, longer version of reviews.jsonl."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

from src.runtime import live_review_rows as rl

ROOT = Path(__file__).resolve().parents[1]


def _sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, files, msg):
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _sh(repo, "add", "-A")
    _sh(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)
    return _sh(repo, "rev-parse", "HEAD")


def _git(repo):
    def g(*args, timeout=30):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()
    return g


def _row(rid, at="2026-10-27T16:00:00Z"):
    return {"review_id": rid, "reviewed_at": at, "recommendation": {"action": "hold"}}


def test_read_at_merges_legacy_and_per_row_files_on_real_git(tmp_path):
    _sh(tmp_path, "init", "-q")
    legacy = "\n".join(json.dumps(_row(f"LR-{i}")) for i in range(3)) + "\n"
    tip = _commit(tmp_path, {rl.REVIEWS_PATH: legacy,
                             rl.row_path("LR-9"): json.dumps(_row("LR-9", "2026-10-27T16:09:00Z"), indent=1),
                             rl.row_path("LR-5"): json.dumps(_row("LR-5", "2026-10-27T16:05:00Z")),
                             rl.row_path("LR-1"): json.dumps(_row("LR-1")),       # already legacy: one row
                             rl.row_path("LR-x"): json.dumps(_row("LR-y"))}, "rows")  # wrong name: not a row
    got = rl.read_at(tip, _git(tmp_path))
    assert got["state"] == "ok"
    assert [r["review_id"] for r in got["rows"]] == ["LR-0", "LR-1", "LR-2", "LR-5", "LR-9"]
    assert got["legacy_rows"] == 3 and got["file_rows"] == 3 and len(got["bad_files"]) == 1
    row, where = rl.find(tip, "LR-9", _git(tmp_path))
    assert row["review_id"] == "LR-9" and where == rl.row_path("LR-9")
    row, where = rl.find(tip, "LR-2", _git(tmp_path))
    assert row["review_id"] == "LR-2" and where == rl.REVIEWS_PATH


def test_per_row_files_alone_need_no_legacy_file(tmp_path):
    _sh(tmp_path, "init", "-q")
    tip = _commit(tmp_path, {rl.row_path("LR-1"): json.dumps(_row("LR-1"))}, "one")
    got = rl.read_at(tip, _git(tmp_path))
    assert got["state"] == "ok" and got["legacy_present"] is False and [r["review_id"] for r in got["rows"]] == ["LR-1"]
    assert rl.read_at("f" * 40, _git(tmp_path))["state"] == "could_not_read"


def test_a_cut_off_line_is_not_a_row_and_lost_ids_names_the_shrink():
    full = [_row(f"LR-{i}") for i in range(26)]
    cut = "\n".join(json.dumps(r) for r in full[:4]) + "\n" + json.dumps(full[4])[:40]
    rows, bad = rl.parse_legacy(cut)
    assert len(rows) == 4 and bad == 1
    assert len(rl.lost_ids([r["review_id"] for r in full], rows)) == 22
    assert rl.lost_ids(["LR-0"], rows) == []


def test_mirror_history_reads_earlier_versions_on_real_git(tmp_path):
    spec = importlib.util.spec_from_file_location("lrm_hist", ROOT / "scripts/ops/live_review_rows_mirror.py")
    lrm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lrm)
    _sh(tmp_path, "init", "-q")
    full = "\n".join(json.dumps(_row(f"LR-{i}")) for i in range(5)) + "\n"
    _commit(tmp_path, {rl.REVIEWS_PATH: full}, "26 rows")
    tip = _commit(tmp_path, {rl.REVIEWS_PATH: json.dumps(_row("LR-0")) + "\n",
                             rl.row_path("LR-7"): json.dumps(_row("LR-7"))}, "truncated")
    hist = lrm.git_history(tip, cwd=tmp_path)
    assert hist == [full.encode()]
    assert lrm.git_row_files(tip, cwd=tmp_path) == [rl.row_path("LR-7")]
    assert "4 review_id(s)" in lrm.shrink_problem({"LR-0", "LR-7"}, hist)


def test_attention_watch_rows_lag_sees_per_row_files(monkeypatch):
    from scripts.ops import attention_watch as aw
    legacy = json.dumps(_row("LR-1")) + "\n"
    tree = {f"{aw.LR_ROWS_REF}:{aw.LR_REVIEWS_REL}": legacy,
            f"{aw.LR_ROWS_REF}:{rl.row_path('LR-2')}": json.dumps(_row("LR-2"), indent=1)}

    def fake(*args):
        if args[0] == "ls-tree":
            return rl.row_path("LR-2") + "\n"
        return tree.get(args[1])
    monkeypatch.setattr(aw, "_git", fake)
    rows, bad, _ = aw._lr_rows(aw._lr_branch_text())
    assert sorted(rows) == ["LR-1", "LR-2"] and bad == 0

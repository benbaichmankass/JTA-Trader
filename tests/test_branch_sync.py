"""AUTO-BRANCH-SYNC: only behind, self-landing, Tier-1 claude/* PRs are updated; nothing else."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("branch_sync", REPO / "scripts/ci/branch_sync.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)

R = "o/r"
SELF = {"tier": 1, "landing": "self"}


def pr(**kw):
    p = {"number": 1, "state": "open", "draft": False, "labels": [], "mergeable_state": "behind",
         "base": {"ref": "main"}, "head": {"ref": "claude/x", "sha": "s1", "repo": {"full_name": R}}}
    p.update(kw)
    return p


def test_eligible_happy_path():
    assert bs.eligible(pr(), SELF, ["docs/a.md"], R) == (True, "ok")


def test_every_exclusion():
    f = ["docs/a.md"]
    assert not bs.eligible(pr(draft=True), SELF, f, R)[0]
    assert not bs.eligible(pr(state="closed"), SELF, f, R)[0]
    assert not bs.eligible(pr(base={"ref": "dev"}), SELF, f, R)[0]
    assert not bs.eligible(pr(labels=[{"name": "landing:hold"}]), SELF, f, R)[0]
    assert not bs.eligible(pr(head={"ref": "automation/x", "sha": "s", "repo": {"full_name": R}}), SELF, f, R)[0]
    assert not bs.eligible(pr(head={"ref": "claude/x", "sha": "s", "repo": {"full_name": "fork/r"}}), SELF, f, R)[0]
    assert not bs.eligible(pr(), None, f, R)[0]
    assert not bs.eligible(pr(), {"tier": 1, "landing": "hold"}, f, R)[0]
    assert not bs.eligible(pr(), {"tier": 2, "landing": "self"}, f, R)[0]


def test_declared_tier1_but_touching_tier23_paths_is_not_touched():
    for path in ("config/strategies.yaml", "src/runtime/pipeline.py", "deploy/x.service"):
        assert not bs.eligible(pr(), SELF, ["docs/a.md", path], R)[0]


def test_plan():
    assert [bs.plan(s) for s in ("behind", "dirty", "clean", "blocked", None)] == \
        ["update", "comment", "skip", "skip", "skip"]


class FakeGh:
    repo = R

    def __init__(self, prs, decls, files=None, comments=None):
        self.prs, self.decls, self.files = prs, decls, files or {}
        self.comments = comments or {}
        self.calls = []

    def api(self, method, path, **kw):
        self.calls.append((method, path, kw))
        if path.startswith("pulls?"):
            return [{"number": p["number"]} for p in self.prs]
        if path.endswith("/files?per_page=100"):
            return [{"filename": f} for f in self.files.get(int(path.split("/")[1]), ["docs/a.md"])]
        if path.startswith("pulls/") and method == "GET":
            return next(p for p in self.prs if p["number"] == int(path.split("/")[1]))
        if path.startswith("contents/"):
            raise RuntimeError("n/a")
        if "/comments" in path and method == "GET":
            return self.comments.get(int(path.split("/")[1]), [])
        return None


def run(gh, pat=True):
    bs.landing_decl = lambda g, p: gh.decls.get(p["number"])
    return bs.run(gh, R, pat, sleep=lambda s: None)


def writes(gh):
    return [c for c in gh.calls if c[0] in ("PUT", "POST")]


def test_updates_only_the_behind_eligible_pr_with_expected_sha():
    gh = FakeGh([pr(number=1), pr(number=2, mergeable_state="clean"),
                 pr(number=3, labels=[{"name": "landing:hold"}])],
                {1: SELF, 2: SELF, 3: SELF})
    run(gh)
    assert writes(gh) == [("PUT", "pulls/1/update-branch", {"expected_head_sha": "s1"})]


def test_no_pat_updates_nothing():
    gh = FakeGh([pr()], {1: SELF})
    out = run(gh, pat=False)
    assert out[0].startswith("REFUSED") and gh.calls == []


def test_conflict_comments_once_per_head():
    gh = FakeGh([pr(mergeable_state="dirty")], {1: SELF})
    run(gh)
    assert [w[0] for w in writes(gh)] == ["POST"] and "branch-sync:s1" in writes(gh)[0][2]["body"]
    gh2 = FakeGh([pr(mergeable_state="dirty")], {1: SELF}, comments={1: [{"body": bs.MARKER.format(sha="s1")}]})
    run(gh2)
    assert writes(gh2) == []


def test_per_run_cap_and_422_is_left_alone():
    many = [pr(number=i) for i in range(1, bs.MAX_UPDATES + 3)]
    gh = FakeGh(many, {p["number"]: SELF for p in many})
    run(gh)
    assert len(writes(gh)) == bs.MAX_UPDATES

    class Refuse(FakeGh):
        def api(self, method, path, **kw):
            if method == "PUT":
                raise RuntimeError("422 merge conflict")
            return super().api(method, path, **kw)
    out = run(Refuse([pr()], {1: SELF}))
    assert any("update refused" in line for line in out)


def test_workflow_uses_the_pat_and_a_main_checkout():
    wf = (REPO / ".github/workflows/branch-sync.yml").read_text()
    assert "secrets.BRANCH_PROTECTION_TOKEN" in wf and "ref: main" in wf
    assert "git push" not in wf and "--force" not in wf

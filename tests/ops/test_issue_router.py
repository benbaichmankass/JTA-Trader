"""Issue fan-out fix (PI-20260927-W6OPSR-0004): issue-router.yml + label-routed workflows."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WF = REPO / ".github" / "workflows"
_spec = importlib.util.spec_from_file_location("irm", REPO / "scripts" / "ops" / "issue_router_migrate.py")
irm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(irm)


def _on(doc):
    return doc.get("on", doc.get(True)) or {}


def _routed():
    for p in sorted(WF.glob("*.yml")):
        src = p.read_text(encoding="utf-8")
        if irm.ROUTED_MARK in src:
            yield p, src, yaml.safe_load(src)


def test_router_runs_once_per_opened_issue_and_forwards_every_label():
    doc = yaml.safe_load((WF / irm.ROUTER).read_text(encoding="utf-8"))
    assert _on(doc) == {"issues": {"types": ["opened"]}}
    job = doc["jobs"]["route"]
    assert "if" not in job, "the router must not gate: every label of every issue is forwarded"
    script = job["steps"][0]["with"]["script"]
    assert "createDispatchEvent" in script and "for (const label of labels)" in script
    for field in irm.PAYLOAD_FIELDS:
        assert re.search(rf"\b{field}:", script), f"router payload lacks issue.{field}"


def test_routed_workflows_are_consistent():
    routed = list(_routed())
    assert len(routed) >= 50
    for p, src, doc in routed:
        on = _on(doc)
        assert "issues" not in on, f"{p.name}: routed and still on issues (would double-run)"
        types = sorted(on["repository_dispatch"]["types"])
        assert types == sorted(set(irm.LABEL_RE.findall(src))), f"{p.name}: dispatch types != label conditions"
        assert "github.event.issue." not in src, f"{p.name}: still reads github.event.issue"
        assert not re.search(r"github\.event_name\s*[!=]=\s*['\"]issues['\"]", src), p.name
        for m in re.finditer(r"github\.event\.client_payload\.issue\.([A-Za-z_]+)", src):
            assert m.group(1) in irm.PAYLOAD_FIELDS, f"{p.name}: reads issue.{m.group(1)}, which the router does not send"
        assert not re.search(r"(?<!\?\? )\bcontext\.issue\.number\b(?!\))", src), f"{p.name}: bare context.issue.number"


def test_check_mode_passes_on_the_tree():
    assert irm.main.__module__  # import smoke
    import subprocess, sys
    r = subprocess.run([sys.executable, str(REPO / "scripts/ops/issue_router_migrate.py"), "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_rewrite_keeps_comments_and_routes_by_label():
    src = (
        "name: x\non:\n  workflow_dispatch:\n  issues:\n    # why opened only\n    types: [opened]\n\n"
        "permissions:\n  issues: write\n\njobs:\n  a:\n    if: |\n      github.event_name == 'workflow_dispatch' ||\n"
        "      (github.event_name == 'issues' && github.event.issue.user.login == github.repository_owner &&\n"
        "       contains(github.event.issue.labels.*.name, 'x-request'))\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/github-script@v7\n        with:\n          script: |\n"
        "            await github.rest.issues.createComment({issue_number: context.issue.number, body: 'ok'});\n"
    )
    out = irm.rewrite(src, ["x-request"])
    doc = yaml.safe_load(out)
    assert _on(doc)["repository_dispatch"] == {"types": ["x-request"]}
    assert "issues" not in _on(doc) and "  issues: write" in out and "# why opened only" in out
    assert "github.event_name == 'repository_dispatch'" in out
    assert "github.event.client_payload.issue.user.login" in out
    assert "context.payload.client_payload?.issue?.number ?? context.issue.number" in out


def test_runs_per_issue_drop(tmp_path):
    # Two label-gated workflows on issues:[opened]: before, an issue labelled for one starts both; after, one.
    for name, label in (("a.yml", "a-req"), ("b.yml", "b-req")):
        (tmp_path / name).write_text(
            "on:\n  issues:\n    types: [opened]\njobs:\n  j:\n"
            f"    if: github.event.issue.user.login == github.repository_owner && "
            f"contains(github.event.issue.labels.*.name, '{label}')\n    runs-on: ubuntu-latest\n    steps: [{{run: 'true'}}]\n")
    paths = sorted(str(p) for p in tmp_path.glob("*.yml"))
    before = irm.runs_per_issue({p: irm.classify(p) for p in paths}, ["a-req"])
    for p in paths:
        st, labels, _ = irm.classify(p)
        assert st == "eligible"
        Path(p).write_text(irm.rewrite(Path(p).read_text(), labels))
    after = irm.runs_per_issue({p: irm.classify(p) for p in paths}, ["a-req"])
    assert (before, after) == (2, 1)

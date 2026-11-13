"""Issue fan-out fix (PI-20260927-W6OPSR-0004): issue-router.yml + label-routed workflows."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
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
    assert _on(doc) == {"issues": {"types": ["opened", "labeled"]}}
    job = doc["jobs"]["route"]
    assert "if" not in job, "the router must not gate: every label of every issue is forwarded"
    script = job["steps"][0]["with"]["script"]
    assert "createDispatchEvent" in script and "for (const label of targets)" in script
    for field in irm.PAYLOAD_FIELDS:
        assert re.search(rf"\b{field}:", script), f"router payload lacks issue.{field}"


def test_routed_workflows_are_consistent():
    routed = list(_routed())
    assert len(routed) >= 50
    for p, src, doc in routed:
        on = _on(doc)
        assert "issues" not in on, f"{p.name}: routed and still on issues (would double-run)"
        types = sorted(on["repository_dispatch"]["types"])
        labels = sorted(set(irm.LABEL_RE.findall(src)) | set(irm.LABEL_ADDED_RE.findall(src)))
        assert types in (labels, sorted(labels + [irm.LABELED_PREFIX + lab for lab in labels]),
                         sorted(irm.LABELED_PREFIX + lab for lab in labels)), \
            f"{p.name}: dispatch types != label conditions"
        assert "github.event.issue." not in src, f"{p.name}: still reads github.event.issue"
        assert not re.search(r"github\.event_name\s*[!=]=\s*['\"]issues['\"]", src), p.name
        for m in re.finditer(r"github\.event\.client_payload\.issue\.([A-Za-z_]+)", src):
            assert m.group(1) in irm.PAYLOAD_FIELDS, f"{p.name}: reads issue.{m.group(1)}, which the router does not send"
        assert not re.search(r"(?<!\?\? )\bcontext\.issue\.number\b(?!\))", src), f"{p.name}: bare context.issue.number"


def test_check_mode_passes_on_the_tree():
    assert irm.main.__module__  # import smoke
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


_EVENT_NAME_VARS = re.compile(r"^\s*([A-Z_]+):\s*\$\{\{\s*github\.event_name\s*\}\}", re.M)


def test_routed_workflows_never_branch_on_the_issues_event_name():
    """A routed workflow runs as repository_dispatch, so any branch that tests for 'issues' is dead code that
    silently takes the wrong path (prop-report read the empty dispatch input instead of the issue body).
    Every env var holding github.event_name, inline ${{ github.event_name }} and context.eventName is checked;
    a line that also accepts repository_dispatch is fine."""
    bad = []
    for p, src, _doc in _routed():
        names = set(_EVENT_NAME_VARS.findall(src))
        pats = [r"\$\{\{\s*github\.event_name\s*\}\}", r"context\.eventName"] + [rf"\$\{{?{n}\}}?" for n in names]
        for i, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#") or "repository_dispatch" in line:
                continue
            for pat in pats:
                if re.search(rf"{pat}[\"']?\s*(?:==?=?)\s*[\"']issues[\"']", line):
                    bad.append(f"{p.name}:{i}: {line.strip()}")
    assert not bad, bad


def test_router_forwards_only_the_added_label_on_labeled():
    script = yaml.safe_load((WF / irm.ROUTER).read_text(encoding="utf-8"))["jobs"]["route"]["steps"][0]["with"]["script"]
    assert "'labeled:' + added" in script and "payload.label = { name: added }" in script
    assert "action === 'labeled' ? (added ? ['labeled:' + added] : []) : labels" in script


def test_rewrite_opened_labeled_keeps_both_events_and_fixes_shell_compare():
    src = ("name: x\non:\n  workflow_dispatch:\n  issues:\n    types: [opened, labeled]\njobs:\n  a:\n"
           "    if: github.event_name == 'issues' && contains(github.event.issue.labels.*.name, 'x-req')\n"
           "    runs-on: ubuntu-latest\n    steps:\n      - env:\n          EVENT_NAME: ${{ github.event_name }}\n"
           "        run: |\n          if [ \"${EVENT_NAME}\" = \"issues\" ]; then echo issue; fi\n")
    out = irm.rewrite(src, ["x-req"])
    assert _on(yaml.safe_load(out))["repository_dispatch"] == {"types": ["x-req", "labeled:x-req"]}
    assert '[ "${EVENT_NAME}" = "repository_dispatch" ]' in out and "'issues'" not in out


def test_labeled_only_workflows_key_on_the_added_label():
    """Phase 2b: a labeled-only workflow subscribes to labeled:<label> and reads the label the router forwards."""
    for name, label in (("etf-history-pipeline.yml", "etf-history-request"),
                        ("options-snapshot-capture.yml", "options-snapshot-request")):
        src = (WF / name).read_text(encoding="utf-8")
        assert _on(yaml.safe_load(src))["repository_dispatch"] == {"types": [irm.LABELED_PREFIX + label]}
        assert "github.event.client_payload.label.name" in src and "github.event.label.name" not in src

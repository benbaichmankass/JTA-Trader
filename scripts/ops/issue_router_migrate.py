#!/usr/bin/env python3
# wiring: manual-only - a one-shot migration and report tool run by a session; its --check is exercised by tests/ops/test_issue_router.py
"""Issue fan-out fix (row PI-20260927-W6OPSR-0004): route issue-triggered workflows by label.

Why: every opened issue starts one run of EVERY workflow declaring `on: issues: [opened]` (75 on 2026-11-11), plus one
per `labeled` workflow per label. A job-level `if:` that is false still creates and queues the run, so one
`system-action: send-ping` issue queued ~89 runs, of which 82-83 had every job evaluate false (measured 2026-11-11 on
the three send-ping issues #24955/#24957/#24958). The Actions queue sat at ~475.

Fix (adds no gate): `.github/workflows/issue-router.yml` runs once per opened issue and sends one
`repository_dispatch` per label on it (event_type = the label, client_payload.issue = the same fields the workflows
already read). A migrated workflow declares `repository_dispatch: types: [<its labels>]` instead of `issues: [opened]`,
so GitHub creates a run only for the workflows the issue's labels name. Every job condition is kept: the author
check, the label check and the workflow_dispatch path read the same values, from client_payload instead of the issue
event. Nothing that ran before stops running; only runs that could never do anything are no longer created.

Eligible: `on: issues: types: [opened]` exactly, at least one `contains(github.event.issue.labels.*.name, '<label>')`,
and no reliance on anything the dispatch would change. Excluded workflows use one of these: a title or body
condition (that path has no label to route on), github.event.action, github.actor / triggering_actor / sender (these
would read github-actions[bot] under a dispatch), GITHUB_EVENT_NAME / GITHUB_EVENT_PATH / toJSON(github.event), or a
context.payload field other than the issue, or a job on the self-hosted runner. Excluded workflows stay on `issues` and keep working unchanged.

    python3 scripts/ops/issue_router_migrate.py            # report: eligible / excluded and runs per issue
    python3 scripts/ops/issue_router_migrate.py --apply    # rewrite the eligible workflows in place
    python3 scripts/ops/issue_router_migrate.py --check    # exit 1 if any workflow is half-migrated (CI)
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import yaml

WF_DIR = ".github/workflows"
ROUTER = "issue-router.yml"
ROUTED_MARK = "# routed by issue-router.yml"
#: Phase 2 (PI-20261112-FANOUT2-0001): the router also forwards each `labeled` event as `labeled:<added label>`.
LABELED_PREFIX = "labeled:"
LABEL_ADDED_RE = re.compile(r"github\.event\.(?:client_payload\.)?label\.name\s*==\s*'([^']+)'")
EVENT_NAME_VARS = re.compile(r"^\s*([A-Z_]+):\s*\$\{\{\s*github\.event_name\s*\}\}", re.M)
SHELL_EVENT_CMP = re.compile(r"(\$\{?EVENT_NAME\}?[\"']?\s*==?\s*)([\"'])issues\2")

LABEL_RE = re.compile(r"contains\(\s*github\.event\.(?:client_payload\.)?issue\.labels\.\*\.name\s*,\s*'([^']+)'\s*\)")
ISSUE_REF_OK = re.compile(r"github\.event\.issue\.(number|title|body|labels\.\*\.name|user\.login|html_url|state)\b")
EXCLUDE = [
    (re.compile(r"github\.event\.action"), "reads github.event.action"),
    (re.compile(r"github\.(?:actor|triggering_actor)\b|github\.event\.sender"), "reads the actor/sender"),
    (re.compile(r"GITHUB_EVENT_NAME|GITHUB_EVENT_PATH|toJSON\(\s*github\.event\s*\)"), "reads the raw event"),
    (re.compile(r"context\.payload\.(?!issue\b)"), "reads a non-issue context.payload field"),
]
#: The client_payload.issue fields the router sends; a migrated workflow may read only these.
PAYLOAD_FIELDS = ("number", "title", "body", "labels", "user", "html_url", "state")


def _on(y: dict):
    return y.get("on", y.get(True)) or {}


def _job_ifs(y: dict) -> list[str]:
    return [str(j.get("if") or "") for j in (y.get("jobs") or {}).values() if isinstance(j, dict)]


def classify(path: str) -> tuple[str, list[str], str]:
    """Return (state, labels, reason): state is eligible | migrated | excluded | not_issue."""
    src = open(path, encoding="utf-8").read()
    try:
        y = yaml.safe_load(src) or {}
    except yaml.YAMLError as exc:
        return "excluded", [], f"yaml error: {exc}"
    on = _on(y)
    if not isinstance(on, dict):
        return "not_issue", [], ""
    if os.path.basename(path) == ROUTER:
        return "router", [], ""
    labels = sorted(set(LABEL_RE.findall(src)))
    rd = on.get("repository_dispatch")
    if isinstance(rd, dict) and any(str(t).startswith(LABELED_PREFIX) for t in (rd.get("types") or [])):
        labels = sorted(set(labels) | set(LABEL_ADDED_RE.findall(src)))   # phase 2b keys on the added label
    if ROUTED_MARK in src and isinstance(rd, dict):
        return "migrated", labels, ""
    iss = on.get("issues")
    if iss is None and "issues" not in on:
        return "not_issue", [], ""
    if isinstance(iss, dict) and iss.get("types") == ["labeled"]:
        # phase 2b: a labeled-only workflow keys on the ADDED label (github.event.label.name == '<x>')
        labels = sorted(set(labels) | set(LABEL_ADDED_RE.findall(src)))
    elif not (isinstance(iss, dict) and iss.get("types") in (["opened"], ["opened", "labeled"])):
        return "excluded", labels, f"issues types {iss.get('types') if isinstance(iss, dict) else iss} (not [opened])"
    if not labels:
        return "excluded", labels, "no label condition (title-prefix gate)"
    if any(re.search(r"github\.event\.issue\.(title|body)", c) for c in _job_ifs(y)):
        return "excluded", labels, "a job if: reads the issue title/body"
    if any(m in str(j.get("runs-on", "")) for j in (y.get("jobs") or {}).values() if isinstance(j, dict)
           for m in ("self-hosted", "jta-infra", "INFRA_RUNS_ON")):
        # tests/test_self_hosted_runner_guard.py lists the triggers allowed on the self-hosted runner (operator popup
        # 2026-11-03); repository_dispatch is not on it, and widening that list is not this tool's call.
        return "excluded", labels, "runs on the self-hosted runner (trigger allowlist in test_self_hosted_runner_guard)"
    for rx, why in EXCLUDE:
        if rx.search(src):
            return "excluded", labels, why
    odd = {m.group(0) for m in re.finditer(r"github\.event\.issue\.[A-Za-z_.*]+", src)} - \
          {m.group(0) for m in ISSUE_REF_OK.finditer(src)}
    odd = {o for o in odd if not ISSUE_REF_OK.match(o)}
    if odd:
        return "excluded", labels, f"reads issue fields the router does not send: {sorted(odd)}"
    return "eligible", labels, ""


def rewrite(src: str, labels: list[str]) -> str:
    """Rewrite one eligible workflow. Pure text edits, so comments and layout are kept."""
    m = re.search(r"^on:[^\n]*\n((?:[ \t]+[^\n]*\n|[ \t]*\n)*)", src, re.M)
    if not m:
        raise ValueError("no top-level on: block")
    block = m.group(0)
    def _types(mm):
        # [opened] -> one dispatch per label at open. [opened, labeled] -> also `labeled:<label>`, the router's
        # forward of each labeled event, so the workflow runs on exactly the events it ran on before.
        shape = mm.group(4).replace(" ", "")
        if shape == "opened,labeled":
            return labels + [LABELED_PREFIX + lab for lab in labels]
        if shape == "labeled":
            return [LABELED_PREFIX + lab for lab in labels]
        return labels
    new_block, n = re.subn(
        r"^([ \t]+)issues:[ \t]*\n((?:\1[ \t]+#[^\n]*\n)*)\1([ \t]+)types:[ \t]*\[(opened|opened,[ \t]*labeled|labeled)\][ \t]*\n",
        lambda mm: (f"{mm.group(1)}repository_dispatch:  {ROUTED_MARK} (one dispatch per issue label)\n"
                    f"{mm.group(2)}{mm.group(1)}{mm.group(3)}types: [{', '.join(_types(mm))}]\n"),
        block, count=1, flags=re.M)
    if n != 1:
        raise ValueError("could not find `issues: types: [opened]` or `[opened, labeled]` in the on: block")
    out = src[:m.start()] + new_block + src[m.end():]
    out = out.replace("github.event.issue.", "github.event.client_payload.issue.")
    out = re.sub(r"(github\.event_name\s*[!=]=\s*)(['\"])issues\2", r"\1\2repository_dispatch\2", out)
    # a step that passes github.event_name into the shell and compares it there (cutover-live, reserve-live-ip)
    out = SHELL_EVENT_CMP.sub(r"\1\2repository_dispatch\2", out)
    for var in set(EVENT_NAME_VARS.findall(out)):     # any env var holding github.event_name (EVENT, EV, ...)
        out = re.sub(r"(\$\{?" + var + r"\}?[\"']?\s*==?\s*)([\"'])issues\2", r"\1\2repository_dispatch\2", out)
    out = out.replace("github.event.label.name", "github.event.client_payload.label.name")
    out = re.sub(r"\bcontext\.issue\.number\b",
                 "(context.payload.client_payload?.issue?.number ?? context.issue.number)", out)
    out = re.sub(r"\bcontext\.payload\.issue\b", "context.payload.client_payload.issue", out)
    return out


def runs_per_issue(states: dict[str, tuple[str, list[str], str]], labels_on_issue: list[str]) -> int:
    """Workflow runs GitHub creates for one opened issue carrying `labels_on_issue` (one labeled event per label)."""
    n = 0
    k = len(labels_on_issue)
    for path in states:
        y = yaml.safe_load(open(path, encoding="utf-8")) or {}
        on = _on(y)
        if not isinstance(on, dict):
            continue
        iss = on.get("issues", "__absent__")
        if iss != "__absent__":
            types = (iss or {}).get("types") if isinstance(iss, dict) else None
            types = types or ["opened", "edited", "deleted", "transferred", "pinned", "unpinned", "closed",
                              "reopened", "assigned", "unassigned", "labeled", "unlabeled", "locked", "unlocked",
                              "milestoned", "demilestoned"]
            n += ("opened" in types) + k * ("labeled" in types)
        rd = on.get("repository_dispatch")
        if isinstance(rd, dict) and os.path.basename(path) != ROUTER:
            types = rd.get("types") or []
            n += sum(1 for lab in labels_on_issue if lab in types)
            n += sum(1 for lab in labels_on_issue if LABELED_PREFIX + lab in types)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dir", default=WF_DIR)
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(a.dir, "*.yml")) + glob.glob(os.path.join(a.dir, "*.yaml")))
    states = {p: classify(p) for p in paths}
    bad = []
    for p, (st, labels, _) in states.items():
        src = open(p, encoding="utf-8").read()
        if st == "migrated":
            y = yaml.safe_load(src)
            types = sorted((_on(y).get("repository_dispatch") or {}).get("types") or [])
            if types not in (labels, sorted(labels + [LABELED_PREFIX + lab for lab in labels]),
                             sorted(LABELED_PREFIX + lab for lab in labels)):
                bad.append(f"{p}: repository_dispatch types {types} != label conditions {labels}")
            if re.search(r"github\.event\.issue\.|github\.event_name\s*[!=]=\s*['\"]issues['\"]", src) \
                    or SHELL_EVENT_CMP.search(src):
                bad.append(f"{p}: routed but still reads the issues event")
    if a.check:
        if not os.path.exists(os.path.join(a.dir, ROUTER)) and any(s[0] == "migrated" for s in states.values()):
            bad.append(f"{ROUTER} is missing but workflows are routed through it")
        for b in bad:
            print("FAIL", b)
        print(f"issue-router check: {sum(s[0] == 'migrated' for s in states.values())} routed, {len(bad)} problem(s)")
        return 1 if bad else 0
    if a.apply:
        for p, (st, labels, _) in states.items():
            if st == "eligible":
                with open(p, encoding="utf-8") as fh:
                    src = fh.read()
                try:
                    out = rewrite(src, labels)          # compute first: a failed rewrite must leave the file untouched
                    yaml.safe_load(out)
                except (ValueError, yaml.YAMLError) as exc:
                    print("skip", os.path.basename(p), exc)
                    continue
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(out)
                print("routed", os.path.basename(p), labels)
        states = {p: classify(p) for p in paths}
    by = {}
    for p, (st, labels, why) in states.items():
        by.setdefault(st, []).append((os.path.basename(p), labels, why))
    for st in ("eligible", "migrated", "excluded"):
        print(f"{st}: {len(by.get(st, []))}")
        if st == "excluded":
            for name, labels, why in by.get(st, []):
                print(f"  {name}: {why}")
    for labs in (["system-action"], ["vm-diag-request"], ["a-label-nothing-listens-to"]):
        print(f"runs created per opened issue labelled {labs}: {runs_per_issue(states, labs)}")
    for b in bad:
        print("PROBLEM", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Pick the concurrency group a system-action run waits in (OA-17, 2026-10-04).

WHY THIS EXISTS. system-actions.yml used ONE workflow-level concurrency group
("system-actions") for every issue-triggered run. GitHub keeps only ONE pending
run per group: a newer request silently CANCELS the older pending one, its
issue stays open with no comment, and nobody is told. Measured 2026-10-04:
#16251 (breakout_1 executor-disable-timer, an OA-03 de-risk step) and #16263
(tradeify_1 executor-enable-timer) were both dropped that way.

THE RULE.
  * A READ-ONLY action gets a group of its own (``system-actions-ro-<run_id>``):
    it can neither displace nor be displaced by anything, and two reads never
    race on a VM resource.
  * Every other action stays in the shared ``system-actions`` group, so two
    mutations on the VM still never run at once. That lane can still drop a
    pending run (GitHub's one-pending limit), which is why
    scripts/ops/system_action_cancel_guard.py exists: it comments
    "CANCELLED, NOT RUN" on the issue and alerts. It never re-queues -- that
    would run the older request after the newer one that displaced it.

REPORT-ONLY SINCE 2026-11-12 (decision: operator 2026-11-12 decisions page,
Gates tab -- SYSTEM-ACTION-CONCURRENCY-LANES: MAKE REPORT-ONLY). The shared
mutating lane queued and dropped runs, so it is gone: EVERY action now gets a
group of its own (``system-actions-<run_id>`` for a mutation,
``system-actions-ro-<run_id>`` for a read), so no run waits behind another and
none is displaced. Overlap is REPORTED instead: the workflow's ``route`` job
lists other system-actions runs in flight (:func:`overlap_report`) and warns +
comments on the request issue. The cost the operator accepted: two mutations can
now run on the VM at once; the report says when they did.

READ_ONLY is an explicit allowlist, never a pattern: an action not named here is
treated as mutating (fail toward serialisation). Adding one is a reviewed edit;
each entry below is documented read-only in docs/claude/system-actions.md.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

SHARED_GROUP = "system-actions"

READ_ONLY = frozenset({
    "status-check",
    "list-listening-ports",
    "gateway-logs",
    "gateway-forensics",
    "gateway-disk-report",
    "pull-latest-logs",
    "inspect-insights",
    "net-r-regrade",
    "verify-account-mode",
    "get-env",
})

_ACTION_LINE = re.compile(r"^\s*action\s*:\s*(.*)$", re.IGNORECASE)


def action_from_issue_body(body: str) -> str:
    """The first ``action:`` line, whitespace removed -- the same parse as the
    workflow's 'Resolve action + reason' step (grep -i -m1 ... | tr -d space)."""
    for line in (body or "").splitlines():
        m = _ACTION_LINE.match(line)
        if m:
            return re.sub(r"\s+", "", m.group(1))
    return ""


def concurrency_group(action: str, run_id: str) -> str:
    """A group of its own for every run, so nothing queues (report-only, 2026-11-12)."""
    if action in READ_ONLY:
        return f"{SHARED_GROUP}-ro-{run_id}"
    return f"{SHARED_GROUP}-{run_id}"


def overlap_report(runs: list, run_id: str) -> list[str]:
    """Lines naming OTHER system-actions runs in flight (queued/in_progress).

    ``runs`` is the ``workflow_runs`` list from the Actions API. Reports only;
    the caller never waits, cancels or fails on it.
    """
    out = []
    for r in runs or []:
        if str(r.get("id")) == str(run_id):
            continue
        if r.get("status") not in ("queued", "in_progress", "waiting", "pending", "requested"):
            continue
        out.append(f"run {r.get('id')} ({r.get('status')}): {r.get('display_title') or ''} "
                   f"{r.get('html_url') or ''}".rstrip())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--overlap-from", default=None,
                    help="JSON file of the Actions API runs list: print overlap lines and exit 0")
    args = ap.parse_args(argv)
    if args.overlap_from:
        import json
        try:
            with open(args.overlap_from, encoding="utf-8") as fh:
                runs = (json.load(fh) or {}).get("workflow_runs") or []
        except (OSError, ValueError) as exc:
            print(f"overlap: could not look ({exc})")
            return 0
        for line in overlap_report(runs, args.run_id):
            print(line)
        return 0
    if args.event == "workflow_dispatch":
        action = (os.environ.get("DISPATCH_ACTION") or "").strip()
    else:
        action = action_from_issue_body(os.environ.get("ISSUE_BODY") or "")
    group = concurrency_group(action, args.run_id)
    print(f"action={action}")
    print(f"group={group}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

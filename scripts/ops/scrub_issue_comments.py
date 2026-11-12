#!/usr/bin/env python3
"""Scrub sensitive values out of this repo's existing issue/PR comments (HEALTH-20261111-IB-ACCTID-PUBLIC).

Operator decisions w17 / x4 (2026-11-12): clean the bot comments that carry IBKR account ids. This tool
finds them and produces the redacted bodies with the SAME rule set the diag relays use
(scripts/ops/redact_diag_output.py), so the old comments end up exactly as new relay comments are written.

It never writes a comment body or a matched value to stdout/stderr or to the repo:
  list   scan comments, print one JSON line per match: {"id","url","author","counts"}  (no body)
  plan   for the ids in --ids, print the PATCH bodies {"id","body"} (redacted) to a LOCAL file (-o)
  apply  PATCH those ids with their redacted bodies; needs --yes. Re-reads each comment first and
         skips any whose redaction is now a no-op (idempotent).
Requires the `gh` CLI (authenticated). GitHub's REST API cannot delete a comment's edit-history
revisions; that part of x4 is a UI action and is NOT done here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import redact_diag_output as rdo  # noqa: E402


def redact_with(text: str, rules: set[str]) -> tuple[str, dict[str, int]]:
    """Apply only the named rules from redact_diag_output.RULES (same replacement tokens)."""
    counts: dict[str, int] = {}
    for name, rx in rdo.RULES:
        if name not in rules:
            continue
        repl = (lambda m: m.group(1) + "[REDACTED:account_balance]") if name == "account_balance" else f"[REDACTED:{name}]"
        text, n = rx.subn(repl, text)
        if n:
            counts[name] = n
    return text, counts


def _gh(args: list[str], stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True).stdout


def _repo() -> str:
    return _gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()


def iter_comments(repo: str, since: str | None, max_pages: int):
    for page in range(1, max_pages + 1):
        q = ["api", "-X", "GET", f"repos/{repo}/issues/comments", "-f", "per_page=100", "-f", f"page={page}",
             "-f", "sort=created", "-f", "direction=asc"]
        if since:
            q += ["-f", f"since={since}"]
        batch = json.loads(_gh(q) or "[]")
        if not batch:
            return
        yield from batch


def cmd_list(a) -> int:
    rules, authors = set(a.rules), set(a.authors)
    repo, n = a.repo or _repo(), 0
    for c in iter_comments(repo, a.since, a.max_pages):
        if authors and (c.get("user") or {}).get("login") not in authors:
            continue
        _, counts = redact_with(c.get("body") or "", rules)
        if counts:
            n += 1
            print(json.dumps({"id": c["id"], "url": c.get("html_url"), "author": (c.get("user") or {}).get("login"),
                              "counts": counts}))
    print(f"matched {n} comment(s)", file=sys.stderr)
    return 0


def _ids(path: str) -> list[int]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(int(json.loads(line)["id"]) if line.startswith("{") else int(line))
    return out


def cmd_plan(a) -> int:
    repo, rules = a.repo or _repo(), set(a.rules)
    with open(a.out, "w", encoding="utf-8") as fh:
        for cid in _ids(a.ids):
            c = json.loads(_gh(["api", f"repos/{repo}/issues/comments/{cid}"]))
            body, counts = redact_with(c.get("body") or "", rules)
            fh.write(json.dumps({"id": cid, "counts": counts, "body": body}) + "\n")
    print(f"wrote PATCH bodies to {a.out} (LOCAL file; do not commit it)", file=sys.stderr)
    return 0


def cmd_apply(a) -> int:
    if not a.yes:
        print("refusing: apply needs --yes", file=sys.stderr)
        return 2
    repo, rules, done, skipped = a.repo or _repo(), set(a.rules), 0, 0
    for cid in _ids(a.ids):
        c = json.loads(_gh(["api", f"repos/{repo}/issues/comments/{cid}"]))
        body, counts = redact_with(c.get("body") or "", rules)
        if not counts:
            skipped += 1
            continue
        _gh(["api", "-X", "PATCH", f"repos/{repo}/issues/comments/{cid}", "--input", "-"], stdin=json.dumps({"body": body}))
        done += 1
        print(json.dumps({"id": cid, "patched": True, "counts": counts}))
    print(f"patched {done}, already clean {skipped}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", help="owner/name (default: gh repo view)")
    p.add_argument("--rules", nargs="+", default=["ib_account_id"], choices=[n for n, _ in rdo.RULES])
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list")
    pl.add_argument("--authors", nargs="*", default=["github-actions[bot]"], help="empty = any author")
    pl.add_argument("--since", help="ISO time: only comments updated at/after it")
    pl.add_argument("--max-pages", type=int, default=2000)
    pp = sub.add_parser("plan")
    pp.add_argument("--ids", required=True, help="file: one id per line, or the JSON lines `list` printed")
    pp.add_argument("-o", "--out", required=True)
    pa = sub.add_parser("apply")
    pa.add_argument("--ids", required=True)
    pa.add_argument("--yes", action="store_true")
    a = p.parse_args(argv)
    return {"list": cmd_list, "plan": cmd_plan, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())

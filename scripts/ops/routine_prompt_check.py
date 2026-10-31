#!/usr/bin/env python3
"""Stale-reference check for routine (trigger) prompts. Tier 1, read-only, advisory.

Input: the JSON of the claude.ai `list_triggers` tool (one page, or several pages
concatenated as {"data": [...]} objects / a bare list), from a file or stdin.
Flags every ENABLED routine whose prompt names
  (a) a specific session id (session_<20+ alnum>) where the routine should resolve
      the current manager by title ('Manager Session YYYY-MM-DD<letter>'), or
  (b) an old repo name used as a GitHub slug / source_url (ict-trading-bot,
      metis-insights) -- NOT the runtime identifiers CLAUDE.md § Repo identity keeps
      (VM dirs /home/ubuntu/ict-trading-bot, /opt/ict-trading-bot, unit names,
      ict-bot.duckdns.org) and NOT a bare historical mention like
      "renamed from Metis-Insights".

Not a gate: exit code is always 0 unless the input is unreadable. The outgoing
manager runs it at rotation (manager skill § Manager handover) and repoints.
A pending one-shot (run_once_at set) is reported as kind=one_shot_pending; a fired
one-shot (no cron, no run_once_at) can never fire again and is kind=one_shot_fired.
"""
from __future__ import annotations

import json
import re
import sys

SESSION_RE = re.compile(r"session_[A-Za-z0-9]{20,}")
# old name only counts when it is a GitHub slug: owner/<old> or github.com/.../<old>
OLD_SLUG_RE = re.compile(
    r"(?:github\.com/[\w.-]+/|\b[\w.-]+/)(ict-trading-bot|metis-insights)\b", re.I
)
# runtime identifiers that deliberately keep old names (CLAUDE.md § Repo identity)
RUNTIME_OK_RE = re.compile(
    r"(/home/ubuntu/ict-trading-bot|/opt/ict-trading-bot|ict-bot\.duckdns\.org)", re.I
)


def _entries(doc):
    if isinstance(doc, list):
        out = []
        for d in doc:
            out.extend(_entries(d))
        return out
    if isinstance(doc, dict):
        if "data" in doc and isinstance(doc["data"], list):
            return doc["data"]
        return [doc]
    return []


def _prompt(t):
    return ((t.get("derived_state") or {}).get("prompt")) or t.get("prompt") or ""


def _kind(t):
    if t.get("cron_expression"):
        return "recurring"
    return "one_shot_pending" if t.get("run_once_at") else "one_shot_fired"


def check(doc):
    entries = _entries(doc)
    enabled = [t for t in entries if t.get("enabled")]
    flagged = []
    for t in enabled:
        p = _prompt(t)
        scrubbed = RUNTIME_OK_RE.sub("", p)
        sessions = sorted(set(SESSION_RE.findall(p)))
        slugs = sorted({m.group(1).lower() for m in OLD_SLUG_RE.finditer(scrubbed)})
        if sessions or slugs:
            flagged.append({"id": t.get("id"), "name": t.get("name"), "kind": _kind(t),
                            "session_ids": sessions, "old_slugs": slugs})
    return {"n_total": len(entries), "n_checked": len(enabled), "n_flagged": len(flagged),
            "flagged": flagged}


def main(argv):
    src = open(argv[1]).read() if len(argv) > 1 and argv[1] != "-" else sys.stdin.read()
    dec, docs, i = json.JSONDecoder(), [], 0
    src = src.strip()
    while i < len(src):
        obj, j = dec.raw_decode(src, i)
        docs.append(obj)
        i = j
        while i < len(src) and src[i].isspace():
            i += 1
    res = check(docs)
    print(f"routine_prompt_check: checked {res['n_checked']} enabled of {res['n_total']} read; flagged {res['n_flagged']}")
    for f in res["flagged"]:
        print(f"  {f['id']} [{f['kind']}] {f['name']!r} sessions={f['session_ids']} old_slugs={f['old_slugs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-PACKET-REDESIGN on each judge subagent transcript; no schedule consumes it.
"""Isolation audit of one judge-subagent transcript: tool calls (name + path) and token usage. Prints no content.

usage: desk_packet_isolation_audit.py TRANSCRIPT.jsonl BATCH_FILE OUT_FILE

A batch is compliant only if every tool call is Read on BATCH_FILE or Write on OUT_FILE (the harness's own
SubagentHandback is allowed). Usage is summed once per assistant message id; dollars are API-equivalent at Sonnet
list price (input 3, cache write 3.75, cache read 0.30, output 15 per million tokens).
"""
import json
import sys

USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
PRICE = {"input_tokens": 3.0, "cache_creation_input_tokens": 3.75, "cache_read_input_tokens": 0.3, "output_tokens": 15.0}


def audit(path: str, batch_file: str, out_file: str) -> dict:
    calls, bad, seen = [], [], set()
    usage = {k: 0 for k in USAGE_KEYS}
    unparsed = 0
    with open(path) as fh:
        for ln in fh:
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                unparsed += 1          # counted and reported, never silently dropped
                continue
            m = r.get("message") or {}
            if m.get("role") != "assistant":
                continue
            mid = m.get("id")
            if mid and mid not in seen and m.get("usage"):
                seen.add(mid)
                for k in USAGE_KEYS:
                    usage[k] += int(m["usage"].get(k) or 0)
            for c in m.get("content") or []:
                if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                    continue
                n, i = c.get("name"), c.get("input") or {}
                p = i.get("file_path") or i.get("path") or i.get("command") or i.get("pattern")
                calls.append((n, p))
                if n != "SubagentHandback" and not ((n == "Read" and p == batch_file) or (n == "Write" and p == out_file)):
                    bad.append((n, str(p)[:120]))
    usd = sum(usage[k] * PRICE[k] for k in USAGE_KEYS) / 1e6
    return {"calls": len(calls), "by_tool": {n: sum(1 for x in calls if x[0] == n) for n in sorted({x[0] for x in calls})},
            "violations": bad, "unparsed_lines": unparsed, "usage": usage, "usd_api_equiv_sonnet": round(usd, 3),
            "compliant": not bad}


if __name__ == "__main__":
    print(json.dumps(audit(sys.argv[1], sys.argv[2], sys.argv[3])))

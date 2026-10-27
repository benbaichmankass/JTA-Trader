#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-PACKET-REDESIGN on each judge subagent transcript; no schedule consumes it.
# usage: desk_packet_isolation_audit.py TRANSCRIPT.jsonl BATCH_FILE OUT_FILE
"""Isolation audit of one judge-subagent transcript: tool calls (name + path) and token usage. Prints no content."""
import json, sys
path, batch_file, out_file = sys.argv[1], sys.argv[2], sys.argv[3]
calls, bad, usage, msgs = [], [], {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}, set()
for ln in open(path):
    try: r = json.loads(ln)
    except Exception: continue
    m = r.get("message") or {}
    if m.get("role") == "assistant":
        mid = m.get("id")
        if mid and mid not in msgs and m.get("usage"):
            msgs.add(mid)
            for k in usage: usage[k] += int(m["usage"].get(k) or 0)
        for c in m.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                n, i = c.get("name"), c.get("input") or {}
                p = i.get("file_path") or i.get("path") or i.get("command") or i.get("pattern")
                calls.append((n, p))
                if n != "SubagentHandback" and not ((n == "Read" and p == batch_file) or (n == "Write" and p == out_file)):
                    bad.append((n, str(p)[:120]))
usd = (usage["input_tokens"] * 3 + usage["cache_creation_input_tokens"] * 3.75 + usage["cache_read_input_tokens"] * 0.3 + usage["output_tokens"] * 15) / 1e6
print(json.dumps({"calls": len(calls), "by_tool": {n: sum(1 for x in calls if x[0] == n) for n in {x[0] for x in calls}},
                  "violations": bad, "usage": usage, "usd_api_equiv_sonnet": round(usd, 3), "compliant": not bad}))

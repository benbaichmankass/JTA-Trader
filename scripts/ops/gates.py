#!/usr/bin/env python3
"""Gate registry CLI for sessions (lane GATE-REGISTRY, operator 2026-11-12).

Reads the live registry over ``GET /api/bot/gates`` (the env proxy authenticates requests to the bot host), or
the local ``trade_journal.db`` with ``--local``. Gates this adds or changes: none (read-only, except
``refresh --local``, which writes only the registry's own tables on the box it runs on).

    python3 scripts/ops/gates.py list [--category C] [--decision D] [--state S] [--real-money true|false] [--json]
    python3 scripts/ops/gates.py show <GATE-ID> [--json]
    python3 scripts/ops/gates.py changed --since 2026-11-12T13:00:00Z     # decisions the manager has to act on
    python3 scripts/ops/gates.py todo                                     # decided remove/report_only, not implemented
    python3 scripts/ops/gates.py refresh --local                          # re-scan this tree into the local DB

Nulls print as "—". A read that fails prints its read-state and exits 2; it never prints an empty list as "0 gates".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DEFAULT_BASE = os.environ.get("BOT_API_BASE", "https://ict-bot.duckdns.org")


def _dash(v) -> str:
    return "—" if v is None or v == "" else str(v)


def _fetch(path: str, params: dict) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{DEFAULT_BASE}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "gates-cli"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        return {"readState": "unreadable", "error": f"HTTP {exc.code}: {body}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"readState": "unreadable", "error": str(exc)}


def _local_list(params: dict) -> dict:
    from src.runtime import gate_registry as gr
    conn = gr.connect()
    try:
        out = gr.list_gates(conn, category=params.get("category"), decision=params.get("decision"),
                            state=params.get("state"), real_money=params.get("real_money"),
                            decided_since=params.get("decided_since"))
        return {"readState": "read", **out, "refresh": gr.last_refresh(conn)}
    finally:
        conn.close()


def _list(args, extra: dict | None = None) -> dict:
    params = {"category": getattr(args, "category", None), "decision": getattr(args, "decision", None),
              "state": getattr(args, "state", None), "real_money": getattr(args, "real_money", None)}
    params.update(extra or {})
    return _local_list(params) if args.local else _fetch("/api/bot/gates", params)


def _print_rows(doc: dict) -> None:
    pop = doc.get("population") or {}
    ref = doc.get("refresh") or {}
    print(f"population: {_dash(pop.get('returned'))} of {_dash(pop.get('total'))} rows — {_dash(pop.get('description'))}")
    print(f"refresh: {_dash(ref.get('at'))} at {_dash(ref.get('head_sha'))} ({_dash(ref.get('read_state'))})"
          + (f" error: {ref['error']}" if ref.get("error") else ""))
    print(f"counts: {json.dumps(doc.get('counts'))}")
    for g in doc.get("gates") or []:
        flag = f"[{g['drift']}] " if g.get("drift") else ""
        impl = g.get("implementation_state")
        if g.get("implementation_pr") or g.get("implementation_sha"):
            impl += f" #{_dash(g.get('implementation_pr'))} {_dash(g.get('implementation_sha'))}"
        print(f"{flag}{g['id']:<44} {_dash(g.get('category')):<20} rm={_dash(g.get('real_money')):<5} "
              f"decision={g.get('operator_decision'):<11} impl={impl:<14} mode={_dash(g.get('mode_in_code')):<11} "
              f"hits14d={_dash(g.get('hits_14d'))}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--local", action="store_true", help="read/write the local trade_journal.db instead of the API")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "todo", "changed"):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        if name == "list":
            p.add_argument("--category")
            p.add_argument("--decision", choices=["keep", "remove", "report_only", "undecided"])
            p.add_argument("--state", choices=["as_is", "pending", "implemented", "unregistered", "drift"])
            p.add_argument("--real-money", dest="real_money", choices=["true", "false"])
        if name == "changed":
            p.add_argument("--since", required=True, help="ISO time; decisions recorded at/after it")
    s = sub.add_parser("show")
    s.add_argument("gate_id")
    s.add_argument("--json", action="store_true")
    sub.add_parser("refresh")
    args = ap.parse_args(argv)

    if args.cmd == "refresh":
        if not args.local:
            print("refresh runs on the box that holds the DB: pass --local (the live registry refreshes itself "
                  "on a deploy / hourly).", file=sys.stderr)
            return 2
        from src.runtime import gate_registry as gr
        print(json.dumps(gr.refresh(), indent=1))
        return 0

    if args.cmd == "show":
        if args.local:
            from src.runtime import gate_registry as gr
            conn = gr.connect()
            try:
                found = gr.get_gate(conn, args.gate_id)
            finally:
                conn.close()
            doc = {"readState": "read", **found} if found else {"readState": "read", "error": "not found"}
        else:
            doc = _fetch(f"/api/bot/gates/{urllib.parse.quote(args.gate_id)}", {})
        print(json.dumps(doc, indent=1))  # one shape for show; --json kept for symmetry
        return 0 if doc.get("readState") == "read" and doc.get("gate") else 2

    extra = {"decided_since": args.since} if args.cmd == "changed" else {}
    doc = _list(args, extra)
    if doc.get("readState") != "read":
        print(f"readState={doc.get('readState')} error={doc.get('error')}", file=sys.stderr)
        return 2
    if args.cmd == "todo":
        doc["gates"] = [g for g in doc.get("gates") or []
                        if g.get("operator_decision") in ("remove", "report_only")
                        and g.get("implementation_state") != "implemented"]
        doc.setdefault("population", {})["returned"] = len(doc["gates"])
    if args.json:
        print(json.dumps(doc, indent=1))
    else:
        _print_rows(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Read-only MCP server (streamable HTTP, JSON responses) for the JTA management console.

Run:  python -m src.console_connector.server   (binds 127.0.0.1:${CONSOLE_CONNECTOR_PORT:-8765})

Every tool is read-only (annotations readOnlyHint: true) and reads PUBLIC repo files on the
host's git checkout, through one shared TTL cache (gate G2: each tool is rebuilt at most once
per TTL however many viewers call it). It serves no journal, P&L, balance or alert data; those
wait for the connector's sign-in (G1, docs/plans/UI-TWO-SURFACE-DESIGN-2026-11.md § 2).
Each request is logged (method, tool, user-agent, duration) to runtime_logs/console_connector.jsonl.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from pathlib import Path
from typing import Any

from src.console_connector import data

REPO = Path(os.environ.get("CONSOLE_CONNECTOR_REPO") or Path(__file__).resolve().parents[2])
LOG = Path(os.environ.get("CONSOLE_CONNECTOR_LOG") or REPO / "runtime_logs" / "console_connector.jsonl")
PROTOCOL_DEFAULT = "2025-06-18"
CACHE = data.TTLCache()
TTL_S = {"work_rows": 30.0, "inbox": 30.0, "work_items": 30.0}
N_CALLS = {"n": 0}

_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
TOOLS: list[dict[str, Any]] = [
    {"name": "hello", "title": "Hello",
     "description": "Connectivity check: returns a greeting and the server clock. No data.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"},
                                                       "client_sent_ms": {"type": "number"}}},
     "annotations": _RO},
    {"name": "work_rows", "title": "Work rows",
     "description": "Checklist rows for the console Work tab, in sections due (overdue), in_flight, blocked "
                    "and queued (with a due date). Each response has as_of, read_state, population and the "
                    "git commit the register was read at.",
     "inputSchema": {"type": "object", "properties": {
         "view": {"type": "string", "enum": ["all", "due", "in_flight", "blocked", "queued"], "default": "all"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}},
     "annotations": _RO},
    {"name": "inbox", "title": "Inbox",
     "description": "The console Inbox: decisions waiting on the operator (checklist operator_decision edges, "
                    "pipeline ask_operator items) and alerts. Sections not yet served say could_not_look.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}},
     "annotations": _RO},
    {"name": "work_items", "title": "Work-store items",
     "description": "Work-store items (WORK-STORE S1). Reports could_not_look until that route is live.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
]
_TOOL_NAMES = {t["name"] for t in TOOLS}


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "hello":
        N_CALLS["n"] += 1
        now = _dt.datetime.now(_dt.timezone.utc)
        return {"hello": f"hello, {args.get('name') or 'console'}", "server": "ict-trainer-vm",
                "server_time_utc": now.isoformat(timespec="milliseconds"),
                "server_epoch_ms": int(time.time() * 1000), "client_sent_ms": args.get("client_sent_ms"),
                "calls_since_start": N_CALLS["n"], "read_state": "read"}
    if name == "work_rows":
        view = str(args.get("view") or "all")
        limit = _clamp(args.get("limit"), 1, 200, 25)
        return CACHE.get(f"work_rows:{view}:{limit}", TTL_S["work_rows"], lambda: data.work_rows(REPO, view, limit))
    if name == "inbox":
        limit = _clamp(args.get("limit"), 1, 200, 25)
        return CACHE.get(f"inbox:{limit}", TTL_S["inbox"], lambda: data.inbox(REPO, limit))
    if name == "work_items":
        return CACHE.get("work_items", TTL_S["work_items"], data.work_items)
    raise KeyError(name)


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message -> its response, or None for a notification."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_DEFAULT
        result: dict[str, Any] = {"protocolVersion": pv, "capabilities": {"tools": {"listChanged": False}},
                                  "serverInfo": {"name": "jta-console", "version": "0.1.0"},
                                  "instructions": "Read-only JTA Trader console data. Every payload carries "
                                                  "as_of, read_state and population; render null as a dash."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params") or {}
        name = p.get("name")
        if name not in _TOOL_NAMES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            out = call_tool(name, p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, default=str)}],
                      "structuredContent": out, "isError": False}
        except Exception as exc:  # noqa: BLE001  # allow-silent: returned to the caller as a tool error
            result = {"content": [{"type": "text", "text": f"tool failed: {exc}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _log(rec: dict[str, Any]) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass  # allow-silent: request logging must never fail a read


def create_app():
    from fastapi import FastAPI, Request, Response

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/mcp")
    async def mcp(req: Request):
        t0 = time.time()
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            return Response(json.dumps({"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}}),
                            status_code=400, media_type="application/json")
        msgs = body if isinstance(body, list) else [body]
        outs = [o for o in (handle(m) for m in msgs if isinstance(m, dict)) if o is not None]
        _log({"t": round(t0, 3), "methods": [m.get("method") for m in msgs if isinstance(m, dict)],
              "tools": [(m.get("params") or {}).get("name") for m in msgs
                        if isinstance(m, dict) and m.get("method") == "tools/call"],
              "ua": req.headers.get("user-agent"), "proto": req.headers.get("mcp-protocol-version"),
              "ms": round((time.time() - t0) * 1000, 2)})
        if not outs:
            return Response(status_code=202)
        return Response(json.dumps(outs if isinstance(body, list) else outs[0], default=str),
                        media_type="application/json")

    @app.get("/mcp")
    async def mcp_get():
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "repo": str(REPO), "cache_builds": CACHE.builds}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("CONSOLE_CONNECTOR_PORT", "8765")),
                log_level="warning")

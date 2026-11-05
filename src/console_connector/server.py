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

from fastapi import FastAPI, Request, Response

from src.console_connector import data, tabs
from src.console_connector import oauth as oauth_mod

REPO = Path(os.environ.get("CONSOLE_CONNECTOR_REPO") or Path(__file__).resolve().parents[2])
LOG = Path(os.environ.get("CONSOLE_CONNECTOR_LOG") or REPO / "runtime_logs" / "console_connector.jsonl")
PROTOCOL_DEFAULT = "2025-06-18"
CACHE = data.TTLCache()
TTL_S = {"work_rows": 30.0, "inbox": 30.0, "work_items": 30.0, "workplan": 60.0, "ml_roadmap": 120.0,
         "performance": 300.0, "system_health": 60.0, "data_query": 30.0, "system_catalog": 300.0}
#: Tools that serve P&L, journal rows or live-VM state: registered ONLY when CONSOLE_CONNECTOR_AUTH=google
#: (the sign-in is on), so they never serve over the authless tunnel. workplan and ml_roadmap carry only
#: public-register data (repo files) and are always available.
GATED_TOOLS = frozenset({"performance", "system_health", "data_query"})


def auth_active() -> bool:
    return os.environ.get("CONSOLE_CONNECTOR_AUTH", "").strip().lower() == "google"
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
                    "queued (with a due date) and open_other (queued without a due date, landed_unproven); each row carries week_lane, roadmap and writeback. Each response has as_of, read_state, population and the "
                    "git commit the register was read at.",
     "inputSchema": {"type": "object", "properties": {
         "view": {"type": "string", "enum": ["all", "due", "in_flight", "blocked", "queued", "open_other"], "default": "all"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
         "offset": {"type": "integer", "minimum": 0, "default": 0,
                    "description": "rows to skip in every returned section; population.next_offset[section] "
                                   "is the offset of the next page, null when that section is complete"}}},
     "annotations": _RO},
    {"name": "inbox", "title": "Inbox",
     "description": "The console Inbox: decisions waiting on the operator (checklist operator_decision edges, "
                    "pipeline ask_operator items) and alerts. Sections not yet served say could_not_look.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}},
     "annotations": _RO},
    {"name": "workplan", "title": "Weekly workplan",
     "description": "This week's plan: the WEEKLY-PLANNING row, overdue / due-this-week / priority checklist rows, "
                    "counts by state, owner and lane, and the latest usage reading with the spend_meter capacity.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 40}}}, "annotations": _RO},
    {"name": "ml_roadmap", "title": "ML roadmap",
     "description": "ML milestones (milestones.yaml, goal G4), the ML plan-vs-measured status "
                    "(ml_plan_status) and live ML-* checklist rows with state, next and due.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 60}}}, "annotations": _RO},
    {"name": "system_catalog", "title": "System catalog",
     "description": "Strategy legs (status testing/production/inactive, books, venue, symbol), ML models with "
                    "manifest target stage, and the signal catalog inputs, all read from committed config at "
                    "the register commit. Nothing live.",
     "inputSchema": {"type": "object", "properties": {
         "signals_limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 400}}}, "annotations": _RO},
    {"name": "performance", "title": "Performance",
     "description": "SIGN-IN ONLY. Per leg and book: trades, realized R and net P&L over 7d/30d/all with n and "
                    "pnl provenance; live-vs-backtest band; ML shadow/advisory metrics per model.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
    {"name": "system_health", "title": "System health",
     "description": "SIGN-IN ONLY. Services and timers, trader restarts today, tick_cost / exit-loop health, "
                    "disk and CPU per VM, lanes running and spend vs the weekly bar.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
    {"name": "data_query", "title": "Data viewer",
     "description": "SIGN-IN ONLY. Read-only rows from the allowlisted trade-journal / trainer-store tables. "
                    "No SQL: pick a table and optional account, leg, symbol, since, until filters. Omit `table` "
                    "for the catalog. Rows are capped at 500.",
     "inputSchema": {"type": "object", "properties": {
         "table": {"type": "string"}, "account": {"type": "string"}, "leg": {"type": "string"},
         "symbol": {"type": "string"}, "since": {"type": "string", "description": "ISO date/datetime, inclusive"},
         "until": {"type": "string", "description": "ISO date/datetime, exclusive"},
         "time_column": {"type": "string"}, "order": {"type": "string", "enum": ["asc", "desc"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
         "offset": {"type": "integer", "minimum": 0}}}, "annotations": _RO},
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
        offset = _clamp(args.get("offset"), 0, 100000, 0)
        return CACHE.get(f"work_rows:{view}:{limit}:{offset}", TTL_S["work_rows"],
                         lambda: data.work_rows(REPO, view, limit, offset=offset))
    if name == "inbox":
        limit = _clamp(args.get("limit"), 1, 200, 25)
        return CACHE.get(f"inbox:{limit}", TTL_S["inbox"], lambda: data.inbox(REPO, limit))
    if name == "work_items":
        return CACHE.get("work_items", TTL_S["work_items"], data.work_items)
    if name in GATED_TOOLS and not auth_active():
        # never cached, never built: the data is not read at all without the sign-in
        return {"as_of": data._iso(data._now()), "read_state": "auth_required", "tool": name,
                "population": {"rows_scanned": None},
                "reason": "this tool serves P&L / journal / live-VM state and is available only when the "
                          "connector's Google sign-in is active (CONSOLE_CONNECTOR_AUTH=google)"}
    if name == "workplan":
        limit = _clamp(args.get("limit"), 1, 200, 40)
        return CACHE.get(f"workplan:{limit}", TTL_S[name], lambda: tabs.workplan(REPO, limit))
    if name == "ml_roadmap":
        limit = _clamp(args.get("limit"), 1, 200, 60)
        return CACHE.get(f"ml_roadmap:{limit}", TTL_S[name], lambda: tabs.ml_roadmap(REPO, limit))
    if name == "system_catalog":
        lim = _clamp(args.get("signals_limit"), 1, 500, 400)
        return CACHE.get(f"system_catalog:{lim}", TTL_S[name], lambda: tabs.system_catalog(REPO, lim))
    if name == "performance":
        return CACHE.get("performance", TTL_S[name], lambda: tabs.performance(REPO))
    if name == "system_health":
        return CACHE.get("system_health", TTL_S[name], lambda: tabs.system_health(REPO))
    if name == "data_query":
        key = "data_query:" + json.dumps({k: args.get(k) for k in sorted(args)}, sort_keys=True, default=str)
        return CACHE.get(key, TTL_S[name], lambda: tabs.data_query(REPO, args))
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
        result = {"tools": [t for t in TOOLS if t["name"] not in GATED_TOOLS or auth_active()]}
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


def create_app(auth: oauth_mod.OAuthServer | None | str = "env"):
    """The ASGI app. `auth` = an OAuthServer, None (no sign-in), or "env" (read CONSOLE_CONNECTOR_AUTH)."""
    from urllib.parse import parse_qsl

    from fastapi.responses import HTMLResponse, JSONResponse

    if auth == "env":
        auth = oauth_mod.from_env(REPO / "runtime_logs" / "console_connector_oauth.json")
    misconfigured = bool(auth) and not (auth.base and auth.google_client_id and auth.allowed_email)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def _oauth_error(exc: oauth_mod.OAuthError):
        return JSONResponse(exc.body(), status_code=exc.status, headers={"Cache-Control": "no-store"})

    if auth is not None:
        @app.get("/.well-known/oauth-protected-resource")
        @app.get("/.well-known/oauth-protected-resource/mcp")
        async def prm():
            return auth.resource_metadata()

        @app.get("/.well-known/oauth-authorization-server")
        async def asm():
            return auth.server_metadata()

        @app.post("/register")
        async def register(req: Request):
            try:
                body = await req.json()
                return JSONResponse(auth.register(body if isinstance(body, dict) else {}), status_code=201)
            except oauth_mod.OAuthError as exc:
                return _oauth_error(exc)
            except ValueError:
                return _oauth_error(oauth_mod.OAuthError(400, "invalid_client_metadata", "body must be JSON"))

        @app.get("/authorize")
        async def authorize(req: Request):
            try:
                rid = auth.begin_authorize(dict(req.query_params))
            except oauth_mod.OAuthError as exc:
                return HTMLResponse(f"<p>Sign-in request refused: {exc.description}</p>", status_code=exc.status)
            return HTMLResponse(auth.sign_in_page(rid), headers={"Cache-Control": "no-store",
                                                                  "Referrer-Policy": "no-referrer"})

        @app.post("/authorize/google")
        async def authorize_google(req: Request):
            try:
                body = await req.json()
            except ValueError:
                body = {}
            try:
                url = auth.complete_authorize(str(body.get("rid", "")), str(body.get("id_token", "")))
            except oauth_mod.OAuthError as exc:
                return _oauth_error(exc)
            return JSONResponse({"redirect": url}, headers={"Cache-Control": "no-store"})

        @app.post("/token")
        async def token(req: Request):
            form = dict(parse_qsl((await req.body()).decode("utf-8", "replace")))
            try:
                return JSONResponse(auth.token(form), headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
            except oauth_mod.OAuthError as exc:
                return _oauth_error(exc)

    @app.post("/mcp")
    async def mcp(req: Request):
        t0 = time.time()
        if auth is not None:
            if misconfigured:
                _log({"t": round(t0, 3), "denied": "misconfigured"})
                return JSONResponse({"error": "server_misconfigured",
                                     "error_description": "sign-in is on but not configured; refusing all reads"},
                                    status_code=503)
            if not auth.check_bearer(req.headers.get("authorization")):
                _log({"t": round(t0, 3), "denied": "no_valid_token", "ua": req.headers.get("user-agent")})
                return JSONResponse({"error": "invalid_token"}, status_code=401,
                                    headers={"WWW-Authenticate": auth.challenge_header()})
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
              "authed": auth is not None, "ms": round((time.time() - t0) * 1000, 2)})
        if not outs:
            return Response(status_code=202)
        return Response(json.dumps(outs if isinstance(body, list) else outs[0], default=str),
                        media_type="application/json")

    @app.get("/mcp")
    async def mcp_get():
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "auth": "google" if auth is not None else "none", "cache_builds": CACHE.builds}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("CONSOLE_CONNECTOR_PORT", "8765")),
                log_level="warning")

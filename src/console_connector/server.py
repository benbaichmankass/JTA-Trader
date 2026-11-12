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
TTL_S = {"work_rows": 30.0, "inbox": 30.0, "work_items": 10.0, "workplan": 60.0, "ml_roadmap": 120.0,
         "performance": 300.0, "system_health": 60.0, "data_query": 30.0, "system_catalog": 300.0,
         "research_queue": 300.0, "wake_toggles": 10.0,
         "alerts": 15.0, "journal": 60.0, "reports": 120.0}
#: Tools that serve P&L, journal rows or live-VM state: registered ONLY when CONSOLE_CONNECTOR_AUTH=google
#: (the sign-in is on), so they never serve over the authless tunnel. workplan and ml_roadmap carry only
#: public-register data (repo files) and are always available.
GATED_TOOLS = frozenset({"performance", "system_health", "data_query", "alerts", "journal", "reports"})


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
    {"name": "research_queue", "title": "Research queue",
     "description": "Every research/queue unit: id, title, status (queued/running/done/blocked), kind, theme group (ml/trading), "
                    "harness, compute (GitHub/trainer), last run and result pointer. counts cover the full population; rows are the "
                    "filtered page (status: pipeline|queued|running|done|blocked|all; theme: all|ml|trading). Every response has as_of, read_state and population.",
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["pipeline", "queued", "running", "done", "blocked", "all"], "default": "pipeline"},
         "theme": {"type": "string", "enum": ["all", "ml", "trading"], "default": "all"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30},
         "offset": {"type": "integer", "minimum": 0}}}, "annotations": _RO},
    {"name": "alerts", "title": "Alerts",
     "description": "SIGN-IN ONLY. The live alert ledger (GET /api/bot/alerts on the trader VM), newest first: ts, kind, "
                    "channel, priority, delivered, body. urgent=true keeps channel system or priority high.",
     "inputSchema": {"type": "object", "properties": {
         "since_hours": {"type": "integer", "minimum": 1, "maximum": 336, "default": 24},
         "kind": {"type": "string"}, "channel": {"type": "string"}, "urgent": {"type": "boolean", "default": False},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 40}}}, "annotations": _RO},
    {"name": "journal", "title": "Trade journal",
     "description": "SIGN-IN ONLY. kind=trades: closed trades (GET /api/bot/trades/closed; real money unless "
                    "include_paper) with realized P&L and its provenance. kind=packages: order packages "
                    "(GET /api/bot/order-packages) with entry/SL/TP, scores and status. Newest first, paged.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["trades", "packages"], "default": "trades"},
         "account": {"type": "string"}, "include_paper": {"type": "boolean", "default": False},
         "since": {"type": "string", "description": "trades: ISO date/datetime"},
         "strategy": {"type": "string"}, "symbol": {"type": "string"}, "status": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
         "offset": {"type": "integer", "minimum": 0, "default": 0}}}, "annotations": _RO},
    {"name": "reports", "title": "Reports",
     "description": "SIGN-IN ONLY. The review reports index (GET /api/bot/reports), newest first; pass report_id for "
                    "one report's metadata and text.",
     "inputSchema": {"type": "object", "properties": {
         "report_id": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}}}, "annotations": _RO},
    {"name": "wake_toggles", "title": "Wake switches",
     "description": "Which wake notifications reach the manager session (live from the trader VM's GET /api/bot/wake-toggles).",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
    {"name": "work_items", "title": "Work-store items",
     "description": "Work-store items from the live work store (WORK-STORE S1, GET /api/bot/work/items on the trader VM), "
                    "for the console Work tab. view: recent (newest updated first within since_hours, default 24) | due "
                    "(the due_now view) | open (queued/in_flight/blocked/routed/landed_unproven) | state (with state). "
                    "Pass item_id for that item's event log and chain check instead. Each item carries by (last writer) "
                    "and source (store = written natively, checklist/pipeline = imported). canonical=false until S4: "
                    "the checklist files stay the register of record until then. 10 s cache.",
     "inputSchema": {"type": "object", "properties": {
         "view": {"type": "string", "enum": ["recent", "due", "open", "state"], "default": "recent"},
         "state": {"type": "string", "description": "for view=state, e.g. in_flight"},
         "kind": {"type": "string", "description": "optional item kind filter, e.g. build"},
         "since_hours": {"type": "integer", "minimum": 1, "maximum": 336, "default": 24},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30},
         "offset": {"type": "integer", "minimum": 0, "default": 0},
         "item_id": {"type": "string", "description": "return this item's events instead of a list"}}},
     "annotations": _RO},
]
#: The ONLY write tool on this otherwise read-only connector (operator 2026-11-07: wake switches must be flippable
#: from the console). Listed and callable only when write_enabled() (Google sign-in + a configured write token);
#: it changes which comments wake a session, nothing else. Gates this adds or changes: none.
WRITE_TOOL = {"name": "set_wake_toggle", "title": "Flip a wake switch",
              "description": "Turn one wake-notification switch on or off on the trader VM (POST /api/bot/wake-toggles). Logged with who/when.",
              "inputSchema": {"type": "object", "required": ["key", "on"], "properties": {
                  "key": {"type": "string"}, "on": {"type": "boolean"}}},
              "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}}
_TOOL_NAMES = {t["name"] for t in TOOLS} | {WRITE_TOOL["name"]}


WAKE_API = os.environ.get("WAKE_TOGGLES_API") or "https://ict-bot.duckdns.org/api/bot/wake-toggles"


def wake_toggles_read() -> dict[str, Any]:
    """Live read of the VM's switches (public GET). ``could_not_look`` is a state, never 'all off'."""
    import urllib.request
    try:
        req = urllib.request.Request(WAKE_API, headers={"User-Agent": "jta-console-connector"})
        with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 fixed https URL
            doc = json.loads(r.read())
        doc["as_of"] = data._iso(data._now())
        doc["write_enabled"] = write_enabled()
        return doc
    except Exception as exc:  # noqa: BLE001
        return {"as_of": data._iso(data._now()), "read_state": "could_not_look", "error": type(exc).__name__,
                "toggles": None, "rows": [], "write_enabled": write_enabled(),
                "population": {"switches": None}, "note": "could not reach the trader VM; posters post when unreadable"}


def write_enabled() -> bool:
    """The ONE write tool is offered only behind the Google sign-in AND a configured write token."""
    return auth_active() and bool(os.environ.get("WAKE_TOGGLES_WRITE_TOKEN", "").strip())


def wake_toggle_write(args: dict[str, Any]) -> dict[str, Any]:
    import urllib.request
    if not write_enabled():
        return {"as_of": data._iso(data._now()), "read_state": "auth_required", "tool": "set_wake_toggle",
                "reason": "needs CONSOLE_CONNECTOR_AUTH=google and WAKE_TOGGLES_WRITE_TOKEN on the connector host"}
    key, on = args.get("key"), args.get("on")
    if not isinstance(key, str) or not isinstance(on, bool):
        return {"as_of": data._iso(data._now()), "read_state": "bad_request", "reason": "key (string) and on (boolean) required"}
    body = json.dumps({"key": key, "on": on, "by": "console (operator Google sign-in)"}).encode()
    req = urllib.request.Request(WAKE_API, data=body, method="POST", headers={
        "Authorization": "Bearer " + os.environ["WAKE_TOGGLES_WRITE_TOKEN"].strip(),
        "Content-Type": "application/json", "User-Agent": "jta-console-connector"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            doc = json.loads(r.read())
        CACHE.get("wake_toggles", 0.0, lambda: doc)  # next read is fresh
        doc["as_of"] = data._iso(data._now())
        return doc
    except Exception as exc:  # noqa: BLE001
        return {"as_of": data._iso(data._now()), "read_state": "could_not_write", "error": type(exc).__name__}


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _clip(o: Any, n: int = 140) -> Any:
    """Long strings clipped (a note tail or title is for a glance); structure and counts untouched."""
    if isinstance(o, str):
        return o if len(o) <= n else o[: n - 1] + "…"
    if isinstance(o, list):
        return [_clip(x, n) for x in o]
    if isinstance(o, dict):
        return {k: _clip(v, n) for k, v in o.items()}
    return o


#: Budget for one tool reply (the page's call must finish inside the artifact's result-size and time limits).
REPLY_BUDGET = 40_000


def _lean_rows(o: Any) -> Any:
    """Row-level diet for the register tools: drop updated_by, keep a short note tail."""
    if isinstance(o, dict):
        if "id" in o and "state" in o and "updated_by" in o:
            o = {k: v for k, v in o.items() if k != "updated_by"}
            if isinstance(o.get("note_tail"), str):
                o["note_tail"] = o["note_tail"][-90:]
        return {k: _lean_rows(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_lean_rows(x) for x in o]
    return o


def _inbox(limit: int) -> dict[str, Any]:
    """The Inbox; with the sign-in on, its alerts section is the live ledger's urgent rows (24 h)."""
    out = data.inbox(REPO, limit)
    if auth_active():
        a = tabs.alerts({"urgent": True, "since_hours": 24, "limit": limit})
        out["sections"]["alerts"] = {
            "read_state": a["read_state"], "count": a.get("count"), "population": a.get("population"),
            "error": a.get("error"),
            "items": [{"source": "alert", "id": f"{r.get('kind')}@{r.get('ts')}", "title": (r.get("body") or "")[:160],
                       "ref": r.get("channel"), "what": f"{r.get('priority')} · {r.get('delivered')}",
                       "due_by": (r.get("ts") or "")[:16]} for r in (a.get("rows") or [])]}
    return out


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    out = _clip(_lean_rows(_call_tool(name, args)))
    if isinstance(out, dict):
        out["reply_bytes"] = len(json.dumps(out, default=str))
        if out["reply_bytes"] > REPLY_BUDGET:
            out["oversize"] = f"reply is {out['reply_bytes']} bytes (> {REPLY_BUDGET}); lower limit or page with offset"
    return out


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
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
        return CACHE.get(f"inbox:{limit}:{auth_active()}", TTL_S["inbox"], lambda: _inbox(limit))
    if name == "research_queue":
        a = {k: args.get(k) for k in ("status", "theme", "limit", "offset")}
        return CACHE.get("research_queue:" + json.dumps(a, sort_keys=True, default=str), TTL_S[name],
                         lambda: tabs.research_queue(REPO, a))
    if name == "wake_toggles":
        return CACHE.get("wake_toggles", TTL_S[name], lambda: wake_toggles_read())
    if name == "set_wake_toggle":
        return wake_toggle_write(args)
    if name == "work_items":
        a = {k: args.get(k) for k in ("view", "state", "kind", "since_hours", "limit", "offset", "item_id")}
        return CACHE.get("work_items:" + json.dumps(a, sort_keys=True, default=str), TTL_S[name],
                         lambda: tabs.work_items(a))
    if name in GATED_TOOLS and not auth_active():
        # never cached, never built: the data is not read at all without the sign-in
        return {"as_of": data._iso(data._now()), "read_state": "auth_required", "tool": name,
                "population": {"rows_scanned": None},
                "reason": "this tool serves P&L / journal / live-VM state and is available only when the "
                          "connector's Google sign-in is active (CONSOLE_CONNECTOR_AUTH=google)"}
    if name in ("alerts", "journal", "reports"):
        fn = getattr(tabs, name)
        return CACHE.get(name + ":" + json.dumps(args, sort_keys=True, default=str), TTL_S[name], lambda: fn(dict(args)))
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
        result = {"tools": [t for t in TOOLS if t["name"] not in GATED_TOOLS or auth_active()]
                  + ([WRITE_TOOL] if write_enabled() else [])}
    elif method == "tools/call":
        p = msg.get("params") or {}
        name = p.get("name")
        if name not in _TOOL_NAMES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            out = call_tool(name, p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, default=str, separators=(",", ":"))}],
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

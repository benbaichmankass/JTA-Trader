"""UI-OAUTH-SIGNIN: anonymous walk over EVERY route, with the site gate ON.

The site gate (``auth.require_site_session``) is default-deny, but it exempts
the prefixes ``/api/diag/`` and ``/api/bot/prop/phone/`` (plus the exact path
``/api/bot/prop/report``). Those routes rely on a credential check INSIDE their
own router. A route under an exempt prefix that forgets the check is open
precisely BECAUSE its prefix is public. This file walks ``app.routes`` (so a
route added later is covered automatically) and pins:

  * every exempt-prefix route refuses an anonymous request (401/403/503), with
    its token configured and with it unset;
  * every other route gets the site gate's own 401 when called anonymously
    (default-deny), except the declared public set;
  * a gate 401 (GET and POST) still carries the CORS headers the browser SPA
    needs to read it (the SPA calls the API browser-direct; CORS is load-bearing).

The walk asserts its own denominator first: a walk that found no routes would
pass every assertion vacuously.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from src.web.api import auth as auth_module
from src.web.api import main as api_main

ORIGIN = "https://benbaichmankass.github.io"
EXEMPT_PREFIXES = ("/api/diag/", "/api/bot/prop/phone/")
EXEMPT_EXACT = ("/api/bot/prop/report",)
# FastAPI's own docs routes are not part of the API surface the SPA calls; the
# gate still covers them (they are on the app, not a router), see the walk below.
# FastAPI's built-in docs routes. Found open by this walk 2026-11-12 (FastAPI
# added them outside the app-level gate dependency); main.py now re-adds them as
# ordinary app routes. Pinned separately so a regression names itself.
_DOC_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
_PARAM = re.compile(r"\{[^}]+\}")
_REFUSED = (401, 403, 503)


def _walk(routes):
    """Yield ``(path, methods, is_websocket)`` for every concrete route.

    Handles both router layouts: older FastAPI flattens ``include_router`` into
    ``APIRoute`` objects; newer FastAPI keeps an included-router node exposing
    ``effective_route_contexts()``.
    """
    for r in routes:
        ctxs = getattr(r, "effective_route_contexts", None)
        if callable(ctxs):
            for c in ctxs():
                orig = getattr(c, "original_route", None)
                is_ws = type(orig).__name__ in ("APIWebSocketRoute", "WebSocketRoute")
                path = c.path or (getattr(c, "frontend_prefix", "") + getattr(orig, "path", ""))
                yield path, set(c.methods or ()), is_ws
            continue
        sub = getattr(r, "routes", None)
        if sub and not hasattr(r, "methods"):
            yield from _walk(sub)
            continue
        path = getattr(r, "path", None)
        if path is None:
            continue
        is_ws = type(r).__name__ in ("APIWebSocketRoute", "WebSocketRoute")
        yield path, set(getattr(r, "methods", None) or ()), is_ws


def _http_routes():
    out = []
    for path, methods, is_ws in _walk(api_main.app.routes):
        if is_ws:
            continue
        for m in sorted(methods - {"HEAD", "OPTIONS"}):
            out.append((m, path))
    return sorted(set(out))


ROUTES = _http_routes()
EXEMPT = [(m, p) for m, p in ROUTES if p.startswith(EXEMPT_PREFIXES) or p in EXEMPT_EXACT
          or (m == "GET" and p.startswith(tuple(getattr(auth_module, "SITE_TOKEN_GET_PREFIXES", ()))))]


def _concrete(path: str) -> str:
    return _PARAM.sub("x", path)


_TOKEN_GET_PREFIXES = tuple(getattr(auth_module, "SITE_TOKEN_GET_PREFIXES", ()))


def _is_public(method: str, path: str) -> bool:
    """Exempt from the SITE gate (the route's own credential then decides)."""
    if auth_module._is_site_public(path):
        return True
    if method in ("GET", "HEAD") and _TOKEN_GET_PREFIXES and path.startswith(_TOKEN_GET_PREFIXES):
        return True
    return method == "POST" and auth_module._is_site_public_post(path)


def _gate_401(resp) -> bool:
    ctype = resp.headers.get("content-type", "")
    body = resp.json() if ctype.startswith("application/json") else {}
    return resp.status_code == 401 and body.get("detail") == auth_module._UNAUTH.detail


def _call(client, method: str, path: str, headers=None):
    """Anonymous call with path params filled. A 422 naming missing REQUIRED query
    params is request validation answering before the handler (and so before the
    handler's own token check): retry once with every such param filled, so the
    route's credential check is what answers."""
    url = _concrete(path)
    kw = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
    r = client.request(method, url, headers=headers or {}, **kw)
    if r.status_code == 422:
        try:
            missing = [d["loc"][1] for d in r.json().get("detail", [])
                       if d.get("type") == "missing" and list(d.get("loc", []))[:1] == ["query"]]
        except (ValueError, AttributeError, KeyError, IndexError, TypeError):
            missing = []
        if missing:
            r = client.request(method, url, headers=headers or {},
                               params={k: "1" for k in missing}, **kw)
    return r


@pytest.fixture
def enforced_client(monkeypatch, tmp_path):
    monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "tj.db"))
    monkeypatch.setenv("ALLOWED_EMAIL", "operator@example.invalid")
    monkeypatch.setenv("WEB_SESSION_PEPPER", "p" * 32)
    return TestClient(api_main.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Denominator: the walk must find what we know is there.
# ---------------------------------------------------------------------------


def test_walk_finds_the_known_routes():
    paths = {p for _, p in ROUTES}
    for known in ("/api/diag/status", "/api/bot/prop/report", "/api/bot/strategies",
                  "/api/health", "/api/auth/google"):
        assert known in paths, known
    assert len(ROUTES) >= 100, len(ROUTES)
    assert len([1 for _, p in EXEMPT if p.startswith("/api/diag/")]) >= 10
    assert len([1 for _, p in EXEMPT if p.startswith("/api/bot/prop/phone/")]) >= 3
    ws = [p for p, _, is_ws in _walk(api_main.app.routes) if is_ws]
    assert "/ws/market" in ws, ws


# ---------------------------------------------------------------------------
# Exempt prefixes: each route's own check must refuse an anonymous caller.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", EXEMPT, ids=[f"{m} {p}" for m, p in EXEMPT])
def test_exempt_route_refuses_anonymous_with_token_configured(enforced_client, monkeypatch, method, path):
    monkeypatch.setenv("DIAG_READ_TOKEN", "diag-configured")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "svc-configured")
    r = _call(enforced_client, method, path)
    assert r.status_code in _REFUSED, (method, path, r.status_code, r.text[:200])


@pytest.mark.parametrize("method,path", EXEMPT, ids=[f"{m} {p}" for m, p in EXEMPT])
def test_exempt_route_fails_closed_with_token_unset(enforced_client, monkeypatch, method, path):
    monkeypatch.delenv("DIAG_READ_TOKEN", raising=False)
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    r = _call(enforced_client, method, path, headers={"Authorization": "Bearer anything"})
    assert r.status_code in _REFUSED, (method, path, r.status_code, r.text[:200])


@pytest.mark.parametrize("method,path", EXEMPT, ids=[f"{m} {p}" for m, p in EXEMPT])
def test_exempt_route_refuses_a_wrong_token(enforced_client, monkeypatch, method, path):
    monkeypatch.setenv("DIAG_READ_TOKEN", "diag-configured")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "svc-configured")
    r = _call(enforced_client, method, path,
              headers={"Authorization": "Bearer wrong", "X-Diag-Token": "wrong"})
    assert r.status_code in _REFUSED, (method, path, r.status_code, r.text[:200])


# ---------------------------------------------------------------------------
# Everything else: default-deny at the gate.
# ---------------------------------------------------------------------------

GATED = [(m, p) for m, p in ROUTES if not _is_public(m, p)]


@pytest.mark.parametrize("method,path", GATED, ids=[f"{m} {p}" for m, p in GATED])
def test_every_non_public_route_is_the_gates_401_when_anonymous(enforced_client, method, path):
    r = _call(enforced_client, method, path)
    assert _gate_401(r), (method, path, r.status_code, r.text[:200])


def test_public_set_is_exactly_the_declared_one():
    """A new public path is a reviewed code change; this lists what the walk
    treats as public so a widening shows up in the diff of this assertion."""
    public = sorted({p for m, p in ROUTES if _is_public(m, p)
                     and not p.startswith(("/api/diag/", "/api/bot/prop/phone/", "/api/auth/"))})
    assert public == sorted([
        "/api/bot/alerts", "/api/bot/devices/register", "/api/bot/live-review/rows",
        "/api/bot/ops/actions", "/api/bot/ops/jobs/{job_id}",
        "/api/bot/prop/report", "/api/bot/wake-toggles", "/api/bot/work/decision",
        "/api/bot/work/items", "/api/bot/work/items/{item_id}/close",
        "/api/bot/work/items/{item_id}/note", "/api/bot/work/items/{item_id}/set",
        "/api/health",
    ]), public


def test_docs_routes_are_gated(enforced_client):
    paths = {p for _, p in ROUTES}
    for p in sorted(_DOC_PATHS):
        assert p in paths, p                                  # still served ...
        assert _gate_401(enforced_client.get(p)), p           # ... but behind the gate


def test_docs_routes_still_serve_with_the_gate_off(monkeypatch):
    monkeypatch.delenv("SITE_AUTH_ENFORCE", raising=False)
    c = TestClient(api_main.app, raise_server_exceptions=False)
    assert c.get("/openapi.json").json()["info"]["title"] == api_main.app.title
    for p in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        assert c.get(p).status_code == 200, p


# ---------------------------------------------------------------------------
# CORS on a gate 401 (the SPA must be able to READ the 401 to show sign-in).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", [("GET", "/api/bot/stats"), ("GET", "/api/bot/strategies"),
                                         ("POST", "/api/bot/learning/progress")])
def test_gate_401_carries_cors_headers(enforced_client, method, path):
    r = _call(enforced_client, method, path, headers={"Origin": ORIGIN})
    assert _gate_401(r), (method, path, r.status_code)
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_gate_401_for_an_unlisted_origin_has_no_allow_origin(enforced_client):
    """Negative control for the CORS check above: the header is not just always there."""
    r = enforced_client.get("/api/bot/stats", headers={"Origin": "https://evil.example"})
    assert _gate_401(r)
    assert "access-control-allow-origin" not in r.headers


def test_router_401_on_a_carved_out_post_carries_cors_headers(enforced_client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "svc-configured")
    r = enforced_client.post("/api/bot/alerts", json={}, headers={"Origin": ORIGIN})
    assert r.status_code in (401, 403) and not _gate_401(r)
    assert r.headers.get("access-control-allow-origin") == ORIGIN

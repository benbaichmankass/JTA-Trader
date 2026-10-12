"""S-013 M3 — JWT helpers and ``require_session`` dependency.

Token contract (binding for S-013):

    alg = HS256, signed with env ``JWT_SIGNING_KEY``
    ttl = 3600 s (1 hour)
    claims = {"email": <str>, "iat": <int>, "exp": <int>}

Allowlist gate ``email == ALLOWED_EMAIL`` is enforced at issuance time
(``POST /api/auth/login``) and again at request time inside
``require_session``.

Secrets stay server-side. Envs (``JWT_SIGNING_KEY``,
``WEBAPP_PASSWORD_SHA256``, ``ALLOWED_EMAIL``) are read **per call**, not
at import time, so unit tests can monkeypatch them and the systemd
``EnvironmentFile`` updates without a process restart.

Error responses must never leak which env var is missing — only that
auth is unavailable.

Default-deny: every route attaches ``Depends(require_session)`` unless
its path is in ``PUBLIC_ROUTES``. Adding to ``PUBLIC_ROUTES`` is a code
change reviewed in a PR.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from src.web.api import web_sessions

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 3600

# Routes that may be reached without a valid session token. Anything not
# in this set is default-deny.
PUBLIC_ROUTES: frozenset[str] = frozenset({
    "/api/auth/login",
    "/api/health",
    # S-014 M1 PR #2 — UI surface. ``/home`` is auth-gated client-side
    # (auth.js redirects to /login if no token). (The HTMX
    # ``/ui/fragments/*`` routers were removed 2026-05-21 — dead UI.)
    "/",
    "/login",
})

# Static assets are served by ``app.mount("/static", StaticFiles(...))``;
# every path under ``/static/*`` is public. Routes under this prefix do
# not attach ``Depends(require_session)`` and are not enumerable here.
PUBLIC_PREFIXES: tuple[str, ...] = ("/static/",)


# ---------------------------------------------------------------------------
# Env accessors. Read per-call so the systemd EnvironmentFile can update
# without a process restart and so tests can monkeypatch.
# ---------------------------------------------------------------------------


def _signing_key() -> str:
    key = os.environ.get("JWT_SIGNING_KEY", "").strip()
    if not key:
        # Don't echo the env-var name out to callers — see error-handling
        # contract above.
        raise RuntimeError("auth misconfigured")
    return key


def _allowed_email() -> str:
    email = os.environ.get("ALLOWED_EMAIL", "").strip().lower()
    if not email:
        raise RuntimeError("auth misconfigured")
    return email


def _password_hash() -> str:
    pw_hash = os.environ.get("WEBAPP_PASSWORD_SHA256", "").strip().lower()
    if not pw_hash:
        raise RuntimeError("auth misconfigured")
    return pw_hash


# ---------------------------------------------------------------------------
# Password verification.
# ---------------------------------------------------------------------------


def _hash_password(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def verify_password(plain: str, expected_hash: str) -> bool:
    """Constant-time SHA-256 hex compare."""
    return hmac.compare_digest(_hash_password(plain), expected_hash.lower())


# ---------------------------------------------------------------------------
# Token helpers.
# ---------------------------------------------------------------------------


def issue_token(email: str, *, now: Optional[int] = None) -> str:
    iat = int(now if now is not None else time.time())
    payload = {"email": email, "iat": iat, "exp": iat + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _signing_key(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Return claims dict on success, ``None`` on any failure.

    Failures swallowed: missing/invalid signing key, expired token,
    bad signature, ``alg=none`` (PyJWT rejects it because we pin
    ``algorithms=[HS256]``), malformed payload.
    """
    try:
        key = _signing_key()
    except RuntimeError:
        return None
    try:
        return jwt.decode(token, key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# require_session — FastAPI dependency.
# ---------------------------------------------------------------------------


_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"error": "invalid_session"},
    headers={"WWW-Authenticate": "Bearer"},
)


async def require_session(request: Request) -> dict:
    """Default-deny session gate.

    - Returns the decoded claims dict on success.
    - 401 ``invalid_session`` on missing/malformed Authorization, expired
      token, bad signature, or ``alg=none``.
    - 403 ``email_not_allowlisted`` if the token's ``email`` claim no
      longer matches ``ALLOWED_EMAIL`` (operator was de-allowlisted
      after issuance).
    - 500 ``auth_unavailable`` if the server's auth env vars are missing
      so the gate cannot make a decision; never echoes which env var.

    Routes whose path is in ``PUBLIC_ROUTES`` opt out by NOT attaching
    this dependency in the first place; that's enforced in
    ``src/web/api/main.py`` by the test suite.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise _UNAUTH

    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise _UNAUTH

    # UI-UPGRADE-1-AUTH: a device-session token (``ws_...``) is accepted in
    # addition to the legacy password JWT, so the routes that already demanded a
    # session keep working once the SPA signs in with Google + passkey. Tokens
    # that are not ``ws_`` take exactly the path they always did.
    if token.startswith(web_sessions.SESSION_TOKEN_PREFIX):
        # sqlite on a worker thread, never on the event loop
        row = await run_in_threadpool(web_sessions.validate_session, token)
        if row is None:
            raise _UNAUTH
        claims = {"email": row["email"], "sid": row["handle"]}
    else:
        claims = decode_token(token)
    if claims is None:
        raise _UNAUTH

    try:
        allowed = _allowed_email()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "auth_unavailable"},
        )

    claim_email = str(claims.get("email", "")).strip().lower()
    if not claim_email or claim_email != allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "email_not_allowlisted"},
        )

    return claims


# ---------------------------------------------------------------------------
# UI-UPGRADE-1-AUTH — the whole-site gate (design §2b).
#
# ``require_site_session`` is attached ONCE, as an app-level dependency, so it
# covers every HTTP route and ``WS /ws/market``. ``SITE_AUTH_ENFORCE`` DEFAULTS
# OFF: with it off the dependency returns before touching anything, so every
# existing route answers exactly as it did. Flipping it is the operator's
# ``set-env`` act, after a passkey is enrolled — NOT part of this change.
#
# This is a ROLLOUT switch for an auth surface, not a trading capability
# (design §2b); it is removed once enforcement has been observed.
# ---------------------------------------------------------------------------

# Exact paths that stay public when the gate is on.
SITE_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/api/health",
    "/api/bot/prop/report",     # prop executor/phone write bearer (DASHBOARD_API_TOKEN)
})
# Prefixes that stay public when the gate is on. Each has its own credential:
# auth routes (they ARE the sign-in; session-bearing ones add
# ``require_device_session`` themselves), ``/api/diag/*`` (DIAG_READ_TOKEN — the
# relays have no browser), prop phone routes (DASHBOARD_API_TOKEN bearer).
SITE_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/diag/",
    "/api/bot/prop/phone/",
)
_SAFE_METHODS = frozenset({"GET", "HEAD"})


def site_auth_enforced() -> bool:
    """``SITE_AUTH_ENFORCE`` — default OFF; only an explicit truthy value arms it."""
    return os.environ.get("SITE_AUTH_ENFORCE", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_site_public(path: str) -> bool:
    return path in SITE_PUBLIC_PATHS or path.startswith(SITE_PUBLIC_PREFIXES)


def _bearer(conn: HTTPConnection) -> str:
    h = conn.headers.get("Authorization", "")
    return h[len("Bearer "):].strip() if h.startswith("Bearer ") else ""


def _service_token_ok(token: str) -> bool:
    """``DASHBOARD_API_TOKEN`` as a READ-ONLY service credential for the
    non-browser consumers inventoried in design §2b."""
    expected = os.environ.get("DASHBOARD_API_TOKEN", "").strip()
    return bool(expected) and bool(token) and hmac.compare_digest(token, expected)


def require_site_session(conn: HTTPConnection) -> None:
    """App-level gate. No-op unless ``SITE_AUTH_ENFORCE`` is on.

    On: public paths and CORS preflight pass; otherwise a live device session
    (``Authorization: Bearer ws_...``) is required — or, for GET/HEAD only,
    ``DASHBOARD_API_TOKEN`` as a service credential. ``WS /ws/market`` takes a
    single-use ``?ticket=`` from ``POST /api/auth/ws-ticket`` (a browser
    WebSocket cannot send an Authorization header).
    """
    if not site_auth_enforced():
        return
    scope = conn.scope
    method = scope.get("method", "")
    if method == "OPTIONS" or _is_site_public(conn.url.path):
        return

    token = _bearer(conn)
    if scope["type"] == "websocket":
        ticket = conn.query_params.get("ticket", "")
        sid = web_sessions.mem_take("wsticket", ticket) if ticket else None
        if sid is not None and web_sessions.session_alive(sid):
            return
        if token.startswith(web_sessions.SESSION_TOKEN_PREFIX) and _session_row_allowed(
                web_sessions.validate_session(token)):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "invalid_session"})

    if token.startswith(web_sessions.SESSION_TOKEN_PREFIX):
        if _session_row_allowed(web_sessions.validate_session(token)):
            return
        raise _UNAUTH
    if method in _SAFE_METHODS and _service_token_ok(token):
        return
    raise _UNAUTH


def _session_row_allowed(row: Optional[dict]) -> bool:
    """A live session still needs ``email == ALLOWED_EMAIL`` (de-allowlisting
    kills every session at once)."""
    if not row:
        return False
    try:
        return str(row["email"]).strip().lower() == _allowed_email()
    except RuntimeError:
        return False


def require_device_session(request: Request) -> dict:
    """ALWAYS-ON session check for the session-management routes
    (``/api/auth/sessions``, ``/api/auth/ws-ticket``…), independent of
    ``SITE_AUTH_ENFORCE``: these routes only make sense for a signed-in device.
    """
    token = _bearer(request)
    if not token.startswith(web_sessions.SESSION_TOKEN_PREFIX):
        raise _UNAUTH
    row = web_sessions.validate_session(token)
    if not _session_row_allowed(row):
        raise _UNAUTH
    return row

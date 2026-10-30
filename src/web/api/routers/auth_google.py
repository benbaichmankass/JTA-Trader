"""UI-UPGRADE-1-AUTH — Google ID token + WebAuthn passkey sign-in, device sessions.

Design: ``docs/plans/ui-upgrade-1-auth-and-keys-design.md`` §2a/§2b/§2c.

Flow::

    POST /api/auth/google            Google ID token  -> 5-min PRE-AUTH ticket
    POST /api/auth/passkey/register/begin|finish   (first device: pre-auth ticket
                                     + one-time enrolment code; later devices: an
                                     already signed-in device session)
    POST /api/auth/passkey/assert/begin|finish     pre-auth ticket + passkey
                                     assertion -> 30-day sliding DEVICE SESSION
    GET/DELETE /api/auth/sessions    list / revoke device sessions
    POST /api/auth/ws-ticket         60 s single-use ticket for ``WS /ws/market``

Everything here is additive: the password login in ``routers/auth.py`` is
untouched, and nothing on a non-auth route changes unless ``SITE_AUTH_ENFORCE``
is on (``auth.require_site_session``).

Errors never say which env var is missing — only ``auth_unavailable``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.web.api import auth as auth_module
from src.web.api import web_sessions as ws

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

RP_NAME = "JTA Trader"
GOOGLE_CLOCK_SKEW_SECONDS = 10
_DEFAULT_ORIGIN = "https://benbaichmankass.github.io"


def _rp_id() -> str:
    return os.environ.get("WEBAUTHN_RP_ID", "").strip() or "benbaichmankass.github.io"


def _origins() -> list[str]:
    raw = os.environ.get("WEBAUTHN_ORIGINS", "").strip() or _DEFAULT_ORIGIN
    return [o.strip() for o in raw.split(",") if o.strip()]


def _err(code: int, error: str) -> HTTPException:
    return HTTPException(status_code=code, detail={"error": error})


def _unavailable() -> HTTPException:
    return _err(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable")


def _client_ip(request: Request) -> str:
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "testclient"):                # behind Caddy
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return host or "unknown"


def _guard_rate(ip: str) -> None:
    if ws.too_many_failures(ip):
        raise _err(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts")


def _fail(ip: str, code: int, error: str) -> HTTPException:
    ws.record_failure(ip)
    return _err(code, error)


def _allowed_email_or_503() -> str:
    try:
        return auth_module._allowed_email()
    except RuntimeError:
        raise _unavailable()


def _need_sessions() -> None:
    """Fail closed (503) when the session pepper is not configured."""
    try:
        ws.hash_secret("probe")
    except ws.SessionsUnavailable:
        raise _unavailable()


# ---------------------------------------------------------------------------
# Google ID token -> pre-auth ticket
# ---------------------------------------------------------------------------


def _verify_google_token(token: str, audience: str) -> dict[str, Any]:
    """Verify signature, expiry, issuer and audience with Google's library.
    Raises ``ValueError`` on anything wrong. Isolated so tests can drive the
    real verifier with a local key (they patch the cert fetch, not this)."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token as g_id_token

    # 10 s skew: the library default is 0, so a VM clock slightly behind Google's
    # would reject a fresh token as "used too early" with no visible cause.
    return g_id_token.verify_oauth2_token(
        token, g_requests.Request(), audience, clock_skew_in_seconds=GOOGLE_CLOCK_SKEW_SECONDS)


class GoogleRequest(BaseModel):
    id_token: str


@router.get("/config")
def public_config() -> dict[str, Any]:
    """What the SPA needs before sign-in. The client id ships in the SPA anyway."""
    return {
        "google_client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip() or None,
        "site_auth_enforced": auth_module.site_auth_enforced(),
    }


@router.post("/google")
def google_signin(body: GoogleRequest, request: Request) -> dict[str, Any]:
    ip = _client_ip(request)
    _guard_rate(ip)
    audience = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not audience:
        raise _unavailable()
    allowed = _allowed_email_or_503()
    _need_sessions()

    try:
        claims = _verify_google_token(body.id_token, audience)
    except Exception as exc:  # allow-silent: fail-closed 401, logged by type (never the token)
        logger.info("google token rejected: %s", type(exc).__name__)
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "invalid_google_token")
    if claims.get("aud") != audience:      # belt and braces on top of the library
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "invalid_google_token")
    if claims.get("email_verified") is not True:
        raise _fail(ip, status.HTTP_403_FORBIDDEN, "email_not_verified")
    if str(claims.get("email", "")).strip().lower() != allowed:
        raise _fail(ip, status.HTTP_403_FORBIDDEN, "email_not_allowlisted")

    ticket = ws.mem_put("preauth", ws.PREAUTH_TTL_SECONDS, {"email": allowed})
    return {
        "preauth_ticket": ticket,
        "expires_in": ws.PREAUTH_TTL_SECONDS,
        "passkey_enrolled": bool(ws.list_passkeys()),
    }


def _preauth(ticket: Optional[str]) -> Optional[dict[str, Any]]:
    return ws.mem_get("preauth", ticket) if ticket else None


# ---------------------------------------------------------------------------
# WebAuthn registration
# ---------------------------------------------------------------------------


class RegisterBegin(BaseModel):
    preauth_ticket: Optional[str] = None
    enrol_code: Optional[str] = None
    label: str = "This device"


class RegisterFinish(BaseModel):
    challenge_id: str
    credential: dict[str, Any]


def _session_from_request(request: Request) -> Optional[dict[str, Any]]:
    """A live device session on this request, or None (never raises)."""
    h = request.headers.get("Authorization", "")
    tok = h[len("Bearer "):].strip() if h.startswith("Bearer ") else ""
    if not tok.startswith(ws.SESSION_TOKEN_PREFIX):
        return None
    row = ws.validate_session(tok)
    return row if auth_module._session_row_allowed(row) else None


@router.post("/passkey/register/begin")
def register_begin(body: RegisterBegin, request: Request) -> dict[str, Any]:
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
        ResidentKeyRequirement, UserVerificationRequirement,
    )

    ip = _client_ip(request)
    _guard_rate(ip)
    _need_sessions()
    email = _allowed_email_or_503()

    session = _session_from_request(request)
    if session is not None:
        via = "session"                                  # adding a later device
    else:
        pre = _preauth(body.preauth_ticket)
        if pre is None:
            raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "invalid_preauth_ticket")
        # The code is burned here: a phished Google login alone cannot enrol.
        if not ws.consume_enrol_code(body.enrol_code or ""):
            raise _fail(ip, status.HTTP_403_FORBIDDEN, "invalid_enrol_code")
        via = "preauth"

    existing = [PublicKeyCredentialDescriptor(id=_b64d(p["id"])) for p in ws.list_passkeys()]
    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=RP_NAME,
        user_id=b"metis-operator",
        user_name=email,
        user_display_name=email,
        exclude_credentials=existing,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    cid = ws.mem_put("challenge", ws.CHALLENGE_TTL_SECONDS, {
        "challenge": options.challenge, "purpose": "register", "via": via,
        "label": body.label, "preauth_ticket": body.preauth_ticket,
    })
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/passkey/register/finish")
def register_finish(body: RegisterFinish, request: Request) -> dict[str, Any]:
    from webauthn import verify_registration_response
    from webauthn.helpers import bytes_to_base64url

    ip = _client_ip(request)
    _guard_rate(ip)
    _need_sessions()
    email = _allowed_email_or_503()
    state = ws.mem_take("challenge", body.challenge_id)            # single use
    if state is None or state["purpose"] != "register":
        raise _fail(ip, status.HTTP_400_BAD_REQUEST, "invalid_challenge")
    try:
        v = verify_registration_response(
            credential=body.credential,
            expected_challenge=state["challenge"],
            expected_rp_id=_rp_id(),
            expected_origin=_origins(),
            require_user_verification=True,
        )
    except Exception as exc:  # allow-silent: fail-closed 400, logged by type
        logger.info("passkey registration rejected: %s", type(exc).__name__)
        raise _fail(ip, status.HTTP_400_BAD_REQUEST, "registration_failed")

    cred_id = bytes_to_base64url(v.credential_id)
    try:
        ws.add_passkey(cred_id, v.credential_public_key, v.sign_count, email, state["label"])
    except Exception as exc:  # allow-silent: duplicate credential id (UNIQUE) -> 409, logged by type
        logger.info("passkey store refused: %s", type(exc).__name__)
        raise _fail(ip, status.HTTP_409_CONFLICT, "credential_already_registered")

    out: dict[str, Any] = {"ok": True, "credential_id": cred_id}
    if state["via"] == "preauth":
        # Registration proved possession of the authenticator: sign this device in.
        ws.mem_take("preauth", state["preauth_ticket"] or "")
        out.update(_issue_session(request, email, cred_id, state["label"]))
    return out


# ---------------------------------------------------------------------------
# WebAuthn assertion -> device session
# ---------------------------------------------------------------------------


class AssertBegin(BaseModel):
    preauth_ticket: str


class AssertFinish(BaseModel):
    preauth_ticket: str
    challenge_id: str
    credential: dict[str, Any]
    device_label: str = "Unnamed device"


@router.post("/passkey/assert/begin")
def assert_begin(body: AssertBegin, request: Request) -> dict[str, Any]:
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor, UserVerificationRequirement,
    )

    ip = _client_ip(request)
    _guard_rate(ip)
    _need_sessions()
    if _preauth(body.preauth_ticket) is None:
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "invalid_preauth_ticket")
    keys = ws.list_passkeys()
    if not keys:
        raise _err(status.HTTP_409_CONFLICT, "no_passkey_enrolled")
    options = generate_authentication_options(
        rp_id=_rp_id(),
        allow_credentials=[PublicKeyCredentialDescriptor(id=_b64d(k["id"])) for k in keys],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    cid = ws.mem_put("challenge", ws.CHALLENGE_TTL_SECONDS,
                     {"challenge": options.challenge, "purpose": "assert"})
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/passkey/assert/finish")
def assert_finish(body: AssertFinish, request: Request) -> dict[str, Any]:
    from webauthn import verify_authentication_response

    ip = _client_ip(request)
    _guard_rate(ip)
    _need_sessions()
    pre = _preauth(body.preauth_ticket)
    if pre is None:
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "invalid_preauth_ticket")
    state = ws.mem_take("challenge", body.challenge_id)            # single use
    if state is None or state["purpose"] != "assert":
        raise _fail(ip, status.HTTP_400_BAD_REQUEST, "invalid_challenge")

    cred_id = str(body.credential.get("id", ""))
    key = ws.get_passkey(cred_id)
    if key is None:
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "unknown_credential")
    try:
        v = verify_authentication_response(
            credential=body.credential,
            expected_challenge=state["challenge"],
            expected_rp_id=_rp_id(),
            expected_origin=_origins(),
            credential_public_key=key["public_key"],
            credential_current_sign_count=key["sign_count"],     # library rejects regression
            require_user_verification=True,
        )
    except Exception as exc:  # allow-silent: fail-closed 401, logged by type
        logger.info("passkey assertion rejected: %s", type(exc).__name__)
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "assertion_failed")
    # Compare-and-set so two racing copies of one assertion cannot both win.
    if not ws.advance_sign_count(cred_id, v.new_sign_count):
        raise _fail(ip, status.HTTP_401_UNAUTHORIZED, "assertion_failed")

    ws.mem_take("preauth", body.preauth_ticket)
    return _issue_session(request, pre["email"], cred_id, body.device_label)


def _issue_session(request: Request, email: str, passkey_id: str, label: str) -> dict[str, Any]:
    s = ws.create_session(
        email=email, passkey_id=passkey_id, label=label,
        user_agent=request.headers.get("User-Agent", ""), ip=_client_ip(request),
    )
    return {
        "session_token": s["token"],
        "token_type": "bearer",
        "session_handle": s["handle"],
        "expires_at": s["expires_at"],
        "expires_in": ws.SESSION_TTL_SECONDS,
    }


# ---------------------------------------------------------------------------
# Device sessions (always require a signed-in device, flag or no flag)
# ---------------------------------------------------------------------------


@router.get("/me")
def me(row: dict = Depends(auth_module.require_device_session)) -> dict[str, Any]:
    return {"email": row["email"], "session_handle": row["handle"],
            "expires_at": row["expires_at"]}


@router.get("/sessions")
def list_device_sessions(row: dict = Depends(auth_module.require_device_session)) -> dict[str, Any]:
    items = ws.list_sessions()
    for it in items:
        it["current"] = it["handle"] == row["handle"]
    return {"sessions": items}


@router.delete("/sessions/{handle}")
def revoke_device_session(handle: str, row: dict = Depends(auth_module.require_device_session)) -> dict[str, Any]:
    if not ws.revoke_session(handle):
        raise _err(status.HTTP_404_NOT_FOUND, "session_not_found")
    return {"revoked": handle}


@router.post("/sessions/{handle}/revoke")
def revoke_device_session_post(handle: str, row: dict = Depends(auth_module.require_device_session)) -> dict[str, Any]:
    """POST twin of the DELETE: the API's CORS allow-list is GET/POST only, so
    the browser SPA revokes through this one (CORS is load-bearing; untouched)."""
    return revoke_device_session(handle, row)


@router.delete("/sessions")
@router.post("/sessions/revoke-others")
def revoke_other_sessions(row: dict = Depends(auth_module.require_device_session)) -> dict[str, Any]:
    """'Sign out everywhere' = every session but the current one."""
    return {"revoked": ws.revoke_all_except(row["handle"])}


@router.post("/ws-ticket")
def ws_ticket(row: dict = Depends(auth_module.require_device_session)) -> dict[str, Any]:
    """60-second single-use ticket for ``WS /ws/market?ticket=...`` (a browser
    WebSocket cannot send an Authorization header)."""
    t = ws.mem_put("wsticket", ws.WS_TICKET_TTL_SECONDS, row["handle"])
    return {"ticket": t, "expires_in": ws.WS_TICKET_TTL_SECONDS}


def _b64d(s: str) -> bytes:
    from webauthn.helpers import base64url_to_bytes
    return base64url_to_bytes(s)

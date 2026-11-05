"""OAuth 2.1 sign-in for the console connector (gate G1; operator 2026-11-05 "Open 443 + Google OAuth").

claude.ai acts as the OAuth client: it discovers this server (RFC 9728 protected-resource metadata,
RFC 8414 authorization-server metadata), registers itself (RFC 7591 dynamic client registration),
and runs the authorization-code flow with PKCE (S256 only). The person signing in proves who they
are with a Google ID token from Google Identity Services, for the same public client id the trading
dashboard uses; the token's verified email must equal ALLOWED_EMAIL. No client secret exists
anywhere: claude.ai is a public client and Google sign-in is the browser ID-token flow.

State (registered clients, issued tokens) is kept in one JSON file. Tokens are stored only as
SHA-256 hashes, so the file never holds a usable credential.

Config (env): CONSOLE_CONNECTOR_AUTH=google|none, CONSOLE_CONNECTOR_BASE_URL (public origin),
GOOGLE_OAUTH_CLIENT_ID, ALLOWED_EMAIL, CONSOLE_CONNECTOR_STATE (path),
CONSOLE_CONNECTOR_REDIRECT_HOSTS (comma list, default claude.ai,claude.com).
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

CODE_TTL_S = 300
PENDING_TTL_S = 600
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 30 * 86400
GOOGLE_CLOCK_SKEW_S = 10


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pkce_s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def verify_google_id_token(token: str, audience: str) -> dict[str, Any]:
    """Signature, expiry, issuer and audience, checked by Google's own library (as the SPA does)."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token as g_id_token

    return g_id_token.verify_oauth2_token(token, g_requests.Request(), audience,
                                          clock_skew_in_seconds=GOOGLE_CLOCK_SKEW_S)


class OAuthError(Exception):
    def __init__(self, status: int, error: str, description: str = "") -> None:
        super().__init__(description or error)
        self.status, self.error, self.description = status, error, description

    def body(self) -> dict[str, str]:
        out = {"error": self.error}
        if self.description:
            out["error_description"] = self.description
        return out


class OAuthServer:
    def __init__(self, *, base_url: str, google_client_id: str, allowed_email: str, state_path: Path,
                 redirect_hosts: tuple[str, ...] = ("claude.ai", "claude.com"),
                 verifier: Callable[[str, str], dict[str, Any]] = verify_google_id_token,
                 clock: Callable[[], float] = time.time) -> None:
        self.base = base_url.rstrip("/")
        self.google_client_id = google_client_id
        self.allowed_email = allowed_email.strip().lower()
        self.state_path = state_path
        self.redirect_hosts = tuple(h.strip().lower() for h in redirect_hosts if h.strip())
        self.verifier = verifier
        self.clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}   # rid -> authorize request (memory only)
        self._codes: dict[str, dict[str, Any]] = {}     # code hash -> grant (memory only)
        self._state = self._load()

    # ---------- persistence ----------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            data = {}
        data.setdefault("clients", {})
        data.setdefault("access", {})
        data.setdefault("refresh", {})
        return data

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state))
        os.chmod(tmp, 0o600)
        tmp.replace(self.state_path)

    def _prune(self) -> None:
        now = self.clock()
        for table in ("access", "refresh"):
            for k in [k for k, v in self._state[table].items() if v["exp"] <= now]:
                del self._state[table][k]
        for k in [k for k, v in self._pending.items() if v["exp"] <= now]:
            del self._pending[k]
        for k in [k for k, v in self._codes.items() if v["exp"] <= now]:
            del self._codes[k]

    # ---------- metadata ----------
    def resource_metadata(self) -> dict[str, Any]:
        return {"resource": self.base + "/mcp", "authorization_servers": [self.base],
                "bearer_methods_supported": ["header"], "resource_name": "JTA Trader console (read-only)"}

    def server_metadata(self) -> dict[str, Any]:
        return {"issuer": self.base, "authorization_endpoint": self.base + "/authorize",
                "token_endpoint": self.base + "/token", "registration_endpoint": self.base + "/register",
                "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": ["console.read"]}

    def challenge_header(self) -> str:
        return f'Bearer resource_metadata="{self.base}/.well-known/oauth-protected-resource"'

    # ---------- registration ----------
    def _redirect_ok(self, uri: str) -> bool:
        try:
            u = urlparse(uri)
        except ValueError:
            return False
        host = (u.hostname or "").lower()
        return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in self.redirect_hosts)

    def register(self, body: dict[str, Any]) -> dict[str, Any]:
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
            raise OAuthError(400, "invalid_redirect_uri", "redirect_uris must be a non-empty list")
        bad = [u for u in uris if not self._redirect_ok(u)]
        if bad:
            raise OAuthError(400, "invalid_redirect_uri", f"redirect host not allowed: {bad[0]}")
        client_id = "jta-" + secrets.token_urlsafe(18)
        rec = {"redirect_uris": uris, "client_name": str(body.get("client_name") or "")[:100],
               "created": int(self.clock())}
        with self._lock:
            self._state["clients"][client_id] = rec
            self._save()
        return {"client_id": client_id, "client_id_issued_at": rec["created"], "redirect_uris": uris,
                "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "client_name": rec["client_name"]}

    # ---------- authorize ----------
    def begin_authorize(self, q: dict[str, str]) -> str:
        """Validate an /authorize request; return the pending-request id the sign-in page carries."""
        client = self._state["clients"].get(q.get("client_id", ""))
        if client is None:
            raise OAuthError(400, "invalid_client", "unknown client_id")
        redirect_uri = q.get("redirect_uri") or (client["redirect_uris"][0] if len(client["redirect_uris"]) == 1 else "")
        if redirect_uri not in client["redirect_uris"]:
            raise OAuthError(400, "invalid_request", "redirect_uri is not registered for this client")
        if q.get("response_type") != "code":
            raise OAuthError(400, "unsupported_response_type", "response_type must be code")
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            raise OAuthError(400, "invalid_request", "PKCE with code_challenge_method=S256 is required")
        rid = secrets.token_urlsafe(24)
        with self._lock:
            self._prune()
            self._pending[rid] = {"client_id": q["client_id"], "redirect_uri": redirect_uri,
                                  "code_challenge": q["code_challenge"], "state": q.get("state"),
                                  "scope": q.get("scope") or "console.read", "exp": self.clock() + PENDING_TTL_S}
        return rid

    def sign_in_page(self, rid: str) -> str:
        cid = html.escape(self.google_client_id, quote=True)
        rid_e = html.escape(rid, quote=True)
        return SIGN_IN_PAGE.replace("{{CLIENT_ID}}", cid).replace("{{RID}}", rid_e)

    def complete_authorize(self, rid: str, id_token: str) -> str:
        """Verify the Google ID token for a pending request; return the redirect URL carrying the code."""
        with self._lock:
            self._prune()
            req = self._pending.pop(rid, None)
        if req is None:
            raise OAuthError(400, "invalid_request", "sign-in request expired; start again from claude.ai")
        try:
            claims = self.verifier(id_token, self.google_client_id)
        except Exception as exc:  # noqa: BLE001  # allow-silent: fail closed as 401, never echo the token
            raise OAuthError(401, "access_denied", f"Google sign-in could not be verified ({type(exc).__name__})") from None
        if claims.get("aud") != self.google_client_id:
            raise OAuthError(401, "access_denied", "Google token was issued for another client")
        if claims.get("email_verified") is not True:
            raise OAuthError(403, "access_denied", "Google email is not verified")
        if not self.allowed_email or str(claims.get("email", "")).strip().lower() != self.allowed_email:
            raise OAuthError(403, "access_denied", "this Google account is not allowed")
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes[_h(code)] = {**req, "exp": self.clock() + CODE_TTL_S, "email": self.allowed_email}
        params = {"code": code}
        if req.get("state") is not None:
            params["state"] = req["state"]
        sep = "&" if "?" in req["redirect_uri"] else "?"
        return req["redirect_uri"] + sep + urlencode(params)

    # ---------- token ----------
    def _issue(self, client_id: str, scope: str) -> dict[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self.clock()
        self._state["access"][_h(access)] = {"client_id": client_id, "scope": scope, "exp": now + ACCESS_TTL_S}
        self._state["refresh"][_h(refresh)] = {"client_id": client_id, "scope": scope, "exp": now + REFRESH_TTL_S}
        self._save()
        return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL_S,
                "refresh_token": refresh, "scope": scope}

    def token(self, form: dict[str, str]) -> dict[str, Any]:
        grant = form.get("grant_type")
        client_id = form.get("client_id", "")
        with self._lock:
            self._prune()
            if client_id not in self._state["clients"]:
                raise OAuthError(401, "invalid_client", "unknown client_id")
            if grant == "authorization_code":
                rec = self._codes.pop(_h(form.get("code", "")), None)
                if rec is None or rec["client_id"] != client_id:
                    raise OAuthError(400, "invalid_grant", "code is invalid or expired")
                if form.get("redirect_uri") and form["redirect_uri"] != rec["redirect_uri"]:
                    raise OAuthError(400, "invalid_grant", "redirect_uri does not match")
                verifier = form.get("code_verifier", "")
                if not verifier or not secrets.compare_digest(pkce_s256(verifier), rec["code_challenge"]):
                    raise OAuthError(400, "invalid_grant", "PKCE verification failed")
                return self._issue(client_id, rec["scope"])
            if grant == "refresh_token":
                rec = self._state["refresh"].pop(_h(form.get("refresh_token", "")), None)
                if rec is None or rec["client_id"] != client_id:
                    self._save()
                    raise OAuthError(400, "invalid_grant", "refresh token is invalid or expired")
                return self._issue(client_id, rec["scope"])  # rotation: the old refresh token is spent
        raise OAuthError(400, "unsupported_grant_type", "use authorization_code or refresh_token")

    def check_bearer(self, authorization: str | None) -> bool:
        if not authorization or not authorization.lower().startswith("bearer "):
            return False
        tok = authorization.split(" ", 1)[1].strip()
        with self._lock:
            rec = self._state["access"].get(_h(tok))
            return bool(rec and rec["exp"] > self.clock())


def from_env(state_default: Path) -> OAuthServer | None:
    """The configured server, or None when CONSOLE_CONNECTOR_AUTH is not 'google'.

    With auth=google, missing config FAILS CLOSED: the caller refuses every /mcp request rather than
    serving unauthenticated (a mis-set env never opens the data)."""
    if os.environ.get("CONSOLE_CONNECTOR_AUTH", "none").strip().lower() != "google":
        return None
    return OAuthServer(
        base_url=os.environ.get("CONSOLE_CONNECTOR_BASE_URL", ""),
        google_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        allowed_email=os.environ.get("ALLOWED_EMAIL", ""),
        state_path=Path(os.environ.get("CONSOLE_CONNECTOR_STATE") or state_default),
        redirect_hosts=tuple((os.environ.get("CONSOLE_CONNECTOR_REDIRECT_HOSTS") or "claude.ai,claude.com").split(",")),
    )


SIGN_IN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · JTA Trader console</title>
<style>
:root{--bg:#f3f4f1;--fg:#1b201e;--muted:#5e6762;--line:#d8dcd6;--card:#fcfcfa;--bad:#ad2b22;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#111514;--fg:#e3e8e5;--muted:#97a19c;--line:#2a322f;--card:#181d1b;--bad:#ee7b70;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}
main{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:24px;max-width:380px;width:100%;display:grid;gap:14px}
h1{font-size:1.15rem;margin:0}p{margin:0;color:var(--muted)}#err{color:var(--bad)}
</style></head><body><main>
<h1>Sign in to the JTA Trader console</h1>
<p>claude.ai is asking for read-only access to the console data. Sign in with the Google account allowed for this system.</p>
<div id="g_id_onload" data-client_id="{{CLIENT_ID}}" data-callback="onGoogle" data-auto_prompt="false"></div>
<div class="g_id_signin" data-type="standard" data-text="signin_with" data-shape="rectangular"></div>
<p id="err" role="alert"></p>
</main>
<script>
async function onGoogle(resp){
  const err = document.getElementById("err"); err.textContent = "Checking…";
  try{
    const r = await fetch("/authorize/google", {method:"POST", headers:{"content-type":"application/json"},
                          body: JSON.stringify({rid: "{{RID}}", id_token: resp.credential})});
    const j = await r.json();
    if(r.ok && j.redirect){ err.textContent = "Signed in. Returning to claude.ai…"; location.assign(j.redirect); }
    else { err.textContent = j.error_description || j.error || "Sign-in failed."; }
  }catch(e){ err.textContent = "Sign-in failed: " + e; }
}
</script>
<script src="https://accounts.google.com/gsi/client" async></script>
</body></html>"""

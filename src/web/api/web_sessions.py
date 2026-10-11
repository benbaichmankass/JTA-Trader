"""UI-UPGRADE-1-AUTH — device sessions + passkey store (``web_sessions`` table).

Design: ``docs/plans/ui-upgrade-1-auth-and-keys-design.md`` §2a/§2c.
Operator decisions 2026-10-11 (checklist row ``UI-UPGRADE-1-AUTH``):
D1 = a new ``web_sessions`` table in ``trade_journal.db`` (this IS the
operator OK for the table); D3 = 30-day SLIDING sessions.

One table, three row kinds (D1 named a single table "holding device sessions
and passkey public keys", so enrolment codes ride in it too):

``passkey``  a registered WebAuthn credential: ``id`` = base64url credential
             id, ``public_key``, ``sign_count`` (enforced on every assertion).
``session``  a device session: ``id`` = HMAC-SHA256(``WEB_SESSION_PEPPER``,
             token) — the bearer token itself is NEVER stored; ``handle`` is
             the public, non-secret label used by list/revoke.
``enrol``    a one-time passkey enrolment code, stored HASHED, single-use,
             short expiry.

Short-lived ceremony state (WebAuthn challenges, 5-min pre-auth tickets, 60-s
ws tickets) is in-process memory only: the API runs as one uvicorn worker and
losing a 5-minute ticket on restart is harmless. It is not durable state.

Secrets are read per call (like ``auth.py``) so the systemd EnvironmentFile can
change without a restart and tests can monkeypatch.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Iterator, Optional

from src.utils.paths import trade_journal_db_path

SESSION_TTL_SECONDS = 30 * 24 * 3600          # D3: 30-day sliding
SLIDE_WRITE_INTERVAL_SECONDS = 60             # do not write last_seen per request
PREAUTH_TTL_SECONDS = 5 * 60
CHALLENGE_TTL_SECONDS = 5 * 60
WS_TICKET_TTL_SECONDS = 60
ENROL_CODE_TTL_SECONDS = 15 * 60
SESSION_TOKEN_PREFIX = "ws_"

# data-wiring: web_sessions is the SOURCE OF TRUTH for site device sessions and
# registered passkeys — operator-authored auth state, NOT a projection of any
# other table, so there is no upstream to backfill from and history begins at
# first sign-in (operator OK for this table: checklist row UI-UPGRADE-1-AUTH,
# decision D1, 2026-10-11). Sole writer: this module (called from
# src/web/api/routers/auth_google.py and the enrol-code CLI); sole readers:
# the same router and src/web/api/auth.py's session gate. Deliberately NOT in
# db_explorer's _TABLE_ALLOWLIST, so it is invisible in the Data Explorer.
_DDL = """
CREATE TABLE IF NOT EXISTS web_sessions (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    handle       TEXT,
    email        TEXT,
    label        TEXT,
    public_key   BLOB,
    sign_count   INTEGER NOT NULL DEFAULT 0,
    passkey_id   TEXT,
    user_agent   TEXT,
    ip           TEXT,
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER,
    expires_at   INTEGER,
    revoked_at   INTEGER,
    used_at      INTEGER
)
"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_web_sessions_kind ON web_sessions (kind)"


class SessionsUnavailable(RuntimeError):
    """``WEB_SESSION_PEPPER`` is not configured — sessions cannot be issued."""


def _pepper() -> bytes:
    p = os.environ.get("WEB_SESSION_PEPPER", "").strip()
    if not p:
        raise SessionsUnavailable("auth misconfigured")
    return p.encode("utf-8")


def hash_secret(value: str) -> str:
    """HMAC-SHA256(pepper, value) hex. Used for session tokens and enrol codes."""
    return hmac.new(_pepper(), value.encode("utf-8"), hashlib.sha256).hexdigest()


@contextlib.contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, ALWAYS close (sqlite3's own
    ``with conn`` only commits — it would leak one handle per request)."""
    conn = sqlite3.connect(trade_journal_db_path(), timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(_DDL)
        conn.execute(_INDEX)
        with conn:
            yield conn
    finally:
        conn.close()


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Passkeys
# ---------------------------------------------------------------------------


def add_passkey(credential_id: str, public_key: bytes, sign_count: int,
                email: str, label: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO web_sessions (id, kind, handle, email, label, public_key,"
            " sign_count, created_at) VALUES (?, 'passkey', ?, ?, ?, ?, ?, ?)",
            (credential_id, secrets.token_hex(6), email, label[:80],
             public_key, int(sign_count), _now()),
        )


def list_passkeys() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM web_sessions WHERE kind='passkey' AND revoked_at IS NULL"
        ).fetchall()
    return [dict(r) for r in rows]


def get_passkey(credential_id: str) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM web_sessions WHERE kind='passkey' AND id=? AND revoked_at IS NULL",
            (credential_id,),
        ).fetchone()
    return dict(r) if r else None


def advance_sign_count(credential_id: str, new_count: int) -> bool:
    """Compare-and-set: only moves the counter forward. False = lost a race
    (a concurrent/replayed assertion already advanced it)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE web_sessions SET sign_count=?, last_seen_at=? WHERE kind='passkey'"
            " AND id=? AND (sign_count < ? OR (sign_count=0 AND ?=0))",
            (int(new_count), _now(), credential_id, int(new_count), int(new_count)),
        )
        return cur.rowcount == 1


# ---------------------------------------------------------------------------
# Enrolment codes
# ---------------------------------------------------------------------------


def issue_enrol_code(*, ttl: int = ENROL_CODE_TTL_SECONDS) -> str:
    """Create a one-time enrolment code; returns the plaintext ONCE."""
    code = "-".join(secrets.token_hex(2) for _ in range(3))      # xxxx-xxxx-xxxx
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO web_sessions (id, kind, created_at, expires_at)"
            " VALUES (?, 'enrol', ?, ?)",
            (hash_secret("enrol:" + code), now, now + ttl),
        )
    return code


def consume_enrol_code(code: str) -> bool:
    """Atomically burn a valid, unexpired, unused code. Single-use."""
    if not code:
        return False
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE web_sessions SET used_at=? WHERE kind='enrol' AND id=?"
            " AND used_at IS NULL AND expires_at > ?",
            (now, hash_secret("enrol:" + code.strip().lower()), now),
        )
        return cur.rowcount == 1


# ---------------------------------------------------------------------------
# Device sessions
# ---------------------------------------------------------------------------


def create_session(*, email: str, passkey_id: str, label: str,
                   user_agent: str, ip: str) -> dict[str, Any]:
    token = SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)    # 256-bit
    now = _now()
    handle = secrets.token_hex(6)
    exp = now + SESSION_TTL_SECONDS
    with _connect() as conn:
        conn.execute(
            "INSERT INTO web_sessions (id, kind, handle, email, label, passkey_id,"
            " user_agent, ip, created_at, last_seen_at, expires_at)"
            " VALUES (?, 'session', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hash_secret(token), handle, email, label[:80], passkey_id,
             user_agent[:200], ip[:64], now, now, exp),
        )
    return {"token": token, "handle": handle, "expires_at": exp}


def validate_session(token: str) -> Optional[dict[str, Any]]:
    """Return the session row for a live bearer token, else ``None``.

    Live = exists, not revoked, not expired. Slides the expiry forward (at most
    one write per ``SLIDE_WRITE_INTERVAL_SECONDS``).
    """
    if not token.startswith(SESSION_TOKEN_PREFIX):
        return None
    try:
        sid = hash_secret(token)
    except SessionsUnavailable:
        return None
    now = _now()
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM web_sessions WHERE kind='session' AND id=?", (sid,)
        ).fetchone()
        if r is None or r["revoked_at"] is not None or (r["expires_at"] or 0) <= now:
            return None
        if now - (r["last_seen_at"] or 0) >= SLIDE_WRITE_INTERVAL_SECONDS:
            conn.execute(
                "UPDATE web_sessions SET last_seen_at=?, expires_at=? WHERE id=?",
                (now, now + SESSION_TTL_SECONDS, sid),
            )
    return dict(r)


def session_alive(handle: str) -> bool:
    """True iff the session with this public handle is unrevoked and unexpired."""
    with _connect() as conn:
        r = conn.execute(
            "SELECT revoked_at, expires_at FROM web_sessions WHERE kind='session' AND handle=?",
            (handle,),
        ).fetchone()
    return bool(r) and r["revoked_at"] is None and (r["expires_at"] or 0) > _now()


def list_sessions() -> list[dict[str, Any]]:
    now = _now()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT handle, label, user_agent, ip, created_at, last_seen_at, expires_at,"
            " revoked_at, passkey_id FROM web_sessions WHERE kind='session'"
            " ORDER BY created_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = d["revoked_at"] is None and (d["expires_at"] or 0) > now
        out.append(d)
    return out


def revoke_session(handle: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE web_sessions SET revoked_at=? WHERE kind='session' AND handle=?"
            " AND revoked_at IS NULL",
            (_now(), handle),
        )
        return cur.rowcount == 1


def revoke_all_except(keep_handle: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE web_sessions SET revoked_at=? WHERE kind='session'"
            " AND handle<>? AND revoked_at IS NULL",
            (_now(), keep_handle),
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# In-memory, short-lived ceremony state (single uvicorn worker — see module doc)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_mem: dict[str, dict[str, tuple[float, Any]]] = {
    "preauth": {}, "challenge": {}, "wsticket": {},
}
_MAX_ENTRIES = 2000


def mem_put(bucket: str, ttl: int, value: Any) -> str:
    key = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        store = _mem[bucket]
        if len(store) >= _MAX_ENTRIES:
            for k in [k for k, (exp, _) in store.items() if exp <= now]:
                store.pop(k, None)
            if len(store) >= _MAX_ENTRIES:
                store.pop(next(iter(store)), None)
        store[key] = (now + ttl, value)
    return key


def mem_get(bucket: str, key: str) -> Any:
    """Peek without consuming (pre-auth tickets are reusable within the window)."""
    with _lock:
        hit = _mem[bucket].get(key)
    if hit is None or hit[0] <= time.time():
        return None
    return hit[1]


def mem_take(bucket: str, key: str) -> Any:
    """Consume: single use. Returns the value once, ``None`` thereafter."""
    with _lock:
        hit = _mem[bucket].pop(key, None)
    if hit is None or hit[0] <= time.time():
        return None
    return hit[1]


def reset_memory_for_tests() -> None:
    with _lock:
        for b in _mem.values():
            b.clear()
    _fail_log.clear()


# Tiny failure limiter for the sign-in endpoints: N failures / window / IP.
_fail_log: dict[str, list[float]] = {}
FAIL_LIMIT = 10
FAIL_WINDOW_SECONDS = 300


def too_many_failures(ip: str) -> bool:
    now = time.time()
    with _lock:
        hits = [t for t in _fail_log.get(ip, []) if now - t < FAIL_WINDOW_SECONDS]
        _fail_log[ip] = hits
        return len(hits) >= FAIL_LIMIT


def record_failure(ip: str) -> None:
    with _lock:
        _fail_log.setdefault(ip, []).append(time.time())

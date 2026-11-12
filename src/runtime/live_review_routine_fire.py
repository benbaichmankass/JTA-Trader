"""Live-review IMMEDIATE wake: due event -> ONE routine fire -> a fresh reviewer session (TRADE-ACTION-DIRECT-PATH phase 3).

Operator, 2026-11-12 ~00:00Z (row TRADE-ACTION-DIRECT-PATH): "when the system recognizes that a review is needed, the
review needs to start immediately ... not through the repo." Decision page m5, 2026-11-12 07:49:44Z: "Accept the
defaults (15 min; all classes; advice rows get a button; yes to Tier-1 on the credential); I'll create the routine
and token". Design: docs/design/trade-action-direct-path-2026-11.md § 2.4.

``live_review_wake_post.run_once`` calls ``fire()`` once per pass with the entries it is about to post. Every entry
whose packet is on ``live-review/rows`` (``evidence_state`` committed / exists) and whose key was never fired goes
into ONE fire: the pass is single-flight at most once per ``MIN_INTERVAL_S`` (60 s), so every package due in the
same minute rides one fire (30 fires/h per routine, 100/h per account).

The endpoint (platform.claude.com/docs/en/api/claude-code/routines-fire, fetched 2026-11-12):
``POST https://api.anthropic.com/v1/claude_code/routines/{routine_id}/fire``, ``Authorization: Bearer <per-routine
token>``, ``anthropic-version`` required (the page's example value ``2026-10-21``; "accepts every version from
2023-06-01 on and behaves the same in each"), body ``{"text": <= 65,536 chars}``; ``200`` returns
``claude_code_session_id`` / ``claude_code_session_url``; ``429`` carries ``Retry-After``; no idempotency key.
Billing (same page): "Claude Code subscription usage on claude.ai", not Claude Platform (API) usage. No API key.

Dedupe (no idempotency key): one fire per ``order_package_id|event|level`` (the wake marker's own key, i.e. one per
package per due level of each event), recorded in ``runtime_logs/live_review/fires.jsonl`` (diag log_file
``live_review_fires``). A key is fired at most once, ever; a failed fire is NOT a fired key.

Fallback: on a 429, any other non-200, a transport error, or the 429 ``Retry-After`` window, nothing is fired and the
entries stay on today's path: the ``ltr-wake`` comment the caller posts anyway wakes the manager, who dispatches. ONE
red flag per incident (an incident opens on the first failure and closes on the next 200). Nothing halts.

Not configured: with ``LIVE_REVIEW_ROUTINE_TOKEN`` or ``LIVE_REVIEW_ROUTINE_ID`` unset (the VM ``.env``, loaded by
``pipeline.load_dotenv`` at start), ``fire()`` returns ``not_configured`` and the wake works exactly as before. This
is not a gate: no capability is withheld, the comment path is unchanged.

The token is read from the environment at fire time, sent only in the Authorization header, and never logged,
returned or written; the log and the receipt carry no part of it.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

ENV_TOKEN = "LIVE_REVIEW_ROUTINE_TOKEN"
ENV_ID = "LIVE_REVIEW_ROUTINE_ID"
FIRE_URL = "https://api.anthropic.com/v1/claude_code/routines/{routine_id}/fire"
#: platform.claude.com/docs/en/api/claude-code/routines-fire (2026-11-12): the documented example value.
ANTHROPIC_VERSION = "2026-10-21"
MAX_TEXT_CHARS = 65536
HTTP_TIMEOUT_S = 15
#: A 429 with no readable Retry-After backs off this long (the hourly window is the documented limit).
DEFAULT_RETRY_AFTER_S = 300
FIRES_LOG_REL = Path("runtime_logs") / "live_review" / "fires.jsonl"
STATE_REL = Path("runtime_logs") / "live_review" / "fire_state.json"
FIRES_LOG_MAX_BYTES = 16 * 1024 * 1024
EVIDENCE_OK = ("committed", "exists")
FLAG_KIND = "live_review_routine_fire_failed"

#: (status, parsed JSON body or None, headers). status None = transport error.
Post = Callable[[str, bytes, Dict[str, str]], Tuple[Optional[int], Any, Dict[str, str]]]


def _root() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root())


def fires_log_path() -> Path:
    return _root() / FIRES_LOG_REL


def state_path() -> Path:
    return _root() / STATE_REL


def fire_key(e: Mapping[str, Any]) -> str:
    return f"{e.get('order_package_id')}|{e.get('event')}|{e.get('level')}"


def read_config(env: Mapping[str, str] = os.environ) -> Optional[Tuple[str, str]]:
    tok, rid = (env.get(ENV_TOKEN) or "").strip(), (env.get(ENV_ID) or "").strip()
    return (tok, rid) if tok and rid else None


def _http_post(url: str, body: bytes, headers: Dict[str, str]) -> Tuple[Optional[int], Any, Dict[str, str]]:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:  # noqa: S310 — fixed https host
            raw = r.read()
            code, hdrs = r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as exc:
        raw, code = exc.read() or b"", exc.code
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, {"transport_error": type(exc).__name__}, {}
    try:
        return code, json.loads(raw) if raw else None, hdrs
    except ValueError:
        return code, None, hdrs


def fired_keys(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """key -> the successful fire that carried it. An unreadable log reads as empty (fire again rather than drop)."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        lines = (path or fires_log_path()).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("state") == "fired":
            for k in r.get("keys") or []:
                out[str(k)] = {"session_id": r.get("session_id"), "fired_at": r.get("fired_at")}
    return out


def _append(rec: Dict[str, Any], path: Optional[Path] = None) -> None:
    try:
        p = path or fires_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > FIRES_LOG_MAX_BYTES:
            # Keep the fired keys across the rotation: the dedupe must not forget them.
            keep = [json.dumps({"state": "fired", "keys": [k], "session_id": v.get("session_id"),
                                "fired_at": v.get("fired_at"), "carried_over": True}, sort_keys=True)
                    for k, v in fired_keys(p).items()]
            os.replace(p, p.with_suffix(".jsonl.1"))
            p.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    except Exception:  # noqa: BLE001 — a log failure never reaches the wake
        logger.warning("ltr-routine-fire: fires log write failed", exc_info=True)


def _load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    try:
        d = json.loads((path or state_path()).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(st: Dict[str, Any], path: Optional[Path] = None) -> None:
    try:
        p = path or state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001
        logger.warning("ltr-routine-fire: state write failed", exc_info=True)


def _retry_after(headers: Mapping[str, str], now: datetime) -> datetime:
    v = (headers or {}).get("retry-after")
    if v:
        try:
            return now + timedelta(seconds=max(1.0, float(v)))
        except ValueError:
            try:
                dt = parsedate_to_datetime(v)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return now + timedelta(seconds=DEFAULT_RETRY_AFTER_S)


def _ts(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def build_text(entries: List[Dict[str, Any]], bundles: Optional[Dict[str, Dict[str, Any]]],
               now: datetime) -> str:
    """The fire payload: the due event as ONE JSON document (the routine receives it as a literal string).

    Per package the same block an ``ltr-wake`` comment carries (``packet``, ``packet_sha``, ``table_path``,
    ``table``) while it fits under the 65,536-char cap; past it the block is left out (``packet_omitted``) and the
    reviewer reads the packet from ``live-review/rows`` (it is committed before any fire)."""
    ev_keys = ("order_package_id", "leg", "symbol", "accounts", "event", "level", "why", "due_at",
               "review_id", "packet_sha", "evidence_state", "evidence_commit", "due_computed_at")
    doc: Dict[str, Any] = {"kind": "ltr-routine-fire", "fired_at": now.isoformat(),
                           "entries": [{k: e.get(k) for k in ev_keys if e.get(k) is not None} for e in entries],
                           "packets": {}, "packet_omitted": []}
    budget = MAX_TEXT_CHARS - len(json.dumps(doc, default=str)) - 512
    for pkg in dict.fromkeys(str(e.get("order_package_id")) for e in entries):
        b = (bundles or {}).get(pkg) or {}
        blk = {k: b.get(k) for k in ("packet_sha", "table_path", "packet", "table")}
        s = json.dumps(blk, sort_keys=True, separators=(",", ":"), default=str)
        if b.get("packet") and len(s) + len(pkg) + 8 <= budget:
            doc["packets"][pkg] = blk
            budget -= len(s) + len(pkg) + 8
        else:
            doc["packet_omitted"].append(pkg)
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)


def _flag(text: str, send: Optional[Callable[[str], Any]]) -> bool:
    try:
        if send is not None:
            return bool(send(text))
        from src.runtime import notify
        return bool(notify.send_telegram_direct(text, parse_mode=None, kind=FLAG_KIND, priority="high"))
    except Exception:  # noqa: BLE001
        logger.warning("ltr-routine-fire: red flag send failed", exc_info=True)
        return False


def _fallback(entries: List[Dict[str, Any]], state: str, reason: str) -> None:
    for e in entries:
        e["routine_fire"] = {"state": state, "reason": reason}


def fire(entries: List[Dict[str, Any]], bundles: Optional[Dict[str, Dict[str, Any]]], *,
         now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
         env: Mapping[str, str] = os.environ, post: Post = _http_post,
         log_path: Optional[Path] = None, state_file: Optional[Path] = None,
         send: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Fire the routine once for every eligible, never-fired entry. Stamps ``routine_fire`` on each entry
    (``fired`` / ``already_fired`` / a fallback state) and returns a receipt summary. Never raises."""
    try:
        return _fire(entries, bundles, now_fn, env, post, log_path, state_file, send)
    except Exception as exc:  # noqa: BLE001 — contained: the comment path still posts
        logger.warning("ltr-routine-fire: fire failed", exc_info=True)
        _fallback(entries, "fire_error", type(exc).__name__)
        return {"state": "fire_error", "reason": f"{type(exc).__name__}: {exc}"}


def _fire(entries, bundles, now_fn, env, post, log_path, state_file, send) -> Dict[str, Any]:
    cfg = read_config(env)
    if cfg is None:
        logger.info("ltr-routine-fire: not_configured (%s / %s unset); the ltr-wake comment path is unchanged",
                    ENV_TOKEN, ENV_ID)
        return {"state": "not_configured"}
    token, routine_id = cfg
    done = fired_keys(log_path)
    todo: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for e in entries:
        k = fire_key(e)
        if k in done:
            e["routine_fire"] = dict(done[k], state="already_fired")
        elif e.get("evidence_state") in EVIDENCE_OK and e.get("packet_sha"):
            todo.append(e)
        else:
            e["routine_fire"] = {"state": "not_fired_no_evidence"}
            skipped.append(k)
    out: Dict[str, Any] = {"already_fired": [fire_key(e) for e in entries if fire_key(e) in done]}
    if skipped:
        out["not_fired_no_evidence"] = skipped
    if not todo:
        out["state"] = "nothing_to_fire"
        return out
    keys = [fire_key(e) for e in todo]
    out["keys"] = keys
    now = now_fn()
    st = _load_state(state_file)
    until = _ts(st.get("retry_after_until"))
    if until and now < until:
        _fallback(todo, "rate_limited_backoff", f"429 Retry-After until {until.isoformat()}")
        out.update(state="rate_limited_backoff", retry_after_until=until.isoformat())
        _append({"fired_at": now.isoformat(), "state": "rate_limited_backoff", "keys": keys,
                 "retry_after_until": until.isoformat(), "fallback": "ltr-wake comment"}, log_path)
        return out
    text = build_text(todo, bundles, now)
    headers = {"Authorization": f"Bearer {token}", "anthropic-version": ANTHROPIC_VERSION,
               "Content-Type": "application/json"}
    code, data, hdrs = post(FIRE_URL.format(routine_id=routine_id), json.dumps({"text": text}).encode(), headers)
    fired_at = now_fn()
    rec: Dict[str, Any] = {"fired_at": fired_at.isoformat(), "keys": keys, "http_code": code,
                           "text_chars": len(text), "latency_s": round((fired_at - now).total_seconds(), 3)}
    dues = [_ts(e.get("due_at")) for e in todo]
    dues = [d for d in dues if d]
    if dues:
        rec["due_to_fire_s"] = round((fired_at - min(dues)).total_seconds(), 1)
    sid = data.get("claude_code_session_id") if isinstance(data, dict) else None
    if code == 200 and sid:
        rec.update(state="fired", session_id=sid,
                   session_url=data.get("claude_code_session_url") if isinstance(data, dict) else None)
        _append(rec, log_path)
        for e in todo:
            e["routine_fire"] = {"state": "fired", "session_id": sid, "fired_at": fired_at.isoformat()}
        if st.get("incident_open") or st.get("retry_after_until"):
            st.update(incident_open=False, incident_closed_at=fired_at.isoformat(), retry_after_until=None)
            _save_state(st, state_file)
        out.update(state="fired", session_id=sid, http_code=code)
        return out
    if code == 429:
        state, reason = "rate_limited", "429 rate_limit_error"
        st["retry_after_until"] = _retry_after(hdrs, fired_at).isoformat()
        rec["retry_after_until"] = st["retry_after_until"]
    elif code is None:
        state, reason = "could_not_fire", f"transport: {(data or {}).get('transport_error')}"
    else:
        err = ((data or {}).get("error") or {}).get("type") if isinstance(data, dict) else None
        state, reason = "could_not_fire", f"http {code}" + (f" {err}" if err else "") + ("" if code != 200 else " no session id")
    rec.update(state=state, reason=reason, fallback="ltr-wake comment")
    _fallback(todo, state, reason)
    if not st.get("incident_open"):
        st.update(incident_open=True, incident_opened_at=fired_at.isoformat(), incident_reason=reason)
        rec["flagged"] = _flag(
            f"LTR routine fire failed ({reason}) for {len(keys)} due event(s); the ltr-wake comment wakes the "
            f"manager as before (fallback). One flag per incident: the next successful fire closes it. "
            f"Receipt: /api/diag/log_file?name=live_review_fires", send)
    _save_state(st, state_file)
    _append(rec, log_path)
    out.update(state=state, reason=reason, http_code=code, flagged=rec.get("flagged"))
    return out

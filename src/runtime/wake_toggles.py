"""Wake-notification toggles: which wake comments reach the manager session.

Operator 2026-11-07: *"we just need to be able to toggle off those notifications when we're not using those
session types"* / *"I don't want to lose the timing of the real money ltr, just to toggle off the notifications
that reach you"* / *"an easy toggle ... something I can toggle from the console dashboard"*.

Gates this adds or changes: none. A toggle decides only whether a SESSION IS WOKEN by a comment on the ops-flags
PR. It never decides what trades, what is reviewed, or whether a packet is built: when a switch is off the poster
still builds and lands its packet / evidence and writes a ``suppressed_by_wake_toggle`` receipt; only the comment
is withheld.

State lives in RUNTIME STATE on the VM (``runtime_state/wake_toggles.json``, not a git-tracked file): a flip needs
no deploy, restart or PR, persists across restarts, and every poster reads it live each pass.

* VM posters read the file directly (``is_on``).
* GitHub-runner posters set ``WAKE_TOGGLES_REMOTE=1`` and read ``GET /api/bot/wake-toggles`` instead.
* **Unreadable state => post.** Silence is never the default for a doubt (real-money timing is not traded for it).
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: key -> (label, default ON?, group).  The switches the console renders, in order.
TOGGLES: Dict[str, Dict[str, Any]] = {
    "ltr_real_money": {"label": "Live-trade review: real money", "default": True, "group": "ltr"},
    "ltr_prop": {"label": "Live-trade review: prop", "default": True, "group": "ltr"},
    "ltr_paper": {"label": "Live-trade review: paper", "default": False, "group": "ltr"},
    "alert_watch": {"label": "Alert watch", "default": True, "group": "alerts"},
    "desk_wake": {"label": "Desk wake (hourly scan)", "default": False, "group": "desk"},
    "desk_could_not_build": {"label": "Desk: could-not-build notice", "default": False, "group": "desk"},
    "desk_trigger_wake": {"label": "Desk trigger wake", "default": False, "group": "desk"},
    "short_hold": {"label": "Short-hold wake", "default": False, "group": "short_hold"},
}
#: telegram_policy.account_class -> toggle key.  Unknown accounts ride the real-money switch (never silenced by doubt).
LTR_CLASS_KEY = {"real_money": "ltr_real_money", "prop": "ltr_prop",
                 "paper_portfolio": "ltr_paper", "testing_paper": "ltr_paper"}
REMOTE_URL = "https://ict-bot.duckdns.org/api/bot/wake-toggles"
SUPPRESSED_RECEIPT = "suppressed_by_wake_toggle"
_RATE_S = 3600.0
_logged: Dict[str, float] = {}


def _service_headers() -> dict:
    """``Authorization: Bearer $DASHBOARD_API_TOKEN`` when the token is in the
    environment, else nothing: the read-only service credential the site gate
    accepts on GET/HEAD once ``SITE_AUTH_ENFORCE`` is on (UI-OAUTH-SIGNIN; ignored
    while it is off). Only ever sent to this project's own API."""
    tok = os.environ.get("DASHBOARD_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _state_dir() -> Path:
    from src.utils.paths import runtime_state_dir
    return Path(runtime_state_dir())


def state_path() -> Path:
    return _state_dir() / "wake_toggles.json"


def flip_log_path() -> Path:
    return _state_dir() / "wake_toggles_flips.jsonl"


def suppressed_log_path() -> Path:
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir()) / "wake_toggle_suppressed.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _defaults() -> Dict[str, bool]:
    return {k: bool(v["default"]) for k, v in TOGGLES.items()}


def read_local(path: Optional[Path] = None) -> Dict[str, Any]:
    """``{read_state: read|defaults|could_not_look, toggles: {key: bool}, detail: {...}}``. Never raises.

    ``defaults`` = no file yet (nobody has flipped anything): the initial state applies. ``could_not_look`` = the
    file exists but cannot be parsed: ``toggles`` is None-free all-ON-for-safety is NOT applied here, ``is_on`` fails
    open instead (a doubt posts)."""
    p = path or state_path()
    try:
        if not p.exists():
            return {"read_state": "defaults", "toggles": _defaults(), "detail": {}}
        doc = json.loads(p.read_text())
        raw = doc.get("toggles") if isinstance(doc, dict) else None
        if not isinstance(raw, dict):
            raise ValueError("toggles missing")
        out, detail = _defaults(), {}
        for k in TOGGLES:
            v = raw.get(k)
            if isinstance(v, dict) and isinstance(v.get("on"), bool):
                out[k] = v["on"]
                detail[k] = {"changed_at": v.get("changed_at"), "changed_by": v.get("changed_by")}
        return {"read_state": "read", "toggles": out, "detail": detail}
    except Exception as exc:  # noqa: BLE001 - unreadable state is a state, not a raise
        return {"read_state": "could_not_look", "toggles": None, "detail": {}, "error": type(exc).__name__}


def read_remote(url: str = REMOTE_URL, timeout: float = 8.0) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wake-toggles-client", "Accept": "application/json",
                                                   **_service_headers()})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
            doc = json.loads(r.read())
        t = doc.get("toggles") if isinstance(doc, dict) else None
        if doc.get("read_state") not in ("read", "defaults") or not isinstance(t, dict):
            raise ValueError("bad payload")
        return {"read_state": doc["read_state"], "toggles": {k: bool(t.get(k, d)) for k, d in _defaults().items()},
                "detail": {}}
    except Exception as exc:  # noqa: BLE001
        return {"read_state": "could_not_look", "toggles": None, "detail": {}, "error": type(exc).__name__}


def read(remote: Optional[bool] = None) -> Dict[str, Any]:
    use_remote = (os.environ.get("WAKE_TOGGLES_REMOTE") == "1") if remote is None else remote
    return read_remote() if use_remote else read_local()


def is_on(key: str, state: Optional[Dict[str, Any]] = None) -> bool:
    """True = post the comment. Unknown key or unreadable state => True (never silence by doubt)."""
    if key not in TOGGLES:
        return True
    st = state if state is not None else read()
    t = st.get("toggles")
    return True if not isinstance(t, dict) else bool(t.get(key, True))


def ltr_keys_for_accounts(accounts: List[Any], classify: Any = None) -> List[str]:
    """Toggle keys for the account classes an LTR entry spans. An unknown account maps to real money."""
    if classify is None:
        try:
            from src.runtime.telegram_policy import account_class as classify
        except Exception:  # noqa: BLE001
            classify = lambda a: "unknown_account"  # noqa: E731
    keys = []
    for a in accounts or []:
        try:
            c = classify(a)
        except Exception:  # noqa: BLE001
            c = "unknown_account"
        k = LTR_CLASS_KEY.get(c, "ltr_real_money")
        if k not in keys:
            keys.append(k)
    return keys or ["ltr_real_money"]


def ltr_entry_on(entry: Dict[str, Any], state: Optional[Dict[str, Any]] = None, classify: Any = None) -> bool:
    """An LTR entry posts when ANY class it spans is ON (a mixed package is never half-silenced)."""
    st = state if state is not None else read()
    return any(is_on(k, st) for k in ltr_keys_for_accounts(entry.get("accounts") or [], classify))


LTR_CLASS_LABEL = {"ltr_real_money": "real-money", "ltr_prop": "prop", "ltr_paper": "paper"}


def ltr_label(entries: List[Dict[str, Any]], classify: Any = None) -> str:
    """'real-money/prop' only for classes actually present in the posted entries (the old head always said so)."""
    seen: List[str] = []
    for e in entries:
        for k in ltr_keys_for_accounts(e.get("accounts") or [], classify):
            if k not in seen:
                seen.append(k)
    order = ["ltr_real_money", "ltr_prop", "ltr_paper"]
    return "/".join(LTR_CLASS_LABEL[k] for k in order if k in seen) or "real-money"


def log_suppressed(key: str, subject: str = "", **kw: Any) -> None:
    """Receipt ``suppressed_by_wake_toggle`` (rate-limited per key+subject; never raises)."""
    try:
        ident = f"{key}|{subject}"
        t = time.monotonic()
        if t - _logged.get(ident, -_RATE_S) < _RATE_S:
            return
        _logged[ident] = t
        p = suppressed_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict({"at": _now(), "receipt": SUPPRESSED_RECEIPT, "toggle": key, "subject": subject},
                                     **kw), default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("wake-toggles: suppress receipt write failed", exc_info=True)


def set_toggle(key: str, on: bool, by: str, path: Optional[Path] = None) -> Dict[str, Any]:
    """Flip one switch. Atomic write + one audit line (who/when/old/new). Raises KeyError / OSError."""
    if key not in TOGGLES:
        raise KeyError(key)
    p = path or state_path()
    cur = read_local(p)
    if cur["read_state"] == "could_not_look":  # a corrupt file is replaced from defaults, and the audit says so
        cur = {"toggles": _defaults(), "detail": {}, "read_state": "defaults"}
    old = cur["toggles"][key]
    detail = dict(cur.get("detail") or {})
    for k in TOGGLES:
        detail.setdefault(k, None)
    at = _now()
    doc = {"version": 1, "toggles": {}}
    for k in TOGGLES:
        d = detail.get(k) or {}
        doc["toggles"][k] = {"on": cur["toggles"][k], "changed_at": d.get("changed_at"), "changed_by": d.get("changed_by")}
    doc["toggles"][key] = {"on": bool(on), "changed_at": at, "changed_by": by}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, p)
    lp = flip_log_path() if path is None else p.with_name(p.stem + "_flips.jsonl")
    with open(lp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": at, "key": key, "old": old, "new": bool(on), "by": by}) + "\n")
    return read_local(p)


def recent_flips(limit: int = 20, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    try:
        lp = (path.with_name(path.stem + "_flips.jsonl") if path else flip_log_path())
        lines = lp.read_text().splitlines()[-limit:]
        return [json.loads(x) for x in reversed(lines) if x.strip()]
    except Exception:  # noqa: BLE001
        return []

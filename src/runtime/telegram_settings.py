"""ONE notification-settings store + ONE cadence gate, shared by all three channels.

Operator, 2026-10-11 (checklist row ``TELEGRAM-CHANNELS``, part C): each
channel's menu gets a settings button to toggle notification TYPES and set the
CADENCE of every periodic update — *per channel / per update*, but built as ONE
mechanism: one store (this file's JSON), one gate (:func:`is_due`), one menu
component (``src/bot/notification_settings_menu.py``).

WHAT IS STORED (``runtime_state/telegram_settings.json``, gitignored, anchored
to the repo checkout so every unit — ``ict-telegram-bot``,
``ict-claude-bridge``, ``ict-claude-decision-bot``, ``ict-hourly-snapshot``,
``ict-work-digest`` — reads the SAME file regardless of data-dir drop-ins;
override with ``TELEGRAM_SETTINGS_PATH``):

* ``muted``     — kinds the operator switched off. A kind in
  ``telegram_channels.UNMUTABLE`` is refused here AND ignored on read, so a
  hand-edited file can never silence an alert.
* ``cadence``   — periodic update -> one of :data:`CADENCES`.
* ``last_sent`` — periodic update -> ISO time of the last confirmed send; the
  gate and the "since last update" window both read it.

DEFAULTS == TODAY'S BEHAVIOUR: nothing muted, every periodic update hourly. An
absent or UNREADABLE file reads as the defaults (``read_state`` says which) —
on a notification path a broken store must announce itself by over-sending,
never by silence.

⚠️ NEVER A HALT. ``off`` stops a periodic DIGEST the operator chose to stop;
it never touches alerts, red flags, decisions or trading.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "runtime_state" / "telegram_settings.json"

#: choice -> period in hours (0 == off). Order is the menu's button order.
CADENCES: Final[dict[str, int]] = {"1h": 1, "4h": 4, "12h": 12, "24h": 24, "off": 0}
CADENCE_LABELS: Final[dict[str, str]] = {
    "1h": "hourly", "4h": "every 4h", "12h": "twice a day", "24h": "once a day", "off": "off"}
DEFAULT_CADENCE: Final = "1h"

#: periodic update -> (channel, human name). One row per channel today; the
#: mechanism takes any number.
PERIODIC: Final[dict[str, tuple[str, str]]] = {
    "system_health": ("system", "Health check"),
    "trades_snapshot": ("trades", "Performance snapshot"),
    "manager_update": ("manager", "Manager update"),
}

#: Toggleable event TYPES per channel: group -> (label, kinds). Aliases that are
#: one thing to the operator (``trade_opened`` / ``trade-open``) are one row.
TOGGLES: Final[dict[str, dict[str, tuple[str, tuple[str, ...]]]]] = {
    "trades": {
        "opened": ("Trade opened", ("trade_opened", "trade-open")),
        "closed": ("Trade closed", ("trade_closed", "trade-close")),
        "updated": ("Trade updated / stop moved", ("trade_updated", "trade-update")),
        "demo": ("Demo-account trades", ("demotrade",)),
        "prop_fill": ("Prop fills", ("prop_fill",)),
        "prop_monitor": ("Prop position updates", ("prop_monitor",)),
    },
    "system": {
        "pipeline": ("Pipeline results", ("pipeline_result",)),
        "news": ("News veto", ("news_veto",)),
        "deploy": ("Deploys", ("deploy",)),
        "heartbeat": ("Daily heartbeat", ("daily_heartbeat",)),
    },
    "manager": {
        "pr_merged": ("PR merged", ("pr_merged",)),
        "session": ("Session pings", ("session",)),
    },
}

#: A missed slot is caught up once it is this late (timer jitter / downtime).
_CATCH_UP_GRACE = timedelta(minutes=30)


def _path() -> Path:
    p = os.environ.get("TELEGRAM_SETTINGS_PATH")
    return Path(p) if p else DEFAULT_PATH


def _unmutable() -> frozenset[str]:
    from src.runtime.telegram_channels import UNMUTABLE

    return UNMUTABLE


def load(path: Optional[Path] = None) -> dict[str, Any]:
    """The store, never raising. ``read_state``: ``read`` · ``absent`` ·
    ``unreadable`` — the last two serve defaults and are never confused."""
    p = path or _path()
    base = {"muted": [], "cadence": {}, "last_sent": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {**base, "read_state": "absent"}
    except (OSError, ValueError) as exc:
        logger.warning("telegram_settings: store unreadable (%s) — serving defaults",
                       type(exc).__name__)
        return {**base, "read_state": "unreadable"}
    if not isinstance(raw, dict):
        return {**base, "read_state": "unreadable"}
    out = {**base, **{k: raw.get(k) for k in base if isinstance(raw.get(k), type(base[k]))}}
    out["read_state"] = "read"
    for k in ("updated_at", "updated_by"):
        if k in raw:
            out[k] = raw[k]
    return out


def _save(d: dict, path: Optional[Path] = None) -> None:
    p = path or _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {k: d[k] for k in ("muted", "cadence", "last_sent", "updated_at", "updated_by") if k in d}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _mutate(fn, *, by: str, path: Optional[Path] = None) -> dict:
    d = load(path)
    fn(d)
    d["updated_at"] = datetime.now(timezone.utc).isoformat()
    d["updated_by"] = by
    _save(d, path)
    return d


# ── TYPES ──────────────────────────────────────────────────────────────────

def is_muted(kind: str, path: Optional[Path] = None) -> bool:
    """Is *kind* switched off? An UNMUTABLE kind is never muted, whatever the
    file says."""
    if kind in _unmutable():
        return False
    return kind in set(load(path).get("muted") or [])


def set_muted(kind: str, muted: bool, *, by: str, path: Optional[Path] = None) -> dict:
    if muted and kind in _unmutable():
        raise ValueError(f"{kind!r} is an alert-class kind and can never be muted")

    def fn(d):
        s = set(d.get("muted") or [])
        (s.add if muted else s.discard)(kind)
        d["muted"] = sorted(s)
    return _mutate(fn, by=by, path=path)


def group_muted(channel: str, group: str, path: Optional[Path] = None) -> bool:
    _, kinds = TOGGLES[channel][group]
    muted = set(load(path).get("muted") or [])
    return all(k in muted for k in kinds)


def set_group_muted(channel: str, group: str, muted: bool, *, by: str,
                    path: Optional[Path] = None) -> dict:
    _, kinds = TOGGLES[channel][group]
    if muted and any(k in _unmutable() for k in kinds):
        raise ValueError(f"group {group!r} contains an unmutable kind")

    def fn(d):
        s = set(d.get("muted") or [])
        for k in kinds:
            (s.add if muted else s.discard)(k)
        d["muted"] = sorted(s)
    return _mutate(fn, by=by, path=path)


# ── CADENCE ────────────────────────────────────────────────────────────────

def cadence(update: str, path: Optional[Path] = None) -> str:
    c = (load(path).get("cadence") or {}).get(update)
    return c if c in CADENCES else DEFAULT_CADENCE


def set_cadence(update: str, choice: str, *, by: str, path: Optional[Path] = None) -> dict:
    if update not in PERIODIC:
        raise ValueError(f"unknown periodic update {update!r}")
    if choice not in CADENCES:
        raise ValueError(f"unknown cadence {choice!r}")

    def fn(d):
        d.setdefault("cadence", {})[update] = choice
    return _mutate(fn, by=by, path=path)


def last_sent(update: str, path: Optional[Path] = None) -> Optional[datetime]:
    v = (load(path).get("last_sent") or {}).get(update)
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return t if (t is None or t.tzinfo) else t.replace(tzinfo=timezone.utc)


def is_due(update: str, now: Optional[datetime] = None,
           path: Optional[Path] = None) -> tuple[bool, str]:
    """THE gate. ``(due, why)``.

    Slots are aligned to UTC hours divisible by the period (4h -> 00/04/08…,
    twice a day -> 00/12, once a day -> 00), so a change of cadence takes effect
    at the next slot. A slot already served is not served twice; a slot missed
    (timer down) is caught up once the gap exceeds the period + 30 min.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    choice = cadence(update, path)
    n = CADENCES[choice]
    if n == 0:
        return False, "cadence off"
    prev = last_sent(update, path)
    slot = now.replace(minute=0, second=0, microsecond=0)
    slot = slot - timedelta(hours=slot.hour % n)
    if prev is not None and prev >= slot:
        return False, f"slot {slot:%H}:00Z already sent"
    if now.hour % n == 0:
        return True, f"{choice} slot {slot:%H}:00Z"
    if prev is None or now - prev >= timedelta(hours=n) + _CATCH_UP_GRACE:
        return True, f"{choice} catch-up (last {prev.isoformat() if prev else '—'})"
    return False, f"{choice}: next slot not reached"


def window_start(update: str, now: Optional[datetime] = None,
                 path: Optional[Path] = None) -> datetime:
    """Start of the "since last update" window: the last send when it is
    recent enough to be meaningful, else one cadence period (min 1h)."""
    now = now or datetime.now(timezone.utc)
    n = CADENCES[cadence(update, path)] or 1
    prev = last_sent(update, path)
    if prev is not None and timedelta(0) < now - prev <= timedelta(hours=n) + timedelta(hours=2):
        return prev
    return now - timedelta(hours=n)


def mark_sent(update: str, now: Optional[datetime] = None, path: Optional[Path] = None) -> None:
    """Stamp a confirmed send. Best-effort: a failed stamp re-sends next slot."""
    t = (now or datetime.now(timezone.utc)).isoformat()
    try:
        d = load(path)
        d.setdefault("last_sent", {})[update] = t
        _save(d, path)
    except OSError as exc:
        logger.warning("telegram_settings: could not stamp %s (%s)", update, exc)

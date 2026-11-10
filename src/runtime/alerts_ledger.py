"""The alert ledger: ONE append-only EVENT LOG of what the system told the operator.

Row shape ``{ts, kind, channel, priority, dedup_key, body[:1024], delivered}``,
written at the send chokepoint (``notify``'s direct-send function) and by
``POST /api/bot/alerts`` for shell / workflow senders that curl Telegram directly.
Design: ``docs/audits/2026-11-04-system-integration.md`` § "Design: how alerts,
data and state reach the manager" (row ``ALERT-LEDGER-TO-MANAGER``).

Gates this adds or changes: **none**. :func:`append` is a best-effort side-write:
any failure logs a warning and returns ``False``; the send it observes proceeds
exactly as before. Nothing here blocks, delays or conditions a send.

This is an EVENT LOG on the VM (``runtime_logs/alerts_ledger.jsonl``), never a
follow-through register and never committed to the repo. It records no work: a
class of alert that needs work becomes a dated row in the one register.

``delivered`` splits the three outcomes that used to look identical:
``telegram_ok`` (Telegram confirmed) · ``skipped_no_creds`` (nothing sent) ·
``raised`` (the send raised). Shell / workflow rows may also carry ``unknown``
(the sender could not say) — never folded into ``telegram_ok``.

READ STATES, never collapsed: ``read`` (the file was read) · ``absent`` (no ledger
exists on this host — nothing has been written yet, which is not "0 alerts
fired anywhere") · ``could_not_look`` (it exists but could not be read).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LEDGER_NAME = "alerts_ledger.jsonl"
#: Rotation: keep the newest KEEP rows once the file passes 2x KEEP (same
#: amortised trim ``operator_alerts.jsonl`` uses).
KEEP = 5000
BODY_MAX = 1024
#: Reads scan at most this many trailing lines (the population is reported).
READ_MAX_LINES = 20000

DELIVERED_VALUES = ("telegram_ok", "skipped_no_creds", "raised", "unknown",
                    # TELEGRAM-TRIM (operator 2026-11-04): kept OFF Telegram by
                    # config/telegram_policy.yaml — recorded here so the UI and the
                    # manager still see it. Wakes the manager only for a high flag or non-routine system kind (wakes_manager).
                    "suppressed_by_policy")
#: Kinds that are replies inside a conversation, not alerts: never ledgered.
SKIP_KINDS = frozenset({"reply", "command_reply"})
#: Kinds a human reads as ``high`` priority. Everything else is ``normal``.
HIGH_KINDS = frozenset({"alert", "execution_alert", "prop_alert", "red_flag"})
#: SYSTEM-channel kinds that are routine status, not an alert: the wake pass
#: (channel==system) skips them so the manager is not woken every hour.
ROUTINE_KINDS = frozenset({
    "hourly_report", "system_health", "daily_heartbeat", "pipeline_result",
    "news_veto", "deploy", "trades_snapshot", "work_digest_receipt",
})

_LOCK = threading.Lock()


def ledger_path() -> Path:
    if os.environ.get("ALERTS_LEDGER_PATH"):   # test isolation / one-off reads
        return Path(os.environ["ALERTS_LEDGER_PATH"])
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir()) / LEDGER_NAME


def default_dedup_key(kind: str, body: str) -> str:
    """kind + the first line with digits normalised, so a per-tick repeat of one
    condition collapses to one key (``close failing 3`` == ``close failing 4``)."""
    first = next((ln.strip() for ln in str(body or "").splitlines() if ln.strip()), "")
    return f"{kind}:{re.sub(r'[0-9]+', '#', first)[:80]}"


def priority_for(kind: str) -> str:
    return "high" if kind in HIGH_KINDS else "normal"


def build_row(kind: str, channel: str, body: str, *, priority: Optional[str] = None,
              dedup_key: Optional[str] = None, delivered: str = "unknown",
              ts: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kind = str(kind or "unclassified")
    body = str(body or "")
    row = {
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "channel": str(channel or "unknown"),
        "priority": str(priority or priority_for(kind)),
        "dedup_key": str(dedup_key or default_dedup_key(kind, body)),
        "body": body[:BODY_MAX],
        "delivered": delivered if delivered in DELIVERED_VALUES else "unknown",
    }
    # Flat scalar extras (e.g. the TELEGRAM-TRIM reason / account / package_id);
    # never shadowing a core field.
    for k, v in (extra or {}).items():
        if str(k) not in row and (v is None or isinstance(v, (str, int, float, bool))):
            row[str(k)] = v
    return row


def append(kind: str, channel: str, body: str, *, priority: Optional[str] = None,
           dedup_key: Optional[str] = None, delivered: str = "unknown",
           path: Optional[Path] = None, extra: Optional[Dict[str, Any]] = None) -> bool:
    """Append one row. Best-effort: returns False and logs on any failure."""
    if str(kind or "") in SKIP_KINDS:
        return False
    try:
        row = build_row(kind, channel, body, priority=priority, dedup_key=dedup_key,
                        delivered=delivered, extra=extra)
        p = path or ledger_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            _maybe_trim(p)
        return True
    except Exception as exc:  # noqa: BLE001  # allow-silent: ledger is a best-effort side-write; the send it observes must proceed unchanged
        logger.warning("alerts_ledger: append failed (send unaffected): %s", exc)
        return False


def _maybe_trim(p: Path) -> None:
    try:
        if p.stat().st_size < KEEP * 2 * 200:   # cheap pre-check: ~200 B/row floor
            return
        with p.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) > KEEP * 2:
            tmp = p.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                fh.writelines(lines[-KEEP:])
            os.replace(tmp, p)
    except OSError:
        pass


def parse_since(since: Any) -> Optional[datetime]:
    """ISO timestamp, ``<n>h`` / ``<n>m`` / ``<n>d`` relative, or None."""
    if since is None or str(since).strip() == "":
        return None
    s = str(since).strip()
    m = re.fullmatch(r"(\d+)\s*([mhd])", s)
    if m:
        n, u = int(m.group(1)), m.group(2)
        return datetime.now(timezone.utc) - timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[u]: n})
    dt = _parse_ts(s)
    if dt is None:
        raise ValueError(f"unparseable since={since!r}")
    return dt


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read(since: Any = None, kind: Optional[str] = None, channel: Optional[str] = None,
         *, limit: int = 500, path: Optional[Path] = None) -> Dict[str, Any]:
    """The one read. ``read_state`` first: ``rows`` is meaningful only when it is
    ``read``. A ledger that cannot be read is ``could_not_look``, never 0 rows."""
    p = path or ledger_path()
    out: Dict[str, Any] = {
        "read_state": "read", "path": p.name, "rows": [], "counts_by_kind": {},
        "newest_ts": None, "total_matching": 0,
        "population": {"lines_scanned": 0, "lines_unparseable": 0, "truncated": False,
                       "scan_cap_lines": READ_MAX_LINES, "ledger_rows_total": None},
    }
    try:
        cutoff = parse_since(since)
    except ValueError as exc:
        out["read_state"] = "could_not_look"
        out["reason"] = str(exc)
        return out
    if not p.is_file():
        out["read_state"] = "absent"
        return out
    try:
        with p.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        out["read_state"] = "could_not_look"
        out["reason"] = f"{type(exc).__name__}"
        return out
    pop = out["population"]
    pop["ledger_rows_total"] = len(lines)
    if len(lines) > READ_MAX_LINES:
        pop["truncated"] = True
        lines = lines[-READ_MAX_LINES:]
    matched: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        pop["lines_scanned"] += 1
        try:
            r = json.loads(line)
            if not isinstance(r, dict):
                raise ValueError("not an object")
        except (ValueError, TypeError):
            pop["lines_unparseable"] += 1
            continue
        if kind and r.get("kind") != kind:
            continue
        if channel and r.get("channel") != channel:
            continue
        if cutoff is not None:
            dt = _parse_ts(r.get("ts"))
            if dt is None or dt < cutoff:
                continue
        matched.append(r)
    counts: Dict[str, int] = {}
    for r in matched:
        counts[str(r.get("kind"))] = counts.get(str(r.get("kind")), 0) + 1
    out["counts_by_kind"] = counts
    out["total_matching"] = len(matched)
    out["newest_ts"] = matched[-1].get("ts") if matched else None
    out["rows"] = matched[-max(1, int(limit)):]
    out["rows_truncated_to_limit"] = len(matched) > len(out["rows"])
    return out


def wakes_manager(row: Dict[str, Any]) -> bool:
    """The wake rule: ``channel == system`` (non-routine kinds) or ``priority ==
    high``. The trades channel never wakes the manager."""
    ch, kind = row.get("channel"), str(row.get("kind"))
    prio = str(row.get("priority") or "").lower()
    high = prio in ("high", "urgent", "critical")
    # TELEGRAM-TRIM (operator 2026-11-10): muting is OPERATOR-ONLY. A row kept off Telegram by policy
    # still wakes the manager when it would have woken it delivered (a high/urgent flag, or a
    # non-routine system kind), so a stuck paper action is still seen and fixed. A ROUTINE
    # suppressed row (normal trade open/close/update, prop_monitor, snapshots) does not wake.
    if ch == "trades":
        # delivered trades rows never wake; a SUPPRESSED high flag does (it never reached the operator)
        return row.get("delivered") == "suppressed_by_policy" and high
    if high:
        return True
    return ch == "system" and kind not in ROUTINE_KINDS

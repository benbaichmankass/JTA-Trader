"""Trading-desk WAKE, VM side (DESK-6B): every 1h bar -> ONE ops-flags comment -> manager.

Operator, 2026-10-26: the hourly desk wake should be triggered from the system itself, through the
same channel as the other triggers (ltr-wake), with the VM holding the timer, rather than as a Claude
routine. Crypto trades 24/7, so the desk wakes EVERY 1h bar: there is NO market-hours or activity
gate. The value is centralization: one VM trigger path, VM receipts, VM liveness. Model:
``live_review_wake_post`` (same credential, ops-flags PR, single-flight daemon thread, receipt style).

Per 1h bar:

1. read ``comms/desk/latest_scan.json`` on ``desk/decisions`` (``desk-scan-packet.yml`` writes it at
   :03), then the packet it points at; verify the packet's sha against the pointer. Missing, stale
   (> ``PACKET_MAX_AGE_MIN``) or sha-mismatched -> receipt ``could_not_look`` with the reason, no post;
2. dedupe on the PACKET ID, not the clock: skip when a ``DD-*`` decision row for that packet is already
   on ``desk/decisions`` (``already_recorded``) or a ``desk-wake`` marker for it is already on the PR
   (``already_posted``). The scan packet can land late (Actions backlog: a :03 packet landed at :33), so
   the poster polls every pass and posts as soon as an unrecorded packet exists, never at a fixed minute;
3. post ONE ``desk-wake`` marker comment. The manager is subscribed to that PR; on the marker it
   ``create_session``s the wake exactly as ``.claude/skills/trading-desk/SKILL.md`` § 6b specifies.

The marker also carries the packet's context as INFORMATION (``context``: open positions, open desk
proposals, near-signal count, calendar events, unread books). None of it suppresses a wake.

No halting: a failed read or post is a receipt state and the next pass retries (until the packet
ages out).

Credential: the ubuntu user's global git extraheader, read in process, never logged or written
(``live_review_wake_post.read_auth_header``). Live VM only: ``kick()`` is a no-op unless this process
is ``python -m src.main``.

Receipt: ``runtime_logs/desk_wake_post_receipt.json`` via
``/api/diag/log_file?name=desk_wake_post_receipt``. ``state``: ``posted`` (``comment_url``,
``context``) · ``already_posted`` · ``already_recorded`` · ``could_not_look`` (``reason``) · ``could_not_post``
(``http_code`` / ``reason``). ``last_post`` is carried forward across passes. Written on every pass, so
its ``computed_at`` is the poster's liveness (``attention_watch`` probe ``desk_wake_post``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.runtime import live_review_wake_post as ltr_post

logger = logging.getLogger(__name__)

RECEIPT_NAME = "desk_wake_post_receipt.json"
MARKER = "desk-wake"
REPO = ltr_post.REPO
API = ltr_post.API
BRANCH = "desk/decisions"
POINTER_PATH = "comms/desk/latest_scan.json"
DECISIONS_PATH = "comms/desk/decisions.jsonl"
#: One pass per this many seconds (a pass is one pointer GET once the bar is handled).
MIN_INTERVAL_S = 120
HTTP_TIMEOUT_S = 10
#: A packet built longer ago than this is not "this hour's": the builder missed a run.
PACKET_MAX_AGE_MIN = 90
BAR = timedelta(hours=1)
NEAR_BARS = (0, 1)

_LOCK = threading.Lock()
_last_kick = float("-inf")
#: bar key -> terminal state this process already reached for it.
_handled: Dict[str, str] = {}
_cached_markers: List[dict] = []

Http = ltr_post.Http
Fetch = Callable[[str, Optional[str]], Tuple[Optional[int], Any]]


def receipt_path() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / RECEIPT_NAME


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def bar_of(cutoff: datetime) -> datetime:
    return cutoff.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def packet_sha(packet: dict) -> str:
    """Same function as ``scripts/ci/check_desk_records.py::packet_sha``."""
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_markers(comments: Optional[list]) -> List[dict]:
    out: List[dict] = []
    for c in comments or []:
        body = str((c or {}).get("body") or "")
        i = body.find(f"<!-- {MARKER} ")
        if i < 0:
            continue
        j = body.find("-->", i)
        try:
            out.append(json.loads(body[i + len(MARKER) + 6:j]))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------------- context (information only)

def _calendar_events(universe: List[dict], now: datetime) -> List[str]:
    out: List[str] = []
    try:
        from src.news.news_events import event_risk_for_symbol
    except Exception:  # noqa: BLE001
        event_risk_for_symbol = None  # type: ignore[assignment]
    for r in universe:
        sym = str(r.get("symbol"))
        cal = r.get("calendar") or {}
        if cal.get("read_state") == "read" and cal.get("events_next_bar"):
            out.append(f"{sym}:packet:{','.join(map(str, cal['events_next_bar']))}")
            continue
        if event_risk_for_symbol is not None:
            try:
                risk, meta = event_risk_for_symbol(sym, now)
            except Exception:  # noqa: BLE001
                continue
            if risk and risk > 0:
                out.append(f"{sym}:{meta.get('class')}@{meta.get('time')} risk={risk:.2f}")
    return out


def packet_context(packet: dict, now: datetime) -> Dict[str, Any]:
    """Pure. What the packet holds, recorded on the marker. It never decides whether to wake.
    An unread book is ``None`` (we could not look), never 0."""
    sb, db = packet.get("system_book") or {}, packet.get("desk_book") or {}
    sb_ok = sb.get("read_state") == "read" and sb.get("items") is not None
    db_ok = db.get("read_state") == "read" and db.get("items") is not None
    items = [i for i in (sb.get("items") or []) if isinstance(i, dict)] if sb_ok else []
    unread = [n for n, ok in (("system_book", sb_ok), ("desk_book", db_ok)) if not ok]
    if sb_ok and sb.get("near_signals_read_state") != "read":
        unread.append("near_signals")
    return {
        "open_positions": sum(1 for i in items if i.get("status") == "open") if sb_ok else None,
        "open_desk_proposals": len(db["items"]) if db_ok else None,
        "near_signals": (sum(1 for i in items if i.get("status") != "open" and i.get("bars_to_signal") in NEAR_BARS)
                         if sb_ok and sb.get("near_signals_read_state") == "read" else None),
        "calendar_events": _calendar_events([r for r in packet.get("universe") or [] if isinstance(r, dict)], now)[:4],
        "unread": unread,
    }


# ----------------------------------------------------------------------------- io

def _get(url: str, auth: Optional[str]) -> Tuple[Optional[int], Any]:
    """(status, parsed JSON or None). Raw media type: the contents API returns the file body."""
    headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "metis-desk-wake-vm"}
    if auth:
        headers["Authorization"] = auth
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            try:
                return resp.status, (json.loads(raw) if raw else None)
            except ValueError:
                return resp.status, raw.decode("utf-8", "replace")  # a .jsonl file
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001
        return None, None


def recorded_packet_ids(text: str) -> set:
    """packet_id of every decision row (``DD-*``) already on the branch."""
    out = set()
    for line in str(text or "").splitlines():
        try:
            pid = json.loads(line).get("packet_id")
        except (ValueError, AttributeError):
            continue
        if pid:
            out.add(pid)
    return out


def _contents_url(path: str) -> str:
    return f"{API}/repos/{REPO}/contents/{path}?ref={urllib.parse.quote(BRANCH, safe='')}"


def read_packet(fetch: Fetch, auth: Optional[str]) -> Tuple[Optional[dict], Optional[dict], Optional[str]]:
    """(pointer, packet, why-not). ``why-not`` None means both were read and the sha verified."""
    code, ptr = fetch(_contents_url(POINTER_PATH), auth)
    if code != 200 or not isinstance(ptr, dict) or not ptr.get("packet_id") or not ptr.get("path"):
        return None, None, f"latest_scan unreadable (http {code})"
    code, pk = fetch(_contents_url(str(ptr["path"])), auth)
    if code != 200 or not isinstance(pk, dict):
        return ptr, None, f"packet {ptr.get('packet_id')} unreadable (http {code})"
    if ptr.get("packet_sha") and packet_sha(pk) != ptr["packet_sha"]:
        return ptr, None, f"packet {ptr.get('packet_id')} sha does not match the pointer"
    return ptr, pk, None


def render(entry: Dict[str, Any], now: datetime) -> str:
    marker = dict(entry, kind="desk-wake", posted_at=now.isoformat())
    c = entry["context"]
    info = (f"open positions {c['open_positions']}, open desk proposals {c['open_desk_proposals']}, "
            f"near signals {c['near_signals']}, calendar events {len(c['calendar_events'])}, unread {c['unread'] or 'none'}")
    return "\n".join([
        f"**desk-wake: bar {entry['bar']}** — packet `{entry['packet_id']}` "
        f"(sha `{str(entry['packet_sha'])[:12]}`, built {entry['built_at']}). "
        "Manager: `create_session` the desk wake exactly as `.claude/skills/trading-desk/SKILL.md` § 6b "
        "specifies (outcome_branch/source_revision `desk/decisions`, the WAKE PROMPT).",
        "", f"Packet context (information only; every bar wakes): {info}", "",
        f"<!-- {MARKER} {json.dumps(marker, separators=(',', ':'), default=str)} -->",
        "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


def _load_last_post(path: Optional[Path]) -> Optional[dict]:
    try:
        return (json.loads((path or receipt_path()).read_text()) or {}).get("last_post")
    except Exception:  # noqa: BLE001
        return None


def run_once(fetch: Fetch = _get,
             auth_fn: Callable[[], Optional[str]] = ltr_post.read_auth_header,
             http: Http = ltr_post._http,
             now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             receipt: Optional[Path] = None,
             pr_fn: Optional[Callable[[], int]] = None) -> Dict[str, Any]:
    """One packet -> at most one comment. Returns (and writes) the receipt."""
    global _cached_markers
    now = now_fn()
    rec: Dict[str, Any] = {"computed_at": now.isoformat(), "poster": "vm"}
    last_post = _load_last_post(receipt)
    if last_post:
        rec["last_post"] = last_post

    def done(state: str, **kw: Any) -> Dict[str, Any]:
        rec.update(state=state, **kw)
        ltr_post.write_receipt(rec, receipt or receipt_path())
        return rec

    auth = auth_fn()
    ptr, pk, why = read_packet(fetch, auth)
    if why:
        return done("could_not_look", reason=why)
    cutoff, built = _ts(ptr.get("info_cutoff_at")), _ts(ptr.get("built_at"))
    if cutoff is None or built is None:
        return done("could_not_look", reason="pointer has no parseable info_cutoff_at/built_at")
    bar = _iso(bar_of(cutoff))
    rec.update(bar=bar, packet_id=ptr["packet_id"], packet_sha=ptr.get("packet_sha"), built_at=ptr["built_at"])
    if now - built > timedelta(minutes=PACKET_MAX_AGE_MIN):
        return done("could_not_look", reason=f"stale_packet: newest packet built {ptr['built_at']}, "
                                             f"older than {PACKET_MAX_AGE_MIN} min")
    pid = ptr["packet_id"]
    if pid in _handled:
        return done(_handled[pid], note="packet already handled by this process")
    # A wake that already recorded a row for this packet needs no new wake (operator/manager
    # 2026-10-26: key on the packet id, not the clock). Unreadable -> could_not_look, retried.
    code, text = fetch(_contents_url(DECISIONS_PATH), auth)
    if code != 200 or not isinstance(text, str):
        return done("could_not_look", reason=f"decisions.jsonl unreadable (http {code})")
    if pid in recorded_packet_ids(text):
        _handled[pid] = "already_recorded"
        return done("already_recorded")

    ctx = packet_context(pk, now)
    rec["context"] = ctx

    if not auth:
        return done("could_not_post", http_code=None, reason="no_credential_in_git_extraheader")
    try:
        pr = pr_fn() if pr_fn else ltr_post.wake_module().ops_flags_pr()
    except Exception as exc:  # noqa: BLE001
        return done("could_not_post", http_code=None, reason=f"ops_flags_pr unreadable: {type(exc).__name__}")
    rec["pr"] = pr
    markers, code = ltr_post.read_markers(SimpleNamespace(parse_markers=parse_markers), pr, auth, now, http)
    if markers is None:
        return done("could_not_post", http_code=code, reason="marker_read_failed: dedupe unknown")
    _cached_markers = markers
    if any(m.get("packet_id") == pid for m in markers):
        _handled[pid] = "already_posted"
        return done("already_posted")

    entry = {"bar": bar, "packet_id": ptr["packet_id"], "packet_sha": ptr.get("packet_sha"),
             "path": ptr.get("path"), "built_at": ptr["built_at"], "poster": "vm",
             "context": ctx}
    body = render(entry, now)
    code, data = http("POST", f"{API}/repos/{REPO}/issues/{pr}/comments", json.dumps({"body": body}).encode(), auth)
    rec["http_code"] = code
    if code != 201:
        return done("could_not_post", reason="comment_post_failed")
    posted_at = now_fn()
    url = (data or {}).get("html_url") if isinstance(data, dict) else None
    _handled[pid] = "already_posted"
    _cached_markers = markers + parse_markers([{"body": body}])
    rec["last_post"] = {"bar": bar, "packet_id": ptr["packet_id"], "posted_at": posted_at.isoformat(),
                        "comment_url": url, "context": ctx}
    return done("posted", posted_at=posted_at.isoformat(), comment_url=url)


def _run_locked() -> None:
    try:
        run_once()
    except Exception:  # noqa: BLE001 — contained: never reaches the tick loop
        logger.warning("desk-wake-post: pass failed", exc_info=True)
        ltr_post.write_receipt({"computed_at": datetime.now(timezone.utc).isoformat(), "poster": "vm",
                               "state": "could_not_post", "http_code": None,
                               "reason": "exception (see bot log)"}, receipt_path())
    finally:
        _LOCK.release()


def kick(force: bool = False) -> bool:
    """Start one background pass if due. Never blocks, never raises."""
    global _last_kick
    try:
        if not (force or ltr_post._is_live_trader()):
            return False
        t = time.monotonic()
        if t - _last_kick < MIN_INTERVAL_S:
            return False
        if not _LOCK.acquire(blocking=False):
            return False
        _last_kick = t
        try:
            threading.Thread(target=_run_locked, name="desk-wake-post", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False

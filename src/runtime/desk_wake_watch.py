"""Trading-desk wake WATCH, VM side (DESK-6B): did the packet that landed also wake the desk?

The desk wake is posted by the step that LANDS the packet (``desk-scan-packet.yml`` ->
``scripts/ops/desk_wake_marker.py post``): the session must never start before its packet exists, so
nothing is clock-timed and nothing polls to trigger it (operator 2026-10-26 ~16:50Z). This module posts
NOTHING. It is the VM's receipt and liveness for that trigger path (the shape of the LTR poster's
receipt): about every ``MIN_INTERVAL_S`` the live trader looks at the newest packet pointer on
``desk/decisions``, the ``desk-wake`` markers on the ops-flags PR and the decision rows, and writes one
receipt so "did the trigger fire" is readable through ``/api/diag/log_file?name=desk_wake_post_receipt``
and a stopped trigger raises one flag (``attention_watch`` probes ``desk_wake_post``).

States (``state``), for the newest packet ``packet_id`` on the pointer:

* ``posted``           a ``desk-wake`` marker for that packet id is on the PR (``posted_at``, ``latency_s``
                       from the packet's ``built_at``; ``commit`` is the packet commit the marker names);
* ``already_recorded`` a ``DD-*`` row for it is on ``desk/decisions`` (the wake ran);
* ``awaiting_wake``    the packet is younger than ``WAKE_GRACE_MIN`` and no marker yet;
* ``wake_missing``     the packet is older than that with neither marker nor row: the trigger did not fire
                       (an incident, named; the watch never posts the wake itself);
* ``could_not_build``  the packet job's failure step posted a ``could_not_build`` marker for the current
                       hour and no newer packet exists (``step`` named);
* ``could_not_look``   the pointer / decisions / PR comments were unreadable (``reason``), or the newest
                       packet is older than ``PACKET_MAX_AGE_MIN`` with no failure marker (``stale_packet``).

Read-only (public GitHub reads; the credential, when present, only raises the rate limit). Live VM only:
``kick()`` is a no-op unless this process is ``python -m src.main``. No halting: every failure is a
receipt state and the next pass looks again.
"""
from __future__ import annotations

import hashlib
import importlib.util
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
from typing import Any, Callable, Dict, Optional, Tuple

from src.runtime import live_review_wake_post as ltr_post

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKER_SCRIPT = ROOT / "scripts" / "ops" / "desk_wake_marker.py"
RECEIPT_NAME = "desk_wake_post_receipt.json"
REPO = ltr_post.REPO
API = ltr_post.API
BRANCH = "desk/decisions"
POINTER_PATH = "comms/desk/latest_scan.json"
DECISIONS_PATH = "comms/desk/decisions.jsonl"
MIN_INTERVAL_S = 300
HTTP_TIMEOUT_S = 10
#: The packet job posts the marker seconds after its commit; this long without one is a missing wake.
WAKE_GRACE_MIN = 10
#: Newest packet older than this with no failure marker: the packet job is not running.
PACKET_MAX_AGE_MIN = 90

_LOCK = threading.Lock()
_last_kick = float("-inf")
_marker_mod: Any = None

Fetch = Callable[[str, Optional[str]], Tuple[Optional[int], Any]]


def receipt_path() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / RECEIPT_NAME


def marker_module() -> Any:
    """The marker script's module, loaded from its file (scripts/ is not a package)."""
    global _marker_mod
    if _marker_mod is None:
        spec = importlib.util.spec_from_file_location("_desk_wake_marker", MARKER_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _marker_mod = mod
    return _marker_mod


def packet_sha(packet: dict) -> str:
    """Same function as ``scripts/ci/check_desk_records.py::packet_sha``."""
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _get(url: str, auth: Optional[str]) -> Tuple[Optional[int], Any]:
    """(status, parsed JSON, or text for a .jsonl, or None). Raw media type: the file body."""
    headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "metis-desk-wake-watch-vm"}
    if auth:
        headers["Authorization"] = auth
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            try:
                return resp.status, (json.loads(raw) if raw else None)
            except ValueError:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001
        return None, None


def _contents_url(path: str) -> str:
    return f"{API}/repos/{REPO}/contents/{path}?ref={urllib.parse.quote(BRANCH, safe='')}"


def recorded_packet_ids(text: str) -> set:
    out = set()
    for line in str(text or "").splitlines():
        try:
            pid = json.loads(line).get("packet_id")
        except (ValueError, AttributeError):
            continue
        if pid:
            out.add(pid)
    return out


def run_once(fetch: Fetch = _get,
             auth_fn: Callable[[], Optional[str]] = ltr_post.read_auth_header,
             http: ltr_post.Http = ltr_post._http,
             now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             receipt: Optional[Path] = None,
             pr_fn: Optional[Callable[[], int]] = None) -> Dict[str, Any]:
    """One look. Returns (and writes) the receipt. Never posts."""
    now = now_fn()
    rec: Dict[str, Any] = {"computed_at": now.isoformat(), "watcher": "vm"}
    try:
        prior = json.loads((receipt or receipt_path()).read_text())
        if prior.get("last_posted"):
            rec["last_posted"] = prior["last_posted"]
    except Exception:  # noqa: BLE001
        pass

    def done(state: str, **kw: Any) -> Dict[str, Any]:
        rec.update(state=state, **kw)
        ltr_post.write_receipt(rec, receipt or receipt_path())
        return rec

    auth = auth_fn()
    code, ptr = fetch(_contents_url(POINTER_PATH), auth)
    if code != 200 or not isinstance(ptr, dict) or not ptr.get("packet_id") or not ptr.get("path"):
        return done("could_not_look", reason=f"latest_scan unreadable (http {code})")
    built = _ts(ptr.get("built_at"))
    if built is None:
        return done("could_not_look", reason="pointer has no parseable built_at")
    pid = ptr["packet_id"]
    rec.update(packet_id=pid, packet_sha=ptr.get("packet_sha"), built_at=ptr["built_at"],
               packet_age_min=round((now - built).total_seconds() / 60, 1))

    code, text = fetch(_contents_url(DECISIONS_PATH), auth)
    if code != 200 or not isinstance(text, str):
        return done("could_not_look", reason=f"decisions.jsonl unreadable (http {code})")
    try:
        pr = pr_fn() if pr_fn else ltr_post.wake_module().ops_flags_pr()
        mm = marker_module()
    except Exception as exc:  # noqa: BLE001
        return done("could_not_look", reason=f"ops_flags_pr / marker module unreadable: {type(exc).__name__}")
    rec["pr"] = pr
    markers, mcode = ltr_post.read_markers(SimpleNamespace(parse_markers=mm.parse_markers), pr, auth, now, http)
    if markers is None:
        return done("could_not_look", reason=f"ops-flags comments unreadable (http {mcode})")

    mine = [m for m in markers if m.get("packet_id") == pid]
    if mine:
        posted_at = _ts(mine[-1].get("posted_at"))
        info = {"packet_id": pid, "posted_at": mine[-1].get("posted_at"), "commit": mine[-1].get("commit")}
        rec["last_posted"] = info
        return done("posted", posted_at=info["posted_at"], commit=info["commit"],
                    latency_s=round((posted_at - built).total_seconds(), 1) if posted_at else None)
    if pid in recorded_packet_ids(text):
        return done("already_recorded")
    age = now - built
    if age < timedelta(minutes=WAKE_GRACE_MIN):
        return done("awaiting_wake")
    fails = [m for m in markers if m.get("kind") == "could_not_build"
             and (_ts(m.get("posted_at")) or built) > built]
    if fails:
        return done("could_not_build", step=fails[-1].get("step"), bar=fails[-1].get("bar"))
    if age > timedelta(minutes=PACKET_MAX_AGE_MIN):
        return done("could_not_look", reason=f"stale_packet: newest packet built {ptr['built_at']}, older than "
                                              f"{PACKET_MAX_AGE_MIN} min and no could_not_build marker")
    return done("wake_missing", reason=f"packet {pid} landed {age.total_seconds() / 60:.0f} min ago; no desk-wake "
                                       "marker and no decision row (the packet job's post step did not run)")


def _run_locked() -> None:
    try:
        run_once()
    except Exception:  # noqa: BLE001 — contained: never reaches the tick loop
        logger.warning("desk-wake-watch: pass failed", exc_info=True)
        ltr_post.write_receipt({"computed_at": datetime.now(timezone.utc).isoformat(), "watcher": "vm",
                               "state": "could_not_look", "reason": "exception (see bot log)"}, receipt_path())
    finally:
        _LOCK.release()


def kick(force: bool = False) -> bool:
    """Start one background look if due. Never blocks, never raises."""
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
            threading.Thread(target=_run_locked, name="desk-wake-watch", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False

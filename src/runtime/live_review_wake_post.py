"""Live trade review WAKE, VM side (LTR-1B B2b): due event -> ONE ops-flags comment -> manager.

The Actions poller (``scripts/ops/live_review_wake.py``, every ~5 min) is the
token-free channel. This module is the low-latency one: the live trader itself
posts the SAME ``ltr-wake`` comment on the ops-flags PR as soon as the due
computation (``src.runtime.live_review_due``) finds a newly due real-money or
prop event. The manager is subscribed to that PR, so the comment wakes it.

ONE dedupe/cooldown implementation. ``plan`` / ``render`` / ``parse_markers`` /
``load_cfg`` are loaded from the poller's own file, never copied, and the state
both read is the same hidden markers on the PR. A key the poller posted is never
re-posted here and vice versa (a residual race: both posting inside the same few
seconds, before either sees the other's comment).

Cadence: ``kick()`` is called at the end of every ``record_position_telemetry``
(the writer the due computation reads). It costs the exit loop one monotonic
compare and a non-blocking lock try; the work runs on a daemon thread, at most
once per ``MIN_INTERVAL_S``, single-flight. Every failure is contained there.

Credential: the ubuntu user's global ``http.https://github.com/.extraheader``
(a Basic-auth header set by ``vm-git-credential-bootstrap.yml``), read at post
time, in process. It is never logged, never passed on a command line and never
written to disk; the receipt carries no part of it.

Live VM only: ``kick()`` is a no-op unless this process is ``python -m
src.main`` (ict-trader-live). The trainer holds the same credential and must
never post.

Receipt: ``runtime_logs/ltr_wake_post_receipt.json``, read through
``/api/diag/log_file?name=ltr_wake_post_receipt``. ``state`` keeps apart:
``nothing_due`` (looked, no real-money/prop wake event) · ``already_posted``
(due, but the markers say it went out) · ``posted`` (with ``http_code`` and
``latency_s`` from the due computation) · ``could_not_post`` (with
``http_code`` or ``reason``) · ``due_could_not_look`` (the due computation
itself could not look; the poller owns that flag).
"""
from __future__ import annotations

import base64
import importlib.util
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
WAKE_SCRIPT = ROOT / "scripts" / "ops" / "live_review_wake.py"
RECEIPT_NAME = "ltr_wake_post_receipt.json"
REPO = "benbaichmankass/Metis-Insights"
API = "https://api.github.com"
EXTRAHEADER_KEY = "http.https://github.com/.extraheader"
#: At most one due computation per this many seconds (the telemetry pass is ~30 s).
MIN_INTERVAL_S = 60
HTTP_TIMEOUT_S = 10
#: Marker read window. Older markers belong to long-closed packages.
MARKER_LOOKBACK_DAYS = 30
MAX_PAGES = 30

_LOCK = threading.Lock()
_last_kick = float("-inf")
_wake_mod: Any = None
#: Last markers read from the PR, so a due-but-already-posted event costs no
#: GitHub call on every pass. Refreshed whenever the plan against it is non-empty.
_cached_markers: List[dict] = []


def receipt_path() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / RECEIPT_NAME


def _is_live_trader() -> bool:
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return getattr(spec, "name", None) == "src.main"


def wake_module() -> Any:
    """The poller's module, loaded from its file (scripts/ is not a package)."""
    global _wake_mod
    if _wake_mod is None:
        spec = importlib.util.spec_from_file_location("_ltr_live_review_wake", WAKE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _wake_mod = mod
    return _wake_mod


def read_auth_header() -> Optional[str]:
    """``Basic <b64>`` from the global git extraheader, or None. Never logged."""
    try:
        r = subprocess.run(["git", "config", "--global", "--get-all", EXTRAHEADER_KEY],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (r.stdout or "").splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "authorization" and value.strip():
            scheme, _, cred = value.strip().partition(" ")
            if scheme.lower() == "basic" and cred.strip():
                try:
                    base64.b64decode(cred.strip(), validate=True)
                except ValueError:
                    return None
                return f"Basic {cred.strip()}"
    return None


Http = Callable[[str, str, Optional[bytes], str], Tuple[Optional[int], Any]]


def _http(method: str, url: str, body: Optional[bytes], auth: str) -> Tuple[Optional[int], Any]:
    """(status, parsed JSON or None). Never raises; status None = no response."""
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": auth, "Accept": "application/vnd.github+json",
        "Content-Type": "application/json", "User-Agent": "metis-ltr-wake-vm"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001 — network failure is a receipt, never a raise
        return None, None


def read_markers(wake: Any, pr: int, auth: str, now: datetime,
                 http: Http = _http) -> Tuple[Optional[List[dict]], Optional[int]]:
    """(markers, failing http code). None markers = dedupe unknown: do not post."""
    since = datetime.fromtimestamp(now.timestamp() - MARKER_LOOKBACK_DAYS * 86400, timezone.utc)
    comments: List[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = (f"{API}/repos/{REPO}/issues/{pr}/comments?per_page=100&page={page}"
               f"&since={since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        code, data = http("GET", url, None, auth)
        if code != 200 or not isinstance(data, list):
            return None, code
        comments.extend(data)
        if len(data) < 100:
            return wake.parse_markers(comments), None
    return None, None  # page cap hit: cannot prove the read was complete


def write_receipt(rec: Dict[str, Any], path: Optional[Path] = None) -> None:
    try:
        p = path or receipt_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=2, default=str) + "\n")
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001
        logger.warning("ltr-wake-post: receipt write failed", exc_info=True)


def run_once(due_fn: Optional[Callable[[], Any]] = None,
             auth_fn: Callable[[], Optional[str]] = read_auth_header,
             http: Http = _http,
             now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             receipt: Optional[Path] = None,
             build_bundle: Optional[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One due computation -> at most one comment. Returns (and writes) the receipt."""
    global _cached_markers
    computed_at = now_fn()
    if due_fn is None:
        from src.runtime.live_review_due import live_review_due as due_fn  # noqa: N806
    wake = wake_module()
    doc = due_fn()
    rec: Dict[str, Any] = {"computed_at": computed_at.isoformat(), "poster": "vm"}
    if not isinstance(doc, dict) or doc.get("read_state") != "looked" or doc.get("due_count") is None:
        rec.update(state="due_could_not_look",
                   reason=(doc.get("reason") if isinstance(doc, dict) else "payload not an object"))
        write_receipt(rec, receipt)
        return rec
    rec["due_count"] = doc.get("due_count")
    cfg = wake.load_cfg()
    if wake.plan(doc, [], cfg, computed_at)["kind"] != "wake":
        rec["state"] = "nothing_due"
        write_receipt(rec, receipt)
        return rec
    if wake.plan(doc, _cached_markers, cfg, computed_at)["kind"] != "wake":
        rec["state"] = "already_posted"
        write_receipt(rec, receipt)
        return rec
    pr = wake.ops_flags_pr()
    rec["pr"] = pr
    auth = auth_fn()
    if not auth:
        rec.update(state="could_not_post", http_code=None, reason="no_credential_in_git_extraheader")
        write_receipt(rec, receipt)
        return rec
    markers, code = read_markers(wake, pr, auth, computed_at, http)
    if markers is None:
        rec.update(state="could_not_post", http_code=code, reason="marker_read_failed: dedupe unknown")
        write_receipt(rec, receipt)
        return rec
    _cached_markers = markers
    _first_proof_wake(markers)
    p = wake.plan(doc, markers, cfg, computed_at)
    if p["kind"] != "wake":
        rec["state"] = "already_posted"
        write_receipt(rec, receipt)
        return rec
    for e in p["entries"]:
        e["poster"] = "vm"
        e["due_computed_at"] = computed_at.isoformat()
    # LTR C2: the decision packet rides the comment (built on the VM, read-only).
    bundles = wake.attach_packets(p, build=build_bundle) if build_bundle else wake.attach_packets(p)
    rec["packet_states"] = {e["order_package_id"]: e.get("packet_state") for e in p["entries"]}
    body = wake.render(p, computed_at, "VM poster (ict-trader-live, in process)", bundles)
    code, data = http("POST", f"{API}/repos/{REPO}/issues/{pr}/comments",
                      json.dumps({"body": body}).encode(), auth)
    posted_at = now_fn()
    rec.update(entries=[f"{e['order_package_id']}|{e['event']}|{e['level']}" for e in p["entries"]],
               http_code=code)
    if code == 201:
        _cached_markers = markers + wake.parse_markers([{"body": body}])
        _first_proof_wake(_cached_markers)
        rec.update(state="posted", posted_at=posted_at.isoformat(),
                   latency_s=round((posted_at - computed_at).total_seconds(), 3),
                   comment_url=(data or {}).get("html_url") if isinstance(data, dict) else None)
    else:
        rec.update(state="could_not_post", reason="comment_post_failed")
    write_receipt(rec, receipt)
    return rec


def _first_proof_wake(markers: List[dict]) -> None:
    """LTR first-proof S1 (best-effort; src/runtime/ltr_first_proof.py)."""
    try:
        from src.runtime import ltr_first_proof
        ltr_first_proof.observe_wake_markers(markers)
    except Exception:  # noqa: BLE001
        logger.debug("ltr-wake-post: first-proof S1 failed", exc_info=True)


def _run_locked() -> None:
    try:
        from src.runtime import ltr_first_proof
        ltr_first_proof.ensure_seeded()
        run_once()
    except Exception:  # noqa: BLE001 — contained: never reaches the exit loop
        logger.warning("ltr-wake-post: pass failed", exc_info=True)
        write_receipt({"computed_at": datetime.now(timezone.utc).isoformat(), "poster": "vm",
                       "state": "could_not_post", "http_code": None, "reason": "exception (see bot log)"})
    finally:
        _LOCK.release()


def kick(force: bool = False) -> bool:
    """Start one background pass if due. Never blocks, never raises."""
    global _last_kick
    try:
        if not (force or _is_live_trader()):
            return False
        t = time.monotonic()
        if t - _last_kick < MIN_INTERVAL_S:
            return False
        if not _LOCK.acquire(blocking=False):
            return False
        _last_kick = t
        try:
            threading.Thread(target=_run_locked, name="ltr-wake-post", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False

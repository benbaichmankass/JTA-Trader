"""Trading-desk PACKET + WAKE, VM side (DESK-6B): build the 1h scan packet, land it, post the wake.

Operator, 2026-10-26: the system landing the packet is what triggers the session; the session must
never start before its packet exists. GitHub's cron never fired ``desk-scan-packet.yml`` on schedule
(MEASURED by the manager: only workflow_dispatch runs), so the live trader is the PRIMARY producer and
the workflow the fallback (``schedule-keeper`` dispatches it for a missed hour; it does nothing when the
bar already has a packet).

One pass, about every ``MIN_INTERVAL_S`` (single-flight daemon thread kicked from the tick loop):

1. LOOK: read the packet pointer ``comms/desk/latest_scan.json`` on ``desk/decisions``, the
   ``desk-wake`` markers on the ops-flags PR and the decision rows (all public reads).
2. PRODUCE, when the current UTC hour has no packet yet, at least ``BUILD_AFTER_MIN`` into it, no
   ``desk-wake`` marker already covers the bar, and fewer than ``MAX_ATTEMPTS`` tries were made for it:
   build the packet with ``scripts/ops/desk_scan_packet.py`` (the same builder the workflow runs; the
   desk book is read from the branch's decisions), stage it with ``desk_branch.py publish``, commit the
   packet and the pointer to ``desk/decisions`` as ONE fast-forward commit through the GitHub git-data API
   (never forced), and, in the same step, post ONE ``desk-wake`` marker (``desk_wake_marker.py``'s renderer)
   carrying the packet id, sha and commit sha. Nothing else posts a wake, and a failed build/commit posts none.
3. RECEIPT: ``runtime_logs/desk_wake_post_receipt.json``
   (``/api/diag/log_file?name=desk_wake_post_receipt``), rewritten every pass so its ``computed_at``
   is the liveness the ``attention_watch`` probe ``desk_wake_post`` reads.

Every hour wakes (crypto is 24/7): no market or activity gate. The marker's ``context`` is information.
Dedupe is on the packet id and on the bar.

States: ``posted`` (``producer`` ``vm`` when this pass built it, ``latency_s`` from the packet's
``built_at``) · ``already_recorded`` · ``awaiting_wake`` · ``wake_missing`` · ``could_not_build``
(``reason``, ``attempts``) · ``could_not_commit`` (``http_code``) · ``could_not_post`` (``http_code``) ·
``could_not_look`` (``reason``, incl. ``stale_packet``). NO HALTING: every failure is a receipt state, the
next pass retries (bounded per bar), and the workflow fallback covers a VM that cannot commit.

Credential: the ubuntu user's global git extraheader, read in process, never logged or written
(``live_review_wake_post.read_auth_header``). UNVERIFIED at the time of writing: whether that credential
may write ``desk/decisions``; if it may not the receipt says ``could_not_commit`` with the http code.
The live-VM gate: ``kick()`` is a no-op unless this process is ``python -m src.main``.
"""
from __future__ import annotations

import hashlib
import base64
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
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
MIN_INTERVAL_S = 120
#: The 1h bar's closing candle is served by then; build no earlier than this many minutes into the hour.
BUILD_AFTER_MIN = 1
#: Build/commit attempts per bar before the VM stops trying and leaves it to the fallback workflow.
MAX_ATTEMPTS = 3
BUILD_TIMEOUT_S = 420
BUILDER = ROOT / "scripts" / "ops" / "desk_scan_packet.py"
PUBLISHER = ROOT / "scripts" / "ops" / "desk_branch.py"
LOCAL_API = "http://127.0.0.1:8001"
COMMIT_MESSAGE = "desk: scan packet {pid}"
HTTP_TIMEOUT_S = 10
#: The packet job posts the marker seconds after its commit; this long without one is a missing wake.
WAKE_GRACE_MIN = 10
#: Newest packet older than this with no failure marker: the packet job is not running.
PACKET_MAX_AGE_MIN = 90

_LOCK = threading.Lock()
_last_kick = float("-inf")
_marker_mod: Any = None
#: bar -> build/commit attempts made by this process.
_attempts: Dict[str, int] = {}

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
    headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "metis-desk-packet-wake-vm"}
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


def build_packet(now: datetime, decisions_text: str) -> Tuple[Optional[Path], Optional[str]]:
    """Run the workflow's own builder + publisher. (stage dir, None) or (None, why). Never raises."""
    try:
        tmp = Path(tempfile.mkdtemp(prefix="desk-packet-"))
        dec = tmp / "decisions.jsonl"
        dec.write_text(decisions_text)
        env = dict(os.environ, LIVE_REVIEW_PUBLIC_BASE=os.environ.get("LIVE_REVIEW_PUBLIC_BASE", LOCAL_API))
        scan, stage = tmp / "scan.json", tmp / "stage"
        for cmd in ([sys.executable, str(BUILDER), "--timeframe", "1h", "--decisions", str(dec), "--out", str(scan)],
                    [sys.executable, str(PUBLISHER), "publish", "--packet", str(scan), "--stage", str(stage)]):
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
            if r.returncode != 0:
                return None, f"{Path(cmd[1]).name} exit {r.returncode}: {(r.stderr or r.stdout).strip()[-160:]}"
        return stage, None
    except Exception as exc:  # noqa: BLE001 — a build failure is a receipt state
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def commit_packet(stage: Path, pid: str, auth: str, http: ltr_post.Http) -> Tuple[Optional[str], Optional[int]]:
    """Land the staged packet + pointer on ``desk/decisions`` as ONE fast-forward commit (git data API,
    never forced). (commit sha, None) or (None, http code of the step that failed)."""
    base = f"{API}/repos/{REPO}/git"
    files = [(rel, (stage / rel).read_bytes()) for rel in (json.loads((stage / POINTER_PATH).read_text())["path"], POINTER_PATH)]
    code: Optional[int] = None
    for _ in range(4):
        code, ref = http("GET", f"{base}/ref/heads/{BRANCH}", None, auth)
        if code != 200 or not isinstance(ref, dict):
            return None, code
        head = ref["object"]["sha"]
        code, cm = http("GET", f"{base}/commits/{head}", None, auth)
        if code != 200 or not isinstance(cm, dict):
            return None, code
        entries = []
        for rel, data in files:
            code, blob = http("POST", f"{base}/blobs", json.dumps(
                {"content": base64.b64encode(data).decode(), "encoding": "base64"}).encode(), auth)
            if code != 201 or not isinstance(blob, dict):
                return None, code
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        code, tree = http("POST", f"{base}/trees", json.dumps({"base_tree": cm["tree"]["sha"], "tree": entries}).encode(), auth)
        if code != 201 or not isinstance(tree, dict):
            return None, code
        code, new = http("POST", f"{base}/commits", json.dumps(
            {"message": COMMIT_MESSAGE.format(pid=pid), "tree": tree["sha"], "parents": [head]}).encode(), auth)
        if code != 201 or not isinstance(new, dict):
            return None, code
        code, _ = http("PATCH", f"{base}/refs/heads/{BRANCH}", json.dumps({"sha": new["sha"], "force": False}).encode(), auth)
        if code == 200:
            return new["sha"], None
        if code != 422:  # 422 = not a fast-forward: someone appended first; re-read the tip and retry
            return None, code
    return None, code


def run_once(fetch: Fetch = _get,
             auth_fn: Callable[[], Optional[str]] = ltr_post.read_auth_header,
             http: ltr_post.Http = ltr_post._http,
             now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             receipt: Optional[Path] = None,
             pr_fn: Optional[Callable[[], int]] = None,
             build_fn: Callable[[datetime, str], Tuple[Optional[Path], Optional[str]]] = build_packet,
             commit_fn: Optional[Callable[..., Tuple[Optional[str], Optional[int]]]] = None) -> Dict[str, Any]:
    """One pass: look, produce + post if this hour has no packet, write the receipt."""
    commit_fn = commit_fn or commit_packet
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
    built, cutoff = _ts(ptr.get("built_at")), _ts(ptr.get("info_cutoff_at"))
    if built is None or cutoff is None:
        return done("could_not_look", reason="pointer has no parseable built_at/info_cutoff_at")
    pid = ptr["packet_id"]

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

    # ---- PRODUCE: this hour has no packet yet -> build, land, wake (one step, one wake per bar)
    bar_now = now.replace(minute=0, second=0, microsecond=0)
    bar_key = bar_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    covered = any(m.get("kind") == "desk-wake" and m.get("bar") == bar_key for m in markers)
    if (mm.bar_of(ptr["info_cutoff_at"]) < bar_key and now.minute >= BUILD_AFTER_MIN and not covered
            and _attempts.get(bar_key, 0) < MAX_ATTEMPTS):
        _attempts[bar_key] = _attempts.get(bar_key, 0) + 1
        rec.update(attempts=_attempts[bar_key], bar=bar_key)
        if not auth:
            return done("could_not_commit", http_code=None, reason="no_credential_in_git_extraheader")
        stage, why = build_fn(now, text)
        if stage is None:
            return done("could_not_build", reason=why)
        pk_ptr = json.loads((stage / POINTER_PATH).read_text())
        sha, ccode = commit_fn(stage, pk_ptr["packet_id"], auth, http)
        if sha is None:
            return done("could_not_commit", http_code=ccode, packet_id=pk_ptr["packet_id"],
                        reason="desk/decisions write refused or failed (the workflow fallback covers this)")
        entry = mm.build_entry(stage, sha, now)
        entry["poster"] = "vm"
        if mm.plan_post(entry, markers) != "post":
            return done("already_posted", packet_id=entry["packet_id"], commit=sha)
        pcode, pdata = http("POST", f"{API}/repos/{REPO}/issues/{pr}/comments",
                            json.dumps({"body": mm.render_wake(entry, now)}).encode(), auth)
        if pcode != 201:
            return done("could_not_post", http_code=pcode, packet_id=entry["packet_id"], commit=sha,
                        reason="the packet landed but the desk-wake comment failed (no retry: the packet exists; "
                               "the manager is told by the wake_missing state on the next pass)")
        posted_at = now_fn()
        rec["last_posted"] = {"packet_id": entry["packet_id"], "posted_at": posted_at.isoformat(), "commit": sha}
        return done("posted", producer="vm", packet_id=entry["packet_id"], packet_sha=entry["packet_sha"],
                    commit=sha, posted_at=posted_at.isoformat(), context=entry["context"],
                    comment_url=(pdata or {}).get("html_url") if isinstance(pdata, dict) else None,
                    latency_s=round((posted_at - (_ts(entry["built_at"]) or posted_at)).total_seconds(), 1))

    # ---- OBSERVE the newest packet already on the branch
    rec.update(packet_id=pid, packet_sha=ptr.get("packet_sha"), built_at=ptr["built_at"],
               packet_age_min=round((now - built).total_seconds() / 60, 1))
    mine = [m for m in markers if m.get("packet_id") == pid]
    if mine:
        posted_at = _ts(mine[-1].get("posted_at"))
        info = {"packet_id": pid, "posted_at": mine[-1].get("posted_at"), "commit": mine[-1].get("commit")}
        rec["last_posted"] = info
        return done("posted", producer=mine[-1].get("poster") or "packet-job", posted_at=info["posted_at"],
                    commit=info["commit"],
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
                                       "marker and no decision row (the producer's post step did not run)")


def _run_locked() -> None:
    try:
        run_once()
    except Exception:  # noqa: BLE001 — contained: never reaches the tick loop
        logger.warning("desk-packet-wake: pass failed", exc_info=True)
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
            threading.Thread(target=_run_locked, name="desk-packet-wake", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False

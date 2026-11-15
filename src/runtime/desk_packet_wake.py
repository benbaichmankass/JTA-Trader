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
``built_at``) · ``skipped_by_cadence`` (the packet landed, the bar is not a wake bar: ``scan_wake_every_h``,
operator 2026-10-30) · ``skipped_nothing_new`` (a wake bar, but the packet does not differ materially from the last
woken one: ``scan_wake_min_move_atr``, operator 2026-10-31; ``reason`` says what was compared) · ``already_recorded`` · ``awaiting_wake`` · ``wake_missing`` · ``could_not_build``
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
import shutil
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
DETACHED = "detached:"
#: A detached build older than this has no live unit left (2 stages + margin; the unit RuntimeMaxSec is 900 s).
DETACHED_WAIT_S = 2 * BUILD_TIMEOUT_S + 60
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


def latency_s(posted: Optional[datetime], built: Optional[datetime]) -> Optional[float]:
    """Seconds from the packet's ``built_at`` to the wake post, never negative. The builder stamps
    ``built_at = max(its clock, info_cutoff_at)``, so a packet whose cutoff is ahead of the post clock reads
    as built AFTER it was posted (MEASURED -59.8 s on the 2026-10-28 receipt); that is 0 s of latency, not a
    negative one. None when either stamp is unreadable."""
    if posted is None or built is None:
        return None
    return round(max(0.0, (posted - built).total_seconds()), 1)


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


def _desk_dir() -> Path:
    return receipt_path().parent / "desk"


def _read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _run_unit(job_id: str, job_dir: Path, stages: list, env_overlay: Dict[str, str],
              stage: Path) -> Optional[Tuple[Optional[Path], Optional[str]]]:
    """Run the stages in ``ict-desk-build@<job>.service`` (own cgroup: a trader restart cannot kill it).
    (stage, None) | (None, why) | None when isolation is unavailable (unit not installed / no sudo) -> in-process fallback.
    A `systemctl start` client killed with the trader is DETACHED, not failed: the unit keeps running and
    ``_adopt_mark`` picks the result up on a later pass. Same contract as desk_event_trigger._run_isolated."""
    (job_dir / "job.json").write_text(json.dumps({"env": env_overlay, "stages": [
        {"name": n, "argv": a, "timeout_s": BUILD_TIMEOUT_S} for n, a in stages]}))
    try:
        r = subprocess.run(["sudo", "-n", "systemctl", "start", f"ict-desk-build@{job_id}.service"],
                           capture_output=True, text=True, timeout=2 * BUILD_TIMEOUT_S + 60)
    except subprocess.TimeoutExpired:
        return None, DETACHED + "systemctl start exceeded 2 stages + 60 s (the unit's RuntimeMaxSec bounds it)"
    return _unit_result(job_dir, stage, r)


def _unit_result(job_dir: Path, stage: Path, r: Any = None) -> Tuple[Optional[Path], Optional[str]]:
    res = _read_json(job_dir / "result.json")
    if res is None:
        err = ((getattr(r, "stderr", "") or getattr(r, "stdout", "") or "")).strip()
        rc = getattr(r, "returncode", None)
        if r is not None and rc != 0 and any(k in err.lower() for k in ("not found", "password", "not allowed", "no tty", "sudo:")):
            return None  # type: ignore[return-value]  # isolation unavailable here
        return None, DETACHED + f"no result.json yet (systemctl exit {rc}: {err[-120:]})"
    bad = next((st for st in res.get("stages") or [] if st.get("outcome") != "exit 0"), None)
    if res.get("state") == "ok" and bad is None:
        return stage, None
    if bad and bad.get("outcome") == "timeout":
        return None, f"TimeoutExpired: {bad['stage']} exceeded {BUILD_TIMEOUT_S}s (isolated unit, {bad.get('wall_s')}s)"
    if bad:
        return None, f"{bad['stage']} {bad.get('outcome')}: {bad.get('tail', '')}"
    return None, f"desk-build unit: {res.get('error') or res.get('state')}"


def _adopt_mark(bar_key: str, now: datetime) -> Optional[Tuple[str, Any]]:
    """A hourly build whose client died with the trader leaves ``wake_inflight.json``. For THIS bar: ('stage', Path)
    when its unit finished ok, ('pending', age_s) while it may still run, else the mark is cleared and the caller builds."""
    mp = _desk_dir() / "wake_inflight.json"
    mark = _read_json(mp)
    if not mark:
        return None
    job_dir = _desk_dir() / "jobs" / str(mark.get("job", ""))
    age = time.time() - float(mark.get("started_at") or 0)
    res = _read_json(job_dir / "result.json")
    if mark.get("bar") != bar_key:
        mp.unlink(missing_ok=True)
        return None
    if res is None:
        if age < DETACHED_WAIT_S:
            return "pending", round(age)
        mp.unlink(missing_ok=True)
        return None
    mp.unlink(missing_ok=True)
    stage, _why = _unit_result(job_dir, job_dir / "stage")
    return ("stage", stage) if stage is not None and (stage / POINTER_PATH).exists() else None


def build_packet(now: datetime, decisions_text: str) -> Tuple[Optional[Path], Optional[str]]:
    """Run the workflow's own builder + publisher. (stage dir, None) or (None, why). Never raises.
    In its own systemd unit when it can (survives a trader restart), else in-process as before."""
    try:
        try:  # job dirs are pruned about 1 h after their last write (the trigger path does the same)
            for j in (_desk_dir() / "jobs").iterdir():
                if j.is_dir() and time.time() - j.stat().st_mtime > 3600.0:
                    shutil.rmtree(j, ignore_errors=True)
        except OSError:
            pass
        job_id = f"hourly-{int(time.time())}-{os.getpid()}"
        tmp = _desk_dir() / "jobs" / job_id
        tmp.mkdir(parents=True, exist_ok=True)
        dec = tmp / "decisions.jsonl"
        dec.write_text(decisions_text)
        base = os.environ.get("LIVE_REVIEW_PUBLIC_BASE", LOCAL_API)
        env = dict(os.environ, LIVE_REVIEW_PUBLIC_BASE=base)
        scan, stage = tmp / "scan.json", tmp / "stage"
        stages = [("builder", [sys.executable, str(BUILDER), "--timeframe", "1h", "--decisions", str(dec), "--out", str(scan)]),
                  ("publisher", [sys.executable, str(PUBLISHER), "publish", "--packet", str(scan), "--stage", str(stage)])]
        mark = _desk_dir() / "wake_inflight.json"
        mark.write_text(json.dumps({"bar": now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "job": job_id, "started_at": time.time()}))
        iso = _run_unit(job_id, tmp, stages, {"LIVE_REVIEW_PUBLIC_BASE": base}, stage)
        if iso is not None:
            if not (iso[1] or "").startswith(DETACHED):
                mark.unlink(missing_ok=True)  # finished (ok or failed): nothing left to adopt
            return iso
        mark.unlink(missing_ok=True)
        for _name, cmd in stages:
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
            if r.returncode != 0:
                return None, f"{Path(cmd[1]).name} exit {r.returncode}: {(r.stderr or r.stdout).strip()[-160:]}"
        return stage, None
    except Exception as exc:  # noqa: BLE001 — a build failure is a receipt state
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def commit_packet(stage: Path, pid: str, auth: str, http: ltr_post.Http,
                  pointer_path: str = POINTER_PATH) -> Tuple[Optional[str], Optional[int]]:
    """Land the staged packet + pointer on ``desk/decisions`` as ONE fast-forward commit (git data API,
    never forced). (commit sha, None) or (None, http code of the step that failed)."""
    base = f"{API}/repos/{REPO}/git"
    files = [(rel, (stage / rel).read_bytes()) for rel in (json.loads((stage / pointer_path).read_text())["path"], pointer_path)]
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
        if prior.get("last_skipped"):
            rec["last_skipped"] = prior["last_skipped"]
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
        adopted = _adopt_mark(bar_key, now)
        if adopted and adopted[0] == "pending":
            _attempts[bar_key] -= 1  # waiting on a live unit is not an attempt
            return done("build_pending", age_s=adopted[1])
        if adopted:
            stage, why = adopted[1], None
            rec["adopted"] = True
        else:
            stage, why = build_fn(now, text)
        if stage is None and (why or "").startswith(DETACHED):
            _attempts[bar_key] -= 1
            return done("build_detached", reason=why)
        if stage is None:
            return done("could_not_build", reason=why)
        pk_ptr = json.loads((stage / POINTER_PATH).read_text())
        sha, ccode = commit_fn(stage, pk_ptr["packet_id"], auth, http)
        if sha is None:
            return done("could_not_commit", http_code=ccode, packet_id=pk_ptr["packet_id"],
                        reason="desk/decisions write refused or failed (the workflow fallback covers this)")
        entry = mm.build_entry(stage, sha, now)
        entry["poster"] = "vm"
        if not mm.wake_due(entry["bar"]):
            return done("skipped_by_cadence", packet_id=entry["packet_id"], commit=sha, bar=entry["bar"],
                        every_h=mm.scan_wake_every_h())
        if mm.plan_post(entry, markers) != "post":
            return done("already_posted", packet_id=entry["packet_id"], commit=sha)
        wake, why = mm.material_change(entry["context"]["fingerprint"], mm.last_woken_fingerprint(markers),
                                       mm.scan_wake_min_move_atr())
        if not wake:
            rec["last_skipped"] = {"packet_id": entry["packet_id"], "bar": entry["bar"], "reason": why}
            return done("skipped_nothing_new", packet_id=entry["packet_id"], commit=sha, bar=entry["bar"], reason=why)
        # Console wake switches (operator 2026-11-07): the packet is already landed; only the comment is withheld.
        # Unreadable switch state => post (wake_toggles.is_on never silences by doubt).
        from src.runtime import wake_toggles as wt
        if not wt.is_on("desk_wake"):
            wt.log_suppressed("desk_wake", entry["packet_id"])
            return done("suppressed_by_wake_toggle", packet_id=entry["packet_id"], commit=sha, bar=entry["bar"])
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
                    latency_s=latency_s(posted_at, _ts(entry["built_at"])))

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
                    latency_s=latency_s(posted_at, built))
    if pid in recorded_packet_ids(text):
        return done("already_recorded")
    pbar = mm.bar_of(ptr["info_cutoff_at"])
    skipped = rec.get("last_skipped") or {}
    if skipped.get("packet_id") == pid:  # this pass's predecessor judged it: nothing new, no wake by design
        return done("skipped_nothing_new", packet_id=pid, bar=skipped.get("bar") or pbar, reason=skipped.get("reason"))
    if not mm.wake_due(pbar):
        return done("skipped_by_cadence", bar=pbar, every_h=mm.scan_wake_every_h(),
                    reason="the packet landed; no wake by design on this bar (config/desk_triggers.yaml scan_wake_every_h)")
    # Console wake switch OFF (operator 2026-11-07; default OFF): the producer withheld the comment on purpose, so a
    # missing marker is by design, never wake_missing (which pages the manager). Unreadable state => is_on is True.
    from src.runtime import wake_toggles as wt
    if not wt.is_on("desk_wake"):
        return done("suppressed_by_wake_toggle", packet_id=pid, bar=pbar,
                    reason="the packet landed; the desk_wake console switch is off, no wake by design")
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

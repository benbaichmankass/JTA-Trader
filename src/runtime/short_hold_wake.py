"""Short-hold lane TRIGGER + 5-min PACKETS, VM side (DESK-SHORT-HOLD-LANE).

Operator goal, 2026-10-27 (approved, relayed by the manager): Claude manages a short-term trade (<= 1 h hold) from
ONE session that lives for the life of that trade -- design § 6.2's per-trade spawned lane. This module is the
trade's side of it; the session's side is ``.claude/skills/trading-desk/SHORT-HOLD-BRIEF.md``.

One pass, about every ``MIN_INTERVAL_S`` (single-flight daemon thread kicked from the tick loop, like
``desk_packet_wake``):

1. LOOK: the journal's open packages (``live_review_due.read_journal_open``), filtered to the legs in
   ``config/short_hold.yaml::legs``; the ``short-hold`` markers on the ops-flags PR; the per-package state file.
2. ENTRY: a short-hold package with no ``short-hold-wake`` marker -> build its first envelope, land it on the rows
   branch, then post ONE ``short-hold-wake`` marker (package id, account, leg, symbol, side, entry, SL, TP,
   opened_at, hard_cap_at, the envelope commit). The manager spawns the lane on it (``manager`` SKILL
   § "Short-hold wake"), exactly as it does on a ``desk-wake``.
3. EVERY 5m BAR: a tracked package whose last landed envelope is for an older 5m bar -> a new envelope
   (``scripts/ops/short_hold_packet.py``: the LTR-11 packet + the 5-min block) at
   ``comms/live_review/short_hold/<pkg>/latest.json`` on ``live-review/rows``, ONE fast-forward commit through the
   git-data API (never forced). The lane's background wait returns when it lands.
4. EXIT: a tracked package no longer open -> the envelope is rewritten ``closed: true`` (with ``close_reason``)
   and ONE ``short-hold-closed`` marker is posted. The lane stops on either.

The lane writes its rows to ``comms/live_review/reviews.jsonl`` on the same branch through
``short_hold_write.py``; the existing rows watcher (``live_review_rows_watch.py``) applies them under
``MD-TRADE-DESK``. Nothing here applies anything.

Receipt ``runtime_logs/short_hold_wake_receipt.json`` (diag ``log_file?name=short_hold_wake_receipt``), rewritten
every pass: ``state`` ``idle`` (looked, nothing short-hold open) / ``tracking`` (with per-package ``packages``) /
``could_not_look`` (journal, markers or config unreadable, with ``reason``). Per-package states:
``wake_posted`` · ``packet_landed`` · ``closed_posted`` · ``could_not_build`` · ``could_not_commit`` (http) ·
``could_not_post`` (http). NO HALTING: every failure is a receipt state and the next pass retries; a dead lane
leaves the trade on its venue brackets.

Credential: the same git extraheader as ``desk_packet_wake`` (never logged). Live VM only: ``kick()`` is a no-op
unless this process is ``python -m src.main``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.runtime import live_review_wake_post as ltr_post

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "short_hold.yaml"
BUILDER = ROOT / "scripts" / "ops" / "short_hold_packet.py"
RECEIPT_NAME = "short_hold_wake_receipt.json"
STATE_NAME = "short_hold_state.json"
REPO, API = ltr_post.REPO, ltr_post.API
ENVELOPE = "comms/live_review/short_hold/{pkg}/latest.json"
MARKER = "short-hold"
MIN_INTERVAL_S = 30
BUILD_TIMEOUT_S = 240
BAR_S = 300

_LOCK = threading.Lock()
_last_kick = float("-inf")

Http = ltr_post.Http


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def last_closed_bar(now: datetime) -> str:
    """Open time of the newest CLOSED 5m bar at ``now``."""
    s = int(now.timestamp()) // BAR_S * BAR_S - BAR_S
    return _iso(datetime.fromtimestamp(s, timezone.utc))


def load_config(path: Path = CONFIG) -> Dict[str, Any]:
    import yaml
    doc = yaml.safe_load(path.read_text()) or {}
    legs = doc.get("legs")
    if not isinstance(legs, list) or not all(isinstance(x, str) for x in legs):
        raise ValueError("config/short_hold.yaml: legs must be a list of leg names")
    return {"legs": legs, "branch": doc.get("branch", "live-review/rows"),
            "hard_cap_minutes": int(doc.get("hard_cap_minutes", 90))}


# ----------------------------------------------------------------------------- markers (pure)

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


def posted(markers: List[dict], kind: str, pkg: str) -> bool:
    return any(m.get("kind") == kind and m.get("order_package_id") == pkg for m in markers)


def render(entry: Dict[str, Any], now: datetime) -> str:
    kind, pkg = entry["kind"], entry["order_package_id"]
    marker = dict(entry, posted_at=now.isoformat())
    if kind == "short-hold-wake":
        head = (f"**short-hold-wake: `{pkg}`** ({entry.get('leg')} {entry.get('side')} {entry.get('symbol')} on "
                f"{', '.join(entry.get('accounts') or []) or '?'}; entry {entry.get('entry')} SL {entry.get('sl')} TP "
                f"{entry.get('tp')}; opened {entry.get('opened_at')}; hard cap {entry.get('hard_cap_at')}). Its first "
                f"5m packet is on `{entry.get('branch')}` (commit `{str(entry.get('commit'))[:10]}`). Manager: "
                "`create_session` the short-hold lane exactly as `.claude/skills/manager/SKILL.md` § \"Short-hold "
                "wake\" specifies.")
    else:
        head = (f"**short-hold-closed: `{pkg}`** (close_reason `{entry.get('close_reason')}`). The envelope reads "
                "`closed: true`; the lane stops on its next wake. Manager: record the lane's cost (§ \"Short-hold wake\").")
    return "\n".join([head, "", f"<!-- {MARKER} {json.dumps(marker, separators=(',', ':'), default=str)} -->",
                      "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


# ----------------------------------------------------------------------------- reads

def read_package(pkg: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """The order_packages row (entry / sl / tp / created_at / status / close_reason). {} when unreadable."""
    try:
        if db_path is None:
            from src.utils.paths import trade_journal_db_path
            db_path = str(trade_journal_db_path())
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            r = conn.execute("SELECT * FROM order_packages WHERE order_package_id = ?", (pkg,)).fetchone()
        finally:
            conn.close()
        return dict(r) if r else {}
    except Exception:  # noqa: BLE001  # allow-silent: an unread row is {} and the marker carries nulls
        return {}


def build_envelope(pkg: str, opened_at: Optional[str]) -> Tuple[Optional[dict], Optional[str]]:
    """``short_hold_packet.py <pkg>``: (envelope, None) or (None, why). Never raises."""
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "env.json"
            cmd = [sys.executable, str(BUILDER), pkg, "--out", str(out)] + (["--opened-at", opened_at] if opened_at else [])
            env = dict(os.environ, LIVE_REVIEW_PUBLIC_BASE=os.environ.get("LIVE_REVIEW_PUBLIC_BASE", "http://127.0.0.1:8001"))
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
            if r.returncode != 0:
                return None, f"exit {r.returncode}: {(r.stderr or r.stdout).strip()[-160:]}"
            return json.loads(out.read_text()), None
    except Exception as exc:  # noqa: BLE001 — a build failure is a receipt state
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def commit_files(branch: str, files: List[Tuple[str, bytes]], message: str, auth: str,
                 http: Http) -> Tuple[Optional[str], Optional[int]]:
    """ONE fast-forward commit of ``files`` on ``branch`` (git data API, never forced). Same shape as
    ``desk_packet_wake.commit_packet``; a 422 (someone appended first) re-reads the tip and retries."""
    base = f"{API}/repos/{REPO}/git"
    code: Optional[int] = None
    for _ in range(4):
        code, ref = http("GET", f"{base}/ref/heads/{branch}", None, auth)
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
            {"message": message, "tree": tree["sha"], "parents": [head]}).encode(), auth)
        if code != 201 or not isinstance(new, dict):
            return None, code
        code, _ = http("PATCH", f"{base}/refs/heads/{branch}", json.dumps({"sha": new["sha"], "force": False}).encode(), auth)
        if code == 200:
            return new["sha"], None
        if code != 422:
            return None, code
    return None, code


# ----------------------------------------------------------------------------- one pass

def run_once(*, journal_fn: Optional[Callable[[], Dict[str, Any]]] = None,
             package_fn: Callable[[str], Dict[str, Any]] = read_package,
             build_fn: Callable[[str, Optional[str]], Tuple[Optional[dict], Optional[str]]] = build_envelope,
             commit_fn: Optional[Callable[..., Tuple[Optional[str], Optional[int]]]] = None,
             auth_fn: Callable[[], Optional[str]] = ltr_post.read_auth_header,
             http: Http = ltr_post._http,
             now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             cfg: Optional[Dict[str, Any]] = None, pr_fn: Optional[Callable[[], int]] = None,
             receipt: Optional[Path] = None, state_path: Optional[Path] = None) -> Dict[str, Any]:
    commit_fn = commit_fn or commit_files
    now = now_fn()
    rpath = receipt or (_log_dir() / RECEIPT_NAME)
    spath = state_path or (_log_dir() / STATE_NAME)
    rec: Dict[str, Any] = {"computed_at": now.isoformat(), "watcher": "vm"}

    def done(state: str, **kw: Any) -> Dict[str, Any]:
        rec.update(state=state, **kw)
        ltr_post.write_receipt(rec, rpath)
        return rec

    try:
        cfg = cfg or load_config()
    except Exception as exc:  # noqa: BLE001
        return done("could_not_look", reason=f"config: {type(exc).__name__}: {str(exc)[:120]}")
    if journal_fn is None:
        from src.runtime.live_review_due import read_journal_open as journal_fn  # noqa: N806
    jo = journal_fn()
    if jo.get("state") != "read":
        return done("could_not_look", reason=jo.get("reason") or "journal unreadable")
    open_now: Dict[str, Dict[str, Any]] = {}
    for p in jo.get("packages") or []:
        if p.get("strategy") in cfg["legs"]:
            d = open_now.setdefault(p["order_package_id"], dict(p, accounts=[]))
            if p.get("account_id") and p["account_id"] not in d["accounts"]:
                d["accounts"].append(p["account_id"])
    try:
        state = json.loads(spath.read_text())
    except Exception:  # noqa: BLE001  # a missing/corrupt state file re-derives from the markers
        state = {}
    if not open_now and not any(not s.get("closed_posted") for s in state.values()):
        return done("idle", legs=cfg["legs"])

    auth = auth_fn()
    if not auth:
        return done("could_not_look", reason="no_credential_in_git_extraheader")
    try:
        pr = pr_fn() if pr_fn else ltr_post.wake_module().ops_flags_pr()
    except Exception as exc:  # noqa: BLE001
        return done("could_not_look", reason=f"ops_flags_pr unreadable: {type(exc).__name__}")
    markers, mcode = ltr_post.read_markers(_MarkerWake, pr, auth, now, http)
    if markers is None:
        return done("could_not_look", reason=f"ops-flags comments unreadable (http {mcode})")
    rec["pr"] = pr
    branch, out = cfg["branch"], {}

    def post(entry: Dict[str, Any]) -> Optional[int]:
        code, _ = http("POST", f"{API}/repos/{REPO}/issues/{pr}/comments",
                       json.dumps({"body": render(entry, now)}).encode(), auth)
        return None if code == 201 else code

    def land(pkg: str, env: dict) -> Tuple[Optional[str], Optional[int]]:
        return commit_fn(branch, [(ENVELOPE.format(pkg=pkg), (json.dumps(env, indent=1, sort_keys=True, default=str)
                                                               + "\n").encode())],
                         f"short-hold: {pkg} packet {env.get('bar')}{' CLOSED' if env.get('closed') else ''}", auth, http)

    bar = last_closed_bar(now)
    for pkg, p in open_now.items():
        s = state.setdefault(pkg, {"leg": p.get("strategy"), "symbol": p.get("symbol"), "side": p.get("direction")})
        s["accounts"] = sorted(set(s.get("accounts") or []) | set(p["accounts"]))
        if s.get("last_bar") == bar and posted(markers, "short-hold-wake", pkg):
            out[pkg] = "tracking"
            continue
        row = package_fn(pkg)
        s.setdefault("opened_at", row.get("created_at"))
        env, why = build_fn(pkg, s.get("opened_at"))
        if env is None:
            out[pkg] = f"could_not_build: {why}"
            continue
        sha, ccode = land(pkg, env)
        if sha is None:
            out[pkg] = f"could_not_commit: http {ccode}"
            continue
        # last_bar = this pass's target bar (not the envelope's, which lags when the candle route is late), so a
        # lagging feed costs one envelope per bar, never one per pass.
        s["last_bar"], s["packet_bar"], s["last_commit"] = bar, env.get("bar"), sha
        out[pkg] = "packet_landed"
        if not posted(markers, "short-hold-wake", pkg):
            opened = _ts(s.get("opened_at")) or now
            entry = {"kind": "short-hold-wake", "order_package_id": pkg, "accounts": s["accounts"],
                     "leg": s["leg"], "symbol": s["symbol"], "side": s["side"], "entry": row.get("entry"),
                     "sl": row.get("sl"), "tp": row.get("tp"), "opened_at": s.get("opened_at"),
                     "hard_cap_at": _iso(opened + timedelta(minutes=cfg["hard_cap_minutes"])),
                     "branch": branch, "commit": sha, "bar": s["last_bar"]}
            pc = post(entry)
            out[pkg] = "wake_posted" if pc is None else f"could_not_post: http {pc}"
            if pc is None:
                markers.append(entry)
    for pkg, s in state.items():
        if pkg in open_now or s.get("closed_posted"):
            continue
        row = package_fn(pkg)
        if row and row.get("status") == "open":  # the journal read above missed it; never close on a doubt
            out[pkg] = "tracking"
            continue
        env = {"order_package_id": pkg, "closed": True, "closed_at": row.get("updated_at") or _iso(now),
               "close_reason": row.get("close_reason"), "bar": s.get("last_bar")}
        sha, ccode = land(pkg, env)
        if sha is None:
            out[pkg] = f"could_not_commit: http {ccode}"
            continue
        if not posted(markers, "short-hold-closed", pkg):
            pc = post({"kind": "short-hold-closed", "order_package_id": pkg, "close_reason": row.get("close_reason"),
                       "commit": sha})
            if pc is not None:
                out[pkg] = f"could_not_post: http {pc}"
                continue
        s["closed_posted"] = _iso(now)
        out[pkg] = "closed_posted"
    try:
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(json.dumps(state, indent=1, default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("short-hold-wake: state write failed", exc_info=True)
    return done("tracking", packages=out, bar=bar)


class _MarkerWake:
    """Adapter so ``ltr_post.read_markers`` parses this module's markers."""
    parse_markers = staticmethod(parse_markers)


def _log_dir() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs"


def _run_locked() -> None:
    try:
        run_once()
    except Exception:  # noqa: BLE001 — contained: never reaches the tick loop
        logger.warning("short-hold-wake: pass failed", exc_info=True)
        ltr_post.write_receipt({"computed_at": datetime.now(timezone.utc).isoformat(), "watcher": "vm",
                               "state": "could_not_look", "reason": "exception (see bot log)"},
                               _log_dir() / RECEIPT_NAME)
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
            threading.Thread(target=_run_locked, name="short-hold-wake", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False

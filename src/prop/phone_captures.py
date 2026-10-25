"""Step captures from the PHONE executor (PHONE-EXEC-OBSERVABLE-1018, operator decision 2026-10-18).

Why this exists. Four builds in three days (#18709, #18775, #18811, #18901) each guessed why one tap on
Breakout's Positions row opened no sheet, shipped an APK, waited for the next trail amend and read a 40-char
diag line. The operator ended that loop: *the app must know what it is doing, record its own actions without
anything popping up on screen, and show what it did right and wrong.* This module is the server half of the
RECORDING piece: at each step of a flow the app posts (a) an off-screen bitmap of its own WebView and (b) a
sanitized DOM snapshot, and a manager reads them back through the diag tier.

Decisions (operator popups, 2026-10-18), each enforced here:

* **Stored on the server only, never in git.** Captures land under the VM data dir beside the other phone
  diag files (``<trade_journal.db dir>/phone_captures/<account>/<run>/``), a path no workflow commits.
* **Auto-deleted after 7 days.** :func:`purge_expired` removes run directories older than :data:`TTL_DAYS`;
  it runs from the daily ``ict-phone-capture-purge.timer`` AND opportunistically on every capture POST (at most
  once per :data:`PURGE_EVERY_S`), so the TTL holds even when the timer is not installed.
* **Redacted on the device before upload** (account ids, balances, equity, P&L are masked by exec.js before the
  snapshot leaves the phone). The server scrubs the DOM text a SECOND time (:func:`scrub_dom_text`): long digit
  runs, currency amounts, the sheet's ``Position – <id>`` subtitle and ``/account/<id>/`` paths. A bitmap cannot
  be scrubbed here; the app paints its redaction boxes before encoding.

Every write is bounded (per-capture bytes, steps per run, runs per account) so a looping app can never fill the
disk; a refused capture answers ``ok: false`` with the reason and the flow continues (no halting: the capture is
evidence, never a gate on the trade).

Read surface (Tier 2.5, ``DIAG_READ_TOKEN``): :func:`list_runs`, :func:`get_run`, :func:`read_file`.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TTL_DAYS = 7
PURGE_EVERY_S = 3600
MAX_PNG_BYTES = 900_000       # a 720-px-wide JPEG/WebP of the terminal is ~100-250 KB
MAX_DOM_BYTES = 600_000       # a scoped DOM tree; the app caps nodes before posting
MAX_NOTE_CHARS = 300
MAX_STEPS_PER_RUN = 80
MAX_RUNS_PER_ACCOUNT = 400    # oldest dropped first, inside the TTL
MAX_ACCOUNT_BYTES = 400_000_000
FLOWS = ("entry", "amend", "drill", "positions", "login", "probe")
_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
_STEP_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_ACCT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def captures_root() -> Path:
    """``<trade_journal.db dir>/phone_captures`` — beside the other ``prop_phone_*`` diag files, on the VM data
    volume, never inside the repo checkout."""
    from src.prop import prop_journal
    return Path(prop_journal._db_path()).parent / "phone_captures"


def account_dir(account_id: str) -> Path:
    acct = str(account_id or "")
    if not _ACCT_RE.match(acct):
        raise ValueError("account_id invalid")
    return captures_root() / acct


def scrub_text(s: Any, n: int = MAX_NOTE_CHARS) -> str:
    """A short free-text field: printable ASCII subset, no links / emails / long digit runs."""
    s = re.sub(r"[^A-Za-z0-9 _.:/()=+&%#,;<>\[\]-]", "", str(s or ""))[:n]
    return re.sub(r"https?\S*|\S+@\S+|\d{6,}", "*", s)


_MONEY_RE = re.compile(r"[-+−]?\s*\$?\s*\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?\s*(USD[TC]?|EUR|GBP)\b|"
                       r"[-+−]?\s*\$?\s*\d+\.\d{2}\s*(USD[TC]?|EUR|GBP)\b", re.I)
_ACCT_PATH_RE = re.compile(r"(/account/)[^/\"'\s]+")
_SUBTITLE_RE = re.compile(r"(Position\s*[\u2013\u2014-]\s*)[A-Za-z0-9_-]+", re.I)
_LONG_DIGITS_RE = re.compile(r"\d{5,}")


def scrub_dom_text(text: str) -> str:
    """Second-line redaction of ONE text value of a DOM snapshot (the device redacts first, by element; this is
    applied to every string leaf of the tree, never to the serialized document, so the JSON stays valid)."""
    text = _ACCT_PATH_RE.sub(r"\1ACCT", text)
    text = _SUBTITLE_RE.sub(r"\1ID", text)
    text = _MONEY_RE.sub(lambda m: "#.## " + (m.group(1) or m.group(2) or "USD").upper(), text)
    text = _LONG_DIGITS_RE.sub("#####", text)
    return text


def _parse_image(body: Dict[str, Any]) -> tuple[Optional[bytes], str, str]:
    raw = body.get("png_b64")
    if not raw:
        return None, "", ""
    if not isinstance(raw, str):
        raise ValueError("png_b64 must be a base64 string")
    if len(raw) > MAX_PNG_BYTES * 4 // 3 + 16:
        raise ValueError(f"image exceeds {MAX_PNG_BYTES} bytes")
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("png_b64 is not valid base64") from exc
    if len(data) > MAX_PNG_BYTES:
        raise ValueError(f"image exceeds {MAX_PNG_BYTES} bytes")
    ctype = str(body.get("png_type") or "image/png").lower()
    if ctype not in _IMAGE_TYPES:
        raise ValueError("png_type must be image/jpeg, image/png or image/webp")
    # the magic bytes must agree with the declared type: an arbitrary blob is never stored as an image
    magic_ok = {"image/png": data[:8] == b"\x89PNG\r\n\x1a\n", "image/jpeg": data[:3] == b"\xff\xd8\xff",
                "image/webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}[ctype]
    if not magic_ok:
        raise ValueError("image bytes do not match png_type")
    return data, ctype, _IMAGE_TYPES[ctype]


def _scrub_tree(node: Any) -> Any:
    """Apply :func:`scrub_dom_text` to every string leaf of a JSON tree (keys included), never to the structure."""
    if isinstance(node, str):
        return scrub_dom_text(node)
    if isinstance(node, list):
        return [_scrub_tree(x) for x in node]
    if isinstance(node, dict):
        return {scrub_dom_text(str(k)): _scrub_tree(v) for k, v in node.items()}
    return node


def _parse_dom(body: Dict[str, Any]) -> Optional[str]:
    dom = body.get("dom")
    if dom is None:
        return None
    if isinstance(dom, str):
        if len(dom.encode("utf-8")) > MAX_DOM_BYTES:
            raise ValueError(f"dom exceeds {MAX_DOM_BYTES} bytes")
        try:
            parsed = json.loads(dom)
        except ValueError:
            parsed = {"text": dom}
    else:
        parsed = dom
    try:
        text = json.dumps(_scrub_tree(parsed), separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("dom is not JSON-serializable") from exc
    if len(text.encode("utf-8")) > MAX_DOM_BYTES:
        raise ValueError(f"dom exceeds {MAX_DOM_BYTES} bytes")
    return text


def _dir_bytes(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def capture_link(account_id: str, run_id: str) -> str:
    """The diag-tier link a Telegram line carries for one run's step captures (manager/operator read; DIAG token)."""
    base = os.environ.get("PUBLIC_API_BASE", "https://ict-bot.duckdns.org").rstrip("/")
    return f"{base}/api/diag/phone_capture?account_id={account_id}&run_id={run_id}" if run_id else ""


def store_capture(account_id: str, body: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Validate and write one step capture. Raises ``ValueError`` on a malformed body; answers
    ``{"ok": False, "why": ...}`` on a quota refusal (the app carries on). On success ``{"ok": True, "stored": True,
    "capture": <meta>}`` (the meta's own ``ok`` is the STEP's result, not the write's)."""
    now = now or _now()
    run_id = str(body.get("run_id") or "")
    step = str(body.get("step") or "")
    flow = str(body.get("flow") or "")
    if not _RUN_RE.match(run_id):
        raise ValueError("run_id invalid")
    if not _STEP_RE.match(step):
        raise ValueError("step invalid")
    if flow not in FLOWS:
        raise ValueError(f"flow must be one of {', '.join(FLOWS)}")
    seq = body.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 or seq > 9999:
        raise ValueError("seq must be an int 0..9999")
    ok = body.get("ok")
    if ok is not None and not isinstance(ok, bool):
        raise ValueError("ok must be true, false or null")
    image, ctype, ext = _parse_image(body)
    dom_text = _parse_dom(body)
    acct_dir = account_dir(account_id)
    run_dir = acct_dir / run_id
    maybe_purge(account_id, now=now)
    if run_dir.exists():
        existing = [p for p in run_dir.glob("*.json") if p.name != "run.json" and not p.name.endswith(".dom.json")]
        if len(existing) >= MAX_STEPS_PER_RUN:
            return {"ok": False, "why": f"run already holds {MAX_STEPS_PER_RUN} steps"}
    else:
        runs = [p for p in acct_dir.iterdir() if p.is_dir()] if acct_dir.exists() else []
        if len(runs) >= MAX_RUNS_PER_ACCOUNT:
            _drop_oldest(runs, len(runs) - MAX_RUNS_PER_ACCOUNT + 1)
    if acct_dir.exists() and _dir_bytes(acct_dir) + len(image or b"") + len((dom_text or "").encode()) > MAX_ACCOUNT_BYTES:
        return {"ok": False, "why": "account capture quota reached"}
    run_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{seq:03d}-{step}"
    meta = {
        "at": now.isoformat(), "run_id": run_id, "flow": flow, "step": step, "seq": seq, "ok": ok,
        "note": scrub_text(body.get("note")),
        "ticket_id": re.sub(r"[^A-Za-z0-9#_-]", "", str(body.get("ticket_id") or ""))[:80] or None,
        "app_version": scrub_text(body.get("app_version"), 24) or None,
        "page": scrub_text(body.get("page"), 12) or None,
        "image": f"{stem}.{ext}" if image is not None else None,
        "image_type": ctype or None, "image_bytes": len(image) if image is not None else 0,
        "dom": f"{stem}.dom.json" if dom_text is not None else None,
        "dom_bytes": len(dom_text.encode("utf-8")) if dom_text is not None else 0,
    }
    if image is not None:
        (run_dir / meta["image"]).write_bytes(image)
    if dom_text is not None:
        (run_dir / meta["dom"]).write_text(dom_text, encoding="utf-8")
    tmp = run_dir / f"{stem}.json.tmp"
    tmp.write_text(json.dumps(meta), encoding="utf-8")
    tmp.replace(run_dir / f"{stem}.json")
    try:
        os.utime(run_dir, None)
    except OSError:
        pass
    return {"ok": True, "stored": True, "capture": meta}


def _drop_oldest(runs: List[Path], n: int) -> None:
    runs.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)
    for p in runs[:max(0, n)]:
        shutil.rmtree(p, ignore_errors=True)


def _run_age_days(run_dir: Path, now: datetime) -> float:
    """Age from the newest step meta's ``at`` (the dir mtime is the fallback)."""
    newest: Optional[datetime] = None
    for p in run_dir.glob("*.json"):
        if p.name.endswith(".dom.json"):
            continue
        try:
            at = datetime.fromisoformat(str(json.loads(p.read_text()).get("at")).replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            if newest is None or at > newest:
                newest = at
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    if newest is None:
        try:
            newest = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return float("inf")
    return (now - newest).total_seconds() / 86400.0


def purge_expired(*, ttl_days: float = TTL_DAYS, now: Optional[datetime] = None, root: Optional[Path] = None) -> Dict[str, Any]:
    """Delete every run older than ``ttl_days`` under every account. Returns what was removed and kept."""
    now = now or _now()
    root = root or captures_root()
    out: Dict[str, Any] = {"at": now.isoformat(), "ttl_days": ttl_days, "removed": [], "kept": 0, "root": str(root)}
    if not root.exists():
        return out
    for acct in sorted(p for p in root.iterdir() if p.is_dir()):
        for run in sorted(p for p in acct.iterdir() if p.is_dir()):
            if _run_age_days(run, now) > ttl_days:
                shutil.rmtree(run, ignore_errors=True)
                out["removed"].append(f"{acct.name}/{run.name}")
            else:
                out["kept"] += 1
    return out


def maybe_purge(account_id: str, *, now: Optional[datetime] = None) -> bool:
    """Run :func:`purge_expired` at most once per :data:`PURGE_EVERY_S` (a marker file beside the store)."""
    now = now or _now()
    root = captures_root()
    marker = root / ".last_purge"
    try:
        if marker.exists() and now.timestamp() - marker.stat().st_mtime < PURGE_EVERY_S:
            return False
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text(now.isoformat())
        purge_expired(now=now, root=root)
        return True
    except OSError:  # allow-silent: the timer is the second purge path; a failed marker never blocks a capture
        logger.warning("phone_captures: opportunistic purge failed for %s", account_id, exc_info=True)
        return False


def _step_metas(run_dir: Path) -> List[Dict[str, Any]]:
    metas = []
    for p in sorted(run_dir.glob("*.json")):
        if p.name.endswith(".dom.json") or p.name == "run.json":
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(m, dict):
            m["meta"] = p.name
            metas.append(m)
    metas.sort(key=lambda m: (int(m.get("seq") or 0), str(m.get("at") or "")))
    return metas


def _summary(run_dir: Path) -> Dict[str, Any]:
    metas = _step_metas(run_dir)
    failed = [m["step"] for m in metas if m.get("ok") is False]
    return {
        "run_id": run_dir.name, "flow": metas[0].get("flow") if metas else None,
        "first_at": metas[0].get("at") if metas else None, "last_at": metas[-1].get("at") if metas else None,
        "steps": len(metas), "failed": failed, "images": sum(1 for m in metas if m.get("image")),
        "doms": sum(1 for m in metas if m.get("dom")),
        "ticket_id": next((m.get("ticket_id") for m in metas if m.get("ticket_id")), None),
        "app_version": next((m.get("app_version") for m in metas if m.get("app_version")), None),
        "bytes": _dir_bytes(run_dir),
    }


def list_runs(account_id: str, limit: int = 20) -> Dict[str, Any]:
    """Runs for the account, newest first. ``present`` False = no capture directory yet (never an empty list
    read as "the phone recorded nothing")."""
    acct_dir = account_dir(account_id)
    if not acct_dir.exists():
        return {"account_id": account_id, "present": False, "runs": [], "ttl_days": TTL_DAYS}
    runs = [p for p in acct_dir.iterdir() if p.is_dir()]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    limit = max(1, min(int(limit), 200))
    return {"account_id": account_id, "present": True, "ttl_days": TTL_DAYS, "count": len(runs),
            "runs": [_summary(p) for p in runs[:limit]]}


def get_run(account_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    if not _RUN_RE.match(str(run_id or "")):
        raise ValueError("run_id invalid")
    run_dir = account_dir(account_id) / run_id
    if not run_dir.is_dir():
        return None
    return {**_summary(run_dir), "account_id": account_id, "steps": _step_metas(run_dir)}


def read_file(account_id: str, run_id: str, name: str) -> Optional[tuple[bytes, str]]:
    """One stored file (image or DOM JSON) as ``(bytes, content_type)``; None when absent. The name must be a
    plain file name the run's meta points at (no path parts)."""
    if not _RUN_RE.match(str(run_id or "")) or not re.match(r"^[0-9]{3}-[a-z0-9_]+\.(jpg|png|webp|dom\.json|json)$", str(name or "")):
        raise ValueError("name invalid")
    p = account_dir(account_id) / run_id / name
    if not p.is_file():
        return None
    ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(p.suffix.lstrip("."), "application/json")
    return p.read_bytes(), ctype


def latest_run_ref(account_id: str) -> Optional[Dict[str, Any]]:
    """The newest run's summary (for /prop/status and the refusal alert), or None."""
    try:
        got = list_runs(account_id, limit=1)
    except ValueError:
        return None
    return got["runs"][0] if got.get("runs") else None


def main(argv: Optional[list] = None) -> int:
    """CLI: ``--purge`` (the timer) or ``--list <account>``."""
    import argparse
    ap = argparse.ArgumentParser(description="phone step-capture store maintenance")
    ap.add_argument("--purge", action="store_true", help=f"delete runs older than {TTL_DAYS} days")
    ap.add_argument("--ttl-days", type=float, default=TTL_DAYS)
    ap.add_argument("--list", metavar="ACCOUNT", help="print the account's runs, newest first")
    a = ap.parse_args(argv)
    if a.purge:
        print(json.dumps(purge_expired(ttl_days=a.ttl_days)))
        return 0
    if a.list:
        print(json.dumps(list_runs(a.list), indent=1))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

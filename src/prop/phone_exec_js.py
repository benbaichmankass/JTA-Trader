"""SIGNED REMOTE LOGIC for the phone executor (PHONE-EXEC-OBSERVABLE-1018, piece 4; operator decision 2026-10-18).

The phone's page-side script (``tools/phone-executor/app/src/main/assets/exec.js``) is where every one of the four
guess-fixes lived, and each needed an APK. From now on the phone fetches it from OUR OWN API at startup and every
30 minutes (``RemoteJs.kt``), verifies it with the ed25519 public key embedded in the APK, and swaps it in without
a reinstall. Native / Kotlin changes still need an APK.

Contract (the three parties must agree byte for byte):

* **version** — the ``var EXEC_VERSION = "YYYY-MM-DD.N";`` line INSIDE exec.js (:func:`version_of`), so the file and
  its version cannot drift apart. Bump it on every change; the app pins by it and never injects the same version
  twice.
* **message** — ``"metis-exec-js\\n" + version + "\\n" + sha256hex(file bytes)``; **sig** — Ed25519 over it (base64).
* **signer** — ``.github/workflows/phone-exec-js-sign.yml`` on every push to ``main`` that touches exec.js: the
  private key lives ONLY in the Actions secret ``PHONE_EXEC_JS_SIGNING_KEY`` (generated once by the workflow itself,
  like the APK keystore; never printed); it POSTs ``{version, sha256, sig}`` to
  ``POST /api/bot/prop/phone/exec-js-signature`` (``DASHBOARD_API_TOKEN``, fail-closed), stored here beside the
  journal (``<trade_journal.db dir>/phone_exec/exec.js.sig.json``).
* **server** — ``GET /api/bot/prop/phone/exec.js?have=<version>`` (per-device bearer) serves the WORKING-TREE
  exec.js ONLY when the stored signature's ``sha256`` equals the tree file's sha256 right now (``ict-git-sync`` pulls
  main every ~5 min; until it does, or when nothing signed this exact file, the answer is ``ok: false`` and the
  phone keeps what it runs). ``unchanged: true`` when ``have`` is already that version.
* **phone** — recomputes the sha256 of the bytes it received, rebuilds the message, verifies with the embedded key,
  accepts only a strictly newer version, caches it, falls back to the bundled copy on any failure.

The server never signs and holds no private key; a signature file is inert data (a wrong one just means "serve
nothing"). The APK job embeds the PUBLIC key as ``assets/exec_pubkey.b64`` (derived from the same secret).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

EXEC_JS_REL = Path("tools/phone-executor/app/src/main/assets/exec.js")
_VERSION_RE = re.compile(r'var EXEC_VERSION = "(\d{4}-\d{2}-\d{2}\.\d+)";')
_VERSION_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_JS_BYTES = 2_000_000


def version_of(src: str) -> str:
    m = _VERSION_RE.search(src or "")
    return m.group(1) if m else ""


def message(version: str, sha256_hex: str) -> str:
    return f"metis-exec-js\n{version}\n{sha256_hex}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exec_js_path(root: Optional[Path] = None) -> Path:
    from src.utils.paths import repo_root
    return Path(root or repo_root()) / EXEC_JS_REL


def signature_path() -> Path:
    from src.prop import prop_journal
    return Path(prop_journal._db_path()).parent / "phone_exec" / "exec.js.sig.json"


def read_tree(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The working-tree exec.js: ``{js, sha256, version, bytes}`` or None when unreadable / unpinned / too big."""
    p = exec_js_path(root)
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_JS_BYTES:
        return None
    js = data.decode("utf-8", errors="strict")
    v = version_of(js)
    if not v:
        return None
    return {"js": js, "sha256": sha256_hex(data), "version": v, "bytes": len(data)}


def read_signature() -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(signature_path().read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not _VERSION_SHAPE.match(str(d.get("version") or "")) or not _SHA_RE.match(str(d.get("sha256") or "")):
        return None
    if not isinstance(d.get("sig"), str):
        return None
    return d


def store_signature(body: Dict[str, Any], *, now: Optional[datetime] = None, root: Optional[Path] = None) -> Dict[str, Any]:
    """``POST /phone/exec-js-signature`` (CI): validate the shape and store it. The answer says whether the VM's
    working tree already carries the signed bytes (``match``) -- it may lag main by a git-sync tick, which is not an
    error: the GET route compares at request time. Never verifies the signature (no public key here; the phone does)."""
    now = now or datetime.now(timezone.utc)
    version = str(body.get("version") or "")
    sha = str(body.get("sha256") or "").lower()
    sig = str(body.get("sig") or "")
    if not _VERSION_SHAPE.match(version):
        raise ValueError("version must be YYYY-MM-DD.N")
    if not _SHA_RE.match(sha):
        raise ValueError("sha256 must be 64 hex chars")
    try:
        raw = base64.b64decode(sig, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("sig must be base64") from exc
    if len(raw) != 64:
        raise ValueError("sig must be a 64-byte ed25519 signature")
    rec = {"version": version, "sha256": sha, "sig": sig, "signed_at": now.isoformat(),
           "signer": re.sub(r"[^A-Za-z0-9 _.:/#-]", "", str(body.get("signer") or ""))[:120] or None,
           "commit": re.sub(r"[^0-9a-f]", "", str(body.get("commit") or "").lower())[:40] or None}
    p = signature_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(p)
    tree = read_tree(root)
    match = bool(tree and tree["sha256"] == sha and tree["version"] == version)
    logger.info("phone_exec_js: signature stored for %s (%s) tree_match=%s", version, sha[:12], match)
    return {"ok": True, "stored": rec, "tree": {"version": tree["version"], "sha256": tree["sha256"]} if tree else None,
            "match": match, "note": None if match else "the VM working tree does not carry these bytes yet (git-sync lag, or not this file): served only once it does"}


def bundle(have: str = "", *, root: Optional[Path] = None) -> Dict[str, Any]:
    """``GET /phone/exec.js?have=``: the signed working-tree script, or why not. Fail closed on every mismatch."""
    tree = read_tree(root)
    if tree is None:
        return {"ok": False, "why": "tree_unreadable"}
    sig = read_signature()
    if sig is None:
        return {"ok": False, "why": "unsigned", "version": tree["version"]}
    if sig["sha256"] != tree["sha256"] or sig["version"] != tree["version"]:
        return {"ok": False, "why": "signature_mismatch", "version": tree["version"], "signed_version": sig["version"]}
    if have and have == tree["version"]:
        return {"ok": True, "unchanged": True, "version": tree["version"], "sha256": tree["sha256"]}
    return {"ok": True, "version": tree["version"], "sha256": tree["sha256"], "sig": sig["sig"], "js": tree["js"],
            "signed_at": sig.get("signed_at"), "bytes": tree["bytes"]}


def status(root: Optional[Path] = None) -> Dict[str, Any]:
    """What a session reads (no script body): tree version/sha, the stored signature, whether they match."""
    tree = read_tree(root)
    sig = read_signature()
    return {"tree": {"version": tree["version"], "sha256": tree["sha256"], "bytes": tree["bytes"]} if tree else None,
            "signature": {k: v for k, v in sig.items() if k != "sig"} if sig else None,
            "served": bool(tree and sig and sig["sha256"] == tree["sha256"] and sig["version"] == tree["version"]),
            "signature_path": str(signature_path())}


__all__ = ["version_of", "message", "sha256_hex", "read_tree", "read_signature", "store_signature", "bundle", "status"]

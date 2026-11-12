"""Gate registry — one row per gate, in the canonical store (lane GATE-REGISTRY).

Operator, 2026-11-12, verbatim:
  "the Admin tab in the UI needs to keep an actively-updated gate registry so we can have visibilty and make
  changes more quickly" / "the registy is a db in the actual system for you to use as well, i just want to see it
  on the admin tab".

Gates this adds or changes: **none.** This module only READS code and WRITES its own two tables. Nothing in the
trade, close, landing or deploy path consults it. A recorded decision is the operator's instruction to Claude; it
changes no code by itself. New, unregistered refusal sites are REPORTED (a listed row + one alert), never blocked.

Store: two tables in ``trade_journal.db`` (resolved by :func:`src.utils.paths.trade_journal_db_path`, created
lazily on connect like ``insights_usage``):

* ``gate_registry`` — one row per gate (registered from the GATE-AUDIT inventory, or ``unregistered`` when the
  drift scan finds a site the inventory does not carry).
* ``gate_decision_log`` — append-only history of every decision (the 2026-11-12 decisions file, and every
  ``POST /api/bot/gates/{id}/decision``).
* ``gate_registry_meta`` — key/value: the last refresh (when, at which HEAD, read-state, error).

Sources, in order (the live tree is read; ``ict-git-sync`` pulls ``main`` every ~5 min):

1. inventory: ``comms/gates/gate_inventory.json`` when present, else the ``gates`` of the compact seed
   ``comms/gates/registry_seed_2026-11-12.json``;
2. decisions: the seed's embedded decisions + every ``comms/gates/gate_decisions_*.json``; a file decision only
   replaces the row's decision when it is NEWER than the one the row holds, so an operator POST is never
   overwritten by an older file;
3. implementation: ``git log`` on the tree since the decision, for commits naming the gate id that touch a file
   outside ``comms/gates/`` and ``docs/`` → ``implemented`` with the PR number and sha; else ``pending``;
4. drift (the scan): a registered gate whose every cited file is gone → ``site_missing``; a ``run_guards.py``
   guard with no ``CI-<name>`` row, or a ``*_ENABLED`` / ``*_DISABLED`` env flag that is neither in the seed's
   baseline nor cited by any row → an ``unregistered`` row.

Hits: the inventory measured no 14-day counts it could defend (refusals are logged on the VM). ``hits_14d`` and
``hits_last_fired`` are therefore ``null`` with ``hits_read_state = "not_measurable"`` and the inventory's note —
never ``0``. A probe in ``comms/gates/hit_probes.json`` (``{gate_id: {"table": "signals", "column": "reason",
"equals": "<value>"}}``) turns a row ``measured``; ship one only after the value is seen in the live table.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from src.utils.paths import repo_root, trade_journal_db_path

logger = logging.getLogger(__name__)

SEED_RELPATH = "comms/gates/registry_seed_2026-11-12.json"
INVENTORY_RELPATH = "comms/gates/gate_inventory.json"
DECISIONS_GLOB = "comms/gates/gate_decisions_*.json"
HIT_PROBES_RELPATH = "comms/gates/hit_probes.json"

DECISIONS = ("keep", "remove", "report_only", "undecided")
IMPL_STATES = ("as_is", "pending", "implemented")
STATE_FILTERS = IMPL_STATES + ("unregistered", "drift")
#: How a decisions-file choice maps to a registry decision.
_CHOICE_MAP = {"KEEP": "keep", "REMOVE": "remove", "MAKE REPORT-ONLY": "report_only",
               "MAKE-REPORT-ONLY": "report_only", "REPORT-ONLY": "report_only", "UNDECIDED": "undecided"}
MAX_NOTE_CHARS = 2000
#: A GET re-runs the refresh when HEAD moved or the last one is older than this.
REFRESH_MAX_AGE = timedelta(hours=1)

_ENV_FLAG_RE = re.compile(r"""["']([A-Z][A-Z0-9_]*_(?:ENABLED|DISABLED))["']""")
_PATH_RE = re.compile(r"((?:[\w.-]+/)+[\w.-]+\.(?:py|ya?ml|sh|json|kt|js|ts|toml|txt|md))")
_PR_RE = re.compile(r"\(#(\d+)\)")
_ADDED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(.*)$", re.S)

_refresh_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────── schema

def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or str(trade_journal_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gate_registry (
            id TEXT PRIMARY KEY,
            category TEXT,
            where_site TEXT,
            where_more TEXT,
            blocks TEXT,
            real_money INTEGER,
            authorization TEXT,
            authorization_class TEXT,
            operator_decision TEXT NOT NULL DEFAULT 'undecided',
            decision_note TEXT,
            decided_at TEXT,
            decided_by TEXT,
            decision_source TEXT,
            implementation_state TEXT NOT NULL DEFAULT 'as_is',
            implementation_pr INTEGER,
            implementation_sha TEXT,
            mode_in_code TEXT,
            registry_state TEXT NOT NULL DEFAULT 'registered',
            drift TEXT,
            drift_detail TEXT,
            alerted_at TEXT,
            hits_last_fired TEXT,
            hits_14d INTEGER,
            hits_read_state TEXT NOT NULL DEFAULT 'not_measurable',
            hits_note TEXT,
            added_by TEXT,
            added_at TEXT,
            recommendation TEXT,
            effect TEXT,
            first_seen_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gate_decision_log (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            gate_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            note TEXT,
            decided_at TEXT NOT NULL,
            decided_by TEXT,
            source TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_gate_decision_log_dedupe "
        "ON gate_decision_log (gate_id, decision, decided_at)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS gate_registry_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()


# ─────────────────────────────────────────────────────────────── sources

def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("gate_registry: cannot read %s: %s", path, exc)
        return None


def load_sources(root: Optional[Path] = None) -> dict[str, Any]:
    """Return ``{gates, decisions, baseline, inventory_path, decision_paths}`` from the tree."""
    root = Path(root or repo_root())
    seed = _read_json(root / SEED_RELPATH) or {}
    inv = _read_json(root / INVENTORY_RELPATH) if (root / INVENTORY_RELPATH).exists() else None
    if isinstance(inv, dict) and isinstance(inv.get("gates"), list) and inv["gates"]:
        gates, inv_path = inv["gates"], INVENTORY_RELPATH
    else:
        gates, inv_path = list(seed.get("gates") or []), SEED_RELPATH
    decision_docs: list[tuple[str, dict]] = []
    if isinstance(seed.get("decisions"), dict):
        decision_docs.append((SEED_RELPATH, seed["decisions"]))
    for p in sorted(glob.glob(str(root / DECISIONS_GLOB))):
        doc = _read_json(Path(p))
        if isinstance(doc, dict):
            decision_docs.append((os.path.relpath(p, root), doc))
    decisions: list[dict] = []
    for rel, doc in decision_docs:
        at = str(doc.get("decided_at") or "")
        at = at + "T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", at) else at
        for d in doc.get("decisions") or []:
            choice = _CHOICE_MAP.get(str(d.get("choice") or "").strip().upper())
            if not d.get("id") or not choice:
                continue
            decisions.append({"id": d["id"], "decision": choice, "note": d.get("note") or "",
                              "decided_at": at or None, "decided_by": doc.get("decided_by") or "operator",
                              "source": rel, "cat": d.get("cat"), "where": d.get("where")})
    return {"gates": gates, "decisions": decisions, "baseline": seed.get("scan_baseline") or {},
            "inventory_path": inv_path, "decision_paths": [r for r, _ in decision_docs]}


def _cited_paths(where: str, where_more: Iterable[str]) -> list[str]:
    text = " ".join([where or ""] + [str(w) for w in (where_more or [])])
    return sorted(set(_PATH_RE.findall(text)))


def _split_added(added: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not added:
        return None, None
    m = _ADDED_RE.match(str(added).strip())
    return (m.group(1), m.group(2).strip()) if m else (None, str(added).strip())


# ─────────────────────────────────────────────────────────────── scans

def _git(root: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def head_sha(root: Optional[Path] = None) -> Optional[str]:
    rc, out = _git(Path(root or repo_root()), "rev-parse", "--short", "HEAD", timeout=10)
    return out.strip() if rc == 0 and out.strip() else None


def scan_implementation_commits(root: Path, ids: Iterable[str], since: str) -> tuple[dict[str, dict], Optional[str]]:
    """Map gate id → newest commit (after ``since``) naming it that touches code outside comms/gates and docs.

    Returns ``(found, error)``; ``error`` set means the scan could not look (the caller keeps prior state).
    """
    rc, out = _git(root, "log", f"--since={since}", "--format=\x1e%H\x1f%cI\x1f%s\x1f%b\x1f", "--name-only",
                   timeout=60)
    if rc != 0:
        return {}, f"git log failed: {out.strip()[:200]}"
    wanted = sorted(set(ids), key=len, reverse=True)
    found: dict[str, dict] = {}
    for chunk in out.split("\x1e"):
        parts = chunk.split("\x1f")
        if len(parts) < 5:
            continue
        sha, when, subject, body, files = parts[0], parts[1], parts[2], parts[3], parts[4]
        paths = [f for f in files.split("\n") if f.strip()]
        if not any(not (p.startswith("comms/gates/") or p.startswith("docs/")) for p in paths):
            continue
        msg = f"{subject}\n{body}"
        pr = _PR_RE.search(subject)
        for gid in wanted:
            if gid in found:
                continue
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(gid)}(?![A-Za-z0-9_-])", msg):
                found[gid] = {"sha": sha[:10], "pr": int(pr.group(1)) if pr else None, "at": when}
    return found, None


def scan_ci_guards(root: Path) -> tuple[Optional[list[str]], Optional[str]]:
    """Names in ``scripts/ci/run_guards.py::GUARDS``, read as text (never imported/executed)."""
    p = root / "scripts/ci/run_guards.py"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {p.name}: {exc}"
    start = text.find("GUARDS:")
    if start < 0:
        return None, "GUARDS registry not found in run_guards.py"
    return sorted(set(re.findall(r'^\s*"name":\s*"([^"]+)"', text[start:], re.M))), None


def scan_env_flags(root: Path) -> tuple[Optional[dict[str, str]], Optional[str]]:
    """``*_ENABLED`` / ``*_DISABLED`` string literals in src/ and scripts/ → first file seen."""
    rc, out = _git(root, "ls-files", "src", "scripts")
    if rc != 0:
        return None, "git ls-files failed"
    flags: dict[str, str] = {}
    for rel in out.split():
        if not rel.endswith((".py", ".sh")) or rel.startswith("src/runtime/gate_registry"):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for flag in _ENV_FLAG_RE.findall(text):
            flags.setdefault(flag, rel)
    return flags, None


def _load_hit_probes(root: Path) -> dict[str, dict]:
    p = root / HIT_PROBES_RELPATH
    doc = _read_json(p) if p.exists() else None
    return doc if isinstance(doc, dict) else {}


def _run_hit_probe(conn: sqlite3.Connection, probe: dict) -> tuple[Optional[int], Optional[str], str]:
    """``(count_14d, last_fired, read_state)``. Only the ``signals`` table is probe-able (allowlisted columns)."""
    if probe.get("table") != "signals" or probe.get("column") not in ("reason", "status") or "equals" not in probe:
        return None, None, "not_measurable"
    since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
    col = probe["column"]
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n, MAX(logged_at_utc) AS last FROM signals WHERE {col} = ? AND logged_at_utc >= ?",
            (str(probe["equals"]), since)).fetchone()
        last = conn.execute(f"SELECT MAX(logged_at_utc) FROM signals WHERE {col} = ?",
                            (str(probe["equals"]),)).fetchone()[0]
    except sqlite3.Error:
        return None, None, "not_measurable"
    return int(row["n"]), last, "measured"


# ─────────────────────────────────────────────────────────────── refresh

def _alert(text: str) -> bool:
    try:
        from src.runtime.notify import send_via_alert_manager
        send_via_alert_manager(text)
        return True
    except Exception as exc:  # noqa: BLE001 — an alert failure is logged and retried next refresh
        logger.error("gate_registry: alert failed (%s): %s", exc, text[:200])
        return False


def refresh(db_path: Optional[str] = None, root: Optional[Path] = None, *, send_alerts: bool = True) -> dict[str, Any]:
    """Re-seed metadata, apply newer file decisions, detect implementation and drift. Idempotent.

    Never raises on a scan failure: a scan that could not look leaves the affected fields as they were and the
    error is recorded on the refresh read-state.
    """
    root = Path(root or repo_root())
    with _refresh_lock:
        src = load_sources(root)
        now = _now()
        errors: list[str] = []
        conn = connect(db_path)
        try:
            existing = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM gate_registry")}
            inv_ids: set[str] = set()

            # 1. registered rows from the inventory
            for g in src["gates"]:
                gid = str(g.get("id") or "").strip()
                if not gid:
                    continue
                inv_ids.add(gid)
                added_at, added_by = _split_added(g.get("added"))
                auth_class = g.get("authorization")
                hits_note = g.get("hits_14d")
                vals = {
                    "category": g.get("category"), "where_site": g.get("where"),
                    "where_more": json.dumps(g.get("where_more") or []), "blocks": g.get("blocks"),
                    "real_money": None if g.get("real_money") is None else int(bool(g.get("real_money"))),
                    "authorization": None if auth_class == "NONE" else g.get("auth"),
                    "authorization_class": auth_class, "added_at": added_at, "added_by": added_by,
                    "recommendation": g.get("rec"), "effect": g.get("effect"),
                    "hits_note": hits_note if isinstance(hits_note, str) else None,
                    "registry_state": "registered",
                }
                _upsert(conn, gid, vals, existing, now)

            # 2. decision rows not in the inventory (e.g. PROPOSED-G1: decided, never in code)
            for d in src["decisions"]:
                if d["id"] not in inv_ids and d["id"] not in existing:
                    _upsert(conn, d["id"], {"category": d.get("cat"), "where_site": d.get("where"),
                                            "where_more": "[]", "registry_state": "registered",
                                            "drift_detail": "decided in the decisions file; not in the inventory"},
                            existing, now)
                    inv_ids.add(d["id"])

            # 3. file decisions (newer-wins; history always appended, de-duplicated)
            for d in src["decisions"]:
                _apply_decision(conn, d["id"], d["decision"], d["note"], d["decided_at"] or now,
                                d["decided_by"], d["source"], only_if_newer=True)

            # 4. scans
            baseline = src["baseline"]
            guards, err = scan_ci_guards(root)
            if err:
                errors.append(err)
            flags, err2 = scan_env_flags(root)
            if err2:
                errors.append(err2)
            rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM gate_registry")}
            cited_text = " ".join(f"{r['where_site'] or ''} {r['where_more'] or ''}" for r in rows.values())
            if guards is not None:
                for name in guards:
                    gid = f"CI-{name}"
                    if gid not in rows:
                        _upsert(conn, gid, {"category": "ci-guard", "where_site": f"scripts/ci/run_guards.py (GUARDS name={name})",
                                            "where_more": "[]", "blocks": "A run_guards.py guard inside the required `guards` check (merge-blocking unless allow_fail).",
                                            "registry_state": "unregistered", "drift": "unregistered",
                                            "drift_detail": f"guard '{name}' is in run_guards.py GUARDS but has no registry row"},
                                existing, now)
            if flags is not None:
                known = set(baseline.get("env_flags") or [])
                for flag, rel in sorted(flags.items()):
                    gid = f"UNREG-ENV-{flag}"
                    if flag in known or flag in cited_text or gid in rows:
                        continue
                    _upsert(conn, gid, {"category": "env-flag", "where_site": rel, "where_more": "[]",
                                        "blocks": f"Env flag {flag} switches a code path on/off (a possible default-off gate).",
                                        "registry_state": "unregistered", "drift": "unregistered",
                                        "drift_detail": f"{flag} first seen in {rel}; not in the 2026-11-12 baseline and not cited by any row"},
                            existing, now)

            # 5. implementation state, mode in code, site drift, hits
            rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM gate_registry")}
            decided = [r for r in rows.values() if r["operator_decision"] in ("remove", "report_only")]
            commits: dict[str, dict] = {}
            commit_err = None
            if decided:
                since = min((r["decided_at"] or now) for r in decided)[:10]
                commits, commit_err = scan_implementation_commits(root, [r["id"] for r in decided], since)
                if commit_err:
                    errors.append(commit_err)
            probes = _load_hit_probes(root)
            guard_set = set(guards) if guards is not None else None
            for gid, r in rows.items():
                upd: dict[str, Any] = {}
                dec = r["operator_decision"]
                if dec in ("remove", "report_only"):
                    c = commits.get(gid)
                    if c and (not r["decided_at"] or c["at"] >= r["decided_at"][:10]):
                        upd.update(implementation_state="implemented", implementation_pr=c["pr"], implementation_sha=c["sha"])
                    elif not commit_err:
                        upd.update(implementation_state="pending", implementation_pr=None, implementation_sha=None)
                else:
                    upd.update(implementation_state="as_is", implementation_pr=None, implementation_sha=None)
                impl = upd.get("implementation_state", r["implementation_state"])

                # site drift: only for registered code rows that cite a path
                site_gone = None
                if r["registry_state"] == "registered" and r["category"] not in ("platform", "proposed-w9"):
                    if r["category"] == "ci-guard" and gid.startswith("CI-") and guard_set is not None:
                        site_gone = gid[3:] not in guard_set
                    else:
                        paths = _cited_paths(r["where_site"] or "", json.loads(r["where_more"] or "[]"))
                        if paths:
                            site_gone = not any((root / p).exists() for p in paths)
                mode = "blocks"
                if r["category"] == "proposed-w9" or str(r["where_site"] or "").startswith("not in place"):
                    mode = None
                elif dec == "remove" and impl == "implemented":
                    mode = "removed"
                elif site_gone:
                    mode = None  # the cited site is not on the tree: we cannot say what the code does
                elif dec == "report_only" and impl == "implemented":
                    mode = "report_only"
                upd["mode_in_code"] = mode
                if r["registry_state"] == "registered":
                    if site_gone and not (dec == "remove" and impl == "implemented"):
                        upd.update(drift="site_missing", drift_detail="every file/guard this row cites is gone from the tree")
                    elif site_gone is not None or r["drift"] == "site_missing":
                        upd.update(drift=None, drift_detail=None if r["drift"] == "site_missing" else r["drift_detail"])
                probe = probes.get(gid)
                if isinstance(probe, dict):
                    n, last, state = _run_hit_probe(conn, probe)
                    upd.update(hits_14d=n, hits_last_fired=last, hits_read_state=state)
                else:
                    upd.update(hits_14d=None, hits_last_fired=None, hits_read_state="not_measurable")
                changed = {k: v for k, v in upd.items() if r.get(k) != v}
                if changed:
                    changed["updated_at"] = now
                    sets = ", ".join(f"{k} = ?" for k in changed)
                    conn.execute(f"UPDATE gate_registry SET {sets} WHERE id = ?", (*changed.values(), gid))
            conn.commit()

            # 6. alerts: once per drifting / unregistered row
            alerts_sent = 0
            if send_alerts:
                for r in conn.execute("SELECT id, drift, drift_detail, where_site FROM gate_registry "
                                      "WHERE drift IS NOT NULL AND alerted_at IS NULL"):
                    text = (f"Gate registry: {r['drift']} — {r['id']}\n{r['drift_detail'] or ''}\n"
                            f"where: {r['where_site'] or '—'}\nReported only; nothing is blocked. "
                            f"GET /api/bot/gates?state=drift")
                    if _alert(text):
                        conn.execute("UPDATE gate_registry SET alerted_at = ? WHERE id = ?", (now, r["id"]))
                        alerts_sent += 1
                conn.commit()

            head = head_sha(root)
            meta = {"at": now, "head_sha": head, "read_state": "partial" if errors else "read",
                    "error": "; ".join(errors) or None, "inventory_path": src["inventory_path"],
                    "decision_paths": src["decision_paths"], "alerts_sent": alerts_sent}
            conn.execute("INSERT OR REPLACE INTO gate_registry_meta (key, value) VALUES ('last_refresh', ?)",
                         (json.dumps(meta),))
            conn.commit()
            return meta
        finally:
            conn.close()


def _upsert(conn: sqlite3.Connection, gid: str, vals: dict, existing: dict, now: str) -> None:
    if gid in existing:
        cur = existing[gid]
        changed = {k: v for k, v in vals.items() if cur.get(k) != v}
        if changed:
            changed["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in changed)
            conn.execute(f"UPDATE gate_registry SET {sets} WHERE id = ?", (*changed.values(), gid))
            cur.update(changed)
    else:
        row = {"id": gid, **vals, "first_seen_at": now, "updated_at": now}
        cols = ", ".join(row)
        conn.execute(f"INSERT INTO gate_registry ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        existing[gid] = row


def _apply_decision(conn: sqlite3.Connection, gid: str, decision: str, note: str, decided_at: str,
                    decided_by: Optional[str], source: str, *, only_if_newer: bool) -> bool:
    """Append to the history (de-duplicated) and set the row's current decision. Returns True if it changed."""
    conn.execute(
        "INSERT OR IGNORE INTO gate_decision_log (gate_id, decision, note, decided_at, decided_by, source, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (gid, decision, note, decided_at, decided_by, source, _now()))
    cur = conn.execute("SELECT decided_at, operator_decision, decision_note FROM gate_registry WHERE id = ?",
                       (gid,)).fetchone()
    if cur is None:
        return False
    if only_if_newer and cur["decided_at"] and cur["decided_at"] >= decided_at:
        return False
    conn.execute(
        "UPDATE gate_registry SET operator_decision = ?, decision_note = ?, decided_at = ?, decided_by = ?, "
        "decision_source = ?, updated_at = ? WHERE id = ?",
        (decision, note or None, decided_at, decided_by, source, _now(), gid))
    return True


# ─────────────────────────────────────────────────────────────── reads / writes

def last_refresh(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute("SELECT value FROM gate_registry_meta WHERE key = 'last_refresh'").fetchone()
    try:
        return json.loads(row["value"]) if row else None
    except ValueError:
        return None


def refresh_if_stale(db_path: Optional[str] = None, root: Optional[Path] = None) -> Optional[dict]:
    """Refresh when never run, HEAD moved (a deploy / git-sync), or older than :data:`REFRESH_MAX_AGE`."""
    root = Path(root or repo_root())
    conn = connect(db_path)
    try:
        meta = last_refresh(conn)
    finally:
        conn.close()
    if meta:
        try:
            age = datetime.now(timezone.utc) - datetime.strptime(meta["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            age = REFRESH_MAX_AGE
        if age < REFRESH_MAX_AGE and meta.get("head_sha") and meta.get("head_sha") == head_sha(root):
            return None
    return refresh(db_path, root)


def row_to_api(r: sqlite3.Row | dict) -> dict[str, Any]:
    r = dict(r)
    try:
        where_more = json.loads(r.get("where_more") or "[]")
    except ValueError:
        where_more = []
    rm = r.get("real_money")
    return {
        "id": r["id"], "category": r.get("category"), "where": r.get("where_site"), "where_more": where_more,
        "blocks": r.get("blocks"), "real_money": None if rm is None else bool(rm),
        "authorization": r.get("authorization"), "authorization_class": r.get("authorization_class"),
        "operator_decision": r.get("operator_decision") or "undecided", "decision_note": r.get("decision_note"),
        "decided_at": r.get("decided_at"), "decided_by": r.get("decided_by"), "decision_source": r.get("decision_source"),
        "implementation_state": r.get("implementation_state"), "implementation_pr": r.get("implementation_pr"),
        "implementation_sha": r.get("implementation_sha"), "mode_in_code": r.get("mode_in_code"),
        "registry_state": r.get("registry_state"), "drift": r.get("drift"), "drift_detail": r.get("drift_detail"),
        "hits_last_fired": r.get("hits_last_fired"), "hits_14d": r.get("hits_14d"),
        "hits_read_state": r.get("hits_read_state"), "hits_note": r.get("hits_note"),
        "added_by": r.get("added_by"), "added_at": r.get("added_at"), "recommendation": r.get("recommendation"),
        "effect": r.get("effect"), "first_seen_at": r.get("first_seen_at"), "updated_at": r.get("updated_at"),
    }


def _parse_bool(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise ValueError("real_money must be true or false")


def list_gates(conn: sqlite3.Connection, *, category: Optional[str] = None, decision: Optional[str] = None,
               state: Optional[str] = None, real_money: Optional[str] = None,
               decided_since: Optional[str] = None) -> dict[str, Any]:
    """Filtered rows, drift/unregistered first, plus counts over the WHOLE registry (the population)."""
    if decision and decision not in DECISIONS:
        raise ValueError(f"decision must be one of {list(DECISIONS)}")
    if state and state not in STATE_FILTERS:
        raise ValueError(f"state must be one of {list(STATE_FILTERS)}")
    rm = _parse_bool(real_money)
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM gate_registry")]

    def keep(r: dict) -> bool:
        if category and r.get("category") != category:
            return False
        if decision and (r.get("operator_decision") or "undecided") != decision:
            return False
        if state == "unregistered" and r.get("registry_state") != "unregistered":
            return False
        if state == "drift" and not r.get("drift"):
            return False
        if state in IMPL_STATES and r.get("implementation_state") != state:
            return False
        if rm is not None and (r.get("real_money") is None or bool(r["real_money"]) != rm):
            return False
        if decided_since and not (r.get("decided_at") and r["decided_at"] >= decided_since):
            return False
        return True

    rows = [r for r in all_rows if keep(r)]
    rows.sort(key=lambda r: (0 if r.get("drift") else 1, 0 if r.get("registry_state") == "unregistered" else 1,
                             0 if r.get("real_money") else 1, str(r.get("category")), r["id"]))

    def count(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in all_rows:
            k = r.get(key)
            k = "—" if k is None else str(k)
            out[k] = out.get(k, 0) + 1
        return out

    return {
        "population": {"total": len(all_rows), "returned": len(rows),
                       "description": "every row in gate_registry (trade_journal.db): the GATE-AUDIT inventory "
                                      "(2026-11-12) + decided rows + unregistered sites found by the drift scan"},
        "counts": {"by_decision": count("operator_decision"), "by_state": count("implementation_state"),
                   "by_category": count("category"), "by_mode": count("mode_in_code"),
                   "real_money": sum(1 for r in all_rows if r.get("real_money")),
                   "drift": sum(1 for r in all_rows if r.get("drift")),
                   "unregistered": sum(1 for r in all_rows if r.get("registry_state") == "unregistered")},
        "gates": [row_to_api(r) for r in rows],
    }


def get_gate(conn: sqlite3.Connection, gid: str) -> Optional[dict[str, Any]]:
    r = conn.execute("SELECT * FROM gate_registry WHERE id = ?", (gid,)).fetchone()
    if r is None:
        return None
    hist = [dict(h) for h in conn.execute(
        "SELECT decision, note, decided_at, decided_by, source, recorded_at FROM gate_decision_log "
        "WHERE gate_id = ? ORDER BY decided_at DESC, seq DESC", (gid,))]
    return {"gate": row_to_api(r), "history": hist}


def record_decision(conn: sqlite3.Connection, gid: str, decision: str, note: Optional[str],
                    decided_by: Optional[str], source: str = "api") -> dict[str, Any]:
    """Record an operator decision. It is an instruction to Claude; it changes no code by itself."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {list(DECISIONS)}")
    note = (note or "").strip()
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"note exceeds {MAX_NOTE_CHARS} characters")
    if conn.execute("SELECT 1 FROM gate_registry WHERE id = ?", (gid,)).fetchone() is None:
        raise KeyError(gid)
    at = _now()
    _apply_decision(conn, gid, decision, note, at, decided_by, source, only_if_newer=False)
    # the implementation state follows the decision at once; the next refresh confirms it from git
    impl = "pending" if decision in ("remove", "report_only") else "as_is"
    conn.execute("UPDATE gate_registry SET implementation_state = ?, implementation_pr = NULL, "
                 "implementation_sha = NULL, updated_at = ? WHERE id = ?", (impl, at, gid))
    conn.commit()
    return {"gate_id": gid, "decision": decision, "note": note or None, "decided_at": at,
            "decided_by": decided_by, "source": source}

#!/usr/bin/env python3
# wiring: .github/workflows/research-queue-dispatch.yml + research-queue-grade.yml (dual-write step, ssh -> trainer `ingest-bundle`);
#         scripts/ops/publish_trainer_mirror.sh (`export-mirror`, every 2 min on the trainer);
#         src/units/db/trainer_store.py::_build_research_runs (live-VM mirror ingest)
"""The research results store (WSD-S6D-RESEARCH-RESULTS, docs/plans/WORK-STORE-DESIGN-2026-11.md § 3, § 6 S6, § 9, D7).

WHAT IT IS
----------
One SQLite file ON THE TRAINER VM (``$RESEARCH_STORE_ROOT/research_store.db``, default
``/home/ubuntu/ict-trader-data/research_store/``) holding ``research_runs``: one row per
research EVENT -- a dispatch stamp, a result record, a grade -- plus the result payloads
on the trainer's disk keyed by sha256. The trainer's 2-min mirror publishes a slim JSONL
export to the live VM, where ``src/units/db/trainer_store.py`` ingests it into
``trainer_store.db`` (table ``research_runs``).

WHY (operator approved D7, 2026-11-04 ~23:37Z): research results, dispatch stamps and
grades were committed to ``main`` (batch-land 127 + single results 52 + stamps 107 +
grading 28 per week, design § 1). On 2026-11-05/06 research-queue-grade timed out twice
waiting ~92 min on commit-to-main. Results belong where they are computed.

WHAT STAYS IN GIT: the unit SPEC (``research/queue/<id>.yaml``) -- its commit timestamp is
the registered-before-run proof. This module never edits a spec.

SHADOW PHASE (this file's current role). Git is still the truth. Every workflow that
writes a stamp / result / grade to git ALSO derives the same events from the files it
just wrote and ships them here (``bundle`` on the runner, ``ingest-bundle`` on the
trainer). ``parity`` compares the store against events derived from the trainer's own
checkout of ``main``: every git event recorded after the shadow start must have a
RUNNER-sourced row (a ``git_backfill`` row does not count -- otherwise parity would be
trivially true). Readers flip only after parity holds (row WSD-S6D-RESEARCH-RESULTS).

EVENT MODEL (derived from the files, one function for runner, backfill and parity):
  * dispatch -- ``last_dispatched_at`` on the unit; run_key = that timestamp.
  * result   -- one per ``research/results/<unit>/<run>.jsonl``; run_key = <run>;
                verdict = the rows' verdict if unanimous else ``mixed``; payload = the
                file bytes (sha256); the run's ``comms/research/<unit>/<run>/`` dir is
                shipped as a second payload (tar) when present.
  * grade    -- the unit's ``grading:`` block; run_key = sha256 of the block (each
                distinct grading state is one event, so ``latest`` refreshes accrue).
``event_id`` = sha256(kind|unit|run_key): idempotent across retries and sources.

Provenance: every row carries ``read_state`` exactly as the record states it; a value the
record does not carry is NULL (render "--"), never 0.

Tier-2 (a new store + a workflow writer). It is off the trade path: nothing on the live VM
reads it to trade. CLI: --self-test | bundle | ingest-bundle | backfill | parity |
export-mirror | stats.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUE = Path("research/queue")
RESULTS = Path("research/results")
COMMS = Path("comms/research")
DEFAULT_ROOT = "/home/ubuntu/ict-trader-data/research_store"
MIRROR_REL = Path("runtime_logs/trainer_mirror/research/research_runs.jsonl")
KINDS = ("dispatch", "result", "grade")
#: Fields copied from an E5 record into a result row's summary (the measurement body stays in the payload).
_SUMMARY_FIELDS = ("research_unit", "verdict", "read_state", "power_state", "generated_at", "note",
                   "schema_version", "data_fingerprint")
_MAX_NOTE = 600


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def store_root() -> Path:
    return Path(os.environ.get("RESEARCH_STORE_ROOT") or DEFAULT_ROOT)


def db_path(root: Path | None = None) -> Path:
    return (root or store_root()) / "research_store.db"


def event_id(kind: str, unit: str, run_key: str) -> str:
    return _sha(f"{kind}|{unit}|{run_key}".encode())


# --------------------------------------------------------------------------- schema

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:  # allow-silent: WAL is an optimization; rollback-journal mode still works
        pass
    # data-wiring: canonical store for research events (D7, design § 3). Shadow phase: the git files
    #   research/queue/<id>.yaml (last_dispatched_at, grading:) and research/results/<unit>/<run>.jsonl
    #   remain the source of truth; `backfill` loads their full history and `parity` checks this table
    #   against them. Readers flip to this table only after parity holds (row WSD-S6D-RESEARCH-RESULTS).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_runs ("
        "event_id TEXT PRIMARY KEY, unit_id TEXT NOT NULL, kind TEXT NOT NULL, run_key TEXT NOT NULL, "
        "at TEXT, verdict TEXT, read_state TEXT, n INTEGER, decision_rule_id TEXT, workflow TEXT, "
        "payload_sha256 TEXT, payload_bytes INTEGER, run_dir_sha256 TEXT, summary TEXT, "
        "first_source TEXT NOT NULL, recorded_at TEXT NOT NULL)")
    # data-wiring: provenance sidecar keyed to research_runs.event_id -- which writer(s) delivered each
    #   event (runner:<workflow>:<run_id> or git_backfill); parity counts only runner sources.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_run_sources ("
        "event_id TEXT NOT NULL, source TEXT NOT NULL, recorded_at TEXT NOT NULL, "
        "PRIMARY KEY (event_id, source))")
    # data-wiring: index of the payload files on the trainer's disk (payloads/<sha[:2]>/<sha>); the bytes
    #   are the canonical copy of research/results/*.jsonl and comms/research/<unit>/<run>/ in shadow.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_payloads ("
        "sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL, kind TEXT NOT NULL, origin TEXT, stored_at TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_rr_unit ON research_runs(unit_id, kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_rr_recorded ON research_runs(recorded_at)")
    return conn


# --------------------------------------------------------------------------- derivation (one function, three callers)

def _yaml():
    import yaml  # noqa: WPS433 -- runners and the trainer both have pyyaml; the import is deferred for --help
    return yaml


def _ts(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    return str(v)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"verdict": None, "read_state": "unparseable"})
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


def _tar_dir(d: Path) -> bytes:
    """Deterministic tar of a run dir (sorted names, zeroed mtimes/owners) so its sha256 is stable."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            data = p.read_bytes()
            ti = tarfile.TarInfo(str(p.relative_to(d)))
            ti.size, ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname, ti.mode = len(data), 0, 0, 0, "", "", 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def result_event(root: Path, unit: str, f: Path, *, with_payload: bool) -> tuple[dict[str, Any], dict[str, bytes]]:
    raw = f.read_bytes()
    rows = _read_rows(f)
    verdicts = {r.get("verdict") for r in rows}
    states = {r.get("read_state") for r in rows}
    first = rows[0] if rows else {}
    rule = first.get("decision_rule") if isinstance(first.get("decision_rule"), dict) else {}
    pop = first.get("population") if isinstance(first.get("population"), dict) else {}
    produced = first.get("produced_by") if isinstance(first.get("produced_by"), dict) else {}
    summary = {k: first.get(k) for k in _SUMMARY_FIELDS if k in first}
    if isinstance(summary.get("note"), str) and len(summary["note"]) > _MAX_NOTE:
        summary["note"] = summary["note"][:_MAX_NOTE] + "..."
    summary["rows"] = len(rows)
    summary["verdicts"] = sorted(str(v) for v in verdicts)
    summary["population"] = pop.get("description") if isinstance(pop.get("description"), str) else None
    payloads: dict[str, bytes] = {}
    sha = _sha(raw)
    if with_payload:
        payloads[sha] = raw
    run_dir = root / COMMS / unit / f.stem
    run_dir_sha = None
    if run_dir.is_dir() and with_payload:
        blob = _tar_dir(run_dir)
        run_dir_sha = _sha(blob)
        payloads[run_dir_sha] = blob
    n = pop.get("n")
    ev = {
        "kind": "result", "unit_id": unit, "run_key": f.stem,
        "at": first.get("generated_at"),
        "verdict": (next(iter(verdicts)) if len(verdicts) == 1 else "mixed") if rows else None,
        "read_state": (next(iter(states)) if len(states) == 1 else "mixed") if rows else None,
        "n": n if isinstance(n, int) else None,
        "decision_rule_id": rule.get("id"),
        "workflow": produced.get("workflow") if isinstance(produced.get("workflow"), str) else None,
        "payload_sha256": sha, "payload_bytes": len(raw), "run_dir_sha256": run_dir_sha,
        "summary": summary,
    }
    return ev, payloads


def spec_events(unit: str, text: str | None) -> list[dict[str, Any]]:
    """The dispatch + grade events one version of a unit spec states. Pure function of the text."""
    evs: list[dict[str, Any]] = []
    doc: dict[str, Any] = {}
    if text:
        try:
            loaded = _yaml().safe_load(text)
            doc = loaded if isinstance(loaded, dict) else {}
        except Exception:  # noqa: BLE001  # allow-silent: an unparseable spec yields no stamp/grade events; parity still sees its results
            doc = {}
    if doc.get("last_dispatched_at"):
        at = _ts(doc["last_dispatched_at"])
        evs.append({"kind": "dispatch", "unit_id": unit, "run_key": at, "at": at, "verdict": None,
                    "read_state": None, "n": None, "decision_rule_id": None,
                    "workflow": (doc.get("dispatch") or {}).get("workflow") if isinstance(doc.get("dispatch"), dict) else None,
                    "payload_sha256": None, "payload_bytes": None, "run_dir_sha256": None,
                    "summary": {"status": doc.get("status")}})
    g = doc.get("grading")
    if isinstance(g, dict) and g:
        block = json.loads(_canon(g))
        key = _sha(_canon(block).encode())[:24]
        rows = g.get("rows")
        evs.append({"kind": "grade", "unit_id": unit, "run_key": key, "at": _ts(g.get("graded_at")),
                    "verdict": None if g.get("verdict") is None else str(g.get("verdict")),
                    "read_state": "needs_review" if g.get("needs_review") else "graded",
                    "n": rows if isinstance(rows, int) else None,
                    "decision_rule_id": g.get("decision_rule_id"),
                    "workflow": None, "payload_sha256": None, "payload_bytes": None, "run_dir_sha256": None,
                    "summary": {"status": doc.get("status"), "grading": block}})
    for ev in evs:
        ev["event_id"] = event_id(ev["kind"], ev["unit_id"], ev["run_key"])
    return evs


def unit_events(root: Path, unit: str, *, with_payload: bool = False) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Every event the checkout's files show for one unit (backfill + parity). Pure read."""
    payloads: dict[str, bytes] = {}
    spec = root / QUEUE / f"{unit}.yaml"
    evs = spec_events(unit, spec.read_text(encoding="utf-8") if spec.exists() else None)
    rdir = root / RESULTS / unit
    if rdir.is_dir():
        for f in sorted(rdir.glob("*.jsonl")):
            ev, p = result_event(root, unit, f, with_payload=with_payload)
            ev["event_id"] = event_id("result", unit, ev["run_key"])
            evs.append(ev)
            payloads.update(p)
    return evs, payloads


def all_units(root: Path) -> list[str]:
    ids = {p.stem for p in (root / QUEUE).glob("RQ-*.yaml")}
    if (root / RESULTS).is_dir():
        ids |= {p.name for p in (root / RESULTS).iterdir() if p.is_dir() and p.name.startswith("RQ-")}
    return sorted(ids)


def changed_paths(root: Path) -> list[str]:
    """Paths under the research trees the working tree changed vs HEAD (tracked edits + untracked files)."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", str(QUEUE), str(RESULTS),
                          str(COMMS)], cwd=root, capture_output=True, text=True, check=True).stdout
    paths = []
    for line in out.splitlines():
        p = line[3:].strip().strip('"')
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.append(p)
    return paths


def changed_units(root: Path) -> list[str]:
    units: set[str] = set()
    for p in changed_paths(root):
        parts = Path(p).parts
        if len(parts) >= 3 and parts[:2] == ("research", "queue") and parts[2].endswith(".yaml"):
            units.add(parts[2][:-5])
        elif len(parts) >= 3 and parts[:2] in (("research", "results"), ("comms", "research")):
            units.add(parts[2])
    return sorted(u for u in units if u.startswith("RQ-"))


def _head_text(root: Path, rel: str) -> str | None:
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root, capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def runner_events(root: Path) -> tuple[list[dict[str, Any]], dict[str, bytes], list[str]]:
    """ONLY the events this working tree adds vs HEAD -- what this runner wrote, nothing it merely re-read.

    * a changed spec contributes the dispatch/grade events its new text states that HEAD's text did not;
    * a changed or new research/results/<unit>/<run>.jsonl contributes its result event, with the record
      bytes and the run dir (tar) as payloads.
    A runner claiming an event it did not write would make parity read true without the dual-write working.
    """
    evs: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    units: set[str] = set()
    for p in changed_paths(root):
        parts = Path(p).parts
        if len(parts) == 3 and parts[:2] == ("research", "queue") and parts[2].startswith("RQ-") and parts[2].endswith(".yaml"):
            unit = parts[2][:-5]
            f = root / p
            new = spec_events(unit, f.read_text(encoding="utf-8") if f.exists() else None)
            old = {e["event_id"] for e in spec_events(unit, _head_text(root, p))}
            add = [e for e in new if e["event_id"] not in old]
            evs.extend(add)
            if add:
                units.add(unit)
        elif len(parts) == 4 and parts[:2] == ("research", "results") and parts[2].startswith("RQ-") \
                and parts[3].endswith(".jsonl") and (root / p).is_file():
            ev, pay = result_event(root, parts[2], root / p, with_payload=True)
            ev["event_id"] = event_id("result", parts[2], ev["run_key"])
            evs.append(ev)
            payloads.update(pay)
            units.add(parts[2])
    return evs, payloads, sorted(units)


# --------------------------------------------------------------------------- bundle (runner) / ingest (trainer)

def make_bundle(root: Path, source: str, out: Path) -> dict[str, Any]:
    """A tar with events.jsonl + payloads/<sha>; built on the runner from the files it just wrote."""
    evs, payloads, units = runner_events(root)
    meta = {"source": source, "built_at": _now(), "units": units, "events": len(evs), "payloads": len(payloads)}
    with tarfile.open(out, "w:gz") as tf:
        def add(name: str, data: bytes) -> None:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        add("meta.json", json.dumps(meta).encode())
        add("events.jsonl", "".join(json.dumps(e, default=str) + "\n" for e in evs).encode())
        for sha, data in payloads.items():
            add(f"payloads/{sha}", data)
    return meta


def _store_payload(root: Path, conn: sqlite3.Connection, sha: str, data: bytes, kind: str, origin: str) -> bool:
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError(f"refused payload name {sha[:80]!r} (must be a sha256 hex digest)")
    if _sha(data) != sha:
        raise ValueError(f"payload hash mismatch for {sha}")
    p = root / "payloads" / sha[:2] / sha
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    cur = conn.execute("INSERT OR IGNORE INTO research_payloads (sha256, bytes, kind, origin, stored_at) VALUES (?,?,?,?,?)",
                       (sha, len(data), kind, origin, _now()))
    return cur.rowcount > 0


def ingest_events(conn: sqlite3.Connection, evs: Iterable[dict[str, Any]], source: str) -> dict[str, int]:
    c = {"events": 0, "new": 0, "new_source": 0}
    now = _now()
    for e in evs:
        if e.get("kind") not in KINDS or not e.get("unit_id") or not e.get("run_key"):
            raise ValueError(f"refused event (needs kind in {KINDS}, unit_id, run_key): {str(e)[:200]}")
        eid = event_id(e["kind"], e["unit_id"], e["run_key"])
        if e.get("event_id") and e["event_id"] != eid:
            raise ValueError(f"event_id mismatch for {e['unit_id']} {e['kind']} {e['run_key']}")
        c["events"] += 1
        cur = conn.execute(
            "INSERT OR IGNORE INTO research_runs (event_id, unit_id, kind, run_key, at, verdict, read_state, n, "
            "decision_rule_id, workflow, payload_sha256, payload_bytes, run_dir_sha256, summary, first_source, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, e["unit_id"], e["kind"], e["run_key"], e.get("at"), e.get("verdict"), e.get("read_state"), e.get("n"),
             e.get("decision_rule_id"), e.get("workflow"), e.get("payload_sha256"), e.get("payload_bytes"),
             e.get("run_dir_sha256"), json.dumps(e.get("summary"), default=str, sort_keys=True), source, now))
        c["new"] += cur.rowcount
        cur = conn.execute("INSERT OR IGNORE INTO research_run_sources (event_id, source, recorded_at) VALUES (?,?,?)",
                           (eid, source, now))
        c["new_source"] += cur.rowcount
    return c


def ingest_bundle(root: Path, fileobj) -> dict[str, Any]:
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tf:
        members = {m.name: m for m in tf.getmembers() if m.isfile()}
        meta = json.loads(tf.extractfile(members["meta.json"]).read())
        source = str(meta.get("source") or "")
        if not source.startswith("runner:"):
            raise ValueError(f"bundle source must be runner:<workflow>:<run_id>, got {source!r}")
        evs = [json.loads(l) for l in tf.extractfile(members["events.jsonl"]).read().decode().splitlines() if l.strip()]
        conn = connect(db_path(root))
        try:
            conn.execute("BEGIN")
            kinds = {}
            for e in evs:
                if e.get("payload_sha256"):
                    kinds[e["payload_sha256"]] = "result_record"
                if e.get("run_dir_sha256"):
                    kinds[e["run_dir_sha256"]] = "run_dir_tar"
            stored = 0
            for name, m in members.items():
                if name.startswith("payloads/"):
                    sha = name.split("/", 1)[1]
                    stored += _store_payload(root, conn, sha, tf.extractfile(m).read(), kinds.get(sha, "other"), source)
            c = ingest_events(conn, evs, source)
            conn.commit()
        finally:
            conn.close()
    return {"source": source, "units": len(meta.get("units") or []), "payloads_new": stored, **c}


def backfill(root: Path, repo: Path) -> dict[str, Any]:
    """Load the full history from a checkout of main (source git_backfill). Payloads are not copied:
    the checkout still holds them in shadow, and the bundle path stores every new one."""
    conn = connect(db_path(root))
    try:
        conn.execute("BEGIN")
        tot = {"units": 0, "events": 0, "new": 0, "new_source": 0}
        for u in all_units(repo):
            evs, _ = unit_events(repo, u)
            c = ingest_events(conn, evs, "git_backfill")
            tot["units"] += 1
            for k in ("events", "new", "new_source"):
                tot[k] += c[k]
        conn.commit()
    finally:
        conn.close()
    return tot


# --------------------------------------------------------------------------- parity / export / stats

def parity(root: Path, repo: Path, since: str) -> dict[str, Any]:
    """Every git-derived event NEWER than `since` must have a runner-sourced row in the store.

    'Newer' is the event's own `at` (dispatch stamp / result generated_at / graded_at date) -- a field the
    file states, so the denominator is printed, never inferred. A grade's at is a DATE, so a grade dated the
    `since` day is included (conservative). An event with no `at` is counted separately as `undated`, not
    folded into either bucket.
    """
    path = db_path(root)
    if not path.exists():
        return {"read_state": "could_not_look", "reason": f"no store at {path}"}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        runner = {r[0] for r in conn.execute("SELECT event_id FROM research_run_sources WHERE source LIKE 'runner:%'")}
        stored = {r[0]: r for r in conn.execute("SELECT event_id, verdict, read_state, payload_sha256 FROM research_runs")}
    finally:
        conn.close()
    day = since[:10]
    out = {"read_state": "measured", "since": since, "denominator": 0, "matched": 0, "undated": 0,
           "missing": [], "differs": [], "by_kind": {k: {"denominator": 0, "matched": 0} for k in KINDS}}
    for u in all_units(repo):
        evs, _ = unit_events(repo, u)
        for e in evs:
            at = e.get("at")
            if not at:
                out["undated"] += 1
                continue
            at_s = str(at)
            older = at_s[:10] < day if len(at_s) == 10 else at_s[:19] < since[:19]
            if older:
                continue
            out["denominator"] += 1
            out["by_kind"][e["kind"]]["denominator"] += 1
            if e["event_id"] not in runner:
                out["missing"].append({"unit": u, "kind": e["kind"], "run_key": e["run_key"], "at": at_s})
                continue
            s = stored[e["event_id"]]
            if (s[1], s[2], s[3]) != (e.get("verdict"), e.get("read_state"), e.get("payload_sha256")):
                out["differs"].append({"unit": u, "kind": e["kind"], "run_key": e["run_key"],
                                       "store": list(s[1:]), "git": [e.get("verdict"), e.get("read_state"),
                                                                     e.get("payload_sha256")]})
                continue
            out["matched"] += 1
            out["by_kind"][e["kind"]]["matched"] += 1
    out["ok"] = not out["missing"] and not out["differs"]
    out["missing_n"], out["differs_n"] = len(out["missing"]), len(out["differs"])
    out["missing"], out["differs"] = out["missing"][:50], out["differs"][:50]
    return out


def export_mirror(root: Path, out: Path) -> dict[str, Any]:
    """Slim JSONL for the live VM (no payload bytes), written atomically; untouched when unchanged so the
    mirror's mtime signature (trainer_store._source_signature) only moves when a row did."""
    path = db_path(root)
    if not path.exists():
        return {"read_state": "could_not_look", "reason": f"no store at {path}"}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        srcs: dict[str, list[str]] = {}
        for eid, s in conn.execute("SELECT event_id, source FROM research_run_sources ORDER BY source"):
            srcs.setdefault(eid, []).append(s)
        lines = []
        for r in conn.execute("SELECT * FROM research_runs ORDER BY unit_id, kind, run_key"):
            d = dict(r)
            d["summary"] = json.loads(d["summary"]) if d.get("summary") else None
            d["sources"] = srcs.get(d["event_id"], [])
            lines.append(json.dumps(d, sort_keys=True, default=str))
    finally:
        conn.close()
    body = ("\n".join(lines) + "\n").encode() if lines else b""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.read_bytes() == body:
        return {"rows": len(lines), "changed": False, "path": str(out)}
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(out)
    return {"rows": len(lines), "changed": True, "path": str(out)}


def stats(root: Path) -> dict[str, Any]:
    path = db_path(root)
    if not path.exists():
        return {"read_state": "could_not_look", "reason": f"no store at {path}"}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        kinds = dict(conn.execute("SELECT kind, COUNT(*) FROM research_runs GROUP BY kind").fetchall())
        src = dict(conn.execute("SELECT CASE WHEN source LIKE 'runner:%' THEN 'runner' ELSE source END, COUNT(*) "
                                "FROM research_run_sources GROUP BY 1").fetchall())
        last = conn.execute("SELECT MAX(recorded_at) FROM research_run_sources WHERE source LIKE 'runner:%'").fetchone()[0]
        recent = [dict(zip(("unit_id", "kind", "run_key", "verdict", "source", "recorded_at"), r)) for r in conn.execute(
            "SELECT r.unit_id, r.kind, r.run_key, r.verdict, s.source, s.recorded_at FROM research_run_sources s "
            "JOIN research_runs r USING (event_id) WHERE s.source LIKE 'runner:%' ORDER BY s.recorded_at DESC LIMIT 10")]
        pay = conn.execute("SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM research_payloads").fetchone()
    finally:
        conn.close()
    return {"read_state": "measured", "db": str(path), "events_by_kind": kinds, "sources": src,
            "last_runner_write": last, "payloads": {"n": pay[0], "bytes": pay[1]}, "recent_runner": recent}


# --------------------------------------------------------------------------- self-test

def _self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo, store = Path(td) / "repo", Path(td) / "store"
        (repo / QUEUE).mkdir(parents=True)
        (repo / RESULTS / "RQ-20300101-001").mkdir(parents=True)
        (repo / COMMS / "RQ-20300101-001" / "77").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / QUEUE / "RQ-20300101-001.yaml").write_text(
            "id: RQ-20300101-001\nstatus: queued\n# a comment that must survive\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"], cwd=repo, check=True)
        assert changed_units(repo) == [], changed_units(repo)
        spec = repo / QUEUE / "RQ-20300101-001.yaml"
        spec.write_text(spec.read_text() + "last_dispatched_at: '2030-01-02T00:00:00+00:00'\n")
        row = {"research_unit": "RQ-20300101-001", "verdict": "pass", "read_state": "measured",
               "generated_at": "2030-01-02T01:00:00Z", "decision_rule": {"id": "RULE-X"},
               "population": {"n": 40, "description": "d"}, "produced_by": {"workflow": "research-script-run"},
               "measurement": {"big": "x" * 5000}}
        (repo / RESULTS / "RQ-20300101-001" / "77.jsonl").write_text(json.dumps(row) + "\n")
        (repo / COMMS / "RQ-20300101-001" / "77" / "verdict.json").write_text("{}")
        assert changed_units(repo) == ["RQ-20300101-001"], changed_units(repo)
        evs, pay = unit_events(repo, "RQ-20300101-001", with_payload=True)
        kinds = sorted(e["kind"] for e in evs)
        assert kinds == ["dispatch", "result"], kinds
        res = next(e for e in evs if e["kind"] == "result")
        assert res["verdict"] == "pass" and res["n"] == 40 and res["decision_rule_id"] == "RULE-X"
        assert "measurement" not in res["summary"], "the measurement body belongs in the payload, not the row"
        assert res["payload_sha256"] in pay and res["run_dir_sha256"] in pay
        # deterministic tar => same sha twice
        assert unit_events(repo, "RQ-20300101-001", with_payload=True)[0][1]["run_dir_sha256"] == res["run_dir_sha256"]
        # parity before any runner write: both events missing (backfill does NOT count)
        backfill(store, repo)
        p = parity(store, repo, "2030-01-01T00:00:00Z")
        assert p["denominator"] == 2 and p["missing_n"] == 2 and not p["ok"], p
        # runner bundle -> ingest -> parity ok
        b = Path(td) / "b.tgz"
        make_bundle(repo, "runner:research-queue-dispatch:1", b)
        with b.open("rb") as fh:
            r = ingest_bundle(store, fh)
        assert r["events"] == 2 and r["new"] == 0 and r["new_source"] == 2 and r["payloads_new"] == 2, r
        p = parity(store, repo, "2030-01-01T00:00:00Z")
        assert p["ok"] and p["matched"] == 2, p
        # idempotent re-ingest
        with b.open("rb") as fh:
            r2 = ingest_bundle(store, fh)
        assert r2["new"] == 0 and r2["new_source"] == 0 and r2["payloads_new"] == 0, r2
        # grade lands -> new grade event; parity flags it until a runner ships it
        spec.write_text(spec.read_text() + "grading:\n  verdict: pass\n  graded_at: '2030-01-03'\n  rows: 1\n")
        p = parity(store, repo, "2030-01-01T00:00:00Z")
        assert p["missing_n"] == 1 and p["missing"][0]["kind"] == "grade", p
        evs3, _, _ = runner_events(repo)
        # still uncommitted: the dispatch + result rows are re-shipped (idempotent), plus the new grade
        assert sorted(e["kind"] for e in evs3) == ["dispatch", "grade", "result"], evs3
        make_bundle(repo, "runner:research-queue-grade:2", b)
        with b.open("rb") as fh:
            ingest_bundle(store, fh)
        assert parity(store, repo, "2030-01-01T00:00:00Z")["ok"]
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c2"], cwd=repo, check=True)
        assert runner_events(repo)[0] == [], "a clean tree ships nothing"
        # a re-grade on a committed unit ships ONLY the grade event, never the unchanged stamp
        spec.write_text(spec.read_text().replace("verdict: pass", "verdict: pass\n  needs_review: true"))
        evs4, pay4, _ = runner_events(repo)
        assert [e["kind"] for e in evs4] == ["grade"] and not pay4, evs4
        assert parity(store, repo, "2030-01-01T00:00:00Z")["missing_n"] == 1
        make_bundle(repo, "runner:research-queue-grade:3", b)
        with b.open("rb") as fh:
            ingest_bundle(store, fh)
        p = parity(store, repo, "2030-01-01T00:00:00Z")
        assert p["ok"] and p["by_kind"]["grade"]["matched"] == 1, p
        # window: an older since excludes nothing, a later since excludes everything
        assert parity(store, repo, "2031-01-01T00:00:00Z")["denominator"] == 0
        # a tampered payload is refused
        bad = Path(td) / "bad.tgz"
        with tarfile.open(bad, "w:gz") as tf:
            for name, data in (("meta.json", json.dumps({"source": "runner:x:1", "units": []}).encode()),
                               ("events.jsonl", b""), ("payloads/" + "0" * 64, b"nope")):
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        try:
            with bad.open("rb") as fh:
                ingest_bundle(store, fh)
            raise AssertionError("tampered payload accepted")
        except ValueError:
            pass
        # a non-runner source is refused on the bundle path
        nb = Path(td) / "nb.tgz"
        make_bundle(repo, "git_backfill", nb)
        try:
            with nb.open("rb") as fh:
                ingest_bundle(store, fh)
            raise AssertionError("non-runner bundle accepted")
        except ValueError:
            pass
        # export: rows carry sources; unchanged export does not rewrite
        out = Path(td) / "mirror" / "research_runs.jsonl"
        e1 = export_mirror(store, out)
        e2 = export_mirror(store, out)
        assert e1["changed"] and not e2["changed"] and e1["rows"] == 4, (e1, e2)  # dispatch, result, 2 grade states
        rows = [json.loads(l) for l in out.read_text().splitlines()]
        assert all(r["sources"] for r in rows) and all("payload" not in r for r in rows)
        assert stats(store)["events_by_kind"] == {"dispatch": 1, "grade": 2, "result": 1}
        assert stats(Path(td) / "nope")["read_state"] == "could_not_look"
    print("research_store self-test: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--store", default=None, help=f"store root (default $RESEARCH_STORE_ROOT or {DEFAULT_ROOT})")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("bundle", help="runner: build a tar of the changed units' events + payloads")
    b.add_argument("--repo", default=".")
    b.add_argument("--source", required=True, help="runner:<workflow>:<run_id>")
    b.add_argument("--out", required=True)
    i = sub.add_parser("ingest-bundle", help="trainer: ingest a bundle tar from stdin or --file")
    i.add_argument("--file", default="-")
    bf = sub.add_parser("backfill", help="trainer: load full history from a checkout (source git_backfill)")
    bf.add_argument("--repo", default=".")
    pa = sub.add_parser("parity", help="trainer: store vs the checkout for events newer than --since")
    pa.add_argument("--repo", default=".")
    pa.add_argument("--since", required=True)
    ex = sub.add_parser("export-mirror", help="trainer: write the slim JSONL the 2-min mirror publishes")
    ex.add_argument("--out", required=True)
    sub.add_parser("stats")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    root = Path(a.store) if a.store else store_root()
    if a.cmd == "bundle":
        print(json.dumps(make_bundle(Path(a.repo).resolve(), a.source, Path(a.out))))
        return 0
    if a.cmd == "ingest-bundle":
        if a.file == "-":
            r = ingest_bundle(root, io.BytesIO(sys.stdin.buffer.read()))
        else:
            with open(a.file, "rb") as fh:
                r = ingest_bundle(root, fh)
        print(json.dumps(r))
        return 0
    if a.cmd == "backfill":
        print(json.dumps(backfill(root, Path(a.repo).resolve())))
        return 0
    if a.cmd == "parity":
        r = parity(root, Path(a.repo).resolve(), a.since)
        print(json.dumps(r, indent=1))
        return 0 if r.get("ok") else 1
    if a.cmd == "export-mirror":
        print(json.dumps(export_mirror(root, Path(a.out))))
        return 0
    if a.cmd == "stats":
        print(json.dumps(stats(root), indent=1))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

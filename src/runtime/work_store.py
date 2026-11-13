"""The work store: ONE register (items) + an append-only, hash-chained event log (S1).

Design and operator approval: ``docs/plans/WORK-STORE-DESIGN-2026-11.md`` §§ 2, 6, 7
(D1 approves the store, D3 the write token; row ``WSD-S1-STORE-API``).

What this module is, and is not, in S1:

* It is the ONE implementation of the store: schema, validator, computed ``due_at``,
  the hash chain and the optimistic-concurrency check. The API routes
  (``src/web/api/routers/work_items.py``) and, later, ``scripts/ops/work.py`` (S3) and
  the VM's in-process writers call it; nothing else opens ``work_store.db``.
* It is NOT yet the source of the Workflow page. The canonical sources stay the
  checklist row files and the pipeline store until the S2 importer backfills them and
  S4 flips the readers. Nothing here migrates rows (S2) or flips a reader (S4).

The file is a SEPARATE SQLite database from ``trade_journal.db`` (a register write can
never lock the money DB), in WAL mode, resolved by ``work_store_db_path()`` in
``src.utils.paths`` -- never a hand-built path.

THE VALIDATOR CARRIES OVER TODAY'S REFUSALS, UNCHANGED (design G1):

* ``kind = build`` (a checklist row) goes through exactly what ``scripts/ops/checklist.py``
  does today: ``fill_defaults`` (process, not gates), the refusal to CLEAR ``owner`` /
  due / ``roadmap`` on a set, then ``checklist_store.filing_problems``.
* ``kind = observation`` (a pipeline item) goes through ``scripts/ops/pipeline.validate``
  itself, on the item mapped back to the pipeline's own vocabulary.

Both call the existing functions; neither is re-implemented here, so the two cannot
fork. ``due_at`` is COMPUTED by the store on every write and never accepted from a caller.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "GENESIS_HASH",
    "ITEM_STATES",
    "KINDS",
    "OPS",
    "TERMINAL",
    "WRITABLE_FIELDS",
    "ConflictError",
    "NotFoundError",
    "WorkStore",
    "WorkStoreError",
    "WorkStoreValidationError",
    "canonical_json",
    "event_hash",
]

KINDS = ("build", "observation")
ITEM_STATES = ("queued", "in_flight", "blocked", "landed_unproven", "done", "dropped")
TERMINAL = ("done", "dropped")
OPS = ("create", "set", "note", "close", "reopen", "observe", "migrate")
NEXT_ACTIONS = ("dispatch_lane", "check_observation", "apply_mandate", "ask_operator")
GENESIS_HASH = "0" * 64

#: Fields a caller may write. Everything else is the store's: ``id`` and ``kind`` are
#: fixed at create; ``due_at``, ``version``, ``created_at``, ``updated_at`` and
#: ``updated_by`` are computed. A patch naming any other key is refused, not ignored.
WRITABLE_FIELDS = (
    "parent_id", "title", "state", "owner", "lane", "model", "tier", "roadmap",
    "roadmap_unmapped_reason", "due_rule", "origin", "next_action", "priority_rank",
    "severity", "ceiling_usd", "spend_usd", "prs", "blocked_on", "summary", "terminal_reason",
    "extra",
)
#: ``extra`` (S2, WSD-S2-IMPORTER-PARITY): the source record's fields the merged model has no
#: column for (a row's ``note``, ``observation``, ``writeback``, ``phase``; a pipeline item's
#: ``routed_to``, ``redate``, ...), kept VERBATIM so the importer is lossless and S4 can serve
#: ``/work/checklist`` in its unchanged shape from the store. Keys starting ``_`` are the
#: importer's own bookkeeping (``src/runtime/work_store_import.py``), never source fields.
#: Planning keys a caller may write by name; the store folds each into ``extra`` (where the
#: importer keeps it, and where ``to_row`` reads it back as a top-level row key). Value ->
#: allowed set; ``None`` clears the key. (WORK-STORE-WEEK-LANE-WRITABLE.)
EXTRA_WRITABLE = {"week_lane": ("surge", "throttle", "after_reset", "standing")}  # "standing" stays writable/readable for old rows; new work uses the first three
_JSON_FIELDS = ("roadmap", "due_rule", "origin", "prs", "blocked_on", "extra")
_COMPUTED = ("due_at", "version", "created_at", "updated_at", "updated_by")

# data-wiring: items + events are the NEW register approved by the operator (D1,
#   docs/plans/WORK-STORE-DESIGN-2026-11.md). Canonical source until S4 flips the
#   readers: the checklist row files (docs/claude/work/checklist/) for kind=build and the
#   pipeline store (scripts/ops/pipeline.py STORE) for kind=observation; the backfill
#   from both is S2 (row WSD-S2-IMPORTER-PARITY). Nothing reads items/events as truth
#   before that parity report is clean.
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL CHECK (kind IN ('build','observation')),
  parent_id       TEXT REFERENCES items(id),
  title           TEXT NOT NULL,
  state           TEXT NOT NULL CHECK (state IN ('queued','in_flight','blocked','landed_unproven','done','dropped')),
  owner           TEXT NOT NULL DEFAULT 'manager',
  lane            TEXT, model TEXT, tier INTEGER,
  roadmap         TEXT NOT NULL,
  roadmap_unmapped_reason TEXT,
  due_rule        TEXT NOT NULL,
  due_at          TEXT,
  origin          TEXT,
  next_action     TEXT CHECK (next_action IN ('dispatch_lane','check_observation','apply_mandate','ask_operator') OR next_action IS NULL),
  priority_rank   INTEGER, severity TEXT,
  ceiling_usd REAL, spend_usd REAL,
  prs             TEXT, blocked_on TEXT,
  summary         TEXT,
  terminal_reason TEXT,
  extra           TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
  version         INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, at TEXT NOT NULL, by TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('create','set','note','close','reopen','observe','migrate')),
  patch TEXT NOT NULL,
  op_id TEXT UNIQUE,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_item ON events(item_id, seq);
CREATE INDEX IF NOT EXISTS idx_items_state_due ON items(state, due_at);
CREATE INDEX IF NOT EXISTS idx_items_parent ON items(parent_id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE VIEW IF NOT EXISTS due_now AS SELECT * FROM items
  WHERE state NOT IN ('done','dropped') AND due_at <= strftime('%Y-%m-%dT%H:%M:%SZ','now');
"""


class WorkStoreError(Exception):
    """Base class. ``status`` is the HTTP status the API answers with."""
    status = 400


class WorkStoreValidationError(WorkStoreError):
    status = 422


class NotFoundError(WorkStoreError):
    status = 404


class ConflictError(WorkStoreError):
    """A write based on a stale ``version`` (G3), or a create on an existing id."""
    status = 409

    def __init__(self, msg: str, current: dict | None = None):
        super().__init__(msg)
        self.current = current


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(obj: Any) -> str:
    """The one serialisation the hash chain is computed over (sorted keys, no spaces)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(prev_hash: str, ev: dict) -> str:
    """sha256(prev_hash || canonical(row)) over the event's own fields (design § 2.2)."""
    row = {k: ev.get(k) for k in ("seq", "item_id", "at", "by", "op", "patch", "op_id")}
    return hashlib.sha256((prev_hash + canonical_json(row)).encode("utf-8")).hexdigest()


# ── the legacy validators, called, not copied ──────────────────────────────────────────


def _checklist_store():
    from src.runtime import checklist_store
    return checklist_store


def _pipeline():
    from scripts.ops import pipeline
    return pipeline


def _date_of(value: Any) -> date | None:
    return _checklist_store()._as_date(value)


def _as_row(item: dict) -> dict:
    """A build item in the checklist row's own vocabulary (for fill_defaults/filing_problems)."""
    rule = item.get("due_rule") if isinstance(item.get("due_rule"), dict) else {}
    row = {
        "id": item.get("id"), "title": item.get("title"), "state": item.get("state"),
        "owner": item.get("owner"), "due_by": rule.get("due_date"),
        "roadmap": item.get("roadmap"), "priority_rank": item.get("priority_rank"),
    }
    # Only when set: fill_defaults uses setdefault, and a row filed by checklist.py has no
    # such key at all -- a None here would suppress the default reason and refuse the row.
    if item.get("roadmap_unmapped_reason") is not None:
        row["roadmap_unmapped_reason"] = item["roadmap_unmapped_reason"]
    return row


def _as_pipeline_item(item: dict) -> dict:
    """An observation item in the pipeline's own vocabulary (for pipeline.validate).

    queued + parent_id -> routed + routed_to (design § 2.2 mapping table); dropped -> killed.
    Any other merged state is passed through and the pipeline's own STATES check refuses it,
    exactly as it refuses that state today.
    """
    state = item.get("state")
    out = {
        "id": item.get("id"), "what": item.get("title"), "origin": item.get("origin"),
        "due_when": item.get("due_rule"), "next_action": item.get("next_action"),
        "state": {"dropped": "killed"}.get(state, state),
    }
    if state == "queued" and item.get("parent_id"):
        out["state"], out["routed_to"] = "routed", item["parent_id"]
    if item.get("terminal_reason") not in (None, ""):
        out["terminal_reason"] = item["terminal_reason"]
    return out


def _validate(item: dict, prior: dict | None, today: date | None) -> list[str]:
    """Run the carried-over validator; mutate ``item`` with the defaults a build gets filled.

    Returns the list of defaults filled (a build's ``fill_defaults``), for the event patch.
    Raises WorkStoreValidationError with the legacy validator's own words.
    """
    if item.get("kind") not in KINDS:
        raise WorkStoreValidationError(f"kind: must be one of {KINDS}, got {item.get('kind')!r}")
    if item.get("state") not in ITEM_STATES:
        raise WorkStoreValidationError(f"state: must be one of {ITEM_STATES}, got {item.get('state')!r}")
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        raise WorkStoreValidationError("title: required and non-empty")
    na = item.get("next_action")
    if na is not None and na not in NEXT_ACTIONS:
        raise WorkStoreValidationError(f"next_action: must be one of {NEXT_ACTIONS} or null, got {na!r}")
    for k in ("due_rule", "origin"):
        if item.get(k) is not None and not isinstance(item[k], dict):
            raise WorkStoreValidationError(f"{k}: must be an object")
    for k in ("prs", "blocked_on"):
        if item.get(k) is not None and not isinstance(item[k], list):
            raise WorkStoreValidationError(f"{k}: must be a list")
    if item.get("extra") is not None and not isinstance(item["extra"], dict):
        raise WorkStoreValidationError("extra: must be an object")

    filled: list[str] = []
    if item["kind"] == "build":
        cs = _checklist_store()
        row = _as_row(item)
        if prior is not None:
            # checklist.py op_set: only a DELIBERATE clearing errors -- re-date it, do not blank it.
            old = _as_row(prior)
            for k in ("owner", "due_by", "roadmap"):
                if old.get(k) and not row.get(k):
                    raise WorkStoreValidationError(
                        f"item {item.get('id')!r}: `set` refuses to clear `{k}` (was {old.get(k)!r}); "
                        f"change it to a new value instead")
        filled = cs.fill_defaults(row, today)
        problems = cs.filing_problems(row)
        if problems:
            raise WorkStoreValidationError(f"item {item.get('id')!r} refused: " + "; ".join(problems))
        item["owner"] = row["owner"]
        item["roadmap"] = row["roadmap"]
        item["roadmap_unmapped_reason"] = row.get("roadmap_unmapped_reason")
        if not item["roadmap"]:
            # fill_defaults leaves TERMINAL rows alone (checklist rows closed long ago carry no
            # roadmap), but items.roadmap is NOT NULL: a done/dropped build created without one
            # was a 500 (IntegrityError) on the live API, 2026-11-05T07:43Z. Fill, never refuse
            # (G1 tightens none), with the same default reason fill_defaults uses.
            item["roadmap"] = [cs.UNMAPPED]
            item["roadmap_unmapped_reason"] = item.get("roadmap_unmapped_reason") or (
                "not set at filing -- manager to map to a milestone at the next weekly pass")
            filled.append('roadmap=["unmapped"]')
        if row.get("due_by"):
            rule = dict(item.get("due_rule") or {})
            rule.setdefault("kind", "date")
            rule["due_date"] = row["due_by"]
            item["due_rule"] = rule
        elif item.get("due_rule") is None:
            item["due_rule"] = {}
    else:
        pl = _pipeline()
        try:
            pl.validate(_as_pipeline_item(item))
        except pl.PipelineError as exc:
            raise WorkStoreValidationError(f"item {item.get('id')!r} refused: {exc}") from None
        if not (isinstance(item.get("owner"), str) and item["owner"].strip()):
            item["owner"] = "manager"
        if not item.get("roadmap"):
            # The pipeline has no roadmap field today; the merged schema needs one. Filled,
            # never refused (G1 tightens none) -- the S8 drain maps it.
            item["roadmap"] = ["unmapped"]
            item.setdefault("roadmap_unmapped_reason",
                            "pipeline observation: no roadmap field in the pipeline vocabulary")
            filled.append('roadmap=["unmapped"]')
    if isinstance(item.get("roadmap"), str):
        item["roadmap"] = [item["roadmap"]]
    return filled


def compute_due_at(item: dict, *, now: str | None = None) -> str | None:
    """The store's computed due instant (UTC, ISO Z). NEVER taken from a caller.

    * build -- ``due_rule.due_date`` at 00:00Z (the checklist's ``due_by``; it is overdue
      once that date has passed, so it is due on the date itself).
    * observation -- ``pipeline.next_due_date`` (the same three clocks ``is_due`` reads):
      a date -> that date 00:00Z; ``date.min`` (always due: no usable cadence, or an
      unparseable clock) -> ``now``; None (soak-bound or event kind) -> the soak verdict
      read now when the item is soak-bound and due, else NULL until an ``observe`` write.
    * terminal -> NULL.
    """
    now = now or _now()
    if item.get("state") in TERMINAL:
        return None
    rule = item.get("due_rule") if isinstance(item.get("due_rule"), dict) else {}
    if item.get("kind") == "build":
        d = _date_of(rule.get("due_date"))
        return f"{d.isoformat()}T00:00:00Z" if d else now
    pl = _pipeline()
    legacy = _as_pipeline_item(item)
    d = pl.next_due_date(legacy)
    if d == date.min:
        return now
    if d is not None:
        return f"{d.isoformat()}T00:00:00Z"
    if (rule.get("soak") or {}).get("subject"):
        try:
            if pl.is_due(legacy):
                return now
        except Exception:  # noqa: BLE001 -- an unreadable soak state is DUE, the safe direction
            return now
    return None


# ── the store ──────────────────────────────────────────────────────────────────────────


class WorkStore:
    """One SQLite file (WAL). Every write is ONE transaction: validate, compute due_at,
    append the event (hash-chained), update the item. A retried ``op_id`` is a no-op."""

    def __init__(self, path: str | Path | None = None):
        if path is None:
            from src.utils.paths import work_store_db_path
            path = work_store_db_path()
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            # S2 added ``extra``; a store created by S1 (live since 2026-11-05) lacks it.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
            if "extra" not in cols:
                conn.execute("ALTER TABLE items ADD COLUMN extra TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                # A schema constraint the validator did not anticipate is the caller's bad
                # input (422 with the constraint named), never an unhandled 500.
                conn.execute("ROLLBACK")
                raise WorkStoreValidationError(f"refused by a store constraint: {exc}") from None
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # ── rows <-> dicts ──
    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in _JSON_FIELDS:
            if d.get(k) is not None:
                d[k] = json.loads(d[k])
        return d

    @staticmethod
    def _encode(item: dict) -> dict:
        d = dict(item)
        for k in _JSON_FIELDS:
            if d.get(k) is not None:
                d[k] = canonical_json(d[k])
        return d

    def _get(self, conn: sqlite3.Connection, item_id: str) -> dict | None:
        return self._decode(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())

    def _replayed(self, conn: sqlite3.Connection, op_id: str | None) -> dict | None:
        if not op_id:
            return None
        ev = conn.execute("SELECT item_id FROM events WHERE op_id = ?", (op_id,)).fetchone()
        if ev is None:
            return None
        return {"item": self._get(conn, ev["item_id"]), "replayed": True}

    def _append_event(self, conn: sqlite3.Connection, *, item_id: str, at: str, by: str,
                      op: str, patch: Any, op_id: str | None) -> dict:
        last = conn.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS_HASH
        ev = {"seq": (last["seq"] + 1) if last else 1, "item_id": item_id, "at": at, "by": by,
              "op": op, "patch": patch if isinstance(patch, str) else canonical_json(patch),
              "op_id": op_id or None, "prev_hash": prev}
        ev["hash"] = event_hash(prev, ev)
        conn.execute(
            "INSERT INTO events (seq, item_id, at, by, op, patch, op_id, prev_hash, hash) "
            "VALUES (:seq, :item_id, :at, :by, :op, :patch, :op_id, :prev_hash, :hash)", ev)
        return ev

    @staticmethod
    def _fold_extra_keys(fields: dict, base_extra: dict | None) -> dict:
        """Pop EXTRA_WRITABLE keys out of ``fields`` and merge them into ``extra``."""
        fields = dict(fields)
        named = {k: fields.pop(k) for k in list(fields) if k in EXTRA_WRITABLE}
        if not named:
            return fields
        for k, v in named.items():
            if v is not None and v not in EXTRA_WRITABLE[k]:
                raise WorkStoreValidationError(
                    f"{k}: must be one of {EXTRA_WRITABLE[k]} or null, got {v!r}")
        extra = dict(fields["extra"] if isinstance(fields.get("extra"), dict) else (base_extra or {}))
        for k, v in named.items():
            if v is None:
                extra.pop(k, None)
            else:
                extra[k] = v
        fields["extra"] = extra or None
        return fields

    @staticmethod
    def _check_patch_keys(fields: dict) -> None:
        bad = sorted(k for k in fields if k not in WRITABLE_FIELDS and k not in EXTRA_WRITABLE)
        if bad:
            computed = [k for k in bad if k in _COMPUTED]
            hint = f" ({', '.join(computed)} computed by the store, never accepted)" if computed else ""
            raise WorkStoreValidationError(f"fields not writable: {bad}{hint}")

    @staticmethod
    def _need_by(by: str) -> None:
        if not isinstance(by, str) or not by.strip():
            raise WorkStoreValidationError("by: required (who is writing)")

    def _write_item(self, conn, item: dict, *, insert: bool) -> None:
        enc = self._encode(item)
        cols = ["id", "kind", *WRITABLE_FIELDS, *_COMPUTED]
        vals = {c: enc.get(c) for c in cols}
        if insert:
            conn.execute(f"INSERT INTO items ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})", vals)
        else:
            sets = ", ".join(f"{c} = :{c}" for c in cols if c != "id")
            conn.execute(f"UPDATE items SET {sets} WHERE id = :id", vals)

    # ── writes ──
    def create(self, fields: dict, *, by: str, op_id: str | None = None,
               today: date | None = None) -> dict:
        self._need_by(by)
        fields = dict(fields)
        item_id, kind = fields.pop("id", None), fields.pop("kind", None)
        if not isinstance(item_id, str) or not item_id.strip():
            raise WorkStoreValidationError("id: required and non-empty")
        if not _checklist_store()._ID_OK.match(item_id):
            raise WorkStoreValidationError(f"id: {item_id!r} must match [A-Za-z0-9][A-Za-z0-9._-]*")
        self._check_patch_keys(fields)
        fields = self._fold_extra_keys(fields, None)
        with self._tx() as conn:
            if (r := self._replayed(conn, op_id)) is not None:
                return r
            if self._get(conn, item_id) is not None:
                raise ConflictError(f"item {item_id!r} already exists; use set", self._get(conn, item_id))
            item = {k: None for k in WRITABLE_FIELDS}
            item.update({"state": "queued", "owner": "manager"}, **fields)
            item.update(id=item_id, kind=kind)
            if item.get("parent_id") and self._get(conn, item["parent_id"]) is None:
                raise WorkStoreValidationError(f"parent_id: no item {item['parent_id']!r}")
            filled = _validate(item, None, today)
            at = _now()
            item.update(due_at=compute_due_at(item, now=at), version=1, created_at=at,
                        updated_at=at, updated_by=by)
            self._write_item(conn, item, insert=True)
            patch = {"fields": {k: item[k] for k in ("kind", *WRITABLE_FIELDS) if item.get(k) is not None}}
            if filled:
                patch["filled"] = filled
            ev = self._append_event(conn, item_id=item_id, at=at, by=by, op="create", patch=patch, op_id=op_id)
            return {"item": self._get(conn, item_id), "event": ev, "replayed": False}

    def _update(self, item_id: str, fields: dict, *, op: str, by: str, op_id: str | None,
                expected_version: int | None, today: date | None, note: str | None = None) -> dict:
        self._need_by(by)
        self._check_patch_keys(fields)
        with self._tx() as conn:
            if (r := self._replayed(conn, op_id)) is not None:
                return r
            prior = self._get(conn, item_id)
            if prior is None:
                raise NotFoundError(f"no item {item_id!r}")
            fields = self._fold_extra_keys(fields, prior.get("extra"))
            if expected_version is None:
                raise WorkStoreValidationError("If-Match: the item version this write is based on is required")
            if int(expected_version) != prior["version"]:
                raise ConflictError(
                    f"item {item_id!r} is at version {prior['version']}, the write was based on "
                    f"{expected_version}; re-read and re-apply", prior)
            item = dict(prior)
            item.update(fields)
            if item.get("parent_id") and item["parent_id"] != prior.get("parent_id") \
                    and self._get(conn, item["parent_id"]) is None:
                raise WorkStoreValidationError(f"parent_id: no item {item['parent_id']!r}")
            if op == "reopen":
                item["terminal_reason"] = None
            filled = _validate(item, prior, today)
            at = _now()
            item.update(due_at=compute_due_at(item, now=at), version=prior["version"] + 1,
                        updated_at=at, updated_by=by)
            # WORK-ROW-AGE-STALE: an item imported from a checklist row carries the row's OWN
            # updated_at/updated_by in `extra`, which every row reader serves (SPA Work page,
            # attention_watch, blocker_watch, work_digest). Only the item-level stamp moved on a
            # write, so rows read days old (MANAGER-VM-DIRECT-OPS: 2026-11-05 served vs 2026-11-12
            # stored). Moving the row's stamp with the write keeps store, export and files equal.
            ex = item.get("extra")
            if isinstance(ex, dict) and "updated_at" in ex:
                item["extra"] = dict(ex, updated_at=at, updated_by=by)
            self._write_item(conn, item, insert=False)
            if op == "note":
                patch: Any = {"note": note}
                if fields:
                    patch["fields"] = fields
            else:
                changed = {k: item[k] for k in WRITABLE_FIELDS if item.get(k) != prior.get(k)}
                patch = {"fields": changed}
            if filled:
                patch["filled"] = filled
            ev = self._append_event(conn, item_id=item_id, at=at, by=by, op=op, patch=patch, op_id=op_id)
            return {"item": self._get(conn, item_id), "event": ev, "replayed": False}

    def set(self, item_id: str, fields: dict, *, by: str, expected_version: int | None,
            op_id: str | None = None, today: date | None = None) -> dict:
        # A build may still be set done/dropped without a reason, exactly as checklist.py allows
        # today; an observation is refused by pipeline.validate without a terminal_reason.
        return self._update(item_id, fields, op="set", by=by, op_id=op_id,
                            expected_version=expected_version, today=today)

    def note(self, item_id: str, text: str, *, by: str, expected_version: int | None,
             op_id: str | None = None, summary: str | None = None, today: date | None = None) -> dict:
        """Append a note as its own event; the item's ``summary`` changes only when given."""
        if not isinstance(text, str) or not text.strip():
            raise WorkStoreValidationError("note: text required")
        fields = {"summary": summary} if summary is not None else {}
        return self._update(item_id, fields, op="note", by=by, op_id=op_id,
                            expected_version=expected_version, today=today, note=text.strip())

    def close(self, item_id: str, *, state: str, reason: str, by: str,
              expected_version: int | None, op_id: str | None = None, today: date | None = None) -> dict:
        if state not in TERMINAL:
            raise WorkStoreValidationError(f"close: state must be one of {TERMINAL}")
        if not isinstance(reason, str) or not reason.strip():
            raise WorkStoreValidationError("close: a stated reason is required (an item never closes by going quiet)")
        return self._update(item_id, {"state": state, "terminal_reason": reason.strip()}, op="close",
                            by=by, op_id=op_id, expected_version=expected_version, today=today)

    # ── the S2 importer's write path (files -> store, one-way, during the shadow) ──
    def migrate(self, entries: list[dict], *, by: str, chunk: int = 250) -> dict:
        """Upsert items imported from the canonical files, each change as ``migrate`` events.

        ``entries``: ``{"item": <full item incl. id + kind>, "events": [{"op_id", "patch"}],
        "reconcile_op_id": str}``. For each entry, in ONE transaction per ``chunk``:

        * source events whose ``op_id`` is already in the chain are skipped (idempotent);
        * if the item equals the stored one (kind + writable fields) and no new event was
          appended, nothing is written;
        * otherwise the item is inserted / updated (version + 1, ``due_at`` recomputed) and,
          when no source event carried the change, one ``reconcile`` event records it.

        This path deliberately does NOT run the G1 filing refusals: the design's rule is "no
        bulk drop -- every open item arrives open" (§ 4), and 504 open rows are undated today.
        What G1 would have refused is recorded on the event (``filing_problems``) instead, so
        the D2 drain can read it. Schema constraints still apply; one bad entry is rolled back
        alone (SAVEPOINT) and reported, never aborting the run.
        """
        self._need_by(by)
        out = {"created": 0, "updated": 0, "unchanged": 0, "skipped_native": 0, "events": 0, "errors": []}
        for start in range(0, len(entries), chunk):
            with self._tx() as conn:
                known = None
                for e in entries[start:start + chunk]:
                    item = dict(e["item"])
                    conn.execute("SAVEPOINT m")
                    try:
                        if known is None:
                            known = {r[0] for r in conn.execute(
                                "SELECT op_id FROM events WHERE op_id LIKE 'import:%'")}
                        res, n_ev = self._migrate_one(conn, item, e, by, known)
                        out[res] += 1
                        out["events"] += n_ev
                        conn.execute("RELEASE m")
                    except (sqlite3.IntegrityError, WorkStoreError, ValueError, TypeError) as exc:
                        conn.execute("ROLLBACK TO m")
                        conn.execute("RELEASE m")
                        out["errors"].append({"id": item.get("id"), "error": f"{type(exc).__name__}: {exc}"})
        return out

    def _migrate_one(self, conn, item: dict, e: dict, by: str, known: set) -> tuple[str, int]:
        if item.get("kind") not in KINDS:
            raise WorkStoreValidationError(f"kind: {item.get('kind')!r}")
        if item.get("state") not in ITEM_STATES:
            raise WorkStoreValidationError(f"state: {item.get('state')!r}")
        prior = self._get(conn, item["id"])
        if prior is not None and prior.get("kind") != item["kind"]:
            raise ConflictError(f"item {item['id']!r} exists as kind {prior.get('kind')!r}")
        # WORK-STORE-IMPORTER-RACE (2026-11-12): the caller decided "not native" from a snapshot
        # read BEFORE this transaction (the VM importer lists the whole store, then migrates for
        # minutes). A session write landing in between made the item native, and writing the
        # entry anyway reverted it to the frozen file (MEASURED: 3 of 319 BACKLOG-DRAIN-20261112
        # writes reverted 2 s after landing, e.g. PI-20261106-01AFOLUJ-0002 seq 10666 -> 10668).
        # Re-check here, under the write lock: an item last written by someone else is the truth.
        if prior is not None and prior.get("updated_by") != by:
            return "skipped_native", 0
        new_events = [ev for ev in e.get("events") or [] if ev["op_id"] not in known]
        full = {k: item.get(k) for k in WRITABLE_FIELDS}
        full.update(id=item["id"], kind=item["kind"])
        if not full.get("owner"):
            full["owner"] = "manager"
        if full.get("roadmap") is None:
            full["roadmap"] = []
        if full.get("due_rule") is None:
            full["due_rule"] = {}
        if not isinstance(full.get("title"), str) or not full["title"].strip():
            full["title"] = item["id"]
        if full.get("parent_id") and self._get(conn, full["parent_id"]) is None:
            full["parent_id"] = None  # the importer only links parents it has imported
        same = prior is not None and all(prior.get(k) == full.get(k) for k in WRITABLE_FIELDS)
        if same and not new_events:
            return "unchanged", 0
        at = _now()
        full.update(due_at=compute_due_at(full, now=at),
                    version=(prior["version"] + 1) if prior else 1,
                    created_at=prior["created_at"] if prior else at,
                    updated_at=at, updated_by=by)
        self._write_item(conn, full, insert=prior is None)
        for ev in new_events:
            self._append_event(conn, item_id=item["id"], at=at, by=by, op="migrate",
                               patch=ev["patch"], op_id=ev["op_id"])
            known.add(ev["op_id"])
        if not new_events:
            changed = {k: full[k] for k in WRITABLE_FIELDS if prior is None or full.get(k) != prior.get(k)}
            op_id = e.get("reconcile_op_id") or f"import:reconcile:{item['id']}:v{full['version']}"
            if op_id in known:
                op_id = f"{op_id}:v{full['version']}"
            self._append_event(conn, item_id=item["id"], at=at, by=by, op="migrate",
                               patch={"reconcile": changed}, op_id=op_id)
            known.add(op_id)
        return ("updated" if prior is not None else "created"), (len(new_events) or 1)

    def chain_head(self) -> dict:
        with self._connect() as conn:
            r = conn.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            return {"seq": r["seq"], "hash": r["hash"]} if r else {"seq": 0, "hash": GENESIS_HASH}

    # ── reads ──
    def get(self, item_id: str) -> dict | None:
        with self._connect() as conn:
            return self._get(conn, item_id)

    def list_items(self, *, state: str | None = None, due: bool = False, parent: str | None = None,
                   since: str | None = None, kind: str | None = None, limit: int = 500,
                   offset: int = 0) -> list[dict]:
        where, args = [], []
        if state:
            where.append("state = ?")
            args.append(state)
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if parent:
            where.append("parent_id = ?")
            args.append(parent)
        if since:
            where.append("updated_at >= ?")
            args.append(since)
        table = "due_now" if due else "items"
        sql = f"SELECT * FROM {table}" + (f" WHERE {' AND '.join(where)}" if where else "")
        sql += " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?"
        with self._connect() as conn:
            return [self._decode(r) for r in conn.execute(sql, (*args, int(limit), int(offset)))]

    def count_items(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def events(self, item_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if item_id is None:
                rows = conn.execute("SELECT * FROM events ORDER BY seq")
            else:
                rows = conn.execute("SELECT * FROM events WHERE item_id = ? ORDER BY seq", (item_id,))
            return [dict(r) for r in rows]

    def verify_chain(self) -> dict:
        """Walk the whole chain. ``ok`` False names the first broken seq (a silent edit)."""
        prev, n = GENESIS_HASH, 0
        for ev in self.events():
            n += 1
            if ev["prev_hash"] != prev:
                return {"ok": False, "events": n, "broken_at": ev["seq"], "why": "prev_hash does not link"}
            if event_hash(prev, ev) != ev["hash"]:
                return {"ok": False, "events": n, "broken_at": ev["seq"], "why": "hash does not match the row"}
            prev = ev["hash"]
        return {"ok": True, "events": n, "head": prev}

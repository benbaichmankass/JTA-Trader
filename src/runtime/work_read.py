"""S4 -- the register is READ from, and WRITTEN to, the work store (WSD-S4-READERS-FLIP).

Design: ``docs/plans/WORK-STORE-DESIGN-2026-11.md`` § 4 steps 2-3 (freeze, flip readers), § 6 S4,
§ 7 (guards read the export when CI has no VM access; rollback is ``work.py export --to-files``).

THE FREEZE IS ONE COMMITTED FACT, not a flag: ``docs/claude/work/checklist/_header.json`` carries
``frozen_into_work_store``. From that commit on:

* READS of the canonical register (``checklist_store.load()`` / ``load_path()`` / ``read_row()`` and
  ``pipeline.read_log()`` on the canonical ``docs/claude/work/pipeline``) come from ``work_store.db``
  WHEREVER THAT FILE EXISTS -- the live VM, where the API, ``attention_watch``, ``work_digest_now``,
  ``work_report`` and ``blocker_watch`` run. Every reader flips at once because they all go through
  those two loaders (the ``checklist-readers-guard`` one-loader rule).
* Where it does not exist (a cloud session, a GitHub runner, a laptop) bulk reads come from the
  LIVE store through ``GET /api/bot/work/items`` (``RemoteStore``) -- HEALTH-20261111-EXPORT-READS-STALE:
  the files are THE EXPORT, frozen at the cutover, and reading them as the register reported counts
  up to 6 days stale with no read-state saying so. If the API cannot be reached the read RAISES
  (could_not_look); it never falls back to the export.
* The export is read only when a caller ASKS for it: ``WORK_READ_SOURCE=export`` (the CI guards,
  which check the committed files -- design § 7; ``scripts/ci/run_guards.py`` sets it) or under
  pytest (a test must never reach the live API). Every export read is stamped in ``LAST_READ``
  (source + the newest export record) so a CLI can print what it actually read.
  A single-row read for a WRITE (``read_row``) goes to the API too, so an edit is never based on
  the stale export.
* WRITES of a row (``checklist_store.write_row``) and of a pipeline record (``pipeline.append``) go
  to the store: in-process where the DB is local, else through ``scripts/ops/work.py`` (the API, with
  its outbox fallback). The files are never written again by those paths.

A read of the store that FAILS raises (callers already map that to unreadable / could_not_look);
it never falls back to the stale files and never reads as "0 rows".
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKLIST_STORE = Path("docs/claude/work/checklist")
PIPELINE_STORE = Path("docs/claude/work/pipeline")
HEADER = "_header.json"
FROZEN_KEY = "frozen_into_work_store"
SEQ = "_seq"
WRITER = "work-read-shim"

__all__ = ["FROZEN_KEY", "SOURCE_ENV", "LAST_READ", "RemoteStore", "WorkReadError", "read_source", "read_state",
           "frozen", "is_canonical", "local_store", "checklist_rows", "pipeline_result",
           "due_now_split", "observation_version", "get_row", "put_row", "get_observation", "put_observation", "WorkWriteError"]


class WorkWriteError(ValueError):
    """A write the store refused (validation / conflict), with the store's own words."""


def is_canonical(path: Path | str, rel: Path) -> bool:
    """Is ``path`` the repo's own register location (not a test fixture / archive copy)?

    ``rel`` must be one of this module's fixed RELATIVE constants -- never a caller's
    monkeypatchable ``STORE`` global: ``REPO / <absolute tmp path>`` is that tmp path, which would
    make a test's temp store "canonical" and send its writes to the live API."""
    if Path(rel).is_absolute() or Path(rel) not in (CHECKLIST_STORE, PIPELINE_STORE):
        return False
    try:
        p = Path(path)
        p = p if p.is_absolute() else (Path.cwd() / p)
        return p.resolve() == (REPO / rel).resolve()
    except OSError:
        return False


def frozen(repo: Path = REPO) -> bool:
    try:
        head = json.loads((repo / CHECKLIST_STORE / HEADER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(head, dict) and head.get(FROZEN_KEY))


def local_store():
    """The WorkStore when ``work_store.db`` exists at the resolved path, else None."""
    from src.utils.paths import work_store_db_path
    path = work_store_db_path()
    if not Path(path).is_file():
        return None
    from src.runtime.work_store import WorkStore
    return WorkStore(path)


#: Where a canonical bulk read comes from off the VM: ``auto`` (default: the live API, the export
#: only under pytest), ``api``, or ``export`` (explicit -- the CI guards over the committed files).
SOURCE_ENV = "WORK_READ_SOURCE"
#: What the LAST canonical read in this process actually read, per register ("checklist" /
#: "pipeline"): ``{"source": "work_store_db" | "work_store_api" | "export", ...}``. A CLI prints it
#: as its read-state so a count is never silently the frozen export.
LAST_READ: dict[str, dict] = {}


class WorkReadError(OSError):
    """The live store could not be read off the VM (could_not_look). Never "0 rows"."""


def _export_newest(repo: Path, rel: Path) -> str | None:
    """The newest export file's stamp: pipeline record filenames are timestamp-prefixed; checklist
    rows carry ``updated_at``. Cheap: names only for the pipeline, a max over rows otherwise."""
    d = repo / rel
    try:
        if rel == PIPELINE_STORE:
            names = sorted(p.name for p in d.glob("*.json"))
            return names[-1].split("-", 1)[0] if names else None
        best = None
        for p in d.glob("*.json"):
            if p.name == HEADER:
                continue
            try:
                u = json.loads(p.read_text(encoding="utf-8")).get("updated_at")
            except (OSError, ValueError):
                continue
            if isinstance(u, str) and (best is None or u > best):
                best = u
        return best
    except OSError:
        return None


class RemoteStore:
    """The read half of ``WorkStore`` over ``GET /api/bot/work/items`` (off the VM).

    Pages at the API's maximum (1000). The listing is ordered by ``updated_at`` so a write landing
    mid-page can shift a page boundary: a duplicate id, or (for an unfiltered list) a count that
    disagrees with the API's ``total``, means the snapshot is torn -- re-page once, then raise."""

    PAGE = 1000
    _cache: dict[tuple, list[dict]] = {}

    def _page_all(self, params: dict) -> list[dict]:
        import urllib.parse
        w = _work_cli()
        last = "unknown"
        for _attempt in range(2):
            out, offset, total = [], 0, None
            while True:
                q = urllib.parse.urlencode({**params, "limit": self.PAGE, "offset": offset})
                try:
                    st, p, _ = w.http("GET", f"{w.API}?{q}", timeout=60.0)
                except w.WorkError as exc:
                    raise WorkReadError(f"could_not_look: work store API not reached: {exc}") from None
                if st != 200 or p.get("readState") != "read" or not isinstance(p.get("items"), list):
                    raise WorkReadError(f"could_not_look: work store API answered HTTP {st} "
                                        f"readState={p.get('readState')!r}: {p.get('error') or p.get('detail')}")
                batch = p["items"]
                total = p.get("total")
                out += batch
                if len(batch) < self.PAGE:
                    break
                offset += self.PAGE
            ids = [i.get("id") for i in out]
            torn = len(set(ids)) != len(ids)
            if not params and isinstance(total, int) and total != len(out):
                torn = True
            if not torn:
                return out
            last = f"{len(out)} rows, {len(ids) - len(set(ids))} duplicate ids, total={total}"
        raise WorkReadError(f"could_not_look: the store changed while paging twice ({last}); re-run")

    def list_items(self, *, state: str | None = None, due: bool = False, parent: str | None = None,
                   since: str | None = None, kind: str | None = None, limit: int = 500,
                   offset: int = 0) -> list[dict]:
        params = {k: v for k, v in (("state", state), ("parent", parent), ("since", since),
                                    ("kind", kind)) if v}
        if due:
            params["due"] = "true"
        key = tuple(sorted(params.items()))
        if key not in self._cache:  # one snapshot per process per query (pipeline + checklist reads)
            self._cache[key] = self._page_all(params)
        return self._cache[key][int(offset): int(offset) + int(limit)]

    def get(self, item_id: str) -> dict | None:
        return _get_item(item_id)


def read_source() -> str:
    """``auto`` resolves to ``export`` under pytest (never the live API from a test), else ``api``."""
    src = (os.environ.get(SOURCE_ENV) or "auto").strip().lower()
    if src not in ("auto", "api", "export"):
        raise WorkReadError(f"{SOURCE_ENV}={src!r}: expected auto | api | export")
    if src == "auto":
        src = "export" if os.environ.get("PYTEST_CURRENT_TEST") else "api"
    return src


def _store_for_read(repo: Path, rel: Path, base: Path):
    """The store a read of ``base`` must come from, or None to read the files.

    Records what was read in ``LAST_READ`` under "checklist" / "pipeline"."""
    if not is_canonical(base, rel) or not frozen(repo):
        return None
    name = "pipeline" if Path(rel) == PIPELINE_STORE else "checklist"
    ws = local_store()
    if ws is not None:
        LAST_READ[name] = {"source": "work_store_db", "read_state": "read"}
        return ws
    if read_source() == "export":
        LAST_READ[name] = {"source": "export", "read_state": "export_frozen",
                           "export_newest": _export_newest(repo, Path(rel)),
                           "note": f"the frozen export, not the live register ({SOURCE_ENV}=export or pytest)"}
        return None
    LAST_READ[name] = {"source": "work_store_api", "read_state": "read"}
    return RemoteStore()


def read_state() -> dict:
    """``LAST_READ`` as a JSON-able block for a CLI's output (empty: nothing canonical was read)."""
    return {k: dict(v) for k, v in sorted(LAST_READ.items())}


# ── reads ───────────────────────────────────────────────────────────────────────────────


def checklist_rows(store) -> list[dict]:
    """Every build item as its checklist row (``_seq`` kept), in the checklist's own order."""
    from src.runtime import work_store_import as wi
    rows = [wi.to_row(i) for i in store.list_items(kind="build", limit=10 ** 7)]
    rows.sort(key=lambda r: (r.get(SEQ, 1 << 60), r["id"]))
    return rows


def pipeline_result(store):
    """A ``pipeline.LoadResult`` from the store: one folded record per observation item.

    ``sources`` maps id -> ``work_store:v<version>`` (the version token a writer passes back);
    ``due_now`` / ``due_now_builds`` carry the store's ``due_now`` view for brief section 0."""
    from scripts.ops import pipeline as pl
    from src.runtime import work_store_import as wi
    items = store.list_items(kind="observation", limit=10 ** 7)
    res = pl.LoadResult()
    for it in sorted(items, key=lambda i: i["id"]):
        rec = wi.to_pipeline_item(it)
        res.items[rec["id"]] = rec
        res.raw.append(rec)
        res.sources[rec["id"]] = f"work_store:v{it['version']}"
        if it.get("updated_at"):
            res.store_updated_at[rec["id"]] = it["updated_at"]
    res.records = len(res.raw)
    obs, builds = due_now_split(store)
    res.due_now = obs
    res.due_now_builds = builds
    return res


def due_now_split(store) -> tuple[list[str], list[str]]:
    """The ``due_now`` view's ids, split (observations, builds)."""
    obs, builds = [], []
    for it in store.list_items(due=True, limit=10 ** 7):
        (obs if it["kind"] == "observation" else builds).append(it["id"])
    return sorted(obs), sorted(builds)


# ── writes (and the single-item reads a write is based on) ──────────────────────────────


def _work_cli():
    # Backstop: a test must never read or write the LIVE register (the 2026-11-06 CI run showed a
    # monkeypatched store reaching the production API). Tests use a local WORK_STORE_DB, or point
    # WORK_STORE_URL at a fake explicitly.
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("WORK_STORE_URL"):
        raise WorkWriteError("refusing to reach the live work-store API from a test "
                             "(set WORK_STORE_DB to a local store, or WORK_STORE_URL to a fake)")
    root = str(REPO / "scripts" / "ops")
    if root not in sys.path:
        sys.path.insert(0, root)
    import work  # noqa: PLC0415 -- scripts/ops/work.py (stdlib only)
    return work


def _get_item(item_id: str) -> dict | None:
    store = local_store()
    if store is not None:
        return store.get(item_id)
    w = _work_cli()
    st, p, _ = w.http("GET", f"{w.API}/{item_id}")
    if st == 404:
        return None
    return w._ok(st, p, f"get {item_id}")["item"]


def get_row(row_id: str) -> dict | None:
    """The row as the store holds it (``_seq`` stripped), or None."""
    from src.runtime import work_store_import as wi
    it = _get_item(row_id)
    if it is None:
        return None
    if it.get("kind") != "build":
        raise WorkWriteError(f"{row_id!r} is a {it.get('kind')} item in the work store, not a checklist row")
    return {k: v for k, v in wi.to_row(it).items() if k != SEQ}


def get_observation(item_id: str) -> dict | None:
    from src.runtime import work_store_import as wi
    it = _get_item(item_id)
    if it is None or it.get("kind") != "observation":
        return None
    return wi.to_pipeline_item(it)


def observation_version(item_id: str) -> str | None:
    """The version token ``pipeline.version_of`` hands out after the freeze."""
    it = _get_item(item_id)
    return None if it is None else f"work_store:v{it['version']}"


def _by(rec: dict) -> str:
    return (rec.get("updated_by") or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("GITHUB_WORKFLOW_REF") or WRITER)


def _put(item: dict, by: str) -> dict:
    """Create the item, or set every writable field that differs, as ONE store write."""
    from src.runtime import work_store as ws
    fields = {k: item.get(k) for k in ws.WRITABLE_FIELDS}
    store = local_store()
    if store is not None:
        try:
            prior = store.get(item["id"])
            if prior is None:
                return store.create({**{k: v for k, v in fields.items() if v is not None},
                                     "id": item["id"], "kind": item["kind"]}, by=by)
            diff = {k: v for k, v in fields.items() if prior.get(k) != v}
            if not diff:
                return {"item": prior, "unchanged": True}
            return store.set(item["id"], diff, by=by, expected_version=prior["version"])
        except ws.WorkStoreError as exc:
            raise WorkWriteError(f"work store refused {item['id']!r}: {exc}") from None
    w = _work_cli()
    try:
        prior = _get_item(item["id"])
        if prior is None:
            body = {**{k: v for k, v in fields.items() if v is not None}, "id": item["id"], "kind": item["kind"]}
            return w.send(w.make_op("create", item["id"], body, by, None), "auto", None)
        diff = {k: v for k, v in fields.items() if prior.get(k) != v}
        if not diff:
            return {"item": prior, "unchanged": True}
        return w.send(w.make_op("set", item["id"], {"fields": diff}, by, None), "auto", None)
    except w.WorkError as exc:
        raise WorkWriteError(f"work store refused {item['id']!r}: {exc}") from None


def put_row(row: dict) -> dict:
    """``checklist_store.write_row`` after the freeze: the row, mapped losslessly, into the store."""
    from src.runtime import work_store_import as wi
    row = dict(row)
    if SEQ not in row:
        prior = _get_item(row["id"])
        seq = ((prior or {}).get("extra") or {}).get(SEQ)
        if seq is None and prior is None:
            store = local_store()
            if store is not None:
                seq = max(((i.get("extra") or {}).get(SEQ, -1) for i in store.list_items(kind="build", limit=10 ** 7)),
                          default=-1) + 1
        if seq is not None:
            row[SEQ] = seq
    return _put(wi.from_row(row), _by(row))


def put_observation(rec: dict) -> dict:
    """``pipeline.append`` after the freeze: the record becomes the item's new state (one event)."""
    from src.runtime import work_store_import as wi

    def owner_of(r: dict) -> tuple[str, str]:
        # pipeline.owner_of's own parse, against the store instead of a loaded row dict.
        from scripts.ops import pipeline as pl
        text = str(r.get("routed_to") or "")
        m = pl._OWNER_TOKEN.match(re.sub(r"^checklist(?:\s+row\s+|\s*:\s*)", "", text.strip()))
        tok = m.group(0) if m else ""
        parent = _get_item(tok) if tok else None
        return ("row", tok) if parent is not None and parent.get("kind") == "build" else ("unresolved", text)

    kind, ref = owner_of(rec) if rec.get("state") == "routed" else ("", "")
    item = wi.from_pipeline_item(rec, {ref} if kind == "row" else set(), lambda r: (kind, ref))
    return _put(item, _by(rec))

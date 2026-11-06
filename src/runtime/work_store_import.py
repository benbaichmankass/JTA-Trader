"""S2: import the checklist rows + pipeline items into the work store, and prove parity.

Design: ``docs/plans/WORK-STORE-DESIGN-2026-11.md`` § 4 steps 1-2 (row ``WSD-S2-IMPORTER-PARITY``).

* **One-way, files -> store.** The checklist row files and the pipeline store stay canonical
  during the shadow. The importer never writes a file and never deletes an item; nothing is
  closed by the import ("no bulk drop": every open item arrives open, a closed one keeps its
  reason).
* **Lossless.** A source field the merged model has a column for goes into that column when
  its value fits the column; every other field -- and any value that does not fit -- is kept
  verbatim in ``items.extra``. ``to_row`` / ``to_pipeline_item`` project a store item back to
  the source vocabulary, and parity compares that projection with the file record byte for
  byte (canonical JSON). The same projection is what S4 will serve ``/work/checklist`` from.
* **Events.** Each pipeline record file becomes one ``migrate`` event (op_id
  ``import:pipeline:<record file>``, so a re-run is a no-op). A checklist row's first import is
  one ``migrate`` event carrying the whole row; each later change is one event with what
  changed (an appended note is recorded as the appended text only).
* **Parity** (``parity``): file record vs projected store item for every id, the Appendix A
  counts computed by the SAME function over both sources, and the hash chain. The design's
  closing observation is a parity report with 0 differences over 2 days.

``extra`` keys starting ``_`` are this module's bookkeeping, never source fields:
``_source`` (checklist | pipeline), ``_absent`` (mapped keys the source did not carry),
``_int`` (int values stored in a REAL column), ``_legacy_state`` (the pipeline's own state word).
"""
from __future__ import annotations

import collections
import hashlib
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.runtime import work_store as ws

IMPORTER = "work-store-importer"

_NUM = (int, float)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _opt(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda v: v is None or check(v)


_NONEMPTY_STR = lambda v: isinstance(v, str) and bool(v.strip())  # noqa: E731
_STR_LIST = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)  # noqa: E731
_REAL = lambda v: isinstance(v, _NUM) and not isinstance(v, bool)  # noqa: E731

#: checklist row key -> (item column, does the value fit the column?)
ROW_MAP: dict[str, tuple[str, Callable[[Any], bool]]] = {
    "title": ("title", _NONEMPTY_STR),
    "state": ("state", lambda v: v in ws.ITEM_STATES),
    "owner": ("owner", _NONEMPTY_STR),
    "lane": ("lane", _opt(lambda v: isinstance(v, str))),
    "model": ("model", _opt(lambda v: isinstance(v, str))),
    "tier": ("tier", _opt(_is_int)),
    "roadmap": ("roadmap", _STR_LIST),
    "roadmap_unmapped_reason": ("roadmap_unmapped_reason", _opt(lambda v: isinstance(v, str))),
    "priority_rank": ("priority_rank", _opt(_is_int)),
    "ceiling_usd": ("ceiling_usd", _opt(_REAL)),
    "spend_usd": ("spend_usd", _opt(_REAL)),
    "prs": ("prs", _opt(lambda v: isinstance(v, list))),
    "blocked_on": ("blocked_on", _opt(lambda v: isinstance(v, list))),
    "next_action": ("next_action", _opt(lambda v: v in ws.NEXT_ACTIONS)),
    "due_by": ("due_rule", lambda v: isinstance(v, str)),
}

#: pipeline item key -> (item column, fits?)
PIPE_MAP: dict[str, tuple[str, Callable[[Any], bool]]] = {
    "what": ("title", _NONEMPTY_STR),
    "origin": ("origin", _opt(lambda v: isinstance(v, dict))),
    "due_when": ("due_rule", lambda v: isinstance(v, dict)),
    "next_action": ("next_action", _opt(lambda v: v in ws.NEXT_ACTIONS)),
    "terminal_reason": ("terminal_reason", _opt(lambda v: isinstance(v, str))),
    "owner": ("owner", _NONEMPTY_STR),
    "tier": ("tier", _opt(_is_int)),
    "severity": ("severity", _opt(lambda v: isinstance(v, str))),
    "roadmap": ("roadmap", _STR_LIST),
}

PIPE_STATE = {"queued": "queued", "due": "queued", "routed": "queued", "done": "done", "killed": "dropped"}
_REAL_COLS = ("ceiling_usd", "spend_usd")


def _sha12(obj: Any) -> str:
    return hashlib.sha256(ws.canonical_json(obj).encode("utf-8")).hexdigest()[:12]


def _map(rec: dict, mapping: dict, source: str, skip: tuple[str, ...]) -> tuple[dict, dict]:
    """-> (columns, extra). A key goes to its column only if its value fits."""
    cols: dict[str, Any] = {}
    extra: dict[str, Any] = {"_source": source}
    absent = [k for k in mapping if k not in rec]
    ints = []
    for k, v in rec.items():
        if k in skip:
            continue
        m = mapping.get(k)
        if m is None or not m[1](v):
            extra[k] = v
            continue
        col = m[0]
        if col == "due_rule" and source == "checklist":
            v = {"kind": "date", "due_date": v}
        if col in _REAL_COLS and _is_int(v):
            ints.append(k)
        cols[col] = v
    if absent:
        extra["_absent"] = absent
    if ints:
        extra["_int"] = ints
    return cols, extra


def from_row(row: dict) -> dict:
    """A checklist row -> a ``build`` item (columns + lossless ``extra``)."""
    cols, extra = _map(row, ROW_MAP, "checklist", skip=("id",))
    item = {"id": row["id"], "kind": "build", **cols, "extra": extra}
    if item.get("state") in ws.TERMINAL and isinstance(row.get("note"), str):
        # design § 4: a closed build's terminal_reason is the row's note (derived, never
        # projected back -- the row has no such key).
        item["terminal_reason"] = row["note"]
    return item


def from_pipeline_item(rec: dict, row_ids: set[str], owner_of: Callable[[dict], tuple[str, str]]) -> dict:
    """A folded pipeline item -> an ``observation`` item. ``routed`` + a resolvable row ->
    ``queued`` with ``parent_id`` (design § 2.2); the pipeline's own state word is kept."""
    cols, extra = _map(rec, PIPE_MAP, "pipeline", skip=("id", "state"))
    st = rec.get("state")
    extra["_legacy_state"] = st
    item = {"id": rec["id"], "kind": "observation", **cols, "extra": extra,
            "state": PIPE_STATE.get(st, st)}
    if st == "routed":
        kind, ref = owner_of(rec)
        if kind == "row" and ref in row_ids:
            item["parent_id"] = ref
    return item


def _project(item: dict, mapping: dict, source: str) -> dict:
    extra = dict(item.get("extra") or {})
    absent = set(extra.pop("_absent", []) or [])
    ints = set(extra.pop("_int", []) or [])
    extra.pop("_source", None)
    legacy = extra.pop("_legacy_state", None)
    out: dict[str, Any] = {"id": item["id"]}
    for k, (col, _fits) in mapping.items():
        if k in absent or k in extra:
            continue
        v = item.get(col)
        if col == "due_rule" and source == "checklist":
            v = (v or {}).get("due_date")
        if k in ints and isinstance(v, float) and v.is_integer():
            v = int(v)
        out[k] = v
    if source == "pipeline":
        st = item.get("state")
        if legacy is not None and PIPE_STATE.get(legacy, legacy) == st:
            out["state"] = legacy
        elif st == "dropped":
            out["state"] = "killed"
        elif st == "queued" and item.get("parent_id"):
            out["state"] = "routed"
        else:
            out["state"] = st
    out.update(extra)
    return out


def to_row(item: dict) -> dict:
    """A ``build`` item -> the checklist row it was imported from (S4 serves this)."""
    return _project(item, ROW_MAP, "checklist")


def to_pipeline_item(item: dict) -> dict:
    return _project(item, PIPE_MAP, "pipeline")


def _same(a: dict, b: dict) -> bool:
    return ws.canonical_json(a) == ws.canonical_json(b)


def _diff_keys(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b)
                  if ws.canonical_json(a.get(k, "\x00absent")) != ws.canonical_json(b.get(k, "\x00absent")))


# ── reading the canonical files ─────────────────────────────────────────────────────────


def read_sources(repo: Path) -> dict:
    """The two canonical stores, read exactly as their own loaders read them."""
    from scripts.ops import pipeline as pl
    from src.runtime import checklist_store as cs
    import json as _json
    _json.loads((repo / cs.STORE / cs.HEADER).read_text(encoding="utf-8"))  # header present -- raises if not
    # Rows WITH their ``_seq`` (the store's ordering key, which ``load`` strips for serving): the
    # importer keeps it so the store can serve the rows in the checklist's own order. FILES only
    # (``_read_rows`` checks id == filename): after the S4 freeze ``load`` reads the store itself.
    rows = cs._read_rows(repo / cs.STORE)
    res = pl.read_files(repo / pl.STORE)
    return {"rows": rows, "pipeline": res, "cs": cs, "pl": pl}


def _pipeline_record_names(repo: Path, res, pl) -> list[str]:
    """The record filename of each entry of ``res.raw``: ``read_log`` reads the directory in
    sorted-filename order and skips (and names) the unreadable files, so the same walk pairs them."""
    bad = {loc for loc, _why in res.unreadable}
    names = [p.name for p in sorted((repo / pl.STORE).glob(f"*{pl.RECORD_SUFFIX}")) if p.name not in bad]
    if len(names) != len(res.raw):
        raise ValueError(f"pipeline store changed under the importer ({len(names)} files vs {len(res.raw)} records)")
    return names


def native_since_import(prior: dict | None) -> bool:
    """WSD-S4 FREEZE: the item was last written by someone other than this importer (a session
    through ``work.py`` / the ``checklist.py`` / ``pipeline.py`` shims, or the API). The store is
    then the truth for it and the frozen file is stale: the importer must never write it back.
    The importer still imports what is NOT native -- a row or record that reached the files after
    the freeze (a stale branch merged) -- so nothing is silently lost at the cutover."""
    return prior is not None and prior.get("updated_by") != IMPORTER


def build_entries(repo: Path, src: dict, store: ws.WorkStore) -> list[dict]:
    """The migrate entries for every row and item (builds first, so parents exist)."""
    rows, res, pl = src["rows"], src["pipeline"], src["pl"]
    R = {r["id"]: r for r in rows}
    current = {i["id"]: i for i in store.list_items(limit=10 ** 7)}
    entries: list[dict] = []
    for row in rows:
        item = from_row(row)
        prior = current.get(row["id"])
        if native_since_import(prior):
            continue
        imported = prior is not None and (prior.get("extra") or {}).get("_source") == "checklist"
        if not imported:
            patch: dict = {"source": "checklist", "record": row}
        else:
            old = to_row(prior)
            if _same(old, row):
                entries.append({"item": item, "events": []})
                continue
            patch = {"source": "checklist",
                     "changed": {k: row[k] for k in row if ws.canonical_json(row[k]) != ws.canonical_json(old.get(k, "\x00"))}}
            removed = sorted(k for k in old if k not in row)
            if removed:
                patch["removed"] = removed
            on, nn = old.get("note"), row.get("note")
            if isinstance(on, str) and isinstance(nn, str) and nn != on and nn.startswith(on):
                patch["changed"].pop("note", None)
                patch["note_append"] = nn[len(on):]
        ver = (prior or {}).get("version", 0) + 1
        entries.append({"item": item, "events": [
            {"op_id": f"import:checklist:{row['id']}:v{ver}:{_sha12(row)}", "patch": patch}]})
    by_id: dict[str, list] = collections.defaultdict(list)
    for rec, name in zip(res.raw, _pipeline_record_names(repo, res, pl)):
        by_id[rec["id"]].append((name, rec))
    row_ids = set(R)
    for iid, rec in res.items.items():
        if native_since_import(current.get(iid)):
            continue
        item = from_pipeline_item(rec, row_ids, lambda r: pl.owner_of(r, R))
        evs = [{"op_id": f"import:pipeline:{name}",
                "patch": {"source": "pipeline", "record_file": name, "record": r}}
               for name, r in by_id.get(iid, [])]
        entries.append({"item": item, "events": evs})
    return entries


def run_import(repo: Path, store: ws.WorkStore, src: dict | None = None) -> dict:
    t0 = time.monotonic()
    src = src or read_sources(repo)
    out = store.migrate(build_entries(repo, src, store), by=IMPORTER)
    out["duration_s"] = round(time.monotonic() - t0, 2)
    return out


# ── parity ──────────────────────────────────────────────────────────────────────────────


def appendix_a(rows: list[dict], items: dict[str, dict], cs, pl, today: date, soak_states=None) -> dict:
    """The design's Appendix A counts, as one dict (the same code over either source)."""
    R = {r["id"]: r for r in rows}
    op = [r for r in rows if r["state"] not in cs.TERMINAL]
    und = [r for r in op if not cs._as_date(r.get("due_by"))]
    b: collections.Counter = collections.Counter()
    for i in (i for i in items.values() if i["state"] in pl.OPEN_STATES):
        if i["state"] == "routed":
            k, ref = pl.owner_of(i, R)
            b[("routed->live row" if R[ref]["state"] not in cs.TERMINAL else "routed->CLOSED row")
              if k == "row" else "routed->" + k] += 1
        else:
            b["queued, due" if pl.is_due(i, today, soak_states) else "queued, not due"] += 1
    return {
        "rows": len(rows), "row_states": dict(sorted(collections.Counter(r["state"] for r in rows).items())),
        "open": len(op), "undated": len(und),
        "undated_states": dict(sorted(collections.Counter(r["state"] for r in und).items())),
        "id_collisions": len(set(R) & set(items)),
        "items": len(items),
        "item_states": dict(sorted(collections.Counter(i["state"] for i in items.values()).items())),
        "open_buckets": dict(sorted(b.items())),
    }


def parity(repo: Path, store: ws.WorkStore, src: dict | None = None, today: date | None = None,
           max_listed: int = 50) -> dict:
    """Compare every file record with its projected store item; Appendix A over both sources."""
    src = src or read_sources(repo)
    cs, pl, rows, res = src["cs"], src["pl"], src["rows"], src["pipeline"]
    today = today or datetime.now(timezone.utc).date()
    soak = pl.load_soak_states(repo / pl.SOAK_STATE)
    db = store.list_items(limit=10 ** 7)
    by_src: dict[str, dict[str, dict]] = {"checklist": {}, "pipeline": {}}
    native = []
    for it in db:
        s = (it.get("extra") or {}).get("_source")
        if s in by_src:
            by_src[s][it["id"]] = it
        else:
            native.append(it["id"])

    def compare(files: dict[str, dict], dbs: dict[str, dict], proj) -> dict:
        differing, missing, native_div = [], sorted(set(files) - set(dbs)), []
        projected = {}
        for iid, rec in files.items():
            it = dbs.get(iid)
            if it is None:
                continue
            p = proj(it)
            projected[iid] = p
            if not _same(rec, p):
                # After the S4 freeze a natively-written item is EXPECTED to differ from its frozen
                # file: the store is the truth for it. Counted, never folded into ``differing``.
                (native_div if native_since_import(it) else differing).append(
                    {"id": iid, "keys": _diff_keys(rec, p)})
        db_only = sorted(i for i in set(dbs) - set(files) if not native_since_import(dbs[i]))
        native_new = sorted(i for i in set(dbs) - set(files) if native_since_import(dbs[i]))
        return {"files": len(files), "db": len(dbs),
                "equal": len(files) - len(missing) - len(differing) - len(native_div),
                "differing_count": len(differing), "differing": differing[:max_listed],
                "native_divergent_count": len(native_div), "native_divergent": native_div[:max_listed],
                "missing_in_db_count": len(missing), "missing_in_db": missing[:max_listed],
                "db_only_count": len(db_only), "db_only": db_only[:max_listed],
                "native_new_count": len(native_new), "native_new": native_new[:max_listed],
                "_projected": projected}

    rows_cmp = compare({r["id"]: r for r in rows}, by_src["checklist"], to_row)
    items_cmp = compare(dict(res.items), by_src["pipeline"], to_pipeline_item)
    proj_rows = [rows_cmp["_projected"][r["id"]] for r in rows if r["id"] in rows_cmp["_projected"]]
    proj_items = {k: items_cmp["_projected"][k] for k in res.items if k in items_cmp["_projected"]}
    rows_cmp.pop("_projected")
    items_cmp.pop("_projected")
    # After the S4 freeze the store legitimately moves ahead of the frozen files; the Appendix A
    # counts then differ by exactly those native writes, so they no longer gate ``clean``.
    frozen_native = any(c.get(k) for c in (rows_cmp, items_cmp)
                        for k in ("native_divergent_count", "native_new_count"))
    a_files = appendix_a(rows, dict(res.items), cs, pl, today, soak)
    a_db = appendix_a(proj_rows, proj_items, cs, pl, today, soak)
    chain = store.verify_chain()
    clean = (rows_cmp["differing_count"] == 0 and rows_cmp["missing_in_db_count"] == 0
             and rows_cmp["db_only_count"] == 0 and items_cmp["differing_count"] == 0
             and items_cmp["missing_in_db_count"] == 0 and items_cmp["db_only_count"] == 0
             and (a_files == a_db or frozen_native) and chain.get("ok") and not res.unreadable)
    return {
        "rows": rows_cmp, "items": items_cmp,
        "appendix_a": {"files": a_files, "db": a_db, "equal": a_files == a_db},
        "pipeline_unreadable": len(res.unreadable), "pipeline_collisions": len(res.collisions),
        "native_db_only": native, "chain": chain, "clean": bool(clean),
    }

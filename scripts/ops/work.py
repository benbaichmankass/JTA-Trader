#!/usr/bin/env python3
"""work.py -- the work store's write CLI (WSD-S3-CLI-OUTBOX; design § 2.3).

A thin HTTPS client over ``/api/bot/work/items`` on the live VM. Stdlib only.

    work.py get   <id>                              # the item + its version
    work.py history <id>                            # its events + the chain check (replaces git log -p)
    work.py list  [--state S] [--due] [--parent P] [--kind K] [--limit N]
    work.py add   <id> --kind build|observation --title T [--field k=v ...]
    work.py set   <id> k=v [k=v ...]                # JSON values parsed (state=done, tier=2, prs=[1,2]);
                                                    # owner=/parent_id= on an observation also ROUTES it (route_fields)
    work.py note  <id> "text" [--summary S]
    work.py close <id> --reason R [--state done|dropped]
    work.py reopen <id> [--state queued]            # set state, clear terminal_reason
    work.py observe <id> "what was seen"            # observation: due_rule.last_checked = today, then a note
    work.py drain --issue N                         # (runner) apply the outbox issue's pending ops
    work.py export --to-files [--root DIR] [--db PATH] [--unfreeze] [--no-precheck] [--no-file] [--run-ref R]
                                                    # the export / ROLLBACK path (WSD-S4); pre-check: AM-OPS-9

Every write carries an ``op_id`` (``--op-id`` or a fresh uuid) -- a retried write is a no-op on the
server -- and, after create, ``If-Match: <version>`` read from the item; a 409 (someone wrote in
between) is re-read and re-applied ONCE by the CLI itself (design G3).

TRANSPORT (``--via``):
  * ``direct`` -- POST to the API. Auth: ``X-Work-Store-Token: $WORK_STORE_TOKEN`` when that env is
    set (GitHub runners); otherwise no auth header at all, because a cloud session's environment
    proxy injects the saved network secret for the host (design D3) -- a session never holds it.
  * ``outbox`` -- print the op as an outbox comment for the one fixed issue titled
    ``work-store outbox``; the session posts it (GitHub MCP ``add_issue_comment``) and
    ``.github/workflows/work-store-outbox.yml`` drains it into the API, idempotent by op_id. With
    ``GITHUB_TOKEN`` + ``--issue`` set (a runner) the CLI posts the comment itself.
  * ``auto`` (default) -- direct; if the VM cannot be REACHED (network error, or a proxy/gateway
    502/504), fall back to outbox. A refusal from the API itself (4xx, 503 not-configured) is
    never re-routed: it is the answer.
The CLI always prints which path carried the write (``"via": ...``).

THE FREEZE (WSD-S4, design § 4 steps 2-3): once ``docs/claude/work/checklist/_header.json`` carries
``frozen_into_work_store``, ``checklist.py`` and ``pipeline.py`` write THROUGH this module
(``src/runtime/work_read.py``: ``checklist_store.write_row`` / ``pipeline.append`` -> create/set here),
and the row / record files become the EXPORT.

EXPORT (``export --to-files``) is the rollback path and the CI export (design § 7, D5): it rewrites
every checklist row file whose content differs from the store's projection and appends ONE pipeline
record per observation whose folded file state differs -- after it, ``checklist_store.load`` and
``pipeline.read_files`` over the files equal the store. ``--db`` reads a local ``work_store.db`` (the
VM); without it the items are paged from ``GET /api/bot/work/items``. ``--unfreeze`` also removes the
freeze key, so the files are canonical again: export --unfreeze, commit, then revert S4.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:  # export imports the store's projection (src.runtime.*)
    sys.path.insert(1, _REPO)

DEFAULT_BASE = "https://ict-bot.duckdns.org"
API = "/api/bot/work/items"
HEADER = "X-Work-Store-Token"
OUTBOX_TITLE = "work-store outbox"
OUTBOX_MARK = "<!-- work-store-op v1 -->"
#: Statuses that mean "we did not reach the store" -- re-routable to the outbox.
UNREACHED = (502, 504)
_OP_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


class WorkError(Exception):
    def __init__(self, msg: str, status: int | None = None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


class Unreachable(WorkError):
    pass


def _base() -> str:
    return os.environ.get("WORK_STORE_URL", DEFAULT_BASE).rstrip("/")


def _by(a) -> str:
    by = a.by or os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("GITHUB_WORKFLOW_REF")
    if not by:
        raise WorkError("--by is required (who is writing: a session id or workflow)")
    return by


def http(method: str, path: str, body: dict | None = None, *, if_match: int | None = None,
         timeout: float = 20.0) -> tuple[int, dict, dict]:
    """-> (status, json, headers). Raises Unreachable when the store was not reached."""
    headers = {"Accept": "application/json", "User-Agent": "jta-work-cli/1"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = os.environ.get("WORK_STORE_TOKEN", "").strip()
    if token and method != "GET":
        headers[HEADER] = token
    if if_match is not None:
        headers["If-Match"] = str(if_match)
    req = urllib.request.Request(_base() + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {"detail": raw.decode("utf-8", "replace")[:500]}
        if e.code in UNREACHED:
            raise Unreachable(f"store not reached: HTTP {e.code}", e.code, payload) from None
        return e.code, payload, dict(e.headers)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unreachable(f"store not reached: {e}") from None


def _ok(status: int, payload: dict, what: str) -> dict:
    if status not in (200, 201):
        raise WorkError(f"{what}: HTTP {status}: {payload.get('detail', payload)}", status, payload)
    return payload


def get_item(item_id: str) -> dict:
    st, p, _ = http("GET", f"{API}/{urllib.parse.quote(item_id)}")
    return _ok(st, p, f"get {item_id}")["item"]


# ── ops: one dict shape for both transports ─────────────────────────────────────────────
#   {"op": create|set|note|close, "id", "body": {...route body without by/op_id...},
#    "by", "op_id"}   (set/note/close re-read the version at apply time)


def make_op(op: str, item_id: str, body: dict, by: str, op_id: str | None) -> dict:
    return {"op": op, "id": item_id, "body": body, "by": by, "op_id": op_id or f"cli-{uuid.uuid4().hex}"}


META_API = "/api/bot/work/meta"


def apply_direct(o: dict) -> dict:
    """Apply one op through the API; a 409 is re-read and re-applied once."""
    body = {**o["body"], "by": o["by"], "op_id": o["op_id"]}
    if o["op"] == "meta":  # a register-header key: last-writer-wins, no version
        st, p, _ = http("POST", f"{META_API}/{urllib.parse.quote(o['id'])}", body)
        return _ok(st, p, f"meta {o['id']}")
    if o["op"] == "create":
        st, p, _ = http("POST", API, body)
        return _ok(st, p, f"create {o['id']}")
    route = f"{API}/{urllib.parse.quote(o['id'])}/{o['op']}"
    for attempt in (1, 2):
        version = get_item(o["id"])["version"]
        st, p, _ = http("POST", route, body, if_match=version)
        if st == 409 and attempt == 1:
            continue
        return _ok(st, p, f"{o['op']} {o['id']}")
    raise AssertionError("unreachable")


def outbox_comment(o: dict) -> str:
    return (f"{OUTBOX_MARK}\n`{o['op']}` **{o['id']}** by `{o['by']}` (op_id `{o['op_id']}`)\n\n"
            f"```json\n{json.dumps(o, sort_keys=True, indent=1)}\n```\n")


def parse_outbox_comment(text: str) -> dict | None:
    if OUTBOX_MARK not in (text or ""):
        return None
    m = _OP_RE.search(text)
    if not m:
        return None
    o = json.loads(m.group(1))
    if not (isinstance(o, dict) and o.get("op") in ("create", "set", "note", "close", "meta")
            and isinstance(o.get("id"), str) and isinstance(o.get("body"), dict)
            and isinstance(o.get("by"), str) and isinstance(o.get("op_id"), str)):
        raise WorkError("outbox op is malformed (needs op, id, body, by, op_id)")
    return o


def _gh(method: str, url: str, body: dict | None = None):
    token = os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "jta-work-cli/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def _repo_api() -> str:
    return f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}"


def post_outbox(o: dict, issue: int | None) -> dict:
    text = outbox_comment(o)
    if issue and os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        c = _gh("POST", f"{_repo_api()}/issues/{issue}/comments", {"body": text})
        return {"via": "outbox", "posted": True, "comment": c.get("html_url"), "op_id": o["op_id"]}
    return {"via": "outbox", "posted": False, "op_id": o["op_id"],
            "action": f"post this body as a comment on the issue titled '{OUTBOX_TITLE}' "
                      "(GitHub MCP add_issue_comment); the outbox workflow applies it",
            "comment_body": text}


def send(o: dict, via: str, issue: int | None) -> dict:
    if via == "outbox":
        return post_outbox(o, issue)
    try:
        res = apply_direct(o)
    except Unreachable as exc:
        if via == "direct":
            raise
        out = post_outbox(o, issue)
        out["direct_error"] = str(exc)
        return out
    return {"via": "direct", "op_id": o["op_id"], "replayed": res.get("replayed", False),
            "item": res.get("item"), "meta": res.get("meta"), "event_seq": (res.get("event") or {}).get("seq")}


# ── the drainer (runner side) ───────────────────────────────────────────────────────────

TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
DONE_REACTION = "rocket"


def drain(issue: int) -> dict:
    """Apply every unprocessed outbox comment on ``issue``. Only comments by trusted authors
    (author_association OWNER/MEMBER/COLLABORATOR) are applied -- the outbox must not become an
    unauthenticated write path (design G2). A processed comment gets a rocket reaction; a refused
    one gets a reply saying why. op_id makes a re-run harmless either way."""
    api = _repo_api()
    out = {"applied": [], "refused": [], "skipped_untrusted": 0, "already_done": 0}
    page = 1
    while True:
        comments = _gh("GET", f"{api}/issues/{issue}/comments?per_page=100&page={page}") or []
        for c in comments:
            try:
                o = parse_outbox_comment(c.get("body", ""))
            except (WorkError, ValueError) as exc:
                o, bad = None, str(exc)
                if c.get("author_association") in TRUSTED and not _processed(api, c):
                    _reply(api, issue, c, f"refused: {bad}")
                    out["refused"].append({"comment": c["id"], "error": bad})
                continue
            if o is None:
                continue
            if c.get("author_association") not in TRUSTED:
                out["skipped_untrusted"] += 1
                continue
            if _processed(api, c):
                out["already_done"] += 1
                continue
            try:
                res = apply_direct(o)
                _gh("POST", f"{api}/issues/comments/{c['id']}/reactions", {"content": DONE_REACTION})
                out["applied"].append({"op_id": o["op_id"], "id": o["id"], "replayed": res.get("replayed", False)})
            except Unreachable as exc:
                out.setdefault("unreached", []).append({"op_id": o["op_id"], "error": str(exc)})
            except WorkError as exc:
                _reply(api, issue, c, f"refused by the store (op_id `{o['op_id']}`): {exc}")
                _gh("POST", f"{api}/issues/comments/{c['id']}/reactions", {"content": "confused"})
                out["refused"].append({"op_id": o["op_id"], "error": str(exc)})
        if len(comments) < 100:
            return out
        page += 1


def _processed(api: str, c: dict) -> bool:
    if not (c.get("reactions") or {}).get("total_count"):
        return False
    rs = _gh("GET", f"{api}/issues/comments/{c['id']}/reactions?per_page=100") or []
    return any(r.get("content") in (DONE_REACTION, "confused") and (r.get("user") or {}).get("type") == "Bot"
               for r in rs)


def _reply(api: str, issue: int, c: dict, text: str) -> None:
    _gh("POST", f"{api}/issues/{issue}/comments",
        {"body": f"Re {c.get('html_url')}: {text}\n\n---\n_work-store outbox drainer_"})


# ── export: the rollback path (WSD-S4) ──────────────────────────────────────────────────


def _all_items(db: str | None) -> list[dict]:
    if db:
        from src.runtime.work_store import WorkStore
        return WorkStore(db).list_items(limit=10 ** 7)
    out, offset, page = [], 0, 1000
    while True:
        st, p, _ = http("GET", f"{API}?{urllib.parse.urlencode({'limit': page, 'offset': offset})}")
        batch = _ok(st, p, "list")["items"]
        out += batch
        if len(batch) < page:
            break
        offset += page
    if len({i["id"] for i in out}) != len(out):
        raise WorkError("the store changed while paging (duplicate ids); re-run, or use --db on the VM")
    return out


#: The register-header keys the store holds (mirrors checklist_store.STORE_HEADER_KEYS).
HEADER_META_KEYS = ("last_review",)


def _header_meta(db: str | None) -> dict:
    out = {}
    for k in HEADER_META_KEYS:
        if db:
            from src.runtime.work_store import WorkStore
            m = WorkStore(db).meta_get(k)
        else:
            st, p, _ = http("GET", f"{META_API}/{urllib.parse.quote(k)}")
            m = None if st == 404 else _ok(st, p, f"header get {k}")["meta"]
        if m is not None:
            out[k] = m["value"]
    return out


# ── export pre-check (AM-OPS-9): the guards' own row checks, run BEFORE a file is written ──
#
# Gates this adds or changes: none added; narrows roadmap-map, soak-contract and claim-basis to skip
# rows whose store updated_at <= export_base_at (pre-cutover debt, tracked on STORE-EXPORT-BACKFILL-258).
#
# A changed row/record that fails roadmap-map (roadmap_map.row_problems), soak-contract
# (check_soak_contracts.row_findings / pipeline_item_findings) or claim-basis
# (check_claim_basis.new_row_failure) stays in the store, is LEFT OUT of this export, and is filed ONCE
# as an observation titled ``EXPORT HELD BACK [<id>] ...`` (no second filing while one is open). The next
# export re-checks it. A row/record whose store updated_at <= export_base_at (_header.json) lands anyway.

HOLD_PREFIX = "EXPORT HELD BACK "
HOLD_BY = "work-export"


def hold_title(item_id: str) -> str:
    """The stable title prefix that keys the one open filing per held-back row/record."""
    return f"{HOLD_PREFIX}[{item_id}]"


def precheck_context(root) -> dict:
    """What the three guards read, from ``root`` (falling back to this repo's copy when ``root``
    lacks a file): the milestones spec, the soak contract ids, and ``export_base_at``."""
    from pathlib import Path
    from scripts import check_claim_basis as cb
    from scripts.ci import check_soak_contracts as sc
    from scripts.ops import roadmap_map as rm
    from scripts.ops import work_export_cutover as cut
    ss = sc.ss  # the soak guard's own soak_state module (its contract loader)
    root = Path(root)
    ms = root / rm.MILESTONES.relative_to(rm.REPO)
    soaks = root / ss.CONTRACTS.relative_to(ss.REPO)
    return {"spec": rm.load_spec(ms if ms.is_file() else rm.MILESTONES),
            "ids": {c.get("id") for c in ss.load_contracts(soaks if soaks.is_file() else ss.CONTRACTS)},
            "base_at": cut.base_at(root), "rm": rm, "sc": sc, "cb": cb}


def export_precheck(kind: str, item_id: str, new: dict, old: dict | None, name: str, ctx: dict) -> list[str]:
    """The guard messages for ONE changed row (``kind`` build) or ONE new pipeline record, through the
    guards' own predicates. ``old`` is the file's current content (None = not in the files yet)."""
    rm, sc, cb = ctx["rm"], ctx["sc"], ctx["cb"]
    if kind == "build":
        msgs = rm.row_problems(ctx["spec"], item_id, new, old, new.get("_seq", 0))
        msgs += sc.row_findings(new, old.get("state") if old is not None else None, ctx["ids"])
        path = cb.BACKLOGS[0]
    else:
        msgs = list(sc.pipeline_item_findings(new, name, ctx["ids"],
                                              lambda: old.get("next_action") if old is not None else None))
        path = cb.PIPELINE_DIR
    if old is None:  # claim-basis grades NEW ids only
        f = cb.new_row_failure(item_id, new, path)
        if f:
            msgs.append(f)
    return msgs


def export_to_files(root, items: list[dict], *, unfreeze: bool = False, header_meta: dict | None = None,
                    precheck: bool = True) -> dict:
    """Write the store's items into the file layout under ``root``; only what differs is written.
    With ``precheck`` (the default) a changed row/record failing a guard's row check is held back
    (``held``), unless its store updated_at <= export_base_at. ``precheck=False`` (``--no-precheck``)
    is the byte-exact rollback: every differing item is written."""
    from pathlib import Path
    from scripts.ops import pipeline as pl
    from scripts.ops import work_export_cutover as cut
    from src.runtime import checklist_store as cs
    from src.runtime import work_read
    from src.runtime import work_store_import as wi
    root = Path(root)
    cdir, pdir = root / cs.STORE, root / pl.STORE
    cdir.mkdir(parents=True, exist_ok=True)
    out = {"rows_written": 0, "rows_unchanged": 0, "rows_held": 0,
           "records_written": 0, "records_unchanged": 0, "records_held": 0,
           "exempt_failing_landed": 0, "held": []}
    have = pl.read_files(pdir).items if pdir.exists() else {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    ctx = precheck_context(root) if precheck else None
    stamps: dict = {}

    def admit(kind: str, it: dict, new: dict, old: dict | None, name: str) -> bool:
        if ctx is None:
            return True
        msgs = export_precheck(kind, it["id"], new, old, name, ctx)
        if not msgs:
            return True
        if cut.is_pre_cutover(it.get("updated_at"), ctx["base_at"]):
            out["exempt_failing_landed"] += 1
            return True
        out["rows_held" if kind == "build" else "records_held"] += 1
        out["held"].append({"id": it["id"], "kind": it["kind"], "updated_at": it.get("updated_at"),
                            "messages": msgs})
        return False

    def write(path: Path, text: str, it: dict) -> None:
        data = text.encode("utf-8")
        path.write_bytes(data)
        stamps[path.relative_to(root).as_posix()] = {"updated_at": it.get("updated_at"), "sha256": cut.sha(data)}

    for it in sorted(items, key=lambda i: i["id"]):
        if it["kind"] == "build":
            row = wi.to_row(it)
            path = cdir / f"{row['id']}.json"
            old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            if old == row:
                out["rows_unchanged"] += 1
                continue
            if not admit("build", it, row, old, path.name):
                continue
            write(path, json.dumps(row, indent=2) + "\n", it)
            out["rows_written"] += 1
        else:
            rec = wi.to_pipeline_item(it)
            if have.get(rec["id"]) == rec:
                out["records_unchanged"] += 1
                continue
            name = f"{stamp}Z-export-{rec['id']}{pl.RECORD_SUFFIX}"
            if not admit("observation", it, rec, have.get(rec["id"]), (pl.STORE / name).as_posix()):
                continue
            pdir.mkdir(parents=True, exist_ok=True)
            write(pdir / name, json.dumps(rec, ensure_ascii=False, sort_keys=True, indent=2) + "\n", it)
            out["records_written"] += 1
    if stamps:  # the cutover's side file: store updated_at + sha of every file THIS export wrote
        sp = root / cut.STAMPS_REL
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({
            "_comment": "Written by scripts/ops/work.py export --to-files (AM-OPS-9). For each file the "
                        "last export wrote: the work store's updated_at and the sha256 of the bytes written. "
                        "The guards skip a file whose updated_at <= _header.json export_base_at and whose "
                        "bytes still match (scripts/ops/work_export_cutover.py). Never edit by hand.",
            "files": dict(sorted(stamps.items()))}, indent=2) + "\n", encoding="utf-8")
    hp = cdir / cs.HEADER
    if header_meta:  # store-backed header keys go back into _header.json (rollback fidelity)
        head = json.loads(hp.read_text(encoding="utf-8"))
        changed = {k: v for k, v in header_meta.items() if head.get(k) != v}
        if changed:
            head.update(changed)
            hp.write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8")
        out["header_keys_written"] = sorted(changed)
    if unfreeze:
        hp = cdir / cs.HEADER
        head = json.loads(hp.read_text(encoding="utf-8"))
        out["unfrozen"] = head.pop(work_read.FROZEN_KEY, None) is not None
        hp.write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8")
    return out


def file_holds(held: list[dict], items: list[dict], *, run_ref: str = "", today=None) -> dict:
    """File ONE observation per held-back row/record through the store API (the ``add`` op), unless
    an open observation titled ``hold_title(id)...`` already exists. Best-effort: a failed filing is
    printed and counted, never raised -- the export already happened."""
    from datetime import timedelta
    today = today or datetime.now(timezone.utc).date()
    due = (today + timedelta(days=2)).isoformat()
    open_titles = [str(i.get("title") or "") for i in items
                   if i.get("kind") == "observation" and i.get("state") not in ("done", "dropped")]
    out = {"filed": [], "skipped_open": [], "errors": []}
    for h in held:
        rid, prefix = h["id"], hold_title(h["id"])
        if any(t.startswith(prefix) for t in open_titles):
            out["skipped_open"].append(rid)
            continue
        what = (f"{prefix} held back from the work-store export of {today.isoformat()}: the store "
                f"{'row' if h.get('kind') == 'build' else 'pipeline record'} fails the guard row check -- "
                + " | ".join(h.get("messages") or []))
        oid = f"EXPORT-HOLD-{today.strftime('%Y%m%d')}-{rid}"
        body = {
            "id": oid, "kind": "observation", "title": what, "owner": "manager",
            "roadmap": ["unmapped"],
            "roadmap_unmapped_reason": "export hygiene: a store row the work-store export held back; the "
                                       "fix is on that row (pre-cutover debt is STORE-EXPORT-BACKFILL-258)",
            "due_rule": {"kind": "date", "due_date": due}, "next_action": "check_observation",
            "origin": {"kind": "audit", "by": HOLD_BY,
                       "ref": f"scripts/ops/work.py export --to-files {run_ref}".strip() + f"; held item {rid}",
                       "rerun": "python3 scripts/ops/work.py export --to-files  # re-checks every held "
                                "row; it lands once the guard row check passes"},
            # a one-shot definition of done, so this filing itself passes soak-contract on export
            "extra": {"observation": {"what": f"{rid} lands in the work-store export",
                                      "how_to_check": f"the next export's summary no longer lists {rid} as held",
                                      "due_by": due}},
        }
        try:
            res = apply_direct(make_op("create", oid, body, HOLD_BY, f"work-export:hold:{oid}"))
            out["filed"].append({"id": oid, "for": rid, "replayed": res.get("replayed", False)})
            open_titles.append(what)
        except Exception as exc:  # noqa: BLE001 -- best-effort: nothing here may abort the export
            print(f"work-export: filing for held {rid} FAILED (export not affected): {exc}", file=sys.stderr)
            out["errors"].append({"for": rid, "error": str(exc)})
    return out


VALIDATION_PREFIX = "EXPORT VALIDATION FAILED ["


def file_validation_failure(checks: list[str], log_tail: str, items: list[dict], *, run_ref: str = "",
                            today=None) -> dict:
    """The workflow's post-export validation (guards + tests on the exported tree) failed, so that run
    committed NOTHING. File ONE observation titled ``EXPORT VALIDATION FAILED [<date>] ...`` naming the
    failing checks and a log tail -- unless an open one with that prefix already exists (whatever its
    date). Best-effort like ``file_holds``: never raises."""
    from datetime import timedelta
    today = today or datetime.now(timezone.utc).date()
    if any(i.get("kind") == "observation" and i.get("state") not in ("done", "dropped")
           and str(i.get("title") or "").startswith(VALIDATION_PREFIX) for i in items):
        return {"filed": None, "skipped_open": True, "error": None}
    due = (today + timedelta(days=2)).isoformat()
    oid = f"EXPORT-VALIDATION-{today.strftime('%Y%m%d')}"
    tail = (log_tail or "").strip()[-2000:]
    what = (f"{VALIDATION_PREFIX}{today.isoformat()}] the work-store export was NOT landed: validation of "
            f"the exported tree failed from the work-store export of {today.isoformat()} -- failing: "
            f"{', '.join(checks) or 'unknown'}. Log tail: {tail}")
    body = {
        "id": oid, "kind": "observation", "title": what, "owner": "manager", "roadmap": ["unmapped"],
        "roadmap_unmapped_reason": "export hygiene: the daily work-store export failed its own validation "
                                   "and landed nothing; the fix is in the failing check or the store data",
        "due_rule": {"kind": "date", "due_date": due}, "next_action": "check_observation",
        "origin": {"kind": "audit", "by": HOLD_BY,
                   "ref": f".github/workflows/work-store-export.yml {run_ref}".strip(),
                   "rerun": "dispatch .github/workflows/work-store-export.yml (or run scripts/ops/work.py "
                            "export --to-files then the guards/tests it lists); it lands once validation passes"},
        "extra": {"observation": {"what": "a work-store-export run validates clean and lands its PR",
                                  "how_to_check": "the latest work-store-export run summary shows validation passed",
                                  "due_by": due}},
    }
    try:
        res = apply_direct(make_op("create", oid, body, HOLD_BY, f"work-export:validation:{oid}"))
        return {"filed": oid, "skipped_open": False, "error": None, "replayed": res.get("replayed", False)}
    except Exception as exc:  # noqa: BLE001 -- best-effort: a failed filing is printed, never raised
        print(f"work-export: filing the validation failure FAILED: {exc}", file=sys.stderr)
        return {"filed": None, "skipped_open": False, "error": str(exc)}


def export_summary(out: dict) -> str:
    """One human line per count, for the workflow log / step summary."""
    f = out.get("filing") or {}
    lines = [f"rows: {out['rows_written']} written, {out['rows_unchanged']} unchanged, {out['rows_held']} held back",
             f"records: {out['records_written']} written, {out['records_unchanged']} unchanged, "
             f"{out['records_held']} held back",
             f"pre-cutover failing items landed (exempt): {out['exempt_failing_landed']}",
             f"items filed: {len(f.get('filed', []))} (already open: {len(f.get('skipped_open', []))}, "
             f"filing errors: {len(f.get('errors', []))})"]
    lines += [f"held: {h['id']}: {' | '.join(h['messages'])}" for h in out.get("held", [])]
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        if "=" not in p:
            raise WorkError(f"expected key=value, got {p!r}")
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


#: Legacy pipeline words that read as UNROUTED in `work_store_import._project`, whatever the item's
#: parent or owner (the projection keeps the legacy word when it still maps to the stored state).
_UNROUTED_LEGACY = ("queued", "due")


def route_fields(item: dict, fields: dict) -> dict:
    """WORK-SET-ROUTE-TRAP (2026-11-13): a ``set`` that gives an observation a parent or an owner
    must also ROUTE it. Without this, setting ``parent_id``/``owner`` alone left
    ``extra._legacy_state=queued`` and ``pipeline.unrouted`` still counted the item (MEASURED: 10
    items re-owned and re-parented, unrouted count unchanged at 34 until ``_legacy_state`` was
    flipped by hand). Returns ``fields`` plus a merged ``extra`` carrying ``_legacy_state=routed``
    and ``routed_to`` (the parent, else the owner); unchanged when not applicable or when the caller
    sets ``extra`` itself."""
    if item.get("kind") != "observation" or "extra" in fields:
        return fields
    target = fields.get("parent_id") or fields.get("owner")
    if not target:
        return fields
    extra = dict(item.get("extra") or {})
    if extra.get("_legacy_state") not in _UNROUTED_LEGACY:
        return fields
    extra["_legacy_state"] = "routed"
    extra["routed_to"] = str(target)
    return {**fields, "extra": extra}


def build_op(a) -> dict:
    by = _by(a)
    if a.cmd == "add":
        body = {"id": a.id, "kind": a.kind, "title": a.title, **_kv(a.field or [])}
        return make_op("create", a.id, body, by, a.op_id)
    if a.cmd == "set":
        return make_op("set", a.id, {"fields": _kv(a.assignments)}, by, a.op_id)
    if a.cmd == "note":
        body = {"text": a.text}
        if a.summary is not None:
            body["summary"] = a.summary
        return make_op("note", a.id, body, by, a.op_id)
    if a.cmd == "close":
        return make_op("close", a.id, {"state": a.state, "reason": a.reason}, by, a.op_id)
    if a.cmd == "reopen":
        return make_op("set", a.id, {"fields": {"state": a.state, "terminal_reason": None}}, by, a.op_id)
    raise WorkError(f"no op for {a.cmd}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="work store CLI (design § 2.3)")
    ap.add_argument("--via", choices=("auto", "direct", "outbox"), default="auto")
    ap.add_argument("--issue", type=int, default=int(os.environ.get("WORK_STORE_OUTBOX_ISSUE") or 0) or None,
                    help="the outbox issue number (runner posting / drain)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("get", "history"):
        sub.add_parser(name).add_argument("id")
    pl = sub.add_parser("list")
    for f in ("state", "parent", "kind", "since"):
        pl.add_argument(f"--{f}")
    pl.add_argument("--due", action="store_true")
    pl.add_argument("--limit", type=int, default=50)
    pa = sub.add_parser("add")
    pa.add_argument("id")
    pa.add_argument("--kind", required=True, choices=("build", "observation"))
    pa.add_argument("--title", required=True)
    pa.add_argument("--field", action="append", help="key=value (JSON parsed), repeatable")
    ps = sub.add_parser("set")
    ps.add_argument("id")
    ps.add_argument("assignments", nargs="+")
    pn = sub.add_parser("note")
    pn.add_argument("id")
    pn.add_argument("text")
    pn.add_argument("--summary")
    pc = sub.add_parser("close")
    pc.add_argument("id")
    pc.add_argument("--reason", required=True)
    pc.add_argument("--state", default="done", choices=("done", "dropped"))
    pr = sub.add_parser("reopen")
    pr.add_argument("id")
    pr.add_argument("--state", default="queued")
    po = sub.add_parser("observe")
    po.add_argument("id")
    po.add_argument("text")
    sub.add_parser("drain")
    ph = sub.add_parser("header", help="the register header's store-backed keys (last_review)")
    ph.add_argument("action", choices=("get", "set"))
    ph.add_argument("key")
    ph.add_argument("value", nargs="?", help="JSON (set only)")
    ph.add_argument("--by")
    ph.add_argument("--op-id")
    pe = sub.add_parser("export")
    pe.add_argument("--to-files", action="store_true", required=True)
    pe.add_argument("--root", default=None, help="repo root to write into (default: this repo)")
    pe.add_argument("--db", default=None, help="a local work_store.db (the VM); default: page the API")
    pe.add_argument("--unfreeze", action="store_true", help="also remove the freeze key (rollback)")
    pe.add_argument("--no-precheck", action="store_true",
                    help="write every differing item, skipping the guards' row checks (the byte-exact rollback)")
    pe.add_argument("--no-file", action="store_true", help="do not file observations for held-back items")
    pe.add_argument("--run-ref", default=None, help="who ran the export (e.g. a workflow run url), for filings")
    pv = sub.add_parser("export-validation-failed",
                        help="(workflow) file ONE 'EXPORT VALIDATION FAILED' observation, deduplicated")
    pv.add_argument("--check", action="append", default=[], help="a failing check name, repeatable")
    pv.add_argument("--log", default=None, help="a log file; its tail goes into the filing")
    pv.add_argument("--run-ref", default=None)
    for sp in (pa, ps, pn, pc, pr, po):
        sp.add_argument("--by")
        sp.add_argument("--op-id")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "get":
            st, p, _ = http("GET", f"{API}/{urllib.parse.quote(a.id)}")
            out = _ok(st, p, f"get {a.id}")
        elif a.cmd == "history":
            st, p, _ = http("GET", f"{API}/{urllib.parse.quote(a.id)}/events")
            out = _ok(st, p, f"history {a.id}")
        elif a.cmd == "list":
            q = {k: v for k, v in (("state", a.state), ("parent", a.parent), ("kind", a.kind),
                                   ("since", a.since), ("limit", a.limit)) if v}
            if a.due:
                q["due"] = "true"
            st, p, _ = http("GET", f"{API}?{urllib.parse.urlencode(q)}")
            out = _ok(st, p, "list")
        elif a.cmd == "header":
            if a.action == "get":
                st, p, _ = http("GET", f"{META_API}/{urllib.parse.quote(a.key)}")
                out = _ok(st, p, f"header get {a.key}")
            else:
                if a.value is None:
                    raise WorkError("header set needs a JSON value")
                try:
                    val = json.loads(a.value)
                except ValueError as exc:
                    raise WorkError(f"header set: value is not JSON: {exc}") from None
                out = send(make_op("meta", a.key, {"value": val}, _by(a), a.op_id), a.via, a.issue)
        elif a.cmd == "export":
            root = a.root or str(_REPO)
            items = _all_items(a.db)
            out = export_to_files(root, items, unfreeze=a.unfreeze, header_meta=_header_meta(a.db),
                                  precheck=not a.no_precheck)
            if out["held"] and not a.no_file:
                out["filing"] = file_holds(out["held"], items, run_ref=a.run_ref or "")
            print(export_summary(out), file=sys.stderr)
        elif a.cmd == "export-validation-failed":
            tail = ""
            if a.log:
                try:
                    with open(a.log, encoding="utf-8", errors="replace") as fh:
                        tail = fh.read()[-4000:]
                except OSError as exc:
                    tail = f"(log unreadable: {exc})"
            try:
                items = _all_items(None)
            except WorkError as exc:  # cannot dedup without the listing: say so, do not file blind
                print(f"work-export: cannot list the store to dedup, NOT filing: {exc}", file=sys.stderr)
                items = None
            out = (file_validation_failure(a.check, tail, items, run_ref=a.run_ref or "")
                   if items is not None else {"filed": None, "error": "store listing failed"})
        elif a.cmd == "drain":
            if not a.issue:
                raise WorkError("drain needs --issue (or WORK_STORE_OUTBOX_ISSUE)")
            out = drain(a.issue)
        elif a.cmd == "observe":
            # Two writes, each idempotent by its own op_id: the check's date, then what was seen.
            by, base = _by(a), a.op_id or f"cli-{uuid.uuid4().hex}"
            if a.via != "outbox":
                item = get_item(a.id)
                rule = dict(item.get("due_rule") or {})
            else:
                raise WorkError("observe needs the item's due_rule: use --via direct/auto, or set + note via outbox")
            rule["last_checked"] = datetime.now(timezone.utc).date().isoformat()
            r1 = send(make_op("set", a.id, {"fields": {"due_rule": rule}}, by, base + ":set"), a.via, a.issue)
            r2 = send(make_op("note", a.id, {"text": a.text}, by, base + ":note"), a.via, a.issue)
            out = {"via": r2.get("via"), "writes": [r1, r2]}
        elif a.cmd == "set" and a.via != "outbox":
            # Route on owner/parent (route_fields): needs the item's current extra, so direct/auto only.
            o = build_op(a)
            fields = o["body"]["fields"]
            if "parent_id" in fields or "owner" in fields:
                o["body"]["fields"] = route_fields(get_item(a.id), fields)
            out = send(o, a.via, a.issue)
        else:
            out = send(build_op(a), a.via, a.issue)
    except WorkError as exc:
        print(json.dumps({"error": str(exc), "status": exc.status, "detail": exc.body}, default=str), file=sys.stderr)
        return 2 if not isinstance(exc, Unreachable) else 3
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

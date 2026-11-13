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
    work.py export --to-files [--root DIR] [--db PATH] [--unfreeze]   # the ROLLBACK path (WSD-S4)

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


def apply_direct(o: dict) -> dict:
    """Apply one op through the API; a 409 is re-read and re-applied once."""
    body = {**o["body"], "by": o["by"], "op_id": o["op_id"]}
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
    if not (isinstance(o, dict) and o.get("op") in ("create", "set", "note", "close")
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
            "item": res.get("item"), "event_seq": (res.get("event") or {}).get("seq")}


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


def export_to_files(root, items: list[dict], *, unfreeze: bool = False) -> dict:
    """Write the store's items into the file layout under ``root``; only what differs is written."""
    from pathlib import Path
    from scripts.ops import pipeline as pl
    from src.runtime import checklist_store as cs
    from src.runtime import work_read
    from src.runtime import work_store_import as wi
    root = Path(root)
    cdir, pdir = root / cs.STORE, root / pl.STORE
    cdir.mkdir(parents=True, exist_ok=True)
    out = {"rows_written": 0, "rows_unchanged": 0, "records_written": 0, "records_unchanged": 0}
    have = pl.read_files(pdir).items if pdir.exists() else {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    for it in sorted(items, key=lambda i: i["id"]):
        if it["kind"] == "build":
            row = wi.to_row(it)
            path = cdir / f"{row['id']}.json"
            if path.is_file() and json.loads(path.read_text(encoding="utf-8")) == row:
                out["rows_unchanged"] += 1
                continue
            path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
            out["rows_written"] += 1
        else:
            rec = wi.to_pipeline_item(it)
            if have.get(rec["id"]) == rec:
                out["records_unchanged"] += 1
                continue
            pdir.mkdir(parents=True, exist_ok=True)
            name = f"{stamp}Z-export-{rec['id']}{pl.RECORD_SUFFIX}"
            (pdir / name).write_text(json.dumps(rec, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                                     encoding="utf-8")
            out["records_written"] += 1
    if unfreeze:
        hp = cdir / cs.HEADER
        head = json.loads(hp.read_text(encoding="utf-8"))
        out["unfrozen"] = head.pop(work_read.FROZEN_KEY, None) is not None
        hp.write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8")
    return out


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
    pe = sub.add_parser("export")
    pe.add_argument("--to-files", action="store_true", required=True)
    pe.add_argument("--root", default=None, help="repo root to write into (default: this repo)")
    pe.add_argument("--db", default=None, help="a local work_store.db (the VM); default: page the API")
    pe.add_argument("--unfreeze", action="store_true", help="also remove the freeze key (rollback)")
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
        elif a.cmd == "export":
            root = a.root or str(_REPO)
            out = export_to_files(root, _all_items(a.db), unfreeze=a.unfreeze)
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

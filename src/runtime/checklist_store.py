"""The per-row checklist store: loader, generator, seed, check (stdlib only).

Lives under ``src/runtime`` so BOTH the web API (``GET /api/bot/work/checklist``)
and the ``scripts/`` readers import one implementation; the CLI and self-test are
``scripts/ops/checklist.py``. Layout, cutover and rationale (PI-20261004-APBY4NTV-0003)
are documented there.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STORE = Path("docs/claude/work/checklist")
MONOLITH = Path("docs/claude/work/MANAGER-CHECKLIST.json")
HEADER = "_header.json"
SEQ = "_seq"
_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


__all__ = ["ChecklistError", "HEADER", "MONOLITH", "MONOLITH_NAME", "RANK", "REPO", "SEQ", "STORE",
           "HISTORY_PATHS", "TERMINAL", "UNMAPPED", "DEFAULT_OWNER", "filing_problems", "fill_defaults", "effective_due", "is_overdue", "check", "queue", "rank_problem", "exists", "is_checklist_path", "load", "load_at", "load_path", "read_row", "render", "seeded", "seed", "write_header", "write_row"]


class ChecklistError(ValueError):
    pass


#: THE FILING CONTRACT (operator, 2026-11-01, lane CHECKLIST-OWNER-DUE): the manager owns every task;
#: a row is filed WITH a date and WITH a roadmap ref, or it is not filed. "It is just a question of
#: when we are getting to them" -- so `owner` defaults to `manager`, `due_by` is an ISO date, and
#: `roadmap` is a milestone list or the explicit ["unmapped"] with `roadmap_unmapped_reason`.
#: Rows in a TERMINAL state are exempt (they are closed; closing needs a stated reason).
TERMINAL = ("done", "dropped")
UNMAPPED = "unmapped"
DEFAULT_OWNER = "manager"
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$")


def _as_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def filing_problems(row: dict) -> list[str]:
    """Why a NON-TERMINAL row may not be filed/changed as it stands (owner, due_by, roadmap), else []."""
    if row.get("state") in TERMINAL:
        return []
    out: list[str] = []
    owner = row.get("owner")
    if not (isinstance(owner, str) and owner.strip()):
        out.append(f"no `owner` (default `{DEFAULT_OWNER}`: the manager owns every task)")
    if _as_date(row.get("due_by")) is None:
        out.append("no `due_by` -- an ISO date (YYYY-MM-DD) when we will get to it; every row is filed with one")
    rm = row.get("roadmap")
    rm = [rm] if isinstance(rm, str) else rm
    refs = [x for x in rm if isinstance(x, str) and x.strip()] if isinstance(rm, list) else []
    if not refs:
        out.append("no `roadmap` ref -- a milestone id from docs/roadmap/milestones.yaml, or "
                   f'["{UNMAPPED}"] with `roadmap_unmapped_reason`')
    elif UNMAPPED in refs:
        if refs != [UNMAPPED]:
            out.append(f'`roadmap` mixes "{UNMAPPED}" with milestone ids; use one or the other')
        elif len(str(row.get("roadmap_unmapped_reason") or "").strip()) < 10:
            out.append(f'`roadmap` is "{UNMAPPED}" with no `roadmap_unmapped_reason` (say why, >= 10 chars)')
    return out


def fill_defaults(row: dict, today: date | None = None) -> list[str]:
    """PROCESS, NOT GATES (operator, 2026-11-01): fill what a filer left out instead of refusing the row.
    owner -> manager; due_by -> computed from state / priority_rank / the observation the row names;
    roadmap -> ["unmapped"] + a reason the drain and the weekly pass will show as work. Mutates ``row``;
    returns what it filled (so the CLI can say so). Terminal rows are left alone."""
    from datetime import timedelta
    today = today or datetime.now().astimezone().date()
    if row.get("state") in TERMINAL:
        return []
    filled: list[str] = []
    if not (isinstance(row.get("owner"), str) and row["owner"].strip()):
        row["owner"] = DEFAULT_OWNER
        filled.append("owner=manager")
    if _as_date(row.get("due_by")) is None:
        obs = row.get("observe") if isinstance(row.get("observe"), dict) else {}
        d = _as_date(obs.get("when")) or (_as_date(row["observation"].get("due_by"))
                                          if isinstance(row.get("observation"), dict) else None)
        st, rank = row.get("state"), row.get("priority_rank")
        if d is not None and d >= today:
            basis = "the observation date the row names"
        elif st == "in_flight":
            d, basis = today + timedelta(days=2), "in_flight: +2d"
        elif st == "blocked":
            d, basis = today + timedelta(days=7), "blocked: re-check in +7d"
        elif st == "landed_unproven":
            d, basis = today + timedelta(days=3), "landed_unproven, no future observation date: +3d"
        elif isinstance(rank, (int, float)) and not isinstance(rank, bool):
            d, basis = today + timedelta(days=1 if rank <= 3 else 3 if rank <= 10 else 7), f"queued, priority_rank {rank}"
        else:
            d, basis = today + timedelta(days=7), "queued, unranked: +7d"
        row["due_by"] = d.isoformat()
        filled.append(f"due_by={row['due_by']} ({basis})")
    rm = row.get("roadmap")
    if not ([rm] if isinstance(rm, str) and rm.strip() else rm):
        row["roadmap"] = [UNMAPPED]
        row.setdefault("roadmap_unmapped_reason", "not set at filing -- manager to map to a milestone at the next weekly pass")
        filled.append('roadmap=["unmapped"]')
    return filled


def effective_due(row: dict) -> date | None:
    """The date a row is due: its own `due_by`, else the legacy `observation.due_by` (rows filed before the contract)."""
    d = _as_date(row.get("due_by"))
    if d is None and isinstance(row.get("observation"), dict):
        d = _as_date(row["observation"].get("due_by"))
    return d


def is_overdue(row: dict, today: date) -> bool:
    d = effective_due(row)
    return bool(d and d < today and row.get("state") not in TERMINAL)


#: THE RANKED QUEUE IS A REGISTER FIELD (MANAGER-PACING-STRUCTURAL, 2026-10-18): the manager's
#: dispatch order used to live in its own head and in a trigger prompt, so no successor could
#: inherit it. `priority_rank` (1 = dispatch next) was already on 7 rows ad hoc; this makes it
#: the one declared rank. Unranked rows sort after every ranked one -- never silently "rank 0".
RANK = "priority_rank"


def rank_problem(value) -> str | None:
    """Why ``value`` is not a valid ``priority_rank`` (a positive number, or null), else None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return f"{RANK} must be a positive number (1 = dispatch next) or null, not {value!r}"
    return None


def queue(data: dict) -> list[dict]:
    """The runnable queue in dispatch order: ``queued`` rows with nothing in ``blocked_on``,
    by ``priority_rank`` (unranked last), then register order. ``data`` is ``load()``'s shape."""
    rows = [r for r in (data.get("items") or [])
            if isinstance(r, dict) and r.get("state") == "queued" and not r.get("blocked_on")]
    order = {id(r): n for n, r in enumerate(rows)}

    def key(r):
        rank = r.get(RANK)
        ranked = rank_problem(rank) is None and rank is not None
        return (0 if ranked else 1, rank if ranked else 0, order[id(r)])
    return sorted(rows, key=key)


def _dump(obj) -> str:
    return json.dumps(obj, indent=2) + "\n"


def _row_path(store: Path, row_id: str) -> Path:
    if not isinstance(row_id, str) or not _ID_OK.match(row_id) or row_id == "_header":
        raise ChecklistError(f"row id {row_id!r} is not filename-safe ([A-Za-z0-9._-], not _header)")
    return store / f"{row_id}.json"


def _read_rows(store: Path) -> list[dict]:
    rows = []
    for p in sorted(store.glob("*.json")):
        if p.name == HEADER:
            continue
        row = json.loads(p.read_text(encoding="utf-8"))
        if row.get("id") != p.stem:
            raise ChecklistError(f"{p.name}: id {row.get('id')!r} does not match the filename")
        rows.append(row)
    # stable order: _seq, then id. A row without _seq sorts last, not first.
    rows.sort(key=lambda r: (r.get(SEQ, 1 << 60), r["id"]))
    return rows


def load(repo: Path = REPO, store: Path = STORE) -> dict:
    """The checklist in exactly today's served shape. Raises ChecklistError /
    OSError / ValueError when unreadable -- callers must not read that as empty."""
    return _load_dir(repo / store)


MONOLITH_NAME = MONOLITH.name


def is_checklist_path(path) -> bool:
    """Is ``path`` the (possibly absent) monolith file? Readers that were handed a
    PATH (``--checklist``, a test fixture root, ``sr.CHECKLIST_PATH``) ask this to
    decide whether to read it as a file or through the store."""
    return Path(path).name == MONOLITH_NAME


def _store_for(path) -> Path:
    return Path(path).parent / STORE.name


def seeded(path) -> bool:
    """Has the per-row store been cut over for the monolith at ``path``?"""
    return (_store_for(path) / HEADER).is_file()


def exists(path) -> bool:
    """Is there a checklist at ``path`` -- the monolith file OR a seeded store?
    Distinct from *readable*: callers keep their absent/unreadable split."""
    return Path(path).is_file() or seeded(path)


def load_path(path):
    """Drop-in for ``json.loads(Path(path).read_text())`` on the checklist: reads the
    per-row store when it is seeded next to ``path`` (rows are the truth after the
    cutover), else the monolith file. Raises OSError / ValueError exactly as the
    inline form did (ChecklistError is a ValueError), so existing ``except`` blocks
    and their absent/unreadable split are unchanged."""
    path = Path(path)
    if seeded(path):
        return _load_dir(_store_for(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dir(base: Path) -> dict:
    header = json.loads((base / HEADER).read_text(encoding="utf-8"))
    rows = [{k: v for k, v in r.items() if k != SEQ} for r in _read_rows(base)]
    return {k: (rows if k == "items" else v) for k, v in header.items()}


HISTORY_PATHS = (str(STORE), str(MONOLITH))
"""Pass both to ``git log -- <paths>``: a row's history is its own file after the
cutover, the monolith's before it."""


def load_at(repo, ref: str):
    """The checklist as of git ``ref``, in the served shape: ``None`` when neither the
    store nor the monolith exists there ("absent", not "empty"); raises ValueError
    when one exists but cannot be read. Uses ONE ``git cat-file --batch`` per call, so
    walking hundreds of revisions stays cheap."""
    repo = str(repo)

    def git(*args):
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)

    head = git("show", f"{ref}:{STORE}/{HEADER}")
    if head.returncode != 0:
        mono = git("show", f"{ref}:{MONOLITH}")
        return None if mono.returncode != 0 else json.loads(mono.stdout)
    names = [n for n in git("ls-tree", "-r", "--name-only", ref, "--", str(STORE)).stdout.splitlines()
             if n.endswith(".json") and not n.endswith(f"/{HEADER}")]
    rows = []
    if names:
        out = subprocess.run(["git", "-C", repo, "cat-file", "--batch"],
                             input="".join(f"{ref}:{n}\n" for n in names).encode(),
                             capture_output=True)
        buf, pos = out.stdout, 0
        for n in names:
            nl = buf.index(b"\n", pos)
            meta = buf[pos:nl].split()
            if len(meta) != 3 or meta[1] != b"blob":
                raise ChecklistError(f"{ref}:{n}: unreadable ({buf[pos:nl][:80]!r})")
            size = int(meta[2])
            rows.append(json.loads(buf[nl + 1:nl + 1 + size]))
            pos = nl + 1 + size + 1
    rows.sort(key=lambda r: (r.get(SEQ, 1 << 60), r["id"]))
    rows = [{k: v for k, v in r.items() if k != SEQ} for r in rows]
    return {k: (rows if k == "items" else v) for k, v in json.loads(head.stdout).items()}


def render(repo: Path = REPO, store: Path = STORE) -> str:
    return _dump(load(repo, store))


def read_row(row_id: str, repo: Path = REPO, store: Path = STORE) -> dict | None:
    """One row as stored (``_seq`` stripped), or None if there is no such row."""
    path = _row_path(repo / store, row_id)
    if not path.is_file():
        return None
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k != SEQ}


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic: no reader ever sees a partial row


def write_row(row: dict, repo: Path = REPO, store: Path = STORE) -> Path:
    """Create or replace ONE row file, atomically. A new row takes ``_seq`` max+1;
    an existing row keeps its position."""
    base = repo / store
    path = _row_path(base, row.get("id"))
    row = dict(row)
    if path.exists():
        row[SEQ] = json.loads(path.read_text(encoding="utf-8")).get(SEQ, row.get(SEQ, 0))
    elif SEQ not in row:
        row[SEQ] = max((r.get(SEQ, 0) for r in _read_rows(base)), default=-1) + 1
    _atomic_write(path, _dump(row))
    return path


def write_header(key: str, value, repo: Path = REPO, store: Path = STORE) -> Path:
    """Set one top-level (non-row) key in the header. Rare; this file is shared."""
    if key == "items":
        raise ChecklistError("'items' is the row list; use write_row")
    path = repo / store / HEADER
    header = json.loads(path.read_text(encoding="utf-8"))
    header[key] = value
    _atomic_write(path, _dump(header))
    return path


def seed(src: Path | None = None, repo: Path = REPO, store: Path = STORE) -> int:
    """Split a monolith into the store. Refuses duplicate ids; idempotent."""
    src = src or (repo / MONOLITH)
    data = json.loads(src.read_text(encoding="utf-8"))
    ids = [i["id"] for i in data["items"]]
    if len(ids) != len(set(ids)):
        raise ChecklistError("duplicate row ids in the monolith")
    base = repo / store
    base.mkdir(parents=True, exist_ok=True)
    for n, row in enumerate(data["items"]):
        path = _row_path(base, row["id"])
        path.write_text(_dump({**row, SEQ: n}), encoding="utf-8")
    (base / HEADER).write_text(
        _dump({k: (None if k == "items" else v) for k, v in data.items()}), encoding="utf-8")
    for p in base.glob("*.json"):  # a row deleted from the monolith leaves the store
        if p.name != HEADER and p.stem not in ids:
            p.unlink()
    return len(ids)


def check(repo: Path = REPO, store: Path = STORE) -> list[str]:
    """Why the monolith is not render(), or [] if it is."""
    try:
        want = render(repo, store)
    except (OSError, ValueError) as exc:
        return [f"store unreadable: {type(exc).__name__}: {exc}"]
    have = (repo / MONOLITH).read_text(encoding="utf-8")
    if have == want:
        return []
    h, w = json.loads(have), json.loads(want)
    hi, wi = {r["id"]: r for r in h["items"]}, {r["id"]: r for r in w["items"]}
    out = [f"row {i}: {'only in the monolith' if i not in wi else 'differs'}"
           for i in hi if i not in wi or hi[i] != wi[i]]
    out += [f"row {i}: only in the store" for i in wi if i not in hi]
    out += [f"header key {k!r} differs" for k in h if k != "items" and h.get(k) != w.get(k)]
    return out or ["bytes differ (key order / formatting) though the data is equal"]

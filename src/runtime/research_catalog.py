"""Read-only projection of the research queue into a searchable catalog.

One row per research unit, built ONLY from files committed to this (public)
repo: ``research/queue/*.yaml`` (+ ``queue/blocked/``), the landed rows under
``research/results/<unit>/*.jsonl``, ``research/THEMES.yaml`` and
``docs/roadmap/milestones.yaml``. No DB, no secrets, no new store -- so there is
nothing to backfill and the catalog cannot disagree with the queue it reads.

Whether a unit is *due* is the dispatcher's own answer
(``scripts.research.dispatch_queue._is_due``), never re-derived here; if that
import or call fails the row says so (``dueState: "unknown"``) instead of
guessing -- "could not look" is a state, not "not due".

Status vocabulary (``status``): ``queued`` | ``due`` | ``dispatched`` |
``running`` | ``result`` | ``blocked`` | ``retired``. ``stuck`` is a separate
flag with a stated ``stuckReason`` (a unit can be e.g. ``dispatched`` AND stuck).
Every nullable field is ``None`` when unknown -- consumers render "—".
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

REPO_BLOB = "https://github.com/benbaichmankass/Metis-Insights/blob/main"
#: A dispatched unit with no landed row after this many hours is flagged stuck.
STUCK_AFTER_HOURS = 6.0
#: Result `read_state` values that carry no verdict (the run did not measure).
_NON_VERDICT = {"producer_failed", "no_data"}
_ID_DATE_RE = re.compile(r"^RQ-(\d{4})(\d{2})(\d{2})")
_SCALAR = (int, float, str, bool)
_DATA_KEY_HINTS = ("symbol", "leg", "timeframe", "tf", "interval", "start", "end", "since",
                   "until", "days", "lookback", "years", "from", "to", "dataset", "corpus")

SORT_KEYS = ("id", "title", "theme", "status", "verdict", "priority", "lastActivity", "created")
STATUS_ORDER = ("due", "running", "dispatched", "queued", "blocked", "result", "retired")


def _ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def _text(v: Any, limit: int = 600) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).split())
    if not s:
        return None
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _created(uid: str) -> datetime | None:
    m = _ID_DATE_RE.match(uid)
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    except ValueError:
        return None


def _load_yaml(path: Path) -> tuple[dict | None, str | None]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, f"unreadable: {type(exc).__name__}"
    if not isinstance(doc, dict):
        return None, "top level is not a mapping"
    return doc, None


def _roadmap_index(root: Path) -> dict[str, dict[str, Any]]:
    """milestone id -> {name, goal, goalName, status}. {} when unreadable."""
    doc, _err = _load_yaml(root / "docs" / "roadmap" / "milestones.yaml")
    if doc is None:
        return {}
    goals = doc.get("goals") or {}
    out: dict[str, dict[str, Any]] = {}
    for m in doc.get("milestones") or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        g = str(m.get("goal") or "")
        out[str(m["id"])] = {
            "id": str(m["id"]), "name": _text(m.get("name"), 160), "goal": g or None,
            "goalName": _text((goals.get(g) or {}).get("name"), 120) if g else None,
            "status": m.get("status"),
        }
    return out


def read_results(uid: str, results_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """(rows newest-first, result file names). Unparseable lines are skipped, counted by absence."""
    rdir = results_root / uid
    rows: list[dict[str, Any]] = []
    files: list[str] = []
    if not rdir.is_dir():
        return rows, files
    for f in sorted(rdir.glob("*.jsonl")):
        files.append(f.name)
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for ln in lines:
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict):
                r["_file"] = f.name
                rows.append(r)
    rows.sort(key=lambda r: _iso(_ts(r.get("generated_at"))) or "", reverse=True)
    return rows, files


#: Result sources OTHER than research/results/<uid>/: shared corpora whose rows are tagged
#: `research_unit=<uid>` and dated by `sweep_generated_at`. A unit's rows at or after its
#: dispatch stamp ARE its landed result; the catalog was blind to them (27 of 41 'dispatched'
#: units on 2026-10-14 had landed there). Read-only; add a corpus by adding a row here.
CORPORA: tuple[tuple[str, str], ...] = (
    ("docs/research/e35-bracket-corpus.jsonl", "e35_bracket"),
)


def _load_corpus_index(root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """({uid: {path, corpus, sweeps: {sweep_generated_at: row_count}}}, readErrors).

    One pass per corpus; only the unit tag and the sweep timestamp of each row are kept, so a
    12 MB file costs a few KB. A missing file or an unparseable line is REPORTED (readErrors),
    never read as 'no corpus rows' -- that would silently turn landed units back into 'stuck'."""
    index: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    for rel, label in CORPORA:
        path = root / rel
        if not path.is_file():
            errors.append({"path": rel, "error": "corpus file missing"})
            continue
        bad = 0
        try:
            with path.open(encoding="utf-8") as fh:
                for ln in fh:
                    if not ln.strip():
                        continue
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        bad += 1
                        continue
                    uid = r.get("research_unit") if isinstance(r, dict) else None
                    if not uid:
                        continue
                    ent = index.setdefault(str(uid), {"path": rel, "corpus": label, "sweeps": {}})
                    sw = str(r.get("sweep_generated_at") or "")
                    ent["sweeps"][sw] = ent["sweeps"].get(sw, 0) + 1
        except (OSError, UnicodeDecodeError) as exc:
            errors.append({"path": rel, "error": f"unreadable: {type(exc).__name__}"})
            continue
        if bad:
            errors.append({"path": rel, "error": f"{bad} unparseable line(s) skipped"})
    return index, errors


def _corpus_state(ent: dict[str, Any] | None, stamp: datetime | None) -> dict[str, Any]:
    """Summarise one unit's corpus rows against its dispatch stamp."""
    if not ent:
        return {"landed": False, "rows": 0, "latest": None, "after_stamp_rows": 0}
    dated = [(_ts(k), n) for k, n in ent["sweeps"].items()]
    latest = max((d for d, _ in dated if d), default=None)
    after = sum(n for d, n in dated if d is not None and (stamp is None or d >= stamp))
    return {"landed": after > 0, "rows": sum(ent["sweeps"].values()), "latest": latest,
            "after_stamp_rows": after}


def _metrics(measurement: Any, limit: int = 14) -> dict[str, Any]:
    if not isinstance(measurement, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in measurement.items():
        if isinstance(v, _SCALAR) or v is None or isinstance(v, list) and all(isinstance(x, _SCALAR) for x in v) and len(v) <= 8:
            out[str(k)] = v
        if len(out) >= limit:
            break
    return out


def _data_used(entry: dict, row: dict | None) -> dict[str, Any]:
    run = entry.get("run") if isinstance(entry.get("run"), dict) else {}
    inputs = run.get("inputs") if isinstance(run.get("inputs"), dict) else {}
    hinted = {str(k): v for k, v in inputs.items()
              if isinstance(v, _SCALAR) and any(h in str(k).lower() for h in _DATA_KEY_HINTS)}
    pop = (row or {}).get("population") if isinstance((row or {}).get("population"), dict) else {}
    lands = entry.get("lands") if isinstance(entry.get("lands"), dict) else {}
    return {
        "workflow": run.get("workflow") if isinstance(run.get("workflow"), str) else None,
        "harness": _text(((row or {}).get("produced_by") or {}).get("tool"), 200),
        "inputs": {str(k): v for k, v in inputs.items() if isinstance(v, _SCALAR)},
        "dataInputs": hinted,
        "population": _text(pop.get("description"), 400),
        "n": pop.get("n"),
        "store": lands.get("store"),
    }


def _route_backend(entry: dict) -> str | None:
    r = entry.get("routing") if isinstance(entry.get("routing"), dict) else {}
    if not r:
        return None
    if r.get("needs_gpu"):
        return "gpu"
    if r.get("needs_trainer_resident_data"):
        return "trainer"
    return "runner"


def _roadmap_refs(entry: dict, index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    raw = entry.get("roadmap")
    ids = [raw] if isinstance(raw, str) else [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    return [index.get(i) or {"id": i, "name": None, "goal": None, "goalName": None, "status": None} for i in ids]


def _due(entry: dict, now: datetime) -> tuple[str, str | None]:
    """('due'|'not_due'|'unknown', reason) from the dispatcher's own predicate."""
    try:
        from scripts.research.dispatch_queue import _is_due
        due, why = _is_due(entry, now)
    except Exception as exc:  # noqa: BLE001 -- surfaced as 'unknown', never as 'not due'
        logger.warning("research_catalog: due-state unavailable for %s: %s", entry.get("id"), exc)
        return "unknown", f"due-state unavailable ({type(exc).__name__})"
    return ("due" if due else "not_due"), _text(why, 300)


def build_unit(entry: dict, *, path: Path, blocked_dir: bool, root: Path, results_root: Path,
               roadmap: dict[str, dict[str, Any]], now: datetime,
               corpus: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    uid = str(entry.get("id") or path.stem)
    rows, files = read_results(uid, results_root)
    latest = rows[0] if rows else None
    verdict_row = next((r for r in rows if str(r.get("read_state")) not in _NON_VERDICT), None)
    last_stamp = _ts(entry.get("last_dispatched_at"))
    latest_at = _ts((latest or {}).get("generated_at"))
    file_status = str(entry.get("status") or "queued")
    grading = entry.get("grading") if isinstance(entry.get("grading"), dict) else {}
    cs = _corpus_state((corpus or {}).get(uid), last_stamp)
    if cs["latest"] is not None and (latest_at is None or cs["latest"] > latest_at):
        latest_at = cs["latest"]

    due_state, due_reason = ("not_due", None)
    stuck_reason: str | None = None
    blocked_reason: str | None = None
    if blocked_dir or file_status == "blocked":
        status = "blocked"
        bo = entry.get("blocked_on")
        blocked_reason = _text(bo if not isinstance(bo, dict) else
                               " ".join(str(v) for v in bo.values() if isinstance(v, str)), 300) \
            or _text(entry.get("clears_when"), 300) or "no blocked_on recorded"
        stuck_reason = f"blocked: {blocked_reason}"
    elif file_status == "retired":
        status = "retired"
    elif verdict_row is not None or file_status == "done" or cs["landed"]:
        status = "result"
    elif file_status == "running":
        status = "running"
    else:
        due_state, due_reason = _due(entry, now)
        if last_stamp and (latest_at is None or latest_at < last_stamp):
            status = "dispatched"
            if (now - last_stamp) > timedelta(hours=STUCK_AFTER_HOURS):
                stuck_reason = (f"dispatched {_iso(last_stamp)} with no landed result after "
                                f"{STUCK_AFTER_HOURS:g}h")
        elif due_state == "due":
            status = "due"
        else:
            status = "queued"
        if due_reason and "retry cap reached" in due_reason:
            stuck_reason = due_reason
    if grading.get("needs_review"):
        stuck_reason = stuck_reason or "grading.needs_review: a session must read this result"

    decision = entry.get("decision_rule") if isinstance(entry.get("decision_rule"), dict) else {}
    power = entry.get("power") if isinstance(entry.get("power"), dict) else {}
    vr = verdict_row or {}
    activity = [d for d in (latest_at, last_stamp, _ts(grading.get("graded_at"))) if d]
    base_files = [f"research/results/{uid}/{f}" for f in files]
    return {
        "id": uid,
        "title": _text(entry.get("title"), 240),
        "summary": _text(entry.get("question"), 700),
        "whyItMatters": _text(entry.get("why_this_matters"), 900),
        "kind": entry.get("kind"),
        "cadence": entry.get("cadence"),
        "theme": entry.get("theme"),
        "priority": entry.get("priority") if isinstance(entry.get("priority"), int) else None,
        "roadmap": _roadmap_refs(entry, roadmap),
        "status": status,
        "fileStatus": file_status,
        "dueState": due_state,
        "dueReason": due_reason,
        "blockedReason": blocked_reason,
        "stuck": stuck_reason is not None,
        "stuckReason": stuck_reason,
        "rule": {
            "id": decision.get("id"), "registeredAt": _text(decision.get("registered_at"), 40),
            "registeredBeforeRun": decision.get("registered_before_run"),
            "statistic": _text(decision.get("statistic"), 500), "text": _text(decision.get("rule"), 1200),
        } if decision else None,
        "power": {"state": vr.get("power_state") or (latest or {}).get("power_state"),
                  "expectedN": power.get("expected_n"),
                  "minDetectableEffect": power.get("min_detectable_effect")} if (power or latest) else None,
        "verdict": vr.get("verdict") or grading.get("verdict"),
        "readState": (latest or {}).get("read_state"),
        "resultNote": (_text(vr.get("note"), 700) or _text(entry.get("result"), 700)
                       or (_text(grading.get("reason"), 700) if cs["landed"] and grading.get("verdict") else None)
                       or (f"result landed in {corpus[uid]['path']} ({cs['after_stamp_rows']} row(s) at or after "
                           f"the dispatch stamp); ungraded" if cs["landed"] and corpus else None)),
        "resultSource": ("results_dir" if verdict_row is not None else
                         (corpus[uid]["corpus"] if cs["landed"] and corpus else None)),
        "corpus": {"path": corpus[uid]["path"], "corpus": corpus[uid]["corpus"], "rows": cs["rows"],
                   "rowsAfterStamp": cs["after_stamp_rows"], "latestSweepAt": _iso(cs["latest"]),
                   "graded": bool(grading.get("verdict"))} if corpus and uid in corpus else None,
        "metrics": _metrics(vr.get("measurement")),
        "resultCount": len(rows) + cs["after_stamp_rows"],
        "dataUsed": _data_used(entry, verdict_row or latest),
        "backend": _route_backend(entry),
        "estMinutes": (entry.get("routing") or {}).get("est_minutes") if isinstance(entry.get("routing"), dict) else None,
        "createdAt": _iso(_created(uid)),
        "lastDispatchedAt": _iso(last_stamp),
        "latestResultAt": _iso(latest_at),
        "lastActivity": _iso(max(activity)) if activity else _iso(_created(uid)),
        "links": {
            "unit": f"{REPO_BLOB}/{path.relative_to(root).as_posix()}" if path.is_relative_to(root) else None,
            "results": [f"{REPO_BLOB}/{p}" for p in base_files]
            + ([f"{REPO_BLOB}/{corpus[uid]['path']}"] if corpus and uid in corpus else []),
            "run": ((vr or latest or {}).get("produced_by") or {}).get("run_url"),
        },
    }


def build_catalog(root: Path, *, now: datetime | None = None,
                  results_root: Path | None = None) -> dict[str, Any]:
    """Every unit, plus the read errors. ``readErrors`` non-empty means we could not look at those files."""
    now = now or datetime.now(timezone.utc)
    results_root = results_root or (root / "research" / "results")
    qdir = root / "research" / "queue"
    roadmap = _roadmap_index(root)
    corpus, corpus_errors = _load_corpus_index(root)
    units: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = list(corpus_errors)
    if not qdir.is_dir():
        return {"units": [], "readErrors": [{"path": "research/queue", "error": "directory missing"}],
                "roadmapAvailable": bool(roadmap)}
    for sub, is_blocked in ((qdir, False), (qdir / "blocked", True)):
        if not sub.is_dir():
            continue
        for p in sorted(sub.glob("*.yaml")):
            doc, err = _load_yaml(p)
            if doc is None:
                errors.append({"path": p.relative_to(root).as_posix(), "error": err or "unreadable"})
                continue
            units.append(build_unit(doc, path=p, blocked_dir=is_blocked, root=root,
                                    results_root=results_root, roadmap=roadmap, now=now, corpus=corpus))
    return {"units": units, "readErrors": errors, "roadmapAvailable": bool(roadmap)}


# ── query: search / filter / sort / paginate / facets ────────────────────────────────────────
_FACETS = ("theme", "status", "verdict", "goal", "backend", "kind", "stuck")


def _facet_value(u: dict[str, Any], facet: str) -> str | None:
    if facet == "goal":
        goals = {r.get("goal") for r in u["roadmap"] if r.get("goal")}
        return ",".join(sorted(goals)) if goals else None
    if facet == "stuck":
        return "yes" if u["stuck"] else "no"
    v = u.get(facet)
    return None if v is None else str(v)


def _matches(u: dict[str, Any], facet: str, wanted: Iterable[str]) -> bool:
    wanted = set(wanted)
    if not wanted:
        return True
    val = _facet_value(u, facet)
    if val is None:
        return "none" in wanted
    return bool(set(val.split(",")) & wanted)


def _haystack(u: dict[str, Any]) -> str:
    parts = [u["id"], u["title"], u["summary"], u["theme"], u["verdict"], u["resultNote"],
             u["blockedReason"], u["stuckReason"], (u["dataUsed"] or {}).get("workflow"),
             json.dumps((u["dataUsed"] or {}).get("dataInputs") or {}),
             " ".join(f"{r['id']} {r.get('name') or ''}" for r in u["roadmap"])]
    return " ".join(str(p) for p in parts if p).lower()


def query_catalog(units: list[dict[str, Any]], *, q: str = "", filters: dict[str, list[str]] | None = None,
                  sort: str = "lastActivity", order: str = "desc", limit: int = 50, offset: int = 0,
                  created_from: str | None = None, created_to: str | None = None) -> dict[str, Any]:
    filters = filters or {}
    terms = [t for t in q.lower().split() if t]

    def base(u: dict[str, Any]) -> bool:
        if terms and not all(t in _haystack(u) for t in terms):
            return False
        if created_from and (u["createdAt"] or "") < created_from:
            return False
        return not (created_to and (u["createdAt"] or "9") > created_to + "T99")

    pool = [u for u in units if base(u)]
    matched = [u for u in pool if all(_matches(u, f, filters.get(f, [])) for f in _FACETS)]

    facets: dict[str, dict[str, int]] = {}
    for f in _FACETS:   # a facet's counts ignore its own selection so the operator can still widen it
        counts: dict[str, int] = {}
        for u in pool:
            if all(_matches(u, g, filters.get(g, [])) for g in _FACETS if g != f):
                for v in (_facet_value(u, f) or "none").split(","):
                    counts[v] = counts.get(v, 0) + 1
        facets[f] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    key = sort if sort in SORT_KEYS else "lastActivity"
    rev = order != "asc"

    def sk(u: dict[str, Any]) -> tuple[int, Any]:
        if key == "created":
            v = u["createdAt"]
        elif key == "status":
            v = STATUS_ORDER.index(u["status"]) if u["status"] in STATUS_ORDER else 99
        else:
            v = u.get(key)
        return (1, v) if v is not None else (0, "")

    present = sorted((u for u in matched if sk(u)[0] == 1), key=lambda u: sk(u)[1], reverse=rev)
    absent = [u for u in matched if sk(u)[0] == 0]
    ordered = present + absent        # unknowns always last, whatever the direction
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    return {"total": len(units), "matched": len(matched), "limit": limit, "offset": offset,
            "sort": key, "order": "desc" if rev else "asc", "facets": facets,
            "items": ordered[offset: offset + limit]}


def stay_on_top(units: list[dict[str, Any]], since: str | None, now: datetime | None = None) -> dict[str, Any]:
    """The operator's first-look block: what is new, stuck, due, and the latest verdicts."""
    since_dt = _ts(since)

    def slim(u: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "title", "theme", "status", "verdict", "lastActivity", "stuckReason", "createdAt")
        return {k: u[k] for k in keys}
    new = [u for u in units if since_dt and (
        (_ts(u["createdAt"]) and _ts(u["createdAt"]) > since_dt) or
        (_ts(u["latestResultAt"]) and _ts(u["latestResultAt"]) > since_dt))]
    stuck = [u for u in units if u["stuck"]]
    due = [u for u in units if u["status"] == "due"]
    verdicts = sorted((u for u in units if u["verdict"] and u["latestResultAt"]),
                      key=lambda u: u["latestResultAt"], reverse=True)
    def cap(xs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [slim(u) for u in xs[:12]]

    return {
        "since": _iso(since_dt),
        "sinceKnown": since_dt is not None,   # False => 'new' is NOT computed (first visit), not 'nothing new'
        "new": {"count": len(new), "items": cap(sorted(new, key=lambda u: u["lastActivity"] or "", reverse=True))}
        if since_dt else None,
        "stuck": {"count": len(stuck), "items": cap(stuck)},
        "due": {"count": len(due), "items": cap(due)},
        "recentVerdicts": cap(verdicts),
    }

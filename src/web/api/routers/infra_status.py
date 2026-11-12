"""Infra health bar + testing queue (UI-SPA-BACKEND-ROUTES, 2026-11-12).

* ``GET /api/bot/health/infra``      -- OVERVIEW (1): one entry per component,
  money path first.
* ``GET /api/bot/work/testing-queue`` -- OVERVIEW (4) card "testing queue":
  what is running now on trainer / research infra.

Both are READ-ONLY views over artifacts that already exist on the live VM
(heartbeat file, the trainer mirror, the reachability latch, committed stamps).
Nothing here probes a network, SSHes, or reads a secret.

THE RULE THAT SHAPES THIS FILE: a component we cannot read is
``could_not_look`` -- never ``ok``. ``ok`` needs a FRESH artifact that says it
works; a stale-but-present artifact is ``degraded``; ``down`` needs an
artifact that SAYS it failed. The ``source`` field names the artifact so the
SPA (and a reviewer) can tell a measurement from an inference.

Component states (``state``): ``ok`` | ``degraded`` | ``down`` | ``could_not_look``.
Thresholds are module constants, deliberately conservative, and stated in
``detail`` where they decided the answer.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from src.runtime.provenance import MEASURED, UNVERIFIED
from src.utils.paths import repo_root, runtime_logs_dir, trade_journal_db_path

logger = logging.getLogger(__name__)

health_router = APIRouter(prefix="/api/bot/health", tags=["health"])
work_router = APIRouter(prefix="/api/bot/work", tags=["work"])

OK, DEGRADED, DOWN, COULD_NOT_LOOK = "ok", "degraded", "down", "could_not_look"

#: Trainer mirror is republished every ~2 min (publish_trainer_mirror.sh).
TRAINER_OK_S = 600
TRAINER_DEGRADED_S = 3600
#: account_reachability_alert's check cadence is minutes; an hour with no
#: ``__last_check__`` update means the checker itself is not running.
REACHABILITY_STALE_S = 3600
#: Phone app: a registration heartbeat (``device_tokens.last_seen_at``), NOT
#: delivery. A phone only touches it when the app opens/registers.
PHONE_OK_S = 3 * 86400
PHONE_DEGRADED_S = 14 * 86400
#: Kaggle backup stamps (kaggle-backups.yml) and the HF lake-health record.
KAGGLE_OK_S = 36 * 3600
LAKE_OK_S = 48 * 3600
#: A trainer cycle_start with no cycle_end older than this is an orphan, not
#: a cycle in flight.
CYCLE_ORPHAN_S = 6 * 3600
#: A research dispatch with no result newer than this is "in flight".
DISPATCH_INFLIGHT_S = 24 * 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    t = raw.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _entry(component: str, state: str, as_of: Optional[datetime], detail: str,
           source: str, now: datetime) -> Dict[str, Any]:
    age = None if as_of is None else max(0.0, (now - as_of).total_seconds())
    return {
        "component": component,
        "state": state,
        "as_of": _iso(as_of) if as_of else None,
        "age_s": None if age is None else round(age, 1),
        "detail": detail,
        "source": source,
        "provenance": UNVERIFIED if state == COULD_NOT_LOOK else MEASURED,
    }


def _cnl(component: str, detail: str, source: str, now: datetime) -> Dict[str, Any]:
    return _entry(component, COULD_NOT_LOOK, None, detail, source, now)


def _read_json(path: Path) -> Any:
    """Parsed JSON, or raises ``OSError``/``ValueError`` (caller maps to could_not_look)."""
    return json.loads(path.read_text(encoding="utf-8"))


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _mirror_root() -> Path:
    return runtime_logs_dir() / "trainer_mirror"


# --------------------------------------------------------------------------
# components
# --------------------------------------------------------------------------
def _trader_vm(now: datetime) -> Dict[str, Any]:
    src = "runtime_logs/heartbeat.txt (mtime)"
    p = runtime_logs_dir() / "heartbeat.txt"
    try:
        as_of = _mtime(p)
    except OSError:
        return _cnl("trader_vm", "heartbeat file not readable", src, now)
    from src.runtime.heartbeat import heartbeat_label, heartbeat_thresholds
    age = max(0.0, (now - as_of).total_seconds())
    label = heartbeat_label(age)
    run_max, pause_max = heartbeat_thresholds()
    state = {"running": OK, "paused": DEGRADED}.get(label, DOWN)
    return _entry("trader_vm", state, as_of,
                  f"last tick {age:.0f}s ago ({label}; running < {run_max}s, "
                  f"paused < {pause_max}s)", src, now)


def _ib_accounts() -> Optional[List[str]]:
    """Declared-live Interactive Brokers account ids from config, or None."""
    from src.config.accounts_loader import load_accounts_dict  # noqa: PLC0415
    accts = load_accounts_dict(Path(repo_root()) / "config" / "accounts.yaml")
    if not accts:
        return None  # empty = unreadable (the loader logs and returns {})
    return sorted(
        a for a, c in accts.items()
        if isinstance(c, dict) and c.get("exchange") == "interactive_brokers"
        and c.get("mode") == "live")


def _ib_gateway(now: datetime) -> Dict[str, Any]:
    # The gateway's own watchdog runs on the GATEWAY VM, so its state file is
    # not on this host. The trader's per-tick reachability latch IS: it reads
    # each declared-live IB account through the gateway.
    src = "runtime_logs/account_reachability_alert_state.json"
    p = runtime_logs_dir() / "account_reachability_alert_state.json"
    try:
        state = _read_json(p)
        if not isinstance(state, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        return _cnl("ib_gateway", "reachability latch not readable", src, now)
    last = _parse_ts(state.get("__last_check__"))
    if last is None:
        return _cnl("ib_gateway", "reachability latch has no __last_check__", src, now)
    age = (now - last).total_seconds()
    if age > REACHABILITY_STALE_S:
        return _entry("ib_gateway", COULD_NOT_LOOK, last,
                      f"reachability checker last ran {age / 60:.0f}m ago "
                      f"(> {REACHABILITY_STALE_S // 60}m): not a current read", src, now)
    ids = _ib_accounts()
    if not ids:
        return _entry("ib_gateway", COULD_NOT_LOOK, last,
                      "no declared-live IB account resolvable from accounts.yaml", src, now)
    rows = {a: state.get(a) for a in ids}
    missing = [a for a, r in rows.items() if not isinstance(r, dict)]
    if len(missing) == len(ids):
        return _entry("ib_gateway", COULD_NOT_LOOK, last,
                      f"no latch row for {', '.join(ids)}", src, now)
    down = [a for a, r in rows.items() if isinstance(r, dict) and r.get("down")]
    flap = [a for a, r in rows.items() if isinstance(r, dict)
            and not r.get("down") and int(r.get("consecutive_down") or 0) > 0]
    if down:
        return _entry("ib_gateway", DOWN, last,
                      f"unreachable via gateway: {', '.join(down)}", src, now)
    if flap or missing:
        bits = ([f"{', '.join(flap)} failing reads (below the DOWN threshold)"] if flap else []) \
            + ([f"no latch row for {', '.join(missing)}"] if missing else [])
        return _entry("ib_gateway", DEGRADED, last, "; ".join(bits), src, now)
    return _entry("ib_gateway", OK, last,
                  f"{', '.join(ids)} reachable at last check", src, now)


def _phone_app(now: datetime) -> Dict[str, Any]:
    src = "trade_journal.db::device_tokens.last_seen_at"
    path = Path(trade_journal_db_path())
    if not path.exists():
        return _cnl("phone_app", "journal DB not found", src, now)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        try:
            row = conn.execute(
                "SELECT COUNT(*), MAX(last_seen_at) FROM device_tokens").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:  # allow-silent: maps to a stated could_not_look entry, never ok
        return _cnl("phone_app", f"device_tokens not readable ({exc.__class__.__name__})",
                    src, now)
    n, newest = row[0], _parse_ts(row[1]) if row[1] else None
    if not n:
        return _entry("phone_app", DOWN, None,
                      "no device registered for push", src, now)
    if newest is None:
        return _cnl("phone_app", f"{n} device(s) but last_seen_at unparseable", src, now)
    age = (now - newest).total_seconds()
    state = OK if age <= PHONE_OK_S else DEGRADED if age <= PHONE_DEGRADED_S else DOWN
    return _entry("phone_app", state, newest,
                  f"{n} device(s) registered; newest seen {age / 3600:.1f}h ago "
                  f"(registration heartbeat, not delivery; ok <= {PHONE_OK_S // 3600}h)",
                  src, now)


def _trainer_vm(now: datetime) -> Dict[str, Any]:
    src = "runtime_logs/trainer_mirror/trainer_status.json (mtime)"
    p = _mirror_root() / "trainer_status.json"
    try:
        as_of = _mtime(p)
    except OSError:
        return _cnl("trainer_vm", "trainer mirror not present", src, now)
    age = (now - as_of).total_seconds()
    detail = f"mirror published {age:.0f}s ago"
    try:
        st = _read_json(p)
        lc = (st or {}).get("last_cycle") or {}
        if lc.get("outcome"):
            detail += f"; last cycle {lc.get('outcome')} (failed={lc.get('failed')})"
    except (OSError, ValueError):
        pass
    state = OK if age <= TRAINER_OK_S else DEGRADED if age <= TRAINER_DEGRADED_S else DOWN
    return _entry("trainer_vm", state, as_of, detail, src, now)


def _kaggle(now: datetime) -> Dict[str, Any]:
    src = "comms/backups/kaggle_latest.json"
    p = Path(repo_root()) / "comms" / "backups" / "kaggle_latest.json"
    try:
        doc = _read_json(p)
        kinds = doc["kinds"]
    except (OSError, ValueError, KeyError, TypeError):
        return _cnl("kaggle", "backup stamp not readable", src, now)
    stamps = []
    bad = []
    for name, k in (kinds or {}).items():
        if not isinstance(k, dict):
            continue
        t = _parse_ts(k.get("last_attempt_at"))
        if t:
            stamps.append(t)
        if k.get("ok") is not True or int(k.get("consecutive_failures") or 0) > 0:
            bad.append(name)
    if not stamps:
        return _cnl("kaggle", "backup stamp carries no attempt times", src, now)
    newest = max(stamps)
    age = (now - newest).total_seconds()
    if bad and len(bad) == len(stamps):
        return _entry("kaggle", DOWN, newest, f"every backup kind failing: {', '.join(bad)}", src, now)
    if bad:
        return _entry("kaggle", DEGRADED, newest, f"failing kinds: {', '.join(bad)}", src, now)
    if age > KAGGLE_OK_S:
        return _entry("kaggle", DEGRADED, newest,
                      f"last Kaggle backup attempt {age / 3600:.0f}h ago "
                      f"(> {KAGGLE_OK_S // 3600}h); a workflow record, not a live probe", src, now)
    return _entry("kaggle", OK, newest,
                  f"{len(stamps)} backup kind(s) ok, newest attempt {age / 3600:.1f}h ago "
                  "(a workflow record, not a live probe)", src, now)


def _hugging_face(now: datetime) -> Dict[str, Any]:
    src = "comms/data_lake/health_latest.json"
    p = Path(repo_root()) / "comms" / "data_lake" / "health_latest.json"
    try:
        doc = _read_json(p)
        gen = _parse_ts(doc.get("generated_at"))
        summ = doc.get("summary") or {}
    except (OSError, ValueError, AttributeError):
        return _cnl("hugging_face", "lake-health record not readable", src, now)
    if gen is None:
        return _cnl("hugging_face", "lake-health record has no generated_at", src, now)
    age = (now - gen).total_seconds()
    fails, warns = summ.get("fail"), summ.get("warn")
    base = (f"market-data-lake health record (the HF-hosted lake): "
            f"fail={fails}, warn={warns}, {age / 3600:.0f}h old; not a live probe of huggingface.co")
    if age > LAKE_OK_S:
        return _entry("hugging_face", DEGRADED, gen, f"STALE (> {LAKE_OK_S // 3600}h): {base}", src, now)
    if isinstance(fails, int) and fails > 0:
        return _entry("hugging_face", DEGRADED, gen, base, src, now)
    return _entry("hugging_face", OK, gen, base, src, now)


@health_router.get("/infra")
def get_health_infra() -> Dict[str, Any]:
    """``{as_of, read_state, components[6], summary{ok,degraded,down,could_not_look}}``.

    Order is fixed, money path first: ``trader_vm``, ``ib_gateway``,
    ``phone_app``, then ``trainer_vm``, ``kaggle``, ``hugging_face``. Each:
    ``{component, state, as_of, age_s, detail, source, provenance}``;
    ``as_of``/``age_s`` are null when no artifact timestamp could be read.
    ``read_state``: ``read`` (every component read), ``partial`` (some
    ``could_not_look``), ``could_not_look`` (all).
    """
    now = _now()
    comps: List[Dict[str, Any]] = []
    for fn, name in ((_trader_vm, "trader_vm"), (_ib_gateway, "ib_gateway"),
                     (_phone_app, "phone_app"), (_trainer_vm, "trainer_vm"),
                     (_kaggle, "kaggle"), (_hugging_face, "hugging_face")):
        try:
            comps.append(fn(now))
        except Exception as exc:  # noqa: BLE001  # allow-silent: logged; a component must never 5xx the bar, and maps to could_not_look
            logger.exception("infra_status: %s failed", name)
            comps.append(_cnl(name, f"read failed ({exc.__class__.__name__})", "n/a", now))
    summary = {s: sum(1 for c in comps if c["state"] == s)
               for s in (OK, DEGRADED, DOWN, COULD_NOT_LOOK)}
    n_cnl = summary[COULD_NOT_LOOK]
    read_state = ("could_not_look" if n_cnl == len(comps)
                  else "partial" if n_cnl else "read")
    return {"as_of": _iso(now), "read_state": read_state,
            "components": comps, "summary": summary}


# --------------------------------------------------------------------------
# testing queue
# --------------------------------------------------------------------------
_UNIT = re.compile(r"^RQ-[0-9A-Za-z-]{3,40}$")


def _jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict):
                out.append(o)
    return out


def _infra_of(workflow: Any) -> str:
    w = str(workflow or "").lower()
    if "kaggle" in w:
        return "kaggle"
    if "gpu" in w or "runpod" in w:
        return "gpu_burst"
    if "trainer" in w:
        return "trainer_vm"
    return "github_runner" if w else "unknown"


def _unit_title(unit: str) -> Optional[str]:
    if not _UNIT.match(unit):
        return None
    f = Path(repo_root()) / "research" / "queue" / f"{unit}.yaml"
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("title:"):
                return line[6:].strip().strip("'\"")[:200] or None
    except OSError:
        return None
    return None


def _trainer_cycle(now: datetime, running: List[Dict[str, Any]]) -> Dict[str, Any]:
    src = "trainer_mirror/training_cycle.jsonl"
    p = _mirror_root() / "training_cycle.jsonl"
    try:
        rows = _jsonl(p)
        mtime = _mtime(p)
    except OSError:
        return {"source": src, "read_state": COULD_NOT_LOOK, "as_of": None,
                "detail": "trainer cycle log not present on this host"}
    last_start = last_end = None
    for r in rows:
        t = _parse_ts(r.get("ts"))
        if t is None:
            continue
        if r.get("status") == "cycle_start":
            last_start = t
        elif r.get("status") == "cycle_end":
            last_end = t
    detail = "no cycle in flight"
    if last_start and (last_end is None or last_end < last_start):
        age = (now - last_start).total_seconds()
        if age <= CYCLE_ORPHAN_S:
            running.append({
                "id": f"trainer-cycle-{_iso(last_start)}", "kind": "trainer_cycle",
                "title": "Trainer VM training cycle", "infra": "trainer_vm",
                "started_at": _iso(last_start), "age_s": round(age, 1),
                "source": src})
            detail = "cycle_start with no cycle_end"
        else:
            detail = (f"last cycle_start {age / 3600:.0f}h ago has no cycle_end "
                      f"(> {CYCLE_ORPHAN_S // 3600}h: treated as orphan, not running)")
    return {"source": src, "read_state": "read", "as_of": _iso(mtime), "detail": detail}


def _research_dispatches(now: datetime, running: List[Dict[str, Any]]) -> Dict[str, Any]:
    src = "trainer_mirror/research/research_runs.jsonl"
    p = _mirror_root() / "research" / "research_runs.jsonl"
    try:
        rows = _jsonl(p)
        mtime = _mtime(p)
    except OSError:
        return {"source": src, "read_state": COULD_NOT_LOOK, "as_of": None,
                "detail": "research-runs mirror not present on this host"}
    last_dispatch: Dict[str, Dict[str, Any]] = {}
    last_result: Dict[str, datetime] = {}
    for r in rows:
        u, t = r.get("unit_id"), _parse_ts(r.get("at"))
        if not isinstance(u, str) or t is None:
            continue
        if r.get("kind") == "dispatch":
            if u not in last_dispatch or t > last_dispatch[u]["_t"]:
                last_dispatch[u] = {**r, "_t": t}
        elif r.get("kind") == "result":
            if u not in last_result or t > last_result[u]:
                last_result[u] = t
    n = 0
    for u, d in sorted(last_dispatch.items(), key=lambda kv: kv[1]["_t"], reverse=True):
        age = (now - d["_t"]).total_seconds()
        if age > DISPATCH_INFLIGHT_S or (u in last_result and last_result[u] >= d["_t"]):
            continue
        n += 1
        running.append({
            "id": u, "kind": "research_run", "title": _unit_title(u) or u,
            "infra": _infra_of(d.get("workflow")), "started_at": _iso(d["_t"]),
            "age_s": round(age, 1), "source": src})
    return {"source": src, "read_state": "read", "as_of": _iso(mtime),
            "detail": f"{n} dispatch(es) < {DISPATCH_INFLIGHT_S // 3600}h old with no later result"}


@work_router.get("/testing-queue")
def get_testing_queue() -> Dict[str, Any]:
    """``{as_of, read_state, n_running, running[], sources[], hf_jobs}``.

    ``running[]``: ``{id, kind: trainer_cycle|research_run, title, infra,
    started_at, age_s, source}``, newest first. A research unit counts as
    running when its newest ``dispatch`` row is < 24h old and has no later
    ``result`` row (the mirror carries no completion for a run that died, so
    a dead run stays listed until the 24h bound -- ``age_s`` shows it).
    ``infra`` is derived from the dispatching workflow name.

    ``sources[]`` states per-source ``read_state`` (``read`` | ``could_not_look``).
    ``n_running`` is **null** when NO source was readable (never ``0`` for
    "we could not look"); ``read_state`` is ``read`` | ``partial`` |
    ``could_not_look``. **Hugging Face jobs are not observable from this host**
    -- ``hf_jobs`` is always ``{"read_state": "could_not_look"}`` rather than an
    empty list.
    """
    now = _now()
    running: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    for fn in (_trainer_cycle, _research_dispatches):
        try:
            sources.append(fn(now, running))
        except Exception as exc:  # noqa: BLE001  # allow-silent: logged; maps to could_not_look
            logger.exception("infra_status: testing-queue source failed")
            sources.append({"source": fn.__name__, "read_state": COULD_NOT_LOOK,
                            "as_of": None, "detail": f"read failed ({exc.__class__.__name__})"})
    running.sort(key=lambda r: r["started_at"], reverse=True)
    states = {s["read_state"] for s in sources}
    read_state = ("read" if states == {"read"}
                  else "partial" if "read" in states else "could_not_look")
    return {
        "as_of": _iso(now),
        "read_state": read_state,
        "n_running": None if read_state == "could_not_look" else len(running),
        "running": running,
        "sources": sources,
        "hf_jobs": {"read_state": COULD_NOT_LOOK,
                    "detail": "no Hugging Face job state is mirrored to this host"},
    }

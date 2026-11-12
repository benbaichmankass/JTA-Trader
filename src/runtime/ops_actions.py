"""The direct ops channel, VM side (MANAGER-VM-DIRECT-OPS; TRADE-ACTION-DIRECT-PATH design § 2.3, phase 2 wave 1).

Operator, 2026-11-12 ~00:05Z, verbatim (design § 2.3): "the Claude sessions should already be able to interact
directly with the VM without needing to go through GitHub ... for things like this, which is not a code change,
it's just an action on the system, that shouldn't have to go through GitHub. It should go through the system
though ... we're not looking for a workaround that has Claude directly interacting with the brokers ... it should
go directly from Claude to the VM and skip like a merge as part of that process." Row approved 2026-11-05 (popup
"Direct ops = Approve (Recommended)", "Config path = Keep via git", "Deploy = Keep git-sync" plus a direct
"sync now").

ONE channel: ``POST /api/bot/ops/actions`` -> :func:`submit` writes a job; ``GET /api/bot/ops/jobs/<id>`` ->
:func:`read_job`. The web API never runs an action itself: a job goes into ``<ops>/queue/`` and the path-activated
``ict-ops-runner`` unit (``scripts/ops/ops_runner.py`` -> :func:`run_queue`) runs it out of process, so a
``restart-service ict-web-api`` job cannot kill the process serving it and a long job never blocks the API.

The REGISTRY below is the allowlist. Every entry is listed with the SAME name and tier in
``docs/claude/system-actions.md`` § 2a, and an entry that ports a § 2 system-action carries that action's tier
(``tests/ops/test_ops_actions_parity.py``), so the channel can never grant more than the workflow does. Nothing here
talks to a broker: each action calls an existing system path on the VM (the system-action wrapper scripts, the
phase-1 directed-action spool -> ``live_review_apply.run()`` and each account's ``RiskManager``, and the phase-2
direct row submit read by the live trader's ``ltr-direct-rows`` thread).

Tiers (unchanged, design § 2.3):

* Tier 1 runs at once (:data:`TIER1_AUTORUN`; the operator's open question, design § 6 line 10, is that one line).
* Tier 2 runs when the call carries the operator's VERBATIM OK (``operator_quote``). Without one, the runner sends
  the operator the phase-1 Approve / Reject ask (``trade_approvals.offer_ops``: the SAME store, ``tapv`` buttons,
  operator-chat check, expiry and ``decide()`` as a trade ask, so Telegram and the SPA console both work), and
  ``decide()`` hands the outcome to :func:`on_approval`, which queues the job on Approve.
* Tier 3 (strategy logic / params, risk caps, account-mode promotion) and every config or code edit are REFUSED by
  name (:data:`REFUSED_BY_NAME`) and stay in git (operator 2026-11-05, "Keep via git").

GATES: none added. The approval card and its expiry are the existing Tier-2 rule carried on a new pipe; no trading
gate, no ``*_ENABLED`` flag, nothing default-off.

Journal: ``<ops>/journal.jsonl`` (one line per event) and ``<ops>/jobs/<id>.json`` (the job record).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

#: Design § 2.3: "Tier 1 (read-only / hygiene) runs at once." The operator's parked question (design § 6 line 10:
#: may this one environment credential run Tier-1 ops at once?) is THIS line. False = every Tier-1 job also waits
#: for an operator quote or an Approve tap, exactly like Tier 2.
TIER1_AUTORUN: bool = True

#: The VM's data dir. The web API (DATA_DIR drop-in), the runner unit and the Claude decision bot (no DATA_DIR)
#: must all see ONE queue, and ``deploy/ict-ops-runner.path`` watches a literal path, so the ops dir does not
#: depend on each process's DATA_DIR. ``OPS_CHANNEL_DIR`` overrides it (tests, a non-VM host).
VM_OPS_DIR = Path("/data/bot-data/runtime_logs/ops")
#: A queued job not picked up this long reads ``runner_not_picking_up`` (never silently "queued").
RUNNER_LAG_S = 120
STDOUT_TAIL = 4000
JOB_ID_RE = re.compile(r"^OPS-[0-9]{8}T[0-9]{6}Z-[a-z0-9-]+-[0-9a-f]{6}$")

QUEUED, AWAITING, RUNNING, DONE, FAILED, REFUSED, REJECTED, EXPIRED = (
    "queued", "awaiting_approval", "running", "done", "failed", "refused", "rejected", "expired")
TERMINAL = (DONE, FAILED, REFUSED, REJECTED, EXPIRED)

#: Actions refused BY NAME, with where they go instead (design § 2.3; operator 2026-11-05 "Keep via git").
REFUSED_BY_NAME: Dict[str, str] = {
    "set-account-mode": "Tier 3 / account-mode promotion: a config/accounts.yaml PR with the operator's approval "
                        "(system-actions `set-account-mode` commits it to git)",
    "config-edit": "config edits stay in git: open a PR",
    "code-edit": "code edits stay in git: open a PR",
    "strategy-params": "Tier 3 (strategy logic and params): a config/strategies.yaml PR with operator approval",
    "risk-caps": "Tier 3 (risk caps / sizing): a PR with operator approval",
    "promote": "Tier 3 (live promotion): a PR with operator approval",
}


class OpsError(Exception):
    """A refusal the API answers with ``status``."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ─────────────────────────────────────────────────────────────────────────── paths + small io

def ops_root() -> Path:
    env = (os.environ.get("OPS_CHANNEL_DIR") or "").strip()
    if env:
        return Path(env)
    if VM_OPS_DIR.parent.parent.is_dir():          # /data/bot-data exists: the VM
        return VM_OPS_DIR
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir()) / "ops"


def _dir(name: str, root: Optional[Path] = None) -> Path:
    d = (root or ops_root()) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(v: Any) -> Optional[datetime]:
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def journal(event: str, job: Dict[str, Any], root: Optional[Path] = None, **extra: Any) -> None:
    doc = {"at": _iso(_now()), "event": event, "job_id": job.get("job_id"), "action": job.get("action"),
           "tier": job.get("tier"), "state": job.get("state"), "session": job.get("session"), **extra}
    try:
        with (_dir("", root) / "journal.jsonl").open("a") as fh:
            fh.write(json.dumps(doc, default=str, separators=(",", ":")) + "\n")
    except OSError:
        logger.warning("ops: journal write failed", exc_info=True)


@contextlib.contextmanager
def _lock(root: Optional[Path] = None) -> Iterator[None]:
    with open(_dir("", root) / ".lock", "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def job_path(job_id: str, root: Optional[Path] = None) -> Path:
    return _dir("jobs", root) / f"{job_id}.json"


def save_job(job: Dict[str, Any], root: Optional[Path] = None) -> None:
    _write_json(job_path(job["job_id"], root), job)


# ─────────────────────────────────────────────────────────────────────────── param validation

_ACCT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TICKET_RE = re.compile(r"^prop-[a-z]+-[0-9a-f]{6,64}$")
_PRICE_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")

#: restart-service: the SAME unit allowlist ``scripts/ops/set_env.sh::ALLOWED_SERVICES`` restarts today (minus
#: ``none``). ict-ops-runner is deliberately absent: a job cannot restart the unit running it.
RESTARTABLE_SERVICES = ("ict-claude-bridge.service", "ict-telegram-bot.service", "ict-web-api.service",
                        "ict-hourly-snapshot.service", "ict-trader-live.service")


def _truthy(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    if v is None:
        return False
    return None


def _v_none(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    return {}, [f"unknown param {k}" for k in p]


def _v_restart(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    svc = str(p.get("service") or "").strip()
    if svc and not svc.endswith(".service"):
        svc += ".service"
    errs = [f"unknown param {k}" for k in p if k != "service"]
    if svc not in RESTARTABLE_SERVICES:
        errs.append(f"service must be one of {', '.join(RESTARTABLE_SERVICES)} (got {p.get('service')!r})")
    return {"service": svc}, errs


def _v_prop_bracket(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The same shape checks as the system-actions workflow's amend-prop-bracket arm (PR #25016); the python
    helper on the VM owns every money guard."""
    keys = ("account", "ticket_id", "new_tp", "new_sl", "clear_tp", "apply")
    errs = [f"unknown param {k}" for k in p if k not in keys]
    acct, tid = str(p.get("account") or "").strip(), str(p.get("ticket_id") or "").strip()
    tp = "" if p.get("new_tp") in (None, "") else str(p.get("new_tp")).strip()
    sl = "" if p.get("new_sl") in (None, "") else str(p.get("new_sl")).strip()
    clear, apply = _truthy(p.get("clear_tp")), _truthy(p.get("apply"))
    if not _ACCT_RE.match(acct):
        errs.append("account: <id> is required")
    if not _TICKET_RE.match(tid):
        errs.append("ticket_id: prop-<kind>-<hex> is required")
    for name, v in (("new_tp", tp), ("new_sl", sl)):
        if v and not _PRICE_RE.match(v):
            errs.append(f"{name} must be a positive decimal")
    if clear is None or apply is None:
        errs.append("clear_tp / apply must be true or false")
    if not tp and not sl and not clear:
        errs.append("needs new_tp, new_sl or clear_tp: true")
    return {"account": acct, "ticket_id": tid, "new_tp": tp, "new_sl": sl, "clear_tp": bool(clear),
            "apply": bool(apply)}, errs


#: set-env (OPS-SET-ENV, operator 2026-11-12: "Go directly using your token to the VM and turn it off ... Do not try
#: going through the repo"): the direct channel's env flip, so a kill switch never waits on an Actions runner. Keys
#: are an explicit pattern allowlist with per-key value sets; the write goes through the SAME scripts/ops/set_env.sh
#: the system-actions set-env arm runs (byte-preserving upsert, symbolic env_file, its own service allowlist).
SET_ENV_KEYS = ((re.compile(r"^PROP_PHONE_MODE_[A-Z0-9_]+$"), ("off", "dry", "live")),)
SET_ENV_FILES = ("shared", "web-api")


def _v_set_env(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    keys = ("key", "value", "service", "env_file")
    errs = [f"unknown param {k}" for k in p if k not in keys]
    key = str(p.get("key") or "").strip()
    val = str(p.get("value") if p.get("value") is not None else "").strip()
    env_file = str(p.get("env_file") or "shared").strip()
    svc = str(p.get("service") or "").strip()
    if svc and svc != "none" and not svc.endswith(".service"):
        svc += ".service"
    allowed = next((vals for rx, vals in SET_ENV_KEYS if rx.match(key)), None)
    if allowed is None:
        errs.append(f"key {key!r} is not in the set-env allowlist")
    elif val not in allowed:
        errs.append(f"value for {key} must be one of {', '.join(allowed)}")
    if env_file not in SET_ENV_FILES:
        errs.append(f"env_file must be one of {', '.join(SET_ENV_FILES)}")
    if svc not in RESTARTABLE_SERVICES and svc != "none":
        errs.append(f"service must be one of {', '.join(RESTARTABLE_SERVICES)} or none")
    return {"key": key, "value": val, "service": svc, "env_file": env_file}, errs


def _v_directed(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """A directed_action/v1 record minus id / created_at / directed_by / operator_quote (filled at run time, so a
    record approved minutes later is not born stale). Validated with the VM's own ``directed_actions.problems``."""
    from src.runtime import directed_actions as da

    keys = ("package", "action", "level", "fraction", "scope", "dry_run")
    errs = [f"unknown param {k}" for k in p if k not in keys]
    dry = _truthy(p.get("dry_run")) if "dry_run" in p else None
    if dry is None:
        errs.append("dry_run: true | false is required (say which, every time)")
    rec: Dict[str, Any] = {"order_package_id": p.get("package"), "action": p.get("action"),
                           "scope": p.get("scope") or "package", "dry_run": bool(dry)}
    if p.get("level") is not None:
        rec["level"] = p.get("level")
    if p.get("fraction") is not None:
        rec["fraction"] = p.get("fraction")
    probe = dict(rec, schema=da.SCHEMA, id=da.new_id(str(rec["action"] or "x"), _now(), "000000"),
                 created_at=_iso(_now()), directed_by="ops:probe", operator_quote="probe")
    errs += [x for x in da.problems(probe) if not x.startswith(f"{da.R_SCHEMA}:id")]
    return rec, errs


def _v_row(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """A review row, validated by the direct row submit's own ``validate_row`` (PR #25045)."""
    from src.web.api.routers import live_review_direct as lrd

    errs = [f"unknown param {k}" for k in p if k != "row"]
    row = p.get("row")
    why = lrd.validate_row(row)
    if why:
        errs.append(f"row: {why}")
    return ({"row": row} if isinstance(row, dict) else {}), errs


_PING_PRIORITIES = ("urgent", "high", "normal", "low")
_PING_TARGETS = ("claude", "trader")
_PING_KINDS = ("decision", "state_change", "lifecycle")
PING_MAX_CHARS = 3500


def _v_ping(p: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The send-ping § 2 row's params, checked HERE instead of warned-and-defaulted in the wrapper: a direct call
    gets a 400 for a bad priority / target rather than a silently different ping. ``kind`` stays blank =
    passthrough (the operator's own words; ``send_ping_action.sh`` header), and a kind needs ``why``."""
    keys = ("message", "priority", "target", "kind", "why", "unproven")
    errs = [f"unknown param {k}" for k in p if k not in keys]
    vals = {k: ("" if p.get(k) is None else str(p.get(k))) for k in keys}
    msg = vals["message"].strip()
    pri = vals["priority"].strip() or "normal"
    tgt = vals["target"].strip() or "claude"
    kind = vals["kind"].strip()
    if not msg:
        errs.append("message: a non-empty message is required")
    elif len(msg) > PING_MAX_CHARS:
        errs.append(f"message: at most {PING_MAX_CHARS} chars (got {len(msg)})")
    if pri not in _PING_PRIORITIES:
        errs.append(f"priority must be one of {', '.join(_PING_PRIORITIES)}")
    if tgt not in _PING_TARGETS:
        errs.append(f"target must be one of {', '.join(_PING_TARGETS)}")
    if kind and kind not in _PING_KINDS:
        errs.append(f"kind must be blank (passthrough) or one of {', '.join(_PING_KINDS)}")
    if kind and not vals["why"].strip():
        errs.append("why: required when kind is set")
    if vals["unproven"].strip() and not kind:
        errs.append("unproven: needs kind")
    return {"message": msg, "priority": pri, "target": tgt, "kind": kind, "why": vals["why"].strip(),
            "unproven": vals["unproven"].strip()}, errs


# ─────────────────────────────────────────────────────────────────────────── the registry

Runner = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class OpsAction:
    name: str
    tier: int
    #: What it ports: a system-actions § 2 action name, or the non-workflow path it replaces.
    ports: str
    validate: Callable[[Dict[str, Any]], Tuple[Dict[str, Any], List[str]]]
    run: str                      # the name of the run_* function below
    timeout_s: int = 600
    notes: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


REGISTRY: Dict[str, OpsAction] = {a.name: a for a in (
    OpsAction("live-review-row", 1, "POST /api/bot/live-review/rows (the direct row submit, PR #25045)", _v_row,
              "run_live_review_row", 60,
              "delegates to the direct row submit: same validation and create-only write; the live trader's "
              "ltr-direct-rows thread and the dispatcher decide what executes, unchanged"),
    OpsAction("directed-action", 2, "scripts/ops/directed_action.py submit (the directed/actions push)",
              _v_directed, "run_directed_action", 900,
              "one directed_action/v1 record into the phase-1 spool -> the live trader's spool-pass -> "
              "live_review_apply.run()"),
    OpsAction("amend-prop-bracket", 2, "amend-prop-bracket", _v_prop_bracket, "run_amend_prop_bracket", 300),
    OpsAction("sync-now", 1, "the ict-git-sync timer's own unit (one early tick)", _v_none, "run_sync_now", 900,
              "starts ict-git-sync.service once: it deploys exactly what the timer would within ~5 min"),
    OpsAction("restart-service", 2, "restart-bot-service", _v_restart, "run_restart_service", 180,
              "the trader goes through scripts/ops/restart_bot.sh; the other units are set-env's allowlist"),
    OpsAction("set-env", 2, "set-env", _v_set_env, "run_set_env", 240,
              "scripts/ops/set_env.sh: one allowlisted key, then restart the named service"),
    OpsAction("send-ping", 1, "send-ping", _v_ping, "run_send_ping", 60,
              "scripts/ops/send_ping_action.sh with the § 2 row's params: one Telegram message, no mutation; "
              "a class-limited ping that was withheld reads verdict withheld, never sent"),
    *(OpsAction(name, 1, name, _v_none, "run_report", 120,
                f"scripts/ops/{script}: read-only, no params; the § 2 row's own wrapper, stdout is the result",
                {"script": script})
      for name, script in (("status-check", "status_check.sh"), ("disk-usage-report", "disk_usage_report.sh"),
                           ("list-listening-ports", "list_listening_ports.sh"))),
)}


# ─────────────────────────────────────────────────────────────────────────── submit / read (web API side)

def new_job_id(action: str, now: datetime) -> str:
    return f"OPS-{now.strftime('%Y%m%dT%H%M%SZ')}-{action}-{secrets.token_hex(3)}"


def _local_row_seen(review_id: str, job_id: str, root: Optional[Path]) -> Optional[str]:
    """The job that already submitted ``review_id`` through this channel, else None (records this one)."""
    path = _dir("", root) / "rows_submitted.json"
    seen = _load(path) or {}
    if review_id in seen:
        return seen[review_id]
    seen[review_id] = job_id
    _write_json(path, seen)
    return None


def submit(body: Dict[str, Any], *, root: Optional[Path] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Validate one call and write its job. Raises :class:`OpsError` (the API's status) on a refusal."""
    now = now or _now()
    name = str(body.get("action") or "").strip()
    session = str(body.get("session") or "").strip()
    reason = str(body.get("reason") or "").strip()
    quote = body.get("operator_quote")
    quote = quote.strip() if isinstance(quote, str) else ""
    params = body.get("params") if body.get("params") is not None else {}
    if not session:
        raise OpsError(400, "`session` is required (who is calling: the Claude session id or name)")
    if not reason:
        raise OpsError(400, "`reason` is required")
    if not isinstance(params, dict):
        raise OpsError(400, "`params` must be an object")
    if name in REFUSED_BY_NAME:
        raise OpsError(403, f"refused: {name} is not an ops-channel action. {REFUSED_BY_NAME[name]}")
    spec = REGISTRY.get(name)
    if spec is None:
        raise OpsError(404, f"{name!r} is not ported to the ops channel (wave 1: {', '.join(REGISTRY)}); "
                            "use the system-actions workflow (docs/claude/system-actions.md)")
    if spec.tier >= 3:                       # defence in depth; the parity test pins the registry below 3
        raise OpsError(403, f"refused: {name} is Tier {spec.tier}; Tier 3 stays in git")
    clean, errs = spec.validate(params)
    if errs:
        raise OpsError(400, f"{name}: " + "; ".join(errs[:8]))
    job_id = new_job_id(name, now)
    if name == "live-review-row":
        with _lock(root):
            prior = _local_row_seen(clean["row"]["review_id"], job_id, root)
        if prior:
            raise OpsError(409, f"duplicate review_id {clean['row']['review_id']}: already submitted as {prior}; "
                                "a new review row is a new decision")
    job: Dict[str, Any] = {"job_id": job_id, "action": name, "tier": spec.tier, "params": clean,
                           "session": session, "reason": reason, "operator_quote": quote or None,
                           "created_at": _iso(now)}
    needs_ok = spec.tier >= 2 or not TIER1_AUTORUN
    if needs_ok and not quote:
        # The ask itself is created by the RUNNER (ops.offer -> trade_approvals.offer_ops), on the trader's tree,
        # where both polled bots read the approvals store; the web API only queues the job.
        job.update(state=AWAITING, approval={"state": "offer_queued"})
        save_job(job, root)
        _write_json(_dir("queue", root) / f"{job_id}.json", {"job_id": job_id})
        journal("awaiting_approval", job, root)
        return _public(job)
    job["state"] = QUEUED
    job["authority"] = "operator_quote" if quote else ("tier1_autorun" if spec.tier == 1 else None)
    save_job(job, root)
    _write_json(_dir("queue", root) / f"{job_id}.json", {"job_id": job_id})
    journal("queued", job, root)
    return _public(job)


def _public(job: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in job.items() if k != "approval"}
    if job.get("approval"):
        out["approval"] = {k: v for k, v in job["approval"].items() if k != "token"}
    return out


def read_job(job_id: str, *, root: Optional[Path] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The job record plus a ``read_state`` (never a silent "queued" when the runner is not picking up)."""
    if not JOB_ID_RE.match(job_id or ""):
        raise OpsError(400, "not an ops job id")
    job = _load(job_path(job_id, root))
    if job is None:
        raise OpsError(404, f"no job {job_id}")
    now = now or _now()
    _expire_if_due(job, now, root)
    out = _public(job)
    out["read_state"] = "measured"
    if job.get("state") == QUEUED or (job.get("approval") or {}).get("state") == "offer_queued":
        age = (now - (_ts(job.get("queued_at") or job.get("created_at")) or now)).total_seconds()
        out["queued_s"] = round(age, 1)
        if age > RUNNER_LAG_S:
            out["read_state"] = "runner_not_picking_up"
    return out


def _expire_if_due(job: Dict[str, Any], now: datetime, root: Optional[Path]) -> bool:
    ap = job.get("approval") or {}
    if job.get("state") != AWAITING or ap.get("state") != "pending":
        return False
    exp = _ts(ap.get("expires_at"))
    if exp is None or now <= exp:
        return False
    ap["state"] = "expired"
    job.update(state=EXPIRED, finished_at=_iso(now), detail="the approval card expired; re-submit the call")
    save_job(job, root)
    journal("expired", job, root)
    return True


# ─────────────────────────────────────────────────────────────────────────── the Approve / Reject ask

def offer(job: Dict[str, Any], *, root: Optional[Path] = None, send: Optional[Callable[..., bool]] = None,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """Send the operator the phase-1 Approve / Reject ask for an awaiting job (``trade_approvals.offer_ops``: the
    same store, ``tapv`` buttons, chat check, expiry and decide() as a trade ask). Runs in the RUNNER, on the trader
    tree, so the ask lands in the store both polled bots read."""
    from src.runtime import trade_approvals

    res = trade_approvals.offer_ops(job, send=send, now=now)
    ap = job.setdefault("approval", {})
    ap.update(state="pending" if res.get("token") else "offer_failed", token=res.get("token"),
              expires_at=res.get("expires_at"), card_sent=res.get("sent"),
              fallback_alert=res.get("fallback_alert"), offer_state=res.get("state"))
    if not res.get("token"):
        job.update(state=FAILED, finished_at=_iso(now or _now()),
                   detail=f"could not create the approval ask: {res.get('detail')}")
    save_job(job, root)
    journal("offered", job, root, card_sent=res.get("sent"), offer_state=res.get("state"))
    return job


def on_approval(job_id: str, choice: str, *, quote: str, source: str, root: Optional[Path] = None,
                now: Optional[datetime] = None) -> Tuple[bool, str]:
    """``trade_approvals.decide`` hands an ops ask's outcome here. Approve queues the job with the tap as its
    authority; reject closes it. (ok, detail)."""
    now = now or _now()
    with _lock(root):
        job = _load(job_path(job_id, root)) if JOB_ID_RE.match(job_id or "") else None
        if job is None:
            return False, f"no ops job {job_id}"
        if job.get("state") != AWAITING:
            return False, f"ops job {job_id} is {job.get('state')}, not awaiting approval"
        ap = job.setdefault("approval", {})
        if choice != "approve":
            ap.update(state="rejected", decided_at=_iso(now), decided_via=source)
            job.update(state=REJECTED, finished_at=_iso(now), detail=f"rejected by the operator ({source})")
            save_job(job, root)
            journal("rejected", job, root)
            return True, "rejected"
        ap.update(state="approved", decided_at=_iso(now), decided_via=source)
        job.update(state=QUEUED, queued_at=_iso(now), authority=f"{source}_approve", operator_quote=quote)
        save_job(job, root)
        _write_json(_dir("queue", root) / f"{job_id}.json", {"job_id": job_id})
        journal("approved", job, root, source=source)
    return True, "queued"


# ─────────────────────────────────────────────────────────────────────────── the runner (ict-ops-runner)

def _tail(text: str) -> str:
    return (text or "")[-STDOUT_TAIL:]


def _script(argv: List[str], env: Dict[str, str], timeout_s: int) -> Dict[str, Any]:
    try:
        r = subprocess.run(argv, cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True,
                           timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return {"exit": 124, "stdout_tail": _tail(out), "detail": f"timed out after {timeout_s}s"}
    except OSError as exc:
        return {"exit": 127, "stdout_tail": "", "detail": f"did not start: {type(exc).__name__}: {exc}"}
    return {"exit": r.returncode, "stdout_tail": _tail((r.stdout or "") + (("\n[stderr]\n" + r.stderr)
                                                                            if r.stderr else ""))}


def run_amend_prop_bracket(job: Dict[str, Any]) -> Dict[str, Any]:
    wrapper = ROOT / "scripts" / "ops" / "amend_prop_bracket_action.sh"
    if not wrapper.is_file():
        return {"exit": 3, "detail": "not_deployed: scripts/ops/amend_prop_bracket_action.sh is not on this VM yet "
                                     "(PROP-BRACKET-APPLY, PR #25016)"}
    p = job["params"]
    env = {"ACCOUNT_ID": p["account"], "ACTION_TICKET_ID": p["ticket_id"], "ACTION_NEW_TP": p["new_tp"],
           "ACTION_NEW_SL": p["new_sl"], "ACTION_CLEAR_TP": "true" if p["clear_tp"] else "",
           "ACTION_REASON": f"{job['reason']} [ops {job['job_id']}, {job['session']}]",
           "ACTION_APPLY": "true" if p["apply"] else ""}
    return _script(["bash", str(wrapper)], env, REGISTRY["amend-prop-bracket"].timeout_s)


def _sudo() -> List[str]:
    return [] if os.geteuid() == 0 else ["sudo", "-n"]


def run_sync_now(job: Dict[str, Any]) -> Dict[str, Any]:
    res = _script([*_sudo(), "systemctl", "start", "ict-git-sync.service"], {}, REGISTRY["sync-now"].timeout_s)
    log = _script([*_sudo(), "journalctl", "-u", "ict-git-sync.service", "-n", "40", "--no-pager", "-o", "cat"],
                  {}, 30)
    res["stdout_tail"] = _tail(f"{res.get('stdout_tail', '')}\n===== ict-git-sync journal (last 40) =====\n"
                               f"{log.get('stdout_tail', '')}")
    return res


def run_restart_service(job: Dict[str, Any]) -> Dict[str, Any]:
    svc = job["params"]["service"]
    if svc == "ict-trader-live.service":
        return _script(["bash", str(ROOT / "scripts" / "ops" / "restart_bot.sh")], {},
                       REGISTRY["restart-service"].timeout_s)
    res = _script([*_sudo(), "systemctl", "restart", svc], {}, 120)
    state = "unknown"
    for _ in range(15):
        st = _script([*_sudo(), "systemctl", "is-active", svc], {}, 10)
        state = (st.get("stdout_tail") or "").strip().splitlines()[0] if st.get("stdout_tail") else "unknown"
        if state == "active":
            break
        time.sleep(2)
    res["post_state"] = state
    if res.get("exit") == 0 and state != "active":
        res.update(exit=1, detail=f"{svc} is {state} after the restart")
    return res


def run_set_env(job: Dict[str, Any]) -> Dict[str, Any]:
    p = job["params"]
    env = {"ENV_KEY": p["key"], "ENV_VALUE": p["value"], "ENV_SERVICE": p["service"],
           "ENV_FILE_TARGET": p["env_file"]}
    return _script(["bash", str(ROOT / "scripts" / "ops" / "set_env.sh")], env, REGISTRY["set-env"].timeout_s)
def run_send_ping(job: Dict[str, Any]) -> Dict[str, Any]:
    """The send-ping system-action's own wrapper (audit row, DATA_DIR inbox, withheld marker), env-threaded exactly
    as ``system-actions.yml`` does. ``verdict`` separates a queued ping from one the class limiter withheld."""
    wrapper = ROOT / "scripts" / "ops" / "send_ping_action.sh"
    p = job["params"]
    env = {"ACTION_MESSAGE": p["message"], "ACTION_PRIORITY": p["priority"], "ACTION_TARGET": p["target"],
           "ACTION_KIND": p["kind"], "ACTION_WHY": p["why"], "ACTION_UNPROVEN": p["unproven"]}
    res = _script(["bash", str(wrapper)], env, REGISTRY["send-ping"].timeout_s)
    out = res.get("stdout_tail") or ""
    if res.get("exit") == 0:
        res["verdict"] = "withheld" if "WITHHELD" in out else "queued"
    return res


def run_report(job: Dict[str, Any]) -> Dict[str, Any]:
    """A parameterless, read-only § 2 wrapper (the script is fixed by the registry entry, never by the caller)."""
    spec = REGISTRY[job["action"]]
    wrapper = ROOT / "scripts" / "ops" / spec.extra["script"]
    if not wrapper.is_file():
        return {"exit": 3, "detail": f"not_deployed: scripts/ops/{spec.extra['script']} is not on this VM"}
    return _script(["bash", str(wrapper)], {}, spec.timeout_s)


def run_live_review_row(job: Dict[str, Any], *, direct_root: Optional[Path] = None,
                        logs: Optional[Path] = None) -> Dict[str, Any]:
    """Delegate to the direct row submit (TRADE-ACTION-DIRECT-PATH phase 2, PR #25045): the SAME validation,
    already-seen check and create-only write as ``POST /api/bot/live-review/rows``, into the dir the live trader's
    ``ltr-direct-rows`` thread reads every 2 s (its ``process_row`` then dispatches or asks the operator). This
    action adds no second row path; it only lets the ops channel carry that submit. Runs in the runner, on the
    trader's tree, so the file lands where the thread looks."""
    from src.runtime import live_review_rows as rows_lib
    from src.runtime import live_review_rows_watch as w
    from src.web.api.routers import live_review_direct as lrd

    row = job["params"]["row"]
    why = lrd.validate_row(row)
    if why:
        return {"exit": 2, "detail": f"refused: {why}"}
    rid = row["review_id"]
    if lrd._already_seen(rid, logs or w.log_dir()):
        return {"exit": 2, "detail": f"refused: {rid} was already handled (a new review is a new decision)"}
    dest = (direct_root or w.direct_root()) / rows_lib.row_path(rid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, indent=1, sort_keys=True) + "\n").encode()
    tmp = Path(str(dest) + f".{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.link(tmp, dest)                       # create-only, exactly as the route
    except FileExistsError:
        return {"exit": 2, "detail": f"refused: {rid} was already submitted"}
    finally:
        tmp.unlink(missing_ok=True)
    return {"exit": 0, "detail": f"queued {rows_lib.row_path(rid)} for the live trader's direct-rows pass",
            "receipt": f"/api/bot/live-review/rows/{rid}"}


def run_directed_action(job: Dict[str, Any], *, spool_root: Optional[Path] = None,
                        receipts: Optional[Path] = None, wait_s: float = 120.0,
                        sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """Build the record NOW (an approval minutes later is not born stale), drop it into the phase-1 spool the live
    trader's directed thread runs every 2 s (``directed_action.py spool-pass``: the SAME vm_pass, state file,
    retries, venue deferral, receipt and ping as a branch record; ``live_review_apply.run()`` and each account's
    RiskManager), then wait up to ``wait_s`` for its receipt. No receipt in time is exit 3 with the record id: the
    trader keeps it and the receipt lands later in ``log_file?name=directed_actions``."""
    from src.runtime import directed_actions as da
    from src.runtime import trade_approvals as ta
    sys.path.insert(0, str(ROOT))
    from scripts.ops import directed_action as dact

    now = _now()
    rec = dict(job["params"], schema=da.SCHEMA, id=da.new_id(job["params"]["action"], now, secrets.token_hex(3)),
               created_at=_iso(now), directed_by=f"ops:{job['session']}", operator_quote=job["operator_quote"])
    probs = da.problems(rec, path=da.record_path(rec["id"]))
    if probs:
        return {"exit": 2, "detail": "refused: " + ", ".join(probs[:6]), "record_id": rec["id"]}
    d = (spool_root or ta.spool_root()) / da.RECORDS_DIR
    d.mkdir(parents=True, exist_ok=True)
    _write_json(d / f"{rec['id']}.json", rec)
    path = receipts or (dact.log_dir() / "receipts.jsonl")
    waited = 0.0
    while True:
        try:
            for ln in reversed(path.read_text().splitlines()[-2000:]):
                if rec["id"] in ln:
                    r = json.loads(ln)
                    if r.get("id") == rec["id"]:
                        v = r.get("verdict")
                        code = 0 if v in ("applied", "dry_run") else int(r.get("exit") or 1)
                        return {"exit": code, "record_id": rec["id"], "verdict": v, "detail": r.get("detail"),
                                "receipt": r}
        except (OSError, ValueError):
            pass
        if waited >= wait_s:
            return {"exit": 3, "record_id": rec["id"], "verdict": "no_receipt_yet",
                    "detail": f"spooled; no receipt after {wait_s:.0f}s (the live trader keeps it: read "
                              "log_file?name=directed_actions)"}
        sleep(2.0)
        waited += 2.0


RUNNERS: Dict[str, Runner] = {
    "run_live_review_row": run_live_review_row,
    "run_directed_action": run_directed_action,
    "run_amend_prop_bracket": run_amend_prop_bracket,
    "run_sync_now": run_sync_now,
    "run_restart_service": run_restart_service,
    "run_set_env": run_set_env,
    "run_send_ping": run_send_ping,
    "run_report": run_report,
}


def run_job(job_id: str, *, root: Optional[Path] = None, runners: Optional[Dict[str, Runner]] = None,
            send: Optional[Callable[..., bool]] = None) -> Dict[str, Any]:
    """Run one claimed job. Never raises: every failure becomes the job's ``failed`` state."""
    job = _load(job_path(job_id, root))
    if job is None:
        return {"job_id": job_id, "state": FAILED, "detail": "job record missing"}
    if job.get("state") == AWAITING and (job.get("approval") or {}).get("state") == "offer_queued":
        return offer(job, root=root, send=send)
    if job.get("state") != QUEUED:
        journal("skipped_not_queued", job, root)
        return job
    spec = REGISTRY.get(job.get("action") or "")
    authority_ok = (job.get("operator_quote") or (spec and spec.tier == 1 and TIER1_AUTORUN))
    if spec is None or spec.tier >= 3 or not authority_ok:
        job.update(state=REFUSED, finished_at=_iso(_now()),
                   detail="refused at run time: unknown action, Tier 3, or no operator authority on a job that needs it")
        save_job(job, root)
        journal("refused", job, root)
        return job
    job.update(state=RUNNING, started_at=_iso(_now()))
    save_job(job, root)
    journal("started", job, root)
    try:
        res = (runners or RUNNERS)[spec.run](job)
    except Exception as exc:  # noqa: BLE001 -- contained per job (no halting)
        res = {"exit": 1, "detail": f"runner raised {type(exc).__name__}: {exc}"[:400]}
    done = _now()
    code = int(res.get("exit") if res.get("exit") is not None else 1)
    job.update(state=DONE if code == 0 else FAILED, finished_at=_iso(done), exit=code,
               result={k: v for k, v in res.items() if k != "exit"})
    st = _ts(job.get("started_at"))
    if st:
        job["run_s"] = round((done - st).total_seconds(), 1)
    save_job(job, root)
    journal("finished", job, root, exit=code, detail=str(res.get("detail") or "")[:300])
    return job


def run_queue(*, root: Optional[Path] = None, runners: Optional[Dict[str, Runner]] = None,
              max_jobs: int = 200, send: Optional[Callable[..., bool]] = None) -> List[Dict[str, Any]]:
    """Drain ``queue/``: claim each file by an atomic rename into ``running/`` (so a queue file never stays behind
    to re-trigger the path unit), run it, remove the claim. Loops until the queue is empty."""
    out: List[Dict[str, Any]] = []
    q, running = _dir("queue", root), _dir("running", root)
    for stale in running.glob("*.json"):            # a runner killed mid-job: say so, never re-run it silently
        jid = stale.stem
        job = _load(job_path(jid, root))
        if job and job.get("state") == RUNNING:
            job.update(state=FAILED, finished_at=_iso(_now()), detail="the runner stopped while this job ran; "
                       "check the VM state before re-submitting")
            save_job(job, root)
            journal("interrupted", job, root)
        stale.unlink(missing_ok=True)
    for _ in range(max_jobs):
        items = sorted(q.glob("OPS-*.json"))
        if not items:
            break
        item = items[0]
        claim = running / item.name
        try:
            os.replace(item, claim)
        except OSError:
            continue
        out.append(run_job(item.stem, root=root, runners=runners, send=send))
        claim.unlink(missing_ok=True)
    for junk in q.glob("*"):                        # anything else in the queue would re-trigger the path forever
        if not junk.name.startswith("OPS-"):
            junk.rename(_dir("rejected_files", root) / junk.name)
    return out

#!/usr/bin/env python3
# wiring: .github/workflows/research-watchdog.yml (cron */15 + dispatch), tests/test_research_watchdog.py
"""RESEARCH-WATCHDOG: the research pipeline checks itself and escalates, with no Claude tokens spent.

WHY (operator, 2026-10-13): the dispatcher started nothing from 12:50Z to >= 15:58Z and nobody noticed until a
Claude check; the research-ops routine runs 4x/day. "The resources themselves must diagnose and raise a flag."

WHY THE EXISTING GUARD MISSED IT (check_research_queue_dispatch_liveness.py, RQ-OPS-2) -- three independent reasons:
  1. It runs INSIDE research-queue-dispatch.yml. An alarm housed in the job it watches is silent exactly when that
     job does not run, or dies before its last step (check_research_queue_throughput.py's docstring records the
     same lesson; it was moved to schedule-keeper for it).
  2. It grades a RECEIPT's age against 48 h. A dispatcher that stalled at 12:50Z reads "fresh" until 12:50Z + 2 days.
  3. The receipt proves a RUN happened, not that anything was fired or that the dispatch job even started: a run
     whose dispatch job is skipped/queued still leaves the receipt fresh, and the receipt only lands on main
     after a CI cycle (35-60 min), so it lags the thing it attests.
This module runs from its own cron, grades the dispatch JOB (not the run), and also grades the queue floor, each
compute backend, the collector and stranded stamps.

CHECKS, each with an explicit read_state -- `could_not_look` is never `ok`:
  dispatcher        minutes since a run's `dispatch` job STARTED; a dispatch job stuck past its normal length
  dispatcher_fires  runnable units exist, nothing queued/running, and nothing started for fires_idle_minutes
  queue             runnable < floor (queue_replenish.runnable(), which follows dispatchable())  -- immediate
  backend:<name>    runnable units are routed to the backend, yet nothing is in flight or has started on it
  collector         completed runs whose result is not on main after collector_stuck_minutes
  stamps            open automation/research-queue-stamp-* PRs older than STRANDED_STAMP_HOURS

SELF-HEAL FIRST, ONCE PER INCIDENT: re-fire ONE dispatch run (it also adopts stranded stamps -- dispatch_queue.py
stranded_stamp_adoptions, the existing re-land path), wait, re-check. Still bad (or `queue`, immediately) ->
ESCALATE: one comment on the standing "ops-flags (do not merge)" PR (the manager subscribes to its activity, so each
comment wakes it), one Telegram message on the operator SYSTEM channel (direct sendMessage with TELEGRAM_BOT_TOKEN + TELEGRAM_SYSTEM_CHAT_ID/TELEGRAM_CHAT_ID; send-ping only as a fallback if that fails), one row in
comms/research/ops/watchdog_incidents.jsonl. A later run that finds the check healthy posts ONE resolved comment +
ping. No halting: nothing here disables or stops any pipeline; an unreadable probe is retried, then flagged once.

Dedupe state is the PR's own comments (a hidden marker per event) merged with the committed ledger; whichever has the
newest event for a check wins.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

CONFIG = _REPO / "scripts" / "research" / "research_watchdog.yaml"
LEDGER = _REPO / "comms" / "research" / "ops" / "watchdog_incidents.jsonl"
DISPATCH_WORKFLOW = "research-queue-dispatch.yml"
STAMP_PREFIX = "automation/research-queue-stamp"
# The FLOOR of the research-compute set, never the whole of it. ⚠️ MEASURED 2026-10-16 09:36Z (lane
# RESEARCH-DISPATCH-STALL-1016): this tuple WAS the whole set, so the dispatcher's 08:12Z and 08:57Z fires -- 12
# research-harness-dispatch.yml runs, all created, their results landed on main -- were invisible here and
# dispatcher_fires escalated "no research compute run started for 160 min". The dispatcher counts every workflow a
# unit routes to (dispatch_queue.research_workflow_names); this watchdog now unions in the workflow every RUNNABLE
# unit resolves to (queue_facts -> compute_workflows), so a new route can never fall outside the count again.
RESEARCH_WORKFLOWS = ("research-script-run.yml", "research-script-run-trainer.yml", "research-script-run-kaggle.yml",
                      "research-script-run-kaggle-cpu.yml")
STALE_ACTIVE_HOURS = 24.0     # a run "in flight" longer than this is stuck debris, not load (dispatch_queue.STALE_PRESSURE_HOURS)
OK, BAD, CNL = "ok", "bad", "could_not_look"


# ── config / time ─────────────────────────────────────────────────────────────────────────────────────────
def load_config(path: Path = CONFIG) -> Dict[str, Any]:
    import yaml
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for k in ("thresholds", "ops_flags"):
        if not isinstance(cfg.get(k), dict):
            raise ValueError(f"{path}: missing `{k}:` block")
    return cfg


def _ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _age_min(raw: Any, now: datetime) -> Optional[float]:
    d = _ts(raw)
    return None if d is None else (now - d).total_seconds() / 60.0


def verdict(check: str, state: str, detail: str, *, evidence: Optional[dict] = None, immediate: bool = False,
            heal: Optional[str] = None) -> Dict[str, Any]:
    return {"check": check, "state": state, "detail": detail, "evidence": evidence or {}, "immediate": immediate,
            "heal": heal}


# ── the checks (pure: facts in, verdict out) ─────────────────────────────────────────────────────────────
def check_dispatcher(runs: Optional[list], jobs_for: Callable[[int], Optional[list]], now: datetime,
                     th: dict) -> Dict[str, Any]:
    lim = float(th["dispatcher_no_start_minutes"])
    if runs is None:
        return verdict("dispatcher", CNL, "could not list research-queue-dispatch runs", heal=None)
    if not runs:
        return verdict("dispatcher", BAD, "no research-queue-dispatch run exists at all (0 runs listed)", heal="dispatch")
    run_ages = [a for a in (_age_min(r.get("created_at"), now) for r in runs) if a is not None]
    if not run_ages:
        return verdict("dispatcher", CNL, "dispatch runs listed but none carried a readable created_at")
    newest_run_age = min(run_ages)
    if newest_run_age > lim:
        return verdict("dispatcher", BAD, f"no dispatch run CREATED for {newest_run_age:.0f} min (limit {lim:g})",
                       evidence={"newest_run_age_min": round(newest_run_age, 1), "runs_listed": len(runs)}, heal="dispatch")
    examined = sorted(runs, key=lambda r: str(r.get("created_at")), reverse=True)[:8]
    starts: List[float] = []
    stuck: List[str] = []
    lookups_failed = 0
    for r in examined:
        jobs = jobs_for(int(r["id"]))
        if jobs is None:
            lookups_failed += 1
            continue
        for j in jobs:
            if str(j.get("name")) != "dispatch":
                continue
            st, concl = str(j.get("status")), str(j.get("conclusion"))
            if j.get("started_at") and concl != "skipped":
                age = _age_min(j["started_at"], now)
                if age is not None:
                    starts.append(age)
                if st == "in_progress" and age is not None and age > float(th["dispatcher_job_running_stuck_minutes"]):
                    stuck.append(f"run {r['id']} dispatch job running {age:.0f} min "
                                 f"(limit {th['dispatcher_job_running_stuck_minutes']}; its own timeout is 30)")
            elif st in ("queued", "pending", "waiting"):
                age = _age_min(j.get("created_at") or r.get("created_at"), now)
                if age is not None and age > float(th["dispatcher_job_pending_stuck_minutes"]):
                    stuck.append(f"run {r['id']} dispatch job {st} for {age:.0f} min "
                                 f"(limit {th['dispatcher_job_pending_stuck_minutes']}; blocked behind the concurrency group or no runner)")
    ev = {"newest_run_age_min": round(newest_run_age, 1), "runs_examined": len(examined),
          "job_lookups_failed": lookups_failed,
          "minutes_since_dispatch_job_started": round(min(starts), 1) if starts else None}
    if lookups_failed == len(examined):
        return verdict("dispatcher", CNL, "runs are recent but no run's jobs could be read -- cannot say a dispatch job started",
                       evidence=ev)
    if stuck:
        return verdict("dispatcher", BAD, "; ".join(stuck), evidence=ev, heal="dispatch")
    if not starts or min(starts) > lim:
        got = f"{min(starts):.0f} min ago" if starts else f"in none of the {len(examined) - lookups_failed} runs examined"
        return verdict("dispatcher", BAD, f"runs exist but the `dispatch` job last started {got} (limit {lim:g}); "
                       "skipped/queued runs are not starts", evidence=ev, heal="dispatch")
    return verdict("dispatcher", OK, f"dispatch job last started {min(starts):.0f} min ago (limit {lim:g})", evidence=ev)


def _active(runs: list, now: datetime) -> list:
    return [r for r in runs if str(r.get("status")) in ("queued", "in_progress", "waiting", "pending")
            and (_age_min(r.get("created_at"), now) or 0) <= STALE_ACTIVE_HOURS * 60]


def check_fires(runnable_n: Optional[int], research_runs: Optional[list], now: datetime, th: dict,
                workflows: Optional[List[str]] = None) -> Dict[str, Any]:
    lim = float(th["fires_idle_minutes"])
    if runnable_n is None or research_runs is None:
        return verdict("dispatcher_fires", CNL, "could not count runnable units or list research compute runs")
    if runnable_n == 0:
        return verdict("dispatcher_fires", OK, "nothing runnable, so nothing is owed a fire", evidence={"runnable": 0})
    act = _active(research_runs, now)
    ages = [a for a in (_age_min(r.get("created_at"), now) for r in research_runs) if a is not None]
    ev = {"runnable": runnable_n, "active_research_runs": len(act), "runs_listed": len(research_runs),
          "minutes_since_last_research_run_created": round(min(ages), 1) if ages else None,
          "workflows_counted": list(workflows) if workflows is not None else list(RESEARCH_WORKFLOWS)}
    if act:
        return verdict("dispatcher_fires", OK, f"{len(act)} research compute run(s) queued/in progress", evidence=ev)
    if ages and min(ages) <= lim:
        return verdict("dispatcher_fires", OK, f"newest research compute run created {min(ages):.0f} min ago (limit {lim:g})", evidence=ev)
    since = f"{min(ages):.0f} min" if ages else "ever (0 runs listed)"
    return verdict("dispatcher_fires", BAD, f"{runnable_n} runnable unit(s) but no research compute run started for {since} "
                   f"(limit {lim:g}) and none in flight", evidence=ev, heal="dispatch")


def check_queue(runnable_n: Optional[int], th: dict, extra: Optional[dict] = None) -> Dict[str, Any]:
    floor = int(th["runnable_floor"])
    if runnable_n is None:
        return verdict("queue", CNL, "could not count runnable units", immediate=True)
    ev = dict(extra or {}, runnable=runnable_n, floor=floor)
    if runnable_n == 0:
        return verdict("queue", BAD, f"queue EMPTY: 0 runnable units (floor {floor})", evidence=ev, immediate=True, heal="replenish")
    if runnable_n < floor:
        return verdict("queue", BAD, f"runnable {runnable_n} < floor {floor}", evidence=ev, immediate=True, heal="replenish")
    return verdict("queue", OK, f"runnable {runnable_n} >= floor {floor}", evidence=ev, immediate=True)


def window_position(windows: Optional[list], now: datetime) -> Optional[Dict[str, Any]]:
    """Where `now` sits against a backend's idle-window policy (research_compute.yaml backends.<b>.queue.windows_utc).
    None = no window policy. Else {inside, since_open_min, until_close_min, next_open} (minutes; next_open 'HH:MMZ')."""
    if not windows:
        return None
    from scripts.research import compute_router as cr
    wins = cr.parse_windows(windows)
    t = now.hour * 60 + now.minute
    for a, b in wins:
        if a <= t < b:
            return {"inside": True, "since_open_min": float(t - a), "until_close_min": float(b - t), "next_open": None}
    nxt = min((a for a, _ in wins if a > t), default=wins[0][0])
    return {"inside": False, "since_open_min": None, "until_close_min": None, "next_open": f"{nxt // 60:02d}:{nxt % 60:02d}Z"}


def check_backend(name: str, runnable_for: Optional[int], runs: Optional[list], now: datetime, th: dict,
                  quota: Optional[dict] = None, max_concurrent: Optional[int] = None,
                  windows: Optional[list] = None, min_need_minutes: Optional[float] = None,
                  due_later: int = 0) -> Dict[str, Any]:
    """`runnable_for` is the count DUE NOW (queue_facts `by_backend_due_now`); `due_later` the units that only the
    refill's look-ahead horizon counts -- reported, never alarmed on."""
    chk, lim = f"backend:{name}", float(th["backend_idle_minutes"])
    if runnable_for is None:
        return verdict(chk, CNL, "could not work out which runnable units route here")
    if runnable_for == 0 and due_later:
        return verdict(chk, OK, f"{due_later} unit(s) route here but none is due yet (the refill horizon counts them; "
                       "the dispatcher fires them when due), so idle is correct",
                       evidence={"runnable_for_backend": 0, "due_within_refill_horizon": due_later})
    if runnable_for == 0:
        return verdict(chk, OK, "no runnable unit is routed here, so idle is correct", evidence={"runnable_for_backend": 0})
    if runs is None:
        return verdict(chk, CNL, f"{runnable_for} runnable unit(s) route here but its runs could not be listed",
                       evidence={"runnable_for_backend": runnable_for})
    ev = {"runnable_for_backend": runnable_for, "runs_listed": len(runs)}
    if name == "kaggle":
        if not quota or quota.get("remaining") is None:
            return verdict(chk, CNL, "kaggle quota unreadable: cannot tell idle-by-quota from idle-by-fault", evidence=ev)
        if float(quota["remaining"]) < float(quota.get("floor_hours", 0)):
            return verdict(chk, OK, f"quota-bound: {quota['remaining']} GPU h left, under the {quota.get('floor_hours')} h floor "
                           "(units wait by design)", evidence=ev)
    act = _active(runs, now)
    ages = [a for a in (_age_min(r.get("created_at"), now) for r in runs) if a is not None]
    ev.update(active=len(act), minutes_since_last_start=round(min(ages), 1) if ages else None)
    # UNDERUTILISED (operator 2026-10-13): runnable work AND free slots. A reading, never an alert: it stays state OK
    # (so nothing reaches ops-flags or Telegram) and is recorded only in evidence / the weekly utilisation view.
    if max_concurrent is not None and len(act) < max_concurrent:
        ev.update(underutilised=True, max_concurrent=max_concurrent)
    if act:
        return verdict(chk, OK, f"{len(act)} run(s) queued/in progress", evidence=ev)
    if ages and min(ages) <= lim:
        return verdict(chk, OK, f"last run started {min(ages):.0f} min ago (limit {lim:g})", evidence=ev)
    # A windowed backend (the trainer: ML-DATA-OFF-TRAINER) releases units only into its idle windows, so idleness
    # OUTSIDE a window is the design working, not an incident; inside one the idle limit runs from the window's opening.
    pos = window_position(windows, now)
    if pos is not None:
        ev.update(window=pos, windows_utc=windows)
        if not pos["inside"]:
            return verdict(chk, OK, f"waiting for window (opens {pos['next_open']}): {runnable_for} runnable unit(s) held by "
                           "backends.<b>.queue.windows_utc, by design", evidence=ev)
        if min_need_minutes is not None and pos["until_close_min"] < float(min_need_minutes):
            return verdict(chk, OK, f"waiting for next window: no runnable unit fits the {pos['until_close_min']:.0f} min left "
                           f"(smallest needs ~{float(min_need_minutes):.0f} min incl. safety factor)", evidence=ev)
        if pos["since_open_min"] <= lim:
            return verdict(chk, OK, f"window opened {pos['since_open_min']:.0f} min ago (idle limit {lim:g} runs from the opening)",
                           evidence=ev)
        since = f"{min(pos['since_open_min'], min(ages)) if ages else pos['since_open_min']:.0f} min (inside its window)"
        return verdict(chk, BAD, f"idle with {runnable_for} runnable unit(s) routed here: nothing started on it for {since} "
                       f"(limit {lim:g}, counted from window open)", evidence=ev, heal="dispatch")
    since = f"{min(ages):.0f} min" if ages else "ever (0 runs listed)"
    return verdict(chk, BAD, f"idle with {runnable_for} runnable unit(s) routed here: nothing started on it for {since} "
                   f"(limit {lim:g})", evidence=ev, heal="dispatch")


def check_collector(status: Optional[dict], th: dict) -> Dict[str, Any]:
    lim = float(th["collector_stuck_minutes"])
    if status is None or status.get("read_error"):
        return verdict("collector", CNL, (status or {}).get("read_error") or "could not list completed research runs")
    unreadable = len(status.get("unreadable") or [])
    stuck = [x for x in status.get("landed") or [] if (x.get("age_minutes") or 0) > lim]
    lost = status.get("lost") or []
    ev = {"awaiting_collection": len(status.get("landed") or []), "stuck": len(stuck), "lost": len(lost),
          "unreadable": unreadable, "oldest_awaiting_min": max([x.get("age_minutes") or 0 for x in status.get("landed") or []] or [0])}
    if lost:
        return verdict("collector", BAD, f"{len(lost)} run(s) LOST their result (e.g. {lost[0].get('unit')} run {lost[0].get('run_id')}: "
                       f"{lost[0].get('why')})", evidence=ev)
    if stuck:
        s = stuck[0]
        return verdict("collector", BAD, f"{len(stuck)} completed run(s) not collected after > {lim:g} min "
                       f"(oldest {s.get('unit')} run {s.get('run_id')}, {s.get('age_minutes'):.0f} min)", evidence=ev, heal="dispatch")
    if unreadable:
        return verdict("collector", CNL, f"{unreadable} run(s) had unreadable artifacts; cannot say they are collected", evidence=ev)
    return verdict("collector", OK, f"{ev['awaiting_collection']} awaiting collection, none older than {lim:g} min", evidence=ev)


def check_stamps(prs: Optional[list], now: datetime, th: dict) -> Dict[str, Any]:
    hrs = float(th["stranded_stamp_hours"])
    if prs is None:
        return verdict("stamps", CNL, "could not list open PRs")
    stamp = [p for p in prs if str(((p.get("head") or {}).get("ref")) or "").startswith(STAMP_PREFIX)]
    old = [p for p in stamp if (_age_min(p.get("created_at"), now) or 0) > hrs * 60]
    ev = {"open_stamp_prs": len(stamp), "stranded": [p.get("number") for p in old], "prs_listed": len(prs)}
    if old:
        return verdict("stamps", BAD, f"{len(old)} stamp PR(s) open > {hrs:g} h: " + ", ".join(f"#{p.get('number')}" for p in old[:6]),
                       evidence=ev, heal="dispatch")
    return verdict("stamps", OK, f"{len(stamp)} open stamp PR(s), none older than {hrs:g} h", evidence=ev)


AUTOMATION_PREFIX = "automation/"


def check_conflicted_automation(prs: Optional[list], state_for: Callable[[int], Optional[str]], now: datetime,
                                th: dict) -> Dict[str, Any]:
    """Name every `automation/*` PR (stamp, receipt, capture-watch ...) that is CONFLICTING and older than the bound.

    A conflicted PR runs no checks and never merges, so the stamp/receipt it carries never lands (#18004, #18014,
    2026-10-14) and the failure surfaced as a false 'idle' alarm. `state_for(n)` is GitHub's `mergeable_state`;
    None = could not look, which is never read as clean."""
    mins = float(th.get("conflicted_automation_minutes", 45))
    if prs is None:
        return verdict("conflicted_automation", CNL, "could not list open PRs")
    auto = [p for p in prs if str(((p.get("head") or {}).get("ref")) or "").startswith(AUTOMATION_PREFIX)]
    old = [p for p in auto if (_age_min(p.get("created_at"), now) or 0) > mins]
    states = {p.get("number"): state_for(p.get("number")) for p in old}
    dirty = [n for n, st in states.items() if st == "dirty"]
    unread = [n for n, st in states.items() if st is None]
    ev = {"open_automation_prs": len(auto), "checked": len(old), "conflicting": dirty, "unreadable": unread}
    if dirty:
        refs = {p.get("number"): (p.get("head") or {}).get("ref") for p in old}
        return verdict("conflicted_automation", BAD,
                       f"{len(dirty)} automation PR(s) CONFLICTING with main for > {mins:g} min: "
                       + ", ".join(f"#{n} ({refs[n]})" for n in dirty[:6]), evidence=ev)
    if unread:
        return verdict("conflicted_automation", CNL, f"could not read mergeable_state for {len(unread)} PR(s)", evidence=ev)
    return verdict("conflicted_automation", OK, f"{len(auto)} open automation PR(s), none conflicting > {mins:g} min", evidence=ev)


def check_phone_heartbeat(res: Optional[dict], th: dict) -> Dict[str, Any]:
    """breakout_2's phone executor heartbeat, graded by scripts/ops/prop_silence.probe_phone_heartbeat (the SAME probe and
    the SAME 'live' definition -- config/accounts.yaml mode == live -- as the hourly attention watch). `res` is that probe's
    {status, detail} dict, or None when it could not be run. unknown is could_not_look, never ok."""
    lim = float(th["phone_heartbeat_max_minutes"])
    if not isinstance(res, dict) or res.get("status") not in ("ok", "breached", "unknown"):
        return verdict("phone_heartbeat", CNL, "phone-heartbeat probe could not be run")
    ev = {"limit_min": lim, "probe_detail": res.get("detail")}
    if res["status"] == "breached":
        return verdict("phone_heartbeat", BAD, f"{res.get('detail')} (watchdog limit {lim:g} min)", evidence=ev)
    if res["status"] == "unknown":
        return verdict("phone_heartbeat", CNL, str(res.get("detail")), evidence=ev)
    return verdict("phone_heartbeat", OK, str(res.get("detail")), evidence=ev)


# ── probes: every fact comes through here, so tests/fixtures replace all of GitHub ──────────────────────────
class GhProbe:
    """`gh`-backed. Each read retries (2 s, 4 s) before it returns None = could not look."""

    def __init__(self, repo: Optional[str] = None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY") or "{owner}/{repo}"

    def _gh(self, args: List[str], *, retries: int = 3) -> Optional[str]:
        for i in range(retries):
            try:
                p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
                if p.returncode == 0:
                    return p.stdout
            except (OSError, subprocess.SubprocessError):
                pass
            if i < retries - 1:
                time.sleep(2 * (i + 1))
        return None

    def _api(self, path: str, key: Optional[str] = None) -> Optional[Any]:
        out = self._gh(["api", path])
        if out is None:
            return None
        try:
            d = json.loads(out)
        except ValueError:
            return None
        return d.get(key) if key and isinstance(d, dict) else d

    def workflow_runs(self, wf: str, per_page: int = 20) -> Optional[list]:
        return self._api(f"repos/{self.repo}/actions/workflows/{wf}/runs?per_page={per_page}", "workflow_runs")

    def run_jobs(self, run_id: int) -> Optional[list]:
        return self._api(f"repos/{self.repo}/actions/runs/{run_id}/jobs?per_page=30", "jobs")

    def open_prs(self) -> Optional[list]:
        return self._api(f"repos/{self.repo}/pulls?state=open&per_page=100")

    def pr_merge_state(self, number: int) -> Optional[str]:
        """GitHub's `mergeable_state` ('dirty' = conflicting); None = could not look. The list endpoint omits it."""
        d = self._api(f"repos/{self.repo}/pulls/{number}")
        st = d.get("mergeable_state") if isinstance(d, dict) else None
        return None if st in (None, "unknown") else st

    def collector_status(self, window_hours: float, now: datetime) -> Optional[dict]:
        from scripts.research import collect_runner_results as crr
        runs = crr.completed_runs()
        if runs is None:
            return {"read_error": "gh run list failed -- could not look"}
        cut = now - timedelta(hours=window_hours)
        runs = [r for r in runs if (_ts(r.get("createdAt")) or now) >= cut]
        born = {int(r["databaseId"]): r.get("createdAt") for r in runs}
        res = crr.collect(_REPO, repo_slug=self.repo, runs=runs, dry_run=True)
        for x in res["landed"]:
            x["age_minutes"] = _age_min(born.get(int(x["run_id"])), now)
        return res

    def phone_probe(self, now: datetime) -> Optional[dict]:
        """prop_silence's own probe, reading the public API (GET /api/bot/prop/status is a public read)."""
        from scripts.ops import prop_silence as ps
        base = os.environ.get("WATCHDOG_API_BASE", "https://ict-bot.duckdns.org")

        def fetch(path: str):
            last = ("unreadable", "no attempt")
            for i in range(3):
                try:
                    with urllib.request.urlopen(base + path, timeout=15) as r:  # noqa: S310
                        return "read", json.loads(r.read().decode("utf-8"))
                except (OSError, ValueError) as exc:    # URLError is an OSError; retried, then reported as unreadable
                    last = ("unreadable", f"{type(exc).__name__}: {exc}")
                time.sleep(2 * (i + 1))
            return last
        try:
            return ps.probe_phone_heartbeat(now, fetch)
        except (ImportError, KeyError, AttributeError) as exc:
            print(f"watchdog: phone probe unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
            return None

    def kaggle_quota(self) -> dict:
        from scripts.research import compute_router as cr
        p = os.environ.get("KAGGLE_QUOTA_FILE")
        return cr.read_quota_file(p) if p and Path(p).exists() else {"note": "quota file not produced (no token / kaggle CLI failed)"}

    # ── effects ──
    def ops_flags_pr(self, title: str) -> Optional[int]:
        out = self._gh(["pr", "list", "--state", "open", "--search", f'"{title}" in:title', "--json", "number,title", "--limit", "20"])
        if out is None:
            return None
        try:
            for p in json.loads(out):
                if p.get("title") == title:
                    return int(p["number"])
        except (ValueError, TypeError, KeyError):
            return None
        return 0

    def pr_comments(self, number: int) -> Optional[list]:
        return self._api(f"repos/{self.repo}/issues/{number}/comments?per_page=100")

    def post_comment(self, number: int, body: str) -> bool:
        return self._gh(["pr", "comment", str(number), "--body", body]) is not None

    def dispatch(self, action: str) -> bool:
        if action == "replenish":
            return self._gh(["workflow", "run", "research-queue-replenish.yml", "-f", "target=25"]) is not None
        return self._gh(["workflow", "run", DISPATCH_WORKFLOW]) is not None

    def ping(self, message: str) -> bool:
        """Operator SYSTEM channel: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID by direct sendMessage -- the exact path
        claude-run-failure-alert.yml, research-loss-detector.yml and guards.yml use. Only if that send fails does it
        fall back to the send-ping system-action (the claude comms bot), so a flag is never dropped silently."""
        import urllib.parse
        import urllib.request
        # same resolution as src/bot/telegram_routes.system_route(): the trader bot token, TELEGRAM_SYSTEM_CHAT_ID if set else the shared chat
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_SYSTEM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
        if tok and chat:
            for i in range(3):
                try:
                    data = urllib.parse.urlencode({"chat_id": chat, "text": message[:3900]}).encode()
                    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=30) as r:
                        if r.status == 200 and json.loads(r.read().decode()).get("ok"):
                            return True
                except (OSError, ValueError):  # URLError/HTTPError are OSError; retried, then falls back below -- never reported as sent
                    pass
                time.sleep(2 * (i + 1))
        else:
            print("::warning::TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set: falling back to send-ping", file=sys.stderr)
        return self._gh(["workflow", "run", "system-actions.yml", "-f", "action=send-ping", "-f", f"message={message}",
                         "-f", "priority=high", "-f", "target=claude"]) is not None


class FixtureProbe:
    """Reads a JSON capture of GitHub's answers and RECORDS every effect instead of performing it."""

    def __init__(self, fx: dict):
        self.fx, self.effects = fx, []

    def _get(self, key: str) -> Any:
        return self.fx.get(key)

    def workflow_runs(self, wf: str, per_page: int = 20):  # inert: per_page — mirrors GhProbe's signature; fixtures are pre-sliced
        return (self._get("workflow_runs") or {}).get(wf)

    def run_jobs(self, run_id: int):
        return (self._get("run_jobs") or {}).get(str(run_id))

    def open_prs(self):
        return self._get("open_prs")

    def pr_merge_state(self, number: int):
        return (self._get("merge_states") or {}).get(str(number), "clean")

    def collector_status(self, window_hours: float, now: datetime):  # inert: window_hours — mirrors GhProbe's signature; inert: now — same
        return self._get("collector")

    def phone_probe(self, now: datetime):  # inert: now — mirrors GhProbe's signature
        return self._get("phone_probe")

    def kaggle_quota(self) -> dict:
        return self._get("kaggle_quota") or {"note": "no quota in fixture"}

    def ops_flags_pr(self, title: str):  # inert: title — mirrors GhProbe's signature
        return self._get("ops_flags_pr")

    def pr_comments(self, number: int):  # inert: number — mirrors GhProbe's signature
        return self._get("pr_comments")

    def post_comment(self, number: int, body: str) -> bool:
        self.effects.append({"post_comment": number, "body": body})
        return True

    def dispatch(self, action: str) -> bool:
        self.effects.append({"dispatch": action})
        return True

    def ping(self, message: str) -> bool:
        self.effects.append({"ping": message})
        return True


# ── facts about the queue (local checkout) ───────────────────────────────────────────────────────────────
def queue_facts(root: Path, now: datetime) -> Optional[dict]:
    """runnable count (queue_replenish.runnable -> dispatchable()), per-backend split, and what dispatchable()
    does NOT count. None = could not read the queue."""
    try:
        from scripts.research import compute_router as cr
        from scripts.research import queue_replenish as qr
        from scripts.research.dispatch_queue import due_within
        units, bad = qr.existing_units(root)
        cfg = cr.load_config()
        run_ids = qr.runnable(units, now=now)
        by_be: Dict[str, int] = {}
        # DUE NOW by the dispatcher's own rule (horizon 0). `runnable` looks DISPATCH_CYCLE_HOURS ahead because the
        # refill must top up before the dispatcher runs dry; a backend's IDLE alarm must not, or a weekly unit due in
        # five hours reads as stranded work (the trainer's giveback census RQ-20261014-9807-01, 2026-10-21 23:20Z:
        # watchdog "idle with 1 runnable unit ... 984 min" while dispatch_queue correctly said not due).
        due_now_be: Dict[str, int] = {}
        min_need: Dict[str, float] = {}
        unplaceable = 0
        wfs = {str(b["workflow"]).split("/")[-1] for b in cfg["backends"].values() if b.get("workflow")}
        for uid in run_ids:
            res = cr.plan(units[uid], cfg)
            if not res.ok:
                unplaceable += 1
                continue
            if res.workflow:
                wfs.add(str(res.workflow).split("/")[-1])
            by_be[str(res.backend)] = by_be.get(str(res.backend), 0) + 1
            if due_within(units[uid], now, 0.0):
                due_now_be[str(res.backend)] = due_now_be.get(str(res.backend), 0) + 1
            q = (cfg["backends"].get(str(res.backend)) or {}).get("queue") or {}
            if q.get("windows_utc"):    # the fit rule: est_minutes x safety_factor must fit before the window closes
                need = cr.est_hours(units[uid]) * 60.0 * float(q.get("safety_factor", 1.0))
                min_need[str(res.backend)] = min(need, min_need.get(str(res.backend), need))
        uncounted = sum(1 for u in units.values() if u.get("status") == "queued" and u.get("compute")
                        and not qr.dispatchable(u) and due_within(u, now, qr.DISPATCH_CYCLE_HOURS))
        return {"runnable": len(run_ids), "by_backend": by_be, "by_backend_due_now": due_now_be,
                "unplaceable": unplaceable, "units_total": len(units),
                "unreadable_units": len(bad), "backends": [n for n, b in cfg["backends"].items() if b.get("auto_route", True)],
                "backend_workflows": {n: b["workflow"] for n, b in cfg["backends"].items()},
                "compute_workflows": sorted(w for w in wfs if w.endswith((".yml", ".yaml"))
                                            and (root / ".github" / "workflows" / w).is_file()),
                "backend_max_concurrent": {n: b.get("max_concurrent") for n, b in cfg["backends"].items()},
                "backend_windows": {n: (b.get("queue") or {}).get("windows_utc") for n, b in cfg["backends"].items()},
                "backend_min_need_minutes": min_need,
                "router_style_due_not_counted_by_dispatchable": uncounted,
                "kaggle_floor_hours": float((cfg["backends"].get("kaggle", {}).get("quota") or {}).get("floor_hours") or 0)}
    except Exception as exc:  # allow-silent: printed to stderr, and the None return becomes a could_not_look verdict, never an ok
        print(f"watchdog: queue facts unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def compute_workflows(facts: Optional[dict]) -> List[str]:
    """The workflows whose runs count as research compute for dispatcher_fires: the RESEARCH_WORKFLOWS floor plus
    every backend workflow and every workflow a runnable unit resolves to (queue_facts). Unreadable facts fall back
    to the floor -- check_fires then reports could_not_look on the runnable count anyway."""
    return sorted(set(RESEARCH_WORKFLOWS) | set((facts or {}).get("compute_workflows") or ()))


def evaluate(probe: Any, cfg: dict, now: datetime, facts: Optional[dict]) -> List[Dict[str, Any]]:
    th = cfg["thresholds"]
    out = [check_dispatcher(probe.workflow_runs(DISPATCH_WORKFLOW, 20), probe.run_jobs, now, th)]
    research_runs: Optional[list] = []
    counted = compute_workflows(facts)
    for wf in counted:
        r = probe.workflow_runs(wf, 10)
        if r is None:
            research_runs = None
            break
        research_runs += r
    n = facts["runnable"] if facts else None
    out.append(check_fires(n, research_runs, now, th, counted))
    out.append(check_queue(n, th, {k: facts[k] for k in ("by_backend", "unplaceable", "router_style_due_not_counted_by_dispatchable")}
                           if facts else None))
    skip = set(cfg.get("backends_not_graded") or [])
    quota = None
    for be in (facts["backends"] if facts else ["github_runner", "trainer", "kaggle"]):
        if be in skip:
            continue
        if be == "kaggle":
            q = probe.kaggle_quota()
            quota = {"remaining": q.get("remaining"), "floor_hours": facts["kaggle_floor_hours"] if facts else 0}
        _h = facts["by_backend"].get(be, 0) if facts else None
        _now_n = (facts.get("by_backend_due_now", facts["by_backend"]).get(be, 0)) if facts else None
        out.append(check_backend(be, _now_n,
                                 probe.workflow_runs(facts["backend_workflows"][be], 10) if facts else None, now, th, quota,
                                 (facts.get("backend_max_concurrent") or {}).get(be) if facts else None,
                                 (facts.get("backend_windows") or {}).get(be) if facts else None,
                                 (facts.get("backend_min_need_minutes") or {}).get(be) if facts else None,
                                 due_later=max(0, (_h or 0) - (_now_n or 0))))
    out.append(check_collector(probe.collector_status(float(th["collector_window_hours"]), now), th))
    prs = probe.open_prs()
    out.append(check_stamps(prs, now, th))
    out.append(check_conflicted_automation(prs, probe.pr_merge_state, now, th))
    out.append(check_phone_heartbeat(probe.phone_probe(now), th))
    return out


# ── incident state / transitions ─────────────────────────────────────────────────────────────────────────
def marker(cfg: dict) -> str:
    return cfg["ops_flags"]["comment_marker"]


def parse_events(comments: Optional[list], mk: str) -> List[dict]:
    """Events carried by this watchdog's own comments (a hidden `<!-- MARKER {json} -->`)."""
    ev: List[dict] = []
    for c in comments or []:
        body = str((c or {}).get("body") or "")
        i = body.find(f"<!-- {mk} ")
        if i < 0:
            continue
        j = body.find("-->", i)
        try:
            ev.append(json.loads(body[i + len(mk) + 6:j]))
        except ValueError:
            continue
    return ev


def read_ledger(path: Path = LEDGER) -> List[dict]:
    try:
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError):
        return []


def open_incidents(events: List[dict]) -> Dict[str, dict]:
    """check -> its OPEN incident, from the newest escalated/resolved event per check."""
    last: Dict[str, dict] = {}
    for e in sorted((e for e in events if e.get("event") in ("escalated", "resolved")), key=lambda e: str(e.get("ts"))):
        last[e["check"]] = e
    return {c: e for c, e in last.items() if e["event"] == "escalated"}


def _event(kind: str, v: dict, now: datetime, *, incident: str, healed_by: Optional[str], run_url: str) -> dict:
    return {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": kind, "check": v["check"], "incident": incident,
            "state": v["state"], "detail": v["detail"], "evidence": v["evidence"], "healed_by": healed_by, "run": run_url}


def run_cycle(probe: Any, cfg: dict, *, now: datetime, root: Path = _REPO, ledger: Path = LEDGER,
              sleep: Callable[[float], None] = time.sleep, live: bool = False, run_url: str = "") -> dict:
    th, mk = cfg["thresholds"], marker(cfg)
    facts = queue_facts(root, now)
    first = evaluate(probe, cfg, now, facts)
    pr = probe.ops_flags_pr(cfg["ops_flags"]["title"])
    comments = probe.pr_comments(pr) if pr else None
    events = parse_events(comments, mk) + read_ledger(ledger)
    opened = open_incidents(events)
    state_known = comments is not None or bool(read_ledger(ledger))
    # 1. self-heal first, once per incident, one dispatch of each kind per cycle
    heals: List[str] = []
    for v in first:
        if v["state"] == BAD and v["heal"] and v["check"] not in opened and v["heal"] not in heals:
            heals.append(v["heal"])
    healed_ok: List[str] = []
    for h in heals:
        if live and probe.dispatch(h):
            healed_ok.append(h)
        elif not live:
            healed_ok.append(h + "(dry-run: not fired)")
    final = first
    if live and healed_ok:
        sleep(float(th["recheck_wait_seconds"]))
        final = evaluate(probe, cfg, datetime.now(timezone.utc), queue_facts(root, datetime.now(timezone.utc)))
    first_by = {v["check"]: v for v in first}
    new_events: List[dict] = []
    for v in final:
        f = first_by.get(v["check"], v)
        healed_by = next((h for h in healed_ok if h.startswith(f["heal"])), None) if f["state"] == BAD and f["heal"] else None
        c = v["check"]
        if c in opened:
            if v["state"] == OK:
                new_events.append(_event("resolved", v, now, incident=opened[c]["incident"], healed_by=None, run_url=run_url))
            continue  # still bad / could-not-look on an open incident: deduped, nothing new to say
        if v["state"] in (BAD, CNL) or (f["state"] == BAD and f["immediate"]):
            use = v if v["state"] != OK else f
            new_events.append(_event("escalated", use, now, incident=f"{c}@{now.strftime('%Y%m%dT%H%MZ')}",
                                     healed_by=healed_by, run_url=run_url))
        elif f["state"] == BAD:    # bad on first look, ok after the heal
            new_events.append(_event("self_healed", f, now, incident=f"{c}@{now.strftime('%Y%m%dT%H%MZ')}",
                                     healed_by=healed_by, run_url=run_url))
    effects = {"pr": pr, "comments_readable": comments is not None, "state_known": state_known, "heals": healed_ok,
               "posted": [], "pinged": []}
    for e in new_events:
        if e["event"] == "self_healed":
            continue
        text = message_for(e, pr)
        if live:
            if pr:
                ok = probe.post_comment(pr, text + f"\n\n<!-- {mk} {json.dumps(e, separators=(',', ':'))} -->")
                effects["posted"].append((e["check"], e["event"], ok))
            effects["pinged"].append((e["check"], e["event"], probe.ping(text.replace("**", "")[:900])))
    if live and new_events:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            for e in new_events:
                fh.write(json.dumps(e, separators=(",", ":")) + "\n")
    return {"now": now.isoformat(), "facts": facts, "verdicts": final, "first_look": first, "events": new_events,
            "open_before": sorted(opened), "effects": effects}


def message_for(e: dict, pr: Optional[int]) -> str:
    where = f" (ops-flags PR #{pr})" if pr else ""
    if e["event"] == "resolved":
        return f"**RESEARCH WATCHDOG resolved** [{e['check']}]: {e['detail']}{where}"
    heal = f" Self-heal tried: {e['healed_by']}; still not healthy." if e.get("healed_by") else " No self-heal available for this check."
    tag = "COULD NOT LOOK" if e["state"] == CNL else "NEEDS FIXING"
    return f"**RESEARCH WATCHDOG {tag}** [{e['check']}]: {e['detail']}.{heal}{where} Incident {e['incident']}. Run: {e.get('run') or 'n/a'}"


def render(result: dict) -> str:
    lines = [f"research-watchdog @ {result['now']}"]
    f = result.get("facts")
    if f:
        lines.append(f"  queue: runnable {f['runnable']} by_backend {f['by_backend']} unplaceable {f['unplaceable']} "
                     f"(router-style due but not counted by dispatchable(): {f['router_style_due_not_counted_by_dispatchable']})")
    for v in result["verdicts"]:
        lines.append(f"  [{v['state']:>14}] {v['check']:<22} {v['detail']}")
    for e in result["events"]:
        lines.append(f"  -> {e['event']}: {e['check']} ({e['incident']})")
    lines.append(f"  effects: {json.dumps(result['effects'], default=str)}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", action="store_true", help="perform effects (dispatch, comment, ping, ledger); default is read-only")
    ap.add_argument("--fixture", help="JSON capture of GitHub's answers (implies no effects)")
    ap.add_argument("--now", help="ISO time to evaluate at (fixtures)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--run-url", default=os.environ.get("RUN_URL", ""))
    ap.add_argument("--open-incidents", action="store_true",
                    help="print the JSON list of checks with an OPEN watchdog incident (ledger + ops-flags comments) and exit; "
                         "other alerters read this to stay silent while the watchdog already told the operator")
    ap.add_argument("--test-alert", action="store_true", help="send ONE labelled test message through the live alert path and exit")
    ap.add_argument("--rows-out", help="also write this run's new ledger rows here (the workflow lands them)")
    a = ap.parse_args(argv)
    cfg = load_config()
    if a.open_incidents:
        gp = GhProbe()
        pr = gp.ops_flags_pr(cfg["ops_flags"]["title"])
        com = gp.pr_comments(pr) if pr else None
        if com is None and not read_ledger():
            print(json.dumps({"read_state": "could_not_look", "open": None}))
            return 2
        print(json.dumps({"read_state": "measured", "open": sorted(open_incidents(parse_events(com, marker(cfg)) + read_ledger()))}))
        return 0
    if a.test_alert:
        ok = GhProbe().ping("research-watchdog: test alert, no action needed")
        print(f"test alert {'SENT' if ok else 'NOT SENT'}")
        return 0 if ok else 1
    now = _ts(a.now) if a.now else datetime.now(timezone.utc)
    probe: Any = FixtureProbe(json.loads(Path(a.fixture).read_text())) if a.fixture else GhProbe()
    res = run_cycle(probe, cfg, now=now, live=a.live and not a.fixture, run_url=a.run_url)
    if a.rows_out:
        Path(a.rows_out).write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in res["events"]), encoding="utf-8")
    print(json.dumps(res, indent=2, default=str) if a.json else render(res))
    bad = [v for v in res["verdicts"] if v["state"] != OK]
    if res["effects"]["pr"] in (None, 0) and a.live:
        print(f"::error::ops-flags PR \"{cfg['ops_flags']['title']}\" not found/readable: escalations cannot wake the manager", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# wiring: .github/workflows/research-slo.yml (cron, writes comms/research/health/), scripts/ops/render_daily_brief.py §0,
#   tests/test_research_slo.py, scripts/ci/run_guards.py (research-queue-autonomy-selftests: --self-test)
"""RESEARCH-PIPELINE-SLO: the research pipeline's service levels, measured, written, alerted and audited.

WHY (operator, 2026-10-16): "The health of the research pipeline must be something we monitor, report on and audit,
so we never again end up realizing there's no actual work getting done. It's a pipeline like the other pipelines and
needs the same infra setup as the trading pipeline." Measured that morning: runnable units ~2 against a computed floor
of 50 for days; research-ops named it in prose four passes running; results landed without verdicts; 39 of 48 plan
questions had no programme node. Each of those had a detector somewhere (a warning line, a brief line, a handoff
note) and none of them was an SLO with a threshold, a status file, an alert and an audit step.

LAYERING (one red flag per condition):
  * scripts/research/research_watchdog.py (every 15 min) -- LIVENESS emergencies: dispatcher job not starting, nothing
    fired, queue below the hard floor 25, collector stuck, stranded stamps. It self-heals, then escalates.
  * THIS module (every 2 h) -- the SERVICE LEVELS: supply vs consumption, the computed floor, grading latency,
    undispositioned results, coverage, theme share, blocked age, stage liveness, hold-PR wait, research-ops
    completeness. It projects over the existing modules (queue_throughput, result_disposition_check,
    programme_coverage, research/THEMES.yaml, comms/research/utilization/, comms/research/ops/) -- it does not
    re-derive any of them. While a watchdog incident is OPEN for the same condition (alerting.watchdog_overlap) the
    SLO is left out of this module's flag.

OUTPUT: comms/research/health/<YYYY-MM-DD>.json -- `latest` (the full SLO table of the newest evaluation that day),
`runs` (one compact line per evaluation) and `alert_state` (what is open, since when, last announced). Every SLO
carries `state` in {ok, breach, could_not_look}; a value that could not be read is null, never 0.

ALERTING: ONE message per state change to the operator SYSTEM Telegram channel (research_watchdog.GhProbe.ping -- the
same direct sendMessage + send-ping fallback the trading-side watchdogs use) and ONE comment on the standing ops-flags
PR (the manager subscribes to it, so it wakes). Re-announced at most every alerting.realert_hours while the breach set
is unchanged; a recovery message when an SLO returns to ok. NO HALTING: nothing here stops, gates or disables
anything.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

CONFIG = _REPO / "scripts" / "research" / "research_slo.yaml"
HEALTH_DIR = Path("comms/research/health")
UTIL_DIR = Path("comms/research/utilization")
OPS_DIR = Path("comms/research/ops")
OK, BREACH, CNL = "ok", "breach", "could_not_look"
_ID_DATE = re.compile(r"RQ-(\d{8})-")


# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────
def load_config(path: Path = CONFIG) -> Dict[str, Any]:
    import yaml
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for k in ("slos", "alerting"):
        if not isinstance(cfg.get(k), dict):
            raise ValueError(f"{path}: missing `{k}:` block")
    return cfg


def _ts(raw: Any) -> Optional[datetime]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hours(a: datetime, b: datetime) -> float:
    return round((a - b).total_seconds() / 3600.0, 2)


def _pct(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    k = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return float(s[k])


def _id_date(uid: str) -> Optional[datetime]:
    m = _ID_DATE.match(uid)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fact(value: Any, read_state: str = "measured", **extra: Any) -> Dict[str, Any]:
    return dict(extra, value=value, read_state=read_state)


def _cnl(why: str) -> Dict[str, Any]:
    return {"value": None, "read_state": CNL, "why": why}


def _safe(fn: Callable[[], Dict[str, Any]], name: str) -> Dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # allow-silent: becomes a could_not_look fact WITH the reason, never an ok or a 0
        return _cnl(f"{name}: {type(exc).__name__}: {exc}")


# ── facts (each reads ONE existing source) ───────────────────────────────────────────────────────────────
def _util_records(root: Path) -> List[Dict[str, Any]]:
    out = []
    for f in sorted((root / UTIL_DIR).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and _ts(d.get("generated_at")):
            out.append(d)
    return out


def gather_facts(root: Path, now: datetime, cfg: Dict[str, Any], gh: Optional["Gh"] = None) -> Dict[str, Dict[str, Any]]:
    from scripts.research import queue_throughput as qt
    from scripts.research.queue_replenish import existing_units

    f: Dict[str, Dict[str, Any]] = {}
    units, _bad = existing_units(root)

    def runnable_floor():
        t = qt.throughput(root, now=now)
        floor = qt.computed_floor(t.get("fired_24h"))
        return _fact(t["runnable"], threshold=floor, fired_24h_stamps=t.get("fired_24h"), queued=t.get("queued"),
                     basis="queue_replenish.runnable(); floor = queue_throughput.computed_floor(fired_24h)")
    f["runnable_floor"] = _safe(runnable_floor, "runnable_floor")

    util = _util_records(root)
    since24 = now - timedelta(hours=24)
    since7 = now - timedelta(days=7)

    def fires_24h():
        if not util:
            return _cnl(f"no readable record under {UTIL_DIR}")
        n = sum(len(d.get("dispatched") or []) for d in util if _ts(d["generated_at"]) >= since24)
        runs = sum(1 for d in util if _ts(d["generated_at"]) >= since24)
        return _fact(n, dispatch_runs_24h=runs, basis=f"sum(len(dispatched)) over {UTIL_DIR} records in 24 h")
    f["fires_24h"] = _safe(fires_24h, "fires_24h")

    def lands_24h():
        from scripts.research.dispatch_queue import NON_VERDICT_READ_STATES
        verdict_rows, non_verdict, unreadable = 0, 0, 0
        for p in (root / "research" / "results").glob("*/*.jsonl"):
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                unreadable += 1
                continue
            for ln in lines:
                try:
                    r = json.loads(ln) if ln.strip() else None
                except ValueError:
                    continue
                if not isinstance(r, dict):
                    continue
                t = _ts(r.get("generated_at"))
                if t and t >= since24:
                    if str(r.get("read_state") or "") in NON_VERDICT_READ_STATES:
                        non_verdict += 1
                    else:
                        verdict_rows += 1
        return _fact(verdict_rows, non_verdict_rows_24h=non_verdict, result_files_unreadable=unreadable,
                     basis="research/results/*/*.jsonl rows by generated_at")
    f["lands_24h"] = _safe(lands_24h, "lands_24h")

    def grade_latency():
        # POPULATION (PIPELINE-HEALTH-1021): units whose NEWEST result row landed in the last 7 d, measured from
        # that row to the grading stamped on or after it. `grading.graded_at` is re-stamped on every mechanical
        # re-grade of an UNCHANGED result (research-queue-grade.yml touches ~240 monthly/weekly units a day), so
        # the old population "graded in 7 d" read a 22-day-old result re-graded today as 22 days of lag and put
        # p90 at 6 d (n=629) when fresh results were graded at p90 2 d (n=389, 2026-10-21). A fresh result with
        # no grading on or after it is counted in `ungraded_fresh`, never silently dropped.
        from scripts.research.result_disposition_check import _rows
        lat: List[float] = []
        ungraded = 0
        for uid, u in units.items():
            res = [t for r in _rows(root / "research" / "results" / uid) if (t := _ts(r.get("generated_at")))]
            if not res or max(res) < since7:
                continue
            newest = max(res).date()
            g = u.get("grading") if isinstance(u.get("grading"), dict) else {}
            ga = _ts(g.get("graded_at"))
            if not ga or ga.date() < newest:
                ungraded += 1
                continue
            lat.append(float((ga.date() - newest).days))
        if not lat:
            return _cnl("no unit with a result row in the last 7 d has a grading on or after it")
        return _fact(None, p50=_pct(lat, 0.5), p90=_pct(lat, 0.9), n=len(lat), ungraded_fresh=ungraded,
                     basis="whole days (graded_at is a date); units whose newest result landed in 7 d, "
                           "newest result -> grading on or after it")
    gl = _safe(grade_latency, "grade_latency")
    f["grade_latency_p50_d"] = dict(gl, value=gl.get("p50")) if gl["read_state"] != CNL else gl
    f["grade_latency_p90_d"] = dict(gl, value=gl.get("p90")) if gl["read_state"] != CNL else gl

    def undispositioned():
        from scripts.research.result_disposition_check import census
        c = census(root, now=now)
        return _fact(c["findings"], counts=c["counts"], with_results=c["with_results"],
                     sample=sorted(c["states"].get("ungraded", []))[:8],
                     basis="result_disposition_check.census findings (ungraded + needs_review_unowned; 24 h grace)")
    f["undispositioned_24h"] = _safe(undispositioned, "undispositioned_24h")

    def supply():
        authored_7d = sum(1 for uid, u in units.items() if not u.get("generated")
                          and (d := _id_date(uid)) and d >= since7.replace(hour=0, minute=0, second=0, microsecond=0))
        authored_24h = sum(1 for uid, u in units.items() if not u.get("generated")
                           and (d := _id_date(uid)) and d >= (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        consumed_7d = sum(1 for u in units.values() if not u.get("generated")
                          and (t := _ts(u.get("last_dispatched_at"))) and t >= since7)
        ratio = round(authored_7d / consumed_7d, 2) if consumed_7d else None
        if ratio is None:
            return _fact(None, read_state=CNL, why="0 authored units fired in 7 d: no consumption to divide by",
                         authored_7d=authored_7d, consumed_7d=0)
        return _fact(ratio, authored_7d=authored_7d, consumed_7d=consumed_7d, authored_since_yesterday=authored_24h,
                     basis="non-generated units: id date in 7 d / last_dispatched_at in 7 d")
    f["authoring_supply_ratio_7d"] = _safe(supply, "authoring_supply_ratio_7d")

    def coverage():
        from scripts.research.programme_coverage import coverage as cov
        rows = cov(root)["programmes"]
        q = sum(len(r["questions"]) for r in rows)
        c = sum(len(r["covered"]) + len(r["carried"]) for r in rows)
        if not q:
            return _cnl("no plan questions found")
        return _fact(round(100.0 * c / q, 1), covered=c, questions=q,
                     uncovered_by_programme={r["programme"]: len(r["uncovered"]) for r in rows},
                     basis="programme_coverage.coverage()")
    f["programme_coverage_pct"] = _safe(coverage, "programme_coverage_pct")

    def theme_share():
        import yaml
        themes = (yaml.safe_load((root / "research" / "THEMES.yaml").read_text(encoding="utf-8")) or {}).get("themes") or {}
        weights = {k: float((v or {}).get("weight") or 0) for k, v in themes.items()}
        wsum = sum(weights.values())
        fired: Dict[str, int] = {k: 0 for k in weights}
        unknown = 0
        for d in util:
            if _ts(d["generated_at"]) < since7:
                continue
            for x in d.get("dispatched") or []:
                th = (units.get(str((x or {}).get("id"))) or {}).get("theme")
                if th in fired:
                    fired[th] += 1
                else:
                    unknown += 1
        tot = sum(fired.values())
        if not tot or not wsum:
            return _cnl("no themed fire in 7 d of utilization records" if not tot else "THEMES.yaml weights sum to 0")
        per = {k: {"fires": fired[k], "share": round(fired[k] / tot, 3), "weight_share": round(weights[k] / wsum, 3),
                   "ratio": round((fired[k] / tot) / (weights[k] / wsum), 2) if weights[k] else None} for k in weights}
        worst = min((v["ratio"] for v in per.values() if v["ratio"] is not None), default=None)
        return _fact(worst, per_theme=per, fires_themed=tot, fires_untheme_or_unknown=unknown,
                     basis="7 d of utilization `dispatched` ids joined to unit theme vs THEMES.yaml weight share")
    f["theme_share_min_ratio"] = _safe(theme_share, "theme_share_min_ratio")

    def blocked():
        age = float((cfg["slos"].get("blocked_over_age") or {}).get("blocked_age_days", 21))
        bl = [(uid, d) for uid, u in units.items() if u.get("status") == "blocked" and (d := _id_date(uid))]
        old = sorted(uid for uid, d in bl if (now - d).days > age)
        oldest = max(((now - d).days for _, d in bl), default=None)
        return _fact(len(old), blocked_total=sum(1 for u in units.values() if u.get("status") == "blocked"),
                     oldest_days=oldest, age_days=age, sample=old[:8], basis="age from the RQ id date (no blocked_at field)")
    f["blocked_over_age"] = _safe(blocked, "blocked_over_age")

    def dispatcher_age():
        if not util:
            return _cnl(f"no readable record under {UTIL_DIR}")
        newest = max(_ts(d["generated_at"]) for d in util)
        return _fact(_hours(now, newest), newest=newest.isoformat(), basis="newest utilization record generated_at")
    f["dispatcher_age_h"] = _safe(dispatcher_age, "dispatcher_age_h")

    def collector_age():
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%cI", "--", "research/results"],
                             capture_output=True, text=True, timeout=60)
        t = _ts(out.stdout.strip()) if out.returncode == 0 else None
        if t is None:
            return _cnl("no commit touching research/results in the available git history (shallow clone?)")
        return _fact(_hours(now, t), newest=t.isoformat(), basis="git log -1 -- research/results (commit time)")
    f["collector_age_h"] = _safe(collector_age, "collector_age_h")

    def grader_age():
        if gh is None:
            return _cnl("no GitHub token: cannot list research-queue-grade.yml runs")
        t = gh.last_success("research-queue-grade.yml")
        if t is None:
            return _cnl("could not read a successful research-queue-grade.yml run")
        return _fact(_hours(now, t), newest=t.isoformat(), basis="last successful research-queue-grade.yml run")
    f["grader_age_h"] = _safe(grader_age, "grader_age_h")

    def ops():
        recs = []
        for p in sorted((root / OPS_DIR).glob("2*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and _ts(d.get("finished_at")):
                recs.append((p.name, d))
        if not recs:
            return _cnl(f"no readable research-ops record under {OPS_DIR}"), _cnl("no research-ops record")
        name, d = max(recs, key=lambda x: _ts(x[1]["finished_at"]))
        t = _ts(d["finished_at"])
        nr = d.get("not_run")
        age = _fact(_hours(now, t), newest=name, finished_at=t.isoformat(), basis="newest comms/research/ops record")
        if not isinstance(nr, list):
            return age, _cnl(f"{name} carries no not_run list")
        return age, _fact(len(nr), record=name, not_run=[str(x)[:160] for x in nr],
                          basis="not_run of the newest research-ops record")
    try:
        f["research_ops_age_h"], f["research_ops_not_run"] = ops()
    except Exception as exc:  # allow-silent: two could_not_look facts WITH the reason
        f["research_ops_age_h"] = f["research_ops_not_run"] = _cnl(f"research_ops: {type(exc).__name__}: {exc}")

    def hold_prs():
        if gh is None:
            return _cnl("no GitHub token: cannot list open PRs")
        prs = gh.open_unit_prs()
        if prs is None:
            return _cnl("could not list open PRs / their files")
        if not prs:
            return _fact(0.0, open_unit_prs=0, basis="no open non-automation PR adds research/queue/ files")
        ages = sorted(((_hours(now, _ts(p["createdAt"])), p["number"], p["title"][:90]) for p in prs if _ts(p.get("createdAt"))),
                      reverse=True)
        return _fact(ages[0][0], open_unit_prs=len(ages), oldest=[{"pr": n, "hours": h, "title": t} for h, n, t in ages[:5]],
                     basis="open non-automation PRs adding research/queue/*.yaml, age since creation")
    f["hold_pr_wait_h"] = _safe(hold_prs, "hold_pr_wait_h")
    return f


# ── evaluation (pure) ────────────────────────────────────────────────────────────────────────────────────
def evaluate(facts: Dict[str, Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for name, spec in cfg["slos"].items():
        fact = facts.get(name) or _cnl("not measured")
        thr = fact.get("threshold") if spec.get("threshold") == "computed" else spec.get("threshold")
        val = fact.get("value")
        if fact.get("read_state") == CNL or val is None or thr is None:
            state = CNL
        elif spec["op"] == "min":
            state = OK if float(val) >= float(thr) else BREACH
        else:
            state = OK if float(val) <= float(thr) else BREACH
        row = {"slo": name, "state": state, "value": val, "op": ">=" if spec["op"] == "min" else "<=", "threshold": thr,
               "what": spec.get("what", "")}
        row["evidence"] = {k: v for k, v in fact.items() if k not in ("value", "threshold")}
        out.append(row)
    return out


# ── alert transitions (pure) ─────────────────────────────────────────────────────────────────────────────
def transition(table: List[Dict[str, Any]], prev: Dict[str, Any], now: datetime, cfg: Dict[str, Any],
               watchdog_open: Optional[List[str]]) -> Dict[str, Any]:
    """prev = {"open": {slo: {"since", "state"}}, "last_alert": iso|None}. Returns {state, alert: None|{kind, ...}}."""
    overlap = cfg["alerting"].get("watchdog_overlap") or {}
    wd = set(watchdog_open or [])
    flagged = {r["slo"]: r for r in table if r["state"] != OK and overlap.get(r["slo"]) not in wd}
    suppressed = sorted(r["slo"] for r in table if r["state"] != OK and overlap.get(r["slo"]) in wd)
    p_open = dict(prev.get("open") or {})
    new = sorted(k for k in flagged if k not in p_open or p_open[k].get("state") != flagged[k]["state"])
    recovered = sorted(k for k in p_open if k not in flagged)
    open_now = {k: {"since": (p_open.get(k) or {}).get("since") if k not in new else now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "state": r["state"]} for k, r in flagged.items()}
    last = _ts(prev.get("last_alert"))
    kind = None
    if new or recovered:
        kind = "change"
    elif flagged and (last is None or (now - last).total_seconds() / 3600.0 >= float(cfg["alerting"]["realert_hours"])):
        kind = "reminder"
    state = {"open": open_now, "last_alert": now.strftime("%Y-%m-%dT%H:%M:%SZ") if kind else prev.get("last_alert"),
             "suppressed_by_watchdog": suppressed}
    alert = None
    if kind:
        alert = {"kind": kind, "new": new, "recovered": recovered, "flagged": sorted(flagged),
                 "text": message(table, flagged, new, recovered, kind, suppressed)}
    return {"state": state, "alert": alert}


def _fmt(v: Any) -> str:
    return "—" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))


def message(table, flagged, new, recovered, kind, suppressed) -> str:
    by = {r["slo"]: r for r in table}
    if not flagged:
        return ("RESEARCH SLO RECOVERED: " + ", ".join(f"{k} now {_fmt(by[k]['value'])} {by[k]['op']} {_fmt(by[k]['threshold'])}"
                                                      for k in recovered if k in by) + ". All research SLOs ok.")
    head = "RESEARCH SLO BREACH" if kind == "change" else "RESEARCH SLO STILL RED (reminder)"
    lines = [f"{head}: {len(flagged)} of {len(table)} research-pipeline SLOs not ok."]
    for k in sorted(flagged):
        r = by[k]
        tag = "COULD NOT LOOK" if r["state"] == CNL else "breach"
        lines.append(f"- {k}{' (NEW)' if k in new else ''}: {_fmt(r['value'])} vs {r['op']} {_fmt(r['threshold'])} [{tag}]")
    if recovered:
        lines.append("Recovered: " + ", ".join(recovered))
    if suppressed:
        lines.append("Already escalated by research-watchdog: " + ", ".join(suppressed))
    lines.append("Same-day work for the manager (manager SKILL § research SLO escalation). Status: comms/research/health/")
    return "\n".join(lines)


# ── status file ──────────────────────────────────────────────────────────────────────────────────────────
def status_path(root: Path, now: datetime) -> Path:
    return root / HEALTH_DIR / f"{now.strftime('%Y-%m-%d')}.json"


def write_status(root: Path, now: datetime, table: List[Dict[str, Any]], alert_state: Dict[str, Any],
                 alert: Optional[Dict[str, Any]], delivered: Optional[Dict[str, Any]]) -> Path:
    p = status_path(root, now)
    doc: Dict[str, Any] = {}
    if p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    counts = {s: sum(1 for r in table if r["state"] == s) for s in (OK, BREACH, CNL)}
    doc.update({"schema": 1, "as_of": stamp, "producer": "scripts/research/research_slo.py",
                "config": "scripts/research/research_slo.yaml", "counts": counts, "latest": table,
                "alert_state": alert_state})
    runs = list(doc.get("runs") or [])
    runs.append({"at": stamp, "counts": counts, "not_ok": [r["slo"] for r in table if r["state"] != OK],
                 "alert": (alert or {}).get("kind"), "delivered": delivered})
    doc["runs"] = runs[-24:]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    return p


from scripts.ops.research_slo_view import latest_status, table_lines  # noqa: E402  (the brief's read side)


# ── GitHub reads + effects ───────────────────────────────────────────────────────────────────────────────
class Gh:
    def __init__(self) -> None:
        self.repo = os.environ.get("GITHUB_REPOSITORY", "benbaichmankass/Metis-Insights")

    def _gh(self, args: List[str]) -> Optional[str]:
        for _ in range(3):
            try:
                r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if r.returncode == 0:
                return r.stdout
        return None

    def last_success(self, wf: str) -> Optional[datetime]:
        out = self._gh(["run", "list", "--repo", self.repo, "--workflow", wf, "--status", "success", "--limit", "1",
                        "--json", "createdAt,updatedAt"])
        try:
            rows = json.loads(out) if out else None
            return _ts(rows[0].get("updatedAt") or rows[0].get("createdAt")) if rows else None
        except (ValueError, IndexError, AttributeError):
            return None

    def open_unit_prs(self) -> Optional[List[Dict[str, Any]]]:
        out = self._gh(["pr", "list", "--repo", self.repo, "--state", "open", "--limit", "100",
                        "--json", "number,title,createdAt,headRefName,files"])
        try:
            prs = json.loads(out) if out else None
        except ValueError:
            return None
        if prs is None:
            return None
        keep = []
        for p in prs:
            if str(p.get("headRefName", "")).startswith(("automation/", "ops/")):
                continue
            if any(str(x.get("path", "")).startswith("research/queue/") and str(x.get("path", "")).endswith(".yaml")
                   for x in p.get("files") or []):
                keep.append(p)
        return keep


def watchdog_open() -> Optional[List[str]]:
    out = subprocess.run([sys.executable, str(_REPO / "scripts/research/research_watchdog.py"), "--open-incidents"],
                         capture_output=True, text=True, timeout=180)
    try:
        return json.loads(out.stdout).get("open")
    except ValueError:
        return None


def prior_state(root: Path, comments: Optional[list], mk: str) -> Dict[str, Any]:
    """Newest of (the newest status file's alert_state, the newest marker in an ops-flags comment)."""
    doc, _ = latest_status(root)
    cands = []
    if doc and isinstance(doc.get("alert_state"), dict):
        cands.append((str(doc.get("as_of") or ""), doc["alert_state"]))
    from scripts.research.research_watchdog import parse_events
    for e in parse_events(comments, mk):
        if isinstance(e.get("state"), dict):
            cands.append((str(e.get("at") or ""), e["state"]))
    return max(cands, key=lambda c: c[0])[1] if cands else {}


def deliver(alert: Dict[str, Any], state: Dict[str, Any], now: datetime, cfg: Dict[str, Any], probe: Any,
            pr: Optional[int]) -> Dict[str, Any]:
    mk = cfg["alerting"]["comment_marker"]
    tag = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": alert["kind"], "state": state}
    posted = bool(pr) and probe.post_comment(pr, alert["text"] + f"\n\n<!-- {mk} {json.dumps(tag, separators=(',', ':'))} -->")
    pinged = probe.ping(alert["text"][:3500])
    return {"telegram": bool(pinged), "ops_flags_comment": bool(posted), "ops_flags_pr": pr}


# ── self-test: a planted starved queue must fire, a healthy pipeline must not ───────────────────────────────
def _fixture(**over: Any) -> Dict[str, Dict[str, Any]]:
    healthy = {"runnable_floor": _fact(60, threshold=50), "fires_24h": _fact(60), "lands_24h": _fact(40),
               "grade_latency_p50_d": _fact(0.0), "grade_latency_p90_d": _fact(1.0), "undispositioned_24h": _fact(0),
               "authoring_supply_ratio_7d": _fact(1.3), "programme_coverage_pct": _fact(90.0),
               "theme_share_min_ratio": _fact(0.8), "blocked_over_age": _fact(2), "dispatcher_age_h": _fact(1.0),
               "collector_age_h": _fact(1.0), "grader_age_h": _fact(3.0), "research_ops_age_h": _fact(4.0),
               "research_ops_not_run": _fact(0), "hold_pr_wait_h": _fact(2.0)}
    healthy.update(over)
    return healthy


class _Recorder:
    def __init__(self) -> None:
        self.effects: List[Any] = []

    def post_comment(self, number: int, body: str) -> bool:
        self.effects.append(("comment", number, body))
        return True

    def ping(self, text: str) -> bool:
        self.effects.append(("ping", text))
        return True


def _self_test() -> int:
    cfg = load_config()
    now = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
    # every configured SLO is in the fixture, so a new SLO without a fixture fact fails here
    assert set(cfg["slos"]) == set(_fixture()), sorted(set(cfg["slos"]) ^ set(_fixture()))
    # positive control: healthy -> all ok, no alert
    t = evaluate(_fixture(), cfg)
    assert all(r["state"] == OK for r in t), [r for r in t if r["state"] != OK]
    tr = transition(t, {}, now, cfg, [])
    assert tr["alert"] is None and tr["state"]["open"] == {}, tr
    # planted defect: starved queue (runnable 2 vs computed floor 50) -> breach -> ONE alert, delivered
    t2 = evaluate(_fixture(runnable_floor=_fact(2, threshold=50)), cfg)
    assert [r["slo"] for r in t2 if r["state"] != OK] == ["runnable_floor"], t2
    tr2 = transition(t2, tr["state"], now, cfg, [])
    assert tr2["alert"] and tr2["alert"]["kind"] == "change" and tr2["alert"]["new"] == ["runnable_floor"], tr2
    rec = _Recorder()
    d = deliver(tr2["alert"], tr2["state"], now, cfg, rec, 17895)
    assert d["telegram"] and d["ops_flags_comment"] and len(rec.effects) == 2, rec.effects
    assert "runnable_floor" in rec.effects[1][1] and "RESEARCH SLO BREACH" in rec.effects[1][1]
    # the marker round-trips: the next run reads its state back from the comment
    from scripts.research.research_watchdog import parse_events
    ev = parse_events([{"body": rec.effects[0][2]}], cfg["alerting"]["comment_marker"])
    assert ev and ev[0]["state"]["open"].get("runnable_floor"), ev
    # same breach 1 h later: silent (dedupe)
    tr3 = transition(t2, tr2["state"], now + timedelta(hours=1), cfg, [])
    assert tr3["alert"] is None, tr3
    # same breach after realert_hours: ONE reminder
    tr4 = transition(t2, tr2["state"], now + timedelta(hours=float(cfg["alerting"]["realert_hours"]) + 1), cfg, [])
    assert tr4["alert"] and tr4["alert"]["kind"] == "reminder", tr4
    # recovery: a message, then nothing open
    tr5 = transition(t, tr2["state"], now + timedelta(hours=2), cfg, [])
    assert tr5["alert"] and tr5["alert"]["recovered"] == ["runnable_floor"] and "RECOVERED" in tr5["alert"]["text"], tr5
    assert tr5["state"]["open"] == {}
    # the watchdog already has the `queue` incident open: no second flag for the same condition
    tr6 = transition(t2, {}, now, cfg, ["queue"])
    assert tr6["alert"] is None and tr6["state"]["suppressed_by_watchdog"] == ["runnable_floor"], tr6
    # could_not_look is never ok, and a null value is never rendered as 0
    t7 = evaluate(_fixture(grader_age_h=_cnl("no token")), cfg)
    r7 = next(r for r in t7 if r["slo"] == "grader_age_h")
    assert r7["state"] == CNL and r7["value"] is None
    lines = table_lines({"as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "latest": t7}, "read", now)
    assert any("grader_age_h | — |" in ln and "could not look" in ln for ln in lines), lines
    assert "COULD NOT BE READ" in table_lines(None, "absent", now)[0]
    assert "STALE" in table_lines({"as_of": "2029-12-31T00:00:00Z", "latest": t}, "read", now)[0]
    print("research-slo self-test OK (planted starved queue alerts once; healthy control silent; dedupe, reminder, "
          "recovery, watchdog overlap, could_not_look all hold)")
    return 0


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────────
def run(root: Path, now: datetime, *, live: bool, write: bool, use_gh: bool) -> Dict[str, Any]:
    from scripts.research import research_watchdog as rw
    cfg = load_config()
    gh = Gh() if use_gh else None
    facts = gather_facts(root, now, cfg, gh)
    table = evaluate(facts, cfg)
    probe = rw.GhProbe() if live else None
    pr = comments = None
    if probe is not None:
        wcfg = rw.load_config()
        pr = probe.ops_flags_pr(wcfg["ops_flags"]["title"]) or None
        comments = probe.pr_comments(pr) if pr else None
    prev = prior_state(root, comments, cfg["alerting"]["comment_marker"])
    wd = watchdog_open() if use_gh else []
    tr = transition(table, prev, now, cfg, wd)
    delivered = deliver(tr["alert"], tr["state"], now, cfg, probe, pr) if (live and tr["alert"]) else None
    # Only a run that DELIVERED (or had nothing to deliver) advances the alert state; a measure-only run keeps the
    # previous state, so the next live run still announces what nobody has been told yet.
    keep = tr["state"] if (live and (tr["alert"] is None or (delivered or {}).get("telegram")
                                     or (delivered or {}).get("ops_flags_comment"))) else prev
    path = write_status(root, now, table, keep, tr["alert"] if live else None, delivered) if write else None
    return {"table": table, "alert": tr["alert"], "delivered": delivered, "status_file": str(path) if path else None,
            "watchdog_open": wd}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true", help="deliver alerts (Telegram system channel + ops-flags comment)")
    ap.add_argument("--write", action="store_true", help="write comms/research/health/<date>.json")
    ap.add_argument("--no-gh", action="store_true", help="skip GitHub reads (those SLOs read could_not_look)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    now = _ts(a.now) if a.now else datetime.now(timezone.utc)
    res = run(_REPO, now, live=a.live, write=a.write, use_gh=not a.no_gh)
    if a.json:
        print(json.dumps(res, indent=1, default=str))
    else:
        for ln in table_lines({"as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "latest": res["table"]}, "read", now):
            print(ln)
        print(f"alert: {(res['alert'] or {}).get('kind')} delivered: {res['delivered']} file: {res['status_file']}")
    # exit 0 even on breach: the alert is the escalation, not a red run (same contract as research_watchdog)
    return 0


if __name__ == "__main__":
    sys.exit(main())

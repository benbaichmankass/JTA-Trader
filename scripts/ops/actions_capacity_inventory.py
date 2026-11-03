#!/usr/bin/env python3
"""GitHub Actions capacity inventory by compute class (COMPUTE-ALLOCATION-DESIGN, 2026-11-03).

The rerun for docs/plans/COMPUTE-ALLOCATION-2026-11-03.md. Read-only: it only calls the Actions API through `gh api`.

  python3 scripts/ops/actions_capacity_inventory.py --days 7 --dense-hours 15 --out comms/ci/compute-allocation-inventory-<date>.json

What it measures, and over what population (printed into the output):
  * every workflow run created in the window (actions/runs paged in 30-min windows, halving any window over 1000 results);
  * job-level timings for EVERY non-skipped run created in the last --dense-hours (the "dense" window) and a stratified
    sample before it (--req-sample per required check, --other-sample per other workflow);
  * per class: runs, non-skipped runs, ESTIMATED job-hours (mean job-minutes per run from the job sample x run count),
    queue wait p50/p95/max (job started_at - created_at; includes a workflow's own concurrency-group wait, so it is an
    UPPER BOUND on pool starvation), the observed hosted concurrency ceiling (exact event sweep, jobs with a runner),
    and who held hosted slots during minutes when a required check was queued with >= 18 hosted jobs running.
A read that fails is listed under read_failures and its population is named; it is never counted as 0.
Classes come from class_of() below; the infra list is research_compute.yaml limits.infra_workflows.
"""
# wiring: manual-only - an on-demand capacity re-measure run by a session (COMPUTE-ALLOCATION-DESIGN verification M1/B11); no schedule, so it spends no runner
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"pytest-collect", "pytest-run", "Guards", "repo-inventory"}
RUN_KEYS = ("id", "name", "path", "event", "status", "conclusion", "created_at", "run_started_at", "updated_at",
            "head_branch", "run_attempt")


def repo_slug() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True, check=False).stdout
    return re.sub(r"\.git$", "", re.sub(r"^.*github\.com[:/]|^.*/git/", "", url.strip()))


def infra_names() -> set:
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "scripts/research/research_compute.yaml").read_text())
        return set(cfg["limits"]["infra_workflows"])
    except (ImportError, OSError, KeyError, TypeError, ValueError) as e:  # unreadable list: say so, never a silent empty set
        print(f"WARNING: infra_workflows COULD_NOT_READ ({e}); ops class falls back to name patterns", file=sys.stderr)
        return set()


INFRA = infra_names()


def class_of(name: str, path: str, event: str) -> str:
    """merge_path | ops | landing | training | research | pr_ci_other | automation."""
    p = (path or "").split("/")[-1].rsplit(".", 1)[0].lower()
    if name in REQUIRED:
        return "merge_path"
    if p in INFRA or name in INFRA or re.match(r"(vm-|system-action|deploy|trainer-vm-diag|trainer-diag|.*diag)", p):
        return "ops"
    if re.search(r"automerge|auto-merge|landing|merge-slot|branch-protection|armed-branch|merge-queue|pr-queue|land", p):
        return "landing"
    if re.search(r"train|ml-|model|kaggle-gpu|gpu-burst|hf-", p):
        return "training"
    if re.search(r"research|sweep|backtest|harness|cf-bulk|panel|candles-kaggle|replay|constraint-readout", p):
        return "research"
    if event == "pull_request":
        return "pr_ci_other"
    return "automation"


def gh(path: str, params: dict | None = None, tries: int = 4):
    cmd = ["gh", "api", "-X", "GET", path] + [a for k, v in (params or {}).items() for a in ("-f", f"{k}={v}")]
    for _ in range(tries):
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode == 0:
            return json.loads(r.stdout)
    return None


def pull_runs(slug, start, end, fails):
    def window(a, b):
        q = f"{a:%Y-%m-%dT%H:%M:%SZ}..{b:%Y-%m-%dT%H:%M:%SZ}"
        d = gh(f"repos/{slug}/actions/runs", {"created": q, "per_page": 100, "page": 1})
        if d is None:
            return [], [f"runs {q}"]
        if d["total_count"] > 1000:
            m = a + (b - a) / 2
            r1, f1 = window(a, m)
            r2, f2 = window(m, b)
            return r1 + r2, f1 + f2
        rows, bad = d["workflow_runs"], []
        for p in range(2, (d["total_count"] + 99) // 100 + 1):
            dd = gh(f"repos/{slug}/actions/runs", {"created": q, "per_page": 100, "page": p})
            if dd is None:
                bad.append(f"runs {q} page {p}")
            else:
                rows += dd["workflow_runs"]
        return [{k: w.get(k) for k in RUN_KEYS} for w in rows], bad
    wins, t = [], start
    while t < end:
        wins.append((t, min(t + timedelta(minutes=30), end)))
        t += timedelta(minutes=30)
    seen = {}
    with ThreadPoolExecutor(10) as ex:
        for rows, bad in ex.map(lambda w: window(*w), wins):
            fails += bad
            for r in rows:
                seen[r["id"]] = r
    return list(seen.values())


def pull_jobs(slug, ids, fails):
    def one(i):
        d = gh(f"repos/{slug}/actions/runs/{i}/jobs", {"per_page": 100, "filter": "all"})
        if d is None:
            return i, None
        return i, [{k: j.get(k) for k in ("name", "conclusion", "created_at", "started_at", "completed_at",
                                         "runner_name", "labels")}
                   | {"checkout_min": next((_mins(s.get("started_at"), s.get("completed_at"))
                                            for s in (j.get("steps") or []) if s.get("name") == "Checkout"), None)}
                   for j in d["jobs"]]
    out = {}
    with ThreadPoolExecutor(8) as ex:
        for i, jobs in ex.map(one, ids):
            if jobs is None:
                fails.append(f"jobs run {i}")
            else:
                out[i] = jobs
    return out


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _mins(a, b):
    return (_t(b) - _t(a)).total_seconds() / 60 if a and b else None


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--end", help="window end, ISO UTC (default now)")
    ap.add_argument("--dense-hours", type=float, default=15)
    ap.add_argument("--req-sample", type=int, default=250)
    ap.add_argument("--other-sample", type=int, default=12)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    slug = repo_slug()
    end = _t(a.end) if a.end else datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start, dense0 = end - timedelta(days=a.days), end - timedelta(hours=a.dense_hours)
    fails: list = []
    runs = pull_runs(slug, start, end, fails)
    live = [r for r in runs if r["conclusion"] != "skipped"]
    random.seed(7)
    dense_ids = [r["id"] for r in live if _t(r["created_at"]) >= dense0]
    by = collections.defaultdict(list)
    for r in live:
        if _t(r["created_at"]) < dense0:
            by[r["name"]].append(r["id"])
    samp = [i for n, ids in by.items()
            for i in random.sample(ids, min(a.req_sample if n in REQUIRED else a.other_sample, len(ids)))]
    jobs = pull_jobs(slug, sorted(set(dense_ids + samp)), fails)
    rmap = {r["id"]: r for r in runs}
    J = []
    for rid, js in jobs.items():
        r = rmap[rid]
        for j in js:
            if j["conclusion"] == "skipped" or not j["started_at"] or not j["completed_at"]:
                continue
            J.append({"run": rid, "wf": r["name"], "cls": class_of(r["name"], r["path"], r["event"]),
                      "c": _t(j["created_at"]), "s": _t(j["started_at"]), "e": _t(j["completed_at"]),
                      "q": _mins(j["created_at"], j["started_at"]), "x": _mins(j["started_at"], j["completed_at"]),
                      "co": j["checkout_min"], "runner": j["runner_name"] or "",
                      "host": "self" if "self-hosted" in (j["labels"] or []) else "hosted"})
    jm, rr = collections.defaultdict(float), collections.defaultdict(set)
    for j in J:
        if j["runner"]:
            jm[j["wf"]] += j["x"]
        rr[j["wf"]].add(j["run"])
    per = {w: jm[w] / len(rr[w]) for w in rr}
    R, L, M, nojob = (collections.Counter() for _ in range(4))
    for r in runs:
        k = class_of(r["name"], r["path"], r["event"])
        R[k] += 1
        if r["conclusion"] == "skipped":
            continue
        L[k] += 1
        if r["name"] in per:
            M[k] += per[r["name"]]
        else:
            nojob[k] += 1

    def qstats(pop):
        g = collections.defaultdict(list)
        for j in pop:
            g[j["wf"] if j["cls"] == "merge_path" else j["cls"]].append(j)
        return {k: {"n": len(v), "queue_p50": pct([x["q"] for x in v], .5), "queue_p95": pct([x["q"] for x in v], .95),
                    "queue_max": pct([x["q"] for x in v], 1), "exec_p50": pct([x["x"] for x in v], .5),
                    "checkout_p50": pct([x["co"] for x in v], .5), "checkout_p95": pct([x["co"] for x in v], .95)}
                for k, v in sorted(g.items())}
    dense = [j for j in J if j["c"] >= dense0]
    hosted = [j for j in dense if j["host"] == "hosted" and j["runner"]]
    ev = sorted([(j["s"], 1) for j in hosted] + [(j["e"], -1) for j in hosted], key=lambda x: (x[0], x[1]))
    c = peak = 0
    for _, v in ev:
        c += v
        peak = max(peak, c)
    mins = int((end - dense0).total_seconds() // 60)
    conc = [collections.Counter() for _ in range(mins)]
    qmp = [0] * mins
    for j in hosted:
        for m in range(max(0, int((j["s"] - dense0).total_seconds() // 60)), min(mins, int((j["e"] - dense0).total_seconds() // 60))):
            conc[m][j["cls"]] += 1
    for j in dense:
        if j["cls"] == "merge_path":
            for m in range(max(0, int((j["c"] - dense0).total_seconds() // 60)), min(mins, int((j["s"] - dense0).total_seconds() // 60))):
                qmp[m] += 1
    held, nq = collections.Counter(), 0
    for m in range(mins):
        if qmp[m] and sum(conc[m].values()) >= 18:
            nq += 1
            held.update(conc[m])
    tot = sum(M.values()) or 1
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "repo": slug,
        "population": {"runs_window": f"{start:%Y-%m-%dT%H:%MZ}..{end:%Y-%m-%dT%H:%MZ}", "runs": len(runs),
                       "dense_window_start": f"{dense0:%Y-%m-%dT%H:%MZ}", "job_runs_dense": len(set(dense_ids)),
                       "job_runs_sampled": len(set(samp)), "jobs": len(J)},
        "read_failures": fails,
        "runs_by_class": dict(R), "nonskipped_runs_by_class": dict(L),
        "job_hours_by_class_ESTIMATED": {k: round(v / 60) for k, v in M.items()},
        "job_hours_share_pct_ESTIMATED": {k: round(100 * v / tot) for k, v in M.items()},
        "nonskipped_runs_without_job_sample": dict(nojob),
        "hosted_concurrency_peak_dense": peak,
        "minutes_required_check_queued_with_hosted_ge_18": nq,
        "slot_share_pct_in_those_minutes": {k: round(100 * v / (sum(held.values()) or 1)) for k, v in held.most_common()},
        "queue_and_checkout_min_dense": qstats(dense),
        "queue_and_checkout_min_sample_before_dense": qstats([j for j in J if j["c"] < dense0]),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({k: out[k] for k in ("population", "read_failures", "job_hours_by_class_ESTIMATED",
                                          "hosted_concurrency_peak_dense", "slot_share_pct_in_those_minutes")}, default=str))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

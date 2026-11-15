"""Lifecycle scheduler: read plans, compute what is due, run it, record one result per job.

Runs on the trainer VM (or free GitHub compute) with ZERO Anthropic usage. Contracts:
* NO HALT: every job is contained (own subprocess, own timeout); one failure never stops the
  pass. A failed job is retried on a backoff; after ``RED_FLAG_AFTER`` consecutive failures ONE
  ``lifecycle_red_flag`` event is written (once per episode) while retries continue.
* Gates nothing on the trade path; never promotes. The ``update`` job only PROPOSES (gate-check
  reports; promotion is decided on offline evidence; the shadow step was retired 2026-11-12).
* One MEASURED result record per attempted job -> <runtime_logs>/trainer/lifecycle_results.jsonl.
  A due job is skipped (recorded once per reason, status=skipped, not counted as done) when the
  model has no registry entry yet or its dataset is empty (rc 78).
* Retrain "last done" also counts nightly-cycle ``manifest_ok`` rows (training_cycle.jsonl), so
  this backstop never duplicates a retrain the cycle already did inside the cadence.

CLI: python -m ml.lifecycle.scheduler [--dry-run] [--only PLAN_ID] [--max-jobs N] [--now ISO]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import plan as P

RED_FLAG_AFTER = int(os.environ.get("LIFECYCLE_RED_FLAG_AFTER", "3"))
BACKOFF_H = float(os.environ.get("LIFECYCLE_RETRY_BACKOFF_H", "6"))
TAIL = 1500


def _root() -> Path:
    return Path(os.environ.get("REPO_ROOT", str(P.REPO)))


def _paths() -> dict[str, Path]:
    r = _root()
    t = r / "runtime_logs" / "trainer"
    return {"state": t / "lifecycle_state.json", "results": t / "lifecycle_results.jsonl",
            "cycle": r / "runtime_logs" / "training_cycle.jsonl"}


def _ts(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cycle_last_ok(path: Path) -> dict[str, datetime]:
    """manifest path -> newest manifest_ok ts in training_cycle.jsonl. Unreadable => {}."""
    out: dict[str, datetime] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "manifest_ok" and r.get("manifest"):
                t = _ts(str(r.get("ts", "")))
                if t and (r["manifest"] not in out or t > out[r["manifest"]]):
                    out[r["manifest"]] = t
    except OSError:
        pass
    return out


def due_jobs(plans: dict[str, dict], state: dict, cycle_ok: dict[str, datetime],
             now: datetime, drift_hot: set[str] | None = None) -> list[dict]:
    """Pure: which jobs are due at ``now``, most overdue first."""
    drift_hot = drift_hot or set()
    due = []
    for stem, plan in plans.items():
        for j in P.jobs(plan):
            key = f"{stem}/{j['id']}"
            st = state.get(key, {})
            last = _ts(st.get("last_ok_ts", "")) if st.get("last_ok_ts") else None
            if j["id"] == "retrain":
                c = cycle_ok.get(plan["manifest"])
                if c and (last is None or c > last):
                    last = c
            cadence = timedelta(days=j["cadence_days"])
            trigger = "calendar"
            if j["id"] == "retrain" and stem in drift_hot:
                trigger = "drift"
                is_due = True
            else:
                is_due = last is None or now - last >= cadence
            if not is_due:
                continue
            fails = int(st.get("consecutive_failures", 0))
            la = _ts(st.get("last_attempt_ts", "")) if st.get("last_attempt_ts") else None
            if st.get("last_skip_reason") and la and now - la < timedelta(hours=24):
                continue  # skipped (no registry entry / empty dataset): re-ask once a day
            if fails and la:
                wait = min(timedelta(hours=BACKOFF_H * 2 ** (fails - 1)), cadence)
                if now - la < wait:
                    continue
            over = 1e9 if last is None else (now - last) / cadence
            due.append({"stem": stem, "key": key, "plan": plan, "job": j,
                        "trigger": trigger, "overdue": over})
    due.sort(key=lambda d: -d["overdue"])
    return due


def _parse_json_tail(text: str) -> Any:
    dec, best = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                best = obj
            except Exception:
                pass
    return best


def run_job(d: dict, ctx: dict[str, str]) -> dict:
    plan, j = d["plan"], d["job"]
    cmd = P.fill(j["command"], plan, ctx)
    reg = Path(ctx["registry_root"]) / f"{plan['model_id']}.json"
    base = {"ts": datetime.now(timezone.utc).isoformat(), "plan_id": d["stem"],
            "model_id": plan["model_id"], "job": j["id"], "kind": j["kind"],
            "trigger": d["trigger"], "provenance": "MEASURED",
            "cadence_provenance": j["provenance"], "cadence_days": j["cadence_days"]}
    if j["kind"] != "retrain" and not reg.is_file():
        return {**base, "status": "skipped", "reason": "no_registry_entry", "rc": None}
    t0 = time.time()
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=j["timeout_s"],
                            cwd=str(_root()))
        out = (cp.stdout or "") + (cp.stderr or "")
        rec = {**base, "status": "ok" if cp.returncode == 0 else "failed", "rc": cp.returncode,
               "result": _parse_json_tail(cp.stdout or ""), "output_tail": out[-TAIL:]}
        if cp.returncode == 78:  # trainer convention: empty/absent dataset = clean skip
            rec["status"], rec["reason"] = "skipped", "empty_dataset"
    except subprocess.TimeoutExpired:
        rec = {**base, "status": "failed", "rc": None, "reason": "timeout"}
    except Exception as exc:  # contain per item
        rec = {**base, "status": "failed", "rc": None, "reason": f"{type(exc).__name__}: {exc}"}
    rec["duration_s"] = round(time.time() - t0, 1)
    return rec


def _drift_hot(plans: dict[str, dict], state: dict) -> set[str]:
    """Plans whose newest drift_check result says overall_verdict == significant AND that
    have not been retrained since (drift trigger, additive to the calendar)."""
    hot = set()
    for stem, plan in plans.items():
        if not any(t.get("kind") == "drift" for t in plan["retrain"].get("triggers", [])):
            continue
        dc = state.get(f"{stem}/drift_check", {})
        if dc.get("last_verdict") == "significant":
            rt = state.get(f"{stem}/retrain", {})
            if not rt.get("last_ok_ts") or rt["last_ok_ts"] < dc.get("last_ok_ts", ""):
                hot.add(stem)
    return hot


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--max-jobs", type=int, default=int(os.environ.get("LIFECYCLE_MAX_JOBS", "12")))
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    from src.utils.paths import trade_journal_db_path  # canonical resolver (canonical-db-resolver guard)
    now = _ts(a.now) if a.now else datetime.now(timezone.utc)
    p = _paths()
    plans = {k: v for k, v in P.load_all().items() if not a.only or k == a.only}
    state = _load_state(p["state"])
    ctx = {"py": sys.executable,
           "datasets_root": os.environ.get("DATASETS_ROOT", str(_root() / "datasets-out")),
           "experiments_root": os.environ.get("EXPERIMENTS_ROOT", str(_root() / "ml" / "experiments-runs")),
           "registry_root": os.environ.get("REGISTRY_ROOT", str(_root() / "ml" / "registry-store")),
           "journal_db": str(trade_journal_db_path())}
    due = due_jobs(plans, state, _cycle_last_ok(p["cycle"]), now, _drift_hot(plans, state))
    summary = {"plans": len(plans), "due": len(due), "ran": 0, "ok": 0, "failed": 0,
               "skipped": 0, "red_flags": 0, "deferred_note": "jobs beyond --max-jobs real runs wait for the next pass"}
    if a.dry_run:
        print(json.dumps({**summary, "due_jobs": [d["key"] for d in due]}, indent=2))
        return 0
    executed = 0
    for d in due:
        if executed >= a.max_jobs:
            break
        rec = run_job(d, ctx)
        if rec["status"] != "skipped":  # skips are free (no subprocess); only real runs use the budget
            executed += 1
        st = state.setdefault(d["key"], {})
        # A skip is recorded once per reason (no spam every pass) and does not count as done.
        if rec["status"] != "skipped" or st.get("last_skip_reason") != rec.get("reason"):
            _append(p["results"], rec)
        st["last_attempt_ts"] = rec["ts"]
        summary["ran"] += 1
        if rec["status"] == "failed":
            summary["failed"] += 1
            st["consecutive_failures"] = int(st.get("consecutive_failures", 0)) + 1
            if st["consecutive_failures"] >= RED_FLAG_AFTER and not st.get("red_flagged"):
                st["red_flagged"] = True
                summary["red_flags"] += 1
                _append(p["cycle"], {"ts": rec["ts"], "status": "lifecycle_red_flag",
                                     "plan_id": d["stem"], "job": d["job"]["id"],
                                     "consecutive_failures": st["consecutive_failures"],
                                     "detail": "lifecycle job failing repeatedly; retries continue",
                                     "last_tail": rec.get("output_tail", rec.get("reason", ""))[-400:]})
        elif rec["status"] == "skipped":
            summary["skipped"] += 1
            st["last_skip_reason"] = rec.get("reason")
        else:
            summary["ok"] += 1
            st["consecutive_failures"] = 0
            st["red_flagged"] = False
            st["last_skip_reason"] = None
            st["last_ok_ts"] = rec["ts"]
            if d["job"]["id"] == "drift_check" and isinstance(rec.get("result"), dict):
                st["last_verdict"] = rec["result"].get("overall_verdict")
        p["state"].parent.mkdir(parents=True, exist_ok=True)
        tmp = p["state"].with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        tmp.replace(p["state"])
    _append(p["results"], {"ts": datetime.now(timezone.utc).isoformat(), "kind": "pass_summary",
                           "provenance": "MEASURED", **summary})
    print(json.dumps(summary))
    return 0  # never non-zero for job failures: no halting, the red flag is the signal


if __name__ == "__main__":
    raise SystemExit(main())

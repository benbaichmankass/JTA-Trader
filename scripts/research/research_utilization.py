#!/usr/bin/env python3
# wiring: scripts/research/dispatch_queue.py (measure + write each fired cycle), research-ops step A (reads the flag), the Wednesday weekly plan (--week)
"""RESEARCH-ROUTER utilization: how much of each research backend did the dispatcher actually use?

Operator, 2026-10-13: not only per-test routing, but OVERALL utilization -- "really getting the most out of all the
resources at our disposal". Three parts, all token-free:

  measure(...)   one record per dispatcher run, with an EXPLICIT read_state per backend (measured | could_not_look):
                 a backend we could not count is never reported as idle or as zero.
  write(...)     one file per run under comms/research/utilization/<run_id>.json (a directory, not one rolling file,
                 so two dispatcher runs can never conflict on the same line the way the receipt json can).
  week(...)      the Wednesday view: per backend capacity-slot-cycles available vs used vs idle, value dispatched,
                 Kaggle GPU hours used / expiring, and the floor-thin flag count, read from the last 7 days of records.

WHAT IS AND IS NOT MEASURED (field beats comment):
  * runner / trainer / kaggle `inflight` = research workflow runs queued or in progress at the START of the cycle,
    from `gh run list` (backpressure()). That is workflow-level occupancy, NOT CPU. The trainer VM's own CPU/memory
    comes from COMPUTE-UTIL-TELEMETRY's comms/cloud/compute_spare.json when it exists, else `could_not_look`.
  * `runner_pool_used_vs_platform`: research runs in flight against GitHub's concurrent-job ceiling (20 on the Free
    plan -- the plan tier is UNVERIFIED, config value `platform_concurrency`). Other workflows share that pool and are
    not counted here, so this is a floor on pool use, not the pool use.
  * Kaggle hours come from `kaggle quota` (used / remaining / total / refreshAt), the only authority.
  * GPU-burst $ is month-to-date from comms/gpu_spend_ledger.json against its budget.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

OUT_DIR = Path("comms") / "research" / "utilization"
EXPIRY_WINDOW_H = 48.0     # Kaggle hours still unused this close to the weekly reset are about to be wasted


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _gpu_burst(repo: Path, now: datetime) -> dict[str, Any]:
    try:
        d = json.loads((repo / "comms" / "gpu_spend_ledger.json").read_text(encoding="utf-8"))
        month = now.strftime("%Y-%m")
        spent = sum(float(r.get("cost_usd") or 0) for r in d.get("runs", [])
                    if str(r.get("ended_at") or r.get("started_at") or "").startswith(month))
        return {"read_state": "measured", "month_to_date_usd": round(spent, 4),
                "budget_usd": float(d.get("budget_usd_per_month") or 0)}
    except (OSError, ValueError, TypeError):
        return {"read_state": "could_not_look", "month_to_date_usd": None, "budget_usd": None}


def _trainer_vm(repo: Path) -> dict[str, Any]:
    p = repo / "comms" / "cloud" / "compute_spare.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"read_state": "could_not_look", "why": "comms/cloud/compute_spare.json absent (COMPUTE-UTIL-TELEMETRY not landed/run)"}
    return {"read_state": "measured", "source": "comms/cloud/compute_spare.json", "spare": d}


def measure(*, cfg: dict[str, Any], by_name_to_backend: dict[str, str], pressure: dict[str, Any],
            quota: dict[str, Any], decisions: list[dict[str, Any]], now: datetime, run_id: str,
            fired: bool, repo: Path = _REPO) -> dict[str, Any]:
    """Build one utilization record. `pressure` is backpressure()'s dict (by_name = {workflow name: count} or absent
    when gh could not be asked)."""
    counted = pressure.get("by_name") is not None and pressure.get("inflight_research") is not None
    by_backend: dict[str, int] = {}
    for name, n in (pressure.get("by_name") or {}).items():
        be = by_name_to_backend.get(name)
        if be:
            by_backend[be] = by_backend.get(be, 0) + int(n)
    backends: dict[str, Any] = {}
    for name, b in cfg["backends"].items():
        if b.get("auto_route", True) is False:
            continue
        cap = int(b["max_concurrent"])
        fired_n = sum(1 for d in decisions if d.get("backend") == name and d.get("outcome") == "dispatched")
        wait_n = sum(1 for d in decisions if d.get("backend") == name and d.get("outcome") == "deferred")
        due_n = sum(1 for d in decisions if d.get("backend") == name
                    and d.get("outcome") in ("dispatched", "deferred", "would_dispatch"))
        if counted:
            inflight = by_backend.get(name, 0)
            free = max(0, cap - inflight - fired_n)
            backends[name] = {"read_state": "measured", "capacity": cap, "inflight_at_start": inflight,
                              "fired_this_cycle": fired_n, "due_waiting": wait_n, "due_total": due_n,
                              "free_slots_after": free, "busy_fraction": round(min(1.0, (inflight + fired_n) / cap), 3)}
        else:
            backends[name] = {"read_state": "could_not_look", "capacity": cap, "why": "gh run list failed; occupancy unknown",
                              "fired_this_cycle": fired_n, "due_waiting": wait_n, "due_total": due_n}
    plat = int(cfg.get("limits", {}).get("platform_concurrency", 20))
    runner_in = backends.get("github_runner", {}).get("inflight_at_start")
    kq: dict[str, Any] = {"read_state": "could_not_look", "why": quota.get("note") or "quota not read"}
    if quota.get("remaining") is not None:
        refresh = _parse(quota.get("refresh"))
        hrs = (refresh - now).total_seconds() / 3600.0 if refresh else None
        kq = {"read_state": "measured", "remaining_h": quota["remaining"], "used_h": quota.get("used"),
              "total_h": quota.get("total"), "refresh_at": quota.get("refresh"),
              "hours_to_refresh": round(hrs, 1) if hrs is not None else None,
              "expiring_h": round(quota["remaining"], 2) if hrs is not None and 0 <= hrs <= EXPIRY_WINDOW_H else 0.0}
    idle = {n: b["free_slots_after"] for n, b in backends.items() if b["read_state"] == "measured" and b["free_slots_after"] > 0}
    thin = [n for n, f in idle.items() if backends[n]["due_waiting"] == 0 and backends[n]["due_total"] <= backends[n]["fired_this_cycle"]]
    flags: list[str] = []
    if thin:
        flags.append("floor_thin: " + ", ".join(f"{n} has {idle[n]} idle slot(s) and nothing due for it" for n in thin)
                     + " -- research-ops should author units whose compute class lands there")
    if kq.get("expiring_h", 0) and kq["expiring_h"] > 1.0 and backends.get("kaggle", {}).get("due_total", 0) == 0:
        flags.append(f"kaggle_quota_expiring: {kq['expiring_h']} GPU h unused with the weekly reset in {kq['hours_to_refresh']} h and no gpu unit due")
    return {"schema": 1, "run_id": run_id, "generated_at": now.isoformat(), "fired": fired, "backends": backends,
            "runner_pool_used_vs_platform": {"research_inflight": runner_in, "platform_concurrency": plat,
                                             "read_state": "measured" if runner_in is not None else "could_not_look",
                                             "note": "research runs only; other workflows share the pool"},
            "kaggle_gpu": kq, "gpu_burst": _gpu_burst(repo, now), "trainer_vm": _trainer_vm(repo),
            "dispatched": [{"id": d["id"], "backend": d.get("backend"), "class": d.get("compute_class"),
                            "value": d.get("value_score"), "idle_fill": bool(d.get("idle_fill"))}
                           for d in decisions if d.get("outcome") == "dispatched"],
            "flags": flags}


def write(rec: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{rec['run_id']}.json"
    p.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return p


def one_line(rec: dict[str, Any]) -> str:
    parts = []
    for n, b in rec["backends"].items():
        parts.append(f"{n} {b['inflight_at_start'] + b['fired_this_cycle']}/{b['capacity']} busy"
                     if b["read_state"] == "measured" else f"{n} ?/{b['capacity']} (could not look)")
    kq = rec["kaggle_gpu"]
    parts.append(f"kaggle GPU {kq['remaining_h']:g} h left" if kq["read_state"] == "measured" else "kaggle GPU quota unread")
    return "utilization: " + " | ".join(parts) + (" | FLAGS: " + "; ".join(rec["flags"]) if rec["flags"] else "")


def week(root: Path = _REPO, now: datetime | None = None, days: int = 7) -> dict[str, Any]:
    """Capacity available vs used vs idle per backend over the last `days`, from the per-run records."""
    now = now or datetime.now(timezone.utc)
    recs = []
    for p in sorted((root / OUT_DIR).glob("*.json")) if (root / OUT_DIR).is_dir() else []:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = _parse(r.get("generated_at"))
        if t and now - t <= timedelta(days=days) and r.get("fired"):
            recs.append(r)
    out: dict[str, Any] = {"window_days": days, "cycles": len(recs), "backends": {}, "flags": {}, "read": "per-run files"}
    for r in recs:
        for n, b in r["backends"].items():
            a = out["backends"].setdefault(n, {"cycles_measured": 0, "cycles_could_not_look": 0, "slot_cycles_available": 0,
                                               "slot_cycles_used": 0, "fires": 0, "waiting_cycles": 0, "underutilised_cycles": 0,
                                               "value_dispatched": 0.0})
            if b["read_state"] != "measured":
                a["cycles_could_not_look"] += 1
                continue
            a["cycles_measured"] += 1
            a["slot_cycles_available"] += b["capacity"]
            a["slot_cycles_used"] += min(b["capacity"], b["inflight_at_start"] + b["fired_this_cycle"])
            a["fires"] += b["fired_this_cycle"]
            a["waiting_cycles"] += 1 if b["due_waiting"] else 0
            # non-alerting reading: units were due and slots were left free after the cycle's fires
            a["underutilised_cycles"] += 1 if (b["due_waiting"] and b.get("free_slots_after", 0) > 0) else 0
        for d in r.get("dispatched", []):
            be = out["backends"].setdefault(d.get("backend") or "unmanaged", {"cycles_measured": 0, "cycles_could_not_look": 0,
                                            "slot_cycles_available": 0, "slot_cycles_used": 0, "fires": 0, "waiting_cycles": 0,
                                            "underutilised_cycles": 0, "value_dispatched": 0.0})
            be["value_dispatched"] = round(be["value_dispatched"] + float(d.get("value") or 0), 2)
        for f in r.get("flags", []):
            k = f.split(":", 1)[0]
            out["flags"][k] = out["flags"].get(k, 0) + 1
    for a in out["backends"].values():
        av = a["slot_cycles_available"]
        a["utilization"] = round(a["slot_cycles_used"] / av, 3) if av else None
        a["idle_slot_cycles"] = av - a["slot_cycles_used"]
    # The trainer is its own managed queue (ML-DATA-OFF-TRAINER): who consumes it, its idle windows, queue depth.
    try:
        from scripts.research import trainer_queue as tq  # noqa: PLC0415
        out["trainer_queue"] = {"workload": tq.breakdown(tq.load()), "queue": tq.status()}
    except (OSError, ValueError, KeyError, ImportError) as exc:
        out["trainer_queue"] = {"read_state": "could_not_look", "why": f"{type(exc).__name__}: {exc}"}
    kq = [r["kaggle_gpu"] for r in recs if r["kaggle_gpu"]["read_state"] == "measured"]
    if kq:
        last = kq[-1]
        out["kaggle_gpu_latest"] = {k: last.get(k) for k in ("used_h", "remaining_h", "total_h", "refresh_at", "expiring_h")}
    return out


def _self_test() -> int:
    import tempfile
    from scripts.research import compute_router as cr
    cfg = cr.load_config()
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    pressure = {"inflight_research": 1, "by_name": {"research-script-run": 1}}
    q = {"remaining": 20.0, "used": 10.0, "total": 30.0, "refresh": "2026-10-17T00:00:00"}
    dec = [{"id": "RQ-1", "outcome": "dispatched", "backend": "github_runner", "value_score": 12.5, "compute_class": "cpu_light"}]
    rec = measure(cfg=cfg, by_name_to_backend={"research-script-run": "github_runner"}, pressure=pressure, quota=q,
                  decisions=dec, now=now, run_id="1", fired=True)
    gh = rec["backends"]["github_runner"]
    assert gh["read_state"] == "measured" and gh["inflight_at_start"] == 1 and gh["fired_this_cycle"] == 1 and gh["free_slots_after"] == 1, gh
    assert rec["kaggle_gpu"]["expiring_h"] == 20.0 and any(f.startswith("kaggle_quota_expiring") for f in rec["flags"]), rec["flags"]
    assert any(f.startswith("floor_thin") for f in rec["flags"]), rec["flags"]
    blind = measure(cfg=cfg, by_name_to_backend={}, pressure={"inflight_research": None}, quota={"remaining": None, "note": "x"},
                    decisions=[], now=now, run_id="2", fired=True)
    assert blind["backends"]["trainer"]["read_state"] == "could_not_look" and "free_slots_after" not in blind["backends"]["trainer"]
    assert blind["kaggle_gpu"]["read_state"] == "could_not_look"
    with tempfile.TemporaryDirectory() as td:
        write(rec, Path(td) / OUT_DIR)
        w = week(Path(td), now)
        assert w["cycles"] == 1 and w["backends"]["github_runner"]["value_dispatched"] == 12.5, w
        assert w["backends"]["github_runner"]["utilization"] == round(2 / 3, 3), w
    print("research_utilization self-test OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--week", action="store_true", help="print the last-7-days per-backend summary as JSON")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    if a.week:
        print(json.dumps(week(), indent=2))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# wiring: scripts/research/compute_router.py (backends.trainer.queue windows), scripts/research/research_utilization.py (weekly view)
"""ML-DATA-OFF-TRAINER: the trainer VM as its OWN managed queue -- measured workload, derived idle windows, depth.

  profile()   per-UTC-hour busy fraction of the trainer's HEAVY services, from comms/cloud/trainer_workload_profile.json
  open_hours  the hours at or below the profile's threshold -- the only hours a research unit may be released into
  windows()   open_hours as "HH:00-HH:00" ranges; research_compute.yaml::backends.trainer.queue.windows_utc must be a
              SUBSET (tests/test_trainer_queue.py), so the config cannot drift from the measurement
  status()    queued trainer-bound units, their est. minutes, and the idle minutes per day -> days to drain
  breakdown() who consumes the trainer (cpu-h, wall-h, share) -- the figure the weekly planning reads

Reads files only. Tier-1. It schedules nothing itself: the dispatcher applies the windows (compute_router.window_problem).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
PROFILE = _REPO / "comms" / "cloud" / "trainer_workload_profile.json"
DAYS = 7.0


def load(path: Path = PROFILE) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def busy_fraction(prof: Dict[str, Any]) -> Dict[str, float]:
    """UTC hour -> fraction of that hour the trainer spent in a heavy service (can exceed 1.0: overlapping jobs)."""
    out = {f"{h:02d}": 0.0 for h in range(24)}
    for name in prof["heavy_services"]:
        for hh, w in (prof["services"][name].get("wall_h_by_utc_hour") or {}).items():
            out[hh] += float(w) / DAYS
    return out


def open_hours(prof: Dict[str, Any]) -> List[int]:
    thr = float(prof["open_threshold_busy_fraction"])
    bf = busy_fraction(prof)
    return [h for h in range(24) if bf[f"{h:02d}"] <= thr]


def windows(prof: Dict[str, Any]) -> List[str]:
    hrs, out, i = open_hours(prof), [], 0
    while i < len(hrs):
        j = i
        while j + 1 < len(hrs) and hrs[j + 1] == hrs[j] + 1:
            j += 1
        out.append(f"{hrs[i]:02d}:00-{hrs[j] + 1:02d}:00")
        i = j + 1
    return out


def breakdown(prof: Dict[str, Any]) -> Dict[str, Any]:
    svc = prof["services"]
    tot_cpu = sum(s["cpu_h"] for s in svc.values())
    avail = DAYS * 24.0 * float(prof["shape"]["ocpus"])
    rows = sorted(({"service": n, "cadence": s["cadence"], "runs": s["runs"], "cpu_h": s["cpu_h"], "wall_h": s["wall_h"],
                    "share_of_service_cpu": round(s["cpu_h"] / tot_cpu, 3) if tot_cpu else None,
                    "cpu_pct_of_1_ocpu_week": round(100 * s["cpu_h"] / avail, 1)} for n, s in svc.items()),
                  key=lambda r: -r["cpu_h"])
    return {"window": prof["window"], "services_cpu_h": round(tot_cpu, 2), "ocpu_h_available": avail,
            "services_cpu_pct_of_week": round(100 * tot_cpu / avail, 1), "rows": rows,
            "not_measured": "research runs launched over SSH and any non-systemd process"}


def status(queue_dir: Path = _REPO / "research" / "queue") -> Dict[str, Any]:
    import yaml  # noqa: PLC0415
    from scripts.research import compute_router as cr  # noqa: PLC0415
    cfg = cr.load_config()
    prof = load()
    idle_min = sum(b - a for a, b in cr.parse_windows(cfg["backends"]["trainer"]["queue"]["windows_utc"]))
    units, mins = [], 0.0
    for f in sorted(queue_dir.glob("RQ-*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if d.get("status") != "queued":
            continue
        p = cr.plan(d, cfg)
        if p.ok and p.backend == "trainer":
            m = cr.est_hours(d) * 60.0
            units.append({"id": d.get("id", f.stem), "est_min": round(m, 1)})
            mins += m
    return {"queued_trainer_units": len(units), "queued_est_min": round(mins, 1), "idle_min_per_day": idle_min,
            "days_to_drain_if_serial": round(mins / idle_min, 2) if idle_min else None, "units": units,
            "windows_utc": cfg["backends"]["trainer"]["queue"]["windows_utc"], "derived_windows": windows(prof)}


def _self_test() -> int:
    prof = load()
    bf = busy_fraction(prof)
    assert bf["01"] > 1.0 and bf["05"] > 1.0, "01Z and 05Z are overlapping-heavy hours in the measured week"
    assert 3 in open_hours(prof) and 12 in open_hours(prof) and 1 not in open_hours(prof) and 5 not in open_hours(prof)
    assert breakdown(prof)["rows"][0]["service"] == "ict-drift-retrain"
    print("trainer_queue self-test OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--breakdown", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    if a.breakdown:
        print(json.dumps(breakdown(load()), indent=1))
        return 0
    if a.status:
        print(json.dumps(status(), indent=1))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

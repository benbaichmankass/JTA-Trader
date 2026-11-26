#!/usr/bin/env python3
# wiring: manual-only - a read-only measurement a session or the daily review runs by hand (row COMPUTE-IDLE-TRAINER-GPU-W48 asks the daily review to read runnable hours per backend); nothing schedules it and it gates nothing
"""Runnable research hours per backend: the "is compute idle?" check-in number.

WHY (operator 2026-11-25, verbatim: "these resources are free and should never sit idle!!!!"; row COMPUTE-IDLE-TRAINER-GPU-W48,
whose done-condition includes "the daily review measures runnable hours per backend"). No script computed this; the manager's
2026-11-25 measurement was ad hoc. This is that measurement as a read-only tool.

WHAT IT COUNTS (the definition the row's own measurement used, COMPUTE-TRAINER-GPU-PLAN-GAP 2026-11-25):
  population  research/queue/RQ-*.yaml with  status == queued,  cadence once (or absent),  no ``blocked_on``,  no ``result``.
  backend     the router's FIRST-CHOICE backend for the unit (``compute_router.plan``): where the unit would go on an idle
              day. It is NOT where it will run (that depends on load at dispatch time).
  hours       ``compute_router.est_hours`` (routing.est_minutes, floor 5 min; 1 h when the unit declares none). An ESTIMATE
              the author wrote, not a measurement.
  A unit the router cannot place is COUNTED under ``unplaced``, never dropped and never added to a backend.

WHAT IT DOES NOT COUNT: recurring units (cadence weekly etc.: they refill themselves), blocked or graded units, and units whose
dependencies are unmet (``requires_result`` is not evaluated here, so this can OVERSTATE runnable work by those units).
Two weeks of work for a backend that runs one job at a time is ~336 h; ``--target-hours`` prints the gap to a stated target.

Read-only. Exit code 0 always; this is a measurement, not a gate.

    python3 scripts/research/runnable_hours.py [--queue-dir research/queue] [--target-hours 336] [--json]
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _router() -> Any:
    spec = importlib.util.spec_from_file_location("compute_router_rh", REPO / "scripts" / "research" / "compute_router.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[spec.name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def counted(entry: Dict[str, Any]) -> bool:
    """True when the unit is in the population (see the module docstring)."""
    return (entry.get("status") == "queued" and entry.get("cadence") in (None, "once")
            and not entry.get("blocked_on") and not entry.get("result"))


def measure(queue_dir: Path, cfg: Optional[Dict[str, Any]] = None, cr: Any = None) -> Dict[str, Any]:
    import yaml  # noqa: PLC0415

    cr = cr or _router()
    cfg = cfg or cr.load_config()
    hours: Dict[str, float] = defaultdict(float)
    units: Dict[str, int] = defaultdict(int)
    unplaced: List[Dict[str, str]] = []
    seen = 0
    unreadable: List[str] = []
    for p in sorted(glob.glob(str(queue_dir / "RQ-*.yaml"))):
        try:
            entry = yaml.safe_load(open(p, encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:  # a unit we cannot read is COUNTED under `unreadable`, never skipped
            unreadable.append(f"{Path(p).name}: {type(exc).__name__}")
            continue
        seen += 1
        if not isinstance(entry, dict) or not counted(entry):
            continue
        res = cr.plan(entry, cfg)
        if not res.ok:
            unplaced.append({"id": str(entry.get("id")), "why": res.error[:100]})
            continue
        hours[res.backend] += cr.est_hours(entry)
        units[res.backend] += 1
    return {
        "basis": "status queued, cadence once, no blocked_on, no result; router first-choice backend; est_hours (author estimate)",
        "units_read": seen,
        "unreadable": unreadable,
        "backends": {be: {"units": units[be], "est_hours": round(hours[be], 1)} for be in sorted(hours)},
        "unplaced": unplaced,
    }


def render(m: Dict[str, Any], target_hours: Optional[float]) -> str:
    lines = [f"runnable hours per backend  ({m['basis']})",
             f"  units read: {m['units_read']}  unreadable: {len(m['unreadable'])}  unplaced: {len(m['unplaced'])}"]
    for be, v in m["backends"].items():
        gap = f"   gap to {target_hours:g} h: {max(target_hours - v['est_hours'], 0):.1f} h" if target_hours else ""
        lines.append(f"  {be:<14} {v['units']:>4} units  {v['est_hours']:>8.1f} h{gap}")
    for u in m["unplaced"][:5]:
        lines.append(f"  unplaced: {u['id']}: {u['why']}")
    for u in m["unreadable"][:5]:
        lines.append(f"  unreadable: {u}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queue-dir", default=str(REPO / "research" / "queue"))
    ap.add_argument("--target-hours", type=float, default=None, help="print each backend's gap to this many runnable hours")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    m = measure(Path(a.queue_dir))
    print(json.dumps(m, indent=1) if a.json else render(m, a.target_hours))
    return 0


if __name__ == "__main__":
    sys.exit(main())

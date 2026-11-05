"""No queue unit may declare a run.timeout_minutes the dispatcher's own preflight refuses.

WHY (2026-11-05, watchdog escalation on backend:kaggle_cpu "idle with 9 runnable units"): 8 units
(RQ-20261101-78fc-44..50, -53) declared `timeout_minutes: 360` while script_run.plan refuses anything over
MAX_TIMEOUT_MIN (330). Every dispatcher cycle logged `dispatch_failed ... outside [10, 330]` for them, they never
ran, and once the other kaggle_cpu units were spent the backend sat idle with "runnable" units that could never
start. The refusal was visible only as a red dispatch job and a watchdog page, so it is pinned here at authoring time.
"""
import glob
import os

import yaml

from scripts.research import script_run as sr

QUEUE = os.path.join(os.path.dirname(__file__), "..", "research", "queue")


def _timeouts():
    for f in sorted(glob.glob(os.path.join(QUEUE, "*.yaml"))):
        try:
            d = yaml.safe_load(open(f, encoding="utf-8")) or {}
        except Exception:
            continue
        t = (d.get("run") or {}).get("timeout_minutes")
        if t is not None:
            yield os.path.basename(f), t


def test_the_probe_finds_units_with_a_timeout():
    """Positive control on the finder: a vacuous pass over an empty queue would prove nothing."""
    assert len(list(_timeouts())) > 100


def test_every_declared_timeout_is_inside_the_preflight_range():
    bad = [f"{f}: {t}" for f, t in _timeouts() if not (sr.MIN_TIMEOUT_MIN <= t <= sr.MAX_TIMEOUT_MIN)]
    assert not bad, (f"these units declare a timeout script_run.plan refuses "
                     f"[{sr.MIN_TIMEOUT_MIN}, {sr.MAX_TIMEOUT_MIN}], so the dispatcher can never run them: " + "; ".join(bad))


def test_the_check_fires_on_a_planted_out_of_range_timeout():
    """Negative control: the same predicate rejects 360, the value that stranded the 8 units."""
    assert not (sr.MIN_TIMEOUT_MIN <= 360 <= sr.MAX_TIMEOUT_MIN)

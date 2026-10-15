#!/usr/bin/env python3
"""research-queue-health — the queue must hold enough runnable units and must
have dispatched something recently; otherwise PAGE.

WHY THIS EXISTS (operator, 2026-09-28, relayed by the manager): "keep
replenishing it" plus "ALARMS: if runnable units < 25 or no unit has run in
12h, send a Telegram ping". Silence is the failure this class always has:
a queue that ran dry, or a dispatcher that stopped firing, looks exactly like
a quiet, healthy one until someone looks.

WHAT IT CHECKS (population: every research/queue/**/*.yaml, read from the
checkout; never inferred from a receipt alone):
  H1  runnable units >= --min-runnable, where RUNNABLE means the dispatcher would
      fire it within the next cycle (status queued + a real *.yml run.workflow +
      due by the dispatcher's own rule: never run, or cadence elapsed). A `once`
      unit that already ran, or a monthly unit that ran yesterday, is queued but
      NOT runnable -- counting those (as this did until 2026-09-29) read 21
      runnable while 3 would fire, and the alarm stayed quiet on idle runners.
  H2  the newest last_dispatched_at across ALL units is younger than --max-idle-hours

SUPPLY, NOT JUST COUNT (RESEARCH-LOOP-AUDIT RC4, 2026-10-15,
docs/research/research-loop-audit-2026-10-15.md § 2d/§ 4). Until then an H1 the five
templates could not fill paged "a refill cannot close this gap" -- read as "research has
run out" -- while the programme plans held weeks of questions and the GPU / Kaggle-CPU /
trainer backends sat idle with nothing due. Now:
  * refill capacity counts READY programme nodes (queue_replenish's sixth source) beside
    template points, so a plan that unlocked questions triggers the refill (exit 3);
  * an H1 neither can fill but the programme AUTHORING QUEUE can is `H1-AUTHOR`: a drafting
    task for research-ops (4x/day, SKILL § E reads `--authoring-queue` first), printed as a
    warning, exit 0 -- it pages only when the authoring queue is empty too (nothing left to
    ask: the weekly programme review must re-plan) or alongside H2;
  * the floor is COMPUTED from the observed fire rate (`computed_floor`: FLOOR_HOURS of
    supply at fired_24h, never below 25) -- the research-ops SKILL derived 25 from 32
    fires/day and asked for a re-derivation whenever that moved by a third (it was 79).
    It drives the refill and the authoring signal; a PAGE still needs runnable < 25 (the
    alarm rings every hourly cycle, so a higher floor must not ring it more): between the
    two it is `H1-THIN`, a warning;
  * idle backends (free capacity, nothing due) from the newest
    comms/research/utilization/*.json are reported, so supply SHAPE is visible, not only size.

Exit 1 on a problem a refill cannot fix (an unfillable H1, or H2), so the caller
(research-queue-dispatch.yml's alarm step) pages; exit 3 (EXIT_REFILL) when the
ONLY problem is an H1 the committed templates can fill, so the caller fires
research-queue-replenish.yml instead of paging. `--self-test` plants all three.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from scripts.research.queue_grade import health  # noqa: E402

DEFAULT_MIN_RUNNABLE = 25
DEFAULT_MAX_IDLE_HOURS = 12.0
#: Exit code when the ONLY problem is an H1 the templates can fill: the caller
#: fires research-queue-replenish.yml instead of paging. Measured 2026-09-29
#: 10:07Z (manager, via lane M19-S1): runnable 8 of 58 on main with 153
#: unclaimed template points -- starved, but self-healing, and the refill is
#: daily while the dispatcher consumed up to 3 units every 6 h, so a bare
#: page would have rung after most cycles. Since 2026-10-06 the dispatcher
#: runs HOURLY (operator: the git infrastructure keeps the queue moving),
#: still capped at 3 research runs in flight, so the gap between refills
#: can only open faster -- the refill-before-page branch matters more, not
#: less. A page is for what a refill cannot fix: an unfillable gap, or a
#: dispatcher that stopped firing (12 h idle, queue_throughput.py).
EXIT_REFILL = 3
#: Hours of supply the floor must cover at the observed fire rate -- the research-ops SKILL's
#: own derivation (25 units = ~19 h at fired_24h 32, 2026-10-10), made mechanical.
FLOOR_HOURS = 19.0
UTILIZATION_DIR = Path("comms/research/utilization")


def computed_floor(fired_24h, *, minimum: int = DEFAULT_MIN_RUNNABLE) -> int:
    """max(minimum, ceil(fired_24h x FLOOR_HOURS / 24)); `minimum` when the rate is unread."""
    import math
    try:
        return max(minimum, math.ceil(float(fired_24h) * FLOOR_HOURS / 24.0))
    except (TypeError, ValueError):
        return minimum


def idle_backends(root: Path) -> dict:
    """{read_state, run_id, idle: [backend, ...]} from the newest utilization record: a backend is
    IDLE when it was measured, has a free slot after the cycle and had nothing due for it."""
    import json
    # Newest = the highest Actions run id (they only increase); NOT mtime -- a fresh checkout
    # stamps every file with the same mtime, so mtime picked an arbitrary old record.
    files = sorted((root / UTILIZATION_DIR).glob("*.json"),
                   key=lambda p: (p.stem.isdigit(), int(p.stem) if p.stem.isdigit() else 0, p.stem))
    if not files:
        return {"read_state": "could_not_look", "run_id": None, "idle": []}
    try:
        d = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"read_state": "could_not_look", "run_id": files[-1].stem, "idle": []}
    idle = sorted(name for name, b in (d.get("backends") or {}).items()
                  if isinstance(b, dict) and b.get("read_state") == "measured"
                  and int(b.get("free_slots_after") or 0) > 0 and int(b.get("due_total") or 0) == 0
                  and name != "runpod")    # runpod is a fallback, never a first choice: idle by design
    return {"read_state": "measured", "run_id": d.get("run_id"), "idle": idle}


def refill_capacity(root: Path, *, target: int) -> dict:
    """{deficit, capacity, fillable}: what a replenish at `target` could add
    from the committed templates right now (population: every unclaimed
    template point at HEAD's rosters and evidence)."""
    from scripts.research.queue_replenish import plan
    pl = plan(root, day="2030-01-01", target=target)
    templates = sum(int(v) for v in pl["candidates"].values())
    programme = int(pl.get("programme_ready") or 0)      # the programme source (absent before it lands)
    capacity = templates + programme
    deficit = max(0, int(pl["deficit"]))
    return {"deficit": deficit, "capacity": capacity, "templates": templates, "programme_ready": programme,
            "authoring_queue": int(pl.get("authoring_queue") or 0), "fillable": capacity >= deficit}


def grade(h: dict, *, min_runnable: int, max_idle_hours: float, refill: dict = None,
          page_floor: int = None) -> list:
    """Problem strings. An H1 the templates can fill is tagged `H1-REFILL` so the
    caller refills instead of paging (`refill` = refill_capacity(); None = not
    measured, graded as a plain H1 page)."""
    problems = []
    if h["runnable"] < min_runnable:
        base = (f"runnable units {h['runnable']} < {min_runnable} "
                f"(would fire within the next dispatch cycle; {h.get('queued', '?')} read queued, "
                f"of {h['units']} unit(s))")
        if refill and refill.get("fillable"):
            problems.append(f"H1-REFILL {base}; the templates hold {refill['capacity']} unclaimed point(s) "
                            f"for a deficit of {refill['deficit']} -- fire research-queue-replenish.yml, do not page")
        elif refill and int(refill.get("authoring_queue") or 0) > 0:
            problems.append(f"H1-AUTHOR {base}; templates + ready programme nodes hold {refill['capacity']} for a "
                            f"deficit of {refill['deficit']}, but the programme authoring queue holds "
                            f"{refill['authoring_queue']} ready question(s) -- research-ops drafts them "
                            "(queue_replenish.py --authoring-queue), do not page")
        elif page_floor is not None and h["runnable"] >= page_floor:
            # Below the COMPUTED floor but at or above the fixed paging floor: thin, not dry.
            # The dispatcher alarm pages every hourly cycle, so the computed floor drives refill and
            # authoring but never raises how often a page rings (RC4 design, 2026-10-15).
            problems.append(f"H1-THIN {base}; nothing to refill or author, runnable still >= the paging floor "
                            f"{page_floor} -- warn, do not page")
        else:
            cap = (f"; the templates hold only {refill['capacity']} point(s) for a deficit of {refill['deficit']}"
                   + ("" if refill.get("authoring_queue") is None else " and the programme authoring queue is empty")
                   if refill else "; refill capacity not measured")
            problems.append(f"H1 {base}{cap} -- a refill cannot close this gap")
    if h["hours_since_last_dispatch"] is None:
        problems.append("H2 no unit carries a last_dispatched_at at all -- nothing has ever run")
    elif h["hours_since_last_dispatch"] > max_idle_hours:
        problems.append(f"H2 last dispatch {h['hours_since_last_dispatch']} h ago > {max_idle_hours} h "
                        f"(newest stamp {h['last_dispatched_at']})")
    if h["unreadable"]:
        problems.append(f"H0 unreadable unit(s): {h['unreadable']}")
    return problems


def _self_test() -> int:
    import tempfile
    now = datetime(2030, 1, 10, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "research" / "queue").mkdir(parents=True)
        for i in range(3):   # daily units that ran 30 h ago: elapsed, so they fire next cycle
            (r / "research" / "queue" / f"RQ-20300101-{i+1:03d}.yaml").write_text(
                f"id: RQ-20300101-{i+1:03d}\nstatus: queued\ncadence: daily\nrun:\n  workflow: x.yml\n"
                f"last_dispatched_at: '{(now - timedelta(hours=30)).isoformat()}'\n")
        # PLANTED (manager, 2026-09-29): queued but NOT runnable -- a once-unit that already
        # ran and a monthly unit that ran yesterday. Both counted as runnable before.
        (r / "research" / "queue" / "RQ-20300101-010.yaml").write_text(
            f"id: RQ-20300101-010\nstatus: queued\ncadence: once\nrun:\n  workflow: x.yml\n"
            f"last_dispatched_at: '{(now - timedelta(hours=30)).isoformat()}'\n")
        (r / "research" / "queue" / "RQ-20300101-011.yaml").write_text(
            f"id: RQ-20300101-011\nstatus: queued\ncadence: monthly\nrun:\n  workflow: x.yml\n"
            f"last_dispatched_at: '{(now - timedelta(days=1)).isoformat()}'\n")
        h = health(r, now=now)
        assert h["queued"] == 5 and h["runnable"] == 3, h
        p = grade(h, min_runnable=25, max_idle_hours=12)
        assert any(x.startswith("H1 ") for x in p) and any(x.startswith("H2") for x in p), p
        # PLANTED (manager 2026-09-29 10:07Z): a fillable H1 is a REFILL (exit 3), not a
        # page; an unfillable one pages; an H2 beside a fillable H1 still pages.
        p_fill = grade(h, min_runnable=25, max_idle_hours=48, refill={"deficit": 22, "capacity": 153, "fillable": True})
        assert len(p_fill) == 1 and p_fill[0].startswith("H1-REFILL"), p_fill
        assert _exit_code(p_fill) == EXIT_REFILL
        p_dry = grade(h, min_runnable=25, max_idle_hours=48, refill={"deficit": 22, "capacity": 3, "fillable": False})
        assert len(p_dry) == 1 and p_dry[0].startswith("H1 ") and "cannot close" in p_dry[0], p_dry
        assert _exit_code(p_dry) == 1 and _exit_code(p_fill + ["H2 idle"]) == 1 and _exit_code([]) == 0
        assert grade(h, min_runnable=3, max_idle_hours=48) == []
        # RC4 (2026-10-15): an unfillable H1 with ready questions in the authoring queue is a
        # drafting task, not a page; with an empty authoring queue it still pages; H2 beside it pages.
        p_auth = grade(h, min_runnable=25, max_idle_hours=48,
                       refill={"deficit": 22, "capacity": 0, "fillable": False, "authoring_queue": 4})
        assert len(p_auth) == 1 and p_auth[0].startswith("H1-AUTHOR") and _exit_code(p_auth) == 0, p_auth
        p_none = grade(h, min_runnable=25, max_idle_hours=48,
                       refill={"deficit": 22, "capacity": 0, "fillable": False, "authoring_queue": 0})
        assert p_none[0].startswith("H1 ") and "authoring queue is empty" in p_none[0] and _exit_code(p_none) == 1
        assert _exit_code(p_auth + ["H2 idle"]) == 1
        # between the paging floor and the computed floor, with nothing to refill or author: warn only
        p_thin = grade(h, min_runnable=25, max_idle_hours=48, page_floor=3,
                       refill={"deficit": 22, "capacity": 0, "fillable": False, "authoring_queue": 0})
        assert p_thin[0].startswith("H1-THIN") and _exit_code(p_thin) == 0, p_thin
        # ready programme nodes count as refill capacity -> exit 3, not a page
        p_prog = grade(h, min_runnable=25, max_idle_hours=48,
                       refill={"deficit": 5, "capacity": 6, "templates": 0, "programme_ready": 6, "fillable": True})
        assert _exit_code(p_prog) == EXIT_REFILL
        # the computed floor: 19 h of supply at the observed rate, never below 25
        assert computed_floor(32) == 26 and computed_floor(79) == 63 and computed_floor(0) == 25 and computed_floor(None) == 25
        # idle backends: measured + free slot + nothing due; runpod never listed; unreadable -> could_not_look
        import json as _json
        ud = r / UTILIZATION_DIR
        ud.mkdir(parents=True)
        assert idle_backends(r)["read_state"] == "could_not_look"
        (ud / "1.json").write_text(_json.dumps({"run_id": "1", "backends": {
            "github_runner": {"read_state": "measured", "free_slots_after": 0, "due_total": 15},
            "kaggle": {"read_state": "measured", "free_slots_after": 1, "due_total": 0},
            "trainer": {"read_state": "could_not_look", "free_slots_after": 1, "due_total": 0},
            "runpod": {"read_state": "measured", "free_slots_after": 1, "due_total": 0}}}))
        assert idle_backends(r) == {"read_state": "measured", "run_id": "1", "idle": ["kaggle"]}, idle_backends(r)
        (r / "research" / "queue" / "RQ-20300101-004.yaml").write_text("id: RQ-20300101-004\nstatus: queued\nrun:\n  workflow: 'none — session-local'\n")
        assert health(r, now=now)["runnable"] == 3, "a session-bound note is not runnable"
        (r / "research" / "queue" / "RQ-20300101-005.yaml").write_text(": : [\n")
        assert any(x.startswith("H0") for x in grade(health(r, now=now), min_runnable=1, max_idle_hours=48))
    print("research-queue-health self-test OK")
    return 0


def _exit_code(problems: list) -> int:
    """0 clean, or only an H1-AUTHOR (a scheduled drafting task, warned, not paged);
    EXIT_REFILL when every other problem is a fillable H1; else 1 (page)."""
    pageable = [x for x in problems if not x.startswith(("H1-AUTHOR", "H1-THIN"))]
    if not pageable:
        return 0
    return EXIT_REFILL if all(x.startswith("H1-REFILL") for x in pageable) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--min-runnable", type=int, default=None,
                    help="floor override; default = computed_floor(fired_24h), never below 25")
    ap.add_argument("--max-idle-hours", type=float, default=DEFAULT_MAX_IDLE_HOURS)
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    h = health(_REPO)
    if args.min_runnable is None:
        try:
            from scripts.research.queue_throughput import throughput  # noqa: PLC0415
            fired = throughput(_REPO).get("fired_24h")
        except Exception as e:  # noqa: BLE001 -- an unread rate falls back to the fixed floor, said aloud
            fired = None
            print(f"::warning::research-queue-health: fired_24h unread ({e!r}); floor falls back to {DEFAULT_MIN_RUNNABLE}")
        args.min_runnable = computed_floor(fired)
        print(f"research-queue-health: floor {args.min_runnable} = max({DEFAULT_MIN_RUNNABLE}, ceil(fired_24h {fired} "
              f"x {FLOOR_HOURS:g} h / 24))")
    ib = idle_backends(_REPO)
    if ib["idle"]:
        print(f"::warning::research-queue-health: backend(s) idle with nothing due (utilization {ib['run_id']}): "
              f"{', '.join(ib['idle'])} -- author units whose compute class lands there (PLANNING.md § 1b)")
    refill = None
    if h["runnable"] < args.min_runnable:
        try:
            refill = refill_capacity(_REPO, target=args.min_runnable)
        except Exception as e:  # noqa: BLE001 -- an unreadable template store must PAGE, never read as fillable
            print(f"::warning::research-queue-health: could not measure refill capacity ({e!r}); grading H1 as a page")
    problems = grade(h, min_runnable=args.min_runnable, max_idle_hours=args.max_idle_hours, refill=refill,
                     page_floor=DEFAULT_MIN_RUNNABLE)
    print(f"research-queue-health: runnable={h['runnable']} of {h['units']} unit(s); last dispatch "
          f"{h['last_dispatched_at']} ({h['hours_since_last_dispatch']} h ago); needs_review={len(h['needs_review'])}"
          + (f"; refill capacity {refill['capacity']} (templates {refill['templates']}, programme nodes "
             f"{refill['programme_ready']}) for deficit {refill['deficit']}; authoring queue {refill['authoring_queue']}"
             if refill else ""))
    rc = _exit_code(problems)
    for p in problems:
        level = "warning" if p.startswith(("H1-AUTHOR", "H1-THIN")) else ("notice" if rc == EXIT_REFILL else "error")
        print(f"::{level}::research-queue-health: {p}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

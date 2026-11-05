#!/usr/bin/env python3
# wiring: manual-only - an on-demand read-only view run by sessions (CHECKLIST-STATE-TRUTH); WSD-S5-STATE-VIEWS will import stale_in_flight() into /api/bot/work/snapshot
"""staleInFlight: how many ``in_flight`` checklist rows have not been touched for > N hours.

CHECKLIST-STATE-TRUTH detector (docs/claude/work/checklist/CHECKLIST-STATE-TRUTH.json): the Work
card is only as true as the register, and ``in_flight`` goes false by time passing. This prints the
count WITH ITS DENOMINATOR (total rows, in_flight rows) and the stale ids. It is a VIEW over
``updated_at`` -- the same definition WSD-S5 (``WSD-S5-STATE-VIEWS``) will serve as
``/api/bot/work/snapshot`` ``staleInFlight`` once dispatch sets ``in_flight`` in the same call that
records the lane. Import ``stale_in_flight()`` there; do not re-derive it.

Report-only. It does not gate (operator, 2026-10-29: no new gates) and exit is 0 unless the store
cannot be read (exit 2 -- "could not look" is never printed as 0).
Age is evidence of staleness, not of the lane's death: confirm with get_session before changing a row.

Usage: stale_in_flight.py [--hours 48] [--json] | --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DEFAULT_HOURS = 48


def _parse(ts):
    try:
        return datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def stale_in_flight(rows, now=None, hours=DEFAULT_HOURS):
    """Return {total, in_flight, stale, unreadable_ts, hours, rows:[{id, age_hours, lane, owner}]}.

    A row with no readable ``updated_at`` counts as stale (we could not show it is fresh) and is
    also counted in ``unreadable_ts`` so the reader can tell.
    """
    now = now or datetime.now(timezone.utc)
    rows = list(rows)
    infl = [r for r in rows if r.get("state") == "in_flight"]
    out, bad = [], 0
    for r in infl:
        t = _parse(r.get("updated_at"))
        if t is None:
            bad += 1
            out.append({"id": r.get("id"), "age_hours": None, "lane": r.get("lane"), "owner": r.get("owner")})
        elif now - t > timedelta(hours=hours):
            out.append({"id": r.get("id"), "age_hours": round((now - t).total_seconds() / 3600, 1),
                        "lane": r.get("lane"), "owner": r.get("owner")})
    out.sort(key=lambda x: -(x["age_hours"] if x["age_hours"] is not None else 1e9))
    return {"total": len(rows), "in_flight": len(infl), "stale": len(out),
            "unreadable_ts": bad, "hours": hours, "rows": out}


def _self_test() -> int:
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    def mk(i, st, ts):
        return {"id": i, "state": st, "updated_at": ts}

    rows = [mk("fresh", "in_flight", "2026-11-05T00:00:00Z"), mk("old", "in_flight", "2026-11-01T00:00:00Z"),
            mk("edge", "in_flight", "2026-11-03T12:00:00Z"), mk("bad", "in_flight", "garbage"),
            mk("doneold", "done", "2026-10-01T00:00:00Z")]
    r = stale_in_flight(rows, now)
    assert (r["total"], r["in_flight"], r["stale"], r["unreadable_ts"]) == (5, 4, 2, 1), r
    assert {x["id"] for x in r["rows"]} == {"old", "bad"}, r  # exactly 48h is not stale; done rows never count
    assert stale_in_flight([], now)["stale"] == 0
    print("stale_in_flight self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=DEFAULT_HOURS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    try:
        from src.runtime import checklist_store as ck
        doc = ck.load()
        rows = [r for r in (doc.get("items") or []) if isinstance(r, dict)]
        if not rows:
            raise ValueError("checklist store returned no rows")
    except Exception as exc:  # noqa: BLE001 -- could-not-look must be loud, never 0
        print(f"stale_in_flight: COULD NOT LOOK ({exc})", file=sys.stderr)
        return 2
    res = stale_in_flight(rows, hours=a.hours)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"staleInFlight={res['stale']} of in_flight={res['in_flight']} (checklist rows={res['total']}; "
              f"threshold >{res['hours']:g}h since updated_at; unreadable_ts={res['unreadable_ts']})")
        for x in res["rows"]:
            print(f"  {x['id']}  age_h={x['age_hours']}  lane={x['lane']}  owner={x['owner']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

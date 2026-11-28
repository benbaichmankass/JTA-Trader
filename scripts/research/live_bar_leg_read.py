#!/usr/bin/env python3
# wiring: manual-only - run by a research/queue unit (research-script-run.yml) to grade ONE leg against the live bar from the
# committed daily feed; first unit RQ-20261128-f1a5-04 (claude_desk).
"""Grade one leg against the LIVE BAR from the committed feed ``comms/live_bar/latest.json`` (written daily by live-bar.yml).

Why a feed reader: the research runner holds no diag token, so it cannot read the journal; the feed is the live bar the
operator's promotion path already uses (OPERATING-PLAN § 2 "Live-performance promotion path"; scripts/research/live_bar.py).

Writes ``<out>/verdict.json`` in the runner's result contract:
  * feed missing / unreadable / older than ``--max-age-h`` (default 26, the feed row's own freshness bar) -> read_state
    ``no_data`` (a non-verdict outcome: the dispatcher re-runs it, it never reads as a measurement);
  * leg absent from a fresh feed -> ``no_data``;
  * leg present: read_state ``measured``; verdict ``pass`` / ``fail`` from the feed's own live-bar verdict, ``indeterminate``
    for ``n_short`` (fewer than the bar's minimum confirmed trades). The verdict is copied, never recomputed here.

    python3 scripts/research/live_bar_leg_read.py --leg claude_desk --out OUT_DIR
    python3 scripts/research/live_bar_leg_read.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO = Path(__file__).resolve().parents[2]
FEED = REPO / "comms" / "live_bar" / "latest.json"
_MAP = {"pass": "pass", "fail": "fail", "n_short": "indeterminate"}


def read(leg: str, feed: Path, now: datetime, max_age_h: float) -> Dict[str, Any]:
    base: Dict[str, Any] = {"schema": "live_bar_leg_read/v1", "leg": leg, "feed": str(feed.relative_to(REPO)
                            if feed.is_relative_to(REPO) else feed), "computed_at": now.isoformat(timespec="seconds"),
                            "provenance": "MEASURED"}
    try:
        doc = json.loads(feed.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {**base, "read_state": "no_data", "verdict": None, "n": None, "note": f"feed unreadable: {e}"}
    gen = doc.get("generated_at")
    try:
        age_h = (now - datetime.fromisoformat(str(gen))).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return {**base, "read_state": "no_data", "verdict": None, "n": None, "note": f"feed generated_at unreadable: {gen!r}"}
    base["feed_generated_at"], base["feed_age_h"] = gen, round(age_h, 2)
    if age_h > max_age_h:
        return {**base, "read_state": "no_data", "verdict": None, "n": None,
                "note": f"feed is {age_h:.1f} h old (> {max_age_h} h): not graded on a stale read"}
    v = (doc.get("legs") or {}).get(leg)
    if not isinstance(v, dict):
        return {**base, "read_state": "no_data", "verdict": None, "n": None, "note": f"{leg} not in the feed"}
    verdict = _MAP.get(str(v.get("verdict")))
    if verdict is None:
        return {**base, "read_state": "no_data", "verdict": None, "n": v.get("n"),
                "note": f"feed verdict {v.get('verdict')!r} is not a live-bar outcome"}
    return {**base, "read_state": "measured", "verdict": verdict, "n": v.get("n"),
            "population": f"{leg}: {v.get('n')} confirmed-R closed trades (declared_initial basis) in the live-bar feed "
                          f"generated {gen}; pooled {v.get('pooled')}",
            "measurement": {k: v.get(k) for k in ("n", "sum_r", "mean_r", "lcb80", "verdict", "pooled",
                                                  "stop_unmoved_subset", "pnl_measured_subset")},
            "rule": doc.get("rule"),
            "note": f"live bar (>= {((doc.get('rule') or {}).get('min_n'))} confirmed, sum R > 0, 80% LCB > 0): "
                    f"feed verdict {v.get('verdict')} -> {verdict}"}


def _self_test() -> int:
    import tempfile
    fails = []

    def chk(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)
    now = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "latest.json"
        chk("missing feed -> no_data", read("x", f, now, 26)["read_state"] == "no_data")

        def feed(gen: str, legs: Dict[str, Any]) -> None:
            f.write_text(json.dumps({"generated_at": gen, "rule": {"min_n": 20}, "legs": legs}))
        feed("2026-11-24T16:29:35+00:00", {"x": {"verdict": "pass", "n": 25}})
        chk("stale feed (> 26 h) -> no_data, never a verdict", read("x", f, now, 26)["read_state"] == "no_data")
        feed("2026-12-01T06:00:00+00:00", {"x": {"verdict": "pass", "n": 25, "sum_r": 9.0, "lcb80": 0.2}})
        r = read("x", f, now, 26)
        chk("fresh pass -> measured pass, n carried", r["read_state"] == "measured" and r["verdict"] == "pass" and r["n"] == 25)
        feed("2026-12-01T06:00:00+00:00", {"x": {"verdict": "n_short", "n": 13}})
        chk("n_short -> indeterminate", read("x", f, now, 26)["verdict"] == "indeterminate")
        feed("2026-12-01T06:00:00+00:00", {"x": {"verdict": "fail", "n": 22}})
        chk("fail -> fail", read("x", f, now, 26)["verdict"] == "fail")
        chk("leg absent -> no_data", read("y", f, now, 26)["read_state"] == "no_data")
    print("self-test: " + ("PASS" if not fails else f"FAIL ({len(fails)})"))
    return 1 if fails else 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--leg")
    ap.add_argument("--out")
    ap.add_argument("--feed", default=str(FEED))
    ap.add_argument("--max-age-h", type=float, default=26.0)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.leg and a.out):
        ap.error("--leg and --out are required (or --self-test)")
    rec = read(a.leg, Path(a.feed), datetime.now(timezone.utc), a.max_age_h)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: rec.get(k) for k in ("leg", "read_state", "verdict", "n", "note")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

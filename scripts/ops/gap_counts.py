#!/usr/bin/env python3
# wiring: called once per 5-min firing by scripts/ops/work_digest_now.py::main (deploy/ict-work-digest.timer, after
# attention_watch.alert_watch); served read-only at GET /api/bot/work/gaps (src/web/api/routers/work_gaps.py).
"""WORK-GAP-ALERTS: two gap NUMBERS, and a non-zero one is routed to the manager's alert path.

(a) ``insights_no_link``  -- ``kind: insight`` pipeline items (latest record per id) whose ``links`` list is empty.
(b) ``milestones_no_topic`` -- milestones in ``docs/roadmap/milestones.yaml`` with no entry in ``docs/roadmap/topics.yaml``
    (the topic map, WORK-TOPIC-TAXONOMY).

Each count carries its POPULATION and a READ-STATE. A source that could not be read is ``could_not_look`` with ``n: null``
-- never ``0``. Routing: a non-zero count (or a could-not-look) appends ONE ``work_gap`` row to the alert ledger
(channel ``system``, priority ``high``) so ``alerts_ledger.wakes_manager`` fires and ``attention_watch.alert_watch``
wakes the manager. Operator decision 2026-11-12 (m12): "The manager needs to get these alerts and handle immediately".

Gates this adds or changes: **none**. No CI check (insight-link-guard / topic-map-guard were refused by the operator).
Emission is best-effort, swallowed on failure, and re-sent only when the gap set changes or every ``REALERT_HOURS``.

Usage: ``python3 scripts/ops/gap_counts.py [--emit] [--dry-run]`` (default: print the numbers, send nothing).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REALERT_HOURS = 6
KIND = "work_gap"
STATE_NAME = "gap_alert_state.json"


def insights_no_link(root: Path) -> Dict[str, Any]:
    """Insights whose ``links`` list is empty. Dangling links are a separate thing, already on /api/bot/work/ledger."""
    out: Dict[str, Any] = {"gap": "insights_no_link", "n": None, "ids": [], "read_state": "could_not_look",
                           "population": {"source": "docs/claude/work/pipeline (kind=insight, latest record per id)",
                                          "n_insights_total": None}}
    try:
        from scripts.ops import pipeline  # noqa: PLC0415
        res = pipeline.read_log(root / pipeline.STORE)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out
    every = [it for it in res.items.values() if it.get("kind") == "insight"]
    ids = sorted(str(it.get("id")) for it in every if not it.get("links"))
    out.update(n=len(ids), ids=ids, read_state="partial" if res.unreadable else "measured",
               n_unreadable_records=len(res.unreadable))
    out["population"]["n_insights_total"] = len(every)
    return out


def milestones_no_topic(root: Path) -> Dict[str, Any]:
    """Milestones with no ``docs/roadmap/topics.yaml`` entry (the same rule as GET /api/bot/work/topics ``coverage``)."""
    out: Dict[str, Any] = {"gap": "milestones_no_topic", "n": None, "ids": [], "read_state": "could_not_look",
                           "population": {"source": "docs/roadmap/milestones.yaml vs docs/roadmap/topics.yaml",
                                          "n_milestones": None}}
    try:
        import yaml  # noqa: PLC0415
        tmap = (yaml.safe_load((root / "docs/roadmap/topics.yaml").read_text(encoding="utf-8")) or {}).get("topics") or {}
        ms = (yaml.safe_load((root / "docs/roadmap/milestones.yaml").read_text(encoding="utf-8")) or {}).get("milestones") or []
        tmap = {str(k) for k, v in tmap.items() if isinstance(v, dict) and v.get("topic")}   # same rule as work_topics.load_topic_map
        mids = [str(m["id"]) for m in ms if isinstance(m, dict) and m.get("id")]
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out
    if not mids:   # an empty milestone list means we did not find the population, not "no gaps"
        out["reason"] = "no milestones parsed from milestones.yaml"
        return out
    missing = sorted(set(mids) - set(tmap))
    out.update(n=len(missing), ids=missing, read_state="measured")
    out["population"]["n_milestones"] = len(mids)
    return out


def compute(root: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(root or REPO_ROOT)
    return {"as_of": datetime.now(timezone.utc).isoformat(), "gaps": [insights_no_link(root), milestones_no_topic(root)]}


def needs_attention(gap: Dict[str, Any]) -> bool:
    """Non-zero OR could-not-look. A zero from an unread source is not a zero."""
    return gap.get("n") is None or gap["n"] > 0


def _line(g: Dict[str, Any]) -> str:
    pop = g["population"]
    denom = pop.get("n_insights_total", pop.get("n_milestones"))
    if g.get("n") is None:
        return f"{g['gap']}: COULD NOT LOOK ({g.get('reason')})"
    head = ", ".join(g["ids"][:5]) + (f" +{len(g['ids']) - 5} more" if len(g["ids"]) > 5 else "")
    return f"{g['gap']}: {g['n']} of {denom} [{g['read_state']}]" + (f" -- {head}" if g["ids"] else "")


def emit(result: Dict[str, Any], *, now: Optional[datetime] = None, state_path: Optional[Path] = None,
         ledger_path: Optional[Path] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Append one alert-ledger row when any gap needs attention AND (the gap set changed OR REALERT_HOURS passed).
    Returns ``{state: nothing_to_alert|held_unchanged|emitted|dry_run|ledger_write_failed, ...}``. Never raises."""
    now = now or datetime.now(timezone.utc)
    rec: Dict[str, Any] = {"state": "nothing_to_alert"}
    try:
        bad = [g for g in result["gaps"] if needs_attention(g)]
        sig = json.dumps([[g["gap"], g.get("n"), g["ids"]] for g in bad], sort_keys=True)
        if state_path is None:
            from src.utils.paths import runtime_logs_dir  # noqa: PLC0415
            state_path = Path(runtime_logs_dir()) / STATE_NAME
        prev: Dict[str, Any] = {}
        try:
            prev = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  # allow-silent: no/unreadable state => treat as first run, alert
            prev = {}
        if not bad:
            if prev and not dry_run:
                state_path.write_text(json.dumps({"sig": "", "at": now.isoformat()}), encoding="utf-8")
            return rec
        last = None
        try:
            last = datetime.fromisoformat(prev["at"])
        except Exception:  # noqa: BLE001
            last = None
        if prev.get("sig") == sig and last and now - last < timedelta(hours=REALERT_HOURS):
            return {"state": "held_unchanged", "signature": sig}
        body = "WORK GAPS need handling (no CI gate; operator m12 2026-11-12)\n" + "\n".join(_line(g) for g in bad)
        rec.update(body=body)
        if dry_run:
            rec["state"] = "dry_run"
            return rec
        from src.runtime import alerts_ledger  # noqa: PLC0415
        # dedup_key is stable per gap-set so alert_watch collapses repeats; system+high => wakes_manager
        ok = alerts_ledger.append(KIND, "system", body, priority="high", dedup_key=f"{KIND}:{sig[:60]}",
                                  delivered="unknown", path=ledger_path)
        if not ok:
            rec["state"] = "ledger_write_failed"
            return rec
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"sig": sig, "at": now.isoformat()}), encoding="utf-8")
        rec["state"] = "emitted"
    except Exception as exc:  # noqa: BLE001 -- never gates the digest unit
        rec.update(state="error", reason=f"{type(exc).__name__}: {exc}")
    return rec


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit", action="store_true", help="route non-zero gaps to the alert ledger")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    res = compute()
    for g in res["gaps"]:
        print(_line(g))
    if a.emit or a.dry_run:
        print("gap-alerts:", emit(res, dry_run=a.dry_run)["state"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

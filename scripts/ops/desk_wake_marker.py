#!/usr/bin/env python3
# wiring: called by .github/workflows/desk-scan-packet.yml (the last steps of the packet job); no schedule of its own.
"""DESK-6B -- the step that LANDS the scan packet is the step that posts the desk wake.

Operator, 2026-10-26 ~16:50Z: *"the system landing the packet [should be] what triggers the session ...
the session shouldn't be starting before the packet lands."* So there is no clock-timed or polled
wake: ``desk-scan-packet.yml`` builds the packet, commits it to ``desk/decisions``, and its next step
runs ``post`` here, which posts ONE ``desk-wake`` marker on the ops-flags PR carrying that packet's id,
sha and commit sha. The manager is subscribed to the PR; on the marker it ``create_session``s the wake
exactly as ``.claude/skills/trading-desk/SKILL.md`` § 6b specifies. Nothing else posts a desk-wake.

Why this is the FALLBACK: GitHub's cron never fired this workflow on schedule (MEASURED by the manager
2026-10-26: only workflow_dispatch runs), so the live trader builds the packet itself and is the primary
producer; this job runs when ``schedule-keeper`` dispatches it for a missed hour and does nothing when the
bar already has a packet (``gate``).

Every hour wakes (crypto is 24/7): no market or activity gate. The packet's context rides the marker as
information only. Dedupe is on the packet id AND the bar: the VM (``src/runtime/desk_packet_wake.py``) is the
PRIMARY producer and this workflow the fallback, so at most one wake is posted per bar whichever lands first.
A failed build posts no wake: the job's failure step runs ``fail``, which posts one ``could_not_build``
incident marker (named step, run url) per bar.

Usage:
  desk_wake_marker.py gate [--ref origin/desk/decisions] [--github-output FILE]
  desk_wake_marker.py post --stage DIR --commit SHA [--run-url URL] [--live]
  desk_wake_marker.py fail --step NAME [--run-url URL] [--live]
  desk_wake_marker.py --self-test
Exit: 0 posted / already posted / printed · 1 could not post · 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MARKER = "desk-wake"
NEAR_BARS = (0, 1)
REPO = os.environ.get("GITHUB_REPOSITORY", "benbaichmankass/JTA-Trader")  # tolerant of the JTA Trader repo rename


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bar_of(cutoff: str) -> str:
    d = datetime.fromisoformat(cutoff.replace("Z", "+00:00")).astimezone(timezone.utc)
    return _iso(d.replace(minute=0, second=0, microsecond=0))


def parse_markers(comments: Optional[list]) -> List[dict]:
    out: List[dict] = []
    for c in comments or []:
        body = str((c or {}).get("body") or "")
        i = body.find(f"<!-- {MARKER} ")
        if i < 0:
            continue
        j = body.find("-->", i)
        try:
            out.append(json.loads(body[i + len(MARKER) + 6:j]))
        except ValueError:
            continue
    return out


def _calendar_events(universe: List[dict], now: datetime) -> List[str]:
    out: List[str] = []
    try:
        from src.news.news_events import event_risk_for_symbol
    except Exception:  # noqa: BLE001
        event_risk_for_symbol = None  # type: ignore[assignment]
    for r in universe:
        sym = str(r.get("symbol"))
        cal = r.get("calendar") or {}
        if cal.get("read_state") == "read" and cal.get("events_next_bar"):
            out.append(f"{sym}:packet:{','.join(map(str, cal['events_next_bar']))}")
            continue
        if event_risk_for_symbol is not None:
            try:
                risk, meta = event_risk_for_symbol(sym, now)
            except Exception:  # noqa: BLE001
                continue
            if risk and risk > 0:
                out.append(f"{sym}:{meta.get('class')}@{meta.get('time')} risk={risk:.2f}")
    return out


def packet_context(packet: dict, now: datetime) -> Dict[str, Any]:
    """Pure. What the packet holds, recorded on the marker. It never decides whether to wake.
    An unread book is ``None`` (we could not look), never 0."""
    sb, db = packet.get("system_book") or {}, packet.get("desk_book") or {}
    sb_ok = sb.get("read_state") == "read" and sb.get("items") is not None
    db_ok = db.get("read_state") == "read" and db.get("items") is not None
    items = [i for i in (sb.get("items") or []) if isinstance(i, dict)] if sb_ok else []
    unread = [n for n, ok in (("system_book", sb_ok), ("desk_book", db_ok)) if not ok]
    if sb_ok and sb.get("near_signals_read_state") != "read":
        unread.append("near_signals")
    near_ok = sb_ok and sb.get("near_signals_read_state") == "read"
    return {
        "open_positions": sum(1 for i in items if i.get("status") == "open") if sb_ok else None,
        "open_desk_proposals": len(db["items"]) if db_ok else None,
        "near_signals": (sum(1 for i in items if i.get("status") != "open" and i.get("bars_to_signal") in NEAR_BARS)
                         if near_ok else None),
        "calendar_events": _calendar_events([r for r in packet.get("universe") or [] if isinstance(r, dict)], now)[:4],
        "unread": unread,
    }


def render_wake(entry: Dict[str, Any], now: datetime, run_url: str = "") -> str:
    c = entry["context"]
    info = (f"open positions {c['open_positions']}, open desk proposals {c['open_desk_proposals']}, "
            f"near signals {c['near_signals']}, calendar events {len(c['calendar_events'])}, "
            f"unread {c['unread'] or 'none'}")
    marker = dict(entry, kind="desk-wake", posted_at=now.isoformat())
    return "\n".join([
        f"**desk-wake: packet `{entry['packet_id']}`** (bar {entry['bar']}, sha `{str(entry['packet_sha'])[:12]}`, "
        f"commit `{str(entry['commit'])[:10]}`) landed on `desk/decisions`. Manager: `create_session` the desk wake exactly "
        "as `.claude/skills/trading-desk/SKILL.md` § 6b specifies (outcome_branch/source_revision `desk/decisions`, "
        "the WAKE PROMPT).",
        "", f"Packet context (information only; every bar wakes): {info}", "",
        *([f"Run: {run_url}", ""] if run_url else []),
        f"<!-- {MARKER} {json.dumps(marker, separators=(',', ':'), default=str)} -->",
        "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


def render_fail(step: str, bar: str, now: datetime, run_url: str = "") -> str:
    marker = {"kind": "could_not_build", "bar": bar, "step": step, "posted_at": now.isoformat()}
    return "\n".join([
        f"**desk-wake: could_not_build** — the scan-packet job failed at step `{step}` for bar {bar}. "
        "NO wake was posted for it (the session must not start before a packet lands). Incident: fix the job or tell "
        "the operator; the next hourly run retries.",
        "", *([f"Run: {run_url}", ""] if run_url else []),
        f"<!-- {MARKER} {json.dumps(marker, separators=(',', ':'))} -->",
        "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


def plan_post(entry: Dict[str, Any], markers: List[dict]) -> str:
    """'post' or 'already_posted'. Dedupe on the packet id and on the bar (two producers, one wake per bar)."""
    return "already_posted" if any(m.get("packet_id") == entry["packet_id"]
                                   or (m.get("kind") == "desk-wake" and m.get("bar") == entry["bar"])
                                   for m in markers) else "post"


def plan_fail(bar: str, markers: List[dict]) -> str:
    return "already_posted" if any(m.get("kind") == "could_not_build" and m.get("bar") == bar for m in markers) else "post"


def build_entry(stage: Path, commit: str, now: datetime) -> Dict[str, Any]:
    ptr = json.loads((stage / "comms/desk/latest_scan.json").read_text())
    pk = json.loads((stage / ptr["path"]).read_text())
    return {"bar": bar_of(ptr["info_cutoff_at"]), "packet_id": ptr["packet_id"], "packet_sha": ptr["packet_sha"],
            "path": ptr["path"], "built_at": ptr["built_at"], "commit": commit, "poster": "packet-job",
            "context": packet_context(pk, now)}


def _read_markers(repo: str, pr: int) -> Optional[List[dict]]:
    from live_review_wake import _gh
    out = _gh(["api", "--paginate", f"repos/{repo}/issues/{pr}/comments?per_page=100",
               "--jq", f'.[] | select(.body | contains("<!-- {MARKER} ")) | {{body: .body}}'])
    if out is None:
        return None
    return parse_markers([json.loads(line) for line in out.splitlines() if line.strip()])


def _comment(repo: str, pr: int, body: str) -> bool:
    from live_review_wake import _gh
    return _gh(["pr", "comment", str(pr), "--repo", repo, "--body", body]) is not None


def _gate(ref: str, out: Optional[Path]) -> int:
    """skip=true when the newest packet on the branch already belongs to the CURRENT hour (the VM built it)."""
    import subprocess
    r = subprocess.run(["git", "show", f"{ref}:comms/desk/latest_scan.json"], capture_output=True, text=True, cwd=ROOT)
    skip = False
    if r.returncode == 0:
        try:
            skip = bar_of(json.loads(r.stdout)["info_cutoff_at"]) == _iso(
                datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0))
        except (ValueError, KeyError):
            skip = False
    print(f"desk-wake-marker gate: skip={'true' if skip else 'false'}")
    if out:
        with out.open("a") as f:
            f.write(f"skip={'true' if skip else 'false'}\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gate")
    g.add_argument("--ref", default="origin/desk/decisions")
    g.add_argument("--github-output", type=Path, default=None)
    for name in ("post", "fail"):
        s = sub.add_parser(name)
        s.add_argument("--run-url", default="")
        s.add_argument("--live", action="store_true", help="post the comment (default: print only)")
        s.add_argument("--pr", type=int, default=None)
        if name == "post":
            s.add_argument("--stage", type=Path, required=True)
            s.add_argument("--commit", required=True)
        else:
            s.add_argument("--step", required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.cmd:
        ap.error("a command (post|fail) is required")
    import os

    if a.cmd == "gate":
        return _gate(a.ref, a.github_output)
    from live_review_wake import ops_flags_pr
    pr = a.pr or ops_flags_pr()
    repo = os.environ.get("GITHUB_REPOSITORY", REPO)
    now = datetime.now(timezone.utc)
    markers = _read_markers(repo, pr) if a.live else []
    if markers is None:
        print(f"::error::cannot read ops-flags PR #{pr} comments: dedupe unknown, not posting", file=sys.stderr)
        return 1
    if a.cmd == "post":
        entry = build_entry(a.stage, a.commit, now)
        verdict, body = plan_post(entry, markers), render_wake(entry, now, a.run_url)
    else:
        bar = _iso(now.replace(minute=0, second=0, microsecond=0))
        verdict, body = plan_fail(bar, markers), render_fail(a.step, bar, now, a.run_url)
    print(f"desk-wake-marker {a.cmd}: {verdict}")
    if verdict != "post":
        return 0
    print(body)
    if a.live and not _comment(repo, pr, body):
        print("::error::posting the ops-flags comment failed", file=sys.stderr)
        return 1
    return 0


def _self_test() -> int:
    now = datetime(2026, 10, 26, 16, 40, tzinfo=timezone.utc)
    pk = {"universe": [{"symbol": "BTCUSDT", "calendar": {"read_state": "read", "events_next_bar": ["cpi"]}}],
          "system_book": {"read_state": "read", "near_signals_read_state": "read",
                          "items": [{"status": "open"}, {"status": "near", "bars_to_signal": 1}]},
          "desk_book": {"read_state": "could_not_look", "items": None}}
    c = packet_context(pk, now)
    ok = (c["open_positions"] == 1 and c["near_signals"] == 1 and c["open_desk_proposals"] is None
          and c["unread"] == ["desk_book"] and c["calendar_events"] == ["BTCUSDT:packet:cpi"])
    e = {"bar": "2026-10-26T16:00:00Z", "packet_id": "DP-x", "packet_sha": "a" * 64, "commit": "b" * 40, "context": c}
    body = render_wake(e, now)
    m = parse_markers([{"body": body}])
    other = dict(e, packet_id="DP-y")  # a second packet in the same bar must not wake again
    ok = ok and m and m[0]["packet_id"] == "DP-x" and plan_post(e, m) == "already_posted" and plan_post(e, []) == "post"
    ok = ok and plan_post(other, m) == "already_posted" and plan_post(dict(other, bar="2026-10-26T17:00:00Z"), m) == "post"
    f = parse_markers([{"body": render_fail("Build the scan packet", "2026-10-26T16:00:00Z", now)}])
    ok = ok and plan_fail("2026-10-26T16:00:00Z", f) == "already_posted" and plan_fail("2026-10-26T17:00:00Z", f) == "post"
    print("desk-wake-marker self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

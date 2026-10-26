#!/usr/bin/env python3
"""Live trade review WAKE (LTR-1B part B): due event -> ONE ops-flags comment -> manager.

The operator, 2026-10-26: when a live-review trigger trips, the system itself
must get a message to the manager so it starts the LIVE-REVIEW lane. The wake
channel is an Actions poller (no new VM credential): every ~5 min
`.github/workflows/live-review-wake.yml` runs this, which

1. reads ``/api/diag/live_review_due`` through ``scripts/ops/diag_fetch.sh``;
2. keeps the due packages on a real-money or prop account (the
   ``due.events.daily_floor.accounts`` list in ``config/live_trade_review.yaml``,
   the one declared set) -- paper packages never wake anyone;
3. drops what was already posted (dedupe on ``package|event|level``) and what
   is inside the per ``package|event`` cooldown, both read back from this
   script's own hidden markers on the ops-flags PR (the same pattern as
   ``scripts/research/research_watchdog.py``);
4. posts ONE comment for everything newly due. The manager is subscribed to the
   PR, so the comment wakes it; it dispatches one LIVE-REVIEW lane per package
   (``.claude/skills/manager/SKILL.md`` § "Live-review wake").

``daily_floor`` never wakes: it is a time floor, not a market event, and the
hourly routine (the backstop) already covers it.

"Could not look" is never "nothing due": a failed read posts ONE flag per
``COULD_NOT_LOOK_COOLDOWN_MIN`` and the poller keeps trying (no halting).

Token-free (no model call). Tier 1: one diag GET and one PR comment.

Exit codes: 0 ran (posted or nothing new) · 1 could not look · 2 crashed/usage.
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
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
FETCH = ROOT / "scripts" / "ops" / "diag_fetch.sh"
CONFIG = ROOT / "config" / "live_trade_review.yaml"

WATCHDOG_CFG = ROOT / "scripts" / "research" / "research_watchdog.yaml"
MARKER = "ltr-wake"
#: Events that never wake the manager (the hourly routine covers them).
NO_WAKE_EVENTS = {"daily_floor"}
#: At most one wake per package+event in this window, unless the event is
#: cooldown-exempt in config (giveback, mechanics). INFERRED default: one 2h bar.
COOLDOWN_MIN = 120
COULD_NOT_LOOK_COOLDOWN_MIN = 360


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def load_cfg(path: Path = CONFIG) -> Dict[str, Any]:
    import yaml
    due = (yaml.safe_load(path.read_text()) or {}).get("due") or {}
    return {"accounts": set(((due.get("events") or {}).get("daily_floor") or {}).get("accounts") or []),
            "exempt": set(due.get("cooldown_exempt") or [])}


def ops_flags_pr(path: Path = WATCHDOG_CFG) -> int:
    """The ops-flags PR number, read from its ONE recorded place (never copied here)."""
    import yaml
    return int(((yaml.safe_load(path.read_text()) or {}).get("ops_flags") or {})["pr_number"])


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


def _key(e: dict) -> str:
    return f"{e.get('order_package_id')}|{e.get('event')}|{e.get('level')}"


def plan(doc: Any, posted: List[dict], cfg: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """What to post. Pure. ``kind`` in wake / could_not_look / quiet."""
    if not isinstance(doc, dict) or doc.get("read_state") != "looked" or doc.get("due_count") is None:
        reason = doc.get("reason") if isinstance(doc, dict) else "payload is not a JSON object"
        last = max((_ts(p.get("posted_at")) for p in posted if p.get("kind") == "could_not_look"
                    and _ts(p.get("posted_at"))), default=None)
        if last and now - last < timedelta(minutes=COULD_NOT_LOOK_COOLDOWN_MIN):
            return {"kind": "quiet", "why": f"could_not_look ({reason}); flagged {last.isoformat()}"}
        return {"kind": "could_not_look", "reason": str(reason or "unknown"), "entries": []}

    seen = {_key(e) for p in posted for e in p.get("entries") or []}
    last_by: Dict[str, datetime] = {}
    for p in posted:
        at = _ts(p.get("posted_at"))
        for e in p.get("entries") or []:
            k = f"{e.get('order_package_id')}|{e.get('event')}"
            if at and (k not in last_by or at > last_by[k]):
                last_by[k] = at
    grouped: Dict[str, dict] = {}
    for d in doc.get("due") or []:
        if str(d.get("account_id")) not in cfg["accounts"]:
            continue  # paper / soak: record-only, never a wake
        for ev in d.get("events") or []:
            name = ev.get("event")
            if name in NO_WAKE_EVENTS:
                continue
            e = {"order_package_id": d.get("order_package_id"), "leg": d.get("leg"),
                 "symbol": d.get("symbol"), "event": name, "level": ev.get("level"),
                 "why": ev.get("why"), "due_at": d.get("telemetry_updated_at") or doc.get("generated_at")}
            if _key(e) in seen:
                continue
            prev = last_by.get(f"{e['order_package_id']}|{name}")
            if prev and name not in cfg["exempt"] and now - prev < timedelta(minutes=COOLDOWN_MIN):
                continue
            g = grouped.setdefault(_key(e), dict(e, accounts=[]))
            if d.get("account_id") not in g["accounts"]:
                g["accounts"].append(d.get("account_id"))
    entries = sorted(grouped.values(), key=_key)
    return {"kind": "wake" if entries else "quiet", "entries": entries,
            "why": f"{doc.get('due_count')} due, {len(entries)} new real-money/prop wake(s)"}


def render(p: Dict[str, Any], now: datetime, run_url: str) -> str:
    marker = {"kind": p["kind"], "posted_at": now.isoformat(), "entries": p.get("entries") or []}
    if p["kind"] == "could_not_look":
        head = (f"**LTR wake: could not look** — `/api/diag/live_review_due` did not answer "
                f"`looked` ({p['reason']}). This is NOT \"nothing due\". The poller keeps trying; "
                f"next flag no sooner than {COULD_NOT_LOOK_COOLDOWN_MIN} min.")
        lines = []
    else:
        head = (f"**LTR wake: {len(p['entries'])} live-review event(s) newly due** on real-money/prop "
                "packages. Manager: dispatch ONE Sonnet LIVE-REVIEW lane per package "
                "(`.claude/skills/manager/SKILL.md` § Live-review wake).")
        lines = [f"- `{e['order_package_id']}` {e['leg']} {e['symbol']} on {', '.join(map(str, e['accounts']))}: "
                 f"**{e['event']}** @ {e['level']} — {e['why']} (due_at {e['due_at']})" for e in p["entries"]]
    return "\n".join([head, "", *lines, "", f"Run: {run_url}", "",
                      f"<!-- {MARKER} {json.dumps(marker, separators=(',', ':'), default=str)} -->",
                      "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


def _gh(args: List[str], retries: int = 4) -> Optional[str]:
    for i in range(retries):
        try:
            r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                return r.stdout
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2 ** (i + 1))
    return None


def read_posted(repo: str, pr: int) -> Optional[List[dict]]:
    # --paginate: the PR carries >100 comments and the API returns oldest first.
    out = _gh(["api", "--paginate", f"repos/{repo}/issues/{pr}/comments?per_page=100",
               "--jq", f'.[] | select(.body | contains("<!-- {MARKER} ")) | {{body: .body}}'])
    if out is None:
        return None
    return parse_markers([json.loads(line) for line in out.splitlines() if line.strip()])


def fetch_due() -> Any:
    r = subprocess.run(["bash", str(FETCH), "live_review_due"], capture_output=True, text=True)
    if r.returncode != 0:
        return {"read_state": "could_not_look", "reason": f"diag_fetch.sh exit {r.returncode}"}
    try:
        return json.loads(r.stdout)
    except ValueError as exc:
        return {"read_state": "could_not_look", "reason": f"non-JSON payload: {exc}"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="post the comment (default: print only)")
    ap.add_argument("--from-file", help="evaluate a saved due payload instead of fetching")
    ap.add_argument("--pr", type=int, default=None, help="default: research_watchdog.yaml ops_flags.pr_number")
    args = ap.parse_args(argv)
    args.pr = args.pr or ops_flags_pr()
    now = datetime.now(timezone.utc)
    repo = os.environ.get("GITHUB_REPOSITORY", "benbaichmankass/Metis-Insights")
    doc = json.loads(Path(args.from_file).read_text()) if args.from_file else fetch_due()
    posted = read_posted(repo, args.pr) if args.live else []
    if posted is None:
        print(f"::error::cannot read ops-flags PR #{args.pr} comments: dedupe unknown, not posting",
              file=sys.stderr)
        return 1
    p = plan(doc, posted, load_cfg(), now)
    body = render(p, now, os.environ.get("RUN_URL", "")) if p["kind"] != "quiet" else ""
    print(f"ltr-wake: {p['kind']} — {p.get('why') or p.get('reason')}")
    if body:
        print(body)
        if args.live and _gh(["pr", "comment", str(args.pr), "--repo", repo, "--body", body]) is None:
            print("::error::posting the ops-flags comment failed", file=sys.stderr)
            return 1
    return 1 if p["kind"] == "could_not_look" else 0


if __name__ == "__main__":
    sys.exit(main())

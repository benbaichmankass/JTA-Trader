#!/usr/bin/env python3
"""Live trade review WAKE (LTR-1B part B): due event -> ONE ops-flags comment -> manager.

The operator, 2026-10-26: when a live-review trigger trips, the system itself
must get a message to the manager so it starts the LIVE-REVIEW lane. The wake
channel is an Actions poller (no new VM credential): every ~5 min
`.github/workflows/live-review-wake.yml` runs this, which

1. reads ``/api/diag/live_review_due`` through ``scripts/ops/diag_fetch.sh``;
2. keeps the due packages on a reviewed account (the
   ``due.events.daily_floor.accounts`` list in ``config/live_trade_review.yaml``,
   the one declared set: real-money, prop and, since the operator's
   2026-10-26 "All accounts now", the paper and soak books) -- an account off
   that list never wakes anyone;
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
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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
#: LTR C2 (operator 2026-10-26 "VM pre-builds the packet"): each woken package's
#: decision packet + priced table ride the comment, so the reviewer needs no repo.
PACKET_BUILDER = ROOT / "scripts" / "ops" / "live_review_packet.py"
PACKET_TIMEOUT_S = 180
#: GitHub caps a comment at 65,536 chars; keep headroom for the head + marker.
MAX_BODY_CHARS = 60000
#: LTR-PACKET-ECHO (2026-10-27): the packet and its outcome table land on the rows branch BY MACHINE,
#: byte-exact, before the wake comment is posted, so a reviewer never re-types them (a reviewer's re-typed
#: packet dropped ``"sd_r":null`` and the mirror refused the row: packet_sha mismatch).
ROWS_BRANCH = "live-review/rows"
PACKETS_DIR = "comms/live_review/packets"
REPO = os.environ.get("GITHUB_REPOSITORY", "benbaichmankass/JTA-Trader")  # tolerant of the JTA Trader repo rename
API = "https://api.github.com"
HTTP_TIMEOUT_S = 15


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
            continue  # not a reviewed account: never a wake
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


def build_bundle(pkg: str, timeout: int = PACKET_TIMEOUT_S) -> Dict[str, Any]:
    """``live_review_packet.py <pkg> --bundle``: {state: built, packet, packet_sha, table_path, table}
    or {state: could_not_build, reason}. Never raises."""
    try:
        r = subprocess.run([sys.executable, str(PACKET_BUILDER), str(pkg), "--bundle"], cwd=ROOT,
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": "could_not_build", "reason": f"{type(exc).__name__}"}
    if r.returncode != 0:
        return {"state": "could_not_build", "reason": f"exit {r.returncode}: {r.stderr.strip()[-160:]}"}
    try:
        doc, _ = json.JSONDecoder().raw_decode(r.stdout.lstrip())
    except ValueError:
        return {"state": "could_not_build", "reason": "non-JSON builder output"}
    if not isinstance(doc, dict) or not doc.get("packet_sha"):
        return {"state": "could_not_build", "reason": "builder output has no packet_sha"}
    return dict(doc, state="built")


def attach_packets(p: Dict[str, Any], build=build_bundle) -> Dict[str, Dict[str, Any]]:
    """One bundle per woken package; stamps review_id / packet_sha / packet_state on its entries."""
    bundles: Dict[str, Dict[str, Any]] = {}
    for e in p.get("entries") or []:
        pkg = e.get("order_package_id")
        if pkg not in bundles:
            bundles[pkg] = build(pkg)
        b = bundles[pkg]
        e["packet_state"] = b["state"]
        if b["state"] == "built":
            e["review_id"] = (b.get("packet") or {}).get("review_id")
            e["packet_sha"] = b.get("packet_sha")
        else:
            e["packet_reason"] = b.get("reason")
    return bundles


def evidence_files(b: Dict[str, Any]) -> List[Tuple[str, bytes]]:
    """The rows-branch files a built bundle lands: the packet and (when priced) its table. Same bytes as
    ``live_review_packet.py --write`` writes on main, so the mirror copies them across unchanged."""
    pk = b.get("packet") or {}
    out = [(f"{PACKETS_DIR}/{pk.get('review_id')}.json", (json.dumps(pk, indent=1, sort_keys=True) + "\n").encode())]
    tp, table = b.get("table_path"), b.get("table")
    if isinstance(tp, str) and tp.startswith("comms/live_review/tables/") and ".." not in tp and table is not None:
        out.append((tp, (json.dumps(table, indent=2) + "\n").encode()))
    return out


Http = Callable[[str, str, Optional[bytes], str], Tuple[Optional[int], Any]]


def http_json(method: str, url: str, body: Optional[bytes], auth: str) -> Tuple[Optional[int], Any]:
    """(status, parsed JSON or None). Never raises; status None = no response."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": auth, "Accept": "application/vnd.github+json",
        "Content-Type": "application/json", "User-Agent": "metis-ltr-wake"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001 — a network failure is a state, never a raise
        return None, None


def _branch_blob(path: str, auth: str, http: Http) -> Tuple[str, Optional[bytes], Optional[int]]:
    """('absent' | 'present' | 'unknown', bytes, http code) for ``path`` at the rows-branch tip."""
    import urllib.parse
    code, doc = http("GET", f"{API}/repos/{REPO}/contents/{path}?ref={urllib.parse.quote(ROWS_BRANCH, safe='')}",
                     None, auth)
    if code == 404:
        return "absent", None, code
    if code == 200 and isinstance(doc, dict) and doc.get("encoding") == "base64":
        try:
            return "present", base64.b64decode(doc.get("content") or ""), code
        except ValueError:
            pass
    return "unknown", None, code


def commit_files(files: List[Tuple[str, bytes]], message: str, auth: str,
                 http: Http) -> Tuple[Optional[str], Optional[int]]:
    """ONE fast-forward commit adding ``files`` to the rows branch through the git data API (never forced;
    the same shape ``src/runtime/desk_packet_wake.py::commit_packet`` uses on desk/decisions, which needs
    no git credential on the VM). (commit sha, None) or (None, http code of the step that failed)."""
    base = f"{API}/repos/{REPO}/git"
    code: Optional[int] = None
    for _ in range(4):
        code, ref = http("GET", f"{base}/ref/heads/{ROWS_BRANCH}", None, auth)
        if code != 200 or not isinstance(ref, dict):
            return None, code
        head = ref["object"]["sha"]
        code, cm = http("GET", f"{base}/commits/{head}", None, auth)
        if code != 200 or not isinstance(cm, dict):
            return None, code
        entries = []
        for rel, data in files:
            code, blob = http("POST", f"{base}/blobs", json.dumps(
                {"content": base64.b64encode(data).decode(), "encoding": "base64"}).encode(), auth)
            if code != 201 or not isinstance(blob, dict):
                return None, code
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        code, tree = http("POST", f"{base}/trees", json.dumps({"base_tree": cm["tree"]["sha"], "tree": entries}).encode(), auth)
        if code != 201 or not isinstance(tree, dict):
            return None, code
        code, new = http("POST", f"{base}/commits", json.dumps(
            {"message": message, "tree": tree["sha"], "parents": [head]}).encode(), auth)
        if code != 201 or not isinstance(new, dict):
            return None, code
        code, _ = http("PATCH", f"{base}/refs/heads/{ROWS_BRANCH}", json.dumps({"sha": new["sha"], "force": False}).encode(), auth)
        if code == 200:
            return new["sha"], None
        if code != 422:  # 422 = not a fast-forward: someone appended first; re-read the tip and retry
            return None, code
    return None, code


def land_evidence(p: Dict[str, Any], bundles: Dict[str, Dict[str, Any]], auth: str,
                  http: Http = http_json) -> Dict[str, Dict[str, Any]]:
    """Land every built bundle's packet + table on the rows branch, create-only, in ONE commit, and stamp
    ``evidence_state`` on the entries. Per package: ``committed`` (``evidence_commit``) · ``exists`` (the
    same bytes are already there: an earlier pass) · ``evidence_conflict`` (a file of that name holds other
    bytes; never overwritten) · ``could_not_commit`` (``evidence_http_code``). A package that is not
    ``committed`` / ``exists`` has its bundle state set to that value, so its block does not ride the comment
    and no reviewer is started on evidence that is not on the branch. Never raises."""
    out: Dict[str, Dict[str, Any]] = {}
    need: List[Tuple[str, bytes]] = []
    need_pkgs: List[str] = []
    for pkg, b in bundles.items():
        if b.get("state") != "built":
            continue
        st: Dict[str, Any] = {"state": "exists"}
        mine: List[Tuple[str, bytes]] = []
        for rel, data in evidence_files(b):
            have, blob, code = _branch_blob(rel, auth, http)
            if have == "absent":
                mine.append((rel, data))
            elif have == "unknown":
                st = {"state": "could_not_commit", "http_code": code, "reason": f"could not read {rel}"}
                break
            elif blob != data:
                st = {"state": "evidence_conflict", "reason": f"{rel} exists on {ROWS_BRANCH} with other bytes"}
                break
        if st["state"] == "exists" and mine:
            need += mine
            need_pkgs.append(pkg)
            st = {"state": "pending"}
        out[pkg] = st
    if need:
        ids = ", ".join(str((bundles[k].get("packet") or {}).get("review_id")) for k in need_pkgs)
        sha, code = commit_files(need, f"live-review: evidence {ids} (machine, byte-exact)", auth, http)
        for k in need_pkgs:
            out[k] = ({"state": "committed", "commit": sha} if sha else
                      {"state": "could_not_commit", "http_code": code, "reason": "git data API commit failed"})
    for pkg, st in out.items():
        if st["state"] not in ("committed", "exists"):
            bundles[pkg] = dict(bundles[pkg], state=st["state"], reason=st.get("reason"))
    for e in p.get("entries") or []:
        st = out.get(e.get("order_package_id"))
        if not st:
            continue
        e["evidence_state"] = st["state"]
        if st.get("commit"):
            e["evidence_commit"] = st["commit"]
        if st["state"] not in ("committed", "exists"):
            e["packet_state"] = st["state"]
            e["packet_reason"] = st.get("reason")
            if st.get("http_code") is not None:
                e["evidence_http_code"] = st["http_code"]
    return out


def _bundle_block(pkg: str, b: Dict[str, Any]) -> str:
    doc = {k: b.get(k) for k in ("packet_sha", "table_path", "packet", "table")}
    return (f"<details><summary>review packet <code>{(b.get('packet') or {}).get('review_id')}</code> "
            f"(packet_sha <code>{str(b.get('packet_sha'))[:12]}</code>)</summary>\n\n"
            f"<!-- ltr-packet {pkg} -->\n```json\n{json.dumps(doc, sort_keys=True, separators=(',', ':'))}\n```\n</details>")


def render(p: Dict[str, Any], now: datetime, run_url: str,
           bundles: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    blocks: List[str] = []
    budget = MAX_BODY_CHARS - 4000 - 400 * len(p.get("entries") or [])
    for pkg, b in (bundles or {}).items():
        if b.get("state") != "built":
            continue
        blk = _bundle_block(pkg, b)
        if len(blk) > budget:
            for e in p.get("entries") or []:
                if e.get("order_package_id") == pkg:
                    e["packet_state"] = "omitted_too_large"
            continue
        budget -= len(blk)
        blocks.append(blk)
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
                 f"**{e['event']}** @ {e['level']} — {e['why']} (due_at {e['due_at']})"
                 + (f"; evidence on `{ROWS_BRANCH}`: **{e['evidence_state']}**"
                    + (f" `{str(e['evidence_commit'])[:12]}`" if e.get("evidence_commit") else "")
                    if e.get("evidence_state") else "")
                 for e in p["entries"]]
    return "\n".join([head, "", *lines, "", *blocks, "", f"Run: {run_url}", "",
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
    repo = os.environ.get("GITHUB_REPOSITORY", "benbaichmankass/JTA-Trader")
    doc = json.loads(Path(args.from_file).read_text()) if args.from_file else fetch_due()
    posted = read_posted(repo, args.pr) if args.live else []
    if posted is None:
        print(f"::error::cannot read ops-flags PR #{args.pr} comments: dedupe unknown, not posting",
              file=sys.stderr)
        return 1
    p = plan(doc, posted, load_cfg(), now)
    # The packet build is minutes of diag reads; a print-only run skips it.
    bundles = attach_packets(p) if (p["kind"] == "wake" and args.live) else None
    if bundles:
        # LTR-PACKET-ECHO: packet + table land on the rows branch by machine BEFORE the wake is posted.
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        ev = land_evidence(p, bundles, f"token {token}")
        print(f"ltr-wake: evidence {json.dumps(ev, sort_keys=True)}")
    body = render(p, now, os.environ.get("RUN_URL", ""), bundles) if p["kind"] != "quiet" else ""
    print(f"ltr-wake: {p['kind']} — {p.get('why') or p.get('reason')}")
    if body:
        print(body)
        if args.live and _gh(["pr", "comment", str(args.pr), "--repo", repo, "--body", body]) is None:
            print("::error::posting the ops-flags comment failed", file=sys.stderr)
            return 1
    return 1 if p["kind"] == "could_not_look" else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::reset-protocol-guard (--self-test); read by the manager skill
# § "Weekly reset protocol" and .github/workflows/reset-protocol-backup.yml.
"""The weekly reset protocol's machinery (operator, 2026-11-02).

Gates this adds or changes: none. This script reads config/reset_protocol.yaml and prints or records
facts; it dispatches nothing, edits no mode and halts nothing.

  --plan <reset-ts>      which jobs are due at that reset, with their due-at timestamps; after_reset items
                         not yet started. Cadence: weekly = every reset; monthly = the first reset of the
                         calendar month (UTC day-of-month <= 7 on the Wednesday reset); quarterly = the
                         first reset of Jan/Apr/Jul/Oct.
  --receipt <reset-ts>   --check            exit 0 + RECEIPT found, or exit 3 + NO_RECEIPT
                         --write started    the CLAIM, written FIRST by whichever trigger gets there; a
                                            second trigger finds it (exit 4) and stops
                         --write complete   the close-out line (needs a `started`, once)
                         Store: comms/ops/reset_receipts.jsonl, APPEND-ONLY (never rewritten). A new
                         store of this kind needs no table: it is a git-tracked JSONL the manager commits
                         and the backup workflow reads from `main` (db-wiring: no DB involved, no second
                         source of truth; nothing else records "did the protocol run").
  --sweep                the stuck-work list: checklist rows in_flight/blocked (this script cannot see
                         sessions, so it lists ROWS; pass --working-lanes to drop rows whose lane the manager
                         saw working in list_sessions), open PRs older than 12 h (needs GH_TOKEN; otherwise
                         the read-state says could_not_look, never an empty list), and PIPELINE items whose
                         due_when.event is `weekly_reset`.
  --self-test

Exit codes: 0 ok · 1 could not look / bad input · 3 no receipt · 4 receipt already exists.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "reset_protocol.yaml"
RECEIPTS = ROOT / "comms" / "ops" / "reset_receipts.jsonl"
CADENCES = ("weekly", "monthly", "quarterly")
JOB_KEYS = ("name", "cadence", "order", "offset_minutes", "model", "ceiling_usd", "skill", "dedupe_tag")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PR_STALE_HOURS = 12
RESET_EVENT = "weekly_reset"


class ProtocolError(ValueError):
    pass


def load_config(path: Path = CONFIG) -> dict:
    import yaml
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    if not isinstance(cfg, dict) or not isinstance(cfg.get("jobs"), list) or not cfg["jobs"]:
        raise ProtocolError("jobs: required non-empty list")
    r = cfg.get("reset") or {}
    if r.get("weekday") not in WEEKDAYS or not isinstance(r.get("hour_utc"), int):
        raise ProtocolError("reset: needs weekday and hour_utc")
    names = set()
    for j in cfg["jobs"]:
        for k in JOB_KEYS:
            if k not in j:
                raise ProtocolError(f"job {j.get('name')!r}: missing {k!r}")
        if j["cadence"] not in CADENCES:
            raise ProtocolError(f"job {j['name']}: cadence must be one of {CADENCES}")
        if not isinstance(j["offset_minutes"], int) or j["offset_minutes"] < 0:
            raise ProtocolError(f"job {j['name']}: offset_minutes must be a non-negative int")
        if not isinstance(j["ceiling_usd"], (int, float)) or j["ceiling_usd"] <= 0:
            raise ProtocolError(f"job {j['name']}: ceiling_usd must be positive")
        if j["name"] in names:
            raise ProtocolError(f"duplicate job name {j['name']}")
        names.add(j["name"])
    for j in cfg["jobs"]:
        if j.get("supersedes") and j["supersedes"] not in names:
            raise ProtocolError(f"job {j['name']}: supersedes unknown job {j['supersedes']!r}")
    keys = set()
    for a in cfg.get("after_reset") or []:
        if not a.get("key") or not a.get("reason"):
            raise ProtocolError("after_reset items need a key and a reason")
        if a["key"] in keys:
            raise ProtocolError(f"duplicate after_reset key {a['key']}")
        keys.add(a["key"])


def parse_reset(ts: str, cfg: dict) -> datetime:
    """The reset instant. A bare date, or any ISO time on that date, means that day's reset time."""
    try:
        d = datetime.fromisoformat(ts.strip().replace("Z", "+00:00")).date() if "T" in ts \
            else date.fromisoformat(ts.strip())
    except ValueError as exc:
        raise ProtocolError(f"bad reset timestamp {ts!r}: {exc}") from None
    r = cfg["reset"]
    return datetime(d.year, d.month, d.day, r["hour_utc"], r.get("minute_utc", 0), tzinfo=timezone.utc)


def is_due(job: dict, reset: datetime) -> bool:
    first_of_month = reset.day <= 7
    if job["cadence"] == "weekly":
        return True
    if job["cadence"] == "monthly":
        return first_of_month
    return first_of_month and reset.month in (1, 4, 7, 10)


def due_jobs(cfg: dict, reset: datetime) -> tuple[list[dict], list[tuple[str, str]]]:
    due = [j for j in cfg["jobs"] if is_due(j, reset)]
    superseded = {j["supersedes"]: j["name"] for j in due if j.get("supersedes")}
    kept = [j for j in due if j["name"] not in superseded]
    skipped = [(n, f"superseded by {by}") for n, by in sorted(superseded.items())]
    kept.sort(key=lambda j: (j["offset_minutes"], j["order"], j["name"]))
    return kept, skipped


# ---------------------------------------------------------------- receipts

def read_receipts(path: Path = RECEIPTS) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"{path}:{n}: unreadable receipt line ({exc})") from None
    return out


def receipts_for(reset: datetime, path: Path = RECEIPTS) -> list[dict]:
    key = reset.date().isoformat()
    return [r for r in read_receipts(path) if r.get("reset") == key]


def write_receipt(reset: datetime, event: str, by: str, data: dict | None, path: Path = RECEIPTS,
                  now: datetime | None = None) -> dict:
    have = receipts_for(reset, path)
    kinds = [r.get("event") for r in have]
    if event == "started" and "started" in kinds:
        raise FileExistsError("a `started` receipt already exists for this reset")
    if event == "complete":
        if "started" not in kinds:
            raise ProtocolError("no `started` receipt for this reset; write it first")
        if "complete" in kinds:
            raise FileExistsError("a `complete` receipt already exists for this reset")
    rec = {"reset": reset.date().isoformat(), "event": event, "by": by,
           "at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    rec.update(data or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:  # append-only: never rewrite earlier lines
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


# ---------------------------------------------------------------- plan / sweep

def started_after_reset_keys(path: Path = RECEIPTS) -> set[str]:
    keys: set[str] = set()
    for r in read_receipts(path):
        keys.update(r.get("after_reset_started") or [])
    return keys


def render_plan(cfg: dict, reset: datetime, receipts: Path = RECEIPTS) -> str:
    kept, skipped = due_jobs(cfg, reset)
    lines = [f"RESET {reset.strftime('%Y-%m-%dT%H:%MZ')} ({WEEKDAYS[reset.weekday()]})"
             + ("" if WEEKDAYS[reset.weekday()] == cfg["reset"]["weekday"]
                else f"  WARNING off-schedule: config says {cfg['reset']['weekday']}"),
             f"receipt: {'found' if receipts_for(reset, receipts) else 'none yet'}",
             "JOBS DUE (offset, due-at, name, cadence, model, $cap, dedupe tag):"]
    total = 0.0
    for j in kept:
        at = reset + timedelta(minutes=j["offset_minutes"])
        total += j["ceiling_usd"]
        extra = f" lookback={j['lookback_days']}d" if j.get("lookback_days") else ""
        lines.append(f"  +{j['offset_minutes']:>3}m {at.strftime('%H:%MZ')} {j['name']:<18} {j['cadence']:<9} "
                     f"{j['model']:<17} ${j['ceiling_usd']:<5g} {j['dedupe_tag']}{extra}")
    for n, why in skipped:
        lines.append(f"  (not dispatched) {n}: {why}")
    lines.append(f"  total ceilings ${total:g} over {len(kept)} jobs")
    done = started_after_reset_keys(receipts)
    pending = [a for a in cfg.get("after_reset") or [] if a["key"] not in done]
    lines.append("AFTER_RESET (one-shot, not yet started):" + ("" if pending else " none"))
    for a in pending:
        lines.append(f"  {a['key']}: {' '.join(str(a['reason']).split())}")
    return "\n".join(lines)


def _gh_open_prs() -> tuple[str, list[dict]]:
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return "could_not_look (no GITHUB_REPOSITORY/GH_TOKEN; the manager lists PRs through the GitHub MCP)", []
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return "ok", json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 - a failed look must read as could_not_look, never as zero
        return f"could_not_look ({type(exc).__name__})", []


def sweep(now: datetime, working_lanes: set[str], prs: tuple[str, list[dict]] | None = None,
          checklist: dict | None = None, pipeline_items: dict | None = None) -> dict:
    if checklist is None:
        sys.path.insert(0, str(ROOT))
        from src.runtime import checklist_store
        checklist = checklist_store.load()
    rows = []
    for r in checklist.get("items", []):
        if r.get("state") in ("in_flight", "blocked") and (r.get("lane") or "") not in working_lanes:
            rows.append({"id": r["id"], "state": r["state"], "lane": r.get("lane"),
                         "updated_at": r.get("updated_at"), "blocked_on": r.get("blocked_on") or []})
    read_state, plist = prs if prs is not None else _gh_open_prs()
    stale = []
    for p in plist:
        created = datetime.strptime(p["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_h = (now - created).total_seconds() / 3600
        if age_h >= PR_STALE_HOURS:
            stale.append({"number": p["number"], "title": p.get("title", ""), "draft": p.get("draft"),
                          "age_h": round(age_h, 1)})
    if pipeline_items is None:
        sys.path.insert(0, str(ROOT / "scripts" / "ops"))
        import pipeline
        pipeline_items = pipeline.load().items
    at_reset = [{"id": i["id"], "what": i["what"][:140]} for i in pipeline_items.values()
                if i.get("state") not in ("done", "killed") and (i.get("due_when") or {}).get("event") == RESET_EVENT]
    return {"rows_in_flight_or_blocked": rows, "pr_read_state": read_state, "open_prs_older_than_12h": stale,
            "open_prs_seen": len(plist), "pipeline_due_at_reset": at_reset,
            "note": "rows listed have no lane the caller saw working; the manager adds list_sessions "
                    "(blocked/failed/paused) and decides each: resume / re-dispatch / close with a reason"}


def render_sweep(s: dict) -> str:
    out = [f"ROWS in_flight/blocked without a lane seen working: {len(s['rows_in_flight_or_blocked'])}"]
    out += [f"  {r['id']} [{r['state']}] lane={r['lane']} updated={r['updated_at']} blocked_on={r['blocked_on']}"
            for r in s["rows_in_flight_or_blocked"]]
    out.append(f"OPEN PRs older than {PR_STALE_HOURS}h (read-state: {s['pr_read_state']}; open seen: {s['open_prs_seen']}): "
               f"{len(s['open_prs_older_than_12h'])}")
    out += [f"  #{p['number']} {p['age_h']}h draft={p['draft']} {p['title']}" for p in s["open_prs_older_than_12h"]]
    out.append(f"PIPELINE items due at reset (due_when.event={RESET_EVENT}): {len(s['pipeline_due_at_reset'])}")
    out += [f"  {i['id']}: {i['what']}" for i in s["pipeline_due_at_reset"]]
    out.append(s["note"])
    return "\n".join(out)


# ---------------------------------------------------------------- self-test

def self_test() -> int:
    cfg = load_config()
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    def names(ts):
        kept, sk = due_jobs(cfg, parse_reset(ts, cfg))
        return [j["name"] for j in kept], sk

    wk, _ = names("2026-11-11")  # second Wednesday: weekly only
    check(len(wk) == 7 and "deep-audit" not in wk, f"2026-11-11 should be the 7 weekly jobs, got {wk}")
    nov, sk = names("2026-11-04T18:00Z")  # first Wednesday of the month
    check("deep-audit" in nov and "weekly-audit" not in nov and ("weekly-audit", "superseded by deep-audit") in sk,
          f"2026-11-04 deep-audit must replace weekly-audit: {nov} {sk}")
    check({"roadmap-rebaseline", "cost-infra-review"} <= set(nov) and len(nov) == 9, f"2026-11-04 job set {nov}")
    check("deep-audit" not in names("2026-12-09")[0] and "deep-audit" in names("2026-12-02")[0], "monthly boundary day 7/8")
    check("deep-audit" in names("2026-12-02")[0] and "deep-audit" not in names("2026-12-09")[0], "monthly Dec")
    probe = {"name": "q", "cadence": "quarterly"}
    check(is_due(probe, parse_reset("2026-10-07", cfg)) and not is_due(probe, parse_reset("2026-11-04", cfg))
          and not is_due(probe, parse_reset("2026-10-14", cfg)), "quarterly = first reset of Jan/Apr/Jul/Oct only")
    perf = next(j for j in cfg["jobs"] if j["name"] == "perf-review-prep")
    check(perf["cadence"] == "weekly" and perf.get("lookback_days") == 30, "performance review: weekly with 30d lookback")
    offs = {j["name"]: (j["offset_minutes"], j["model"], j["ceiling_usd"]) for j in cfg["jobs"]}
    expect = {"weekly-audit": (31, "claude-opus-5-5", 15), "perf-review-prep": (53, "claude-opus-5-5", 20),
              "ml-frontier-prep": (53, "claude-opus-5-5", 16), "practice-refresh": (53, "claude-opus-5-5", 16),
              "health-review": (71, "claude-opus-5-5", 12), "programme-review": (89, "claude-opus-5-5", 12),
              "cj7-weekly": (133, "claude-sonnet-5-5", 3)}
    check(all(offs.get(k) == v for k, v in expect.items()), "seeded Wednesday cascade differs from the routines")
    for bad in ("garbage", "2026-13-40"):
        try:
            parse_reset(bad, cfg)
            fails.append(f"parse_reset accepted {bad!r}")
        except ProtocolError:
            pass
    # receipts: claim, dedupe, complete, append-only
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "r.jsonl"
        r = parse_reset("2026-11-04", cfg)
        check(not receipts_for(r, p), "no receipt before any write")
        write_receipt(r, "started", "A", {"jobs_due": nov}, p)
        check(len(receipts_for(r, p)) == 1, "started receipt found")
        try:
            write_receipt(r, "started", "B", None, p)
            fails.append("second started was accepted")
        except FileExistsError:
            pass
        try:
            write_receipt(parse_reset("2026-11-11", cfg), "complete", "A", None, p)
            fails.append("complete without started was accepted")
        except ProtocolError:
            pass
        before = p.read_text()
        write_receipt(r, "complete", "A", {"after_reset_started": ["PROJECT-PITCH-DECK"]}, p)
        check(p.read_text().startswith(before) and len(p.read_text().splitlines()) == 2, "append-only")
        check(started_after_reset_keys(p) == {"PROJECT-PITCH-DECK"}, "after_reset key recorded")
        plan = render_plan(cfg, r, p)
        check("PROJECT-PITCH-DECK" not in plan and "STRUCTURE-EXITS-DEFAULT" in plan, "plan drops started one-shots only")
        check("receipt: found" in plan, "plan reports the receipt")
    # sweep on fixtures, including the could-not-look read-state and a positive control
    now = datetime(2026, 11, 4, 18, 5, tzinfo=timezone.utc)
    cl = {"items": [{"id": "R1", "state": "in_flight", "lane": "s1"}, {"id": "R2", "state": "blocked", "lane": "s2"},
                    {"id": "R3", "state": "done", "lane": "s3"}]}
    pl = {"X": {"id": "X", "what": "paused work", "state": "queued", "due_when": {"kind": "event", "event": RESET_EVENT}},
          "Y": {"id": "Y", "what": "other", "state": "queued", "due_when": {"kind": "event", "event": "x"}}}
    prs = ("ok", [{"number": 1, "created_at": "2026-11-04T04:00:00Z", "title": "old"},
                  {"number": 2, "created_at": "2026-11-04T17:00:00Z", "title": "new"}])
    s = sweep(now, {"s1"}, prs, cl, pl)
    check([r["id"] for r in s["rows_in_flight_or_blocked"]] == ["R2"], "sweep drops working lanes and non-open states")
    check([p["number"] for p in s["open_prs_older_than_12h"]] == [1], "sweep: only PRs older than 12h")
    check([i["id"] for i in s["pipeline_due_at_reset"]] == ["X"], "sweep: only reset-due pipeline items")
    s2 = sweep(now, set(), ("could_not_look (x)", []), cl, pl)
    check(s2["pr_read_state"].startswith("could_not_look"), "failed PR read stays could_not_look, not 0")
    for f in fails:
        print("SELF-TEST FAIL:", f)
    print("self-test:", "FAIL" if fails else "ok")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", metavar="RESET_TS")
    ap.add_argument("--receipt", metavar="RESET_TS")
    ap.add_argument("--check", action="store_true", help="with --receipt")
    ap.add_argument("--write", choices=("started", "complete"), help="with --receipt")
    ap.add_argument("--by", default="", help="session id writing the receipt")
    ap.add_argument("--json", default="{}", help="extra receipt fields (object)")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--working-lanes", default="", help="comma-separated lane ids seen working")
    ap.add_argument("--receipts-file", default=str(RECEIPTS))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.self_test:
            return self_test()
        cfg = load_config()
        rf = Path(a.receipts_file)
        if a.plan:
            print(render_plan(cfg, parse_reset(a.plan, cfg), rf))
            return 0
        if a.receipt:
            reset = parse_reset(a.receipt, cfg)
            if a.write:
                if not a.by:
                    print("--write needs --by <session id>", file=sys.stderr)
                    return 1
                data = json.loads(a.json)
                if not isinstance(data, dict):
                    raise ProtocolError("--json must be an object")
                try:
                    rec = write_receipt(reset, a.write, a.by, data, rf)
                except FileExistsError as exc:
                    print(f"RECEIPT_EXISTS: {exc}; stop (another trigger owns this reset)")
                    return 4
                print("RECEIPT_WRITTEN:", json.dumps(rec, sort_keys=True))
                return 0
            have = receipts_for(reset, rf)
            if have:
                print(f"RECEIPT found for reset {reset.date()}: " + ", ".join(f"{r['event']} by {r.get('by')} at {r.get('at')}" for r in have))
                return 0
            print(f"NO_RECEIPT for reset {reset.date()}")
            return 3
        if a.sweep:
            print(render_sweep(sweep(datetime.now(timezone.utc), {x for x in a.working_lanes.split(",") if x})))
            return 0
        ap.print_help()
        return 1
    except (ProtocolError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"reset_protocol: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

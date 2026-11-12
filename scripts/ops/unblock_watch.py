#!/usr/bin/env python3
# wiring: run every firing of deploy/ict-work-digest.timer by scripts/ops/work_digest_now.py::main (hourly latch inside),
#   BEFORE attention_watch.alert_watch, so a cleared block reaches the manager on the same ledger -> PR #17895 alert-watch
#   path every other alert takes. Read by scripts/ops/render_daily_brief.py (the brief's "BLOCKED" section) and the
#   weekly planning. NO CI guard, by the dispatch's instruction (no new gates): run --self-test by hand on change.
"""UNBLOCK-WATCH — evaluate every blocked or waiting item's ``clears_when`` conditions; alert the manager when one clears.

WHY (operator, 2026-11-12 ~10:45Z): slv_trend_1h's demote was lifted 2026-11-04; its last blocker (TP test
RQ-20261104-7fdb-02) was parked with ``not_before`` 2027-03-16 and a stale config note, and NOTHING WATCHED IT, so for 8 days
nobody acted. The same day: PRs reported "held" that were merged, "not mergeable" that were closed, "not deployed" that were
deployed. Every one of those is a condition a machine can check. Row ``UNBLOCK-WATCH``; grammar in
``src/runtime/unblock_conditions.py``.

Gates this adds or changes: **none**. It reads, reports and appends alert-ledger rows. It never edits an item, never
refuses a write, and adds no CI check.

WHAT IT CHECKS (one population, stated on every report):
  * checklist rows in state ``blocked`` or with a non-empty ``blocked_on`` (closed rows excluded);
  * research units with a ``blocked:`` block, a ``not_before``, a ``requires_result`` or status ``blocked`` (done/retired
    excluded);
  * open pipeline items with ``due_when.kind == event`` or ``due_when.conditions``.

PER ITEM, never collapsed (RULE ONE; canonical § "Collapsed states"):
  ``cleared``        every checkable condition cleared and nothing manual remains -> ALERT (once per item+conditions)
  ``still_blocked``  at least one checkable condition is verifiably not met
  ``could_not_look`` no condition is verifiably unmet, but at least one could not be read (GitHub/diag unreachable, ...)
  ``unconditioned``  no machine-checkable condition at all (only free text, or nothing)
Flags on top: ``stale_manual`` (a manual condition older than 7 days), ``no_reason``, ``no_owner``, ``money`` and
``money_wait`` (a money-blocking item waiting > 7 days -> an operator decisions-page question, never chosen silently).

CADENCE (and why): the 5-min ``ict-work-digest`` tick already carries the alert pass to the manager, has the GitHub
credential (the same poster attention_watch uses) and the deploy markers on disk, and pulls main via ``ict-git-sync``. The
evaluator runs there with an HOURLY latch so the GitHub API sees at most ~one call per open PR condition per hour. The brief
route cannot do network reads per request, so it renders the newest receipt plus a repo-only evaluation.

Usage::
    python3 scripts/ops/unblock_watch.py                 # human report (repo + whatever network reads work here)
    python3 scripts/ops/unblock_watch.py --json          # machine report
    python3 scripts/ops/unblock_watch.py --offline       # repo-only (network kinds -> could_not_look)
    python3 scripts/ops/unblock_watch.py --pr-states F   # PR states from a JSON file {n: {state, merged, merge_commit_sha}}
    python3 scripts/ops/unblock_watch.py --tick          # the VM pass: evaluate, alert on new clears, write the receipt
    python3 scripts/ops/unblock_watch.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.runtime import unblock_conditions as uc  # noqa: E402

CLEARED, STILL, CNL, UNCOND = "cleared", "still_blocked", "could_not_look", "unconditioned"
MET, UNMET, UNKNOWN, NA = "met", "unmet", "could_not_look", "manual"
RECEIPT = REPO_ROOT / "runtime_logs" / "unblock_watch_receipt.json"
STATE = REPO_ROOT / "runtime_logs" / "unblock_watch_state.json"
TICK_EVERY_MIN = 60
ALERT_KIND = "unblock_cleared"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if v is None:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    if not s:
        return None
    if "T" in s and s.count(":") == 1:
        s = s.replace("+00:00", ":00+00:00") if s.endswith("+00:00") else s + ":00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.fromisoformat(s[:10])
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _git(*args: str, repo: Path = REPO_ROOT) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


# ── resolvers: every network read is cached for the pass and returns a three-way answer ───────────────────────────
class Resolver:
    def __init__(self, *, repo: Path = REPO_ROOT, rows: dict | None = None, pipe: dict | None = None,
                 units: dict | None = None, offline: bool = False, pr_states: dict | None = None,
                 deployed: dict | None = None, decisions: dict | None = None, github: Any = None,
                 now: datetime | None = None, git_ref: str = "origin/main"):
        self.repo, self.rows, self.pipe, self.units = repo, rows or {}, pipe or {}, units or {}
        self.offline, self.now, self.git_ref = offline, now or _now(), git_ref
        self._pr = {int(k): v for k, v in (pr_states or {}).items()}
        self._deployed, self._decisions, self._github = deployed, decisions, github
        self._main_log: dict[int, str] | None = None

    # git: a squash-merged PR's subject ends "(#N)" on main. Cheap, no API, works on the VM and in a session.
    def _merged_on_main(self, n: int) -> str | None:
        if self._main_log is None:
            self._main_log = {}
            rc, out = _git("log", self.git_ref, "--since=400 days ago", "--format=%H %s", repo=self.repo)
            if rc != 0:
                rc, out = _git("log", "HEAD", "--since=400 days ago", "--format=%H %s", repo=self.repo)
            for line in out.splitlines() if rc == 0 else []:
                sha, _, subj = line.partition(" ")
                for m in re.finditer(r"\(#(\d+)\)", subj):
                    self._main_log.setdefault(int(m.group(1)), sha)
        return self._main_log.get(n)

    def pr(self, n: int) -> tuple[str | None, bool | None, str | None, str]:
        """-> (state open|closed|None, merged True|False|None, merge sha, evidence)."""
        if n in self._pr:
            d = self._pr[n]
            sha = d.get("merge_commit_sha") or (self._merged_on_main(n) if d.get("merged") else None)
            return d.get("state"), d.get("merged"), sha, "PR state supplied (--pr-states)"
        sha = self._merged_on_main(n)
        if sha:
            return "closed", True, sha, f"merged: main carries (#{n}) at {sha[:9]}"
        if self.offline:
            return None, None, None, f"(#{n}) not on main; open-vs-closed needs GitHub (offline)"
        try:
            auth, http, api = self._github or _github()
            if not auth:
                return None, None, None, "no GitHub credential on this host"
            from scripts.ops.attention_watch import RAW_REPO  # noqa: PLC0415
            code, data = http("GET", f"{api}/repos/{RAW_REPO}/pulls/{n}", None, auth)
            if code == 200 and isinstance(data, dict):
                self._pr[n] = {"state": data.get("state"), "merged": bool(data.get("merged")),
                               "merge_commit_sha": data.get("merge_commit_sha")}
                return data.get("state"), bool(data.get("merged")), data.get("merge_commit_sha"), f"GitHub API {code}"
            return None, None, None, f"GitHub API answered {code}"
        except Exception as exc:  # noqa: BLE001  # allow-silent: a failed read is reported as could_not_look, never as unmet
            return None, None, None, f"GitHub read failed: {type(exc).__name__}"

    def deployed_markers(self) -> tuple[dict | None, str]:
        if self._deployed is not None:
            return self._deployed, "deploy markers supplied"
        local = {}
        for unit, name in (("ict-web-api.service", "deployed_sha.txt"), ("ict-trader-live.service", "deployed_sha_trader.txt")):
            try:
                local[unit] = (self.repo / "runtime_logs" / name).read_text(encoding="utf-8").strip() or None
            except OSError:
                pass
        if any(local.values()):
            self._deployed = local
            return local, "deploy markers read from runtime_logs/ (on the VM)"
        if self.offline:
            return None, "deploy markers are on the VM (offline)"
        try:
            p = subprocess.run(["bash", str(self.repo / "scripts/ops/diag_fetch.sh"), "version"], capture_output=True,
                               text=True, timeout=60)
            if p.returncode == 0:
                self._deployed = json.loads(p.stdout).get("deployed_sha_by_unit") or {}
                return self._deployed, "diag version: deployed_sha_by_unit"
            return None, f"diag version unreachable (exit {p.returncode})"
        except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look
            return None, f"diag version read failed: {type(exc).__name__}"

    def decisions(self) -> tuple[dict | None, str]:
        if self._decisions is not None:
            return self._decisions, "decisions supplied"
        if self.offline:
            return None, "decisions inbox is on the VM (offline)"
        try:
            import urllib.request  # noqa: PLC0415
            base = "http://127.0.0.1:8001" if (self.repo / "runtime_logs" / "deployed_sha.txt").exists() else "https://ict-bot.duckdns.org"
            with urllib.request.urlopen(f"{base}/api/bot/work/decisions", timeout=30) as r:  # noqa: S310
                self._decisions = json.loads(r.read().decode())
            return self._decisions, f"GET {base}/api/bot/work/decisions"
        except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look
            return None, f"decisions inbox unreachable: {type(exc).__name__}"

    def _unit_file(self, ref: str) -> dict | None:
        f = self.repo / "research" / "queue" / f"{ref}.yaml"
        if not re.match(r"^RQ-[A-Za-z0-9-]+$", ref) or not f.is_file():
            return None
        try:
            import yaml  # noqa: PLC0415
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else None
        except Exception:  # noqa: BLE001  # allow-silent: an unreadable unit reads as "no such unit" -> could_not_look
            return None

    # ── one condition -> (verdict, evidence) ──
    def check(self, c: dict) -> tuple[str, str]:
        k = c.get("kind")
        if k == "manual":
            return NA, "manual: " + (c.get("malformed") or "not machine-checkable")
        if k in ("pr_merged", "pr_closed"):
            state, merged, _sha, ev = self.pr(c["pr"])
            if k == "pr_merged":
                if merged is True:
                    return MET, ev
                if state == "closed" and merged is False:
                    return UNMET, f"PR #{c['pr']} was CLOSED unmerged — the condition can never clear; re-scope ({ev})"
                return (UNMET, ev) if state == "open" else (UNKNOWN, ev)
            if state == "closed" or merged is True:
                return MET, ev
            return (UNMET, ev) if state == "open" else (UNKNOWN, ev)
        if k == "deployed":
            sha = c.get("sha")
            if c.get("pr"):
                _st, merged, msha, ev = self.pr(c["pr"])
                if merged is False:
                    return UNMET, f"PR #{c['pr']} not merged ({ev})"
                if not msha:
                    return UNKNOWN, f"merge sha of #{c['pr']} unknown ({ev})"
                sha = msha
            markers, ev = self.deployed_markers()
            if not markers:
                return UNKNOWN, ev
            got, missing = [], []
            for unit, dsha in markers.items():
                if not dsha:
                    continue
                if _git("cat-file", "-e", f"{dsha}^{{commit}}", repo=self.repo)[0] != 0:
                    missing.append(unit)
                    continue
                if _git("merge-base", "--is-ancestor", sha, dsha, repo=self.repo)[0] == 0:
                    got.append(unit)
            if got:
                return MET, f"{sha[:9]} is in the deployed sha of {', '.join(got)} ({ev})"
            if missing and len(missing) == len([v for v in markers.values() if v]):
                return UNKNOWN, f"deployed sha(s) not in the local git object store ({', '.join(missing)})"
            return UNMET, f"{sha[:9]} not yet in any deployed sha ({ev})"
        if k == "row_state":
            ref, want = c["ref"], c["states"]
            r = self.rows.get(ref)
            if r is not None:
                st = r.get("state")
                return (MET if st in want else UNMET), f"row {ref} state={st}"
            it = self.pipe.get(ref)
            if it is not None:
                st = it.get("state")
                return (MET if st in want else UNMET), f"pipeline {ref} state={st}"
            u = self.units.get(ref) or self._unit_file(ref)
            if u is not None:
                st = u.get("status")
                return (MET if st in want else UNMET), f"unit {ref} status={st}"
            return UNKNOWN, f"{ref} matches no checklist row, pipeline item or unit"
        if k == "unit_result":
            from scripts.research.dispatch_queue import precondition_met  # noqa: PLC0415
            met, why = precondition_met({"requires_result": {"unit": c["ref"], "verdict": c.get("verdict")}}, self.repo)
            if not met and not (self.repo / "research/queue" / f"{c['ref']}.yaml").is_file() \
                    and not (self.repo / "research/results" / c["ref"]).is_dir():
                return UNKNOWN, f"no unit {c['ref']} in the queue and no result dir"
            return (MET if met else UNMET), why
        if k == "date":
            d = _ts(c["arg"])
            if d is None:
                return UNKNOWN, f"unparseable date {c['arg']!r}"
            return (MET, f"{c['arg']} has passed") if d <= self.now else (UNMET, f"waits until {c['arg']} ({(d - self.now).days}d)")
        if k == "operator_answer":
            doc, ev = self.decisions()
            if doc is None:
                return UNKNOWN, ev
            from src.runtime import work_decisions as wd  # noqa: PLC0415  one owner of the answer-state vocabulary
            for rq in doc.get("requests") or []:
                ids = {str(rq.get(x)) for x in ("id", "requestId", "request_id", "qid") if rq.get(x)}
                if c["ref"] in ids:
                    st = rq.get("answerState")
                    # every state lands in one of three buckets, never folded: settled -> met; the grader could not
                    # read or recognise the answer -> could_not_look; not submitted / in transit / engaged -> unmet.
                    if st in wd.SETTLED_STATES:
                        return MET, f"answerState={st} on the decisions inbox ({ev})"
                    if st in (wd.UNREADABLE, wd.VERDICT_UNRECOGNISED) or st not in wd.ANSWER_STATES:
                        return UNKNOWN, f"answerState={st!r}: the inbox could not grade the answer ({ev})"
                    return UNMET, f"answerState={st} ({ev})"
            return UNKNOWN, (f"{c['ref']} is not on the decisions inbox ({ev}); answers given on an Artifact decision doc are "
                             "recorded by the manager on the row, then the block is edited")
        if k == "data_n":
            if self.offline:
                return UNKNOWN, "diag query needs the network (offline)"
            try:
                p = subprocess.run(["bash", str(self.repo / "scripts/ops/diag_fetch.sh"), c["query"]], capture_output=True,
                                   text=True, timeout=90)
                if p.returncode != 0:
                    return UNKNOWN, f"diag {c['query']} unreachable (exit {p.returncode})"
                doc = json.loads(p.stdout)
                n = _count(doc)
                if n is None:
                    return UNKNOWN, f"diag {c['query']} returned no countable rows/count field"
                return (MET if n >= c["k"] else UNMET), f"diag {c['query']} n={n} (need >= {c['k']})"
            except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look
                return UNKNOWN, f"diag read failed: {type(exc).__name__}"
        return UNKNOWN, f"unknown kind {k!r}"


def _count(doc: Any) -> int | None:
    if isinstance(doc, list):
        return len(doc)
    if isinstance(doc, dict):
        for key in ("count", "n", "total"):
            if isinstance(doc.get(key), int):
                return doc[key]
        for key in ("rows", "items", "trades", "results", "lines"):
            if isinstance(doc.get(key), list):
                return len(doc[key])
    return None


def _github():
    from scripts.ops.attention_watch import _alert_github  # noqa: PLC0415
    return _alert_github()


_WAIT_HINT = re.compile(r"^(?:not_before|requires_result|blocked):|^status:\s*['\"]?blocked", re.M)
_CLOSED_HINT = re.compile(r"^status:\s*['\"]?(?:done|retired)\b", re.M)


def load_waiting_units(queue_dir: Path) -> tuple[str, dict[str, dict], int]:
    """Parse ONLY unit files whose text can hold a wait (a cheap regex prefilter, then the C YAML loader when present).
    Parsing all ~2,100 units costs ~35 s with the pure-Python loader (MEASURED 2026-11-12), which the brief route cannot
    afford. The prefilter can only skip a file that has none of the wait keys at line start or is closed, i.e. a file
    ``unit_block`` would return None for anyway."""
    try:
        import yaml  # noqa: PLC0415
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    except ImportError:
        return "unreadable: no yaml", {}, 0
    if not queue_dir.is_dir():
        return "unreadable: no research/queue", {}, 0
    units: dict[str, dict] = {}
    bad = 0
    for f in sorted(queue_dir.glob("RQ-*.yaml")):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            bad += 1
            continue
        if not _WAIT_HINT.search(text) or _CLOSED_HINT.search(text):
            continue
        try:
            d = yaml.load(text, Loader=loader)  # noqa: S506 -- a SafeLoader variant
        except yaml.YAMLError:
            bad += 1
            continue
        if isinstance(d, dict):
            units[str(d.get("id") or f.stem)] = d
        else:
            bad += 1
    return "read", units, bad


# ── collect + evaluate ─────────────────────────────────────────────────────────────────────────────────────────────
def _export_note(repo: Path) -> str:
    """WSD-S4: after the freeze the files are a frozen EXPORT unless this host holds work_store.db (the VM), where
    checklist_store/pipeline loaders already read the store. Say which one a report read -- never pass an export off
    as the live register."""
    from src.runtime import work_read  # noqa: PLC0415
    if work_read.frozen(repo) and work_read.local_store() is None:
        return " (FROZEN EXPORT files, not the live work store)"
    return ""


def _live_register(repo: Path):
    """In a session (frozen register, no local work_store.db): read the LIVE store through the work-store API.
    -> (rows, pipeline items, source label) or None (not frozen / store local / API unreachable)."""
    from src.runtime import work_read  # noqa: PLC0415
    if not work_read.frozen(repo) or work_read.local_store() is not None:
        return None
    try:
        from src.runtime import work_store_import as wi  # noqa: PLC0415
        w = work_read._work_cli()
        items = None
        for _attempt in range(3):   # paging refuses when the store changes mid-read; a re-read is the documented fix
            try:
                items = w._all_items(None)
                break
            except Exception:  # noqa: BLE001  # allow-silent: retried, then the export fallback is labelled
                import time  # noqa: PLC0415
                time.sleep(2 * (_attempt + 1))
                continue
        if items is None:
            return None
        rows = {r["id"]: r for r in (wi.to_row(i) for i in items if i.get("kind") == "build")}
        pipe = {r["id"]: r for r in (wi.to_pipeline_item(i) for i in items if i.get("kind") == "observation")}
        return rows, pipe, f"read (LIVE work store via API, {len(items)} items)"
    except Exception:  # noqa: BLE001  # allow-silent: falls back to the export, and the source label says so
        return None


def collect(repo: Path = REPO_ROOT, use_live: bool = True) -> tuple[list[dict], dict, dict]:
    """-> (items, sources, inputs). Each item: {store, id, title, path, block(s)}."""
    from scripts.ops import pipeline  # noqa: PLC0415
    from src.runtime import checklist_store  # noqa: PLC0415
    sources: dict[str, str] = {}
    rows: dict[str, dict] = {}
    pipe: dict[str, dict] = {}
    live = _live_register(repo) if use_live else None
    if live is not None:
        rows, pipe, how = live
        sources["checklist"] = sources["pipeline"] = how
    else:
        try:
            rows = {r["id"]: r for r in checklist_store.load(repo)["items"] if isinstance(r, dict) and r.get("id")}
            sources["checklist"] = "read" + _export_note(repo)
        except Exception as exc:  # noqa: BLE001
            sources["checklist"] = f"unreadable: {exc}"
        try:
            res = pipeline.load(repo / pipeline.STORE)
            pipe = dict(res.items)
            sources["pipeline"] = ("read" if res.healthy else f"read ({len(res.unreadable)} unreadable)") + _export_note(repo)
        except Exception as exc:  # noqa: BLE001
            sources["pipeline"] = f"unreadable: {exc}"
    qs, units, bad = load_waiting_units(repo / "research" / "queue")
    sources["research_queue"] = qs if not bad else f"{qs} ({bad} unparseable)"
    items: list[dict] = []
    for rid, r in rows.items():
        if r.get("state") in ("done", "dropped"):
            continue
        if r.get("state") == "blocked" or r.get("blocked_on"):
            items.append({"store": "checklist", "id": rid, "title": r.get("title"), "state": r.get("state"),
                          "blocks": uc.row_blocks(r), "path": f"docs/claude/work/checklist/{rid}.json"})
    for uid, u in units.items():
        b = uc.unit_block(u)
        if b is not None:
            items.append({"store": "research", "id": uid, "title": u.get("title"), "state": u.get("status"),
                          "blocks": [b], "path": f"research/queue/{uid}.yaml"})
    for pid, it in pipe.items():
        b = uc.pipeline_block(it)
        if b is not None:
            items.append({"store": "pipeline", "id": pid, "title": it.get("what"), "state": it.get("state"),
                          "blocks": [b], "path": f"{pipeline.STORE}/…({pid})"})
    return items, sources, {"rows": rows, "pipe": pipe, "units": units}


NEXT_ACTION = {
    "checklist": "move the row out of blocked (queued + dispatch, or close it with the evidence)",
    "research": "clear the unit's block (status/not_before/blocked:) so the dispatcher runs it, or run it now",
    "pipeline": "route or close the pipeline item (pipeline.py), citing the cleared condition",
}


def evaluate(items: list[dict], res: Resolver) -> list[dict]:
    out = []
    for it in items:
        conds: list[dict] = []
        flags: set[str] = set()
        money = False
        since_vals = []
        for b in it["blocks"]:
            money = money or b.get("money")
            if not b.get("reason"):
                flags.add("no_reason")
            if not b.get("owner"):
                flags.add("no_owner")
            if b.get("since"):
                since_vals.append(b["since"])
            for c in b.get("conditions") or []:
                v, ev = res.check(c)
                conds.append({"cond": c.get("raw") or f"{c['kind']}:{c.get('arg')}", "kind": c["kind"], "verdict": v,
                              "evidence": ev, "implied": bool(c.get("implied"))})
        since = min((d for d in (_ts(s) for s in since_vals) if d), default=None)
        age_days = (res.now - since).days if since else None
        checkable = [c for c in conds if c["kind"] != "manual"]
        manual = [c for c in conds if c["kind"] == "manual"]
        if manual and (age_days is None or age_days > uc.STALE_MANUAL_DAYS):
            flags.add("stale_manual")
        if not checkable:
            status = UNCOND
        elif any(c["verdict"] == UNMET for c in checkable):
            status = STILL
        elif any(c["verdict"] == UNKNOWN for c in checkable):
            status = CNL
        elif manual:
            status = STILL   # every checkable condition met, a manual one remains: a human must look (flagged below)
            flags.add("checkable_met_manual_left")
        else:
            status = CLEARED
        if money:
            flags.add("money")
            if status != CLEARED and age_days is not None and age_days > uc.MONEY_WAIT_DAYS:
                flags.add("money_wait")
        out.append({"store": it["store"], "id": it["id"], "title": (it.get("title") or "")[:140], "state": it.get("state"),
                    "status": status, "flags": sorted(flags), "conditions": conds, "since": since.isoformat() if since else None,
                    "age_days": age_days, "owner": next((b["owner"] for b in it["blocks"] if b.get("owner")), None),
                    "reason": next((b["reason"] for b in it["blocks"] if b.get("reason")), None),
                    "next_action": NEXT_ACTION[it["store"]], "path": it["path"]})
    order = {CLEARED: 0, CNL: 1, STILL: 2, UNCOND: 3}
    out.sort(key=lambda r: (order[r["status"]], "money" not in r["flags"], r["store"], r["id"]))
    return out


def build(*, repo: Path = REPO_ROOT, offline: bool = False, pr_states: dict | None = None, now: datetime | None = None,
          github: Any = None) -> dict:
    items, sources, inp = collect(repo, use_live=not offline)
    res = Resolver(repo=repo, rows=inp["rows"], pipe=inp["pipe"], units=inp["units"], offline=offline,
                   pr_states=pr_states, now=now, github=github)
    ev = evaluate(items, res)
    by_store: dict[str, dict[str, int]] = {}
    for r in ev:
        by_store.setdefault(r["store"], {}).setdefault(r["status"], 0)
        by_store[r["store"]][r["status"]] += 1
    counts = {s: sum(1 for r in ev if r["status"] == s) for s in (CLEARED, STILL, CNL, UNCOND)}
    for f in ("stale_manual", "money", "money_wait", "no_reason", "no_owner"):
        counts[f] = sum(1 for r in ev if f in r["flags"])
    return {"generated_at": res.now.isoformat(), "offline": offline, "sources": sources,
            "readable": all(str(v).startswith("read") for v in sources.values()),
            "population": {"items": len(ev), "by_store": by_store,
                           "definition": "checklist rows blocked or with blocked_on (not done/dropped); research units with "
                                         "blocked:/not_before/requires_result/status blocked (not done/retired); open pipeline "
                                         "items with due_when.kind=event or due_when.conditions"},
            "counts": counts, "items": ev}


# ── the VM tick: alert on NEW clears, dedupe per item + conditions ────────────────────────────────────────────────
def _alert_key(r: dict) -> str:
    met = sorted(c["cond"] for c in r["conditions"] if c["verdict"] == MET)
    return f"{r['store']}:{r['id']}|{'&'.join(met)}"


def plan_alerts(rep: dict, state: dict) -> tuple[list[dict], dict]:
    """Pure. -> (ledger rows to append, new state). A first run (no state) seeds: ONE summary row, every current clear
    recorded as seen (the backfill reported them to the manager directly)."""
    seen = dict(state.get("alerted") or {})
    cleared = [r for r in rep["items"] if r["status"] == CLEARED]
    out = []
    if not state.get("seeded_at"):
        for r in cleared:
            seen[_alert_key(r)] = rep["generated_at"]
        out.append({"body": f"UNBLOCK-WATCH seeded: {len(cleared)} item(s) already cleared at first run "
                            f"(reported to the manager by the backfill); {rep['counts'].get(UNCOND, 0)} unconditioned.",
                    "dedup_key": "unblock:seed", "priority": "normal"})
        return out, {"seeded_at": rep["generated_at"], "alerted": seen}
    for r in cleared:
        k = _alert_key(r)
        if k in seen:
            continue
        seen[k] = rep["generated_at"]
        met = [c for c in r["conditions"] if c["verdict"] == MET]
        body = (f"UNBLOCKED {'💰 ' if 'money' in r['flags'] else ''}{r['store']} `{r['id']}` — "
                f"{'; '.join(c['cond'] + ' (' + c['evidence'][:120] + ')' for c in met)}. "
                f"Next: {r['next_action']}. {r['title'][:100]}")
        out.append({"body": body, "dedup_key": f"unblock:{k}"[:200], "priority": "high" if "money" in r["flags"] else "normal"})
    live = {_alert_key(r) for r in cleared}
    # forget keys whose item is no longer cleared+open for 14 days, so the state file does not grow forever
    cutoff = (_ts(rep["generated_at"]) or _now()) - timedelta(days=14)
    seen = {k: v for k, v in seen.items() if k in live or (_ts(v) or _now()) > cutoff}
    return out, {"seeded_at": state["seeded_at"], "alerted": seen}


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)


def tick(*, repo: Path = REPO_ROOT, now: datetime | None = None, force: bool = False, dry_run: bool = False) -> dict:
    """The VM pass. NEVER raises; never gates the digest. Hourly latch on the receipt."""
    now = now or _now()
    try:
        prior = _read_json(RECEIPT)
        last = _ts(prior.get("generated_at"))
        if last and now - last < timedelta(minutes=TICK_EVERY_MIN) and not force:
            return {"state": "latched", "last": prior.get("generated_at")}
        rep = build(repo=repo, now=now)
        rows, new_state = plan_alerts(rep, _read_json(STATE))
        appended = 0
        if not dry_run:
            from src.runtime import alerts_ledger  # noqa: PLC0415
            for row in rows:
                appended += bool(alerts_ledger.append(ALERT_KIND, "system", row["body"], priority=row["priority"],
                                                      dedup_key=row["dedup_key"]))
            if appended == len(rows):   # state advances only when every alert reached the ledger
                _write_json(STATE, new_state)
        rep["alerts"] = {"planned": len(rows), "appended": appended, "dry_run": dry_run}
        if not dry_run:   # slim, one line: readable whole through /api/diag/log_file?name=unblock_watch_receipt
            slim = {k: rep[k] for k in ("generated_at", "sources", "readable", "population", "counts", "alerts")}
            slim["items"] = [r for r in rep["items"] if r["status"] in (CLEARED, CNL) or "money_wait" in r["flags"]]
            RECEIPT.parent.mkdir(parents=True, exist_ok=True)
            tmp = RECEIPT.with_suffix(".tmp")
            tmp.write_text(json.dumps(slim, separators=(",", ":"), default=str) + "\n", encoding="utf-8")
            tmp.replace(RECEIPT)
        return {"state": "ran", "alerts": rep["alerts"], "counts": rep["counts"]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: the receipt is not written, so the brief shows it stale; the digest proceeds
        return {"state": "error", "error": f"{type(exc).__name__}: {exc}"}


# ── rendering (the brief's daily BLOCKED section; weekly planning reads the same) ─────────────────────────────────
def _line(r: dict) -> str:
    who = r.get("owner") or "—"
    age = "—" if r.get("age_days") is None else f"{r['age_days']}d"
    conds = "; ".join(f"{c['cond'][:70]}={c['verdict']}" for c in r["conditions"][:3]) or "no condition"
    return f"- `{r['id']}` ({r['store']}, owner {who}, waiting {age}) — {conds}"


def render_lines(rep: dict | None, *, receipt: dict | None = None, cap: int = 10) -> list[str]:
    L = ["### ⛓️ BLOCKED — every blocked/waiting item and the condition that clears it (UNBLOCK-WATCH)", ""]
    if rep is None:
        return L + ["COULD NOT BE EVALUATED (we did not look; this is not zero).", ""]
    c, p = rep["counts"], rep["population"]
    if not rep.get("readable"):
        L.append("⚠️ input unreadable: " + "; ".join(f"{k} {v}" for k, v in rep["sources"].items() if not str(v).startswith("read")))
    L.append(f"Population: {p['items']} items ({', '.join(f'{s} {sum(v.values())}' for s, v in sorted(p['by_store'].items()))}). "
             f"cleared {c[CLEARED]} · still_blocked {c[STILL]} · could_not_look {c[CNL]} · unconditioned {c[UNCOND]} · "
             f"stale_manual {c['stale_manual']} · money {c['money']} (waiting >{uc.MONEY_WAIT_DAYS}d: {c['money_wait']}).")
    if rep.get("offline"):
        L.append("_Repo-only evaluation (PR/deploy/decision/diag conditions read could_not_look here)._")
    if receipt:
        rc = receipt.get("counts") or {}
        L.append(f"VM receipt {receipt.get('generated_at', '—')}: cleared {rc.get(CLEARED, '—')} · could_not_look "
                 f"{rc.get(CNL, '—')}; alerts {json.dumps(receipt.get('alerts') or {})}.")
    L.append("")
    groups = [
        ("💰 Money-blocking waits > 7 days (each is an operator decisions-page question, never chosen silently)",
         [r for r in rep["items"] if "money_wait" in r["flags"]]),
        ("✅ Already cleared — act now", [r for r in rep["items"] if r["status"] == CLEARED]),
        ("❓ could_not_look", [r for r in rep["items"] if r["status"] == CNL]),
        ("🕳️ Unconditioned (no machine-checkable clears_when)", [r for r in rep["items"] if r["status"] == UNCOND]),
        ("🕰️ Stale manual (> 7 days)", [r for r in rep["items"] if "stale_manual" in r["flags"] and r["status"] != UNCOND]),
    ]
    for head, rows in groups:
        L.append(f"**{head}: {len(rows)}**")
        L += [_line(r) for r in rows[:cap]]
        if len(rows) > cap:
            L.append(f"- …and {len(rows) - cap} more (`python3 scripts/ops/unblock_watch.py`).")
        L.append("")
    L += ["Rule (manager + close-out skills): blocked/waiting = a structured `clears_when` condition + owner, never prose only.", ""]
    return L


def brief_lines(repo: Path = REPO_ROOT) -> list[str]:
    """For render_daily_brief: a repo-only evaluation (no network per request) plus the newest VM receipt."""
    try:
        rep = build(repo=repo, offline=True)
    except Exception:  # noqa: BLE001
        rep = None
    rc = _read_json(repo / "runtime_logs" / "unblock_watch_receipt.json") or None
    return render_lines(rep, receipt=rc)


# ── self-test ────────────────────────────────────────────────────────────────────────────────────────────────────
def _self_test() -> int:
    fails: list[str] = []

    def ck(label: str, cond: bool) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            fails.append(label)

    P = uc.parse
    ck("pr_merged parses", P("pr_merged:25135")["pr"] == 25135 and P("pr_merged:#7")["pr"] == 7)
    ck("deployed parses a PR and a sha", P("deployed:#12")["pr"] == 12 and P("deployed:abcdef12")["sha"] == "abcdef12")
    ck("row_state parses states", P("row_state:A-B=done|dropped")["states"] == ["done", "dropped"])
    ck("data_n parses query and k", P("data_n:journal?table=trades&strategy=x>=2")["k"] == 2)
    ck("free text is manual (legacy readable)", P("waiting on the operator")["kind"] == "manual")
    try:
        P("pr_merged:abc")
        ck("a malformed known kind raises", False)
    except uc.ConditionError:
        ck("a malformed known kind raises", True)
    ck("parse_safe never raises", uc.parse_safe("date:not-a-date").get("malformed"))
    ck("legacy work_item edge implies row_state", uc.edge_block({"kind": "work_item", "ref": "X-1"})["conditions"][0]["kind"] == "row_state")
    ck("legacy bare id string implies row_state", uc.edge_block("ALPACA-LIVE-MECHANICS")["conditions"][0]["kind"] == "row_state")
    ck("legacy prose string is manual", uc.edge_block("operator review of trades")["conditions"][0]["kind"] == "manual")
    ub = uc.unit_block({"status": "queued", "not_before": "2027-03-16T00:00:00Z"})
    ck("unit not_before implies date, with no reason flagged", ub and ub["conditions"][0]["kind"] == "date" and "no reason" in uc.problems(ub))
    ck("a done unit is not waiting", uc.unit_block({"status": "done", "not_before": "2027-01-01"}) is None)
    ck("refusable: prose only", uc.refusable(uc.edge_block("waiting on review")))
    ck("refusable: empty blocked row", uc.refusable(uc.row_blocks({"state": "blocked", "blocked_on": []})[0]))
    ck("NOT refusable: explicit manual:<text> (the allowed last resort)",
       not uc.refusable(uc.edge_block({"reason": "r", "owner": "o", "clears_when": ["manual:a human checks X"]})))
    ck("NOT refusable: a checkable condition", not uc.refusable(uc.edge_block({"clears_when": ["pr_merged:1"]})))
    ck("NOT refusable: a legacy row ref (implies row_state)", not uc.refusable(uc.edge_block("ALPACA-LIVE-MECHANICS")))
    ck("refusable: a malformed known kind", uc.refusable(uc.edge_block({"clears_when": ["pr_merged:abc"]})))
    ck("a pipeline observation item is not a wait", uc.pipeline_block({"state": "queued", "due_when": {"kind": "observation", "clears_when": "x"}}) is None)

    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    rows = {"R-DONE": {"id": "R-DONE", "state": "done"}, "R-Q": {"id": "R-Q", "state": "queued"}}
    res = Resolver(rows=rows, offline=True, now=now, pr_states={1: {"state": "closed", "merged": True, "merge_commit_sha": "a" * 40},
                                                               2: {"state": "open", "merged": False},
                                                               3: {"state": "closed", "merged": False}},
                   deployed={})

    def item(store, iid, blocks):
        return {"store": store, "id": iid, "title": iid, "state": "blocked", "blocks": blocks, "path": iid}

    def blk(conds, owner="m", reason="r", since="2026-11-10", money=False):
        return {"reason": reason, "owner": owner, "conditions": [uc.parse_safe(c) for c in conds], "since": since, "money": money}

    ev = {r["id"]: r for r in evaluate([
        item("checklist", "A", [blk(["pr_merged:1", "row_state:R-DONE=done"])]),
        item("checklist", "B", [blk(["pr_merged:2"])]),
        item("checklist", "C", [blk(["pr_merged:1", "deployed:#1"])]),
        item("checklist", "D", [blk(["waiting for review"], since="2026-10-01")]),
        item("research", "E", [blk(["date:2026-11-01"], money=True, since="2026-11-01")]),
        item("research", "F", [blk(["date:2027-03-16"], money=True, since="2026-11-04")]),
        item("checklist", "G", [blk(["pr_merged:3"])]),
        item("checklist", "H", [blk(["pr_closed:3"])]),
    ], res)}
    ck("all checkable met -> cleared", ev["A"]["status"] == CLEARED)
    ck("one unmet -> still_blocked", ev["B"]["status"] == STILL)
    ck("unreadable deploy marker -> could_not_look, never blocked", ev["C"]["status"] == CNL)
    ck("prose only -> unconditioned + stale_manual", ev["D"]["status"] == UNCOND and "stale_manual" in ev["D"]["flags"])
    ck("past date -> cleared", ev["E"]["status"] == CLEARED)
    ck("money item waiting > 7d -> money_wait (the slv shape)", "money_wait" in ev["F"]["flags"] and ev["F"]["status"] == STILL)
    ck("closed-unmerged PR on pr_merged -> still_blocked, says it can never clear",
       ev["G"]["status"] == STILL and "never clear" in ev["G"]["conditions"][0]["evidence"])
    ck("closed PR satisfies pr_closed", ev["H"]["status"] == CLEARED)

    rep = {"generated_at": now.isoformat(), "items": list(ev.values()), "counts": {UNCOND: 1}}
    rows1, st1 = plan_alerts(rep, {})
    ck("first run seeds with ONE summary row", len(rows1) == 1 and rows1[0]["dedup_key"] == "unblock:seed")
    rep2 = dict(rep, items=list(ev.values()) + [dict(ev["A"], id="NEW")])
    rows2, st2 = plan_alerts(rep2, st1)
    ck("a new clear alerts once, naming item and condition", len(rows2) == 1 and "NEW" in rows2[0]["body"] and "pr_merged:1" in rows2[0]["body"])
    rows3, _ = plan_alerts(rep2, st2)
    ck("dedupe: the same item+conditions never alerts twice", rows3 == [])
    money_new = dict(ev["E"], id="NEWM")
    rows4, _ = plan_alerts(dict(rep, items=[money_new]), st2)
    ck("a money clear alerts high", rows4 and rows4[0]["priority"] == "high")
    L = render_lines({"counts": {CLEARED: 1, STILL: 1, CNL: 1, UNCOND: 1, "stale_manual": 1, "money": 2, "money_wait": 1},
                      "population": {"items": 8, "by_store": {"checklist": {CLEARED: 1}}}, "sources": {"x": "read"},
                      "readable": True, "items": list(ev.values())})
    ck("render names the money waits and the unconditioned", any("Money-blocking" in x for x in L) and any("Unconditioned" in x for x in L))
    ck("render of None says we did not look", any("did not look" in x for x in render_lines(None)))
    print("unblock_watch self-test:", "PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--pr-states", metavar="FILE")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.tick:
        print(json.dumps(tick(force=a.force, dry_run=a.dry_run), default=str))
        return 0
    prs = json.loads(Path(a.pr_states).read_text(encoding="utf-8")) if a.pr_states else None
    rep = build(offline=a.offline, pr_states=prs)
    if a.json:
        print(json.dumps(rep, indent=1, default=str))
    else:
        print("\n".join(render_lines(rep, cap=10_000)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

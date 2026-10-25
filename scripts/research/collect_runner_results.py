#!/usr/bin/env python3
# wiring: .github/workflows/research-queue-dispatch.yml (the collect step, once per dispatcher cycle)
"""Land the token-free runner's results ONE PR PER DISPATCHER CYCLE, not one per run.

WHY (manager review, 2026-09-29 01:27Z). `research-script-run.yml` used to end
in a `land` job that opened TWO auto-merge PRs per unit (the outputs, then the
E5 record), each with a 30-minute `verify-merged` wait and a full CI fan-out
(guards + pytest-collect + pytest-run + repo-inventory). Sixteen units fired in
one cycle meant ~32 PRs and ~130 CI jobs queued behind each other, in the same
runner pool every system-action (set-env, flatten, the Breakout AUTO-REVERT)
waits in. Research must never starve a safety action.

WHAT. The runner now only UPLOADS its outputs as an artifact (with
`record-inputs.json`, the research-result inputs `script_run.py --derive-record`
derived from what the run wrote). This collector runs at the top of every
dispatcher cycle, finds every completed `research-script-run` whose artifact is
not yet on `main`, downloads it into `comms/research/<unit>/<run_id>/`, emits
the E5 record through `research_result.py --emit` (the one owner of the record
schema), and the dispatcher lands the whole batch with a SINGLE
`commit-to-main` and asserts every record landed. One PR, one CI fan-out, one
wait per cycle.

WHAT IS AND IS NOT LANDED, stated rather than assumed:
  * a run whose `comms/research/<unit>/<run_id>/run-manifest.json` OR whose
    E5 record `research/results/<unit>/<run_id>.jsonl` is already in the
    checkout is skipped (landed by an earlier cycle, or by the old per-run
    `land` job). The record test matters: a CANCELLED / timed-out run never
    writes a run-manifest, so keying on the manifest alone re-collected such a
    run every cycle, `gh run download` refused the non-empty directory ("file
    exists"), and that was reported as a LOST run -- on every cycle since
    2026-10-07 (RQ-COLLECTOR, run 37283785325), although its record was on main;
  * a run whose artifact carries no `record-inputs.json` is an OLD-STYLE run
    (dispatched before this change): it landed itself, skipped;
  * a run whose artifact has expired, whose record-inputs.json is unreadable or
    whose record is refused is reported by id as `lost` -- rows that cost runner
    minutes are gone or cannot land; not silently dropped, not fabricated;
  * an API failure (run list / artifact listing / download) is `unreadable`, NOT
    `lost`: we could not look, nothing is claimed, the next cycle retries. It
    warns but does not fail the cycle; a run list that fails outright is
    `read_error`, which still does;
  * nothing to collect (every run already landed or not a unit run) is success;
  * a run with `conclusion != success` still lands (its manifest, logs and a
    `producer_failed` record), exactly as the old `land` job did.

Tier-1: research tooling. Reads `gh run list` / downloads artifacts with the
ambient token, writes only comms/research/** and research/results/**.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

WORKFLOW = "research-script-run.yml"
WORKFLOW_NAME = "research-script-run"
#: ML-RQ-RUNNER (2026-10-11): the trainer-side twin lands through this SAME collector. Its artifact is
#: named research-script-run-trainer-<unit>-<run_id>; the E5 record's `--workflow` is the run's own name.
TRAINER_WORKFLOW = "research-script-run-trainer.yml"
#: RESEARCH-ROUTER (2026-10-13): the Kaggle GPU twin lands through the same collector too; its artifact is
#: research-script-run-kaggle-<unit>-<run_id>.
KAGGLE_WORKFLOW = "research-script-run-kaggle.yml"
#: ML-DATA-OFF-TRAINER (2026-10-13): the published-data twin; artifact research-script-run-data-<unit>-<run_id>.
DATA_WORKFLOW = "research-script-run-data.yml"
KAGGLE_CPU_WORKFLOW = "research-script-run-kaggle-cpu.yml"
COLLECTED_WORKFLOWS = (WORKFLOW, TRAINER_WORKFLOW, KAGGLE_WORKFLOW, DATA_WORKFLOW, KAGGLE_CPU_WORKFLOW)
RECORD_INPUTS = "record-inputs.json"
_ARTIFACT_RE = re.compile(r"^research-script-run(?:-trainer|-kaggle-cpu|-kaggle|-data)?-(RQ-\d{8}-(?:\d{3}|[0-9a-f]{4}-\d{2}))-(\d+)$")
_EMIT_FIELDS = ("research_unit", "power_state", "decision_rule_id", "decision_rule_registered_at",
                "verdict", "read_state", "population", "n", "tool", "measurement_file",
                "records_file", "artifact_store", "artifact_locator", "note",
                # RESEARCH-TRIAL-LEDGER (2026-10-16): script_run.derive_record's input-data hash. Absent from
                # record-inputs.json written before then -> "" -> the record simply carries none.
                "data_fingerprint")


def _gh(args: List[str], *, timeout: int = 120) -> Optional[str]:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def completed_runs(limit: int = 100) -> Optional[List[Dict[str, Any]]]:
    """Completed runs of every collected workflow, each tagged with its `_workflow_name`. Any one listing
    failing is `None` (could not look) — never a partial list passed off as the whole population."""
    merged: List[Dict[str, Any]] = []
    for wf in COLLECTED_WORKFLOWS:
        out = _gh(["run", "list", "--workflow", wf, "--status", "completed", "--limit", str(limit),
                   "--json", "databaseId,conclusion,headSha,createdAt,url"])
        if out is None:
            return None
        try:
            rows = json.loads(out or "[]")
        except ValueError:
            return None
        if not isinstance(rows, list):
            return None
        for r in rows:
            r["_workflow_name"] = wf[:-len(".yml")]
        merged.extend(rows)
    return merged


def run_artifacts(repo_slug: str, run_id: int) -> Optional[List[Dict[str, Any]]]:
    out = _gh(["api", f"repos/{repo_slug}/actions/runs/{run_id}/artifacts", "--jq", ".artifacts"])
    if out is None:
        return None
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def download(run_id: int, name: str, dest: Path) -> bool:
    """Download into a scratch dir and merge, because `gh run download -D <dir>` refuses
    to extract over an existing file -- a half-landed directory must not read as a failure."""
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        if _gh(["run", "download", str(run_id), "-n", name, "-D", td], timeout=600) is None:
            return False
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(td, dest, dirs_exist_ok=True)
    return True


def already_landed(root: Path, unit: str, run_id: int) -> bool:
    return ((root / "comms" / "research" / unit / str(run_id) / "run-manifest.json").exists()
            or (root / "research" / "results" / unit / f"{run_id}.jsonl").exists())


_BATCH_PREFIX = "automation/research-results-batch"
_RECORD_PATH_RE = re.compile(r"^research/results/(?P<unit>[^/]+)/(?P<run>\d+)\.jsonl$")


def pending_in_open_batches(repo_slug: str) -> Optional[set]:
    """{(unit, run_id)} whose E5 record sits in an OPEN results-batch PR, or None when we could not look.

    WHY (RESEARCH-PIPE-UNSTICK 2026-10-14): a batch PR stays open ~1 h (CI). The next hourly cycle
    checks out `main`, which does not yet carry that record, so `already_landed` said no and the
    same runs were collected AGAIN into a second batch PR. Each carries a different `generated_at`,
    so the first to merge left the others `dirty` (add/add on research/results/**) -- #17897, #17927.
    None -> fail open: collect as before (a duplicate PR is the old, visible failure)."""
    raw = _gh(["api", f"repos/{repo_slug}/pulls?state=open&per_page=100", "--paginate", "--jq",
               f'.[] | select(.head.ref | startswith("{_BATCH_PREFIX}")) | .number'])
    if raw is None:
        return None
    pending: set = set()
    for num in raw.split():
        files = _gh(["api", f"repos/{repo_slug}/pulls/{num}/files?per_page=100", "--paginate", "--jq", ".[].filename"])
        if files is None:
            return None
        for name in files.split():
            m = _RECORD_PATH_RE.match(name)
            if m:
                pending.add((m.group("unit"), int(m.group("run"))))
    return pending


def _scalar_n(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The E5 record's `n` is one integer. A producer that emitted a per-arm dict (same_symbol_head_to_head
    before 2026-10-25 -- runs 40148576330/-77750/-78991, all refused as LOST) is collected with the dict's
    `together` count (the combined-book sample the unit's power rule reads), else `null`; the per-arm detail
    stays in the run's measurement.json. Anything else passes through for research_result.py to judge."""
    n = rec.get("n")
    if not isinstance(n, dict):
        return rec
    together = n.get("together")
    return {**rec, "n": together if isinstance(together, int) and not isinstance(together, bool) else None}


def emit_record(root: Path, rec: Dict[str, Any], *, run: Dict[str, Any], repo_slug: str) -> Optional[str]:
    """Write the E5 record through research_result.py; returns its repo path."""
    run_id = str(run["databaseId"])
    cmd = [sys.executable, str(root / "scripts/research/research_result.py"), "--emit",
           "--workflow", str(run.get("_workflow_name") or WORKFLOW_NAME), "--run-id", run_id, "--run-attempt", "1",
           "--run-url", str(run.get("url") or f"https://github.com/{repo_slug}/actions/runs/{run_id}"),
           "--commit-sha", str(run.get("headSha") or "")]
    rec = _scalar_n(rec)
    for k in _EMIT_FIELDS:
        cmd += [f"--{k.replace('_', '-')}", str(rec.get(k, "") if rec.get(k) is not None else "null" if k == "n" else "")]
    if root != _REPO:
        cmd += ["--root", str(root / "research" / "results")]   # --root is the RESULTS root
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(root))
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"::error::{run_id}: research_result.py --emit could not run ({exc})", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"::error::{run_id}: research_result.py --emit refused: {(proc.stderr or proc.stdout).strip()[-400:]}",
              file=sys.stderr)
        return None
    # research_result.py prints the written path as its one stdout line
    # (`path=` goes to $GITHUB_OUTPUT only); normalise it to root-relative.
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line.endswith(".jsonl"):
            continue
        cand = Path(line)
        if cand.is_absolute():
            try:
                return cand.relative_to(root).as_posix()
            except ValueError:
                return line
        return line
    return None


def recollect_orphans(root: Path, *, repo_slug: str) -> List[Dict[str, Any]]:
    """Re-emit the E5 record for every numeric-run-id artifact dir that holds a `record-inputs.json`
    but no `research/results/<unit>/<run_id>.jsonl`.

    WHY (RESEARCH-PIPE-UNSTICK 2026-10-14): `collect()` only looks at the last 100 completed runs, so a
    run whose outputs landed (old per-run `land` job) but whose record did not is never retried; the
    catalog then reads the unit as `dispatched` with no result for ever (RQ-20261007-005..008, 130+ h).
    Nothing is invented: the record is emitted by research_result.py from the committed record-inputs.json,
    exactly as `collect()` does. Non-numeric run ids (`local-*`) are not Actions runs and are skipped."""
    done: List[Dict[str, Any]] = []
    for ri in sorted((root / "comms" / "research").glob("*/*/record-inputs.json")):
        unit, run_id = ri.parent.parent.name, ri.parent.name
        if not run_id.isdigit() or (root / "research" / "results" / unit / f"{run_id}.jsonl").exists():
            continue
        try:
            rec = json.loads(ri.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            man = json.loads((ri.parent / "run-manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            man = {}
        if not man.get("commit_sha"):
            continue      # a record without a commit sha is inadmissible; never invent one
        # rows written before script_run defaulted `read_state` carry none; give them the run's own
        # (record-inputs.json) so the emitter admits them. Same rule as script_run.derive_record.
        rf = str(rec.get("records_file") or "")
        tmp = None
        if rf and (root / rf).is_file():
            rows = [json.loads(ln) for ln in (root / rf).read_text(encoding="utf-8").splitlines() if ln.strip()]
            if any("read_state" not in r for r in rows):
                import tempfile
                tmp = Path(tempfile.mkdtemp()) / "records.jsonl"
                tmp.write_text("".join(json.dumps({"read_state": rec.get("read_state"), **r}) + "\n" for r in rows),
                               encoding="utf-8")
                rec = {**rec, "records_file": str(tmp)}
        out = emit_record(root, rec, run={"databaseId": int(run_id), "headSha": man["commit_sha"],
                                          "url": man.get("run_url") or ""}, repo_slug=repo_slug)
        if out:
            done.append({"unit": unit, "run_id": int(run_id), "record": out})
    return done


def collect(root: Path, *, repo_slug: str, runs: Optional[List[Dict[str, Any]]] = None,
            artifacts_for=run_artifacts, downloader=download, dry_run: bool = False,
            pending: Optional[set] = None) -> Dict[str, Any]:
    """The batch: {landed, skipped, lost, unreadable, read_error}."""
    out: Dict[str, Any] = {"landed": [], "skipped": [], "lost": [], "unreadable": [], "read_error": None}
    if runs is None:
        runs = completed_runs()
    if runs is None:
        out["read_error"] = "gh run list failed -- could not look; nothing collected, nothing claimed"
        return out
    for run in sorted(runs, key=lambda r: int(r["databaseId"])):
        run_id = int(run["databaseId"])
        arts = artifacts_for(repo_slug, run_id)
        if arts is None:
            out["unreadable"].append({"run_id": run_id, "why": "artifact listing failed (API); retried next cycle"})
            continue
        hit = None
        for a in arts:
            m = _ARTIFACT_RE.match(str(a.get("name") or ""))
            if m and int(m.group(2)) == run_id:
                hit = (a, m.group(1))
                break
        if hit is None:
            out["skipped"].append({"run_id": run_id, "why": "no research-script-run[-trainer] artifact (not a unit run)"})
            continue
        art, unit = hit
        dest = root / "comms" / "research" / unit / str(run_id)
        if already_landed(root, unit, run_id):
            out["skipped"].append({"run_id": run_id, "unit": unit, "why": "already on main"})
            continue
        if pending and (unit, run_id) in pending:
            out["skipped"].append({"run_id": run_id, "unit": unit, "why": "record is in an open results-batch PR"})
            continue
        if art.get("expired"):
            out["lost"].append({"run_id": run_id, "unit": unit, "why": "artifact expired before any cycle collected it"})
            continue
        if dry_run:
            out["landed"].append({"unit": unit, "run_id": run_id, "record": None, "dry_run": True})
            continue
        if not downloader(run_id, str(art["name"]), dest):
            out["unreadable"].append({"run_id": run_id, "unit": unit, "why": "artifact download failed (API); retried next cycle"})
            continue
        rec_path = dest / RECORD_INPUTS
        if not rec_path.exists():
            # old-style run: its own land job landed the record; leave its outputs out too
            for f in sorted(dest.rglob("*")):
                if f.is_file():
                    f.unlink()
            out["skipped"].append({"run_id": run_id, "unit": unit, "why": "old-style run (no record-inputs.json): landed itself"})
            continue
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["lost"].append({"run_id": run_id, "unit": unit, "why": f"record-inputs.json unreadable: {exc}"})
            continue
        record = emit_record(root, rec, run=run, repo_slug=repo_slug)
        if not record:
            out["lost"].append({"run_id": run_id, "unit": unit, "why": "record emit refused (see ::error above)"})
            continue
        out["landed"].append({"unit": unit, "run_id": run_id, "record": record,
                              "min_rows": int(rec.get("min_rows") or 1), "conclusion": run.get("conclusion")})
    return out


# ── self-test ───────────────────────────────────────────────────────────────
def _self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "scripts/research").mkdir(parents=True)
        for f in ("research_result.py",):
            (root / "scripts/research" / f).write_text((_REPO / "scripts/research" / f).read_text(encoding="utf-8"))
        (root / "research/results").mkdir(parents=True)
        (root / "research/queue").mkdir(parents=True)
        # landed already: run 1; old-style: run 2; new: run 3 (pass) and run 4 (failed script)
        (root / "comms/research/RQ-20300101-001/1").mkdir(parents=True)
        (root / "comms/research/RQ-20300101-001/1/run-manifest.json").write_text("{}")
        runs = [{"databaseId": i, "conclusion": "success" if i != 4 else "failure", "headSha": "abc", "url": f"u{i}"}
                for i in (1, 2, 3, 4)] + [{"databaseId": 5, "conclusion": "success", "headSha": "abc", "url": "u5"}]

        def arts(_slug, run_id):
            if run_id == 5:
                return [{"name": "research-script-run-RQ-20300101-005-5", "expired": True}]
            unit = {1: "RQ-20300101-001", 2: "RQ-20300101-002", 3: "RQ-20300101-003", 4: "RQ-20300101-004"}[run_id]
            return [{"name": f"research-script-run-{unit}-{run_id}", "expired": False}]

        def fake_download(run_id, name, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "run-manifest.json").write_text("{}")
            if run_id == 2:
                return True   # old-style: no record-inputs.json
            unit = name.split("research-script-run-")[1].rsplit("-", 1)[0]
            rec = {"research_unit": unit, "power_state": "runnable", "decision_rule_id": "RULE-X",
                   "decision_rule_registered_at": "2030-01-01", "tool": "python3 x.py",
                   "artifact_store": f"comms/research/{unit}/{run_id}", "artifact_locator": "x", "note": "",
                   "measurement_file": "", "records_file": "", "min_rows": "1"}
            if run_id == 3:
                rec.update(verdict="pass", read_state="measured", population="7 committed trades", n="7")
            else:
                # collapsed-state: not_applicable — E5 VERDICT vocabulary (with read_state
                # producer_failed), not research_queue.power_state; fixture data only
                rec.update(verdict="not_applicable", read_state="producer_failed", population="script failed", n="null")
            (dest / RECORD_INPUTS).write_text(json.dumps(rec))
            return True

        res = collect(root, repo_slug="o/r", runs=runs, artifacts_for=arts, downloader=fake_download)
        assert [x["run_id"] for x in res["landed"]] == [3, 4], res
        assert [x["run_id"] for x in res["skipped"]] == [1, 2], res
        assert [x["run_id"] for x in res["lost"]] == [5], res
        for x in res["landed"]:
            assert (root / x["record"]).exists(), x
            rows = [json.loads(ln) for ln in (root / x["record"]).read_text().splitlines() if ln.strip()]
            assert rows and rows[0]["research_unit"] == x["unit"] and rows[0]["produced_by"]["run_id"] == str(x["run_id"]), rows
        # idempotent: a second collect lands nothing new
        res2 = collect(root, repo_slug="o/r", runs=runs, artifacts_for=arts, downloader=fake_download)
        assert res2["landed"] == [] and len(res2["skipped"]) == 4, res2
        # gh unreadable -> read_error, nothing claimed
        assert collect(root, repo_slug="o/r", runs=None, artifacts_for=arts, downloader=fake_download)["read_error"] \
            if not _gh(["--version"]) else True
        # dry run touches nothing
        (root / "comms/research/RQ-20300101-003").rename(root / "comms/research/RQ-20300101-003.bak")
        (root / "research/results/RQ-20300101-003").rename(root / "research/results/RQ-20300101-003.bak")
        res3 = collect(root, repo_slug="o/r", runs=runs, artifacts_for=arts, downloader=fake_download, dry_run=True)
        assert any(x["run_id"] == 3 and x["dry_run"] for x in res3["landed"]) and not (root / "comms/research/RQ-20300101-003").exists()
        # the three verdicts, planted (RQ-COLLECTOR). A CANCELLED run: record on main, NO run-manifest,
        # a non-empty directory -> already landed, never "lost" (the bug that read red every cycle).
        (root / "comms/research/RQ-20300101-006/6").mkdir(parents=True)
        (root / "comms/research/RQ-20300101-006/6/record-inputs.json").write_text("{}")
        (root / "research/results/RQ-20300101-006").mkdir(parents=True)
        (root / "research/results/RQ-20300101-006/6.jsonl").write_text("{}\n")
        runs2 = [{"databaseId": i, "conclusion": "cancelled", "headSha": "abc", "url": f"u{i}"} for i in (6, 7, 8, 9)]

        def arts2(_slug, run_id):
            if run_id == 7:
                return None                                            # API failure listing artifacts
            unit = f"RQ-20300101-00{run_id}"
            return [{"name": f"research-script-run-{unit}-{run_id}", "expired": run_id == 9}]

        res4 = collect(root, repo_slug="o/r", runs=runs2, artifacts_for=arts2, downloader=lambda *a: False)
        assert [x["run_id"] for x in res4["skipped"]] == [6], res4        # nothing-to-collect: landed already
        assert [x["run_id"] for x in res4["unreadable"]] == [7, 8], res4  # could-not-list / could-not-download
        assert [x["run_id"] for x in res4["lost"]] == [9], res4           # lost: expired before any cycle took it
        assert res4["landed"] == [] and res4["read_error"] is None, res4
        # nothing to collect at all is a clean cycle
        # a run whose record is already in an OPEN batch PR is skipped, not collected twice
        res6 = collect(root, repo_slug="o/r", runs=[runs2[2]], artifacts_for=arts2, downloader=lambda *a: False,
                       pending={("RQ-20300101-008", 8)})
        assert [x["run_id"] for x in res6["skipped"]] == [8] and not res6["unreadable"], res6
        assert _RECORD_PATH_RE.match("research/results/RQ-1-001/12.jsonl") and not _RECORD_PATH_RE.match("comms/x/1.jsonl")
        res5 = collect(root, repo_slug="o/r", runs=runs2[:1], artifacts_for=arts2, downloader=lambda *a: False)
        assert not (res5["lost"] or res5["unreadable"] or res5["read_error"] or res5["landed"]), res5
    # orphan re-collect: an artifact dir with record-inputs.json and no E5 record gets one; `local-*` is skipped
    with tempfile.TemporaryDirectory() as td:
        r2 = Path(td)
        (r2 / "scripts/research").mkdir(parents=True)
        (r2 / "scripts/research/research_result.py").write_text((_REPO / "scripts/research/research_result.py").read_text(encoding="utf-8"))
        (r2 / "research/results").mkdir(parents=True)
        for rid in ("777", "local-abc"):
            d = r2 / "comms/research/RQ-20300101-009" / rid
            d.mkdir(parents=True)
            (d / "run-manifest.json").write_text(json.dumps({"commit_sha": "abc123", "run_url": None}))
            (d / "record-inputs.json").write_text(json.dumps({
                "research_unit": "RQ-20300101-009", "power_state": "runnable", "decision_rule_id": "RULE-X",
                "decision_rule_registered_at": "2030-01-01", "tool": "python3 x.py", "verdict": "pass", "read_state": "measured",
                "population": "p", "n": "5", "artifact_store": f"comms/research/RQ-20300101-009/{rid}", "artifact_locator": "x",
                "note": "", "measurement_file": "", "records_file": "", "min_rows": "1"}))
        got = recollect_orphans(r2, repo_slug="o/r")
        assert [x["run_id"] for x in got] == [777], got
        assert (r2 / "research/results/RQ-20300101-009/777.jsonl").exists()
        assert recollect_orphans(r2, repo_slug="o/r") == []          # idempotent: now landed
    # ML-RQ-RUNNER: the trainer twin's artifact name resolves to the same (unit, run id) pair
    m = _ARTIFACT_RE.match("research-script-run-trainer-RQ-20261011-9da8-01-123456")
    assert m and m.group(1) == "RQ-20261011-9da8-01" and m.group(2) == "123456", m
    m = _ARTIFACT_RE.match("research-script-run-RQ-20261011-9da8-01-123456")
    assert m and m.group(1) == "RQ-20261011-9da8-01", m
    assert _ARTIFACT_RE.match("research-script-runner-RQ-20261011-001-1") is None
    print("collect_runner_results self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--repo", default="", help="owner/name (default: $GITHUB_REPOSITORY)")
    ap.add_argument("--recollect-orphans", action="store_true",
                    help="re-emit E5 records for landed artifact dirs that have none; then exit")
    ap.add_argument("--dry-run", action="store_true", help="list what would be collected; write nothing")
    ap.add_argument("--json-out", default="", help="write the batch manifest here (the dispatcher reads it)")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    import os
    slug = args.repo or os.environ.get("GITHUB_REPOSITORY") or ""
    if not slug:
        ap.error("--repo or $GITHUB_REPOSITORY is required")
    if args.recollect_orphans:
        for x in recollect_orphans(_REPO, repo_slug=slug):
            print(f"  recollected {x['unit']} run {x['run_id']} -> {x['record']}")
        return 0
    pending = pending_in_open_batches(slug)
    if pending is None:
        print("::warning::could not list open results-batch PRs; collecting without the duplicate check")
    res = collect(_REPO, repo_slug=slug, dry_run=args.dry_run, pending=pending)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(f"collect_runner_results: landed={len(res['landed'])} skipped={len(res['skipped'])} lost={len(res['lost'])}"
          + (f" READ_ERROR={res['read_error']}" if res["read_error"] else ""))
    for x in res["landed"]:
        print(f"  landed  {x['unit']:<18} run {x['run_id']}  {x.get('record') or '(dry run)'}")
    for x in res["lost"]:
        print(f"  LOST    {x.get('unit', '?'):<18} run {x['run_id']}  {x['why']}")
    for x in res["unreadable"]:
        print(f"::warning::collect_runner_results: could not read run {x['run_id']} ({x['why']}) -- not lost")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"count={len(res['landed'])}\nlost={len(res['lost'])}\nunreadable={len(res['unreadable'])}\n")
    # A lost run (or an unreadable run list) is a red cycle; a single API hiccup is a warning: rows that cost runner minutes must never vanish silently.
    return 1 if res["lost"] or res["read_error"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

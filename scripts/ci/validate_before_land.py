#!/usr/bin/env python3
# wiring: .github/workflows/research-queue-replenish.yml (before "Land the new units on main");
#         .github/workflows/research-queue-dispatch.yml (before "Land the batch of runner results on main" and
#         before "Land the dispatch stamps on main"); tests/test_validate_before_land.py
"""validate-before-land -- a self-landing producer checks its OWN generated tree before it lands anything.

Producer-side validation; enforces the existing never-land-red rule; respects the operator's 2026-11-12
PYTEST-RUN-REQUIRED: REPORT-ONLY decision; adds no merge-side gate.

WHY (AM-OPS-9, 2026-11-19). The replenish PR #27507 self-landed at 22:30:41Z while `pytest-run` was still
running -- legitimately: since 2026-11-12 `pytest-run` is report-only and branch protection requires only
`guards`. `pytest-run` then failed (`test_research_queue`: generated unit RQ-20261119-031 had no `power.sd`)
and main went red. The fix the manager chose is on the PRODUCER side, not the merge side: each self-landing
research producer runs the tests that read what it writes, on its generated working tree, BEFORE its
commit-to-main step. Nothing about what may merge changes.

WHAT IT DOES

  1. Runs the given pytest targets (one pytest process) and any ``--command`` strings, in the CURRENT
     working tree (the generated, uncommitted tree).
  2. PASS -> ``ok=true`` on $GITHUB_OUTPUT; the caller's commit-to-main step runs.
  3. FAIL -> ``ok=false``; the caller lands NOTHING this run (its commit-to-main step is gated on ok).
     With ``--baseline-ref`` the same checks are first re-run on a clean worktree of that ref: when every
     failure also fails there, main was ALREADY red on it, this producer did not introduce it, and the
     result is ``ok=true`` with a warning (used by the dispatch-stamp landing: an unlanded stamp re-fires
     its unit next cycle, so blocking stamps on someone else's red would turn one red test into a
     re-fire loop).
  4. On a FAIL it files exactly ONE pipeline item (scripts/ops/pipeline.py, which after the WSD-S4 freeze
     writes through the work store with WORK_STORE_TOKEN -- the route counterfactual-grade-closed.yml and
     desk-decisions-mirror.yml use). Deduplicated by the stable title prefix
     ``PRODUCER VALIDATION FAILED [<producer>]``: no second item while an open one exists. The item
     carries the failing test ids and a log tail. Filing is best effort: a failed filing is printed,
     never raised.
  5. Exits 0 on a pass AND on a fail (no red run, no halt -- "there is no halting"); the next scheduled run
     retries automatically. Only a bad invocation (argparse) or a failed --self-test exits non-zero.

    python3 scripts/ci/validate_before_land.py --producer research-queue-replenish --profile research-queue
    python3 scripts/ci/validate_before_land.py --producer x --pytest tests/test_foo.py --command "python3 y.py"
    python3 scripts/ci/validate_before_land.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]

TITLE_PREFIX = "PRODUCER VALIDATION FAILED"

#: The readers of what each self-landing research producer writes. Small on purpose: the tests that READ the
#: committed tree the producer writes into (whole-tree iterators of research/queue, the readers of the stamped
#: `last_dispatched_at`, the validator of research/results), never the whole suite -- `pytest-run` still runs
#: the full set on every push, report-only. Pinned (files exist, non-empty) by tests/test_validate_before_land.py.
PROFILES = {
    # research-queue-replenish ADDS research/queue/RQ-*.yaml: every test that walks the committed queue.
    "research-queue": {
        "pytest": [
            "tests/test_research_queue.py",
            "tests/test_research_queue_dispatch_fire_gate.py",
            "tests/test_research_queue_dispatch_rearm.py",
            "tests/test_research_queue_fairshare.py",
            "tests/test_research_queue_idempotence.py",
            "tests/test_research_queue_parse_cache.py",
            "tests/test_research_queue_timeouts_in_preflight_range.py",
            "tests/test_research_backpressure.py",
            "tests/test_kaggle_cpu_route.py",
            "tests/test_ml_data_published.py",
            "tests/test_fetch_corpus_candidate_pairs.py",
        ],
        "commands": [],
    },
    # research-queue-dispatch's stamp landing EDITS `last_dispatched_at` on existing units: the readers of that
    # field over the committed queue, plus the whole-queue validators a malformed edit would break.
    "research-queue-stamps": {
        "pytest": [
            "tests/test_research_queue.py",
            "tests/test_research_queue_idempotence.py",
            "tests/test_research_queue_dispatch_fire_gate.py",
            "tests/test_research_queue_fairshare.py",
            "tests/test_research_queue_parse_cache.py",
            "tests/test_research_backpressure.py",
        ],
        "commands": [],
    },
    # research-queue-dispatch's batch landing ADDS research/results/<unit>/<run>.jsonl + comms/research/<unit>/<run>/:
    # the whole-tree results validator, the dispatcher that reads a landed result row as a stamp, and the
    # committed-research no-balance check.
    "research-results": {
        "pytest": [
            "tests/test_research_queue.py",
            "tests/test_research_queue_idempotence.py",
            "tests/test_no_balance_in_committed_research.py",
        ],
        "commands": ["python3 scripts/ci/check_research_results.py"],
    },
}
LOG_TAIL_CHARS = 3000
_FAILED_LINE = re.compile(r"^(FAILED|ERROR) (\S+)")


def title_prefix(producer: str) -> str:
    """The STABLE prefix every filing for ``producer`` opens with; the dedupe key."""
    return f"{TITLE_PREFIX} [{producer}]"


@dataclass
class Result:
    ok: bool
    failing: List[str] = field(default_factory=list)
    log: str = ""
    note: str = ""


Runner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(cwd))
    return subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True, env=env)


def failing_ids(pytest_output: str) -> List[str]:
    """Test ids from pytest's ``-rfE`` short summary (``FAILED tests/x.py::t - msg`` / ``ERROR ...``)."""
    out = []
    for line in pytest_output.splitlines():
        m = _FAILED_LINE.match(line.strip())
        if m and m.group(2) not in out:
            out.append(m.group(2))
    return out


def run_checks(pytest_targets: Sequence[str], commands: Sequence[str], cwd: Path,
               runner: Runner = _run) -> Result:
    """Run every check in ``cwd``. Any non-zero exit is a failure -- including pytest's 5 (collected
    nothing): a validation that ran no test is not a pass."""
    failing: List[str] = []
    logs: List[str] = []
    if pytest_targets:
        argv = [sys.executable, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", *pytest_targets]
        cp = runner(argv, cwd)
        text = (cp.stdout or "") + (cp.stderr or "")
        logs.append(f"$ {' '.join(argv)}\n{text}")
        if cp.returncode != 0:
            ids = failing_ids(text)
            failing += ids or [f"pytest exit {cp.returncode} (no FAILED/ERROR line: collection or usage error)"]
    for cmd in commands:
        cp = runner(["bash", "-c", cmd], cwd)
        logs.append(f"$ {cmd}\n{(cp.stdout or '') + (cp.stderr or '')}")
        if cp.returncode != 0:
            failing.append(f"command (exit {cp.returncode}): {cmd}")
    return Result(ok=not failing, failing=failing, log="\n".join(logs))


def baseline_failures(ref: str, pytest_targets: Sequence[str], commands: Sequence[str], repo: Path,
                      runner: Runner = _run) -> Optional[List[str]]:
    """The same checks on a clean detached worktree of ``ref``; None when that could not be run."""
    tmp = Path(tempfile.mkdtemp(prefix="validate-before-land-base-"))
    wt = tmp / "tree"
    add = subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt), ref],
                         capture_output=True, text=True)
    if add.returncode != 0:
        print(f"::warning::validate-before-land: could not check out baseline {ref!r}: {add.stderr.strip()[:300]}")
        return None
    try:
        return run_checks(pytest_targets, commands, wt, runner).failing
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "(local run, no run url)"


def rerun_command(producer: str, pytest_targets: Sequence[str], commands: Sequence[str]) -> str:
    parts = ["python3", "scripts/ci/validate_before_land.py", "--producer", producer, "--no-file"]
    for t in pytest_targets:
        parts += ["--pytest", t]
    for c in commands:
        parts += ["--command", c]
    return " ".join(shlex.quote(p) for p in parts)


def build_item(item_id: str, producer: str, result: Result, run_url: str, rerun: str,
               today: Optional[date] = None) -> dict:
    due = ((today or _today()) + timedelta(days=2)).isoformat()
    shown = ", ".join(result.failing[:8]) + (f" (+{len(result.failing) - 8} more)" if len(result.failing) > 8 else "")
    return {
        "id": item_id,
        "what": (f"{title_prefix(producer)}: {len(result.failing)} failing check(s) on the generated tree; "
                 f"nothing was landed that run and the next scheduled run retries. Failing: {shown}"),
        "owner": "manager",
        "roadmap": ["unmapped"],
        "roadmap_unmapped_reason": "producer-validation observation (CI hygiene of a self-landing producer); "
                                   "no milestone owns it",
        "origin": {"kind": "audit", "by": producer, "ref": run_url, "rerun": rerun},
        "due_when": {"kind": "date", "due_date": due},
        "observation": {
            "what": f"{producer}'s generated output passes the tests that read it (validate-before-land ok=true) "
                    f"and its landing reaches main",
            "how_to_check": f"the latest {producer} run's 'Validate the generated tree' step prints "
                            f"'validate-before-land: PASS'; or run origin.rerun on a fresh generation",
            "due_by": due,
        },
        "failing_tests": list(result.failing),
        "log_tail": result.log[-LOG_TAIL_CHARS:],
        "next_action": "check_observation",
        "state": "queued",
    }


def open_duplicate(items: Iterable[dict], producer: str) -> Optional[str]:
    """The id of an OPEN item already filed for ``producer``, else None."""
    prefix = title_prefix(producer)
    for it in items:
        if str(it.get("what") or "").startswith(prefix) and it.get("state") in ("queued", "due", "routed"):
            return str(it.get("id"))
    return None


def file_failure(producer: str, result: Result, *, run_url: str, rerun: str,
                 store: Optional[Path] = None) -> str:
    """File ONE pipeline item for this failure, unless an open one exists. Never raises.

    Returns what happened, for the log: ``filed <id>`` / ``duplicate <id>`` / ``not filed: <why>``."""
    try:
        sys.path.insert(0, str(REPO / "scripts" / "ops"))
        if str(REPO) not in sys.path:
            sys.path.insert(1, str(REPO))
        import pipeline  # noqa: PLC0415 -- scripts/ops/pipeline.py
        st = Path(store) if store is not None else REPO / pipeline.STORE
        dup = open_duplicate(pipeline.read_log(st).items.values(), producer)
        if dup:
            return f"duplicate {dup}"
        tag = "PV" + hashlib.sha1(producer.encode("utf-8")).hexdigest()[:6].upper()
        item_id = pipeline.mint_id(tag, store=st)
        pipeline.append(build_item(item_id, producer, result, run_url, rerun), st, intent="new")
        return f"filed {item_id}"
    except BaseException as exc:  # noqa: BLE001 -- best effort by contract: a filing never stops the producer
        return f"not filed: {type(exc).__name__}: {exc}"


def _emit(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{name}={value}\n")
        except OSError as exc:
            print(f"::warning::validate-before-land: could not write $GITHUB_OUTPUT: {exc}")


def _summary(lines: List[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass


def validate(producer: str, pytest_targets: Sequence[str], commands: Sequence[str], *,
             baseline_ref: Optional[str] = None, file: bool = True, store: Optional[Path] = None,
             cwd: Optional[Path] = None, runner: Runner = _run) -> Result:
    """The whole step. Returns the verdict; never raises for a failing check or a failed filing."""
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    if not pytest_targets and not commands:
        res = Result(ok=False, failing=["no checks given (a validation that runs nothing is not a pass)"])
    else:
        res = run_checks(pytest_targets, commands, cwd, runner)
    if not res.ok and baseline_ref and (pytest_targets or commands):
        base = baseline_failures(baseline_ref, pytest_targets, commands, cwd, runner)
        if base is not None and res.failing and set(res.failing) <= set(base):
            res.ok = True
            res.note = (f"pre-existing on {baseline_ref}: every failing check also fails there, so this producer "
                        f"did not introduce it ({', '.join(res.failing[:5])})")
    if res.ok:
        print(f"validate-before-land: PASS [{producer}]" + (f" -- {res.note}" if res.note else ""))
        if res.note:
            print(f"::warning::validate-before-land [{producer}]: {res.note}")
        _emit("ok", "true")
        _summary([f"### validate-before-land [{producer}]: PASS", res.note])
        return res
    print(res.log[-LOG_TAIL_CHARS:])
    print(f"::error::validate-before-land [{producer}]: FAIL -- {len(res.failing)} failing check(s); "
          f"NOTHING is landed this run, the next scheduled run retries: {', '.join(res.failing[:10])}")
    outcome = "filing disabled (--no-file)"
    if file:
        outcome = file_failure(producer, res, run_url=_run_url(),
                               rerun=rerun_command(producer, pytest_targets, commands), store=store)
        if outcome.startswith("not filed"):
            print(f"::warning::validate-before-land [{producer}]: pipeline item {outcome}")
    print(f"validate-before-land: FAIL [{producer}] -- pipeline: {outcome}")
    _emit("ok", "false")
    _summary([f"### validate-before-land [{producer}]: FAIL (nothing landed)", "",
              *[f"- `{f}`" for f in res.failing[:30]], "", f"pipeline: {outcome}"])
    return res


def _self_test() -> int:
    bad = 0

    def ck(label: str, cond: bool) -> None:
        nonlocal bad
        print(("PASS " if cond else "FAIL ") + label)
        bad += 0 if cond else 1

    out = "....F\nFAILED tests/a.py::t1 - AssertionError: x\nERROR tests/b.py - ImportError\n1 failed"
    ck("failing_ids reads FAILED and ERROR lines", failing_ids(out) == ["tests/a.py::t1", "tests/b.py"])

    def fake(rc: int, text: str) -> Runner:
        return lambda argv, cwd: subprocess.CompletedProcess(argv, rc, text, "")

    ck("a passing run is ok", run_checks(["t"], [], REPO, fake(0, "1 passed")).ok)
    r = run_checks(["t"], [], REPO, fake(1, out))
    ck("a failing run is not ok and names the ids", not r.ok and r.failing == ["tests/a.py::t1", "tests/b.py"])
    ck("pytest collecting nothing (exit 5) is a failure", not run_checks(["t"], [], REPO, fake(5, "")).ok)
    ck("a failing command is a failure", not run_checks([], ["false"], REPO, fake(1, "")).ok)
    ck("an open item for the producer is a duplicate",
       open_duplicate([{"id": "X", "what": title_prefix("p") + ": 1", "state": "queued"}], "p") == "X")
    ck("a closed item is not a duplicate",
       open_duplicate([{"id": "X", "what": title_prefix("p") + ": 1", "state": "done"}], "p") is None)
    ck("another producer's item is not a duplicate",
       open_duplicate([{"id": "X", "what": title_prefix("q") + ": 1", "state": "queued"}], "p") is None)
    it = build_item("PI-1", "p", r, "u", "rr", today=date(2026, 11, 19))
    ck("the item is due in two days and carries an observation block",
       it["due_when"] == {"kind": "date", "due_date": "2026-11-21"} and it["observation"]["due_by"] == "2026-11-21")
    try:
        sys.path.insert(0, str(REPO / "scripts" / "ops"))
        import pipeline  # noqa: PLC0415
        pipeline.validate(it)
        ck("the item passes pipeline.validate", True)
    except Exception as exc:  # noqa: BLE001
        ck(f"the item passes pipeline.validate ({exc})", False)
    with tempfile.TemporaryDirectory() as d:
        store = Path(d) / "pipeline"
        first = file_failure("p", r, run_url="u", rerun="rr", store=store)
        second = file_failure("p", r, run_url="u", rerun="rr", store=store)
        ck("first failure files one item", first.startswith("filed "))
        ck("second failure while it is open files nothing", second.startswith("duplicate "))
        ck("exactly one record was written", len(list(store.glob("*.json"))) == 1)
    ck("a failed filing is returned, never raised",
       file_failure("p", r, run_url="u", rerun="rr", store=Path("/proc/version/nope")).startswith("not filed"))
    print("validate-before-land self-test: " + ("OK" if not bad else f"{bad} FAILED"))
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--producer", help="the calling workflow's name (the filing's title key)")
    ap.add_argument("--profile", action="append", default=[], choices=sorted(PROFILES),
                    help="a named reader set (PROFILES); repeatable; adds its pytest targets and commands")
    ap.add_argument("--pytest", action="append", default=[], metavar="TARGET",
                    help="a pytest target (file or node id); repeatable; all run in one pytest process")
    ap.add_argument("--command", action="append", default=[], metavar="CMD",
                    help="a shell command that must exit 0; repeatable")
    ap.add_argument("--baseline-ref", default=None,
                    help="re-run failures on a clean worktree of this ref; failures that also fail there are "
                         "pre-existing (not introduced by this producer) and do not block")
    ap.add_argument("--no-file", action="store_true", help="do not file a pipeline item on a failure")
    ap.add_argument("--store", default=None, help=argparse.SUPPRESS)  # tests: a temp pipeline store
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.producer:
        ap.error("--producer is required")
    targets, commands = list(a.pytest), list(a.command)
    for name in a.profile:
        targets += [t for t in PROFILES[name]["pytest"] if t not in targets]
        commands += [c for c in PROFILES[name]["commands"] if c not in commands]
    try:
        validate(a.producer, targets, commands, baseline_ref=a.baseline_ref, file=not a.no_file,
                 store=Path(a.store) if a.store else None)
    except Exception as exc:  # noqa: BLE001 -- an internal error is a FAIL (land nothing), never a red run
        print(f"::error::validate-before-land [{a.producer}]: internal error {type(exc).__name__}: {exc}; "
              f"treating as FAIL, nothing is landed this run")
        _emit("ok", "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

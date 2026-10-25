"""STAMP-RACE-2 (2026-10-12): dispatcher landings must not fail on their own plumbing.

MEASURED over 14 red `research-queue-dispatch` `land` jobs 2026-10-10/11:
a caller's dirty working tree broke `git checkout --detach FETCH_HEAD` (3 jobs)
and `git merge` in the stale-branch refresh (3), a content conflict between two
stamp PRs stranded 5, and the refresh itself cancelled the in-flight pytest-run
(`cancel-in-progress`) so the restarted suite outlasted the wait on 4 more.
These tests run the action's REAL blocks (sliced from action.yml) in scratch repos.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/commit-to-main/action.yml"
RESOLVER = ROOT / "scripts/ops/resolve_stamp_conflicts.py"
sys.path.insert(0, str(ROOT / "scripts/ops"))
import resolve_stamp_conflicts as rsc  # noqa: E402

TEXT = ACTION.read_text(encoding="utf-8")


def _git(cwd, *a, check=True):
    return subprocess.run(["git", *a], cwd=cwd, check=check, capture_output=True, text=True)


def _repo(tmp: Path) -> Path:
    w = tmp / "w"
    _git(tmp, "init", "-q", "-b", "main", str(w))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _git(w, "config", k, v)
    return w


def _unit(stamp: str, extra: str = "") -> str:
    return f"id: RQ-1\nstatus: queued\n{extra}last_dispatched_at: '{stamp}'\n"


def test_resolver_keeps_the_later_stamp_when_only_the_stamp_differs():
    a = _unit("2026-10-11T21:00:00+00:00")
    b = _unit("2026-10-11T22:00:00+00:00")
    p = "research/queue/RQ-1.yaml"
    assert rsc.resolve(p, a, b) == b
    assert rsc.resolve(p, b, a) == b


def test_resolver_never_lets_a_stamp_undo_a_rearm():
    """PI-20261013-HOPS1447-0001: a cleared stamp (`last_dispatched_at: null`) is a deliberate re-arm."""
    p = "research/queue/RQ-1.yaml"
    stamped = _unit("2026-10-12T14:51:40+00:00")
    cleared = "id: RQ-1\nstatus: queued\nlast_dispatched_at: null\n"
    base = _unit("2026-10-12T14:51:40+00:00")
    assert rsc.resolve(p, stamped, cleared) == cleared                    # branch stamp vs main re-arm
    assert rsc.resolve(p, cleared, stamped) == cleared
    assert rsc.resolve(p, _unit("2026-10-13T09:00:00+00:00"), cleared, base) == cleared
    # a side that did not move off the merge base loses to the side that did
    assert rsc.resolve(p, stamped, _unit("2026-10-13T01:00:00+00:00"), base) == _unit("2026-10-13T01:00:00+00:00")
    assert rsc.resolve(p, _unit("2026-10-13T01:00:00+00:00"), stamped, base) == _unit("2026-10-13T01:00:00+00:00")


def test_resolver_refuses_any_other_difference_or_path():
    p = "research/queue/RQ-1.yaml"
    assert rsc.resolve(p, _unit("2026-10-11T21:00:00+00:00", "x: 1\n"),
                       _unit("2026-10-11T22:00:00+00:00")) is None
    assert rsc.resolve("config/accounts.yaml", _unit("a"), _unit("b")) is None
    assert rsc.resolve(p, "id: RQ-1\n", "id: RQ-1\nstatus: x\n") is None


def test_resolver_cli_resolves_a_real_merge_conflict(tmp_path):
    w = _repo(tmp_path)
    f = w / "research/queue/RQ-1.yaml"
    f.parent.mkdir(parents=True)
    f.write_text(_unit("2026-10-11T20:00:00+00:00"))
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", "base")
    _git(w, "checkout", "-qb", "br")
    f.write_text(_unit("2026-10-11T21:00:00+00:00"))
    _git(w, "commit", "-qam", "br")
    _git(w, "checkout", "-q", "main")
    f.write_text(_unit("2026-10-11T22:00:00+00:00"))
    _git(w, "commit", "-qam", "main")
    _git(w, "checkout", "-q", "br")
    assert _git(w, "merge", "main", check=False).returncode != 0
    r = subprocess.run([sys.executable, str(RESOLVER), "research/queue/RQ-1.yaml"], cwd=w, check=False)
    assert r.returncode == 0
    assert "22:00:00" in f.read_text() and "<<<<" not in f.read_text()


def test_resolver_cli_is_all_or_nothing(tmp_path):
    w = _repo(tmp_path)
    q = w / "research/queue"
    q.mkdir(parents=True)
    for n in ("RQ-1", "RQ-2"):
        (q / f"{n}.yaml").write_text(_unit("2026-10-11T20:00:00+00:00"))
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", "base")
    _git(w, "checkout", "-qb", "br")
    (q / "RQ-1.yaml").write_text(_unit("2026-10-11T21:00:00+00:00"))
    (q / "RQ-2.yaml").write_text(_unit("2026-10-11T21:00:00+00:00", "x: 1\n"))
    _git(w, "commit", "-qam", "br")
    _git(w, "checkout", "-q", "main")
    (q / "RQ-1.yaml").write_text(_unit("2026-10-11T22:00:00+00:00"))
    (q / "RQ-2.yaml").write_text(_unit("2026-10-11T22:00:00+00:00", "x: 2\n"))
    _git(w, "commit", "-qam", "main")
    _git(w, "checkout", "-q", "br")
    _git(w, "merge", "main", check=False)
    before = (q / "RQ-1.yaml").read_text()
    r = subprocess.run([sys.executable, str(RESOLVER), "research/queue/RQ-1.yaml",
                        "research/queue/RQ-2.yaml"], cwd=w, check=False)
    assert r.returncode == 1
    assert (q / "RQ-1.yaml").read_text() == before


def test_replay_in_a_clean_worktree_survives_the_callers_dirty_tree(tmp_path):
    """The exact 3 'overwritten by checkout' failures: dirty file differs HEAD vs main."""
    start, end = "PRODUCED_WT=", "# CUT THE THROWAWAY BRANCH"
    assert start in TEXT and end in TEXT
    snippet = TEXT[TEXT.index(start):TEXT.index(end)]
    snippet = "\n".join(ln for ln in snippet.splitlines() if not ln.lstrip().startswith("#"))
    w = _repo(tmp_path)
    (w / "q.yaml").write_text("stamp: 0\n")
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", "base")
    base = _git(w, "rev-parse", "HEAD").stdout.strip()
    _git(w, "checkout", "-q", "--detach", base)
    (w / "r.json").write_text("1\n")
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", "produced")
    produced = _git(w, "rev-parse", "HEAD").stdout.strip()
    # main moves the file the caller has dirty
    _git(w, "checkout", "-q", "-B", "main", base)
    (w / "q.yaml").write_text("stamp: 9\n")
    _git(w, "commit", "-qam", "main moved")
    _git(w, "checkout", "-q", "--detach", produced)
    (w / "q.yaml").write_text("stamp: 5\n")          # caller's dirty edit
    script = f"set -euo pipefail\nRUNNER_TEMP={tmp_path}\n{snippet}\n" \
             "git checkout -q --detach main\ngit pwd 2>/dev/null || pwd\n"
    r = subprocess.run(["bash", "-c", script], cwd=w, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    assert (w / "q.yaml").read_text() == "stamp: 5\n"   # caller's tree untouched
    # control: the same checkout in the dirty tree is the failure we measured
    c = _git(w, "checkout", "-q", "--detach", "main", check=False)
    assert c.returncode != 0 and "overwritten" in c.stderr


def test_refresh_never_restarts_checks_that_are_running():
    assert "deferred_checks_in_flight" in TEXT
    assert "not_needed_checks_green" in TEXT
    assert "resolve_stamp_conflicts.py" in TEXT
    i = TEXT.index("WANT_REFRESH=0\n                if [ \"${MERGEABLE}\"")
    block = TEXT[i:i + 700]
    assert "inflight) REFRESH_STATE=" in block and "WANT_REFRESH=1" not in block.split("inflight)")[1].split(";;")[0]

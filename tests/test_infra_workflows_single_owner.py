"""B13: the single-owner report holds on the real repo, and its detector fires on planted cases."""
import subprocess
import sys

from scripts.ci import check_infra_workflows_single_owner as m


def test_self_test_passes():
    assert m.self_test() == 0


def test_real_repo_is_clean():
    """(b) is a subset of (a) plus runner-admin, and no research workflow reads the ops-pool variable."""
    assert m.owner_list(m.REPO) is not None
    assert m.findings(m.REPO) == []


def test_report_never_fails_the_run():
    r = subprocess.run([sys.executable, "scripts/ci/check_infra_workflows_single_owner.py"],
                       cwd=m.REPO, capture_output=True, text=True)
    assert r.returncode == 0

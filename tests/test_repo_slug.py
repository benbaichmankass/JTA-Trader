"""RENAME-SLUG-FUNCTIONAL-AUDIT: string-matched repo names read the slug and still accept the historical names."""
from __future__ import annotations

from scripts.ops import lane_reconcile, manager_view, repo_slug, session_reaper


def test_the_name_comes_from_the_runner_env_and_old_names_still_match(monkeypatch):
    repo_slug.current_name.cache_clear()
    monkeypatch.setenv("GITHUB_REPOSITORY", "benbaichmankass/JTA-Trader")
    try:
        assert repo_slug.current_name() == "JTA-Trader"
        for n in ("JTA-Trader", "jta-trader", "Metis-Insights", "benbaichmankass/metis-insights.git", "ict-trading-bot"):
            assert repo_slug.is_this_repo(n), n
        assert not repo_slug.is_this_repo("ict-trader-dashboard") and not repo_slug.is_this_repo(None)
    finally:
        repo_slug.current_name.cache_clear()


def test_pr_refs_under_the_new_and_the_old_name_are_this_repos():
    assert manager_view.parse_pr_ref("JTA-Trader#24881") == (24881, True)
    assert manager_view.parse_pr_ref("Metis-Insights#10654") == (10654, True)      # rows written before the rename
    assert manager_view.parse_pr_ref("ict-trader-dashboard#210") == (210, False)


def test_the_reaper_keeps_this_repos_branches_under_either_name_and_drops_others():
    row = {"branches": ["JTA-Trader:claude/a", "Metis-Insights:claude/b", "ict-trader-dashboard:claude/c", "claude/d"]}
    assert session_reaper._branch_names(row) == ["claude/a", "claude/b", "claude/d"]


def test_a_session_on_the_renamed_repo_is_not_foreign():
    assert "jta-trader" in lane_reconcile.PROJECT_REPOS

"""Tests for scripts/ops/pr_landing_hold_alarm.py (JC-CA-04,
docs/audits/code-audit-2026-09-27.md §6 `A09-hold-merge-unenforced`).

Wires the module's own ``_self_test`` into pytest (same shape as
tests/test_pr_mergeability.py — the self-tests are the contract; running
them here means pytest fails when they do) and adds MUTATION checks: each
load-bearing predicate is broken in isolation and the suite is proved to
NOTICE. A green run over an unmutated tree proves a test ran, never that it
discriminates.

Run: python3 -m pytest tests/test_pr_landing_hold_alarm.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import pr_landing_hold_alarm as pla  # noqa: E402


def test_self_test_passes():
    ok, fails = pla._self_test(quiet=True)
    assert ok, f"pr_landing_hold_alarm self-test failures: {fails}"


def test_alarm_fires_for_tier3_hold_with_no_reviews():
    v = pla.grade({"tier": 3, "landing": "hold"}, decl_unreadable=False,
                   reviews=[], reviews_unreadable=False,
                   pr_number=100, pr_title="flip a gate")
    assert v.state == pla.ALARM
    assert "#100" in v.ping_message()
    assert "flip a gate" in v.ping_message()


def test_clean_for_tier3_hold_with_human_approval():
    v = pla.grade(
        {"tier": 3, "landing": "hold"}, decl_unreadable=False,
        reviews=[{"state": "APPROVED", "user": {"login": "benbaichmankass", "type": "User"}}],
        reviews_unreadable=False,
    )
    assert v.state == pla.CLEAN


def test_bot_approval_does_not_clear_the_alarm():
    v = pla.grade(
        {"tier": 3, "landing": "hold"}, decl_unreadable=False,
        reviews=[{"state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}}],
        reviews_unreadable=False,
    )
    assert v.state == pla.ALARM


def test_out_of_scope_landings_never_alarm():
    for decl in (
        {"tier": 1, "landing": "hold"},
        {"tier": 2, "landing": "self", "approved_by": "x"},
        {"tier": 3, "landing": "mandate", "mandate": "MD-X"},
    ):
        v = pla.grade(decl, decl_unreadable=False, reviews=[], reviews_unreadable=False)
        assert v.state == pla.CLEAN, decl


def test_missing_declaration_alarms_rather_than_staying_quiet():
    v = pla.grade(None, decl_unreadable=False, reviews=[], reviews_unreadable=False)
    assert v.state == pla.ALARM


def test_unreadable_is_never_collapsed_into_clean_or_alarm():
    v = pla.grade(None, decl_unreadable=True, reviews=None, reviews_unreadable=True)
    assert v.state == pla.UNREADABLE
    v2 = pla.grade({"tier": 3, "landing": "hold"}, decl_unreadable=False,
                    reviews=None, reviews_unreadable=True)
    assert v2.state == pla.UNREADABLE


def test_cli_exit_codes(tmp_path, capsys):
    decl_path = tmp_path / "decl.json"
    decl_path.write_text(json.dumps({"tier": 3, "landing": "hold"}))
    reviews_path = tmp_path / "reviews.json"
    reviews_path.write_text(json.dumps([]))

    rc = pla.main(["--decl-json", str(decl_path), "--reviews-json", str(reviews_path),
                   "--pr-number", "42", "--pr-title", "test pr"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "#42" in out

    reviews_path.write_text(json.dumps(
        [{"state": "APPROVED", "user": {"login": "op", "type": "User"}}]))
    rc = pla.main(["--decl-json", str(decl_path), "--reviews-json", str(reviews_path)])
    assert rc == 0

    rc = pla.main(["--decl-json", "UNREADABLE", "--reviews-json", "UNREADABLE"])
    assert rc == 3

    rc = pla.main(["--decl-json", "MISSING", "--reviews-json", str(reviews_path)])
    assert rc == 2  # no declaration at all is itself an alarm


# ---------------------------------------------------------------------------
# MUTATION CHECKS — break a load-bearing predicate and prove _self_test
# notices.
# ---------------------------------------------------------------------------
def test_mutation_widening_alarm_tiers_is_load_bearing(monkeypatch):
    # If tier 2/3 stopped being the checked set (e.g. someone narrows it to
    # tier 3 only), the self-test's tier-2 case must go red.
    monkeypatch.setattr(pla, "_ALARM_TIERS", (3,))
    v = pla.grade({"tier": 2, "landing": "hold"}, decl_unreadable=False,
                  reviews=[{"state": "CHANGES_REQUESTED", "user": {"login": "op", "type": "User"}}],
                  reviews_unreadable=False)
    assert v.state == pla.CLEAN, "sanity: the mutation took (tier 2 no longer checked)"
    ok, _ = pla._self_test(quiet=True)
    assert not ok, "the self-test must go RED on this mutation"


def test_mutation_bot_login_counting_as_human_is_load_bearing(monkeypatch):
    # The exact self-land-failure shape JC-CA-04/A09 exists to catch: a bot
    # approving its own PR must never clear the alarm.
    monkeypatch.setattr(pla, "_is_human_approval", lambda review: review.get("state") == "APPROVED")
    v = pla.grade(
        {"tier": 3, "landing": "hold"}, decl_unreadable=False,
        reviews=[{"state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}}],
        reviews_unreadable=False,
    )
    assert v.state == pla.CLEAN, "sanity: the mutation took (bot now counts as human)"
    ok, _ = pla._self_test(quiet=True)
    assert not ok, "the self-test must go RED on this mutation"


def test_mutation_missing_declaration_reading_as_clean_is_load_bearing(monkeypatch):
    original_grade = pla.grade

    def _leaky_grade(decl, **kwargs):
        if decl is None and not kwargs.get("decl_unreadable"):
            return pla.Verdict(pla.CLEAN, "mutated: missing decl treated as clean",
                                kwargs.get("pr_number"), kwargs.get("pr_title"))
        return original_grade(decl, **kwargs)

    monkeypatch.setattr(pla, "grade", _leaky_grade)
    v = pla.grade(None, decl_unreadable=False, reviews=[], reviews_unreadable=False)
    assert v.state == pla.CLEAN, "sanity: the mutation took"
    ok, _ = pla._self_test(quiet=True)
    assert not ok, "the self-test must go RED on this mutation"


# --- recorded decisions resolve against the REAL tree (PI-20261004-GCFA5DOR-0005) ---
_ROOT = str(Path(__file__).resolve().parents[1])


def _grade_rd(rd, reviews=()):
    return pla.grade({"tier": 3, "landing": "hold", "recorded_decision": rd},
                     decl_unreadable=False, reviews=list(reviews), reviews_unreadable=False,
                     resolve=pla.make_resolver(_ROOT))


def test_real_checklist_row_and_pipeline_item_resolve():
    r = pla.make_resolver(_ROOT)
    assert r("BREAKOUT1-RETIRE")                      # docs/claude/work/checklist/BREAKOUT1-RETIRE.json
    assert r("PI-20261004-GCFA5DOR-0005")             # a pipeline item id
    assert r("scripts/ops/pr_landing_hold_alarm.py")  # a repo file
    assert not r("PI-99999999-NOPE-0001")
    assert not r("../etc/passwd") and not r("/etc/passwd")


def test_operator_decision_with_real_ref_is_clean_and_fake_ref_alarms():
    assert _grade_rd({"kind": "operator_decision", "ref": "BREAKOUT1-RETIRE"}).state == pla.CLEAN
    assert _grade_rd({"kind": "operator_decision", "ref": "MADE-UP-ROW"}).state == pla.ALARM


def test_standing_authorization_needs_the_date_and_an_existing_evidence_record():
    ok = {"kind": "standing_authorization",
          "ref": "2026-09-27 standing authorization BREAKOUT1-RETIRE",
          "evidence": "docs/claude/work/checklist/BREAKOUT1-RETIRE.json"}
    assert _grade_rd(ok).state == pla.CLEAN
    assert _grade_rd(dict(ok, evidence="comms/does-not-exist.json")).state == pla.ALARM
    assert _grade_rd(dict(ok, ref="BREAKOUT1-RETIRE")).state == pla.ALARM  # no 2026-09-27


def test_uncited_hold_still_alarms():
    assert pla.grade({"tier": 2, "landing": "hold"}, decl_unreadable=False, reviews=[],
                     reviews_unreadable=False, resolve=pla.make_resolver(_ROOT)).state == pla.ALARM


# --- 2026-11-12 (PI-20261112-BOTPING-0001, manager option (b)): a recorded approval on the PR itself ---
# The four tier-2/3 holds merged on the night the ping was first delivered. Bodies are verbatim excerpts.
_HOLD3 = {"tier": 3, "landing": "hold"}
_TONIGHT = {
    25001: ("**Operator decisions**, 2026-11-11 Thursday-planning doc, verbatim:\n"
            "- **a1:** *\"Retire the 28 with no active manifest now; the 44 after their manifests are removed\"*.\n"
            "- **a2:** *\"Accept as proposed\"*.", True),
    24988: ("**Operator decision**, 2026-11-11 Thursday-planning doc, question b1, verbatim choice: "
            "*\"Put qqq and tlt on the paper floor now; promote tlt to real money\"*.", True),
    24991: ("**Operator decision**, 2026-11-11 Thursday-planning doc, question b3, verbatim choice: "
            "*\"Retire it\"*. Operator's note: *\"We can retire it\"*", True),
    # #24926 cites no operator decision anywhere: it must still page unless one is recorded.
    24926: ("## What\nThree read routes over the ML lane's M1 long table ... Tier-2 by path; declared hold "
            "(`tier_2_3_needs_approval`).", False),
}


def test_tonights_merges_read_as_expected():
    for n, (body, approved) in _TONIGHT.items():
        v = pla.grade(_HOLD3, decl_unreadable=False, reviews=[], reviews_unreadable=False,
                      resolve=lambda t: False, pr_body=body, pr_number=n)
        assert (v.state == pla.CLEAN) is approved, (n, v.state, v.reason)


def test_label_and_meta_unreadable(tmp_path):
    v = pla.grade(_HOLD3, decl_unreadable=False, reviews=[], reviews_unreadable=False,
                  resolve=lambda t: False, pr_labels=[pla.APPROVED_LABEL])
    assert v.state == pla.CLEAN
    v = pla.grade(_HOLD3, decl_unreadable=False, reviews=[], reviews_unreadable=False,
                  resolve=lambda t: False, pr_meta_unreadable=True)
    assert v.state == pla.UNREADABLE


def test_cli_reads_body_and_labels_from_pr_json(tmp_path, capsys):
    decl = tmp_path / "d.json"
    decl.write_text(json.dumps(_HOLD3))
    rev = tmp_path / "r.json"
    rev.write_text("[]")
    pr = tmp_path / "pr.json"
    pr.write_text(json.dumps({"body": _TONIGHT[24991][0], "labels": []}))
    assert pla.main(["--decl-json", str(decl), "--reviews-json", str(rev), "--pr-json", str(pr)]) == 0
    pr.write_text(json.dumps({"body": "no citation", "labels": [{"name": "operator-approved"}]}))
    assert pla.main(["--decl-json", str(decl), "--reviews-json", str(rev), "--pr-json", str(pr)]) == 0
    pr.write_text(json.dumps({"body": "no citation", "labels": []}))
    assert pla.main(["--decl-json", str(decl), "--reviews-json", str(rev), "--pr-json", str(pr)]) == 2
    assert pla.main(["--decl-json", str(decl), "--reviews-json", str(rev), "--pr-json", "UNREADABLE"]) == 3


def test_ping_issue_is_opened_with_a_pat_not_github_token():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/pr-landing-hold-merge-alarm.yml").read_text()
    assert "PING_TOKEN: ${{ secrets.BRANCH_PROTECTION_TOKEN }}" in wf
    assert 'GH_TOKEN="${PING_TOKEN:-$GH_TOKEN}" gh issue create' in wf
    assert '--pr-json "$pr_arg"' in wf


def test_alarm_pings_via_the_direct_channel_first_and_keeps_the_issue_fallback():
    """HOLD-ALARM-PING-DIRECT: the ping goes to POST /api/bot/ops/actions send-ping first; any non-2xx falls back
    to the system-actions issue, so the alarm is never dropped (no halting)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / ".github/workflows/pr-landing-hold-merge-alarm.yml").read_text()
    i_direct, i_issue = src.index("/api/bot/ops/actions"), src.index("gh issue create --label system-action")
    assert i_direct < i_issue
    assert '"action": "send-ping"' in src and "X-Work-Store-Token" in src
    assert 'WORK_STORE_TOKEN: ${{ secrets.WORK_STORE_TOKEN }}' in src
    assert '[ "$code" = "202" ] || [ "$code" = "200" ]' in src and '[ "$direct" = "yes" ] && continue' in src


# --- a SPARSE checkout must still resolve a real path in the commit (#25799, run 43476136968;
#     operator decision 2026-11-13 "fix_a", PR-ALARM-RESOLVER-FIX) ---
def _git(*a, cwd):
    import os
    import subprocess
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"], "HOME": str(cwd)}
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=True,
                          env=env).stdout.strip()


def test_sparse_checkout_resolves_the_25799_ref_and_still_rejects_a_fake_path(tmp_path):
    """Reproduces the #25799 page on REAL git: the alarm workflow's checkout is sparse, so research/
    and comms/ are absent from the working tree though present in the commit. The ref and the
    evidence must resolve; a path the commit does not hold, and a directory, must not."""
    src = tmp_path / "src"
    for rel in ("research/queue/RQ-20261113-f251-02.yaml",
                "comms/research/RQ-20261113-f251-02/43452855935/evidence/slv_trend_1h.json",
                "scripts/ops/pr_landing_hold_alarm.py"):
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x\n")
    _git("init", "-q", "-b", "main", cwd=src)
    _git("add", "-A", cwd=src)
    _git("commit", "-q", "-m", "c", cwd=src)
    sparse = tmp_path / "sparse"
    _git("clone", "-q", "--no-checkout", "--filter=blob:none", f"file://{src}", str(sparse), cwd=tmp_path)
    _git("sparse-checkout", "set", "--no-cone", "/scripts/ops/pr_landing_hold_alarm.py", cwd=sparse)
    _git("checkout", "-q", "main", cwd=sparse)
    assert not (sparse / "research").exists(), "sanity: the checkout really is sparse"
    r = pla.make_resolver(str(sparse))
    ref = ("2026-09-27 data-backed authorization CRYPTO-FORMING-EQUITY-REGEN "
           "(unit research/queue/RQ-20261113-f251-02.yaml)")
    ev = "comms/research/RQ-20261113-f251-02/43452855935/evidence/slv_trend_1h.json"
    assert any(r(t) for t in ref.split())               # the exact #25799 ref now resolves
    assert r(ev)
    assert not r("research/queue/RQ-NOPE.yaml")         # still strict: absent from the commit
    assert not r("research/queue")                      # a directory is not a record
    v = pla.grade({"tier": 3, "landing": "hold",
                   "recorded_decision": {"kind": "standing_authorization", "ref": ref, "evidence": ev}},
                  decl_unreadable=False, reviews=[], reviews_unreadable=False, resolve=r)
    assert v.state == pla.CLEAN


def test_resolver_outside_a_git_repo_never_guesses(tmp_path):
    """No git repo under root: a repo path that is not on disk must NOT resolve (False on any git error)."""
    r = pla.make_resolver(str(tmp_path))
    assert not r("research/queue/RQ-20261113-f251-02.yaml")

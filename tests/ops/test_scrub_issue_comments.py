"""HEALTH-20261111-IB-ACCTID-PUBLIC: scrub tool uses the relay redactor's ib_account_id rule, touches nothing else
by default, and never prints a comment body from `list`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ops"))
import scrub_issue_comments as sic  # noqa: E402

FAKE = "DU" + "1234567"   # synthetic, built at runtime so no id-shaped literal sits in the repo


def test_redacts_only_the_named_rule():
    text = f"acct {FAKE} total_equity: 1000 ok"
    out, counts = sic.redact_with(text, {"ib_account_id"})
    assert FAKE not in out and "[REDACTED:ib_account_id]" in out
    assert "total_equity: 1000" in out          # other rules untouched by default
    assert counts == {"ib_account_id": 1}


def test_clean_text_is_a_no_op():
    out, counts = sic.redact_with("nothing sensitive here", {"ib_account_id"})
    assert out == "nothing sensitive here" and counts == {}


def test_list_prints_ids_and_counts_never_bodies(monkeypatch, capsys):
    comments = [{"id": 1, "html_url": "u1", "user": {"login": "github-actions[bot]"}, "body": f"x {FAKE}"},
                {"id": 2, "html_url": "u2", "user": {"login": "someone"}, "body": f"y {FAKE}"},
                {"id": 3, "html_url": "u3", "user": {"login": "github-actions[bot]"}, "body": "clean"}]
    monkeypatch.setattr(sic, "iter_comments", lambda repo, since, max_pages: iter(comments))
    rc = sic.main(["--repo", "o/r", "list"])
    out = capsys.readouterr()
    assert rc == 0
    rows = [json.loads(line) for line in out.out.splitlines()]
    assert [r["id"] for r in rows] == [1]                      # bot-only by default, matches only
    assert FAKE not in out.out and FAKE not in out.err          # no value leaks to the terminal
    assert "body" not in rows[0]


def test_apply_refuses_without_yes(tmp_path):
    ids = tmp_path / "ids.txt"
    ids.write_text("1\n")
    assert sic.main(["--repo", "o/r", "apply", "--ids", str(ids)]) == 2

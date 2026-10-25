"""PI-20261010-ERFFUW41-0002: the paper-book tracker reports a CURRENT-roster split
beside the historical cohort, and says "could not look" when accounts.yaml is unreadable."""
import json

from scripts.ops import paper_book_tracker as pbt


def _write(tmp_path, accounts_text):
    cohort = tmp_path / "cohort.yaml"
    cohort.write_text(
        "name: t\naccount: bybit_1\ncells: [a_cell, b_cell]\n"
        "families: {pullback: [a_cell, b_cell]}\nwatch: {recent_window_days: 30}\n")
    trades = tmp_path / "t.json"
    trades.write_text(json.dumps([
        {"pattern": "a_cell", "realizedPnl": 10.0, "closedAt": "2026-10-20T00:00:00Z"},
        {"pattern": "b_cell", "realizedPnl": -40.0, "closedAt": "2026-10-20T00:00:00Z"},
    ]))
    acc = tmp_path / "accounts.yaml"
    acc.write_text(accounts_text)
    return cohort, trades, acc


def _run(tmp_path, cohort, trades, acc):
    tracker = tmp_path / "tracker.jsonl"
    rc = pbt.main(["--trades-json", str(trades), "--cohort", str(cohort), "--tracker", str(tracker),
                   "--accounts", str(acc), "--asof", "2026-10-22T00:00:00Z"])
    assert rc == 0
    return json.loads(tracker.read_text().splitlines()[-1])


def test_split_counts_only_rostered_cells(tmp_path):
    cohort, trades, acc = _write(tmp_path, "accounts:\n  bybit_1:\n    strategies: [a_cell]\n")
    snap = _run(tmp_path, cohort, trades, acc)
    cr = snap["current_roster"]
    assert cr["rostered_cells"] == ["a_cell"]
    assert cr["off_roster_cells"] == ["b_cell"]
    assert cr["book"]["n"] == 1
    assert snap["book"]["n"] == 2  # historical cohort unchanged


def test_unreadable_accounts_is_none_not_empty(tmp_path):
    cohort, trades, acc = _write(tmp_path, "accounts: [unclosed\n")
    snap = _run(tmp_path, cohort, trades, acc)
    assert snap["current_roster"] is None

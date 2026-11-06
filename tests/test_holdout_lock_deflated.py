"""HOLDOUT-DEFLATED-REUSE (operator 2026-11-05, "Adopt (Rec.)"): the holdout ledger records every read, never refuses a re-read,
raises the bar with each read of a family on a window, and refuses only a window that overlaps training."""
import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import holdout_lock as HL


def test_self_test():
    HL.self_test()


def test_first_read_is_todays_bar_and_later_reads_are_stricter():
    b = [HL.bar_for(n) for n in range(1, 11)]
    assert abs(b[0]["ci_z"] - 1.96) < 1e-3 and b[0]["point_t_min"] == 0.0 and b[0]["ci_level"] == 0.95
    assert all(x["ci_z"] < y["ci_z"] and x["point_t_min"] < y["point_t_min"] for x, y in itertools.pairwise(b))


def test_rereads_recorded_and_overlap_refused(tmp_path):
    led = tmp_path / "l.jsonl"
    r = [HL.claim_read("MANAGE-a", "2025-10-01", "2026-09-30", f"U{i}", "t", led, train_end="2025-09-30") for i in range(3)]
    assert [x["n_tries"] for x in r] == [1, 2, 3]
    with pytest.raises(HL.WindowOverlapsTraining):
        HL.claim_read("MANAGE-a", "2025-06-01", "2026-09-30", "U9", "t", led, train_end="2025-09-30")
    assert len(HL._rows(led)) == 3


def test_committed_ledger_counts():
    fams = {(e["family"], e["start"], e["symbols"]): e for e in HL.families()}
    assert all(e["n_tries"] >= 1 and e["next_bar"]["n_tries"] >= 2 for e in fams.values())

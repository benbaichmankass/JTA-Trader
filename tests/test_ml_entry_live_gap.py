"""ml_decision_entry live-gap (drift-remediation step 2): the descriptive cuts are exact group statistics and the command is wired."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_decision_entry as E  # noqa: E402


def test_cut_gives_exact_group_stats_and_handles_empty():
    tk = pd.DataFrame({"side": ["long", "long", "short"], "net_r": [1.0, -0.5, 2.0]})
    c = E._cut(tk, "side")
    assert c["long"]["n"] == 2 and c["long"]["sum_net_r"] == 0.5 and abs(c["long"]["mean_net_r"] - 0.25) < 1e-12
    assert c["short"]["n"] == 1 and c["short"]["se_net_r"] is None
    assert E._cut(tk.iloc[0:0], "side") == {}


def test_live_gap_is_a_wired_subcommand():
    src = (Path(E.__file__)).read_text()
    assert '"live-gap"' in src and "return live_gap_cmd(a)" in src
    assert "holdout_lock.claim_read" in src.split("def live_gap_cmd", 1)[1].split("def main", 1)[0]

"""The holding_pays_neg25 exit-head target (RQ-20261117-aadc-11 dev PASS, -aadc-12 held-out-symbol PASS) is
1[future_r_delta >= -0.25], derived at matrix time from the same column holding_pays (>= +0.25) is cut from."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ml"))

import train_exit_head as teh  # noqa: E402


def _rows():
    return [{**{f: 0.0 for f in teh.FEATURES}, "future_r_delta": d, "holding_pays": int(d >= 0.25)}
            for d in (-1.0, -0.26, -0.25, -0.1, 0.0, 0.24, 0.25, 1.0)]


def test_neg25_label_is_the_margin_cut_on_future_r_delta(monkeypatch):
    monkeypatch.setattr(teh, "TARGET", "holding_pays_neg25")
    _, y = teh.matrix(_rows())
    assert y.tolist() == [0, 0, 1, 1, 1, 1, 1, 1]


def test_champion_label_is_unchanged(monkeypatch):
    monkeypatch.setattr(teh, "TARGET", "holding_pays")
    _, y = teh.matrix(_rows())
    assert y.tolist() == [0, 0, 0, 0, 0, 0, 1, 1]


def test_cli_and_export_accept_the_target():
    src = (ROOT / "scripts" / "ml" / "export_exit_head.py").read_text()
    assert '"holding_pays_neg25"' in src
    assert "holding_pays_neg25" in teh.DERIVED_TARGETS

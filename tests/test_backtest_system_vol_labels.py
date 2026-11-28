"""backtest_system --vol-verdict labels (RQ-20261128-rc4e-01): as-of, past-only, no stale carry beyond the labelled span."""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
import backtest_system as B  # noqa: E402


def _labels(tmp: Path) -> str:
    p = tmp / "l.jsonl"
    rows = [{"ts": "2021-01-01T00:00:00+00:00", "vol_regime": "calm"},
            {"ts": "2021-01-01T00:15:00+00:00", "vol_regime": "volatile"},
            {"ts": "2021-01-01T00:30:00+00:00", "vol_regime": "unknown"},
            {"ts": "2021-01-01T00:45:00+00:00", "vol_regime": "calm"}]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(p)


def _win(*stamps):
    return pd.DataFrame({"timestamp": pd.to_datetime(list(stamps), utc=True)})


def test_labels_resolver_is_past_only_and_asof(tmp_path):
    r = B._LabelsVolResolver(_labels(tmp_path))
    assert r.available and r.reason == "ok" and r._bar == 900.0
    # 5m clock bar 00:10-00:15 closes at 00:15: only the 00:00 label bar (closes 00:15) is closed -> calm
    assert r.vol_regime_for_window(_win("2021-01-01T00:05", "2021-01-01T00:10"), symbol="BTCUSDT", timeframe="5m") == "calm"
    # clock bar 00:25-00:30: the 00:15 label bar closed at 00:30 -> volatile (never the still-open later bar)
    assert r.vol_regime_for_window(_win("2021-01-01T00:20", "2021-01-01T00:25"), symbol="BTCUSDT", timeframe="5m") == "volatile"
    # an `unknown` row is dropped, so 00:40-00:45 still reads the newest closed calm/volatile bar (00:15)
    assert r.vol_regime_for_window(_win("2021-01-01T00:35", "2021-01-01T00:40"), symbol="BTCUSDT", timeframe="5m") == "volatile"
    # before the first label, and far beyond the labelled span: None (caller falls back to frozen and counts it)
    assert r.vol_regime_for_window(_win("2020-12-31T23:50", "2020-12-31T23:55"), symbol="BTCUSDT", timeframe="5m") is None
    assert r.vol_regime_for_window(_win("2021-01-02T00:00", "2021-01-02T00:05"), symbol="BTCUSDT", timeframe="5m") is None
    assert r.skips == {"before_first_label": 1, "label_gap": 1}


def test_labels_resolver_unreadable(tmp_path):
    r = B._LabelsVolResolver(str(tmp_path / "missing.jsonl"))
    assert not r.available and r.reason.startswith("labels_unreadable")


def test_vol_offcell_ml_arm_can_key_on_a_labels_file():
    sys.path.insert(0, str(REPO / "scripts" / "research"))
    import vol_offcell_fresh_wf as W
    assert W.ml_arm_flags("m") == ["--regime-router", "on", "--vol-verdict", "ml", "--ml-model-id", "m"]
    assert W.ml_arm_flags("m", "L.jsonl") == ["--regime-router", "on", "--vol-verdict", "labels", "--vol-labels", "L.jsonl"]

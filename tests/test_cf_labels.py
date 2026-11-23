"""CF-D1-LABELS: label rows from cf_bulk records, fidelity flag on every row (low-fidelity rows kept), purge/embargo folds."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_labels as cl  # noqa: E402


def _rec(key, entry, end, gap, base=0.5):
    return {"trade_key": key, "strategy": "s", "symbol": "BTCUSDT", "timeframe": "1h", "direction": "long", "entry_time": entry, "net_r": 0.4,
            "cf": {"status": "graded", "path": {"horizon_end": end}, "fidelity": {"abs_gap_r": gap},
                   "post_exit": {"verdict": {"verdict": "exited_early", "r_diff": 0.3}, "mfe_r": 2.0, "mae_r": -0.5},
                   "arms": {"replayed_actual_net_r": base, "original_brackets": {"net_r": 0.1, "resolved": True},
                            "alt_brackets": [{"sl_mult": 1.5, "tp_r": 6.0, "net_r": 0.9, "resolved": True},
                                             {"sl_mult": 1.0, "tp_r": 2.0, "net_r": None, "resolved": False}],
                            "less_management": [], "more_management": [{"arm_id": "more_x", "net_r": 0.7, "resolved": True}]}}}


def test_label_row_deltas_and_fidelity_flag_keep_low_fidelity_rows():
    ok, bad = cl.label_row(_rec("a", "2026-01-01 00:00:00+00:00", "2026-01-02T00:00:00Z", 0.05)), cl.label_row(
        _rec("b", "2026-01-01 00:00:00+00:00", "2026-01-02T00:00:00Z", 0.9))
    assert ok["fidelity_ok"] is True and bad["fidelity_ok"] is False and bad["abs_gap_r"] == 0.9      # low fidelity is emitted, flagged
    assert ok["arm_net_r"] == {"original_brackets": 0.1, "alt_sl1.5x_tp6R": 0.9, "more_x": 0.7}          # unresolved / null arm is absent, never 0
    assert ok["delta_vs_replay"]["alt_sl1.5x_tp6R"] == 0.4 and ok["post_exit"]["verdict"] == "exited_early"


def test_ungraded_record_is_not_labelled_and_is_counted():
    rows, meta = cl.build([_rec("a", "2026-01-01 00:00:00+00:00", "2026-01-02T00:00:00Z", 0.05),
                           {"trade_key": "z", "cf": {"status": "could_not_grade", "reason": "no_bars"}}])
    assert len(rows) == 1 and meta["n_records"] == 2 and meta["n_not_graded"] == 1 and meta["frac_fidelity_ok"] == 1.0


def test_purged_folds_drop_train_rows_whose_label_window_touches_the_test_fold():
    rows = [cl.label_row(_rec(f"k{i}", f"2026-01-{i + 1:02d} 00:00:00+00:00", f"2026-01-{i + 3:02d}T00:00:00Z", 0.0)) for i in range(10)]
    f = cl.purged_folds(rows, n_folds=5, embargo_s=0)
    assert len(f) == 5
    t = f[2]                                        # rows 4,5 (entries Jan 5-6, label ends Jan 7-8)
    assert t["test"] == [4, 5] and not set(t["test"]) & set(t["train"])
    assert 3 not in t["train"] and 2 not in t["train"]    # their windows (to Jan 5-6) reach into the test span
    assert 0 in t["train"] and 9 in t["train"]
    emb = cl.purged_folds(rows, n_folds=5, embargo_s=86400 * 2)[2]
    assert set(emb["train"]) < set(t["train"])      # an embargo only removes more

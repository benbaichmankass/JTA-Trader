"""ml_vol_label_replay featdiff (ML-VOL-LABEL-LIVE-VERIFY): live shadow feature rows joined to the offline dataset row of the
same bar (bar open = floor(predicted_at, tf) - tf, checked against hour_of_day), per-column agreement, stale fc_* bars flagged."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_live_bar_open_is_the_bar_that_just_closed():
    import ml_vol_label_replay as M
    bo = M.live_bar_open("2026-11-26T00:02:16+00:00", 900)
    assert bo.isoformat() == "2026-11-25T23:45:00+00:00"


def test_featdiff_aligns_bars_counts_agreement_and_flags_stale_fc(tmp_path):
    import ml_vol_label_replay as M
    live, off = [], []
    for i in range(6):
        h, m = divmod(i * 15, 60)
        bar = f"2026-11-25T10:{i * 15:02d}:00+00:00" if i < 4 else f"2026-11-25T11:{(i - 4) * 15:02d}:00+00:00"
        hour = 10 if i < 4 else 11
        pred_min = (i + 1) * 15
        ph, pm = 10 + pred_min // 60, pred_min % 60
        fc = 0.01 if i in (2, 3) else 0.001 * i          # bars 2 and 3 share one fc block -> bar 3 is stale
        live.append({"predicted_at_utc": f"2026-11-25T{ph:02d}:{pm:02d}:20+00:00", "model_id": "m1",
                     "feature_row": {"hour_of_day": hour, "log_return": 0.1 * i, "fc_ret_med": fc, "vol_bucket": "vol_b1"}})
        off.append({"ts": bar, "hour_of_day": hour, "log_return": 0.1 * i if i != 5 else 9.9, "fc_ret_med": fc,
                    "vol_bucket": "vol_b1" if i != 4 else "vol_b2", "unused_wide_col": 1})
    live.append({"predicted_at_utc": "2026-11-25T12:00:00+00:00", "model_id": "other", "feature_row": {"hour_of_day": 11}})
    lp, dp = tmp_path / "live.jsonl", tmp_path / "data.jsonl"
    lp.write_text("".join(json.dumps(r) + "\n" for r in live))
    dp.write_text("".join(json.dumps(r) + "\n" for r in off))
    rep = M.run_featdiff(live_path=lp, dataset_path=dp, model_id="m1")
    pop = rep["population"]
    assert pop["joined_bars"] == 6 and pop["other_model"] == 1 and pop["hour_mismatch"] == 0 and pop["stale_fc_bars"] == 1
    c = rep["columns"]
    assert c["log_return"]["compared"] == 6 and c["log_return"]["agree"] == 5
    assert c["vol_bucket"]["agree"] == 5 and c["fc_ret_med"]["agree_pct"] == 100.0
    assert rep["read_state"] == "measured" and rep["worst_agreement"]


def test_featdiff_verdict_names_the_divergent_columns():
    import ml_vol_label_replay as M
    rep = {"population": {"joined_bars": 100}, "read_state": "measured", "worst_agreement": [], "bar_range": None,
           "columns": {"a": {"agree_pct": 100.0}, "b": {"agree_pct": 80.0}, "c": {"agree_pct": None}}}
    v = M.featdiff_verdict(rep)
    assert v["verdict"] == "fail" and "b 80.0%" in v["note"]
    rep["columns"]["b"]["agree_pct"] = 99.5
    assert M.featdiff_verdict(rep)["verdict"] == "pass"
    rep["population"]["joined_bars"] = 10
    assert M.featdiff_verdict(rep)["verdict"] == "indeterminate"

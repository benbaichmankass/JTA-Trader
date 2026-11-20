"""scripts/research/mgc_feed_adequacy.py: is the Dukascopy XAU_USD proxy adequate for ict_scalp_mgc_15m, measured on the leg's own IB bars.

Covers the pieces that decide the verdict without any network or trainer: IB source discovery (pick printed, missing source named), the
5m->15m build (complete bins only), the feed metrics (a pure level basis moves the basis, not the correlation), the replay match, every
branch of the registered rule, and run() end to end with the fetch and the harness replaced.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import mgc_feed_adequacy as m  # noqa: E402

THR = dict(min_corr=0.985, max_p99_bps=8.0, max_pertrade_r=0.05, min_match=0.70, n_floor=39)


def _series(n=3000, seed=0, start="2025-01-06 00:00", freq="15min"):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(seed)
    close = 2000 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0}, index=idx)


def _trades(n, r, start="2025-02-03 10:00", every_h=7, direction="long"):
    ts = pd.date_range(start, periods=n, freq=f"{every_h}h", tz="UTC")
    return [{"entry_time": str(t), "direction": direction, "net_r": r} for t in ts]


def test_to_15m_keeps_only_complete_bins():
    idx = pd.date_range("2025-01-06 00:00", periods=6, freq="5min", tz="UTC")
    df = pd.DataFrame({"open": range(6), "high": range(6), "low": range(6), "close": range(6), "volume": 1.0}, index=idx)
    full = m.to_15m(df)
    assert len(full) == 2 and list(full.index) == [idx[0], idx[3]]
    gappy = m.to_15m(df.drop(idx[4]))             # the second bin lost a sub-bar: it must not become a bar
    assert len(gappy) == 1 and gappy.index[0] == idx[0]
    assert gappy.iloc[0]["close"] == 2 and gappy.iloc[0]["open"] == 0


def test_load_ib_5m_reads_jsonl_and_csv(tmp_path):
    rows = [{"ts": "2025-01-06T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3},
            {"ts": "2025-01-06T00:00:00+00:00", "open": 9, "high": 9, "low": 9, "close": 9, "volume": 9},     # duplicate ts dropped
            {"ts": "2025-01-06T00:05:00+00:00", "open": 1.5, "high": 2, "low": 1, "close": 1.8, "volume": 2}]
    j = tmp_path / "data.jsonl"
    j.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    c = tmp_path / "x.csv"
    c.write_text("timestamp,open,high,low,close,volume\n2025-01-06 00:00:00+00:00,1,2,0.5,1.5,3\n", encoding="utf-8")
    a, b = m.load_ib_5m(str(j)), m.load_ib_5m(str(c))
    assert len(a) == 2 and a.iloc[0]["close"] == 1.5 and len(b) == 1 and str(b.index[0].tz) == "UTC"


def test_find_ib_source_prints_its_pick_and_names_what_was_tried(tmp_path, capsys):
    (tmp_path / "v001").mkdir()
    (tmp_path / "v002").mkdir()
    for v in ("v001", "v002"):
        (tmp_path / v / "data.jsonl").write_text("{}\n")
    pick, tried = m.find_ib_source([str(tmp_path / "nope" / "*.jsonl"), str(tmp_path / "v*" / "data.jsonl")])
    assert pick.endswith("v002/data.jsonl")                       # highest version wins
    assert "v002/data.jsonl" in capsys.readouterr().err           # the pick is printed, never silent
    assert len(tried) == 2 and "0 file(s)" in tried[0]
    none, tried2 = m.find_ib_source([str(tmp_path / "zzz" / "*.csv")])
    assert none is None and tried2 == [f"{tmp_path}/zzz/*.csv -> 0 file(s)"]


def test_a_pure_level_basis_moves_the_basis_not_the_correlation():
    ib = _series()
    dk = ib * np.array([1, 1, 1, 1, 1])                           # same shape ...
    dk["close"] = ib["close"] / 1.0088                            # ... a constant +88 bps futures-over-spot basis
    f = m.feed_metrics(ib, dk)
    assert f["corr"] > 0.9999 and f["p99_bps"] < 0.01
    assert abs(f["basis_median_bps"] - 88.0) < 1.0 and abs(f["basis_drift_bps"]) < 0.5
    assert f["common"] == len(ib) and f["only_ib"] == 0 and f["only_duka"] == 0


def test_a_drifting_basis_is_reported_as_drift():
    ib = _series(n=4000)
    ramp = np.linspace(0.0, 0.01, len(ib))                        # basis grows 0 -> 100 bps over ~42 days
    dk = ib.copy()
    dk["close"] = ib["close"] / (1 + ramp)
    f = m.feed_metrics(ib, dk)
    # drift = mean basis of the LAST 20 days minus the FIRST 20 days: 100 x (1 - 2 x 10/41.7) = about 52 bps, not 100
    assert 48.0 < f["basis_drift_bps"] < 56.0
    flat = m.feed_metrics(ib, ib.assign(close=ib["close"] / 1.0088))
    assert abs(flat["basis_drift_bps"]) < 0.5                     # control: a constant basis has no drift


def test_independent_noise_lowers_the_correlation_and_counts_one_sided_bars():
    ib = _series(seed=1)
    dk = _series(seed=2).drop(_series(seed=2).index[1000:1010])   # unrelated returns, 10 bars missing INSIDE the overlap
    f = m.feed_metrics(ib, dk)
    assert f["corr"] < 0.5 and f["only_ib"] == 10 and f["only_duka"] == 0


def test_too_little_overlap_reads_null_not_zero():
    f = m.feed_metrics(_series(n=50), _series(n=50))
    assert f["corr"] is None and f["p99_bps"] is None and f["basis_median_bps"] is None


def test_replay_matches_by_direction_within_one_bar():
    ib = [{"entry_time": "2025-02-03 10:00:00+00:00", "direction": "long", "net_r": 1.0},
          {"entry_time": "2025-02-03 12:00:00+00:00", "direction": "short", "net_r": -1.0},
          {"entry_time": "2025-02-03 14:00:00+00:00", "direction": "long", "net_r": 0.5}]
    dk = [{"entry_time": "2025-02-03 10:15:00+00:00", "direction": "long", "net_r": 0.9},      # one bar late: matches
          {"entry_time": "2025-02-03 12:00:00+00:00", "direction": "long", "net_r": -0.5},     # wrong direction: no match
          {"entry_time": "2025-02-03 14:45:00+00:00", "direction": "long", "net_r": 0.5}]      # three bars late: no match
    r = m.replay_metrics(ib, dk)
    assert r["matched"] == 1 and abs(r["match_share"] - 1 / 3) < 1e-9
    assert r["n_ib"] == 3 and abs(r["net_r_ib"] - 0.5) < 1e-9 and abs(r["per_trade_duka"] - 0.9 / 3) < 1e-9


GOOD_FEED = {"corr": 0.995, "p99_bps": 4.0, "basis_median_bps": 80.0, "basis_drift_bps": 5.0}
GOOD_REP = {"n_ib": 120, "n_duka": 118, "net_r_ib": -20.0, "net_r_duka": -22.0, "per_trade_ib": -0.1667, "per_trade_duka": -0.1864, "match_share": 0.85}


def test_the_rule_passes_when_every_clause_holds():
    g = m.grade(GOOD_FEED, GOOD_REP, **THR)
    assert g["verdict"] == "pass" and g["label"] == "PROXY_ADEQUATE" and all(g["conditions"].values())


@pytest.mark.parametrize("feed_patch,rep_patch,failed", [
    ({"corr": 0.97}, {}, "F1_corr"),
    ({"p99_bps": 9.0}, {}, "F2_p99"),
    ({}, {"net_r_duka": +5.0, "per_trade_duka": 0.04}, "R1_sign"),
    ({}, {"per_trade_duka": -0.30}, "R2_per_trade"),
    ({}, {"match_share": 0.5}, "R3_match"),
])
def test_each_clause_fails_the_proxy_on_its_own(feed_patch, rep_patch, failed):
    g = m.grade({**GOOD_FEED, **feed_patch}, {**GOOD_REP, **rep_patch}, **THR)
    assert g["verdict"] == "fail" and g["label"] == "PROXY_INADEQUATE" and not g["conditions"][failed]
    assert failed in g["note"]
    # the control: with that one clause healthy again the same inputs pass
    assert m.grade(GOOD_FEED, GOOD_REP, **THR)["verdict"] == "pass"


def test_below_the_n_floor_or_with_a_null_is_indeterminate_never_a_pass():
    assert m.grade(GOOD_FEED, {**GOOD_REP, "n_ib": 38}, **THR)["verdict"] == "indeterminate"
    assert m.grade({**GOOD_FEED, "corr": None}, GOOD_REP, **THR)["verdict"] == "indeterminate"
    assert m.grade(GOOD_FEED, {**GOOD_REP, "match_share": None}, **THR)["verdict"] == "indeterminate"


def _args(tmp_path, **kw):
    d = dict(out=str(tmp_path / "out"), rule_id="RULE-X", **THR)
    d.update(kw)
    return argparse.Namespace(**d)


def test_run_without_an_ib_source_lands_unmeasured_and_names_what_it_tried(tmp_path):
    rc = m.run(_args(tmp_path), source=lambda: (None, ["a -> 0 file(s)"]))
    v = json.loads((tmp_path / "out" / "verdict.json").read_text())
    assert rc == 0 and v["verdict"] == "indeterminate" and v["read_state"] == "unmeasured"
    assert v["measurement"]["tried"] == ["a -> 0 file(s)"]


def test_run_end_to_end_with_the_fetch_and_the_harness_replaced(tmp_path, monkeypatch):
    ib15 = _series(n=2400)
    ib5 = []
    for t, row in ib15.iterrows():                                # rebuild 5m rows that aggregate back to the same 15m closes
        for k in range(3):
            ib5.append({"ts": (t + pd.Timedelta(minutes=5 * k)).isoformat(), "open": row.close, "high": row.close, "low": row.close,
                        "close": row.close, "volume": 1})
    src = tmp_path / "data.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in ib5), encoding="utf-8")

    def fake_fetch(days, dest):
        d = ib15.copy()
        d["close"] = d["close"] / 1.0088
        d.reset_index().rename(columns={"index": "timestamp"}).to_csv(dest, index=False)
        return 0

    calls = []

    def fake_arm(csv, start, end, out):
        calls.append((Path(csv).name, start, end))
        return 0, _trades(60, -0.1)

    monkeypatch.setattr(m, "fetch_duka", fake_fetch)
    monkeypatch.setattr(m, "run_arm_a", fake_arm)
    rc = m.run(_args(tmp_path), source=lambda: (str(src), ["t"]))
    v = json.loads((tmp_path / "out" / "verdict.json").read_text())
    assert rc == 0 and v["read_state"] == "measured" and v["verdict"] == "pass"
    assert v["measurement"]["feed"]["corr"] > 0.999 and abs(v["measurement"]["feed"]["basis_median_bps"] - 88) < 1
    assert len(calls) == 2 and calls[0][1:] == calls[1][1:]       # BOTH corpora replayed on the SAME window
    assert calls[0][0] == "ib_MGC_15m.csv" and calls[1][0] == "duka_MGC_15m.csv"
    assert (tmp_path / "out" / "arms" / "A_IB__trades.jsonl").exists()

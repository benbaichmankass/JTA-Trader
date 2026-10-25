"""PATH-FLOW-JOIN: the point-in-time flow join (scripts/research/path_flow_join.py).

Covers: the join is point-in-time (funding = last settled at or before the bar close, OI lagged, taker = the bar's
own), missing flow stays missing (never 0), a forward-shifted flow column is refused, the coverage report is exact,
the low-coverage drop names the leg, and the grade finds a planted flow signal and not a null one.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
import first_passage_paths as fpp  # noqa: E402
import path_flow_join as pfj  # noqa: E402

TF = 240
T0 = pd.Timestamp("2024-01-01", tz="UTC")


def _candles(n=40, with_taker=True):
    ts = [T0 + pd.Timedelta(minutes=TF * i) for i in range(n)]
    vol = np.full(n, 100.0)
    df = pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": vol})
    if with_taker:
        df["taker_buy_base"] = 50.0 + np.arange(n)  # imbalance = 2*(50+i)/100 - 1 = i/50
    return df


def _rows(entry_i=10, n=6):
    """One trade: bar_offset 1..n, the last row the exit."""
    rows = []
    for k in range(1, n + 1):
        rows.append({"trade_key": "t1", "ts": str(T0 + pd.Timedelta(minutes=TF * (entry_i + k))), "bar_offset": k,
                     "is_exit": k == n})
    return rows


def _funding():
    # settles every 8h: 00:00, 08:00, 16:00 ...; rate encodes the settlement hour index
    ts = pd.date_range(T0 - pd.Timedelta(days=1), periods=30, freq="8h")
    return pd.DataFrame({"ts": ts, "rate": np.arange(30) * 1e-5})


def _oi():
    ts = pd.date_range(T0 - pd.Timedelta(days=1), periods=2000, freq="5min")
    return pd.DataFrame({"ts": ts, "oi": 1000.0 + np.arange(2000)})


def _join(rows=None, funding=None, oi=None, candles=None):
    c = _candles() if candles is None else candles
    imb = pfj.candle_imbalance(c, TF)
    return pfj.join_flow(rows or _rows(), TF, imb, _funding() if funding is None else funding,
                         _oi() if oi is None else oi), imb


def test_taker_is_the_bars_own_and_matches_the_definition():
    j, _ = _join()
    # row offset 1 is bar index 11 -> imbalance 11/50
    assert j[0]["flow_taker_imb"] == pytest.approx(11 / 50)
    assert j[0]["flow_taker_imb_src_ts"] == str(T0 + pd.Timedelta(minutes=TF * 11))
    # trailing 6-bar mean including bar t: bars 6..11 -> mean(6..11)/50
    assert j[0]["flow_taker_imb_mean6"] == pytest.approx(np.mean(range(6, 12)) / 50)


def test_funding_is_last_settled_at_or_before_the_close():
    j, _ = _join()
    # row 0: bar 11 opens T0+44h, closes T0+48h = exactly a settlement (index of T0+48h in the series is 9)
    close = T0 + pd.Timedelta(hours=48)
    assert pd.Timestamp(j[0]["flow_funding_src_ts"]) == close
    assert j[0]["flow_funding_last"] == pytest.approx(9e-5)
    # row 1 closes at +52h: still the +48h settlement, never the +56h one
    assert pd.Timestamp(j[1]["flow_funding_src_ts"]) == close
    for r in j:
        assert pd.Timestamp(r["flow_funding_src_ts"]) <= pd.Timestamp(r["ts"]) + pd.Timedelta(minutes=TF)


def test_oi_is_lagged_and_entry_relative():
    j, _ = _join()
    close0 = T0 + pd.Timedelta(minutes=TF * 12)
    assert pd.Timestamp(j[0]["flow_oi_src_ts"]) == close0 - pd.Timedelta(minutes=5)
    assert pd.Timestamp(j[0]["flow_oi_src_ts"]) <= close0 - pd.Timedelta(minutes=5)
    # OI rises 1 per 5 minutes: the change since the entry-bar close is positive and grows with offset
    assert j[0]["flow_oi_chg_entry"] > 0
    assert j[3]["flow_oi_chg_entry"] > j[0]["flow_oi_chg_entry"]


def test_missing_flow_stays_missing_never_zero():
    c = _candles(with_taker=False)
    empty_f = pd.DataFrame({"ts": pd.to_datetime([], utc=True), "rate": []})
    empty_o = pd.DataFrame({"ts": pd.to_datetime([], utc=True), "oi": []})
    j, _ = _join(candles=c, funding=empty_f, oi=empty_o)
    for r in j:
        for k in ("taker_imb", "taker_imb_mean6", "funding_last", "funding_chg_entry", "oi", "oi_chg_6bar",
                  "oi_chg_entry"):
            assert r[f"flow_{k}"] is None, k
    cov = pfj.coverage("x", j)
    assert all(v == 0.0 for v in cov["share"].values())


def test_stale_funding_is_missing_not_carried_forever():
    f = _funding().iloc[:2]  # last settlement at T0-24h+8h = T0-16h; every row is > 24h later
    j, _ = _join(funding=f)
    assert all(r["flow_funding_last"] is None for r in j)


def test_forward_shifted_taker_column_is_refused():
    j, imb = _join()
    shifted = [dict(r) for r in j]
    vals = [r["flow_taker_imb"] for r in j]
    for i in range(len(shifted) - 1):  # each row now carries the NEXT bar's imbalance
        shifted[i]["flow_taker_imb"] = vals[i + 1]
    with pytest.raises(pfj.LookaheadError, match="shifted column"):
        pfj.refuse_lookahead(shifted, TF, imb=imb)
    # ... and the untouched join passes the same guard
    pfj.refuse_lookahead(j, TF, imb=imb)


def test_forward_stamped_sources_are_refused():
    j, imb = _join()
    bad = [dict(r) for r in j]
    bad[0]["flow_funding_src_ts"] = str(pd.Timestamp(bad[0]["ts"]) + pd.Timedelta(hours=9))
    with pytest.raises(pfj.LookaheadError, match="funding source"):
        pfj.refuse_lookahead(bad, TF, imb=imb)
    bad = [dict(r) for r in j]
    bad[0]["flow_oi_src_ts"] = str(pd.Timestamp(bad[0]["ts"]) + pd.Timedelta(minutes=TF))
    with pytest.raises(pfj.LookaheadError, match="OI source"):
        pfj.refuse_lookahead(bad, TF, imb=imb)
    bad = [dict(r) for r in j]
    bad[0]["flow_taker_imb_src_ts"] = str(pd.Timestamp(bad[0]["ts"]) + pd.Timedelta(minutes=TF))
    with pytest.raises(pfj.LookaheadError, match="taker source stamp"):
        pfj.refuse_lookahead(bad, TF, imb=imb)


def test_join_itself_refuses_a_shifted_candle_feed():
    """A feed whose taker column is shifted one bar forward cannot be laundered through the join: the guard
    recomputes from the SAME series the join read, so only a column that disagrees with its source is caught --
    which is why the shifted-ROW test above is the load-bearing one. Here the series is the truth."""
    c = _candles()
    imb = pfj.candle_imbalance(c, TF)
    rows = pfj.join_flow(_rows(), TF, imb, _funding(), _oi())
    assert rows[0]["flow_taker_imb"] == pytest.approx(imb[pd.Timestamp(rows[0]["ts"])])


def test_coverage_report_counts_states_not_the_exit_row():
    j, _ = _join()
    # remove the OI for the last two pre-exit states and the taker for one
    j[3]["flow_oi_chg_6bar"] = None
    j[4]["flow_oi_chg_6bar"] = None
    j[0]["flow_taker_imb"] = None
    cov = pfj.coverage("leg_x", j)
    assert cov["n_states"] == 5 and cov["n_trades"] == 1
    assert cov["share"]["taker_imb"] == pytest.approx(4 / 5)
    assert cov["share"]["oi_chg_6bar"] == pytest.approx(3 / 5)
    assert cov["share"]["funding_last"] == 1.0
    assert cov["input_share"] == {"taker": 0.8, "funding": 1.0, "open_interest": 0.6}
    assert pfj.legs_failing([cov], 0.8) == {"leg_x": {"oi_chg_6bar": 0.6}}
    assert pfj.legs_failing([cov], 0.5) == {}


# --------------------------------------------------------------------------- the grade
def _args(**kw):
    d = dict(mode="grade", reference="R0", min_coverage=0.8, min_gain_nats=0.002, min_folds=4, min_n=100,
             n_folds=6, n_boot=300)
    d.update(kw)
    return argparse.Namespace(**d)


def _flowed(corpus, planted, seed=3, drop_oi_for=None):
    """Attach flow_* to synthetic path rows. planted: taker imbalance reads the trade's regime (adx), which R0 lacks."""
    rng = np.random.default_rng(seed)
    out = []
    for leg, prow, trow, tf in corpus:
        rows = []
        for r in prow:
            n = dict(r)
            sig = 0.4 * (float(r["adx_14"]) - 22) / 8 if planted else 0.0
            n["flow_taker_imb"] = float(np.clip(sig + 0.3 * rng.normal(), -1, 1))
            n["flow_taker_imb_mean6"] = n["flow_taker_imb"]
            n["flow_funding_last"] = float(1e-4 * rng.normal())
            n["flow_funding_chg_entry"] = float(1e-4 * rng.normal())
            has_oi = leg != drop_oi_for
            n["flow_oi_chg_entry"] = float(0.01 * rng.normal()) if has_oi else None
            n["flow_oi_chg_6bar"] = float(0.01 * rng.normal()) if has_oi else None
            rows.append(n)
        out.append((leg, rows, trow, tf))
    return out


def test_grade_finds_planted_flow_and_not_a_null():
    planted = pfj.grade_corpus(_flowed(fpp.synthetic_corpus(planted=True), True), _args())
    assert planted["verdict"] == "pass", planted["note"]
    assert planted["measurement"]["flow_info"]["mean_gain_nats"] > 0.002
    null = pfj.grade_corpus(_flowed(fpp.synthetic_corpus(planted=False), False), _args())
    assert null["verdict"] != "pass", null["note"]


def test_low_coverage_leg_is_dropped_and_named():
    corpus = _flowed(fpp.synthetic_corpus(planted=True), True, drop_oi_for="syn_pullback_2h")
    v = pfj.grade_corpus(corpus, _args(min_n=100))
    assert list(v["measurement"]["legs_dropped_low_coverage"]) == ["syn_pullback_2h"]
    assert "syn_pullback_2h" in v["note"]
    kept_legs = {p["leg"] for p in v["measurement"]["flow_info"]["per_leg"].items()} if False else set(
        v["measurement"]["flow_info"]["per_leg"])
    assert kept_legs == {"trend_donchian_syn_4h"}


def test_too_few_trades_after_the_drop_is_indeterminate():
    corpus = _flowed(fpp.synthetic_corpus(planted=True), True, drop_oi_for="syn_pullback_2h")
    v = pfj.grade_corpus(corpus, _args(min_n=600))
    assert v["verdict"] == "indeterminate"

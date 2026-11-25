"""cf_bar_labels (AM v2 unit 1): the entry convention, no-lookahead and the label arithmetic."""
import copy
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "scripts" / "research")]
import cf_bar_labels as L  # noqa: E402

H = 3600.0


def bar(i, o, h, lo, c):
    return {"time": i * H, "open": o, "high": h, "low": lo, "close": c}


def flat(n, start=0, px=100.0):
    return [bar(start + i, px, px + 0.2, px - 0.2, px) for i in range(n)]


def test_signal_bar_is_never_read():
    # signal bar (index 0, opens at entry_time) has a huge range; the fill is at its close, so it must be dropped
    bars = [bar(0, 100, 150, 50, 100)] + flat(5, start=1)
    rows = L.build_rows(side="long", entry=100.0, sl=98.0, bars=bars, entry_time=0.0, bar_seconds=H)
    assert rows and rows[0]["features"]["bars_open"] == 1 and rows[0]["features"]["peak_r"] < 0.2   # not the 150 high


def test_features_do_not_depend_on_future_bars():
    base = flat(10, start=1)
    a = L.build_rows(side="long", entry=100.0, sl=98.0, bars=base, entry_time=0.0, bar_seconds=H)
    fut = copy.deepcopy(base)
    fut[7] = bar(8, 100, 130, 60, 90)                                     # wreck the future after bar 5
    b = L.build_rows(side="long", entry=100.0, sl=98.0, bars=fut, entry_time=0.0, bar_seconds=H)
    for k in range(5):
        assert a[k]["features"] == b[k]["features"]                       # features at k identical for k < the changed bar
    assert a[0]["labels"] != b[0]["labels"] or a[0]["labels"]["fwd_mfe_r"] != b[0]["labels"]["fwd_mfe_r"]  # labels DO read it


def test_reach_and_stop_first_arithmetic_long():
    # R0 = 2. bar1 flat; bar2 runs to 104 (= +2R from entry, +2R from the bar-1 close at 100); bar3 would hit the stop at 98
    bars = [bar(1, 100, 100.2, 99.8, 100), bar(2, 100, 104.0, 99.9, 103.0), bar(3, 103, 103, 97.0, 98)]
    rows = L.build_rows(side="long", entry=100.0, sl=98.0, bars=bars, entry_time=0.0, bar_seconds=H, max_fwd_bars=10)
    lab = rows[0]["labels"]                                              # decision at the close of bar 1
    assert abs(lab["fwd_mfe_r"] - 2.0) < 1e-9 and lab["reach_1"] == 1 and lab["reach_2"] == 1 and lab["reach_3"] == 0
    assert lab["stop_first"] == 0                                         # the +2R target came before the stop touch


def test_stop_first_when_stop_precedes_target_and_row_stops_at_the_stop():
    bars = [bar(1, 100, 100.2, 99.8, 100), bar(2, 100, 100.5, 97.5, 98), bar(3, 98, 110, 98, 109)]
    rows = L.build_rows(side="long", entry=100.0, sl=98.0, bars=bars, entry_time=0.0, bar_seconds=H, max_fwd_bars=10)
    assert len(rows) == 1                                                 # bar 2 stops the trade: no decision row at or after it
    lab = rows[0]["labels"]
    assert lab["stop_first"] == 1 and lab["reach_2"] == 0                 # the later +10 never counts once the stop is touched


def test_short_side_mirrors_long():
    bars = [bar(1, 100, 100.2, 99.8, 100), bar(2, 100, 100.1, 96.0, 97.0)]
    rows = L.build_rows(side="short", entry=100.0, sl=102.0, bars=bars, entry_time=0.0, bar_seconds=H, max_fwd_bars=10)
    assert abs(rows[0]["labels"]["fwd_mfe_r"] - 2.0) < 1e-9 and rows[0]["labels"]["reach_2"] == 1


def test_dip_that_recovers():
    # R0 = 2, close of bar 1 at 101 (+0.5R). bar2 dips to 99.0 (1.0R below the bar-1 close >= half the 1.5R distance to the stop at 98), bar3 recovers to 106
    bars = [bar(1, 100, 101.2, 100.9, 101), bar(2, 101, 101.1, 99.0, 100), bar(3, 100, 106.0, 100, 105)]
    lab = L.build_rows(side="long", entry=100.0, sl=98.0, bars=bars, entry_time=0.0, bar_seconds=H, max_fwd_bars=10)[0]["labels"]
    assert lab["dip_recovers"] == 1 and lab["stop_first"] == 0


def test_truncated_forward_window_is_censored_not_filled():
    rows = L.build_rows(side="long", entry=100.0, sl=98.0, bars=flat(4, start=1), entry_time=0.0, bar_seconds=H, max_fwd_bars=48)
    assert all(r["labels"]["censored"] for r in rows)
    c = L.census({"t": rows})
    assert c["n_rows"] == len(rows) and c["share_censored"] == 1.0 and c["share_stop_first_uncensored"] is None


def test_zero_risk_and_bad_side():
    assert L.build_rows(side="long", entry=100.0, sl=100.0, bars=flat(3, 1), entry_time=0.0, bar_seconds=H) == []
    try:
        L.build_rows(side="x", entry=1, sl=0, bars=[], entry_time=0, bar_seconds=H)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_exit_idx_ends_the_rows():
    rows = L.build_rows(side="long", entry=100.0, sl=98.0, bars=flat(10, 1), entry_time=0.0, bar_seconds=H, exit_idx=4)
    assert [r["k"] for r in rows] == [1, 2, 3]


# ---- the driver (cf_bar_labels_run): job -> rows, no network ------------------------------------------------------------------
def _driver():
    sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
    import cf_bar_labels_run as D
    return D


def _job(direction="long", entry_time="1970-01-01T00:00:00+00:00", exit_time="1970-01-01T05:00:00+00:00"):
    return {"entry": 100.0, "sl": 98.0, "direction": direction, "entry_time": entry_time, "exit_time": exit_time,
            "strategy": "s", "symbol": "BTCUSDT"}


def test_label_job_drops_signal_bar_and_ends_at_the_replayed_exit():
    D = _driver()
    bars = [bar(0, 100, 150, 50, 100)] + flat(8, start=1)                  # bar 0 = signal bar (1h tf), huge range
    rows = D.label_job(_job(), bars, "1h")
    assert rows and rows[0]["features"]["peak_r"] < 0.2                      # the 150 high is not read
    assert [r["k"] for r in rows][-1] < 5                                    # exit_time 05:00 -> exit bar index 4 (bars close 02:00..05:00)


def test_label_job_rejects_unusable_geometry():
    D = _driver()
    assert D.label_job({**_job(), "sl": None}, flat(5, 1), "1h") is None
    assert D.label_job(_job(direction="flat"), flat(5, 1), "1h") is None
    assert D.label_job({**_job(), "entry_time": None}, flat(5, 1), "1h") is None


def test_run_shard_writes_census_and_counts_non_crypto(tmp_path):
    D = _driver()
    jobs = {"k1": {**_job(), "_file": "f"}}
    shard = {"shard_id": "BTCUSDT_1h_x", "symbol": "BTCUSDT", "timeframe": "1h"}
    meta = D.run_shard(shard, {"BTCUSDT_1h_x": ["k1"]}, jobs, tmp_path, fetcher=lambda s, tf, a, b: [
        {"time": i * H, "open": 100, "high": 100.2, "low": 99.8, "close": 100, "volume": 1} for i in range(0, 12)])
    assert meta["state"] == "done" and meta["n_labelled_trades"] == 1 and meta["census"]["n_rows"] > 0
    assert D.reduce_census(tmp_path)["n_trades"] == 1
    eq = {"shard_id": "SPY_1h_y", "symbol": "SPY", "timeframe": "1h"}
    m2 = D.run_shard(eq, {"SPY_1h_y": ["k1"]}, {"k1": {**_job(), "symbol": "SPY", "_file": "f"}}, tmp_path)
    assert m2["could_not_label"] == {"no_bar_source": 1} and m2["n_labelled_trades"] == 0


# ---- AM-V2-RICHER-FEATURES: the ctx block ---------------------------------------------------------------------------------------------
def _walk(n=260, seed=3):
    import random
    rnd = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        o = p
        p = p * (1 + rnd.gauss(0, 0.01))
        out.append(bar(i, o, max(o, p) * 1.003, min(o, p) * 0.997, p))
    return out


def test_context_off_is_byte_identical_and_on_only_adds_ctx():
    bs = _walk()
    et, e = 150 * H, bs[150]["close"]
    plain = L.build_rows(side="long", entry=e, sl=e * 0.95, bars=bs, entry_time=et, bar_seconds=H)
    ctx = L.build_rows(side="long", entry=e, sl=e * 0.95, bars=bs, entry_time=et, bar_seconds=H, context=True)
    assert plain and [{k: v for k, v in r.items() if k != "ctx"} for r in ctx] == plain
    assert all(set(r["ctx"]) == set(L.CTX_KEYS) for r in ctx)
    assert all(r["ctx"][k] is not None for r in ctx for k in L.CTX_KEYS)          # 150 bars of history cover every window


def test_context_never_reads_a_future_bar():
    bs = _walk()
    et, e = 150 * H, bs[150]["close"]
    full = L.build_rows(side="short", entry=e, sl=e * 1.05, bars=bs, entry_time=et, bar_seconds=H, context=True, with_labels=False)
    for k in (1, 3, 7):
        cut = [b for b in bs if b["time"] < et + H * (k + 1)]                       # bars up to and including bar k
        part = L.build_rows(side="short", entry=e, sl=e * 1.05, bars=cut, entry_time=et, bar_seconds=H, context=True, with_labels=False)
        assert part[k - 1]["ctx"] == full[k - 1]["ctx"]


def test_context_signs_and_short_history():
    bs = _walk()
    et, e = 150 * H, bs[150]["close"]
    lg = L.build_rows(side="long", entry=e, sl=e * 0.95, bars=bs, entry_time=et, bar_seconds=H, context=True)
    sh = L.build_rows(side="short", entry=e, sl=e * 1.05, bars=bs, entry_time=et, bar_seconds=H, context=True)
    for a, b in zip(lg, sh):
        assert a["ctx"]["fav_ext_r"] >= 0 and a["ctx"]["adv_ext_r"] >= 0 and 0 <= a["ctx"]["range_pos"] <= 1
        assert abs(a["ctx"]["range_pos"] + b["ctx"]["range_pos"] - 1.0) < 1e-9       # mirrored range position
        assert abs(a["ctx"]["trend_atr"] + b["ctx"]["trend_atr"]) < 1e-9
    few = L.build_rows(side="long", entry=bs[10]["close"], sl=bs[10]["close"] * 0.95, bars=bs, entry_time=10 * H, bar_seconds=H, context=True)
    assert few[0]["ctx"]["atr_ratio"] is None and few[0]["ctx"]["fav_ext_r"] is None   # windows longer than the history: None, never filled


def test_driver_context_rows_match_plain_rows():
    D = _driver()
    bs = _walk()
    job = {"entry": bs[150]["close"], "sl": bs[150]["close"] * 0.95, "direction": "long", "entry_time": 150 * H, "exit_time": 180 * H,
           "strategy": "s", "symbol": "BTCUSDT"}
    plain = D.label_job(job, bs, "1h")
    ctx = D.label_job(job, bs, "1h", context=True)
    assert plain and [{k: v for k, v in r.items() if k != "ctx"} for r in ctx] == plain and "ctx" in ctx[0]

"""QUEUE-FILL-1013B -- scripts/research/macro_event_study_run.py: the registered rule, and an end-to-end run on fixtures."""
from __future__ import annotations

import json
import math

from scripts.research import macro_event_study_run as m


def _rows(n, t, ic):
    return [{"horizon_days": 1, "n": n, "ic": ic, "ic_t_eff": t}]


def test_pass_requires_n_t_and_sign():
    kw = dict(primary=[1], min_n=100, t_bar=2.4, expected_sign="negative")
    assert m.grade(_rows(200, -3.0, -0.2), **kw)["verdict"] == "pass"
    assert m.grade(_rows(200, 3.0, 0.2), **kw)["verdict"] == "fail"       # significant, WRONG sign: not a pass
    assert "WRONG-sign" in m.grade(_rows(200, 3.0, 0.2), **kw)["note"]
    assert m.grade(_rows(200, -1.0, -0.1), **kw)["verdict"] == "fail"
    assert m.grade(_rows(50, -3.0, -0.2), **kw)["verdict"] == "indeterminate"  # n bounded by the source
    assert m.grade([], **kw)["read_state"] == "no_data"


def test_end_to_end_on_fixtures(tmp_path):
    # planted negative relation: bigger surprise -> lower next-day return, 150 weekly releases
    import random
    rnd = random.Random(3)
    from datetime import date, timedelta
    d0 = date(2020, 1, 2)
    px, price = [], 100.0
    for i in range(1200):
        px.append((d0 + timedelta(days=i)).isoformat())
    closes = {}
    rel = []
    for k in range(150):
        day = d0 + timedelta(days=7 * k)
        s = rnd.gauss(0, 1)
        rel.append((day, s))
    # build closes: a flat random walk with a -0.01*surprise jump the day after each release
    jump = {(day + timedelta(days=1)).isoformat(): -0.01 * s for day, s in rel}
    for ds in px:
        price *= 1.0 + jump.get(ds, 0.0) + rnd.gauss(0, 0.0005)
        closes[ds] = price
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "NG=F.csv").write_text("date,close\n" + "\n".join(f"{k},{v}" for k, v in closes.items()))
    lines = [json.dumps({"kind": "eia_natgas_storage", "status": "resolved", "scheduled_for": day.isoformat(),
                         "observed_at": "2020-01-01T00:00:00Z",
                         "realized_outcome": {"surprise": s, "actual": 1.0, "consensus": 0.0, "change": 0.0}})
             for day, s in rel]
    (tmp_path / "snap.jsonl").write_text("\n".join(lines) + "\n")
    out = tmp_path / "out"
    assert m.main(["--kind", "eia_natgas_storage", "--snapshots", str(tmp_path / "snap.jsonl"),
                   "--candles-dir", str(tmp_path / "candles"), "--horizons", "1,3", "--primary-horizons", "1",
                   "--min-n", "100", "--t-bar", "2.4", "--expected-sign", "negative", "--out", str(out)]) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] == "pass", v
    assert v["n"] >= 100 and math.isfinite(v["measurement"]["per_horizon"][0]["ic_t_eff"])
    assert (out / "scorecard.json").exists()


def test_empty_panel_is_no_data_not_a_verdict(tmp_path):
    (tmp_path / "candles").mkdir()
    (tmp_path / "snap.jsonl").write_text("")
    out = tmp_path / "o"
    m.main(["--kind", "eia_natgas_storage", "--snapshots", str(tmp_path / "snap.jsonl"),
            "--candles-dir", str(tmp_path / "candles"), "--out", str(out)])
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "no_data" and v["verdict"] == "not_applicable"


# ── P4-MACRO-PROGRAMME confirmation arms (2026-10-14) ─────────────────────────
def test_filter_window_is_half_open():
    ev = [{"date": "2020-12-31"}, {"date": "2021-01-01"}, {"date": "2021-06-01"}]
    assert [e["date"] for e in m.filter_window(ev, "2021-01-01", None)] == ["2021-01-01", "2021-06-01"]
    assert [e["date"] for e in m.filter_window(ev, None, "2021-01-01")] == ["2020-12-31"]
    assert m.filter_window(ev, None, None) == ev


def test_shift_anchor_moves_by_trading_days_and_drops_out_of_panel():
    dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
    ev = [{"date": "2021-01-06", "surprise": 1.0}, {"date": "2021-01-04", "surprise": 2.0}]
    sh = m.shift_anchor(ev, dates, -2)
    assert [e["date"] for e in sh] == ["2021-01-04"]          # the 01-04 release falls off the panel: dropped
    assert sh[0]["placebo_original_date"] == "2021-01-06"
    assert m.shift_anchor(ev, dates, 0) == ev


def test_sign_book_charges_cost_and_compares_to_floor():
    ev = [{"date": f"d{i}", "surprise": (1.0 if i % 2 else -1.0)} for i in range(40)] + [{"date": "z", "surprise": 0.0}]
    # negative expected sign: positive surprise -> price falls 1%, negative -> rises 1%
    fwd = lambda d, h: (None if d == "z" else (-0.01 if int(d[1:]) % 2 else 0.01))  # noqa: E731
    sb = m.sign_book(ev, fwd, horizon=3, cost_frac=0.00125, expected_sign="negative")
    assert sb["book_net"]["n"] == 40                           # the zero-surprise release is not a trade
    assert abs(sb["book_net"]["mean"] - (0.01 - 0.00125)) < 1e-9
    assert abs(sb["floor_all_long_net"]["mean"] - (0.0 - 0.00125)) < 1e-9
    assert m.grade_trade(sb, min_n=30, t_bar=2.0)["verdict"] in ("pass", "fail")  # sd 0 -> t None -> fail
    assert m.grade_trade(sb, min_n=50, t_bar=2.0)["verdict"] == "indeterminate"


def test_grade_trade_rule():
    def sb(n, mean, t, fmean):
        return {"book_net": {"n": n, "mean": mean, "t": t}, "floor_all_long_net": {"n": n, "mean": fmean, "t": None}}
    assert m.grade_trade(sb(100, 0.002, 2.5, 0.001), min_n=60, t_bar=2.0)["verdict"] == "pass"
    assert m.grade_trade(sb(100, 0.002, 2.5, 0.003), min_n=60, t_bar=2.0)["verdict"] == "fail"   # loses to the floor
    assert m.grade_trade(sb(100, 0.002, 1.5, 0.0), min_n=60, t_bar=2.0)["verdict"] == "fail"
    assert m.grade_trade(sb(100, -0.001, 3.0, -0.002), min_n=60, t_bar=2.0)["verdict"] == "fail"
    assert m.grade_trade(sb(0, None, None, None), min_n=60, t_bar=2.0)["read_state"] == "no_data"


def test_cost_frac_for_mes_is_the_full_stack():
    c = m.cost_frac_for("MES")
    assert c["total_bps_roundtrip"] == c["fee_bps_roundtrip"] + c["slippage_bps_roundtrip"] > 0
    assert c["cost_frac"] == c["total_bps_roundtrip"] / 1e4 and c["funding_bps_per_window"] == 0.0


def test_end_to_end_trade_and_placebo_arms(tmp_path):
    import random
    from datetime import date, timedelta
    rnd = random.Random(5)
    d0 = date(2020, 1, 2)
    rel = [(d0 + timedelta(days=7 * k), rnd.gauss(0, 1)) for k in range(150)]
    jump = {(day + timedelta(days=1)).isoformat(): -0.01 * s for day, s in rel}
    price, closes = 100.0, {}
    for i in range(1200):
        ds = (d0 + timedelta(days=i)).isoformat()
        price *= 1.0 + jump.get(ds, 0.0) + rnd.gauss(0, 0.0005)
        closes[ds] = price
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "NG=F.csv").write_text("date,close\n" + "\n".join(f"{k},{v}" for k, v in closes.items()))
    (tmp_path / "snap.jsonl").write_text("\n".join(json.dumps(
        {"kind": "eia_natgas_storage", "status": "resolved", "scheduled_for": day.isoformat(),
         "observed_at": "2020-01-01T00:00:00Z",
         "realized_outcome": {"surprise": s, "actual": 1.0, "consensus": 0.0, "change": 0.0}}) for day, s in rel) + "\n")
    base = ["--kind", "eia_natgas_storage", "--snapshots", str(tmp_path / "snap.jsonl"), "--candles-dir",
            str(tmp_path / "candles"), "--horizons", "1", "--min-n", "60", "--t-bar", "2.4", "--expected-sign", "negative"]
    assert m.main(base + ["--trade-horizon", "1", "--cost-symbol", "MES", "--out", str(tmp_path / "t")]) == 0
    v = json.loads((tmp_path / "t" / "verdict.json").read_text())
    assert v["verdict"] == "pass" and v["measurement"]["sign_book"]["cost_stack"]["total_bps_roundtrip"] > 0, v
    assert m.main(base + ["--anchor-shift-td", "-10", "--out", str(tmp_path / "p")]) == 0
    p = json.loads((tmp_path / "p" / "verdict.json").read_text())
    assert p["verdict"] == "fail" and p["measurement"]["anchor_shift_td"] == -10, p   # the planted edge is post-release
    assert m.main(base + ["--release-start", "2021-06-01", "--out", str(tmp_path / "w")]) == 0
    w = json.loads((tmp_path / "w" / "verdict.json").read_text())
    assert w["measurement"]["releases_after_window"] < 150

"""PM-SURPRISE-JOIN — builder, exact-date join, paired IC comparison and the registered rule (fixtures only)."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "macro"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "research"))
import econ_event_study as ees  # noqa: E402
import pm_surprise as pms  # noqa: E402
import pm_surprise_eval as ev  # noqa: E402


def row(mkt, ev_t, close, end, bid, ask, floor=None, st="greater", exp=None):
    return {"market_id": mkt, "event_ticker": ev_t, "close_time": close, "candle_end_utc": end, "yes_bid_close": bid,
            "yes_ask_close": ask, "floor_strike": floor, "strike_type": st, "expiration_value": exp}


def test_usable_mid_rejects_empty_and_wide_books():
    assert pms.usable_mid(row("m", "e", "c", "t", 0.0, 1.0)) is None  # settled/empty book
    assert pms.usable_mid(row("m", "e", "c", "t", None, 0.5)) is None
    assert pms.usable_mid(row("m", "e", "c", "t", 0.5, 0.4)) is None  # crossed
    assert abs(pms.usable_mid(row("m", "e", "c", "t", 0.40, 0.44)) - 0.42) < 1e-12


def test_no_lookahead_and_last_usable_quote():
    close = "2026-09-11T12:25:00Z"
    rows = [row("m", "e", close, "2026-09-11T10:00:00Z", 0.40, 0.44, 0.3),
            row("m", "e", close, "2026-09-11T12:00:00Z", 0.0, 1.0, 0.3),   # unusable: skipped, falls back
            row("m", "e", close, "2026-09-11T13:00:00Z", 0.90, 0.92, 0.3)]  # after close: never read
    q = pms.last_quotes(rows, close)
    assert q["m"][0] == "2026-09-11T10:00:00Z" and abs(q["m"][1] - 0.42) < 1e-12


def test_ladder_expectation_point_mass_and_monotone_clamp():
    # all mass between 0.2 and 0.3 on a 0.1 grid -> value 0.3
    r = pms.ladder_expectation([(0.0, 1.0), (0.1, 1.0), (0.2, 1.0), (0.3, 0.0), (0.4, 0.0)], tick=0.1)
    assert abs(r["expected"] - 0.3) < 1e-9
    # non-monotone noise is clamped by running min
    r2 = pms.ladder_expectation([(0.0, 0.9), (0.1, 0.95), (0.2, 0.5)], tick=0.0)
    r3 = pms.ladder_expectation([(0.0, 0.9), (0.1, 0.9), (0.2, 0.5)], tick=0.0)
    assert abs(r2["expected"] - r3["expected"]) < 1e-12
    assert pms.ladder_expectation([(0.0, 0.5), (0.1, 0.4)]) is None  # too thin


def test_ladder_expectation_shifts_with_probability():
    lo = pms.ladder_expectation([(0.0, 0.9), (0.1, 0.5), (0.2, 0.1)])["expected"]
    hi = pms.ladder_expectation([(0.0, 0.95), (0.1, 0.8), (0.2, 0.5)])["expected"]
    assert hi > lo


def test_fomc_delta_and_expectation():
    assert pms.fomc_delta_bps("KXFEDDECISION-26SEP-H0") == 0.0
    assert pms.fomc_delta_bps("KXFEDDECISION-26SEP-C25") == -25.0
    assert pms.fomc_delta_bps("KXFEDDECISION-26SEP-H25") == 25.0
    assert pms.fomc_delta_bps("KXFEDDECISION-26SEP-C26") == -pms.FOMC_BEYOND_25_BPS
    assert pms.fomc_delta_bps("FEDDECISION-23MAY-TC25") is None
    q = {m: ("t", p, {}) for m, p in {"X-H0": 0.6, "X-C25": 0.3, "X-H25": 0.1}.items()}
    assert abs(pms.fomc_expected_bps(q)["expected"] - (-7.5 + 2.5)) < 1e-9
    assert pms.fomc_expected_bps({m: ("t", 0.1, {}) for m in ("X-H0", "X-C25", "X-H25")}) is None  # mass 0.3


def test_parse_expiration_value_units():
    assert pms.parse_expiration_value("KXCPI", "0.4") == 0.4
    assert abs(pms.parse_expiration_value("KXPAYROLLS", "29,000") - 29.0) < 1e-9
    assert pms.parse_expiration_value("KXFEDDECISION", "Hike 25bps") == 25.0
    assert pms.parse_expiration_value("KXFEDDECISION", "Cut 50bps") == -50.0


def cpi_event(tag, date, probs, bid_pad=0.01, end="10:00:00"):
    close = f"{date}T12:25:00Z"
    return [row(f"KXCPI-{tag}-T{k}", f"KXCPI-{tag}", close, f"{date}T{end}Z", max(0.0, p - bid_pad), min(1.0, p + bid_pad),
                k, exp="0.3") for k, p in probs]


def test_build_series_and_exact_date_join_and_staleness():
    rows = cpi_event("26JUN", "2026-07-14", [(0.0, 0.95), (0.1, 0.8), (0.2, 0.5), (0.3, 0.2), (0.4, 0.05)])
    rows += cpi_event("26JUL", "2026-08-12", [(0.0, 0.9), (0.1, 0.7), (0.2, 0.4)], end="03:00:00")  # 9h stale
    rows += [row("KXCPI-26MAY-T0.1", "KXCPI-26MAY", "2026-06-10T12:25:00Z", "2026-06-10T11:00:00Z", 0.0, 1.0, 0.1)]
    recs = pms.build_series("KXCPI", rows)
    by = {r["event_ticker"]: r for r in recs}
    assert by["KXCPI-26MAY"]["skipped"] and by["KXCPI-26MAY"]["reason"] == "no_usable_two_sided_quote"
    assert abs(by["KXCPI-26JUN"]["stale_hours"] - 2.4166667) < 1e-3
    cal = {"cpi_mom": [{"date": "2026-07-14", "actual": 0.4, "consensus": 0.2, "change": 0.1},
                       {"date": "2026-08-13", "actual": 0.3, "consensus": 0.3, "change": 0.0}]}  # 08-13 != 08-12
    paired, d = pms.join_pm_to_calendar(recs, cal)
    assert len(paired) == 1 and d["off_by_one_day_only"] == 1 and d["skipped_no_pm"] == 1
    p = paired[0]
    assert abs(p["pm_surprise"] - (0.4 - p["pm_expected"])) < 1e-12 and abs(p["surprise"] - 0.2) < 1e-12
    _, d6 = pms.join_pm_to_calendar(recs, cal, max_stale_hours=1.0)
    assert d6["stale_dropped"] == 2 and d6["paired"] == 0


def synthetic(n=80, pm_informative=True, seed=3):
    rng = random.Random(seed)
    import datetime as dt
    d0 = dt.date(2024, 1, 2)
    panel, px = [], 100.0
    for i in range(400):
        px *= 1 + rng.gauss(0, 0.01)
        panel.append(((d0 + dt.timedelta(days=i)).isoformat(), px))
    return rng, d0, panel


def test_paired_ic_comparison_detects_better_expectation_and_halves():
    import datetime as dt
    rng, d0, panel = synthetic()
    # make forward returns depend on the PM surprise, not on the consensus surprise
    events = []
    for i in range(0, 300, 3):
        date = (d0 + dt.timedelta(days=i)).isoformat()
        pm = rng.gauss(0, 1)
        events.append({"date": date, "kind": "k", "pm_surprise": pm, "surprise": rng.gauss(0, 1)})
        # shape the price path after the release so fwd(5) tracks pm
        for j in range(i, min(i + 8, 399)):
            panel[j + 1] = (panel[j + 1][0], panel[j][1] * (1 + 0.004 * pm + rng.gauss(0, 0.002)))
    rows = ees.paired_ic_comparison(events, panel, horizons=[1, 3, 5], n_boot=300, group_key="kind")
    r5 = next(r for r in rows if r["horizon_days"] == 5)
    assert r5["n_paired"] > 40 and r5["diff"] > 0 and r5["boot_lo"] > 0
    assert len(r5["half_diffs"]) == 2 and all(h > 0 for h in r5["half_diffs"])
    again = ees.paired_ic_comparison(events, panel, horizons=[5], n_boot=300, group_key="kind")[0]
    assert again["boot_lo"] == r5["boot_lo"]  # seeded: deterministic


def test_censored_and_missing_dropped_not_zero_filled():
    panel = [(f"2024-01-{d:02d}", 100.0 + d) for d in range(1, 11)]
    events = [{"date": "2024-01-03", "pm_surprise": 1.0, "surprise": 2.0},
              {"date": "2024-01-04", "pm_surprise": None, "surprise": 1.0},
              {"date": "2024-01-09", "pm_surprise": 1.0, "surprise": 1.0}]  # no forward bar 5 days out
    r = ees.paired_ic_comparison(events, panel, horizons=[5], n_boot=10)[0]
    assert r["n_paired"] == 1 and r["diff"] is None


def mk(h, n, diff, lo, hi, halves):
    return {"horizon_days": h, "n_paired": n, "diff": diff, "boot_lo": lo, "boot_hi": hi, "half_diffs": halves}


def test_grade_is_the_registered_rule():
    def ok():
        return [mk(3, 60, 0.2, 0.05, 0.4, [0.1, 0.3]), mk(5, 58, 0.25, 0.02, 0.5, [0.2, 0.3])]

    g = ev.grade(ok())
    assert g["verdict"] == "pass" and g["n"] == 58
    under = ev.grade([mk(3, 48, 0.9, 0.5, 1.0, [1, 1]), mk(5, 60, 0.9, 0.5, 1.0, [1, 1])])
    assert under["verdict"] == "indeterminate" and "UNDERPOWERED" in under["note"]  # never pass below 49
    spans = ok()
    spans[1] = mk(5, 58, 0.25, -0.1, 0.5, [0.2, 0.3])
    assert ev.grade(spans)["verdict"] == "fail"
    neg = ok()
    neg[0] = mk(3, 60, -0.01, -0.2, 0.1, [0.1, 0.3])
    assert ev.grade(neg)["verdict"] == "fail"
    gap = ok()
    gap[1] = mk(5, 58, 0.25, 0.02, 0.5, [0.2, -0.3])
    g2 = ev.grade(gap)
    assert g2["verdict"] == "indeterminate" and "RULE SILENT" in g2["note"]


def test_attach_pm_surprise_exact_date_only():
    evs = [{"date": "2026-07-14", "surprise": 0.1}, {"date": "2026-08-12", "surprise": 0.0}]
    out = ees.attach_pm_surprise(evs, [{"kind": "cpi_mom", "date": "2026-07-14", "pm_surprise": 0.25}], "cpi_mom")
    assert out[0]["pm_surprise"] == 0.25 and out[1]["pm_surprise"] is None


def test_end_to_end_on_fixture_files(tmp_path):
    import datetime as dt
    bdir = tmp_path / "kalshi"
    bdir.mkdir()
    cal = tmp_path / "cal.jsonl"
    rng = random.Random(9)
    rows, calrows = [], []
    d0 = dt.date(2024, 1, 10)
    for i in range(6):
        date = (d0 + dt.timedelta(days=30 * i)).isoformat()
        probs = [(0.0, 0.95), (0.1, 0.8), (0.2, 0.5), (0.3, 0.2), (0.4, 0.05)]
        rows += cpi_event(f"E{i}", date, probs)
        calrows.append({"kind": "cpi_mom", "status": "resolved", "scheduled_for": date, "observed_at": "2026-01-01T00:00:00Z",
                        "realized_outcome": {"actual": 0.2 + 0.1 * rng.randint(0, 2), "consensus": 0.2, "surprise": 0.0,
                                             "change": 0.0}})
    (bdir / "KXCPI.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    cal.write_text("\n".join(json.dumps(r) for r in calrows))
    panel = [((d0 + dt.timedelta(days=i)).isoformat(), 100 + i * 0.1) for i in range(400)]
    res = ev.run(bdir, [str(cal)], panel, [3, 5], n_boot=50)
    assert res["join_graded"]["paired"] == 6 and res["series"]["KXCPI"]["events"] == 6
    assert ev.grade(res["pooled"])["verdict"] == "indeterminate"  # n=6 < 49: UNDERPOWERED

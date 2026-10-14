"""NEWS-HIST-REPLAY: point-in-time (leakage) tests for the historical news replay harness.

The load-bearing fixture is `test_item_published_one_second_after_signal_is_excluded`: an item that
becomes available 1s AFTER the signal must not influence it, even if it would otherwise be a veto.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import news_hist_fetch as fetch  # noqa: E402
import news_hist_replay as rp  # noqa: E402
from src.news import news_normalizer as nn  # noqa: E402

T = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
# crypto-desk headline: strongly negative + high-impact patterns -> trips the live veto for BTC.
BAD = "Bitcoin crash: SEC lawsuit, exchange hack and liquidation panic as bankruptcy fear spreads"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _item(avail, title=BAD, pub=None, domain="coindesk.com"):
    return {"title": title, "description": "", "url": "https://x/" + _iso(avail), "publishedAt": _iso(pub or avail),
            "source": {"name": domain}, "available_at": _iso(avail), "pub_basis": "ingest"}


def _decide(items, t=T, symbol="BTCUSDT", side="buy"):
    return rp.decide(rp.Corpus(items), symbol, side, t)


def test_fixture_headline_vetoes_when_visible():
    d = _decide([_item(T - timedelta(minutes=5))])
    assert d["veto"] is True and d["decision"] == "veto", d


def test_item_published_one_second_after_signal_is_excluded():
    d = _decide([_item(T + timedelta(seconds=1), pub=T - timedelta(minutes=3))])
    assert d["n_visible"] == 0 and d["veto"] is False and d["decision"] == "neutral", d


def test_item_available_exactly_at_signal_time_is_excluded_strict():
    d = _decide([_item(T)])
    assert d["n_visible"] == 0 and d["veto"] is False, d


def test_item_one_second_before_signal_is_included():
    d = _decide([_item(T - timedelta(seconds=1))])
    assert d["n_visible"] == 1 and d["veto"] is True, d


def test_publication_before_signal_does_not_override_late_availability():
    # published 30 min before the signal but only ingested 1s after it: not knowable at T.
    d = _decide([_item(T + timedelta(seconds=1), pub=T - timedelta(minutes=30))])
    assert d["n_visible"] == 0 and d["veto"] is False


def test_stale_item_outside_max_age_is_dropped_by_live_scorer():
    d = _decide([_item(T - timedelta(minutes=200), pub=T - timedelta(minutes=200))])
    assert d["veto"] is False and d["item_count"] == 0


def test_domain_must_be_a_live_feed_for_the_symbol():
    # coindesk is a crypto-desk feed: it is NOT read by the live path for an index future
    assert "coindesk.com" in rp.feed_domains("BTCUSDT")
    assert "coindesk.com" not in rp.feed_domains("MES")
    d = _decide([_item(T - timedelta(minutes=5), domain="coindesk.com")], symbol="MES")
    assert d["n_visible"] == 0


def test_frozen_clock_is_used_and_restored():
    orig = nn._freshness_minutes
    with rp.frozen_clock(T):
        assert nn._freshness_minutes(_iso(T - timedelta(minutes=10))) == 10.0
        assert nn._freshness_minutes(_iso(T + timedelta(minutes=10))) == 0.0  # clamped, like live
    assert nn._freshness_minutes is orig


def test_decision_uses_signal_clock_not_wall_clock():
    # 2024 item vs a 2026 wall clock: live freshness would call it ancient (stale, dropped).
    d = _decide([_item(T - timedelta(minutes=5))])
    assert d["item_count"] == 1


def test_corpus_visible_window_is_strict_and_sorted():
    c = rp.Corpus([_item(T + timedelta(seconds=1)), _item(T - timedelta(seconds=1)), _item(T - timedelta(minutes=50))])
    got = [i["available_at"] for i in c.visible(T, 120)]
    assert got == sorted(got) and _iso(T + timedelta(seconds=1)) not in got and len(got) == 2


def test_net_r_recompute_matches_harness_row_cross_check():
    row = {"symbol": "BTCUSDT", "direction": "long", "entry": 50000.0, "sl": 49000.0, "gross_r": 1.5,
           "entry_time": "2024-03-01 00:00:00+00:00", "exit_time": "2024-03-01 20:00:00+00:00"}
    net, cost, diff = rp.net_r_for(row)
    assert diff is None and cost > 0 and net == pytest.approx(1.5 - cost)
    row["net_r"] = round(net, 4)
    assert rp.net_r_for(row)[2] < 1e-3


def test_spearman_known_values():
    rho, p = rp.spearman([1, 2, 3, 4, 5, 6], [2, 1, 4, 3, 6, 5])
    assert rho == pytest.approx(0.8286, abs=1e-3) and p < 0.05
    assert rp.spearman([1, 2], [1, 2]) == (None, None)


def test_summarize_veto_arm_and_gap_exclusion():
    rows = [{"strategy": "s", "symbol": "BTCUSDT", "side": "buy", "t": f"2024-03-0{i}T00:00:00+00:00",
             "net_r": r, "cost_r": 0.1, "window_gap": gap, "decision": dec, "adjustment": adj, "veto": dec == "veto",
             "item_count": 1, "n_visible": 1, "size_factor": 1.0, "alignment": adj}
            for i, (r, dec, adj, gap) in enumerate(
                [(-1.0, "veto", -0.5, False), (-1.0, "veto", -0.5, True), (1.0, "neutral", 0.0, False),
                 (2.0, "boost", 0.4, False), (-0.5, "reduce", -0.2, False)], start=1)]
    s = rp.summarize({"rows": rows, "cost_xcheck_max_abs_diff": None, "cost_xcheck_n": 0})
    assert s["population"]["n_excluded_window_gap"] == 1 and s["population"]["n_trades_in"] == 5
    assert s["veto"]["n_vetoed"] == 1 and s["veto"]["mean_net_r_vetoed"] == -1.0
    assert s["veto"]["mean_diff_vetoed_minus_taken"] == pytest.approx(-1.0 - (1.0 + 2.0 - 0.5) / 3, abs=1e-3)


# ── fetch side ──────────────────────────────────────────────────────────────
def _gkg_line(date, domain, url, title, precise=None):
    extras = "<PAGE_LINKS>a</PAGE_LINKS>"
    if precise:
        extras += f"<PAGE_PRECISEPUBTIMESTAMP>{precise}</PAGE_PRECISEPUBTIMESTAMP>"
    extras += f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    cols = [f"{date}-1", date, "1", domain, url] + [""] * 21 + [extras]
    assert len(cols) == 27
    return "\t".join(cols)


def test_parse_gkg_precise_pub_clamped_and_ingest_is_availability():
    kws = ["bitcoin"]
    lines = [
        _gkg_line("20240301120000", "coindesk.com", "u1", "Bitcoin up", precise="20240301113000"),
        _gkg_line("20240301120000", "coindesk.com", "u2", "Bitcoin future-dated", precise="20240301130000"),  # > ingest
        _gkg_line("20240301120000", "coindesk.com", "u3", "Weather today"),                                    # no keyword
        _gkg_line("20240301120000", "randomblog.com", "u4", "Bitcoin up"),                                     # not a live feed
    ]
    out = list(fetch.parse_gkg_rows(lines, domains={"coindesk.com"}, keywords=kws))
    assert [o["url"] for o in out] == ["u1", "u2"]
    assert out[0]["publishedAt"] == "2024-03-01T11:30:00Z" and out[0]["available_at"] == "2024-03-01T12:00:00Z"
    assert out[1]["publishedAt"] == out[1]["available_at"] == "2024-03-01T12:00:00Z"  # clamped, never in the future
    assert all(o["publishedAt"] <= o["available_at"] for o in out)


def test_files_for_signals_never_include_a_file_at_or_after_signal_time():
    files = fetch.files_for_signals([T], 120.0, 15.0)
    assert files and max(files) < T and min(files) >= T - timedelta(minutes=135 + 15)
    t2 = T + timedelta(minutes=7)
    assert max(fetch.files_for_signals([t2], 120.0, 15.0)) <= t2


def test_relevance_keyword_prefilter_is_superset_of_live_relevance():
    kws = fetch.relevance_keywords()
    for title in ["Bitcoin ETF approved", "Fed holds rates", "Gold rallies as dollar slips", "S&P 500 record high"]:
        rel, _ = nn._relevance_breakdown(title, ["BTC", "MES", "MGC"])
        assert (rel > 0) == any(k in title.lower() for k in kws) or rel == 0


# ── arm E (event study) + the registered grading rule ────────────────────────
def _candles(n=200, start=T - timedelta(hours=100), flat=100.0, step=0.0):
    import pandas as pd
    return pd.DataFrame({"timestamp": [start + timedelta(hours=i) for i in range(n)],
                         "close": [flat + step * i for i in range(n)]})


def test_event_study_veto_episode_anchored_and_forward_return_uses_future_only():
    # one veto item becomes visible at T-30m -> veto state for decision bars closing in (T-30m, T-30m+~2h)
    c = rp.Corpus([_item(T - timedelta(minutes=30))])
    df = _candles(step=1.0)  # strictly rising: forward return positive
    r = rp.event_study(c, df, "BTCUSDT", bar_minutes=60, horizon_bars=6)
    assert r["n_veto_episodes"] == 1 and r["n_veto_bars"] >= 1
    assert r["veto_long"]["mean_net_bps"] > -r["cost_bps_roundtrip"]  # rising prices: gross return > 0
    assert r["veto_short"]["mean_net_bps"] < 0


def test_event_study_item_after_decision_bar_creates_no_veto():
    c = rp.Corpus([_item(T + timedelta(seconds=1))])
    r = rp.event_study(c, _candles(), "BTCUSDT", bar_minutes=60, horizon_bars=6,
                       start=T - timedelta(hours=3), end=T)  # decisions closing at or before T only
    assert r["n_veto_bars"] == 0


def test_event_study_gap_windows_are_excluded_not_counted_as_no_news():
    r = rp.event_study(rp.Corpus([]), _candles(), "BTCUSDT", bar_minutes=60, horizon_bars=6, ok_files=set())
    assert r["n_decision_bars"] == 0


def _pooled(n=30, diff=-50.0, ci=(-80.0, -20.0), vmean=-60.0, base=10.0, halves=((15, -60.0), (15, -60.0)),
            n_scored=300, ic=0.1, p=0.001, sym_ic=(0.1, 0.1, -0.05)):
    return {"n_veto_episodes": n, "n_baseline_obs": 1000,
            "veto_long": {"mean_net_bps": vmean, "baseline_mean_net_bps": base, "diff_bps": diff, "boot95_ci_diff": list(ci),
                          "date_split_halves": [{"n": a, "mean_long_net_bps": b} for a, b in halves]},
            "rank": {"n_scored": n_scored, "spearman_ic": ic, "one_sided_p": p,
                     "per_symbol_ic": {f"S{i}": v for i, v in enumerate(sym_ic)}}}


def test_grading_rule_registered_branches():
    g = rp.grade_event_arm
    assert g(_pooled())["g1_offline"] == "PASS"
    assert g(_pooled(n=24))["arm_e"] == "INSUFFICIENT_BASE" and g(_pooled(n=24))["g1_offline"] == "OPEN"
    assert g(_pooled(diff=5.0, ci=(-10.0, 20.0)))["arm_e"] == "FAIL"
    assert g(_pooled(diff=5.0, ci=(-10.0, 20.0)))["g1_offline"] == "RETIRE_OR_REPLACE_REVIEW"
    assert g(_pooled(ci=(-80.0, 5.0)))["arm_e"] == "INCONCLUSIVE"              # CI straddles 0
    assert g(_pooled(vmean=+5.0))["arm_e"] == "INCONCLUSIVE"                   # veto episodes not net-negative
    assert g(_pooled(halves=((15, -60.0), (15, 40.0))))["arm_e"] == "INCONCLUSIVE"  # a half disagrees
    assert g(_pooled(halves=((4, -60.0), (26, -60.0))))["arm_e"] == "INCONCLUSIVE"  # half not evaluable (n<5)
    assert g(_pooled(n_scored=199))["arm_r"] == "INSUFFICIENT_BASE"
    assert g(_pooled(ic=-0.01))["arm_r"] == "FAIL" and g(_pooled(ic=-0.01))["g1_offline"] == "RETIRE_OR_REPLACE_REVIEW"
    assert g(_pooled(p=0.02))["arm_r"] == "INCONCLUSIVE"                       # p >= 0.01
    assert g(_pooled(sym_ic=(0.1, -0.1, -0.05)))["arm_r"] == "INCONCLUSIVE"    # <2 symbols positive
    assert g(_pooled(n_scored=10))["g1_offline"] == "PASS"                     # E pass, R insufficient is not a FAIL


def test_broad_population_widens_domains_but_keeps_point_in_time():
    mes_item = _item(T - timedelta(minutes=5), domain="coindesk.com")
    assert _decide([mes_item], symbol="MES")["n_visible"] == 0  # live: coindesk is not an index-future feed
    c = rp.Corpus([mes_item, _item(T + timedelta(seconds=1), domain="coindesk.com")])
    d = rp.decide(c, "MES", "buy", T, domains={"coindesk.com"})
    assert d["n_visible"] == 1  # broad: domain admitted, the future item still excluded


def test_broad_domains_exclude_aggregators_and_include_live_feeds():
    assert "biztoc.com" not in fetch.BROAD_DOMAINS and "wkrb13.com" not in fetch.BROAD_DOMAINS
    assert fetch.feed_domain_allowlist() <= (fetch.BROAD_DOMAINS | fetch.feed_domain_allowlist())


def test_archive_row_schema_and_leakage_guarantee():
    cols = [""] * 27
    cols[0], cols[1], cols[3], cols[4] = "x-1", "20240301120000", "Reuters.com", "https://r/u"
    cols[7] = "ECON_INFLATION,12;TAX_FNCACT,5;ECON_INFLATION,99"
    cols[9] = "1#United States#US#US#38#-97#US#1;1#Germany#GM#GM#51#9#GM#2"
    cols[11], cols[13] = "jerome powell", "federal reserve;sec"
    cols[15] = "-2.5,1.0,3.5,4.5,20.1,2.0,300"
    cols[26] = ("<PAGE_PRECISEPUBTIMESTAMP>20240301130000</PAGE_PRECISEPUBTIMESTAMP>"  # future-dated vs ingest
                "<PAGE_TITLE>Fed   holds</PAGE_TITLE>")
    [r] = list(fetch.archive_rows(["\t".join(cols) + "\n"]))
    assert r["a"] == "2024-03-01T12:00:00Z" and r["p"] == r["a"] and r["pb"] == "i"   # p never later than a
    assert r["d"] == "reuters.com" and len(r["u"]) == 16 and r["ti"] == "Fed holds"
    assert r["th"] == ["ECON_INFLATION", "TAX_FNCACT"] and r["pe"] == ["jerome powell"] and r["or"] == ["federal reserve", "sec"]
    assert r["cc"] == ["GM", "US"] and r["tone"][:3] == [-2.5, 1.0, 3.5] and len(r["tone"]) == 7
    assert list(fetch.archive_rows(["short\trow\n"])) == []

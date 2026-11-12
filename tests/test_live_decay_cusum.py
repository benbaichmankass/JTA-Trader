"""LIVE-DECAY-MONITOR: the CUSUM's declared false-alarm rate, its power, the grading, and the template's expansion."""
from __future__ import annotations

import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops")]
from scripts.research import live_decay_cusum as d  # noqa: E402
from scripts.research import queue_replenish as q  # noqa: E402

# a skewed, fat-tailed Stage-0 series: stop-outs at -1R and occasional big winners (positive expectancy)
XS0 = [-1.0] * 60 + [0.4] * 15 + [2.5] * 20 + [5.0] * 5


def test_cusum_path_resets_at_zero_and_accumulates_shortfall():
    assert d.cusum_path([-1, -1, 1, 1, 1], k=0.25) == [0.0, 0.0, 0.75, 1.5, 2.25]


def test_false_alarm_rate_is_the_declared_one_on_held_out_healthy_series():
    h = d.calibrate_h(XS0, 1, sims=3000)
    rng = random.Random(7)             # a different seed than the calibration's
    trips = sum(
        1 for _ in range(1000)
        if d.grade_series(XS0, [rng.choice(XS0) for _ in range(d.HORIZON)], 1, h=h)["verdict"] == "fail")
    rate = trips / 1000
    assert 0.02 <= rate <= 0.08, rate   # declared 0.05 over 100 trades


def test_a_decayed_leg_trips_and_a_flat_loser_streak_is_indeterminate_when_short():
    mu, _ = d.moments(XS0)
    decayed = [-1.0] * 30                           # pure stop-outs vs a positive Stage-0 mean
    out = d.grade_series(XS0, decayed, 1)
    assert out["verdict"] == "fail" and out["first_trip_trade"] <= 30 and out["mu0"] == round(mu, 4)
    assert d.grade_series(XS0, [-1.0, -1.0], 1)["verdict"] == "indeterminate"
    assert d.grade_series(XS0, [], 1)["verdict"] == "not_applicable"


def test_a_series_at_the_stage0_mean_passes():
    assert d.grade_series(XS0, [d.moments(XS0)[0]] * 40, 1)["verdict"] == "pass"


def test_block_resolution_standardises_by_block_size():
    out = d.grade_series(XS0, [-20.0, -20.0], 20)
    assert out["verdict"] == "fail" and out["block"] == 20 and out["n_trades"] == 40
    assert d.grade_series(XS0, [-20.0], 20)["verdict"] == "indeterminate"


def test_live_observations_reads_the_per_trade_series_and_counts_no_r_basis_never_zero():
    recent = {"realMoney": {"perStrategy": {"leg": {"journalTrust": {"accountsKnownDivergent": ["bybit_2"]},
                                                    "series": [{"r": -1.0}, {"r": None}, {"r": 0.5}]}}}}
    lo = d.live_observations(recent, "leg")
    assert lo["obs"] == [-1.0, 0.5] and lo["b"] == 1 and lo["n_no_r_basis"] == 1 and lo["divergent"] == ["bybit_2"]


def test_live_observations_block_payload_oldest_first_and_no_complete_block_is_not_a_series():
    blk = lambda r: {"perStrategy": [{"name": "leg", "totalR": r, "rTradeCount": 20}]}  # noqa: E731
    recent = {"block": 20, "realMoney": {"perStrategy": {"leg": {"last": {}, "blocks": [blk(-3.0), blk(2.0)]}}}}
    assert d.live_observations(recent, "leg")["obs"] == [2.0, -3.0]
    thin = {"block": 20, "realMoney": {"perStrategy": {"leg": {"last": {"rTradeCount": 9}, "blocks": []}}}}
    lo = d.live_observations(thin, "leg")
    assert lo["obs"] == [] and lo["state"] == "no_complete_block" and lo["n_trades"] == 9


def test_coverage_lists_prop_legs_and_names_why_a_leg_is_not_monitorable():
    rows = {r["leg"]: r for r in d.coverage(REPO)}
    assert "prop" in rows["trend_donchian_eth_4h"]["classes"] and not rows["trend_donchian_eth_4h"]["monitorable"]
    assert rows["ml_entry"]["stage0_state"] == "no_series" and rows["ml_entry"]["stage0_why"]
    assert all(r["stage0_n"] > 0 for r in rows.values() if r["monitorable"])


def test_the_template_expands_over_monitorable_legs_only_and_renders():
    facts = q.repo_facts(REPO)
    T = {t["family"]: (p, s, t) for p, s, t in q.load_templates(REPO)}
    path, sha, tpl = T["live-decay"]
    pts = q.expand(tpl, facts)
    mon = {r["leg"] for r in d.coverage(REPO) if r["monitorable"]} & set(facts["legs"])
    assert {p["leg"] for p in pts} == mon and pts
    text = q.render(tpl, path, sha, pts[0], "RQ-20261112-0001", "2026-11-12")
    assert "live_decay_cusum.py" in text and "RULE-TPL-LIVE-DECAY-CUSUM" in text and "{leg}" not in text

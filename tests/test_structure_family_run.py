"""structure_family_run: a family unit expands its legs at run time; uncovered harnesses are LISTED, never dropped; one leg's failure never halts the rest."""
from __future__ import annotations

import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import structure_family_run as F  # noqa: E402

STRAT = {"trend_donchian_eth": {"symbols": ["ETHUSDT"], "donchian": 20}, "trend_donchian_sol": {"symbols": ["SOLUSDT"]},
         "eth_pullback_2h": {"symbols": ["ETHUSDT"]}, "gld_pullback_1d": {"symbols": ["GLD"]}, "ict_scalp_5m": {"symbols": ["BTCUSDT"]},
         "turtle_soup": {"symbols": ["BTCUSDT"]}, "unrostered_trend_donchian_x": {"symbols": ["BTCUSDT"]}}
ACC = {"bybit_1": {"strategies": ["trend_donchian_eth", "trend_donchian_sol", "eth_pullback_2h", "ict_scalp_5m", "turtle_soup", "not_in_strategies"]},
       "alpaca_paper": {"strategies": ["gld_pullback_1d", "trend_donchian_eth"]}}
HARNESS = {"trend_donchian_eth": "trend", "trend_donchian_sol": "trend", "eth_pullback_2h": "pullback", "gld_pullback_1d": "pullback",
           "ict_scalp_5m": "ict_scalp", "turtle_soup": "turtle_soup"}


def _plan(family, accounts):
    return F.plan(family, accounts, STRAT, ACC, classify=lambda cfg: HARNESS[next(k for k, v in STRAT.items() if v is cfg)])


def test_the_leg_list_comes_from_the_rosters_and_strategies_not_from_a_quoted_list():
    assert F.expand("trend_donchian", ["bybit_1"], STRAT, ACC) == ["trend_donchian_eth", "trend_donchian_sol"]   # un-rostered and un-configured legs are not in
    assert F.expand("pullback", ["bybit_1", "alpaca_paper"], STRAT, ACC) == ["eth_pullback_2h", "gld_pullback_1d"]
    assert F.expand("trend_donchian", ["bybit_1", "alpaca_paper"], STRAT, ACC) == ["trend_donchian_eth", "trend_donchian_sol"]   # de-duplicated across accounts
    assert F.expand("remaining", ["bybit_1"], STRAT, ACC) == ["turtle_soup"]                                            # the other families are excluded


def test_a_harness_without_the_structure_arm_is_listed_not_dropped():
    p = _plan("ict_scalp", ["bybit_1"])
    assert p["covered"] == [] and p["not_covered"] == [{"leg": "ict_scalp_5m", "harness": "ict_scalp"}]
    p = _plan("remaining", ["bybit_1"])
    assert p["not_covered"] == [{"leg": "turtle_soup", "harness": "turtle_soup"}]
    p = _plan("trend_donchian", ["bybit_1"])
    assert [c["leg"] for c in p["covered"]] == ["trend_donchian_eth", "trend_donchian_sol"] and p["not_covered"] == []


def test_each_leg_gets_the_single_leg_unit_shape():
    argv = F.leg_argv("trend_donchian_eth", STRAT["trend_donchian_eth"], Path("/o"))
    assert argv[argv.index("--leg") + 1] == "trend_donchian_eth"
    assert [x for x in argv if x.startswith("S")] == ["S3=--structure-exit=pivot=3", "S5=--structure-exit=pivot=5", "S8=--structure-exit=pivot=8"]
    assert "--non-crypto-source" not in argv and argv[argv.index("--start") + 1] == "2020-07-01"
    eq = F.leg_argv("gld_pullback_1d", STRAT["gld_pullback_1d"], Path("/o"))
    assert eq[eq.index("--non-crypto-source") + 1] == "dukascopy" and eq[eq.index("--start") + 1] == "2021-07-01"


def test_roll_up_is_a_listing_roll_up():
    assert F.roll_up([]) == "not_applicable"
    assert F.roll_up([{"verdict": "fail"}, {"verdict": "pass"}]) == "pass"
    assert F.roll_up([{"verdict": "fail"}, {"verdict": "indeterminate"}]) == "indeterminate"
    assert F.roll_up([{"verdict": "fail"}, {"verdict": "fail"}]) == "fail"


def test_one_failing_leg_is_recorded_and_the_next_leg_still_runs(tmp_path, monkeypatch):
    calls = []

    def fake_run_leg(leg, cfg, out, timeout_s):
        calls.append(leg)
        if leg == "trend_donchian_eth":
            return {"leg": leg, "verdict": "not_applicable", "read_state": "producer_failed", "note": "boom"}
        return {"leg": leg, "verdict": "fail", "read_state": "measured", "n": 100}

    monkeypatch.setattr(F, "run_leg", fake_run_leg)
    monkeypatch.setattr(F, "harness_of", lambda cfg: "trend")
    monkeypatch.setattr(F, "plan", lambda *a, **k: {"family": "trend_donchian", "accounts": ["bybit_1"], "legs": ["trend_donchian_eth", "trend_donchian_sol"],
                                                    "covered": [{"leg": "trend_donchian_eth", "harness": "trend"}, {"leg": "trend_donchian_sol", "harness": "trend"}],
                                                    "not_covered": [{"leg": "x", "harness": "fade"}]})
    assert F.main(["--family", "trend_donchian", "--out", str(tmp_path)]) == 0
    top = json.loads((tmp_path / "verdict.json").read_text())
    assert calls == ["trend_donchian_eth", "trend_donchian_sol"]                    # the failure did not stop the loop
    assert top["verdict"] == "indeterminate" and top["n"] == 1 and len(top["records"]) == 2
    assert top["not_covered"] == [{"leg": "x", "harness": "fade"}]                  # listed in the landed record
    assert "2 covered" in top["population"] and "1 not covered" in top["population"]


def test_the_real_configs_expand_to_a_nonempty_trend_family():
    import yaml
    st = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    ac = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())
    legs = F.expand("trend_donchian", ["bybit_1"], st.get("strategies", st), ac.get("accounts", ac))
    assert legs and all(x.startswith("trend_donchian") for x in legs)

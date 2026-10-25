"""EXIT-BUILDS-W43: the four research-harness builds behind the six blocked eba2 units.

GIVEBACK-FRAC-FLAG (eba2-05/-06), LEVEL-TRAIL-R-GATE (eba2-11), HARNESS-METRIC-TRIGGER (eba2-07/-08),
PATHMETRIC-VOLCTL (eba2-04). Every flag is default-off and byte-identical; each has a planted case.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
from src.research import metric_trigger as mt  # noqa: E402
from src.research import trail_levers as tl  # noqa: E402


# ── GIVEBACK-FRAC-FLAG: the rule ────────────────────────────────────────────
def test_fractional_giveback_exits_at_the_fraction_of_a_planted_peak_then_fade():
    path = [1.0, 2.0, 3.0, 4.0, 3.9, 3.0, 2.5, 2.3, 1.0]
    peak, fired_at = 0.0, None
    for i, o in enumerate(path):
        peak = max(peak, o)
        if tl.giveback_fires(peak, o, 2.0, 1.0, 0.6):
            fired_at = i
            break
    assert fired_at == 7                      # 2.3 <= 0.6 x 4.0; the 3.0 bar (1 R down) did NOT fire
    assert tl.giveback_fires(4.0, 3.0, 2.0, 1.0, 0.0)          # the absolute rule would have
    assert not tl.giveback_fires(4.0, 3.0, 2.0, 1.0, 0.6)      # frac replaces giveback_r, it does not add


def test_giveback_unarmed_below_the_arming_peak_and_off_by_default():
    assert not tl.giveback_fires(1.9, 0.0, 2.0, 1.0, 0.6)
    assert not tl.giveback_fires(5.0, -5.0, 0.0, 1.0, 0.6)     # min_mfe 0 = lever off
    assert tl.giveback_fires(2.0, 1.0, 1.0, 1.0, 0.0) and not tl.giveback_fires(2.0, 1.1, 1.0, 1.0, 0.0)


def test_giveback_frac_refusals():
    assert tl.giveback_flag_errors(2.0, 0.6) == [] and tl.giveback_flag_errors(0.0, 0.0) == []
    assert tl.giveback_flag_errors(0.0, 0.6) and tl.giveback_flag_errors(2.0, 1.0) and tl.giveback_flag_errors(2.0, -0.1)


# ── LEVEL-TRAIL-R-GATE: the rule ────────────────────────────────────────────
def test_level_r_gate_open():
    assert tl.level_r_gate_open(0.0, 0.0) and tl.level_r_gate_open(0.0, -3.0)
    assert not tl.level_r_gate_open(1.5, 1.49) and tl.level_r_gate_open(1.5, 1.5)
    assert tl.level_flag_errors("swing", 4.0, 6.0, 60, 3, 0.0, 1.5) == []
    assert tl.level_flag_errors("", 0.0, 6.0, 60, 3, 0.0, 1.5)       # a gate on no level is inert
    assert tl.level_flag_errors("swing", 4.0, 6.0, 60, 3, 0.0, -1.0)


# ── HARNESS-METRIC-TRIGGER: file + refusals ─────────────────────────────────
def test_trigger_file_contract(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("")
    assert mt.load_triggers(str(f)) == {}                              # empty is valid: nothing flagged
    f.write_text('{"trade_key":"a","k":6,"trigger":true,"p":0.7}\n{"trade_key":"b","k":6,"trigger":false,"p":0.2}\n')
    assert mt.load_triggers(str(f)) == {"a": 6}
    with pytest.raises(FileNotFoundError):
        mt.load_triggers(str(tmp_path / "missing.jsonl"))
    f.write_text('{"trade_key":"a","trigger":true}\n')
    with pytest.raises(ValueError):
        mt.load_triggers(str(f))


def test_trigger_flag_refusals(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("")
    ok = dict(bank_frac=0.5, bank_at_r=1.0, trail_mult=5.0, trail_decay_tight_mult=0.0, trail_decay_arm_r=0.0,
              trail_decay_stall_bars=0)
    assert mt.trigger_flag_errors("", "", 0, **ok) == []
    assert mt.trigger_flag_errors("bank", str(f), 0, **ok) == []
    assert mt.trigger_flag_errors("bank", "", 6, **ok) == []
    assert mt.trigger_flag_errors("bank", "", 0, **ok)                                 # no source
    assert mt.trigger_flag_errors("", "", 6, **ok)                                     # no action
    assert mt.trigger_flag_errors("bank", str(f), 6, **ok)                             # both sources
    assert mt.trigger_flag_errors("bank", str(tmp_path / "nope"), 0, **ok)             # missing file
    assert mt.trigger_flag_errors("bank", "", 6, **{**ok, "bank_frac": 0.0})           # nothing to bank
    assert mt.trigger_flag_errors("tight", "", 6, **ok)                                # no tight mult
    assert mt.trigger_flag_errors("tight", "", 6, **{**ok, "trail_decay_tight_mult": 2.5}) == []
    assert mt.trigger_flag_errors("tight", "", 6, **{**ok, "trail_decay_tight_mult": 2.5, "trail_decay_arm_r": 2.0})


# ── harness runs (both harnesses) ───────────────────────────────────────────
@pytest.fixture(scope="module")
def csv(tmp_path_factory):
    import numpy as np
    import pandas as pd
    d = tmp_path_factory.mktemp("w43")
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", "2024-06-01", freq="4h", tz="UTC")
    c = 2000 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
    p = d / "c.csv"
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1000.0}).to_csv(p, index=False)
    return p


HARNESS = {
    "trend": ["scripts/backtest_trend.py", "--donchian", "20", "--trail-mult", "6.0", "--atr-stop-mult", "1.5"],
    "pullback": ["scripts/backtest_pullback.py", "--trend-lookback", "40", "--pullback-lookback", "10",
                 "--trail-mult", "5.0", "--atr-stop-mult", "1.5"],
}


def _run(csv, out: Path, harness: str, *extra: str, expect_rc: int = 0):
    script, *base = HARNESS[harness]
    argv = [sys.executable, str(REPO / script), *base, "--data", str(csv), "--symbol", "ETHUSDT",
            "--resample", "4h", "--fee-bps-roundtrip", "7.5", "--tp-cap-pct", "0.099", "--tp-r", "50",
            "--emit-trades", str(out.with_suffix(".jsonl")), "--json", str(out), *extra]
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == expect_rc, r.stderr[-2000:]
    if expect_rc:
        return r.stderr
    d = json.loads(out.read_text())
    d.pop("run_date", None)
    trades = [json.loads(ln) for ln in out.with_suffix(".jsonl").read_text().splitlines() if ln.strip()]
    return d, trades


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_new_flags_at_their_defaults_are_byte_identical(csv, tmp_path, harness):
    a = _run(csv, tmp_path / "a.json", harness)
    b = _run(csv, tmp_path / "b.json", harness, "--giveback-frac", "0", "--trail-level-min-r", "0",
             "--trigger-all", "0")
    assert a == b


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_fractional_giveback_in_the_harness(csv, tmp_path, harness):
    d, trades = _run(csv, tmp_path / "f.json", harness, "--giveback-min-mfe-r", "1.5", "--giveback-frac", "0.6")
    gb = [t for t in trades if t["exit_reason"] == "giveback_stop"]
    assert d["params"]["giveback_frac"] == 0.6 and len(gb) > 10
    # gross R is the bar-close open profit at the exit, mfe_r the running peak (3 dp): exit at or below 0.6 x peak,
    # and only ever after the peak armed it. (The absolute 1 R default giveback_r is NOT also in force.)
    assert all(t["mfe_r"] >= 1.5 and t["gross_r"] <= 0.6 * t["mfe_r"] + 1e-3 for t in gb)
    absolute, _ = _run(csv, tmp_path / "g.json", harness, "--giveback-min-mfe-r", "1.5", "--giveback-r", "1.0")
    assert (absolute["total_trades"], absolute["net_total_r"]) != (d["total_trades"], d["net_total_r"])


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_level_trail_r_gate_in_the_harness(csv, tmp_path, harness):
    lv = ("--trail-level", "round", "--trail-level-tight-mult", "1.5")
    base, _ = _run(csv, tmp_path / "base.json", harness)
    open_, t_open = _run(csv, tmp_path / "open.json", harness, *lv)
    gated, t_gated = _run(csv, tmp_path / "gated.json", harness, *lv, "--trail-level-min-r", "1.0")
    never, _ = _run(csv, tmp_path / "never.json", harness, *lv, "--trail-level-min-r", "1000")
    assert gated["params"]["trail_level_min_r"] == 1.0 and "trail_level_min_r" not in open_["params"]
    # a touch before the peak reaches 1 R must not latch: every LATCHED trade had a peak >= 1 R, and the
    # ungated run does latch trades that never got there (so the gate is doing something)
    assert any(t["level_touched"] and t["mfe_r"] < 1.0 for t in t_open)
    assert all(t["mfe_r"] >= 1.0 for t in t_gated if t["level_touched"])
    # a gate nothing can pass leaves the level inert: the book is the no-level book
    assert never["level_trail"]["n_touched"] == 0
    assert (never["total_trades"], never["net_total_r"]) == (base["total_trades"], base["net_total_r"])


def _flag_file(trades, path: Path, n: int, k: int = 2) -> None:
    rows = [{"trade_key": f"{t['strategy']}|{t['symbol']}|{t['entry_time']}|{t['direction']}", "k": k,
             "trigger": True, "p": 0.9} for t in trades[:n]]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_trigger_empty_file_is_the_declared_exit_and_a_populated_one_acts_only_on_flagged(csv, tmp_path, harness):
    base, trades = _run(csv, tmp_path / "base.json", harness)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    for action, extra in (("bank", ("--bank-frac", "0.5", "--bank-at-r", "1.0")),
                          ("tight", ("--trail-decay-tight-mult", "2.5"))):
        e, _ = _run(csv, tmp_path / f"e_{action}.json", harness, *extra, "--trigger-action", action,
                    "--trigger-file", str(empty))
        assert e["metric_trigger"]["n_acted"] == 0
        assert (e["total_trades"], e["net_total_r"]) == (base["total_trades"], base["net_total_r"])
        pop = tmp_path / f"pop_{action}.jsonl"
        _flag_file(trades, pop, 5)
        p, _ = _run(csv, tmp_path / f"p_{action}.json", harness, *extra, "--trigger-action", action,
                    "--trigger-file", str(pop))
        assert 0 < p["metric_trigger"]["n_acted"] <= 5 and p["metric_trigger"]["n_flagged_in_file"] == 5
        everyone, _ = _run(csv, tmp_path / f"u_{action}.json", harness, *extra, "--trigger-action", action,
                           "--trigger-all", "2")
        assert everyone["metric_trigger"]["n_acted"] > p["metric_trigger"]["n_acted"]
        never, _ = _run(csv, tmp_path / f"n_{action}.json", harness, *extra, "--trigger-action", action,
                        "--trigger-all", "100000")
        assert (never["total_trades"], never["net_total_r"]) == (base["total_trades"], base["net_total_r"])


def test_trigger_flags_refuse_a_missing_file_and_half_a_declaration(csv, tmp_path):
    err = _run(csv, tmp_path / "x.json", "pullback", "--bank-frac", "0.5", "--trigger-action", "bank",
               "--trigger-file", str(tmp_path / "nope.jsonl"), expect_rc=2)
    assert "does not exist" in err
    err = _run(csv, tmp_path / "y.json", "trend", "--trigger-all", "6", expect_rc=2)
    assert "declared together" in err


# ── PATHMETRIC-VOLCTL / emit-triggers in the label study ────────────────────
def test_path_metric_self_test_covers_the_volatility_control_and_the_out_of_fold_construction():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/path_metric_giveback.py"), "--self-test"],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == 0, r.stdout[-3000:]
    assert "--baseline-extra vol_ratio_k -> no gain" in r.stdout and "OOF rejects the leak" in r.stdout


def test_vol_ratio_k_reads_bars_one_to_k_and_is_off_by_default():
    import path_metric_giveback as pm

    def rows(tail=0.0):
        return [{"trade_key": "l|S|2021-01-01 00:00:00+00:00|long", "bar_offset": b, "c_r": 0.1 * b,
                 "fav_r": 0.1 * b + 0.2, "adv_r": 0.1 * b - 0.2, "open_r": 0.1 * b, "peak_r": 0.1 * b + 0.2,
                 "mae_r": 0.0, "bars_since_peak": 0, "is_exit": b == 9, "atr_r": 0.5 + tail * b} for b in range(1, 10)]
    f = pm.path_features(rows(), 6, ("vol_ratio_k",))
    assert f["vol_ratio_k"] > 0 and "vol_ratio_k" not in pm.path_features(rows(), 6)
    assert f == pm.path_features(rows(), 6, ("vol_ratio_k",))
    # ATR at entry is bar 1's atr_r: changing a later bar's ATR cannot move the feature
    later = rows()
    later[4]["atr_r"] = 9.0
    assert pm.path_features(later, 6, ("vol_ratio_k",)) == f


def test_end_to_end_emit_triggers_feed_the_ablation(tmp_path):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(5)
    ts = pd.date_range("2020-01-01", "2024-06-01", freq="2h", tz="UTC")
    c = 0.5 * np.exp(np.cumsum(rng.normal(0.0001, 0.012, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
    csv = tmp_path / "c2h.csv"
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1e6}).to_csv(csv, index=False)
    # the producer alone, with the volatility control
    trig = tmp_path / "trig.jsonl"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/path_metric_giveback.py"), "--leg",
                        "ada_pullback_2h", "--k", "6", "--data-csv", str(csv), "--folds", "4", "--fold-majority", "3",
                        "--n-floor", "20", "--min-r2-gain", "0.02", "--min-ll-gain", "0.01", "--big-quantile", "0.5",
                        "--baseline-extra", "vol_ratio_k", "--emit-triggers", str(trig), "--out", str(tmp_path / "pm")],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    v = json.loads((tmp_path / "pm/verdict.json").read_text())
    rows = [json.loads(ln) for ln in trig.read_text().splitlines()]
    assert v["measurement"]["baseline_extra"] == ["vol_ratio_k"] and v["measurement"]["triggers"]["n_scored"] == len(rows) == v["n"]
    assert all(set(x) == {"trade_key", "k", "trigger", "p"} and x["k"] == 6 for x in rows)
    # the one-command form the queue units use: producer + arms in a single run
    out = tmp_path / "abl"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", "ada_pullback_2h",
                        "--data-csv", str(csv), "--trigger-from-path-metrics", "6", "--arm", "A=", "--arm",
                        "MB=--trigger-action=bank;--bank-frac=0.5;--bank-at-r=1.0;--trigger-file=@trigger_file",
                        "--arm", "UB=--trigger-action=bank;--bank-frac=0.5;--bank-at-r=1.0;--trigger-all=6",
                        "--grade", "replace", "--baseline", "A", "--delta-r", "0", "--fold-majority", "3",
                        "--folds", "4", "--n-floor", "20", "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=900)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2500:]
    s = json.loads((out / "verdict.json").read_text())
    assert s["measurement"]["trigger"]["n_flagged"] > 0
    mb = json.loads((out / "arms/MB__bt.json").read_text())["metric_trigger"]
    assert mb["n_flagged_in_file"] == s["measurement"]["trigger"]["n_flagged"] and 0 < mb["n_acted"]
    # an arm that names @trigger_file without the producer is refused, not run on a literal path
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", "ada_pullback_2h",
                        "--data-csv", str(csv), "--arm", "A=", "--arm", "MB=--trigger-file=@trigger_file",
                        "--grade", "replace", "--baseline", "A", "--delta-r", "0", "--fold-majority", "3",
                        "--folds", "4", "--n-floor", "20", "--out", str(tmp_path / "abl2")],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=900)
    assert r.returncode == 2 and "trigger_file" in r.stderr

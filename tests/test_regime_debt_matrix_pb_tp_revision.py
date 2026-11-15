"""The pullback harness models a declared tp_extend TP revision (TP-REALMONEY-UNITS, 2026-11-04).

A leg declaring `tp_revision: {rule: tp_extend, ...}` must be replayed with the GEOM-B1
`--tp-*` flags anchored at its tp_r (the arm shape RQ-20261104-c6f1-02/-06 measured) and
grade faithful; any other rule must stay OMITTED (approximate), never silently faithful.
"""
from scripts.research import regime_debt_matrix as r

BASE = {"trend_lookback": 40, "pullback_lookback": 10, "pullback_frac": 0.5, "atr_period": 14,
        "atr_stop_mult": 1.5, "trail_mult": 3.0, "tp_r": 3.0, "symbols": ["XRPUSDT"], "timeframe": "2h",
        "decision_bar": "closed"}  # absent == forming == an omitted lever (EVIDENCE-DECISION-BAR-DEFAULT)


def _cmd(cfg):
    return r.build_harness_cmd("leg", cfg, "pullback", "x.csv", "2h", "e", "j")


def test_tp_extend_is_modelled_and_faithful():
    cfg = dict(BASE, tp_revision={"rule": "tp_extend", "extend_r": 1.0, "approach_frac": 0.85, "max_extends": 3})
    argv, faithful, omitted = _cmd(cfg)
    assert faithful and omitted == []
    i = argv.index("--tp-target-r")
    assert argv[i:i + 10] == ["--tp-target-r", "3.0", "--tp-extend-r", "1.0", "--tp-approach-frac", "0.85",
                              "--tp-max-extends", "3", "--tp-thesis", "native"]


def test_undeclared_is_byte_identical():
    argv, faithful, _ = _cmd(dict(BASE))
    assert faithful and "--tp-extend-r" not in argv and "--tp-target-r" not in argv


def test_unknown_rule_or_missing_extend_r_is_omitted():
    for rev in ({"rule": "stall_pull_in"}, {"rule": "tp_extend"}, "tp_extend"):
        argv, faithful, omitted = _cmd(dict(BASE, tp_revision=rev))
        assert not faithful and "tp_revision" in omitted and "--tp-extend-r" not in argv

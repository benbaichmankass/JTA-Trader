"""ML universe from the per-symbol pass record (row ML-ENTRY-ALL-ACCOUNTS, PR B): no record = configured set, byte-identical;
GROUP-LEVEL (operator 2026-11-04 ~19:33Z "Group-level (Recommended)"): a passed population adds its symbols on the account's
venue; a fail / indeterminate population changes nothing; nothing is ever removed."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.config import ml_universe as MU
from src.config.symbol_sets import leg_symbols, roster_symbols

REPO = Path(__file__).resolve().parents[1]


def _cfgs():
    return yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]


def _accts():
    return yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]


def test_no_record_exists_today_so_every_leg_and_account_is_unchanged():
    cfgs, accts = _cfgs(), _accts()
    assert not list(MU.RECORD_DIR.glob("*.json")), "a record would change what trades: it must arrive by its own unit"
    for name, scfg in cfgs.items():
        if not isinstance(scfg, dict):
            continue
        assert leg_symbols(scfg, None, leg=name) == leg_symbols(scfg, None)
        for a in accts:
            assert leg_symbols(scfg, a, leg=name) == leg_symbols(scfg, a), (name, a)
    for a, acct in accts.items():
        roster = acct.get("strategies") or []
        assert roster_symbols(roster, cfgs, a) == [s for s in _old_roster(roster, cfgs, a)], a


def _old_roster(roster, cfgs, account_id):
    out = []
    for name in roster:
        for s in leg_symbols(cfgs.get(name) or {}, account_id):
            if s not in out:
                out.append(s)
    return out


def _pop(verdict, syms, unit="RQ-X"):
    return {"unit": unit, "verdict": verdict, "symbols": {s: {"venues": v} for s, v in syms.items()}}


def test_apply_rule():
    rec = [_pop("pass", {"AAVEUSDT": ["bybit"], "BTCUSDT": ["bybit"], "SPY": ["alpaca"]}),
           _pop("fail", {"ZECUSDT": ["bybit"], "ETHUSDT": ["bybit"]}),
           _pop("indeterminate", {"DOGEUSDT": ["bybit"]})]
    conf = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert MU.apply(conf, None, "bybit") == conf                                   # no record: unchanged
    assert MU.apply(conf, rec, "bybit") == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AAVEUSDT"]  # pass adds; fail never removes
    assert MU.apply(conf, rec, "alpaca") == conf + ["SPY"]                         # the venue decides which passes
    assert MU.apply([], rec, None) == []                                           # no venue: nothing added


def _write(tmp_path, doc):
    d = tmp_path / "ml_universe"
    d.mkdir()
    (d / "ml_entry.json").write_text(json.dumps(doc))
    return d


def test_record_flows_through_leg_symbols_with_the_account_venue(tmp_path, monkeypatch):
    d = _write(tmp_path, {"schema": MU.SCHEMA, "leg": "ml_entry", "populations": [
        _pop("pass", {"AAVEUSDT": ["bybit"], "BTCUSDT": ["bybit"]}, "RQ-20261101-a24c-01"),
        _pop("fail", {"ETHUSDT": ["bybit"]}, "RQ-OTHER")]})
    monkeypatch.setattr(MU, "RECORD_DIR", d)
    MU._CACHE.clear()
    cfg = _cfgs()["ml_entry"]
    five = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
    assert leg_symbols(cfg, "bybit_2", leg="ml_entry") == five + ["AAVEUSDT"]       # widened, never narrowed
    assert "AAVEUSDT" not in leg_symbols(cfg, "alpaca_paper", leg="ml_entry")     # not listed on alpaca
    assert "AAVEUSDT" in leg_symbols(cfg, None, leg="ml_entry")                    # the builder's union sees it
    assert leg_symbols(cfg, "bybit_2") == five                                     # no leg name: config
    MU._CACHE.clear()


def test_a_malformed_or_foreign_record_changes_nothing(tmp_path, monkeypatch):
    d = _write(tmp_path, {"schema": MU.SCHEMA, "leg": "other_leg", "populations": [_pop("pass", {"AAVEUSDT": ["bybit"]})]})
    monkeypatch.setattr(MU, "RECORD_DIR", d)
    MU._CACHE.clear()
    cfg = _cfgs()["ml_entry"]
    assert leg_symbols(cfg, "bybit_2", leg="ml_entry") == leg_symbols(cfg, "bybit_2")
    (d / "ml_entry.json").write_text("{not json")
    MU._CACHE.clear()
    assert leg_symbols(cfg, "bybit_2", leg="ml_entry") == leg_symbols(cfg, "bybit_2")
    MU._CACHE.clear()


def test_default_write_keeps_other_units_populations(tmp_path, monkeypatch):
    """base=None writes to RECORD_DIR and must read RECORD_DIR first: a second unit's write never erases the first's."""
    d = tmp_path / "ml_universe"
    monkeypatch.setattr(MU, "RECORD_DIR", d)
    a = {"unit": "RQ-A", "rule_id": "R-A", "verdict": "pass", "result": "r/a", "symbols": {"BTCUSDT": {"venues": ["bybit"]}}}
    b = {"unit": "RQ-B", "rule_id": "R-B", "verdict": "fail", "result": "r/b", "symbols": {"ZECUSDT": {"venues": ["bybit"]}}}
    MU.write_population("ml_entry", a)
    MU.write_population("ml_entry", b)
    MU.write_population("ml_entry", {**b, "verdict": "indeterminate"})     # same unit replaces, never duplicates
    pops = MU.load("ml_entry")
    assert [(p["unit"], p["verdict"]) for p in pops] == [("RQ-A", "pass"), ("RQ-B", "indeterminate")]
    assert MU.passed_symbols(pops, "bybit") == ["BTCUSDT"]

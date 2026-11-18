"""VALUES EXCLUSIONS: no real-money or prop roster may trade a fossil-fuel instrument (config/values_exclusions.yaml).

Operator, 2026-11-17 ~07:15Z, verbatim: "In general, I ask that we not trade fossil fuels." / "We can do it on paper in order to
create data and learn from it. I just don't want to trade it on actual live money." Standing rule since 2026-08-29: "I don't wanna
make money from fossil fuels." (config/accounts.yaml, the alpaca_live roster comment.)

This is a CI TEST, NOT a runtime gate: nothing in the trader reads config/values_exclusions.yaml. It resolves each gated account's
effective symbol set the way the runtime does (``src.config.symbol_sets.roster_symbols``: the leg's ``symbols`` list, narrowed by
``account_symbols``, widened by a passed ML population record) and fails the PR that puts a fossil symbol back on one. The 2026-08-29 rule
had only been wired as "uso_trend_1h is not on real money"; ml_entry_eq_struct (alpaca_live + its mirror alpaca_portfolio) still reached
nine oil/gas names through its 173-ETF pool until 2026-11-17.

GATED accounts: account_class real_money or prop, and the real-money MIRRORS (src/runtime/mirror_pairs.py MIRROR_PAIRS). PAPER-testing
accounts are exempt: paper trades these symbols for data, on the operator's own words.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.config.symbol_sets import load_strategies_cfg, roster_symbols  # noqa: E402
from src.runtime.mirror_pairs import MIRROR_PAIRS  # noqa: E402

GATED_CLASSES = ("real_money", "prop")


def _fossil() -> Dict[str, Any]:
    return yaml.safe_load((REPO / "config" / "values_exclusions.yaml").read_text())["fossil_fuels"]


def _accounts() -> Dict[str, Any]:
    raw = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())
    return raw.get("accounts") or raw


def is_gated(account_id: str, acct: Mapping[str, Any], mirrors: Iterable[str] = tuple(MIRROR_PAIRS)) -> bool:
    return str(acct.get("account_class") or "") in GATED_CLASSES or str(account_id) in set(mirrors)


def fossil_hits(accounts: Mapping[str, Any], strategies_cfg: Mapping[str, Any], fossil: Iterable[str],
                mirrors: Iterable[str] = tuple(MIRROR_PAIRS)) -> Dict[str, Dict[str, List[str]]]:
    """``{account: {leg: [fossil symbols it reaches]}}`` for every GATED account; empty when clean."""
    bad = set(fossil)
    out: Dict[str, Dict[str, List[str]]] = {}
    for aid, acct in accounts.items():
        if not isinstance(acct, Mapping) or not is_gated(aid, acct, mirrors):
            continue
        for leg in acct.get("strategies") or []:
            hit = sorted(set(roster_symbols([leg], strategies_cfg, str(aid))) & bad)
            if hit:
                out.setdefault(str(aid), {})[str(leg)] = hit
    return out


def test_no_gated_account_reaches_a_fossil_fuel_symbol():
    hits = fossil_hits(_accounts(), load_strategies_cfg(), _fossil()["symbols"])
    assert not hits, (
        "a fossil-fuel symbol is reachable on a real-money / prop / real-money-mirror roster "
        f"(operator 2026-11-17 'In general, I ask that we not trade fossil fuels.'): {hits}. "
        "Remove it from the leg's symbols (and add it to pool_exclude with the reason); paper accounts are exempt."
    )


def test_the_check_can_fail_a_synthetic_real_money_leg_on_uso_is_caught():
    """Negative control: the same function MUST flag a gated account whose leg reaches USO, and must not flag a paper one."""
    accounts = {
        "real_acct": {"account_class": "real_money", "strategies": ["legA"]},
        "prop_acct": {"account_class": "prop", "strategies": ["legA"]},
        "paper_mirror": {"account_class": "paper", "strategies": ["legA"]},
        "paper_acct": {"account_class": "paper", "strategies": ["legA"]},
    }
    cfg = {"legA": {"symbols": ["SPY", "USO"]}}
    hits = fossil_hits(accounts, cfg, ["USO"], mirrors=["paper_mirror"])
    assert hits == {"real_acct": {"legA": ["USO"]}, "prop_acct": {"legA": ["USO"]}, "paper_mirror": {"legA": ["USO"]}}
    assert "paper_acct" not in hits


def test_the_gate_is_not_vacuous_it_sees_real_money_prop_and_mirror_accounts():
    gated = sorted(a for a, v in _accounts().items() if isinstance(v, dict) and is_gated(a, v))
    for must in ("alpaca_live", "bybit_2", "alpaca_portfolio", "bybit_portfolio", "tradeify_1", "velotrade_1"):
        assert must in gated, (must, gated)
    # and the rule really does bite where it was broken: alpaca_live trades the 173-ETF pool minus the exclusions
    syms = roster_symbols(_accounts()["alpaca_live"]["strategies"], load_strategies_cfg(), "alpaca_live")
    assert len(syms) > 100 and "SPY" in syms and "USO" not in syms


def test_the_record_carries_the_decision_the_quotes_and_every_reachable_name():
    f = _fossil()
    assert f["decision"].startswith("2026-11-17 operator-chat") and "not trade fossil fuels" in f["decision"]
    assert any("actual live money" in q for q in f["quotes"]) and any("fossil fuels" in q for q in f["quotes"])
    syms = f["symbols"]
    assert len(syms) == len(set(syms)) and all(isinstance(s, str) and s == s.upper() for s in syms)
    assert set(f["reachable_2026_11_17"]) <= set(syms)
    for must in ("USO", "UCO", "UNG", "XLE", "XOP", "OIH", "GUSH", "AMLP", "NFX", "CL", "MCL", "QM", "NG"):
        assert must in syms, must


def test_ml_entry_eq_struct_declares_every_excluded_name_in_pool_exclude_with_a_reason():
    leg = load_strategies_cfg()["ml_entry_eq_struct"]
    excl = leg["pool_exclude"]
    for s in _fossil()["reachable_2026_11_17"]:
        assert s in excl and "fossil fuels" in str(excl[s]), s
        assert s not in leg["symbols"], s


def test_an_open_package_in_an_excluded_symbol_is_still_managed():
    """The open USO package (pkg-0a89fcdbe96b4169, alpaca_live + alpaca_portfolio) stays open and closes on its own bracket: the monitor
    dispatches per OPEN PACKAGE with the package's own symbol and never reads the leg's ``symbols:`` list, and ml_entry_eq.monitor takes no
    symbol set, so excluding USO from the leg does not orphan it (the venue bracket and the monitor's time stop / structure verdict hold)."""
    import inspect

    from src.runtime import order_monitor
    from src.units.strategies import ml_entry_eq

    cfg = {"structure_exit": "pivot=5;sl_only", "symbols": []}           # USO is not in the leg's symbols any more
    old = {"order_package_id": "pkg-x", "symbol": "USO", "created_at": "2026-11-15T00:00:00+00:00",
           "meta": {"max_hold_min": 60, "entry_time": "2026-11-15T00:00:00+00:00"}}
    assert ml_entry_eq.monitor(cfg, None, old) == {"action": "close", "reason": "max_hold"}   # time stop still fires
    src = inspect.getsource(order_monitor._call_strategy_monitor)
    assert 'cfg["symbols"]' not in src and "cfg.get(\"symbols\")" not in src and "symbols" not in src

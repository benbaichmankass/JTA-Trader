"""I6 ML-ADVISORY-SCOPE-GUARD: no ML order effect on a real-money or prop leg
without a Gate-2 evidence record.

Plan docs/plans/ml-live-promotion-plan-2026-10-29.md § 2 ("all five act only on
legs rostered on bybit_1 alone") and § 6 I6. Three config surfaces let a model
change an order:

  advisory_downsize   config/strategies.yaml::<leg>.advisory_policy.mode: downsize
                      (WS7, src/runtime/advisory_sizing.py; a size_floor 0 is a veto)
  trend_vol           an `off` side in config/regime_policy.yaml::trend_vol
                      (the ML vol head drops the intent before routing)
  exit_head_close     config/strategies.yaml::<leg>.exit_head_action: close

A leg carrying one of them must not be on a RISK-BEARING roster unless
`comms/ml_gate2/<leg>.json` names that consumer and points at a committed
evidence record that exists. Risk-bearing = `account_class` other than `paper`
(real_money and prop), plus the paper-portfolio mirrors of the real-money
accounts (Stage 2 is one stage; scripts/ops/strategy_status.py::REAL_MONEY_MIRROR).

⚠️ It keys on ROSTER MEMBERSHIP, not on `mode` / `execution` (CLAUDE.md: CI is
asymmetric). Adding a leg to `bybit_2` is the edit that must go red, and it is
planted below against a copy of the real config. YAML 1.1 reads `off` as False;
both spellings count.

Record shape (`comms/ml_gate2/<leg>.json`):
  {"leg": "<leg>", "consumers": ["advisory_downsize", ...],
   "evidence": "<repo path of the committed Gate-2 evidence record>"}
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[1]
RECORDS_REL = "comms/ml_gate2"


def _mirrors() -> set[str]:
    spec = importlib.util.spec_from_file_location(
        "strategy_status", REPO / "scripts/ops/strategy_status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {m for m in mod.REAL_MONEY_MIRROR.values() if m}


def risk_bearing_rosters(accounts: dict) -> dict[str, set[str]]:
    """leg -> the risk-bearing accounts that roster it."""
    risk = {a for a, c in accounts.items()
            if isinstance(c, dict) and c.get("account_class") != "paper"}
    risk |= _mirrors() & set(accounts)
    out: dict[str, set[str]] = {}
    for a in risk:
        for leg in (accounts[a] or {}).get("strategies") or []:
            out.setdefault(str(leg), set()).add(a)
    return out


def ml_consumers(strategies: dict, regime_policy: dict) -> dict[str, set[str]]:
    """leg -> the ML order-changing consumers its config arms."""
    out: dict[str, set[str]] = {}
    for leg, cfg in strategies.items():
        if not isinstance(cfg, dict):
            continue
        if str((cfg.get("advisory_policy") or {}).get("mode") or "") == "downsize":
            out.setdefault(leg, set()).add("advisory_downsize")
        if str(cfg.get("exit_head_action") or "") == "close":
            out.setdefault(leg, set()).add("exit_head_close")
    for vols in (regime_policy.get("trend_vol") or {}).values():
        for cells in (vols or {}).values():
            for leg, sides in (cells or {}).items():
                if any(v is False or str(v).lower() == "off"
                       for v in (sides or {}).values()):
                    out.setdefault(str(leg), set()).add("trend_vol")
    return out


def violations(root: Path, accounts: dict, strategies: dict, regime_policy: dict) -> list[str]:
    ros = risk_bearing_rosters(accounts)
    bad: list[str] = []
    for leg, consumers in sorted(ml_consumers(strategies, regime_policy).items()):
        on = ros.get(leg)
        if not on:
            continue
        rec_path = root / RECORDS_REL / f"{leg}.json"
        rec = {}
        if rec_path.is_file():
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
            except ValueError:
                rec = {}
        ev = str(rec.get("evidence") or "")
        cleared = set(rec.get("consumers") or []) if ev and (root / ev).is_file() else set()
        for c in sorted(consumers - cleared):
            bad.append(f"{leg}: {c} on {sorted(on)} without a Gate-2 record "
                       f"({RECORDS_REL}/{leg}.json)")
    return bad


def _real():
    def load(rel):
        return yaml.safe_load((REPO / rel).read_text(encoding="utf-8")) or {}

    return (load("config/accounts.yaml")["accounts"],
            load("config/strategies.yaml")["strategies"],
            load("config/regime_policy.yaml"))


def test_main_is_green():
    accounts, strategies, rp = _real()
    assert violations(REPO, accounts, strategies, rp) == []


def test_the_probe_sees_the_armed_consumers():
    """A negative needs a denominator: the real config arms consumers today."""
    _, strategies, rp = _real()
    seen = set().union(*ml_consumers(strategies, rp).values())
    assert {"trend_vol", "exit_head_close"} <= seen


def _a_real_money_account(accounts):
    return next(a for a, c in accounts.items()
                if isinstance(c, dict) and c.get("account_class") == "real_money")


@pytest.mark.parametrize("consumer", ["trend_vol", "exit_head_close", "advisory_downsize"])
def test_rostering_an_ml_leg_on_real_money_goes_red(consumer):
    accounts, strategies, rp = _real()
    armed = ml_consumers(strategies, rp)
    if consumer == "advisory_downsize":
        leg = "trend_donchian"
        strategies[leg]["advisory_policy"] = {"mode": "downsize", "size_floor": 0.0}
    else:
        leg = next(lg for lg, cs in sorted(armed.items()) if consumer in cs)
    acct = _a_real_money_account(accounts)
    accounts[acct]["strategies"] = list(accounts[acct].get("strategies") or []) + [leg]
    bad = violations(REPO, accounts, strategies, rp)
    assert any(b.startswith(f"{leg}: {consumer}") for b in bad), bad


def test_a_prop_roster_counts():
    accounts, strategies, rp = _real()
    prop = next(a for a, c in accounts.items()
                if isinstance(c, dict) and c.get("account_class") == "prop")
    accounts[prop]["strategies"] = list(accounts[prop].get("strategies") or []) + ["trend_donchian"]
    assert violations(REPO, accounts, strategies, rp)


def test_arming_a_consumer_on_an_already_real_money_leg_goes_red():
    """The other direction of the same edit: the leg is already on real money
    and the PR arms the consumer."""
    accounts, strategies, rp = _real()
    ros = risk_bearing_rosters(accounts)
    if not ros:
        pytest.skip("no leg is on a risk-bearing roster")
    leg = min(ros)
    strategies.setdefault(leg, {})["exit_head_action"] = "close"
    assert any(b.startswith(f"{leg}: exit_head_close")
               for b in violations(REPO, accounts, strategies, rp))


def test_a_gate2_record_with_existing_evidence_clears_it(tmp_path):
    accounts, strategies, rp = _real()
    acct = _a_real_money_account(accounts)
    accounts[acct]["strategies"] = list(accounts[acct].get("strategies") or []) + ["trend_donchian"]
    (tmp_path / RECORDS_REL).mkdir(parents=True)
    (tmp_path / "ev.json").write_text("{}")
    consumers = sorted(ml_consumers(strategies, rp)["trend_donchian"])
    (tmp_path / RECORDS_REL / "trend_donchian.json").write_text(json.dumps(
        {"leg": "trend_donchian", "consumers": consumers, "evidence": "ev.json"}))
    assert violations(tmp_path, accounts, strategies, rp) == []
    # A record pointing at a missing evidence file is a claim, not a record.
    (tmp_path / "ev.json").unlink()
    assert violations(tmp_path, accounts, strategies, rp)

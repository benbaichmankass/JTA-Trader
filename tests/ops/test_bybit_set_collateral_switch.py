"""set-bybit-collateral-switch: demo-only, dry-run by default, re-read is the proof,
and no dollar figure reaches the output (the issue comment is public)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
import bybit_set_collateral_switch as m  # noqa: E402

DEMO = {"account_id": "bybit_1", "exchange": "bybit", "demo": True, "account_class": "paper"}
REAL = {"account_id": "bybit_2", "exchange": "bybit", "account_class": "real_money"}


class _Client:
    def __init__(self, switch=False, honour=True, margin=(36447.1, 25777.1), after_margin=(116000.0, 105000.0)):
        self.switch, self.honour = switch, honour
        self.margin, self.after_margin = margin, after_margin
        self.calls = []

    def get_wallet_balance(self, accountType):  # noqa: N803
        mb, av = self.margin if not self.calls else self.after_margin
        return {"result": {"list": [{"totalMarginBalance": str(mb), "totalAvailableBalance": str(av),
                                     "coin": [{"coin": "BTC", "collateralSwitch": self.switch}]}]}}

    def set_collateral_switch(self, coin, collateralSwitch):  # noqa: N803
        self.calls.append((coin, collateralSwitch))
        if self.honour:
            self.switch = collateralSwitch == "ON"
        return {"retCode": 0, "retMsg": "OK"}


def _args(**kw):
    d = dict(account="bybit_1", coin="BTC", switch="ON", confirm_account=None, apply=False)
    d.update(kw)
    return argparse.Namespace(**d)


def test_dry_run_never_mutates():
    c = _Client()
    code, out = m.run(_args(), DEMO, c)
    assert code == 0 and out["action"] == "report_only" and c.calls == []


@pytest.mark.parametrize("cfg", [REAL, {**DEMO, "account_class": "real_money"}, {**DEMO, "demo": False},
                                 {**DEMO, "exchange": "alpaca"}])
def test_non_demo_accounts_are_refused_even_with_apply(cfg):
    c = _Client()
    code, out = m.run(_args(apply=True, confirm_account="bybit_1"), cfg, c)
    assert code == 2 and out["action"] == "abort_not_demo" and c.calls == []


def test_unknown_account_and_bad_args_refused():
    assert m.run(_args(), None, _Client())[1]["action"] == "abort_unknown_account"
    assert m.run(_args(coin="DOGE"), DEMO, _Client())[1]["action"] == "abort_bad_args"
    assert m.run(_args(switch="MAYBE"), DEMO, _Client())[1]["action"] == "abort_bad_args"


def test_apply_requires_confirm_account():
    c = _Client()
    code, out = m.run(_args(apply=True), DEMO, c)
    assert code == 2 and out["action"] == "abort_unconfirmed" and c.calls == []


def test_apply_switches_and_verifies_by_reread_without_printing_dollars():
    c = _Client()
    code, out = m.run(_args(apply=True, confirm_account="bybit_1"), DEMO, c)
    assert code == 0 and out["action"] == "switched" and out["switch_verified"] is True
    assert c.calls == [("BTC", "ON")]
    assert out["margin_balance"] == "increased" and out["available"] == "increased"
    blob = json.dumps(out)
    for n in ("36447", "25777", "116000", "105000"):
        assert n not in blob


def test_silent_venue_noop_is_a_failure_not_a_success():
    c = _Client(honour=False)
    code, out = m.run(_args(apply=True, confirm_account="bybit_1"), DEMO, c)
    assert code == 5 and out["action"] == "switch_unverified" and out["switch_verified"] is False


def test_already_in_state_is_a_clean_noop():
    c = _Client(switch=True)
    code, out = m.run(_args(apply=True, confirm_account="bybit_1"), DEMO, c)
    assert code == 0 and out["action"] == "noop_already_set" and c.calls == []


def test_revert_off_uses_the_same_path():
    c = _Client(switch=True)
    code, out = m.run(_args(switch="OFF", apply=True, confirm_account="bybit_1"), DEMO, c)
    assert code == 0 and c.calls == [("BTC", "OFF")]


def test_unreadable_wallet_refuses_apply():
    class _Boom(_Client):
        def get_wallet_balance(self, accountType):  # noqa: N803
            raise RuntimeError("down")
    code, out = m.run(_args(apply=True, confirm_account="bybit_1"), DEMO, _Boom())
    assert code == 3 and out["action"] == "abort_unreadable"


def test_runs_standalone_from_a_foreign_cwd(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/ops/bybit_set_collateral_switch.py"), "--help"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

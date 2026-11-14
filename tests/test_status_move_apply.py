"""scripts/ops/status_move_apply.py: close the general-paper copy of a promoted trade (row STATUS-MOVE-AUTO-PAPER-CLOSE).

Hard limits the manager reviews (2026-11-14 11:35Z): a real-money or mirror account is NEVER a target; a close is per
row and account/trade-scoped (never a whole-symbol flatten); only a MEASURED (order-package) match acts; a trade id is
acted on at most once; the close goes through the existing directed-action -> live_review_apply path.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import status_move_apply as sma  # noqa: E402

from src.runtime import directed_actions as da  # noqa: E402

ACCOUNTS = {
    "bybit_1": {"account_class": "paper", "strategies": ["other"]},
    "bybit_2": {"account_class": "real_money", "strategies": ["ada"]},
    "bybit_portfolio": {"account_class": "paper", "paper_role": "portfolio", "strategies": ["ada"]},
}
STRATS = {"ada": {"enabled": True}, "other": {"enabled": True}}


def _p(i, acct, leg="ada", sym="ADAUSDT", side="short", pkg="pkg-A"):
    return {"id": i, "account_id": acct, "strategy_name": leg, "symbol": sym, "direction": side, "order_package_id": pkg}


def test_real_money_and_mirror_are_never_targets():
    assert sma.general_paper_refusal("bybit_1", ACCOUNTS) is None
    for aid in ("bybit_2", "bybit_portfolio", "alpaca_live", "alpaca_portfolio", "ib_live", "tradeify_1"):
        assert sma.general_paper_refusal(aid, ACCOUNTS), aid
    # a general-paper NAME whose config says real money (or is missing) still fails closed
    assert sma.general_paper_refusal("bybit_1", {"bybit_1": {"account_class": "real_money"}})
    assert sma.general_paper_refusal("bybit_1", {})
    assert sma.general_paper_refusal("bybit_1", {"bybit_1": {"account_class": "paper", "paper_role": "portfolio"}})


def test_promoted_paper_copy_with_a_money_sibling_is_closed_per_row():
    pos = [_p(1, "bybit_1"), _p(2, "bybit_2"), _p(3, "bybit_portfolio")]
    closes, refusals = sma.plan(pos, ACCOUNTS, STRATS, {})
    assert [c["trade_id"] for c in closes] == ["1"] and refusals == []
    c = closes[0]
    assert c["account_id"] == "bybit_1" and c["order_package_id"] == "pkg-A"
    rec = sma.directed_record(c, apply=True)
    assert da.problems(rec) == []
    assert rec["action"] == "close" and rec["scope"] == {"account_id": "bybit_1", "trade_id": "1"}   # per row, scoped
    assert rec["operator_quote"] == sma.OPERATOR_QUOTE and rec["dry_run"] is False


def test_netted_neighbour_closes_only_its_own_row():
    pos = [_p(1, "bybit_1"), _p(2, "bybit_2"), _p(5, "bybit_1", leg="other", pkg="pkg-B")]
    closes, _ = sma.plan(pos, ACCOUNTS, STRATS, {})
    assert [(c["trade_id"], c["verdict"]) for c in closes] == [("1", "close_netted")]
    assert sma.directed_record(closes[0], apply=False)["scope"]["trade_id"] == "1"   # the neighbour (5) is untouched


def test_sole_copy_runs_out_and_estimated_or_done_rows_never_act():
    assert sma.plan([_p(1, "bybit_1")], ACCOUNTS, STRATS, {}) == ([], [])          # no money sibling: runs to its exit
    closes, refusals = sma.plan([_p(1, "bybit_1", pkg=None), _p(2, "bybit_2", pkg=None)], ACCOUNTS, STRATS, {})
    assert closes == [] and refusals[0]["refused"].startswith(sma.R_ESTIMATED)
    closes, refusals = sma.plan([_p(1, "bybit_1"), _p(2, "bybit_2")], ACCOUNTS, STRATS, {"1": "DA-x"})
    assert closes == [] and refusals[0]["refused"].startswith(sma.R_DONE)


def test_a_close_row_on_a_non_paper_account_is_refused_even_if_classify_names_it(monkeypatch):
    """Defence in depth: whatever classify returns, a non-general-paper target is refused before any record."""
    fake = {"positions": [{"id": "9", "account": "bybit_2", "leg": "ada", "symbol": "ADAUSDT", "side": "sell",
                           "verdict": sma.sm.CLOSE_DUPLICATE, "match": sma.sm.MEASURED}]}
    monkeypatch.setattr(sma.sm, "classify", lambda *a, **k: fake)
    closes, refusals = sma.plan([_p(9, "bybit_2")], ACCOUNTS, STRATS, {})
    assert closes == [] and refusals[0]["refused"].startswith(sma.R_NOT_GENERAL_PAPER)


def test_run_hands_each_close_to_the_directed_path_pings_marks_and_never_repeats(monkeypatch, tmp_path):
    from scripts.ops import directed_action
    monkeypatch.setattr(sma.st, "load", lambda: (ACCOUNTS, STRATS))
    monkeypatch.setattr(sma, "open_positions", lambda db: [_p(1, "bybit_1"), _p(2, "bybit_2")])
    monkeypatch.setattr(sma, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(sma, "_log_path", lambda: tmp_path / "log.jsonl")
    seen, pings, marks = [], [], []
    monkeypatch.setattr(directed_action, "_apply_record",
                        lambda rec: seen.append(rec) or {"exit": 0, "accounts": [{"account_id": "bybit_1", "executed": True}]})
    monkeypatch.setattr(directed_action, "_ping", lambda rec, res, verdict: pings.append(verdict))
    monkeypatch.setattr(sma, "_mark", lambda db, tid: marks.append(tid) or "marked:1")
    doc = sma.run(apply=True, db_path=str(tmp_path / "x.db"))
    assert len(seen) == 1 and seen[0]["scope"] == {"account_id": "bybit_1", "trade_id": "1"}
    assert pings == ["applied"] and marks == ["1"] and doc["closes"][0]["executed"] is True
    sma.run(apply=True, db_path=str(tmp_path / "x.db"))                              # a second pass: already acted
    assert len(seen) == 1


def test_dry_run_builds_dry_records_and_writes_nothing(monkeypatch, tmp_path):
    from scripts.ops import directed_action
    monkeypatch.setattr(sma.st, "load", lambda: (ACCOUNTS, STRATS))
    monkeypatch.setattr(sma, "open_positions", lambda db: [_p(1, "bybit_1"), _p(2, "bybit_2")])
    monkeypatch.setattr(sma, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(sma, "_log_path", lambda: tmp_path / "log.jsonl")
    seen = []
    monkeypatch.setattr(directed_action, "_apply_record", lambda rec: seen.append(rec) or {"exit": 0, "accounts": []})
    monkeypatch.setattr(directed_action, "_ping", lambda *a: pytest.fail("a dry run never pings"))
    sma.run(apply=False, db_path=str(tmp_path / "x.db"))
    assert seen and seen[0]["dry_run"] is True
    assert not (tmp_path / "state.json").exists() and not (tmp_path / "log.jsonl").exists()


def test_the_real_general_paper_books_are_paper_in_the_real_config():
    accounts, _ = sma.st.load()
    for aid in sma.sm.GENERAL_PAPER:
        if aid in accounts:
            assert sma.general_paper_refusal(aid, accounts) is None, aid
    for aid in list(sma.sm.REAL_MONEY_MIRROR) + list(sma.sm.MIRRORS):
        assert sma.general_paper_refusal(aid, accounts), aid


def test_the_deploy_runs_it_only_after_an_accounts_yaml_change_and_never_fails_the_deploy():
    text = (REPO / "scripts" / "deploy_pull_restart.sh").read_text()
    i = text.index("STATUS-MOVE-AUTO-PAPER-CLOSE")
    block = text[i:text.index("===== DEPLOY COMPLETE: $(date) =====", i)]
    assert "grep -qx 'config/accounts.yaml'" in block and "status_move_apply.py\" --apply" in block
    assert "timeout 300" in block and "|| echo" in block   # bounded, and a failure never exits the deploy

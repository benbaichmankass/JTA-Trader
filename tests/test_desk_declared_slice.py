"""DESK-WIDEN: claude_desk on bybit_1 holds a DECLARED slice (config/slice_allocation.yaml::declared_slices).

A desk entry on a symbol a strategy leg already holds is neither blocked (the pooled budget is spent)
nor shrunk by that leg, never dilutes the pooled split, and the leg's symbols reach all six markets.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.runtime import allocator_ev as ae
from src.runtime.arbitration_fanout import plan_per_account_election
from src.runtime.positions import admit_slice

REPO = Path(__file__).resolve().parents[1]
CFG = {"account_id": "bybit_1", "exchange": "bybit", "position_model": "slices"}
SIX = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT"]


def _slice(strategy, direction, qty, entry=100.0, sl=95.0):
    return {"strategy_name": strategy, "direction": direction, "position_size": qty,
            "entry_price": entry, "stop_loss": sl}


def _admit(slices, strategy, *, direction="long", meta=None, declared=None):
    sl = 95.0 if direction == "long" else 105.0
    return admit_slice(
        account_id="bybit_1", account_cfg=CFG, strategy=strategy, symbol="ETHUSDT",
        direction=direction, entry=100.0, sl=sl, meta=meta, sized_qty=2.0, dry=True,
        slices_reader=lambda a, s: slices, tpsl_mode_fn=lambda: "partial",
        hedge_fn=lambda a, s: False, budget_trades=1.0,
    )


@pytest.fixture(autouse=True)
def _declare(monkeypatch):
    monkeypatch.setattr(ae, "declared_slices",
                        lambda account_id, config=None: {"claude_desk": 0.5} if account_id == "bybit_1" else {})


def test_yaml_declares_the_desk_slice_and_the_leg_scope_is_all_six():
    raw = yaml.safe_load((REPO / "config/slice_allocation.yaml").read_text())
    assert raw["declared_slices"] == {"bybit_1": {"claude_desk": 0.5}}
    strat = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]["claude_desk"]
    assert strat["symbols"] == SIX
    acc = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    assert [a for a, c in acc.items() if "claude_desk" in (c.get("strategies") or [])] == ["bybit_1"]


def test_loader_reads_the_real_file():
    ae.load_allocation_config(force=True)
    cfg = ae.load_allocation_config()
    assert cfg["declared_slices"] == {"bybit_1": {"claude_desk": 0.5}}


def test_desk_is_not_blocked_when_a_strategy_leg_spent_the_pooled_budget():
    book = [_slice("trend_donchian_eth_4h", "long", 2.0)]   # risk 10 == the full pooled budget (1.0 * 2 * 5)
    pooled = _admit(book, "avax_pullback_2h")
    assert not pooled["ok"] and pooled["reason"] == "slice_budget_exhausted"
    desk = _admit(book, "claude_desk")
    assert desk["ok"] and desk["qty"] == pytest.approx(1.0)      # 0.5 of one trade, its own budget
    assert desk["detail"]["declared_slice"] is True


def test_strategy_leg_is_not_shrunk_by_an_open_desk_slice():
    book = [_slice("claude_desk", "long", 1.0)]
    out = _admit(book, "avax_pullback_2h")
    assert out["ok"] and out["qty"] == pytest.approx(2.0)         # full pooled budget, desk slice not counted


def test_desk_is_not_double_sized_against_its_own_open_slice():
    book = [_slice("claude_desk", "long", 1.0)]                    # holds 5 of its 5 budget
    # another declared-slice holder would be shrunk; the desk's own slice short-circuits to ok (own_slice_open)
    out = _admit(book, "claude_desk")
    assert out["ok"] and out["detail"]["admission"] == "own_slice_open"


def test_opposite_side_to_a_strategy_slice_is_still_refused_on_a_one_way_book():
    out = _admit([_slice("trend_donchian_eth_4h", "long", 1.0)], "claude_desk", direction="short")
    assert not out["ok"] and out["reason"] == "opposite_slice_one_way_book"


def test_pooled_legs_ignore_the_desk_weight_in_meta():
    meta = {"slice_allocation": {"bybit_1": {"weight": 0.5, "contenders": ["a", "claude_desk"]}}}
    out = _admit([], "a", meta=meta)
    assert out["ok"] and out["qty"] == pytest.approx(1.0)          # weight 0.5 of the full pooled budget


def test_planner_gives_the_desk_weight_one_and_does_not_dilute_the_pool():
    def cand(name, conf):
        return SimpleNamespace(strategy=name, symbol="ETHUSDT", side="long", entry=100.0, sl=95.0,
                               tp=110.0, confidence=conf, meta={})

    cands = [cand("claude_desk", 0.9), cand("a", 0.5), cand("b", 0.5)]
    elect = lambda c, **kw: SimpleNamespace(winning_intent=c[0], side="long")  # noqa: E731
    plan = plan_per_account_election(
        cands, accounts={"bybit_1": {"position_model": "slices", "strategies": ["claude_desk", "a", "b"]}},
        elect_fn=elect, slice_score_fn=lambda c: {"score": c.confidence},
    )
    alloc = plan["per_account"]["bybit_1"]["allocation"]
    assert alloc["claude_desk"] == 1.0
    assert alloc["a"] == pytest.approx(0.5) and alloc["b"] == pytest.approx(0.5)


def test_non_demo_accounts_in_the_yaml_are_ignored(tmp_path, monkeypatch):
    f = tmp_path / "slice_allocation.yaml"
    f.write_text("declared_slices:\n  bybit_1: {claude_desk: 0.5}\n  bybit_2: {claude_desk: 0.5}\n"
                 "  breakout_1: {claude_desk: 0.5}\n  alpaca_live: {x: 0.5}\n")
    monkeypatch.setattr(ae, "_ALLOC_CONFIG_PATH", f)
    cfg = ae.load_allocation_config(force=True)
    try:
        assert cfg["declared_slices"] == {"bybit_1": {"claude_desk": 0.5}}
    finally:
        monkeypatch.undo()
        ae.load_allocation_config(force=True)

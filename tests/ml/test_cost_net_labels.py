"""Cost-net triple-barrier labels (ML-TRAINING-PRINCIPLES-GAPS, practice M1).

Planted rows: the cost-net label's r_multiple must differ from the gross label's
by EXACTLY the full-cost-stack charge in R that
``src.runtime.execution_costs.roundtrip_cost_r`` computes — no second cost model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.datasets.families.exit_candidates import ExitCandidatesBuilder
from ml.datasets.families.setup_candidates import SetupCandidatesBuilder
from ml.datasets.labeling import BarrierConfig, label_event
from ml.datasets.labeling import cost_policy
from src.runtime.execution_costs import roundtrip_cost_r

from tests.ml.test_setup_candidates import _trending_closes, _write_market_raw

_COSTS = dict(fee_bps_roundtrip=11.0, slippage_bps_roundtrip=3.0,
              funding_bps_per_window=1.0, bar_hours=1.0)


def _path(kind: str):
    # entry 100; vol 0.01 → TP 101 / SL 99; 4 bars.
    if kind == "tp":
        return [100.5, 101.5, 100.0, 100.0], [99.5, 100.2, 100.0, 100.0], [100.2, 101.2, 100.0, 100.0]
    if kind == "sl":
        return [100.5, 100.1, 100.0, 100.0], [99.5, 98.8, 100.0, 100.0], [100.0, 99.0, 100.0, 100.0]
    return [100.3] * 4, [99.8] * 4, [100.1, 100.2, 100.3, 100.4]


@pytest.mark.parametrize("kind,barrier", [("tp", "tp"), ("sl", "sl"), ("to", "timeout")])
def test_net_r_is_gross_r_minus_exact_cost(kind, barrier):
    highs, lows, closes = _path(kind)
    kw = dict(entry_idx=0, entry_price=100.0, direction=1, vol=0.01)
    gross = label_event(highs, lows, closes, config=BarrierConfig(max_holding=3), **kw)
    net = label_event(highs, lows, closes, config=BarrierConfig(max_holding=3, **_COSTS), **kw)
    assert gross.barrier == net.barrier == barrier
    expected = roundtrip_cost_r(
        entry=100.0, exit_price=net.exit_price, risk=100.0 * 0.01,
        hold_hours=(net.holding_bars + 1) * 1.0,
        fee_bps_roundtrip=11.0, slippage_bps_roundtrip=3.0, funding_bps_per_window=1.0,
    )["total_cost_r"]
    assert expected > 0
    assert net.cost_r == pytest.approx(expected, abs=1e-12)
    assert gross.r_multiple - net.r_multiple == pytest.approx(expected, abs=1e-12)
    assert gross.cost_r == 0.0


def test_tp_that_does_not_cover_cost_labels_loss():
    # tiny barrier (vol 0.0005 → TP +0.05%) vs ~15 bps of cost
    highs, lows, closes = [100.06, 100.0], [99.99, 100.0], [100.04, 100.0]
    kw = dict(entry_idx=0, entry_price=100.0, direction=1, vol=0.0005)
    gross = label_event(highs, lows, closes, config=BarrierConfig(max_holding=1), **kw)
    net = label_event(highs, lows, closes, config=BarrierConfig(max_holding=1, **_COSTS), **kw)
    assert gross.barrier == net.barrier == "tp"
    assert gross.label == 1 and net.label == -1 and net.r_multiple < 0


def test_switch_reverts_to_gross(tmp_path):
    cfg = tmp_path / "ml_training.yaml"
    cfg.write_text("cost_net_labels: false\n")
    assert cost_policy.cost_net_enabled(cfg) is False
    cfg.write_text("cost_net_labels: true\n")
    assert cost_policy.cost_net_enabled(cfg) is True
    assert cost_policy.cost_net_enabled(tmp_path / "absent.yaml") is True
    # the shipped repo value is ON
    assert cost_policy.cost_net_enabled() is True


def test_hold_scope_charges_only_funding_and_non_perp_pays_none():
    perp = cost_policy.resolve_barrier_costs("BTCUSDT", "1h", scope="hold")
    assert perp["fee_bps_roundtrip"] == 0 and perp["slippage_bps_roundtrip"] == 0
    assert perp["funding_bps_per_window"] > 0
    fut = cost_policy.resolve_barrier_costs("MES", "15m")
    assert fut["funding_bps_per_window"] == 0 and fut["bar_hours"] == 0.25
    assert fut["fee_bps_roundtrip"] > 0 and fut["slippage_bps_roundtrip"] > 0


def _rows(builder, ddir, **kw):
    return list(builder.iter_rows(market_raw_path=ddir, vol_window_n=10, **kw))


def test_setup_candidates_default_on_and_exact_delta(tmp_path):
    ddir = _write_market_raw(tmp_path, _trending_closes(200))
    b = SetupCandidatesBuilder()
    gross = _rows(b, ddir, max_holding=8, cusum_threshold_mult=0.5, cost_net="false")
    net = _rows(b, ddir, max_holding=8, cusum_threshold_mult=0.5)  # default = config ON
    assert len(gross) == len(net) > 5
    assert {r["label_cost_basis"] for r in gross} == {"gross"}
    assert {r["label_cost_basis"] for r in net} == {"net"}
    for g, n in zip(gross, net):
        assert g["ts"] == n["ts"] and g["barrier_touched"] == n["barrier_touched"]
        assert n["label_cost_r"] > 0
        assert g["r_multiple"] - n["r_multiple"] == pytest.approx(n["label_cost_r"], rel=1e-9, abs=1e-9)
    assert sum(r["won"] for r in net) <= sum(r["won"] for r in gross)


def test_exit_candidates_default_on_funding_only(tmp_path):
    ddir = _write_market_raw(tmp_path, _trending_closes(200))
    b = ExitCandidatesBuilder()
    gross = _rows(b, ddir, cost_net=False)
    net = _rows(b, ddir)
    assert len(gross) == len(net) > 5
    assert {r["label_cost_basis"] for r in net} == {"net"}
    for g, n in zip(gross, net):
        assert g["fwd_r_multiple"] - n["fwd_r_multiple"] == pytest.approx(n["label_cost_r"], rel=1e-9, abs=1e-9)


def test_built_dataset_records_basis(tmp_path):
    ddir = _write_market_raw(tmp_path, _trending_closes(200))
    paths = SetupCandidatesBuilder().build(
        output_dir=tmp_path / "out", version="v1", source="test",
        symbol_scope="BTCUSDT", timeframe="1h",
        market_raw_path=ddir, vol_window_n=10, max_holding=8, cusum_threshold_mult=0.5,
    )
    rows = [json.loads(l) for l in Path(paths.data).read_text().splitlines() if l]
    assert rows and all(r["label_cost_basis"] == "net" for r in rows)

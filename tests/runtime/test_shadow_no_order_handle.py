"""ML-SHADOW-NO-ORDER-HANDLE: a shadow-stage model gets no handle to the order path, by construction.

Operator 2026-11-12 (Gates tab, CI-TEST-SHADOW-NEVER-ORDERS): "This should be handled through
structuring the functionality correctly, not with a gate". The order path reads ONE conviction block,
``meta["conviction_influencing"]``, built from ``influencing_scores(captured)`` (advisory+ only, no
flag). The observe-only blend with shadow scores stays in ``meta["conviction"]`` for the soak and
analytics. These tests describe that structure; they are a report, not a required check.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime import allocator_ev as ae
from src.runtime import conviction_sizing as cs
from src.runtime.conviction_inputs import influencing_scores
from src.runtime.strategy_signal_builders import conviction_stamp, influencing_conviction_block

_SHADOW = {"trade-outcome-x": {"stage": "shadow", "score": 0.05},
           "setup-quality-y": {"stage": "shadow", "score": -2.5}}
_LARGE = {"balance_usd": 100000.0, "available_usd": 1_000_000.0,
          "total_account_usd": 1_000_000.0, "leverage": 1, "market_type": "linear"}


def test_influencing_scores_keeps_only_influence_stages():
    scores = {**_SHADOW, "trade-outcome-a": {"stage": "advisory", "score": 0.7},
              "trade-outcome-c": {"stage": "candidate", "score": 0.7}, "junk": "x"}
    assert set(influencing_scores(scores)) == {"trade-outcome-a"}


def test_order_path_block_is_built_without_shadow_inputs():
    blk = influencing_conviction_block("trend_donchian", 0.6, _SHADOW, direction="long")
    assert set(blk["inputs_used"]) == {"c_strat"}
    assert not any(isinstance(v, list) for v in blk["provenance"].values())  # no head slot at all
    # the observe-only blend DOES see them (the soak number is intact)
    obs = conviction_stamp("trend_donchian", 0.6, _SHADOW, direction="long")
    assert {"c_wr", "c_setup"} <= set(obs["inputs_used"])
    assert obs["influencing"] == blk["conviction"]


def test_sizing_reads_the_order_path_block_not_the_observed_blend():
    pkg = SimpleNamespace(entry=100.0, sl=90.0, symbol="BTCUSDT", direction="long", strategy="s",
                          meta={"conviction": {"conviction": 0.05}})          # observed only
    q, rec = cs.compute_conviction_sizing(pkg, 0.5, **_LARGE)
    assert q is None and rec["action"] == "no_conviction"                        # nothing to act on
    pkg.meta["conviction_influencing"] = {"conviction": 0.9}
    q2, rec2 = cs.compute_conviction_sizing(pkg, 0.5, **_LARGE)
    assert rec2["conviction"] == pytest.approx(0.9)


def test_slice_allocation_ignores_the_observed_blend():
    def intent(meta):
        return SimpleNamespace(strategy="s", confidence=0.6, entry=100.0, sl=95.0, tp=110.0, meta=meta)
    kw = {"config": ae.DEFAULT_ALLOCATION_CONFIG, "counts": {"s": (0, 0)}}
    base = ae.intent_allocation_score(intent({}), **kw)
    shadow_fed = ae.intent_allocation_score(
        intent({"conviction": {"inputs_used": {"c_strat": 0.6, "c_wr": 0.01, "c_setup": 0.01}}}), **kw)
    assert shadow_fed["score"] == pytest.approx(base["score"])
    assert "c_wr" not in shadow_fed["inputs"]

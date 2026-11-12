"""REGIME-VOL-SPEC-ADVISORY-ONLY (closes PI-20261029-Q17QWHDZ-0003).

The frozen vol label (``intent.vol_regime``) is built from SHADOW-stage regime
heads' frozen bucket edges (``vol_detector.resolve_vol_specs``). A shadow head
is observe-only under the ladder, so promoting one (candidate -> shadow) for a
symbol whose strategies have authored ``trend_vol`` cells must not change ANY
part of the enforcing hard gate's verdict: not which intents are dropped, and
not the audit row the gate writes.

Planted/clean pair: the same intents run through the hard gate twice, once
with a planted shadow spec (frozen label resolves ``volatile`` — the OFF cell's
label) and once clean (no shadow spec -> frozen ``unknown``). Every mode, with
the advisory head absent (ML ``unknown``) and present. The kept set and the
``regime_hard_gate`` rows must be identical. Before the fix the frozen label
was fed to ``would_gate`` (enforcement refused only by a later guard), so the
planted run's audit row carried ``vol_gated: true`` / ``vol_regime: volatile``
and the pair differed.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import src.runtime.intents as intents_mod
from src.runtime.intents import StrategyIntent
from src.runtime.regime.vol_detector import detect_vol_regime

# trend_donchian: 1-D trending short OFF (trend axis gates the short) and the
# 2-D (trending, volatile) long OFF cell — the live cell shape.
_POLICY = {
    "trending": {"trend_donchian": {"long": "on", "short": "off"}},
    "trend_vol": {"trending": {"volatile": {"trend_donchian": {"long": "off", "short": "off"}}}},
}

# A shadow head's frozen spec whose lowest edge sits below the planted tape's
# vol, so the frozen label resolves ``volatile``.
_SHADOW_SPEC = {
    ("BTCUSDT", "1H"): {
        "symbol": "BTCUSDT", "timeframe": "1h",
        "vol_bucket_labels": ["vol_b0", "vol_b1"],
        "vol_bucket_edges": [1e-9],
        "vol_window_n": 20,
        "model_id": "btc-regime-1h-planted-shadow",
    },
}


def _candles():
    import pandas as pd

    closes = [100.0 * (1.0 + 0.01 * ((-1) ** i)) for i in range(60)]
    return pd.DataFrame({"close": closes})


def _frozen_label(specs: dict) -> str:
    out = detect_vol_regime(_candles(), symbol="BTCUSDT", timeframe="1h", specs=specs)
    return out["vol_regime"]


def _intents(vol_regime: str) -> List[StrategyIntent]:
    return [
        StrategyIntent(
            strategy="trend_donchian", symbol="BTCUSDT", side=side, target_qty=1.0,
            regime="trending", adx_14=30.0, vol_regime=vol_regime,
            entry=70000.0, sl=69000.0 if side == "long" else 71000.0,
            tp=72000.0 if side == "long" else 68000.0,
        )
        for side in ("long", "short")
    ]


def _run(vol_regime: str, mode: str, ml: Dict[str, Any]):
    rows: List[Dict[str, Any]] = []
    with patch.object(intents_mod, "_REGIME_POLICY_CACHE", _POLICY), \
         patch.object(intents_mod, "_regime_router_active", return_value=True), \
         patch.object(intents_mod, "_regime_ml_verdict_mode", return_value=mode), \
         patch("src.runtime.regime.ml_vol_regime_for_symbol", return_value=ml), \
         patch("src.utils.signal_audit_logger.log_signal",
               side_effect=lambda p, *a, **k: rows.append(dict(p))):
        kept = intents_mod._hard_regime_gate(tuple(_intents(vol_regime)))
    gate_rows = [r for r in rows if r.get("event") == "regime_hard_gate"]
    for r in gate_rows:
        r.pop("vol_regime_frozen", None)  # the audit-only frozen echo differs by design
    return [(i.strategy, i.side) for i in kept], gate_rows


_ML_UNKNOWN = {"vol_regime": "unknown", "source": "unavailable", "model_id": None}
_ML_CALM = {"vol_regime": "calm", "p_volatile": 0.1,
            "source": "ml-advisory:btc-regime-15m-adv", "model_id": "btc-regime-15m-adv"}


def test_planted_shadow_spec_really_changes_the_frozen_label():
    # Guard the premise: the plant must move the frozen label onto the OFF cell.
    assert _frozen_label(_SHADOW_SPEC) == "volatile"
    assert _frozen_label({}) == "unknown"


@pytest.mark.parametrize("mode", ["off", "shadow", "use"])
@pytest.mark.parametrize("ml", [_ML_UNKNOWN, _ML_CALM], ids=["no-advisory", "advisory-calm"])
def test_shadow_promotion_leaves_hard_gate_unchanged(mode, ml):
    planted = _run(_frozen_label(_SHADOW_SPEC), mode, ml)
    clean = _run(_frozen_label({}), mode, ml)
    assert planted == clean


def test_frozen_label_never_reaches_the_hard_gate_verdict():
    # No advisory head: the trend axis still drops the short; the long survives
    # and the dropped row records the vol axis as not evaluated.
    kept, rows = _run("volatile", "use", _ML_UNKNOWN)
    assert kept == [("trend_donchian", "long")]
    assert len(rows) == 1 and rows[0]["side"] == "short"
    assert rows[0]["vol_regime"] == "unknown"
    assert rows[0]["vol_gated"] is False and rows[0]["vol_enforced"] is False
    assert rows[0]["vol_label_source"] == "frozen"


def test_advisory_label_still_enforces_the_vol_cell():
    # Control: an ADVISORY volatile label drops the long via the vol cell.
    ml_vol = {"vol_regime": "volatile", "p_volatile": 0.9,
              "source": "ml-advisory:btc-regime-15m-adv", "model_id": "btc-regime-15m-adv"}
    kept, rows = _run("calm", "use", ml_vol)
    assert kept == []
    long_row = next(r for r in rows if r["side"] == "long")
    assert long_row["vol_enforced"] is True and long_row["vol_regime"] == "volatile"
    assert long_row["vol_label_source"] == "ml"

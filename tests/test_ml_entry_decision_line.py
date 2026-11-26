"""ML-ENTRY-SERVE-FIXES: the per-symbol ml_entry decision line (logging only) separates refused reasons from no_signal.
2026-11-26: a no_signal line carries the model's numbers from the below_tau reason, and an evaluated line the package's."""
from src.runtime.strategy_signal_builders import _ml_entry_decision_line as L


def test_outcomes():
    assert L("SPY", 400, side="long") == "ml_entry_decision symbol=SPY bars=400 outcome=evaluated side=long"
    assert L("GDX", 203, reason=ValueError("insufficient_bars:203")) == \
        "ml_entry_decision symbol=GDX bars=203 outcome=refused: insufficient_bars:203"
    assert L("QQQ", 400, reason="not_a_decision_bar").endswith("outcome=no_decision_bar")
    assert L("QQQ", 400, reason="market_closed").endswith("outcome=refused: market_closed")


def test_no_signal_line_carries_the_prediction():
    line = L("BTCUSDT", 399, reason=ValueError("below_tau:pred=0.0412;p_long=0.0412;p_short=-0.0300;tau=0.1000;n_ref=52"))
    assert line == ("ml_entry_decision symbol=BTCUSDT bars=399 outcome=no_signal "
                    "(pred=0.0412;p_long=0.0412;p_short=-0.0300;tau=0.1000;n_ref=52)")
    assert "outcome=no_signal" in line                                   # existing greps keep matching
    assert L("QQQ", 400, reason=ValueError("below_tau")).endswith("outcome=no_signal")


def test_evaluated_line_carries_package_numbers():
    meta = {"p_long": 0.151, "p_short": -0.02, "tau": 0.1, "n_reference": 52, "atr14": 9.0}
    assert L("SOLUSDT", 399, side="long", meta=meta) == \
        "ml_entry_decision symbol=SOLUSDT bars=399 outcome=evaluated side=long (p_long=0.151;p_short=-0.02;tau=0.1;n_reference=52)"


def test_logging_only_no_behaviour_change():
    """The line is a pure function of its inputs: it never raises on odd input and returns a str, so it cannot change the
    decision path it reports on (the caller logs the return value and continues)."""
    for args, kw in (((None, None), {}), (("X", 0), {"reason": object()}), (("X", 0), {"side": None, "meta": "not-a-dict"})):
        assert isinstance(L(*args, **kw), str)

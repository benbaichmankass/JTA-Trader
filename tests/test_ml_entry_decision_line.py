"""ML-ENTRY-SERVE-FIXES: the per-symbol ml_entry decision line (logging only) separates refused reasons from no_signal."""
from src.runtime.strategy_signal_builders import _ml_entry_decision_line as L


def test_outcomes():
    assert L("SPY", 400, side="long") == "ml_entry_decision symbol=SPY bars=400 outcome=evaluated side=long"
    assert L("GDX", 203, reason=ValueError("insufficient_bars:203")) == \
        "ml_entry_decision symbol=GDX bars=203 outcome=refused: insufficient_bars:203"
    assert L("QQQ", 400, reason=ValueError("below_tau:pred=0.01;p_long=0.1;p_short=0.2")).endswith("outcome=no_signal")
    assert L("QQQ", 400, reason="not_a_decision_bar").endswith("outcome=no_decision_bar")
    assert L("QQQ", 400, reason="market_closed").endswith("outcome=refused: market_closed")

"""ledger_row: the per-trade gross-R row the moving-TP prop gate consumes (ledger_ethsol.jsonl shape)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_entry_tp_revision as T  # noqa: E402


def test_short_take_profit_row():
    t = SimpleNamespace(symbol="ETHUSDT", side="short")
    r = T.ledger_row(t, 100.0, 2.0, -1, 94.0, 3, 2, 6.0, "a", "b", 2.9)
    assert r["gross_r"] == 3.0 and r["sl"] == 102.0 and r["exit_reason"] == "take_profit"
    assert r["mfe_r"] == 3.0 and r["leg"] == "ml_entry" and r["direction"] == "short"


def test_long_sl_row_keys_match_v1_ledger():
    t = SimpleNamespace(symbol="SOLUSDT", side="long")
    r = T.ledger_row(t, 100.0, 2.0, 1, 98.0, 1, 1, 0.5, "a", "b", -1.08)
    assert r["gross_r"] == -1.0 and r["sl"] == 98.0 and r["mfe_r"] == 0.25
    v1 = {"leg", "strategy", "symbol", "direction", "entry_time", "exit_time", "entry", "sl", "exit_reason", "gross_r", "mfe_r", "net_r_evidence"}
    assert v1 <= set(r)

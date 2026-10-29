"""ML-REAL-MONEY-OVERLAY: the demotion CUSUM's live join (shadow rows -> closed trades) and its relay parsing."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("overlay_cusum_join", REPO / "scripts/ops/overlay_cusum_join.py")
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)


def test_self_test_passes():
    assert J._self_test() == 0


def test_relay_trades_comment_shape_parses_and_costs_are_netted():
    """The relay's `journal?table=trades` comment is a ```json list of full trade rows (SELECT *)."""
    rows = [{"id": 9, "timestamp": "2026-10-29T06:23:34+00:00", "symbol": "SOLUSDT", "direction": "long",
             "account_id": "bybit_portfolio", "strategy_name": "trend_donchian_sol_prop", "status": "closed",
             "order_package_id": "pkg-11c1100f6cbb4667", "pnl": 3.0, "fee_taker_usd": 4.0,
             "funding_paid_usd": None, "cost_source": "estimate", "closed_at": "2026-10-29T12:00:00+00:00"}]
    comment = "**vm-diag-snapshot** result\n\n## `journal?table=trades&limit=30`\n```json\n" + json.dumps(rows) + "\n```\n"
    t = J.load_trades(comment)
    assert len(t) == 1 and J.net_pnl(t[0]) == -1.0  # a gross win is a LOSS once the taker fee is netted


def test_ambiguous_time_window_match_is_dropped_not_guessed():
    s = {"action": "annotate", "strategy_id": "L", "symbol": "ETHUSDT", "direction": "long", "account": "a",
         "would_be_multiplier": 0.5, "logged_at_utc": "2026-10-30T12:00:00+00:00"}
    t = {"id": 1, "status": "closed", "closed_at": "x", "account_id": "a", "strategy_name": "L", "symbol": "ETHUSDT",
         "direction": "long", "pnl": 1.0, "timestamp": "2026-10-30T12:02:00+00:00", "order_package_id": "p"}
    j = J.join([s, dict(s)], [t])
    assert j["n_joined"] == 0 and j["n_ambiguous_dropped"] == 1

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


def test_a_truncated_relay_block_reads_incomplete_never_zero(tmp_path):
    """Relay #21272 (2026-10-29): a batched comment cut the trades block mid-JSON; the loader read 0 rows and the
    join said `no_closed_trades`. A cut block must read `incomplete_read` and exit 2 (could not look)."""
    cut = ("## `journal?table=trades&limit=30`\n```json\n[\n  {\"id\": 1, \"order_package_id\": \"p\", \"pnl\": 1.0,\n"
           "    \"status\": \"clo\n```\n_(`rows`: ONLY THE FIRST 1 of 30 element(s) are shown; the LAST 29 are NOT. "
           "Re-request with a smaller `lines`/`limit` to see the tail.)_\n")
    assert J.relay_completeness(cut) == {"unparsed_blocks": 1, "truncated": True, "complete": False}
    sh, tr = tmp_path / "s.md", tmp_path / "t.md"
    sh.write_text("```json\n{\"name\": \"overlay_shadow\", \"present\": false, \"lines\": []}\n```\n")
    tr.write_text(cut)
    assert J.main(["--shadow", str(sh), "--trades", str(tr), "--cusum"]) == 2
    good = "```json\n" + json.dumps([{"id": 2, "order_package_id": "q", "pnl": 1.0, "status": "closed"}]) + "\n```\n"
    assert J.relay_completeness(good)["complete"] is True


def test_paired_challenger_per_package_and_applied_rescale():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ocj_pc", Path(__file__).resolve().parents[1] / "scripts/ops/overlay_cusum_join.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ch = lambda mult: [{"artifact": "overlay_td_ev.json", "would_be_multiplier": mult}]
    rows = [
        # reduce leg, base cut 0.5, challenger keeps 1.0, realised R +0.4 at half size -> d = (1-0.5)/0.5*0.4 = +0.4
        {"strategy": "leg_r", "order_package_id": "p1", "account": "a1", "multiplier": 0.5, "net_R": 0.4, "challengers": ch(1.0)},
        {"strategy": "leg_r", "order_package_id": "p1", "account": "a2", "multiplier": 0.5, "net_R": 0.4, "challengers": ch(1.0)},
        # annotate leg, base would cut, challenger keeps, realised R -1.0 at full size -> d = (1-0.5)/1*-1 = -0.5
        {"strategy": "leg_a", "order_package_id": "p2", "account": "a1", "multiplier": 0.5, "net_R": -1.0, "challengers": ch(1.0)},
        # agree -> d 0
        {"strategy": "leg_a", "order_package_id": "p3", "account": "a1", "multiplier": 1.0, "net_R": 2.0, "challengers": ch(1.0)},
        {"strategy": "leg_a", "order_package_id": "p4", "account": "a1", "multiplier": 1.0, "net_R": None, "challengers": ch(1.0)},
        {"strategy": "leg_a", "order_package_id": "p5", "account": "a1", "multiplier": 1.0, "net_R": 1.0, "challengers": []},
    ]
    out = m.paired_challenger(rows, "overlay_td_ev.json", {"leg_r"})
    assert out["all_packages"]["n"] == 3 and out["disagreement_packages"]["n"] == 2
    assert abs(out["disagreement_packages"]["mean_r"] - (-0.05)) < 1e-9
    assert out["skipped"] == {"no_net_R": 1, "no_challenger": 1, "duplicate_package": 1}

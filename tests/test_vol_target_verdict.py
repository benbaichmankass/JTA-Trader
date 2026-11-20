"""vol_target_verdict (IR-VOL-TARGET-SIZING-STAGE0 / P2-R5): the registered rule, the calendar blocks and the verdict.json contract.

Synthetic trade ledgers through the real overlay (``backtest_vol_target.run_vol_target``) and the real book builder; no
candles, no harness. The candle + harness path is exercised by the units themselves on the trainer.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import vol_target_verdict as vtv

RULE = ["--dsharpe-bar", "0.10", "--n-floor", "100", "--block-majority", "3"]


def _ledger(path: Path, n: int, seed: int = 5) -> Path:
    rng = random.Random(seed)
    t = datetime(2023, 1, 2, tzinfo=timezone.utc)
    with path.open("w") as fh:
        for _ in range(n):
            t += timedelta(hours=rng.randint(10, 40))
            fh.write(json.dumps({"entry_time": t.isoformat(), "exit_time": (t + timedelta(hours=8)).isoformat(),
                                 "net_r": rng.gauss(0.05, 1.0)}) + "\n")
    return path


def _run(tmp_path, trades, extra=()):
    out = tmp_path / "out"
    rc = vtv.main(["--leg", "trend_donchian_eth_4h", "--trades", str(trades), "--cost-symbol", "ETHUSDT",
                   "--out", str(out), *RULE, *extra])
    assert rc == 0
    return json.loads((out / "verdict.json").read_text())


def test_verdict_json_carries_the_script_run_contract(tmp_path):
    v = _run(tmp_path, _ledger(tmp_path / "t.jsonl", 400))
    assert v["verdict"] in ("pass", "fail", "indeterminate")
    assert v["read_state"] == "measured" and v["n"] == 400
    assert "400 Stage-0 trades" in v["population"]
    m = v["measurement"]
    assert len(m["block_detail"]) == 4 and m["blocks"] == 4
    assert m["rule_thresholds"] == {"dsharpe_bar": 0.10, "n_floor": 100, "blocks": 4, "block_majority": 3}
    assert "series" not in m["overlay"], "the per-day series stays out of verdict.json"


def test_below_the_floor_is_indeterminate_never_fail(tmp_path):
    v = _run(tmp_path, _ledger(tmp_path / "t.jsonl", 60))
    assert v["verdict"] == "indeterminate" and v["measurement"]["label"] == "underpowered"


def test_thresholds_are_required_flags(tmp_path):
    with pytest.raises(SystemExit):
        vtv.main(["--leg", "x", "--out", str(tmp_path)])


def test_the_rule_needs_all_three_clauses():
    ov = {"sharpe_delta": 0.3, "baseline": {"max_drawdown_r": 8.0}, "vol_targeted": {"max_drawdown_r": 7.0}}
    blocks = [{"dsharpe": d} for d in (0.2, 0.1, 0.4, -0.1)]
    kw = {"dsharpe_bar": 0.10, "n_floor": 100, "block_majority": 3}
    assert vtv.decide(200, ov, blocks, **kw)["verdict"] == "pass"
    assert vtv.decide(200, {**ov, "sharpe_delta": 0.09}, blocks, **kw)["verdict"] == "fail"
    assert vtv.decide(200, {**ov, "vol_targeted": {"max_drawdown_r": 8.01}}, blocks, **kw)["verdict"] == "fail"
    assert vtv.decide(200, ov, [{"dsharpe": d} for d in (0.2, -0.1, 0.4, -0.1)], **kw)["verdict"] == "fail"


def test_blocks_are_calendar_spans_not_equal_counts():
    dates = [f"2024-01-{d:02d}" for d in range(1, 31)] + ["2024-12-31"]
    r = [0.1] * len(dates)
    b = vtv.block_sharpes(dates, r, r, 4)
    assert b[0]["n_days"] == 30 and b[-1]["n_days"] == 1, "a calendar split puts the dense January in block 0"


def test_self_test_passes():
    assert vtv._self_test() == 0

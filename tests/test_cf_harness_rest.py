"""CF-C2-HARNESS-REST: the squeeze, fade, ict_scalp and vwap harnesses grade each trade on the counterfactual arms
(schema cf_trade/1) behind an opt-in ``--cf`` flag, without changing any pre-existing output.

Golden = each harness's emit file on origin/main BEFORE this change, for the fixed synthetic run in tests/data/cf_c1_trend_fixture.csv
(squeeze 21 trades, fade 79, ict_scalp 6, vwap 59). The ``--cf`` tests fail without the change (unknown flag / no `cf` key); the
default tests pin that nothing else moved."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_harness as ch  # noqa: E402

FIX = REPO / "tests" / "data" / "cf_c1_trend_fixture.csv"
D = REPO / "tests" / "data"
STD = ["--data", str(FIX), "--timeframe", "1h", "--symbol", "BTCUSDT"]
HARNESSES = {
    "squeeze": ([sys.executable, str(REPO / "scripts/backtest_squeeze.py"), *STD], {}, 21),
    "fade": ([sys.executable, str(REPO / "scripts/backtest_fade.py"), *STD], {}, 79),
    "ict_scalp": ([sys.executable, str(REPO / "scripts/backtest_ict_scalp.py"), *STD], {}, 6),
    "vwap": ([sys.executable, "-m", "src.backtest.run_backtest_vwap", "--no-htf"], {"BACKTEST_DATA_PATH": str(FIX)}, 59),
}
KEYS = {"schema", "grader_schema_version", "trade_key", "status", "reason", "path", "cost", "arms", "random_control",
        "post_exit", "fidelity", "provenance"}


def _run(tmp_path, name, *flags):
    cmd, env, _ = HARNESSES[name]
    out = tmp_path / f"{name}.jsonl"
    subprocess.run([*cmd, "--emit-trades", str(out), *flags], check=True, capture_output=True, cwd=REPO,
                   env={**os.environ, **env})
    return [json.loads(ln) for ln in out.read_text().splitlines()]


def _same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, float) and isinstance(b, float):
        return a == pytest.approx(b, rel=1e-9, abs=1e-12)
    return a == b


def _gold(name):
    return [json.loads(ln) for ln in (D / f"cf_c2_{name}_emit_golden.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("name", list(HARNESSES))
def test_default_run_matches_pre_change_output_without_a_cf_key(tmp_path, name):
    rows, gold = _run(tmp_path, name), _gold(name)
    assert len(rows) == len(gold) == HARNESSES[name][2] and all("cf" not in r for r in rows)
    assert all(_same(r, g) for r, g in zip(rows, gold))


@pytest.mark.parametrize("name", list(HARNESSES))
def test_cf_only_adds_the_cf_key_and_rows_match_the_schema(tmp_path, name):
    rows, gold = _run(tmp_path, name, "--cf"), _gold(name)
    assert len(rows) == len(gold) == HARNESSES[name][2]
    n_graded = 0
    for r, g in zip(rows, gold):
        assert _same({k: v for k, v in r.items() if k != "cf"}, g)
        c = r["cf"]
        assert KEYS <= set(c) and c["schema"] == "cf_trade/1" and len(c["trade_key"]) == 40
        if c["status"] == "graded":
            n_graded += 1
            assert len(c["arms"]["alt_brackets"]) >= 19 and {"verdict", "r_diff", "resolved"} == set(c["post_exit"]["verdict"])
        else:
            assert c["reason"]                                    # an ungradable row says why; it is never dropped
    assert n_graded >= 0.9 * len(rows), (name, n_graded, len(rows))


def test_stage0_appends_cf_for_every_cf_harness():
    assert set(ch.CF_HARNESSES) == {"backtest_trend.py", "backtest_squeeze.py", "backtest_fade.py", "backtest_ict_scalp.py",
                                    "run_backtest_vwap.py"}

"""Row ML-ENTRY-LTR-OUTCOME-TABLE: live reviews of ml_entry packages are PRICED from its Stage-0 ledger, not judgement-only.

Before: ``live_review_outcomes.py --leg ml_entry`` read the evidence record's source_run (a one-line graded RESULT, no
per-trade rows) and died (KeyError 'direction'; later FileNotFoundError on the annotated path), so priced_options was null.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "comms/strategy_evidence/ltr_corpus"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lro = _load("lro_ml_entry", "scripts/research/live_review_outcomes.py")
B = _load("build_ltr_corpus_ml", "scripts/research/build_ltr_corpus.py")
P = _load("lrp_ml_entry", "scripts/ops/live_review_packet.py")

T0 = pd.Timestamp("2026-01-01 00:00", tz="UTC")


def _frame(closes_hi_lo):
    idx = [T0 + pd.Timedelta(hours=i) for i in range(len(closes_hi_lo))]
    return pd.DataFrame([(c, h, lo, c) for c, h, lo in closes_hi_lo], index=pd.DatetimeIndex(idx, name="timestamp"),
                        columns=["open", "high", "low", "close"])


def _long(sym, net_r, exit_i, mfe_r):
    return {"symbol": sym, "direction": "long", "entry": 100.0, "sl": 99.0, "mfe_r": mfe_r, "exit_reason": "time",
            "entry_time": str(T0), "exit_time": str(T0 + pd.Timedelta(hours=exit_i)), "net_r": net_r,
            "cost_fee_r": 0.11, "cost_slippage_r": 0.03, "cost_funding_r": 0.0}


def test_committed_corpus_reproduces_the_evidence_record():
    man = json.loads((CORPUS / "ml_entry__corpus.json").read_text())
    body = (CORPUS / "ml_entry__trades.jsonl").read_text()
    rows = [json.loads(x) for x in body.splitlines() if x.strip()]
    rec = json.loads((REPO / "comms/strategy_evidence/ml_entry.json").read_text())
    assert man["n_trades"] == len(rows) == rec["n_trades_oos"] == 907
    assert man["trades_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert man["source_file"].endswith("ml_entry_5sym.jsonl")      # built from the committed gate ledger
    mean = sum(r["net_r"] for r in rows) / len(rows)
    assert mean == pytest.approx(0.0271, abs=5e-5)                   # the record's arm A (extend-only) expectancy
    assert set(man["symbols"]) == {"BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"}
    assert "structure SL" in man["note"]                              # what the corpus does NOT model is stated


def test_from_ledger_splits_costs_so_they_sum_to_net_exactly():
    rows = B.from_ledger([{"symbol": "X", "direction": "short", "entry": 100.0, "sl": 102.0, "gross_r": 1.0,
                           "net_r_evidence": 0.9}])
    r = rows[0]
    assert r["net_r"] == 0.9 and "net_r_evidence" not in r
    assert r["cost_fee_r"] == pytest.approx(11 * 100 / 2 / 1e4) and r["cost_slippage_r"] == pytest.approx(3 * 100 / 2 / 1e4)
    assert r["gross_r"] - r["cost_fee_r"] - r["cost_slippage_r"] - r["cost_funding_r"] == pytest.approx(0.9, abs=1e-6)
    with pytest.raises(ValueError):
        B.from_ledger([{"symbol": "X", "entry": 1, "sl": 2, "gross_r": 0}])


def test_pooled_rows_replay_on_their_own_symbols_candles():
    # A rallies to +2R then fades; B never moves. One shared frame would replay B's trade on A's prices.
    a = _frame([(100, 100, 100), (101, 102, 100.5), (100.2, 100.6, 99.9), (100.1, 100.3, 99.95)])
    b = _frame([(100, 100, 100), (100, 100.1, 99.9), (100, 100.1, 99.9), (100, 100.1, 99.9)])
    trades = [_long("AAA", 0.0, 3, 2.0), _long("BBB", -0.1, 3, 0.1)]
    res = lro.build_table(trades, {"AAA": a, "BBB": b}, side="long", open_r=1.0, peak_r=1.5, bars_held=None,
                          atr_stop_mult=2.0, tighten=["atr:1.0"], n_floor=1, close=True)
    pop = res["population"]
    assert pop["comparable"] == 1 and pop["never_reached_peak"] == 1 and pop["no_candles"] == 0
    names = [o["action"] for o in res["options"]]
    assert names == ["hold", "tighten", "close"]
    close = res["options"][2]
    assert close["state"] == "measured" and close["spec"] == "close"
    # CLOSE banks open_r (1.0) on the review bar, minus fee + slippage (+ funding, 0 here)
    assert close["mean_r"] == pytest.approx(1.0 - 0.11 - 0.03, abs=1e-4)
    # a symbol with no frame is no_candles, never silently priced on another symbol
    res2 = lro.build_table([_long("CCC", 0.0, 3, 2.0)], {"AAA": a}, side="long", open_r=1.0, peak_r=1.5,
                           bars_held=None, atr_stop_mult=2.0, tighten=[], n_floor=1)
    assert res2["population"]["no_candles"] == 1 and res2["population"]["comparable"] == 0


def test_symbol_filter_is_counted():
    a = _frame([(100, 100, 100), (101, 102, 100.5), (100.2, 100.6, 99.9), (100.1, 100.3, 99.95)])
    res = lro.build_table([_long("AAA", 0.0, 3, 2.0), _long("BBB", 0.0, 3, 2.0)], {"AAA": a, "BBB": a}, side="long",
                          open_r=1.0, peak_r=1.5, bars_held=None, atr_stop_mult=2.0, tighten=[], n_floor=1, symbol="AAA")
    assert res["population"]["symbol_excluded"] == 1 and res["population"]["comparable"] == 1


def test_result_row_source_run_is_a_named_error_not_keyerror(tmp_path):
    (tmp_path / "comms/strategy_evidence").mkdir(parents=True)
    (tmp_path / "res.jsonl").write_text(json.dumps({"measurement": {}, "verdict": "pass"}) + "\n")
    (tmp_path / "comms/strategy_evidence/legx.json").write_text(json.dumps({"source_run": "res.jsonl (run https://x)"}))
    with pytest.raises(FileNotFoundError, match="not a per-trade corpus"):
        lro.load_trades("legx", repo=tmp_path)


def test_atr_stop_mult_falls_back_to_risk_over_atr():
    assert P.atr_stop_mult_of({"atr_stop_mult": 1.5}) == 1.5
    assert P.atr_stop_mult_of({"risk_per_unit": 0.02, "atr14": 0.01}) == 2.0      # ml_entry: SL = 2 x ATR14
    assert P.atr_stop_mult_of({"atr14": 0.01}) is None


def test_open_ml_entry_package_is_priced_end_to_end():
    """The row's done-condition on the COMMITTED corpus + candles: hold / tighten / close all measured, n stated."""
    if any(lro.find_candles(s, "1h", widest_span=True) is None
           for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT")):
        pytest.skip("research candle files not in this checkout (sparse VM checkout)")
    trades, src = lro.load_trades("ml_entry", corpus="auto")
    assert src.startswith(lro.LTR_CORPUS_DIR)
    cand = {s: lro.load_candles(lro.find_candles(s, "1h", widest_span=True)) for s in {t["symbol"] for t in trades}}
    res = lro.build_table(trades, cand, side="short", open_r=0.4, peak_r=0.8, bars_held=None, atr_stop_mult=2.0,
                          tighten=["atr:1.0"], close=True)
    acts = {o["action"]: o for o in res["options"]}
    assert set(acts) == {"hold", "tighten", "close"}
    assert all(o["state"] == "measured" and o["n"] >= lro.N_FLOOR for o in acts.values())
    assert res["population"]["corpus_trades"] == 907 and res["population"]["no_candles"] == 0

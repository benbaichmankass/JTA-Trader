"""LTR-CORPUS-REAL-MONEY-LEGS: full-history corpora + the packet builder pricing from them."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "comms/strategy_evidence/ltr_corpus"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("lrp_corpus", "scripts/ops/live_review_packet.py")
B = _load("build_ltr_corpus_t", "scripts/research/build_ltr_corpus.py")

LEGS = sorted(p.name[:-len("__corpus.json")] for p in CORPUS.glob("*__corpus.json"))


@pytest.mark.parametrize("leg", LEGS)
def test_manifest_matches_trades(leg):
    man = json.loads((CORPUS / f"{leg}__corpus.json").read_text())
    body = (CORPUS / f"{leg}__trades.jsonl").read_text()
    rows = [json.loads(x) for x in body.splitlines() if x.strip()]
    assert man["n_trades"] == len(rows) > 0
    assert man["trades_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert abs(man["net_total_r"] - sum(r["net_r"] for r in rows)) < 1e-3
    for r in rows:  # the cost components the option table reads, net of all three
        assert abs(r["net_r"] - (r["gross_r"] - r["cost_fee_r"] - r["cost_slippage_r"] - r["cost_funding_r"])) < 1e-3


def test_recost_scales_only_the_fee():
    t = {"gross_r": 1.0, "cost_fee_r": 0.015, "cost_slippage_r": 0.007, "cost_funding_r": 0.02,
         "net_r": 1.0 - 0.015 - 0.007 - 0.02}
    (o,) = B.recost([t], 7.5, 11.0)
    assert o["cost_fee_r"] == pytest.approx(0.022)
    assert o["net_r"] == pytest.approx(1.0 - 0.022 - 0.007 - 0.02, abs=1e-4)
    assert o["net_r_fee_only"] == pytest.approx(1.0 - 0.022, abs=1e-4)
    assert (o["cost_slippage_r"], o["cost_funding_r"], o["gross_r"]) == (0.007, 0.02, 1.0)


def _price(leg, side="short"):
    p, why = L._price(leg, side, {"open_r": 1.0, "peak_r": 1.5, "bars_held": 10}, 1.5, "t", False)
    assert p is not None, why
    return p


def test_packet_prices_from_full_history_corpus_and_says_so():
    p = _price("ada_pullback_2h")
    assert p["corpus_source"] == "ltr_full_history"
    assert p["corpus"] == f"{L.LTR_CORPUS_DIR}/ada_pullback_2h__trades.jsonl"
    assert p["corpus_trades"] == json.loads((CORPUS / "ada_pullback_2h__corpus.json").read_text())["n_trades"]
    assert p["corpus_trades"] > 300  # the 61-trade evidence-window file is what this replaces


def test_packet_falls_back_to_evidence_source_run_when_no_corpus():
    leg = "eth_pullback_2h"
    assert not (CORPUS / f"{leg}__trades.jsonl").exists()
    p = _price(leg, "long")
    assert p["corpus_source"] == "evidence_source_run"
    assert not p["corpus"].startswith(L.LTR_CORPUS_DIR)

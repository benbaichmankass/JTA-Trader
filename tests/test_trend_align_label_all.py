"""Row TREND-ALIGN-LABEL-ALL: meta.trend_align on EVERY strategy's package, LABEL ONLY.

Pins:
  1. the stamp changes no key of a signal but ``meta.trend_align`` (package identical apart from the label);
  2. a non-actionable signal is untouched and costs no fetch;
  3. every builder that stamps the regime also stamps trend_align, and the ML legs are covered (structural guard);
  4. ``intent_from_signal`` gives an unstamped actionable signal an explicit null label, and the intent is identical
     whatever the label says (it never changes a decision, size or bracket);
  5. nothing in the decision / order / sizing path reads ``trend_align`` (allowlisted readers only);
  6. the read-only split groups with / counter / neutral / unlabelled per strategy x account.
"""
from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.runtime import intents as I
from src.runtime import strategy_signal_builders as ssb
from src.runtime import trend_alignment as ta

REPO = Path(__file__).resolve().parents[1]


def _frame(n: int = 120, step_h: int = 1, drift: float = 1.0, start: str = "2026-10-01") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq=f"{step_h}h", tz="UTC")
    base = 100 + np.cumsum(np.full(n, drift)) + np.sin(np.arange(n)) * 0.3
    return pd.DataFrame({"timestamp": ts, "open": base, "high": base + 1.0, "low": base - 1.0, "close": base + 0.2,
                         "volume": 1.0})


def _sig(side: str = "buy") -> dict:
    return {"symbol": "ETHUSDT", "side": side, "price": 101.0, "entry_price": 101.0, "stop_loss": 99.0,
            "take_profit": 105.0, "pattern": "x", "meta": {"strategy_name": "x", "direction": "long", "confidence": 0.5,
                                                         "risk_pct": 0.3}}


def _without_label(sig: dict) -> dict:
    s = copy.deepcopy(sig)
    s.get("meta", {}).pop("trend_align", None)
    return s


def test_stamp_changes_nothing_but_meta_trend_align():
    sig = _sig("buy")
    before = copy.deepcopy(sig)
    d1 = _frame(n=80, step_h=24, start="2026-07-01")   # daily bars that CLOSE before the leg entry
    ssb._stamp_trend_align_on_signal(sig, _frame(), symbol="ETHUSDT", timeframe="1h", exchange=object())
    assert "trend_align" in sig["meta"]
    assert _without_label(sig) == before          # every other key, every value, byte-identical
    # with a D1 frame supplied through the fetch path, still identical apart from the label
    sig2 = _sig("buy")
    ssb._stamp_trend_align_on_meta(sig2["meta"], _frame(), symbol="ETHUSDT", timeframe="1h", direction="buy",
                                   fetch_d1=lambda: d1)
    assert _without_label(sig2) == before
    assert sig2["meta"]["trend_align"]["D1"]["label"] in ta.LABELS
    assert sig2["meta"]["trend_align"]["LEG"]["label"] in ta.LABELS


def test_non_actionable_signal_is_untouched_and_fetches_nothing():
    calls = []

    class _Boom:
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError("no venue call on a non-actionable signal")

    sig = _sig("none")
    before = copy.deepcopy(sig)
    ssb._stamp_trend_align_on_signal(sig, _frame(), symbol="ETHUSDT", timeframe="1h", exchange=_Boom())
    assert sig == before and not calls


def test_stamp_never_raises_on_garbage():
    sig = _sig("sell")
    ssb._stamp_trend_align_on_signal(sig, "not a frame", symbol=None, timeframe=None, exchange=None)
    assert sig["meta"]["trend_align"]["LEG"]["label"] is None


def _functions_calling(tree: ast.Module, callee: str) -> set:
    out = set()
    for f in tree.body:
        if isinstance(f, ast.FunctionDef):
            for n in ast.walk(f):
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == callee:
                    out.add(f.name)
    return out


def test_every_regime_stamping_builder_also_stamps_trend_align_and_ml_legs_are_covered():
    tree = ast.parse((REPO / "src/runtime/strategy_signal_builders.py").read_text())
    regime = _functions_calling(tree, "_stamp_regime_on_meta")
    stamped = _functions_calling(tree, "_stamp_trend_align_on_signal")
    assert len(regime) >= 30
    assert regime - stamped == set(), f"builders stamping regime but not trend_align: {sorted(regime - stamped)}"
    assert {"ml_entry_signal_builder", "ml_entry_v2_signal_builder"} <= stamped
    eq = (REPO / "src/runtime/strategy_signal_builders.py").read_text()
    assert '_ta_unlabelled("snapshot_scored_no_candles"' in eq   # ml_entry_eq*: explicit null, no candle fetch


def test_intent_from_signal_fills_an_unstamped_actionable_signal_with_an_explicit_null():
    it = I.intent_from_signal(_sig("buy"), strategy="x")
    lab = it.meta["trend_align"]
    assert lab["LEG"]["label"] is None and lab["D1"]["label"] is None
    assert lab["LEG"]["missing_reason"] == "not_stamped_by_builder"
    assert I.intent_from_signal(_sig("none"), strategy="x") is None


def test_label_never_changes_the_intent():
    with_t, counter = _sig("buy"), _sig("buy")
    with_t["meta"]["trend_align"] = {"definition": "TREND-ALIGN-V1", "LEG": {"label": "with_trend"},
                                     "D1": {"label": "with_trend"}, "agreement": "both_with", "side": "long"}
    counter["meta"]["trend_align"] = {"definition": "TREND-ALIGN-V1", "LEG": {"label": "counter_trend"},
                                      "D1": {"label": "counter_trend"}, "agreement": "both_counter", "side": "long"}
    a = I.intent_from_signal(with_t, strategy="x", timestamp=1.0)
    b = I.intent_from_signal(counter, strategy="x", timestamp=1.0)
    c = I.intent_from_signal(_sig("buy"), strategy="x", timestamp=1.0)
    fields = ("strategy", "symbol", "side", "target_qty", "priority", "entry", "sl", "tp", "confidence", "regime",
              "adx_14", "vol_regime")
    for f in fields:
        assert getattr(a, f) == getattr(b, f) == getattr(c, f), f
    strip = lambda m: {k: v for k, v in m.items() if k != "trend_align"}  # noqa: E731
    assert strip(a.meta) == strip(b.meta) == strip(c.meta)


# Files allowed to mention trend_align: the producers (stamp), the label module, the read-only split route, the
# research side. Anything else under src/ reading it would be a decision reading a label -- refused here.
_ALLOWED = {
    "src/runtime/trend_alignment.py",
    "src/runtime/strategy_signal_builders.py",
    "src/runtime/intents.py",
    "src/web/api/routers/performance_trend_align.py",
    "src/web/api/main.py",                       # router registration only
}


def test_nothing_in_the_trade_path_reads_trend_align():
    hits = []
    for p in (REPO / "src").rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if rel in _ALLOWED:
            continue
        if re.search(r"trend_align", p.read_text(errors="ignore")):
            hits.append(rel)
    assert hits == [], f"trend_align read outside the label producers / read route: {hits}"


def test_split_groups_per_strategy_account_label_and_unlabelled_is_null():
    from src.web.api.routers.performance_trend_align import split

    def meta(d1):
        return json.dumps({"trend_align": {"D1": {"label": d1, "missing_reason": None if d1 else "no_candles"},
                                           "LEG": {"label": "neutral"}}})
    rows = [
        {"strategy_name": "s", "account_id": "a", "pnl": 10.0, "package_meta": meta("with_trend")},
        {"strategy_name": "s", "account_id": "a", "pnl": -4.0, "package_meta": meta("with_trend")},
        {"strategy_name": "s", "account_id": "a", "pnl": -5.0, "package_meta": meta("counter_trend")},
        {"strategy_name": "s", "account_id": "b", "pnl": 3.0, "package_meta": meta("with_trend")},
        {"strategy_name": "s", "account_id": "a", "pnl": 2.0, "package_meta": None},              # pre-stamp history
        {"strategy_name": "s", "account_id": "a", "pnl": 1.0, "package_meta": meta(None)},       # stamped, D1 null
    ]
    out = split(rows, "D1")
    g = {(x["account_id"], x["label"]): x for x in out["groups"]}
    assert g[("a", "with_trend")]["n"] == 2 and g[("a", "with_trend")]["net_pnl_usd"] == 6.0
    assert g[("a", "with_trend")]["wins"] == 1 and g[("a", "with_trend")]["label_provenance"] == "measured"
    assert g[("a", "counter_trend")]["net_pnl_usd"] == -5.0
    assert g[("b", "with_trend")]["n"] == 1
    un = g[("a", None)]
    assert un["n"] == 2 and un["label_provenance"] is None
    assert un["missing_reasons"] == {"unlabelled": 1, "no_candles": 1}
    assert out["n_closed"] == 6 and out["n_labelled"] == 4
    assert split(rows, "LEG")["n_labelled"] == 5

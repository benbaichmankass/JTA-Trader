#!/usr/bin/env python3
# wiring: manual research tooling (lane ML-DECISION-MODELS, deliverable A); output docs/research/ml-decision-models-2026-11-01/diagnosis_table.json
"""Tabulate every GRADED ML / AI-trader result in research/results/ by how it was set up (Tier-1, read-only).

The operator asked (2026-11-01) "what we're not doing correctly and why this is so difficult". This script
measures instead of narrating: for every research unit that (a) is an ML / AI-trader unit and (b) has at least
one result record under research/results/<id>/, it classifies

* ``task``          regime_vol_head | direction_head | in_trade_exit | entry_filter_meta | infra_parity_drift | other
* ``label_source``  strategy_trades (labels are a strategy's own trades) | bar_market (labels from market bars)
                    | none (plumbing / parity / drift: no decision label)
* ``metric``        net_r (decision value in R, net of cost) | statistical (log-loss / F1 / AUC / Brier / accuracy)
                    | other
* ``pooling``       pooled_cross_symbol | per_symbol | unstated
* ``decides``       True iff the unit's model OUTPUTS a trade action (enter long/short/flat, a bracket, or an
                    in-trade action) AND is scored in net R. A head whose output only gates / labels a regime is False.
* ``n``             the largest test-population count found in the measurement block (keys n_oos*, n_test*,
                    n_trades*, n_rows*, n_holdout*, n); ``None`` = could not read one (never 0).
* ``verdict``       the LAST result record's verdict.

Classification is by regex over the unit's title + question + decision_rule text. That is a heuristic; the table
carries the matched evidence so a reader can audit any row. Population: units in research/queue/**.yaml whose id
has a research/results/<id>/ directory. ML filter: theme ``ml_health`` OR an ML term in the title.

    python3 scripts/research/ml_decision_diagnosis.py --out docs/research/ml-decision-models-2026-11-01/diagnosis_table.json
    python3 scripts/research/ml_decision_diagnosis.py --self-test
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

ML_TITLE = re.compile(
    r"(exit[- ]head|regime[- ]head|direction[- ]head|meta[- ]?label|lightgbm|lgbm|gbdt|xgboost|catboost|classifier|"
    r"\bmodel\b|tabpfn|tabicl|chronos|timesfm|kronos|\blearner|\bml\b|\bml-|overlay|ai trader|logit|\bmlp\b|gru|"
    r"extratrees|foundation)", re.I)
NOT_ML = re.compile(r"head-to-head", re.I)

TASK_RULES = [
    ("infra_parity_drift", re.compile(r"(parity|smoke|plumbing|drift|health monitor|feasibility|wiring|census|selfcheck|re-entry test)", re.I)),
    ("in_trade_exit", re.compile(r"(exit[- ]head|in-trade|exit line|exit/tighten|partial close|giveback|sl-before-tp|"
                                  r"action-value|hold-to-bracket|exit-now)", re.I)),
    ("entry_filter_meta", re.compile(r"(meta[- ]?label|overlay|take/skip|entry gate|veto|label wall|conviction|"
                                      r"setup[- ]quality|winrate|trade[- ]outcome|impact scoping|gates? each leg)", re.I)),
    ("direction_head", re.compile(r"direction", re.I)),
    ("regime_vol_head", re.compile(r"(regime|vol(atility)?[- ]?(head|label|regime)|range-vol|har-rv)", re.I)),
]
STRATEGY_LABEL = re.compile(r"(\btrades?\b|\blegs?\b|ledger|exit|meta[- ]?label|overlay|in-trade|take/skip|giveback|"
                            r"strategy x symbol|trade corpus|entry gate|veto)", re.I)
BAR_LABEL = re.compile(r"(regime_label|direction_label|regime head|direction|vol label|forward return|bars?\b|shards?)",
                       re.I)
NET_R = re.compile(r"(net[- ]?r\b|r per trade|r/trade|recovered_r|\bdr\b|net of (the )?(full )?cost|mean_net_r|"
                   r"net-of-cost|delta[_ ]r|per capital-day)", re.I)
STAT = re.compile(r"(log[-_ ]?loss|macro[-_ ]?f1|f1_|\bauc\b|brier|accuracy|nats|calibrat|\bece\b)", re.I)
POOLED = re.compile(r"(pooled across symbols|cross-symbol|pooled over (the )?symbols|universe|60[- ]perp|"
                    r"one model .* all|generalist)", re.I)
SYMBOL = re.compile(r"\b(BTC|ETH|SOL|XRP|ADA|DOGE|MES|BNB)(USDT)?\b")
CLOCK = re.compile(r"\b(5m|15m|30m|1h|2h|4h|1d|daily)\b", re.I)
COST = re.compile(r"(net of (the )?(full )?cost|net-of-cost|cost stack|fee|slippage|funding|net r|netr)", re.I)
N_KEY = re.compile(r"^(n|n_oos\w*|n_test\w*|n_trades\w*|n_rows\w*|n_holdout\w*|n_eval\w*|n_total\w*|rows_n|block_n)$")


def _walk_n(obj, best=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and N_KEY.match(str(k)):
                best = v if best is None else max(best, v)
            else:
                best = _walk_n(v, best)
    elif isinstance(obj, list):
        for v in obj[:200]:
            best = _walk_n(v, best)
    return best


def classify(unit: dict) -> dict:
    title = str(unit.get("title", ""))
    dr = unit.get("decision_rule") or {}
    text = " ".join([title, str(unit.get("question", "")), str(dr.get("statistic", "")), str(dr.get("rule", ""))])
    task = "other"
    for name, rx in TASK_RULES:
        if rx.search(title) or (name != "infra_parity_drift" and rx.search(str(unit.get("question", "")))):
            task = name
            break
    if task == "infra_parity_drift":
        label = "none"
    elif task in ("in_trade_exit", "entry_filter_meta"):
        label = "strategy_trades"
    elif task in ("regime_vol_head", "direction_head"):
        label = "bar_market"
    else:
        label = "strategy_trades" if STRATEGY_LABEL.search(text) else ("bar_market" if BAR_LABEL.search(text) else "none")
    # The registered STATISTIC decides the metric; the rule text is a fallback only (rules often carry a
    # "NOT a P&L figure / says nothing about net of cost" disclaimer that a net-R regex would mis-hit).
    statistic = str(dr.get("statistic", ""))
    rule_text = str(dr.get("rule", ""))
    if NET_R.search(statistic) and not STAT.search(statistic):
        metric = "net_r"
    elif STAT.search(statistic) or STAT.search(title):
        metric = "statistical"
    elif NET_R.search(statistic) or NET_R.search(title):
        metric = "net_r"
    elif STAT.search(rule_text):
        metric = "statistical"
    elif NET_R.search(rule_text):
        metric = "net_r"
    else:
        metric = "other"
    syms = sorted({m.group(1) for m in SYMBOL.finditer(text)})
    pooling = "pooled_cross_symbol" if POOLED.search(text) else ("per_symbol" if syms else "unstated")
    clocks = sorted({m.group(1).lower() for m in CLOCK.finditer(text)})
    cost = ("full_or_stated" if metric == "net_r" and COST.search(text) else
            ("none_statistical_metric" if metric == "statistical" else "unstated"))
    decides = metric == "net_r" and task in ("in_trade_exit", "entry_filter_meta", "direction_head")
    return {"task": task, "label_source": label, "metric": metric, "pooling": pooling, "symbols_named": syms,
            "clock": clocks, "cost_stack": cost, "decides": decides}


def load_units() -> dict:
    units = {}
    for f in glob.glob(str(REPO / "research/queue/*.yaml")) + glob.glob(str(REPO / "research/queue/*/*.yaml")):
        try:
            d = yaml.safe_load(open(f))
        except Exception:  # noqa: BLE001 - an unparsable unit is counted below, not fatal
            continue
        if isinstance(d, dict) and d.get("id"):
            units[d["id"]] = d
    return units


def is_ml(unit: dict) -> bool:
    title = str(unit.get("title", ""))
    if NOT_ML.search(title) and unit.get("theme") != "ml_health":
        return False
    return unit.get("theme") == "ml_health" or bool(ML_TITLE.search(title))


def build() -> dict:
    units = load_units()
    res_root = REPO / "research/results"
    rows, no_unit = [], 0
    for rid in sorted(os.listdir(res_root)):
        u = units.get(rid)
        if u is None:
            no_unit += 1
            continue
        if not is_ml(u):
            continue
        recs = []
        for f in sorted(glob.glob(str(res_root / rid / "*.jsonl"))):
            for line in open(f):
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
        if not recs:
            continue
        last = recs[-1]
        c = classify(u)
        c.update({"id": rid, "theme": u.get("theme"), "title": str(u.get("title", ""))[:160],
                  "verdict": last.get("verdict"), "n": _walk_n(last.get("measurement")),
                  "n_records": len(recs)})
        rows.append(c)
    return {"population": {"result_dirs": len(os.listdir(res_root)), "result_dirs_without_unit": no_unit,
                           "ml_units_with_results": len(rows),
                           "rule": "research/results/<id>/ with a unit in research/queue/**; ML = theme ml_health OR ML term in title"},
            "rows": rows, "summary": summarize(rows)}


def summarize(rows: list) -> dict:
    out = {}
    for key in ("task", "label_source", "metric", "pooling", "verdict", "decides", "cost_stack"):
        out[key] = dict(collections.Counter(str(r[key]) for r in rows).most_common())
    cross = collections.Counter((r["task"], r["label_source"], r["metric"], str(r["verdict"])) for r in rows)
    out["task_label_metric_verdict"] = [{"task": k[0], "label_source": k[1], "metric": k[2], "verdict": k[3], "count": v}
                                        for k, v in sorted(cross.items(), key=lambda kv: -kv[1])]
    ns = collections.defaultdict(list)
    for r in rows:
        if isinstance(r["n"], (int, float)):
            ns[r["task"]].append(r["n"])
    out["median_n_by_task"] = {k: sorted(v)[len(v) // 2] for k, v in ns.items()}
    out["n_unread_by_task"] = dict(collections.Counter(r["task"] for r in rows if r["n"] is None))
    out["bar_level_market_label_AND_net_r_AND_pooled"] = sum(
        1 for r in rows if r["label_source"] == "bar_market" and r["metric"] == "net_r" and r["pooling"] == "pooled_cross_symbol")
    out["clock_counts"] = dict(collections.Counter(c for r in rows for c in (r["clock"] or ["unstated"])).most_common())
    nl = collections.defaultdict(list)
    for r in rows:
        if isinstance(r["n"], (int, float)):
            nl[r["label_source"]].append(r["n"])
    out["median_n_by_label_source"] = {k: sorted(v)[len(v) // 2] for k, v in nl.items()}
    out["pass_by_metric"] = {m: dict(collections.Counter(str(r["verdict"]) for r in rows if r["metric"] == m))
                             for m in ("net_r", "statistical", "other")}
    return out


def _self_test() -> None:
    c = classify({"title": "Regime head at 1h: does CatBoost beat LightGBM on logloss on BTC/ETH/SOL", "decision_rule": {}})
    assert c["task"] == "regime_vol_head" and c["metric"] == "statistical" and c["label_source"] == "bar_market", c
    c = classify({"title": "exit-head-donchian-1h-v1 recovered_R, multi-fold", "decision_rule": {"statistic": "pooled net R per trade", "rule": "PASS IF > 0"}})
    assert c["task"] == "in_trade_exit" and c["metric"] == "net_r" and c["label_source"] == "strategy_trades", c
    assert _walk_n({"a": {"n_oos_total": 1041, "folds": [{"n_test_trades": 347}]}}) == 1041
    assert _walk_n({"x": 1}) is None
    assert not is_ml({"title": "Programme 05 head-to-head", "theme": "new_strategy_prop"})
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    data = build()
    txt = json.dumps(data, indent=1, sort_keys=True, default=str)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(txt + "\n")
    print(json.dumps({"population": data["population"], "summary": data["summary"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

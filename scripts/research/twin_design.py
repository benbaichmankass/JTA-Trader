#!/usr/bin/env python3
# wiring: scripts/research/queue_replenish.py (_leg_source: live_roster_legs_symbol_twins / live_roster_legs_timeframe_twins) -> research/templates/leg-twin-*.yaml
"""CONFIG-EXACT TWIN DESIGN for generated research units (row RESEARCH-LEVER-FAMILY-REACH part a, 2026-11-26).

WHY SIBLING UNITS, NOT ARMS. `symbol_set` and `timeframe` are lever families the weekly arm sweep cannot express: an arm is graded as
"arm minus control A on the same trades", but a different symbol or bar size is a DIFFERENT TRADE SET, so there is no paired control.
Each twin is therefore its own unit, graded ABSOLUTE by the Stage-0 rule (net R > 0, n >= the floor, >= 3 of 4 folds net-positive) -- the
same shape the by-hand twin units use (`exit_lever_ablation.py --symbol` / `--timeframe`, "config-exact": every other config key, and the
leg's own cost policy, are kept).

WHAT IT DECIDES AND WHAT IT DOES NOT. Pure functions over the committed config and the leg's lever map; no network, no writes.
  * symbol twins   -- other symbols the roster ALREADY trades, same harness class (trend / pullback) and same asset class (a `...USDT`
                      perp is crypto; everything else is "other"), never the leg's own symbol, at most `LIMIT` per leg, in sorted order.
                      Only for a leg whose map reads `symbol_set` as not `tested`.
  * timeframe twins-- the next `LIMIT` COARSER bar sizes of exit_lever_ablation's `_TF_MIN` (a coarser bar is resampled from the leg's
                      native fetch; a finer one cannot be). Only for a leg whose map reads `timeframe` as not `tested`.
A twin result is a LEVER-MAP READING, never a promotion or a retirement: per-symbol results never gate (operator 2026-11-04), and a
population claim needs its own pooled test.

NOT HERE, deliberately: the measured-cost reprice (`sizing_vs_cost`). Its 26 / 53 bps basis was measured for the Alpaca live legs and is
venue-specific, so it stays a by-hand, per-venue unit (RQ-20261119-f2a4-* are the pattern) until an owner supplies a per-venue cost basis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]

LIMIT = 2                                      # twins per leg per kind: bounds the family, keeps the point set stable
HARNESS = ("trend", "pullback")                # the two harnesses whose twins exit_lever_ablation runs config-exact
#: bar sizes in ascending length; mirrors exit_lever_ablation._TF_MIN (asserted equal in the self-test, so a drift is loud)
TF_ORDER = ("5m", "15m", "30m", "1h", "2h", "4h", "1d")


def asset_class(symbol: str) -> str:
    return "crypto" if str(symbol).upper().endswith("USDT") else "other"


def harness_of(cfg: dict[str, Any]) -> str | None:
    from regime_debt_matrix import classify
    return classify(cfg)


def _unread(map_doc: dict[str, Any], family: str) -> bool:
    """True when the lever map does NOT already read `family` as tested (a missing map reads as untested)."""
    return ((map_doc.get("manifest") or {}).get(family, "untested")) != "tested"


def symbol_twins(leg: str, roster: dict[str, dict[str, Any]], cfgs: dict[str, dict[str, Any]], map_doc: dict[str, Any],
                 *, harness: str | None = None, limit: int = LIMIT) -> list[str]:
    h = harness if harness is not None else harness_of(cfgs.get(leg) or {})
    if h not in HARNESS or not _unread(map_doc, "symbol_set"):
        return []
    own = str(roster[leg]["symbol"])
    cls = asset_class(own)
    pool = sorted({str(r["symbol"]) for lg, r in roster.items()
                   if lg != leg and r.get("symbol") and str(r["symbol"]) != own and asset_class(str(r["symbol"])) == cls
                   and harness_of(cfgs.get(lg) or {}) == h})
    return pool[:limit]


def timeframe_twins(leg: str, roster: dict[str, dict[str, Any]], cfgs: dict[str, dict[str, Any]], map_doc: dict[str, Any],
                    *, harness: str | None = None, limit: int = LIMIT) -> list[str]:
    h = harness if harness is not None else harness_of(cfgs.get(leg) or {})
    if h not in HARNESS or not _unread(map_doc, "timeframe"):
        return []
    native = str(roster[leg]["timeframe"])
    if native not in TF_ORDER:
        return []
    return list(TF_ORDER[TF_ORDER.index(native) + 1:][:limit])


def design(kind: str, leg: str, value: str, roster: dict[str, dict[str, Any]], map_doc: dict[str, Any]) -> dict[str, Any]:
    """The `iteration` facts a twin unit stamps (JSON-serialisable: it travels in generated.params)."""
    fam = {"symbol": "symbol_set", "timeframe": "timeframe"}[kind]
    base = map_doc.get("baseline") or {}
    own = roster[leg]["symbol"] if kind == "symbol" else roster[leg]["timeframe"]
    return {"lever": fam, "twin_kind": kind, "twin_value": value, "leg": leg, "leg_value": str(own),
            "from_result": str(base.get("record") or f"none: {leg} has no Stage-0 record (first measurement)"),
            "verdict_read": str(base.get("rule_verdict") or base.get("verdict") or "pending"),
            "diagnosis": (f"{leg}: the lever map reads {fam} as not tested. A config-exact {kind} twin ({own} -> {value}) is the cheapest read of "
                          f"whether the leg's edge is a property of the setup or of one {('symbol', 'bar size')[kind == 'timeframe']}; it is "
                          f"graded absolute because a twin has a different trade set than the leg (no paired control).")}


def points(kind: str, roster: dict[str, dict[str, Any]], cfgs: dict[str, dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    """One generator point per (leg, twin): `leg`, `twin`, `twin_key` (the dedupe identity), `design_json`, plus the leg's facts."""
    from lever_design import read_map
    fn = {"symbol": symbol_twins, "timeframe": timeframe_twins}[kind]
    out: list[dict[str, Any]] = []
    for leg in sorted(roster):
        m = read_map(root, leg)
        for v in fn(leg, roster, cfgs, m):
            out.append({"leg": leg, **roster[leg], "harness": harness_of(cfgs.get(leg) or {}), "twin": v,
                        "twin_key": f"{kind}:{v}", "design_json": json.dumps(design(kind, leg, v, roster, m), sort_keys=True)})
    return out


def _self_test() -> int:
    from exit_lever_ablation import _TF_MIN
    assert tuple(sorted(_TF_MIN, key=_TF_MIN.get)) == TF_ORDER, "TF_ORDER drifted from exit_lever_ablation._TF_MIN"
    roster = {"a_pb": {"symbol": "AAAUSDT", "timeframe": "2h"}, "b_pb": {"symbol": "BBBUSDT", "timeframe": "2h"},
              "c_pb": {"symbol": "CCCUSDT", "timeframe": "2h"}, "d_pb": {"symbol": "DDDUSDT", "timeframe": "2h"},
              "etf_pb": {"symbol": "GLD", "timeframe": "1d"}, "tr": {"symbol": "EEEUSDT", "timeframe": "4h"}}
    cfgs = {k: {"pullback_frac": 0.5, "trend_lookback": 60} for k in ("a_pb", "b_pb", "c_pb", "d_pb", "etf_pb")}
    cfgs["tr"] = {"donchian": 20}
    assert symbol_twins("a_pb", roster, cfgs, {}) == ["BBBUSDT", "CCCUSDT"]                      # same harness, same class, own excluded, LIMIT 2
    assert symbol_twins("tr", roster, cfgs, {}) == []                                            # no other trend leg
    assert symbol_twins("etf_pb", roster, cfgs, {}) == []                                        # 'other' class has no other pullback leg
    assert symbol_twins("a_pb", roster, cfgs, {"manifest": {"symbol_set": "tested"}}) == []       # already read: no twin
    assert timeframe_twins("a_pb", roster, cfgs, {}) == ["4h", "1d"]
    assert timeframe_twins("tr", roster, cfgs, {}) == ["1d"] and timeframe_twins("etf_pb", roster, cfgs, {}) == []
    assert timeframe_twins("a_pb", roster, cfgs, {"manifest": {"timeframe": "tested"}}) == []
    assert symbol_twins("a_pb", roster, {**cfgs, "a_pb": {"timeframe": "2h"}}, {}) == []          # unclassifiable harness: nothing
    d = design("symbol", "a_pb", "BBBUSDT", roster, {"baseline": {"record": "r.json", "rule_verdict": "fail"}})
    assert d["lever"] == "symbol_set" and d["verdict_read"] == "fail" and json.dumps(d)
    print("self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test() if "--self-test" in sys.argv else 0)

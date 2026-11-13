#!/usr/bin/env python3
"""Consumer test of the regime gate on a strategy FAMILY, pooled, by money (row ML-D2-CONSUMER-TEST).

Question: if the authored (trend, vol) OFF-cells were applied to every leg of a family, would the dropped trades have been
net-negative, pooled across legs, out of sample in time, and more so than the same NUMBER of trades dropped at random?

Input: per-leg fully tagged trade JSONL files (``regime_tag_emitted.py --emit-tagged <file> --vol-labels <labels>`` with NO
``--only-*`` filter), each row carrying ``entry_time, direction, net_r, regime, vol_regime``; ``net_r`` is the harness's own
full-cost-stack figure. Cells come from the gate spec (default: the trend_vol cells ``config/regime_policy.yaml`` authors for
``--cell-strategy``), never from a threshold chosen after seeing the trades.

Graded statistic (registered in the unit before any run):
  added_r      = -(sum net_r of the trades the gate drops), pooled over legs  (a gate that drops losers adds R)
  fold_wins    = calendar folds (equal-width time spans over the pooled trades, K=6) with added_r > 0
  random ctrl  = per leg, drop the same number of same-direction trades uniformly at random (R draws, fixed seed); p = share of
                 draws with added_r >= actual
Verdict: indeterminate if dropped < MIN_DROPPED; PASS iff added_r > 0 AND fold_wins >= 4 AND p <= 0.05; else FAIL.
Reads nothing live, writes no config.

Opt-in ``--cells-per-leg`` (default OFF; without it the behaviour is byte-identical): each leg's cells are the trend_vol cells
the policy authors for THAT leg's own name, instead of one ``--cell-strategy`` for every leg. For a gate whose cells name
several different strategies (e.g. the BTC trend_vol cells on trend_donchian, squeeze_breakout_4h and ict_scalp_5m; unit
RQ-20261113-b819-01). The statistic, folds, control and verdict are unchanged.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

MIN_DROPPED = 25
FOLDS = 6
ALPHA = 0.05


def _ts(s: str) -> float:
    s = str(s).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def load_cells(policy_path: str, strategy: str) -> set[tuple[str, str, str]]:
    """{(trend, vol, direction)} the policy turns OFF for ``strategy`` (the authored trend_vol block)."""
    import yaml
    with open(policy_path, encoding="utf-8") as fh:
        pol = yaml.safe_load(fh) or {}
    cells: set[tuple[str, str, str]] = set()
    for trend, vols in (pol.get("trend_vol") or {}).items():
        for vol, strats in (vols or {}).items():
            cell = (strats or {}).get(strategy) or {}
            for side in ("long", "short"):
                v = cell.get(side, True)
                if v is False or str(v).lower() == "off":  # YAML 1.1 parses bare `off` as False
                    cells.add((trend, vol, side))
    return cells


def load_legs(paths: dict[str, str]) -> dict[str, list[dict]]:
    legs: dict[str, list[dict]] = {}
    for leg, p in paths.items():
        rows = []
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    if "net_r" in r and "direction" in r and r.get("vol_regime") is not None:
                        r["_t"] = _ts(r.get("entry_time") or r.get("exit_time"))
                        rows.append(r)
        legs[leg] = sorted(rows, key=lambda r: r["_t"])
    return legs


def _dropped(rows, cells):
    return [r for r in rows if (r.get("regime"), r.get("vol_regime"), str(r["direction"]).lower()) in cells]


def _leg_cells(cells, leg: str) -> set:
    """``cells`` is one set applied to every leg (default), or a {leg: set} map (opt-in --cells-per-leg)."""
    return cells.get(leg, set()) if isinstance(cells, dict) else cells


def grade(legs: dict[str, list[dict]], cells, draws: int = 5000, seed: int = 20261112,
          folds: int = FOLDS, since: float | None = None) -> dict:
    if since is not None:
        legs = {k: [r for r in v if r["_t"] >= since] for k, v in legs.items()}
    drops = {k: _dropped(v, _leg_cells(cells, k)) for k, v in legs.items()}
    all_rows = [r for v in legs.values() for r in v]
    n_drop = sum(len(d) for d in drops.values())
    added = -sum(r["net_r"] for d in drops.values() for r in d)
    cells_out = ({k: sorted("/".join(c) for c in v) for k, v in sorted(cells.items())} if isinstance(cells, dict)
                 else sorted("/".join(c) for c in cells))
    out = {"cells": cells_out, "legs": {}, "trades_total": len(all_rows),
           "dropped_n": n_drop, "added_r": round(added, 4), "min_dropped": MIN_DROPPED, "folds": folds,
           "draws": draws, "seed": seed}
    if not all_rows:
        out["verdict"] = "no_trades"
        return out
    t0, t1 = min(r["_t"] for r in all_rows), max(r["_t"] for r in all_rows)
    width = (t1 - t0) / folds or 1.0
    fold_added = [0.0] * folds
    for d in drops.values():
        for r in d:
            fold_added[min(folds - 1, int((r["_t"] - t0) / width))] -= r["net_r"]
    out["fold_added_r"] = [round(x, 4) for x in fold_added]
    out["fold_wins"] = sum(1 for x in fold_added if x > 0)
    rng = random.Random(seed)
    ge = 0
    for _ in range(draws):
        tot = 0.0
        for leg, d in drops.items():
            for side in ("long", "short"):
                k = sum(1 for r in d if str(r["direction"]).lower() == side)
                pool = [r for r in legs[leg] if str(r["direction"]).lower() == side]
                if k and pool:
                    tot -= sum(r["net_r"] for r in rng.sample(pool, min(k, len(pool))))
        ge += tot >= added
    out["control_p"] = round((ge + 1) / (draws + 1), 4)
    for leg, d in drops.items():
        out["legs"][leg] = {"trades": len(legs[leg]), "dropped": len(d), "added_r": round(-sum(r["net_r"] for r in d), 4)}
    if n_drop < MIN_DROPPED:
        out["verdict"] = "indeterminate_underpowered"
    elif added > 0 and out["fold_wins"] >= 4 and out["control_p"] <= ALPHA:
        out["verdict"] = "pass"
    else:
        out["verdict"] = "fail"
    return out


def _selftest() -> None:
    rng = random.Random(1)
    def mk(bias, n=200):
        rows = []
        for i in range(n):
            tr = rng.choice(["trending", "chop"])
            vol = rng.choice(["calm", "volatile"])
            r = rng.gauss(0.05, 1.0) + (bias if (tr, vol) == ("trending", "volatile") else 0)
            rows.append({"entry_time": f"2025-{1 + i % 12:02d}-{1 + i % 27:02d}T00:00:00Z", "direction": "long",
                         "net_r": r, "regime": tr, "vol_regime": vol, "_t": 1.7e9 + i * 86400 * 3})
        return rows
    cells = {("trending", "volatile", "long")}
    bad = grade({"a": mk(-1.0), "b": mk(-1.0)}, cells, draws=500)
    null = grade({"a": mk(0.0), "b": mk(0.0)}, cells, draws=500)
    assert bad["verdict"] == "pass", bad
    assert null["verdict"] == "fail", null
    assert grade({"a": mk(-1.0, 8)}, cells, draws=50)["verdict"] == "indeterminate_underpowered"
    # opt-in per-leg cells: each leg is gated only by its own cells
    per_leg = {"a": cells, "b": {("chop", "calm", "long")}}
    ra, rb = mk(-1.0), mk(0.0)
    pl = grade({"a": ra, "b": rb}, per_leg, draws=500)
    a_only = grade({"a": ra}, cells, draws=50)
    assert pl["legs"]["a"] == a_only["legs"]["a"], (pl, a_only)
    assert pl["legs"]["b"]["dropped"] == len(_dropped(rb, per_leg["b"])) > 0
    assert all((r["regime"], r["vol_regime"]) == ("chop", "calm") for r in _dropped(rb, per_leg["b"]))
    assert isinstance(pl["cells"], dict) and pl["cells"]["b"] == ["chop/calm/long"], pl["cells"]
    assert grade({"a": mk(-1.0)}, {"zz": cells}, draws=50)["dropped_n"] == 0  # a leg with no cells drops nothing
    print("self-test ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leg", action="append", default=[], help="LEG=tagged.jsonl (repeatable)")
    ap.add_argument("--policy", default="config/regime_policy.yaml")
    ap.add_argument("--cell-strategy", default="trend_donchian")
    ap.add_argument("--cells-per-leg", action="store_true",
                    help="opt-in: gate each leg by the cells the policy authors for its OWN name (ignores --cell-strategy)")
    ap.add_argument("--since", default=None, help="ISO date: grade only trades at/after it (secondary slice)")
    ap.add_argument("--draws", type=int, default=5000)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        _selftest()
        return 0
    legs = load_legs(dict(x.split("=", 1) for x in a.leg))
    cells = ({leg: load_cells(a.policy, leg) for leg in legs} if a.cells_per_leg
             else load_cells(a.policy, a.cell_strategy))
    res = grade(legs, cells, a.draws,
                since=_ts(a.since) if a.since else None)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

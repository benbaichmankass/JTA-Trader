#!/usr/bin/env python3
# wiring: library - CF-C1-HARNESS-HOOK; imported by scripts/backtest_trend.py (the --cf flag) and scripts/research/harness_stage0.py (cf_summary)
"""cf_harness: grade ONE backtest-harness trade on the counterfactual arms (per-trade record schema ``cf_trade/1``).

Pure and OFFLINE: bars come IN as arguments, nothing is fetched. A harness ``Trade`` row is mapped to the shape
``cf_core.grade_package`` already takes (one closed package with one closed leg) so the live grader, tm_bench and the
backtest harness share ONE engine. The block is attached under the key ``cf`` of an emitted trade row; no existing key
is touched (design docs/plans/counterfactual-everywhere-DESIGN-2026-10-29.md § 4.2).

Biases that matter to a reader (the engine's full list rides in ``cf.biases``):
* ``replayed_actual`` replays the leg's initial bracket plus an ATR trail rebuilt from ``leg_meta`` (atr, trail_mult); the
  harness's other exit levers (bank, giveback, stale, momentum) are NOT replayed, so ``fidelity.abs_gap_r`` says how far the
  replay is from the harness ``net_r`` and a reader must look at it before believing an arm.
* ``post_exit`` is HINDSIGHT by construction: a label, never a feature.
* cost: the fee term is the harness's own ``cost_fee_r``; slippage/funding come from the engine's cost policy (ESTIMATED).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "cf_trade/1"
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
# arms whose net R is summarised per family in cf_summary
ARM_FAMILIES = ("entry_brackets", "alt_brackets", "less_management", "more_management")


def trade_key(strategy: Any, symbol: Any, entry_time: Any, direction: Any, sl: Any) -> str:
    return hashlib.sha1(f"{strategy}|{symbol}|{entry_time}|{direction}|{sl}".encode()).hexdigest()


class FrameBars:
    """Engine bars from a harness frame (``timestamp`` + OHLC), indexed once per run so each trade's slice is O(log n).
    ``bar_label='close'`` means a row's timestamp stamps the bar's END; the engine wants the OPEN."""

    def __init__(self, df: Any, *, timeframe: str, bar_label: str = "open"):
        import numpy as np
        self.dur = float(TF_SECONDS[timeframe])
        shift = self.dur if bar_label == "close" else 0.0
        self.t = np.array([x.timestamp() for x in df["timestamp"]], dtype="float64") - shift
        self.o, self.h = df["open"].to_numpy(dtype="float64"), df["high"].to_numpy(dtype="float64")
        self.lo, self.c = df["low"].to_numpy(dtype="float64"), df["close"].to_numpy(dtype="float64")

    def slice(self, t0: float, t1: float) -> List[dict]:
        """Bars opening in ``[t0, t1)``, oldest first (the frame is time-ordered)."""
        import numpy as np
        i, j = int(np.searchsorted(self.t, t0, side="left")), int(np.searchsorted(self.t, t1, side="left"))
        return [{"time": float(self.t[k]), "open": float(self.o[k]), "high": float(self.h[k]), "low": float(self.lo[k]),
                 "close": float(self.c[k]), "dur": self.dur} for k in range(i, j)]


def horizon_end(trade: dict, horizon_cfg: Optional[dict]) -> float:
    """Epoch second the post-exit path ends: harness exit + the engine's horizon (leg max-hold, else per-timeframe default)."""
    pkg = {"timeframe": (horizon_cfg or {}).get("timeframe")}
    h = cf_core.resolve_horizon(pkg, horizon_cfg)
    return float(lrc._ts(trade.get("exit_time"))) + h["seconds"]


def _could_not(trade: dict, reason: str) -> dict:
    return {"schema": SCHEMA, "grader_schema_version": cf_core.SCHEMA_VERSION,
            "trade_key": trade_key(trade.get("strategy"), trade.get("symbol"), trade.get("entry_time"), trade.get("direction"), trade.get("sl")),
            "status": "could_not_grade", "reason": reason, "provenance": "UNVERIFIED"}


def cf_fields(trade: dict, bars: Sequence[dict], cost_policy: Optional[dict] = None, horizon_cfg: Optional[dict] = None,
              n_random: int = cf_core.N_RANDOM, leg_meta: Optional[dict] = None) -> dict:
    """The ``cf`` block for one emitted harness row. ``trade`` is the row the harness writes (strategy, symbol,
    entry_time, exit_time, direction, entry, sl, exit_price?, net_r, cost_fee_r, cost_funding_r?). ``cost_policy`` =
    ``{'basis': 'full'|'fee_only'}`` (default: 'full' when the row carries ``cost_funding_r``). ``leg_meta`` may carry
    ``atr``, ``trail_mult``, ``tp`` (a price) to rebuild the leg's own trail/TP for the replay. Never raises on a
    ungradable row: it returns ``status: could_not_grade`` with a reason."""
    side = str(trade.get("direction") or "").lower()
    entry, sl = lrc._num(trade.get("entry")), lrc._num(trade.get("sl"))
    t_entry, t_exit = lrc._ts(trade.get("entry_time")), lrc._ts(trade.get("exit_time"))
    net_r = lrc._num(trade.get("net_r"))
    if side not in ("long", "short") or entry is None or sl is None or entry == sl:
        return _could_not(trade, "geometry_missing")
    if t_entry is None or t_exit is None or net_r is None:
        return _could_not(trade, "row_incomplete")
    if not bars:
        return _could_not(trade, "no_bars")
    basis = (cost_policy or {}).get("basis") or ("full" if trade.get("cost_funding_r") is not None else "fee_only")
    r_dist = abs(entry - sl)
    meta = dict(leg_meta or {})
    pkg = {"order_package_id": trade_key(trade.get("strategy"), trade.get("symbol"), trade.get("entry_time"), side, sl),
           "strategy_name": trade.get("strategy"), "symbol": trade.get("symbol"), "direction": side, "entry": entry,
           "exit_plan": {"stop": {"price": sl}}, "tp": meta.get("tp"),
           "meta": {k: meta[k] for k in ("atr", "trail_mult") if meta.get(k) is not None},
           "timeframe": (horizon_cfg or {}).get("timeframe")}
    fee_r = lrc._num(trade.get("cost_fee_r")) or 0.0
    leg = {"account_id": "backtest", "id": pkg["order_package_id"], "status": "closed", "account_class": "backtest",
           "timestamp": lrc._iso(t_entry), "closed_at": lrc._iso(t_exit), "entry_price": entry,
           "exit_price": lrc._num(trade.get("exit_price")), "position_size": 1.0, "exit_reason": trade.get("exit_reason"),
           "pnl": net_r * r_dist,                       # qty 1 => actual_r == the harness net_r, so fidelity is quoted against it
           "fee_taker_usd": fee_r * r_dist, "cost_source": "estimate"}
    horizon = cf_core.resolve_horizon(pkg, horizon_cfg)
    g = cf_core.grade_package(pkg, [leg], list(bars), [], [], {"backtest": None}, {}, graded_at=lrc._iso(t_exit),
                              n_random=n_random, horizon=horizon)
    if g.get("status") != "graded":
        return _could_not(trade, str(g.get("reason") or "engine_refused"))
    arms = g["arms"]
    by_id = {a["arm_id"]: a for a in arms}

    def compact(a: dict) -> dict:
        return {"arm_id": a["arm_id"], "net_r": a.get("net_r"), "resolved": a.get("resolved"),
                **({"exit_reason": (a.get("exit") or {}).get("reason")} if a["arm_id"] == "original_brackets" else {})}

    rep, orig = by_id.get("replayed_actual"), by_id.get("original_brackets")
    po = g.get("post_exit") or {}
    v = po.get("verdict") or {}
    return {
        "schema": SCHEMA, "grader_schema_version": g["schema_version"], "trade_key": pkg["order_package_id"],
        "status": "graded", "reason": None,
        "path": {"bars": g["path"]["bars"], "timeframe": (horizon_cfg or {}).get("timeframe"), "first_bar": g["path"]["first_bar"],
                 "last_bar": g["path"]["last_bar"], "horizon_end": lrc._iso(t_exit + horizon["seconds"])},
        "cost": {"basis": basis, "provenance": "ESTIMATED"},
        "arms": {"replayed_actual_net_r": None if rep is None else rep["net_r"],
                 "original_brackets": None if orig is None else compact(orig),
                 "alt_brackets": [{"sl_mult": a["params"].get("sl_mult"), "tp_r": a["params"].get("tp_r"), "net_r": a["net_r"],
                                   "resolved": a["resolved"]} for a in arms if a["family"] == "alt_brackets"],
                 "less_management": [compact(a) for a in arms if a["family"] == "less_management"],
                 "more_management": [compact(a) for a in arms if a["family"] == "more_management"]},
        "random_control": g.get("random_control"),
        "post_exit": {"horizon_seconds": horizon["seconds"], "horizon_source": horizon["source"],
                      "horizon_reached": po.get("horizon_reached"), "mfe_r": po.get("mfe_r"), "mae_r": po.get("mae_r"),
                      "tp_reach": po.get("tp_reach"), "wider_sl_arms": po.get("wider_sl_arms"),
                      "verdict": {"verdict": v.get("verdict"), "r_diff": v.get("r_diff"), "resolved": v.get("resolved")}},
        "fidelity": {"replayed_actual_net_r": g["fidelity"]["replayed_actual_net_r"], "actual_net_r": g["fidelity"]["actual_net_r"],
                     "abs_gap_r": g["fidelity"]["abs_gap_r"]},
        "provenance": "ESTIMATED",
    }


# ---- aggregation (harness_stage0.summarize_arm -> cf_summary) ----------------------------------------------------
def _boot_ci(vals: List[float], groups: List[Any], n_boot: int = 500, seed: int = 7) -> Optional[List[float]]:
    """Percentile 95% CI of the mean, resampling GROUPS (trade-level groups; pass the trade key) not bars."""
    import random
    if not vals:
        return None
    by: Dict[Any, List[float]] = {}
    for x, g in zip(vals, groups):
        by.setdefault(g, []).append(x)
    keys = list(by)
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        pick = [rng.choice(keys) for _ in keys]
        flat = [x for k in pick for x in by[k]]
        means.append(sum(flat) / len(flat))
    means.sort()
    return [round(means[int(0.025 * n_boot)], 4), round(means[min(n_boot - 1, int(0.975 * n_boot))], 4)]


def cf_summary(trades: Sequence[dict]) -> Optional[dict]:
    """Aggregate block for ``summary.json`` from loaded harness rows. ``None`` when no row carries a ``cf`` block (the
    run was not graded: rendered "—", never 0). Population = the rows given; ungraded rows are counted, not dropped."""
    cfs = [t.get("cf") for t in trades if isinstance(t.get("cf"), dict)]
    if not cfs:
        return None
    graded = [c for c in cfs if c.get("status") == "graded"]
    out: Dict[str, Any] = {"schema": "cf_summary/1", "n_rows": len(trades), "n_with_cf": len(cfs), "n_graded": len(graded),
                           "n_could_not_grade": len(cfs) - len(graded), "provenance": "ESTIMATED"}
    keys = [c["trade_key"] for c in graded]

    def block(vals: List[Optional[float]]) -> Optional[dict]:
        pairs = [(v, k) for v, k in zip(vals, keys) if v is not None]
        if not pairs:
            return None
        v, k = [p[0] for p in pairs], [p[1] for p in pairs]
        return {"n": len(v), "mean_net_r": round(sum(v) / len(v), 4), "ci95_mean": _boot_ci(v, k)}

    out["original_brackets"] = block([((c["arms"].get("original_brackets") or {}).get("net_r")) for c in graded])
    out["replayed_actual"] = block([c["arms"].get("replayed_actual_net_r") for c in graded])
    # per-ARM means, not a per-trade max: a max over arms is a hindsight oracle. The best static arm is picked by the
    # consumer on TRAIN folds only (design § 1.1); these are the inputs it needs.
    def by_arm(rows: List[tuple]) -> Dict[str, dict]:
        acc: Dict[str, List[float]] = {}
        for k, v in rows:
            if v is not None:
                acc.setdefault(k, []).append(v)
        return {k: {"n": len(v), "mean_net_r": round(sum(v) / len(v), 4)} for k, v in sorted(acc.items())}
    out["alt_brackets_mean_by_cell"] = by_arm([(f"sl{a.get('sl_mult'):g}x_tp{a.get('tp_r'):g}R", a.get("net_r"))
                                                for c in graded for a in c["arms"]["alt_brackets"]])
    out["more_management_mean_by_arm"] = by_arm([(a["arm_id"], a.get("net_r")) for c in graded for a in c["arms"]["more_management"]])
    ps = [c["random_control"]["p_random_ge_replayed_actual"] for c in graded if c.get("random_control")]
    out["p_random_ge_actual"] = {"n": len(ps), "mean": None if not ps else round(sum(ps) / len(ps), 4)}
    mix: Dict[str, int] = {}
    for c in graded:
        vd = (c["post_exit"].get("verdict") or {}).get("verdict") or "null"
        mix[vd] = mix.get(vd, 0) + 1
    out["post_exit_verdict_mix"] = mix
    gaps = [c["fidelity"]["abs_gap_r"] for c in graded if c["fidelity"].get("abs_gap_r") is not None]
    out["fidelity_abs_gap_r"] = {"n": len(gaps), "mean": None if not gaps else round(sum(gaps) / len(gaps), 4),
                                 "max": None if not gaps else round(max(gaps), 4)}
    return out

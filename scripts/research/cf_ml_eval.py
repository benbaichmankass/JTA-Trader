#!/usr/bin/env python3
# wiring: library - CF-ML-EVAL: counterfactual block for ML dev-fold / holdout evaluations; imported by scripts/research/exit_head_holdout.py (and any ML eval driver that has the harness trade rows)
"""cf_ml_eval: report, BESIDE a model's realised R, what the counterfactual arms would have made on the same trades.

``cf_block(rows, bt=None, ...)`` takes the harness trade rows an evaluation was run on (``entry_time``, ``exit_time``, ``entry``, ``sl``,
``direction``, ``net_r`` ...) plus the harness summary (``__bt.json``, for the leg's trail geometry), fetches the bars keylessly, grades each
row with the ONE engine (``cf_harness.cf_fields``) and returns an aggregate: realised mean net R, the replay baseline, per-arm mean net R
and the post-exit verdict mix, with the replay-vs-harness fidelity beside them so a reader knows how far to believe an arm.

Never raises: any failure is returned as ``{"read_state": "could_not_look", "reason": ...}`` (never 0, never omitted), so an evaluation's own
verdict is unaffected. Pure of the model: it grades the TRADES, so it is the same table for any model evaluated on them.
Provenance ESTIMATED. Hindsight arms: a label/report, never a feature.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_bars  # noqa: E402
import cf_bulk  # noqa: E402
import cf_core  # noqa: E402
import cf_harness  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "cf_ml_eval/1"


def cf_block(rows: Sequence[dict], bt: Optional[dict] = None, *, timeframe: Optional[str] = None, symbol: Optional[str] = None,
             n_random: int = 30, max_rows: int = 3000, bars_fn: Optional[Callable[[str, str, float, float], List[dict]]] = None) -> Dict[str, Any]:
    try:
        rows = [r for r in rows if isinstance(r, dict)]
        tf = timeframe or (bt or {}).get("timeframe")
        sym = symbol or (bt or {}).get("symbol") or next((r.get("symbol") for r in rows if r.get("symbol")), None)
        if not rows:
            return {"schema": SCHEMA, "read_state": "could_not_look", "reason": "no_rows"}
        if tf not in cf_bars.TF_SECONDS or not sym:
            return {"schema": SCHEMA, "read_state": "could_not_look", "reason": "timeframe_or_symbol_unresolved", "n_rows": len(rows)}
        if not cf_bulk.is_crypto(sym):
            return {"schema": SCHEMA, "read_state": "could_not_look", "reason": "no_bar_source", "n_rows": len(rows)}
        use = rows[:max_rows]
        side = {"params": (bt or {}).get("params") or {}}
        cfg = {"timeframe": tf, **({"max_hold_bars": mb} if (mb := cf_bulk.timeout_bars_for((bt or {}).get("strategy") or use[0].get("strategy"))) else {})}
        h = cf_core.resolve_horizon({"timeframe": tf}, cfg)["seconds"]
        t_in = [lrc._ts(r.get("entry_time")) for r in use]
        t_out = [lrc._ts(r.get("exit_time")) for r in use]
        pairs = [(a, b) for a, b in zip(t_in, t_out) if a is not None and b is not None]
        if not pairs:
            return {"schema": SCHEMA, "read_state": "could_not_look", "reason": "row_times_unreadable", "n_rows": len(rows)}
        lo, hi = min(p[0] for p in pairs), max(p[1] for p in pairs) + h
        bars = (bars_fn or (lambda s, t, a, b: cf_bars.historical_bars(s, t, a, b)))(sym, tf, lo, hi)
        if not bars:
            return {"schema": SCHEMA, "read_state": "could_not_look", "reason": "no_bars", "n_rows": len(rows)}
        store = cf_bulk.BarStore(bars)
        graded: List[dict] = []
        for r in use:
            a, b = lrc._ts(r.get("entry_time")), lrc._ts(r.get("exit_time"))
            if a is None or b is None:
                continue
            row = dict(r, symbol=sym)
            graded.append({"cf": cf_harness.cf_fields(row, store.window(a, b + h), None, cfg, n_random=n_random,
                                                      leg_meta=cf_bulk.leg_meta_for(row, side))})
        summ = cf_harness.cf_summary(graded)
        realised = [lrc._num(r.get("net_r")) for r in use]
        realised = [x for x in realised if x is not None]
        return {"schema": SCHEMA, "read_state": "measured", "n_rows": len(rows), "n_used": len(use), "timeframe": tf,
                "realised_mean_net_r": None if not realised else round(sum(realised) / len(realised), 4),
                "cf_summary": summ, "provenance": "ESTIMATED",
                "note": "arms are hindsight counterfactuals; read them with fidelity_abs_gap_r beside them"}
    except Exception as exc:  # allow-silent: a failed counterfactual read is a recorded state on the evaluation, never a failure of the evaluation itself
        return {"schema": SCHEMA, "read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}

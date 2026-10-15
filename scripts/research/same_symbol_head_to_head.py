#!/usr/bin/env python3
# wiring: research/queue/RQ-*-SSA-*.yaml (run.command, via research-script-run.yml) + tests/test_same_symbol_head_to_head.py
"""Same-symbol head-to-head — which of N legs on ONE (account, symbol) earns the slot?

OPERATOR, 2026-10-15 (verbatim): "If we're running the same strategy and symbol on 2 different
timeframes, than we need to make sure that we know how to allocate the trades properly (and not, say
alphabetically), or we need to choose the better one based on testing on run with that one".

HARNESS: ``scripts/backtest_system.py::run_system_backtest`` — the REAL ``aggregate_intents`` election, ONE shared
netted position per symbol (a single position slot), each strategy's REAL ``order_package``/``monitor``, and the
venue-aware cost stack (fee + slippage + perp funding). Arms (fixed before any run):

  * ``solo:<leg>``   each leg alone in the roster;
  * ``together``     all legs under the live election.

RULE (registered before the run, in the unit's ``decision_rule``): the arm with the highest OOS
net-R per capital-day wins; if ``together`` does not beat the best single arm, the best single arm
is kept alone. Strictly greater: a tie keeps the single arm (fewer legs, no election to be wrong about).

  net R          = sum over OOS closed trades of pnl / (qty * |entry - entry_stop|)   (pnl is net of fee+slippage+funding)
  capital-days   = sum over OOS closed trades of (exit_ts - entry_ts) in days          (one slot -> no double count)
  metric         = net R / capital-days

OOS = trades whose entry is on/after ``oos_start``. Each arm must have >= ``min_oos_trades`` OOS trades to be
ranked; otherwise the verdict is ``indeterminate`` and names the starved arm (a thin leg is a DATA verdict,
never a silent win).

COST STACK TRAP (do not remove): ``backtest_system`` module globals ``SLIPPAGE_BPS_ROUNDTRIP`` /
``FUNDING_BPS_PER_WINDOW`` default to 0.0 and are only set from ``execution_costs`` inside its ``main()``.
Calling ``run_system_backtest`` directly without setting them is a fee-only run. ``apply_cost_policy`` sets
them here and the policy is recorded in the output.

Output: ``<out>/verdict.json`` (script_run contract) and ``<out>/head_to_head.json`` — the evidence record. The record
is the shape ``scripts/ci/check_same_symbol_allocation.py`` accepts once committed under ``comms/same_symbol_allocation/``.

Tier-1 research tooling. Reads candles, writes only under ``--out``. No config, no order path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_REPO = Path(__file__).resolve().parents[2]

SECONDS_PER_DAY = 86400.0


def metric_from_trades(trades: Sequence[Dict[str, Any]], oos_start: Any) -> Dict[str, Any]:
    """OOS net-R per capital-day from plain trade dicts ``{entry_ts, exit_ts, qty, entry, sl, pnl}``."""
    import pandas as pd

    cut = pd.Timestamp(oos_start, tz="UTC") if not hasattr(oos_start, "tzinfo") else pd.Timestamp(oos_start)
    net_r = 0.0
    cap_days = 0.0
    n = 0
    skipped = 0
    for t in trades:
        et = pd.Timestamp(t["entry_ts"])
        if et.tzinfo is None:
            et = et.tz_localize("UTC")
        if et < cut:
            continue
        risk = abs(float(t["qty"]) * (float(t["entry"]) - float(t["sl"])))
        if risk <= 0:
            skipped += 1
            continue
        xt = pd.Timestamp(t["exit_ts"])
        if xt.tzinfo is None:
            xt = xt.tz_localize("UTC")
        net_r += float(t["pnl"]) / risk
        cap_days += max((xt - et).total_seconds(), 0.0) / SECONDS_PER_DAY
        n += 1
    return {
        "n_oos": n, "n_skipped_zero_risk": skipped,
        "net_r": round(net_r, 4), "capital_days": round(cap_days, 4),
        "net_r_per_capital_day": round(net_r / cap_days, 6) if cap_days > 0 else None,
    }


def decide(arms: Dict[str, Dict[str, Any]], min_oos_trades: int) -> Dict[str, Any]:
    """The registered rule, pure. ``arms`` maps ``solo:<leg>`` / ``together`` to a ``metric_from_trades`` dict."""
    solos = {k: v for k, v in arms.items() if k.startswith("solo:")}
    if "together" not in arms or len(solos) < 2:
        return {"verdict": "indeterminate", "winner": None, "reason": "need together + >=2 solo arms"}
    starved = sorted(k for k, v in arms.items()
                     if v.get("n_oos", 0) < min_oos_trades or v.get("net_r_per_capital_day") is None)
    if starved:
        return {"verdict": "indeterminate", "winner": None,
                "reason": f"arm(s) below min_oos_trades={min_oos_trades} or zero capital-days: {starved}"}
    best_single = max(solos, key=lambda k: (solos[k]["net_r_per_capital_day"], k))
    together_wins = arms["together"]["net_r_per_capital_day"] > solos[best_single]["net_r_per_capital_day"]
    winner = "together" if together_wins else best_single
    return {"verdict": "pass", "winner": winner, "best_single": best_single,
            "keep_legs": "all (live election)" if together_wins else best_single.split(":", 1)[1],
            "reason": ("together beats the best single arm" if together_wins
                       else "together does not beat the best single arm -> keep it alone")}


def apply_cost_policy(bs: Any, symbol: str) -> Dict[str, Any]:
    """Set backtest_system's module cost globals the way its main() does; return the policy for the record."""
    ec = bs.execution_costs
    bs.SLIPPAGE_BPS_ROUNDTRIP = ec.slippage_bps_roundtrip_for(symbol)
    bs.FUNDING_BPS_PER_WINDOW = ec.funding_bps_per_window_for(symbol)
    return {"fee_bps_roundtrip": bs.FEE_BPS_ROUNDTRIP, "slippage_bps_roundtrip": bs.SLIPPAGE_BPS_ROUNDTRIP,
            "funding_bps_per_window": bs.FUNDING_BPS_PER_WINDOW, "funding_window_hours": bs.FUNDING_WINDOW_HOURS}


def _load_bs() -> Any:
    sys.path.insert(0, str(_REPO))
    import importlib.util
    spec = importlib.util.spec_from_file_location("backtest_system", _REPO / "scripts" / "backtest_system.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_system"] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


def _trade_dicts(closed: Sequence[Any]) -> List[Dict[str, Any]]:
    return [{"entry_ts": t.entry_ts, "exit_ts": t.exit_ts, "qty": t.qty, "entry": t.entry,
             "sl": t.sl if t.sl is not None else t.entry, "pnl": t.pnl} for t in closed]


def run(unit_path: Path, out_dir: Path) -> int:
    import yaml

    unit = yaml.safe_load(unit_path.read_text())
    h = unit["head_to_head"]
    legs: List[str] = list(h["legs"])
    symbol: str = h["symbol"]
    out_dir.mkdir(parents=True, exist_ok=True)

    def finish(verdict: Dict[str, Any], population: str, n: Any, **extra: Any) -> int:
        rec = {"unit": unit["id"], "symbol": symbol, "legs": legs, "accounts": h.get("accounts"), **extra, **verdict}
        (out_dir / "head_to_head.json").write_text(json.dumps(rec, indent=2, default=str))
        (out_dir / "verdict.json").write_text(json.dumps({
            "verdict": verdict["verdict"], "read_state": extra.get("read_state", "measured"),
            "population": population, "n": n, "measurement": rec, "note": verdict.get("reason")}, default=str))
        return 0

    bs = _load_bs()
    missing = [leg for leg in legs if leg not in bs.ROSTER]
    if missing:
        return finish({"verdict": "indeterminate", "winner": None,
                       "reason": f"legs not registered in backtest_system.ROSTER: {missing} — harness gap, not a verdict"},
                      f"{symbol} {legs}", "null", read_state="unavailable")
    from src.research import risk_basis
    from src.runtime.intents import aggregate_intents  # noqa: F401  (import proves the live election is reachable)

    try:
        src = bs._backtest_data_source.resolve_or_refuse(symbol, "5m", h.get("data"))
    except Exception as exc:  # noqa: BLE001
        return finish({"verdict": "indeterminate", "winner": None, "reason": f"data source: {exc}"},
                      f"{symbol} {legs}", "null", read_state="unavailable")
    if not src.ok:
        return finish({"verdict": "indeterminate", "winner": None,
                       "reason": "no 5m candle source for the symbol: " + str(getattr(src, "reason", "unresolved"))},
                      f"{symbol} {legs}", "null", read_state="unavailable")
    cost = apply_cost_policy(bs, symbol)
    live = risk_basis.live_risk(h.get("risk_account", risk_basis.DEFAULT_REFERENCE_ACCOUNT))
    if not live.ok or live.percent is None:
        return finish({"verdict": "indeterminate", "winner": None, "reason": f"live risk unresolved: {live.describe()}"},
                      f"{symbol} {legs}", "null", read_state="unavailable")
    base5m = bs._load_candles(src.path)

    def one(roster: List[str]) -> Dict[str, Any]:
        s = bs.run_system_backtest(
            base5m, roster=roster, start=h.get("start"), end=h.get("end"),
            initial_balance=float(h.get("initial_balance", 10_000.0)), risk_pct=float(live.percent),
            daily_loss_pct=float(h.get("daily_loss_pct", 3.0)), signal_ttl_bars=int(h.get("signal_ttl_bars", 1)),
            overrides={}, refresh=False, clock_tf=h.get("clock_tf", "15m"), attach_full=True, symbol=symbol)
        return metric_from_trades(_trade_dicts(s["closed_trades"]), h["oos_start"])

    arms = {f"solo:{leg}": one([leg]) for leg in legs}
    arms["together"] = one(legs)
    verdict = decide(arms, int(h.get("min_oos_trades", 20)))
    return finish(verdict, f"{symbol} legs={legs} OOS from {h['oos_start']} (candles {src.path})",
                  {k: v["n_oos"] for k, v in arms.items()}, arms=arms, cost_policy=cost,
                  risk_pct=live.percent, oos_start=h["oos_start"])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", required=True, help="queue unit id (RQ-...) or a YAML path")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    p = Path(a.unit)
    if not p.exists():
        p = _REPO / "research" / "queue" / f"{a.unit}.yaml"
    return run(p, Path(a.out))


if __name__ == "__main__":
    sys.exit(main())

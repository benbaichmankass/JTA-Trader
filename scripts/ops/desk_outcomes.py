#!/usr/bin/env python3
# wiring: called by .github/workflows/desk-decisions-mirror.yml after each mirror onto main.
"""DESK-6-SHADOW-PILOT -- the outcome join: every desk decision becomes a graded training row.

Design docs/plans/claude-trading-desk-DESIGN.md § 4.1 / § 4A: a label is (packet, decision, realised
outcome). A shadow ``propose_entry`` is replayed on the REAL price path from its ``info_cutoff_at``,
whether or not anything traded, net of the full cost stack, and the result is appended to
``comms/desk/outcomes.jsonl`` (schema ``desk_decision.schema.json`` ``outcomes``; validated by
desk-records-guard). This is the minimal replay DESK-6 needs; DESK-20 owns the full joiner (realised
fills per account, the in-trade / exit roles, the no_trade baseline bracket).

THE REPLAY (computed, never measured; conservative where a bar cannot say what came first)
* forward bars = bars that OPEN at or after ``info_cutoff_at`` (nothing the packet could not see);
* entry: ``market`` fills at the first forward bar's open; ``limit`` (long: low <= level) and
  ``stop`` (long: high >= level) fill at the level, or at the open when the bar gaps through it,
  within ``good_till_bars`` -- else ``expired_unfilled`` (every number null);
* from the fill bar on, up to ``horizon_bars`` bars: a bar touching the stop exits at the stop, one
  touching the target exits at the target, a bar touching BOTH is taken as the stop (the pessimistic
  order, so a replay never flatters the desk); neither by the horizon exits at that bar's close;
* R = the proposal's own planned risk |entry.level - stop|; ``net_r`` = side * (exit - fill) / R minus
  the round-trip cost in R from ``execution_costs.roundtrip_cost_r`` with the venue-aware policy the
  scan builder uses (``desk_scan_packet.cost_policy``: fee + slippage + funding over the hold);
* ``mae_r`` / ``mfe_r`` from bar extremes after the fill (gross), ``giveback_r`` = mfe - gross exit R.

``no_trade`` / ``watch_note`` rows get ONE ``not_computable`` row naming why: their label is the best
baseline bracket from the same packet (design § 8.1), priced by DESK-20 on the DESK-7 harness. A
decision whose horizon has not elapsed, or whose candles could not be read, gets NO row this run
(could-not-look is retried, never written as zero).

Exit: 0 ok (``written=N``) · 2 could not look (decisions unreadable).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts" / "ci", ROOT / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_desk_records as cdr  # noqa: E402
import desk_scan_packet as dsp  # noqa: E402

from src.runtime import execution_costs as xc  # noqa: E402

NO_TRADE_REASON = ("no_trade/watch_note label is the best baseline bracket from the same packet (design § 8.1); "
                   "priced by DESK-20 on the DESK-7 harness, not built yet")
Bar = dict[str, float]


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r4(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def replay(pr: dict, cutoff: datetime, bars: Sequence[Bar], cost: Callable[..., float]) -> dict | None:
    """Replay one proposal. None = not decidable yet (horizon or good-till window not elapsed)."""
    sec = dsp.TF_SECONDS[pr["timeframe"]]
    fwd = [b for b in bars if b["time"] >= cutoff.timestamp()]
    long_ = pr["side"] == "long"
    e, sl, tp = pr["entry"]["level"], pr["stop"]["level"], pr["tp"]["level"]
    risk = abs(e - sl)
    if risk <= 0:
        return {"kind": "not_computable", "reason": "proposal risk |entry - stop| is zero"}
    fill_i, fill = None, None
    for i, b in enumerate(fwd[: pr["entry"]["good_till_bars"]]):
        t = pr["entry"]["type"]
        if t == "market":
            fill_i, fill = i, b["open"]
        elif t == "limit" and (b["low"] <= e if long_ else b["high"] >= e):
            fill_i, fill = i, (min(b["open"], e) if long_ else max(b["open"], e))
        elif t == "stop" and (b["high"] >= e if long_ else b["low"] <= e):
            fill_i, fill = i, (max(b["open"], e) if long_ else min(b["open"], e))
        if fill_i is not None:
            break
    if fill_i is None:
        if len(fwd) < pr["entry"]["good_till_bars"]:
            return None
        return {"kind": "expired_unfilled"}
    path = fwd[fill_i: fill_i + pr["horizon_bars"]]
    sgn = 1.0 if long_ else -1.0
    exit_px, reason, held = None, None, 0
    mae = mfe = 0.0
    for b in path:
        held += 1
        hi, lo = sgn * (b["high"] - fill) / risk, sgn * (b["low"] - fill) / risk
        mfe, mae = max(mfe, hi, lo), min(mae, hi, lo)
        hit_sl = b["low"] <= sl if long_ else b["high"] >= sl
        hit_tp = b["high"] >= tp if long_ else b["low"] <= tp
        if hit_sl:  # both in one bar -> the stop: the pessimistic order
            exit_px, reason = sl, "sl_hit"
            break
        if hit_tp:
            exit_px, reason = tp, "tp_hit"
            break
    if exit_px is None:
        if len(path) < pr["horizon_bars"]:
            return None
        exit_px, reason = path[-1]["close"], "horizon"
    gross = sgn * (exit_px - fill) / risk
    c = cost(entry=fill, exit_price=exit_px, risk=risk, hold_hours=held * sec / 3600.0)
    return {"kind": "replayed", "net_r": gross - c, "mae_r": mae, "mfe_r": mfe,
            "giveback_r": max(0.0, mfe - gross), "bars_held": held, "close_reason": reason}


def _cost_fn(symbol: str) -> Callable[..., float]:
    fee, slip, fund = dsp.cost_policy(symbol)

    def f(**kw) -> float:
        return xc.roundtrip_cost_r(fee_bps_roundtrip=fee, slippage_bps_roundtrip=slip,
                                   funding_bps_per_window=fund, **kw)["total_cost_r"]
    return f


def outcome_row(d: dict, res: dict, now: datetime, policy: str | None) -> dict:
    oid = "DO-" + d["decision_id"][3:]
    nums = {k: _r4(res.get(k)) for k in ("net_r", "mae_r", "mfe_r", "giveback_r")}
    return {"schema_version": 2, "outcome_id": oid, "decision_id": d["decision_id"], "kind": res["kind"],
            "account_id": None, "order_package_id": None, "trade_id": None, "computed_at": _iso(now),
            **nums, "bars_held": res.get("bars_held"), "close_reason": res.get("close_reason"),
            "provenance": "computed", "net_of_full_cost_stack": res["kind"] == "replayed",
            "cost_policy": policy if res["kind"] == "replayed" else None, "reason": res.get("reason")}


def run(decisions: Path, outcomes: Path, candles: Callable[[str, str], list[Bar] | None],
        now: datetime | None = None) -> dict[str, object]:
    if not decisions.exists():
        return {"state": "could_not_look", "reason": f"{decisions} missing"}
    now = now or datetime.now(timezone.utc)
    done = {r.get("decision_id") for _, r, err in cdr._rows(outcomes) if not err and isinstance(r, dict)} \
        if outcomes.exists() else set()
    new, waiting = [], []
    for _, d, err in cdr._rows(decisions):
        if err or not isinstance(d, dict) or d.get("role") != "entry_generation" or d["decision_id"] in done:
            continue
        cutoff = cdr._ts(d["info_cutoff_at"])
        if now <= cutoff:
            continue
        if d["action"] != "propose_entry":
            new.append(outcome_row(d, {"kind": "not_computable", "reason": NO_TRADE_REASON}, now, None))
            continue
        if d.get("basis") == "mechanics":  # DESK-18E probe: a mechanics test, not an edge sample -- never replayed into a scorer
            new.append(outcome_row(d, {"kind": "not_computable", "reason": "mechanics probe: excluded from edge replay"}, now, None))
            continue
        pr = d["proposal"]
        if pr["onboarding"] != "onboarded":
            new.append(outcome_row(d, {"kind": "not_computable", "reason": "onboarding pending: no priced candles"}, now, None))
            continue
        if pr["timeframe"] not in dsp.TF_SECONDS:
            new.append(outcome_row(d, {"kind": "not_computable", "reason": f"unknown timeframe {pr['timeframe']}"}, now, None))
            continue
        span = timedelta(seconds=dsp.TF_SECONDS[pr["timeframe"]] * (pr["entry"]["good_till_bars"] + pr["horizon_bars"]))
        if now < cutoff + timedelta(seconds=dsp.TF_SECONDS[pr["timeframe"]]):
            waiting.append(d["decision_id"])
            continue
        bars = candles(pr["symbol"], pr["timeframe"])
        if not bars:
            waiting.append(d["decision_id"])  # could not look: retried next run, never written
            continue
        closed = [b for b in bars if b["time"] + dsp.TF_SECONDS[pr["timeframe"]] <= now.timestamp()]
        res = replay(pr, cutoff, closed, _cost_fn(pr["symbol"]))
        if res is None:
            if now > cutoff + span + timedelta(days=2):
                res = {"kind": "not_computable", "reason": "forward candles missing past the horizon + 2 days"}
            else:
                waiting.append(d["decision_id"])
                continue
        policy = "execution_costs.roundtrip_cost_r with desk_scan_packet.cost_policy(%s): fee %.2f + slippage %.2f bps rt, funding %.2f bps/window" % (
            (pr["symbol"],) + tuple(dsp.cost_policy(pr["symbol"])))
        new.append(outcome_row(d, res, now, policy))
    if new:
        text = outcomes.read_text() if outcomes.exists() else ""
        sep = "" if (not text or text.endswith("\n")) else "\n"
        outcomes.write_text(text + sep + "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in new))
    return {"state": "ok", "written": len(new), "outcome_ids": [r["outcome_id"] for r in new], "waiting": waiting}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--decisions", type=Path, default=cdr.DECISIONS)
    ap.add_argument("--outcomes", type=Path, default=cdr.OUTCOMES)
    a = ap.parse_args(argv)
    res = run(a.decisions, a.outcomes, lambda s, tf: dsp.candles_from_api([s], tf).get(s))
    print(json.dumps(res, indent=2))
    return 0 if res["state"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())

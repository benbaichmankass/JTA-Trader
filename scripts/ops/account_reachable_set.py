#!/usr/bin/env python3
# wiring: manual-only - run on demand by a session/review that needs an account's reachable set (row SMALL-ACCOUNT-RISK); it replaces a recorded constant, so there is nothing to schedule
"""WHICH SYMBOLS CAN THIS ACCOUNT ACTUALLY TRADE, RIGHT NOW? -- derived on demand, never a constant.

WHY (row SMALL-ACCOUNT-RISK, pipeline item
BL-20260910-THE-ALPACA-LIVE-REACHABLE-SYMBOL-SET-IS-RECORDED-AS-A-CONSTANT-AND-GDX-HAS-SINCE-FALLEN-OUT-OF-IT, option (a))
--------------------------------------------------------------------------------------------------------------------------
config/accounts.yaml and a 2026-08-25 sweep recorded alpaca_live's reachable set as a fixed list. Reachability on a
whole-share cash book is a function of price, stop distance and balance, so the list went stale (GDX fell out) and the drift
was in the permissive direction. This script is the replacement: it runs the LIVE sizer,
``src/units/accounts/risk.py::RiskManager.position_size``, over the account's CURRENT roster at the CURRENT balance and
CURRENT prices, and its output is what a session reads. Nothing here is a recorded list.

It also answers the companion item
BL-20260823-ALPACA-RISK-SIZING-EXCEEDS-ACCOUNT-NOTIONAL-AT-EVERY-FUNDING-LEVEL: per sized (leg, symbol) it reports the notional
and notional as a share of equity, and a WHAT-IF table: how many of the reachable symbols survive a per-position notional cap
of 25 / 33 / 50 / 75 / 90 % of equity. The what-if is arithmetic over the sizer's output (qty floored to whole shares under the
cap); it changes no config and no sizer.

SOURCES (read-only; never the order path)
-----------------------------------------
  * roster + risk block : config/accounts.yaml::<account>  (strategies:, risk:, exchange)
  * leg symbols + stop  : config/strategies.yaml::<leg>    (symbols minus pool_exclude; atr_stop_mult, atr_period, timeframe)
  * balance             : /api/diag/broker_account_status  (MEASURED: equity, buying_power, captured_at)
  * prices + ATR        : /api/bot/candles                  (the bot's own exchange feed; last close; Wilder ATR on the served bars)

PROVENANCE. The cash wall (one share vs buying power) is MEASURED. The stop distance is ESTIMATED: atr_stop_mult x ATR on the
bars the candles route serves, which may include extended-hours bars and differ from the strategy's own ATR at decision time.
Sizing assumes full confidence (the confidence scalar can only LOWER size), so the qty is an UPPER BOUND, and the record says so.

    python3 scripts/ops/account_reachable_set.py --account alpaca_live [--out PATH] [--equity X --buying-power Y]
    python3 scripts/ops/account_reachable_set.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import yaml

SCHEMA = "account_reachable_set/1"
CANDLES_BASE = "https://ict-bot.duckdns.org/api/bot/candles"
WHAT_IF_CAPS = (0.25, 0.33, 0.50, 0.75, 0.90)
CANDLE_LIMIT = {"1h": 200, "1d": 60}


def wilder_atr(high: list[float], low: list[float], close: list[float], n: int) -> float | None:
    """ATR(n), Wilder smoothing; None when fewer than n+1 bars."""
    if len(close) < n + 1:
        return None
    trs = [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])) for i in range(1, len(close))]
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def roster_legs(account: str, accounts: dict[str, Any], strategies: dict[str, Any]) -> list[dict[str, Any]]:
    """(leg, symbols, stop rule) for every leg on the account's roster. Symbols come from the STRATEGY (operator 2026-11-04:
    an account configures strategies, never symbols), minus the leg's own pool_exclude."""
    acct = accounts[account]
    out = []
    for leg in acct.get("strategies") or []:
        s = strategies.get(leg) or {}
        excl = set((s.get("pool_exclude") or {}).keys())
        out.append({
            "leg": leg,
            "symbols": [x for x in (s.get("symbols") or []) if x not in excl],
            "excluded": sorted(excl),
            "timeframe": str(s.get("timeframe") or "1h"),
            "atr_period": int(s.get("atr_period") or 14),
            "atr_stop_mult": float(s.get("atr_stop_mult") or 2.0),
            "tp_r": float(s.get("tp_r") or 1.5),
        })
    return out


def size_one(rm: Any, *, leg: str, symbol: str, entry: float, stop_dist: float, tp_r: float, equity: float,
             buying_power: float | None, whole: bool, market_type: str, direction: str = "long") -> dict[str, Any]:
    """One (leg, symbol) through the LIVE sizer. Returns qty, notional, risk and the binding reason -- never a bare bool."""
    from src.core.coordinator import OrderPackage

    sign = 1 if direction == "long" else -1
    sl = entry - sign * stop_dist
    tp = entry + sign * tp_r * stop_dist
    pkg = OrderPackage(strategy=leg, symbol=symbol, direction=direction, entry=entry, sl=sl, tp=tp,
                       confidence=1.0, meta={})
    basis: dict[str, Any] = {}
    qty = float(rm.position_size(pkg, equity, available_usd=buying_power, total_account_usd=equity,
                                 whole_units=whole, market_type=market_type, margin_basis_out=basis) or 0.0)
    budget = equity * float(rm.risk_pct)
    cash_cap = basis.get("max_qty_by_margin")
    if qty > 0:
        reason = "ok"
        ideal = budget / stop_dist if stop_dist > 0 else math.inf
        if whole and ideal < 1 <= qty:
            reason = "ok_round_up"          # risk.py round-up-to-one-share (overshoots the per-trade budget)
        elif cash_cap is not None and qty <= cash_cap < ideal:
            reason = "ok_cash_capped"       # the 0.9 x buying-power cap bound, not risk
    elif whole and buying_power is not None and entry > 0.9 * buying_power:
        reason = "cash"                     # one share exceeds 0.9 x buying power
    else:
        reason = "stop_risk_over_round_up"  # one share's stop risk > 1.5 x budget
    risk_usd = qty * stop_dist
    return {
        "leg": leg, "symbol": symbol, "entry": round(entry, 4), "stop_dist": round(stop_dist, 4),
        "qty": qty, "notional_usd": round(qty * entry, 2),
        "notional_pct_equity": round(qty * entry / equity, 4) if equity > 0 else None,
        "risk_usd": round(risk_usd, 2), "risk_x_budget": round(risk_usd / budget, 3) if budget > 0 else None,
        "reason": reason,
    }


def what_if(rows: list[dict[str, Any]], equity: float, caps=WHAT_IF_CAPS) -> list[dict[str, Any]]:
    """For each per-position cap c (fraction of equity): qty' = min(qty, floor(c*equity/entry)); count survivors."""
    sized = [r for r in rows if r["qty"] > 0]
    out = []
    for c in caps:
        cap_usd = c * equity
        survivors, trimmed, lost = 0, 0, []
        for r in sized:
            q2 = min(r["qty"], math.floor(cap_usd / r["entry"])) if r["entry"] > 0 else 0
            if q2 >= 1:
                survivors += 1
                trimmed += int(q2 < r["qty"])
            else:
                lost.append(f'{r["leg"]}:{r["symbol"]}')
        out.append({"cap_pct_equity": c, "cap_usd": round(cap_usd, 2), "sized_before": len(sized),
                    "still_sized": survivors, "trimmed": trimmed, "lost": len(lost), "lost_examples": lost[:12]})
    return out


def _http_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_candles(symbol: str, interval: str) -> list[dict[str, Any]]:
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": CANDLE_LIMIT.get(interval, 200)})
    for attempt in range(3):
        try:
            d = _http_json(f"{CANDLES_BASE}?{q}")
            return d.get("candles") or []
        except Exception:  # noqa: BLE001 -- retried, then reported as no_data, never as 0
            time.sleep(1.5 * (attempt + 1))
    return []


def fetch_balance(account: str) -> dict[str, Any]:
    raw = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), "broker_account_status"],
                         capture_output=True, text=True, timeout=120, check=False)
    if raw.returncode != 0:
        raise SystemExit(f"broker_account_status unreadable (rc={raw.returncode}); pass --equity/--buying-power")
    d = json.loads(raw.stdout)
    for a in d.get("accounts") or []:
        if a.get("account_id") == account:
            cap = ((a.get("status_flags") or {}).get("capacity") or {})
            return {"equity": float(cap["equity"]), "buying_power": float(cap["buying_power"]),
                    "cash": float(cap.get("cash") or 0), "multiplier": cap.get("multiplier"),
                    "captured_at": d.get("captured_at"), "source": "/api/diag/broker_account_status"}
    raise SystemExit(f"{account} not in broker_account_status")


def run(account: str, *, balance: dict[str, Any], candles: Callable[[str, str], list[dict[str, Any]]],
        accounts: dict[str, Any], strategies: dict[str, Any]) -> dict[str, Any]:
    from src.units.accounts.risk import RiskManager, requires_whole_unit_qty

    acct = accounts[account]
    rm = RiskManager(acct.get("risk") or {}, dry_run=True, account_id="")
    whole = requires_whole_unit_qty(acct.get("exchange"))
    market_type = str(acct.get("market_type") or "spot")
    direction = "short" if str(acct.get("side_filter") or "").lower() == "short" else "long"
    equity, bp = balance["equity"], balance.get("buying_power")
    legs = roster_legs(account, accounts, strategies)
    rows: list[dict[str, Any]] = []
    cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for L in legs:
        for sym in L["symbols"]:
            key = (sym, L["timeframe"])
            if key not in cache:
                cache[key] = candles(sym, L["timeframe"])
            c = cache[key]
            atr = wilder_atr([b["high"] for b in c], [b["low"] for b in c], [b["close"] for b in c], L["atr_period"])
            if not c or atr is None or atr <= 0:
                rows.append({"leg": L["leg"], "symbol": sym, "qty": 0.0, "reason": "no_data",
                             "notional_usd": None, "notional_pct_equity": None, "entry": None})
                continue
            r = size_one(rm, leg=L["leg"], symbol=sym, entry=float(c[-1]["close"]),
                         stop_dist=L["atr_stop_mult"] * atr, tp_r=L["tp_r"], equity=equity, buying_power=bp,
                         whole=whole, market_type=market_type, direction=direction)
            r["price_bar_time"] = datetime.fromtimestamp(int(c[-1]["time"]), tz=timezone.utc).isoformat()
            rows.append(r)
    sized = [r for r in rows if r["qty"] > 0]
    by_reason: dict[str, int] = {}
    for r in rows:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    max_n = max((r["notional_pct_equity"] for r in sized), default=None)
    return {
        "schema": SCHEMA, "account": account, "generated_at": datetime.now(timezone.utc).isoformat(),
        "balance": balance, "risk_pct": rm.risk_pct, "whole_units": whole,
        "max_gross_exposure_pct": rm.max_gross_exposure_pct or None,
        "population": {"legs": [L["leg"] for L in legs], "pairs": len(rows),
                       "symbols": len({r["symbol"] for r in rows})},
        "read_state": "measured" if rows and by_reason.get("no_data", 0) < len(rows) else "unreadable",
        "provenance": {"cash_wall": "MEASURED", "stop_distance": "ESTIMATED (atr_stop_mult x ATR on candles-route bars)",
                       "qty": "UPPER BOUND (confidence 1.0; the scalar only lowers size)"},
        "counts": {"sized": len(sized), "by_reason": by_reason},
        "reachable": sorted({r["symbol"] for r in sized}),
        "max_notional_pct_equity": max_n,
        "what_if_per_position_cap": what_if(rows, equity),
        "rows": rows,
    }


def _self_test() -> int:
    accounts = {"acct": {"exchange": "alpaca", "side_filter": "long", "strategies": ["legA"],
                         "risk": {"risk_pct": 0.02, "max_dd_pct": 0.1, "daily_loss_pct": 0.1}}}
    strategies = {"legA": {"symbols": ["CHEAP", "MID", "PRICEY", "WIDE", "NODATA", "EXCL"], "pool_exclude": {"EXCL": "x"},
                           "timeframe": "1h", "atr_period": 3, "atr_stop_mult": 2.0, "tp_r": 1.5}}

    def bars(px: float, rng: float) -> list[dict[str, Any]]:
        return [{"time": 1_700_000_000 + 3600 * i, "open": px, "high": px + rng / 2, "low": px - rng / 2, "close": px}
                for i in range(10)]

    feed = {"CHEAP": bars(20.0, 0.5), "MID": bars(90.0, 1.0), "PRICEY": bars(500.0, 2.0), "WIDE": bars(60.0, 6.0)}
    res = run("acct", balance={"equity": 200.0, "buying_power": 200.0, "captured_at": "t"},
              candles=lambda s, tf: feed.get(s, []), accounts=accounts, strategies=strategies)
    by = {r["symbol"]: r for r in res["rows"]}
    assert "EXCL" not in by, "pool_exclude must drop the symbol"
    assert by["NODATA"]["reason"] == "no_data" and by["NODATA"]["notional_usd"] is None, "no data is not 0"
    assert by["PRICEY"]["reason"] == "cash" and by["PRICEY"]["qty"] == 0, by["PRICEY"]
    # CHEAP: budget 4, stop 1 -> 4 shares = $80
    assert by["CHEAP"]["qty"] == 4 and by["CHEAP"]["reason"] == "ok", by["CHEAP"]
    # MID: stop 2 -> ideal 2 shares = $180 > 0.9*200=180 -> 2 fits exactly (cap qty 2.0)
    assert by["MID"]["qty"] == 2, by["MID"]
    # WIDE: stop 12 > 1.5*4 -> refused on stop risk
    assert by["WIDE"]["reason"] == "stop_risk_over_round_up", by["WIDE"]
    wi = {w["cap_pct_equity"]: w for w in res["what_if_per_position_cap"]}
    assert wi[0.25]["still_sized"] == 1 and wi[0.25]["lost"] == 1, wi[0.25]   # $50 cap: CHEAP 2 sh survives, MID lost
    assert wi[0.90]["still_sized"] == 2 and wi[0.90]["trimmed"] == 0, wi[0.90]
    assert res["reachable"] == ["CHEAP", "MID"]
    print("self-test OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--account", default="alpaca_live")
    ap.add_argument("--out")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--buying-power", type=float)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    from src.config.accounts_loader import load_accounts_dict
    accounts = load_accounts_dict()
    strategies = yaml.safe_load((REPO / "config/strategies.yaml").read_text())
    strategies = strategies.get("strategies", strategies)
    if a.equity is not None:
        balance = {"equity": a.equity, "buying_power": a.buying_power if a.buying_power is not None else a.equity,
                   "captured_at": None, "source": "--equity (operator/session supplied)"}
    else:
        balance = fetch_balance(a.account)
    res = run(a.account, balance=balance, candles=fetch_candles, accounts=accounts, strategies=strategies)
    text = json.dumps(res, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text + "\n")
    summary = {k: res[k] for k in ("account", "generated_at", "balance", "population", "read_state", "counts",
                                   "max_notional_pct_equity", "what_if_per_position_cap")}
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

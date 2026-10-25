#!/usr/bin/env python3
# wiring: manual-only — a per-leg diagnostic a session RUNS when live_vs_backtest.py reads BELOW_BACKTEST; no scheduled consumer.
"""Live-vs-backtest Stage B: join each LIVE closed trade to the BACKTEST trade on the same bar.

    python3 scripts/research/live_bt_trade_join.py --leg xrp_pullback_2h \\
        --bt-trades comms/research/RQ-20261016-077e-01/38936617653/arms/A__trades.jsonl \\
        --alt-trades C5=comms/research/RQ-20261016-077e-01/38936617653/arms/C5__trades.jsonl \\
        --out comms/research/live_bt_join/2026-10-18

``live_vs_backtest.py`` answers only "is cumulative live R below the bootstrap band" (a
percentile). It cannot say WHY. This tool names the cause (PI-20261015-10152047-0001,
checklist LIVE-BT-STAGE-B) by splitting the gap into components that each map to one fix:

  entry      live-only trades (a live entry the closed-bar backtest never took) minus
             backtest-only trades (a backtest entry live never took) over the same window
  exit       on MATCHED pairs: live gross R minus backtest gross R, net of entry slippage
  execution  entry slippage on matched pairs (fill vs the order package's entry) plus
             trades with no order package / zero duration / a close that is not TP or SL
  cost       not measurable from the closed-trades route (no fee/funding fields); the
             backtest's own modelled cost on the matched twins is reported as the reference
  regime     the BACKTEST's own net R over the live window: if the closed-bar strategy also
             lost there, the loss is the market, not the live implementation

R BASIS: the strategy's own ``meta.risk_per_unit`` recorded in the order package at signal
time (``order_packages.meta``) — NOT the package ``sl`` field, which carries the CURRENT
(trailed) stop. Live R here is GROSS of fees (the route publishes no fee field); backtest
twins are compared on ``gross_r`` and their modelled cost is reported beside.

Reads (read-only GETs of public routes): ``/api/bot/trades/closed`` (paged by ``offset``,
filtered by ``account_id``) and ``/api/bot/order-packages`` (``strategy`` + ``since``), or
saved payloads via ``--closed-json`` / ``--packages-json``. Dollar fields (``realizedPnl``,
``pnl``) are dropped on read and never written. Edits no config, places no order.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BASE = "https://ict-bot.duckdns.org"
TF_HOURS = {"15m": 0.25, "1h": 1, "2h": 2, "4h": 4, "1d": 24}
TP_SL_REASONS = {"tp", "sl", "tp_cross", "sl_cross", "take_profit", "stop", "trail_stop"}
_DOLLAR_KEYS = ("realizedPnl", "pnl")


def _ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed public host
        return json.load(r)


def fetch_closed(account: str, base: str = BASE) -> List[dict]:
    out: List[dict] = []
    off = 0
    while True:
        d = _get(f"{base}/api/bot/trades/closed?limit=200&offset={off}&account_id={account}&include_paper=true")
        rows = d.get("trades") if isinstance(d, dict) else d
        out += rows or []
        if not rows or len(rows) < 200:
            return out
        off += 200


def fetch_packages(leg: str, since: str, base: str = BASE) -> List[dict]:
    """The route caps at 200 newest-first with no offset, so page by moving ``since``."""
    seen: Dict[str, dict] = {}
    start = _ts(since)
    now = datetime.now(timezone.utc)
    while start < now:
        q = start.strftime("%Y-%m-%dT%H:%M:%S%%2B00:00")
        rows = _get(f"{base}/api/bot/order-packages?limit=200&strategy={leg}&include_paper=true&since={q}")["rows"]
        for r in rows:
            seen[r["orderPackageId"]] = r
        start += timedelta(days=20)
    return list(seen.values())


def _strip(rows: Iterable[dict]) -> List[dict]:
    return [{k: v for k, v in r.items() if k not in _DOLLAR_KEYS} for r in rows]


def load_bt(path: Path) -> List[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        r["_t"] = _ts(r["entry_time"])
    return rows


def _side(trade_side: str) -> str:
    return "long" if str(trade_side).lower() in ("buy", "long") else "short"


def _twin(bt: List[dict], bar: Optional[datetime], side: str, tol: timedelta) -> Optional[dict]:
    if bar is None:
        return None
    c = [x for x in bt if x["direction"] == side and abs(x["_t"] - bar) <= tol]
    return min(c, key=lambda x: abs(x["_t"] - bar)) if c else None


def join(leg: str, live: List[dict], packages: List[dict], bt: List[dict], timeframe: str,
         alts: Optional[Dict[str, List[dict]]] = None, tol_bars: int = 1,
         exclude: Optional[List[tuple]] = None) -> Dict[str, Any]:
    """Pure: live closes x order packages x backtest trades -> per-trade rows + the split.

    ``exclude`` = [(from, to), ...] spans in which the leg was NOT on the live account's
    roster: a backtest trade entered there is not a trade live "missed", so it leaves the
    backtest-only and backtest-window sums (and is counted in ``excluded_bt``)."""
    alts = alts or {}
    spans = [(_ts(a), _ts(b)) for a, b in (exclude or [])]
    tf = timedelta(hours=TF_HOURS[timeframe])
    tol = tf * tol_bars
    pk = [p for p in packages if p.get("strategy") == leg]
    rows: List[dict] = []
    used_bt: set = set()
    for t in sorted(live, key=lambda r: r["openedAt"]):
        side = _side(t["side"])
        op, cl = _ts(t["openedAt"]), _ts(t["closedAt"])
        cand = [p for p in pk if p.get("direction") == side and abs(_ts(p["createdAt"]) - op) <= timedelta(hours=3)]
        p = min(cand, key=lambda p: abs(_ts(p["createdAt"]) - op)) if cand else None
        meta = (p or {}).get("meta") or {}
        rpu = meta.get("risk_per_unit")
        bar = _ts(meta.get("entry_time"))
        sgn = 1 if side == "long" else -1
        row: Dict[str, Any] = {
            "trade_id": t.get("id"), "side": side, "opened_at": t["openedAt"], "closed_at": t["closedAt"],
            "close_reason": t.get("closeReason"), "pnl_provenance": t.get("pnlProvenance"),
            "decision_bar": meta.get("entry_time"), "package_id": (p or {}).get("orderPackageId"),
            "package_created_at": (p or {}).get("createdAt"),
            "minutes_into_bar": (round((_ts(p["createdAt"]) - bar).total_seconds() / 60, 1) if p and bar else None),
        }
        flags = []
        if p is None or not rpu:
            flags.append("no_package_or_r_basis")
        if op == cl:
            flags.append("zero_duration")
        if str(t.get("closeReason") or "").lower() not in TP_SL_REASONS:
            flags.append("close_not_tp_sl")
        row["flags"] = flags
        if rpu:
            row["live_gross_r"] = round((t["exitPrice"] - t["entryPrice"]) * sgn / rpu, 4)
            row["entry_slip_r"] = round((t["entryPrice"] - p["entry"]) * sgn / rpu, 4)  # + = adverse
        tw = _twin(bt, bar, side, tol)
        if tw is not None:
            used_bt.add(id(tw))
            row["bt"] = {"entry_time": tw["entry_time"], "exit_time": tw.get("exit_time"),
                         "exit_reason": tw.get("exit_reason"), "gross_r": tw.get("gross_r"),
                         "net_r": tw.get("net_r"),
                         "cost_r": round(tw.get("gross_r", 0) - tw.get("net_r", 0), 4)}
        row["alt"] = {}
        for name, arm in alts.items():
            aw = _twin(arm, bar, side, tol)
            row["alt"][name] = None if aw is None else {"net_r": aw.get("net_r"), "exit_reason": aw.get("exit_reason")}
        if "live_gross_r" not in row:
            row["class"] = "execution_unattributable"
        elif tw is None:
            row["class"] = "live_only"
        else:
            row["class"] = "matched"
        rows.append(row)
    lo = min(_ts(t["openedAt"]) for t in live) - tf if live else None
    hi = max(_ts(t["closedAt"]) for t in live) if live else None
    def _off(x: dict) -> bool:
        return any(a <= x["_t"] < b for a, b in spans)
    in_win = [x for x in bt if lo and lo <= x["_t"] <= hi]
    excluded = [x for x in in_win if _off(x)]
    bt_window = [x for x in in_win if not _off(x)]
    bt_only = [x for x in bt_window if id(x) not in used_bt]
    return {"rows": rows, "bt_only": [{"entry_time": x["entry_time"], "direction": x["direction"],
                                       "net_r": x.get("net_r"), "exit_reason": x.get("exit_reason")} for x in bt_only],
            "summary": summarise(rows, bt_only, bt_window, alts),
            "window": {"from": lo.isoformat() if lo else None, "to": hi.isoformat() if hi else None,
                       "excluded_spans": [[a.isoformat(), b.isoformat()] for a, b in spans],
                       "excluded_bt": {"n": len(excluded), "net_r": _s(x.get("net_r", 0) for x in excluded)}}}


def _s(xs: Iterable[float]) -> float:
    return round(sum(xs), 4)


def summarise(rows: List[dict], bt_only: List[dict], bt_window: List[dict],
              alts: Dict[str, List[dict]]) -> Dict[str, Any]:
    m = [r for r in rows if r["class"] == "matched"]
    lo = [r for r in rows if r["class"] == "live_only"]
    un = [r for r in rows if r["class"] == "execution_unattributable"]
    slip = _s(r["entry_slip_r"] for r in m)
    exit_diff = _s(r["live_gross_r"] - r["bt"]["gross_r"] - r["entry_slip_r"] for r in m)
    entry = round(_s(r["live_gross_r"] for r in lo) - _s(x.get("net_r", 0) for x in bt_only), 4)
    comps = {"entry": entry, "exit": exit_diff, "execution": slip}
    out = {
        "live_trades": len(rows), "with_r_basis": len(m) + len(lo),
        "live_gross_r": _s(r["live_gross_r"] for r in rows if "live_gross_r" in r),
        "matched": {"n": len(m), "live_gross_r": _s(r["live_gross_r"] for r in m),
                    "bt_gross_r": _s(r["bt"]["gross_r"] for r in m), "bt_net_r": _s(r["bt"]["net_r"] for r in m),
                    "bt_modelled_cost_r": _s(r["bt"]["cost_r"] for r in m),
                    "entry_slip_r": slip, "exit_path_r": exit_diff},
        "live_only": {"n": len(lo), "live_gross_r": _s(r["live_gross_r"] for r in lo),
                      "median_minutes_into_bar": _median([r["minutes_into_bar"] for r in lo if r["minutes_into_bar"] is not None])},
        "bt_only": {"n": len(bt_only), "net_r": _s(x.get("net_r", 0) for x in bt_only)},
        "execution_unattributable": {"n": len(un), "ids": [r["trade_id"] for r in un]},
        "flagged_close_not_tp_sl": [r["trade_id"] for r in rows if "close_not_tp_sl" in r["flags"]],
        "regime_bt_window": {"n": len(bt_window), "net_r": _s(x.get("net_r", 0) for x in bt_window)},
        "components_r": comps,
        "largest_component": max(comps, key=lambda k: abs(comps[k])) if rows else None,
        "alt_arms": {},
    }
    # gap identity: live gross - backtest window net = entry + exit + execution + modelled cost on matched twins
    out["gap_r"] = round(out["live_gross_r"] - out["regime_bt_window"]["net_r"], 4)
    out["gap_identity_residual_r"] = round(out["gap_r"] - (entry + exit_diff + slip + out["matched"]["bt_modelled_cost_r"]), 4)
    for name in alts:
        delta = {}
        for r in rows:
            a = (r["alt"].get(name) or {}).get("net_r") or 0.0
            b = (r.get("bt") or {}).get("net_r") or 0.0
            if r["class"] != "execution_unattributable":
                delta[r["trade_id"]] = round(a - b, 4)
        out["alt_arms"][name] = {
            "backtest_twin_r_delta_on_live_bars": _s(delta.values()),
            "live_trades_whose_twin_changes_gt_0_1r": [k for k, v in delta.items() if abs(v) > 0.1],
            "on_live_only_trades_alt_fires": [r["trade_id"] for r in lo if r["alt"].get(name)]}
    return out


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else round((xs[n // 2 - 1] + xs[n // 2]) / 2, 2)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", required=True)
    ap.add_argument("--account", default="bybit_2")
    ap.add_argument("--timeframe", help="default: the leg's config/strategies.yaml timeframe")
    ap.add_argument("--bt-trades", type=Path, required=True, help="harness --emit-trades jsonl (the declared arm)")
    ap.add_argument("--alt-trades", action="append", default=[], help="NAME=path.jsonl (repeatable)")
    ap.add_argument("--closed-json", type=Path)
    ap.add_argument("--packages-json", type=Path)
    ap.add_argument("--since", default="2026-06-25T00:00:00+00:00")
    ap.add_argument("--exclude", action="append", default=[],
                    help="FROM/TO (ISO): a span the leg was OFF the account's roster (repeatable)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    tf = a.timeframe
    if not tf:
        import yaml
        tf = yaml.safe_load((Path(__file__).resolve().parents[2] / "config/strategies.yaml").read_text())["strategies"][a.leg]["timeframe"]
    closed = json.loads(a.closed_json.read_text()) if a.closed_json else fetch_closed(a.account)
    live = _strip(r for r in closed if r.get("pattern") == a.leg and r.get("account", a.account) == a.account)
    pk = json.loads(a.packages_json.read_text()) if a.packages_json else fetch_packages(a.leg, a.since)
    pk = _strip(pk)
    alts = {}
    for spec in a.alt_trades:
        name, _, path = spec.partition("=")
        alts[name] = load_bt(Path(path))
    spans = [tuple(x.split("/", 1)) for x in a.exclude]
    res = join(a.leg, live, pk, load_bt(a.bt_trades), tf, alts, exclude=spans)
    res.update({"leg": a.leg, "account": a.account, "timeframe": tf, "bt_trades": str(a.bt_trades),
                "population": f"{a.leg} on {a.account}: every closed trade the /api/bot/trades/closed route returns "
                              f"(pattern == leg), joined to {a.bt_trades} within 1 {tf} bar, same direction",
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    a.out.mkdir(parents=True, exist_ok=True)
    f = a.out / f"{a.leg}.json"
    f.write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(f), **res["summary"]["components_r"], "largest": res["summary"]["largest_component"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

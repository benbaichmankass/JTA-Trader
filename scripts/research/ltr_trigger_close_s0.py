#!/usr/bin/env python3
# wiring: manual-only — LTR-TRIGGER-CLOSE-S0 one-shot Stage-0 replay of live-review triggers over the journal's closed crypto trades; re-run by hand. No timer.
"""Does "close at the first live-review trigger" beat holding, and beat closing at a random time? (reviewer removed)

    python3 scripts/research/ltr_trigger_close_s0.py --trades DIR --packages FILE --out comms/research/ltr_trigger_close_s0/verdict.json

Pre-registration: comms/research/ltr_trigger_close_s0/PREREGISTRATION.md (committed before this ran).
Inputs: the VM journal's trades + order_packages (saved /api/diag/journal pages), the roster in config/accounts.yaml,
candles from data-api.binance.vision (cached under --cache). Thresholds: config/live_trade_review.yaml `due.events`.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
import live_review_counterfactual as cf  # noqa: E402

SEED, DRAWS, N_RANDOM, MIN_N = 20261101, 10_000, 50, 20
TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
TRIGGERS = ["adverse_r_0.5", "adverse_r_0.75", "giveback", "new_peak", "r_milestone", "near_target", "swing", "stall",
            "momentum_flip", "structure_break"]
K = len(TRIGGERS)


def _ts(v: Any) -> Optional[float]:
    return cf._ts(v)


def load_rows(paths: List[str]) -> List[dict]:
    out = []
    for p in paths:
        d = json.load(open(p))
        out += d.get("rows", d) if isinstance(d, dict) else d
    return out


def roster_legs() -> set:
    from src.config.accounts_loader import load_accounts_dict
    acc = load_accounts_dict()
    legs = set()
    for v in acc.values():
        if isinstance(v, dict):
            for s in v.get("strategies") or []:
                legs.add(s if isinstance(s, str) else (s.get("name") or s.get("strategy")))
    return legs


def fetch_klines(symbol: str, tf: str, start: float, end: float, cache: Path) -> List[dict]:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{symbol}_{tf}_{int(start)}_{int(end)}.json"
    if f.exists():
        return json.loads(f.read_text())
    bars: List[dict] = []
    t = int(start * 1000)
    while t < end * 1000:
        url = "https://data-api.binance.vision/api/v3/klines?" + urllib.parse.urlencode(
            {"symbol": symbol, "interval": tf, "startTime": t, "endTime": int(end * 1000), "limit": 1000})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    page = json.loads(r.read())
                break
            except OSError:
                time.sleep(2 ** (attempt + 1))
        else:
            raise RuntimeError(f"klines {symbol} {tf} unavailable")
        if not page:
            break
        bars += [{"time": k[0] / 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                  "close": float(k[4])} for k in page]
        t = page[-1][0] + 1
    f.write_text(json.dumps(bars))
    return bars


def wilder_atr(bars: List[dict], n: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    atr = None
    trs = []
    for i, b in enumerate(bars):
        pc = bars[i - 1]["close"] if i else b["close"]
        tr = max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc))
        if atr is None:
            trs.append(tr)
            if len(trs) == n:
                atr = sum(trs) / n
        else:
            atr = (atr * (n - 1) + tr) / n
        out[i] = atr
    return out


def first_fires(path: List[dict], atrs: List[Optional[float]], *, side: float, entry: float, r_dist: float,
                tp: Optional[float], tf: str, cfg: dict) -> Dict[str, int]:
    """Index (into ``path``) of the first CLOSED bar on which each trigger fires. ``path`` = closed bars after entry."""
    ev = cfg["events"]
    stall_bars = (ev["stall"].get("bars_by_timeframe") or {}).get(tf, ev["stall"].get("default_bars", 8))
    fires: Dict[str, int] = {}
    peak = -math.inf
    ext_against = None
    for k, b in enumerate(path):
        c = b["close"]
        r = side * (c - entry) / r_dist
        peak = max(peak, r)
        atr = atrs[k]

        def hit(name: str) -> None:
            fires.setdefault(name, k)
        if r <= -0.5:
            hit("adverse_r_0.5")
        if r <= -0.75:
            hit("adverse_r_0.75")
        gb = ev["giveback"]
        if peak >= gb["min_peak_r"] and peak - r >= max(gb["min_giveback_r"], gb["giveback_frac_of_peak"] * peak):
            hit("giveback")
        if peak >= ev["new_peak"]["step_r"]:
            hit("new_peak")
        if r >= ev["r_milestone"]["first_r"]:
            hit("r_milestone")
        if tp is not None and side * (tp - c) / r_dist <= ev["near_target"]["max_r_to_target"]:
            hit("near_target")
        if k >= 1 and atrs[k - 1] and abs(c - path[k - 1]["close"]) >= ev["swing"]["atr_multiple"] * atrs[k - 1]:
            hit("swing")
        if k + 1 >= stall_bars and peak < ev["stall"]["max_peak_r"]:
            hit("stall")
        mf = ev["momentum_flip"]
        if k + 1 >= mf["bars"] and atr:
            w = path[k + 1 - mf["bars"]:k + 1]
            prev = path[k - mf["bars"]]["close"] if k - mf["bars"] >= 0 else entry
            against = all(side * (w[j]["close"] - (w[j - 1]["close"] if j else prev)) < 0 for j in range(len(w)))
            if against and side * (prev - w[-1]["close"]) >= mf["min_atr"] * atr:
                hit("momentum_flip")
        sb = ev["structure_break"]
        if ext_against is not None and k >= sb["min_bars"] and atr and side * (ext_against - c) > sb["buffer_atr"] * atr:
            hit("structure_break")
        ext_against = c if ext_against is None else (min(ext_against, c) if side > 0 else max(ext_against, c))
    return fires


def boot(xs: List[float], rng: random.Random, alpha: float) -> Optional[List[float]]:
    if len(xs) < 2:
        return None
    n = len(xs)
    ms = sorted(statistics.fmean(rng.choice(xs) for _ in range(n)) for _ in range(DRAWS))
    lo, hi = ms[int(alpha / 2 * DRAWS)], ms[min(DRAWS - 1, int((1 - alpha / 2) * DRAWS))]
    return [round(lo, 4), round(hi, 4)]


def summ(xs: List[float]) -> Dict[str, Any]:
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 4) if xs else None,
            "sum": round(sum(xs), 3) if xs else None}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", required=True, help="dir of saved /api/diag/journal?table=trades pages (tr_*.json)")
    ap.add_argument("--packages", required=True, help="saved order_packages rows (json list)")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", default=str(REPO / "comms/research/ltr_trigger_close_s0/verdict.json"))
    ap.add_argument("--rows-out", default=None)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load((REPO / "config/live_trade_review.yaml").read_text())["due"]
    trades = load_rows(sorted(glob.glob(str(Path(a.trades) / "tr_*.json"))))
    pk = {p["order_package_id"]: p for p in load_rows([a.packages])}
    legs = roster_legs()
    pool = [t for t in trades if str(t.get("status") or "").lower() == "closed" and not t.get("is_backtest")
            and t.get("strategy_name") in legs and str(t.get("symbol") or "").endswith("USDT")
            and t.get("order_package_id") in pk]
    by_pkg: Dict[str, dict] = {}
    for t in sorted(pool, key=lambda t: int(t["id"])):
        by_pkg.setdefault(t["order_package_id"], t)
    excluded: Counter = Counter()
    rows: List[dict] = []
    # group by (symbol, tf) to fetch candles once per range
    groups: Dict[tuple, List[tuple]] = defaultdict(list)
    for pid, t in by_pkg.items():
        p = pk[pid]
        tf = cf._meta(p).get("timeframe")
        if tf not in TF_S:
            excluded["timeframe_unknown"] += 1
            continue
        groups[(t["symbol"], tf)].append((pid, t, p))
    for (sym, tf), items in sorted(groups.items()):
        t0 = min(_ts(t.get("timestamp")) for _, t, _ in items) - 40 * TF_S[tf]
        t1 = max(_ts(t.get("closed_at")) or 0 for _, t, _ in items) + 2 * TF_S[tf]
        bars = fetch_klines(sym, tf, t0, t1, Path(a.cache))
        atrs_all = wilder_atr(bars)
        times = [b["time"] for b in bars]
        for pid, t, p in items:
            side = 1.0 if str(t.get("direction") or p.get("direction")).lower() in ("long", "buy") else -1.0
            sl0 = cf.initial_stop(p)
            entry = cf._num(t.get("entry_price"))
            te, tc = _ts(t.get("timestamp")), _ts(t.get("closed_at"))
            if sl0 is None or entry is None or not te or not tc or tc <= te or abs(entry - sl0) <= 0:
                excluded["geometry_or_times_missing"] += 1
                continue
            lab = cf.net_r_for_trade(dict(t, stop_loss=sl0))
            if lab is None:
                excluded["realised_net_r_uncomputable"] += 1
                continue
            r_dist = abs(entry - sl0)
            # closed bars after entry: bar opens >= entry time and closes (open + tf) <= realised close
            idx = [i for i, ts in enumerate(times) if ts >= te and ts + TF_S[tf] <= tc]
            # an exit at bar (i+1).open must be strictly before the realised close
            idx = [i for i in idx if i + 1 < len(bars) and bars[i + 1]["time"] < tc]
            if not idx:
                excluded["no_closed_bar_before_close"] += 1
                continue
            path = [bars[i] for i in idx]
            atrs = [atrs_all[i] for i in idx]
            fee_r, fund_r, slip_r, stack = cf.cost_legs(t, sym, entry, r_dist, lab["risk_usd"])

            def close_net(k: int) -> float:
                b = bars[idx[k] + 1]
                gross = side * (b["open"] - entry) / r_dist
                return cf.net_of_costs(gross, fee_r, fund_r, slip_r, (b["time"] - te) / (tc - te))
            hold = lab["net_R"]
            fires = first_fires(path, atrs, side=side, entry=entry, r_dist=r_dist, tp=cf._num(p.get("tp")), tf=tf,
                                cfg=cfg)
            rng = random.Random(f"{SEED}:{pid}")
            rand = statistics.fmean(close_net(rng.randrange(len(path))) for _ in range(N_RANDOM))
            rows.append({"package": pid, "leg": t.get("strategy_name"), "symbol": sym, "tf": tf,
                         "account": t.get("account_id"), "month": datetime.fromtimestamp(te, timezone.utc).strftime("%Y-%m"),
                         "hold": round(hold, 6), "random_close": round(rand, 6), "n_bars": len(path),
                         "cost_stack": stack, "fires": {k: v for k, v in fires.items()},
                         "close_at": {k: round(close_net(v), 6) for k, v in fires.items()}})
    rng = random.Random(SEED)
    alpha = 0.05 / K
    out_t: Dict[str, Any] = {}
    for T in TRIGGERS:
        s = [r for r in rows if T in r["close_at"]]
        dT = [r["close_at"][T] - r["hold"] for r in s]
        dR = [r["random_close"] - r["hold"] for r in s]
        edge = [x - y for x, y in zip(dT, dR)]
        by_m: Dict[str, List[float]] = defaultdict(list)
        by_leg: Dict[str, List[float]] = defaultdict(list)
        by_acct: Dict[str, List[float]] = defaultdict(list)
        for r, d in zip(s, dT):
            by_m[r["month"]].append(d)
            by_leg[r["leg"]].append(d)
            by_acct[r["account"]].append(d)
        row: Dict[str, Any] = {"n_packages": len(s), "share_fired_in_time": round(len(s) / len(rows), 3) if rows else None,
                               "mean_hold": summ([r["hold"] for r in s])["mean"],
                               "delta_close_vs_hold": summ(dT), "delta_random_vs_hold": summ(dR), "edge_vs_random": summ(edge),
                               "ci95_delta": boot(dT, rng, 0.05), "ci_bonf_delta": boot(dT, rng, alpha),
                               "ci95_edge": boot(edge, rng, 0.05), "ci_bonf_edge": boot(edge, rng, alpha),
                               "hit_rate": round(sum(1 for d in dT if d > 0) / len(dT), 3) if dT else None,
                               "by_month": {k: summ(v) for k, v in sorted(by_m.items())},
                               "by_leg": {k: summ(v) for k, v in sorted(by_leg.items())},
                               "by_account": {k: summ(v) for k, v in sorted(by_acct.items())}}
        big = [m for m, v in by_m.items() if len(v) >= 5]
        pos = [m for m in big if statistics.fmean(by_m[m]) > 0]
        best_m = max(by_m, key=lambda m: sum(by_m[m])) if by_m else None
        rest_m = [d for m, v in by_m.items() if m != best_m for d in v]
        best_l = max(by_leg, key=lambda k: sum(by_leg[k])) if by_leg else None
        rest_l = [d for k, v in by_leg.items() if k != best_l for d in v]
        p = {"P1": len(s) >= MIN_N,
             "P2": bool(dT) and statistics.fmean(dT) > 0 and bool(row["ci_bonf_delta"]) and row["ci_bonf_delta"][0] > 0,
             "P3": bool(edge) and statistics.fmean(edge) > 0 and bool(row["ci_bonf_edge"]) and row["ci_bonf_edge"][0] > 0,
             "P4": bool(big) and len(pos) * 2 > len(big) and bool(rest_m) and statistics.fmean(rest_m) > 0,
             "P5": bool(rest_l) and statistics.fmean(rest_l) > 0}
        row["clauses"] = p
        row["regime_detail"] = {"months_ge5": len(big), "months_positive": len(pos), "best_month": best_m,
                                "mean_without_best_month": round(statistics.fmean(rest_m), 4) if rest_m else None,
                                "best_leg": best_l, "mean_without_best_leg": round(statistics.fmean(rest_l), 4) if rest_l else None}
        if all(p.values()):
            v = "PASS"
        elif dT and (statistics.fmean(dT) <= 0 or (row["ci_bonf_delta"] and row["ci_bonf_delta"][1] <= 0)):
            v = "FAIL"
        else:
            v = "INDETERMINATE"
        row["verdict"] = v
        out_t[T] = row
    allr = {"n_packages": len(rows), "mean_hold": summ([r["hold"] for r in rows]),
            "random_close_vs_hold": summ([r["random_close"] - r["hold"] for r in rows]),
            "ci95_random_vs_hold": boot([r["random_close"] - r["hold"] for r in rows], rng, 0.05)}
    out = {"schema": "ltr_trigger_close_s0/v1", "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "preregistration": "comms/research/ltr_trigger_close_s0/PREREGISTRATION.md",
           "population": {"trades_pool": len(pool), "packages": len(by_pkg), "packages_priced": len(rows),
                          "excluded": dict(excluded),
                          "first_entry": min((r["month"] for r in rows), default=None),
                          "accounts": dict(Counter(r["account"] for r in rows)),
                          "by_tf": dict(Counter(r["tf"] for r in rows))},
           "unconditional": allr, "triggers": out_t}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    if a.rows_out:
        with open(a.rows_out, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    print(json.dumps(out["population"]), json.dumps(allr))
    for T, r in out_t.items():
        print(f"{T:16s} n={r['n_packages']:4d} dT={r['delta_close_vs_hold']['mean']} dR={r['delta_random_vs_hold']['mean']} "
              f"edge={r['edge_vs_random']['mean']} ciB_dT={r['ci_bonf_delta']} ciB_edge={r['ci_bonf_edge']} "
              f"{''.join(k for k, v in r['clauses'].items() if v)} -> {r['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

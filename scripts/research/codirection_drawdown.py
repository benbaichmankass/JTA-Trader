#!/usr/bin/env python3
# wiring: pipeline PI-20261118-PREP1118-0002 (perf review 2026-11-18 G4) -> a research/queue unit; `export` runs in a session
# with read access to the diag journal and commits trade-level ratios; `run` is the unit's runner command.
"""Cross-book same-direction concentration vs the next 24 h of book return (perf review 2026-11-18, call G4).

  export  pages GET /api/diag/journal?table=trades (read-only) and writes ONE ROW PER CLOSED, NON-BACKTEST TRADE:
          account (config name), account_class, leg, symbol, direction (+1 long / -1 short), opened, closed and ret_pct
          (the journal's pnl_percent: return on the position's notional, a ratio). No sizes, dollars or ids beyond the row id.
  run     on a DAILY grid (00:00 UTC; daily, not hourly, so consecutive 24 h outcomes do not overlap) computes
              C(t) = max(#open long, #open short) across the population's open positions at t   (same-direction count)
              Y(t) = sum of ret_pct of trades CLOSING in (t, t + 24 h]                            (equal-weight book return)
          and the Spearman rank correlation rho(C, Y) with a WEEK-block bootstrap 95% CI. Also reported: rho(C, |Y|)
          (does concentration predict bigger moves either way) and rho on the worst-decile Y indicator.

Units: ret_pct is return on notional per trade, summed equal-weight, NOT R: the journal's stop_loss is the CURRENT
(possibly trailed) stop, so an R from it would be biased. Said in every result.

    python3 scripts/research/codirection_drawdown.py --self-test
    python3 scripts/research/codirection_drawdown.py export --since 2026-09-01 --out comms/research/codirection/<date>.jsonl
    python3 scripts/research/codirection_drawdown.py run --trades <jsonl> --population all|real_money|demo --unit ID --rule-id R --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ENV_BASE = os.environ.get("DIAG_BASE_URL") or ""
BASE = _ENV_BASE if _ENV_BASE.startswith("https://") else "https://ict-bot.duckdns.org"
N_MIN_DAYS = 45
BOOT = 4000
SEED = 20261119


def _ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def trades_from_rows(rows: List[Dict[str, Any]], since: str) -> List[Dict[str, Any]]:
    lo = _ts(since + "T00:00:00+00:00")
    out = []
    for r in rows:
        if r.get("status") != "closed" or r.get("is_backtest"):
            continue
        o, c, ret = _ts(r.get("timestamp") or r.get("created_at")), _ts(r.get("closed_at")), r.get("pnl_percent")
        if not (o and c and isinstance(ret, (int, float))) or o < lo or c < o:
            continue
        out.append({"trade": str(r.get("id")), "account": r.get("account_id"), "account_class": r.get("account_class"),
                    "leg": r.get("strategy_name"), "symbol": r.get("symbol"),
                    "direction": 1 if str(r.get("direction") or "").lower() in ("long", "buy") else -1,
                    "opened": o.isoformat(), "closed": c.isoformat(), "ret_pct": round(float(ret), 6)})
    return out


def export(since: str, out: Path, page: int = 1000) -> Dict[str, Any]:
    rows, off = [], 0
    while True:
        req = urllib.request.Request(f"{BASE}/api/diag/journal?table=trades&limit={page}&offset={off}")
        if os.environ.get("DIAG_READ_TOKEN"):
            req.add_header("Authorization", f"Bearer {os.environ['DIAG_READ_TOKEN']}")
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - fixed host
            batch = json.load(r)
        batch = batch if isinstance(batch, list) else batch.get("rows") or []
        rows += batch
        if len(batch) < page or min((x.get("created_at") or "9") for x in batch) < since:
            break
        off += page
    tr = trades_from_rows(rows, since)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in tr))
    return {"journal_rows_read": len(rows), "trades": len(tr), "out": str(out)}


def daily_series(trades: List[Dict[str, Any]]) -> List[Tuple[datetime, int, float]]:
    """[(t, C, Y)] at each 00:00 UTC from the first open to the last close minus 24 h."""
    if not trades:
        return []
    ops = [(_ts(t["opened"]), _ts(t["closed"]), t["direction"], t["ret_pct"]) for t in trades]
    t = min(o for o, _, _, _ in ops).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end = max(c for _, c, _, _ in ops) - timedelta(days=1)
    out = []
    while t <= end:
        longs = sum(1 for o, c, d, _ in ops if o <= t < c and d > 0)
        shorts = sum(1 for o, c, d, _ in ops if o <= t < c and d < 0)
        y = sum(r for _, c, _, r in ops if t < c <= t + timedelta(days=1))
        out.append((t, max(longs, shorts), y))
        t += timedelta(days=1)
    return out


def _ranks(xs: List[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0
        i = j + 1
    return r


def spearman(a: List[float], b: List[float]) -> Optional[float]:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va > 0 and vb > 0 else None


def week_block_ci(series: List[Tuple[datetime, int, float]], f, draws: int = BOOT, seed: int = SEED) -> Dict[str, Any]:
    weeks: Dict[str, List[Tuple[int, float]]] = {}
    for t, c, y in series:
        weeks.setdefault(t.strftime("%G-%V"), []).append((c, y))
    blocks = list(weeks.values())
    rng = random.Random(seed)
    est = f([c for _, c, _ in series], [y for _, _, y in series])
    vals = []
    for _ in range(draws):
        pts = [p for _ in blocks for p in blocks[rng.randrange(len(blocks))]]
        v = f([p[0] for p in pts], [p[1] for p in pts])
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals or est is None:
        return {"rho": est, "lo": None, "hi": None, "weeks": len(blocks)}
    return {"rho": round(est, 4), "lo": round(vals[int(0.025 * len(vals))], 4), "hi": round(vals[int(0.975 * len(vals)) - 1], 4),
            "weeks": len(blocks)}


def grade(series: List[Tuple[datetime, int, float]]) -> Tuple[str, str, Dict[str, Any]]:
    """Registered rule (RQ unit for G4): PASS (concentration predicts worse next-24 h book return) iff rho(C, Y) < 0
    with the week-block 95% CI upper bound < 0 on >= N_MIN_DAYS daily points; FAIL iff the CI lower bound > -0.10
    (no material negative association); INDETERMINATE otherwise or under N_MIN_DAYS."""
    main = week_block_ci(series, spearman)
    absy = week_block_ci([(t, c, abs(y)) for t, c, y in series], spearman)
    ys = sorted(y for _, _, y in series)
    q10 = ys[int(0.1 * len(ys))] if ys else 0.0
    tail = week_block_ci([(t, c, 1.0 if y <= q10 else 0.0) for t, c, y in series], spearman)
    m = {"rho_c_y": main, "rho_c_abs_y": absy, "rho_c_worst_decile": tail, "days": len(series)}
    if len(series) < N_MIN_DAYS or main["hi"] is None:
        return "indeterminate", f"{len(series)} daily points < {N_MIN_DAYS} or no CI", m
    if main["hi"] < 0:
        return "pass", f"concentration predicts worse next-24 h book return: rho {main['rho']:+.3f}, CI [{main['lo']:+.3f}, {main['hi']:+.3f}]", m
    if main["lo"] > -0.10:
        return "fail", f"no material negative association: rho {main['rho']:+.3f}, CI [{main['lo']:+.3f}, {main['hi']:+.3f}]", m
    return "indeterminate", f"CI [{main['lo']:+.3f}, {main['hi']:+.3f}] straddles the bars", m


def select(trades: List[Dict[str, Any]], population: str) -> List[Dict[str, Any]]:
    if population == "real_money":
        return [t for t in trades if t.get("account_class") == "real_money"]
    if population == "demo":
        return [t for t in trades if t.get("account_class") != "real_money"]
    return trades


def self_test() -> int:
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    rows = [{"id": 1, "status": "closed", "is_backtest": False, "timestamp": "2026-10-01T10:00:00Z", "closed_at": "2026-10-02T10:00:00Z",
             "pnl_percent": -1.5, "direction": "short", "account_id": "bybit_1", "account_class": "demo", "strategy_name": "x",
             "symbol": "BTCUSDT", "pnl": -99.0, "position_size": 3.0}, {"id": 2, "status": "open"}]
    tr = trades_from_rows(rows, "2026-09-01")
    check("closed live trade exported, open dropped; no dollar or size field", len(tr) == 1 and "pnl" not in tr[0] and "position_size" not in tr[0])
    check("short direction is -1", tr[0]["direction"] == -1)
    check("spearman of a monotone pair is 1 and of a reversed pair -1",
          abs(spearman([1, 2, 3, 4], [2, 4, 6, 8]) - 1) < 1e-9 and abs(spearman([1, 2, 3, 4], [8, 6, 4, 2]) + 1) < 1e-9)
    # planted: days with many same-direction shorts are followed by a loss
    rng = random.Random(3)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = []
    for d in range(120):
        k = rng.randrange(1, 8)
        day = t0 + timedelta(days=d)
        for i in range(k):
            trades.append({"trade": f"{d}-{i}", "direction": -1, "opened": (day - timedelta(hours=2)).isoformat(),
                           "closed": (day + timedelta(hours=12)).isoformat(), "ret_pct": -0.3 * k + rng.gauss(0, 0.3)})
    s = daily_series(trades)
    v, _, m = grade(s)
    check("planted concentration -> loss association reads PASS", v == "pass" and m["rho_c_y"]["rho"] < 0)
    null = [{**t, "ret_pct": rng.gauss(0, 1.0)} for t in trades]
    check("a null (returns independent of concentration) does not PASS", grade(daily_series(null))[0] != "pass")
    check("too few days -> indeterminate", grade(s[:20])[0] == "indeterminate")
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("export")
    e.add_argument("--since", required=True)
    e.add_argument("--out", required=True)
    r = sub.add_parser("run")
    for k in ("--trades", "--unit", "--rule-id", "--out"):
        r.add_argument(k, required=True)
    r.add_argument("--population", choices=["all", "real_money", "demo"], default="all")
    r.add_argument("--registered-at", default="2026-11-19")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd == "export":
        print(json.dumps(export(a.since, Path(a.out))))
        return 0
    if a.cmd != "run":
        ap.error("export | run | --self-test")
    trades = select([json.loads(x) for x in Path(a.trades).read_text().splitlines() if x.strip()], a.population)
    series = daily_series(trades)
    v, why, m = grade(series)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    row = {"schema_version": 1, "schema": "codirection_drawdown/1", "research_unit": a.unit, "read_state": "measured", "verdict": v,
           "n": len(series), "note": why, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "population": f"{a.population} closed trades in {a.trades}; daily 00:00 UTC grid; Y in summed per-trade return on "
                         f"notional (pnl_percent), NOT R",
           "measurement": {**m, "trades": len(trades), "population_filter": a.population}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"CODIRECTION {v}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

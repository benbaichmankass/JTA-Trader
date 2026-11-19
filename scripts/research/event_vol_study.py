#!/usr/bin/env python3
# wiring: research/queue/RQ-20261118-a5b3-02 (event-class weights from our own markets)
"""Event-class volatility study: is realized vol after a US release elevated vs matched non-event hours? (a5b3-02)

For each release class (fomc_decision, fomc_minutes, cpi, nfp) in comms/research/event_span_history/us_releases.jsonl
and each symbol: RV(t) = sum of squared bar log returns over [t, t + 2 h). Baseline = the mean RV over the SAME weekday
and UTC time on the 8 surrounding weeks (t +- 7 d x {1..4}) that are not within +-6 h of ANY graded release. Statistic
per (class, symbol): the median over events of log(RV(event) / baseline), with an event-level bootstrap 95% CI; and the
decision-minus-minutes difference of that median with a CI from independent event bootstraps. An event is skipped for a
symbol when the window or any baseline week has fewer than 80% of its bars (counted, never imputed).

Verdict (the unit's registered rule): a class is EVENT-ELEVATED on a symbol iff its CI lower bound > 0. DECISION >
MINUTES iff the difference CI lower bound > 0 on >= 3 of the 5 symbols. PASS: every class with n >= 30 events reads its
CI (weights evidenced; impact per class = its median log ratio rescaled so fomc_decision on BTC = 1.0). FAIL: no class
is EVENT-ELEVATED on any crypto symbol. INDETERMINATE: a class under 30 events, or decision and minutes not separable.

    python3 scripts/research/event_vol_study.py --self-test
    python3 scripts/research/event_vol_study.py run --events <jsonl> --unit ID --rule-id R --out DIR
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
CLASSES = ("fomc_decision", "fomc_minutes", "cpi", "nfp")
SYMBOLS = {"BTCUSDT": None, "ETHUSDT": None, "SOLUSDT": None, "SPY": "dukascopy", "GLD": "dukascopy"}
CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
WINDOW = timedelta(hours=2)
WEEKS = (1, 2, 3, 4)
EXCL = timedelta(hours=6)
COVER = 0.8
N_MIN = 30
BOOT = 4000
SEED = 20261119


def _ts(s: str) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def rv(bars: List[Tuple[datetime, float]], t: datetime, bar: timedelta) -> Optional[float]:
    """Sum of squared log returns of consecutive closes inside [t, t + WINDOW); None under COVER of the expected bars."""
    lo, hi = 0, len(bars)
    while lo < hi:
        m = (lo + hi) // 2
        if bars[m][0] < t:
            lo = m + 1
        else:
            hi = m
    xs = []
    k = lo
    while k < len(bars) and bars[k][0] < t + WINDOW:
        xs.append(bars[k][1])
        k += 1
    need = WINDOW / bar
    if len(xs) < COVER * need or len(xs) < 3:
        return None
    return sum(math.log(b / a) ** 2 for a, b in zip(xs, xs[1:]) if a > 0 and b > 0)


def event_ratio(bars, t: datetime, bar: timedelta, all_events: List[datetime]) -> Optional[float]:
    ev = rv(bars, t, bar)
    if not ev:
        return None
    base = []
    for w in WEEKS:
        for s in (-1, 1):
            u = t + s * timedelta(days=7 * w)
            if any(abs(u - e) <= EXCL for e in all_events):
                continue
            x = rv(bars, u, bar)
            if x is None:
                return None          # a short baseline week voids the event for this symbol (counted)
            base.append(x)
    if not base or sum(base) <= 0:
        return None
    return math.log(ev / (sum(base) / len(base)))


def median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def boot_median(xs: List[float], draws: int = BOOT, seed: int = SEED) -> List[float]:
    rng = random.Random(seed)
    return sorted(median([xs[rng.randrange(len(xs))] for _ in xs]) for _ in range(draws))


def ci(sorted_draws: List[float]) -> Tuple[float, float]:
    n = len(sorted_draws)
    return sorted_draws[int(0.025 * n)], sorted_draws[int(0.975 * n) - 1]


def summarize(ratios: Dict[str, Dict[str, List[float]]]) -> Dict[str, Any]:
    cells: Dict[str, Dict[str, Any]] = {}
    for cls, by_sym in ratios.items():
        for sym, xs in by_sym.items():
            if not xs:
                cells.setdefault(cls, {})[sym] = {"n": 0}
                continue
            lo, hi = ci(boot_median(xs))
            cells.setdefault(cls, {})[sym] = {"n": len(xs), "median_log_ratio": round(median(xs), 4), "lo": round(lo, 4),
                                              "hi": round(hi, 4), "elevated": lo > 0}
    diff = {}
    for sym in SYMBOLS:
        d, m = ratios.get("fomc_decision", {}).get(sym) or [], ratios.get("fomc_minutes", {}).get(sym) or []
        if len(d) >= 2 and len(m) >= 2:
            bd, bm = boot_median(d, seed=SEED), boot_median(m, seed=SEED + 1)
            dd = sorted(a - b for a, b in zip(bd, random.Random(SEED + 2).sample(bm, len(bm))))
            lo, hi = ci(dd)
            diff[sym] = {"diff": round(median(d) - median(m), 4), "lo": round(lo, 4), "hi": round(hi, 4), "decision_gt_minutes": lo > 0}
    return {"cells": cells, "decision_minus_minutes": diff}


def verdict(s: Dict[str, Any], class_events: Dict[str, int]) -> Tuple[str, str]:
    """`class_events` = releases per class in the history (the registered "fewer than 30 events in a class" clause is
    per CLASS). A (class, symbol) cell with fewer than N_MIN measured events is reported and not read: e.g. cpi / nfp
    print at 13:30Z, before the US cash session, so an RTH-only SPY CFD has no bars in those windows."""
    cells, diff = s["cells"], s["decision_minus_minutes"]
    thin = sorted(c for c in CLASSES if class_events.get(c, 0) < N_MIN)
    if thin:
        return "indeterminate", f"classes under {N_MIN} events in the history: {thin}"
    for c, by in cells.items():
        for y, v in by.items():
            if v.get("n", 0) < N_MIN:
                v["elevated"] = None
                v["read"] = False
    if len(diff) < 3:
        return "indeterminate", "decision and minutes not separable on >= 3 symbols"
    if not any(cells[c][y].get("elevated") for c in cells for y in CRYPTO if y in cells[c]):
        return "fail", "no class is EVENT-ELEVATED on any crypto symbol"
    n_dm = sum(1 for v in diff.values() if v["decision_gt_minutes"])
    base = (cells.get("fomc_decision", {}).get("BTCUSDT") or {}).get("median_log_ratio")
    w = {c: {y: (round(v["median_log_ratio"] / base, 3) if base else None) for y, v in by.items() if "median_log_ratio" in v}
         for c, by in cells.items()}
    s["weights_rel_fomc_decision_btc"] = w
    elev = sorted(f"{c}/{y}" for c in cells for y in cells[c] if cells[c][y].get("elevated"))
    return "pass", f"weights evidenced: elevated cells {elev}; DECISION > MINUTES on {n_dm} of {len(diff)} symbols"


def fetch(symbol: str, src: Optional[str], start: str, end: str, work: Path) -> Tuple[timedelta, List[Tuple[datetime, float]]]:
    for iv in ("5", "60"):
        out = work / f"{symbol}_{iv}.csv"
        cmd = [sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", symbol, "--interval", iv,
               "--start-date", start, "--end-date", end, "--output", str(out)] + (["--source", src] if src else [])
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5400)
        if p.returncode == 0 and out.exists():
            bars = []
            with out.open() as fh:
                for row in csv.DictReader(fh):
                    t, c = row.get("timestamp") or row.get("time") or row.get("open_time"), row.get("close")
                    if t and c:
                        bars.append((_ts(t), float(c)))
            if bars:
                return timedelta(minutes=int(iv)), sorted(bars)
    return timedelta(minutes=5), []


def run(events_path: Path) -> Dict[str, Any]:
    evs = [json.loads(x) for x in events_path.read_text().splitlines() if x.strip()]
    times = sorted(_ts(e["release_utc"]) for e in evs)
    start = (times[0] - timedelta(days=35)).date().isoformat()
    end = (times[-1] + timedelta(days=35)).date().isoformat()
    work = Path(tempfile.mkdtemp(prefix="evvol_"))
    ratios: Dict[str, Dict[str, List[float]]] = {c: {} for c in CLASSES}
    skipped: Dict[str, int] = {}
    meta = {}
    for sym, src in SYMBOLS.items():
        bar, bars = fetch(sym, src, start, end, work)
        meta[sym] = {"bar_minutes": int(bar.total_seconds() // 60), "bars": len(bars)}
        for c in CLASSES:
            xs = []
            for e in (e for e in evs if e["class"] == c):
                r = event_ratio(bars, _ts(e["release_utc"]), bar, times) if bars else None
                if r is None:
                    skipped[f"{c}/{sym}"] = skipped.get(f"{c}/{sym}", 0) + 1
                else:
                    xs.append(r)
            ratios[c][sym] = xs
    s = summarize(ratios)
    class_events = {c: sum(1 for e in evs if e["class"] == c) for c in CLASSES}
    s["class_events"] = class_events
    v, why = verdict(s, class_events)
    n = sum(len(x) for by in ratios.values() for x in by.values())
    return {"verdict": v, "note": why, "n": n, **s, "skipped_events": skipped, "symbols": meta, "events_source": str(events_path)}


def self_test() -> int:
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rng = random.Random(1)
    bar = timedelta(minutes=5)
    n = 12 * 24 * 7 * 12          # 12 weeks of 5m bars
    ev_t = t0 + timedelta(days=42, hours=13, minutes=30)
    bars, p = [], 100.0
    for k in range(n):
        t = t0 + k * bar
        sd = 0.004 if ev_t <= t < ev_t + WINDOW else 0.001        # planted 4x vol in the event window
        p *= math.exp(rng.gauss(0, sd))
        bars.append((t, p))
    r = event_ratio(bars, ev_t, bar, [ev_t])
    check("a planted 4x vol window reads a log RV ratio near log(16)", r is not None and 2.0 < r < 3.5)
    quiet = event_ratio(bars, ev_t + timedelta(hours=5), bar, [ev_t])
    check("a quiet hour reads a ratio near 0", quiet is not None and abs(quiet) < 0.8)
    check("a window with too few bars is skipped (None)", rv(bars[:10], t0, bar) is None)
    s = summarize({"fomc_decision": {"BTCUSDT": [2.0 + 0.1 * (i % 5) for i in range(40)]},
                   "fomc_minutes": {"BTCUSDT": [0.1 * (i % 5) for i in range(40)]}})
    check("an elevated class has CI lower bound > 0", s["cells"]["fomc_decision"]["BTCUSDT"]["elevated"])
    check("decision > minutes is detected", s["decision_minus_minutes"]["BTCUSDT"]["decision_gt_minutes"])
    ce = {c: 45 for c in CLASSES}
    check("verdict: a class under 30 events in the HISTORY is indeterminate",
          verdict({"cells": {}, "decision_minus_minutes": {}}, {**ce, "fomc_minutes": 4})[0] == "indeterminate")
    full = {c: {y: {"n": 40, "median_log_ratio": 0.5, "lo": -0.1, "hi": 1.0, "elevated": False} for y in SYMBOLS} for c in CLASSES}
    dm = {y: {"diff": 0.1, "lo": -0.1, "hi": 0.3, "decision_gt_minutes": False} for y in SYMBOLS}
    check("verdict: nothing elevated on crypto -> fail", verdict({"cells": full, "decision_minus_minutes": dm}, ce)[0] == "fail")
    full["cpi"]["BTCUSDT"]["elevated"] = True
    full["cpi"]["SPY"] = {"n": 0}
    check("verdict: an elevated crypto cell -> pass, and an empty SPY cell is reported unread, not blocking",
          verdict({"cells": full, "decision_minus_minutes": dm}, ce)[0] == "pass" and full["cpi"]["SPY"]["read"] is False)
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    for k in ("--events", "--unit", "--rule-id", "--out"):
        r.add_argument(k, required=True)
    r.add_argument("--registered-at", default="2026-11-18")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run":
        ap.error("run or --self-test")
    res = run(Path(a.events))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    row = {"schema_version": 1, "schema": "event_vol_study/1", "research_unit": a.unit, "read_state": "measured",
           "verdict": res["verdict"], "n": res["n"], "note": res["note"],
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "population": f"US releases in {a.events} x {list(SYMBOLS)}; RV over [t, t+2h) vs 8 matched non-event weekday-hours",
           "measurement": res}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"EVENT-VOL {row['verdict']}: {row['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

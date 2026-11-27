#!/usr/bin/env python3
# wiring: research/queue/RQ-20261127-cb1a-01.yaml run.command (trainer: reads the synced trade_journal.db)
"""ml_entry CLOSE-AT-BAR-1 vs HOLD on the LIVE + PAPER book (Manager 26a item (3), 2026-11-27 18:17Z).

Three ml_entry real-money longs (SOL, ADA, XRP) were reviewed CLOSE about one bar after entry on 2026-11-27, and the
per-leg priced tables (scripts/research/live_review_outcomes.py, Stage-0 history) show close dominating hold on both mean
and worst R right after entry. That is a BACKTEST read. This asks the same question of the trades ml_entry actually took:
on every closed ml_entry / ml_entry_v2 package, would closing at the end of the first bar after entry have beaten holding
to the bracket?

POPULATION: order packages (one decision each; the same package on several accounts shares one price path) with a closed,
non-backtest trade row whose strategy_name is ml_entry or ml_entry_v2, any account class. Per package the representative
trade row is the real-money one if any, else the earliest.

PER PACKAGE (price R on the trade's own signal-time stop, so both arms share the denominator and the entry):
  R_hold = sign x (exit_price - entry_price) / |entry_price - stop_loss|        (what the trade realised)
  R_bar1 = position_path_history.open_r on the package's earliest path row with bars_held >= BAR1_BARS_HELD (2).
           bars_held is the length of the since-entry candle window (src/runtime/trail_decay.since_entry_peak `bars`,
           written by position_telemetry), which counts the entry bar itself, so >= 2 is the first row after one full
           bar beyond the entry bar. A package whose path never reached 2 bars (it closed inside the entry bar or the next)
           has R_bar1 = R_hold: delta 0.
  delta  = R_bar1 - R_hold. Each arm pays exactly one exit and the same entry, so the cost stack cancels to first order
           (declared: a TP exit can be a maker fill where a bar-1 close is taker; the difference is <= ~0.01 R at these stops).
A package with no bar-1 path row although its trade lasted past bar 1 is EXCLUDED and counted (coverage).

VERDICT (verdict.json; the unit registers this rule): see decide(). Read-only (sqlite mode=ro). Writes only --out.
No config, model, registry or order path. Tier-1 research tooling.

    python3 scripts/research/ml_entry_close_bar1.py --db data/trade_journal.db --unit RQ-... --out DIR
    python3 scripts/research/ml_entry_close_bar1.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STRATEGIES = ("ml_entry", "ml_entry_v2")
MIN_N = 40               # packages
DELTA = 0.10             # R per package
T_BAR = 2.0              # day-clustered t
MIN_COVERAGE = 0.70      # share of eligible packages with a bar-1 path row (or closed before bar 1)
BAR1_BARS_HELD = 2       # bars_held counts the entry bar (trail_decay window length): 2 = one full bar after it


def _sign(direction: str | None) -> float | None:
    d = str(direction or "").lower()
    return 1.0 if d in ("long", "buy") else (-1.0 if d in ("short", "sell") else None)


def collect(db: Path) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"trades", "position_path_history"}
        if not need <= have:
            return {"read_state": "no_data", "why": f"tables missing: {sorted(need - have)}"}
        q = ",".join("?" * len(STRATEGIES))
        rows = conn.execute(
            "SELECT id, order_package_id, strategy_name, account_class, direction, entry_price, exit_price, stop_loss, "
            "timestamp, exit_reason FROM trades WHERE status = 'closed' AND COALESCE(is_backtest, 0) = 0 "
            f"AND strategy_name IN ({q}) AND order_package_id IS NOT NULL ORDER BY timestamp", STRATEGIES).fetchall()
        rep: dict = {}
        for r in rows:
            k = r["order_package_id"]
            cur = rep.get(k)
            if cur is None or (r["account_class"] == "real_money" and cur["account_class"] != "real_money"):
                rep[k] = dict(r)
        pkgs, excluded = [], {"no_bar1_path_row": 0, "bad_prices": 0}
        for k, t in rep.items():
            s = _sign(t["direction"])
            try:
                e, x, sl = float(t["entry_price"]), float(t["exit_price"]), float(t["stop_loss"])
            except (TypeError, ValueError):
                excluded["bad_prices"] += 1
                continue
            risk = abs(e - sl)
            if s is None or not (risk > 0) or not math.isfinite(x):
                excluded["bad_prices"] += 1
                continue
            r_hold = s * (x - e) / risk
            path = conn.execute("SELECT bars_held, open_r, bar_ts FROM position_path_history WHERE order_package_id = ? "
                                "ORDER BY bar_ts", (k,)).fetchall()
            bar1 = next((p for p in path if (p["bars_held"] or 0) >= BAR1_BARS_HELD and p["open_r"] is not None), None)
            if bar1 is not None:
                r_bar1, how = float(bar1["open_r"]), "path_bar1"
            elif path and max((p["bars_held"] or 0) for p in path) < BAR1_BARS_HELD:
                r_bar1, how = r_hold, "closed_before_bar1"
            elif not path:
                # no path rows at all: the trade may have closed inside its first bar (no bar ever closed while open) or the
                # path writer missed it; the two are not distinguishable here, so it is excluded, never assumed delta 0
                excluded["no_bar1_path_row"] += 1
                continue
            else:
                excluded["no_bar1_path_row"] += 1
                continue
            pkgs.append({"order_package_id": k, "strategy": t["strategy_name"], "account_class": t["account_class"],
                         "side": "long" if s > 0 else "short", "day": str(t["timestamp"])[:10], "r_hold": r_hold,
                         "r_bar1": r_bar1, "delta": r_bar1 - r_hold, "how": how, "exit_reason": t["exit_reason"]})
        return {"read_state": "measured", "packages": pkgs, "eligible": len(rep), "excluded": excluded}
    finally:
        conn.close()


def _q(xs: list, p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = (len(s) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def summarise(pkgs: list) -> dict:
    n = len(pkgs)
    if n == 0:
        return {"n": 0}
    d = [p["delta"] for p in pkgs]
    mean = sum(d) / n
    # day-clustered se: packages on one day share a market path (the closes of three longs on one day are not independent)
    by_day: dict = {}
    for p in pkgs:
        by_day.setdefault(p["day"], []).append(p["delta"] - mean)
    g = len(by_day)
    se = math.sqrt(sum(sum(v) ** 2 for v in by_day.values())) / n * math.sqrt(g / (g - 1)) if g > 1 else None
    rh, rb = [p["r_hold"] for p in pkgs], [p["r_bar1"] for p in pkgs]
    return {"n": n, "days": g, "mean_delta": mean, "se_day_clustered": se, "t": (mean / se) if se else None,
            "mean_r_hold": sum(rh) / n, "mean_r_bar1": sum(rb) / n,
            "p10_r_hold": _q(rh, 0.10), "p10_r_bar1": _q(rb, 0.10)}


def decide(s: dict, coverage: float | None) -> str:
    """Registered (RQ-20261127-cb1a-01): PASS iff n >= MIN_N AND coverage >= MIN_COVERAGE AND mean delta >= +DELTA AND the
    day-clustered t >= T_BAR AND p10(R_bar1) >= p10(R_hold) (close dominates on the mean AND the worst decile). FAIL iff
    n >= MIN_N AND coverage >= MIN_COVERAGE AND mean delta + T_BAR x se < +DELTA. INDETERMINATE otherwise (incl. low n /
    coverage / an unreadable se)."""
    if not s.get("n") or s["n"] < MIN_N or coverage is None or coverage < MIN_COVERAGE or s.get("se_day_clustered") is None:
        return "INDETERMINATE"
    if s["mean_delta"] + T_BAR * s["se_day_clustered"] < DELTA:
        return "FAIL"
    if (s["mean_delta"] >= DELTA and (s["t"] or 0) >= T_BAR and s["p10_r_bar1"] is not None
            and s["p10_r_hold"] is not None and s["p10_r_bar1"] >= s["p10_r_hold"]):
        return "PASS"
    return "INDETERMINATE"


def run(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    c = collect(Path(a.db))
    if c["read_state"] != "measured":  # collapsed-state: measured — this script's own read_state (measured | no_data), not position_telemetry.peak_state
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": c["read_state"], "verdict": "no_data",
               "note": c.get("why"), "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    else:
        pk = c["packages"]
        cov = (len(pk) / (len(pk) + c["excluded"]["no_bar1_path_row"])) if (pk or c["excluded"]["no_bar1_path_row"]) else None
        allp = summarise(pk)
        v = decide(allp, cov)
        cuts = {f"side={sd}": summarise([p for p in pk if p["side"] == sd]) for sd in ("long", "short")}
        cuts.update({f"class={k}": summarise([p for p in pk if p["account_class"] == k]) for k in sorted({p["account_class"] for p in pk})})
        cuts.update({f"strategy={k}": summarise([p for p in pk if p["strategy"] == k]) for k in sorted({p["strategy"] for p in pk})})
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured",
               "verdict": {"PASS": "pass", "FAIL": "fail"}.get(v, "indeterminate"),
               "population": (f"closed non-backtest {'/'.join(STRATEGIES)} order packages in the synced trade_journal.db (one per package, "
                              f"real-money row preferred), any account class; R on the trade's own signal-time stop"),
               "n": allp.get("n", 0),
               "note": (f"CLOSE-BAR1: {v} | n {allp.get('n')} pkgs over {allp.get('days')} days, coverage "
                        f"{None if cov is None else round(cov, 3)} | mean delta {allp.get('mean_delta')} (t {allp.get('t')}) | "
                        f"mean R hold {allp.get('mean_r_hold')} vs bar1 {allp.get('mean_r_bar1')} | p10 hold {allp.get('p10_r_hold')} "
                        f"vs bar1 {allp.get('p10_r_bar1')}"),
               "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "measurement": {"all": allp, "cuts": cuts, "eligible_packages": c["eligible"], "excluded": c["excluded"],
                               "coverage": cov, "thresholds": {"min_n": MIN_N, "delta": DELTA, "t_bar": T_BAR,
                                                               "min_coverage": MIN_COVERAGE},
                               "packages": pk},
               "produced_by": {"tool": "python3 scripts/research/ml_entry_close_bar1.py", "where": a.where}}
    (out / f"{a.unit or 'close_bar1'}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(row["note"], flush=True)
    return 0


def self_test() -> int:
    root = Path(tempfile.mkdtemp())
    db = root / "tj.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, order_package_id TEXT, strategy_name TEXT, account_class TEXT, "  # data-wiring: self-test fixture (temp dir); the truth is the canonical trade_journal.db, read mode=ro
                 "direction TEXT, entry_price REAL, exit_price REAL, stop_loss REAL, timestamp TEXT, exit_reason TEXT, "
                 "status TEXT, is_backtest INTEGER)")
    conn.execute("CREATE TABLE position_path_history (order_package_id TEXT, bar_ts TEXT, bars_held INTEGER, open_r REAL)")  # data-wiring: self-test fixture (temp dir); the truth is the canonical trade_journal.db, read mode=ro
    tid = 0
    for i in range(60):
        pkg = f"p{i}"
        day = f"2026-11-{1 + i // 3:02d}"
        long = i % 2 == 0
        e, sl = 100.0, (98.0 if long else 102.0)
        x = 98.0 if long else 102.0                 # every trade stopped out: R_hold = -1
        for acct in (("real_money", "paper") if i % 3 == 0 else ("paper",)):   # duplicated package -> one representative
            tid += 1
            conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",  # writer-conformance: allow self-test fixture in a temp dir, never the journal
                         (tid, pkg, "ml_entry" if i % 4 else "ml_entry_v2", acct, "long" if long else "short", e, x, sl,
                          day + "T01:00:00", "sl_hit", "closed", 0))
        if i < 56:                                   # bars_held 1 = the entry bar; 2 = first row after one full bar
            conn.execute("INSERT INTO position_path_history VALUES (?,?,?,?)", (pkg, day + "T01:30:00", 1, 0.3))  # writer-conformance: allow self-test fixture in a temp dir, never the journal
            conn.execute("INSERT INTO position_path_history VALUES (?,?,?,?)", (pkg, day + "T02:00:00", 2, -0.2 + 0.01 * (i % 5)))  # writer-conformance: allow self-test fixture in a temp dir, never the journal
            conn.execute("INSERT INTO position_path_history VALUES (?,?,?,?)", (pkg, day + "T03:00:00", 3, -0.5))  # writer-conformance: allow self-test fixture in a temp dir, never the journal
        elif i == 56:                                # closed inside the first bars: path never reached 2 -> delta 0
            conn.execute("INSERT INTO position_path_history VALUES (?,?,?,?)", (pkg, day + "T01:30:00", 1, -0.4))  # writer-conformance: allow self-test fixture in a temp dir, never the journal
        # i 57..59: no path rows at all -> excluded (not assumed delta 0), coverage 57/60
    tid += 1                                         # a backtest row and an open row are never read
    conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",  # writer-conformance: allow self-test fixture in a temp dir, never the journal
                 (tid, "bt", "ml_entry", "paper", "long", 100, 110, 98, "2026-11-02T00:00:00", "tp", "closed", 1))
    conn.commit()
    conn.close()
    c = collect(db)
    assert c["read_state"] == "measured" and c["eligible"] == 60, c["eligible"]  # collapsed-state: measured — this script's own read_state (measured | no_data), not position_telemetry.peak_state
    assert c["excluded"]["no_bar1_path_row"] == 3 and len(c["packages"]) == 57, c["excluded"]
    assert all(abs(p["r_hold"] + 1.0) < 1e-9 for p in c["packages"])
    cb = [p for p in c["packages"] if p["how"] == "closed_before_bar1"]
    assert len(cb) == 1 and cb[0]["delta"] == 0.0, cb
    assert all(abs(p["r_bar1"] - 0.3) > 1e-9 for p in c["packages"]), "the entry-bar row (bars_held 1) must never be read as bar 1"
    assert all(p["account_class"] == "real_money" for p in c["packages"] if int(p["order_package_id"][1:]) % 3 == 0)
    s = summarise(c["packages"])
    assert s["n"] == 57 and abs(s["mean_delta"] - (s["mean_r_bar1"] + 1.0)) < 1e-9 and s["p10_r_bar1"] > s["p10_r_hold"]
    assert decide(s, 57 / 60) == "PASS", (s, decide(s, 57 / 60))     # bar1 ~ -0.18 vs hold -1: close dominates
    assert decide(s, 0.5) == "INDETERMINATE"                          # coverage below the floor
    assert decide({**s, "n": 10}, 0.95) == "INDETERMINATE"            # n below the floor
    assert decide({**s, "mean_delta": -0.2, "t": -3.0}, 0.95) == "FAIL"
    assert decide({**s, "mean_delta": 0.12, "se_day_clustered": 0.2, "t": 0.6}, 0.95) == "INDETERMINATE"
    o = root / "out"
    rc = run(argparse.Namespace(db=str(db), out=str(o), unit="RQ-SELFTEST", rule_id="R", registered_at="2026-11-27", where="local"))
    v = json.loads((o / "verdict.json").read_text())
    assert rc == 0 and v["verdict"] == "pass" and v["n"] == 57 and "side=long" in v["measurement"]["cuts"]
    nd = root / "empty.db"
    sqlite3.connect(nd).close()
    assert collect(nd)["read_state"] == "no_data"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--db", default="data/trade_journal.db")
    ap.add_argument("--out", default="/tmp/ml_entry_close_bar1")
    ap.add_argument("--unit", default="")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    ap.add_argument("--where", default="trainer")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    return run(a)


if __name__ == "__main__":
    sys.exit(main())

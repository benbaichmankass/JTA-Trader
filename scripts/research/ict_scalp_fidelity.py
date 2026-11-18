#!/usr/bin/env python3
# wiring: research/queue/RQ-20261118-abab-*.yaml (the ict_scalp_eth_15m FIDELITY re-test unit, via research-script-run.yml)
"""FIDELITY re-test of one ict_scalp 15m leg: does the backtest reproduce what the leg did live, and is it
net-positive at the cost actually paid? (promotion row PI-20261117-LSFHBH4A-0007; manager spec 2026-11-18)

ARM A  TRADE-MATCH. Replay the live window in the SAME harness the Stage-0 records use and join each live closed trade
       (``/api/bot/trades/closed`` for the account, ``/api/bot/order-packages`` for the R basis) to the harness trade on
       the same side within +-1 bar, using ``live_bt_trade_join.join`` (not re-implemented). Reported: match rate
       (matched / live trades that carry an R basis), Pearson r of live gross R vs replay gross R on matched pairs,
       the mean live-minus-replay GROSS R gap with a seeded 10,000-draw bootstrap 95% CI, and the divergence components
       (entry / exit / execution) so a FAIL names its cause.
       A_PASS iff matched_rate >= 0.80 AND the gap CI contains 0. A_FAIL iff live trades with R basis >= 30 and not
       A_PASS. A_INDETERMINATE iff fewer than 30 live trades carry an R basis (the floor is never lowered).
ARM B  COST. The committed 365 d record window re-run at five registered cost bases (fee bps round trip / slippage bps
       round trip, funding per window from ``execution_costs.resolve_cost_policy`` in all five):
         B1 11.0 / 3.0   the current stack          B2 7.5 / 3.0   the pre-2026-10-28 reading
         B3 11.0 / 0.82  taker/taker fee, MEASURED  B4 7.5 / 0.82  maker-entry/taker-exit bound, MEASURED slippage
         B5 11.0 / 1.64  0.82 read as per-side (sensitivity)
       B3 is the primary basis (this leg has no post-only entry line, so its fee is taker/taker).
       Per basis: n, net R, expectancy, bootstrap 95% CI of expectancy.
       B3_CLEAR iff expectancy >= 0. B3_NEGATIVE iff the CI upper bound < 0. Otherwise B3_AMBIGUOUS (mean < 0, CI
       contains 0). B_INDETERMINATE iff B3 n < 39.
UNIT VERDICT (registered in the queue unit before the run):
       pass          iff A_PASS and B3_CLEAR            -> the live-bar promotion stands.
       fail          iff A_FAIL or B3_NEGATIVE          -> a revert is PROPOSED to the operator (never done here).
       indeterminate otherwise (an indeterminate arm, or A_PASS with B3_AMBIGUOUS): no endorsement, numbers to the manager.

    ict_scalp_fidelity.py --leg ict_scalp_eth_15m --out DIR [--account bybit_1] [--live-start 2026-07-24]
    ict_scalp_fidelity.py --self-test

Reads two public GET routes (dollar fields are dropped on read and never written). Research tooling: no config write,
places no order. Writes DIR/verdict.json (read by script_run.py).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research", REPO / "scripts" / "ops"):
    sys.path.insert(0, str(_p))

RULE_ID = "RULE-RQ20261118-ICTSCALP-ETH15M-FIDELITY"
MATCH_MIN = 0.80
A_MIN_N = 30
B_MIN_N = 39
BOOT_DRAWS = 10_000
BOOT_SEED = 20261118
TOL_BARS = 1
COST_BASES = {"B1": (11.0, 3.0), "B2": (7.5, 3.0), "B3": (11.0, 0.82), "B4": (7.5, 0.82), "B5": (11.0, 1.64)}
PRIMARY = "B3"


def bootstrap_mean_ci(xs: list, seed: int = BOOT_SEED, draws: int = BOOT_DRAWS) -> list | None:
    """Seeded percentile bootstrap 95% CI of the mean; None for an empty sample."""
    n = len(xs)
    if not n:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(xs) for _ in range(n)) / n for _ in range(draws))
    return [round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)]


def pearson(a: list, b: list) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return None
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb), 4)


def arm_a(summary: dict, rows: list) -> dict:
    """The registered A rule on a ``live_bt_trade_join`` result (pure)."""
    with_r = int(summary.get("with_r_basis", 0))
    m = [r for r in rows if r.get("class") == "matched"]
    gaps = [r["live_gross_r"] - float(r["bt"]["gross_r"]) for r in m]
    live_r = [r["live_gross_r"] for r in m]
    bt_r = [float(r["bt"]["gross_r"]) for r in m]
    rate = round(len(m) / with_r, 4) if with_r else None
    ci = bootstrap_mean_ci(gaps)
    gap_mean = round(sum(gaps) / len(gaps), 4) if gaps else None
    ci_has_0 = bool(ci and ci[0] <= 0 <= ci[1])
    comps = summary.get("components_r") or {}
    if with_r < A_MIN_N:
        state = "indeterminate"
    elif rate is not None and rate >= MATCH_MIN and ci_has_0:
        state = "pass"
    else:
        state = "fail"
    why = []
    if state == "fail":
        if rate is None or rate < MATCH_MIN:
            why.append(f"match rate {rate} < {MATCH_MIN}: live-only {summary['live_only']['n']} "
                       f"(median {summary['live_only'].get('median_minutes_into_bar')} min into the bar = forming-bar entries), "
                       f"backtest-only {summary['bt_only']['n']}")
        if not ci_has_0:
            why.append(f"mean live-minus-replay gross R gap {gap_mean} CI {ci} excludes 0 "
                       f"(entry {comps.get('entry')}, exit {comps.get('exit')}, execution {comps.get('execution')})")
    return {"state": state, "live_trades_with_r_basis": with_r, "live_trades": summary.get("live_trades"),
            "matched": len(m), "match_rate": rate, "pearson_r_live_vs_replay_gross_r": pearson(live_r, bt_r),
            "mean_gap_gross_r": gap_mean, "gap_ci95_bootstrap": ci, "gap_ci_contains_0": ci_has_0,
            "mde_note": "with the observed spread of the gap the CI-contains-0 clause only excludes a gap larger than half "
                        "the CI width; a narrow-pass is not proof of zero gap",
            "components_r": comps, "diverged_because": why,
            "close_reason_mix": _mix(rows)}


def _mix(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        k = f"{r.get('class')}:{r.get('close_reason')}"
        out[k] = out.get(k, 0) + 1
    return out


def arm_b_basis(trades: list) -> dict:
    rs = [float(t.get("net_r") or 0.0) for t in trades]
    n = len(rs)
    net = round(sum(rs), 4)
    return {"n": n, "net_r": net, "expectancy_r": round(net / n, 4) if n else None,
            "expectancy_ci95_bootstrap": bootstrap_mean_ci(rs)}


def arm_b(by_basis: dict) -> dict:
    p = by_basis[PRIMARY]
    ci = p["expectancy_ci95_bootstrap"]
    if p["n"] < B_MIN_N:
        state = "indeterminate"
    elif p["expectancy_r"] is not None and p["expectancy_r"] >= 0:
        state = "clear"
    elif ci and ci[1] < 0:
        state = "negative"
    else:
        state = "ambiguous"
    return {"state": state, "primary_basis": PRIMARY, "bases": by_basis,
            "cost_bases_fee_slip_bps_rt": {k: list(v) for k, v in COST_BASES.items()}}


def unit_verdict(a: dict, b: dict) -> str:
    if a["state"] == "fail" or b["state"] == "negative":
        return "fail"
    if a["state"] == "pass" and b["state"] == "clear":
        return "pass"
    return "indeterminate"


def _fetch_and_emit(leg: str, cfg: dict, csv: str, start: str, end: str, tag: str, wd: str, extra: list) -> list:
    import regime_debt_matrix as rdm  # noqa: PLC0415
    from live_bt_trade_join import load_bt  # noqa: PLC0415
    emit = os.path.join(wd, f"{leg}__{tag}__trades.jsonl")
    jout = os.path.join(wd, f"{leg}__{tag}__bt.json")
    argv, _faithful, _omitted = rdm.build_harness_cmd(leg, cfg, "ict_scalp", csv, rdm.resolve_feed(cfg["symbols"][0], cfg["timeframe"])["resample"], emit, jout)
    argv += extra
    subprocess.run(argv, check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    return load_bt(Path(emit))


def _candles(leg: str, cfg: dict, start: str, end: str, wd: str, tag: str) -> str:
    import regime_debt_matrix as rdm  # noqa: PLC0415
    feed = rdm.resolve_feed(cfg["symbols"][0], cfg["timeframe"])
    csv = os.path.join(wd, f"{leg}__{tag}__data.csv")
    subprocess.run([sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", feed["ticker"],
                    "--interval", feed["interval"], "--start-date", start, "--end-date", end,
                    "--output", csv, "--source", "binance_vision"], check=True, cwd=REPO)
    return csv


def run(leg: str, account: str, live_start: str, cost_start: str, cost_end: str, wd: str) -> dict:
    import regime_debt_matrix as rdm  # noqa: PLC0415
    import live_bt_trade_join as lbj  # noqa: PLC0415
    from src.runtime.execution_costs import resolve_cost_policy  # noqa: PLC0415
    cfg = rdm.resolve_strategy(leg)
    if not cfg:
        return {"verdict": "not_applicable", "read_state": "no_data", "note": f"{leg} not in strategies.yaml"}
    sym = cfg["symbols"][0]
    _slip, fund = resolve_cost_policy(sym)
    # ---- arm A: live window replay at the current cost stack (gross R is compared, so cost does not enter the gap)
    ls = datetime.fromisoformat(live_start).replace(tzinfo=timezone.utc)
    live_end = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    warm = (ls - timedelta(days=45)).strftime("%Y-%m-%d")
    csv_a = _candles(leg, cfg, warm, live_end, wd, "live")
    slip_now, _ = resolve_cost_policy(sym)
    bt = _fetch_and_emit(leg, cfg, csv_a, warm, live_end, "live", wd, ["--slippage-bps-roundtrip", str(slip_now), "--funding-bps-per-window", str(fund)])
    closed = [t for t in lbj.fetch_closed(account) if t.get("pattern") == leg and str(t.get("openedAt")) >= live_start]
    live = lbj._strip(closed)
    pk = lbj.fetch_packages(leg, live_start)
    res = lbj.join(leg, live, pk, bt, cfg["timeframe"], tol_bars=TOL_BARS)
    a = arm_a(res["summary"], res["rows"])
    a.update({"account": account, "live_window": res["window"], "harness_trades_in_window": res["summary"]["regime_bt_window"]["n"]})
    # ---- arm B: the committed 365 d window at five cost bases
    csv_b = _candles(leg, cfg, cost_start, cost_end, wd, "cost")
    by = {}
    for name, (fee, slip) in COST_BASES.items():
        tr = _fetch_and_emit(leg, cfg, csv_b, cost_start, cost_end, name, wd,
                             ["--fee-bps-roundtrip", str(fee), "--slippage-bps-roundtrip", str(slip), "--funding-bps-per-window", str(fund)])
        by[name] = arm_b_basis(tr)
    b = arm_b(by)
    b["window"] = {"start": cost_start, "end": cost_end}
    v = unit_verdict(a, b)
    return {"verdict": v, "read_state": "measured", "n": a["live_trades_with_r_basis"], "leg": leg, "symbol": sym,
            "arm_a": a, "arm_b": b, "decision_rule_id": RULE_ID,
            "action": {"pass": "live-bar promotion stands", "fail": "PROPOSE a revert to the operator (a demotion is never done here)",
                       "indeterminate": "no endorsement and no revert: numbers to the manager"}[v]}


def self_test() -> int:
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0 and pearson([1, 1, 1], [1, 2, 3]) is None
    assert bootstrap_mean_ci([]) is None
    ci = bootstrap_mean_ci([0.1] * 50)
    assert ci == [0.1, 0.1], ci

    def rows(n_match, n_live_only, gap):
        r = [{"class": "matched", "live_gross_r": 0.5 + (i % 3) * 0.1, "bt": {"gross_r": 0.5 + (i % 3) * 0.1 - gap},
              "close_reason": "tp"} for i in range(n_match)]
        r += [{"class": "live_only", "live_gross_r": 0.1, "close_reason": "other"} for _ in range(n_live_only)]
        return r
    summ = lambda r: {"with_r_basis": len(r), "live_trades": len(r), "live_only": {"n": sum(1 for x in r if x["class"] == "live_only"), "median_minutes_into_bar": 4.0}, "bt_only": {"n": 0}, "components_r": {}}  # noqa: E731
    r1 = rows(40, 5, 0.0)
    assert arm_a(summ(r1), r1)["state"] == "pass"
    r2 = rows(30, 15, 0.0)
    assert arm_a(summ(r2), r2)["state"] == "fail"                       # match 0.667 < 0.8
    r3 = rows(40, 0, 0.3)
    assert arm_a(summ(r3), r3)["state"] == "fail"                       # gap CI excludes 0
    r4 = rows(10, 0, 0.0)
    assert arm_a(summ(r4), r4)["state"] == "indeterminate"              # < 30 with an R basis
    mk = lambda e, n: {"n": n, "net_r": e * n, "expectancy_r": e, "expectancy_ci95_bootstrap": [e - 0.1, e + 0.1]}  # noqa: E731
    assert arm_b({"B3": mk(0.05, 80)})["state"] == "clear"
    assert arm_b({"B3": {"n": 80, "net_r": -8, "expectancy_r": -0.1, "expectancy_ci95_bootstrap": [-0.2, -0.05]}})["state"] == "negative"
    assert arm_b({"B3": mk(-0.02, 80)})["state"] == "ambiguous"
    assert arm_b({"B3": mk(0.05, 20)})["state"] == "indeterminate"
    A = lambda s: {"state": s}  # noqa: E731
    B = lambda s: {"state": s}  # noqa: E731
    assert unit_verdict(A("pass"), B("clear")) == "pass"
    assert unit_verdict(A("fail"), B("clear")) == "fail" and unit_verdict(A("pass"), B("negative")) == "fail"
    assert unit_verdict(A("pass"), B("ambiguous")) == "indeterminate" and unit_verdict(A("indeterminate"), B("clear")) == "indeterminate"
    print("ict_scalp_fidelity self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", default="ict_scalp_eth_15m")
    ap.add_argument("--out")
    ap.add_argument("--account", default="bybit_1")
    ap.add_argument("--live-start", default="2026-07-24", help="first live closed trade of the leg on the account (soak start)")
    ap.add_argument("--cost-start", default="2025-10-04", help="the committed 365 d record's window start")
    ap.add_argument("--cost-end", default="2026-10-01")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.out:
        ap.error("--out is required")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as wd:
        try:
            res = run(a.leg, a.account, a.live_start, a.cost_start, a.cost_end, wd)
        except Exception as e:  # allow-silent: not silent -- recorded in verdict.json as read_state producer_failed with the exception text; noqa: BLE001
            res = {"verdict": "not_applicable", "read_state": "producer_failed", "note": f"{type(e).__name__}: {e}", "leg": a.leg}
    doc = {"verdict": res["verdict"], "read_state": res["read_state"], "n": res.get("n", 0),
           "population": f"{a.leg}: live closed trades on {a.account} since {a.live_start} joined to the harness replay (arm A); "
                         f"harness re-run on {a.cost_start}..{a.cost_end} at five cost bases (arm B)",
           "measurement": res, "note": res.get("note", "")}
    (out / "verdict.json").write_text(json.dumps(doc, indent=2, default=str) + "\n")
    print(json.dumps({k: doc[k] for k in ("verdict", "read_state", "n")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

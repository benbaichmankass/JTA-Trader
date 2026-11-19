#!/usr/bin/env python3
# wiring: manual-only - run by queue unit RQ-20261119-d4f8-01 (research-script-run.yml, once the manager merges it); no schedule consumes it.
"""IB-GROSS-ATR-FLOOR-S0 re-registered on ict_scalp_mgc_15m, on a Dukascopy XAU_USD (spot gold) PROXY of MGC.

Registered BEFORE any run: unit RQ-20261119-d4f8-01 decision_rule RULE-IB-GROSS-ATR-FLOOR-S0-MGC15-XAUPROXY (lane QUEUE-FILL-STANDING-W47b, manager GO
2026-11-19 04:21Z with four conditions, all kept). WHY: RQ-20261119-b9a4-01 (the ATR-floor test on the 141 committed IB trades) was vacuous -- the floor
never binds there (0% reweighted, every stop is already >= 2.5 ATR) -- because the leg whose stop motivated the fix, ict_scalp_mgc_15m (live stop
0.26-0.40% of price), has no committed per-trade rows and the only committed 15m MGC candles give 18 trades in 54 days.

THE PROXY (state it everywhere): the candles are Dukascopy XAU_USD spot gold at 15m, the adjudicated proxy for MGC (scripts/ops/dukascopy_instruments.py,
REL_PROXY). It has NO futures roll, a different session calendar (24x5 spot vs CME Globex with a daily break) and a different price level; the harness
costs are MGC's OWN stack (resolve_cost_policy keyed on the leg's symbol MGC, not on the data source). A result is a statement about the leg's stop
geometry against ATR on gold, not a Stage-0 record for MGC futures.

STEPS (a registered step each, nothing previewed before the unit merges):
 1  fetch   scripts/ops/fetch_backtest_candles.py --source dukascopy XAU proxy of MGC, 15m, --days DAYS -> <root>/candles/MGC_15m.csv
 2  corpus  exit_lever_ablation.py --leg ict_scalp_mgc_15m --arm A= --data-csv <that csv> (the leg as declared in config/strategies.yaml, the
            same call build_ltr_corpus.py makes in mode harness) -> arms/A__trades.jsonl, net of the harness's full cost stack
 3  floor   the ib_gross_atr_floor.evaluate test, UNCHANGED, on those rows: ATR14 at entry from bars closed before entry_time at 15m; arms A and
            B_k (k 0.5, 1.0); M1 max gross notional / equity, M2 ratio (80% bootstrap lower bound), M3 return / max drawdown.
N FLOOR: INDETERMINATE if fewer than 100 trades come out of step 2 or fewer than 100 have a computable ATR14 (manager condition; the ATR test's own
floor of 60 is raised for this unit). BAR (identical to RULE-IB-GROSS-ATR-FLOOR-S0): PASS for the smallest k where (a) M1 <= 1.5 at every point AND
(b) the 80% bootstrap lower bound of M2(B_k)/M2(A) >= 0.80 AND (c) M3(B_k) >= 0.90 x M3(A); FAIL if no k passes. Reported: reweighted share, median
stop / ATR14, per-month trade counts. Tier-1 research tooling: public candles, writes only under --out, changes no sizer and no config.
Gates this adds or changes: none. Provenance: counts and metrics are MEASURED when a run lands; nothing in this file is a result.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ib_gross_atr_floor as ib  # noqa: E402  (the registered test; reused, not rewritten)

RULE_ID = "RULE-IB-GROSS-ATR-FLOOR-S0-MGC15-XAUPROXY"
LEG = "ict_scalp_mgc_15m"
SYMBOL, TF = "MGC", "15m"
DAYS = 1100
N_FLOOR = 100


@contextlib.contextmanager
def single_leg() -> Iterator[None]:
    """ib_gross_atr_floor.evaluate loops over its module LEGS and TF_SEC; point them at this one 15m leg for the call, restore on exit."""
    old = (ib.LEGS, dict(ib.TF_SEC))
    ib.LEGS = (LEG,)
    ib.TF_SEC["15m"] = 900
    try:
        yield
    finally:
        ib.LEGS, ib.TF_SEC = old[0], old[1]
        ib.TF_SEC.clear()
        ib.TF_SEC.update(old[1])


def trade_rows(trades: List[dict]) -> List[dict]:
    """ib_gross_atr_floor row dicts from the harness's per-trade rows (entry, sl, net_r, times)."""
    rows = []
    holds = [(ib._t(t["exit_time"]) - ib._t(t["entry_time"])).total_seconds() for t in trades if t.get("exit_time")]
    med = statistics.median(holds) if holds else 0.0
    for t in trades:
        et = ib._t(t["entry_time"])
        xt = ib._t(t["exit_time"]) if t.get("exit_time") else et + timedelta(seconds=med)
        rows.append({"leg": LEG, "symbol": SYMBOL, "tf": TF, "strategy": "ict_scalp", "atr_stop_mult": None, "entry_time": et, "exit_time": xt,
                     "entry": float(t["entry"]), "sl": float(t["sl"]), "net_r": float(t["net_r"]),
                     "dist": abs(float(t["entry"]) - float(t["sl"])), "exit_imputed": not t.get("exit_time")})
    rows.sort(key=lambda r: (r["entry_time"], r["leg"]))
    return rows


def evaluate_proxy(rows: List[dict], draws: int = ib.BOOT) -> Dict[str, Any]:
    """The registered floor test with the unit's n floor of 100 (trades AND computable ATR14)."""
    n, n_atr = len(rows), sum(1 for r in rows if r.get("atr") is not None)
    base: Dict[str, Any] = {"rule": RULE_ID, "proxy": "Dukascopy XAU_USD spot 15m for MGC (no roll, different session, MGC's own cost stack)",
                            "n_trades": n, "n_atr_computable": n_atr, "n_floor": N_FLOOR}
    if n < N_FLOOR or n_atr < N_FLOOR:
        return dict(base, verdict="INDETERMINATE", verdict_reason=f"{n} trades / {n_atr} with a computable ATR14, below the n floor of {N_FLOOR}")
    with single_leg():
        res = ib.evaluate(rows, draws=draws)
    stops = [r["dist"] / r["atr"] for r in rows if r.get("atr")]
    res.update(base)
    res["median_stop_over_atr"] = float(statistics.median(stops)) if stops else None
    months: Dict[str, int] = {}
    for r in rows:
        months[r["entry_time"].strftime("%Y-%m")] = months.get(r["entry_time"].strftime("%Y-%m"), 0) + 1
    res["trades_per_month"] = months
    return res


def fetch_and_corpus(root: Path, days: int = DAYS) -> List[dict]:
    """Steps 1 and 2. Raises on a failed fetch or harness (a producer failure, never a partial read)."""
    import exit_lever_ablation as ela
    csv = root / "candles" / f"{SYMBOL}_{TF}.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    code = ela._DUKA_INTERVAL[TF]
    subprocess.run([sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", SYMBOL, "--source", "dukascopy",
                    "--interval", code, "--days", str(days), "--output", str(csv)], check=True, cwd=str(REPO))
    out = root / "ablation"
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", LEG, "--arm", "A=", "--data-csv", str(csv),
                        "--grade", "stage0", "--baseline", "A", "--delta-r", "1", "--fold-majority", "3", "--n-floor", "20", "--out", str(out)],
                       cwd=str(REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"harness exit {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
    return [json.loads(ln) for ln in (out / "arms" / "A__trades.jsonl").read_text().splitlines() if ln.strip()]


def self_test() -> int:
    from datetime import timezone
    base = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def mk(i: int, dist: float, atr: Optional[float], net: float) -> dict:
        et = base + timedelta(hours=7 * i)
        return {"leg": LEG, "symbol": SYMBOL, "tf": TF, "strategy": "ict_scalp", "atr_stop_mult": None, "entry_time": et, "exit_time": et + timedelta(hours=1),
                "entry": 4000.0, "sl": 4000.0 - dist, "net_r": net, "dist": dist, "exit_imputed": False, "atr": atr}

    # below the n floor: 99 trades with an ATR each is INDETERMINATE (a hand-checked boundary)
    few = [mk(i, 12.0, 8.0, 0.1) for i in range(99)]
    assert evaluate_proxy(few, draws=50)["verdict"] == "INDETERMINATE"
    # 100 trades but only 99 with a computable ATR: INDETERMINATE
    assert evaluate_proxy([mk(i, 12.0, 8.0 if i else None, 0.1) for i in range(100)], draws=50)["verdict"] == "INDETERMINATE"
    # a tight stop (dist 4, ATR 8): the floor BINDS (k=1.0 weight 0.5, k=0.5 weight 1.0); a wide stop (dist 20) does not
    tight = [mk(i, 4.0, 8.0, 0.2 if i % 3 else -1.0) for i in range(120)]
    e = evaluate_proxy(tight, draws=200)
    assert e["verdict"] in ("PASS", "FAIL") and abs(e["arms"]["1.0"]["reweighted_share"] - 1.0) < 1e-9 and e["arms"]["0.5"]["reweighted_share"] == 0.0, e["arms"]["1.0"]["reweighted_share"]
    assert abs(e["arms"]["1.0"]["mean_w"] - 0.5) < 1e-9
    wide = [mk(i, 20.0, 8.0, 0.2) for i in range(120)]
    ew = evaluate_proxy(wide, draws=100)
    assert ew["arms"]["1.0"]["reweighted_share"] == 0.0 and ew["median_stop_over_atr"] == 2.5
    # the module globals the test patches are restored
    assert ib.LEGS == ("mgc_trend_1h", "mhg_pullback_1d", "mgc_pullback_1d", "mes_trend_long_1d") and "15m" not in ib.TF_SEC
    # trade_rows maps a harness row
    r = trade_rows([{"entry_time": "2026-01-05 00:00:00+00:00", "exit_time": "2026-01-05 01:00:00+00:00", "entry": 4000.0, "sl": 3996.0, "net_r": 0.5}])[0]
    assert r["dist"] == 4.0 and r["leg"] == LEG and r["tf"] == "15m"
    print("self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", choices=("run",))
    ap.add_argument("--root")
    ap.add_argument("--out")
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.mode:
        ap.error("mode or --self-test required")
    root = Path(a.root)
    out = Path(a.out or root / "out")
    trades = fetch_and_corpus(root, a.days)
    rows = trade_rows(trades)
    with single_leg():
        ib.attach_atr(rows, ib.load_bars(root, rows))
    res = evaluate_proxy(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ict_mgc_xau_atr_floor.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps({
        "verdict": {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate"}[res["verdict"]], "read_state": "measured",
        "population": f"{res['n_trades']} ict_scalp_mgc_15m trades on the Dukascopy XAU_USD 15m proxy of MGC, {res['n_atr_computable']} with a computable ATR14",
        "n": res["n_atr_computable"], "measurement": res, "note": res["verdict_reason"], "data_inputs": ["dukascopy XAU_USD 15m (proxy for MGC)"]},
        indent=2, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("n_trades", "n_atr_computable", "verdict", "verdict_reason")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

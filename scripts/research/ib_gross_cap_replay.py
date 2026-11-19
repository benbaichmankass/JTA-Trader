#!/usr/bin/env python3
# wiring: manual-only - run by queue unit RQ-20261119-c7e5-01 (research-script-run.yml, once the manager merges it); no schedule consumes it.
"""IB-GROSS-CAP-S0 -- does a gross-exposure CAP of G x equity cost the dollar edge of the committed Stage-0 IB corpus?

Registered BEFORE any run: unit RQ-20261119-c7e5-01 decision_rule RULE-IB-GROSS-CAP-S0 (lane QUEUE-FILL-STANDING-W47b, manager GO 2026-11-19
04:17Z, follow-up (b) of IB-GROSS-ATR-FLOOR-S0: RQ-20261119-b9a4-01 showed the ATR floor never binds on this corpus, reweighted 0%, and that the
3.53x peak gross is CONCURRENCY across legs at 1.5% risk each). Tier-1 research tooling: reads committed evidence only, writes under --out,
changes no sizer and no config.

CORPUS  the same 141 committed Stage-0 per-trade rows as ib_gross_atr_floor.py (mgc_trend_1h 118, mhg_pullback_1d 10, mgc_pullback_1d 8,
        mes_trend_long_1d 5; net of the full cost stack), loaded by ``ib_gross_atr_floor.load_corpus`` (timeframes read from each bt.json).
        ict_scalp_mgc_15m is NOT in it (no committed per-trade rows): this test says nothing about that leg.
ARMS    A = current sizing, risk 1.5% of equity over |entry-sl|, no cap. C_G = the same sizing under a gross-notional cap of G x equity, G in
        {1.5, 2.5}, applied at each entry the way the live cap acts: headroom = G - (sum of open notional)/equity; the trade takes
        f = clip(headroom / its desired notional-to-equity, 0, 1) of its size; f = 0 is a refusal (the live 'sized_qty=0'). SL unchanged, so a
        taken trade's net R is unchanged and only its dollar weight f moves. One compounding realised-equity path in entry_time order, a trade's
        P&L credited at exit_time (the same event path as ib_gross_atr_floor.path); desired notional-to-equity of a trade = 0.015 x entry / |entry-sl|.
METRICS M1 max concurrent gross notional / equity (<= G by construction); M2 = sum(f_i x net_r_i), ratio to arm A; M3 = return / max drawdown of the
        path; skipped share = trades with f = 0; scaled share = trades with 0 < f < 1.
BAR     PASS for the LARGEST G in {2.5, 1.5} whose cap costs no more than 20% of the dollar edge: (a) the 80% bootstrap lower bound (one-sided 20th
        percentile) of M2(C_G)/M2(A) >= 0.80, trades resampled 10,000 times with each trade's realised f held fixed (a paired reweighting, as
        b9a4-01), seed 20261119; AND (b) M3(C_G) >= 0.90 x M3(A); AND (c) at least 60 trades keep f > 0. FAIL if neither G passes.
        INDETERMINATE if fewer than 60 of the 141 trades have f > 0 under BOTH caps (the test cannot tell). Reported, not graded: the skipped and
        scaled shares, M1 of arm A, and the per-leg share of the skipped trades.
        pass_action: the cap at the passing G costs at most ~20% of the Stage-0 dollar edge on this corpus: a data-backed Tier-3 PROPOSAL to keep
        a gross cap at that G (config is not edited here). fail_action: a cap at these G costs more than 20% of the edge on this corpus; the
        concurrency driver needs a different lever (per-leg risk_pct, or staggering), not a cap. Gates this adds or changes: none.
Provenance: counts and metrics are MEASURED when a run lands; nothing in this file is a result.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ib_gross_atr_floor as ib  # noqa: E402  (the corpus loader and the shared constants; reused, not rewritten)

RULE_ID = "RULE-IB-GROSS-CAP-S0"
GS = (2.5, 1.5)                      # tried largest first: the bar picks the largest G that costs no more than 20% of the edge
RISK_PCT = ib.RISK_PCT
RATIO_BAR, M3_FRAC, MIN_TAKEN = 0.80, 0.90, 60
BOOT, SEED, LOWER_PCT = ib.BOOT, ib.SEED, ib.LOWER_PCT


def path_cap(rows: List[dict], cap: Optional[float]) -> Dict[str, Any]:
    """One compounding realised-equity path under a gross cap (None = no cap). Returns the per-trade fraction taken and the path metrics."""
    ev = []
    for i, r in enumerate(rows):
        ev.append((r["entry_time"], 1, i))
        ev.append((r["exit_time"], 0, i))               # an exit at the same instant as an entry is credited first
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    eq, peak, mdd, m1 = 1.0, 1.0, 0.0, 0.0
    open_: Dict[int, tuple] = {}                         # i -> (notional in equity units, pnl in equity units)
    f = np.ones(len(rows))
    for _, kind, i in ev:
        r = rows[i]
        if kind == 1:
            want = (RISK_PCT * eq * r["entry"] / r["dist"]) if r["dist"] > 0 else 0.0     # desired notional, equity units
            if cap is not None and want > 0:
                headroom = cap - sum(v[0] for v in open_.values()) / eq
                f[i] = min(1.0, max(0.0, headroom * eq / want))
            take = want * f[i]
            open_[i] = (take, eq * RISK_PCT * f[i] * r["net_r"])
            m1 = max(m1, sum(v[0] for v in open_.values()) / eq)
        else:
            eq += open_.pop(i, (0.0, 0.0))[1]
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
    ret = eq - 1.0
    return {"f": f, "m1_max": m1, "total_return": ret, "max_drawdown": mdd, "m3": (ret / mdd) if mdd > 0 else (float("inf") if ret > 0 else None)}


def evaluate(rows: List[dict], draws: int = BOOT) -> Dict[str, Any]:
    net = np.array([r["net_r"] for r in rows])
    a = path_cap(rows, None)
    res: Dict[str, Any] = {"rule": RULE_ID, "n_trades": len(rows), "A": {k: v for k, v in a.items() if k != "f"} | {"m2": float(net.sum())}, "arms": {}}
    legs = sorted({r["leg"] for r in rows})
    for g in GS:
        p = path_cap(rows, g)
        f = p["f"]
        m2 = float((f * net).sum())
        boot = ib.bootstrap_ratio(net, f, draws=draws)
        taken = int((f > 0).sum())
        m3_ok = bool(p["m3"] is not None and a["m3"] is not None and p["m3"] >= M3_FRAC * a["m3"])
        arm = {"m1_max": p["m1_max"], "total_return": p["total_return"], "max_drawdown": p["max_drawdown"], "m3": p["m3"], "m2": m2,
               "m2_ratio": (m2 / float(net.sum())) if net.sum() > 0 else None, "ratio_boot": boot, "taken": taken,
               "skipped_share": float((f == 0).mean()), "scaled_share": float(((f > 0) & (f < 1)).mean()),
               "skipped_by_leg": {leg: int(sum(1 for r, x in zip(rows, f) if r["leg"] == leg and x == 0)) for leg in legs},
               "a_ratio_ok": bool(boot["lower_80"] >= RATIO_BAR), "b_m3_ok": m3_ok, "c_taken_ok": bool(taken >= MIN_TAKEN)}
        arm["passes"] = bool(arm["a_ratio_ok"] and arm["b_m3_ok"] and arm["c_taken_ok"])
        res["arms"][str(g)] = arm
    if all(res["arms"][str(g)]["taken"] < MIN_TAKEN for g in GS):
        res["verdict"], res["verdict_reason"] = "INDETERMINATE", f"fewer than {MIN_TAKEN} trades keep f > 0 under both caps"
    else:
        win = next((g for g in GS if res["arms"][str(g)]["passes"]), None)
        res["verdict"] = "PASS" if win is not None else "FAIL"
        res["passing_cap"] = win
        res["verdict_reason"] = (f"largest passing cap G = {win}" if win is not None else "no cap passes: " + "; ".join(
            f"G={g}: ratio lb80 {res['arms'][str(g)]['ratio_boot']['lower_80']:.3f} ({res['arms'][str(g)]['a_ratio_ok']}), M3 ok {res['arms'][str(g)]['b_m3_ok']}, "
            f"taken {res['arms'][str(g)]['taken']}, skipped {res['arms'][str(g)]['skipped_share']:.2f}" for g in GS))
    return res


def _row(leg, t0, hold_h, entry, sl, net_r):
    et = datetime.fromisoformat(t0)
    return {"leg": leg, "symbol": "X", "tf": "1h", "entry_time": et, "exit_time": et + timedelta(hours=hold_h), "entry": entry, "sl": sl, "net_r": net_r,
            "dist": abs(entry - sl), "exit_imputed": False}


def self_test() -> int:
    # one trade, dist 1 at entry 100: desired notional/equity 1.5. Under cap 1.5 it takes f = 1; under cap 0.75 it takes f = 0.5 (hand-computed)
    one = [_row("a", "2026-01-01T00:00:00+00:00", 5, 100.0, 99.0, 2.0)]
    assert np.allclose(path_cap(one, None)["f"], [1.0]) and np.allclose(path_cap(one, 1.5)["f"], [1.0]) and np.allclose(path_cap(one, 0.75)["f"], [0.5])
    assert abs(path_cap(one, None)["total_return"] - 0.03) < 1e-12 and abs(path_cap(one, 0.75)["total_return"] - 0.015) < 1e-12
    # two overlapping trades, each wanting 1.5: under cap 2.0 the first takes all (1.5), the second gets headroom 0.5 -> f = 1/3; under cap 1.5 it is refused
    two = [_row("a", "2026-01-01T00:00:00+00:00", 10, 100.0, 99.0, 1.0), _row("b", "2026-01-01T02:00:00+00:00", 10, 100.0, 99.0, 1.0)]
    assert np.allclose(path_cap(two, 2.0)["f"], [1.0, 1 / 3]) and np.allclose(path_cap(two, 1.5)["f"], [1.0, 0.0])
    assert abs(path_cap(two, None)["m1_max"] - 3.0) < 1e-12 and abs(path_cap(two, 2.0)["m1_max"] - 2.0) < 1e-12
    # sequential (the first exits as the second enters): no overlap, no scaling under any cap that fits one trade
    seq = [_row("a", "2026-01-01T00:00:00+00:00", 5, 100.0, 99.0, 1.0), _row("b", "2026-01-01T05:00:00+00:00", 5, 100.0, 99.0, 1.0)]
    assert np.allclose(path_cap(seq, 1.5)["f"], [1.0, 1.0])
    # a cap that every trade fits under changes nothing: ratio 1, verdict PASS at the largest G
    solo = [_row("mgc_trend_1h", f"2026-02-{d:02d}T00:00:00+00:00", 6, 100.0, 90.0, 1.0 if d % 3 else -1.0) for d in range(1, 28)] * 3
    for i, r in enumerate(solo):
        r["entry_time"] = r["entry_time"] + timedelta(seconds=i)
        r["exit_time"] = r["entry_time"] + timedelta(hours=6)
    e = evaluate(sorted(solo, key=lambda x: x["entry_time"]), draws=300)
    assert e["verdict"] in ("PASS", "FAIL") and 0 <= e["arms"]["2.5"]["skipped_share"] <= 1
    # a corpus where both caps refuse almost everything is INDETERMINATE
    jam = [_row("a", "2026-03-01T00:00:00+00:00", 500, 100.0, 99.9, 1.0)] + [_row("b", f"2026-03-02T00:{m:02d}:00+00:00", 400, 100.0, 99.9, 1.0) for m in range(59)]
    assert evaluate(jam, draws=100)["verdict"] == "INDETERMINATE"
    # the registered corpus loads: 141 rows
    rows = ib.load_corpus()
    assert len(rows) == 141
    print("self-test OK", {"n": len(rows)})
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", choices=("run",))
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.mode:
        ap.error("mode or --self-test required")
    rows = ib.load_corpus()
    res = evaluate(rows)
    out = Path(a.out or ".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "ib_gross_cap_replay.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps({
        "verdict": {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate"}[res["verdict"]], "read_state": "measured",
        "population": f"{res['n_trades']} committed Stage-0 trades over 4 IB futures legs (comms/strategy_evidence/runs/2026-09-24-e55), gross cap replay",
        "n": res["n_trades"], "measurement": res, "note": res["verdict_reason"], "data_inputs": ["comms/strategy_evidence/runs/2026-09-24-e55"]},
        indent=2, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("n_trades", "verdict", "verdict_reason")}, indent=1))
    print("A", json.dumps(res["A"]))
    for g, v in res["arms"].items():
        print("G", g, json.dumps({x: v[x] for x in ("m1_max", "m2_ratio", "m3", "taken", "skipped_share", "scaled_share", "ratio_boot", "passes")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

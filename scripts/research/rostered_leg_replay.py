#!/usr/bin/env python3
# wiring: research/queue/RQ-20261125-f1a0-24.yaml (row REGIME-ROSTERED-CONFIG-REPLAY: the R3 confirmation on the configs we actually trade)
"""REGIME-ROSTERED-CONFIG-REPLAY: replay every ROSTERED crypto leg (a `mode: live` book, real-money / prop / demo floor) of the trend, pullback,
fade and squeeze families with its DECLARED config/strategies.yaml params over one pinned window, then grade the REGIME-PROGRAM R3 / R4 tilts on
those legs as books. The confirmation population of RQ-20261125-f1a0-20 (R3 PASS on the sweep corpus): different trades (declared configs, not
averaged sweep variants), the legs a sizing proposal would act on.

Replay: the evidence builder's own path, nothing reimplemented: exit_lever_ablation.fetch_candles (regime_debt_matrix._fetch_csv, keyless Binance
Vision) + exit_lever_ablation.build_arm_argv (regime_debt_matrix.build_harness_cmd, the harness's own venue-aware fee + slippage + funding) with
--start/--end pinned to WINDOW. A leg whose harness fails is a recorded state (`legs.<leg>.state`), never dropped silently.

Grade (RULE-REGIME-R3-CONFIRM-ROSTERED-20261125): books = leg x direction; the regime_r2_family_router machinery unchanged (weekly books, causal
trailing / same-cell prior means, 2.0 / 0.5 tilt renormalised weekly, 1,000 week-bootstrap draws, 200 within-week permutations). Arms: advol and hmm2
state tilts (f1a0-20) and the no-state tilt (f1a0-23's control), each vs equal risk. An arm PASSES iff delta >= +0.01 R/trade AND t >= 2 AND
permutation share <= 0.0167 (three arms, Bonferroni of 0.05) AND >= 4 of 5 test years > 0. UNIT PASS iff any arm passes; FAIL iff every arm has
delta <= 0 or share >= 0.5; else INDETERMINATE. Reported, not graded: the state-vs-no-state week-paired deltas (decomp), per-leg trade counts / net R.

    python3 scripts/research/rostered_leg_replay.py --out DIR [--legs a,b] [--work DIR]
    python3 scripts/research/rostered_leg_replay.py --self-test
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import regime_r2_family_router as RR  # noqa: E402

FAMILIES = ("trend", "pullback", "fade", "squeeze")
WINDOW = ("2020-09-01", "2026-10-26")          # pinned: the R2-R3 corpus window
FETCH_DAYS = 2350
RULE = {"id": "RULE-REGIME-R3-CONFIRM-ROSTERED-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05 / 3,
        "min_years_positive": 4, "n_test_years": 5, "fail_random_share": 0.5}


def rostered_legs(root: Path = REPO) -> Dict[str, Dict[str, Any]]:
    """Crypto legs on a `mode: live` book whose cfg classifies into FAMILIES: {leg: {cfg, book, harness}}."""
    import yaml
    import regime_debt_matrix as rdm
    spec = importlib.util.spec_from_file_location("mlc", root / "scripts/ci/check_research_queue_ml_consumer.py")
    mlc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mlc)
    book = mlc.books(root)
    st = yaml.safe_load((root / "config/strategies.yaml").read_text(encoding="utf-8"))["strategies"]
    out = {}
    for leg, b in sorted(book.items()):
        cfg = st.get(leg)
        if not isinstance(cfg, dict):
            continue
        sym = (cfg.get("symbols") or [None])[0]
        h = rdm.classify(cfg)
        if str(sym).endswith("USDT") and h in FAMILIES:
            out[leg] = {"cfg": cfg, "book": b, "harness": h}
    return out


def replay_leg(leg: str, cfg: Dict[str, Any], work: Path) -> Dict[str, Any]:
    import exit_lever_ablation as ela
    work.mkdir(parents=True, exist_ok=True)
    csv, emit, jout, log = (str(work / f"{leg}{x}") for x in (".csv", "__trades.jsonl", "__bt.json", ".log"))
    try:
        feed = ela.fetch_candles(leg, cfg, FETCH_DAYS, csv)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        return {"state": "fetch_failed", "why": f"{type(e).__name__}: {e}"[:300]}
    argv, omitted = ela.build_arm_argv(leg, cfg, csv, str(feed["resample"]), emit, jout, [], WINDOW[0], WINDOW[1])
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO), timeout=3600, check=False).returncode
    if rc != 0 or not Path(jout).is_file():
        return {"state": "harness_failed", "why": f"exit {rc}", "argv": argv[1:]}
    trades = ela._load_trades(emit) if Path(emit).is_file() else []
    return {"state": "measured", "n": len(trades), "net_r": round(float(sum(t.get("net_r") or 0.0 for t in trades)), 3),
            "omitted_levers": omitted, "argv": argv[1:], "trades": trades}


def trades_frame(per_leg: Dict[str, Dict[str, Any]], cfgs: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for leg, r in per_leg.items():
        if r.get("state") != "measured":
            continue
        sym, tf = cfgs[leg]["cfg"]["symbols"][0], str(cfgs[leg]["cfg"].get("timeframe"))
        for t in r["trades"]:
            if t.get("net_r") is None or t.get("entry_time") is None:
                continue
            rows.append((leg, sym, tf, str(t["entry_time"])[:19], str(t.get("direction")), float(t["net_r"])))
    df = pd.DataFrame(rows, columns=["family", "symbol", "tf", "entry_time", "direction", "net_r"])
    df["ts"] = pd.to_datetime(df.entry_time, utc=True, errors="coerce")
    return df.dropna(subset=["ts"])


def grade(trades: pd.DataFrame, btc: Optional[pd.Series] = None, seed: int = RR.SEED) -> Dict[str, Any]:
    S, N = RR.weekly_books(trades, "family")
    f = RR.features(S, N)
    test_weeks = [w for w in S.index if w >= pd.Timestamp(RR.TEST_START)]
    btc = btc if btc is not None else RR.btc_daily()
    raws = {"nostate": RR.state_raw(f, pd.Series("all", index=S.index)), "advol": RR.state_raw(f, RR.cells_advol(btc, list(S.index))),
            "hmm2": RR.state_raw(f, RR.cells_hmm2(btc, list(S.index))[0])}
    arms, verdicts = {}, {}
    for k, raw in raws.items():
        g = RR.grade_tilt(f, test_weeks, np.random.default_rng(seed), raw_all=raw)
        v, g["checks"] = RR.tilt_verdict(g, RULE)
        g["verdict"] = verdicts[k] = v
        arms[k] = g
    sums = {k: RR.tilt_week_sums(f, test_weeks, r) for k, r in raws.items()}
    decomp = {f"{k}_vs_nostate": RR.paired_delta(sums[k], sums["nostate"], np.random.default_rng(seed + 1)) for k in ("advol", "hmm2")}
    uv = "pass" if "pass" in verdicts.values() else ("fail" if all(v == "fail" for v in verdicts.values()) else "indeterminate")
    return {"arms": arms, "decomp_reported": decomp, "verdict": uv, "n_books": int(S.shape[1]), "n_test_weeks": len(test_weeks)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/rostered_replay")
    ap.add_argument("--work", default="")
    ap.add_argument("--legs", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(a.work) if a.work else out / "work"
    cfgs = rostered_legs()
    if a.legs:
        cfgs = {k: v for k, v in cfgs.items() if k in set(a.legs.split(","))}
    per = {}
    for leg, c in cfgs.items():
        per[leg] = replay_leg(leg, c["cfg"], work)
        print(json.dumps({"leg": leg, "state": per[leg]["state"], "n": per[leg].get("n")}), flush=True)
    tr = trades_frame(per, cfgs)
    tr = tr[(tr.ts >= pd.Timestamp(WINDOW[0], tz="UTC")) & (tr.ts < pd.Timestamp(WINDOW[1], tz="UTC"))]
    (out / "legs").mkdir(exist_ok=True)
    for leg, r in per.items():
        if r.get("state") == "measured":
            with open(out / "legs" / f"{leg}__trades.jsonl", "w", encoding="utf-8") as fh:
                for t in r["trades"]:
                    fh.write(json.dumps(t, default=str) + "\n")
    m = grade(tr) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
    legs_report = {k: {x: v[x] for x in v if x != "trades"} | {"book": cfgs[k]["book"], "harness": cfgs[k]["harness"]} for k, v in per.items()}
    pop = (f"{sum(1 for v in per.values() if v.get('state') == 'measured')} of {len(per)} rostered crypto legs ({'/'.join(FAMILIES)} harnesses) "
           f"replayed with DECLARED params over {WINDOW[0]}..{WINDOW[1]} ({len(tr)} trades, harness net_r full cost stack); books = leg x direction; "
           f"test weeks {RR.TEST_START}..{WINDOW[1]}")
    why = "; ".join(f"{k}: {g['verdict']} delta {g['delta']:+.4f} t {g['t']} share {g['random']['share_ge_arm']}" for k, g in (m.get("arms") or {}).items())
    summ = {"schema": "rostered_leg_replay/1", "unit": a.unit, "verdict": m["verdict"], "why": why, "rule": RULE, "population": pop,
            "window": WINDOW, "legs": legs_report, "measurement": m, "git_sha": RR._git_sha(), "elapsed_s": round(time.time() - t0), "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps({"verdict": m["verdict"], "read_state": "measured", "n": int(len(tr)), "note": why, "population": pop,
                                                  "rule": RULE, "data_window": {"start": WINDOW[0], "end": WINDOW[1], "legs": sorted(per)},
                                                  "measurement": m}, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": m["verdict"], "why": why}), flush=True)
    return 0


def _self_test() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    legs = rostered_legs()
    check("rostered legs found in the four families", len(legs) >= 10 and all(v["harness"] in FAMILIES for v in legs.values()))
    check("every rostered leg is a crypto symbol", all(str(v["cfg"]["symbols"][0]).endswith("USDT") for v in legs.values()))
    per = {"L1": {"state": "measured", "trades": [{"entry_time": "2023-01-02 00:00:00", "direction": "long", "net_r": 1.0}]},
           "L2": {"state": "harness_failed"}}
    tf = trades_frame(per, {"L1": {"cfg": {"symbols": ["BTCUSDT"], "timeframe": "1h"}}, "L2": {"cfg": {"symbols": ["X"]}}})
    check("trades frame keeps measured legs only, family = leg", list(tf.family) == ["L1"] and tf.net_r.iloc[0] == 1.0)
    # the grade runs the router on leg books: a synthetic BTC-trend-conditioned edge must be found by advol
    days = pd.date_range("2019-01-01", "2026-10-26", freq="1D", tz="UTC")
    rng = np.random.default_rng(5)
    regime = np.repeat(rng.choice([1.0, -1.0], size=len(days) // 60 + 1), 60)[:len(days)]
    btc = pd.Series(100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.01, len(days)))), index=days)
    syn = RR._synthetic(persistent=False)
    up = btc > btc.rolling(50).mean()
    st = up.reindex(syn.ts.dt.floor("D")).fillna(False).to_numpy()
    syn = syn.assign(net_r=syn.net_r + 0.3 * np.where(syn.direction == "long", 1.0, -1.0) * np.where(st, 1.0, -1.0))
    g = grade(syn, btc=btc)
    check("grade: advol finds a trend-conditioned edge on leg books", g["arms"]["advol"]["delta"] > 0.02 and g["arms"]["advol"]["random"]["share_ge_arm"] <= 0.05)
    check("grade: decomp reported", "advol_vs_nostate" in g["decomp_reported"])
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

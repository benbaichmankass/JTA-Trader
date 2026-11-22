#!/usr/bin/env python3
# wiring: research/queue/RQ-20261115-a474-02.yaml (run.command, via research-script-run.yml); --self-test in CI-free use
"""D5 (position aggregation, "Mastiff") AGG-HARNESS: rule arms A0..A4 on the census pairs -- Tier-1 research tooling.

RQ-20261114-82fd-02 (census) PASSED: on all 5 declared real-money (account, symbol) pairs 27-54% of Stage-0 trades open
while another leg on the pair is open. This replays the same solo streams (d5_concurrency_census: rule legs via
backtest_system solo arms on the full cost stack, ml_entry via its served-policy replay) through ONE shared risk budget
per pair (1.0 = one trade of risk, slice_allocation.yaml::symbol_budget_trades) under five allocation rules, and asks
whether any rule beats what the account does today by enough to justify a learned aggregator.

Arms (weight w in [0, 1] fixed at entry; a trade contributes w * net_r):
  A0  TODAY'S RULE, per the pair's accounts (config/accounts.yaml::position_model):
        slices   -- same-side: w = 1 - (sum of open weights), refused below MIN_W; an OPPOSITE open slice refuses the
                    entry (slice_allocation.yaml `opposite_slice_one_way_book`). Stops are not trailed in the replay,
                    so an open slice holds its full weight until exit (conservative for A0: live trailing frees budget).
        election -- one package per (account, symbol): w = 1 when nothing is open, else refused.
  A1  1/N netting -- every trade w = 1/N (N = legs on the pair), opposite sides allowed (a net-position venue book).
                    Netting fee savings are NOT credited (conservative for A1).
  A2  best-single -- only the leg with the highest net R on the OTHER window trades, w = 1 (cross-fit).
  A3  forecast combination -- static w_leg = max(0, mean net R per trade on the OTHER window) normalised over the
                    pair's legs (sum 1; equal 1/N when none is positive); every trade of the leg at that weight (cross-fit).
  A4  matched random -- each trade kept independently with p = (A0's total weight / n trades), w = 1; N_DRAWS draws.
                    The null: does a rule beat random exposure of the same size?

Metric per (arm, window): net R summed over the 5 pairs (capital = 1 budget per pair, so R per capital-day =
net R / (5 * days)), and max drawdown of the combined equity (pairs summed, ordered by exit time).
The verdict is the unit's registered rule (decide()). Writes <out>/arms.json + <out>/verdict.json.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

MIN_W = 0.05             # a slice below 5% of one trade's risk is not opened (rounding to nothing)
N_DRAWS = 1000
SEED = 20261115
DELTA_MIN_R = 5.0        # summed over the 5 pairs, per window (~1 R per pair-year)
DD_TOL = 1.25            # a winning arm's maxDD may be at most 1.25x A0's
LEARNED_ARMS = ("A1", "A2", "A3")

Trade = dict[str, Any]   # {entry_ts, exit_ts, side (+1/-1), net_r, leg}


# ── pure allocation ────────────────────────────────────────────────────────────────────────────────────────────
def allocate(trades: list[Trade], weight: Callable[[Trade, list[tuple[Trade, float]]], float]) -> list[tuple[Trade, float]]:
    """Walk trades by entry time; `weight(t, open)` returns w given the still-open (trade, w) list. Touching edges
    (exit == next entry) do not overlap. Returns [(trade, w)] for every trade (w may be 0)."""
    out: list[tuple[Trade, float]] = []
    open_: list[tuple[Trade, float]] = []
    for t in sorted(trades, key=lambda x: (x["entry_ts"], x["leg"])):
        open_ = [(o, w) for o, w in open_ if o["exit_ts"] > t["entry_ts"]]
        w = float(weight(t, open_))
        w = w if w >= MIN_W else 0.0
        out.append((t, w))
        if w > 0:
            open_.append((t, w))
    return out


def w_slices(t: Trade, open_: list[tuple[Trade, float]]) -> float:
    if any(o["side"] != t["side"] for o, _ in open_):
        return 0.0
    return max(0.0, 1.0 - sum(w for _, w in open_))


def w_election(t: Trade, open_: list[tuple[Trade, float]]) -> float:
    """One package per (account, symbol): the trade's own side does not matter, any open package refuses it."""
    return 0.0 if any(o is not t for o, _ in open_) else 1.0


def leg_stats(trades: list[Trade]) -> dict[str, dict[str, float]]:
    s: dict[str, dict[str, float]] = {}
    for t in trades:
        d = s.setdefault(t["leg"], {"n": 0, "net_r": 0.0})
        d["n"] += 1
        d["net_r"] += float(t["net_r"])
    for d in s.values():
        d["mean_r"] = d["net_r"] / d["n"] if d["n"] else 0.0
    return s


def static_weights(legs: Sequence[str], other: dict[str, dict[str, float]], arm: str) -> dict[str, float]:
    if arm == "A1":
        return {lg: 1.0 / len(legs) for lg in legs}
    if arm == "A2":
        best = max(legs, key=lambda lg: (other.get(lg, {}).get("net_r", float("-inf")), lg))
        return {lg: (1.0 if lg == best else 0.0) for lg in legs}
    pos = {lg: max(0.0, other.get(lg, {}).get("mean_r", 0.0)) for lg in legs}
    tot = sum(pos.values())
    return {lg: (pos[lg] / tot if tot > 0 else 1.0 / len(legs)) for lg in legs}


def curve(pnls: list[tuple[Any, float]]) -> dict[str, float]:
    eq = peak = dd = 0.0
    for _ts, p in sorted(pnls, key=lambda x: x[0]):
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"net_r": eq, "max_dd": dd}


def run_arms(pairs: dict[str, dict[str, Any]], seed: int = SEED, n_draws: int = N_DRAWS) -> dict[str, Any]:
    """pairs: key -> {model: slices|election, legs: [...], windows: {wn: [Trade]}}. Pure given the streams."""
    wins = sorted({w for p in pairs.values() for w in p["windows"]})
    res: dict[str, Any] = {"windows": {}, "pairs": {}}
    for wn in wins:
        other_wn = [w for w in wins if w != wn]
        agg: dict[str, list[tuple[Any, float]]] = {a: [] for a in ("A0",) + LEARNED_ARMS}
        a0_total_w, n_total, all_trades = 0.0, 0, []
        for key, p in pairs.items():
            tr = p["windows"][wn]
            other = leg_stats(p["windows"][other_wn[0]]) if other_wn else {}
            rule = w_slices if p["model"] == "slices" else w_election
            a0 = allocate(tr, rule)
            cell = {"model": p["model"], "n_trades": len(tr)}
            for arm, alloc in [("A0", a0)] + [
                    (arm, [(t, sw[t["leg"]]) for t in tr]) for arm, sw in
                    ((a, static_weights(p["legs"], other, a)) for a in LEARNED_ARMS)]:
                pn = [(t["exit_ts"], w * float(t["net_r"])) for t, w in alloc]
                agg[arm] += pn
                cell[arm] = {**curve(pn), "exposure": sum(w for _, w in alloc), "n_taken": sum(1 for _, w in alloc if w > 0)}
            a0_total_w += cell["A0"]["exposure"]
            n_total += len(tr)
            all_trades += tr
            res["pairs"].setdefault(key, {})[wn] = cell
        summ = {arm: curve(pn) for arm, pn in agg.items()}
        p_keep = a0_total_w / n_total if n_total else 0.0
        rng = random.Random(f"{seed}:{wn}")
        draws = sorted(sum(float(t["net_r"]) for t in all_trades if rng.random() < p_keep) for _ in range(n_draws))
        summ["A4"] = {"p_keep": p_keep, "p50": draws[len(draws) // 2] if draws else None,
                      "p95": draws[int(0.95 * (len(draws) - 1))] if draws else None, "n_draws": n_draws}
        res["windows"][wn] = summ
    return res


def decide(res: dict[str, Any]) -> dict[str, Any]:
    """The registered rule. PASS iff ONE arm X in {A1,A2,A3} in EVERY window: net R - A0 net R >= DELTA_MIN_R, net R
    > A4 p95, and max_dd <= DD_TOL * A0 max_dd (A0 max_dd floored at 1 R). FAIL iff no X beats A0 (delta > 0) in every
    window. INDETERMINATE otherwise."""
    W = res["windows"]
    passing, beating = [], []
    for x in LEARNED_ARMS:
        ok_all = beat_all = True
        for s in W.values():
            d = s[x]["net_r"] - s["A0"]["net_r"]
            beat_all &= d > 0
            ok_all &= (d >= DELTA_MIN_R and s["A4"]["p95"] is not None and s[x]["net_r"] > s["A4"]["p95"]
                       and s[x]["max_dd"] <= DD_TOL * max(1.0, s["A0"]["max_dd"]))
        if ok_all:
            passing.append(x)
        if beat_all:
            beating.append(x)
    if passing:
        return {"verdict": "pass", "arms": passing, "reason": f"{passing} beat today's rule (A0) by >= {DELTA_MIN_R} R, "
                "beat matched random (A4 p95) and kept maxDD within 1.25x in BOTH windows: build the learned aggregator "
                "arm against the best of these and propose the rule arm (Tier-3) on this record"}
    if not beating:
        return {"verdict": "fail", "arms": [], "reason": "no rule arm beats today's rule (A0) in both windows: D5 stays "
                "the slices/election rule; the learned aggregator is not built"}
    return {"verdict": "indeterminate", "arms": beating, "reason": f"{beating} beat A0 in both windows but miss the "
            f"materiality / random-null / drawdown bar"}


# ── windows (RESEARCH-FILL-20261122: the census windows were hard-coded; now a unit may register its own) ─────────
def resolve_windows(unit: dict[str, Any], cli: str | None = None, default: dict | None = None) -> dict[str, tuple[str, str]]:
    """Precedence: --windows 'a=2022-10-01:2023-10-01,b=2023-10-01:2024-10-01' > unit arms_on.windows {name: [lo, hi]}
    > the census default. Exactly TWO ordered, non-overlapping windows are required: A2/A3 are cross-fit (each window
    is scored on weights fitted on the OTHER), and decide() requires the rule to win in every window."""
    raw: dict[str, tuple[str, str]]
    if cli:
        raw = {}
        for part in cli.split(","):
            name, _, rng = part.partition("=")
            lo, _, hi = rng.partition(":")
            if not (name and lo and hi):
                raise ValueError(f"bad --windows entry {part!r}: want name=YYYY-MM-DD:YYYY-MM-DD")
            raw[name.strip()] = (lo.strip(), hi.strip())
    elif (unit.get("arms_on") or {}).get("windows"):
        raw = {str(k): (str(v[0]), str(v[1])) for k, v in unit["arms_on"]["windows"].items()}
    else:
        raw = dict(default or {})
    if len(raw) != 2:
        raise ValueError(f"exactly 2 windows required (cross-fit), got {len(raw)}: {sorted(raw)}")
    (n1, (a1, b1)), (n2, (a2, b2)) = sorted(raw.items(), key=lambda kv: kv[1][0])
    if not (a1 < b1 <= a2 < b2):
        raise ValueError(f"windows must be ordered and non-overlapping: {raw}")
    return dict(sorted(raw.items(), key=lambda kv: kv[1][0]))


# ── streams (re-uses the census replays) ───────────────────────────────────────────────────────────────────────
def build_pairs(unit: dict[str, Any], out: Path, cache: Path, windows: dict | None = None, fetch_start: str | None = None) -> dict[str, dict[str, Any]]:
    import d5_concurrency_census as C
    import pandas as pd
    from same_symbol_head_to_head import _load_bs, fetch_5m

    from src.research import risk_basis
    from src.research.run_costs import resolve_run_costs
    from src.config.accounts_loader import load_accounts_dict
    accounts = load_accounts_dict(REPO / "config" / "accounts.yaml")
    bs = _load_bs()
    live = risk_basis.live_risk(risk_basis.DEFAULT_REFERENCE_ACCOUNT)
    risk_pct = float(live.percent) if live.ok and live.percent is not None else 1.0
    spec = unit["arms_on"]["pairs"]
    ml = C._ml_entry_trades(cache) if any("ml_entry" in p["legs"] for p in spec) else {}
    candles: dict[str, Any] = {}
    pairs: dict[str, dict[str, Any]] = {}
    for p in spec:
        sym, legs = p["symbol"], list(p["legs"])
        models = {str((accounts.get(a) or {}).get("position_model") or "election") for a in p["accounts"]}
        if len(models) != 1:
            raise ValueError(f"{p['accounts']} disagree on position_model {models}: A0 is undefined")
        streams: dict[str, list[Trade]] = {}
        for leg in legs:
            if leg == "ml_entry":
                streams[leg] = ml.get(sym, [])
                continue
            if leg not in bs.ROSTER:
                raise ValueError(f"{leg} not in backtest_system ROSTER")
            if sym not in candles:
                path = fetch_5m(sym, out / "candles", fetch_start or C.FETCH_START)
                if not path:
                    raise ValueError(f"no 5m candles for {sym}")
                candles[sym] = bs._load_candles(str(path))
            streams[leg] = C._rule_leg_trades(bs, leg, sym, candles[sym], resolve_run_costs(sym), risk_pct)
        wins = {}
        for wn, (lo, hi) in (windows or C.WINDOWS).items():
            a, b = pd.Timestamp(lo, tz="UTC"), pd.Timestamp(hi, tz="UTC")
            wins[wn] = [{**t, "leg": lg} for lg, ts in streams.items() for t in ts if a <= t["entry_ts"] < b]
        pairs[f"{'+'.join(p['accounts'])}:{sym}"] = {"model": models.pop(), "legs": legs, "windows": wins}
    return pairs


def run(unit_path: Path, out: Path, cache: Path, windows_cli: str | None = None, fetch_start: str | None = None) -> int:
    import yaml
    out.mkdir(parents=True, exist_ok=True)
    unit = yaml.safe_load(unit_path.read_text())
    try:
        import d5_concurrency_census as C
        windows = resolve_windows(unit, windows_cli, C.WINDOWS)
        fetch_start = fetch_start or (unit.get("arms_on") or {}).get("fetch_start")
        pairs = build_pairs(unit, out, cache, windows, fetch_start)
        res = run_arms(pairs)
        v = decide(res)
        rec = {"unit": unit["id"], "window_ranges": windows, "fetch_start": fetch_start or C.FETCH_START, **res, "delta_min_r": DELTA_MIN_R, "dd_tol": DD_TOL, "min_w": MIN_W, **v}
        (out / "arms.json").write_text(json.dumps(rec, indent=1, default=str))
        n = sum(len(w) for p in pairs.values() for w in p["windows"].values())
        (out / "verdict.json").write_text(json.dumps({
            "verdict": v["verdict"], "read_state": "measured",
            "population": f"{len(pairs)} declared real-money (account, symbol) pairs x 2 windows, solo Stage-0 streams",
            "n": n, "measurement": rec, "note": v["reason"]}, default=str))
        for wn, s in res["windows"].items():
            print(wn, json.dumps({k: (round(v2["net_r"], 2), round(v2["max_dd"], 2)) if "net_r" in v2 else v2
                                  for k, v2 in s.items()}, default=str), flush=True)
        print("VERDICT", v, flush=True)
        return 0
    except Exception as exc:  # allow-silent: landed as read_state=producer_failed with the reason in verdict.json
        (out / "verdict.json").write_text(json.dumps({"verdict": "not_applicable", "read_state": "producer_failed",
                                                      "population": "declared pairs", "n": None,
                                                      "note": f"{type(exc).__name__}: {exc}"}))
        raise


def _self_test() -> None:
    import pandas as pd
    T0 = pd.Timestamp("2025-01-01", tz="UTC")
    h = lambda x: T0 + pd.Timedelta(hours=x)  # noqa: E731
    tr = lambda leg, a, b, s, r: {"leg": leg, "entry_ts": h(a), "exit_ts": h(b), "side": s, "net_r": r}  # noqa: E731
    x = [tr("a", 0, 10, 1, 1.0), tr("b", 5, 15, 1, 2.0), tr("c", 6, 8, -1, -1.0), tr("b", 10, 12, 1, 1.0)]
    sl = allocate(x, w_slices)
    assert [w for _, w in sl] == [1.0, 0.0, 0.0, 1.0], sl          # full first slice blocks; opposite refused
    el = allocate(x, w_election)
    assert [w for _, w in el] == [1.0, 0.0, 0.0, 1.0], el           # touching edge (exit 10 == entry 10) is free
    half = allocate([tr("a", 0, 10, 1, 1.0), tr("b", 1, 3, 1, 1.0)], lambda t, o: 0.5 if not o else w_slices(t, o))
    assert [w for _, w in half] == [0.5, 0.5], half
    assert allocate([tr("a", 0, 10, 1, 1.0), tr("b", 1, 3, 1, 1.0)], lambda t, o: 0.97 if not o else w_slices(t, o))[1][1] == 0.0
    st = {"a": {"net_r": 5.0, "mean_r": 0.5}, "b": {"net_r": -1.0, "mean_r": -0.1}}
    assert static_weights(["a", "b"], st, "A2") == {"a": 1.0, "b": 0.0}
    assert static_weights(["a", "b"], st, "A3") == {"a": 1.0, "b": 0.0}
    assert static_weights(["a", "b"], {}, "A3") == {"a": 0.5, "b": 0.5}
    assert curve([(1, 2.0), (2, -3.0), (3, 1.0)]) == {"net_r": 0.0, "max_dd": 3.0}
    pairs = {"p": {"model": "slices", "legs": ["a", "b"],
                   "windows": {"w1": [tr("a", 0, 10, 1, 1.0), tr("b", 5, 15, 1, 2.0)],
                               "w2": [tr("a", 0, 10, 1, -1.0), tr("b", 5, 15, 1, 3.0)]}}}
    r = run_arms(pairs, n_draws=50)
    assert r["windows"]["w1"]["A0"]["net_r"] == 1.0 and r["windows"]["w1"]["A1"]["net_r"] == 1.5, r
    assert r["windows"]["w2"]["A2"]["net_r"] == 3.0 and r["windows"]["w1"]["A2"]["net_r"] == 2.0, r  # cross-fit pick b
    mk = lambda a0, x, p95, dd=0.0: {"A0": {"net_r": a0, "max_dd": 1.0}, "A1": {"net_r": x, "max_dd": dd},  # noqa: E731
                                    "A2": {"net_r": a0 - 1, "max_dd": 0.0}, "A3": {"net_r": a0 - 1, "max_dd": 0.0},
                                    "A4": {"p95": p95}}
    assert decide({"windows": {"w1": mk(0, 6, 3), "w2": mk(0, 6, 3)}})["verdict"] == "pass"
    assert decide({"windows": {"w1": mk(0, 6, 7), "w2": mk(0, 6, 3)}})["verdict"] == "indeterminate"   # random null
    assert decide({"windows": {"w1": mk(0, 6, 3, dd=2.0), "w2": mk(0, 6, 3)}})["verdict"] == "indeterminate"  # DD
    assert decide({"windows": {"w1": mk(0, 6, 3), "w2": mk(0, -1, 3)}})["verdict"] == "fail"
    print("self-test ok")


def _self_test_windows() -> None:
    dflt = {"w1": ("2024-10-01", "2025-10-01"), "w2": ("2025-10-01", "2026-10-01")}
    assert resolve_windows({}, None, dflt) == dflt
    u = {"arms_on": {"windows": {"late": ["2023-10-01", "2024-10-01"], "early": ["2022-10-01", "2023-10-01"]}}}
    r = resolve_windows(u, None, dflt)
    assert list(r) == ["early", "late"] and r["early"] == ("2022-10-01", "2023-10-01"), r
    assert resolve_windows(u, "a=2021-01-01:2022-01-01,b=2022-01-01:2023-01-01", dflt)["a"][0] == "2021-01-01"
    for bad in ("a=2021-01-01:2022-01-01", "a=2021-01-01:2022-06-01,b=2022-01-01:2023-01-01", "a=2021:", "x"):
        try:
            resolve_windows({}, bad, dflt)
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass
    print("windows self-test OK")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", default="RQ-20261115-a474-02")
    ap.add_argument("--out", default="/tmp/d5_arms_out")
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--windows", default=None, help="name=lo:hi,name=lo:hi (exactly two); default unit arms_on.windows, else census")
    ap.add_argument("--fetch-start", default=None, help="5m candle warm-up start; default unit arms_on.fetch_start, else census")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        _self_test_windows()
        return 0
    p = Path(a.unit)
    if not p.exists():
        p = REPO / "research" / "queue" / f"{a.unit}.yaml"
    return run(p, Path(a.out), Path(a.cache), a.windows, a.fetch_start)


if __name__ == "__main__":
    sys.exit(main())

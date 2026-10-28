#!/usr/bin/env python3
# wiring: manual-only - run by lane LTR-TIGHTEN-OPTIMIZE (and any re-run of its evidence record); no schedule consumes it.
"""LTR-TIGHTEN-OPTIMIZE -- which stop-tightens lose, and is there a tighten RULE that beats hold-to-bracket out of sample?

Operator 2026-10-28 ~19:45Z (relayed by the manager): on stop-tightening, "Investigate further and optimize before
turning off". Design, registration and results: docs/research/ltr-tighten-optimize-2026-10-28.md.

COMPOSES, never rewrites: scripts/research/desk_lifecycle_driver.py (the bar-by-bar replay `run`, the check-in
policies, the full cost stack via src/runtime/execution_costs.py, the weekly-cluster bootstrap) over the DESK-LIFECYCLE-S0
full-run evidence record (comms/research/desk_lifecycle/full-c4e/, PR #20967). Tier 1 research tooling: reads candles and
committed evidence, writes only under --out.

MODES
-----
  slices  --lifecycle DIR --out DIR   Q1: every Claude tighten_sl of the full run, re-priced by ablation (that one answer
                                      replaced by hold), enriched with its state at the decision bar, sliced; the
                                      re-priced value must equal the committed labels.jsonl value (asserted).
  rules   --lifecycle DIR --out DIR --split train|test|fresh [--registration F]
                                      Q2: the registered rule grid replayed on every entry of the corpus (no judging);
                                      `train` selects ONE rule; `test` / `fresh` grade the selected rule and refuse to
                                      run unless --registration names the committed registration (its sha is recorded).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.research import desk_gen_replay_driver as g
from scripts.research import desk_lifecycle_driver as dl

# ----------------------------------------------------------------------------- registered numbers (see the doc § 2)
SEED = 20261028
SPLIT_EPOCH = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())    # train: entry bar < this; test: >= this
FRESH_START = datetime(2026, 9, 7, tzinfo=timezone.utc)                     # after the corpus's last week (2026-W36)
FRESH_END = datetime(2026, 10, 24, tzinfo=timezone.utc)                     # last entry bar; leaves 48 bars to close
FRESH_N_PER_SYMBOL = 70
FRESH_MIN_GAP = 4
STOP_SLIP_SENS_R = 0.05                                                     # sensitivity: extra R per moved-stop exit
VOL_LOOKBACK = 720                                                          # 30 days of 1h bars for the ATR% rank
TREND_N = 48

# ----------------------------------------------------------------------------- slices (Q1)
HELD = ((4, "1-3"), (12, "4-11"), (24, "12-23"), (10 ** 9, "24-47"))
NOWR = ((0.0, "<0"), (0.5, "0..0.5"), (1.0, "0.5..1"), (2.0, "1..2"), (10 ** 9, ">=2"))
DIST_R = ((0.25, "<0.25R"), (0.5, "0.25..0.5R"), (1.0, "0.5..1R"), (10 ** 9, ">=1R"))
DIST_ATR = ((1.0, "<1ATR"), (2.0, "1..2ATR"), (3.0, "2..3ATR"), (10 ** 9, ">=3ATR"))
LEVEL = ((-1e-9, "below_BE"), (1e-9, "at_BE"), (0.5, "BE..+0.5R"), (10 ** 9, ">=+0.5R"))
GIVEBACK = ((0.25, "<0.25R"), (0.5, "0.25..0.5R"), (1.0, "0.5..1R"), (10 ** 9, ">=1R"))
TRIGGER = {"clock": "time", "mom_against": "momentum_flip_against", "mom_with": "momentum_flip_with",
           "break_down_with": "structure_break_with", "break_up_with": "structure_break_with",
           "break_up_against": "structure_break_against", "break_down_against": "structure_break_against",
           "r-0.5": "adverse_-0.5R", "atr_up": "vol_change", "atr_down": "vol_change", "atr_norm": "vol_change"}


def _b(x: float, edges: Sequence[tuple[float, str]]) -> str:
    for ed, lb in edges:
        if x < ed:
            return lb
    return edges[-1][1]


def regime(s: g.Series, side: float, j: int) -> dict[str, Any]:
    """Point-in-time regime at bar j (bars <= j only): vol = ATR% rank in the trailing 30 days (tercile);
    trend = the 48-bar close change, signed by the trade's side."""
    lo = max(0, j - VOL_LOOKBACK)
    pct = s.atr[lo:j + 1] / s.c[lo:j + 1]
    pct = pct[np.isfinite(pct)]
    rank = float((pct <= pct[-1]).mean()) if len(pct) > 20 else float("nan")
    vol = "low" if rank < 1 / 3 else ("mid" if rank < 2 / 3 else "high") if np.isfinite(rank) else "unknown"
    tr = side * (s.c[j] - s.c[max(0, j - TREND_N)]) / (s.atr[j] * np.sqrt(TREND_N)) if s.atr[j] > 0 else float("nan")
    trend = "unknown" if not np.isfinite(tr) else ("with" if tr > 0.5 else ("against" if tr < -0.5 else "flat"))
    return {"vol_rank": rank, "vol": vol, "trend_z": float(tr), "trend": trend}


def _recording(dec: Callable, log: dict[int, tuple[int, dict]]) -> Callable:
    def d(k, j, st):
        log[k] = (j, dict(st))
        return dec(k, j, st)
    return d


def load(lifecycle: Path, candles: str | None, fetch: bool):
    a = argparse.Namespace(candles_dir=candles, fetch=fetch)
    mkt, missing, _cls, src = dl._prepare_market(a)
    if missing:
        raise SystemExit(f"candles missing for {missing}")
    entries = dl.read_entries(lifecycle / "entries.jsonl")
    dec = dl.read_decisions(lifecycle, lifecycle / "decisions.jsonl")
    return mkt, entries, dec, src


def cmd_slices(a: argparse.Namespace) -> int:
    lc, out = Path(a.lifecycle), Path(a.out)
    mkt, entries, dec, src = load(lc, a.candles_dir, a.fetch)
    pol = dl.POLICIES["C4E"]
    committed = {}
    for ln in (lc / "labels.jsonl").read_text().splitlines():
        r = json.loads(ln)
        if r["arm"] == "claude" and r["action"] == "tighten_sl":
            committed[(r["pair_id"], r["src"], r["k"])] = r["value"]
    rows: list[dict] = []
    for e in entries:
        s = mkt[e.symbol]
        log: dict[int, tuple[int, dict]] = {}
        res, p = dl.run(s, e, _recording(dl._decider(e.entry_id, dec), log), pol())
        if p is not None or res.state != "filled":
            continue
        a0 = float(s.atr[log[0][0]]) if log else float("nan")
        for c in res.checkins:
            if c["action"] != "tighten_sl":
                continue
            j, st = log[c["k"]]
            alt = dl.run(s, e, dl._ablate(dec, e.entry_id, c["k"], {"action": "hold"}), pol())[0]
            if alt.state != "filled":
                continue
            v = res.net_r - alt.net_r
            dist_r = st["close_r"] - c["level_r"]
            rows.append({"pair_id": e.pair_id, "src": e.source, "symbol": e.symbol, "week": e.week, "k": c["k"],
                         "value": v, "value_slip": v - (STOP_SLIP_SENS_R if res.moved_stop_exit and not alt.moved_stop_exit else 0.0),
                         "bars_held": st["bars_held"], "now_r": st["close_r"], "mfe_r": st["mfe_r"],
                         "giveback_r": st["mfe_r"] - st["close_r"], "old_stop_r": st["stop_r"], "level_r": c["level_r"],
                         "move_r": c["level_r"] - st["stop_r"], "dist_r": dist_r,
                         "dist_atr": dist_r * st["risk_px"] / st["atr_px"] if st["atr_px"] > 0 else float("nan"),
                         "atr_ratio": st["atr_px"] / a0 if a0 > 0 else float("nan"), "tags": c["tags"],
                         "first_tighten": not any(x.startswith("tighten_sl") for x in st["prior_actions"]),
                         "exit_reason": res.exit_reason, **regime(s, e.side, j)})
    keyed = {(r["pair_id"], r["src"], r["k"]): r["value"] for r in rows}
    mism = [k for k in committed if k not in keyed or abs(committed[k] - keyed[k]) > 1e-9]
    extra = [k for k in keyed if k not in committed]
    repro = {"committed": len(committed), "recomputed": len(keyed), "mismatched_or_missing": len(mism), "extra": len(extra)}
    if mism or extra:
        print(json.dumps({"error": "re-priced tighten values differ from the committed labels", **repro,
                          "examples": [list(k) for k in (mism + extra)[:5]]}))
        return 2
    cells: dict[str, list[dict]] = {}

    def add(key: str, r: dict) -> None:
        cells.setdefault(key, []).append(r)
    for r in rows:
        add("all", r)
        add(f"src:{r['src']}", r)
        add(f"now_r:{_b(r['now_r'], NOWR)}", r)
        add(f"new_stop_dist_R:{_b(r['dist_r'], DIST_R)}", r)
        add(f"new_stop_dist_ATR:{_b(r['dist_atr'], DIST_ATR)}", r)
        add(f"new_stop_level:{_b(r['level_r'], LEVEL)}", r)
        add(f"giveback:{_b(r['giveback_r'], GIVEBACK)}", r)
        add(f"held:{_b(r['bars_held'], HELD)}", r)
        add(f"vol:{r['vol']}", r)
        add(f"trend:{r['trend']}", r)
        add(f"symbol:{r['symbol']}", r)
        add(f"first_tighten:{r['first_tighten']}", r)
        for t in sorted({TRIGGER.get(t, t if t.startswith('r+') else 'other') for t in r["tags"]}):
            add(f"trigger:{t}", r)
        add(f"now_r x dist_ATR:{_b(r['now_r'], NOWR)} | {_b(r['dist_atr'], DIST_ATR)}", r)
        add(f"now_r x vol:{_b(r['now_r'], NOWR)} | {r['vol']}", r)
        add(f"dist_ATR x trend:{_b(r['dist_atr'], DIST_ATR)} | {r['trend']}", r)
    table = {}
    for k, vs in sorted(cells.items()):
        st = dl.cluster_mean_ci([v["value"] for v in vs], [v["week"] for v in vs], seed=SEED, draws=4000)
        sl = dl.cluster_mean_ci([v["value_slip"] for v in vs], [v["week"] for v in vs], seed=SEED, draws=4000)
        table[k] = {"n": st["n"], "weeks": st["weeks"], "mean": st["mean"], "ci95": st["ci95"],
                    "hit_pos": float(np.mean([v["value"] > 1e-9 for v in vs])),
                    "hit_zero": float(np.mean([abs(v["value"]) <= 1e-9 for v in vs])),
                    "mean_with_stop_slip": sl["mean"], "ci95_with_stop_slip": sl["ci95"]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "tighten_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    doc = {"what": "Q1 slices of Claude's tighten_sl actions, DESK-LIFECYCLE-S0 full run (C4E), value = managed net R - "
                   "the same trade with that one tighten replaced by hold (net of the full cost stack)",
           "population": f"{len(rows)} tighten_sl check-ins over the walked trades of {lc}",
           "reproduction": repro, "candles": src, "cluster": "ISO week of the pair (weekly-cluster bootstrap, 4000 draws)",
           "stop_slip_sensitivity_r": STOP_SLIP_SENS_R, "cells": table,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "slices.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({"rows": len(rows), "reproduction": repro, "all": table["all"]}))
    return 0


# ----------------------------------------------------------------------------- rules (Q2)
def _tighten(x: float, st: dict) -> dict:
    return {"action": "tighten_sl", "level_r": x} if x > st["stop_r"] + 1e-9 and x <= st["close_r"] - dl.MIN_GAP_R \
        else {"action": "hold"}


def make_rule(fam: str, p: dict[str, float], s: g.Series, side: float) -> Callable:
    """One registered rule. Evaluated at every bar close (policy C1), effective from the next bar (the engine's rule)."""
    def d(k, j, st):  # inert: k -- the shared Decider signature
        if fam == "hold":
            return {"action": "hold"}
        if fam == "breakeven":                       # stop to +off R once the close reaches X R
            return _tighten(p["off"], st) if st["close_r"] >= p["X"] else {"action": "hold"}
        if fam == "atr_trail":                       # chandelier: MFE - k ATR, armed once MFE reaches X R
            return _tighten(st["mfe_r"] - p["k"] * st["atr_px"] / st["risk_px"], st) if st["mfe_r"] >= p["X"] \
                else {"action": "hold"}
        if fam == "structure":                       # the n-bar low (long) / high (short), armed once MFE reaches X R
            if st["mfe_r"] < p["X"]:
                return {"action": "hold"}
            n = int(p["n"])
            lo = max(0, j - n + 1)
            lvl = s.l[lo:j + 1].min() if side > 0 else s.h[lo:j + 1].max()
            fill = st["ext_px"] - side * st["mfe_r"] * st["risk_px"]
            return _tighten(side * (lvl - fill) / st["risk_px"], st)
        if fam == "giveback":                        # keep (1 - f) of MFE, armed once MFE reaches X R
            return _tighten(st["mfe_r"] * (1 - p["f"]), st) if st["mfe_r"] >= p["X"] else {"action": "hold"}
        if fam == "losscut":                         # close at a close <= Y R, after T bars held
            return {"action": "close"} if st["close_r"] <= p["Y"] and st["bars_held"] >= p["T"] else {"action": "hold"}
        raise KeyError(fam)
    return d


def grid() -> list[tuple[str, dict[str, float]]]:
    G: list[tuple[str, dict[str, float]]] = [("hold", {})]
    G += [("breakeven", {"X": X, "off": off}) for X in (0.5, 1.0, 1.5, 2.0) for off in (0.0, 0.1)]
    G += [("atr_trail", {"X": X, "k": k}) for X in (0.0, 0.5, 1.0, 1.5, 2.0) for k in (1.5, 2.0, 3.0, 4.0, 5.0)]
    G += [("structure", {"X": X, "n": n}) for X in (0.5, 1.0, 1.5) for n in (6, 12, 24)]
    G += [("giveback", {"X": X, "f": f}) for X in (1.0, 1.5, 2.0) for f in (0.3, 0.5, 0.7)]
    G += [("losscut", {"Y": Y, "T": T}) for Y in (-0.5, -0.6, -0.75) for T in (1, 4, 8)]
    return G


def rule_name(fam: str, p: dict[str, float]) -> str:
    return fam + ("" if not p else "(" + ",".join(f"{k}={v:g}" for k, v in p.items()) + ")")


def fresh_entries(mkt: dict[str, g.Series], corpus: list[dl.Entry]) -> list[dl.Entry]:
    """Random market entries in the FRESH window (after the corpus): geometry (side, stop in ATR, TP in R) drawn from the
    corpus's own random partners, at seeded cutoffs >= FRESH_MIN_GAP bars apart per symbol. Nothing judged."""
    rng = np.random.default_rng(SEED)
    geo = []
    for e in corpus:
        if e.source != "random":
            continue
        s = mkt[e.symbol]
        a = float(s.atr[e.i])
        if a > 0:
            geo.append((e.side, abs(e.level - e.stop) / a, abs(e.tp - e.level) / abs(e.level - e.stop)))
    t0, t1 = int(FRESH_START.timestamp()), int(FRESH_END.timestamp())
    out: list[dl.Entry] = []
    for sym in sorted(mkt):
        s = mkt[sym]
        idx = [i for i in range(len(s.t)) if t0 <= s.t[i] <= t1 and np.isfinite(s.atr[i]) and s.atr[i] > 0]
        pick: list[int] = []
        for i in rng.permutation(idx):
            if all(abs(int(i) - q) >= FRESH_MIN_GAP for q in pick):
                pick.append(int(i))
            if len(pick) >= FRESH_N_PER_SYMBOL:
                break
        for n, i in enumerate(sorted(pick)):
            side, sl_atr, tp_r = geo[int(rng.integers(len(geo)))]
            px, a = float(s.c[i]), float(s.atr[i])
            stop = px - side * sl_atr * a
            tp = px + side * tp_r * sl_atr * a
            wk = g.iso_week(int(s.t[i]))
            out.append(dl.Entry(f"F-{sym}-{n}", "fresh", f"F-{sym}-{n}", sym, i, side, "market", px, stop, tp, 1, 48, 5,
                                wk, wk))
    return out


def fresh_manifest(mkt: dict[str, g.Series]) -> list[str]:
    """candle_manifest covers only the S0 replay window; this names the FRESH window's bars the same way."""
    lo, hi = int(FRESH_START.timestamp()), int(FRESH_END.timestamp()) + 3 * 86400
    out = []
    for sym, s in sorted(mkt.items()):
        m = (s.t >= lo) & (s.t <= hi)
        h = hashlib.sha256()
        for arr in (s.t[m], s.o[m], s.h[m], s.l[m], s.c[m]):
            h.update(np.ascontiguousarray(arr).tobytes())
        out.append(f"binance_vision:{sym}:1h:rows={int(m.sum())}:first={datetime.fromtimestamp(int(s.t[m][0]), tz=timezone.utc):%Y-%m-%dT%H}"
                   f":last={datetime.fromtimestamp(int(s.t[m][-1]), tz=timezone.utc):%Y-%m-%dT%H}:sha256={h.hexdigest()[:16]}")
    return out


def evaluate_rules(mkt, entries, rules) -> dict[str, dict[str, dict]]:
    """{rule: {entry_id: {dR, dR_slip, week, src}}} -- dR = rule net R - HOLD net R on the same entry."""
    pol = dl.POLICIES["C1"]
    hold = {}
    for e in entries:
        r = dl.run(mkt[e.symbol], e)[0]
        if r.state == "filled":
            hold[e.entry_id] = r
    out: dict[str, dict[str, dict]] = {}
    for fam, p in rules:
        nm = rule_name(fam, p)
        out[nm] = {}
        for e in entries:
            if e.entry_id not in hold:
                continue
            r = dl.run(mkt[e.symbol], e, make_rule(fam, p, mkt[e.symbol], e.side), pol())[0]
            d = r.net_r - hold[e.entry_id].net_r
            out[nm][e.entry_id] = {"dR": d, "dR_slip": d - (STOP_SLIP_SENS_R if r.moved_stop_exit else 0.0),
                                   "week": e.week, "src": e.source, "net": r.net_r, "hold": hold[e.entry_id].net_r}
    return out


def _ci975(vals: Sequence[float], weeks: Sequence[str]) -> list[float | None]:
    """Weekly-cluster bootstrap 97.5 % two-sided interval (the Holm first step for a family of two)."""
    if not len(vals):
        return [None, None]
    wk = sorted(set(weeks))
    ix = {w: n for n, w in enumerate(wk)}
    s_w, n_w = np.zeros(len(wk)), np.zeros(len(wk))
    for x, w in zip(vals, weeks):
        s_w[ix[w]] += x
        n_w[ix[w]] += 1
    b = np.random.default_rng(SEED).integers(0, len(wk), size=(10_000, len(wk)))
    m = s_w[b].sum(axis=1) / n_w[b].sum(axis=1)
    return [float(np.percentile(m, 1.25)), float(np.percentile(m, 98.75))]


def verdict(test: dict, fresh: dict | None, ci_key: str) -> str:
    """The registered rule (doc § 2.4): PASS = test CI lower > 0 AND fresh mean > 0; FAIL = test CI upper < 0."""
    lo, hi = test[ci_key]
    if lo is not None and lo > 0 and fresh is not None and fresh["mean_dR"] is not None and fresh["mean_dR"] > 0:
        return "pass"
    if hi is not None and hi < 0:
        return "fail"
    return "indeterminate"


def _summ(rows: dict[str, dict], key: str = "dR") -> dict:
    v = list(rows.values())
    st = dl.cluster_mean_ci([x[key] for x in v], [x["week"] for x in v], seed=SEED, draws=10_000)
    nets = np.array([x["net"] for x in v])
    holds = np.array([x["hold"] for x in v])
    return {"n": st["n"], "weeks": st["weeks"], "mean_dR": st["mean"], "ci95": st["ci95"],
            "ci975": _ci975([x[key] for x in v], [x["week"] for x in v]),
            "net_r_rule": float(nets.mean()) if len(v) else None, "net_r_hold": float(holds.mean()) if len(v) else None,
            "maxdd_rule": _maxdd(nets), "maxdd_hold": _maxdd(holds)}


def _maxdd(x: np.ndarray) -> float | None:
    if not len(x):
        return None
    eq = np.cumsum(x)
    return float((np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq).max())


def cmd_rules(a: argparse.Namespace) -> int:
    lc, out = Path(a.lifecycle), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mkt, corpus, _dec, src = load(lc, a.candles_dir, a.fetch)
    reg_sha = None
    if a.split != "train":
        if not a.registration or not Path(a.registration).exists():
            print(json.dumps({"error": "test/fresh refuse to run without the committed registration (--registration)"}))
            return 2
        reg_sha = hashlib.sha256(Path(a.registration).read_bytes()).hexdigest()
        sel = json.loads((out / "train.json").read_text())["selected"]
    if a.split == "fresh":
        ents = fresh_entries(mkt, corpus)
    else:
        ents = [e for e in corpus if (mkt[e.symbol].t[e.i] < SPLIT_EPOCH) == (a.split == "train")]
    if a.split == "train":
        res = evaluate_rules(mkt, ents, grid())
        table = {nm: _summ(rows) for nm, rows in res.items()}
        best = max(table, key=lambda k: (round(table[k]["mean_dR"], 6), -len(k)))
        doc = {"split": "train", "population": f"{len(next(iter(res.values())))} filled entries (claude + random) of "
                                                 f"{lc} with entry bar < {datetime.fromtimestamp(SPLIT_EPOCH, tz=timezone.utc).date()}",
               "grid_size": len(table), "selected": best, "selected_stats": table[best], "table": table,
               "candles": src, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (out / "train.json").write_text(json.dumps(doc, indent=1))
        print(json.dumps({"selected": best, **table[best], "hold_rank": sorted(table, key=lambda k: -table[k]["mean_dR"]).index("hold") + 1}))
        return 0
    fam, p = next((f, q) for f, q in grid() if rule_name(f, q) == sel)
    secondary = ("losscut", {"Y": -0.5, "T": 1})
    rules = [(fam, p)] + ([secondary] if rule_name(*secondary) != sel else [])
    if a.all_grid:
        rules += [r for r in grid() if rule_name(*r) not in {rule_name(*x) for x in rules}]
    res = evaluate_rules(mkt, ents, rules)
    table = {}
    for nm, rows in res.items():
        t = _summ(rows)
        t["with_stop_slip"] = _summ(rows, "dR_slip")["ci95"]
        t["by_src"] = {sv: _summ({k: v for k, v in rows.items() if v["src"] == sv}) for sv in sorted({v["src"] for v in rows.values()})}
        table[nm] = t
    doc = {"split": a.split, "registration_sha256": reg_sha, "selected": sel, "secondary": rule_name(*secondary),
           "population": f"{len(next(iter(res.values())))} filled entries ({a.split})", "table": table,
           "graded": [sel, rule_name(*secondary)], "candles": src,
           **({"candles_fresh_window": fresh_manifest(mkt)} if a.split == "fresh" else {}),
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if a.split == "fresh" and not a.all_grid and (out / "test.json").exists():
        tt = json.loads((out / "test.json").read_text())["table"]
        doc["verdicts"] = {nm: verdict(tt[nm], table.get(nm), "ci975") for nm in doc["graded"] if nm in tt}
        doc["verdict_rule"] = "per graded rule (Bonferroni over 2): PASS = test 97.5% weekly-cluster CI lower > 0 AND fresh mean > 0; FAIL = test 97.5% CI upper < 0; else indeterminate. HOLD selected => the primary reads 'no_rule'."
        if sel == "hold":
            doc["verdicts"][sel] = "no_rule"
    (out / f"{a.split}{'-allgrid' if a.all_grid else ''}.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({"verdicts": doc.get("verdicts"), **{k: {x: table[k][x] for x in ("n", "mean_dR", "ci95", "ci975", "with_stop_slip")} for k in doc["graded"] if k in table}}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for m in ("slices", "rules"):
        s = sub.add_parser(m)
        s.add_argument("--lifecycle", default=str(REPO / "comms/research/desk_lifecycle/full-c4e"))
        s.add_argument("--out", default=str(REPO / "comms/research/ltr_tighten_optimize"))
        s.add_argument("--candles-dir", default=None)
        s.add_argument("--fetch", action="store_true")
        if m == "rules":
            s.add_argument("--split", choices=("train", "test", "fresh"), required=True)
            s.add_argument("--registration", default=None)
            s.add_argument("--all-grid", action="store_true", help="also report (not grade) every grid rule")
    a = ap.parse_args(argv)
    return {"slices": cmd_slices, "rules": cmd_rules}[a.mode](a)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# wiring: research/queue units via research-script-run.yml (TM-BENCH runner unit; RQ-20261029-7294-01/-02 once unblocked)
"""TM-BENCH: the one trade-management bench (checklist row TM-BENCH; docs/plans/ML-PROGRAMME-2026-10-28.md § 4.2, § 5 row 1).

One frozen corpus, one fold file, one cost stack, one action enum, one replay engine, one labeler, one scorer. Every
policy -- a rule, a model, the desk -- is scored on the same states and reported against the same baselines.

    python3 scripts/research/tm_bench.py selfcheck
    python3 scripts/research/tm_bench.py score --test-corpus v1 --rule reproduce --out <dir>
    python3 scripts/research/tm_bench.py score --test-corpus v1 --train-corpus <dir> --rule s_offline --out <dir>
    python3 scripts/research/tm_bench.py transfer --test-corpus v1 --train-corpus <dir> --fractions 0,0.25,1,4 --out <dir>
    python3 scripts/research/tm_bench.py corpus --test-corpus v1 --out <dir>          # freeze + hash, nothing scored

ONE ENGINE (row note, binding: "the labeler imports the cf core ... never rebuilt"). Neither CF-B0-ENGINE-LIFT's
`cf_core` nor the ML-EXIT-ACTIONGRID-LABELS replay exists on main (both rows `queued`, 2026-10-30). The narrowest
existing interface is the pure replay in `counterfactual_grader.simulate` + `net_of` (the grader CF-B0 will lift), so
this module imports exactly those two and nothing else from the engine. When `cf_core` lands, `ENGINE_*` below is the
one line to repoint. Corpus, events and the census oracle are imported from `first_passage_paths` (the 09a6-01
construction), the causal matched-random draw and the trade-cluster CI from `intervention_controls`.

THE CONSTRUCTION
  * CORPUS. Harness `--emit-paths` trades (stop and target IN FORCE per bar, each leg's own trail / stale / TP
    revision), joined and parity-checked by `first_passage_paths.build_trades`. `corpus_id` = sha256 over the sorted
    trade_keys, the leg list and the source string. Corpus `v1` = the six money legs, window 2020-07-01 ..
    2026-10-15 23:59 (the RQ-20261024-09a6-01 population: 2,627 trades, the 0.756 R/trade oracle).
  * R-SPACE ADAPTER. Every trade is replayed in R units through the engine as a long: price = q + r with
    q = entry / risk, r_dist = 1, so the engine's bps cost stack lands in R exactly as on the real notional.
    Bars: open = o_r, high = fav_r, low = adv_r, close = c_r (the exit bar closes at the harness exit_r).
    The harness fills a stop/TP AT A TOUCH (`lo <= trail`, backtest_trend.py); the engine needs price to trade
    THROUGH a level, so each bar's extremes are widened by 1e-9 R (touch == fill, the harness convention).
  * B0 REPLAY. The leg's own management is replayed as timed actions: at each bar, set_stop to that row's
    `stop_r` (tighten-only in the engine) and set_tp to its `target_r`. `engine_fidelity` reports how often the
    replayed B0 gross R equals the harness exit_r within 0.01 R. Every delta is quoted against the REPLAYED B0, so
    an engine bias common to both arms cancels (the grader's `delta_vs_replayed_actual`).
  * ACTION ENUM (closed; ML-PROGRAMME § 1.1). hold · close · partial_close{0.5} · tighten_sl{be, atr1, atr2} ·
    tp_pull_in{+0.5R, +1R}. A decision at state t (after bar t's close) acts from bar t+1's open. Invalid
    (a stop not tighter than the in-force one or at/above the market; a TP not inside the in-force one) is
    scored HOLD and counted. Never widens a stop, never sizes up.
  * ACTION-VALUE LABEL  label[a][t] = net R(B0 + a at t) - net R(B0), both replayed, full cost stack (fee + exit
    slippage unless a TP rests + funding pro-rata). Past features / future label by construction.
  * POLICY (v1): the FIRST non-hold action at a check-in state is applied; the leg's own management continues
    after it. Multi-action sequences are TM-LEARNERS-2's (LSM backward induction). A policy file is JSONL
    `{state_id, action}` with state_id = `<trade_key>@<bar_offset>`.
  * ORACLE. (a) `census_best_close_saving_r_per_trade` -- imported verbatim from `first_passage_paths.census`
    (the 0.756 definition: max(0, best pre-exit close - c_exit - exit_r)); (b) `action_value_ceiling` = per trade
    max(0, max over labelled (t, a)) -- >= every v1 policy arm by construction, checked per trade in selfcheck.
  * FOLDS. 6 calendar folds by entry over the TEST corpus. A train trade (any corpus, ANY SYMBOL) is purged if
    [entry, exit + embargo] overlaps the test fold window, embargo = its leg's max hold in that corpus
    (cross-symbol purge, ml-data-rate-path § 1 row A). Train trades whose trade_key is in the test corpus are
    dropped (de-dup). The fold file is written beside every result.
  * CHECK-IN POLICY (§ 1.4, binding). clock {every bar, every 4 bars, none} x triggers {none, all}. Triggers:
    R crossings (-1, -0.5, +0.5, +1, +2 R), ATR(14) vs its value at bar 1 crossing 1.5 / 0.67 (the emit carries
    ATR(14) only, not ATR(100): stated proxy), 3-bar momentum sign flip, time in trade = the leg's median winning
    duration on the TRAIN folds. Level/structure break: not in the emit -> `not_available`. every_bar+triggers
    is every_bar (every state is already a check-in), so the grid has 4 distinct cells.
  * BASELINES. B0 hold (dR = 0 exactly). B1 best static rule per leg, leave-fold-out (BE at +1R, lock +1R at
    +2R, the ladder, chandelier k in {2,3} x ATR(14) off the running extreme, channel exit N in {10, 20}) --
    replayed as continuous rules through the engine. B2 distance-only logit (room to stop / target only) closing
    at the first check-in with p >= p*, p* chosen on train folds. B3 the desk: `--desk-policy` file, else
    `not_available`. B4 matched random per arm: `intervention_controls.matched_random_intervention`, mode causal
    (same count and type of actions, one fixed horizon -- never the trade's own length). B5 re-score exit: the
    entry model does not replay point-in-time from the emit -> `not_available`. B6 vol-rescale: partial close of
    1 - ATR0/ATR_t at the first check-in where ATR_t / ATR0 >= 1.5 (reductive only).
  * LEARNERS. `lgbm_action_value`: one LightGBM regressor per action on label[a] (fixed hyper-parameters below,
    never tuned on a test fold); acts on argmax prediction if > ACT_MARGIN_R. `logit_action_value`: one
    L2 logit per action on 1[label > 0] (`first_passage.Logit`); acts on argmax p if p > LOGIT_ACT_P. Features =
    `first_passage_paths` R1 + leg fixed effects (state at the bar close; nothing later).
  * SCORER. Per arm: paired dR vs B0 per trade, trade bootstrap 95% CI, per-fold sign, one-sided bootstrap p,
    Holm across each family, B4 margin and P(random >= arm), max drawdown vs B0 per leg, net R per capital-day
    (`capital_efficiency`, single home), action rate, acted vs held split, strata (leg family x vol tercile at
    entry x asset class). Every arm lands in `measurement.arms` with its `net_r` so `trial_ledger.py` counts it.

STATED BIASES. Harness paths are not live paths. Gaps fill at the open in the engine and at the level in the harness
(fidelity is reported). The intrabar order is stop-first. The v1 policy applies one intervention per trade. E2
(matched random ENTRIES) and E3 (desk entries) are not built in v1 (`entry_source: E1`).

Tier-1 research code: keyless public candles via the config-exact harnesses; no VM, no journal, no order path.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import capital_efficiency  # noqa: E402  (the ONE net R per capital-day)
import counterfactual_grader as _engine  # noqa: E402  (ONE ENGINE: simulate + net_of; repoint to cf_core when CF-B0 lands)
import first_passage_paths as fpp  # noqa: E402  (corpus, parity, events, census oracle -- the 09a6-01 construction)
from first_passage import Logit, TF_MIN  # noqa: E402
from intervention_controls import HOLD, boot_ci_by_group, matched_random_intervention  # noqa: E402

ENGINE_SIMULATE = _engine.simulate
ENGINE_NET_OF = _engine.net_of
ENGINE_SOURCE = "scripts/research/counterfactual_grader.py::simulate+net_of (CF-B0 cf_core not on main 2026-10-30)"

SCHEMA = "tm_bench/1"
V1_LEGS = ["trend_donchian_eth_4h", "trend_donchian_xrp_4h", "xrp_pullback_2h", "ada_pullback_2h",
           "trend_donchian_eth_prop", "trend_donchian_sol_prop"]
V1_WINDOW = {"start": "2020-07-01", "end": "2026-10-15 23:59", "days": 2330}
ORACLE_TARGET_R = 0.756
ORACLE_TOL_R = 0.005
FIDELITY_TOL_R = 0.01
TOUCH_EPS_R = 1e-9
ACTIONS = ("close", "partial_close_50", "tighten_sl_be", "tighten_sl_atr1", "tighten_sl_atr2",
           "tp_pull_in_0p5r", "tp_pull_in_1r")
ALL_ACTIONS = ("hold",) + ACTIONS
R_LEVELS = (-1.0, -0.5, 0.5, 1.0, 2.0)
VOL_LEVELS = (1.5, 0.67)
CHECKINS = {"every_bar": (1, False), "every_4": (4, False), "every_4+triggers": (4, True), "triggers_only": (0, True)}
B1_GRID = [
    {"id": "be_at_1r", "rules": [{"kind": "stop_at", "trigger_r": 1.0, "level_r": 0.0}]},
    {"id": "lock1_at_2r", "rules": [{"kind": "stop_at", "trigger_r": 2.0, "level_r": 1.0}]},
    {"id": "be_lock_ladder", "rules": [{"kind": "stop_at", "trigger_r": 1.0, "level_r": 0.0},
                                       {"kind": "stop_at", "trigger_r": 2.0, "level_r": 1.0}]},
    {"id": "chandelier_2atr", "trail_atr": 2.0}, {"id": "chandelier_3atr", "trail_atr": 3.0},
    {"id": "channel_10", "channel": 10}, {"id": "channel_20", "channel": 20},
]
B2_P_GRID = (0.6, 0.7, 0.8, 0.9)
ACT_MARGIN_R = 0.05
LOGIT_ACT_P = 0.6
LGBM_ROUNDS = 300
LGBM_PARAMS = {"objective": "regression", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 100,
               "bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "verbose": -1,
               "num_threads": 4}
S_OFFLINE = {"min_gain_r": 0.03, "min_folds": 5}
SYNTH_SUBSTEPS = 100


# --------------------------------------------------------------------------- corpus
def _cost_policy(symbol: str) -> Tuple[float, float]:
    from src.runtime.execution_costs import resolve_cost_policy
    slip, fund = resolve_cost_policy(symbol)
    return float(slip), float(fund)


def _read_jsonl(p: Path) -> List[dict]:
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def _leg_tf(leg: str) -> Optional[str]:
    import yaml
    cfg = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    cfg = cfg.get("strategies", cfg)
    return (cfg.get(leg) or {}).get("timeframe") if isinstance(cfg.get(leg), dict) else None


def load_combined(d: Path) -> List[Tuple[str, List[dict], List[dict], Optional[str]]]:
    """A directory holding one trades.jsonl[.gz] + paths.jsonl[.gz] for many legs (the broad-paths shard layout)."""
    tp = next((p for p in (d / "trades.jsonl.gz", d / "trades.jsonl") if p.exists()), None)
    pp = next((p for p in (d / "paths.jsonl.gz", d / "paths.jsonl") if p.exists()), None)
    if tp is None or pp is None:
        raise FileNotFoundError(f"{d}: needs trades.jsonl[.gz] and paths.jsonl[.gz]")
    trows, prows = _read_jsonl(tp), _read_jsonl(pp)
    by_leg_t: Dict[str, List[dict]] = {}
    for r in trows:
        by_leg_t.setdefault(str(r.get("strategy")), []).append(r)
    by_leg_p: Dict[str, List[dict]] = {}
    for r in prows:
        by_leg_p.setdefault(str(r.get("strategy") or str(r.get("trade_key", "")).split("|")[0]), []).append(r)
    return [(leg, by_leg_p.get(leg, []), tr, (tr[0].get("meta") or {}).get("timeframe") or _leg_tf(leg))
            for leg, tr in sorted(by_leg_t.items())]


def resolve_corpus(spec: str, *, work: Path, synthetic_seed: int = 5) -> Tuple[list, Dict[str, Any]]:
    """`v1` | `synthetic[-planted]` | a frozen corpus dir (corpus.json) | a combined-shard dir | a __paths.jsonl glob."""
    if spec in ("synthetic", "synthetic-planted"):
        # sub=100: at the default 10 sub-steps a stop hit overshoots its level by ~0.1 R and is filled AT the level, so a
        # tightened stop earns +0.03..0.06 R on a driftless walk (measured 2026-10-30: the null learner read +0.106 R,
        # CI [-0.0005, 0.198]); at 100 every null label is <= 0 (costs) and the null learner's CI spans 0
        return (fpp.synthetic_corpus(spec.endswith("planted"), seed=synthetic_seed, sub=SYNTH_SUBSTEPS),
                {"source": f"in-process {spec} corpus (first_passage_paths.synthetic_corpus, seed {synthetic_seed}, "
                           f"sub {SYNTH_SUBSTEPS})"})
    if spec == "v1":
        wd = Path(tempfile.mkdtemp(prefix="tm_bench_v1_", dir=str(work)))
        corpus, failed, runs = fpp.run_harness_legs(V1_LEGS, days=V1_WINDOW["days"], start=V1_WINDOW["start"],
                                                    end=V1_WINDOW["end"], wd=wd, data_csv=None)
        return corpus, {"source": f"corpus v1: config-exact harness runs with --emit-paths of {V1_LEGS}, window "
                                  f"{V1_WINDOW['start']} .. {V1_WINDOW['end']}", "failed": failed, "runs": runs}
    p = Path(spec)
    if p.is_dir() and (p / "corpus.json").exists():
        man = json.loads((p / "corpus.json").read_text())
        corpus = [(leg, _read_jsonl(p / f"{leg}__paths.jsonl"), _read_jsonl(p / f"{leg}__trades.jsonl"),
                   man.get("timeframes", {}).get(leg)) for leg in man["legs"]]
        return corpus, {"source": f"frozen corpus {man['corpus_id']} ({p})", "frozen_manifest": man}
    if p.is_dir():
        return load_combined(p), {"source": f"combined shard dir {p}"}
    corpus, skipped = fpp.load_paths_glob(spec)
    return [(leg, pr, tr, ((tr[0].get("meta") or {}).get("timeframe") if tr else None) or _leg_tf(leg))
            for leg, pr, tr, _ in corpus], {"source": f"emitted path files {spec}", "failed": skipped}


def build_corpus(corpus: list, meta: Dict[str, Any], cost_fn=None) -> Dict[str, Any]:
    """Join + parity (first_passage_paths.build_trades), hash, and return the bench corpus."""
    trades, reports = [], []
    cx = cost_fn or fpp.c_exit_r
    for leg, prow, trow, tf in corpus:
        tf = tf or _leg_tf(leg)
        ts, rep = fpp.build_trades(leg, prow, trow, tf, cost_fn=cx)
        if rep["state"] == "included" and ts and ts[0]["tfm"] is None:
            rep["state"] = "timeframe_unresolved"
        rep["timeframe"] = tf
        reports.append(rep)
        if rep["state"] == "included":
            trades.extend(ts)
    # content hash: the trades themselves (key, exit, net, bars), not where they were read from, so a frozen copy
    # of a corpus keeps its id and two emits that differ in any trade do not share one
    rows = sorted((t["trade_key"], round(t["exit_r"], 6), round(t["net_r"], 6), int(t["bars"])) for t in trades)
    legs = sorted({t["leg"] for t in trades})
    h = hashlib.sha256(json.dumps({"trades": rows, "legs": legs}).encode()).hexdigest()
    return {"corpus_id": f"tmb-{h[:12]}", "trades": trades, "legs": reports, "source": meta.get("source"),
            "failed": meta.get("failed") or [], "runs": meta.get("runs") or {},
            "parity_ok": bool(reports) and not meta.get("failed") and all(r["state"] == "included" for r in reports)}


def freeze(corpus: list, bc: Dict[str, Any], out: Path) -> Dict[str, Any]:
    """Write the corpus as per-leg files + corpus.json; `resolve_corpus(<out>)` reads it back unchanged."""
    out.mkdir(parents=True, exist_ok=True)
    for leg, prow, trow, _tf in corpus:
        for kind, rows in (("paths", prow), ("trades", trow)):
            with open(out / f"{leg}__{kind}.jsonl", "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, default=str) + "\n")
    man = {"schema": SCHEMA, "corpus_id": bc["corpus_id"], "source": bc["source"], "legs": [c[0] for c in corpus],
           "timeframes": {c[0]: c[3] for c in corpus}, "n_trades": len(bc["trades"]),
           "trade_keys_sha256": hashlib.sha256("\n".join(sorted(t["trade_key"] for t in bc["trades"])).encode()).hexdigest()}
    (out / "corpus.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return man


# --------------------------------------------------------------------------- engine adapter (R-space)
def _sec(t: dict) -> float:
    return float(t["tfm"] or 60) * 60.0


def engine_bars(t: dict) -> List[dict]:
    q, sec, n = t["entry_over_risk"], _sec(t), t["bars"]
    c = t["c_r"]
    o = t.get("o_r")
    bars = []
    for j in range(n):
        op = o[j] if o is not None and np.isfinite(o[j]) else (c[j - 1] if j else 0.0)
        cl = t["exit_r"] if j == n - 1 else c[j]
        hi = np.nanmax([t["fav"][j], op, cl])
        lo = np.nanmin([t["adv"][j], op, cl])
        bars.append({"time": j * sec, "dur": sec, "open": q + op, "high": q + hi + TOUCH_EPS_R,
                     "low": q + lo - TOUCH_EPS_R, "close": q + cl})
    return bars


def _cm(t: dict, cost: Callable[[str], Tuple[float, float]]) -> dict:
    slip_rt, fund = cost(t["symbol"])
    return {"fee_bps": t["cost_fee_r"] * 1e4 / t["entry_over_risk"], "slip_exit_bps": slip_rt / 2.0,
            "fund_bps_window": fund, "fee_source": "harness cost_fee_r"}


def leg_actions(t: dict, tp_cap: Optional[Tuple[int, float]] = None) -> List[dict]:
    """The leg's own management as timed actions; `tp_cap=(from_bar, level_r)` pulls the TP in from that bar on."""
    q, sec = t["entry_over_risk"], _sec(t)
    acts = []
    for j in range(t["bars"]):
        s, g = t["stop_r"][j], t["target_r"][j]
        if np.isfinite(s):
            acts.append({"ts": j * sec, "kind": "set_stop", "level": q + s})
        lvl = q + g if np.isfinite(g) else None
        if tp_cap is not None and j >= tp_cap[0]:
            cap = q + tp_cap[1]
            lvl = cap if lvl is None else min(lvl, cap)
        acts.append({"ts": j * sec, "kind": "set_tp", "level": lvl})
    return acts


def replay(t: dict, bars: List[dict], cm: dict, *, extra: Sequence[dict] = (), tp_cap=None, rules=(),
           trail_r: Optional[float] = None) -> Tuple[float, dict]:
    q = t["entry_over_risk"]
    s0, g0 = t["stop_r"][0], t["target_r"][0]
    sim = ENGINE_SIMULATE(bars, side="long", entry_ref=q, r_dist=1.0, t_entry=0.0,
                          stop0=q + (s0 if np.isfinite(s0) else -1.0), tp=q + g0 if np.isfinite(g0) else None,
                          actions=list(leg_actions(t, tp_cap)) + list(extra), rules=rules, trail_dist=trail_r)
    net = ENGINE_NET_OF(sim, side="long", entry_fill=q, r_dist=1.0, t_entry=0.0, cm=cm)
    return net["net_r"], {"gross_r": net["gross_r"], "sim": sim}


def action_spec(t: dict, a: str, s: int) -> Optional[dict]:
    """Engine inputs for action `a` decided at state s (after bar s's close), or None if invalid there."""
    q, sec = t["entry_over_risk"], _sec(t)
    ts = (s + 1) * sec
    c, stop, tgt, atr = t["c_r"][s], t["stop_r"][s], t["target_r"][s], t["atr_r"][s]
    if a == "close":
        return {"extra": [{"ts": ts, "kind": "close", "frac": 1.0}]}
    if a == "partial_close_50":
        return {"extra": [{"ts": ts, "kind": "close", "frac": 0.5}]}
    if a.startswith("tighten_sl"):
        lvl = 0.0 if a == "tighten_sl_be" else c - (1.0 if a.endswith("atr1") else 2.0) * atr
        if not np.isfinite(lvl) or lvl >= c or (np.isfinite(stop) and lvl <= stop):
            return None
        return {"extra": [{"ts": ts, "kind": "set_stop", "level": q + lvl}]}
    if a.startswith("tp_pull_in"):
        lvl = c + (0.5 if a.endswith("0p5r") else 1.0)
        if np.isfinite(tgt) and lvl >= tgt:
            return None
        return {"tp_cap": (s + 1, lvl)}
    raise ValueError(a)


def label_trade(t: dict, cost) -> Dict[str, Any]:
    """label[a] (len n_states): net R(B0 + a at t) - net R(B0 replay); NaN = invalid there (scored as HOLD)."""
    bars, cm = engine_bars(t), _cm(t, cost)
    net0, info = replay(t, bars, cm)
    n = t["bars"] - 1
    lab = {a: np.full(max(n, 0), np.nan) for a in ACTIONS}
    for s in range(max(n, 0)):
        for a in ACTIONS:
            sp = action_spec(t, a, s)
            if sp is not None:
                lab[a][s] = replay(t, bars, cm, extra=sp.get("extra", ()), tp_cap=sp.get("tp_cap"))[0] - net0
    return {"labels": lab, "b0_replay_net_r": net0, "b0_replay_gross_r": info["gross_r"], "bars": bars, "cm": cm,
            "fidelity_ok": bool(abs(info["gross_r"] - t["exit_r"]) <= FIDELITY_TOL_R)}


def rule_delta(t: dict, L: Dict[str, Any], rule: dict) -> float:
    bars, cm = L["bars"], L["cm"]
    extra: List[dict] = []
    trail = None
    if "trail_atr" in rule:
        a0 = t["atr_r"][0]
        trail = rule["trail_atr"] * a0 if np.isfinite(a0) and a0 > 0 else None
    if "channel" in rule:
        N, q, sec = rule["channel"], t["entry_over_risk"], _sec(t)
        for j in range(1, t["bars"]):
            lo = np.nanmin(t["adv"][max(0, j - N):j])
            extra.append({"ts": j * sec, "kind": "set_stop", "level": q + lo})
    return replay(t, bars, cm, extra=extra, rules=rule.get("rules", ()), trail_r=trail)[0] - L["b0_replay_net_r"]


# --------------------------------------------------------------------------- folds (cross-symbol purge)
def make_folds(test: List[dict], train: List[dict], k: int, same: bool) -> Dict[str, Any]:
    ent = np.array([t["entry_time"].value for t in test], dtype=np.int64)
    edges = np.linspace(ent.min(), ent.max() + 1, k + 1)
    fid = np.clip(np.searchsorted(edges, ent, side="right") - 1, 0, k - 1)
    emb: Dict[str, int] = {}
    for t in train:
        emb[t["leg"]] = max(emb.get(t["leg"], 0), int(t["exit_time"].value - t["entry_time"].value))
    test_keys = {t["trade_key"] for t in test}
    folds = []
    for f in range(k):
        lo_, hi_ = edges[f], edges[f + 1]
        te = [int(i) for i in np.nonzero(fid == f)[0]]
        tr, n_purged, n_dup = [], 0, 0
        for i, t in enumerate(train):
            if same and fid[i] == f:
                continue
            if not same and t["trade_key"] in test_keys:
                n_dup += 1
                continue
            e0, e1 = t["entry_time"].value, t["exit_time"].value + emb[t["leg"]]
            if e0 < hi_ and e1 >= lo_:
                n_purged += 1
                continue
            tr.append(i)
        folds.append({"fold": f, "lo": str(pd.Timestamp(int(lo_), tz="UTC")), "hi": str(pd.Timestamp(int(hi_), tz="UTC")),
                      "test": te, "train": tr, "n_purged": n_purged, "n_dedup": n_dup})
    return {"k": k, "folds": folds, "embargo_hours_by_leg": {lg: round(v / 3.6e12, 2) for lg, v in sorted(emb.items())},
            "rule": "train trade purged if [entry, exit + leg max hold] overlaps the test fold window (any symbol); "
                    "train trade_keys present in the test corpus dropped"}


# --------------------------------------------------------------------------- check-ins
def checkin_mask(t: dict, cell: str, med_win_bars: Optional[float]) -> np.ndarray:
    n = t["bars"] - 1
    if n <= 0:
        return np.zeros(0, bool)
    every, trig = CHECKINS[cell]
    off = t["off"][:n]
    m = np.zeros(n, bool)
    if every:
        m |= (off.astype(int) % every) == (1 % every)
    if trig:
        x = np.r_[0.0, t["open_r"][:n]]
        for L in R_LEVELS:
            m |= (x[:-1] - L) * (x[1:] - L) < 0
        atr = t["atr_r"][:n]
        a0 = atr[0] if np.isfinite(atr[0]) and atr[0] > 0 else np.nan
        ratio = np.r_[1.0, atr / a0]
        for L in VOL_LEVELS:
            m |= np.nan_to_num((ratio[:-1] - L) * (ratio[1:] - L), nan=1.0) < 0
        c = np.r_[0.0, t["c_r"][:n]]
        b = np.arange(1, n + 1)
        mom = np.where(b >= 3, np.sign(c[b] - c[np.maximum(b - 3, 0)]), 0.0)
        m |= np.r_[False, (mom[1:] * mom[:-1]) < 0]
        if med_win_bars:
            m |= off == round(med_win_bars)
    return m


def med_win(trades: List[dict], idx: Sequence[int]) -> Dict[str, float]:
    out: Dict[str, List[int]] = {}
    for i in idx:
        if trades[i]["net_r"] > 0:
            out.setdefault(trades[i]["leg"], []).append(trades[i]["bars"])
    return {lg: float(np.median(v)) for lg, v in out.items()}


# --------------------------------------------------------------------------- learners
def _fit_lgbm(X: np.ndarray, y: np.ndarray, seed: int):
    import lightgbm as lgb   # native API: the runner installs lightgbm without scikit-learn on some paths
    return lgb.train(dict(LGBM_PARAMS, seed=seed), lgb.Dataset(X, label=y), num_boost_round=LGBM_ROUNDS)


def fit_learners(trades, ev, labs, tr_idx: List[int], kinds: Sequence[str], seed: int) -> Dict[str, Any]:
    rows = [i for i in tr_idx if ev[i]["n"]]
    if not rows:
        return {}
    X = np.vstack([ev[i]["X1"] for i in rows])
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    Xf = np.where(np.isfinite(X), X, med)
    Y = {a: np.nan_to_num(np.concatenate([labs[i]["labels"][a] for i in rows]), nan=0.0) for a in ACTIONS}
    w = np.concatenate([np.full(ev[i]["n"], 1.0 / ev[i]["n"]) for i in rows])
    out: Dict[str, Any] = {"_med": med}
    if "lgbm_action_value" in kinds:
        try:
            out["lgbm_action_value"] = {a: _fit_lgbm(Xf, Y[a], seed) for a in ACTIONS}
        except ImportError as exc:  # allow-silent: an unavailable learner is a recorded fact in the arm, never a pooled zero
            out["lgbm_action_value"] = {"unavailable": repr(exc)}
    if "logit_action_value" in kinds:
        out["logit_action_value"] = {a: Logit().fit(Xf, (Y[a] > 0).astype(float), w) for a in ACTIONS}
    if "b2" in kinds:   # distance-only reference: stop_atr, target_atr, no_target (R1 columns 4, 5, 6)
        y = np.concatenate([ev[i]["y"] for i in rows])
        out["b2"] = Logit().fit(Xf[:, 4:7], y, w)
    return out


def learner_scores(kind: str, model, X: np.ndarray, med: np.ndarray) -> Optional[np.ndarray]:
    """(n_states x n_actions) action scores, or None if the learner is unavailable."""
    if isinstance(model, dict) and "unavailable" in model:
        return None
    Xf = np.where(np.isfinite(X), X, med)
    if kind == "lgbm_action_value":
        return np.column_stack([model[a].predict(Xf) for a in ACTIONS])
    return np.column_stack([model[a].predict_proba_sl(Xf) for a in ACTIONS])


# --------------------------------------------------------------------------- scoring
def first_action(scores: Optional[np.ndarray], mask: np.ndarray, thr: float) -> Optional[Tuple[int, str]]:
    if scores is None or not len(mask):
        return None
    for s in np.nonzero(mask)[0]:
        j = int(np.argmax(scores[s]))
        if scores[s, j] > thr:
            return int(s), ACTIONS[j]
    return None


def _maxdd(x: Sequence[float]) -> float:
    c = np.cumsum(x)
    return float(np.max(np.maximum.accumulate(np.r_[0.0, c]) - np.r_[0.0, c])) if len(c) else 0.0


def _p_one_sided(d: np.ndarray, rng, n_boot: int) -> float:
    if not len(d):
        return float("nan")
    m = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(axis=1)
    return float(np.mean(m <= 0))


def holm(ps: Dict[str, float]) -> Dict[str, float]:
    items = sorted((p, k) for k, p in ps.items() if p == p)
    out, run = {}, 0.0
    m = len(items)
    for r, (p, k) in enumerate(items):
        run = max(run, min(1.0, (m - r) * p))
        out[k] = round(run, 5)
    return out


def summarize_arm(arm_id: str, trades, recs: List[dict], rng, n_boot: int, b4: Optional[np.ndarray] = None,
                  extra: Optional[dict] = None) -> Dict[str, Any]:
    """recs: one per OOS trade {i, fold, d, act, s}. The arm's paired dR vs B0 and every secondary line."""
    if not recs:
        return {"arm_id": arm_id, "n": 0, "read_state": "unmeasured"}
    d = np.array([r["d"] for r in recs])
    m, lo, hi = boot_ci_by_group(d, None, rng, n_boot)
    folds = {}
    for f in sorted({r["fold"] for r in recs}):
        folds[str(f)] = round(float(np.mean([r["d"] for r in recs if r["fold"] == f])), 5)
    act = np.array([r["act"] is not None for r in recs])
    b0 = np.array([trades[r["i"]]["net_r"] for r in recs])
    legs_dd = {}
    for lg in sorted({trades[r["i"]]["leg"] for r in recs}):
        rr = sorted([r for r in recs if trades[r["i"]]["leg"] == lg], key=lambda r: trades[r["i"]]["entry_time"])
        a0 = _maxdd([trades[r["i"]]["net_r"] for r in rr])
        a1 = _maxdd([trades[r["i"]]["net_r"] + r["d"] for r in rr])
        legs_dd[lg] = {"n": len(rr), "b0_maxdd_r": round(a0, 3), "arm_maxdd_r": round(a1, 3), "ok": bool(a1 <= a0 + 1e-9)}

    def capday(arm: bool) -> Optional[float]:
        days = net = 0.0
        for r in recs:
            t = trades[r["i"]]
            bars = (r["s"] + 1) if (arm and r["act"] in ("close",)) else t["bars"]
            days += capital_efficiency.days_from_bars(bars, t["tfm"]) or 0.0
            net += t["net_r"] + (r["d"] if arm else 0.0)
        return round(net / days, 5) if days > 0 else None
    strata: Dict[str, Dict[str, Any]] = {}
    for r in recs:
        strata.setdefault(r.get("stratum", "all"), []).append(r["d"])  # type: ignore[arg-type]
    out = {"arm_id": arm_id, "n": len(recs), "read_state": "measured",
           "net_r": round(float(b0.mean() + d.mean()), 5), "b0_net_r": round(float(b0.mean()), 5),
           "delta_vs_b0_r": round(m, 5), "ci95": [round(lo, 5), round(hi, 5)],
           "p_one_sided": round(_p_one_sided(d, rng, n_boot), 5),
           "folds": folds, "folds_positive": sum(1 for v in folds.values() if v > 0),
           "action_rate": round(float(act.mean()), 4),
           "delta_acted_r": round(float(d[act].mean()), 5) if act.any() else None,
           "n_acted": int(act.sum()), "n_invalid_scored_hold": int(sum(1 for r in recs if r.get("invalid"))),
           "maxdd_per_leg": legs_dd, "maxdd_ok": all(v["ok"] for v in legs_dd.values()),
           "net_r_per_capital_day": capday(True), "b0_net_r_per_capital_day": capday(False),
           "strata": {k: {"n": len(v), "delta_r": round(float(np.mean(v)), 5)} for k, v in sorted(strata.items())},
           "provenance": "ESTIMATED (harness paths, engine replay, full cost stack)"}
    if b4 is not None:
        mm, l2, h2 = boot_ci_by_group(d - b4, None, rng, n_boot)
        out["b4_matched_random"] = {"mode": "causal", "delta_vs_b0_r": round(float(b4.mean()), 5),
                                    "margin_r": round(mm, 5), "margin_ci95": [round(l2, 5), round(h2, 5)],
                                    "p_random_ge_arm": round(float(np.mean(
                                        [b4[rng.integers(0, len(b4), len(b4))].mean() >= d.mean() for _ in range(500)])), 4)}
    if extra:
        out.update(extra)
    return out


def b4_for(recs: List[dict], labs, masks: Dict[int, np.ndarray], seed: int, draws: int) -> np.ndarray:
    """B4: the arm's own action mix (count and type per trade) at causal random check-ins of the same trades."""
    freq: Dict[Tuple, float] = {HOLD: 0.0}
    for r in recs:
        k = (r["act"],) if r["act"] else HOLD
        freq[k] = freq.get(k, 0.0) + 1.0 / len(recs)
    table = []
    for r in recs:
        mk = masks[r["i"]]
        row = {}
        for a in ACTIONS:
            arr = labs[r["i"]]["labels"][a][mk] if len(mk) else np.zeros(0)
            row[(a,)] = np.nan_to_num(arr, nan=0.0)
        table.append(row)
    return matched_random_intervention(table, freq, seed, draws, mode="causal")


def _stratum(t: dict, terc: Tuple[float, float]) -> str:
    a0 = t["atr_r"][0] if len(t["atr_r"]) else np.nan
    v = "vol_na" if not np.isfinite(a0) else ("vol_lo" if a0 <= terc[0] else ("vol_hi" if a0 > terc[1] else "vol_mid"))
    asset = "crypto" if str(t["symbol"]).endswith("USDT") else "other"
    return f"{t['family']}|{v}|{asset}"


def score(test: Dict[str, Any], train: Optional[Dict[str, Any]], *, k: int, n_boot: int, draws: int, seed: int,
          cost, kinds: Sequence[str], desk_policy: Optional[Dict[str, str]] = None,
          checkins: Sequence[str] = tuple(CHECKINS), act_margin_r: float = ACT_MARGIN_R,
          logit_act_p: float = LOGIT_ACT_P) -> Dict[str, Any]:
    T = test["trades"]
    same = train is None
    TR = T if same else train["trades"]
    fe_legs = sorted({t["leg"] for t in T} | {t["leg"] for t in TR})
    ev = [fpp.events(t, fe_legs) for t in T]
    ev_tr = ev if same else [fpp.events(t, fe_legs) for t in TR]
    labs = [label_trade(t, cost) for t in T]
    fl = make_folds(T, TR, k, same)
    labs_tr: Dict[int, Any] = {}

    def lab_tr(i: int):
        if same:
            return labs[i]
        if i not in labs_tr:
            labs_tr[i] = label_trade(TR[i], cost)
        return labs_tr[i]
    rng = np.random.default_rng(seed)
    a0 = np.array([t["atr_r"][0] for t in T if len(t["atr_r"]) and np.isfinite(t["atr_r"][0])])
    terc = tuple(np.percentile(a0, [33.3, 66.7])) if len(a0) else (np.nan, np.nan)
    oracle_ceiling = []
    for L in labs:
        vals = [np.nanmax(v) for v in L["labels"].values() if len(v) and np.isfinite(v).any()]
        oracle_ceiling.append(max([0.0] + vals))
    census = fpp.census(T, ev)["__pooled__"] if T else {}
    fid = float(np.mean([L["fidelity_ok"] for L in labs])) if labs else None

    # B1: rules on the engine, leave-fold-out per leg (independent of the check-in policy: continuous rules)
    rule_mat = np.array([[rule_delta(T[i], labs[i], r) for r in B1_GRID] for i in range(len(T))]) if T else np.zeros((0, 0))
    fold_of = np.full(len(T), -1)
    for f in fl["folds"]:
        fold_of[f["test"]] = f["fold"]
    b1_d = np.zeros(len(T))
    b1_chosen: Dict[str, Dict[str, str]] = {}
    for lg in sorted({t["leg"] for t in T}):
        li = np.array([i for i, t in enumerate(T) if t["leg"] == lg])
        for f in sorted(set(fold_of[li].tolist())):
            trn = li[fold_of[li] != f]
            tst = li[fold_of[li] == f]
            best = int(np.argmax(rule_mat[trn].mean(axis=0))) if len(trn) else None
            b1_chosen.setdefault(lg, {})[str(f)] = B1_GRID[best]["id"] if best is not None else None
            b1_d[tst] = rule_mat[tst, best] if best is not None else 0.0

    # per fold: fitted learners and train-fold constants
    fold_models, fold_medwin, fold_b2p = {}, {}, {}
    for f in fl["folds"]:
        if not f["test"] or not f["train"]:
            continue
        tr = f["train"]
        trlabs = {i: lab_tr(i) for i in tr} if not same else {i: labs[i] for i in tr}
        fold_models[f["fold"]] = fit_learners(TR, ev_tr, trlabs, tr, list(kinds) + ["b2"], seed)
        fold_medwin[f["fold"]] = med_win(TR, tr)
        mdl = fold_models[f["fold"]]
        best_p, best_v = B2_P_GRID[0], -1e9      # p* for B2 on the TRAIN fold, every-bar check-ins
        for p in B2_P_GRID:
            v = 0.0
            for i in tr:
                if not ev_tr[i]["n"]:
                    continue
                pr = mdl["b2"].predict_proba_sl(np.where(np.isfinite(ev_tr[i]["X1"][:, 4:7]), ev_tr[i]["X1"][:, 4:7], mdl["_med"][4:7]))
                hit = np.nonzero(pr >= p)[0]
                if len(hit):
                    v += np.nan_to_num(trlabs[i]["labels"]["close"][hit[0]], nan=0.0)
            if v > best_v:
                best_p, best_v = p, v
        fold_b2p[f["fold"]] = best_p

    arms: List[Dict[str, Any]] = []
    oos = [(f["fold"], i) for f in fl["folds"] if f["fold"] in fold_models for i in f["test"]]

    def rec(i, fold, act):
        if act is None:
            return {"i": i, "fold": fold, "d": 0.0, "act": None, "s": -1, "stratum": _stratum(T[i], terc)}
        s, a = act
        v = labs[i]["labels"][a][s]
        return {"i": i, "fold": fold, "d": float(v) if np.isfinite(v) else 0.0, "act": a, "s": s,
                "invalid": not np.isfinite(v), "stratum": _stratum(T[i], terc)}

    b0_recs = [rec(i, f, None) for f, i in oos]
    b0 = summarize_arm("B0_hold", T, b0_recs, rng, n_boot)
    b0["b0_minus_b0_r"] = float(sum(r["d"] for r in b0_recs))    # the hold policy through the same scorer: 0 exactly
    arms.append(b0)
    arms.append(summarize_arm("B1_best_static_rule", T, [dict(rec(i, f, None), d=float(b1_d[i]), act="rule")
                                                         for f, i in oos], rng, n_boot,
                              extra={"chosen_by_leg_fold": b1_chosen, "grid": [r["id"] for r in B1_GRID],
                                     "checkin": "continuous (rule)"}))
    for cell in checkins:
        masks = {i: checkin_mask(T[i], cell, fold_medwin[f].get(T[i]["leg"])) for f, i in oos}
        fam_ps: Dict[str, float] = {}
        cell_arms = []
        # B2 distance-only close
        recs = []
        for f, i in oos:
            act = None
            if ev[i]["n"]:
                md = fold_models[f]
                pr = md["b2"].predict_proba_sl(np.where(np.isfinite(ev[i]["X1"][:, 4:7]), ev[i]["X1"][:, 4:7], md["_med"][4:7]))
                hit = [s for s in np.nonzero(masks[i])[0] if pr[s] >= fold_b2p[f]]
                act = (int(hit[0]), "close") if hit else None
            recs.append(rec(i, f, act))
        cell_arms.append(summarize_arm(f"B2_distance_logit@{cell}", T, recs, rng, n_boot,
                                       b4_for(recs, labs, masks, seed + 2, draws),
                                       extra={"p_star_by_fold": fold_b2p}))
        # B6 vol-rescale (reductive partial close at the first vol check-in)
        recs = []
        for f, i in oos:
            t, mk = T[i], masks[i]
            n = t["bars"] - 1
            a0_ = t["atr_r"][0] if n > 0 else np.nan
            hit = [s for s in np.nonzero(mk)[0] if np.isfinite(a0_) and a0_ > 0 and t["atr_r"][s] / a0_ >= 1.5]
            if hit:
                s = int(hit[0])
                frac = float(np.clip(1.0 - a0_ / t["atr_r"][s], 0.0, 1.0))
                dv = replay(t, labs[i]["bars"], labs[i]["cm"], extra=[{"ts": (s + 1) * _sec(t), "kind": "close",
                                                                        "frac": frac}])[0] - labs[i]["b0_replay_net_r"]
                recs.append({"i": i, "fold": f, "d": dv, "act": "vol_rescale", "s": s, "stratum": _stratum(t, terc)})
            else:
                recs.append(rec(i, f, None))
        cell_arms.append(summarize_arm(f"B6_vol_rescale@{cell}", T, recs, rng, n_boot))
        # learners
        for kind in kinds:
            recs, unavailable = [], None
            for f, i in oos:
                mdl = fold_models[f].get(kind)
                sc = learner_scores(kind, mdl, ev[i]["X1"], fold_models[f]["_med"]) if (mdl is not None and ev[i]["n"]) else None
                if isinstance(mdl, dict) and "unavailable" in mdl:
                    unavailable = mdl["unavailable"]
                thr = act_margin_r if kind == "lgbm_action_value" else logit_act_p
                recs.append(rec(i, f, first_action(sc, masks[i], thr)))
            if unavailable:
                cell_arms.append({"arm_id": f"{kind}@{cell}", "read_state": "unavailable", "reason": unavailable})
                continue
            arm = summarize_arm(f"{kind}@{cell}", T, recs, rng, n_boot, b4_for(recs, labs, masks, seed + 3, draws),
                                extra={"act_threshold": act_margin_r if kind == "lgbm_action_value" else logit_act_p})
            fam_ps[arm["arm_id"]] = arm["p_one_sided"]
            cell_arms.append(arm)
        if desk_policy is not None:
            recs = []
            for f, i in oos:
                t, act = T[i], None
                for s in np.nonzero(masks[i])[0]:
                    a = desk_policy.get(f"{t['trade_key']}@{int(t['off'][s])}")
                    if a and a != "hold":
                        act = (int(s), a) if a in ACTIONS else None
                        break
                recs.append(rec(i, f, act))
            cell_arms.append(summarize_arm(f"B3_desk@{cell}", T, recs, rng, n_boot, b4_for(recs, labs, masks, seed + 4, draws)))
        hp = holm(fam_ps)
        for a in cell_arms:
            if a.get("arm_id") in hp:
                a["p_holm_family"] = hp[a["arm_id"]]
            a["checkin"] = cell
        arms.extend(cell_arms)
    arms.append({"arm_id": "B3_desk", "read_state": "not_available" if desk_policy is None else "measured",
                 "reason": None if desk_policy is not None else "no --desk-policy file (DESK-LABEL-JOIN not landed)"})
    arms.append({"arm_id": "B5_rescore_exit", "read_state": "not_available",
                 "reason": "the entry model does not replay point-in-time from the harness emit"})
    # ceiling check: every policy arm <= the action-value oracle, per trade (v1 single-action policies)
    oracle_oos = float(np.mean([oracle_ceiling[i] for _f, i in oos])) if oos else None
    return {"corpus_id": test["corpus_id"], "train_corpus_id": None if same else train["corpus_id"],
            "n_trades": len(T), "n_states": int(sum(e["n"] for e in ev)), "n_oos_trades": len(oos),
            "engine": ENGINE_SOURCE, "engine_fidelity": {"share_within_tol": None if fid is None else round(fid, 4),
                                                         "tol_r": FIDELITY_TOL_R},
            "oracle": {"census_best_close_saving_r_per_trade": census.get("oracle_best_close_saving_r_per_trade"),
                       "census": census, "action_value_ceiling_r_per_trade_all": round(float(np.mean(oracle_ceiling)), 5)
                       if oracle_ceiling else None, "action_value_ceiling_r_per_trade_oos": None if oracle_oos is None
                       else round(oracle_oos, 5)},
            "folds": {k_: v for k_, v in fl.items() if k_ != "folds"} | {"per_fold": [
                {kk: (len(vv) if kk in ("test", "train") else vv) for kk, vv in f.items()} for f in fl["folds"]]},
            "fold_assignment": {T[i]["trade_key"]: f["fold"] for f in fl["folds"] for i in f["test"]},
            "action_enum": list(ALL_ACTIONS), "checkin_grid": list(checkins), "entry_source": "E1",
            "arms": arms, "_labs": labs, "_oracle": oracle_ceiling, "_trades": T}


def s_offline(arm: Dict[str, Any], arms: List[Dict[str, Any]]) -> Tuple[str, str]:
    """S-OFFLINE (ML-PROGRAMME § 1.3) for one arm, against B1 and its own B4 / B2 under the same check-in.
    The fresh-window re-pass is a separate run; B5 is not available, so a PASS here is `pass_pending_fresh_window`."""
    if arm.get("read_state") != "measured":
        return "indeterminate", "arm not measured"
    b1 = next((a for a in arms if a["arm_id"] == "B1_best_static_rule"), None)
    cell = arm.get("checkin")
    b2 = next((a for a in arms if a["arm_id"] == f"B2_distance_logit@{cell}"), None)
    bar = max(0.0, b1["delta_vs_b0_r"] if b1 else 0.0)
    gain = arm["delta_vs_b0_r"] - bar
    b4m = (arm.get("b4_matched_random") or {}).get("margin_ci95", [None])[0]
    checks = {"gain_ge_0.03_over_max_b0_b1": gain >= S_OFFLINE["min_gain_r"], "ci_lo_gt_0": arm["ci95"][0] > 0,
              "folds_ge_5": arm["folds_positive"] >= S_OFFLINE["min_folds"], "maxdd_ok": arm["maxdd_ok"],
              "capday_ok": (arm["net_r_per_capital_day"] or -1e9) >= (arm["b0_net_r_per_capital_day"] or 0.0),
              "beats_b2": b2 is None or arm["delta_vs_b0_r"] > b2["delta_vs_b0_r"],
              "beats_own_b4": b4m is not None and b4m > 0,
              "holm_p_lt_0.05": (arm.get("p_holm_family") or 1.0) < 0.05}
    why = ", ".join(f"{k}={v}" for k, v in checks.items())
    if all(checks.values()):
        return "pass_pending_fresh_window", why
    if arm["ci95"][1] < bar + S_OFFLINE["min_gain_r"]:
        return "fail", why
    return "indeterminate", why


# --------------------------------------------------------------------------- transfer (RQ-20261029-7294-01)
def transfer(test: Dict[str, Any], train: Dict[str, Any], fractions: Sequence[float], *, k: int, n_boot: int,
             seed: int, cost) -> Dict[str, Any]:
    """Trade-weighted OOS MSE of the per-action advantage on v1 test rows, per arm A0 + frac x |v1 train| of v2."""
    T, TR = test["trades"], train["trades"]
    fe_legs = sorted({t["leg"] for t in T} | {t["leg"] for t in TR})
    ev, ev2 = [fpp.events(t, fe_legs) for t in T], [fpp.events(t, fe_legs) for t in TR]
    labs = [label_trade(t, cost) for t in T]
    fl_self, fl_x = make_folds(T, T, k, True), make_folds(T, TR, k, False)
    labs2: Dict[int, Any] = {}
    per_trade: Dict[float, Dict[int, float]] = {fr: {} for fr in fractions}
    rng = np.random.default_rng(seed)
    for fs, fx in zip(fl_self["folds"], fl_x["folds"]):
        if not fs["test"] or not fs["train"]:
            continue
        base = [i for i in fs["train"] if ev[i]["n"]]
        pool = [i for i in fx["train"] if ev2[i]["n"]]
        order = list(np.random.default_rng(seed + fs["fold"]).permutation(len(pool)))
        for fr in fractions:
            take = [pool[j] for j in order[:min(len(pool), int(round(fr * len(base))))]]
            for i in take:
                if i not in labs2:
                    labs2[i] = label_trade(TR[i], cost)
            X = np.vstack([ev[i]["X1"] for i in base] + [ev2[i]["X1"] for i in take])
            med = np.nanmedian(X, axis=0)
            med = np.where(np.isfinite(med), med, 0.0)
            Xf = np.where(np.isfinite(X), X, med)
            for a in ACTIONS:
                y = np.nan_to_num(np.concatenate([labs[i]["labels"][a] for i in base] + [labs2[i]["labels"][a] for i in take]), nan=0.0)
                mdl = _fit_lgbm(Xf, y, seed)
                for i in fs["test"]:
                    if not ev[i]["n"]:
                        continue
                    p = mdl.predict(np.where(np.isfinite(ev[i]["X1"]), ev[i]["X1"], med))
                    e = float(np.mean((p - np.nan_to_num(labs[i]["labels"][a], nan=0.0)) ** 2)) / len(ACTIONS)
                    per_trade[fr][i] = per_trade[fr].get(i, 0.0) + e
    fr0, frx = min(fractions), max(fractions)
    ids = sorted(set(per_trade[fr0]) & set(per_trade[frx]))
    m0 = np.array([per_trade[fr0][i] for i in ids])
    mx = np.array([per_trade[frx][i] for i in ids])
    R = 1.0 - mx.mean() / m0.mean() if len(ids) and m0.mean() > 0 else None
    boot = []
    for _ in range(n_boot):
        j = rng.integers(0, len(ids), len(ids))
        boot.append(1.0 - mx[j].mean() / m0[j].mean())
    fold_of = {i: f["fold"] for f in fl_self["folds"] for i in f["test"]}
    folds = {}
    for f in sorted({fold_of[i] for i in ids}):
        jj = [n for n, i in enumerate(ids) if fold_of[i] == f]
        folds[str(f)] = round(1.0 - mx[jj].mean() / m0[jj].mean(), 5)
    mse = {str(fr): round(float(np.mean([per_trade[fr][i] for i in ids])), 6) for fr in fractions}
    seq = [mse[str(fr)] for fr in sorted(fractions)]
    return {"n_test_trades": len(ids), "n_train_corpus_trades": len(TR), "mse_by_fraction": mse,
            "relative_reduction": None if R is None else round(float(R), 5),
            "ci95": [round(float(np.percentile(boot, 2.5)), 5), round(float(np.percentile(boot, 97.5)), 5)] if boot else None,
            "folds": folds, "folds_positive": sum(1 for v in folds.values() if v > 0),
            "nested_steps_mse_rises": int(sum(1 for a, b in zip(seq, seq[1:]) if b > a)),
            "folds_cross": {kk: vv for kk, vv in fl_x.items() if kk != "folds"} | {"per_fold": [
                {kk: (len(vv) if kk in ("test", "train") else vv) for kk, vv in f.items()} for f in fl_x["folds"]]}}


# --------------------------------------------------------------------------- selfcheck
def selfcheck(verbose: bool = True) -> Dict[str, Any]:
    checks: List[Tuple[str, bool, str]] = []
    cost = lambda sym: (3.0, 1.0)  # noqa: E731  (synthetic symbol: fixed policy-default costs)
    cx = lambda sym, entry, risk: 3.0 / 1e4 * entry / risk  # noqa: E731
    with tempfile.TemporaryDirectory() as td:
        res = {}
        for spec in ("synthetic", "synthetic-planted"):
            corp, meta = resolve_corpus(spec, work=Path(td))
            bc = build_corpus(corp, meta, cost_fn=cx)
            # 1. freeze round-trip keeps the corpus_id
            freeze(corp, bc, Path(td) / spec)
            bc2 = build_corpus(*resolve_corpus(str(Path(td) / spec), work=Path(td)), cost_fn=cx)
            checks.append((f"{spec}: frozen corpus re-reads to the same corpus_id", bc2["corpus_id"] == bc["corpus_id"],
                           f"{bc['corpus_id']}, {len(bc['trades'])} trades"))
            bc["trades"] = bc["trades"][:300]
            r = score(bc, None, k=6, n_boot=200, draws=50, seed=7, cost=cost,
                      kinds=("lgbm_action_value", "logit_action_value"), checkins=("every_bar", "every_4+triggers"))
            res[spec] = r
            b0 = next(a for a in r["arms"] if a["arm_id"] == "B0_hold")
            checks.append((f"{spec}: B0 - B0 == 0 exactly", b0["delta_vs_b0_r"] == 0.0 and b0["b0_minus_b0_r"] == 0.0,
                           str(b0["delta_vs_b0_r"])))
            fid = r["engine_fidelity"]["share_within_tol"]
            checks.append((f"{spec}: engine replays B0 to the harness exit_r on >= 99% of trades", (fid or 0) >= 0.99,
                           str(fid)))
            # oracle >= every arm, per trade, for each single-action policy arm (recompute from the labels)
            labs, orc = r["_labs"], r["_oracle"]
            worst = max((np.nanmax(v) - orc[i]) for i, L in enumerate(labs) for v in L["labels"].values()
                        if len(v) and np.isfinite(v).any())
            checks.append((f"{spec}: action-value ceiling >= every labelled action per trade", worst <= 1e-12,
                           f"max excess {worst:.2e}"))
            # census oracle is first_passage_paths.census's own number
            T = r["_trades"]
            ev = [fpp.events(t, sorted({t['leg'] for t in T})) for t in T]
            checks.append((f"{spec}: census oracle == first_passage_paths.census",
                           r["oracle"]["census_best_close_saving_r_per_trade"] ==
                           fpp.census(T, ev)["__pooled__"]["oracle_best_close_saving_r_per_trade"], ""))
        # 2. positive / negative control on the learners
        lg = lambda spec: next((a for a in res[spec]["arms"] if a.get("arm_id") == "lgbm_action_value@every_bar"), {})  # noqa: E731
        pl, nl = lg("synthetic-planted"), lg("synthetic")
        if pl.get("read_state") == "unavailable":
            checks.append(("planted: lightgbm importable", False, pl.get("reason", "")))
        else:
            checks.append(("planted: lgbm action-value beats B0 (CI lower > 0)", pl.get("ci95", [0])[0] > 0,
                           f"{pl.get('delta_vs_b0_r')} {pl.get('ci95')}"))
            checks.append(("null: lgbm action-value does not pass on a driftless walk (CI lower <= 0)",
                           nl.get("read_state") == "measured" and nl["ci95"][0] <= 0,
                           f"null {nl.get('delta_vs_b0_r')} {nl.get('ci95')}"))
            lo = next((a for a in res["synthetic"]["arms"] if a.get("arm_id") == "logit_action_value@every_bar"), {})
            checks.append(("null: logit action-value does not pass on a driftless walk (CI lower <= 0)",
                           lo.get("read_state") == "measured" and lo["ci95"][0] <= 0,
                           f"null {lo.get('delta_vs_b0_r')} {lo.get('ci95')}"))
        # 3. cross-symbol purge: a train trade overlapping a test fold window is dropped whatever its symbol
        corp, meta = resolve_corpus("synthetic", work=Path(td))
        bc = build_corpus(corp, meta, cost_fn=cx)
        T = bc["trades"][:120]
        TR = [dict(t, symbol="OTHERUSDT", trade_key=t["trade_key"] + "|x") for t in T]
        fl = make_folds(T, TR, 6, False)
        leak = 0
        for f in fl["folds"]:
            lo, hi = pd.Timestamp(f["lo"]).value, pd.Timestamp(f["hi"]).value
            leak += sum(1 for i in f["train"] if TR[i]["entry_time"].value < hi and TR[i]["exit_time"].value >= lo)
        checks.append(("cross-symbol purge leaves no overlapping train trade", leak == 0 and all(f["n_purged"] for f in fl["folds"]),
                       f"{leak} leaks; purged {[f['n_purged'] for f in fl['folds']]}"))
        fl2 = make_folds(T, T, 6, False)
        checks.append(("same trade_key in train and test is de-duplicated", sum(f["n_dedup"] for f in fl2["folds"]) == 6 * len(T),
                       ""))
    ok = all(c[1] for c in checks)
    if verbose:
        for lbl, c, d in checks:
            print(f"  {'PASS' if c else 'FAIL'} {lbl} {d}")
        print("SELFCHECK", "PASS" if ok else "FAIL")
    return {"pass": ok, "checks": [{"check": a, "pass": bool(b), "detail": c} for a, b, c in checks]}


# --------------------------------------------------------------------------- driver
def _strip(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _strip(v) for k, v in d.items() if not str(k).startswith("_")}
    if isinstance(d, list):
        return [_strip(v) for v in d]
    return d


def _write(out: Path, v: Dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(_strip(v), indent=2, default=str) + "\n", encoding="utf-8")


def _load(spec: Optional[str], out: Path) -> Optional[Dict[str, Any]]:
    if not spec:
        return None
    corp, meta = resolve_corpus(spec, work=out)
    return build_corpus(corp, meta)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("selfcheck", "score", "transfer", "corpus"))
    ap.add_argument("--test-corpus", default="v1")
    ap.add_argument("--train-corpus", default=None, help="train on this corpus, test on --test-corpus (cross-symbol purge)")
    ap.add_argument("--rule", choices=("reproduce", "s_offline", "none"), default="none")
    ap.add_argument("--learners", default="lgbm_action_value,logit_action_value")
    ap.add_argument("--checkins", default=",".join(CHECKINS))
    ap.add_argument("--desk-policy", default=None, help="JSONL {state_id, action}: scored as B3")
    ap.add_argument("--fractions", default="0,0.25,1,4")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--random-draws", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--act-margin", type=float, default=ACT_MARGIN_R, help="lgbm: act if best predicted dR > this (R)")
    ap.add_argument("--logit-act-p", type=float, default=LOGIT_ACT_P, help="logit: act if best P(dR > 0) > this")
    ap.add_argument("--write-labels", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "selfcheck":
        sc = selfcheck()
        if a.out:
            _write(Path(a.out), {"verdict": "pass" if sc["pass"] else "fail", "read_state": "measured",
                                 "population": "synthetic first_passage_paths corpora (null and planted)", "n": None,
                                 "measurement": {"selfcheck": sc}, "note": "tm_bench selfcheck"})
        return 0 if sc["pass"] else 1
    out = Path(a.out or tempfile.mkdtemp(prefix="tm_bench_"))
    out.mkdir(parents=True, exist_ok=True)
    cost = _cost_policy
    if a.cmd == "corpus":
        corp, meta = resolve_corpus(a.test_corpus, work=out)
        bc = build_corpus(corp, meta)
        man = freeze(corp, bc, out / "corpus")
        print(json.dumps(man, indent=2))
        return 0
    sc = selfcheck(verbose=True)
    test = _load(a.test_corpus, out)
    train = _load(a.train_corpus, out)
    pop = (f"test corpus {test['corpus_id']} ({test['source']}): {len(test['trades'])} trades on "
           f"{sum(r['state'] == 'included' for r in test['legs'])} legs passing the peak_r==mfe_r parity control; "
           + (f"train corpus {train['corpus_id']} ({train['source']}), {len(train['trades'])} trades, cross-symbol purged; "
              if train else "") + f"as traded (harness paths), full cost stack, {a.folds} purged calendar folds by entry")
    meas: Dict[str, Any] = {"schema": SCHEMA, "selfcheck": sc, "test_corpus": {k: test[k] for k in
                            ("corpus_id", "source", "legs", "failed", "runs", "parity_ok")}}
    if train:
        meas["train_corpus"] = {k: train[k] for k in ("corpus_id", "source", "legs", "failed", "parity_ok")}
    verdict, why = "indeterminate", "no trades"
    if a.cmd == "transfer" and test["trades"] and train and train["trades"]:
        fr = [float(x) for x in a.fractions.split(",")]
        meas["transfer"] = transfer(test, train, fr, k=a.folds, n_boot=a.n_boot, seed=a.seed, cost=cost)
        why = "transfer is graded by its unit's registered rule (RULE-RQ20261029-7294-01-DATA-TRANSFER)"
        verdict = "indeterminate" if not sc["pass"] else "measured"
    elif a.cmd == "score" and test["trades"]:
        desk = None
        if a.desk_policy:
            desk = {r["state_id"]: r["action"] for r in _read_jsonl(Path(a.desk_policy))}
        r = score(test, train, k=a.folds, n_boot=a.n_boot, draws=a.random_draws, seed=a.seed, cost=cost,
                  kinds=[s for s in a.learners.split(",") if s], desk_policy=desk,
                  checkins=[s for s in a.checkins.split(",") if s], act_margin_r=a.act_margin, logit_act_p=a.logit_act_p)
        if a.write_labels:
            with gzip.open(out / "labels.jsonl.gz", "wt", encoding="utf-8") as fh:
                for t, L in zip(r["_trades"], r["_labs"]):
                    for s in range(t["bars"] - 1):
                        fh.write(json.dumps({"state_id": f"{t['trade_key']}@{int(t['off'][s])}", **{
                            act: (None if not np.isfinite(L["labels"][act][s]) else round(float(L["labels"][act][s]), 6))
                            for act in ACTIONS}}) + "\n")
        (out / "folds.json").write_text(json.dumps({"corpus_id": r["corpus_id"], "train_corpus_id": r["train_corpus_id"],
                                                    **r["folds"], "fold_assignment": r["fold_assignment"]}, indent=1) + "\n")
        r.pop("fold_assignment")
        meas.update(r)
        b0 = next(x for x in r["arms"] if x["arm_id"] == "B0_hold")
        orc = r["oracle"]["census_best_close_saving_r_per_trade"]
        for arm in r["arms"]:
            if arm.get("arm_id", "").startswith(("lgbm_", "logit_")) and arm.get("read_state") == "measured":
                arm["s_offline"] = dict(zip(("verdict", "why"), s_offline(arm, r["arms"])))
        if a.rule == "reproduce":
            parts = [f"selfcheck {'pass' if sc['pass'] else 'FAIL'}", f"B0-B0 {b0['b0_minus_b0_r']}",
                     f"census oracle {orc} vs {ORACLE_TARGET_R} +- {ORACLE_TOL_R}", f"n {len(test['trades'])}"]
            if not sc["pass"] or not test["parity_ok"]:
                verdict = "indeterminate"
            elif b0["b0_minus_b0_r"] == 0.0 and orc is not None and abs(orc - ORACLE_TARGET_R) <= ORACLE_TOL_R:
                verdict = "pass"
            else:
                verdict = "fail"
            why = "; ".join(parts)
        elif a.rule == "s_offline":
            vs = [x["s_offline"]["verdict"] for x in r["arms"] if "s_offline" in x]
            verdict = ("pass" if any(v.startswith("pass") for v in vs) else
                       "fail" if vs and all(v == "fail" for v in vs) else "indeterminate")
            why = f"S-OFFLINE per learner arm: {vs}"
        else:
            verdict, why = "measured", "scored; no rule applied"
    v = {"verdict": verdict, "read_state": "measured" if test["trades"] else "unmeasured", "population": pop,
         "n": len(test["trades"]), "measurement": meas, "note": f"tm_bench {a.cmd}/{a.rule}: {why}"}
    _write(out, v)
    print(v["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

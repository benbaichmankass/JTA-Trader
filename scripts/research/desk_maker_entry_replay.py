#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-18F-MAKER-FILLS and by research/queue/blocked/RQ-20261030-f18f-01 (research-script-run.yml, once the manager releases it); no schedule consumes it.
"""DESK-18F-MAKER-FILLS -- do the desk's judged-1 ENTRIES clear the S3 bar when they enter as maker (limit) fills?

Question (operator 2026-10-30 ~20:45Z, popup answer "Maker fills"): judged-1 entered at the market and its S3 was +0.006 R
(row DESK-18C-EDGE-OPT). Re-enter the SAME 8xx valid proposals with a resting limit and score them against a random entry
that uses the SAME maker model, net of the full cost stack. An arm clears iff S3 >= +0.25 R with the CI lower bound > 0.

Reuses, does not rewrite, the certified instrument: ``desk_gen_replay_driver.simulate`` (limit fills only when price trades
THROUGH the level inside the window, a fill bar credits no target, stop before target in a bar, gap fills at the open) and
``execution_costs.roundtrip_cost_r``. This module only (1) builds the maker entry from a proposal, (2) reprices the entry leg,
(3) counts non-fills as NO TRADE (0 R, kept in the denominator) on both sides of the pair, (4) takes the weekly-cluster CI.

MAKER ENTRY MODEL (registered in research/queue/blocked/RQ-20261030-f18f-01.yaml before the first score):
  limit  L = E - side * offset * ATR14(cutoff)   E = the proposal's entry level (a market proposal: the cutoff close)
  window W bars after the cutoff (the order is cancelled after W bars); stop and target keep the PROPOSAL'S ABSOLUTE LEVELS
  fill   only if a bar's low (long) / high (short) trades STRICTLY through L; a gap fills at the open (better than L)
  fee    maker on the entry leg (MAKER_FEE_BPS, PUBLISHED, UNVERIFIED on our account), the venue taker fee on the exit leg
  slip   the cost policy's round-trip slippage halves: the entry leg is 0 (a limit fills at its price), the exit leg is kept
  funding, the exit and the horizon (counted from the FILL bar) are unchanged

ADVERSE-SELECTION BIAS, stated (printed into every verdict):
  * the filled limits are the ones price came back to; the ones price ran away from (the profitable ones for a trend entry) are
    NO-TRADE and count 0 R in the denominator of both the desk and the random baseline, so the bias is priced, not dropped;
  * a 1h bar gives no intrabar order: on the fill bar the stop is checked first and the target is not credited (pessimistic);
  * a print one price step through L is not observable on 1h bars; low < L (long) / high > L (short) is the test (strict);
  * not modelled: latency, queue position (moot under a strict trade-through), post-only rejects, partial fills.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "ci", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import desk_gen_replay_driver as gr  # noqa: E402  (the certified replay engine; reused, not rewritten)
from src.runtime import execution_costs as xc  # noqa: E402

UNIT_ID = "RQ-20261030-f18f-01"
RULE_ID = "RULE-RQ20261030-F18F-01-DESK-MAKER-ENTRY"

# ----------------------------------------------------------------------------- registered numbers (not tunable)
MAKER_FEE_BPS = 2.0                 # per side; Bybit published non-VIP schedule, UNVERIFIED on our account (zero maker fills ever)
S3_BAR = 0.25                       # R, relative to the same-model random entry
N_ARMS = 2                          # decisive arms -> Bonferroni: the decisive CI is the 97.5% one
WINDOW_BARS = 4
ARMS = {                            # name -> limit offset inside the proposal's entry, in ATR14 at the cutoff
    "A_at_entry": 0.0,
    "B_inside_0.25atr": 0.25,
}
SENS_MAKER_FEE = (3.5, 5.5)         # reported, not decisive; 5.5 = no fee advantage at all (isolates the fill-price effect)
SENS_WINDOWS = (1, 12)
SENS_OFFSET = (0.5,)
DRAWS = 200                         # random-entry draws per proposal (as the registered S3)
BOOT = 10_000
SEED = gr.SEED                      # 20261026, as the registered S3


# ----------------------------------------------------------------------------- pricing
def price(t: gr.Trade, s: gr.Series, *, entry_fee_bps: float, entry_slip_bps: float) -> Optional[float]:
    """Net R of a FILLED trade re-costed with the given entry-leg fee/slip; the exit leg keeps the taker fee and half the slip.
    entry_fee_bps/entry_slip_bps are per-leg bps. None when the trade did not fill."""
    if t.state != "filled":
        return None
    fee_rt = entry_fee_bps + s.fee_bps / 2.0
    slip_rt = entry_slip_bps + s.slip_bps / 2.0
    cost = xc.roundtrip_cost_r(
        entry=t.fill_px, exit_price=t.exit_px, risk=t.risk,
        entry_time=datetime.fromtimestamp(int(s.t[t.fill_i]), tz=timezone.utc).isoformat(),
        exit_time=datetime.fromtimestamp(int(s.t[t.exit_i]) + gr.SEC, tz=timezone.utc).isoformat(),
        fee_bps_roundtrip=fee_rt, slippage_bps_roundtrip=slip_rt, funding_bps_per_window=s.fund_bps)
    if not cost["total_cost_r"] > 0:
        raise AssertionError("zero cost on a filled trade")
    return t.gross_r - cost["total_cost_r"]


@dataclass
class Variant:
    name: str
    etype: str              # market | limit
    offset: float           # ATR14 inside E
    window: int             # bars
    entry_fee_bps: float    # per leg
    entry_slip_bps: float   # per leg


def make_variant(name: str, etype: str, offset: float, window: int, maker_fee: float, keep_entry_slip: bool, s_ref: gr.Series
                 ) -> Variant:
    return Variant(name, etype, offset, window, maker_fee, s_ref.slip_bps / 2.0 if keep_entry_slip else 0.0)


def run_trade(s: gr.Series, i: int, side: float, E: float, stop: float, tp: float, horizon: int, v: Variant) -> gr.Trade:
    """The bracket (absolute levels) decided at the close of bar i, entered per variant."""
    if v.etype == "market":
        return gr.simulate(s, i, side, "market", E, stop, tp, 1, horizon)
    a = float(s.atr[i])
    L = E - side * v.offset * a
    return gr.simulate(s, i, side, "limit", L, stop, tp, v.window, horizon)


def net_of(t: gr.Trade, s: gr.Series, v: Variant, taker_entry: bool) -> Optional[float]:
    """Slot value: net R if filled, 0.0 for a NO-TRADE (unfilled / refused), None for unresolved (data end: excluded, counted)."""
    if t.state == "unresolved":
        return None
    if t.state != "filled":
        return 0.0
    if taker_entry:
        return t.net_r                      # the driver's own number (s.fee_bps, s.slip_bps): the control reproduces judged-1
    return price(t, s, entry_fee_bps=v.entry_fee_bps, entry_slip_bps=v.entry_slip_bps)


def baseline(s: gr.Series, g: dict, pool: np.ndarray, rng: np.random.Generator, v: Variant, taker_entry: bool
             ) -> Dict[str, Any]:
    """Random entries with the proposal's geometry at random eligible cutoffs of the same symbol and fold, SAME entry model.
    slot_mean counts non-fills as 0 R (the fair pair of a desk slot); filled_mean is the old per-fill statistic."""
    slots, fills, unres, nofill = [], [], 0, 0
    if not len(pool):
        return {"slot_mean": None, "filled_mean": None, "fill_rate": None, "n": 0}
    for j in rng.choice(pool, size=DRAWS, replace=True):
        j = int(j)
        a = float(s.atr[j])
        if not np.isfinite(a) or a <= 0:
            continue
        side, E = g["side"], float(s.c[j])
        t = run_trade(s, j, side, E, E - side * g["sl_atr"] * a, E + side * g["tp_atr"] * a, g["horizon"], v)
        x = net_of(t, s, v, taker_entry)
        if x is None:
            unres += 1
            continue
        slots.append(x)
        if t.state == "filled":
            fills.append(x)
        else:
            nofill += 1
    return {"slot_mean": float(np.mean(slots)) if slots else None, "filled_mean": float(np.mean(fills)) if fills else None,
            "fill_rate": (len(fills) / len(slots)) if slots else None, "n": len(slots), "unresolved": unres}


# ----------------------------------------------------------------------------- scoring
def week_cluster_mean(vals: List[float], weeks: List[str], seed: int = SEED, draws: int = BOOT, alpha: float = 0.05
                      ) -> Dict[str, Any]:
    if not vals:
        return {"n": 0, "mean": None, "ci": [None, None]}
    wk = sorted(set(weeks))
    ix = {w: k for k, w in enumerate(wk)}
    sm, ct = np.zeros(len(wk)), np.zeros(len(wk))
    for x, w in zip(vals, weeks):
        sm[ix[w]] += x
        ct[ix[w]] += 1
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(wk), size=(draws, len(wk)))
    d = sm[pick].sum(axis=1) / ct[pick].sum(axis=1)
    lo, hi = np.percentile(d, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"n": len(vals), "weeks": len(wk), "mean": float(np.mean(vals)), "ci": [float(lo), float(hi)], "alpha": alpha}


def score_variant(mkt: Dict[str, gr.Series], keys: dict, by: dict, v: Variant, taker_entry: bool, seed: int = SEED
                  ) -> Dict[str, Any]:
    rng = np.random.default_rng(seed + 7)
    pools: Dict[Tuple[str, int], np.ndarray] = {}
    rows: List[dict] = []
    c = {"proposals": 0, "filled": 0, "unfilled": 0, "refused": 0, "unresolved": 0, "no_atr": 0}
    for pid, lst in by.items():
        key = keys[pid]
        ce = key["cutoff_epoch"]
        for row in lst:
            pr = row["proposal"]
            sym = key["alias"][pr["symbol"]]
            sc = float(key["price_scale"][pr["symbol"]])
            s = mkt[sym]
            i = s.last_closed(ce)
            side = 1.0 if pr["side"] == "long" else -1.0
            E, stp, tpl = pr["entry"]["level"] / sc, pr["stop"]["level"] / sc, pr["tp"]["level"] / sc
            a = float(s.atr[i]) if np.isfinite(s.atr[i]) else float("nan")
            c["proposals"] += 1
            if not np.isfinite(a) or a <= 0:
                c["no_atr"] += 1
                continue
            t = run_trade(s, i, side, E, stp, tpl, pr["horizon_bars"], v)
            x = net_of(t, s, v, taker_entry)
            if x is None:
                c["unresolved"] += 1
                continue
            c[t.state] = c.get(t.state, 0) + 1
            g = {"side": side, "sl_atr": side * (E - stp) / a, "tp_atr": side * (tpl - E) / a, "horizon": pr["horizon_bars"]}
            pk = (sym, key["fold"])
            if pk not in pools:
                pools[pk] = gr.eligible_cutoffs(s, gr.WINDOW_START, gr.WINDOW_END, key["fold"])
            b = baseline(s, g, pools[pk], rng, v, taker_entry)
            if b["slot_mean"] is None:
                continue
            rows.append({"week": gr.iso_week(ce), "fold": key["fold"], "symbol": sym, "side": pr["side"], "net": x,
                         "filled": t.state == "filled", "base_slot": b["slot_mean"], "base_filled": b["filled_mean"],
                         "base_fill_rate": b["fill_rate"], "d_slot": x - b["slot_mean"],
                         "d_filled": (x - b["filled_mean"]) if t.state == "filled" and b["filled_mean"] is not None else None})
    n = len(rows)
    wk = [r["week"] for r in rows]
    out: Dict[str, Any] = {"variant": v.name, "counts": c, "n_slots": n}
    if not n:
        return out
    filled = [r for r in rows if r["filled"]]
    out["fill_rate"] = len(filled) / n
    out["baseline_fill_rate"] = float(np.mean([r["base_fill_rate"] for r in rows if r["base_fill_rate"] is not None]))
    out["random_null_slot_mean_R"] = float(np.mean([r["base_slot"] for r in rows]))
    out["desk_slot_mean_R"] = float(np.mean([r["net"] for r in rows]))
    out["S3_slot"] = {"ci95": week_cluster_mean([r["d_slot"] for r in rows], wk),
                      "ci97.5": week_cluster_mean([r["d_slot"] for r in rows], wk, alpha=0.025)}
    out["S1_slot"] = week_cluster_mean([r["net"] for r in rows], wk)
    if filled:
        fw = [r["week"] for r in filled]
        out["S1_filled"] = week_cluster_mean([r["net"] for r in filled], fw)
        dd = [(r["d_filled"], r["week"]) for r in filled if r["d_filled"] is not None]
        out["S3_filled"] = week_cluster_mean([d for d, _ in dd], [w for _, w in dd])
    out["by_fold_S3_slot"] = {str(f): float(np.mean([r["d_slot"] for r in rows if r["fold"] == f]))
                              for f in sorted({r["fold"] for r in rows})}
    out["by_side"] = {sd: {"n": sum(1 for r in rows if r["side"] == sd),
                           "S3_slot": float(np.mean([r["d_slot"] for r in rows if r["side"] == sd]))}
                      for sd in ("long", "short") if any(r["side"] == sd for r in rows)}
    sd_ = float(np.std([r["d_slot"] for r in rows], ddof=1))
    out["sd_d_slot"] = sd_
    out["mde_R_iid"] = 2.8 * sd_ / math.sqrt(n)
    return out


def decide(res: Dict[str, Any]) -> Dict[str, Any]:
    """The registered rule, per decisive arm: CLEARS iff S3_slot mean >= S3_BAR AND the 97.5% cluster CI lower bound > 0."""
    arms = {}
    for name in ARMS:
        r = res["arms"][name]
        s3 = r["S3_slot"]
        arms[name] = {"S3_slot": s3["ci95"]["mean"], "ci97.5": s3["ci97.5"]["ci"],
                      "clears": bool(s3["ci95"]["mean"] >= S3_BAR and s3["ci97.5"]["ci"][0] > 0)}
    any_clear = any(a["clears"] for a in arms.values())
    return {"arms": arms, "verdict": "S3_CLEARED" if any_clear else "S3_NOT_CLEARED",
            "reopens_DESK_18D": any_clear}


def load_judged_tolerant(a: argparse.Namespace, mkt: Dict[str, gr.Series], classes: Dict[str, List[str]]):
    """gr._load_judged WITHOUT its abort on a packet-sha mismatch. MEASURED 2026-10-30: every re-derived judged-1 packet keeps its
    id but has a different sha (candle/builder drift since 2026-10-27; git history is shallow so the cause is not established).
    The drift is COUNTED and printed, and the replacement evidence is `control_reproduction`: the market-entry control must
    reproduce the committed per-proposal net R of judged-1-decomposition/records.jsonl, else the verdict is INDETERMINATE."""
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    want = {json.loads(ln)["packet_id"] for ln in Path(a.proposals).read_text().splitlines() if ln.strip()}
    packets, drift = {}, 0
    for pid in sorted(want & set(keys)):
        k = keys[pid]
        m, _ = gr.build_masked_packet(mkt, classes, k["cutoff_epoch"], k["index"], a.seed)
        if m["meta"]["packet_id"] != pid:
            raise ValueError(f"packet id changed for {pid}")
        drift += int(bool(k.get("packet_sha")) and gr.cdr.packet_sha(m) != k["packet_sha"])
        packets[pid] = m
    by, intake = gr.read_proposals(Path(a.proposals), packets)
    intake["packet_sha_drift"] = drift
    intake["packets_rederived"] = len(packets)
    intake["valid_proposals"] = sum(len(v) for v in by.values())
    return keys, packets, by, intake


def control_reproduction(mkt, keys, by) -> Dict[str, Any]:
    """Market-entry control vs the committed judged-1 records, per (packet, symbol, side).
    MEASURED 2026-10-30: the PATH reproduces exactly (exit reason and days) but the committed net R is a CONSTANT number of bps cheaper than
    today's cost policy (execution_costs / dsp.cost_policy), so the registered clause is: every exit reason and days match, and the
    implied round-trip cost gap (net-R gap / (avg price / risk), in bps) is one constant (sd < 0.01 bps). The constant is reported; the
    run is scored under TODAY's policy for desk and baseline alike."""
    rec = {}
    for ln in (REPO / "comms/research/desk_gen_replay/judged-1-decomposition/records.jsonl").read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            rec[(r["packet_id"], r["symbol"], r["side"])] = r
    gaps, path_bad, n = [], 0, 0
    for pid, lst in by.items():
        key = keys[pid]
        for row in lst:
            pr = row["proposal"]
            sym, sc = key["alias"][pr["symbol"]], float(key["price_scale"][pr["symbol"]])
            s = mkt[sym]
            i = s.last_closed(key["cutoff_epoch"])
            side = 1.0 if pr["side"] == "long" else -1.0
            t = gr.simulate(s, i, side, "market", pr["entry"]["level"] / sc, pr["stop"]["level"] / sc, pr["tp"]["level"] / sc, 1,
                            pr["horizon_bars"])
            r = rec.get((pid, sym, pr["side"]))
            if t.state != "filled" or r is None:
                path_bad += 1
                continue
            n += 1
            if t.reason != r["exit"] or abs(t.days - r["days"]) > 1e-9:
                path_bad += 1
            per_r = (abs(t.fill_px) + abs(t.exit_px)) / 2.0 / t.risk
            gaps.append((t.net_r - r["net_r"]) / per_r * 1e4)
    g = np.array(gaps)
    sd = float(g.std()) if len(g) else float("nan")
    return {"committed_filled": len(rec), "replayed_filled": n, "path_mismatch_or_missing": path_bad,
            "implied_cost_gap_bps_mean": float(g.mean()) if len(g) else None, "implied_cost_gap_bps_sd": sd,
            "reproduces": bool(rec) and n == len(rec) and path_bad == 0 and sd < 0.01}


def cmd_run(a: argparse.Namespace) -> int:
    mkt, missing, classes, note, src = gr._prepare(a)
    if missing:
        print(json.dumps({"error": f"candles missing for {missing}"}))
        return 2
    keys, packets, by, intake = load_judged_tolerant(a, mkt, classes)
    s_ref = next(iter(mkt.values()))
    res: Dict[str, Any] = {"unit": UNIT_ID, "rule": RULE_ID, "intake": intake, "candles": src, "arms": {}, "sensitivities": {}}
    res["control_reproduction"] = control_reproduction(mkt, keys, by)
    print(json.dumps({"intake": intake, "control_reproduction": res["control_reproduction"]}), flush=True)
    if a.intake_only:
        return 0
    ctrl = Variant("control_market_taker", "market", 0.0, 1, 0.0, 0.0)
    res["control_market"] = score_variant(mkt, keys, by, ctrl, True, a.seed)
    for name, off in ARMS.items():
        res["arms"][name] = score_variant(mkt, keys, by, make_variant(name, "limit", off, WINDOW_BARS, MAKER_FEE_BPS, False, s_ref),
                                          False, a.seed)
    for fee in SENS_MAKER_FEE:
        for name, off in ARMS.items():
            res["sensitivities"][f"{name}|maker_fee={fee}"] = score_variant(
                mkt, keys, by, make_variant(name, "limit", off, WINDOW_BARS, fee, False, s_ref), False, a.seed)
    for name, off in ARMS.items():
        res["sensitivities"][f"{name}|entry_slip_kept"] = score_variant(
            mkt, keys, by, make_variant(name, "limit", off, WINDOW_BARS, MAKER_FEE_BPS, True, s_ref), False, a.seed)
    for w in SENS_WINDOWS:
        for name, off in ARMS.items():
            res["sensitivities"][f"{name}|window={w}"] = score_variant(
                mkt, keys, by, make_variant(name, "limit", off, w, MAKER_FEE_BPS, False, s_ref), False, a.seed)
    for off in SENS_OFFSET:
        res["sensitivities"][f"offset={off}"] = score_variant(
            mkt, keys, by, make_variant(f"offset={off}", "limit", off, WINDOW_BARS, MAKER_FEE_BPS, False, s_ref), False, a.seed)
    res["decision"] = decide(res)
    if not res["control_reproduction"]["reproduces"]:
        res["decision"]["verdict"] = "INDETERMINATE_INSTRUMENT_DID_NOT_REPRODUCE"
        res["decision"]["reopens_DESK_18D"] = False
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "maker_entry_result.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=float))
    brief = {k: {"fill": v.get("fill_rate"), "S1_slot": (v.get("S1_slot") or {}).get("mean"),
                 "S3_slot": ((v.get("S3_slot") or {}).get("ci95") or {}).get("mean"),
                 "ci97.5": ((v.get("S3_slot") or {}).get("ci97.5") or {}).get("ci"),
                 "null": v.get("random_null_slot_mean_R")} for k, v in {**{"control": res["control_market"]}, **res["arms"]}.items()}
    print(json.dumps({"decision": res["decision"], "brief": brief}, indent=1, default=float))
    return 0


# ----------------------------------------------------------------------------- self-test (planted known answers; scores no proposal)
def _synthetic(o, h, l, c) -> gr.Series:  # noqa: E741
    n = len(o)
    return gr.Series("TESTUSDT", np.arange(n, dtype=np.int64) * gr.SEC, np.array(o, float), np.array(h, float),
                     np.array(l, float), np.array(c, float), np.full(n, 1.0), 11.0, 3.0, 0.0)


def cmd_selftest(_a: argparse.Namespace) -> int:
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= cond
        print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")

    # bar 0 = cutoff bar (close 100, ATR 1). Short, stop 101, target 98.
    #  (1) bar 1 trades up through the at-entry limit (high 100.5 > 100) then falls through the target -> filled, TP.
    s = _synthetic([100, 99.9, 99.5, 99, 99], [100, 100.5, 99.8, 99.2, 99.2], [100, 99.4, 97.9, 98.5, 98.5], [100, 99.5, 98, 99, 99])
    vA = make_variant("A", "limit", 0.0, 4, 2.0, False, s)
    t = run_trade(s, 0, -1.0, 100.0, 101.0, 98.0, 4, vA)
    check("short limit at entry fills when price trades through", t.state == "filled" and t.fill_i == 1, f"state={t.state} fi={t.fill_i}")
    check("fill bar credits no target (target exits the NEXT bar)", t.state == "filled" and t.exit_i == 2 and t.reason == "tp", f"exit_i={t.exit_i} {t.reason}")
    mk = gr.simulate(s, 0, -1.0, "market", 100.0, 101.0, 98.0, 1, 4)
    pm, pk = price(t, s, entry_fee_bps=2.0, entry_slip_bps=0.0), net_of(mk, s, vA, True)
    check("maker entry leg is cheaper than the taker entry leg on the same path", pm is not None and pk is not None and t.gross_r >= mk.gross_r - 1e-9 and pm > pk - 0.5,
          f"maker_net={pm:.4f} taker_net={pk:.4f}")
    fee_gap_bps = (5.5 - 2.0) + 1.5
    exp = fee_gap_bps / 1e4 * ((abs(t.fill_px) + abs(t.exit_px)) / 2.0 / t.risk)
    cost_t = xc.roundtrip_cost_r(entry=t.fill_px, exit_price=t.exit_px, risk=t.risk, entry_time=None, exit_time=None,
                                 fee_bps_roundtrip=11.0, slippage_bps_roundtrip=3.0)["total_cost_r"]
    cost_m = xc.roundtrip_cost_r(entry=t.fill_px, exit_price=t.exit_px, risk=t.risk, entry_time=None, exit_time=None,
                                 fee_bps_roundtrip=7.5, slippage_bps_roundtrip=1.5)["total_cost_r"]
    check("cost arithmetic: taker-minus-maker cost = (3.5 fee + 1.5 slip) bps x price/risk", abs((cost_t - cost_m) - exp) < 1e-9, f"{cost_t - cost_m:.6f} vs {exp:.6f}")
    #  (2) price runs away (never trades above 100) -> NO TRADE, counted as 0 R, not dropped.
    s2 = _synthetic([100, 99.8, 99, 98, 98], [100, 99.9, 99.2, 98.2, 98.2], [100, 99.0, 97.8, 97.5, 97.5], [100, 99, 98, 98, 98])
    t2 = run_trade(s2, 0, -1.0, 100.0, 101.0, 98.0, 4, vA)
    check("ran-away entry is unfilled and scores 0.0 R (kept in the denominator)", t2.state == "unfilled" and net_of(t2, s2, vA, False) == 0.0,
          f"state={t2.state}")
    #  (3) a touch exactly AT the limit does not fill (strict trade-through).
    s3 = _synthetic([100, 99.8, 99, 98, 98], [100, 100.0, 99.2, 98.2, 98.2], [100, 99.0, 97.8, 97.5, 97.5], [100, 99, 98, 98, 98])
    t3 = run_trade(s3, 0, -1.0, 100.0, 101.0, 98.0, 4, vA)
    check("a print exactly AT the limit does not fill (strict)", t3.state == "unfilled", f"state={t3.state}")
    #  (4) a gap through the limit fills at the open (better than L).
    s4 = _synthetic([100, 100.6, 99, 98, 98], [100, 100.8, 99.2, 98.2, 98.2], [100, 100.2, 97.8, 97.5, 97.5], [100, 100.4, 98, 98, 98])
    t4 = run_trade(s4, 0, -1.0, 100.0, 101.5, 98.0, 4, vA)
    check("a gap through the limit fills at the open", t4.state == "filled" and abs(t4.fill_px - 100.6) < 1e-9, f"fill_px={t4.fill_px}")
    #  (5) offset inside: B waits for 100.25.
    vB = make_variant("B", "limit", 0.25, 4, 2.0, False, s)
    tB = run_trade(s, 0, -1.0, 100.0, 101.0, 98.0, 4, vB)
    check("offset-inside limit (100.25) does not fill when the high is 100.5? it DOES (100.5 > 100.25), at 100.25",
          tB.state == "filled" and abs(tB.fill_px - 100.25) < 1e-9, f"state={tB.state} fill_px={tB.fill_px}")
    #  (6) bootstrap sanity: a constant has a degenerate CI at that constant.
    r = week_cluster_mean([0.3] * 30, ["2026-W01"] * 10 + ["2026-W02"] * 10 + ["2026-W03"] * 10)
    check("cluster CI of a constant is that constant", abs(r["mean"] - 0.3) < 1e-12 and abs(r["ci"][0] - 0.3) < 1e-9 and abs(r["ci"][1] - 0.3) < 1e-9)
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    st = sub.add_parser("selftest")
    st.set_defaults(fn=cmd_selftest)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--fetch", action="store_true")
    r.add_argument("--candles-dir")
    r.add_argument("--seed", type=int, default=SEED)
    r.add_argument("--proposals", default=str(REPO / "comms/research/desk_gen_replay/judged-1/proposals.jsonl"))
    r.add_argument("--mask-key", default=str(REPO / "comms/research/desk_gen_replay/judged-1/mask-key.json"))
    r.add_argument("--packets", default=None)
    r.add_argument("--intake-only", action="store_true", help="re-derive, count valid proposals, check the control; score NO maker arm")
    r.set_defaults(fn=cmd_run)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

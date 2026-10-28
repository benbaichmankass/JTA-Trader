#!/usr/bin/env python3
# wiring: manual-only - run by the judging lane (`entries`, `step`, `score`) and by research/queue RQ-20261028-d1f5-01 (`selfcheck`) via research-script-run.yml; no schedule consumes it.
"""DESK-LIFECYCLE-S0 -- the desk's FULL-LIFECYCLE factorial replay: every trade runs bar by bar from entry to close.

Operator 2026-10-28 ~06:10Z (paraphrased by the manager, binding for the lane): the desk's edge test must be a FULL RUN of
each trade from entry to close, not one step in isolation, so we learn WHERE the value is (entry vs management vs exit)
and HOW to combine the desk with the existing strategies. Design + pre-registration:
docs/research/desk-lifecycle-factorial-2026-10-28.md, units research/queue/RQ-20261028-d1f5-01 (self-check) and
research/queue/blocked/RQ-20261028-d1f5-02 (the factorial), -03 (the live 60-min contract).

COMPOSES, never rewrites: scripts/research/desk_gen_replay_driver.py (the 1h market, the bracket engine `simulate`, the
judged-1 intake and its masked-packet re-derivation, the random-entry transplant, the fold and week definitions) and
src/runtime/execution_costs.py (the full cost stack). Tier 1 research tooling: reads candles and committed evidence,
writes only under --out.

THE FACTORIAL (contract C48: 1h bars, the entry's own bracket and 48-bar time stop)
-------------------------------------------------------------------------------
ENTRY factor     claude  = the committed judged-1 fills (comms/research/desk_gen_replay/judged-1; 732, re-derived and
                           checked against e535-03's landed mean), sampled with a registered seed for a pilot;
                 random  = ONE matched partner per claude entry: same symbol, same fold, same side, same bracket in ATR
                           units, at a random eligible cutoff (the driver's `transplant`), so frequency, direction and
                           geometry match the e535 random-entry baseline;
                 strategy = the committed Stage-0 legs (registered in -02; the in-trade slice is RQ-20261026-bf56-02/-03,
                           lane DESK-MGMT-S0; not built here).
MANAGEMENT       hold    = the bracket + time stop, untouched (== desk_gen_replay_driver.simulate, verified per trade);
factor           claude  = a decision at every registered CHECKPOINT the trade is still open at (bars held = round(f x
                           horizon), f in CHECKPOINT_FRACS -> 4, 12, 24, 36 of 48), decided on a MASKED packet, effective
                           from the NEXT bar: hold | tighten_sl r | widen_sl r | move_tp r | partial_close | close.
                 static  = a fixed menu of rules applied at the same checkpoints (no judging); the best one chosen
                           leave-one-fold-out is B3, the bar Claude's judgement must clear to be called judgement.
CHAINING         A checkpoint packet exists only if the trade is still open under the decisions already made, so
                 judging runs in ROUNDS: `step` replays every trade under the decisions so far and writes the packets
                 now due; judges answer; `step` again until nothing is pending. Deterministic and resumable.

REPLAY RULES     As `simulate`: SL before TP inside a bar, a gap fills at the open, a limit/stop fill bar credits no TP,
                 time stop at the close of bar fill + horizon - 1. A moved stop/target applies from the bar after the
                 decision. close / partial_close fill at the next bar's open (partial = 50 %, once per trade). Net R per
                 piece = side x (exit - fill) / initial risk minus execution_costs.roundtrip_cost_r(fee, resolve_cost_policy
                 slippage + funding) on that piece; pieces are weighted by size. A tighten that fills its stop pays no
                 extra charge here (the original stop pays none either); --stop-fill-slip-r reports a sensitivity.
INFERENCE        Weekly-cluster bootstrap over the claude entry's ISO week (the pair is the unit), 10,000 draws.

MODES
-----
  entries   --out DIR [--pilot-n N] [--fetch]       claude entries (all fills, or a seeded pilot sample) + matched random
  step      --out DIR --entries F [--decisions F]   writes round packets (masked) + their key; prints what is pending
  score     --out DIR --entries F --decisions F     every cell, both main effects, the interaction, B3, verdict labels
  selfcheck --out DIR [--fetch]                     unit d1f5-01: hold == simulate, judged-1 reproduction, no-lookahead,
                                                    leak scan + positive control, planted oracle / anti-oracle / null

STATED LIMITS (printed into every verdict)
* Six crypto USD-M perps, Binance Vision 1h klines; the desk's venue is Bybit. Funding is charged by the cost stack, not seen.
* C48 is NOT the live desk contract (60-min cap): it is the contract the committed Claude entries were judged under.
* The random partner's own week differs from its pair's; clustering on the pair's week is an approximation, stated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.research import desk_gen_replay_driver as g  # noqa: E402  (market, engine, intake, transplant)
from src.runtime import execution_costs as xc  # noqa: E402

# ----------------------------------------------------------------------------- registered numbers
# Registered in research/queue/RQ-20261028-d1f5-01 and research/queue/blocked/RQ-20261028-d1f5-02 on 2026-10-28,
# before any management decision was judged. Not tunable after a result.
SEED = 20261028
CHECKPOINT_FRACS = (1 / 12, 1 / 4, 1 / 2, 3 / 4)       # of the entry's horizon: 4, 12, 24, 36 bars held of 48
ACTIONS = ("hold", "tighten_sl", "widen_sl", "move_tp", "partial_close", "close")
LEVEL_ACTIONS = ("tighten_sl", "widen_sl", "move_tp")
WIDEN_FLOOR_R = -2.0                                  # a stop may be widened to at most 2 R of initial risk
TP_CAP_R = 10.0
MIN_GAP_R = 0.10                                      # a stop / target must sit >= 0.10 R from the decision close
PARTIAL_FRAC = 0.5
LOOKBACK_BARS = 48                                    # closed bars in a packet, ending at the checkpoint bar
STOP_FILL_SLIP_SENS_R = 0.05                          # sensitivity only: extra R per exit at a MOVED stop
BOOT_DRAWS = 10_000
FOLDS_NEEDED = 3                                      # of 4, each with n >= FOLD_MIN_N
FOLD_MIN_N = 20
N_MIN_PAIRS = 126                                     # the pass floor per management contrast (bf56's floor)
MAX_RANDOM_TRIES = 50
PILOT_N = 40
JUDGED1 = REPO / "comms" / "research" / "desk_gen_replay" / "judged-1"
E535_03_MEAN = 0.15886636006268712                    # landed: comms/research/RQ-20261026-e535-03/40603772459/verdict.json
E535_03_N = 732
E535_03_FEE_BPS = 7.5                                  # the fee policy e535-03 ran under (before #20783)
JUDGED1_VALID = 732                                   # landed intake: 732 propose_entry, 0 refused / over cap / duplicate


def checkpoints(horizon: int) -> List[int]:
    """Bars held at each registered checkpoint (unique, >= 1, < horizon)."""
    out: List[int] = []
    for f in CHECKPOINT_FRACS:
        c = max(1, int(round(f * horizon)))
        if c < horizon and c not in out:
            out.append(c)
    return out


# ----------------------------------------------------------------------------- entries
@dataclass
class Entry:
    entry_id: str
    source: str                  # claude | random
    pair_id: str
    symbol: str
    i: int                       # the cutoff bar (the decision to enter is taken at its close)
    side: float
    etype: str
    level: float
    stop: float
    tp: float
    good_till: int
    horizon: int
    fold: int
    week: str                    # the PAIR's week (the claude entry's cutoff week)
    own_week: str
    packet_id: str = ""          # judged-1 scan packet (claude) / "" (random)


def _eid(seed: int, source: str, pair_id: str) -> str:
    return "E-" + hashlib.sha256(f"{seed}|{source}|{pair_id}".encode()).hexdigest()[:12]


def claude_fills(mkt: Dict[str, g.Series], keys: Dict[str, dict], by: Dict[str, List[dict]]) -> List[Entry]:
    """Every valid judged-1 proposal that FILLS, in packet order. Mirrors desk_gen_replay_driver.score exactly."""
    out: List[Entry] = []
    for pid in sorted(by, key=lambda p: int(keys[p]["index"])):
        key = keys[pid]
        for r, row in enumerate(by[pid]):
            pr = row["proposal"]
            sym = key["alias"][pr["symbol"]]
            sc = float(key["price_scale"][pr["symbol"]])
            s = mkt[sym]
            i = s.last_closed(key["cutoff_epoch"])
            side = 1.0 if pr["side"] == "long" else -1.0
            lvl, stp, tpl = pr["entry"]["level"] / sc, pr["stop"]["level"] / sc, pr["tp"]["level"] / sc
            gt, hz = pr["entry"]["good_till_bars"], pr["horizon_bars"]
            t = g.simulate(s, i, side, pr["entry"]["type"], lvl, stp, tpl, gt, hz)
            if t.state != "filled":
                continue
            pair = f"{pid}#{r}"
            wk = g.iso_week(key["cutoff_epoch"])
            out.append(Entry(_eid(SEED, "claude", pair), "claude", pair, sym, i, side, pr["entry"]["type"], lvl, stp, tpl,
                             gt, hz, int(key["fold"]), wk, wk, pid))
    return out


def random_partner(mkt: Dict[str, g.Series], e: Entry, seed: int,
                   pools: Dict[Tuple[str, int], np.ndarray]) -> Optional[Entry]:
    """One random-timing partner: same symbol, fold, side and ATR-unit bracket; the first draw that fills. The draw is
    seeded per PAIR (seed + pair id), so a pair is the same pair in a pilot and in the full run."""
    rng = np.random.default_rng(int(hashlib.sha256(f"{seed}|{e.pair_id}".encode()).hexdigest()[:12], 16))
    s = mkt[e.symbol]
    geo = g.geometry_of(s, e.i, e.side, e.etype, e.level, e.stop, e.tp, e.good_till, e.horizon)
    if geo is None:
        return None
    pk = (e.symbol, e.fold)
    if pk not in pools:
        pools[pk] = g.eligible_cutoffs(s, g.WINDOW_START, g.WINDOW_END, e.fold)
    pool = pools[pk]
    if not len(pool):
        return None
    for _ in range(MAX_RANDOM_TRIES):
        j = int(rng.choice(pool))
        t = g.transplant(s, j, geo)
        if t is None or t.state != "filled":
            continue
        a = float(s.atr[j])
        level = float(s.c[j]) - e.side * geo["offset_atr"] * a
        stop = level - e.side * geo["sl_atr"] * a
        tp = level + e.side * geo["tp_atr"] * a
        return Entry(_eid(SEED, "random", e.pair_id), "random", e.pair_id, e.symbol, j, e.side, e.etype, level, stop, tp,
                     e.good_till, e.horizon, e.fold, e.week, g.iso_week(int(s.t[j]) + g.SEC))
    return None


# ----------------------------------------------------------------------------- the chained engine
@dataclass
class Pending:
    entry_id: str
    k: int                       # checkpoint ordinal
    j: int                       # the checkpoint bar (decision at its close)
    state: Dict[str, Any]


@dataclass
class Result:
    state: str                   # filled | unfilled | refused | unresolved
    net_r: float = float("nan")
    gross_r: float = float("nan")
    cost_r: float = float("nan")
    days: float = float("nan")
    exit_reason: str = ""
    pieces: List[Tuple[float, float, int, str]] = field(default_factory=list)
    decided: int = 0
    invalid: int = 0
    moved_stop_exit: bool = False
    actions: List[str] = field(default_factory=list)


def _state(s: g.Series, e: Entry, fill: float, fi: int, risk: float, kk: int, stop: float, tp: float,
           partial: bool, end: int) -> Dict[str, Any]:
    side = e.side
    seg_h, seg_l = s.h[fi:kk + 1], s.l[fi:kk + 1]
    fav = (seg_h.max() - fill) if side > 0 else (fill - seg_l.min())
    adv = (seg_l.min() - fill) if side > 0 else (fill - seg_h.max())
    return {"close_r": side * (float(s.c[kk]) - fill) / risk, "stop_r": side * (stop - fill) / risk,
            "tp_r": side * (tp - fill) / risk, "mfe_r": float(fav) / risk, "mae_r": float(adv) / risk,
            "bars_held": kk - fi + 1, "bars_left": end - kk, "partial_taken": partial}


def validate(act: Optional[dict], st: Dict[str, Any]) -> Tuple[str, Optional[float], bool]:
    """(action, level_r, valid). An invalid or missing decision is HOLD, and counted."""
    if not isinstance(act, dict) or act.get("action") not in ACTIONS:
        return "hold", None, False
    a = act["action"]
    if a in ("hold", "close"):
        return a, None, True
    if a == "partial_close":
        return ("partial_close", None, True) if not st["partial_taken"] else ("hold", None, False)
    x = act.get("level_r")
    if not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return "hold", None, False
    x = float(x)
    ok = {"tighten_sl": st["stop_r"] + 1e-9 < x <= st["close_r"] - MIN_GAP_R,
          "widen_sl": WIDEN_FLOOR_R <= x < st["stop_r"] - 1e-9 and x <= st["close_r"] - MIN_GAP_R,
          "move_tp": st["close_r"] + MIN_GAP_R <= x <= TP_CAP_R and abs(x - st["tp_r"]) > 1e-9}[a]
    return (a, x, True) if ok else ("hold", None, False)


Decider = Callable[[int, int, Dict[str, Any]], Optional[dict]]


def run(s: g.Series, e: Entry, decide: Optional[Decider] = None) -> Tuple[Result, Optional[Pending]]:
    """Replay `e` bar by bar. `decide(k, j, state)` returns the decision at checkpoint k (bar j), or None when it is
    not yet known -> (partial Result, Pending). decide=None is HOLD at every checkpoint (== g.simulate)."""
    t0 = g.simulate(s, e.i, e.side, e.etype, e.level, e.stop, e.tp, e.good_till, e.horizon)
    if t0.state != "filled":
        return Result(t0.state, exit_reason=t0.reason), None
    side, fill, fi, risk = e.side, t0.fill_px, t0.fill_i, t0.risk
    end = fi + e.horizon - 1
    ck = {fi + c - 1: k for k, c in enumerate(checkpoints(e.horizon))}
    stop, tp, size, partial = e.stop, e.tp, 1.0, False
    stop_moved = False
    res = Result("filled")
    pieces: List[Tuple[float, float, int, str]] = []
    nxt: Optional[Tuple[str, Optional[float]]] = None
    for kk in range(fi, end + 1):
        if nxt is not None:
            a, x = nxt
            nxt = None
            if a == "close":
                pieces.append((size, float(s.o[kk]), kk, "claude_close"))
                size = 0.0
                break
            if a == "partial_close":
                pieces.append((size * PARTIAL_FRAC, float(s.o[kk]), kk, "claude_partial"))
                size *= (1 - PARTIAL_FRAC)
                partial = True
            elif a in ("tighten_sl", "widen_sl"):
                stop, stop_moved = fill + side * x * risk, True
            elif a == "move_tp":
                tp = fill + side * x * risk
        sl_hit = (s.l[kk] <= stop) if side > 0 else (s.h[kk] >= stop)
        if sl_hit:
            gap = (s.o[kk] <= stop) if side > 0 else (s.o[kk] >= stop)
            px, why = (float(s.o[kk]), "gap_sl") if gap and kk > fi else (float(stop), "sl")
            pieces.append((size, px, kk, why))
            res.moved_stop_exit = stop_moved
            size = 0.0
            break
        credit_tp = (e.etype == "market") or kk > fi
        tp_hit = credit_tp and ((s.h[kk] >= tp) if side > 0 else (s.l[kk] <= tp))
        if tp_hit:
            gap = (s.o[kk] >= tp) if side > 0 else (s.o[kk] <= tp)
            px, why = (float(s.o[kk]), "gap_tp") if gap and kk > fi else (float(tp), "tp")
            pieces.append((size, px, kk, why))
            size = 0.0
            break
        if kk in ck and kk < end:
            k = ck[kk]
            st = _state(s, e, fill, fi, risk, kk, stop, tp, partial, end)
            act = None if decide is None else decide(k, kk, st)
            if decide is not None and act is None:
                return res, Pending(e.entry_id, k, kk, st)
            if decide is not None:
                a, x, ok = validate(act, st)
                res.decided += 1
                res.invalid += 0 if ok else 1
                res.actions.append(a)
                if a != "hold":
                    nxt = (a, x)
    if size > 0:
        pieces.append((size, float(s.c[end]), end, "timeout"))
    t_in = int(s.t[fi])
    gross = cost = days = 0.0
    for frac, px, xi, _why in pieces:
        t_out = int(s.t[xi]) + g.SEC if _why not in ("claude_close", "claude_partial") else int(s.t[xi])
        c = xc.roundtrip_cost_r(entry=fill, exit_price=px, risk=risk,
                                entry_time=datetime.fromtimestamp(t_in, tz=timezone.utc).isoformat(),
                                exit_time=datetime.fromtimestamp(max(t_out, t_in + 1), tz=timezone.utc).isoformat(),
                                fee_bps_roundtrip=s.fee_bps, slippage_bps_roundtrip=s.slip_bps,
                                funding_bps_per_window=s.fund_bps)
        if not c["total_cost_r"] > 0:
            raise AssertionError(f"zero cost on a filled piece ({s.symbol} entry {fill} exit {px} risk {risk})")
        gross += frac * side * (px - fill) / risk
        cost += frac * c["total_cost_r"]
        days += frac * (t_out - t_in) / 86400.0
    res.pieces, res.gross_r, res.cost_r, res.net_r, res.days = pieces, gross, cost, gross - cost, days
    res.exit_reason = pieces[-1][3]
    return res, None


# ----------------------------------------------------------------------------- masked checkpoint packets
def build_packet(s: g.Series, e: Entry, p: Pending, seed: int = SEED) -> Tuple[dict, dict]:
    """(packet, key). Only bars with index <= the checkpoint bar; prices rebased to 100 at its close; bar times are
    offsets (0 = the checkpoint bar); no symbol, no date, no source, no entry id."""
    j = p.j
    lo = max(0, j - LOOKBACK_BARS + 1)
    ref = float(s.c[j])
    sc = 100.0 / ref
    t0 = g.simulate(s, e.i, e.side, e.etype, e.level, e.stop, e.tp, e.good_till, e.horizon)
    fill, risk = t0.fill_px, t0.risk
    st = p.state
    bars = [[j2 - j, round(float(s.o[j2]) * sc, 4), round(float(s.h[j2]) * sc, 4), round(float(s.l[j2]) * sc, 4),
             round(float(s.c[j2]) * sc, 4)] for j2 in range(lo, j + 1)]
    xcost = xc.roundtrip_cost_r(entry=fill, exit_price=ref, risk=risk,
                                entry_time=datetime.fromtimestamp(int(s.t[t0.fill_i]), tz=timezone.utc).isoformat(),
                                exit_time=datetime.fromtimestamp(int(s.t[j]) + g.SEC, tz=timezone.utc).isoformat(),
                                fee_bps_roundtrip=s.fee_bps, slippage_bps_roundtrip=s.slip_bps,
                                funding_bps_per_window=s.fund_bps)["total_cost_r"]
    pid = "LC-" + hashlib.sha256(f"{seed}|{e.entry_id}|{p.k}".encode()).hexdigest()[:12]
    stop_px = fill + e.side * st["stop_r"] * risk
    tp_px = fill + e.side * st["tp_r"] * risk
    pk = {
        "packet_id": pid, "kind": "lifecycle_checkpoint", "timeframe": "1h",
        "mask": "asset hidden; prices rebased to 100 at the checkpoint close; bar 't' is the offset in bars (0 = now)",
        "trade": {"side": "long" if e.side > 0 else "short", "entry_px": round(fill * sc, 4),
                  "stop_px": round(stop_px * sc, 4), "tp_px": round(tp_px * sc, 4),
                  "one_r_px": round(risk * sc, 4),
                  "now_r": round(st["close_r"], 3), "stop_r": round(st["stop_r"], 3), "tp_r": round(st["tp_r"], 3),
                  "mfe_r": round(st["mfe_r"], 3), "mae_r": round(st["mae_r"], 3),
                  "bars_held": st["bars_held"], "bars_left_to_time_stop": st["bars_left"],
                  "partial_taken": st["partial_taken"], "checkpoint": p.k + 1,
                  "atr_now_px": round(float(s.atr[j]) * sc, 4) if np.isfinite(s.atr[j]) else None,
                  "cost_r_if_closed_now": round(float(xcost), 3)},
        "bars_ohlc": bars,
        "rules": {"actions": list(ACTIONS), "level_units": "R from entry (stop_r / tp_r scale)",
                  "min_gap_r": MIN_GAP_R, "widen_floor_r": WIDEN_FLOOR_R, "tp_cap_r": TP_CAP_R,
                  "partial_fraction": PARTIAL_FRAC, "fills": "close / partial_close at the next bar's open; a moved level "
                  "applies from the next bar; at the time stop the trade closes at that bar's close"},
    }
    key = {"packet_id": pid, "entry_id": e.entry_id, "k": p.k, "j": j, "symbol": e.symbol, "price_ref": ref,
           "checkpoint_epoch": int(s.t[j]) + g.SEC}
    return pk, key


def packet_sha(pk: dict) -> str:
    return hashlib.sha256(json.dumps(pk, sort_keys=True).encode()).hexdigest()


PRICE_LEVEL_FIELDS = ("entry_px", "stop_px", "tp_px")    # the trade's price LEVELS; R values and rebased distances are not prices


def leak_scan(text: str, key: dict, symbols: Sequence[str]) -> List[str]:
    """[] = no leak found: no symbol token (word-bounded: a hex packet id may contain 'ada'), no real date or epoch,
    no real price LEVEL (only the entry/stop/TP levels, the bars and free text are checked: an R value or a rebased
    distance can equal a price by chance), and no
    source label."""
    import re
    out: List[str] = []
    low = text.lower()
    for sym in symbols:
        for tok in {sym.lower(), sym.lower().replace("usdt", "")}:
            if len(tok) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", low):
                out.append(f"symbol token {tok!r}")
    for tok in ("claude", "random", "judged", "strategy"):
        if re.search(rf"(?<![a-z0-9]){tok}(?![a-z0-9])", low):
            out.append(f"source token {tok!r}")
    for m in re.finditer(r"(?:19|20)\d{2}-\d{2}-\d{2}", text):
        out.append(f"date string {m.group(0)!r}")
    for m in re.finditer(r"(?<![\w.])(1[5-9]\d{8})(?![\w.])", text):
        out.append(f"epoch-seconds number {m.group(1)}")
    obj = json.loads(text)
    tr = obj.get("trade") or {}
    levels = [tr[f] for f in PRICE_LEVEL_FIELDS if isinstance(tr.get(f), (int, float))]
    levels += [x for b in obj.get("bars_ohlc") or [] for x in b[1:]]
    ref = float(key["price_ref"])
    for v in levels:
        if ref > 0 and abs(ref - 100.0) > 0.5 and abs(float(v) - ref) <= 1e-6 * ref:
            out.append(f"real price {v}")
    for m in re.finditer(r"(?<![\w.])(\d+\.\d+)", json.dumps({k: v for k, v in obj.items() if k not in ("trade", "bars_ohlc")})):
        if ref > 0 and abs(ref - 100.0) > 0.5 and abs(float(m.group(1)) - ref) <= 1e-6 * ref:
            out.append(f"real price {m.group(1)}")       # free text outside the numeric fields (the positive control)
    return sorted(set(out))


JUDGE_PROTOCOL = """# Desk in-trade management -- judging protocol (packet only; no tools, no repo, no web)

You are the in-trade manager of an OPEN trade. Each packet is one trade at one checkpoint. Decide the action that
maximises the trade's expected net R from here to its close, NET OF COSTS. You see only the packet.

The packet: `trade` = side, entry / stop / target (prices rebased to 100 at the current close), the same levels in R
from entry (`stop_r`, `tp_r`; 1 R = the initial risk), `now_r` (current price in R), `mfe_r` / `mae_r` (best / worst so
far), `bars_held`, `bars_left_to_time_stop` (the trade closes at market at the time stop), `partial_taken`,
`atr_now_px`, `cost_r_if_closed_now` (the round-trip cost in R a close now realises; costs are already counted in
every outcome). `bars_ohlc` = the last closed 1h bars [t, open, high, low, close], t = 0 is now. The asset and the
date are hidden on purpose; do not guess them.

Actions (closed enum; one per packet):
  hold                          keep both brackets as they are
  tighten_sl   level_r = x      move the stop to x R from entry: above the current stop_r, at least 0.10 R below now_r
  widen_sl     level_r = x      move the stop to x R: below the current stop_r, not below -2.0 R
  move_tp      level_r = y      move the target to y R: at least 0.10 R beyond now_r, at most 10 R
  partial_close                 close 50 % at the next bar's open (once per trade)
  close                         close all at the next bar's open
A moved level applies from the next bar. Both brackets always exist; nothing removes one. An invalid level is
treated as hold. Holding is a decision, not a default: choose it when it is your best estimate.

Answer with ONLY JSON lines, one per packet, in the order given, nothing else:
{"packet_id": "LC-...", "action": "hold|tighten_sl|widen_sl|move_tp|partial_close|close", "level_r": <number, only for tighten_sl/widen_sl/move_tp>, "confidence": <0..1>, "reason": "<= 20 words"}
"""


# ----------------------------------------------------------------------------- static rules (B3 menu; no judging)
def _static(name: str) -> Decider:
    def hold(k, j, st):
        return {"action": "hold"}

    def close1(k, j, st):
        return {"action": "close"} if k == 0 else {"action": "hold"}

    def breakeven(k, j, st):
        return {"action": "tighten_sl", "level_r": 0.0} if st["close_r"] >= 0.5 and st["stop_r"] < 0 else {"action": "hold"}

    def trail1(k, j, st):
        x = st["close_r"] - 1.0
        return {"action": "tighten_sl", "level_r": x} if x > st["stop_r"] else {"action": "hold"}

    def partial1r(k, j, st):
        return {"action": "partial_close"} if st["close_r"] >= 1.0 and not st["partial_taken"] else {"action": "hold"}

    def cut_loser(k, j, st):
        return {"action": "close"} if st["close_r"] <= -0.5 else {"action": "hold"}

    return {"hold": hold, "close_at_ckpt1": close1, "breakeven_at_0.5r": breakeven, "trail_1r": trail1,
            "partial_at_1r": partial1r, "cut_below_-0.5r": cut_loser}[name]


STATIC_RULES = ("hold", "close_at_ckpt1", "breakeven_at_0.5r", "trail_1r", "partial_at_1r", "cut_below_-0.5r")


# ----------------------------------------------------------------------------- statistics
def cluster_mean_ci(vals: Sequence[float], weeks: Sequence[str], seed: int = SEED, draws: int = BOOT_DRAWS) -> Dict[str, Any]:
    v = np.asarray(vals, dtype=float)
    if not len(v):
        return {"n": 0, "weeks": 0, "mean": None, "ci95": [None, None], "sd": None}
    wk = sorted(set(weeks))
    ix = {w: n for n, w in enumerate(wk)}
    s_w = np.zeros(len(wk))
    n_w = np.zeros(len(wk))
    for x, w in zip(v, weeks):
        s_w[ix[w]] += x
        n_w[ix[w]] += 1
    rng = np.random.default_rng(seed)
    b = rng.integers(0, len(wk), size=(draws, len(wk)))
    m = s_w[b].sum(axis=1) / n_w[b].sum(axis=1)
    return {"n": int(len(v)), "weeks": len(wk), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else None,
            "ci95": [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]}


def folds_positive(vals: Sequence[float], folds: Sequence[int]) -> Tuple[int, Dict[str, Any]]:
    det, pos = {}, 0
    for f in range(1, g.N_FOLDS + 1):
        x = [v for v, ff in zip(vals, folds) if ff == f]
        det[str(f)] = {"n": len(x), "mean": float(np.mean(x)) if x else None}
        if len(x) >= FOLD_MIN_N and np.mean(x) > 0:
            pos += 1
    return pos, det


def required_n(sd: Optional[float], effect: float, deff: float = 1.0) -> Optional[int]:
    return None if not sd or not math.isfinite(sd) else int(math.ceil(deff * (2.8 * sd / effect) ** 2))


def grade_contrast(st: Dict[str, Any], pos: int, beats_b3: Optional[bool]) -> Tuple[str, str]:
    """The rule registered in -02 for a management or entry contrast (paired dR)."""
    if st["n"] < N_MIN_PAIRS:
        return "indeterminate", f"n {st['n']} < {N_MIN_PAIRS}"
    lo, hi = st["ci95"]
    if hi < 0:
        return "fail", "CI upper < 0: it costs R"
    if st["mean"] > 0 and lo > 0 and pos >= FOLDS_NEEDED:
        if beats_b3 is False:
            return "pass_rule", "adds value, but the best static rule (B3) does as well: a rule, not judgement"
        return "pass", "adds value, CI excludes 0, >= 3 of 4 folds"
    return "indeterminate", "CI straddles 0 or < 3 folds positive"


def factorial(rows: List[Dict[str, Any]], seed: int = SEED) -> Dict[str, Any]:
    """rows: one per matched pair with keys week, fold, C_h, C_m, R_h, R_m (any of the *_m may be None when that
    arm is not judged) and optionally C_b3 / R_b3. Returns every cell, contrast, main effect and the interaction."""
    def col(k):
        return [r for r in rows if r.get(k) is not None]

    out: Dict[str, Any] = {"cells": {}, "contrasts": {}}
    for k in ("C_h", "C_m", "R_h", "R_m", "C_b3", "R_b3"):
        rr = col(k)
        out["cells"][k] = cluster_mean_ci([r[k] for r in rr], [r["week"] for r in rr], seed)

    def contrast(name, f, need):
        rr = [r for r in rows if all(r.get(x) is not None for x in need)]
        vals = [f(r) for r in rr]
        st = cluster_mean_ci(vals, [r["week"] for r in rr], seed)
        pos, det = folds_positive(vals, [r["fold"] for r in rr])
        st["folds_positive"], st["folds"] = pos, det
        st["n_to_resolve_0.10R"] = required_n(st.get("sd"), 0.10)
        out["contrasts"][name] = st
        return st

    contrast("mgmt_value|claude_entry", lambda r: r["C_m"] - r["C_h"], ("C_m", "C_h"))
    contrast("mgmt_value|random_entry", lambda r: r["R_m"] - r["R_h"], ("R_m", "R_h"))
    contrast("entry_value|hold", lambda r: r["C_h"] - r["R_h"], ("C_h", "R_h"))
    contrast("entry_value|claude_mgmt", lambda r: r["C_m"] - r["R_m"], ("C_m", "R_m"))
    full = ("C_h", "C_m", "R_h", "R_m")
    contrast("main_effect_mgmt", lambda r: 0.5 * ((r["C_m"] - r["C_h"]) + (r["R_m"] - r["R_h"])), full)
    contrast("main_effect_entry", lambda r: 0.5 * ((r["C_h"] - r["R_h"]) + (r["C_m"] - r["R_m"])), full)
    contrast("interaction", lambda r: (r["C_m"] - r["C_h"]) - (r["R_m"] - r["R_h"]), full)
    contrast("claude_mgmt_vs_b3|claude_entry", lambda r: r["C_m"] - r["C_b3"], ("C_m", "C_b3"))
    contrast("claude_mgmt_vs_b3|random_entry", lambda r: r["R_m"] - r["R_b3"], ("R_m", "R_b3"))
    contrast("end_to_end|claude_x_claude_vs_random_x_hold", lambda r: r["C_m"] - r["R_h"], ("C_m", "R_h"))
    return out


def best_static_lofo(per_rule: Dict[str, Dict[str, float]], fold_of_pair: Dict[str, int], hold: Dict[str, float]
                     ) -> Dict[str, float]:
    """B3: per pair, the outcome of the static rule with the best mean dR on the OTHER folds."""
    out: Dict[str, float] = {}
    for f in range(1, g.N_FOLDS + 1):
        best, best_m = "hold", -math.inf
        for name, vals in per_rule.items():
            d = [vals[p] - hold[p] for p in vals if fold_of_pair[p] != f and p in hold]
            m = float(np.mean(d)) if d else -math.inf
            if m > best_m:
                best, best_m = name, m
        for p, ff in fold_of_pair.items():
            if ff == f and p in per_rule[best]:
                out[p] = per_rule[best][p]
    return out


# ----------------------------------------------------------------------------- IO helpers
def _prepare_market(a: argparse.Namespace) -> Tuple[Dict[str, g.Series], List[str], Dict[str, List[str]], List[str]]:
    uni, _note = g.parse_universe()
    syms = [u["symbol"] for u in uni]
    cdir = Path(a.candles_dir) if a.candles_dir else Path(tempfile.mkdtemp(prefix="desk_lc_candles_"))
    if getattr(a, "fetch", False):
        g.fetch_market(cdir, syms)
    mkt, missing = g.load_market(cdir, syms)
    return mkt, missing, {u["symbol"]: u["classes"] for u in uni}, g.candle_manifest(mkt) if mkt else []


def load_claude_entries(mkt: Dict[str, g.Series], classes: Optional[Dict[str, List[str]]] = None) -> List[Entry]:
    """The judged-1 fills. Proposal validity is the LANDED intake's (e535-03: 732 propose_entry rows, 0 refused, 0
    over cap, 0 duplicate), asserted here, so the masked packets are not re-derived: the packet builder's base rates
    moved with the fee (#20783, 7.5 -> 11.0 bps), so a re-derived packet no longer hashes to what the judge saw."""
    keys = {k["packet_id"]: k for k in json.loads((JUDGED1 / "mask-key.json").read_text())["keys"]}
    by: Dict[str, List[dict]] = {}
    n_prop = 0
    for ln in (JUDGED1 / "proposals.jsonl").read_text().splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        if row["packet_id"] not in keys:
            raise ValueError(f"judged-1 packet {row['packet_id']!r} has no mask key")
        if row.get("action") == "propose_entry":
            n_prop += 1
            by.setdefault(row["packet_id"], []).append(row)
    if n_prop != JUDGED1_VALID:
        raise ValueError(f"judged-1 holds {n_prop} propose_entry rows; the landed intake validated {JUDGED1_VALID}")
    return claude_fills(mkt, keys, by)


def fee_repro(mkt: Dict[str, g.Series], entries: List[Entry], fee_bps: float) -> float:
    """Mean HOLD net R of `entries` with the venue fee set to `fee_bps` (the fidelity check against a landed record)."""
    vals = []
    for e in entries:
        s = mkt[e.symbol]
        s2 = g.Series(s.symbol, s.t, s.o, s.h, s.l, s.c, s.atr, fee_bps, s.slip_bps, s.fund_bps)
        vals.append(run(s2, e)[0].net_r)
    return float(np.mean(vals))


def read_entries(path: Path) -> List[Entry]:
    return [Entry(**json.loads(ln)) for ln in path.read_text().splitlines() if ln.strip()]


def read_decisions(out: Path, decisions: Optional[Path]) -> Dict[Tuple[str, int], dict]:
    """{(entry_id, k): decision} joined through every round key under OUT/rounds/."""
    keymap: Dict[str, Tuple[str, int]] = {}
    for kf in sorted((out / "rounds").glob("round-*-key.jsonl")) if (out / "rounds").exists() else []:
        for ln in kf.read_text().splitlines():
            if ln.strip():
                k = json.loads(ln)
                keymap[k["packet_id"]] = (k["entry_id"], int(k["k"]))
    got: Dict[Tuple[str, int], dict] = {}
    if decisions and decisions.exists():
        for n, ln in enumerate(decisions.read_text().splitlines(), 1):
            if not ln.strip():
                continue
            d = json.loads(ln)
            if d.get("packet_id") not in keymap:
                raise ValueError(f"{decisions}:{n}: packet_id {d.get('packet_id')!r} is in no round key")
            got.setdefault(keymap[d["packet_id"]], d)          # first answer wins; a duplicate is ignored
    return got


def _decider(entry_id: str, dec: Dict[Tuple[str, int], dict]) -> Decider:
    return lambda k, j, st: dec.get((entry_id, k))


# ----------------------------------------------------------------------------- modes
def cmd_entries(a: argparse.Namespace) -> int:
    mkt, missing, classes, src = _prepare_market(a)
    if missing:
        print(json.dumps({"error": f"candles missing for {missing}"}))
        return 2
    claude = load_claude_entries(mkt, classes)
    repro = {"n": len(claude), "mean_hold_net_r_at_e535_fee": fee_repro(mkt, claude, E535_03_FEE_BPS),
             "mean_hold_net_r_current_cost": float(np.mean([run(mkt[e.symbol], e)[0].net_r for e in claude]))}
    repro["matches_e535_03"] = repro["n"] == E535_03_N and abs(repro["mean_hold_net_r_at_e535_fee"] - E535_03_MEAN) < 1e-9
    if a.pilot_n:
        rng = np.random.default_rng(a.seed)
        pick = sorted(rng.choice(len(claude), size=min(a.pilot_n, len(claude)), replace=False).tolist())
        claude = [claude[n] for n in pick]
    pools: Dict[Tuple[str, int], np.ndarray] = {}
    out_rows: List[Entry] = []
    unmatched = 0
    for e in claude:
        r = random_partner(mkt, e, a.seed + 1, pools)
        if r is None:
            unmatched += 1
            continue
        out_rows += [e, r]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "entries.jsonl").write_text("".join(json.dumps(asdict(e)) + "\n" for e in out_rows))
    meta = {"judged1_reproduction": repro, "pilot_n": a.pilot_n, "seed": a.seed, "pairs": len(out_rows) // 2,
            "unmatched": unmatched, "candles": src}
    (out / "entries-meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k != "candles"}))
    return 0


def cmd_step(a: argparse.Namespace) -> int:
    mkt, missing, _classes, _src = _prepare_market(a)
    out = Path(a.out)
    entries = read_entries(Path(a.entries))
    dec = read_decisions(out, Path(a.decisions) if a.decisions else None)
    pend: List[Tuple[dict, dict]] = []
    closed = 0
    for e in entries:
        res, p = run(mkt[e.symbol], e, _decider(e.entry_id, dec))
        if p is None:
            closed += 1
            continue
        pk, key = build_packet(mkt[e.symbol], e, p)
        leaks = leak_scan(json.dumps(pk), key, sorted(mkt))
        if leaks:
            raise AssertionError(f"leak in {pk['packet_id']}: {leaks}")
        pend.append((pk, key))
    pend.sort(key=lambda x: x[0]["packet_id"])                 # opaque order: sources interleave
    rd = out / "rounds"
    rd.mkdir(parents=True, exist_ok=True)
    (out / "JUDGE-PROTOCOL.md").write_text(JUDGE_PROTOCOL)
    n = len(list(rd.glob("round-*-key.jsonl"))) + 1
    if pend:
        (rd / f"round-{n:02d}-packets.jsonl").write_text("".join(json.dumps(pk) + "\n" for pk, _ in pend))
        (rd / f"round-{n:02d}-key.jsonl").write_text("".join(json.dumps(k) + "\n" for _, k in pend))
    print(json.dumps({"round": n if pend else None, "pending": len(pend), "closed": closed, "decisions_read": len(dec),
                      "protocol_sha256": hashlib.sha256(JUDGE_PROTOCOL.encode()).hexdigest()[:16]}))
    return 0


def evaluate(mkt: Dict[str, g.Series], entries: List[Entry], dec: Dict[Tuple[str, int], dict]) -> Dict[str, Any]:
    by_pair: Dict[str, Dict[str, Entry]] = {}
    for e in entries:
        by_pair.setdefault(e.pair_id, {})[e.source] = e
    static: Dict[str, Dict[str, Dict[str, float]]] = {"claude": {r: {} for r in STATIC_RULES},
                                                      "random": {r: {} for r in STATIC_RULES}}
    rows, acct = [], {"pairs": 0, "pending_claude_mgmt": 0, "decisions": 0, "invalid": 0, "actions": {},
                      "moved_stop_exits": 0, "slip_sens_r": 0.0}
    fold_of_pair: Dict[str, int] = {}
    for pid, d in sorted(by_pair.items()):
        if "claude" not in d or "random" not in d:
            continue
        acct["pairs"] += 1
        row: Dict[str, Any] = {"pair_id": pid, "week": d["claude"].week, "fold": d["claude"].fold}
        fold_of_pair[pid] = d["claude"].fold
        for src, tag in (("claude", "C"), ("random", "R")):
            e = d[src]
            s = mkt[e.symbol]
            row[f"{tag}_h"] = run(s, e)[0].net_r
            res, p = run(s, e, _decider(e.entry_id, dec))
            if p is not None:
                row[f"{tag}_m"] = None
                acct["pending_claude_mgmt"] += 1
            else:
                row[f"{tag}_m"] = res.net_r
                acct["decisions"] += res.decided
                acct["invalid"] += res.invalid
                for x in res.actions:
                    acct["actions"][x] = acct["actions"].get(x, 0) + 1
                if res.moved_stop_exit:
                    acct["moved_stop_exits"] += 1
            for rule in STATIC_RULES:
                static[src][rule][pid] = run(s, e, _static(rule))[0].net_r
        rows.append(row)
    for src, tag in (("claude", "C"), ("random", "R")):
        hold = {r["pair_id"]: r[f"{tag}_h"] for r in rows}
        b3 = best_static_lofo(static[src], fold_of_pair, hold)
        for r in rows:
            r[f"{tag}_b3"] = b3.get(r["pair_id"])
    fx = factorial(rows)
    static_table = {}
    for src, tag in (("claude", "C"), ("random", "R")):
        for rule in STATIC_RULES:
            vals = [static[src][rule][r["pair_id"]] - r[f"{tag}_h"] for r in rows]
            st = cluster_mean_ci(vals, [r["week"] for r in rows])
            static_table[f"{rule}|{src}_entry"] = {"mean_dR": st["mean"], "ci95": st["ci95"], "n": st["n"]}
    labels = {}
    for name, b3k in (("mgmt_value|claude_entry", "claude_mgmt_vs_b3|claude_entry"),
                      ("mgmt_value|random_entry", "claude_mgmt_vs_b3|random_entry")):
        st, b3 = fx["contrasts"][name], fx["contrasts"][b3k]
        beats = None if b3["n"] == 0 else bool(b3["ci95"][0] is not None and b3["ci95"][0] > 0)
        labels[name] = grade_contrast(st, st["folds_positive"], beats) if st["n"] else ("indeterminate", "not judged")
    for name in ("entry_value|hold", "entry_value|claude_mgmt", "interaction"):
        st = fx["contrasts"][name]
        labels[name] = grade_contrast(st, st["folds_positive"], None) if st["n"] else ("indeterminate", "not judged")
    return {"factorial": fx, "static_rules_dR": static_table, "labels": labels, "accounting": acct, "rows": rows}


def cmd_score(a: argparse.Namespace) -> int:
    mkt, missing, _classes, src = _prepare_market(a)
    if missing:
        print(json.dumps({"error": f"candles missing for {missing}"}))
        return 2
    out = Path(a.out)
    entries = read_entries(Path(a.entries))
    dec = read_decisions(out, Path(a.decisions) if a.decisions else None)
    res = evaluate(mkt, entries, dec)
    res["label"] = a.label
    res["candles"] = src
    res["limits"] = [l.strip() for l in __doc__.split("STATED LIMITS (printed into every verdict)")[1].strip().split("*") if l.strip()]
    (out / "score.json").write_text(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1, default=str))
    (out / "pairs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in res["rows"]))
    c = res["factorial"]["contrasts"]
    print(json.dumps({"label": a.label, "pairs": res["accounting"]["pairs"],
                      "cells": {k: (v["mean"], v["ci95"]) for k, v in res["factorial"]["cells"].items()},
                      "mgmt|claude": (c["mgmt_value|claude_entry"]["mean"], c["mgmt_value|claude_entry"]["ci95"]),
                      "mgmt|random": (c["mgmt_value|random_entry"]["mean"], c["mgmt_value|random_entry"]["ci95"]),
                      "interaction": (c["interaction"]["mean"], c["interaction"]["ci95"])}, default=str))
    return 0


# ----------------------------------------------------------------------------- self-check (unit d1f5-01)
def _oracle(s: g.Series, e: Entry, pick: str) -> Decider:
    """Hindsight manager at checkpoint 1: close when the rest of the HOLD path ends worse than closing now
    (pick='oracle'), or the reverse ('anti'). Reads the future on purpose: a planted known answer."""
    def d(k, j, st):
        if k != 0:
            return {"action": "hold"}
        hold_net = run(s, e)[0].net_r
        closed = run(s, e, lambda k2, j2, st2: {"action": "close"} if k2 == 0 else {"action": "hold"})[0].net_r
        better_close = closed > hold_net
        want = better_close if pick == "oracle" else not better_close
        return {"action": "close"} if want else {"action": "hold"}
    return d


def _random_policy(seed: int) -> Callable[[Entry], Decider]:
    def mk(e: Entry) -> Decider:
        rng = np.random.default_rng(int(hashlib.sha256(f"{seed}|{e.entry_id}".encode()).hexdigest()[:8], 16))

        def d(k, j, st):
            a = ACTIONS[int(rng.integers(0, len(ACTIONS)))]
            if a in ("tighten_sl",):
                return {"action": a, "level_r": st["stop_r"] + 0.5 * (st["close_r"] - MIN_GAP_R - st["stop_r"])}
            if a == "widen_sl":
                return {"action": a, "level_r": max(WIDEN_FLOOR_R, st["stop_r"] - 0.5)}
            if a == "move_tp":
                return {"action": a, "level_r": min(TP_CAP_R, st["close_r"] + 1.0)}
            return {"action": a}
        return d
    return mk


def selfcheck(mkt: Dict[str, g.Series], classes: Dict[str, List[str]], seed: int = SEED) -> Dict[str, Any]:
    cl: Dict[str, Any] = {}
    claude = load_claude_entries(mkt, classes)
    pools: Dict[Tuple[str, int], np.ndarray] = {}
    pairs = [(e, random_partner(mkt, e, seed + 1, pools)) for e in claude]
    pairs = [(c, r) for c, r in pairs if r is not None]
    ents = [x for p in pairs for x in p]
    # (a) the chained engine under HOLD == simulate, every trade; judged-1 reproduced
    worst = 0.0
    for e in ents:
        t = g.simulate(mkt[e.symbol], e.i, e.side, e.etype, e.level, e.stop, e.tp, e.good_till, e.horizon)
        r1 = run(mkt[e.symbol], e)[0]
        r2 = run(mkt[e.symbol], e, _static("hold"))[0]
        worst = max(worst, abs(t.net_r - r1.net_r), abs(t.net_r - r2.net_r))
    mean_c = fee_repro(mkt, claude, E535_03_FEE_BPS)
    cl["a_hold_equals_simulate"] = {"ok": worst <= 1e-9, "max_abs_diff_r": worst, "n_trades": len(ents)}
    cl["a2_judged1_reproduced"] = {"ok": len(claude) == E535_03_N and abs(mean_c - E535_03_MEAN) < 1e-9,
                                   "n": len(claude), "mean_net_r_at_e535_fee": mean_c,
                                   "landed": [E535_03_N, E535_03_MEAN, E535_03_FEE_BPS]}
    # (b) no lookahead: 50 checkpoint packets are byte-identical when every bar AFTER the checkpoint is x3
    prng = np.random.default_rng(seed + 2)
    sample = [ents[n] for n in prng.choice(len(ents), size=min(50, len(ents)), replace=False)]
    same, tried = 0, 0
    for e in sample:
        s = mkt[e.symbol]
        _res, p = run(s, e, lambda k, j, st: None)
        if p is None:
            continue
        tried += 1
        pk, _ = build_packet(s, e, p)
        s2 = g.Series(s.symbol, s.t.copy(), s.o.copy(), s.h.copy(), s.l.copy(), s.c.copy(), s.atr.copy(),
                      s.fee_bps, s.slip_bps, s.fund_bps)
        for arr in (s2.o, s2.h, s2.l, s2.c):
            arr[p.j + 1:] *= 3.0
        _r2, p2 = run(s2, e, lambda k, j, st: None)
        same += int(p2 is not None and packet_sha(build_packet(s2, e, p2)[0]) == packet_sha(pk))
    cl["b_no_lookahead"] = {"ok": tried > 0 and same == tried, "identical": same, "tried": tried}
    # (c) leak scan on every first-checkpoint packet, plus a planted positive control
    found, n_pk, ctrl = 0, 0, None
    for e in ents:
        s = mkt[e.symbol]
        _r, p = run(s, e, lambda k, j, st: None)
        if p is None:
            continue
        pk, key = build_packet(s, e, p)
        n_pk += 1
        found += int(bool(leak_scan(json.dumps(pk), key, sorted(mkt))))
        if ctrl is None:
            bad = json.loads(json.dumps(pk))
            bad["note"] = f"{e.symbol} random 2026-01-05 {int(s.t[p.j])} {key['price_ref']}"
            ctrl = leak_scan(json.dumps(bad), key, sorted(mkt))
    ctrl_ok = ctrl is not None and sum(1 for x in ctrl if x.startswith(("symbol", "source", "date", "epoch", "real price"))) >= 5
    cl["c_leak_scan"] = {"ok": n_pk > 0 and found == 0 and ctrl_ok, "packets": n_pk, "with_finding": found,
                         "positive_control_findings": ctrl}
    # (d) planted managers on the claude entries: oracle > 0, anti < 0, null false positives <= 3 of 20
    weeks = [c.week for c, _ in pairs]
    hold = [run(mkt[c.symbol], c)[0].net_r for c, _ in pairs]
    orc = [run(mkt[c.symbol], c, _oracle(mkt[c.symbol], c, "oracle"))[0].net_r - h for (c, _), h in zip(pairs, hold)]
    ant = [run(mkt[c.symbol], c, _oracle(mkt[c.symbol], c, "anti"))[0].net_r - h for (c, _), h in zip(pairs, hold)]
    so, sa = cluster_mean_ci(orc, weeks, seed), cluster_mean_ci(ant, weeks, seed)
    fp = 0
    for rep in range(20):
        pa, pb = _random_policy(seed + 100 + rep), _random_policy(seed + 200 + rep)
        d = [run(mkt[c.symbol], c, pa(c))[0].net_r - run(mkt[c.symbol], c, pb(c))[0].net_r for c, _ in pairs]
        st = cluster_mean_ci(d, weeks, seed + rep, draws=2000)
        fp += int(st["ci95"][0] > 0 or st["ci95"][1] < 0)
    cl["d_planted"] = {"ok": so["mean"] > 0 and so["ci95"][0] > 0 and sa["mean"] < 0 and sa["ci95"][1] < 0 and fp <= 3,
                       "oracle": so, "anti_oracle": sa, "null_false_positives_of_20": fp}
    ok = all(v["ok"] for v in cl.values())
    return {"verdict": "pass" if ok else "fail", "read_state": "measured", "clauses": cl, "pairs": len(pairs)}


def cmd_selfcheck(a: argparse.Namespace) -> int:
    mkt, missing, classes, src = _prepare_market(a)
    if missing:
        v = {"verdict": "indeterminate", "read_state": "no_data", "reason": f"candles missing for {missing}"}
    else:
        v = selfcheck(mkt, classes, a.seed)
    pop = (f"{v.get('pairs', 0)} judged-1 Claude fills (comms/research/desk_gen_replay/judged-1) and one matched random partner each, "
           f"{', '.join(sorted(mkt))} 1h Binance Vision USD-M perp klines")
    g._write_verdict(Path(a.out), v, pop, v.get("pairs"), "lifecycle harness self-check (RULE-RQ20261028-D1F5-01-LIFECYCLE-SELFCHECK)",
                     None, src + [f"MISSING:{m}" for m in missing])
    print(json.dumps({"verdict": v["verdict"], "clauses": {k: c["ok"] for k, c in v.get("clauses", {}).items()}}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("entries", cmd_entries), ("step", cmd_step), ("score", cmd_score), ("selfcheck", cmd_selfcheck)):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--fetch", action="store_true", help="fetch candles from Binance Vision (the queue runner)")
        s.add_argument("--candles-dir", help="default: a scratch dir outside --out")
        s.add_argument("--seed", type=int, default=SEED)
        s.set_defaults(fn=fn)
        if name == "entries":
            s.add_argument("--pilot-n", type=int, default=0, help="0 = every judged-1 fill (the full run)")
        if name in ("step", "score"):
            s.add_argument("--entries", required=True)
            s.add_argument("--decisions", help="judge rows, one per packet: {packet_id, action, level_r?, confidence, reason}")
        if name == "score":
            s.add_argument("--label", default="pilot", help="pilot | registered")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

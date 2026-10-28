#!/usr/bin/env python3
# wiring: manual-only - run by the judging lane (`packets`, `score`) and, once PR #20349 lands, by research/queue RQ-20261026-bf56-01 via research-script-run.yml (`selfcheck`); no schedule consumes it.
"""DESK-7B-REPLAY-DRIVER -- the D-S0 blind-replay driver for the desk's in-trade and exit roles.

Design: docs/plans/claude-trading-desk-DESIGN.md section 8.1 (D-S0), section 10. Units:
research/queue/blocked/RQ-20261026-bf56-01 (harness self-check), -02 (in-trade), -03 (exit)
(PR #20339). Tier 1 research tooling: reads committed Stage-0 evidence, candles, writes only under --out.

WHAT IT DOES
------------
population  The real-money (non-prop) 2h/4h legs, RE-PARSED from config/accounts.yaml + strategies.yaml
            at run time (the units say "re-parse before running"); compared with the registered four.
trades      Each leg's committed Stage-0 per-trade rows (comms/strategy_evidence/<leg>.json ->
            source_run). Every net_r is already net of the full cost stack.
decision    The first CLOSED bar whose running favourable extreme reached +1.0 R while the trade was
point       still open (the state scripts/research/live_review_outcomes.py prices). A trade whose
            recorded exit is that same bar has no decision to make and is counted, not silently dropped.
packet      MASKED, point in time: only bars whose close is <= the decision bar's close. Symbol ->
            alias, prices rebased to 100 at the decision close, timestamps re-anchored to year 2000,
            volume/calendar/funding withheld, the REAL leg name never appears. The unmask key (packet
            id -> leg, entry time, fold, pre_cutoff) is a separate file the judging session never reads.
actions     A judging session writes one jsonl row per packet (closed enum, prose is not a label):
              {"packet_id": "P-...", "role": "in_trade", "action": "hold"}
              {"packet_id": "P-...", "role": "in_trade", "action": "tighten_sl",
               "level": {"kind": "atr", "value": 1.5}}   # ratchet 1.5 entry-ATR behind the running extreme
              {"packet_id": "P-...", "role": "in_trade", "action": "tighten_sl",
               "level": {"kind": "r", "value": 0.5}}      # fixed stop at +0.5 R (must be > -1 R and < price)
              {"packet_id": "P-...", "role": "exit", "action": "hold" | "close" | "partial_close"}
            An invalid level (loosening, or not below price) is scored as HOLD and COUNTED.
replay      The action is replayed on the real candle path, SL-first, a gap fills at the open. A tighten
            fills at the stop price and pays an extra --stop-fill-slip-r (0.05 registered; 0 and 0.10
            reported as sensitivities). close fills at the NEXT bar's open; partial_close realises 50%
            there and holds the other 50% to the recorded exit. Every non-hold exit is priced through
            execution_costs.roundtrip_cost_r with resolve_cost_policy(symbol) and the leg's recorded
            fee; hold is the recorded net_r.
scoring     Paired dR = replayed net R - recorded net R, trade-resampling bootstrap CI, B2 random-timing,
            B3 leave-one-fold-out best static rule, per-fold and post-cutoff strata, then the rule
            REGISTERED in the unit (the numbers below are the registered ones and are not tunable).

MODES
-----
  desk_replay_driver.py selfcheck --out DIR [--fetch]     # unit bf56-01 -> DIR/verdict.json
  desk_replay_driver.py packets   --out DIR [--fetch]     # packets.jsonl (judge) + mask-key.json (scorer)
  desk_replay_driver.py score --role in_trade|exit --actions-file F --mask-key K --out DIR \\
        --selfcheck-verdict DIR1/verdict.json --model-cutoff 2026-06-01 [--fetch]   # units bf56-02 / -03

STATED LIMITS (printed into every verdict, not hidden)
* The committed trade lists carry the INITIAL stop only; the trailed stop at the decision bar and the
  take-profit are not in them, so a packet reports both as could_not_look and a tighten level is
  checked against the initial stop only (a trail already tighter than the judge's level is not seen).
* A stop touched on the recorded exit bar is taken as hit (SL-first), as in live_review_outcomes.py.
* The decision state is selected by the candle path (running high >= +1R), never by the recorded
  outcome; the recorded mfe_r is only compared with the replayed one (fidelity diagnostic).
* Registered clause (a) of bf56-01 prices HOLD as the recorded net_r, so it cannot fail by itself;
  the non-vacuous evidence is the fidelity diagnostics block (cost-stack recomputation, exit price
  inside the exit bar, replayed vs recorded MFE) and the planted known-answer case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.research import live_review_outcomes as lro  # noqa: E402  (path pricing: compose, not rewrite)
from scripts.research.intervention_controls import best_static_rule, matched_random_intervention  # noqa: E402  (shared B2/B3)
from src.runtime import execution_costs as xc  # noqa: E402
import desk_scan_packet as dsp  # noqa: E402  (ATR definition, bar convention, TF_SECONDS)

# ----------------------------------------------------------------------------- registered numbers
# Registered in research/queue/blocked/RQ-20261026-bf56-0{1,2,3}.yaml on 2026-10-26, before any run.
REGISTERED_LEGS = ("ada_pullback_2h", "trend_donchian_eth_4h", "trend_donchian_xrp_4h", "xrp_pullback_2h")
REGISTERED_N_TRADES = 370             # 55 + 61 + 208 + 46, MEASURED from comms/strategy_evidence/*.json
PEAK_R = 1.0                          # the decision state: first closed bar whose running high >= +1.0 R
SELFCHECK_TOL_R = 1e-6                # clause (a)
N_MIN = 126                           # pass floor for -02/-03
FOLDS_NEEDED = 3                      # of 4
STOP_FILL_SLIP_R = 0.05               # registered; 0.0 and 0.10 are reported sensitivities
SENSITIVITIES = (0.0, 0.10)
BOOT_DRAWS = 10_000
B2_DRAWS = 1_000
DEFAULT_SEED = 20261026
POST_CUTOFF_MIN_N = 20
LEG_N_FLOOR = 20
LOOKBACK_BARS = 48                    # closed bars shown in a packet, ending at the decision bar
B3_GRIDS = {
    "in_trade": [("tighten", "atr", 1.0), ("tighten", "atr", 1.5), ("tighten", "atr", 2.0),
                 ("tighten", "r", 0.0), ("tighten", "r", 0.5)],
    "exit": [("close",), ("partial_close",), ("close_at_r", 2.0)],
}
ROLE_ACTIONS = {"in_trade": ("hold", "tighten_sl"), "exit": ("hold", "close", "partial_close")}
RESOLVE_EFFECT = {"in_trade": 0.10, "exit": 0.20}   # R the "n that would resolve" line is quoted for
PRICE_KEYS = {"o", "h", "l", "c", "entry_px", "stop_initial_px"}
# Packets are anchored so the decision bar's CLOSE is this instant; the lookback stays inside year 2000.
MASK_DECISION_CLOSE = datetime(2000, 2, 1, tzinfo=timezone.utc)
ALLOWED_YEAR = "2000"

REQUIRED_PACKET_KEYS = ("packet_id", "kind", "mask", "trade", "bars", "missing_inputs")


# ----------------------------------------------------------------------------- population + data

def parse_population(repo: Path = REPO) -> List[str]:
    """Real-money, non-prop legs on a 2h/4h timeframe that have a committed Stage-0 trade list."""
    from src.config.accounts_loader import load_accounts_dict
    acc = load_accounts_dict()
    strat = yaml.safe_load((repo / "config" / "strategies.yaml").read_text())
    strat = strat.get("strategies", strat)
    out: List[str] = []
    for _, a in acc.items():
        if not isinstance(a, dict) or a.get("account_class") != "real_money":
            continue
        for leg in a.get("strategies") or []:
            cfg = strat.get(leg) or {}
            if (leg not in out and not leg.endswith("_prop") and cfg.get("timeframe") in ("2h", "4h")
                    and (repo / "comms" / "strategy_evidence" / f"{leg}.json").exists()):
                out.append(leg)
    return sorted(out)


def fetch_candles(symbol: str, tf: str, days: int, dest: Path, repo: Path = REPO) -> Path:
    """Public Binance Vision candles by the first_passage.py route: fetch the base interval through
    regime_debt_matrix, resample with the harness convention in candle_io, write a timestamp-first CSV."""
    for q in (repo / "scripts" / "research", repo / "scripts"):
        if str(q) not in sys.path:
            sys.path.insert(0, str(q))
    import candle_io  # noqa: E402
    import regime_debt_matrix as rdm  # noqa: E402
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_name(dest.stem + ".raw.csv")
    rdm._fetch_csv(rdm.resolve_feed(symbol, tf), days, str(raw))
    df = candle_io.resample_ohlcv(candle_io.load_candles(str(raw)), tf)
    if "timestamp" in df.columns:
        df = df.reset_index(drop=True)
    else:
        df = df.rename_axis("timestamp").reset_index()
    df.to_csv(dest, index=False)
    return dest


@dataclass
class Leg:
    name: str
    symbol: str
    timeframe: str
    trades: List[Dict[str, Any]]
    candles: Optional[pd.DataFrame]
    candle_src: Optional[str]
    atr: Optional[pd.Series]
    fee_bps: float
    slip_bps: float
    fund_bps: float
    record_cost_stack: Dict[str, Any]
    fold_starts: List[pd.Timestamp]
    n_trades_oos: int


def load_leg(name: str, *, fetch: bool = False, candle_dir: Optional[Path] = None,
             candles: Optional[pd.DataFrame] = None, repo: Path = REPO) -> Leg:
    rec = json.loads((repo / "comms" / "strategy_evidence" / f"{name}.json").read_text())
    trades, _ = lro.load_trades(name, repo)
    sym, tf = rec["symbol"], rec["timeframe"]
    src = None
    if candles is None and trades:
        first = pd.Timestamp(min(t["entry_time"] for t in trades))
        if first.tzinfo is None:
            first = first.tz_localize("UTC")
        days = int((pd.Timestamp.now(tz="UTC") - first).days + 30)
        if fetch:
            src = str(fetch_candles(sym, tf, days, (candle_dir or repo / "comms" / "research" / "_desk_replay")
                                    / f"{sym}_{tf}_{days}d.csv", repo))
        else:
            src = lro.find_candles(sym, tf, repo)
        candles = lro.load_candles(src) if src else None
    atr = None
    if candles is not None:
        bars = [{"time": int(ts.timestamp()), "open": float(r.open), "high": float(r.high),
                 "low": float(r.low), "close": float(r.close)} for ts, r in candles.iterrows()]
        atr = pd.Series(dsp.atr_series(bars), index=candles.index, dtype="float64")
    cs = rec.get("cost_stack") or {}
    slip, fund = xc.resolve_cost_policy(sym)
    starts = sorted(pd.Timestamp(f["start"]).tz_convert("UTC") if pd.Timestamp(f["start"]).tzinfo
                    else pd.Timestamp(f["start"]).tz_localize("UTC") for f in rec.get("fold_detail") or [])
    return Leg(name, sym, tf, trades, candles, src, atr, float(cs.get("fees", xc.DEFAULT_FEE_BPS_ROUNDTRIP)),
               slip, fund, cs, starts, int(rec.get("n_trades_oos") or len(trades)))


def fold_of(leg: Leg, entry_time: Any) -> Optional[int]:
    """1-based fold index: the fold whose [start_i, start_{i+1}) holds the entry; None if there are no folds."""
    if not leg.fold_starts:
        return None
    et = pd.Timestamp(entry_time)
    et = et.tz_localize("UTC") if et.tzinfo is None else et.tz_convert("UTC")
    idx = 0
    for i, s in enumerate(leg.fold_starts):
        if et >= s:
            idx = i
    return idx + 1


# ----------------------------------------------------------------------------- decision points

@dataclass
class Point:
    leg: Leg
    trade: Dict[str, Any]
    path: Dict[str, Any]
    j0: int
    atr_over_r: float
    fold: Optional[int]
    packet_id: str = ""
    pre_cutoff: Optional[bool] = None

    @property
    def sign(self) -> float:
        return 1.0 if self.trade["direction"] == "long" else -1.0


def _id(seed: int, leg: str, entry_time: str) -> str:
    return "P-" + hashlib.sha256(f"{seed}|{leg}|{entry_time}".encode()).hexdigest()[:12]


def replay_state(leg: Leg, t: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """("path", path) | ("zero_bar", None) | ("no_candles", None). A trade recorded as entering and exiting on
    the same bar has no bar after entry to replay: its HOLD is the recorded exit and it carries no decision."""
    if leg.candles is None:
        return "no_candles", None
    path = lro._paths(t, leg.candles)
    if path is not None:
        return "path", path
    et, xt = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
    if et.tzinfo is None:
        et, xt = et.tz_localize("UTC"), xt.tz_localize("UTC")
    if et == xt and leg.candles.index[0] <= et <= leg.candles.index[-1] and et in leg.candles.index:
        return "zero_bar", None
    return "no_candles", None


def replayed_mfe(t: Dict[str, Any], path: Dict[str, Any]) -> float:
    """Candle-path MFE in R with the exit bar capped at the recorded exit (a take-profit bar's high can
    run past the fill, which the harness's own mfe_r does not count)."""
    hi = list(path["hi"])
    cap = max(float(t["gross_r"]), 0.0)
    last = min(hi[-1], max(cap, max(hi[:-1], default=-math.inf)))
    return max(hi[:-1] + [last])


def build_points(leg: Leg, seed: int = DEFAULT_SEED) -> Tuple[List[Point], Dict[str, Any]]:
    """Decision points for one leg, with every exclusion counted (a population, not a silent filter)."""
    pop = {"trades": len(leg.trades), "no_candles": 0, "never_reached_peak_on_candles": 0,
           "closed_on_decision_bar": 0, "zero_bar_trades": 0, "no_atr": 0, "decision_points": 0,
           "recorded_mfe_ge_peak": sum(1 for t in leg.trades if float(t["mfe_r"]) >= PEAK_R),
           "mfe_replay_mismatch": 0}
    pts: List[Point] = []
    if leg.candles is None:
        pop["no_candles"] = len(leg.trades)
        return pts, pop
    for t in leg.trades:
        state, path = replay_state(leg, t)
        if state == "zero_bar":
            pop["zero_bar_trades"] += 1
            continue
        if path is None:
            pop["no_candles"] += 1
            continue
        j0 = lro.review_bar(path, PEAK_R)
        if j0 is None:
            pop["never_reached_peak_on_candles"] += 1
            continue
        if j0 >= len(path["idx"]) - 1:
            pop["closed_on_decision_bar"] += 1      # the recorded exit is the bar that crossed +1R
            continue
        a = leg.atr.get(path["idx"][0] - pd.Timedelta(seconds=dsp.TF_SECONDS[leg.timeframe]))
        if a is None or not np.isfinite(a) or a <= 0:
            pop["no_atr"] += 1
            continue
        if abs(replayed_mfe(t, path) - float(t["mfe_r"])) > lro.MFE_TOL_R:
            pop["mfe_replay_mismatch"] += 1
        p = Point(leg, t, path, j0, float(a) / path["r_dist"], fold_of(leg, t["entry_time"]),
                  _id(seed, leg.name, str(t["entry_time"])))
        pts.append(p)
    pop["decision_points"] = len(pts)
    return pts, pop


# ----------------------------------------------------------------------------- packets (masked, no lookahead)

def _bar_close_time(ts: pd.Timestamp, tf: str) -> pd.Timestamp:
    return ts + pd.Timedelta(seconds=dsp.TF_SECONDS[tf])


def build_packet(p: Point) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(masked packet, unmask-key row). Uses ONLY candles whose open time <= the decision bar's open."""
    leg, t, path = p.leg, p.trade, p.path
    dec_ts = path["idx"][p.j0]
    bars = leg.candles.loc[:dec_ts].iloc[-LOOKBACK_BARS:]     # label-based slice: nothing after dec_ts
    scale = 100.0 / float(bars["close"].iloc[-1])
    sec = dsp.TF_SECONDS[leg.timeframe]
    n = len(bars)
    out_bars = []
    for i, (ts, r) in enumerate(bars.iterrows()):
        close_t = MASK_DECISION_CLOSE - timedelta(seconds=sec * (n - 1 - i))
        out_bars.append({"k": i - (n - 1), "t": close_t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "o": round(float(r.open) * scale, 4), "h": round(float(r.high) * scale, 4),
                         "l": round(float(r.low) * scale, 4), "c": round(float(r.close) * scale, 4)})
    atr_now = float(leg.atr.loc[dec_ts])
    ext = max(path["hi"][: p.j0 + 1])
    entry, sl = float(t["entry"]), float(t["sl"])
    family = "trend_donchian" if "donchian" in leg.name else ("pullback" if "pullback" in leg.name else "unknown")
    packet = {
        "packet_id": p.packet_id, "kind": "in_trade",
        "mask": {"symbol": "ASSET_01", "prices": "rebased to 100 at the decision-bar close",
                 "time": "anchored; bar close of k=0 is the decision instant",
                 "withheld": ["volume", "calendar", "funding", "date", "symbol name"]},
        "trade": {
            "strategy_family": family, "timeframe": leg.timeframe, "side": t["direction"],
            "entry_px": round(entry * scale, 4), "stop_initial_px": round(sl * scale, 4),
            "r_in_atr": round(path["r_dist"] / (atr_now if atr_now else float("nan")), 4) if atr_now else None,
            "atr_now": round(atr_now * scale, 4), "atr_over_r_at_entry": round(p.atr_over_r, 4),
            "open_r": round(path["close"][p.j0], 4), "peak_r": round(ext, 4), "bars_held": p.j0 + 1,
            "current_stop": {"read_state": "could_not_look"}, "take_profit": {"read_state": "could_not_look"},
        },
        "bars": out_bars,
        "missing_inputs": ["trade.current_stop: the committed trade list carries the initial stop only",
                           "trade.take_profit: not in the committed trade list",
                           "volume, calendar, funding: masked"],
    }
    key = {"packet_id": p.packet_id, "leg": leg.name, "symbol": leg.symbol, "entry_time": str(t["entry_time"]),
           "decision_bar_open": str(dec_ts), "decision_close": str(_bar_close_time(dec_ts, leg.timeframe)),
           "fold": p.fold, "real_entry": entry, "price_scale": scale}
    return packet, key


def leak_scan(packet_text: str, key: Dict[str, Any]) -> List[str]:
    """Findings for one serialised packet against its own unmask key. [] = no leak found."""
    out: List[str] = []
    low = packet_text.lower()
    sym = str(key["symbol"]).lower()
    base = re.sub(r"(usdt|usdc|usd|perp)$", "", sym)
    for tok in {sym, base, str(key["leg"]).lower()}:
        if tok and tok in low:
            out.append(f"symbol/leg token {tok!r}")
    real = float(key["real_entry"])
    try:
        obj = json.loads(packet_text)
    except ValueError:
        return sorted(set(out + ["packet is not valid JSON"]))

    def walk(x: Any, k: str = "") -> None:
        if isinstance(x, dict):
            for kk, v in x.items():
                walk(v, kk)
        elif isinstance(x, list):
            for v in x:
                walk(v, k)
        elif isinstance(x, str):
            # dates/years only matter in STRING fields: a 4-digit number among prices is a price
            for m in re.finditer(r"(?<![\w.])((?:19|20)\d{2})(?![\w.])", x):
                if m.group(1) != ALLOWED_YEAR:
                    out.append(f"year {m.group(1)!r} in string field {k!r}")
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            if 1.5e9 <= abs(x) < 2e9 and float(x).is_integer():
                out.append(f"epoch-seconds number in {k!r}")
            if k in PRICE_KEYS and real and abs(x - real) <= 0.005 * abs(real):
                out.append(f"price field {k}={x} within 0.5% of the real entry")
    walk(obj)
    return sorted(set(out))


# ----------------------------------------------------------------------------- pricing an action

def _net_from_exit(p: Point, gross_r: float, exit_ts: pd.Timestamp, extra_r: float = 0.0) -> float:
    """Net R of exiting the WHOLE position at ``gross_r`` at ``exit_ts``: full cost stack, recomputed."""
    t = p.trade
    entry, rd = float(t["entry"]), p.path["r_dist"]
    px = entry + p.sign * gross_r * rd
    c = xc.roundtrip_cost_r(entry=entry, exit_price=px, risk=rd, entry_time=str(t["entry_time"]),
                            exit_time=str(exit_ts), fee_bps_roundtrip=p.leg.fee_bps,
                            slippage_bps_roundtrip=p.leg.slip_bps, funding_bps_per_window=p.leg.fund_bps)
    return gross_r - c["total_cost_r"] - extra_r


def _tighten_valid(p: Point, j: int, kind: str, val: float) -> bool:
    price = p.path["close"][j]
    ext = max(p.path["hi"][: j + 1])
    lvl = val if kind == "r" else ext - val * p.atr_over_r
    return -1.0 < lvl < price


def price_action(p: Point, spec: Tuple, j: Optional[int] = None, stop_fill_slip_r: float = STOP_FILL_SLIP_R
                 ) -> Optional[float]:
    """Net R of ``spec`` decided at path bar ``j`` (default: the decision bar). None = invalid spec at that
    bar (the caller decides what invalid means; it is never silently priced)."""
    recorded = float(p.trade["net_r"])
    kind = spec[0]
    if kind == "hold":
        return recorded                            # the leg's own exit, untouched
    j = p.j0 if j is None else j
    n = len(p.path["idx"])
    if j >= n - 1:
        return None                                # nothing left to act on
    if kind == "tighten":
        _, k, val = spec
        if not _tighten_valid(p, j, k, val):
            return None
        hit = lro.replay_tighten(p.path, j, k, val, p.atr_over_r)
        if hit is None:
            return recorded                        # the stop was never touched: the recorded exit stands
        gross, ts = hit
        return _net_from_exit(p, gross, ts, stop_fill_slip_r)
    if kind == "close":
        return _net_from_exit(p, p.path["open"][j + 1], p.path["idx"][j + 1])
    if kind == "partial_close":
        return 0.5 * _net_from_exit(p, p.path["open"][j + 1], p.path["idx"][j + 1]) + 0.5 * recorded
    if kind == "close_at_r":                       # a take-profit limit at +x R after the decision bar
        x = spec[1]
        for jj in range(j + 1, n):
            if p.path["hi"][jj] >= x:
                fill = max(x, p.path["open"][jj])  # a gap through the limit fills at the open
                return _net_from_exit(p, fill, p.path["idx"][jj])
        return recorded
    raise ValueError(f"unknown action spec {spec!r}")


def dR(p: Point, spec: Tuple, j: Optional[int] = None, slip: float = STOP_FILL_SLIP_R) -> Optional[float]:
    v = price_action(p, spec, j, slip)
    return None if v is None else v - float(p.trade["net_r"])


# ----------------------------------------------------------------------------- actions intake

def parse_action(row: Dict[str, Any], role: str) -> Tuple[Tuple, Optional[str]]:
    """(spec, problem). A problem means the row is scored as HOLD and counted as invalid."""
    a = row.get("action")
    if a not in ROLE_ACTIONS[role]:
        return ("hold",), f"action {a!r} not in {ROLE_ACTIONS[role]}"
    if a == "tighten_sl":
        lv = row.get("level") or {}
        if lv.get("kind") not in ("atr", "r") or not isinstance(lv.get("value"), (int, float)) \
                or isinstance(lv.get("value"), bool):
            return ("hold",), "tighten_sl without a {kind: atr|r, value: number} level"
        return ("tighten", lv["kind"], float(lv["value"])), None
    return (a,), None


def read_actions(path: Path, role: str, valid_ids: set) -> Dict[str, Tuple[Tuple, Optional[str]]]:
    out: Dict[str, Tuple[Tuple, Optional[str]]] = {}
    for ln, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        pid = row.get("packet_id")
        if pid not in valid_ids:
            raise ValueError(f"{path}:{ln}: packet_id {pid!r} is not in the mask key")
        if row.get("role") != role:
            raise ValueError(f"{path}:{ln}: role {row.get('role')!r} != {role!r}")
        if pid in out:
            raise ValueError(f"{path}:{ln}: duplicate action for {pid}")
        out[pid] = parse_action(row, role)
    return out


# ----------------------------------------------------------------------------- statistics

def boot_ci(x: Sequence[float], rng: np.random.Generator, draws: int = BOOT_DRAWS) -> Tuple[float, float, float]:
    a = np.asarray(x, dtype=float)
    if len(a) == 0:
        return (float("nan"),) * 3
    idx = rng.integers(0, len(a), size=(draws, len(a)))
    m = a[idx].mean(axis=1)
    return float(a.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def _r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def b2_random_timing(points: List[Point], freq: Dict[Tuple, float], seed: int,
                     slip: float) -> np.ndarray:
    """Per-point mean dR over B2_DRAWS draws: Claude's action mix, applied at random valid bars of the same trade.
    A drawn non-hold action with no valid bar on that trade scores 0 (it could not be applied) and is not hidden.
    The draw itself is the shared `intervention_controls.matched_random_intervention`."""
    kinds = [s for s in freq if s != ("hold",)]
    table: List[Dict[Tuple, np.ndarray]] = []
    for p in points:
        tb = {}
        for s in kinds:
            vals = [dR(p, s, j, slip) for j in range(len(p.path["idx"]) - 1)]
            tb[s] = np.array([v for v in vals if v is not None], dtype=float)
        table.append(tb)
    return matched_random_intervention(table, freq, seed + 2, B2_DRAWS)


def b3_best_static(points: List[Point], role: str, slip: float) -> Tuple[np.ndarray, Dict[int, Optional[Tuple]]]:
    """Leave-one-fold-out best static rule: for each fold pick the rule with the best mean dR on the OTHER folds."""
    grid = B3_GRIDS[role]
    mat = np.full((len(points), len(grid)), np.nan)
    for i, p in enumerate(points):
        for g, spec in enumerate(grid):
            v = dR(p, spec, None, slip)
            mat[i, g] = np.nan if v is None else v
    return best_static_rule(mat, [p.fold or 0 for p in points], grid)


def required_n(sd: float, effect: float) -> Optional[int]:
    return None if not sd or not np.isfinite(sd) else int(math.ceil((2.8 * sd / effect) ** 2))


def grade_role(stats: Dict[str, Any]) -> Tuple[str, List[str]]:
    """The registered rule of bf56-02 / -03. ``stats`` carries already-computed numbers; this only decides."""
    why: List[str] = []
    n = stats["n_obs"]
    if n < N_MIN:
        return "indeterminate", [f"n_obs {n} < {N_MIN}"]
    if stats["selfcheck"] is not True:
        scr = stats["selfcheck"]
        if scr is False and stats.get("scrambled_nonzero"):
            return "fail", ["the scrambled-label arm of RQ-20261026-bf56-01 was nonzero"]
        return "indeterminate", ["the bf56-01 self-check verdict was not supplied or is not a pass"]
    if stats["mean"] <= 0 or stats["ci_hi"] < 0:
        return "fail", [f"mean dR {stats['mean']:+.4f} <= 0 or CI upper bound {stats['ci_hi']:+.4f} < 0"]
    checks = [
        (stats["ci_lo"] > 0, "CI lower bound > 0"),
        (stats["mean"] > stats["b2_mean"] and stats["b2_diff_lo"] > 0, "beats B2 random timing with the paired CI excluding 0"),
        (stats["mean"] >= stats["b3_mean"], "mean dR >= B3 best static"),
        (stats["folds_positive"] >= FOLDS_NEEDED, f"dR > 0 in >= {FOLDS_NEEDED} of 4 pooled folds"),
    ]
    post = stats["post_cutoff"]
    if post["state"] == "could_not_look":
        why.append("post-cutoff stratum could not be formed (no --model-cutoff)")
        return "indeterminate", why
    if post["n"] >= POST_CUTOFF_MIN_N:
        checks.append((post["mean"] is not None and post["mean"] > 0, "post-cutoff stratum point estimate > 0"))
    failed = [m for ok, m in checks if not ok]
    if failed:
        return "indeterminate", ["not met: " + "; ".join(failed)]
    if post["n"] < POST_CUTOFF_MIN_N:
        why.append("masked-replay only, forward-shadow confirmation required")
    return "pass", why


# ----------------------------------------------------------------------------- scoring (units -02 / -03)

def score(points: List[Point], actions: Dict[str, Tuple[Tuple, Optional[str]]], role: str, *, seed: int,
          cutoff: Optional[pd.Timestamp], selfcheck_pass: Optional[bool], scrambled_nonzero: bool = False
          ) -> Dict[str, Any]:
    judged = [p for p in points if p.packet_id in actions]
    rng = np.random.default_rng(seed)
    specs = [actions[p.packet_id][0] for p in judged]
    invalid = 0
    d_by_slip: Dict[float, List[float]] = {}
    for slip in (STOP_FILL_SLIP_R,) + SENSITIVITIES:
        vals = []
        for p, s in zip(judged, specs):
            v = dR(p, s, None, slip)
            vals.append(0.0 if v is None else v)
        d_by_slip[slip] = vals
    for p, s in zip(judged, specs):
        if actions[p.packet_id][1] is not None or dR(p, s, None, STOP_FILL_SLIP_R) is None:
            invalid += 1
    d = np.array(d_by_slip[STOP_FILL_SLIP_R])
    mean, lo, hi = boot_ci(d, rng)
    freq = Counter(specs)
    freq_f = {s: c / len(specs) for s, c in freq.items()} if specs else {("hold",): 1.0}
    b2 = b2_random_timing(judged, freq_f, seed, STOP_FILL_SLIP_R) if judged else np.array([])
    diff = d - b2
    dmean, dlo, dhi = boot_ci(diff, rng)
    b3, chosen = b3_best_static(judged, role, STOP_FILL_SLIP_R) if judged else (np.array([]), {})
    folds_mean: Dict[str, Any] = {}
    for f in (1, 2, 3, 4):
        m = [x for x, p in zip(d, judged) if p.fold == f]
        folds_mean[str(f)] = {"n": len(m), "mean_dR": _r(float(np.mean(m))) if m else None}
    folds_pos = sum(1 for v in folds_mean.values() if v["mean_dR"] is not None and v["mean_dR"] > 0)
    if cutoff is None:
        post = {"state": "could_not_look", "n": 0, "mean": None}
    else:
        m = [x for x, p in zip(d, judged) if p.pre_cutoff is False]
        post = {"state": "measured", "n": len(m), "mean": _r(float(np.mean(m))) if m else None}
    per_leg = []
    for leg in sorted({p.leg.name for p in judged}):
        m = [x for x, p in zip(d, judged) if p.leg.name == leg]
        if len(m) < LEG_N_FLOOR:
            per_leg.append({"leg": leg, "n_obs": len(m), "state": "insufficient_n", "mean_dR": None, "ci": None})
        else:
            a, lo_, hi_ = boot_ci(m, rng)
            per_leg.append({"leg": leg, "n_obs": len(m), "state": "measured", "mean_dR": _r(a), "ci": [_r(lo_), _r(hi_)]})
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    stats = {"n_obs": len(judged), "mean": mean, "ci_lo": lo, "ci_hi": hi, "b2_mean": float(b2.mean()) if len(b2) else 0.0,
             "b2_diff_lo": dlo, "b3_mean": float(b3.mean()) if len(b3) else 0.0, "folds_positive": folds_pos,
             "post_cutoff": post, "selfcheck": selfcheck_pass, "scrambled_nonzero": scrambled_nonzero}
    verdict, why = grade_role(stats) if judged else ("indeterminate", ["no judged points"])
    sens = {str(s): _r(float(np.mean(v))) for s, v in d_by_slip.items() if len(v)}
    return {
        "verdict": verdict, "reasons": why, "role": role, "n_obs": len(judged), "n_packets": len(points),
        "n_unjudged": len(points) - len(judged), "n_invalid_actions_scored_as_hold": invalid,
        "mean_dR": _r(mean), "ci95": [_r(lo), _r(hi)], "observed_paired_sd": _r(sd),
        "n_to_resolve": {f"{RESOLVE_EFFECT[role]:+.2f}R": required_n(sd, RESOLVE_EFFECT[role])},
        "sensitivity_mean_dR_by_stop_fill_slip_r": sens,
        "b1_hold_mean_dR": 0.0, "b2_random_timing": {"mean_dR": _r(stats["b2_mean"]), "draws": B2_DRAWS,
                                                    "paired_diff_mean": _r(dmean), "paired_diff_ci95": [_r(dlo), _r(dhi)]},
        "b3_best_static": {"mean_dR": _r(stats["b3_mean"]), "rule_by_held_out_fold": {str(k): v for k, v in chosen.items()}},
        "folds": folds_mean, "folds_positive": folds_pos, "post_cutoff": post, "per_leg": per_leg,
        "action_mix": {str(k): v for k, v in sorted(freq.items(), key=lambda kv: -kv[1])},
        "seed": seed, "bootstrap_draws": BOOT_DRAWS,
    }


# ----------------------------------------------------------------------------- self-check (unit -01)

def fidelity_diagnostics(points_all: Dict[str, List[Point]], legs: Dict[str, Leg]) -> Dict[str, Any]:
    """The non-vacuous half of the self-check: reported, not decisive (see the module docstring)."""
    cost_dev = 0.0
    inside = outside = 0
    implied: Dict[str, float] = {}
    for name, leg in legs.items():
        mults = []
        for t in leg.trades:
            if leg.candles is None:
                continue
            path = lro._paths(t, leg.candles)
            if path is None:
                continue
            sign = 1.0 if t["direction"] == "long" else -1.0
            rd = path["r_dist"]
            px = float(t["entry"]) + sign * float(t["gross_r"]) * rd
            c = xc.roundtrip_cost_r(entry=t["entry"], exit_price=px, risk=rd, entry_time=str(t["entry_time"]),
                                    exit_time=str(t["exit_time"]), fee_bps_roundtrip=leg.fee_bps,
                                    slippage_bps_roundtrip=leg.slip_bps, funding_bps_per_window=leg.fund_bps)
            rec = float(t["cost_fee_r"]) + float(t["cost_slippage_r"]) + float(t["cost_funding_r"])
            cost_dev = max(cost_dev, abs(c["total_cost_r"] - rec))
            lo_r, hi_r = min(path["lo"][-1], path["hi"][-1]), max(path["lo"][-1], path["hi"][-1])
            g = float(t["gross_r"])
            # exit price must lie inside the exit bar's range (a trail/TP can fill anywhere in it); tolerance 0.02 R
            if lo_r - 0.02 <= g <= hi_r + 0.02 or t.get("exit_reason") == "timeout":
                inside += 1
            else:
                outside += 1
            a = leg.atr.get(path["idx"][0] - pd.Timedelta(seconds=dsp.TF_SECONDS[leg.timeframe]))
            if a and np.isfinite(a):
                mults.append(rd / float(a))
        implied[name] = round(float(np.median(mults)), 3) if mults else None
    return {
        "cost_stack_recompute_max_abs_dev_R": _r(cost_dev, 7),
        "cost_stack_note": "recorded costs are rounded to 5 dp; ~1e-5 R is rounding, 1e-3 R or more would be a policy mismatch",
        "exit_gross_r_inside_exit_bar_range": inside, "exit_gross_r_outside_exit_bar_range": outside,
        "median_implied_atr_stop_mult_by_leg": implied,
        "mfe_replay_mismatch_by_leg": {n: sum(1 for p in pts if abs(replayed_mfe(p.trade, p.path) - float(p.trade['mfe_r'])) > lro.MFE_TOL_R)
                                       for n, pts in points_all.items()},
    }


def planted_known_answer(points: List[Point]) -> Dict[str, Any]:
    """A planted case with a known answer. The ORACLE policy picks, per decision point and with hindsight,
    the better of hold / breakeven-tighten; so its mean dR must be >= 0 and >= the plain breakeven tighten.
    A harness that fails this prices the paths wrongly. Raises on failure (a harness bug, not a verdict)."""
    be = ("tighten", "r", 0.0)
    plain, oracle = [], []
    for p in points:
        v = dR(p, be) or 0.0
        plain.append(v)
        oracle.append(max(0.0, v))
    # the same oracle's decisions replayed against PERMUTED outcomes must lose the information it had
    act = [o > 0.0 for o in oracle]
    perm = np.random.default_rng(DEFAULT_SEED + 7).permutation(len(points)) if points else []
    scrambled = [(plain[int(perm[i])] if act[i] else 0.0) for i in range(len(points))]
    out = {"n": len(points), "breakeven_tighten_mean_dR": _r(float(np.mean(plain))) if plain else None,
           "oracle_mean_dR": _r(float(np.mean(oracle))) if oracle else None,
           "oracle_scrambled_mean_dR": _r(float(np.mean(scrambled))) if scrambled else None}
    if points and not (min(oracle) >= 0.0 and np.mean(oracle) >= np.mean(plain) - 1e-12):
        raise AssertionError(f"planted known-answer case failed: {out}")
    if not points or np.mean(oracle) <= 0.0:
        # no decision point where the planted action helps: the case has nothing to detect, so it proves nothing
        out.update(passed=False, state="vacuous_no_point_where_the_planted_action_helps")
        return out
    if not np.mean(oracle) > np.mean(scrambled):
        raise AssertionError(f"planted known-answer case failed (scrambling kept the information): {out}")
    out.update(passed=True, state="passed")
    return out


def oracle_arms(pts_by_leg: Dict[str, List[Point]], rng: np.random.Generator
                ) -> Tuple[List[float], List[float], List[float]]:
    """(oracle aligned dR, the same oracle decisions against outcome ids permuted WITHIN LEG, plain breakeven dR).
    The oracle takes the breakeven tighten at +1R iff hindsight says it beats holding."""
    be = ("tighten", "r", 0.0)
    aligned_o: List[float] = []
    scrambled_o: List[float] = []
    breakeven: List[float] = []
    for pts in pts_by_leg.values():
        plain = [dR(p, be) or 0.0 for p in pts]
        act = [v > 0.0 for v in plain]
        perm = rng.permutation(len(pts))
        aligned_o += [v if a_ else 0.0 for v, a_ in zip(plain, act)]
        scrambled_o += [plain[int(perm[i])] if act[i] else 0.0 for i in range(len(pts))]
        breakeven += plain
    return aligned_o, scrambled_o, breakeven


def selfcheck(legs: Dict[str, Leg], population: List[str], seed: int) -> Dict[str, Any]:
    """Unit bf56-01, with the registered clauses (c as re-registered 2026-10-26) decided exactly as registered."""
    rng = np.random.default_rng(seed)
    per_leg, pts_by_leg, all_pts = {}, {}, []
    replayed = recorded = 0
    max_dev = 0.0
    missing = []
    for name in population:
        leg = legs[name]
        pts, pop = build_points(leg, seed)
        pts_by_leg[name] = pts
        all_pts += pts
        n_rep = 0
        for t in leg.trades:
            state, path = replay_state(leg, t)
            if state == "no_candles":
                continue
            n_rep += 1
            # clause (a): the HOLD replay through the SAME pricing function the scorer uses
            max_dev = max(max_dev, abs(price_action(Point(leg, t, path, 0, 1.0, None), ("hold",)) - float(t["net_r"])))
        replayed += n_rep
        recorded += len(leg.trades)
        if n_rep < len(leg.trades) and leg.candles is not None:
            lo, hi = leg.candles.index[0], leg.candles.index[-1]
            missing.append({"leg": name, "not_replayed": len(leg.trades) - n_rep,
                            "candle_window": [str(lo), str(hi)]})
        elif leg.candles is None:
            missing.append({"leg": name, "not_replayed": len(leg.trades), "candle_window": None})
        per_leg[name] = {"trades": len(leg.trades), "replayed": n_rep, "n_trades_oos_in_record": leg.n_trades_oos,
                         "population": pop}
    # clause (b): scan every built packet; first prove the probe can find a positive (RULE ONE)
    leaks, n_packets = [], 0
    probe_ok = None
    for pts in pts_by_leg.values():
        for p in pts:
            pk, key = build_packet(p)
            txt = json.dumps(pk, sort_keys=True)
            n_packets += 1
            found = leak_scan(txt, key)
            if found:
                leaks.append({"packet_id": p.packet_id, "leg": p.leg.name, "findings": found})
            if probe_ok is None:
                bad = json.loads(txt)
                bad["trade"]["note"] = f"{key['symbol']} {key['entry_time'][:10]}"
                bad["bars"][0]["c"] = round(key["real_entry"], 4)
                probe_ok = len(leak_scan(json.dumps(bad), key)) >= 3
                if not probe_ok:
                    raise AssertionError("leak scanner failed its positive control: it cannot see a planted leak")
    # clause (c), re-registered 2026-10-26 (manager decision, see RQ-20261026-bf56-01): STRUCTURAL, no tuned band.
    #   (c1) the hindsight oracle's aligned mean dR > 0 with its 95% CI lower bound > 0 (the harness can see information);
    #   (c2) the SAME oracle decisions replayed against outcome ids permuted within leg: the 95% CI contains 0
    #        (scrambling destroys the information).
    aligned_o, scrambled_o, breakeven = oracle_arms(pts_by_leg, rng)
    a_mean, a_lo, a_hi = boot_ci(aligned_o, rng)
    s_mean, s_lo, s_hi = boot_ci(scrambled_o, rng)
    b_mean, b_lo, b_hi = boot_ci(breakeven, rng)
    planted = planted_known_answer(all_pts)
    a_ok = replayed == REGISTERED_N_TRADES and max_dev <= SELFCHECK_TOL_R
    b_ok = n_packets > 0 and not leaks
    c1_ok = bool(aligned_o) and a_mean > 0.0 and a_lo > 0.0
    c2_ok = bool(scrambled_o) and s_lo <= 0.0 <= s_hi
    c_ok = c1_ok and c2_ok
    complete = replayed == REGISTERED_N_TRADES
    if not complete:
        verdict = "indeterminate"
        note = (f"fewer than the registered {REGISTERED_N_TRADES} trades are replayable (candles for a leg window could not be "
                "fetched): " + json.dumps(missing) + ". bf56-02/-03 stay blocked.")
    elif a_ok and b_ok and c_ok:
        verdict, note = "pass", "all three registered clauses hold"
    else:
        bad = [n for n, ok in (("(a)", a_ok), ("(b)", b_ok), ("(c1)", c1_ok), ("(c2)", c2_ok)) if not ok]
        verdict = "fail"
        note = "violated clause(s) " + ", ".join(bad) + "; DESK-7B-REPLAY-DRIVER reopens (registered wording)."
    return {
        "verdict": verdict, "read_state": "measured" if all_pts or complete else "no_data", "note": note,
        "clauses": {"a_hold_replay": {"ok": a_ok, "max_abs_dR": max_dev, "tol": SELFCHECK_TOL_R,
                                      "replayed": replayed, "of": REGISTERED_N_TRADES, "trades_in_lists": recorded},
                    "b_mask": {"ok": b_ok, "packets_scanned": n_packets, "leaks": leaks[:20], "n_leaking": len(leaks),
                               "probe_positive_control_found_planted_leak": probe_ok},
                    "c_scrambled_label": {"ok": c_ok, "n": len(aligned_o),
                                          "c1_oracle_aligned": {"ok": c1_ok, "mean_dR": _r(a_mean), "ci95": [_r(a_lo), _r(a_hi)]},
                                          "c2_oracle_scrambled": {"ok": c2_ok, "mean_dR": _r(s_mean), "ci95": [_r(s_lo), _r(s_hi)]},
                                          "oracle": "breakeven (r:0.0) at the +1R decision state iff hindsight says it beats hold"}},
        # A SEPARATE finding, not a clause: the packet-blind breakeven-at-+1R policy's own mean dR. Kept for the
        # exit-refinement queue (pipeline item), where it was first measured as -0.1195 R over 176 points.
        "breakeven_at_1r_finding": {"mean_dR": _r(b_mean), "ci95": [_r(b_lo), _r(b_hi)], "n": len(breakeven),
                                    "population": f"{len(breakeven)} decision points over {recorded} committed trades, {len(population)} legs"},
        "fidelity_diagnostics": fidelity_diagnostics(pts_by_leg, {n: legs[n] for n in population}),
        "planted_known_answer": planted, "per_leg": per_leg,
        "scrambled_nonzero": not c_ok,
    }


# ----------------------------------------------------------------------------- CLI

def _legs(a: argparse.Namespace) -> Tuple[List[str], Dict[str, Leg], str]:
    parsed = parse_population()
    population = a.legs.split(",") if a.legs else parsed
    note = ("population re-parsed from config/accounts.yaml + strategies.yaml: " + ", ".join(parsed)
            + ("" if sorted(parsed) == sorted(REGISTERED_LEGS) else f" -- DIFFERS from the registered {list(REGISTERED_LEGS)}"))
    cdir = Path(a.out) / "candles"
    legs = {n: load_leg(n, fetch=a.fetch, candle_dir=cdir) for n in population}
    return population, legs, note


def _write_verdict(out: Path, v: Dict[str, Any], population: str, n: Optional[int], measurement: Dict[str, Any],
                   note: str, records: Optional[List[Dict[str, Any]]] = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    doc = {"verdict": v["verdict"], "read_state": v.get("read_state", "measured"), "population": population,
           "n": n, "measurement": measurement, "note": note,
           "data_inputs": sorted({s for s in (measurement.get("candle_sources") or []) if s})}
    if records:
        doc["records"] = records
    (out / "verdict.json").write_text(json.dumps(doc, indent=2, default=str) + "\n")


def cmd_selfcheck(a: argparse.Namespace) -> int:
    population, legs, pnote = _legs(a)
    res = selfcheck(legs, population, a.seed)
    res["candle_sources"] = [legs[n].candle_src for n in population]
    n_tr = sum(len(legs[n].trades) for n in population)
    pop = (f"{len(population)} real-money non-prop 2h/4h legs ({', '.join(population)}); {n_tr} committed Stage-0 trades "
           f"(comms/strategy_evidence/<leg>.json -> source_run); registered population {REGISTERED_N_TRADES}")
    recs = [{"leg": n, "population": f"{n}: {d['trades']} trades, {d['replayed']} replayed", "n": d["replayed"],
             "verdict": res["verdict"], "read_state": "measured" if d["replayed"] else "no_data"}
            for n, d in res["per_leg"].items()]
    _write_verdict(Path(a.out), res, pop, n_tr, res, f"{res['note']} | {pnote}", recs)
    print(json.dumps({"verdict": res["verdict"], "clauses": {k: v["ok"] for k, v in res["clauses"].items()},
                      "replayed": res["clauses"]["a_hold_replay"]["replayed"]}))
    return 0


def _all_points(population: List[str], legs: Dict[str, Leg], seed: int) -> Tuple[List[Point], Dict[str, Any]]:
    pts, pops = [], {}
    for n in population:
        p, pop = build_points(legs[n], seed)
        pts += p
        pops[n] = pop
    return pts, pops


def cmd_packets(a: argparse.Namespace) -> int:
    population, legs, pnote = _legs(a)
    pts, pops = _all_points(population, legs, a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys, leaked = [], 0
    with (out / "packets.jsonl").open("w") as fh:
        for p in pts:
            pk, key = build_packet(p)
            txt = json.dumps(pk, sort_keys=True)
            if leak_scan(txt, key):
                leaked += 1
                continue                                 # a leaking packet is never handed to a judge
            fh.write(txt + "\n")
            keys.append(key)
    (out / "mask-key.json").write_text(json.dumps({"seed": a.seed, "note": "NEVER given to the judging session",
                                                    "keys": keys}, indent=2) + "\n")
    size = [len(json.dumps(build_packet(p)[0], sort_keys=True)) for p in pts[:50]]
    print(json.dumps({"packets": len(keys), "withheld_for_leak": leaked, "population": pops, "note": pnote,
                      "median_packet_chars": int(np.median(size)) if size else None}))
    return 0


def cmd_score(a: argparse.Namespace) -> int:
    population, legs, pnote = _legs(a)
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    pts, pops = _all_points(population, legs, a.seed)
    cutoff = pd.Timestamp(a.model_cutoff, tz="UTC") if a.model_cutoff else None
    for p in pts:
        if p.packet_id not in keys:
            continue
        dec = pd.Timestamp(keys[p.packet_id]["decision_close"])
        p.pre_cutoff = None if cutoff is None else bool(dec < cutoff)
    actions = read_actions(Path(a.actions_file), a.role, set(keys))
    sc_pass: Optional[bool] = None
    scr_nonzero = False
    if a.selfcheck_verdict:
        sv = json.loads(Path(a.selfcheck_verdict).read_text())
        sc_pass = sv.get("verdict") == "pass"
        scr_nonzero = not ((sv.get("measurement") or {}).get("clauses", {}).get("c_scrambled_label", {}).get("ok", True))
    pts = [p for p in pts if p.packet_id in keys]
    res = score(pts, actions, a.role, seed=a.seed, cutoff=cutoff, selfcheck_pass=sc_pass, scrambled_nonzero=scr_nonzero)
    res["candle_sources"] = [legs[n].candle_src for n in population]
    res["decision_point_population"] = pops
    pop = (f"{a.role} role, {res['n_obs']} judged decision points of {res['n_packets']} packets "
           f"(first closed bar with running high >= +1.0 R) over {', '.join(population)}")
    notes = "; ".join(res["reasons"]) or "all registered clauses met"
    recs = [{"leg": r["leg"], "population": f"{r['leg']} {a.role}", "n": r["n_obs"], "verdict": "not_applicable",
             "read_state": "measured" if r["state"] == "measured" else "no_data",
             "mean_dR": r["mean_dR"], "ci95": r["ci"]} for r in res["per_leg"]]
    _write_verdict(Path(a.out), res, pop, res["n_obs"], res, f"{notes} | {pnote}", recs or None)
    print(json.dumps({"verdict": res["verdict"], "n_obs": res["n_obs"], "mean_dR": res["mean_dR"], "ci95": res["ci95"]}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("selfcheck", cmd_selfcheck), ("packets", cmd_packets), ("score", cmd_score)):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--fetch", action="store_true", help="top up candles from Binance Vision (the queue runner)")
        s.add_argument("--legs", help="comma list; default = re-parse the real-money 2h/4h population")
        s.add_argument("--seed", type=int, default=DEFAULT_SEED)
        # DESK-8b: a different registered population (the two 15m ict_scalp legs) registers its OWN trade count and
        # n floor in its queue unit; unset = the bf56 registered 370 / 126, byte-identical to before.
        s.add_argument("--registered-n", type=int, help="the unit's registered replayable-trade count (default 370)")
        s.add_argument("--n-min", type=int, help="the unit's registered pass floor for n_obs (default 126)")
        s.set_defaults(fn=fn)
        if name == "score":
            s.add_argument("--role", required=True, choices=list(ROLE_ACTIONS))
            s.add_argument("--actions-file", required=True)
            s.add_argument("--mask-key", required=True)
            s.add_argument("--selfcheck-verdict")
            s.add_argument("--model-cutoff", help="the judge model's knowledge cutoff date, YYYY-MM-DD")
    a = ap.parse_args(argv)
    global REGISTERED_N_TRADES, N_MIN
    if a.registered_n is not None:
        REGISTERED_N_TRADES = a.registered_n
    if a.n_min is not None:
        N_MIN = a.n_min
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

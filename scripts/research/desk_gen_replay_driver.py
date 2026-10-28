#!/usr/bin/env python3
# wiring: manual-only - run by the judging lane (`packets`, `intake`) and by research/queue units RQ-20261026-e535-01..04 via research-script-run.yml (`selfcheck`, `baselines`, `score`); no schedule consumes it.
"""DESK-18-GEN-REPLAY-S0 -- the D-S0 blind-replay driver for the desk's ENTRY-GENERATION role.

Design: docs/plans/claude-trading-desk-DESIGN.md section 8.1 (D-S0, entry generation), section 10.2 row 5.
Sibling of scripts/research/desk_replay_driver.py (DESK-7B: in-trade / exit); this file composes, never
rewrites, the pieces that exist: scripts/ops/desk_scan_packet.py (the scan builder and its masking),
scripts/ci/check_desk_records.py (the proposal guard), src/runtime/execution_costs.py (the cost stack) and
the committed Stage-0 trade lists. Tier 1 research tooling: reads candles and committed evidence, writes
only under --out.

WHAT IS REPLAYED
----------------
packet      A MASKED scan packet (desk_scan_packet.build_scan_packet + mask_packet, the single builder the
            live desk uses) at a sampled 1h bar close. Aliases are re-drawn PER PACKET, prices are rebased
            to 100, time is anchored at year 2000, volume / calendar are withheld, every bar at or after
            the cutoff is dropped before anything is computed. The unmask key is a separate file the
            judging session never reads. The historical system_book is NOT reconstructed (the builder says
            so in missing_inputs), so the judge cannot see the strategies' book: a proposal's own
            `novelty` is `unverifiable`, and NOVELTY IS ASSIGNED BY THE SCORER (below), never self-reported.
proposal    At most MAX_PER_PACKET `propose_entry` rows per packet (design 2.4 fields), or `no_trade`.
            Every row passes check_desk_records.proposal_problems (geometry, TP doctrine, p_hit, expected_r)
            against its own masked packet; a refused row is scored as no_trade and COUNTED.
replay      On the REAL candles after the cutoff: entry (market = next open; limit/stop fill only when
            price trades THROUGH the level, a gap fills at the open), SL checked before TP inside a bar, a
            gap fills at the open, a time stop at `horizon_bars` from the fill at that bar's close. A limit
            or stop fill bar credits no TP (ambiguous) but does check the SL. Net R = side*(exit-fill)/risk
            minus execution_costs.roundtrip_cost_r with the venue fee and the resolve_cost_policy()
            slippage + funding (the SAME cost_policy() the packet's base rates use). A fill whose stop is
            on the wrong side of, or within MIN_RISK_ATR x ATR of, the fill - or whose target is already
            passed - is REFUSED and counted, in the desk arm and in every baseline alike.
baselines   B-R random entry: each proposal's own geometry (side, entry offset / stop / target in ATR at its
            cutoff, good_till, horizon) transplanted to B_R_DRAWS random cutoffs of the SAME symbol in the
            SAME fold, same engine, same costs. B-S strategy-own: the committed Stage-0 trade lists on the
            same symbols and window; they also classify novelty.
inference   Weekly-CLUSTER bootstrap (a week is the unit of resampling: simultaneous proposals share a
            market), 10,000 draws, registered seed. The design's n arithmetic (2.8 sd / effect)^2 assumes
            iid; the cluster CI is wider, and the verdict says which it used.

MODES
-----
  selfcheck --out DIR [--fetch]        unit 01: the instrument gates (no-lookahead both directions, mask leak
                                       scan with a positive control, cost fidelity vs the committed stack,
                                       planted oracle / anti-oracle / null policies). No LLM.
  baselines --out DIR [--fetch]        unit 02: random-entry null + strategy-own table + MEASURED sd and the n
                                       that sd implies. No LLM.
  packets   --out DIR [--fetch] --n N [--offset K] [--seed S]
                                       packets.jsonl + JUDGE-PROTOCOL.md (judge) + mask-key.json (scorer only). A
                                       pilot uses a different --seed, so no registered cutoff is touched.
  intake    --out DIR --proposals F --mask-key K
                                       the stopping-rule accounting from the proposals alone (valid proposals,
                                       schedule prefix, next_batch_allowed). NO replay: no outcome is seen.
  score     --out DIR --proposals F --packets P --mask-key K --subset all|new --model-cutoff YYYY-MM-DD
            [--selfcheck-verdict V]    units 03 (all) and 04 (novelty = new).

STATED LIMITS (printed into every verdict)
* Candles are Binance Vision USD-M PERP klines (fetch_backtest_candles.py --source binance_vision reads
  data/futures/um; corrected 2026-10-27, DESK-PACKET-REDESIGN: this line said SPOT) for the six crypto USDT symbols in the pull lists (the CPU-only
  runner route); the ETF / futures symbols of the pull lists are out of scope. The desk's venue is Bybit perp.
* Funding is not in the replayed packet (`could_not_look`); the cost stack still charges it.
* The system book is not reconstructed point in time; novelty is scorer-assigned from the committed lists,
  which cover each leg's own evidence window only (outside it a cutoff is `unclassifiable`, counted).
* The desk's `desk_book` (its own pending proposals) is absent, so packets are independent decisions.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import sys
import tempfile
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "ci", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_desk_records as cdr  # noqa: E402  (the proposal guard)
import desk_scan_packet as dsp  # noqa: E402  (the scan builder, masking, cost_policy, ATR)
from src.runtime import execution_costs as xc  # noqa: E402

# ----------------------------------------------------------------------------- registered numbers
# Registered in research/queue/RQ-20261026-*-0{1,2,3,4}.yaml on 2026-10-26, before any run. Not tunable.
REGISTERED_SYMBOLS = ("ADAUSDT", "AVAXUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SCAN_TF = "1h"
SEC = dsp.TF_SECONDS[SCAN_TF]
HORIZONS = (4, 12, 48)
LOOKBACK = 3000
WINDOW_START = datetime(2025, 11, 1, tzinfo=timezone.utc)      # inside every covering leg's evidence window
WINDOW_END = datetime(2026, 9, 15, tzinfo=timezone.utc)         # leaves >= 5 days of forward path
N_FOLDS = 4
MIN_GAP_H = 4                                                   # between two sampled cutoffs
SCHEDULE_LEN = 1500
MAX_PER_PACKET = 2
MIN_RISK_ATR = 0.1
B_R_DRAWS = 200
BOOT_DRAWS = 10_000
SEED = 20261026
N_MIN_ALL = 200                                                 # design 8.1: +0.20 R needs ~200 filled proposals
N_MIN_NEW = 100
N_POWERED_01R = 785                                             # (2.8 x 1.0 / 0.10)^2, the design's +0.10 R figure
FOLDS_NEEDED = 3                                                # of 4 (>= 2/3)
FOLD_MIN_N = 20
BATCH = 200                                                     # packets judged per batch (the stopping rule's grain)
STOP_PROPOSALS = 800                                            # stop at a batch boundary once this many VALID proposals exist (counted before any replay)
POST_CUTOFF_MIN_N = 20
NEAR_BARS = 1                                                   # a strategy entry within 1 bar of ITS timeframe
COST_TOL_R = 1e-3
CANDLE_SINCE = datetime(2025, 5, 1, tzinfo=timezone.utc)        # lookback behind the first cutoff
ENTRY_TYPES = ("market", "limit", "stop")

# Reference geometries for the unit-02 random-entry null (side, SL ATR, TP in R, horizon bars). Market entries.
REFERENCE_GEOMETRIES = (
    ("G1", 1.0, 1.5, 12), ("G2", 1.5, 2.0, 24), ("G3", 2.0, 2.0, 48),
    ("G4", 1.0, 3.0, 48), ("G5", 1.5, 1.0, 12), ("G6", 2.0, 3.0, 96),
)
BASELINE_DRAWS_PER_CELL = 500                                   # per symbol x side x geometry
BASELINE_N_FLOOR = 2000                                         # filled trades per geometry

Bar = Dict[str, float]


# ----------------------------------------------------------------------------- market data
@dataclass
class Series:
    """One symbol's closed 1h bars as arrays. ATR[t] depends on bars <= t only, so one pass over the whole
    series equals the as-of ATR at every cutoff (verified by the no-lookahead test)."""
    symbol: str
    t: np.ndarray            # bar OPEN epoch seconds
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    atr: np.ndarray
    fee_bps: float
    slip_bps: float
    fund_bps: float

    @classmethod
    def from_bars(cls, symbol: str, bars: Sequence[Bar]) -> "Series":
        bars = sorted(bars, key=lambda b: b["time"])
        a = dsp.atr_series(bars)
        fee, slip, fund = dsp.cost_policy(symbol)
        return cls(symbol, np.array([b["time"] for b in bars], dtype=np.int64),
                   np.array([b["open"] for b in bars]), np.array([b["high"] for b in bars]),
                   np.array([b["low"] for b in bars]), np.array([b["close"] for b in bars]),
                   np.array([np.nan if x is None else x for x in a]), fee, slip, fund)

    def last_closed(self, cutoff_epoch: int) -> int:
        """Index of the last bar whose close time (open + 1h) is <= the cutoff; -1 if none."""
        return int(np.searchsorted(self.t + SEC, cutoff_epoch, side="right")) - 1

    def bars(self, lo: int, hi: int) -> List[Bar]:
        return [{"time": int(self.t[i]), "open": float(self.o[i]), "high": float(self.h[i]),
                 "low": float(self.l[i]), "close": float(self.c[i])} for i in range(max(lo, 0), hi + 1)]


def load_market(candles_dir: Path, symbols: Sequence[str]) -> Tuple[Dict[str, Series], List[str]]:
    """({symbol: Series}, [symbols that could not be read]) -- a missing file is named, never an empty series."""
    got = dsp.candles_from_dir(candles_dir, symbols, SCAN_TF)
    out, missing = {}, []
    for s in symbols:
        if got.get(s):
            out[s] = Series.from_bars(s, got[s])
        else:
            missing.append(s)
    return out, missing


def fetch_market(candles_dir: Path, symbols: Sequence[str]) -> None:
    from scripts.research import desk_replay_driver as d7   # the one Binance Vision route
    days = int((datetime.now(timezone.utc) - CANDLE_SINCE).days) + 2
    for s in symbols:
        d7.fetch_candles(s, SCAN_TF, days, candles_dir / f"{s}_{SCAN_TF}.csv")


def parse_universe() -> Tuple[List[dict], List[str]]:
    """The crypto USDT perps of the pull-list UNION, RE-PARSED from config; and the note on the registered six."""
    acc, strat = dsp._load_cfg()
    uni = [u for u in dsp.pulled_universe(acc, strat) if xc.is_perp(u["symbol"]) and u["symbol"].endswith("USDT")]
    parsed = sorted(u["symbol"] for u in uni)
    note = [] if parsed == sorted(REGISTERED_SYMBOLS) else [f"DIFFERS from the registered {list(REGISTERED_SYMBOLS)}: {parsed}"]
    return uni, note


# ----------------------------------------------------------------------------- schedule and folds
def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def make_schedule(start: datetime = WINDOW_START, end: datetime = WINDOW_END, n: int = SCHEDULE_LEN,
                  seed: int = SEED, min_gap_h: int = MIN_GAP_H) -> List[int]:
    """Cutoff epochs, in ACCEPTANCE order: hourly closes shuffled by `seed`, kept when >= min_gap_h from every
    kept one. Greedy in a fixed order, so the first k of a length-n schedule ARE the length-k schedule (a
    stopping rule on filled count cannot depend on any outcome)."""
    s0, e0 = _epoch(start), _epoch(end)
    cands = np.arange(s0, e0, SEC, dtype=np.int64)
    order = np.random.default_rng(seed).permutation(len(cands))
    kept: List[int] = []
    srt: List[int] = []
    gap = min_gap_h * SEC
    for ix in order:
        c = int(cands[ix])
        j = bisect.bisect_left(srt, c)
        if (j > 0 and c - srt[j - 1] < gap) or (j < len(srt) and srt[j] - c < gap):
            continue
        srt.insert(j, c)
        kept.append(c)
        if len(kept) >= n:
            break
    return kept


def fold_of(cutoff_epoch: int, start: datetime = WINDOW_START, end: datetime = WINDOW_END) -> int:
    s0, e0 = _epoch(start), _epoch(end)
    return int(min(N_FOLDS, max(1, 1 + math.floor((cutoff_epoch - s0) / (e0 - s0) * N_FOLDS))))


def iso_week(epoch: int) -> str:
    y, w, _ = datetime.fromtimestamp(epoch, tz=timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


# ----------------------------------------------------------------------------- the replay engine
@dataclass
class Trade:
    state: str                       # filled | unfilled | refused | unresolved
    reason: str = ""                 # tp | sl | timeout | gap_sl | gap_tp | expired | risk | tp_passed | data_end
    side: float = 0.0
    fill_px: float = float("nan")
    exit_px: float = float("nan")
    fill_i: int = -1
    exit_i: int = -1
    risk: float = float("nan")
    gross_r: float = float("nan")
    cost_r: float = float("nan")
    net_r: float = float("nan")
    days: float = float("nan")


def simulate(s: Series, i: int, side: float, etype: str, level: float, stop: float, tp: float,
             good_till: int, horizon: int) -> Trade:
    """Replay ONE bracket decided at the close of bar `i` on the bars AFTER it. Reads only s[i+1:]; the ATR at
    bar i (a past value) is the only earlier input, for the refusal floor. See the module docstring."""
    n = len(s.t)
    atr_c = float(s.atr[i]) if 0 <= i < n and np.isfinite(s.atr[i]) else float("nan")
    k = i + 1
    fill, fi = float("nan"), -1
    if etype == "market":
        if k >= n:
            return Trade("unresolved", "data_end", side)
        fill, fi = float(s.o[k]), k
    else:
        last = i + good_till
        if last >= n:
            return Trade("unresolved", "data_end", side)
        for kk in range(k, last + 1):
            if etype == "limit":
                hit = (s.l[kk] < level) if side > 0 else (s.h[kk] > level)
                px = min(level, s.o[kk]) if side > 0 else max(level, s.o[kk])
            else:   # stop entry: price must trade THROUGH the level in the trade's direction
                hit = (s.h[kk] > level) if side > 0 else (s.l[kk] < level)
                px = max(level, s.o[kk]) if side > 0 else min(level, s.o[kk])
            if hit:
                fill, fi = float(px), kk
                break
        if fi < 0:
            return Trade("unfilled", "expired", side)
    risk = side * (fill - stop)
    if not np.isfinite(atr_c) or risk < MIN_RISK_ATR * atr_c:
        return Trade("refused", "risk", side, fill_px=fill, fill_i=fi, risk=risk)
    if side * (tp - fill) <= 0:
        return Trade("refused", "tp_passed", side, fill_px=fill, fill_i=fi, risk=risk)
    end = fi + horizon - 1
    if end >= n:
        return Trade("unresolved", "data_end", side, fill_px=fill, fill_i=fi, risk=risk)
    exit_px, exit_i, reason = float("nan"), -1, ""
    for kk in range(fi, end + 1):
        sl_hit = (s.l[kk] <= stop) if side > 0 else (s.h[kk] >= stop)
        if sl_hit:
            gap = (s.o[kk] <= stop) if side > 0 else (s.o[kk] >= stop)
            exit_px = float(s.o[kk]) if gap and kk > fi else float(stop)
            exit_i, reason = kk, "gap_sl" if gap and kk > fi else "sl"
            break
        credit_tp = (etype == "market") or kk > fi          # a limit/stop fill bar credits no TP
        tp_hit = credit_tp and ((s.h[kk] >= tp) if side > 0 else (s.l[kk] <= tp))
        if tp_hit:
            gap = (s.o[kk] >= tp) if side > 0 else (s.o[kk] <= tp)
            exit_px = float(s.o[kk]) if gap and kk > fi else float(tp)
            exit_i, reason = kk, "gap_tp" if gap and kk > fi else "tp"
            break
    if exit_i < 0:
        exit_px, exit_i, reason = float(s.c[end]), end, "timeout"
    t_in = int(s.t[fi])
    t_out = int(s.t[exit_i]) + SEC
    cost = xc.roundtrip_cost_r(entry=fill, exit_price=exit_px, risk=risk,
                               entry_time=datetime.fromtimestamp(t_in, tz=timezone.utc).isoformat(),
                               exit_time=datetime.fromtimestamp(t_out, tz=timezone.utc).isoformat(),
                               fee_bps_roundtrip=s.fee_bps, slippage_bps_roundtrip=s.slip_bps,
                               funding_bps_per_window=s.fund_bps)
    if not cost["total_cost_r"] > 0:
        # roundtrip_cost_r returns ZEROS for an un-derivable input: never let that read as a free trade.
        raise AssertionError(f"zero cost on a filled trade ({s.symbol} entry {fill} exit {exit_px} risk {risk})")
    gross = side * (exit_px - fill) / risk
    return Trade("filled", reason, side, fill, exit_px, fi, exit_i, risk, gross, cost["total_cost_r"],
                 gross - cost["total_cost_r"], (t_out - t_in) / 86400.0)


# ----------------------------------------------------------------------------- packets
def build_masked_packet(mkt: Dict[str, Series], classes: Dict[str, List[str]], cutoff_epoch: int, k: int,
                        seed: int = SEED, mode: str = "A", raw: Any = None) -> Tuple[dict, dict]:
    """(masked packet, key). Aliases are re-drawn per packet (seeded), so ASSET_01 is not one symbol forever.
    `mode` (DESK-PACKET-REDESIGN): "A" = today's packet (default, unchanged); "B" = base-rate rows removed; "C" = raw
    bars (needs `raw`, a desk_packet_modes.RawStore). B and C keep A's packet_id, aliases and rebasing, so the same key
    scores them; they are not the live desk schema and skip its validator."""
    cutoff = datetime.fromtimestamp(cutoff_epoch, tz=timezone.utc)
    order = np.random.default_rng(seed + 1000 + k).permutation(len(mkt))
    syms = [sorted(mkt)[j] for j in order]
    uni = [{"symbol": s, "venue": "bybit", "classes": classes.get(s, ["paper"])} for s in syms]
    candles: Dict[str, Optional[List[Bar]]] = {}
    for s in syms:
        i = mkt[s].last_closed(cutoff_epoch)
        # trimming to the builder's own look-back is exact: base_rates() trims to the same tail
        candles[s] = mkt[s].bars(i - (LOOKBACK + max(HORIZONS) + dsp.ATR_PERIOD + 5), i) if i >= 0 else None
    p = dsp.build_scan_packet(cutoff=cutoff, tf=SCAN_TF, universe=uni, candles=candles, horizons=HORIZONS,
                              lookback=LOOKBACK, system_book=None, desk_book=None, built_at=cutoff,
                              unread_why={"system_book": "not reconstructed point in time (historical mode)",
                                          "desk_book": "not reconstructed point in time (historical mode)"})
    m, key = dsp.mask_packet(p)
    bad = dsp.validate(m)
    if bad:
        raise AssertionError(f"masked packet fails desk-records-guard: {bad[:3]}")
    key.update(index=k, cutoff_epoch=cutoff_epoch, fold=fold_of(cutoff_epoch))
    if mode != "A":
        from scripts.research import desk_packet_modes as pm   # noqa: E402 - optional builder modes
        m = pm.apply(mode, m, key, raw)
    return m, key


PRICE_FIELDS = ("last_close", "atr", "high", "low")


def leak_scan(packet_text: str, key: dict, symbols: Sequence[str]) -> List[str]:
    """Findings for one serialised masked packet against its own key. [] = no leak found."""
    out: List[str] = []
    low = packet_text.lower()
    for s in symbols:
        for tok in {s.lower(), re.sub(r"usdt$", "", s.lower())}:
            if len(tok) >= 3 and re.search(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", low):
                out.append(f"symbol token {tok!r}")
    cut = datetime.fromtimestamp(key["cutoff_epoch"], tz=timezone.utc)
    for tok in (cut.strftime("%Y-%m-%d"), cut.strftime("%Y%m%d"), cut.strftime("%Y-%m-%dT%H")):
        if tok in packet_text:
            out.append(f"real cutoff date {tok!r}")
    for m in re.finditer(r'"(?:19|20)\d{2}-\d{2}-\d{2}', packet_text):
        if not m.group(0).startswith('"2000-'):
            out.append(f"date string {m.group(0)!r}")
    for m in re.finditer(r"(?<![\w.])(1[5-9]\d{8})(?![\w.])", packet_text):
        out.append(f"epoch-seconds number {m.group(1)}")
    obj = json.loads(packet_text)
    real_last = {a: 100.0 / sc for a, sc in key["price_scale"].items() if sc}
    for u in obj.get("universe", []):
        r = real_last.get(u["symbol"])
        if r and u.get("last_close") not in (None, 100.0) and abs(float(u["last_close"]) - r) <= 0.005 * r:
            out.append(f"{u['symbol']} last_close equals the real price")
    return sorted(set(out))


# ----------------------------------------------------------------------------- statistics
def _week_arrays(rows: List[dict], fields: Sequence[str]) -> Dict[str, np.ndarray]:
    weeks = sorted({r["week"] for r in rows})
    ix = {w: j for j, w in enumerate(weeks)}
    out = {f: np.zeros(len(weeks)) for f in fields}
    out["_n"] = np.zeros(len(weeks))
    for r in rows:
        j = ix[r["week"]]
        out["_n"][j] += 1
        for f in fields:
            v = r.get(f)
            if v is not None and np.isfinite(v):
                out[f][j] += v
    return out


def _ci(draws: np.ndarray) -> Tuple[float, float]:
    d = draws[np.isfinite(draws)]
    return (float("nan"), float("nan")) if not len(d) else (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)))


def cluster_stats(rows: List[dict], seed: int = SEED, draws: int = BOOT_DRAWS) -> Dict[str, Any]:
    """rows: dicts with week, net_r, days, diff (paired vs B-R; may be None). Week-cluster bootstrap."""
    if not rows:
        return {"n": 0, "weeks": 0}
    flat = [dict(r, has_diff=0.0 if r.get("diff") is None else 1.0) for r in rows]
    a = _week_arrays(flat, ("net_r", "days", "diff", "has_diff"))
    w = len(a["_n"])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, w, size=(draws, w))
    n_b = a["_n"][idx].sum(axis=1)
    mean_b = a["net_r"][idx].sum(axis=1) / n_b
    cap_b = a["net_r"][idx].sum(axis=1) / np.where(a["days"][idx].sum(axis=1) > 0, a["days"][idx].sum(axis=1), np.nan)
    nd_b = a["has_diff"][idx].sum(axis=1)
    diff_b = np.where(nd_b > 0, a["diff"][idx].sum(axis=1) / np.where(nd_b > 0, nd_b, 1), np.nan)
    n = int(a["_n"].sum())
    nd = float(a["has_diff"].sum())
    xs = np.array([r["net_r"] for r in rows])
    out = {"n": n, "weeks": w, "mean_net_r": float(xs.mean()), "sd_net_r": float(xs.std(ddof=1)) if n > 1 else float("nan"),
           "mean_ci95": list(_ci(mean_b)),
           "net_r_per_capital_day": float(a["net_r"].sum() / a["days"].sum()) if a["days"].sum() > 0 else float("nan"),
           "per_capital_day_ci95": list(_ci(cap_b)),
           "capital_days": float(a["days"].sum()), "n_paired": int(nd)}
    if nd > 0:
        out["paired_diff_vs_random"] = float(a["diff"].sum() / nd)
        out["paired_diff_ci95"] = list(_ci(diff_b))
    return out


def required_n(sd: float, effect: float) -> Optional[int]:
    return None if not sd or not np.isfinite(sd) or effect <= 0 else int(math.ceil((2.8 * sd / effect) ** 2))


# ----------------------------------------------------------------------------- baselines
def geometry_of(s: Series, i: int, side: float, etype: str, level: float, stop: float, tp: float,
                good_till: int, horizon: int) -> Optional[dict]:
    """A proposal's bracket in ATR units at its own cutoff (None when the ATR there is undefined)."""
    a = float(s.atr[i])
    if not np.isfinite(a) or a <= 0:
        return None
    ref = float(s.c[i])
    return {"side": side, "etype": etype, "offset_atr": side * (ref - level) / a,
            "sl_atr": side * (level - stop) / a, "tp_atr": side * (tp - level) / a,
            "good_till": good_till, "horizon": horizon}


def transplant(s: Series, i: int, g: dict) -> Optional[Trade]:
    """The geometry `g` applied at cutoff bar `i` of series `s` (ATR and last close at i; nothing later)."""
    a = float(s.atr[i]) if 0 <= i < len(s.atr) else float("nan")
    if not np.isfinite(a) or a <= 0:
        return None
    side = g["side"]
    level = float(s.c[i]) - side * g["offset_atr"] * a
    return simulate(s, i, side, g["etype"], level, level - side * g["sl_atr"] * a, level + side * g["tp_atr"] * a,
                    g["good_till"], g["horizon"])


def eligible_cutoffs(s: Series, start: datetime, end: datetime, fold: Optional[int] = None) -> np.ndarray:
    """Indices i of bars whose close lies in the window (and the fold), with an ATR and forward room."""
    close = s.t + SEC
    m = (close >= _epoch(start)) & (close < _epoch(end)) & np.isfinite(s.atr)
    m &= np.arange(len(s.t)) < len(s.t) - 2
    ix = np.nonzero(m)[0]
    if fold is not None:
        ix = np.array([j for j in ix if fold_of(int(close[j])) == fold], dtype=int)
    return ix


def random_baseline(s: Series, g: dict, pool: np.ndarray, rng: np.random.Generator, draws: int) -> Dict[str, Any]:
    nets, grosses, refused, unfilled = [], [], 0, 0
    if not len(pool):
        return {"mean": None, "gross_mean": None, "n": 0, "refused": 0, "unfilled": 0, "draws": 0}
    for j in rng.choice(pool, size=draws, replace=True):
        t = transplant(s, int(j), g)
        if t is None or t.state == "unresolved":
            continue
        if t.state == "filled":
            nets.append(t.net_r)
            grosses.append(t.gross_r)
        elif t.state == "refused":
            refused += 1
        else:
            unfilled += 1
    return {"mean": float(np.mean(nets)) if nets else None, "gross_mean": float(np.mean(grosses)) if grosses else None,
            "n": len(nets), "refused": refused, "unfilled": unfilled, "draws": draws}


def atr_pct_of(s: Series) -> np.ndarray:
    """ATR% = ATR / close at each bar (as-of, bars <= t only). The volatility state the matched baseline conditions on."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return s.atr / s.c


def vol_matched_pool(s: Series, pool: np.ndarray, i: int, n_dec: int = 10,
                     window: Optional[Tuple[datetime, datetime]] = None) -> np.ndarray:
    """The members of `pool` (the symbol's cutoffs of ONE fold) in the same ATR%-decile as bar `i`. Deciles are the
    symbol's own, cut over the whole registered window (all folds), so a fold's pool is never re-binned by its own
    contents (`window` overrides the registered window for a re-windowed program). Empty when bar i has no ATR%. Never crosses symbols (a Series is one symbol) or folds (pool is one fold)."""
    ap = atr_pct_of(s)
    if not np.isfinite(ap[i]):
        return pool[:0]
    allc = eligible_cutoffs(s, *(window or (WINDOW_START, WINDOW_END)))
    edges = np.quantile(ap[allc], np.linspace(0, 1, n_dec + 1)[1:-1])
    dec = np.searchsorted(edges, ap[pool])
    return pool[dec == int(np.searchsorted(edges, ap[i]))]


# ----------------------------------------------------------------------------- strategy-own lists and novelty
@dataclass
class LegList:
    leg: str
    symbol: str
    tf_sec: int
    start: int
    end: int
    trades: List[dict]
    cost_stack: Dict[str, Any] = field(default_factory=dict)
    ent: List[int] = field(default_factory=list)       # entry epochs, aligned with `trades`
    ext: List[int] = field(default_factory=list)       # exit epochs


# The arm under test is not part of "the strategies' book" it is compared with: it has no Stage-0 list (it is a
# proposal-queue leg, not a candle strategy), and left in it makes every non-duplicate cell `unclassifiable`.
DESK_OWN_LEGS = frozenset({"claude_desk"})


def rostered_legs(symbols: Iterable[str]) -> Dict[str, set]:
    """{symbol: {strategy names on ANY account roster whose strategies.yaml entry trades that symbol and is not
    `enabled: false`}}: the system's book, by config (RULE ONE: the roster is read, not assumed). A shadow leg
    stays in (it builds and logs packages); a disabled one produces none."""
    acc, strat = dsp._load_cfg()
    names = {s for a in acc.values() if isinstance(a, dict) and a.get("configured") is not False for s in (a.get("strategies") or [])}
    names -= DESK_OWN_LEGS
    out: Dict[str, set] = {s: set() for s in symbols}
    for n in names:
        cfg = strat.get(n) or {}
        if cfg.get("enabled") is False:
            continue
        for sym in (cfg.get("symbols") or ([cfg["symbol"]] if cfg.get("symbol") else [])):
            if sym in out:
                out[sym].add(n)
    return out


def load_strategy_lists(rostered: Dict[str, set], repo: Path = REPO) -> Tuple[List[LegList], List[str]]:
    """The committed Stage-0 trade list of every ROSTERED leg on the replay symbols. (lists, named gaps): a
    rostered leg with no readable list is a gap, never an absent leg."""
    from scripts.research import live_review_outcomes as lro
    out: List[LegList] = []
    gaps: List[str] = []
    want = {n: sym for sym, names in rostered.items() for n in names}
    for name, sym in sorted(want.items()):
        f = repo / "comms" / "strategy_evidence" / f"{name}.json"
        if not f.exists():
            gaps.append(f"{name} ({sym}): rostered, no committed evidence record")
            continue
        try:
            rec = json.loads(f.read_text())
        except ValueError:
            gaps.append(f"{name} ({sym}): evidence record unreadable")
            continue
        fd = rec.get("fold_detail") or []
        tf = rec.get("timeframe")
        if not fd or tf not in dsp.TF_SECONDS:
            gaps.append(f"{name} ({sym}): no fold_detail / timeframe")
            continue
        try:
            trades, _ = lro.load_trades(name, repo)
        except Exception as exc:  # allow-silent: named in the verdict as a gap, never an empty leg
            gaps.append(f"{name} ({sym}): trade list unreadable ({type(exc).__name__})")
            continue
        if not trades:
            gaps.append(f"{name} ({sym}): empty trade list")
            continue
        short = [k for k in ("entry_time", "exit_time", "direction", "net_r") if not all(k in t for t in trades)]
        if short:
            gaps.append(f"{name} ({sym}): trade rows lack {short}")
            continue
        ts = [datetime.fromisoformat(str(x).replace("Z", "+00:00")) for x in (fd[0]["start"], fd[-1]["end"])]
        ts = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in ts]
        out.append(LegList(name, sym, dsp.TF_SECONDS[tf], _epoch(ts[0]), _epoch(ts[1]), trades,
                           rec.get("cost_stack") or {}, [_t(t["entry_time"]) for t in trades],
                           [_t(t["exit_time"]) for t in trades]))
    return out, gaps


def _t(x: Any) -> int:
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return _epoch(d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def classify_novelty(symbol: str, side: float, cutoff_epoch: int, legs: List[LegList],
                     rostered: Dict[str, set]) -> str:
    """Scorer-assigned (design 2.4's enum, plus the two states a scorer must be able to say):
    duplicates_system_package | duplicates_near_signal | new | new_no_leg | unclassifiable.
    `new` is claimed only when EVERY rostered leg on the symbol was looked at for this cutoff (a list, and an
    evidence window that covers it): a negative needs a denominator."""
    names = rostered.get(symbol) or set()
    if not names:
        return "new_no_leg"
    have = [lg for lg in legs if lg.symbol == symbol and lg.leg in names]
    cover = [lg for lg in have if lg.start <= cutoff_epoch <= lg.end]
    unseen = (len(names) - len({lg.leg for lg in have})) + (len(have) - len(cover))
    want = "long" if side > 0 else "short"
    near = False
    for lg in cover:
        for t, e, x in zip(lg.trades, lg.ent, lg.ext):
            if t.get("direction") != want:
                continue
            if e <= cutoff_epoch < x:
                return "duplicates_system_package"
            if cutoff_epoch < e <= cutoff_epoch + NEAR_BARS * lg.tf_sec:
                near = True
    if near:
        return "duplicates_near_signal"
    return "unclassifiable" if unseen else "new"


def strategy_own_table(legs: List[LegList], start: datetime, end: datetime) -> Dict[str, Any]:
    s0, e0 = _epoch(start), _epoch(end)
    rows, per_leg = [], []
    for lg in legs:
        sel = [t for t, e in zip(lg.trades, lg.ent) if s0 <= e < e0]
        per_leg.append({"leg": lg.leg, "symbol": lg.symbol, "n": len(sel),
                        "mean_net_r": float(np.mean([t["net_r"] for t in sel])) if sel else None})
        for t in sel:
            e, x = _t(t["entry_time"]), _t(t["exit_time"])
            rows.append({"week": iso_week(e), "net_r": float(t["net_r"]), "days": max((x - e) / 86400.0, 1e-9), "diff": None})
    st = cluster_stats(rows) if rows else {"n": 0}
    return {"pooled": st, "per_leg": per_leg}


# ----------------------------------------------------------------------------- proposals intake
def _proposal_row_problems(row: dict, packet: dict) -> List[str]:
    pr = row.get("proposal")
    if not isinstance(pr, dict):
        return ["propose_entry without a proposal object"]
    need = ("symbol", "side", "timeframe", "horizon_bars", "entry", "stop", "tp", "expected_r_net", "novelty", "onboarding")
    miss = [k for k in need if k not in pr]
    if miss:
        return [f"proposal missing {miss}"]
    if pr["side"] not in ("long", "short"):
        return [f"side {pr['side']!r}"]
    e = pr["entry"]
    if not isinstance(e, dict) or e.get("type") not in ENTRY_TYPES or not isinstance(e.get("level"), (int, float)) \
            or not isinstance(e.get("good_till_bars"), int) or e["good_till_bars"] < 1:
        return ["entry needs {type in market|limit|stop, level, good_till_bars >= 1}"]
    if not isinstance(pr["horizon_bars"], int) or not 1 <= pr["horizon_bars"] <= 200:
        return ["horizon_bars must be an int in [1, 200]"]
    if pr["timeframe"] != SCAN_TF:
        return [f"timeframe must be {SCAN_TF!r} in this replay"]
    for k in ("stop", "tp"):
        if not isinstance(pr[k], dict) or not isinstance(pr[k].get("level"), (int, float)):
            return [f"{k}.level must be a number"]
    if not isinstance(pr["tp"].get("p_hit"), (int, float)) or not isinstance(pr["expected_r_net"], (int, float)):
        return ["tp.p_hit and expected_r_net must be numbers"]
    enums = json.loads(cdr.DECISION_SCHEMA.read_text())["enums"]          # the schema's own closed enums
    for blk, enum in (("stop", "stop_basis"), ("tp", "tp_basis")):
        if pr[blk].get("basis") not in enums[enum]:
            return [f"{blk}.basis {pr[blk].get('basis')!r} is not in the closed enum {enums[enum]}"]
    if pr["novelty"] != "unverifiable":
        return ["novelty must be `unverifiable` in this replay (the system book is not visible; the scorer assigns novelty)"]
    return cdr.proposal_problems({"proposal": pr, "judge_prior": row.get("judge_prior")}, packet)


def read_proposals(path: Path, packets: Dict[str, dict]) -> Tuple[Dict[str, List[dict]], Dict[str, Any]]:
    """{packet_id: [valid propose_entry rows]} and the intake accounting. Unknown packet ids raise (a typo
    must not read as a no_trade); a refused proposal is counted with its reasons and scored as no_trade."""
    by: Dict[str, List[dict]] = {}
    acc = {"rows": 0, "no_trade": 0, "propose_entry": 0, "refused": 0, "refused_reasons": {}, "over_cap": 0,
           "duplicate_symbol": 0, "packets_with_rows": 0}
    seen_nt: set = set()
    for ln, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        pid = row.get("packet_id")
        if pid not in packets:
            raise ValueError(f"{path}:{ln}: packet_id {pid!r} is not in the packets file")
        acc["rows"] += 1
        a = row.get("action")
        if a == "no_trade":
            acc["no_trade"] += 1
            seen_nt.add(pid)
            by.setdefault(pid, [])
            continue
        if a != "propose_entry":
            raise ValueError(f"{path}:{ln}: action {a!r} is not no_trade|propose_entry")
        acc["propose_entry"] += 1
        probs = _proposal_row_problems(row, packets[pid])
        if probs:
            acc["refused"] += 1
            key = probs[0][:80]
            acc["refused_reasons"][key] = acc["refused_reasons"].get(key, 0) + 1
            by.setdefault(pid, [])
            continue
        lst = by.setdefault(pid, [])
        if any(r["proposal"]["symbol"] == row["proposal"]["symbol"] for r in lst):
            acc["duplicate_symbol"] += 1
            continue
        if len(lst) >= MAX_PER_PACKET:
            acc["over_cap"] += 1
            continue
        lst.append(row)
    acc["packets_with_rows"] = len(by)
    return by, acc


# ----------------------------------------------------------------------------- the registered rule
def grade_arm(st: Dict[str, Any], *, n_min: int, selfcheck: Optional[bool], label: str) -> Tuple[str, List[str]]:
    """The rule registered in units 03 / 04; this only decides from numbers already computed."""
    n = st["n"]
    if selfcheck is not True:
        return "indeterminate", ["the unit-01 harness self-check verdict was not supplied or is not a pass"]
    if n < n_min:
        return "indeterminate", [f"{label}: n_filled {n} < {n_min}"]
    lo, hi = st["mean_ci95"]
    if st["mean_net_r"] <= 0 or hi < 0:
        return "fail", [f"{label}: mean net R {st['mean_net_r']:+.4f} <= 0 or CI upper {hi:+.4f} < 0"]
    d_hi = st.get("paired_diff_ci95", [float("nan")] * 2)[1]
    if st.get("paired_diff_vs_random") is not None and d_hi < 0:
        return "fail", [f"{label}: worse than the random-entry baseline (paired diff CI upper {d_hi:+.4f} < 0)"]
    cd_lo = st["per_capital_day_ci95"][0]
    checks = [
        (lo > 0, "mean net R CI lower bound > 0"),
        (st["net_r_per_capital_day"] > 0 and cd_lo > 0, "net R per capital-day > 0 with the CI lower bound > 0"),
        (st.get("paired_diff_vs_random") is not None and st["paired_diff_vs_random"] > 0
         and st["paired_diff_ci95"][0] > 0, "beats random-entry timing with the paired CI excluding 0"),
        (st["folds_positive"] >= FOLDS_NEEDED, f"net R > 0 in >= {FOLDS_NEEDED} of {N_FOLDS} folds (each with n >= {FOLD_MIN_N})"),
    ]
    post = st["post_cutoff"]
    if post["state"] == "could_not_look":
        return "indeterminate", ["post-cutoff stratum could not be formed (no --model-cutoff)"]
    if post["n"] >= POST_CUTOFF_MIN_N:
        checks.append((post["mean"] is not None and post["mean"] > 0, "post-cutoff stratum point estimate > 0"))
    failed = [m for ok, m in checks if not ok]
    if failed:
        return "indeterminate", [f"{label}: not met: " + "; ".join(failed)]
    why = []
    if post["n"] < POST_CUTOFF_MIN_N:
        why.append("masked-replay only, post-cutoff n < 20: forward-shadow confirmation required")
    why.append("forward-shadow set (DESK-6) not yet available: PASS is masked-replay only")
    if n < N_POWERED_01R:
        why.append(f"n {n} < {N_POWERED_01R}: powered for the observed-sd MDE, not for +0.10 R")
    return "pass", why


def stopping_design(judged_idx: List[int], key_idx: Iterable[int], valid_index: List[int]) -> Dict[str, Any]:
    """The registered stopping rule's accounting. The schedule is the mask key's index set, NOT range(n): a packet
    withheld at build time (mask leak) has no key and was never offered to a judge, so its hole is not a skipped
    packet. Judged packets are a PREFIX when they are exactly the keyed indices up to the last judged one."""
    idx = sorted(judged_idx)
    keyed = sorted(set(int(k) for k in key_idx))
    prefix_ok = bool(idx) and idx == [k for k in keyed if k <= idx[-1]]
    last_start = ((idx[-1]) // BATCH) * BATCH if idx else 0
    n_before_last = sum(1 for j in valid_index if j < last_start)
    return {"packets_judged": len(idx), "is_schedule_prefix": prefix_ok, "batch": BATCH, "stop_proposals": STOP_PROPOSALS,
            "valid_proposals_before_last_batch": n_before_last, "valid_proposals_total": len(valid_index),
            "schedule_exhausted": bool(idx) and idx[-1] >= SCHEDULE_LEN - 1,
            "stopping_rule_respected": bool(prefix_ok and (n_before_last < STOP_PROPOSALS))}


def score(mkt: Dict[str, Series], keys: Dict[str, dict], by: Dict[str, List[dict]],
          legs: List[LegList], rostered: Dict[str, set], *, subset: str, cutoff: Optional[datetime],
          selfcheck: Optional[bool], seed: int = SEED, draws: int = B_R_DRAWS) -> Dict[str, Any]:
    rng = np.random.default_rng(seed + 7)
    rng_vm = np.random.default_rng(seed + 11)       # companions draw from their OWN stream: the registered S3 draws are unchanged
    recs: List[dict] = []
    counts = {"proposals_valid": 0, "filled": 0, "filled_in_subset": 0, "unfilled": 0, "refused": 0, "unresolved": 0,
              "novelty": {}, "excluded_by_subset": 0}
    pools: Dict[Tuple[str, int], np.ndarray] = {}
    valid_index: List[int] = []                      # packet index of EVERY valid proposal, whatever its fate
    for pid, rows in by.items():
        key = keys[pid]
        ce = key["cutoff_epoch"]
        for row in rows:
            pr = row["proposal"]
            alias = pr["symbol"]
            sym = key["alias"].get(alias)
            if sym is None or sym not in mkt:
                raise ValueError(f"{pid}: alias {alias!r} has no symbol in the mask key")
            sc = float(key["price_scale"][alias])
            s = mkt[sym]
            i = s.last_closed(ce)
            side = 1.0 if pr["side"] == "long" else -1.0
            lvl, stp, tpl = pr["entry"]["level"] / sc, pr["stop"]["level"] / sc, pr["tp"]["level"] / sc
            counts["proposals_valid"] += 1
            valid_index.append(int(key["index"]))
            nov = classify_novelty(sym, side, ce, legs, rostered)
            counts["novelty"][nov] = counts["novelty"].get(nov, 0) + 1
            t = simulate(s, i, side, pr["entry"]["type"], lvl, stp, tpl, pr["entry"]["good_till_bars"], pr["horizon_bars"])
            if t.state != "filled":
                counts[t.state] = counts.get(t.state, 0) + 1
                continue
            counts["filled"] += 1                                   # every fill, whatever its novelty
            if subset == "new" and nov not in ("new", "new_no_leg"):
                counts["excluded_by_subset"] += 1
                continue
            counts["filled_in_subset"] += 1
            g = geometry_of(s, i, side, pr["entry"]["type"], lvl, stp, tpl, pr["entry"]["good_till_bars"], pr["horizon_bars"])
            br = None
            if g is not None:
                pk = (sym, key["fold"])
                if pk not in pools:
                    pools[pk] = eligible_cutoffs(s, WINDOW_START, WINDOW_END, key["fold"])
                br = random_baseline(s, g, pools[pk], rng, draws)
                bm = random_baseline(s, g, vol_matched_pool(s, pools[pk], i), rng_vm, draws)
            else:
                bm = None
            diff = None if br is None or br["mean"] is None else t.net_r - br["mean"]
            diff_gross = None if br is None or br["gross_mean"] is None else t.gross_r - br["gross_mean"]
            diff_matched = None if bm is None or bm["mean"] is None else t.net_r - bm["mean"]
            recs.append({"packet_id": pid, "symbol": sym, "side": pr["side"], "week": iso_week(ce), "fold": key["fold"],
                         "net_r": t.net_r, "days": t.days, "diff": diff, "exit": t.reason, "novelty": nov,
                         "gross_r": t.gross_r, "diff_gross": diff_gross, "diff_matched": diff_matched,
                         "diff_gross_matched": None if bm is None or bm["gross_mean"] is None else t.gross_r - bm["gross_mean"],
                         "pre_cutoff": None if cutoff is None else bool(ce < _epoch(cutoff)),
                         "b_r_mean": None if br is None else br["mean"]})
    # the registered stopping rule: judged packets are a schedule PREFIX, taken in whole batches, and the run stopped
    # as soon as the count of VALID proposals (a count taken before any replay, so it cannot depend on a result)
    # reached STOP_PROPOSALS
    design = stopping_design([int(keys[pid]["index"]) for pid in by], [k["index"] for k in keys.values()], valid_index)
    st = cluster_stats(recs, seed)
    st["n"] = len(recs)
    st["companions"] = s3_companions(recs, seed)
    if recs:
        folds = {}
        for f in range(1, N_FOLDS + 1):
            m = [r["net_r"] for r in recs if r["fold"] == f]
            folds[str(f)] = {"n": len(m), "mean_net_r": float(np.mean(m)) if m else None}
        st["folds"] = folds
        st["folds_positive"] = sum(1 for v in folds.values() if v["n"] >= FOLD_MIN_N and v["mean_net_r"] and v["mean_net_r"] > 0)
        if cutoff is None:
            st["post_cutoff"] = {"state": "could_not_look", "n": 0, "mean": None}
        else:
            m = [r["net_r"] for r in recs if r["pre_cutoff"] is False]
            st["post_cutoff"] = {"state": "measured", "n": len(m), "mean": float(np.mean(m)) if m else None}
        st["by_exit"] = {k: sum(1 for r in recs if r["exit"] == k) for k in sorted({r["exit"] for r in recs})}
        st["by_symbol"] = {k: {"n": sum(1 for r in recs if r["symbol"] == k),
                               "mean_net_r": float(np.mean([r["net_r"] for r in recs if r["symbol"] == k]))}
                           for k in sorted({r["symbol"] for r in recs})}
        st["by_side"] = {k: sum(1 for r in recs if r["side"] == k) for k in ("long", "short")}
        st["b_r_mean_net_r"] = float(np.mean([r["b_r_mean"] for r in recs if r["b_r_mean"] is not None])) \
            if any(r["b_r_mean"] is not None for r in recs) else None
    else:
        st["post_cutoff"] = {"state": "could_not_look" if cutoff is None else "measured", "n": 0, "mean": None}
        st["folds_positive"] = 0
    n_min = N_MIN_NEW if subset == "new" else N_MIN_ALL
    verdict, why = grade_arm(st, n_min=n_min, selfcheck=selfcheck, label=f"subset={subset}") if recs else \
        ("indeterminate", ["no filled proposals"])
    if not design["stopping_rule_respected"]:
        verdict, why = "indeterminate", ["the judged packets break the registered stopping rule (not a schedule prefix, or judging continued "
                                         f"past {STOP_PROPOSALS} valid proposals): {json.dumps(design)}"] + why
    st["n_to_resolve"] = {f"{e:+.2f}R": required_n(st.get("sd_net_r", float("nan")), e) for e in (0.10, 0.20)}
    return {"verdict": verdict, "reasons": why, "subset": subset, "stats": st, "counts": counts, "design": design,
            "fill_rate": (counts["filled"] / counts["proposals_valid"]) if counts["proposals_valid"] else None}


def s3_companions(recs: List[dict], seed: int = SEED) -> Dict[str, Any]:
    """DESK-S3-VOL-MATCHED-BASELINE. COMPANIONS beside the registered S3 (stats["paired_diff_vs_random"]); no decision rule
    reads them. Each is the weekly-cluster mean of a paired difference over the filled proposals that have it (n stated):
      S3                    net R minus the whole-fold random entries' net R (the registered statistic, repeated for the table)
      gross_excess          GROSS R (before cost) minus the same random entries' gross R
      S3_matched            net R minus random entries from the SAME symbol, fold and ATR%-decile as the proposal
      gross_excess_matched  gross R minus those matched entries' gross R
    A selector that only finds cheap-cost-in-R (high-ATR%) moments has a large S3 and ~0 on the other three."""
    out: Dict[str, Any] = {}
    for name, key in (("S3", "diff"), ("gross_excess", "diff_gross"), ("S3_matched", "diff_matched"),
                      ("gross_excess_matched", "diff_gross_matched")):
        rows = [dict(r, diff=r[key]) for r in recs if r.get(key) is not None]
        st = cluster_stats(rows, seed) if rows else {}
        out[name] = {"n": len(rows), "mean": st.get("paired_diff_vs_random"), "ci95": st.get("paired_diff_ci95")}
    return out


# ----------------------------------------------------------------------------- self-check (unit 01)
def _same_outcome(a: Trade, b: Trade) -> bool:
    return a.state == b.state and a.reason == b.reason and (
        (a.state != "filled") or bool(np.isclose(a.net_r, b.net_r, rtol=0, atol=1e-12)))


def _policy_oracle(mkt: Dict[str, Series], cutoffs: List[int], geom: Tuple[float, float, int], pick: str,
                   rng: np.random.Generator) -> List[dict]:
    """A planted policy over (cutoff, symbol): `pick` = oracle (best side with hindsight) | anti | null (random side)."""
    sl_atr, tp_r, hor = geom
    rows = []
    syms = sorted(mkt)
    for c in cutoffs:
        s = mkt[syms[int(rng.integers(0, len(syms)))]]
        i = s.last_closed(c)
        if i < 0 or not np.isfinite(s.atr[i]):
            continue
        g = {"etype": "market", "offset_atr": 0.0, "sl_atr": sl_atr, "tp_atr": sl_atr * tp_r, "good_till": 1, "horizon": hor}
        res = {sd: transplant(s, i, dict(g, side=sd)) for sd in (1.0, -1.0)}
        if any(t is None or t.state != "filled" for t in res.values()):
            continue
        if pick == "oracle":
            sd = max(res, key=lambda k: res[k].net_r)
        elif pick == "anti":
            sd = min(res, key=lambda k: res[k].net_r)
        else:
            sd = 1.0 if rng.random() < 0.5 else -1.0
        t = res[sd]
        gg = dict(g, side=sd)
        pool = eligible_cutoffs(s, WINDOW_START, WINDOW_END, fold_of(c))
        br = random_baseline(s, gg, pool, rng, 100)
        rows.append({"week": iso_week(c), "net_r": t.net_r, "days": t.days,
                     "diff": None if br["mean"] is None else t.net_r - br["mean"]})
    return rows


def cost_fidelity(legs: List[LegList]) -> Dict[str, Any]:
    """Clause (c): the engine's cost function against the committed stack, trade by trade."""
    policy_now = {}
    per_leg, max_dev, n_cmp = [], 0.0, 0
    for lg in legs:
        cs = lg.cost_stack or {}
        fee, slip, fund = dsp.cost_policy(lg.symbol)
        policy_now = {"fees": fee, "slippage": slip, "funding": fund}
        same = all(abs(float(cs.get(k, -1)) - v) < 1e-9 for k, v in policy_now.items() if k in cs) and \
            all(k in cs for k in ("fees", "slippage", "funding"))
        if not same:
            per_leg.append({"leg": lg.leg, "state": "policy_differs_excluded", "record": cs and {k: cs.get(k) for k in ("fees", "slippage", "funding")}, "now": policy_now})
            continue
        dev, n = 0.0, 0
        for t in lg.trades:
            if not all(k in t for k in ("entry", "sl", "gross_r", "direction", "entry_time", "exit_time", "cost_fee_r", "cost_slippage_r", "cost_funding_r")):
                continue
            sd = 1.0 if t["direction"] == "long" else -1.0
            rd = abs(float(t["entry"]) - float(t["sl"]))
            px = float(t["entry"]) + sd * float(t["gross_r"]) * rd
            c = xc.roundtrip_cost_r(entry=t["entry"], exit_price=px, risk=rd, entry_time=str(t["entry_time"]),
                                    exit_time=str(t["exit_time"]), fee_bps_roundtrip=fee, slippage_bps_roundtrip=slip,
                                    funding_bps_per_window=fund)
            dev = max(dev, abs(c["total_cost_r"] - (float(t["cost_fee_r"]) + float(t["cost_slippage_r"]) + float(t["cost_funding_r"]))))
            n += 1
        per_leg.append({"leg": lg.leg, "state": "compared" if n else "no_cost_columns", "n": n, "max_abs_dev_R": dev})
        max_dev, n_cmp = max(max_dev, dev), n_cmp + n
    return {"max_abs_dev_R": max_dev, "n_compared": n_cmp, "tol_R": COST_TOL_R, "per_leg": per_leg,
            "legs_compared": sum(1 for p in per_leg if p["state"] == "compared"),
            "legs_excluded_policy_differs": sum(1 for p in per_leg if p["state"] == "policy_differs_excluded")}


def selfcheck(mkt: Dict[str, Series], missing: List[str], legs: List[LegList], gaps: List[str], classes: Dict[str, List[str]],
              seed: int = SEED, k_packets: int = 25, k_policy: int = 300, null_reps: int = 20) -> Dict[str, Any]:
    if missing or not mkt:
        return {"verdict": "indeterminate", "read_state": "no_data" if not mkt else "measured",
                "note": f"candles could not be read for {missing}: the self-check measured nothing for them",
                "clauses": {}, "missing": missing}
    sched = make_schedule(n=SCHEDULE_LEN, seed=seed)
    # --- clause (a): no look-ahead, both directions
    rng = np.random.default_rng(seed + 11)
    pick = [sched[int(j)] for j in rng.choice(len(sched), size=min(k_packets, len(sched)), replace=False)]
    sym0 = sorted(mkt)[0]
    shas_equal, n_a = 0, 0
    for ce in pick:
        i = mkt[sym0].last_closed(ce)
        # real vs future-garbage: every bar AFTER the cutoff replaced by 3x prices
        mk2 = {}
        for s, ser in mkt.items():
            j = ser.last_closed(ce)
            f = dict(o=ser.o.copy(), h=ser.h.copy(), l=ser.l.copy(), c=ser.c.copy())
            for kk in f:
                f[kk][j + 1:] = f[kk][j + 1:] * 3.0
            mk2[s] = Series(s, ser.t, f["o"], f["h"], f["l"], f["c"], ser.atr.copy(), ser.fee_bps, ser.slip_bps, ser.fund_bps)
            # the ATR array is recomputed as-of from the (garbage-extended) bars, not copied
            mk2[s].atr = np.array([np.nan if x is None else x for x in dsp.atr_series(mk2[s].bars(0, len(ser.t) - 1))])
        a, _ = build_masked_packet(mkt, classes, ce, 0, seed)
        b, _ = build_masked_packet(mk2, classes, ce, 0, seed)
        n_a += 1
        shas_equal += int(cdr.packet_sha(a) == cdr.packet_sha(b))
    # replay engine reads only bars AFTER the cutoff: garbage BEFORE it must not move an outcome
    n_b, same_b = 0, 0
    for ce in pick:
        for s_name, ser in mkt.items():
            i = ser.last_closed(ce)
            a0 = float(ser.atr[i])
            ent = float(ser.c[i])
            t1 = simulate(ser, i, 1.0, "market", ent, ent - 1.5 * a0, ent + 3.0 * a0, 1, 24)
            f = dict(o=ser.o.copy(), h=ser.h.copy(), l=ser.l.copy(), c=ser.c.copy())
            for kk in f:
                f[kk][:i] = f[kk][:i] * 2.0
            ser2 = Series(s_name, ser.t, f["o"], f["h"], f["l"], f["c"], ser.atr.copy(), ser.fee_bps, ser.slip_bps, ser.fund_bps)
            t2 = simulate(ser2, i, 1.0, "market", ent, ent - 1.5 * a0, ent + 3.0 * a0, 1, 24)
            n_b += 1
            same_b += int(_same_outcome(t1, t2))
    a_ok = n_a > 0 and shas_equal == n_a and n_b > 0 and same_b == n_b
    # --- clause (b): mask leak scan, with a positive control
    leaks, probe = [], None
    for k, ce in enumerate(pick):
        m, key = build_masked_packet(mkt, classes, ce, k, seed)
        txt = json.dumps(m, sort_keys=True)
        f = leak_scan(txt, key, sorted(mkt))
        if f:
            leaks.append({"cutoff_index": k, "findings": f})
        if probe is None:
            bad = json.loads(txt)
            sym = key["alias"][bad["universe"][0]["symbol"]]
            bad["meta"]["note"] = f"{sym} {datetime.fromtimestamp(ce, tz=timezone.utc):%Y-%m-%d}"
            bad["universe"][0]["last_close"] = round(100.0 / key["price_scale"][bad["universe"][0]["symbol"]], 4)
            probe = len(leak_scan(json.dumps(bad), key, sorted(mkt))) >= 3
            if not probe:
                raise AssertionError("leak scanner failed its positive control: it cannot see a planted leak")
    b_ok = not leaks and bool(pick)
    # --- clause (c): cost fidelity against the committed stack
    cf = cost_fidelity(legs)
    c_ok = cf["n_compared"] > 0 and cf["max_abs_dev_R"] <= COST_TOL_R
    # --- clause (d): planted oracle / anti-oracle / null
    rng = np.random.default_rng(seed + 21)
    cut_pol = [sched[int(j)] for j in rng.choice(len(sched), size=min(k_policy, len(sched)), replace=False)]
    geom = (1.5, 2.0, 24)
    orc = cluster_stats(_policy_oracle(mkt, cut_pol, geom, "oracle", np.random.default_rng(seed + 31)), seed)
    anti = cluster_stats(_policy_oracle(mkt, cut_pol, geom, "anti", np.random.default_rng(seed + 32)), seed)
    fp = 0
    for r in range(null_reps):
        rows = _policy_oracle(mkt, cut_pol[: max(60, k_policy // 3)], geom, "null", np.random.default_rng(seed + 100 + r))
        st = cluster_stats(rows, seed + r, 2000)
        if st.get("paired_diff_ci95") and (st["paired_diff_ci95"][0] > 0 or st["paired_diff_ci95"][1] < 0):
            fp += 1
    d_ok = bool(orc.get("n") and anti.get("n") and orc["mean_net_r"] > 0 and orc["paired_diff_ci95"][0] > 0
                and anti["mean_net_r"] < 0 and anti["paired_diff_ci95"][1] < 0 and fp <= 3)
    clauses = {
        "a_no_lookahead": {"ok": a_ok, "packets_checked": n_a, "packet_sha_equal_when_future_bars_garbled": shas_equal,
                           "replay_outcomes_checked": n_b, "replay_equal_when_past_bars_garbled": same_b},
        "b_mask": {"ok": b_ok, "packets_scanned": len(pick), "n_leaking": len(leaks), "leaks": leaks[:10],
                   "probe_positive_control_found_planted_leak": probe},
        "c_cost_fidelity": dict(cf, ok=c_ok),
        "d_planted_policies": {"ok": d_ok, "oracle": {k: orc.get(k) for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95")},
                               "anti_oracle": {k: anti.get(k) for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95")},
                               "null_false_positives": fp, "null_reps": null_reps, "null_false_positive_limit": 3},
    }
    ok = all(c["ok"] for c in clauses.values())
    bad = [k for k, c in clauses.items() if not c["ok"]]
    return {"verdict": "pass" if ok else "fail", "read_state": "measured",
            "note": "all four registered clauses hold" if ok else f"violated clause(s) {bad}; the driver reopens (registered wording)",
            "clauses": clauses, "strategy_list_gaps": gaps}


# ----------------------------------------------------------------------------- baselines (unit 02)
def baselines(mkt: Dict[str, Series], missing: List[str], legs: List[LegList], gaps: List[str],
              rostered: Dict[str, set], seed: int = SEED, draws_per_cell: int = BASELINE_DRAWS_PER_CELL) -> Dict[str, Any]:
    if missing or not mkt:
        return {"verdict": "indeterminate", "read_state": "no_data" if not mkt else "measured",
                "note": f"candles could not be read for {missing}", "geometries": {}, "missing": missing}
    rng = np.random.default_rng(seed + 41)
    out_g, all_rows, fast_fail = {}, [], []
    for name, sl, tpr, hor in REFERENCE_GEOMETRIES:
        rows, refused, exits = [], 0, {}
        for sym, ser in sorted(mkt.items()):
            pool = eligible_cutoffs(ser, WINDOW_START, WINDOW_END)
            for sd in (1.0, -1.0):
                g = {"side": sd, "etype": "market", "offset_atr": 0.0, "sl_atr": sl, "tp_atr": sl * tpr, "good_till": 1, "horizon": hor}
                for j in rng.choice(pool, size=draws_per_cell, replace=True):
                    t = transplant(ser, int(j), g)
                    if t is None or t.state == "unresolved":
                        continue
                    if t.state != "filled":
                        refused += 1
                        continue
                    exits[t.reason] = exits.get(t.reason, 0) + 1
                    rows.append({"week": iso_week(int(ser.t[j]) + SEC), "net_r": t.net_r, "days": t.days, "diff": None,
                                 "cost_r": t.cost_r})
        st = cluster_stats(rows, seed)
        st.update(geometry={"sl_atr": sl, "tp_r": tpr, "horizon_bars": hor, "entry": "market"}, refused=refused,
                  mean_cost_r=float(np.mean([r["cost_r"] for r in rows])) if rows else None, exits=exits,
                  n_to_resolve={"+0.10R": required_n(st.get("sd_net_r", float("nan")), 0.10),
                                "+0.20R": required_n(st.get("sd_net_r", float("nan")), 0.20)})
        out_g[name] = st
        all_rows += rows
        if st["n"] < BASELINE_N_FLOOR:
            fast_fail.append(f"{name}: n_filled {st['n']} < {BASELINE_N_FLOOR}")
    pooled = cluster_stats(all_rows, seed)
    so = strategy_own_table(legs, WINDOW_START, WINDOW_END)
    uncovered = sorted(sym for sym in mkt if rostered.get(sym) and not any(lg.symbol == sym for lg in legs))
    no_leg = sorted(sym for sym in mkt if not rostered.get(sym))
    ok = not fast_fail and bool(legs)
    return {"verdict": "pass" if ok else "indeterminate", "read_state": "measured",
            "note": ("calibrated: every reference geometry measured at n >= %d" % BASELINE_N_FLOOR) if ok else
            ("; ".join(fast_fail) or "no strategy lists readable"),
            "geometries": out_g, "pooled_random_entry": pooled,
            "n_required_at_pooled_sd": {"+0.10R": required_n(pooled.get("sd_net_r", float("nan")), 0.10),
                                       "+0.20R": required_n(pooled.get("sd_net_r", float("nan")), 0.20),
                                       "basis": "iid arithmetic (2.8 sd / effect)^2; the cluster-bootstrap CI the verdict uses is wider"},
            "strategy_own": so, "symbols_rostered_but_without_a_list": uncovered, "symbols_with_no_rostered_leg": no_leg,
            "rostered_legs": {k: sorted(v) for k, v in rostered.items()}, "strategy_list_gaps": gaps,
            "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()]}


# ----------------------------------------------------------------------------- CLI
def _write_verdict(out: Path, res: Dict[str, Any], population: str, n: Optional[int], note: str,
                   records: Optional[List[dict]] = None, sources: Optional[List[str]] = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    doc = {"verdict": res["verdict"], "read_state": res.get("read_state", "measured"), "population": population,
           "n": n, "measurement": res, "note": note, "data_inputs": sorted(s for s in (sources or []) if s)}
    if records:
        doc["records"] = records
    (out / "verdict.json").write_text(json.dumps(doc, indent=2, default=str) + "\n")


def latest_verdict_path(unit: Optional[str], root: Path = REPO / "comms" / "research") -> Optional[Path]:
    """The newest landed run of `unit` (run ids are increasing integers); None when there is none -- which the
    caller reads as `could not look`, never as a pass."""
    if not unit:
        return None
    runs = [p for p in (root / unit).glob("*/verdict.json") if p.parent.name.isdigit()]
    if not runs:
        print(f"desk_gen_replay_driver: no landed run of {unit} under {root / unit}: the self-check reads as could-not-look", file=sys.stderr)
        return None
    chosen = max(runs, key=lambda p: int(p.parent.name))
    print(f"desk_gen_replay_driver: self-check verdict = {chosen} (newest of {len(runs)} landed run(s) of {unit})", file=sys.stderr)
    return chosen


def candle_manifest(mkt: Dict[str, Series]) -> List[str]:
    """One traceable line per symbol (rows, first / last bar, sha256 of the replay-window arrays) so a result
    names the exact candles it read without committing megabytes of them beside it."""
    out = []
    lo, hi = _epoch(CANDLE_SINCE), _epoch(WINDOW_END) + 10 * 86400
    for sym, s in sorted(mkt.items()):
        m = (s.t >= lo) & (s.t <= hi)
        h = hashlib.sha256()
        for arr in (s.t[m], s.o[m], s.h[m], s.l[m], s.c[m]):
            h.update(np.ascontiguousarray(arr).tobytes())
        out.append(f"binance_vision:{sym}:{SCAN_TF}:rows={int(m.sum())}:first={datetime.fromtimestamp(int(s.t[m][0]), tz=timezone.utc):%Y-%m-%dT%H}"
                   f":last={datetime.fromtimestamp(int(s.t[m][-1]), tz=timezone.utc):%Y-%m-%dT%H}:sha256={h.hexdigest()[:16]}")
    return out


def _prepare(a: argparse.Namespace) -> Tuple[Dict[str, Series], List[str], Dict[str, List[str]], str, List[str]]:
    uni, note = parse_universe()
    syms = [u["symbol"] for u in uni]
    # candles go to a scratch dir, never beside the result: the runner commits {out_dir}
    cdir = Path(a.candles_dir) if a.candles_dir else Path(tempfile.mkdtemp(prefix="desk_gen_candles_"))
    if getattr(a, "fetch", False):
        fetch_market(cdir, syms)
    mkt, missing = load_market(cdir, syms)
    classes = {u["symbol"]: u["classes"] for u in uni}
    return mkt, missing, classes, "; ".join(note), (candle_manifest(mkt) if mkt else []) + [f"MISSING:{m}" for m in missing]


def cmd_selfcheck(a: argparse.Namespace) -> int:
    mkt, missing, classes, note, src = _prepare(a)
    rost = rostered_legs(sorted(mkt)) if mkt else {}
    legs, gaps = load_strategy_lists(rost) if mkt else ([], [])
    res = selfcheck(mkt, missing, legs, gaps, classes, a.seed)
    pop = (f"{len(mkt)} crypto USDT symbols of the pull-list UNION ({', '.join(sorted(mkt))}); 25 sampled masked scan packets; "
           f"{res.get('clauses', {}).get('c_cost_fidelity', {}).get('n_compared', 0)} committed Stage-0 trades for cost fidelity")
    _write_verdict(Path(a.out), res, pop, len(mkt), f"{res['note']} | {note}", None, src)
    print(json.dumps({"verdict": res["verdict"], "clauses": {k: v["ok"] for k, v in res.get("clauses", {}).items()}}))
    return 0


def cmd_baselines(a: argparse.Namespace) -> int:
    mkt, missing, classes, note, src = _prepare(a)
    rost = rostered_legs(sorted(mkt)) if mkt else {}
    legs, gaps = load_strategy_lists(rost) if mkt else ([], [])
    res = baselines(mkt, missing, legs, gaps, rost, a.seed)
    recs = [{"leg": f"random_entry_{g}", "population": f"random-entry null, geometry {g}", "n": v["n"],
             # research_result.validate(): a measured row carries the run's verdict; not_applicable is only for no_data rows
             "verdict": res["verdict"] if v["n"] else "not_applicable",
             "read_state": "measured" if v["n"] else "no_data", "mean_net_r": v.get("mean_net_r")}
            for g, v in res.get("geometries", {}).items()]
    pop = (f"random-entry null over {len(mkt)} symbols x 2 sides x {len(REFERENCE_GEOMETRIES)} geometries x {BASELINE_DRAWS_PER_CELL} draws; "
           f"strategy-own: {len(legs)} committed Stage-0 lists")
    _write_verdict(Path(a.out), res, pop, res.get("pooled_random_entry", {}).get("n"), f"{res['note']} | {note}", recs or None, src)
    print(json.dumps({"verdict": res["verdict"], "n_required": res.get("n_required_at_pooled_sd")}))
    return 0


JUDGE_PROTOCOL = """# DESK-18 judging protocol (one packet per call; no tools, no repo, no web)

You are the trading desk's ENTRY-GENERATION role. You see ONE masked market scan packet. Symbols are aliases
(re-drawn per packet), prices are rebased so each alias's last close is 100, time is anchored in year 2000,
volume and calendar are withheld. The strategies' book is NOT shown. Decide whether any alias offers a trade
worth taking over the next hours, net of costs (the packet's `history` rows are net-of-cost forward-R base rates).

Reply with JSON lines and nothing else, ONE of:

  {"packet_id": "<meta.packet_id>", "action": "no_trade"}
  {"packet_id": "<meta.packet_id>", "action": "propose_entry", "judge_prior": <P(target before stop), 0..1>,
   "proposal": {"symbol": "<alias>", "venue_class": "masked:perp", "side": "long"|"short", "timeframe": "1h",
                "horizon_bars": <int 1..200, the longest you will hold, in 1h bars>,
                "entry": {"type": "market"|"limit"|"stop", "level": <price>, "good_till_bars": <int >= 1>},
                "stop": {"level": <price>, "basis": "swing_level"|"structure_invalidation"|"atr_multiple"|"range_boundary"|"liquidity_level"},
                "tp": {"level": <price>, "basis": "swing_level"|"measured_move"|"base_rate_quantile"|"liquidity_level"|"range_boundary"|"ml_head", "p_hit": <0.10..<1>},
                "expected_r_net": <your net-of-cost estimate in R, below the target's own R>,
                "thesis": "<one line>", "novelty": "unverifiable", "onboarding": "onboarded"}}

At most %(cap)d propose_entry rows (different aliases) per packet; `no_trade` is the default and is a real answer.
Rules the scorer enforces, row by row (a refused row is scored as no_trade and counted):
* geometry: long needs stop < entry < target, short needs target < entry < stop;
* the target is a PREDICTION, not a sentinel: under %(sent).0f R from entry, under %(cap_pct).1f%% from entry, p_hit >= %(reach).2f;
* `novelty` must be "unverifiable" and `onboarding` "onboarded";
* a market entry fills at the NEXT bar's open; a limit/stop fills only if price trades through the level within
  good_till_bars; the stop is checked before the target inside a bar; the time stop exits at the close of the
  horizon bar; a fill whose stop is within %(minrisk).1f ATR of (or beyond) the fill price is refused.
Costs (fee, slippage, funding) are charged by the scorer; do not model them in the levels.
"""


def cmd_packets(a: argparse.Namespace) -> int:
    mkt, missing, classes, note, src = _prepare(a)
    if missing:
        print(json.dumps({"error": f"candles missing for {missing}"}))
        return 2
    sched = make_schedule(n=SCHEDULE_LEN, seed=a.seed)
    sel = sched[a.offset: a.offset + a.n]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys, leaked, sizes = [], 0, []
    with (out / "packets.jsonl").open("w") as fh:
        for off, ce in enumerate(sel):
            k = a.offset + off
            m, key = build_masked_packet(mkt, classes, ce, k, a.seed)
            txt = json.dumps(m, sort_keys=True)
            if leak_scan(txt, key, sorted(mkt)):
                leaked += 1
                continue                          # a leaking packet is never handed to a judge
            fh.write(json.dumps({"packet_id": m["meta"]["packet_id"], "packet": m}, sort_keys=True) + "\n")
            key["packet_sha"] = cdr.packet_sha(m)          # the score step re-derives the packet and must match
            keys.append(key)
            sizes.append(len(txt))
    (out / "mask-key.json").write_text(json.dumps({"seed": a.seed, "note": "NEVER given to the judging session", "keys": keys}, indent=1) + "\n")
    (out / "JUDGE-PROTOCOL.md").write_text(JUDGE_PROTOCOL % {"cap": MAX_PER_PACKET, "sent": cdr.SENTINEL_R_FLOOR,
                                                              "cap_pct": cdr.TP_VENUE_CAP_PCT * 100, "reach": cdr.REACH_FLOOR,
                                                              "minrisk": MIN_RISK_ATR})
    print(json.dumps({"packets": len(keys), "withheld_for_leak": leaked, "schedule_len": len(sched), "note": note,
                      "median_packet_chars": int(np.median(sizes)) if sizes else None}))
    return 0


def _load_judged(a: argparse.Namespace, mkt: Dict[str, Series], classes: Dict[str, List[str]]
                 ) -> Tuple[Optional[Tuple[dict, dict, dict, dict]], Optional[dict]]:
    """((keys, packets, by, intake), None) or (None, error). Reads the key file and the proposals; the packets are
    the judge's file when given, else re-derived from the candles and verified against the sha the key carries."""
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    packets: Dict[str, dict] = {}
    if a.packets:
        for line in Path(a.packets).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                packets[r["packet_id"]] = r["packet"]
    else:
        # packets are a pure function of (candles, cutoff, index, seed): re-derive them, and refuse if the
        # candles have drifted since the judge saw them (the key carries each packet's sha)
        want = {json.loads(ln)["packet_id"] for ln in Path(a.proposals).read_text().splitlines() if ln.strip()}
        drift = []
        for pid in sorted(want & set(keys)):
            k = keys[pid]
            m, _ = build_masked_packet(mkt, classes, k["cutoff_epoch"], k["index"], a.seed)
            if m["meta"]["packet_id"] != pid or (k.get("packet_sha") and cdr.packet_sha(m) != k["packet_sha"]):
                drift.append(pid)
            packets[pid] = m
        if drift:
            return None, {"error": f"{len(drift)} re-derived packet(s) differ from what the judge saw (candle drift or a changed builder)",
                          "first": drift[:3]}
    by, intake = read_proposals(Path(a.proposals), packets)
    return (keys, packets, by, intake), None


def cmd_intake(a: argparse.Namespace) -> int:
    """For the judging lane: the stopping-rule accounting from the proposals alone. NO replay, so no outcome is seen."""
    mkt, missing, classes, note, src = _prepare(a)
    if missing:
        print(json.dumps({"error": f"candles missing for {missing}"}))
        return 2
    got, err = _load_judged(a, mkt, classes)
    if err:
        print(json.dumps(err))
        return 2
    keys, packets, by, intake = got
    valid_index = [int(keys[pid]["index"]) for pid, v in by.items() for _ in v]
    d = stopping_design([int(keys[pid]["index"]) for pid in by], [k["index"] for k in keys.values()], valid_index)
    print(json.dumps({**d, "next_batch_allowed": d["is_schedule_prefix"] and d["valid_proposals_total"] < STOP_PROPOSALS
                      and not d["schedule_exhausted"], "intake": intake}))
    return 0


def cmd_score(a: argparse.Namespace) -> int:
    mkt, missing, classes, note, src = _prepare(a)
    if missing:
        print(json.dumps({"error": f"candles missing for {missing}"}))
        return 2
    got, err = _load_judged(a, mkt, classes)
    if err:
        print(json.dumps(err))
        return 2
    keys, packets, by, intake = got
    rost = rostered_legs(sorted(mkt))
    legs, gaps = load_strategy_lists(rost)
    sc: Optional[bool] = None
    sc_src = a.selfcheck_verdict or latest_verdict_path(a.selfcheck_unit)
    if sc_src:
        sc = json.loads(Path(sc_src).read_text()).get("verdict") == "pass"
    cutoff = datetime.fromisoformat(a.model_cutoff).replace(tzinfo=timezone.utc) if a.model_cutoff else None
    res = score(mkt, keys, by, legs, rost, subset=a.subset, cutoff=cutoff, selfcheck=sc, seed=a.seed)
    res["selfcheck_verdict_path"] = str(sc_src) if sc_src else None
    res["intake"] = intake
    res["n_packets"] = len(packets) if a.packets else len(keys)
    res["n_packets_judged"] = len(by)
    res["strategy_list_gaps"] = gaps
    st = res["stats"]
    pop = (f"entry generation, subset={a.subset}: {st['n']} filled proposals from {len(by)} judged of {len(packets)} masked packets "
           f"over {', '.join(sorted(mkt))}")
    notes = "; ".join(res["reasons"]) or "all registered clauses met"
    recs = [{"leg": k, "population": f"{k} entry generation", "n": v["n"],
             "verdict": res["verdict"] if v["n"] >= 20 else "not_applicable",
             "read_state": "measured" if v["n"] >= 20 else "no_data", "mean_net_r": v["mean_net_r"]}
            for k, v in (st.get("by_symbol") or {}).items()]
    _write_verdict(Path(a.out), res, pop, st["n"], f"{notes} | {note}", recs or None, src)
    print(json.dumps({"verdict": res["verdict"], "n_filled": st["n"], "mean_net_r": st.get("mean_net_r"), "mean_ci95": st.get("mean_ci95")}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("selfcheck", cmd_selfcheck), ("baselines", cmd_baselines), ("packets", cmd_packets), ("intake", cmd_intake),
                     ("score", cmd_score)):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--fetch", action="store_true", help="fetch candles from Binance Vision (the queue runner)")
        s.add_argument("--candles-dir", help="default: a scratch dir outside --out (the runner commits --out)")
        s.add_argument("--seed", type=int, default=SEED)
        s.set_defaults(fn=fn)
        if name == "packets":
            s.add_argument("--n", type=int, required=True)
            s.add_argument("--offset", type=int, default=0)
        if name in ("score", "intake"):
            s.add_argument("--proposals", required=True)
            s.add_argument("--packets", help="the judge's packets.jsonl; omitted = re-derive each judged packet and verify its sha")
            s.add_argument("--mask-key", required=True)
        if name == "score":
            s.add_argument("--subset", choices=("all", "new"), default="all")
            s.add_argument("--selfcheck-verdict", help="path to a unit-01 verdict.json")
            s.add_argument("--selfcheck-unit", help="queue unit id: use the newest landed comms/research/<unit>/<run>/verdict.json")
            s.add_argument("--model-cutoff", help="the judge model's knowledge cutoff date, YYYY-MM-DD")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

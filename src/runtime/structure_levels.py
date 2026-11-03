"""Causal market-structure levels: confirmed swings and unfilled FVG edges.

ONE pure, index-based module shared by the research harnesses and (later) the
live monitor (row STRUCTURE-EXITS-DEFAULT). It has no I/O, no config reads, no
pandas, and no global state.

NO LOOKAHEAD, by construction
-----------------------------
* A swing high at bar ``p`` with half-width ``n`` needs the ``n`` bars on its
  right to be known, so it is CONFIRMED at bar ``p + n`` (the bar whose close
  completes the pattern). ``levels_asof(t)`` returns only levels with
  ``confirmed_idx <= t``; the level is usable from the bar AFTER ``t``.
* A fair-value gap formed by bars ``k-2, k-1, k`` is known at the close of
  bar ``k`` (``confirmed_idx = k``). It is "unfilled as of t" iff no bar in
  ``k+1 .. t`` has traded back to its near edge.
* Everything stored may have been computed from the whole frame (for speed),
  but every query filters by ``confirmed_idx`` / ``fill_idx`` against ``t``.
  The equivalence "query at t on the full frame == query at t on the frame
  truncated to bars 0..t" is the parity contract and is pinned by
  ``tests/test_structure_levels.py``.

Tie rule: a swing high needs ``high[p] > high[p-n..p-1]`` (strictly) and
``high[p] >= high[p+1..p+n]``; the mirror for lows. Plateaus therefore yield
the FIRST bar of a flat top only.

Bar-timeframe agnostic: the caller passes the arrays of whatever timeframe the
leg runs on (a daily or session-aware frame for overnight-gap legs).
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

SWING_HIGH = "swing_high"
SWING_LOW = "swing_low"
FVG_BEAR_EDGE = "fvg_bear_edge"   # lower edge of a bearish gap: resistance above price
FVG_BULL_EDGE = "fvg_bull_edge"   # upper edge of a bullish gap: support below price


@dataclass(frozen=True)
class Level:
    kind: str
    price: float
    formed_idx: int       # bar the level sits on (pivot bar / the middle gap bar)
    confirmed_idx: int    # first bar at whose CLOSE the level is known
    fill_idx: int = -1    # FVG only: first bar that traded to the edge (-1 = never)


class StructureLevels:
    """Structure of one OHLC frame. Build once, query ``*_asof(t)`` per bar."""

    def __init__(self, high: Sequence[float], low: Sequence[float], n: int = 3):
        if n < 1:
            raise ValueError("pivot half-width n must be >= 1")
        self.n = int(n)
        h = np.asarray(high, dtype=float)
        lo = np.asarray(low, dtype=float)
        if h.shape != lo.shape or h.ndim != 1:
            raise ValueError("high and low must be equal-length 1-D")
        self._len = len(h)
        self._sh = self._pivots(h, True)
        self._sl = self._pivots(lo, False)
        self._bear, self._bull = self._fvgs(h, lo)
        # confirmed_idx is ascending in every list -> bisect on it.
        self._sh_c = [x.confirmed_idx for x in self._sh]
        self._sl_c = [x.confirmed_idx for x in self._sl]
        self._bear_c = [x.confirmed_idx for x in self._bear]
        self._bull_c = [x.confirmed_idx for x in self._bull]

    # ---- construction --------------------------------------------------
    def _pivots(self, a: np.ndarray, is_high: bool) -> List[Level]:
        n, m = self.n, len(a)
        out: List[Level] = []
        for p in range(n, m - n):
            left, right = a[p - n:p], a[p + 1:p + n + 1]
            v = a[p]
            if np.isnan(v) or np.isnan(left).any() or np.isnan(right).any():
                continue
            if is_high:
                ok = v > left.max() and v >= right.max()
            else:
                ok = v < left.min() and v <= right.min()
            if ok:
                out.append(Level(SWING_HIGH if is_high else SWING_LOW, float(v), p, p + n))
        return out

    @staticmethod
    def _fvgs(h: np.ndarray, lo: np.ndarray):
        bear: List[Level] = []
        bull: List[Level] = []
        m = len(h)
        for k in range(2, m):
            # bullish gap: low[k] > high[k-2]; support edge = low[k]? The unfilled
            # edge price that matters as a LEVEL is the near edge a retrace first
            # meets: top of the gap (low[k]) for a bull gap, bottom (high[k]) for a bear gap.
            if lo[k] > h[k - 2]:
                edge = float(lo[k])
                fill = -1
                for q in range(k + 1, m):
                    if lo[q] <= edge:
                        fill = q
                        break
                bull.append(Level(FVG_BULL_EDGE, edge, k - 1, k, fill))
            elif h[k] < lo[k - 2]:
                edge = float(h[k])
                fill = -1
                for q in range(k + 1, m):
                    if h[q] >= edge:
                        fill = q
                        break
                bear.append(Level(FVG_BEAR_EDGE, edge, k - 1, k, fill))
        return bear, bull

    # ---- causal queries -------------------------------------------------
    @staticmethod
    def _upto(lst: List[Level], keys: List[int], t: int) -> List[Level]:
        return lst[:bisect_right(keys, t)]

    def last_swing_low(self, t: int, below: Optional[float] = None) -> Optional[Level]:
        """Most recently CONFIRMED swing low as of bar t (optionally below a price)."""
        for lv in reversed(self._upto(self._sl, self._sl_c, t)):
            if below is None or lv.price < below:
                return lv
        return None

    def last_swing_high(self, t: int, above: Optional[float] = None) -> Optional[Level]:
        for lv in reversed(self._upto(self._sh, self._sh_c, t)):
            if above is None or lv.price > above:
                return lv
        return None

    def resistance_above(self, t: int, price: float, *, fvg: bool = True) -> Optional[Level]:
        """Nearest opposing level ABOVE price known at bar t (swing high or unfilled bear-FVG edge)."""
        best: Optional[Level] = None
        cands = [lv for lv in self._upto(self._sh, self._sh_c, t) if lv.price > price]
        if fvg:
            cands += [lv for lv in self._upto(self._bear, self._bear_c, t)
                      if lv.price > price and (lv.fill_idx < 0 or lv.fill_idx > t)]
        for lv in cands:
            if best is None or lv.price < best.price:
                best = lv
        return best

    def support_below(self, t: int, price: float, *, fvg: bool = True) -> Optional[Level]:
        """Nearest opposing level BELOW price known at bar t (swing low or unfilled bull-FVG edge)."""
        best: Optional[Level] = None
        cands = [lv for lv in self._upto(self._sl, self._sl_c, t) if lv.price < price]
        if fvg:
            cands += [lv for lv in self._upto(self._bull, self._bull_c, t)
                      if lv.price < price and (lv.fill_idx < 0 or lv.fill_idx > t)]
        for lv in cands:
            if best is None or lv.price > best.price:
                best = lv
        return best

    def levels_asof(self, t: int) -> List[Level]:
        """Every level known at bar t (unfilled FVGs only), ordered by confirmed_idx."""
        out = (self._upto(self._sh, self._sh_c, t) + self._upto(self._sl, self._sl_c, t)
               + [lv for lv in self._upto(self._bear, self._bear_c, t) if lv.fill_idx < 0 or lv.fill_idx > t]
               + [lv for lv in self._upto(self._bull, self._bull_c, t) if lv.fill_idx < 0 or lv.fill_idx > t])
        return sorted(out, key=lambda lv: (lv.confirmed_idx, lv.kind, lv.price))


def levels_asof(high: Sequence[float], low: Sequence[float], t: int, n: int = 3) -> List[Level]:
    """Live-monitor entry point: levels known at bar ``t`` from bars ``0..t`` ONLY.

    Truncates before building, so it cannot see past ``t`` even by mistake. The
    harness builds ``StructureLevels`` once over the whole frame; parity of the
    two paths is the contract tested in ``tests/test_structure_levels.py``.
    """
    return StructureLevels(list(high)[:t + 1], list(low)[:t + 1], n).levels_asof(t)


# ---- the exit rule shared by harness and monitor -----------------------------
def structure_sl(sl_struct: StructureLevels, t: int, entry: float, is_long: bool,
                 atr: float, atr_stop_dist: float, *, buffer_atr: float = 0.25,
                 clamp: tuple = (0.5, 3.0)) -> Optional[float]:
    """SL beyond the last confirmed swing on the adverse side, minus an ATR buffer,
    the distance clamped to ``clamp`` x the declared ATR-stop distance.
    None when no confirmed swing sits on the adverse side (caller keeps its ATR stop)."""
    if is_long:
        lv = sl_struct.last_swing_low(t, below=entry)
        if lv is None:
            return None
        dist = entry - (lv.price - buffer_atr * atr)
    else:
        lv = sl_struct.last_swing_high(t, above=entry)
        if lv is None:
            return None
        dist = (lv.price + buffer_atr * atr) - entry
    dist = min(max(dist, clamp[0] * atr_stop_dist), clamp[1] * atr_stop_dist)
    return entry - dist if is_long else entry + dist


def structure_tp(sl_struct: StructureLevels, t: int, entry: float, is_long: bool,
                 risk: float, *, min_r: float = 1.0, fvg: bool = True) -> Optional[float]:
    """Nearest opposing level at >= ``min_r`` R from entry, known at bar t. None if none."""
    floor = entry + min_r * risk if is_long else entry - min_r * risk
    lv = (sl_struct.resistance_above(t, floor, fvg=fvg) if is_long
          else sl_struct.support_below(t, floor, fvg=fvg))
    return None if lv is None else lv.price


def parse_structure_exit(spec: str) -> int:
    """``--structure-exit pivot=N`` -> N. '' -> 0 (off). Anything else raises."""
    if not spec:
        return 0
    key, _, val = spec.partition("=")
    if key.strip() != "pivot" or not val.strip().isdigit() or int(val) < 1:
        raise ValueError(f"--structure-exit expects pivot=N (N>=1), got {spec!r}")
    return int(val)


class StructureExit:
    """Per-trade structure bracket. Same object in the harness and (later) the live monitor.

    start()  -> initial SL / risk / TP as of the entry bar's close (None when no
               confirmed adverse swing exists: caller keeps its own stop, the arm
               degenerates to the declared exit for that trade).
    on_bar_close(j, close, sl, tp) -> (sl, tp) after bar j has CLOSED; the new
               levels bind from bar j+1. SL only ratchets toward price; TP is extend-only.
    """

    def __init__(self, levels: StructureLevels, is_long: bool, atr: float, *,
                 buffer_atr: float, min_r: float, fvg: bool, sl: float, risk: float,
                 tp: Optional[float]):
        self.levels, self.is_long, self.atr = levels, is_long, atr
        self.buffer_atr, self.min_r, self.fvg = buffer_atr, min_r, fvg
        self.sl, self.risk, self.tp = sl, risk, tp

    @classmethod
    def start(cls, levels: StructureLevels, t: int, entry: float, is_long: bool,
              atr: float, atr_stop_dist: float, *, buffer_atr: float = 0.25,
              min_r: float = 1.0, fvg: bool = True,
              clamp: tuple = (0.5, 3.0)) -> Optional["StructureExit"]:
        sl = structure_sl(levels, t, entry, is_long, atr, atr_stop_dist,
                          buffer_atr=buffer_atr, clamp=clamp)
        if sl is None:
            return None
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        tp = structure_tp(levels, t, entry, is_long, risk, min_r=min_r, fvg=fvg)
        return cls(levels, is_long, atr, buffer_atr=buffer_atr, min_r=min_r, fvg=fvg,
                   sl=sl, risk=risk, tp=tp)

    def on_bar_close(self, j: int, close: float, sl: float, tp: Optional[float],
                     entry: float) -> tuple:
        if self.is_long:
            lv = self.levels.last_swing_low(j, below=close)
            if lv is not None:
                sl = max(sl, lv.price - self.buffer_atr * self.atr)
            new_tp = structure_tp(self.levels, j, entry, True, self.risk,
                                  min_r=self.min_r, fvg=self.fvg)
            if new_tp is not None and (tp is None or new_tp > tp):
                tp = new_tp
        else:
            lv = self.levels.last_swing_high(j, above=close)
            if lv is not None:
                sl = min(sl, lv.price + self.buffer_atr * self.atr)
            new_tp = structure_tp(self.levels, j, entry, False, self.risk,
                                  min_r=self.min_r, fvg=self.fvg)
            if new_tp is not None and (tp is None or new_tp < tp):
                tp = new_tp
        self.sl, self.tp = sl, tp
        return sl, tp

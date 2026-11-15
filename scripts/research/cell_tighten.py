"""CELL-RESTRICTED TIGHTEN — the harness lever for RQ-20261101-78fc-09 (ltr-tighten-sl), build gap (c).

WHY. comms/research/ltr_tighten_optimize/verdict.json (#21003): tightening in the EARLY cell lost -0.041 R
(CI -0.087..-0.005), and all 5 priced live tighten options sat in that cell. The lane's never-graded fallback is a
tighten allowed only in the LATE cell: open >= +1 R, new stop >= break-even, and >= 1 ATR of room left to price.
Row BOOK-SIM-REAL-SIZER was marked DONE without this arm (manager order 2026-11-13 04:00Z).

THE LEVER (off unless ``min_r > 0``; every harness stays byte-identical when off). Evaluated on each bar's CLOSE
after the harness's own trail ratchet and break-even floor, so the moved stop binds from the NEXT bar
(SL-first, the convention both harnesses use):
  * cell     : open R at the close >= ``min_r`` (default use 1.0), measured against the entry-time risk;
  * level    : candidate stop = close - ``room_atr`` x ATR (long; mirrored for short) -- the TIGHTEST stop the
               gate admits, i.e. exactly ``room_atr`` ATR of room;
  * gate     : candidate >= entry (long; <= for short) -- never below break-even -- and strictly tighter than
               the current stop (a tighten never loosens);
  * one-shot : at most ONE tighten per trade.
``mode``:
  * ``first``  -- the CANDIDATE: tighten at the first bar whose close is in the cell;
  * ``random`` -- the MATCHED RANDOM CONTROL for the same cell: at each in-cell bar the tighten fires with
                  probability ``p`` (default 0.5), from an RNG seeded by (``seed``, the trade's entry index), so the
                  control acts in the SAME cell at the SAME level rule but at random timing, with no lookahead.
Both arms are fixed here before any run; the unit's rule (RULE-AM-RISK-ADJUSTED-V1, R4 vs this control) reads them.

Pure (no I/O). ``--self-test`` via tests/test_cell_tighten.py.
"""
from __future__ import annotations

import random
from typing import Optional

MODES = ("first", "random")


class CellTighten:
    """Per-TRADE state. Build one per trade (``for_trade``); call ``on_close`` on every bar close after the trail
    update; it returns the (possibly tightened) stop."""

    def __init__(self, min_r: float, room_atr: float = 1.0, mode: str = "first", p: float = 0.5,
                 seed: int = 0, entry_i: int = 0):
        if mode not in MODES:
            raise ValueError(f"cell-tighten mode {mode!r} not in {MODES}")
        if not 0.0 < float(p) <= 1.0:
            raise ValueError("cell-tighten p must be in (0, 1]")
        self.min_r, self.room_atr, self.mode, self.p = float(min_r), float(room_atr), mode, float(p)
        self._rng = random.Random(f"{int(seed)}:{int(entry_i)}")
        self.fired_j: Optional[int] = None
        self.in_cell_bars = 0

    @property
    def on(self) -> bool:
        return self.min_r > 0.0

    def on_close(self, j: int, close: float, entry: float, risk: float, atr: float, stop: float,
                 is_long: bool) -> float:
        if not self.on or self.fired_j is not None or risk <= 0 or atr != atr or atr <= 0:
            return stop
        open_r = ((close - entry) if is_long else (entry - close)) / risk
        if open_r < self.min_r:
            return stop
        cand = close - self.room_atr * atr if is_long else close + self.room_atr * atr
        admissible = (cand >= entry and cand > stop) if is_long else (cand <= entry and cand < stop)
        if not admissible:
            return stop
        self.in_cell_bars += 1
        if self.mode == "random" and self._rng.random() >= self.p:
            return stop
        self.fired_j = j
        return cand


def for_trade(min_r: float, room_atr: float, mode: str, p: float, seed: int, entry_i: int) -> CellTighten:
    return CellTighten(min_r, room_atr, mode, p, seed, entry_i)


def add_cli(parser) -> None:
    """The four harness flags (backtest_trend.py / backtest_pullback.py share them)."""
    parser.add_argument("--cell-tighten-min-r", type=float, default=0.0,
                        help="CELL TIGHTEN (0 = off, byte-identical): one-shot stop move once open R >= this (RQ-20261101-78fc-09)")
    parser.add_argument("--cell-tighten-room-atr", type=float, default=1.0,
                        help="CELL TIGHTEN: the new stop leaves exactly this many ATR of room (and never below break-even)")
    parser.add_argument("--cell-tighten-mode", choices=MODES, default="first",
                        help="first = tighten at the first in-cell close (candidate); random = matched random control")
    parser.add_argument("--cell-tighten-random-p", type=float, default=0.5,
                        help="CELL TIGHTEN random control: per in-cell bar firing probability")
    parser.add_argument("--cell-tighten-seed", type=int, default=0, help="CELL TIGHTEN random control seed")

#!/usr/bin/env python3
# wiring: imported by scripts/research/m20_fleet_exit_sweep.py (--holdout-frac); tests/test_m20_holdout.py
"""Pre-registered holdout for the m20 exit-lever sweep: discovery and confirmation in ONE run.

OPERATOR DECISION, 2026-10-16 (popup, "Holdout re-run"; row RESEARCH-CONFIRM-FRESH-WINDOW), verbatim:
  "From now on, each sweep holds back the most recent ~25% of history before it chooses settings,
   then tests the winner on that held-back part, so discovery and confirmation come from one run
   with no wait. The 13 current passes get re-run that way now, within days. Cost: each choice is
   made on 25% less data."

WHY (measured 2026-10-16, pipeline PI-20261016-QOTFUEXV-0003): a forward-only confirmation after a
60-day wait reaches the rule's 25-OOS-trade floor for NONE of the 13 m20 PASS legs (0.7-13.9 trades
in 60 days; 108-2252 days to the floor), and no backward-disjoint window exists because the sweep
uses every bar the trainer holds. Holding the latest span back BEFORE selection is the only way to
get an unseen window today.

THE MECHANISM
  * `plan_holdout` places one boundary per leg from the leg's own full-history base trades: the
    holdout keeps at least `share` of them AND at least the rule's floor, never more than `cap`
    (40%). Short of the floor at the cap -> `underpowered`, said in the record, not hidden.
  * `HoldoutGuard` is the lookahead guard. In DISCOVERY every harness window is capped at the
    boundary, and a window that explicitly asks for data at or past it is REFUSED (HoldoutLeak):
    selection cannot read the holdout even by accident. In CONFIRM only windows starting at or
    after the boundary are allowed.
  * `confirm_cells` grades ONLY the cells discovery selected (`is_oos_pass`), once, on the holdout,
    under the same Path A comparison (`beats`) and the same base-trades floor.
  * `leg_confirmation` folds that into one of: confirmed / not_replicated / underpowered /
    no_discovery. A FAIL closes the configuration, never the family (family-retirement protocol).

Tier-1 research tooling. No live path.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

DEFAULT_SHARE = 0.25
MAX_SHARE = 0.40


class HoldoutLeak(RuntimeError):
    """A discovery-phase read asked for data inside the held-back span."""


def plan_holdout(entry_stamps: Sequence[str], share: float, floor: int,
                 cap: float = MAX_SHARE) -> dict[str, Any]:
    """Boundary for one leg. `entry_stamps` = the base's full-history entry times (ISO strings).

    Holdout size k = max(ceil(share * N), floor), clamped to floor(cap * N). The boundary is the
    DATE of the k-th trade from the end, so the harness (which windows candles by date) can
    reproduce it. Pure."""
    stamps = sorted(str(s) for s in entry_stamps if s)
    n = len(stamps)
    out: dict[str, Any] = {"lifetime_trades": n, "share_requested": share, "floor": floor,
                           "cap": cap}
    if n == 0:
        return {**out, "boundary": None, "state": "no_trades"}
    k = max(math.ceil(share * n), floor)
    k_cap = math.floor(cap * n)
    underpowered = k > k_cap
    k = min(k, k_cap)
    if k < 1:
        return {**out, "boundary": None, "state": "no_trades"}
    boundary = stamps[-k][:10]
    held = sum(1 for s in stamps if s[:10] >= boundary)
    return {**out, "boundary": boundary, "holdout_trades_planned": held,
            "discovery_trades_planned": n - held, "share_used": round(held / n, 4),
            "state": "underpowered" if underpowered else "ok",
            "discovery_span": [stamps[0][:10], boundary], "holdout_span": [boundary, stamps[-1][:10]]}


class HoldoutGuard:
    """Caps/refuses harness windows by phase. `boundary` None = inactive (every window passes)."""

    def __init__(self) -> None:
        self.boundary: str | None = None
        self.cap: str | None = None
        self.phase: str = "off"

    def begin(self, boundary: str | None) -> None:
        """Discovery may read up to and including `cap` = the day BEFORE the boundary: the harnesses
        filter `timestamp <= end` and `>= start` (backtest_pullback._date_filter), so ending discovery
        AT the boundary would put that day's 00:00 bar in both spans."""
        self.boundary = boundary
        self.cap = (date.fromisoformat(boundary[:10]) - timedelta(days=1)).isoformat() if boundary else None
        self.phase = "discovery" if boundary else "off"

    def confirm(self) -> None:
        if self.boundary:
            self.phase = "confirm"

    def end(self) -> None:
        self.boundary, self.cap, self.phase = None, None, "off"

    @property
    def active(self) -> bool:
        return self.phase != "off"

    def window(self, start: str | None, end: str | None):
        """(start, end) to actually run, or HoldoutLeak."""
        b = self.boundary
        if self.phase == "discovery":
            if start and str(start)[:10] >= b:
                raise HoldoutLeak(f"discovery window starts at {start}, inside the holdout (>= {b})")
            if end and str(end)[:10] > self.cap:
                raise HoldoutLeak(f"discovery window ends at {end}, past the last discovery day {self.cap} "
                                  f"(holdout starts {b})")
            return start, (end or self.cap)
        if self.phase == "confirm" and (not start or str(start)[:10] < b):
            raise HoldoutLeak(f"confirm window starts at {start}, before the holdout boundary {b}")
        return start, end

    def harness_args(self) -> list[str]:
        """Extra argv for a full-history harness call made during discovery (emit / census)."""
        return ["--end", self.cap] if self.phase == "discovery" else []

    def clip_fold(self, fs: str, fe: str):
        """A walk-forward fold during discovery: None = wholly held back, else the clipped fold."""
        if self.phase != "discovery":
            return fs, fe
        if fs[:10] >= self.boundary:
            return None
        return fs, (self.cap if fe[:10] > self.cap else fe)


def confirm_cells(selected: list[dict[str, Any]], run_window: Callable[[list | None, str], dict],
                  beats: Callable[[dict, dict], bool], boundary: str, floor: int) -> dict[str, Any]:
    """Grade each selected cell ONCE on the holdout. `selected` = [{"cell": tag, "args": argv}];
    `run_window(args_or_None, start)` runs the base (None) or a cell from `start` to the end."""
    base = run_window(None, boundary)
    n = base.get("total_trades")
    rows = []
    for s in selected:
        if "error" in base:
            rows.append({"cell": s["cell"], "holdout_verdict": "error", "why": base.get("error")})
            continue
        c = run_window(s["args"], boundary)
        if "error" in c:
            rows.append({"cell": s["cell"], "holdout_verdict": "error", "why": c.get("error")})
            continue
        if not isinstance(n, (int, float)) or n < floor:
            v = "holdout_underpowered"
        else:
            v = "holdout_pass" if beats(c, base) else "holdout_fail"
        rows.append({"cell": s["cell"], "holdout_verdict": v,
                     "d_net_r": _delta(c, base, "net_total_r"), "d_max_dd": _delta(c, base, "max_drawdown_r")})
    return {"base_trades": n, "base_net_r": base.get("net_total_r"), "cells": rows}


def _delta(c: dict, b: dict, k: str):
    try:
        return round(float(c[k]) - float(b[k]), 4)
    except (KeyError, TypeError, ValueError):
        return None


def leg_confirmation(selected_n: int, cells: list[dict[str, Any]]) -> str:
    """One word for the leg. A pass on ANY selected cell confirms that cell; the denominator rides
    beside it (`selected_from`), never folded in."""
    if selected_n == 0:
        return "no_discovery"
    verdicts = [c.get("holdout_verdict") for c in cells]
    if "holdout_pass" in verdicts:
        return "confirmed"
    if verdicts and all(v == "holdout_underpowered" for v in verdicts):
        return "underpowered"
    if "holdout_fail" in verdicts:
        return "not_replicated"
    return "error"

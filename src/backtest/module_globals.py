"""Restore a research harness's module-level knobs after an entry point has applied them.

Several `scripts/backtest_*.py` harnesses apply their cost stack in `main()` by ASSIGNING module globals (FEE_BPS_ROUNDTRIP,
SLIPPAGE_BPS_ROUNDTRIP, FUNDING_BPS_PER_WINDOW, ...) that the engine reads while it runs. Nothing put them back, so an
in-process caller (a test, a driver) leaked one run's cost stack into the next: PR #27149 measured net_total_r -14.7793 -> -17.1766
on identical trades. `restores_globals(*names)` snapshots those names from the decorated function's own module and puts them back in
`finally`, so a CLI run is unchanged (the process exits) and an in-process run is hermetic. Research-only: nothing the trader loads
imports this module."""
from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def restores_globals(*names: str) -> Callable[[F], F]:
    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*a: Any, **k: Any) -> Any:
            g = fn.__globals__
            saved = {n: g[n] for n in names}      # KeyError here = a misnamed knob, caught by the tests, never silent
            try:
                return fn(*a, **k)
            finally:
                g.update(saved)
        wrapper.__restored_globals__ = names      # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]
    return deco

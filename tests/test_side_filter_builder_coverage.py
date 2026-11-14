"""Every rostered leg that declares a directional gate in config/strategies.yaml must have a builder that ENFORCES it.

Why (2026-11-14, TLT-1H-PROMOTE): tlt_pullback_1h_signal_builder never read ``side_filter``, so the operator-approved
long-only real-money config would have been INERT -- live would still have sent shorts. Nothing caught it: a YAML key a
builder ignores is silent. This sweep makes an inert directional key fail CI (manager ask, 2026-11-14 16:57Z).

A builder enforces the gate when its source calls ``_resolve_side_filter`` or one of the builders that do (the shared
gate: ``_side_filter_suppresses`` on the resolved value), or -- for a LONG gate only -- hard-codes the long-only short
suppression (``pkg["direction"] != "long"``, the ETF trend_long builders). A hard-coded long builder cannot honour
``side_filter: short``, so a ``short`` key there fails.

Population: legs in config/strategies.yaml that sit on at least one config/accounts.yaml roster and declare
``side_filter: long|short`` or ``long_only: true``. Offline: source inspection only, no candles, no network.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import yaml

import src.runtime.strategy_signal_builders as ssb
from src.runtime.intent_multiplexer import _resolve_builders

REPO = Path(__file__).resolve().parents[1]
_HARDCODED_LONG = 'pkg["direction"] != "long"'


def _gate_functions() -> set:
    return {n for n, f in inspect.getmembers(ssb, inspect.isfunction)
            if n != "_resolve_side_filter" and "_resolve_side_filter(" in inspect.getsource(f)}


def enforces(fn, wanted: str, gaters: set) -> bool:
    """True when ``fn`` enforces ``wanted`` ('long' | 'short')."""
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return False
    if "_resolve_side_filter(" in src or any(f"{g}(" in src for g in gaters):
        return True
    return wanted == "long" and _HARDCODED_LONG in src


def _declared(cfg: dict):
    sf = cfg.get("side_filter")
    if isinstance(sf, str) and sf.strip().lower() in ("long", "short"):
        return sf.strip().lower()
    if cfg.get("long_only") is True:
        return "long"
    return None


def test_every_rostered_directional_leg_has_a_builder_that_enforces_it():
    strategies = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]
    accounts = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())["accounts"]
    rostered = {s for a in accounts.values() if isinstance(a, dict) for s in (a.get("strategies") or [])}
    builders = _resolve_builders()
    gaters = _gate_functions()
    checked, inert = [], []
    for name, cfg in strategies.items():
        if not isinstance(cfg, dict) or name not in rostered:
            continue
        wanted = _declared(cfg)
        if wanted is None:
            continue
        fn = builders.get(name)
        if fn is None:
            continue  # no in-process builder (e.g. the pairs sleeve); nothing here can read a key
        checked.append(name)
        if not enforces(fn, wanted, gaters):
            inert.append(f"{name}: declares {wanted} but {getattr(fn, '__name__', fn)} never reads side_filter")
    assert checked, "the sweep found no directional leg at all -- the probe itself is broken"
    assert not inert, "INERT directional gate(s):\n  " + "\n  ".join(inert)


def test_the_sweep_catches_a_builder_that_ignores_the_key():
    """Positive control: a builder that never reads side_filter must be flagged, for either direction."""
    gaters = _gate_functions()

    def ignores_it(settings):  # noqa: ARG001
        pkg = {"direction": "short"}
        return {"side": "sell" if pkg["direction"] == "short" else "buy"}

    def hard_long(settings):  # noqa: ARG001
        pkg = {"direction": "short"}
        if pkg["direction"] != "long":
            return {"side": "none"}
        return {"side": "buy"}

    def reads_it(settings):  # noqa: ARG001
        return ssb._resolve_side_filter({})

    assert not enforces(ignores_it, "long", gaters)
    assert not enforces(ignores_it, "short", gaters)
    assert enforces(hard_long, "long", gaters)
    assert not enforces(hard_long, "short", gaters)       # a hard-coded long builder cannot honour `short`
    assert enforces(reads_it, "short", gaters)
    assert {"_htf_pullback_variant_builder", "_trend_donchian_variant_builder"} <= gaters

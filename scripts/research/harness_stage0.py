#!/usr/bin/env python3
# wiring: research/queue/RQ-20261018-ef5d-03..09 (programme 07 TIMEFRAMES), run.command via research-script-run.yml
"""Stage-0 for a SYNTHETIC leg: a harness family at FIXED params on symbols and a timeframe that exist on
no roster, graded with calendar folds, breadth across symbols and Holm across cells, writing verdict.json.

WHY THIS EXISTS (programme 07 TIMEFRAMES, lane FRONTIER-TIMEFRAMES-1018; row IR-CRYPTO-DAILY-TREND's FIRST
STEP: "a scripts/research wrapper running backtest_trend.py --timeframe 1d --resample 1D ... writing
verdict.json"). `exit_lever_ablation.py` grades a LEG -- a `config/strategies.yaml` key -- so a horizon
or symbol nobody has configured cannot be measured by it, and a bare `scripts/backtest_*.py` command on
the runner writes no verdict.json, so it lands `producer_failed` (script_run.py). This fills that gap
with the SAME machinery: the argv is built by `regime_debt_matrix.build_harness_cmd` from a cfg dict (what
the evidence builder and the ablation run), the cost stack is the harness's own venue-aware fee +
slippage + funding (`execution_costs.resolve_cost_policy`, never a zero default), and the folds are the
ablation's calendar folds. Nothing here is a new harness.

WHAT A RUN IS
  family     trend | pullback | squeeze | fade  (the four cost-complete `scripts/backtest_*.py` harnesses
             `regime_debt_matrix.classify` routes; ict_scalp/fvg_range take no --resample and are excluded;
             backtest_orb.py and src/backtest/backtester.py lack the cost stack -- CLAUDE.md D1 -- and are
             refused here by construction)
  symbols    one CELL per symbol (and per arm): e.g. the six Bybit perps the books trade
  timeframe  the bar the strategy decides on; the candles are fetched at --fetch-bar (default: the same
             bar; `1w` fetches 1d and resamples) and the harness resamples with the right-labelled,
             right-closed rule every harness uses
  arms       `--arm LABEL=tok;tok` as exit_lever_ablation.py (key=value sets a cfg key; --flag=value is a
             raw harness flag). Default: one arm `B=` = the family's declared base params + --param.
             EVERY arm is fixed BEFORE the run; the unit lists them. A best-of-k arm result is a LEAD
             (programme 03 rung S0-C), never a finding -- the unit's rule says what follows.

GRADES (pure; thresholds are the UNIT's, passed as flags)
  cell       pass iff n >= --n-floor AND net_r > 0 AND >= --fold-majority of --folds calendar folds net > 0;
             fail iff n >= --n-floor and not; indeterminate iff n < --n-floor. One-sided Student-t p on
             net_r/trade is reported and Holm-corrected across the arm's measured cells
             (`holm_survivors`, alpha --holm-alpha) -- REPORTED, it gates nothing unless the unit says so.
  pooled     the arm's trades across all its measured cells, on ONE set of calendar edges spanning the
             union of the cells' windows: same rule with --pooled-n-floor; max drawdown is recomputed on
             the exit-time-ordered pooled net_r sequence (labelled `sequential`, not a per-cell harness DD).
  arm        pass iff pooled pass AND cells_pass >= ceil(--breadth-frac x measured cells)  (breadth: the
             pooled edge is not one symbol's); indeterminate iff pooled n < --pooled-n-floor OR fewer than
             half the declared cells measured (a harness/fetch fault is RECORDED per cell, never dropped);
             fail otherwise.
  verdict    pass iff any arm passes (best = highest pooled net_r, named); indeterminate iff no arm passes
             and any arm is indeterminate; fail iff every arm fails.

Reported per cell and pooled, never graded: net_r_per_capital_day (the programme's headline measure),
mean_bars_held and hold_days (how long the money is out), by_outcome, the cost stack the harness charged.

Tier-1 research tooling: fetches public candles (Binance Vision for *USDT, PROXY for Bybit linear; Yahoo via
yfinance for equities/ETFs/futures proxies), runs the repo harnesses, writes only under --out. No live
path, no config write, no roster. A `pass` is an input to a re-entry case under MD-PROMOTE-S0-S1 built as
a new evidence record -- it is not itself a record and not a roster act.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]

FAMILIES: dict[str, dict[str, Any]] = {
    # The structural keys `regime_debt_matrix.classify` routes on come first; the rest are the harness
    # defaults spelled out so a cell's params are in its record, not implied.
    "trend": {"model": "trend_donchian", "donchian": 20, "atr_period": 14, "atr_stop_mult": 2.5, "trail_mult": 3.0},
    "pullback": {"model": "htf_pullback_trend", "trend_lookback": 40, "pullback_lookback": 10, "pullback_frac": 0.5,
                 "atr_period": 14, "atr_stop_mult": 2.5, "trail_mult": 5.0},
    "squeeze": {"model": "squeeze_breakout", "bb_period": 20, "bb_std": 2.0, "kc_mult": 1.5, "atr_period": 14,
                "atr_stop_mult": 2.5, "trail_mult": 3.5},
    "fade": {"model": "fade_breakout", "donchian": 20, "pierce_min": 0.0, "atr_period": 14, "atr_stop_buffer": 0.5,
             "trail_mult": 3.0},
}
#: Bybit-style interval codes the fetcher speaks, per bar; `1w` is fetched DAILY and resampled (the harness
#: and the fetcher both label right/closed right, so a 1W resample of 1d bars is the venue's weekly bar).
BINANCE_CODE = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "1d": "D"}
YAHOO_CODE = {"5m": "5", "15m": "15", "1h": "60", "1d": "D"}
RESAMPLE_RULE = {"1d": "1D", "1w": "1W"}
TF_HOURS = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "30m": 0.5, "1h": 1.0, "2h": 2.0, "4h": 4.0, "1d": 24.0, "1w": 168.0}


def _warn(msg: str) -> None:
    print(f"[harness_stage0] {msg}", file=sys.stderr)


# ---- fetch ---------------------------------------------------------------------------------
def fetch_bar_for(timeframe: str, symbol: str) -> str:
    """The bar to FETCH for `timeframe`: native where a lane serves it, else the finest lane bar below it."""
    crypto = symbol.upper().endswith("USDT")
    table = BINANCE_CODE if crypto else YAHOO_CODE
    if timeframe in table:
        return timeframe
    if timeframe == "1w":
        return "1d"
    if not crypto and timeframe in ("30m", "2h", "4h"):
        return "1h" if timeframe in ("2h", "4h") else "15m"
    raise ValueError(f"{symbol}: no candle lane for timeframe {timeframe!r}")


def fetch_csv(symbol: str, bar: str, *, days: int, data_dir: Path, non_crypto_source: str) -> Path:
    fetcher = REPO / "scripts/ops/fetch_backtest_candles.py"
    crypto = symbol.upper().endswith("USDT")
    code = BINANCE_CODE[bar] if crypto else YAHOO_CODE[bar]
    src = "binance_vision" if crypto else non_crypto_source
    out = data_dir / f"{symbol}_{code}.csv"
    if not out.exists():
        subprocess.run([sys.executable, str(fetcher), "--symbol", symbol, "--interval", code, "--days", str(days),
                        "--output", str(out), "--source", src], check=True, cwd=str(REPO))
    return out


# ---- argv ----------------------------------------------------------------------------------
def build_cfg(family: str, symbol: str, timeframe: str, params: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(FAMILIES[family])
    cfg.update({"symbols": [symbol], "timeframe": timeframe})
    cfg.update(params)
    return cfg


def build_argv(name: str, cfg: dict[str, Any], csv: str, timeframe: str, emit: str, jout: str,
               extra: list[str], start: str | None, end: str | None) -> list[str]:
    import regime_debt_matrix as rdm
    from exit_lever_ablation import _replace_opt
    harness = rdm.classify(cfg)
    if harness not in FAMILIES:
        raise ValueError(f"{name}: cfg classifies as {harness!r}; this wrapper runs {sorted(FAMILIES)}")
    rule = RESAMPLE_RULE.get(timeframe, timeframe)
    argv, _faithful, _omitted = rdm.build_harness_cmd(name, cfg, harness, csv, rule, emit, jout)
    argv = _replace_opt(list(argv), "--timeframe", timeframe)
    i = 0
    while i < len(extra):
        flag = extra[i]
        if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
            argv = _replace_opt(argv, flag, extra[i + 1])
            i += 2
        else:
            if flag not in argv:
                argv.append(flag)
            i += 1
    if start:
        argv += ["--start", start]
    if end:
        argv += ["--end", end]
    return argv


# ---- grading (pure) ------------------------------------------------------------------------
def grade_cell(n: int, net_r: float, folds_pos: int, *, n_floor: int, fold_majority: int) -> str:
    if n < n_floor:
        return "indeterminate"
    return "pass" if (net_r > 0.0 and folds_pos >= fold_majority) else "fail"


def holm(pvals: dict[str, float | None], alpha: float) -> list[str]:
    """Holm step-down: the cells whose one-sided p survives alpha across the arm."""
    items = sorted((p, k) for k, p in pvals.items() if p is not None and not math.isnan(p))
    m = len(items)
    out: list[str] = []
    for i, (p, k) in enumerate(items):
        if p <= alpha / (m - i):
            out.append(k)
        else:
            break
    return out


def sequential_max_drawdown(trades: list[dict[str, Any]]) -> float:
    """Max drawdown in R of the cumulative net_r sequence ordered by exit time (pooled cells)."""
    seq = sorted(trades, key=lambda t: str(t.get("exit_time") or t.get("entry_time")))
    peak = cum = 0.0
    dd = 0.0
    for t in seq:
        cum += float(t.get("net_r") or 0.0)
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return round(dd, 4)


def grade_arm(cells: dict[str, dict[str, Any]], pooled: dict[str, Any] | None, *, declared: int, breadth_frac: float,
              pooled_n_floor: int, fold_majority: int, min_powered_cells: int = 2,
              baseline_pooled: dict[str, Any] | None = None, delta_r_per_trade: float = 0.0) -> dict[str, Any]:
    """The arm verdict. Breadth is counted over POWERED cells (n >= the cell floor): a thin cell says nothing
    either way, so it neither passes nor counts against. `baseline_pooled` (when the arm is a CANDIDATE against a
    declared baseline arm) adds the materiality clause net_r/trade(C) - net_r/trade(B) >= delta_r_per_trade."""
    measured = {k: c for k, c in cells.items() if c.get("state") == "measured"}
    if declared and len(measured) * 2 < declared:
        return {"verdict": "indeterminate", "why": f"{len(measured)} of {declared} cells measured (< half)"}
    if pooled is None or pooled["n"] < pooled_n_floor:
        return {"verdict": "indeterminate",
                "why": f"pooled n {pooled['n'] if pooled else 0} < floor {pooled_n_floor}: underpowered, never FAIL on thin n"}
    powered = {k: c for k, c in measured.items() if c.get("grade") != "indeterminate"}
    if len(powered) < min_powered_cells:
        return {"verdict": "indeterminate", "powered_cells": len(powered),
                "why": f"only {len(powered)} powered cell(s) (< {min_powered_cells}): breadth cannot be read"}
    cells_pass = sum(1 for c in powered.values() if c.get("grade") == "pass")
    need = math.ceil(breadth_frac * len(powered))
    pooled_pass = pooled["net_r"] > 0.0 and pooled["folds_pos"] >= fold_majority
    delta = None
    if baseline_pooled is not None:
        delta = round(pooled["net_r_per_trade"] - baseline_pooled["net_r_per_trade"], 4)
        if delta < delta_r_per_trade:
            return {"verdict": "fail", "cells_pass": cells_pass, "need": need, "delta_r_per_trade_vs_baseline": delta,
                    "why": f"net_r/trade {pooled['net_r_per_trade']} beats the baseline's {baseline_pooled['net_r_per_trade']} "
                           f"by {delta} < the {delta_r_per_trade} materiality bar"}
    if pooled_pass and cells_pass >= need:
        return {"verdict": "pass", "cells_pass": cells_pass, "need": need, "delta_r_per_trade_vs_baseline": delta,
                "why": f"pooled net_r {pooled['net_r']} > 0 with {pooled['folds_pos']} folds positive and "
                       f"{cells_pass} of {len(powered)} powered cells pass (breadth floor {need})"
                       + (f"; beats the baseline by {delta} R/trade" if delta is not None else "")}
    return {"verdict": "fail", "cells_pass": cells_pass, "need": need, "delta_r_per_trade_vs_baseline": delta,
            "why": ("pooled net_r <= 0 or folds short" if not pooled_pass
                    else f"pooled passes but only {cells_pass} of {len(powered)} powered cells pass (< {need}): one symbol's edge")}


# ---- run -----------------------------------------------------------------------------------
def run_cell(name: str, cfg: dict[str, Any], csv: Path, timeframe: str, extra: list[str], start: str | None,
             end: str | None, work: Path, *, folds: int, timeout_s: int) -> dict[str, Any]:
    import exit_lever_ablation as ela
    ela.N_FOLDS = folds
    emit, jout = work / f"{name}__trades.jsonl", work / f"{name}__bt.json"
    argv = build_argv(name, cfg, str(csv), timeframe, str(emit), str(jout), extra, start, end)
    log = work / f"{name}.log"
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO), timeout=timeout_s,
                            check=False).returncode   # a non-zero exit is a recorded cell state, not an exception
    if rc != 0 or not jout.is_file():
        return {"state": "harness_failed", "why": f"exit {rc}; log {log.name}", "argv": argv[1:]}
    if not emit.is_file():
        emit.write_text("", encoding="utf-8")       # zero trades: a real measurement of an empty sample
    edges = ela.fold_edges(str(csv), start, end)
    s = ela.summarize_arm(str(jout), str(emit), edges)
    trades = ela._load_trades(str(emit))
    return {"state": "measured", "argv": argv[1:], "summary": s, "trades": trades, "edges": edges}


def run(a: argparse.Namespace) -> dict[str, Any]:
    import exit_lever_ablation as ela
    import yaml
    from exit_lever_ablation import parse_arm
    from short_tf_discovery_sweep import mean_test
    params: dict[str, Any] = {}
    for kv in a.param or []:
        k, _, v = kv.partition("=")
        params[k.strip()] = yaml.safe_load(v)
    arm_specs = [parse_arm(s) for s in (a.arm or ["B="])]
    symbols = [s for s in a.symbols.split(",") if s]
    tf_hours = TF_HOURS.get(a.timeframe)
    data_dir = Path(a.data_dir) if a.data_dir else Path(tempfile.mkdtemp(prefix="stage0_"))
    data_dir.mkdir(parents=True, exist_ok=True)
    work = Path(a.out) / "cells"
    work.mkdir(parents=True, exist_ok=True)
    given = dict(kv.split("=", 1) for kv in (a.data_csv or []))
    csvs: dict[str, Path | None] = {}
    fetch_why: dict[str, str] = {}
    inputs: list[str] = []
    for sym in symbols:
        try:
            if sym in given:
                csvs[sym] = Path(given[sym])
            elif a.no_fetch:
                raise FileNotFoundError("--no-fetch and no --data-csv")
            else:
                bar = a.fetch_bar or fetch_bar_for(a.timeframe, sym)
                csvs[sym] = fetch_csv(sym, bar, days=a.days, data_dir=data_dir, non_crypto_source=a.non_crypto_source)
            try:
                inputs.append(str(csvs[sym].resolve().relative_to(REPO.resolve())))  # type: ignore[union-attr]
            except ValueError:
                pass
        except Exception as exc:  # allow-silent: the fetch failure is RECORDED on every cell of that symbol below (state fetch_failed), never dropped  # noqa: BLE001
            csvs[sym] = None
            fetch_why[sym] = f"{type(exc).__name__}: {exc}"
            _warn(f"{sym}: fetch failed: {fetch_why[sym]}")
    arms_out: dict[str, Any] = {}
    for label, sets, unsets, extra in arm_specs:
        cells: dict[str, Any] = {}
        pooled_trades: list[dict[str, Any]] = []
        spans: list[Any] = []
        for sym in symbols:
            name = f"{a.family}_{sym}_{a.timeframe}_{label}"
            cfg = build_cfg(a.family, sym, a.timeframe, params)
            for k in unsets:
                cfg.pop(k, None)
            cfg.update(sets)
            if csvs.get(sym) is None:
                cells[sym] = {"state": "fetch_failed", "why": fetch_why.get(sym, "no candles")}
                continue
            try:
                r = run_cell(name, cfg, csvs[sym], a.timeframe, list(extra), a.start, a.end, work,  # type: ignore[arg-type]
                             folds=a.folds, timeout_s=a.cell_timeout_s)
            except Exception as exc:  # allow-silent: a crashed cell lands as state harness_failed with the exception text; the denominator stays whole  # noqa: BLE001
                r = {"state": "harness_failed", "why": f"{type(exc).__name__}: {exc}"}
            if r["state"] != "measured":
                cells[sym] = {k: v for k, v in r.items() if k != "trades"}
                continue
            s = r["summary"]
            rs = [float(t.get("net_r") or 0.0) for t in r["trades"]]
            folds_pos = sum(1 for f in s["folds"] if f["net_r"] > 0)
            mt = mean_test(rs)
            cells[sym] = {
                "state": "measured", "n": s["n"], "net_r": s["net_r"], "max_drawdown_r": s["max_drawdown_r"],
                "folds": s["folds"], "folds_pos": folds_pos,
                "net_r_per_capital_day": s.get("net_r_per_capital_day"), "mean_bars_held": s.get("mean_bars_held"),
                "hold_days_mean": (round(s["mean_bars_held"] * tf_hours / 24.0, 3)
                                   if s.get("mean_bars_held") is not None and tf_hours else None),
                "net_r_per_trade": round(s["net_r"] / s["n"], 4) if s["n"] else None,
                "t_one_sided_p": mt.get("p"), "by_outcome": s.get("by_outcome"), "cost_stack": s.get("cost_stack"),
                "params": s.get("params"), "data_start": s.get("data_start"), "data_end": s.get("data_end"),
                "grade": grade_cell(s["n"], s["net_r"], folds_pos, n_floor=a.n_floor, fold_majority=a.fold_majority),
                "argv": r["argv"],
            }
            pooled_trades.extend(r["trades"])
            spans += [r["edges"][0], r["edges"][-1]]
        pooled = None
        if pooled_trades and spans:
            ela.N_FOLDS = a.folds
            lo, hi = min(spans), max(spans)
            step = (hi - lo) / a.folds
            edges = [lo + step * i for i in range(a.folds)] + [hi]
            folds = ela.fold_net_r(pooled_trades, edges)
            net = round(sum(float(t.get("net_r") or 0.0) for t in pooled_trades), 4)
            mt = mean_test([float(t.get("net_r") or 0.0) for t in pooled_trades])
            pooled = {"n": len(pooled_trades), "net_r": net, "folds": folds,
                      "folds_pos": sum(1 for f in folds if f["net_r"] > 0),
                      "max_drawdown_r_sequential": sequential_max_drawdown(pooled_trades),
                      "net_r_per_trade": round(net / len(pooled_trades), 4), "t_one_sided_p": mt.get("p"),
                      "window": [str(lo), str(hi)]}
        arms_out[label] = {"sets": sets, "unsets": unsets, "extra_flags": extra, "cells": cells, "pooled": pooled}
    base_pooled = arms_out[a.baseline]["pooled"] if a.baseline else None
    if a.baseline and a.baseline not in arms_out:
        raise SystemExit(f"--baseline {a.baseline!r} is not one of the arms {sorted(arms_out)}")
    for label, arm in arms_out.items():
        is_cand = bool(a.baseline) and label != a.baseline
        g = grade_arm(arm["cells"], arm["pooled"], declared=len(symbols), breadth_frac=a.breadth_frac,
                      pooled_n_floor=a.pooled_n_floor, fold_majority=a.fold_majority,
                      min_powered_cells=a.min_powered_cells,
                      baseline_pooled=base_pooled if (is_cand and base_pooled) else None,
                      delta_r_per_trade=a.delta_r_per_trade)
        if is_cand and base_pooled is None and g["verdict"] == "pass":
            g = {"verdict": "indeterminate", "why": f"candidate passes but the baseline arm {a.baseline} has no pooled trades to compare against"}
        g["role"] = "baseline" if (a.baseline and label == a.baseline) else ("candidate" if a.baseline else "arm")
        g["holm_survivors"] = holm({k: c.get("t_one_sided_p") for k, c in arm["cells"].items() if c.get("state") == "measured"},
                                   a.holm_alpha)
        arm["grade"] = g
    # verdict across arms: with a baseline declared, only CANDIDATE arms can carry the verdict
    judged = {k: v for k, v in arms_out.items() if v["grade"]["role"] != "baseline"}
    passing = {k: v for k, v in judged.items() if v["grade"]["verdict"] == "pass"}
    if passing:
        best = max(passing, key=lambda k: passing[k]["pooled"]["net_r"])
        verdict, why = "pass", f"arm {best} passes (pooled net_r {passing[best]['pooled']['net_r']}); {len(passing)} of {len(arms_out)} arms pass"
    elif any(v["grade"]["verdict"] == "indeterminate" for v in judged.values()):
        best = None
        verdict, why = "indeterminate", "; ".join(f"{k}: {v['grade']['why']}" for k, v in arms_out.items())
    else:
        best = None
        verdict, why = "fail", "; ".join(f"{k}: {v['grade']['why']}" for k, v in arms_out.items())
    measured_cells = sum(1 for v in arms_out.values() for c in v["cells"].values() if c.get("state") == "measured")
    n_total = sum(v["pooled"]["n"] for v in arms_out.values() if v["pooled"])
    any_measured = measured_cells > 0
    out = {
        "verdict": verdict if any_measured else "not_applicable",
        "read_state": "measured" if any_measured else "producer_failed",
        "population": (f"family={a.family} timeframe={a.timeframe} symbols={','.join(symbols)} arms={list(arms_out)} "
                       f"window={a.start or 'data_start'}..{a.end or 'data_end'} days={a.days}; "
                       f"{measured_cells} of {len(symbols) * len(arms_out)} cells measured; trades net of fee+slippage+funding"),
        "n": n_total if any_measured else None,
        "note": (f"{verdict.upper()}: {why}. Thresholds: n_floor {a.n_floor}, pooled_n_floor {a.pooled_n_floor}, folds "
                 f"{a.folds} majority {a.fold_majority}, breadth {a.breadth_frac} over >= {a.min_powered_cells} powered cells, "
                 f"holm alpha {a.holm_alpha}"
                 + (f", baseline {a.baseline} with materiality {a.delta_r_per_trade} R/trade" if a.baseline else "") + ". "
                 "Crypto candles are Binance USD-M (PROXY for Bybit linear); the cost stack is the harness's venue-aware "
                 "fee + slippage + funding. A pass is an input to a re-entry case, never a roster act."
                 if any_measured else f"producer_failed: no cell measured ({why})"),
        "decision_rule_id": a.rule_id,
        "data_inputs": sorted(set(inputs)),
        "measurement": {"family": a.family, "timeframe": a.timeframe, "params": params, "best_arm": best,
                        "thresholds": {"n_floor": a.n_floor, "pooled_n_floor": a.pooled_n_floor, "folds": a.folds,
                                       "fold_majority": a.fold_majority, "breadth_frac": a.breadth_frac,
                                       "min_powered_cells": a.min_powered_cells, "holm_alpha": a.holm_alpha,
                                       "baseline": a.baseline, "delta_r_per_trade": a.delta_r_per_trade},
                        "arms": arms_out},
    }
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "verdict.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    _write_summary(Path(a.out) / "SUMMARY.md", out)
    return out


def _write_summary(path: Path, v: dict[str, Any]) -> None:
    m = v["measurement"]
    lines = [f"# Stage-0 (synthetic leg) -- {m['family']} {m['timeframe']} -- {v['verdict']}", "", v["note"], ""]
    for label, arm in m["arms"].items():
        lines += [f"## arm `{label}` ({arm['grade'].get('role')}) -- {arm['grade']['verdict']} -- {arm['grade']['why']}", "",
                  "| cell | n | net R | R/trade | folds+ | maxDD R | R/cap-day | hold d | p (1-sided) | grade |",
                  "|---|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
        for sym, c in arm["cells"].items():
            if c.get("state") != "measured":
                lines.append(f"| {sym} | - | - | - | - | - | - | - | - | {c.get('state')}: {c.get('why')} |")
                continue
            lines.append(f"| {sym} | {c['n']} | {c['net_r']} | {c['net_r_per_trade']} | {c['folds_pos']}/{len(c['folds'])} | "
                         f"{c['max_drawdown_r']} | {c.get('net_r_per_capital_day')} | {c.get('hold_days_mean')} | "
                         f"{c.get('t_one_sided_p')} | {c['grade']} |")
        p = arm["pooled"]
        if p:
            lines.append(f"| **pooled** | {p['n']} | {p['net_r']} | {p['net_r_per_trade']} | {p['folds_pos']}/{len(p['folds'])} | "
                         f"{p['max_drawdown_r_sequential']} (seq) | - | - | {p.get('t_one_sided_p')} | - |")
        lines += ["", f"Holm survivors (alpha {m['thresholds']['holm_alpha']}): {arm['grade'].get('holm_survivors')}", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- self-test -----------------------------------------------------------------------------
def _self_test() -> int:
    # pure grading
    assert grade_cell(10, 5.0, 4, n_floor=39, fold_majority=4) == "indeterminate"
    assert grade_cell(40, 5.0, 4, n_floor=39, fold_majority=4) == "pass"
    assert grade_cell(40, 5.0, 3, n_floor=39, fold_majority=4) == "fail"
    assert grade_cell(40, -1.0, 6, n_floor=39, fold_majority=4) == "fail"
    assert holm({"a": 0.001, "b": 0.03, "c": 0.5}, 0.05) == ["a"]             # 0.001 <= 0.05/3; 0.03 > 0.05/2 -> stop
    assert holm({"a": 0.001, "b": 0.02, "c": 0.5}, 0.05) == ["a", "b"]        # 0.02 <= 0.05/2; 0.5 > 0.05
    assert holm({}, 0.05) == [] and holm({"a": None}, 0.05) == []
    assert sequential_max_drawdown([{"net_r": 1, "exit_time": "2026-01-01"}, {"net_r": -2, "exit_time": "2026-01-02"},
                                    {"net_r": 3, "exit_time": "2026-01-03"}]) == 2.0
    ok = {"state": "measured", "grade": "pass"}
    bad = {"state": "measured", "grade": "fail"}
    pooled_ok = {"n": 50, "net_r": 4.0, "folds_pos": 4}
    g = grade_arm({"A": ok, "B": ok, "C": bad}, pooled_ok, declared=3, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "pass", g
    g = grade_arm({"A": ok, "B": bad, "C": bad}, pooled_ok, declared=3, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "fail" and "one symbol" in g["why"], g
    g = grade_arm({"A": ok}, {"n": 20, "net_r": 4.0, "folds_pos": 4}, declared=1, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "indeterminate", g
    g = grade_arm({"A": ok, "B": {"state": "harness_failed"}, "C": {"state": "fetch_failed"}}, pooled_ok, declared=3,
                  breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "indeterminate" and "< half" in g["why"], g
    g = grade_arm({"A": ok, "B": ok}, {"n": 50, "net_r": -1.0, "folds_pos": 4}, declared=2, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "fail", g
    thin = {"state": "measured", "grade": "indeterminate"}
    # thin cells count neither for nor against breadth; fewer than 2 powered cells cannot read breadth
    g = grade_arm({"A": ok, "B": ok, "C": thin, "D": thin}, pooled_ok, declared=4, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "pass" and g["need"] == 1, g
    g = grade_arm({"A": ok, "C": thin, "D": thin}, pooled_ok, declared=3, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4)
    assert g["verdict"] == "indeterminate" and "powered" in g["why"], g
    # a candidate must beat the baseline by the materiality bar, whatever its own Stage-0 reads
    cand = {"n": 50, "net_r": 4.0, "folds_pos": 4, "net_r_per_trade": 0.08}
    base = {"n": 60, "net_r": 3.0, "folds_pos": 4, "net_r_per_trade": 0.05}
    assert grade_arm({"A": ok, "B": ok}, cand, declared=2, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4,
                     baseline_pooled=base, delta_r_per_trade=0.05)["verdict"] == "fail"
    assert grade_arm({"A": ok, "B": ok}, cand, declared=2, breadth_frac=0.5, pooled_n_floor=39, fold_majority=4,
                     baseline_pooled=base, delta_r_per_trade=0.02)["verdict"] == "pass"
    # argv: every family classifies to itself and the raw flags/params land
    for fam in FAMILIES:
        cfg = build_cfg(fam, "ETHUSDT", "1d", {})
        import regime_debt_matrix as rdm
        assert rdm.classify(cfg) == fam, (fam, rdm.classify(cfg))
    argv = build_argv("t", build_cfg("trend", "ETHUSDT", "1w", {"donchian": 55}), "x.csv", "1w", "e", "j",
                      ["--vol-skip-below-pctl", "75", "--long-only"], "2020-01-01", None)
    s = " ".join(argv)
    assert "--donchian 55" in s and "--resample 1W" in s and "--timeframe 1w" in s and "--vol-skip-below-pctl 75" in s
    assert "--long-only" in s and "--start 2020-01-01" in s and "--slippage-bps-roundtrip" not in s  # venue default resolves in the harness
    assert fetch_bar_for("1w", "ETHUSDT") == "1d" and fetch_bar_for("4h", "SPY") == "1h" and fetch_bar_for("4h", "ETHUSDT") == "4h"
    try:
        build_argv("t", {"symbols": ["X"], "timeframe": "1h", "range_lookback": 1, "third_frac": 1}, "x", "1h", "e", "j", [], None, None)
        raise AssertionError("fvg_range must be refused")
    except ValueError:
        pass
    # end to end on the repo's smoke fixture (5,001 1m bars -> 15m): the harness runs, the contract is written
    fixture = REPO / "data" / "backtest_candles.csv"
    if fixture.is_file():
        with tempfile.TemporaryDirectory() as td:
            ns = argparse.Namespace(family="trend", symbols="BTCUSDT", timeframe="15m", fetch_bar=None, days=10, start=None,
                                    end=None, param=["donchian=10"], arm=["B=", "T=--timeout-bars=20"], folds=4, fold_majority=3,
                                    n_floor=5, pooled_n_floor=5, breadth_frac=0.5, holm_alpha=0.05, min_powered_cells=1,
                                    baseline="B", delta_r_per_trade=0.0, non_crypto_source="yfinance",
                                    data_csv=[f"BTCUSDT={fixture}"], data_dir=td, no_fetch=True, cell_timeout_s=600,
                                    out=os.path.join(td, "out"), rule_id="RULE-SELFTEST")
            v = run(ns)
            assert v["read_state"] == "measured" and v["verdict"] in ("pass", "fail", "indeterminate"), v["note"]
            arms = v["measurement"]["arms"]
            assert set(arms) == {"B", "T"} and arms["B"]["cells"]["BTCUSDT"]["state"] == "measured", arms["B"]["cells"]
            assert arms["B"]["grade"]["role"] == "baseline" and arms["T"]["grade"]["role"] == "candidate", arms
            assert "--timeout-bars 20" in " ".join(arms["T"]["cells"]["BTCUSDT"]["argv"])
            assert Path(td, "out", "verdict.json").is_file() and Path(td, "out", "SUMMARY.md").is_file()
            # a fetch failure is a recorded cell state and halves the denominator
            ns2 = argparse.Namespace(**{**vars(ns), "symbols": "BTCUSDT,ETHUSDT", "out": os.path.join(td, "out2")})
            v2 = run(ns2)
            assert v2["measurement"]["arms"]["B"]["cells"]["ETHUSDT"]["state"] == "fetch_failed", v2["measurement"]["arms"]["B"]["cells"]
    else:
        _warn("self-test: data/backtest_candles.csv missing; end-to-end leg skipped")
    print("harness_stage0 self-test: ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", choices=sorted(FAMILIES))
    ap.add_argument("--symbols", default=None, help="comma list; one cell per symbol")
    ap.add_argument("--timeframe", default=None, help="the decision bar (1m..1w); the harness resamples to it")
    ap.add_argument("--fetch-bar", default=None, help="bar to fetch (default: native, or 1d for 1w)")
    ap.add_argument("--days", type=int, default=1825, help="trailing days to fetch (the window is pinned by --start/--end)")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--param", action="append", default=None, metavar="KEY=VALUE", help="cfg key for every arm (YAML value)")
    ap.add_argument("--arm", action="append", default=None, metavar="LABEL=tok;tok", help="as exit_lever_ablation.py; default B=")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--fold-majority", type=int, default=4)
    ap.add_argument("--n-floor", type=int, default=39)
    ap.add_argument("--pooled-n-floor", type=int, default=39)
    ap.add_argument("--breadth-frac", type=float, default=0.5)
    ap.add_argument("--holm-alpha", type=float, default=0.05)
    ap.add_argument("--min-powered-cells", type=int, default=2, help="breadth needs at least this many cells at n >= --n-floor")
    ap.add_argument("--baseline", default=None, help="arm label the other arms are CANDIDATES against (materiality clause)")
    ap.add_argument("--delta-r-per-trade", type=float, default=0.0,
                    help="a candidate must beat the baseline's pooled net_r/trade by at least this (R)")
    ap.add_argument("--non-crypto-source", choices=("yfinance", "dukascopy"), default="yfinance")
    ap.add_argument("--data-csv", action="append", default=None, metavar="SYM=PATH", help="use this CSV for a symbol (tests)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--cell-timeout-s", type=int, default=3600)
    ap.add_argument("--rule-id", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    for req in ("family", "symbols", "timeframe", "out"):
        if not getattr(a, req):
            ap.error(f"--{req} is required")
    if a.fold_majority > a.folds:
        ap.error("--fold-majority may not exceed --folds")
    v = run(a)
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

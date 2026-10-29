#!/usr/bin/env python3
# wiring: manual-only - a lane-run research driver (ML-VOLGATE-WF-ETH-BTC, plan docs/plans/ml-live-promotion-plan-2026-10-29.md step B3); it needs trainer-produced vol-label files, so no workflow can run it unattended
"""B3 driver (ML-VOLGATE-WF-ETH-BTC): 2-D (trend, vol) cell walk-forward for ONE strategy x ONE head.

Runs the leg's harness ONCE per (strategy, labels file), tags every trade with its
(trend, vol) cell, then grades all six cells with the SAME fixed-panel verdict
`regime_cell_walkforward.cell_verdict` uses (`FOLD_PANEL = (3, 4, 5)`), and applies the
plan's registered BOOK rule (docs/plans/ml-live-promotion-plan-2026-10-29.md section 3 P2):
gated book (all passing cells together) vs ungated, yearly folds -- net >= ungated in
>= 3 of 4 folds AND pooled maxDD <= ungated.

Registered rules are imported or restated verbatim, never tuned here:
  * cell pass  = `<dir>_stable_drag` and not `<dir>_fold_sensitive`, trades in that direction
                 >= `MIN_DIRECTION_TRADES`, for the direction the cell gates;
  * fidelity   = the harness fidelity flag; an `approximate` leg is REFUSED (plan section 7);
  * cost       = every trade's `net_r` is net of fee + slippage + funding (the harness stamps
                 `cost_*_r`); the run stamps `resolve_run_costs(symbol)` and asserts the stamps.

Research only (Tier 1). Reads public candles (Binance-vision) and a vol-labels JSONL.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import direction_walkforward as dwf  # noqa: E402
import regime_cell_walkforward as rcw  # noqa: E402
import regime_debt_matrix as rdm  # noqa: E402

REPO = rdm.REPO
sys.path.insert(0, REPO)
from src.research.run_costs import resolve_run_costs  # noqa: E402

REGIMES = ("trending", "transitional", "chop")
VOLS = ("calm", "volatile")
BOOK_FOLDS = 4          # registered: "yearly folds, net >= ungated in >= 3 of 4"
BOOK_MIN_FOLDS_OK = 3


def _load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _t(r: dict) -> datetime:
    s = str(r.get("entry_time")).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _x(r: dict) -> datetime:
    s = str(r.get("exit_time") or r.get("entry_time")).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def max_dd(trades: list[dict]) -> float:
    """Max peak-to-trough drawdown (R) of cumulative net_r ordered by exit time."""
    eq = peak = dd = 0.0
    for r in sorted(trades, key=_x):
        eq += float(r["net_r"])
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return round(dd, 4)


def yearly_folds(trades: list[dict], start: datetime) -> tuple[list[float], list[int]]:
    """Net-R and trade count per 365-day fold anchored at ``start`` (last fold absorbs the tail)."""
    out, n = [0.0] * BOOK_FOLDS, [0] * BOOK_FOLDS
    for r in trades:
        k = min(BOOK_FOLDS - 1, int((_t(r) - start).days // 365))
        out[k] += float(r["net_r"])
        n[k] += 1
    return [round(v, 4) for v in out], n


def _write(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")


def run(strategy: str, labels: str, head: str, workdir: str, days: int, cache: str | None,
        labels_end: str | None = None) -> dict:
    cfg = rdm.resolve_strategy(strategy)
    out: dict = {"strategy": strategy, "head": head, "labels": os.path.basename(labels), "days": days}
    if cfg is None:
        out["error"] = "not declared in strategies.yaml"
        return out
    harness = rdm.classify(cfg)
    sym = (cfg.get("symbols") or [None])[0]
    tf = cfg.get("timeframe")
    if harness is None or not sym or not tf:
        out["error"] = "no offline harness for this leg (unclassifiable)"
        out["verdict"] = "REFUSED_NO_HARNESS"
        return out
    out.update({"symbol": sym, "timeframe": tf, "harness": harness})
    feed = rdm.resolve_feed(sym, tf)
    out["feed"] = feed
    os.makedirs(workdir, exist_ok=True)
    csv = os.path.join(workdir, f"{strategy}__data.csv")
    cached = os.path.join(cache, f"{sym}_{feed['interval']}_{days}.csv") if cache else None
    if cached and os.path.exists(cached):
        shutil.copy(cached, csv)
    else:
        rdm._fetch_csv(feed, days, csv)
        if cached:
            os.makedirs(cache, exist_ok=True)
            shutil.copy(csv, cached)
    emit = os.path.join(workdir, f"{strategy}__trades.jsonl")
    jout = os.path.join(workdir, f"{strategy}__bt.json")
    argv, faithful, omitted = rdm.build_harness_cmd(strategy, cfg, harness, csv, feed["resample"], emit, jout)
    unrep = sorted(k for k in cfg if k in rdm._UNREPLAYABLE)
    if unrep:
        faithful = False
        omitted = sorted(set(omitted) | set(unrep))
    out["fidelity"] = "faithful" if faithful else "approximate"
    out["omitted_levers"] = omitted
    subprocess.run(argv, check=True, cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    tagged = os.path.join(workdir, f"{strategy}__tagged.jsonl")
    subprocess.run([sys.executable, os.path.join(REPO, "scripts/research/regime_tag_emitted.py"),
                    "--trades", emit, "--data", csv, "--resample", feed["resample"], "--label", strategy,
                    "--emit-tagged", tagged, "--vol-labels", labels, "--json"],
                   check=True, cwd=REPO, capture_output=True)
    trades = _load_jsonl(tagged)
    # The as-of lookup carries the LAST label forward forever, so a labels file that ends
    # before the candles do would silently label every later trade with a stale state.
    # Trades after the labels' last bar are therefore excluded and counted, never graded.
    out["labels_end"] = labels_end
    if labels_end:
        end = datetime.fromisoformat(labels_end.replace("Z", "+00:00"))
        kept = [r for r in trades if _t(r) <= end]
        out["trades_excluded_after_labels_end"] = len(trades) - len(kept)
        trades = kept
    out["n_trades_all"] = len(trades)
    out["vol_unknown_trades"] = sum(1 for r in trades if r.get("vol_regime") not in VOLS)
    # cost-stack attestation: every trade carries the three terms and the slippage/funding are live.
    keys = ("cost_fee_r", "cost_slippage_r", "cost_funding_r")
    out["cost_stamped_trades"] = sum(1 for r in trades if all(k in r for k in keys))
    out["cost_policy"] = resolve_run_costs(sym)
    out["mean_cost_r"] = {k: round(sum(float(r.get(k) or 0) for r in trades) / max(1, len(trades)), 5) for k in keys}
    out["cost_stack_ok"] = bool(trades) and out["cost_stamped_trades"] == len(trades) \
        and out["mean_cost_r"]["cost_slippage_r"] > 0

    cells: dict = {}
    for reg in REGIMES:
        for vol in VOLS:
            sub = [r for r in trades if r.get("regime") == reg and r.get("vol_regime") == vol]
            slug = f"{reg}/{vol}"
            if not sub:
                cells[slug] = {"trades": 0, "note": "no trades in cell"}
                continue
            p = os.path.join(workdir, f"{strategy}__{reg}_{vol}.jsonl")
            _write(p, sub)
            panel = {k: dwf.analyze([p], k, f"{strategy}:{slug}") for k in rcw.FOLD_PANEL}
            cv = rcw.cell_verdict(panel, reg, vol)
            disp = dwf.analyze([p], 4, f"{strategy}:{slug}")
            cells[slug] = {
                "trades": len(sub), "by_fold_4": disp.get("by_fold"), "pooled": disp.get("pooled"),
                "verdict": {k: cv.get(k) for k in (
                    "long_trades", "short_trades", "pooled_long_r", "pooled_short_r",
                    "long_verdict", "short_verdict", "long_stable_drag", "short_stable_drag",
                    "long_fold_sensitive", "short_fold_sensitive",
                    "long_insufficient_n", "short_insufficient_n", "per_fold_count")},
            }
    out["cells"] = cells

    # --- book rule over the passing (cell, direction) pairs -------------------------
    passing = []
    for slug, c in cells.items():
        v = c.get("verdict") or {}
        for d in ("long", "short"):
            if v.get(f"{d}_stable_drag") and not v.get(f"{d}_fold_sensitive") and not v.get(f"{d}_insufficient_n"):
                passing.append((slug, d))
    out["passing_cell_directions"] = [f"{s}:{d}" for s, d in passing]
    ordered = sorted(trades, key=_t)
    start = _t(ordered[0]) if ordered else None
    if start is not None:
        gated_off = set()
        for slug, d in passing:
            reg, vol = slug.split("/")
            for i, r in enumerate(ordered):
                if r.get("regime") == reg and r.get("vol_regime") == vol \
                        and str(r["direction"]).lower().startswith(d[0]):
                    gated_off.add(i)
        gated = [r for i, r in enumerate(ordered) if i not in gated_off]
        (uf, un), (gf, _gn) = yearly_folds(ordered, start), yearly_folds(gated, start)
        dd_u, dd_g = max_dd(ordered), max_dd(gated)
        # only folds the UNGATED book populates can vote; an empty fold is 0 >= 0 for free
        populated = sum(1 for k in un if k)
        ok_folds = sum(1 for a, b, k in zip(gf, uf, un) if k and a >= b)
        out["book"] = {
            "n_ungated": len(ordered), "n_gated": len(gated), "trades_removed": len(gated_off),
            "ungated_fold_net_r": uf, "ungated_fold_n": un, "gated_fold_net_r": gf,
            "folds_populated": populated, "folds_gated_ge_ungated": ok_folds,
            "ungated_max_dd_r": dd_u, "gated_max_dd_r": dd_g,
            "rule_net": (ok_folds >= BOOK_MIN_FOLDS_OK) if populated >= BOOK_FOLDS else None,  # None = INDETERMINATE
            "rule_maxdd": dd_g <= dd_u,
            "rule1_ungated_all_folds_profitable": all(v > 0 for v in uf),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--workdir", default="/tmp/ml_volgate_b3")
    ap.add_argument("--days", type=int, default=1460)
    ap.add_argument("--cache", default=None, help="dir to cache fetched candle CSVs between strategies")
    ap.add_argument("--labels-end", default=None, help="ISO ts of the labels' last bar; later trades are excluded")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        res = run(a.strategy, a.labels, a.head, os.path.join(a.workdir, a.strategy), a.days, a.cache, a.labels_end)
    except Exception as e:  # noqa: BLE001  # allow-silent: the failure is written into the output record (res["error"]) and printed, never swallowed
        res = {"strategy": a.strategy, "head": a.head, "error": f"{type(e).__name__}: {e}"}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(json.dumps({k: res.get(k) for k in ("strategy", "head", "fidelity", "error", "passing_cell_directions")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

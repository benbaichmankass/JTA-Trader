#!/usr/bin/env python3
# wiring: research/queue units RQ-20261120-htf* (P3-M27-htf-pass disjoint-window confirmation) via research-script-run.yml
"""P3-M27-htf-pass confirmation driver: ict_scalp HTF trend filter ON vs forced OFF on ONE leg and ONE pinned window.

WHY A DRIVER. ``exit_lever_ablation.py`` cannot toggle the HTF filter: an arm's ``htf_trend_filter_enabled=true`` is a
``config/strategies.yaml`` key the harness never forwards to the backtest (PI-20261119-FILLW47B-0013). The original test
(RQ-20260928-001) used the manual-only driver ``rq_20260928_001_htf_wire.py``, which patches the backtest's YAML read, takes a ready
candle CSV and has no window flags and writes no ``verdict.json`` (so a queue unit would land ``producer_failed``). This module
fetches the candles, runs that driver's ``run_arm`` for OFF and ON on a pinned ``--start/--end`` window with the full cost stack,
keeps per-trade emits under ``arms/``, grades the ORIGINAL RQ-20260928-001 rule plus the worst-trade-removed clause, and writes
``verdict.json`` in the ``script_run.py`` contract.

THE RULE (copied verbatim from RULE-RQ0928-001-ICTSCALP-HTF-FILTER-WIRE; thresholds are flags, none is defaulted to a new value)
  INDETERMINATE  if n(OFF) + n(ON) < --min-n (175);
  PASS           if n(OFF) + n(ON) >= --min-n AND net R(ON) > net R(OFF) AND mean R(ON) is not worse than mean R(OFF) by more
                 than --mean-tol (0.3) AND, added by the programme node, net R(ON) > net R(OFF) with EACH arm's single worst
                 trade removed (a PASS carried by one tiny-stop trade is not a finding);
  FAIL           otherwise.
Reported, not gating: net R per fold (``--folds`` equal calendar spans by entry time) and the folds where ON >= OFF.

Changes no config, places no order; writes only under --out.

    python3 scripts/research/htf_filter_confirm.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

#: the strategies.yaml timeframe label -> the fetcher's interval code
_INTERVAL = {"5m": "5", "15m": "15"}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def read_trades(path: Path) -> List[Dict[str, Any]]:
    """The backtest's --emit-trades file (CSV or JSONL) as dicts with entry_time, exit_time, direction, net_r."""
    text = path.read_text(encoding="utf-8")
    rows: List[Dict[str, Any]] = []
    if path.suffix == ".jsonl" or text.lstrip().startswith("{"):
        rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    else:
        rows = list(csv.DictReader(text.splitlines()))
    out = []
    for r in rows:
        out.append(
            {
                "entry_time": str(r["entry_time"]),
                "exit_time": str(r.get("exit_time") or r["entry_time"]),
                "direction": r.get("direction") or r.get("side"),
                "net_r": float(r["net_r"]),
            }
        )
    return out


def _net(rows: Sequence[Dict[str, Any]]) -> float:
    return sum(r["net_r"] for r in rows)


def _ex_worst(rows: Sequence[Dict[str, Any]]) -> float:
    """Net R with the single worst trade (lowest net_r) removed; an empty arm is 0.0."""
    if not rows:
        return 0.0
    return _net(rows) - min(r["net_r"] for r in rows)


def fold_table(
    off: Sequence[Dict[str, Any]], on: Sequence[Dict[str, Any]], n_folds: int
) -> List[Dict[str, Any]]:
    """Equal calendar spans of the pooled entry range, a trade binned by entry_time (same edges for both arms)."""
    both = [_ts(r["entry_time"]) for r in (*off, *on)]
    if not both or n_folds < 1:
        return []
    lo, hi = min(both), max(both)
    step = (hi - lo) / n_folds
    res = [{"fold": i + 1, "off": 0.0, "on": 0.0} for i in range(n_folds)]
    for arm, rows in (("off", off), ("on", on)):
        for r in rows:
            k = n_folds - 1 if step.total_seconds() == 0 else min(
                n_folds - 1, int((_ts(r["entry_time"]) - lo) / step)
            )
            res[k][arm] += r["net_r"]
    for f in res:
        f["off"], f["on"] = round(f["off"], 4), round(f["on"], 4)
    return res


def grade(
    off: Sequence[Dict[str, Any]],
    on: Sequence[Dict[str, Any]],
    *,
    min_n: int,
    mean_tol: float,
    n_folds: int,
) -> Dict[str, Any]:
    n_off, n_on = len(off), len(on)
    net_off, net_on = _net(off), _net(on)
    mean_off = net_off / n_off if n_off else 0.0
    mean_on = net_on / n_on if n_on else 0.0
    ex_off, ex_on = _ex_worst(off), _ex_worst(on)
    folds = fold_table(off, on, n_folds)
    m = {
        "n_off": n_off,
        "n_on": n_on,
        "net_r_off": round(net_off, 4),
        "net_r_on": round(net_on, 4),
        "net_r_delta_on_minus_off": round(net_on - net_off, 4),
        "mean_r_off": round(mean_off, 4),
        "mean_r_on": round(mean_on, 4),
        "net_r_off_ex_worst_trade": round(ex_off, 4),
        "net_r_on_ex_worst_trade": round(ex_on, 4),
        "folds": folds,
        "folds_on_ge_off": sum(1 for f in folds if f["on"] >= f["off"]),
    }
    c_net = net_on > net_off
    c_mean = mean_on >= mean_off - mean_tol
    c_ex = ex_on > ex_off
    m["conditions"] = {
        "n_floor": n_off + n_on >= min_n,
        "net_on_gt_off": c_net,
        "mean_not_worse_than_tol": c_mean,
        "ex_worst_on_gt_off": c_ex,
    }
    if n_off + n_on < min_n:
        m["verdict"] = "indeterminate"
        m["note"] = f"INDETERMINATE: n(OFF)+n(ON) = {n_off + n_on} < {min_n}"
    elif c_net and c_mean and c_ex:
        m["verdict"] = "pass"
        m["note"] = (
            f"PASS: ON {net_on:.2f} R vs OFF {net_off:.2f} R (delta {net_on - net_off:+.2f}); mean {mean_on:.4f} vs {mean_off:.4f}; "
            f"ex-worst-trade ON {ex_on:.2f} vs OFF {ex_off:.2f}; folds ON>=OFF {m['folds_on_ge_off']}/{n_folds}"
        )
    else:
        why = [
            name
            for name, ok in (
                ("net R(ON) <= net R(OFF)", c_net),
                (f"mean R(ON) worse than OFF by more than {mean_tol}", c_mean),
                ("ON <= OFF with each arm's worst trade removed", c_ex),
            )
            if not ok
        ]
        m["verdict"] = "fail"
        m["note"] = (
            f"FAIL ({'; '.join(why)}): ON {net_on:.2f} R vs OFF {net_off:.2f} R (delta {net_on - net_off:+.2f}); "
            f"n {n_on}/{n_off}; folds ON>=OFF {m['folds_on_ge_off']}/{n_folds}"
        )
    return m


def _fetch(leg: str, days: int, csv_path: Path) -> str:
    """Fetch the leg's candles exactly as the harness does for a Binance USD-M leg (fetch_backtest_candles, binance_vision)."""
    from src.units.strategies import load_strategy_config  # noqa: PLC0415

    cfg = dict(load_strategy_config()[leg])
    symbol = str(cfg["symbols"][0])
    tf = str(cfg.get("timeframe"))
    if tf not in _INTERVAL:
        raise SystemExit(f"htf_filter_confirm: {leg} timeframe {tf!r} is not one of {sorted(_INTERVAL)}")
    r = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ops" / "fetch_backtest_candles.py"),
            "--symbol",
            symbol,
            "--interval",
            _INTERVAL[tf],
            "--days",
            str(days),
            "--output",
            str(csv_path),
            "--source",
            "binance_vision",
        ],
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"htf_filter_confirm: candle fetch failed rc={r.returncode}")
    return symbol


def run(a: argparse.Namespace) -> int:
    import rq_20260928_001_htf_wire as drv  # noqa: PLC0415

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = Path(a.csv) if a.csv else out / f"{a.leg}__candles.csv"
    if not a.csv:
        _fetch(a.leg, a.days, csv_path)
    window = ["--start", a.start, "--end", a.end]
    raw: Dict[str, Any] = {}
    emits: Dict[str, List[Dict[str, Any]]] = {}
    for arm in ("off", "on"):
        raw[arm] = drv.run_arm(a.leg, str(csv_path), out, arm, extra_argv=window)
        if raw[arm]["rc"] != 0:
            rec = {
                "verdict": "indeterminate",
                "read_state": "unmeasured",
                "n": 0,
                "population": f"{a.leg} {a.start}..{a.end}: backtest arm {arm} exited rc={raw[arm]['rc']}",
                "measurement": {"arms": {k: {kk: vv for kk, vv in v.items() if kk != 'summary'} for k, v in raw.items()}},
                "note": f"backtest arm {arm} failed; nothing graded",
                "decision_rule_id": a.rule_id,
            }
            (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
            return 0
        emits[arm] = read_trades(out / f"{a.leg}_{arm}_trades.csv")
    arms_dir = out / "arms"
    arms_dir.mkdir(exist_ok=True)
    for arm, label in (("off", "OFF"), ("on", "ON")):
        (arms_dir / f"{label}__trades.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in emits[arm]), encoding="utf-8"
        )
    m = grade(emits["off"], emits["on"], min_n=a.min_n, mean_tol=a.mean_tol, n_folds=a.folds)
    rec = {
        "verdict": m["verdict"],
        "read_state": "measured",
        "n": m["n_off"] + m["n_on"],
        "population": (
            f"{a.leg} {a.start}..{a.end}: {m['n_off']} OFF + {m['n_on']} ON trades; HTF trend filter forced OFF vs ON; "
            "net of the harness's full cost stack (fee + slippage + funding passed explicitly)"
        ),
        "measurement": {
            **m,
            "window": [a.start, a.end],
            "cost_policy": {
                k: raw["on"][k]
                for k in ("fee_bps_roundtrip", "slippage_bps_roundtrip", "funding_bps_per_window")
            },
            "harness_faithful": bool(raw["on"].get("faithful")),
            "omitted_cfg_keys": raw["on"].get("omitted_cfg_keys"),
        },
        "note": m["note"],
        "decision_rule_id": a.rule_id,
    }
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": rec["verdict"], "note": rec["note"]}, indent=1))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--leg")
    p.add_argument("--days", type=int, help="candle days to fetch back from today (must cover --start)")
    p.add_argument("--csv", help="a ready candle CSV (skips the fetch)")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--min-n", type=int, default=175)
    p.add_argument("--mean-tol", type=float, default=0.3)
    p.add_argument("--folds", type=int, default=6)
    p.add_argument("--rule-id", default=None)
    p.add_argument("--research-unit", default=None)
    p.add_argument("--out")
    a = p.parse_args(argv)
    if a.self_test:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_htf_filter_confirm.py"]).returncode
    for need in ("leg", "start", "end", "out"):
        if not getattr(a, need):
            p.error(f"--{need} is required")
    if not a.csv and not a.days:
        p.error("--days is required unless --csv is given")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())

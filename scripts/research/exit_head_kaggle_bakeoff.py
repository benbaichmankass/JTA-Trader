#!/usr/bin/env python3
# wiring: research/queue/RQ-20261118-f7c1-02.yaml run.command (ML-EXITHEAD-ROWS-KAGGLE: exit-head bake-off on kaggle_cpu from PUBLISHED market candles)
"""EXIT-HEAD BAKE-OFF OFF THE TRAINER, from published MARKET data only (row ML-EXITHEAD-ROWS-KAGGLE, 2026-11-18).

WHY. Every exit-head unit routed to the one-slot trainer because rows.jsonl lives only there. Publishing rows.jsonl is NOT
an option: the trainer corpus includes live journal trades (build_exit_head_dataset.py --db), which are OURS, and
docs/research/ml-data-classification-2026-10-13.md approves publishing MARKET data only. So nothing new is published.
This driver REBUILDS a backtest-source-only exit-head corpus inside the run, from the already-published market_raw 1h
shards (metis-market-data, allowlisted in scripts/research/market_data_export.py::ALLOW), then runs the unchanged
exit_head_label_bakeoff on it.

ONE COMMAND (script_run allows only scripts/research/*.py, no shell):
  1. candles: $ML_DATA_ROOT/datasets-out/market_raw/<SYM>/1h/v002/data.jsonl -> <work>/candles/<SYM>_1h.csv
     (read with candle_io.load_candles, the harness's own reader). The span of every shard is recorded.
  2. harness trades: scripts/backtest_trend.py run_backtest per leg (params from config/strategies.yaml, the same call
     exit_head_label_bakeoff.run_leg makes, on the venue cost policy) -> <work>/emit/<leg>.jsonl.
  3. rows: scripts/ml/build_exit_head_dataset.py main() with --trades/--candles and NO --db -> harness rows only. The run
     REFUSES if any built row has source != "harness".
  4. bake-off: exit_head_label_bakeoff.main(--rows <built> --candles-dir <work>/candles ...). Its result row is
     re-labelled with this unit's rule, the rows' source, the shard spans and the build report, and written to
     <out>/verdict.json.

POPULATION CHANGE (stated in every result): backtest-source rows only, on the published market_raw window. Not the trainer
corpus, so a result here REPLICATES / PROVES the route; it does not replace a trainer-corpus unit (aadc-04/11/12).

    python3 scripts/research/exit_head_kaggle_bakeoff.py --unit RQ-20261118-f7c1-02 --out O [--data-root D] [--arms ...]
    python3 scripts/research/exit_head_kaggle_bakeoff.py --self-test

Tier-1 research tooling: writes only --out (and a work dir under it). No config, model, registry or order path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "scripts", _REPO / "scripts" / "ml", _REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

UNIT = "RQ-20261118-f7c1-02"
RULE_ID = "RULE-RQ20261118-f7c1-02-EXITHEAD-KAGGLE-NEG25"
REGISTERED_AT = "2026-11-18"
LEGS: List[Tuple[str, str]] = [("trend_donchian", "BTCUSDT"), ("trend_donchian_eth", "ETHUSDT"), ("trend_donchian_sol", "SOLUSDT")]
SHARD = "datasets-out/market_raw/{sym}/1h/v002/data.jsonl"
TF = "1h"


def shard_path(root: Path, sym: str) -> Tuple[str, Path]:
    rel = SHARD.format(sym=sym)
    from scripts.research import market_data_export as mde
    if not mde.covers(rel):
        raise SystemExit(f"refused: {rel} is not in the published allowlist (market_data_export.ALLOW)")
    return rel, root / rel


def fetch_bybit_candles(sym: str, dst: Path, start: str, end: Optional[str] = None) -> Dict[str, Any]:
    """RUNNER ROUTE (RESEARCH-FILL-20261122): public Bybit linear-perp 1h klines for a symbol that is NOT in the published
    market_raw allowlist (LINK/BNB/XRP/ADA/AVAX). Same venue and same pager the trainer's candle history uses
    (scripts/ops/fetch_backtest_candles.fetch_klines). Needs the internet, so the unit declares why_runner. Market data only."""
    from datetime import datetime, timezone
    sys.path.insert(0, str(_REPO / "scripts" / "ops"))
    import fetch_backtest_candles as fbc
    t0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)
    rows = fbc.fetch_klines(sym, "60", int(t0.timestamp() * 1000), int(t1.timestamp() * 1000))
    if not rows:
        return {"read_state": "could_not_look", "why": "bybit returned no klines"}
    import pandas as pd
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    return _csv_from_df(df, dst)


def _csv_from_df(df, dst: Path) -> Dict[str, Any]:
    cols = ["timestamp", "open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])
    out = df[cols].copy()
    import pandas as pd
    ts = pd.to_datetime(out["timestamp"], utc=True, unit="ms" if str(out["timestamp"].dtype).startswith(("int", "float")) else None)
    out["timestamp"] = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dst, index=False)
    return {"read_state": "measured", "bars": int(len(out)),
            "first_ts": str(out["timestamp"].iloc[0]) if len(out) else None,
            "last_ts": str(out["timestamp"].iloc[-1]) if len(out) else None, "has_volume": "volume" in cols}


def write_candles(src: Path, dst: Path) -> Dict[str, Any]:
    """Published market_raw JSONL -> the harness / builder CSV shape (timestamp ISO, open, high, low, close, volume)."""
    import candle_io
    df = candle_io.load_candles(str(src))
    cols = ["timestamp", "open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])
    out = df[cols].copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dst, index=False)
    return {"bars": int(len(out)), "first_ts": str(out["timestamp"].iloc[0]) if len(out) else None,
            "last_ts": str(out["timestamp"].iloc[-1]) if len(out) else None, "has_volume": "volume" in cols}


def emit_trades(strategy: str, symbol: str, candles_csv: Path, emit: Path, conf: Dict[str, Any]) -> Dict[str, Any]:
    """The same run_backtest call exit_head_label_bakeoff.run_leg makes, on the venue cost policy, emitting the JSONL."""
    from exit_head_replay import _apply_venue_cost_policy, _load_harness
    cfg = conf.get("strategies", conf).get(strategy)
    if not isinstance(cfg, dict):
        return {"leg": strategy, "read_state": "producer_failed", "why": f"no strategy {strategy!r} in config"}
    harness = _load_harness()
    cost = _apply_venue_cost_policy(harness, symbol)
    df = harness._load_candles(str(candles_csv))
    emit.parent.mkdir(parents=True, exist_ok=True)
    trades: List[Any] = []
    harness.run_backtest(
        df.copy(), donchian=int(cfg.get("donchian", 20)), atr_period=int(cfg.get("atr_period", 14)),
        atr_stop_mult=float(cfg.get("atr_stop_mult", 2.5)), trail_mult=float(cfg.get("trail_mult", 3.0)),
        timeout_bars=200, cooldown_bars=1, timeframe=TF, symbol=symbol,
        min_confidence=float(cfg.get("min_confidence", 0.0)), long_only=bool(cfg.get("long_only")),
        emit_path=str(emit), strategy_name=strategy, trades_out=trades)
    return {"leg": strategy, "symbol": symbol, "read_state": "measured", "n_trades": len(trades), "cost_basis": cost}


def harness_only_sources(rows_p: Path) -> Dict[str, int]:
    """Row count by `source`; REFUSES (SystemExit) if any row is not 'harness' -- this route never holds journal rows."""
    sources: Dict[str, int] = {}
    if rows_p.exists():
        with rows_p.open() as fh:
            for line in fh:
                if line.strip():
                    s = str(json.loads(line).get("source"))
                    sources[s] = sources.get(s, 0) + 1
    bad = {s: n for s, n in sources.items() if s != "harness"}
    if bad:
        raise SystemExit(f"refused: built rows carry non-harness sources {bad}; this route may hold backtest rows only")
    return sources


def build_rows(emits: List[Path], candles: Dict[str, Path], out: Path) -> Dict[str, Any]:
    """build_exit_head_dataset.main with NO --db: harness rows only. Refuses any row whose source is not 'harness'."""
    import build_exit_head_dataset as B
    argv = ["build_exit_head_dataset"] + [x for e in emits for x in ("--trades", str(e))] \
        + [x for s, p in candles.items() for x in ("--candles", f"{s}={p}")] + ["--tf", TF, "--out", str(out)]
    rc = B.main(argv)
    rep_p = out / "build_report.json"
    rep = json.loads(rep_p.read_text()) if rep_p.exists() else {}
    rows_p = out / "donchian" / "rows.jsonl"
    sources = harness_only_sources(rows_p)
    return {"rc": rc, "rows_path": str(rows_p), "rows_exist": rows_p.exists(), "rows_by_source": sources,
            "build_report": rep}


def run(a) -> int:
    root = Path(a.data_root or os.environ.get("ML_DATA_ROOT") or "")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="exithead_kaggle_"))
    import yaml
    conf = yaml.safe_load((_REPO / "config/strategies.yaml").read_text(encoding="utf-8"))
    legs = [tuple(x.split(":")) for x in a.legs.split(",") if x]
    spans: Dict[str, Any] = {}
    csvs: Dict[str, Path] = {}
    for _, sym in legs:
        if sym in csvs or sym in spans:
            continue
        if a.candle_source == "bybit":
            csvs[sym] = work / "candles" / f"{sym}_{TF}.csv"
            try:
                info = fetch_bybit_candles(sym, csvs[sym], a.start, a.end)
            except Exception as exc:  # network/pager failure: a could_not_look, never a silent empty
                info = {"read_state": "could_not_look", "why": f"{type(exc).__name__}: {exc}"}
            spans[sym] = {"source": "bybit_public_klines", **info}
            if info.get("read_state") != "measured":
                csvs.pop(sym)
            continue
        rel, src = shard_path(root, sym)
        if not src.is_file():
            spans[sym] = {"shard": rel, "read_state": "could_not_look", "why": f"not found under ML_DATA_ROOT={root!s}"}
            continue
        csvs[sym] = work / "candles" / f"{sym}_{TF}.csv"
        spans[sym] = {"shard": rel, "read_state": "measured", **write_candles(src, csvs[sym])}
    emits, harness_legs = [], []
    for strategy, sym in legs:
        if sym not in csvs:
            harness_legs.append({"leg": strategy, "read_state": "could_not_look", "why": "no published candles"})
            continue
        e = work / "emit" / f"{strategy}_{sym}.jsonl"
        harness_legs.append(emit_trades(strategy, sym, csvs[sym], e, conf))
        if e.exists():
            emits.append(e)
    extra = {"rows_source": "harness_only (backtest-source rows; NO journal trades: nothing OURS is read or published)",
             "published_shard_spans": spans, "harness_legs": harness_legs}
    if not emits:
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "producer_failed", "verdict": "not_applicable",
               "n": 0, "note": "no harness trades emitted (see published_shard_spans / harness_legs)",
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "measurement": extra}
        (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
        print(json.dumps({k: row[k] for k in ("read_state", "verdict", "note")}))
        return 2
    built = build_rows(emits, csvs, work / "rows")
    extra["rows_build"] = built
    if not built["rows_exist"]:
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "producer_failed", "verdict": "not_applicable",
               "n": 0, "note": "row build produced no donchian rows.jsonl", "measurement": extra,
               "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True}}
        (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
        print(json.dumps({k: row[k] for k in ("read_state", "verdict", "note")}))
        return 2
    import exit_head_label_bakeoff as L
    bj = work / "bakeoff.json"
    rc = L.main(["--rows", built["rows_path"], "--candles-dir", str(work / "candles"), "--timeframe", TF,
                 "--legs", a.legs, "--arms", a.arms, "--unit", a.unit, "--rule-id", a.rule_id, "--z", str(a.z),
                 "--pass-dr", str(a.pass_dr), "--num-folds", str(a.num_folds), "--embargo-days", str(a.embargo_days),
                 "--lookback", str(a.lookback), "--registered-at", a.registered_at, "--json", str(bj)]
                + (["--feature-arms", a.feature_arms] if a.feature_arms else []))
    row = json.loads(bj.read_text())
    row["decision_rule"] = {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True}
    row["population"] = (f"BACKTEST-SOURCE ROWS ONLY (rebuilt in-run from {'public Bybit 1h klines' if a.candle_source == 'bybit' else 'published market_raw 1h v002'}; no journal trades) -- "
                         + str(row.get("population", "")))
    row.setdefault("measurement", {}).update(extra)
    row["produced_by"] = {"tool": "python3 scripts/research/exit_head_kaggle_bakeoff.py (-> exit_head_label_bakeoff.py)"}
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(json.dumps({k: row.get(k) for k in ("read_state", "verdict", "note", "n")}))
    return rc


def _self_test() -> int:
    """Synthetic market_raw shards (canonical 9-key rows, `ts` ISO, ml/datasets/adapters/base.py) -> candles -> harness trades -> rows; proves the harness-only refusal and the allowlist."""
    import math
    import random
    from datetime import datetime, timezone
    rng = random.Random(7)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel, src = shard_path(root, "BTCUSDT")
        src.parent.mkdir(parents=True, exist_ok=True)
        px, t0 = 100.0, 1_600_000_000
        with src.open("w") as fh:
            for i in range(3000):                     # trending regimes so a Donchian breakout fires
                drift = 0.004 * math.sin(i / 150.0)
                o = px
                px = max(1.0, px * (1 + drift + rng.gauss(0, 0.006)))
                hi, lo = max(o, px) * (1 + abs(rng.gauss(0, 0.002))), min(o, px) * (1 - abs(rng.gauss(0, 0.002)))
                ts = datetime.fromtimestamp(t0 + 3600 * i, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                fh.write(json.dumps({"ts": ts, "symbol": "BTCUSDT", "timeframe": "1h", "open": o, "high": hi, "low": lo,
                                     "close": px, "volume": 1000 + rng.random(), "source": "synthetic"}) + "\n")
        csv_p = root / "w" / "candles" / "BTCUSDT_1h.csv"
        span = write_candles(src, csv_p)
        assert span["bars"] == 3000 and span["first_ts"].startswith("2020-09-13"), span
        conf = {"strategies": {"trend_donchian": {"donchian": 20, "atr_period": 14, "atr_stop_mult": 2.5, "trail_mult": 3.0}}}
        e = root / "w" / "emit" / "trend_donchian.jsonl"
        h = emit_trades("trend_donchian", "BTCUSDT", csv_p, e, conf)
        assert h["read_state"] == "measured" and h["n_trades"] > 5 and e.exists(), h
        built = build_rows([e], {"BTCUSDT": csv_p}, root / "w" / "rows")
        assert built["rows_exist"] and set(built["rows_by_source"]) == {"harness"}, built
        # the refusal: a row with a live source must stop the run
        with open(built["rows_path"], "a") as fh:
            fh.write(json.dumps({"source": "live"}) + "\n")
        try:
            harness_only_sources(Path(built["rows_path"]))
            raise AssertionError("a live row was not refused")
        except SystemExit as ex:
            assert "non-harness" in str(ex), ex
        # the allowlist: a non-published path is refused
        import scripts.research.market_data_export as mde
        assert not mde.covers("datasets-out/exit_head/1h/donchian/rows.jsonl")
        # the router reads routing.published_paths
        from scripts.research import compute_router as cr
        assert cr.unit_dataset_paths({"routing": {"published_paths": [rel]}}) == [rel]
    print(json.dumps({"self_test": "ok", "synthetic_trades": h["n_trades"], "rows": built["rows_by_source"]}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--out", default="out/exit_head_kaggle")
    ap.add_argument("--data-root", default=None, help="dir containing datasets-out/ (default $ML_DATA_ROOT)")
    ap.add_argument("--legs", default=",".join(f"{s}:{y}" for s, y in LEGS))
    ap.add_argument("--arms", default="holding_pays_neg25")
    ap.add_argument("--rule-id", default=RULE_ID)
    ap.add_argument("--z", type=float, default=1.96)
    ap.add_argument("--pass-dr", type=float, default=0.01)
    ap.add_argument("--num-folds", type=int, default=5)
    ap.add_argument("--feature-arms", default="", help="feature arms vs the champion (exit_head_label_bakeoff.FEATURE_ARMS)")
    ap.add_argument("--embargo-days", type=float, default=7.0)
    ap.add_argument("--lookback", type=int, default=500)
    ap.add_argument("--registered-at", default=REGISTERED_AT, help="the unit's decision_rule.registered_at")
    ap.add_argument("--candle-source", choices=("published", "bybit"), default="published",
                    help="published = metis-market-data market_raw (kaggle_cpu, internet off); bybit = public klines (runner)")
    ap.add_argument("--start", default="2020-06-01", help="bybit source: first bar date")
    ap.add_argument("--end", default=None, help="bybit source: last bar date (default now)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())

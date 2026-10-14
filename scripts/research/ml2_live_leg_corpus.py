#!/usr/bin/env python3
# wiring: research/queue units (run.command) via research-script-run.yml -- the token-free runner
"""ML-LEG-CORPUS · the `ml2-live-leg-corpus` lever -- keep per-trade harness emits
for the six live legs that carry money, and turn them into a gradable corpus.

WHAT IT IS FOR
--------------
RQ-20261009-900 (TP-PREDICT-HEAD step 1) asks whether an entry-time MFE-quantile
head beats four naive TP baselines on the legs that carry money. ML-2's corpus is
a 15m trend_donchian backtest no live leg runs. Nothing produced per-trade rows
for the live legs: `m20_fleet_exit_sweep.py` runs the harness config-exact but
reads only the summary, and `mi307_offline_mfe.py --run` runs it config-exact and
uncapped but `rec.pop("rows")`s the trades away. This runner is the missing
driver. It

  1. builds each leg's args with `m20_fleet_exit_sweep.base_args` (the ONE
     config->harness arg builder) and runs the harness UNCAPPED with
     `--emit-trades`, so `mfe_r` is the full path excursion, not one censored at
     a take-profit;
  2. KEEPS the emit under `<out>/emit/<leg>.jsonl` (stable names) and the
     corpus at `<out>/ml2_live_leg_corpus.jsonl`;
  3. writes `manifest.json` (population, per-leg states, parity) and the
     `verdict.json` the research-script-run contract expects.

THE STRATA ARE CARRIED, NEVER POOLED (RULE-RQ1009-900)
  S1 bybit_2 Donchian 4h  : trend_donchian_eth_4h, trend_donchian_xrp_4h
  S2 bybit_2 pullback 2h  : xrp_pullback_2h, ada_pullback_2h
  S3 prop Donchian 1h     : trend_donchian_eth_prop, trend_donchian_sol_prop

COST STACK. The harness applies fee + slippage + funding itself
(`execution_costs.resolve_cost_policy`); the emit carries `net_r` and the three
`cost_*_r` columns. This runner passes no cost override, so the policy is the
harness's venue-aware default -- the same one the promotion corpus uses.

⚠️ `adx_at_entry` IS NULL FOR 4 OF THE 6 LEGS UNLESS THIS RUNNER SUPPLIES IT.
The harness computes the ADX series only when an ADX lever is armed
(`adx_active`). MEASURED 2026-10-14 from config/strategies.yaml: the four
Donchian legs declare none, so their emit carries `adx_at_entry: null` and
`regime_weight: 1.0`; only the two pullback legs declare `adx_min`. The unit
text ("both ARE in the trend and pullback emits") was true of the KEYS and false
of the values. A null feature drops the row, which would have left strata S1 and
S3 empty and read as "no data".

The fix keeps the book unchanged: for a leg with no ADX lever the runner appends
`--adx-max 100`. ADX is bounded by 100, so the band admits every bar the
config-exact run admits; its only effect is to make the harness populate
`adx_at_entry` with its OWN Wilder series at the entry bar (decision-time: the
harness enters at the signal bar's close). That "no-op" is a claim, so it is
CHECKED rather than trusted: every such leg is also run WITHOUT the band and the
two trade lists must match exactly (entry_time, direction, gross_r). A mismatch
is reported as `adx_band_not_noop` in the manifest and the verdict is
`indeterminate`, never a quiet pass.

Tier-1 research tooling: reads candles, writes only under --out. No config, no
order path, no live broker state.

    python3 scripts/research/ml2_live_leg_corpus.py --data-dir data/rq-ml-leg-corpus \\
        --fetch 1830 --out comms/research/ml-leg-corpus
    python3 scripts/research/ml2_live_leg_corpus.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts"), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402
from bracket_expectation_census import (  # noqa: E402  (the ONE class-default reader)
    CLASS_DEFAULT_SOURCES,
    _read_class_default,
    family_of,
)
from m20_fleet_exit_sweep import (  # noqa: E402  (the ONE leg->harness resolver)
    FAMILY_HARNESS,
    base_args,
    classify,
    resolve_data,
)
from ml2_bracket_corpus import FEATURE_NAMES, build_rows, read_emit, summarise  # noqa: E402

#: leg -> stratum. Closed and fixed by the unit before the run.
STRATA: Dict[str, str] = {
    "trend_donchian_eth_4h": "S1_bybit2_donchian_4h",
    "trend_donchian_xrp_4h": "S1_bybit2_donchian_4h",
    "xrp_pullback_2h": "S2_bybit2_pullback_2h",
    "ada_pullback_2h": "S2_bybit2_pullback_2h",
    "trend_donchian_eth_prop": "S3_prop_donchian_1h",
    "trend_donchian_sol_prop": "S3_prop_donchian_1h",
}

#: Eval floor from the unit's power basis: (1.96+0.8416)^2 / 0.30^2 = 87.2 -> 88
#: eval trades per stratum at split 0.65, i.e. >= 88 / 0.35 = 252 usable rows.
EVAL_FLOOR = 88
SPLIT = 0.65

#: A band that never excludes: ADX is bounded by 100.
ADX_NOOP_BAND = ["--adx-max", "100"]
_ADX_KEYS = ("adx_min", "adx_max", "adx_soft_weight_floor", "adx_soft_weight_ceiling")

CORPUS_NAME = "ml2_live_leg_corpus.jsonl"


def load_legs(names: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    raw = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    cfgs = raw.get("strategies", raw)
    out: Dict[str, Dict[str, Any]] = {}
    for leg in (names or list(STRATA)):
        if leg not in STRATA:
            raise SystemExit(f"{leg!r} is not one of the six registered legs: {sorted(STRATA)}")
        cfg = cfgs.get(leg)
        if not isinstance(cfg, dict):
            raise SystemExit(f"{leg!r} is not in config/strategies.yaml")
        out[leg] = cfg
    return out


def has_adx_lever(cfg: Dict[str, Any]) -> bool:
    return any(cfg.get(k) is not None for k in _ADX_KEYS)


def class_default_tp_r(leg: str, cfg: Dict[str, Any]) -> Optional[float]:
    """B2: the strategy class's default `tp_r`, via the census's own reader."""
    src = CLASS_DEFAULT_SOURCES.get(family_of(leg, cfg))
    return _read_class_default(*src) if src else None


def fetch(data_dir: Path, symbols: List[str], days: int) -> Dict[str, int]:
    """Public 1h klines (data.binance.vision USD-M perps) -> <SYMBOL>_1h.csv.
    An empty fetch writes nothing, so the leg reads `no_data` ("could not
    look"), never a result."""
    import importlib.util

    import pandas as pd
    spec = importlib.util.spec_from_file_location("_fetch_candles",
                                                  REPO / "scripts/ops/fetch_backtest_candles.py")
    fbc = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["_fetch_candles"] = fbc
    spec.loader.exec_module(fbc)  # type: ignore[union-attr]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    data_dir.mkdir(parents=True, exist_ok=True)
    got: Dict[str, int] = {}
    for sym in symbols:
        rows = fbc.fetch_klines_binance_vision(sym, "60", start_ms, end_ms)
        got[sym] = len(rows or [])
        if not rows:
            print(f"fetch: {sym}: no rows", file=sys.stderr)
            continue
        df = pd.DataFrame([{k: r[k] for k in ("timestamp", "open", "high", "low", "close", "volume")}
                           for r in rows])
        df.to_csv(data_dir / f"{sym}_1h.csv", index=False)
        print(f"fetch: {sym}: {len(df)} bars {df['timestamp'].iloc[0]} .. {df['timestamp'].iloc[-1]}")
    return got


def _run_harness(harness: str, args: List[str], leg: str, emit_path: Path) -> Tuple[bool, str]:
    emit_path.parent.mkdir(parents=True, exist_ok=True)
    emit_path.unlink(missing_ok=True)
    cmd = [sys.executable, str(REPO / harness), *args, "--strategy-name", leg,
           "--emit-trades", str(emit_path)]
    try:
        # check=False: a non-zero rc is a STATE (`harness_failed`), not an exception
        # that aborts the other five legs.
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                           cwd=str(REPO), check=False)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if p.returncode != 0:
        return False, (p.stderr or "").strip()[-400:] or f"rc={p.returncode}"
    if not emit_path.exists():
        # The harness writes nothing when it makes no trades. That is a result
        # (0 trades), reported as such by the caller -- not a failed run.
        emit_path.write_text("")
    return True, ""


def _trade_key(r: Dict[str, Any]) -> Tuple[Any, ...]:
    g = r.get("gross_r")
    return (r.get("entry_time"), r.get("direction"),
            round(float(g), 6) if isinstance(g, (int, float)) else g)


def run_leg(leg: str, cfg: Dict[str, Any], data_dir: Path, out_dir: Path,
            *, verify_band: bool = True) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """-> (state record, corpus rows). States are never collapsed:
    ok · no_harness · no_data · harness_failed · adx_band_not_noop."""
    fam = classify(leg)
    harness = FAMILY_HARNESS.get(fam or "")
    sym = (cfg.get("symbols") or [None])[0]
    tf = str(cfg.get("timeframe") or "1h")
    rec: Dict[str, Any] = {"leg": leg, "stratum": STRATA[leg], "family": fam, "symbol": sym,
                           "timeframe": tf, "declared_tp_r": cfg.get("tp_r"),
                           "class_default_tp_r": class_default_tp_r(leg, cfg),
                           "adx_declared": has_adx_lever(cfg)}
    if not harness:
        return {**rec, "state": "no_harness"}, []
    data, proxy, resample = resolve_data(str(sym), tf, data_dir)
    if not data:
        return {**rec, "state": "no_data", "why": f"no candle file for {sym}/{tf} under {data_dir}"}, []
    args = base_args(leg, cfg, fam or "", data, resample)   # uncapped: no --tp-cap-pct
    emit = out_dir / "emit" / f"{leg}.jsonl"
    adx_source = "harness_declared_lever"
    run_args = list(args)
    if not rec["adx_declared"]:
        run_args += ADX_NOOP_BAND
        adx_source = "harness_noop_band"
    ok, why = _run_harness(harness, run_args, leg, emit)
    if not ok:
        return {**rec, "state": "harness_failed", "why": why}, []
    raws, malformed = read_emit(str(emit))
    rec.update(data_file=os.path.basename(data), proxy=bool(proxy), resample=resample,
               adx_source=adx_source, emit=str(emit), emit_rows=len(raws),
               malformed_lines=malformed, harness_args=run_args)

    if adx_source == "harness_noop_band" and verify_band:
        with tempfile.TemporaryDirectory(prefix="mlleg_parity_") as td:
            pe = Path(td) / "exact.jsonl"
            ok2, why2 = _run_harness(harness, args, leg, pe)
            if not ok2:
                return {**rec, "state": "harness_failed", "why": f"parity run: {why2}"}, []
            exact, _ = read_emit(str(pe))
        same = sorted(map(_trade_key, exact)) == sorted(map(_trade_key, raws))
        rec["adx_band_parity"] = {"config_exact_trades": len(exact), "banded_trades": len(raws),
                                  "identical": same}
        if not same:
            rec["state"] = "adx_band_not_noop"
    rec.setdefault("state", "ok")

    rows = build_rows(raws, leg_override=leg)
    for r in rows:
        r["stratum"] = STRATA[leg]
        r["declared_tp_r"] = rec["declared_tp_r"]
        r["class_default_tp_r"] = rec["class_default_tp_r"]
        r["adx_source"] = adx_source
    return rec, rows


def usable(rows: List[Dict[str, Any]]) -> int:
    return sum(1 for r in rows
               if r.get("mfe_r") is not None and all(r.get(k) is not None for k in FEATURE_NAMES))


def grade(recs: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Corpus completeness, against the bar registered in the unit. Not an edge
    claim of any kind -- it says only whether the corpus can be graded."""
    per_leg = []
    problems: List[str] = []
    for rec in recs:
        lr = [r for r in rows if r.get("leg") == rec["leg"]]
        u = usable(lr)
        per_leg.append({"leg": rec["leg"], "state": rec["state"], "rows": len(lr), "usable": u})
        if rec["state"] != "ok":
            problems.append(f"{rec['leg']}: state {rec['state']}")
    by_stratum: Dict[str, int] = {}
    for p in per_leg:
        by_stratum[STRATA[p["leg"]]] = by_stratum.get(STRATA[p["leg"]], 0) + p["usable"]
    need = int(-(-EVAL_FLOOR // (1 - SPLIT)))  # ceil(88 / 0.35) = 252
    # A stratum under the floor is NOT a corpus defect: RULE-RQ1009-900 grades it
    # INDETERMINATE on its own. It is reported here so the shortfall is visible
    # at build time; it does not fail the build.
    short = {s: n for s, n in by_stratum.items() if n < need}
    # Each leg must have produced usable rows: a leg with rows but zero usable
    # ones (a null feature) is the silent-drop failure this runner exists to stop.
    for p in per_leg:
        if p["state"] == "ok" and p["usable"] == 0:
            problems.append(f"{p['leg']}: 0 usable rows of {p['rows']}")
    pop = (f"{len(recs)} registered live legs, 1830 d window, uncapped config-exact harness "
           f"runs; usable rows per stratum {by_stratum}; strata below the {need}-row "
           f"eval floor (graded INDETERMINATE by RQ-20261009-900): {sorted(short) or 'none'}")
    if not rows:
        return {"verdict": "indeterminate", "read_state": "no_data", "population": pop, "n": 0,
                "note": "no corpus rows -- could not look: " + "; ".join(problems),
                "measurement": {"per_leg": per_leg}}
    return {"verdict": "indeterminate" if problems else "pass", "read_state": "measured",
            "population": pop, "n": sum(by_stratum.values()),
            "note": ("corpus buildable and gradable" if not problems
                     else "corpus NOT gradable as built: " + "; ".join(problems)),
            "measurement": {"per_leg": per_leg, "usable_by_stratum": by_stratum,
                            "min_usable_rows_per_stratum": need,
                            "strata_below_eval_floor": short}}


def build(out_dir: Path, data_dir: Path, *, fetch_days: int = 0,
          only: Optional[List[str]] = None, verify_band: bool = True) -> int:
    legs = load_legs(only)
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched: Dict[str, int] = {}
    if fetch_days:
        fetched = fetch(data_dir, sorted({(c.get("symbols") or [None])[0] for c in legs.values()} - {None}),
                        fetch_days)
    recs: List[Dict[str, Any]] = []
    all_rows: List[Dict[str, Any]] = []
    for leg, cfg in legs.items():
        rec, rows = run_leg(leg, cfg, data_dir, out_dir, verify_band=verify_band)
        recs.append(rec)
        all_rows.extend(rows)
        print(f"{leg:26} {rec['state']:18} rows={len(rows):5} usable={usable(rows):5} "
              f"adx={rec.get('adx_source')} parity={rec.get('adx_band_parity', {}).get('identical')}")
    corpus = out_dir / CORPUS_NAME
    with open(corpus, "w", encoding="utf-8") as fh:
        for r in all_rows:
            fh.write(json.dumps(r) + "\n")
    manifest = {"corpus": str(corpus), "features": list(FEATURE_NAMES), "fetched_bars": fetched,
                "summary": summarise(all_rows), "legs": recs,
                "regrade": (f"python3 scripts/research/ml2_bracket_train_eval.py --corpus {corpus} "
                            "--outcome mfe_r --per-leg --per-stratum")}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    verdict = grade(recs, all_rows)
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
    print(f"corpus: {corpus} ({len(all_rows)} rows)  verdict: {verdict['verdict']} -- {verdict['note']}")
    return 0


def selftest() -> int:
    """Positive + negative control on the pieces that can silently be wrong."""
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"[selftest] {'PASS' if cond else 'FAIL'}  {name}")
        ok = ok and cond

    legs = load_legs()
    check("six legs, three strata of two", len(legs) == 6 and
          sorted(set(STRATA.values())) == ["S1_bybit2_donchian_4h", "S2_bybit2_pullback_2h",
                                           "S3_prop_donchian_1h"])
    check("donchian legs declare no ADX lever (the band is needed)",
          not has_adx_lever(legs["trend_donchian_eth_4h"]))
    check("pullback legs declare adx_min (no band added)", has_adx_lever(legs["xrp_pullback_2h"]))
    check("B2 class default readable for both families",
          class_default_tp_r("trend_donchian_eth_4h", legs["trend_donchian_eth_4h"]) is not None
          and class_default_tp_r("xrp_pullback_2h", legs["xrp_pullback_2h"]) is not None)
    # grade(): a corpus missing a stratum must NOT pass.
    row = {"leg": "trend_donchian_eth_4h", "mfe_r": 1.0, **{k: 1.0 for k in FEATURE_NAMES}}
    recs = [{"leg": "trend_donchian_eth_4h", "state": "ok"}]
    g_thin = grade(recs, [row] * 10)
    check("an under-floor stratum is REPORTED, and does not fail the build",
          g_thin["verdict"] == "pass" and
          g_thin["measurement"]["strata_below_eval_floor"] == {"S1_bybit2_donchian_4h": 10})
    check("floor met reports no short stratum",
          grade(recs, [row] * 300)["measurement"]["strata_below_eval_floor"] == {})
    nullrow = dict(row, adx_at_entry=None)
    check("rows present but 0 usable (null feature) is indeterminate, not pass",
          grade(recs, [nullrow] * 300)["verdict"] == "indeterminate")
    check("empty corpus grades no_data, not a clean zero", grade(recs, [])["read_state"] == "no_data")
    check("a leg whose state is not ok blocks the pass",
          grade([{"leg": "trend_donchian_eth_4h", "state": "adx_band_not_noop"}], [row] * 300)
          ["verdict"] == "indeterminate")
    print("[selftest]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data/ml-leg-corpus")
    ap.add_argument("--fetch", type=int, default=0, metavar="DAYS",
                    help="download the legs' 1h klines into --data-dir first")
    ap.add_argument("--out", default="comms/research/ml-leg-corpus")
    ap.add_argument("--leg", action="append", default=None)
    ap.add_argument("--no-verify-band", action="store_true",
                    help="skip the config-exact parity run (NOT for the registered run)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    return build(Path(a.out), Path(a.data_dir), fetch_days=a.fetch, only=a.leg,
                 verify_band=not a.no_verify_band)


if __name__ == "__main__":
    raise SystemExit(main())

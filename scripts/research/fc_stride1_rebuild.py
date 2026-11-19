#!/usr/bin/env python3
"""D2 option A: rebuild the fc-pcv forecast side-stream at stride 1, retrain the fc-pcv-v2 heads as PRIVATE
candidates, and re-run the serve-path diff (PI-20261119-K7ZSW5Z7-0002; unit RQ-20261119-a10d-01).

WHY. RQ-20261118-04a5-03 PASSED with the named block forecast_fc: the trainer's v002 forecast side-stream is computed
only at stride-4 anchors and carried forward by market_features' as-of join (~75% of training rows stale by
construction), while the live publisher serves a fresh forecast every bar. The heads were trained on mostly-stale fc_*
and score fresh fc_* live, and every replay of the live labels reads the stale stream.

WHAT IT DOES, per symbol (BTCUSDT, SOLUSDT; 15m), each step timed (the trainer cost of option A is part of the answer):
  1. forecasts   python -m scripts.ml.build_forecasts --stride 1 over the EXISTING trainer market_raw v002 (read-only)
                 into <root>/datasets/forecasts/<SYM>/15m/v002;
  2. features    python -m ml build-dataset market_features with the nightly builder's exact 15m params plus
                 forecast_path=<step 1>, into <root>/datasets (version v002, so the head manifests resolve unchanged);
  3. candidate   python -m ml train ml/configs/<sym>-regime-15m-lgbm-fc-pcv-v2.yaml --datasets-root <root>/datasets
                 --registry-root <root>/registry-store: the candidate lives in a PRIVATE registry, so nothing the live
                 trader or the nightly cycle reads is touched; it is a candidate by construction;
  4. parity      vol_serve_path_diff.diff_head with the SERVED head (production registry) on the rebuilt rows against
                 the committed live snapshot (comms/live_parity/vol_serve_rows_20261118, 11-09..18): GRADED;
  5. candidate   the same diff with the private candidate head: REPORTED, not graded;
  6. staleness   share of consecutive rows whose fc_ret_med repeats, production v002 vs rebuilt (diagnostic).

Registered rule (RULE-RQ-20261119-a10d-01-FC-STRIDE1-PARITY), per head, on step 4:
  INDETERMINATE if any step 1-4 failed for the head, or matched bars < 200;
  PASS          if agreement >= 0.98 AND kappa >= 0.8 (the clears_when of PI-20261119-K7ZSW5Z7-0002);
  FAIL          otherwise (forecast_fc's share of the remaining flips is reported).
Unit verdict = the worst head, FAIL > INDETERMINATE > PASS.

Tier-1 research tooling. Writes only under --root and --out-dir. Serves, stages and promotes nothing; edits no config.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

RULE_ID = "RULE-RQ-20261119-a10d-01-FC-STRIDE1-PARITY"
MIN_MATCHED = 200
AGREE_OK, KAPPA_OK = 0.98, 0.8
SYMBOLS = {"BTCUSDT": "btc-regime-15m-lgbm-fc-pcv-v2", "SOLUSDT": "sol-regime-15m-lgbm-fc-pcv-v2"}
# The nightly builder's 15m market_features params (scripts/ops/build_trainer_datasets.sh::build_bybit_features).
FEATURE_PARAMS = ["vol_window_n=20", "forward_window_m=5", "vol_threshold=0.005", "trend_threshold=0.005", "n_vol_buckets=3"]


def _run(cmd: List[str], log: Path) -> Dict[str, Any]:
    t0 = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT).returncode
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-6:]
    return {"rc": rc, "seconds": round(time.monotonic() - t0, 1), "cmd": cmd[1:6], "log_tail": tail}


def stale_share(path: Path, lo: Optional[str] = None) -> Dict[str, Any]:
    """Share of consecutive rows (ts >= lo) whose fc_ret_med equals the previous row's (a carried-forward forecast)."""
    if not path.is_file():
        return {"n": 0, "share_repeat": None, "read_state": "no_data"}
    prev, n, rep = None, 0, 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if '"fc_ret_med"' not in line:
                continue
            r = json.loads(line)
            if lo and str(r.get("ts", "")) < lo:
                continue
            v = r.get("fc_ret_med")
            if prev is not None:
                n += 1
                rep += int(v == prev)
            prev = v
    return {"n": n, "share_repeat": round(rep / n, 4) if n else None, "read_state": "measured" if n else "no_data"}


def grade(diff: Dict[str, Any], failed_step: Optional[str]) -> tuple[str, str]:
    if failed_step:
        return "INDETERMINATE", f"step {failed_step} failed"
    if "error" in diff:
        return "INDETERMINATE", f"diff error: {str(diff['error'])[:160]}"
    n = int(diff.get("n_scored") or 0)
    if n < MIN_MATCHED:
        return "INDETERMINATE", f"matched {n} < {MIN_MATCHED}"
    agree, kap = diff.get("agreement"), diff.get("kappa")
    if agree is not None and kap is not None and agree >= AGREE_OK and kap >= KAPPA_OK:
        return "PASS", f"agreement {agree} kappa {kap} n {n}"
    nd = int(diff.get("n_disagree") or 0)
    fc = (diff.get("blocks") or {}).get("forecast_fc", {}).get("flips_reproduced", 0)
    return "FAIL", f"agreement {agree} kappa {kap} n {n}; forecast_fc reproduces {fc}/{nd} flips"


def roll_up(vs: List[str]) -> str:
    for v in ("FAIL", "INDETERMINATE", "PASS"):
        if v in vs:
            return v
    return "INDETERMINATE"


def _slim(diff: Dict[str, Any]) -> Dict[str, Any]:
    keep = ("n_live", "n_matched", "n_scored", "agreement", "kappa", "n_disagree", "match_offsets", "share_volatile_live",
            "share_volatile_replay", "dataset_last_matched_bar", "column_share_differing_1e-3", "error")
    out = {k: diff.get(k) for k in keep if k in diff}
    out["blocks"] = {b: {k: v for k, v in d.items() if k != "columns"} for b, d in (diff.get("blocks") or {}).items()}
    return out


def verdict_row(heads: Dict[str, Dict[str, Any]], unit: str, steps_s: float) -> dict:
    vs = [h["verdict"] for h in heads.values()]
    top = roll_up(vs)
    measured = any(int((h.get("parity_served") or {}).get("n_scored") or 0) > 0 for h in heads.values())
    vmap = {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate"}
    return {"schema_version": 1, "research_unit": unit, "rule_id": RULE_ID, "verdict": vmap[top],
            "read_state": "measured" if measured else "producer_failed",
            "note": f"{top}: " + "; ".join(f"{s} {h['verdict']} ({h['reason']})" for s, h in heads.items())
                    + f"; total trainer wall {round(steps_s / 60, 1)} min",
            "population": "live per-bar shadow_predictions feature rows (comms/live_parity/vol_serve_rows_20261118, "
                          "2026-11-09..18) matched bar-for-bar to a STRIDE-1 rebuild of market_features v002, scored by the "
                          "served heads " + ", ".join(f"{s}:{h['model_id']}" for s, h in heads.items()),
            "n": int(sum(int((h.get("parity_served") or {}).get("n_scored") or 0) for h in heads.values())),
            "measurement": {"heads": heads, "total_wall_seconds": round(steps_s, 1),
                            "generated_at": datetime.now(timezone.utc).isoformat()}}


def run_symbol(sym: str, model_id: str, root: Path, raw_root: Path, prod_root: Path, logs: Path,
               snapshot: Path, skip_build: bool) -> Dict[str, Any]:
    import vol_serve_path_diff as D
    py = sys.executable
    raw = raw_root / "market_raw" / sym / "15m" / "v002"
    fc_out = root / "datasets" / "forecasts" / sym / "15m" / "v002"
    ds_root = root / "datasets"
    rebuilt = ds_root / "market_features" / sym / "15m" / "v002" / "data.jsonl"
    live = snapshot / f"{sym}.jsonl"
    h: Dict[str, Any] = {"symbol": sym, "model_id": model_id, "steps": {}}
    failed: Optional[str] = None
    plan = [
        ("forecasts", [py, "-m", "scripts.ml.build_forecasts", "--target", str(raw), "--out", str(fc_out), "--stride", "1"]),
        ("features", [py, "-m", "ml", "build-dataset", "market_features", "--output-dir", str(ds_root), "--version", "v002",
                      "--source", str(raw), "--symbol-scope", sym, "--timeframe", "15m", "--overwrite",
                      f"market_raw_path={raw}", *FEATURE_PARAMS, f"forecast_path={fc_out}"]),
        ("candidate", [py, "-m", "ml", "train", str(REPO / "ml" / "configs" / f"{model_id}.yaml"),
                       "--datasets-root", str(ds_root), "--registry-root", str(root / "registry-store"),
                       "--experiments-root", str(root / "experiments")]),
    ]
    if not raw.is_dir():
        failed = "forecasts"
        h["steps"]["forecasts"] = {"rc": None, "error": f"market_raw not found at {raw}"}
    for name, cmd in ([] if failed or skip_build else plan):
        r = _run(cmd, logs / f"{sym}_{name}.log")
        h["steps"][name] = r
        print(sym, name, json.dumps({"rc": r["rc"], "seconds": r["seconds"]}), flush=True)
        if r["rc"] != 0:
            failed = name
            break
    if not failed and not rebuilt.is_file():
        failed = "features"
    if failed:
        h["parity_served"] = {"error": f"step {failed} failed"}
    else:
        t0 = time.monotonic()
        try:
            h["parity_served"] = _slim(D.diff_head(sym, model_id, rebuilt, live, "15m", None))
        except Exception as e:  # noqa: BLE001  # allow-silent: recorded per head as a producer error -> INDETERMINATE
            h["parity_served"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            h["parity_candidate"] = _slim(D.diff_head(sym, model_id, rebuilt, live, "15m", str(root / "registry-store")))
        except Exception as e:  # noqa: BLE001  # allow-silent: reported only, never graded
            h["parity_candidate"] = {"error": f"{type(e).__name__}: {e}"}
        h["steps"]["diffs"] = {"rc": 0, "seconds": round(time.monotonic() - t0, 1)}
    h["verdict"], h["reason"] = grade(h["parity_served"], failed)
    prod = prod_root / "market_features" / sym / "15m" / "v002" / "data.jsonl"
    h["staleness"] = {"production_v002_since_2026-11-09": stale_share(prod, "2026-11-09"),
                      "rebuilt_since_2026-11-09": stale_share(rebuilt, "2026-11-09")}
    return h


def _self_test() -> int:
    import tempfile
    ok = True

    def check(msg, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    check("thin is INDETERMINATE", grade({"n_scored": 50, "agreement": 1.0, "kappa": 1.0}, None)[0] == "INDETERMINATE")
    check("step failure is INDETERMINATE", grade({}, "forecasts")[0] == "INDETERMINATE")
    check("clean is PASS", grade({"n_scored": 900, "agreement": 0.99, "kappa": 0.85}, None)[0] == "PASS")
    check("kappa short is FAIL", grade({"n_scored": 900, "agreement": 0.99, "kappa": 0.7, "n_disagree": 9,
                                        "blocks": {"forecast_fc": {"flips_reproduced": 8}}}, None)[0] == "FAIL")
    check("roll_up order", roll_up(["PASS", "INDETERMINATE"]) == "INDETERMINATE" and roll_up(["PASS", "FAIL"]) == "FAIL")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "d.jsonl"
        p.write_text("\n".join(json.dumps({"ts": f"2026-11-1{i // 4}T00:{i:02d}", "fc_ret_med": i // 4}) for i in range(8)) + "\n")
        s = stale_share(p)
        check("stale_share: stride-4 carry repeats 6 of 7", s["n"] == 7 and s["share_repeat"] == round(6 / 7, 4))
        check("stale_share: missing file is no_data", stale_share(Path(td) / "nope.jsonl")["read_state"] == "no_data")
    import script_run as SR
    row = verdict_row({"BTCUSDT": {"model_id": "m", "verdict": "PASS", "reason": "r", "parity_served": {"n_scored": 900}}},
                      "U", 60.0)
    check("verdict row vocabularies", row["verdict"] in SR.VERDICTS and row["read_state"] in SR.READ_STATES and row["n"] == 900)
    bad = verdict_row({"BTCUSDT": {"model_id": "m", "verdict": "INDETERMINATE", "reason": "r",
                                   "parity_served": {"error": "x"}}}, "U", 1.0)
    check("nothing scored is producer_failed", bad["read_state"] == "producer_failed" and bad["verdict"] == "indeterminate")
    print("fc_stride1_rebuild self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--root", default="runtime_logs/research/fc_stride1", help="private datasets/registry root")
    ap.add_argument("--prod-datasets-root", default="datasets-out")
    ap.add_argument("--snapshot", default="comms/live_parity/vol_serve_rows_20261118")
    ap.add_argument("--symbol", action="append", default=[])
    ap.add_argument("--skip-build", action="store_true", help="re-diff an existing rebuild (no steps 1-3)")
    ap.add_argument("--unit", default="RQ-20261119-a10d-01")
    ap.add_argument("--out-dir", required=False)
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out_dir:
        ap.error("--out-dir is required")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    root = (REPO / a.root) if not os.path.isabs(a.root) else Path(a.root)
    root.mkdir(parents=True, exist_ok=True)
    prod = (REPO / a.prod_datasets_root) if not os.path.isabs(a.prod_datasets_root) else Path(a.prod_datasets_root)
    try:
        from scripts.ml._heavy_queue import take_heavy_queue
        _lock = take_heavy_queue("fc-stride1-rebuild")  # noqa: F841 - held for the process lifetime
    except Exception as e:  # allow-silent: fail-open by design (the helper is inert off-trainer); stderr line printed
        print(f"WARN heavy-queue helper unavailable ({type(e).__name__}); proceeding unlocked", file=sys.stderr)
    t0 = time.monotonic()
    heads: Dict[str, Dict[str, Any]] = {}
    for sym in (a.symbol or list(SYMBOLS)):
        heads[sym] = run_symbol(sym, SYMBOLS[sym], root, prod, prod, logs, REPO / a.snapshot, a.skip_build)
    row = verdict_row(heads, a.unit, time.monotonic() - t0)
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(row["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# wiring: .github/workflows/feature-impact.yml (weekly + workflow_dispatch) + tests/test_feature_impact.py
"""FEATURE-IMPACT-MAP v0 -- the long table of per-feature impact, M1 (model-internal importance) only.

Design: docs/design/ui-workplan-2026-11.md section 15 (row FEATURE-IMPACT-MAP). Off-VM, no Claude, no network:
reads the committed model artifacts and writes ``comms/feature_impact/<run_id>.jsonl`` plus
``comms/feature_impact/latest.json`` (a pointer and the run's summary).

M1 SOURCES (v0): every ``ml/served/*/model.json`` and ``ml/candidates/*/model.json`` whose ``booster_txt`` holds
LightGBM model text (a string, a ``{side: text}`` map, or ``{side: [text, ...]}`` for a seed ensemble).
  * ``split_share`` -- the booster's split count per feature / total splits. Parsed from the text's
    ``feature_importances:`` block, so it needs no lightgbm import. That block LISTS ONLY FEATURES WITH >= 1 SPLIT;
    a feature in the model's ``features`` list with no split is written as value 0.0, read_state ``measured``
    (zero splits is a measured fact, not a could-not-look).
  * ``gain_share`` -- total gain per feature / total gain, via ``lightgbm.Booster(model_str=...)``. If lightgbm is
    not importable the row is written with value null and read_state ``not_computed`` -- never 0.
  * Shares are normalised WITHIN one (model, side) booster set; a seed ensemble sums its members first.
  * Population: the model's own TRAINING population, pooled over its symbols (``symbol: "pooled"``). There is no
    per-symbol M1 in a pooled model; per-symbol impact is M2's job (rank IC, NOT in v0).

NOT IN v0 (stated, not hidden): M2 model-free rank IC per symbol/asset/timeframe (needs the pooled bar store
off-VM), M3 ablation (reuse fs01 results), the registry regime models whose importances live on the trainer VM
(``ml/offload-inbox/*/model_state.json``), and SHAP/permutation on OOF data. Each is a ``coverage.not_in_v0`` entry
in latest.json so a reader cannot mistake absence for zero impact.

No halting: a model whose artifact cannot be parsed gets one ``read_state: "not_computed"`` row with the reason
and the run continues. Exit 0 unless NO model could be read (then exit 1: a run over nothing is not a pass).

    python3 scripts/research/feature_impact.py --out-dir comms/feature_impact
    python3 scripts/research/feature_impact.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
STAGE_DIRS = (("ml/served", "served"), ("ml/candidates", "candidate"))
SCHEMA = "feature_impact/1"
_IMP_RE = re.compile(r"^feature_importances:\s*$")

#: Feature family by name (v0; the catalog id is ``ml_feature.<name>``). Unknown names -> "other", never dropped.
FAMILY_RULES: Tuple[Tuple[str, str], ...] = (
    (r"^(xs_rank_|breadth_|rel_vol$|btc_)", "cross_section"),
    (r"^(ret_\d+|rsi\d+|sret_\d+)$", "momentum"),
    (r"^(vol24|vol_ratio|atr_pct|atr_ratio)$", "volatility"),
    (r"^vol_z$", "volume"),
    (r"^range_pos_", "range_position"),
    (r"^(hour|dow)$", "calendar"),
    (r"^(side|bars_held|open_r|mfe_r|mae_r|dist_sl_atr)$", "position_state"),
)


def feature_family(name: str) -> str:
    for pat, fam in FAMILY_RULES:
        if re.search(pat, name):
            return fam
    return "other"


def parse_split_counts(model_txt: str) -> Dict[str, int]:
    """The ``feature_importances:`` block of LightGBM model text -> {feature: split count}."""
    out: Dict[str, int] = {}
    on = False
    for line in model_txt.splitlines():
        if not on:
            on = bool(_IMP_RE.match(line))
            continue
        line = line.strip()
        if not line or "=" not in line or line.startswith("["):
            break
        k, _, v = line.rpartition("=")
        try:
            out[k] = out.get(k, 0) + int(v)
        except ValueError:
            break
    return out


def gain_totals(model_txt: str) -> Optional[Dict[str, float]]:
    """{feature: total gain} via lightgbm, or None when lightgbm is not importable."""
    try:
        import lightgbm as lgb  # noqa: PLC0415
    except Exception:  # allow-silent: absence is reported as read_state not_computed on every gain row
        return None
    try:
        b = lgb.Booster(model_str=model_txt)
        return {n: float(g) for n, g in zip(b.feature_name(), b.feature_importance(importance_type="gain"))}
    except Exception:  # allow-silent: an unloadable booster reports its gain rows as not_computed, splits still land
        return None


def booster_sets(model: Dict[str, Any]) -> Dict[str, List[str]]:
    """{side: [model_text, ...]} from ``booster_txt`` (str | {side: str} | {side: [str, ...]})."""
    b = model.get("booster_txt")
    if isinstance(b, str):
        return {"all": [b]}
    if isinstance(b, dict):
        return {str(s): (v if isinstance(v, list) else [v]) for s, v in b.items()}
    raise TypeError("booster_txt is neither text nor a {side: text} map")


def model_meta(model: Dict[str, Any], stage: str) -> Dict[str, Any]:
    br = model.get("bracket") or {}
    horizon = br.get("horizon_bars") or br.get("horizon_h") or model.get("horizon_h")
    eq = bool(model.get("pool_symbols")) or "EQ" in str(model.get("model_id", ""))
    return {"model_id": model.get("model_id"), "stage": stage,
            "ml_type": "tp_revision" if "tp-revision" in str(model.get("model_id")) else "entry",
            "asset_class": "us_etf" if eq else "crypto_perp",
            "venue": "alpaca" if eq else "bybit", "timeframe": "1h", "horizon_bars": horizon}


def rows_for_model(path: Path, stage: str, run_id: str, computed_at: str) -> List[Dict[str, Any]]:
    model = json.loads(path.read_text(encoding="utf-8"))
    meta = model_meta(model, stage)
    feats = [str(f) for f in (model.get("features") or [])]
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, **meta, "symbol": "pooled",
            "regime": "all", "source_artifact": str(path.relative_to(REPO)) if REPO in path.parents else str(path),
            "provenance": "MEASURED", "ci_low": None, "ci_high": None,
            "window_end": model.get("train_end_exclusive"), "n_obs": model.get("train_rows") or model.get("n_train")}
    out: List[Dict[str, Any]] = []
    for side, texts in booster_sets(model).items():
        splits: Dict[str, int] = {}
        gains: Optional[Dict[str, float]] = {}
        for t in texts:
            for k, v in parse_split_counts(t).items():
                splits[k] = splits.get(k, 0) + v
            g = gain_totals(t)
            if g is None or gains is None:
                gains = None
            else:
                for k, v in g.items():
                    gains[k] = gains.get(k, 0.0) + v
        names = feats or sorted(set(splits) | set(gains or {}))
        s_tot = float(sum(splits.values()))
        g_tot = float(sum(gains.values())) if gains else 0.0
        for f in names:
            row = {**base, "side": side, "n_boosters": len(texts), "feature_id": f"ml_feature.{f}", "feature": f,
                   "feature_family": feature_family(f)}
            out.append({**row, "measure": "split_share", "value": (splits.get(f, 0) / s_tot) if s_tot else None,
                        "raw": splits.get(f, 0), "read_state": "measured" if s_tot else "not_computed"})
            if gains is None:
                out.append({**row, "measure": "gain_share", "value": None, "raw": None, "read_state": "not_computed",
                            "reason": "lightgbm not importable, or the booster text did not load"})
            else:
                out.append({**row, "measure": "gain_share", "value": (gains.get(f, 0.0) / g_tot) if g_tot else None,
                            "raw": gains.get(f, 0.0), "read_state": "measured" if g_tot else "not_computed"})
    return out


def model_paths(root: Path) -> Iterable[Tuple[Path, str]]:
    for rel, stage in STAGE_DIRS:
        for p in sorted((root / rel).glob("*/model.json")):
            yield p, stage


def run(root: Path, out_dir: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    computed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = run_id or now.strftime("%Y%m%dT%H%MZ")
    rows: List[Dict[str, Any]] = []
    models: Dict[str, str] = {}
    for p, stage in model_paths(root):
        try:
            r = rows_for_model(p, stage, run_id, computed_at)
            rows += r
            models[str(p.relative_to(root))] = "measured"
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as a not_computed row, run continues
            rows.append({"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at,
                         "source_artifact": str(p.relative_to(root)), "stage": stage, "measure": "split_share",
                         "value": None, "read_state": "not_computed", "reason": f"{type(exc).__name__}: {exc}"})
            models[str(p.relative_to(root))] = f"not_computed: {type(exc).__name__}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{run_id}.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    measured = [r for r in rows if r.get("read_state") == "measured"]
    summary = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "file": f"{run_id}.jsonl",
               "read_state": "measured" if measured else "no_data", "n_rows": len(rows), "n_measured": len(measured),
               "models": models,
               "measures": sorted({r["measure"] for r in rows if "measure" in r}),
               "coverage": {"in_v0": "M1 split_share + gain_share for ml/served + ml/candidates LightGBM artifacts, pooled population",
                            "not_in_v0": ["M2 rank IC per symbol/asset_class/timeframe", "M3 family ablation",
                                          "registry regime models (importances on the trainer VM)", "SHAP / permutation on OOF"]}}
    (out_dir / "latest.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _self_test() -> int:
    ok = True
    txt = "tree\nfeature_importances:\na=3\nb=1\n\nparameters:\n[boosting: gbdt]\n"
    if parse_split_counts(txt) != {"a": 3, "b": 1}:
        print("  FAIL  parse_split_counts", parse_split_counts(txt))
        ok = False
    else:
        print("  PASS  split block parsed and stops at the blank line")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / "ml/candidates/x"
        d.mkdir(parents=True)
        (d / "model.json").write_text(json.dumps({"model_id": "ENTRY-EQ-x", "features": ["a", "b", "c"],
                                                  "booster_txt": {"long": [txt, txt]}}))
        bad = root / "ml/served/bad"
        bad.mkdir(parents=True)
        (bad / "model.json").write_text(json.dumps({"model_id": "bad", "features": ["a"]}))
        s = run(root, root / "out", run_id="T")
        rows = [json.loads(x) for x in (root / "out/T.jsonl").read_text().splitlines()]
        sp = {r["feature"]: r["value"] for r in rows if r.get("measure") == "split_share" and r.get("feature")}
        if abs(sp["a"] - 0.75) < 1e-9 and abs(sp["b"] - 0.25) < 1e-9 and sp["c"] == 0.0:
            print("  PASS  ensemble split shares sum members; an unsplit listed feature is a measured 0")
        else:
            print("  FAIL  shares", sp)
            ok = False
        if s["models"].get("ml/served/bad/model.json", "").startswith("not_computed") and s["read_state"] == "measured":
            print("  PASS  an unreadable artifact is a not_computed row and the run continues")
        else:
            print("  FAIL  bad artifact handling", s["models"])
            ok = False
        gains = [r for r in rows if r.get("measure") == "gain_share" and r.get("feature")]
        if all((r["value"] is None) == (r["read_state"] == "not_computed") for r in gains):
            print("  PASS  a gain row is null exactly when not_computed (never a silent 0)")
        else:
            print("  FAIL  gain null/read_state mismatch")
            ok = False
        empty = run(root / "nothing", root / "out2", run_id="E")
        if empty["read_state"] == "no_data":
            print("  PASS  a run over no artifacts reads no_data")
        else:
            print("  FAIL  empty run", empty["read_state"])
            ok = False
    print("feature_impact self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", default=str(REPO / "comms/feature_impact"))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    s = run(REPO, Path(a.out_dir), a.run_id)
    print(f"feature_impact: run={s['run_id']} read_state={s['read_state']} rows={s['n_rows']} measured={s['n_measured']}")
    return 0 if s["read_state"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())

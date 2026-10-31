#!/usr/bin/env python3
# wiring: manual-only - run deliberately when a leg's declared params or decision_bar change (the corpus
# manifest's `config_fingerprint` goes stale then); consumer: scripts/research/live_review_outcomes.py --corpus auto
"""Build a leg's FULL-HISTORY per-trade corpus for the live-trade-review option table.

Output (under ``comms/strategy_evidence/ltr_corpus/``): ``<leg>__trades.jsonl`` + ``<leg>__corpus.json``. NOT a
promotion-evidence record (the Stage-0 gate reads ``comms/strategy_evidence/<leg>.json``); it exists so a live review
prices hold / tighten / exit / scale from the leg's whole history (n >= the n_floor per cell) instead of the ~1-year
evidence window.

Two producers, both the canonical cost-complete harness (fee + slippage + funding, ``resolve_cost_policy``):

* ``harness`` - ``scripts/research/exit_lever_ablation.py`` arm ``A`` (the leg as declared in config/strategies.yaml,
  argv built by ``regime_debt_matrix.build_harness_cmd``) on a COMMITTED candle CSV. Scores the CLOSED bar.
* ``recost`` - for a leg that TRADES the forming bar (no ``decision_bar: closed``): the committed forming-arm trades of
  RQ-20261022-4de5-01 (``forming_bar_pooled_regrade``, Binance USD-M 1m proxy), re-costed from the fee that run used to
  the current Bybit-linear round-trip fee. Exits do not depend on cost, so only ``cost_fee_r`` / ``net_r`` /
  ``net_r_fee_only`` move; the fee scaling was checked 2026-10-31 against a fresh harness run: cost_fee_r agrees within 0.0013 R per trade.

Nothing is fetched (the exchange APIs are geo-blocked from research containers); a leg whose candles are not
committed is reported and skipped, never invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "comms" / "strategy_evidence" / "ltr_corpus"
FORMING_RUN = "comms/research/RQ-20261022-4de5-01"
_DROP_KEYS = {"model", "signal_prefixes", "shadow_model_ids", "execution", "enabled"}


def _read(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def recost(rows: List[Dict[str, Any]], from_bps: float, to_bps: float) -> List[Dict[str, Any]]:
    """Scale each trade's fee component from ``from_bps`` to ``to_bps`` round-trip; gross, slippage, funding unchanged."""
    k = to_bps / from_bps
    out = []
    for t in rows:
        t = dict(t)
        fee = round(float(t["cost_fee_r"]) * k, 5)
        t["cost_fee_r"] = fee
        t["net_r"] = round(float(t["gross_r"]) - fee - float(t["cost_slippage_r"]) - float(t["cost_funding_r"]), 4)
        t["net_r_fee_only"] = round(float(t["gross_r"]) - fee, 4)
        out.append(t)
    return out


def run_harness(leg: str, csv: str) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="ltr_corpus_") as td:
        cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", leg, "--arm", "A=",
               "--data-csv", str(REPO / csv), "--grade", "stage0", "--baseline", "A", "--delta-r", "1",
               "--fold-majority", "3", "--n-floor", "20", "--out", td]
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{leg}: harness exit {r.returncode}: {r.stderr[-400:] or r.stdout[-400:]}")
        return _read(Path(td) / "arms" / "A__trades.jsonl"), json.loads((Path(td) / "arms" / "A__bt.json").read_text())


def build(leg: str, mode: str, source: str, *, fee_to: float = 11.0, fee_from: float = 7.5,
          note: Optional[str] = None, write: bool = True) -> Dict[str, Any]:
    from scripts.ops.build_strategy_evidence import config_fingerprint  # type: ignore
    cfg = (yaml.safe_load((REPO / "config/strategies.yaml").read_text()).get("strategies") or {})[leg]
    if mode == "harness":
        rows, bt = run_harness(leg, source)
        produced = ("scripts/research/exit_lever_ablation.py --leg %s arm A (the leg as declared in "
                    "config/strategies.yaml; closed-bar harness)" % leg)
        costs = {k: bt.get(k) for k in ("fee_bps_roundtrip", "slippage_bps_roundtrip", "funding_bps_per_window")}
        extra = {"candles": source}
    elif mode == "recost":
        rows = recost(_read(REPO / source), fee_from, fee_to)
        produced = ("committed forming-bar arm of RQ-20261022-4de5-01 (forming_bar_pooled_regrade.leg_run, "
                    "config-exact), fee re-costed %.1f -> %.1f bps round-trip by build_ltr_corpus.recost" % (fee_from, fee_to))
        costs = {"fee_bps_roundtrip": fee_to, "slippage_bps_roundtrip": 3.0, "funding_bps_per_window": 1.0}
        extra = {"recosted_from_fee_bps_roundtrip": fee_from}
    else:
        raise ValueError(mode)
    rows.sort(key=lambda t: str(t["entry_time"]))
    body = "".join(json.dumps(t) + "\n" for t in rows)
    man = {
        "leg": leg,
        "purpose": "full-history per-trade corpus for the live-trade-review outcome table "
                   "(scripts/research/live_review_outcomes.py --corpus auto); NOT a promotion-evidence record "
                   "(the Stage-0 gate reads comms/strategy_evidence/%s.json)" % leg,
        "produced_by": produced,
        "builder": "scripts/research/build_ltr_corpus.py (mode %s)" % mode,
        "source_file": source,
        "decision_bar": cfg.get("decision_bar") or "forming",
        "data_start": str(rows[0]["entry_time"]) if rows else None,
        "data_end": str(max(str(t["exit_time"]) for t in rows)) if rows else None,
        "n_trades": len(rows),
        "net_total_r": round(sum(float(t["net_r"]) for t in rows), 4),
        **costs,
        "params": {k: v for k, v in cfg.items() if k not in _DROP_KEYS},
        "config_fingerprint": config_fingerprint(cfg),
        "trades_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "staleness": "regenerate when the leg's declared params or decision_bar change (config_fingerprint no longer "
                     "matches comms/strategy_evidence/%s.json) or when the cost stack moves" % leg,
        **extra,
    }
    if note:
        man["note"] = note
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{leg}__trades.jsonl").write_text(body)
        (OUT_DIR / f"{leg}__corpus.json").write_text(json.dumps(man, indent=2) + "\n")
    return man


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", required=True)
    ap.add_argument("--mode", choices=("harness", "recost"), required=True)
    ap.add_argument("--source", required=True, help="harness: committed candle CSV; recost: committed trades JSONL")
    ap.add_argument("--fee-to", type=float, default=11.0)
    ap.add_argument("--fee-from", type=float, default=7.5)
    ap.add_argument("--note")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(REPO))
    man = build(a.leg, a.mode, a.source, fee_to=a.fee_to, fee_from=a.fee_from, note=a.note, write=not a.dry_run)
    print(json.dumps({k: man[k] for k in ("leg", "n_trades", "net_total_r", "data_start", "data_end")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

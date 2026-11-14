#!/usr/bin/env python3
"""Refresh the GENERATED block of docs/reference/trading-pipeline-map.md (lane PIPELINE-MAP, 2026-11-14).

The pipeline map's prose (stages, code paths, how each decision-maker works) is hand-written. Its NUMBERS
(per-leg status, backtest evidence, live results, TP-doctrine compliance) go stale, so they live in one
fenced block that this script rewrites from the records:

    status     scripts/ops/strategy_status.py (DERIVED from config/accounts.yaml + config/strategies.yaml)
    backtest   comms/strategy_evidence/*.json (matched on the record's own ``strategy`` field)
    live       GET /api/bot/performance on the live web API (R only, never USD -- public repo)
    TP         scripts/ci/check_tp_doctrine.py summary lines

A live book never establishes edge: backtest and live are printed in separate columns and the block says so.
Missing values render as "—" (CLAUDE.md "render a missing/null field as —"). Every number carries a provenance
label from src/runtime/provenance.py and a dated "as of".

This is a REPORT, not a guard: it never fails CI. The weekly doc-freshness check re-runs it.

Usage:
    python3 scripts/ops/pipeline_map_numbers.py               # rewrite the block, live numbers fetched from the API
    python3 scripts/ops/pipeline_map_numbers.py --offline     # skip the API; live columns read "—" (not read)
    python3 scripts/ops/pipeline_map_numbers.py --live-json f # use a saved /api/bot/performance payload
    python3 scripts/ops/pipeline_map_numbers.py --check       # print whether the block is current; exit 0 always
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import strategy_status  # noqa: E402  (after the sys.path insert above)

try:  # the provenance vocabulary is the one source; fall back to the literals only if the import fails
    from src.runtime.provenance import (  # type: ignore
        ESTIMATED,
        MEASURED,
        UNVERIFIED,
    )
except ImportError:  # pragma: no cover
    MEASURED, ESTIMATED, UNVERIFIED = "measured", "estimated", "unverified"

DOC = REPO / "docs" / "reference" / "trading-pipeline-map.md"
BEGIN = "<!-- BEGIN GENERATED: pipeline_map_numbers.py -->"
END = "<!-- END GENERATED: pipeline_map_numbers.py -->"
API = os.environ.get("PIPELINE_MAP_API", "https://ict-bot.duckdns.org") + "/api/bot/performance?window=all"
DASH = "—"


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return DASH
    if isinstance(v, float):
        return f"{v:+.{nd}f}" if nd else f"{v:.0f}"
    return str(v)


def load_evidence() -> dict[str, dict[str, Any]]:
    """leg -> its evidence record. Keyed on the record's own ``strategy`` field (field beats filename)."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(glob.glob(str(REPO / "comms" / "strategy_evidence" / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"pipeline_map_numbers: skipped unreadable evidence record {f}: {e}", file=sys.stderr)
            continue
        leg = d.get("strategy")
        if isinstance(leg, str):
            d["_path"] = os.path.relpath(f, REPO)
            out[leg] = d
    return out


def cost_basis(ev: dict[str, Any]) -> str:
    cs = ev.get("cost_stack")
    if isinstance(cs, dict) and all(cs.get(k) is not None for k in ("fees", "slippage", "funding")):
        return "full"
    if ev.get("fee_bps_roundtrip") is not None:
        return "fee-only"
    return DASH


def fetch_live(path: str | None, offline: bool) -> tuple[dict[str, Any] | None, str]:
    if offline:
        return None, "not read (--offline)"
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8")), f"read from {path}"
    try:
        ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE"))
        with urllib.request.urlopen(urllib.request.Request(API, headers={"User-Agent": "pipeline-map"}),
                                    timeout=30, context=ctx) as r:
            return json.loads(r.read().decode("utf-8")), "read"
    except (OSError, ValueError) as e:  # unreadable is a state, never a zero
        return None, f"unreadable ({type(e).__name__})"


def per_strategy(block: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(block, dict):
        return {}
    return {r.get("name"): r for r in block.get("perStrategy") or [] if isinstance(r, dict)}


def live_cell(row: dict[str, Any] | None, read_state: str) -> str:
    if read_state != "read" and not read_state.startswith("read from"):
        return DASH
    if not row:
        return "0 trades"
    n = row.get("trades")
    rp = row.get("rProvenance") or {}
    # Every r_provenance state the route reports, so none collapse into another
    # (contaminated / confirmed_initial / unverified / no_basis).
    states = [("confirmed", rp.get("confirmedInitial")), (UNVERIFIED, rp.get("unverified")),
              ("contaminated", rp.get("contaminated")), ("no basis", rp.get("noBasis"))]
    parts = [f"{k} {v}" for k, v in states if v]
    tag = f" · R basis: {', '.join(parts)}" if parts else (" · R basis —" if not rp else "")
    return f"n={n} · ΣR {_fmt(row.get('totalR'))} · E[R] {_fmt(row.get('expectancyR'))}{tag}"


def tp_summary() -> str:
    try:
        p = subprocess.run([sys.executable, str(REPO / "scripts" / "ci" / "check_tp_doctrine.py")], cwd=REPO,
                           capture_output=True, text=True, timeout=120, check=False)
        lines = [ln.rstrip() for ln in (p.stdout + p.stderr).splitlines()
                 if ln.startswith(("population:", "  real_money", "  prop", "  mirror", "  paper"))]
        return "\n".join(lines) if lines else "unreadable (no summary lines)"
    except (OSError, subprocess.SubprocessError) as e:
        return f"unreadable ({type(e).__name__})"


def build(live_path: str | None, offline: bool) -> str:
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    status = strategy_status.table(REPO)
    strategies = strategy_status.load(REPO)[1]
    evidence = load_evidence()
    live, live_state = fetch_live(live_path, offline)
    real = per_strategy(live)
    paper = per_strategy((live or {}).get("paper"))
    trust = (live or {}).get("journalTrust") or {}

    counts: dict[str, int] = {}
    for r in status.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    order = {"production": 0, "testing": 1, "inactive": 2}

    out = [BEGIN,
           f"_Generated {today} by `scripts/ops/pipeline_map_numbers.py` — do not hand-edit this block; re-run the script._",
           "",
           f"**Population:** {len(status)} legs in `config/strategies.yaml` — "
           + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: order.get(kv[0], 9)))
           + " (status DERIVED by `scripts/ops/strategy_status.py`).",
           "",
           "**Read this table in two halves.** *Backtest* is the offline Stage-0 evidence record (the only thing that "
           "establishes edge; provenance `" + MEASURED + "` when the record's `coverage_state` is measured). *Live* is the "
           "journal's realized R from `/api/bot/performance?window=all` (lifetime window): it checks mechanics and cost, "
           "**never edge**. The live window is lifetime, so it can include trades from before a leg's current status. Live real money = the route's top-level real-money aggregate; live paper = its `paper` block. "
           f"Live read-state: **{live_state}**"
           + (f"; journal trust: known-divergent {trust.get('accountsKnownDivergent') or []}, "
              f"unrecorded {trust.get('accountsUnrecorded') or []}" if trust else "") + ".",
           "",
           "| Leg | Status | Books | Exec | Backtest net R OOS (full cost) | n OOS | Folds + | Cost basis | Stage-0 verdict | Evidence as of | Live real money (R) | Live paper (R) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for leg, row in sorted(status.items(), key=lambda kv: (order.get(kv[1]["status"], 9), kv[0])):
        ev = evidence.get(leg) or {}
        cfg = strategies.get(leg) or {}
        verdict = (ev.get("decision_rule") or {}).get("verdict") if isinstance(ev.get("decision_rule"), dict) else None
        folds = f"{ev['folds_positive']}/{ev['folds']}" if ev.get("folds_positive") is not None and ev.get("folds") else DASH
        cov = ev.get("coverage_state")
        prov = f" `{MEASURED}`" if cov == "measured" else (f" `{cov}`" if cov else "")
        net = (_fmt(ev.get("net_r_oos")) + prov) if ev.get("net_r_oos") is not None else DASH
        asof = str(ev.get("generated_at") or "")[:10] or DASH
        link = f"[{asof}](../../{ev['_path']})" if ev.get("_path") and asof != DASH else asof
        out.append("| " + " | ".join([
            f"`{leg}`", row["status"], ", ".join(row["books"]) or DASH, str(cfg.get("execution") or DASH),
            net, _fmt(ev.get("n_trades_oos")), folds, cost_basis(ev) if ev else DASH, verdict or DASH, link,
            live_cell(real.get(leg), live_state), live_cell(paper.get(leg), live_state)]) + " |")
    no_ev = sorted(leg for leg, r in status.items() if r["status"] != "inactive" and leg not in evidence)
    out += ["",
            f"**Active legs with NO evidence record** ({len(no_ev)}): " + (", ".join(f"`{x}`" for x in no_ev) or "none")
            + ". A leg without a committed record has no Stage-0 evidence on file — it is not a pass.",
            "",
            "**Evidence records naming no leg in `config/strategies.yaml`** (matched on the record's `strategy` field): "
            + (", ".join(f"`{e['_path']}` (`{k}`)" for k, e in sorted(evidence.items()) if k not in status) or "none")
            + ". Each is either a renamed leg (fix the record's `strategy` field) or a research record.",
            "",
            f"**TP doctrine compliance** (`scripts/ci/check_tp_doctrine.py`, as of {today}):",
            "", "```", tp_summary(), "```", "", END]
    return "\n".join(out)


def splice(doc: str, block: str) -> str:
    if BEGIN in doc and END in doc:
        head, rest = doc.split(BEGIN, 1)
        return head + block + rest.split(END, 1)[1]
    return doc.rstrip() + "\n\n" + block + "\n"


def _strip_stamp(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("_Generated ") and "as of 20" not in ln)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--live-json")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    block = build(a.live_json, a.offline)
    doc = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
    new = splice(doc, block)
    if a.check:
        current = _strip_stamp(doc) == _strip_stamp(new)
        print("pipeline-map numbers: CURRENT" if current else "pipeline-map numbers: STALE — re-run without --check")
        return 0
    DOC.write_text(new, encoding="utf-8")
    print(f"wrote {os.path.relpath(DOC, REPO)} ({len(block)} B generated block)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

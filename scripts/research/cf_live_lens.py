#!/usr/bin/env python3
# wiring: manual-only - CF-INSIGHTS step 6: the best ROBUST counterfactual arm per live/testing leg in R per year at its live trade frequency: python3 scripts/research/cf_live_lens.py --shards <dir> --journal <order_packages.json> --out <file>
"""cf_live_lens: for every leg that trades live or on paper, the best ROBUST arm vs the replayed harness trade, in R per YEAR at the leg's own
live trade frequency, ranked by that figure.

* corpus rows for a leg: exact strategy name first (e.g. ``trend_donchian_eth_4h``), else the family x symbol (``trend_donchian`` x ETHUSDT).
* ROBUST arm: the arm with the highest LOWER 95% bound of the week-block CI on the unique trades (not the highest mean), standard + extended
  non-entry arms only, n_unique >= MIN_N. Entry-side arms are excluded (they change whether a trade exists, so they are not a drop-in exit).
* frequency: closed packages of the leg in the journal export over its observed span, annualised (a leg with < 20 closed packages is ``thin``).
* R per year = mean_delta_r x trades/year. R is at constant money risk, so multiply by the leg's live risk per trade to get money.
Output holds strategy names, symbols and counts only (no account ids, no balances). In-sample discovery: a ranking of where to look, not a result.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


sys.path.insert(0, str(Path(__file__).resolve().parent))
import cf_insights as ci  # noqa: E402

MIN_N = 500
MIN_PKG = 20


def live_frequency(packages: Sequence[dict]) -> Dict[str, Dict[str, Any]]:
    """Per strategy: closed-package count, observed span in days, trades per year, symbol. Counts the CLOSED packages only."""
    by: Dict[str, List[dict]] = collections.defaultdict(list)
    for p in packages:
        if str(p.get("status")).lower() == "closed" and p.get("created_at"):
            by[str(p.get("strategy_name"))].append(p)
    out = {}
    for s, ps in by.items():
        ts = sorted(dt.datetime.fromisoformat(str(p["created_at"]).replace("Z", "+00:00")) for p in ps)
        span = max(30.0, (ts[-1] - ts[0]).total_seconds() / 86400.0)
        sym = collections.Counter(str(p.get("symbol")) for p in ps).most_common(1)[0][0]
        out[s] = {"n_closed": len(ps), "span_days": round(span, 1), "trades_per_year": round(len(ps) / span * 365.0, 1), "symbol": sym}
    return out


def _corpus_symbol(sym: str) -> str:
    return sym if sym.endswith("USDT") else sym


def robust_arm(rows: Sequence[dict], min_n: int = MIN_N) -> Optional[dict]:
    arms = [a for a in ci.all_arms(rows) if not a.startswith("ext_delay") and not a.startswith("ext_limit") and not a.startswith("less_without")]
    tab = ci.arm_table(rows, arms, min_n)
    tab = [t for t in tab if t["ci95"][0] > 0]
    return max(tab, key=lambda t: t["ci95"][0]) if tab else None


def lens(rows: Sequence[dict], packages: Sequence[dict]) -> List[dict]:
    uniq = ci.dedupe(rows)
    by_name: Dict[str, List[dict]] = collections.defaultdict(list)
    by_fs: Dict[tuple, List[dict]] = collections.defaultdict(list)
    for r in uniq:
        by_name[str(r["strat"])].append(r)
        by_fs[(r["fam"], r["sym"])].append(r)
    out = []
    for s, f in sorted(live_frequency(packages).items()):
        rs, basis = by_name.get(s), "exact_strategy_name"
        if not rs or len(rs) < MIN_N:
            fam = ci.family(s)
            rs, basis = by_fs.get((fam, _corpus_symbol(f["symbol"]))), "family_x_symbol"
        row = {"strategy": s, "symbol": f["symbol"], **f, "corpus_basis": basis, "n_unique_corpus": 0 if not rs else len(rs)}
        if not rs or len(rs) < MIN_N:
            row["read_state"] = "no_corpus"
        elif f["n_closed"] < MIN_PKG:
            row["read_state"] = "thin_live_frequency"
        else:
            b = robust_arm(rs)
            if b is None:
                row["read_state"] = "no_arm_with_ci_above_zero"
            else:
                row.update(read_state="ok", best_robust_arm=b["arm"], mean_delta_r=b["mean_delta_r"], ci95=b["ci95"], share_improved=b["share_improved"],
                           r_per_year=round(b["mean_delta_r"] * f["trades_per_year"], 2), r_per_year_low=round(b["ci95"][0] * f["trades_per_year"], 2))
        out.append(row)
    return sorted(out, key=lambda r: -(r.get("r_per_year_low") or -1e9))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shards", required=True)
    ap.add_argument("--journal", required=True, help="order_packages.json export (strategy_name, symbol, status, created_at); not committed")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = lens(ci.load(a.shards), json.loads(Path(a.journal).read_text()))
    Path(a.out).write_text(json.dumps({"schema": "cf_live_lens/1", "provenance": "ESTIMATED", "legs": res}, indent=1) + "\n")
    print(json.dumps({"legs": len(res), "ok": sum(1 for r in res if r.get("read_state") == "ok")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

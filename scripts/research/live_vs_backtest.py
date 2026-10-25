#!/usr/bin/env python3
"""Live-vs-backtest consistency check: does a leg's LIVE cumulative R fall inside
the range its BACKTEST predicts for the same number of trades?

    python3 scripts/research/live_vs_backtest.py                      # fetch live, Stage-2 legs
    python3 scripts/research/live_vs_backtest.py --recent-json r.json # a saved payload
    python3 scripts/research/live_vs_backtest.py --leg xrp_pullback_2h --json

THE FIRST STEP FOR ANY UNDERPERFORMING STRATEGY (operator, 2026-10-15,
verbatim: "that should be a first step for any underperforming strategy").
R4 (scripts/ops/r4_demotion_gate.py) abstains below 40 trades; this check
answers the question R4 cannot at n=7..20 -- is the live result worse than bad
luck explains -- BEFORE anyone tunes anything. It does NOT change R4's
pre-registered threshold and never edits a roster or config.

METHOD
------
* Backtest side: the per-trade ``net_r`` rows of the leg's COMMITTED Stage-0
  evidence record (``comms/strategy_evidence/<leg>.json`` -> ``source_run``),
  net of the full cost stack. Loaded exactly as ``mandate_resolver.stage0_block_p10``
  loads it (same record, same committed-in-git requirement, same
  ``T3_MIN_SOURCE_TRADES`` floor), so the two cannot disagree on the corpus.
* Distribution: i.i.d. bootstrap, ``draws`` sums of n resampled trades, n = the
  leg's live closed-trade count that has an R basis (``rTradeCount``). Fixed
  seed. Reports p5/p50/p95 and the live percentile (share of draws <= live).
* Live side: ``GET /api/bot/performance/recent?n=200`` (the canonical journal
  through the existing read path; the same ``_aggregate`` rollup R4 reads).
  ``last.totalR`` over ``rTradeCount`` rows, per book (realMoney / mirror).

VERDICTS
--------
  CONSISTENT       p5 <= live <= p95 -- keep accruing; R4 decides at its threshold
  BELOW_BACKTEST   live < p5 -- worse than bad luck explains: fidelity/regime unit
  ABOVE_BACKTEST   live > p95
  NO_BACKTEST      no committed record / source_run / enough per-trade rows -- a finding
  NO_LIVE_TRADES   nothing closed with an R basis on that book -- "could not look"
  INSUFFICIENT_N   1..MIN_N-1 live trades: the band collapses to the backtest's own
                   trade extremes, so a "verdict" would only be one trade vs another.
                   Reported with the band and a ``worse_than_worst_bt_trade`` flag (a
                   live trade worse than EVERY backtest trade is a one-line fidelity
                   lead -- slippage/gap past the stop -- not a statistical finding).

⚠️ LIMITS, stated so they are not rediscovered as surprises
* i.i.d. resampling ignores autocorrelation/regime clustering and parameter
  selection on the backtest window (``param_selection_provenance``); a
  CONSISTENT verdict is "not distinguishable from backtest luck at this n", not
  "the edge is confirmed". At tiny n the p5/p95 band is wide by construction.
* Two-sided at 5%/95% over many legs: ~10% of healthy legs flag by chance.
* Live ``totalR`` spans ``rTradeCount`` rows, a WIDER population than the
  MEASURED-USD coverage (``pnlCoverage``); both are printed. Rows with no R
  basis (UNVERIFIED) are not in ``rTradeCount`` and are never folded in.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "ops")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mandate_resolver as mr  # noqa: E402

CONSISTENT, BELOW, ABOVE = "CONSISTENT", "BELOW_BACKTEST", "ABOVE_BACKTEST"
NO_BACKTEST, NO_LIVE = "NO_BACKTEST", "NO_LIVE_TRADES"
THIN = "INSUFFICIENT_N"
#: Below this many live R trades the bootstrap band is not a test (see THIN).
MIN_N = 5
NEXT_STEP = {
    BELOW: "fidelity/regime investigation unit (research/queue)",
    CONSISTENT: "keep accruing; R4 decides at its pre-registered threshold",
    ABOVE: "keep accruing; no action",
    NO_BACKTEST: "backtest unit (build the Stage-0 evidence record)",
    NO_LIVE: "keep accruing; nothing to compare yet",
    THIN: "keep accruing; re-run at n>=%d" % MIN_N,
}
DEFAULT_URL = "https://ict-bot.duckdns.org/api/bot/performance/recent?n=200"
LOW_PCT, HIGH_PCT = 0.05, 0.95
DRAWS = 20000
SEED = 20261015


def load_backtest_r(leg: str, root: Path = REPO) -> Dict[str, Any]:
    """``{"xs": [net_r...], "why": str|None, ...}`` for the leg's Stage-0 record."""
    rel = f"{mr.EVIDENCE_DIR_REL}/{leg}.json"
    out: Dict[str, Any] = {"xs": [], "evidence_record": rel, "source_run": None,
                           "fidelity": None, "why": None}
    rec = mr._json(root / rel)
    if rec is None or not mr.in_repo(root, rel):
        out["why"] = f"no committed Stage-0 evidence record at {rel}"
        return out
    src = rec.get("source_run")
    out.update(source_run=src, fidelity=rec.get("fidelity"),
               n_trades_oos=rec.get("n_trades_oos"), net_r_oos=rec.get("net_r_oos"))
    if not isinstance(src, str) or not mr.in_repo(root, src):
        out["why"] = f"{rel} cites source_run {src!r}, which is not a committed file"
        return out
    xs: List[float] = []
    try:
        for line in (root / src).read_text(encoding="utf-8").splitlines():
            if line.strip():
                v = json.loads(line).get("net_r")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    xs.append(float(v))
    except (OSError, ValueError, AttributeError) as e:
        out["why"] = f"{src} is not a readable per-trade JSONL: {e}"
        return out
    if len(xs) < mr.T3_MIN_SOURCE_TRADES:
        out["why"] = (f"{src} carries {len(xs)} numeric net_r row(s); at least "
                      f"{mr.T3_MIN_SOURCE_TRADES} are needed to resample")
        return out
    out["xs"] = xs
    return out


def _quantile(sorted_xs: List[float], q: float) -> float:
    return sorted_xs[min(len(sorted_xs) - 1, max(0, int(q * len(sorted_xs))))]


def bootstrap_sums(xs: List[float], n: int, *, draws: int = DRAWS, seed: int = SEED) -> List[float]:
    rng = random.Random(seed)
    m = len(xs)
    return sorted(sum(xs[rng.randrange(m)] for _ in range(n)) for _ in range(draws))


def judge(live_r: float, xs: List[float], n: int, *, draws: int = DRAWS,
          seed: int = SEED) -> Dict[str, Any]:
    sums = bootstrap_sums(xs, n, draws=draws, seed=seed)
    p5, p50, p95 = (_quantile(sums, q) for q in (LOW_PCT, 0.5, HIGH_PCT))
    pct = sum(1 for s in sums if s <= live_r) / len(sums)
    verdict = BELOW if live_r < p5 else ABOVE if live_r > p95 else CONSISTENT
    return {"verdict": verdict, "live_r": round(live_r, 4), "n": n,
            "p5": round(p5, 4), "p50": round(p50, 4), "p95": round(p95, 4),
            "live_percentile": round(100 * pct, 1), "draws": draws, "seed": seed}


def check_leg(leg: str, book: str, row: Optional[Dict[str, Any]], root: Path = REPO,
              *, draws: int = DRAWS) -> Dict[str, Any]:
    """One (book, leg) verdict from the ``last`` per-strategy row of /performance/recent."""
    live = {"book": book, "leg": leg}
    r_n = (row or {}).get("rTradeCount") or 0
    live_r = (row or {}).get("totalR")
    live.update(closed=(row or {}).get("trades", 0), r_trades=r_n, live_r=live_r,
                usd_net_measured_and_estimated=(row or {}).get("totalPnlMeasured"),
                pnl_coverage_measured=(row or {}).get("pnlCoverage"))
    bt = load_backtest_r(leg, root)
    live.update(evidence_record=bt["evidence_record"], source_run=bt["source_run"],
                backtest_n=len(bt["xs"]), backtest_fidelity=bt["fidelity"],
                backtest_expectancy_r=(sum(bt["xs"]) / len(bt["xs"])) if bt["xs"] else None)
    if not bt["xs"]:
        return {**live, "verdict": NO_BACKTEST, "why": bt["why"], "next": NEXT_STEP[NO_BACKTEST]}
    if r_n < 1 or not isinstance(live_r, (int, float)) or isinstance(live_r, bool):
        return {**live, "verdict": NO_LIVE, "why": "no closed trade with an R basis on this book",
                "next": NEXT_STEP[NO_LIVE]}
    res = judge(float(live_r), bt["xs"], int(r_n), draws=draws)
    if r_n < MIN_N:
        res["verdict"] = THIN
        res["worse_than_worst_bt_trade"] = float(live_r) < min(bt["xs"]) if r_n == 1 else None
    return {**live, **res, "why": None, "next": NEXT_STEP[res["verdict"]]}


def _leg_last(recent: Dict[str, Any], key: str, leg: str) -> Optional[Dict[str, Any]]:
    ent = ((recent.get(key) or {}).get("perStrategy") or {}).get(leg) or {}
    for s in (ent.get("last") or {}).get("perStrategy") or []:
        if s.get("name") == leg:
            return s
    return None


def run(recent: Dict[str, Any], legs: List[Any], root: Path = REPO,
        *, draws: int = DRAWS) -> List[Dict[str, Any]]:
    """``legs`` is ``[(account, leg)]``; each is judged on realMoney and on the mirror."""
    out = []
    for acct, leg in legs:
        for key in ("realMoney", "mirror"):
            r = check_leg(leg, key, _leg_last(recent, key, leg), root, draws=draws)
            r["account"] = acct
            out.append(r)
    return out


def render(rows: List[Dict[str, Any]]) -> str:
    lines = ["live-vs-backtest (bootstrap of the leg's committed Stage-0 per-trade net_r; "
             f"p5/p95; seed {SEED}; i.i.d., see module docstring for limits)"]
    for r in rows:
        head = f"  {r['verdict']:15s} {r['account']:12s} {r['book']:9s} {r['leg']:24s}"
        if "p5" in r:
            lines.append(f"{head} n={r['n']:>3} live={r['live_r']:+8.2f}R  band p5={r['p5']:+.2f} "
                         f"p50={r['p50']:+.2f} p95={r['p95']:+.2f}  pct={r['live_percentile']:>5}  "
                         f"usd={r['usd_net_measured_and_estimated']} cov={r['pnl_coverage_measured']} "
                         f"bt_n={r['backtest_n']} fid={r['backtest_fidelity']} -> {r['next']}"
                         + (" [live trade worse than EVERY backtest trade]"
                            if r.get("worse_than_worst_bt_trade") else ""))
        else:
            lines.append(f"{head} {r['why']} -> {r['next']}")
    return "\n".join(lines)


def _fetch(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as resp:  # read-only GET
        return json.loads(resp.read().decode("utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--recent-json", type=Path, help="saved /performance/recent?n=200 payload")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--leg", action="append", help="restrict to these legs (default: every Stage-2 leg)")
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        recent = (json.loads(a.recent_json.read_text(encoding="utf-8")) if a.recent_json
                  else _fetch(a.url))
    except (OSError, ValueError) as e:
        print(f"error: cannot read the live payload: {e}", file=sys.stderr)
        return 2
    if recent.get("error") or any((recent.get(k) or {}).get("readState") != "ok"
                                  for k in ("realMoney", "mirror")):
        print("error: route could not read both books -- we could not look", file=sys.stderr)
        return 2
    import r4_demotion_gate as g  # noqa: E402 (imports the resolver; kept local)
    legs = g.stage2_legs(REPO)
    if a.leg:
        legs = [(acct, leg) for acct, leg in legs if leg in a.leg]
    rows = run(recent, legs, draws=a.draws)
    print(json.dumps(rows, indent=2, sort_keys=True) if a.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

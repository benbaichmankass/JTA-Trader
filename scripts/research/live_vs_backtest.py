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

THE CONFIG-DATE CUT (PERF-F1-DEMOTION-SIGNAL, 2026-11-12)
----------------------------------------------------------
A leg re-promoted on a NEW config must be compared on trades its CURRENT config
produced, against the Stage-0 record OF that config. The 2026-11-11 performance
review (C2) found ada_pullback_2h, trend_donchian_xrp_4h and
trend_donchian_sol_prop banded on 30 of 31 closes made under their pre-11-06
configs -- a band of the wrong strategy. So, per leg:

* ``config_since`` = the commit time at which the leg's CURRENT
  ``config_fingerprint`` (``scripts/ops/build_strategy_evidence.py``, the digest
  the evidence record carries) first held in ``config/strategies.yaml``, found by
  walking that file's git history newest -> oldest. A ``--since leg=ISO``
  override wins. If the walk reaches a shallow-clone boundary or the root without
  seeing the fingerprint change, the cut is ``unknown`` -- stated, never guessed,
  and the leg is then read UNCUT and labelled so.
* the live payload is fetched with ``since=<config_since>`` (one fetch per
  distinct date; the route filters rows closed at/after it before taking the
  last n). A payload that does not echo the ``since`` it was asked for (a route
  without the parameter) is NOT used as a cut read: the leg reads
  ``CUT_UNAVAILABLE`` rather than silently falling back to the uncut rows.
* the evidence record's ``config_fingerprint`` must equal the current one, else
  the backtest describes another config: ``STALE_BACKTEST``.
* Commit time is a LOWER bound on when the config ran: the trader picks the
  config up at its next restart. Trades closed between the commit and that
  restart are still inside the cut (a stated contamination, at most a restart's
  worth of closes).

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
import urllib.parse
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
STALE_BT, CUT_UNAVAILABLE = "STALE_BACKTEST", "CUT_UNAVAILABLE"
#: Below this many live R trades the bootstrap band is not a test (see THIN).
MIN_N = 5
NEXT_STEP = {
    BELOW: "fidelity/regime investigation unit (research/queue)",
    CONSISTENT: "keep accruing; R4 decides at its pre-registered threshold",
    ABOVE: "keep accruing; no action",
    NO_BACKTEST: "backtest unit (build the Stage-0 evidence record)",
    NO_LIVE: "keep accruing; nothing to compare yet",
    THIN: "keep accruing; re-run at n>=%d" % MIN_N,
    STALE_BT: "re-measure the Stage-0 record on the current config (build_strategy_evidence.py)",
    CUT_UNAVAILABLE: "deploy the /performance/recent since= read path, then re-run",
}
DEFAULT_URL = "https://ict-bot.duckdns.org/api/bot/performance/recent?n=200"
LOW_PCT, HIGH_PCT = 0.05, 0.95
DRAWS = 20000
SEED = 20261015
STRATEGIES_REL = "config/strategies.yaml"


def _strategies_at(root: Path, rev: Optional[str]) -> Optional[Dict[str, Any]]:
    import subprocess
    import yaml
    try:
        txt = ((root / STRATEGIES_REL).read_text(encoding="utf-8") if rev is None else
               subprocess.run(["git", "-C", str(root), "show", f"{rev}:{STRATEGIES_REL}"],
                              capture_output=True, text=True, check=True).stdout)
        d = yaml.safe_load(txt) or {}
    except (OSError, subprocess.CalledProcessError, yaml.YAMLError, UnicodeDecodeError):  # allow-silent: the caller ends the walk and publishes config_cut "unknown" with a why; never read as a cut
        return None
    d = d.get("strategies", d) if isinstance(d, dict) else {}
    return d if isinstance(d, dict) else None


def _utc(ts: str) -> str:
    import datetime as _dt
    return _dt.datetime.fromisoformat(ts).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_since(legs: List[str], root: Path = REPO) -> Dict[str, Dict[str, Any]]:
    """``{leg: {"since": iso|None, "state": "derived"|"unknown", "fingerprint", "why"}}``.

    ``since`` is the commit time of the OLDEST consecutive commit (walking newest ->
    oldest through ``config/strategies.yaml``'s history) whose version of the leg
    has the leg's current fingerprint. ``unknown`` when the history ends (shallow
    boundary / root) before the fingerprint ever differs."""
    import subprocess
    from build_strategy_evidence import config_fingerprint  # the digest the records carry
    cur = _strategies_at(root, None) or {}
    out = {leg: {"since": None, "state": "unknown", "why": None,
                 "fingerprint": config_fingerprint(cur.get(leg)) if cur.get(leg) else None}
           for leg in legs}
    try:
        log = subprocess.run(["git", "-C", str(root), "log", "--format=%H %cI", "--", STRATEGIES_REL],
                             capture_output=True, text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError) as e:  # allow-silent: every leg is published config_cut "unknown" with this error as its why
        for leg in legs:
            out[leg]["why"] = f"git log unavailable: {e}"
        return out
    open_legs = {leg for leg in legs if out[leg]["fingerprint"]}
    for leg in set(legs) - open_legs:
        out[leg]["why"] = f"{leg} not in {STRATEGIES_REL}"
    for line in (x for x in log if x.strip()):
        if not open_legs:
            break
        sha, ts = line.split()
        d = _strategies_at(root, sha)
        if d is None:
            break
        for leg in list(open_legs):
            fp = config_fingerprint(d.get(leg)) if d.get(leg) else None
            if fp == out[leg]["fingerprint"]:
                out[leg]["since"] = _utc(ts)
            else:
                out[leg]["state"] = "derived"
                out[leg]["changed_after"] = sha
                open_legs.discard(leg)
    for leg in open_legs:
        out[leg]["why"] = ("history ended (shallow clone or root) before the fingerprint changed; "
                           f"oldest commit seen with it: {out[leg]['since']}")
        out[leg]["since"] = None
    return out


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
    out.update(source_run=src, fidelity=rec.get("fidelity"), config_fingerprint=rec.get("config_fingerprint"),
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
              *, draws: int = DRAWS, current_fp: Optional[str] = None) -> Dict[str, Any]:
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
    if (current_fp and bt.get("config_fingerprint") and bt["config_fingerprint"] != current_fp):
        return {**live, "verdict": STALE_BT, "next": NEXT_STEP[STALE_BT],
                "why": f"evidence record fingerprint {bt['config_fingerprint']} != current config {current_fp}"}
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
        *, draws: int = DRAWS, cuts: Optional[Dict[str, Dict[str, Any]]] = None,
        cut_payloads: Optional[Dict[str, Optional[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """``legs`` is ``[(account, leg)]``; each is judged on realMoney and on the mirror.

    ``cuts`` (from ``config_since`` + overrides) and ``cut_payloads`` (``{since_iso:
    payload|None}``) apply the config-date cut; without them the read is uncut, as before."""
    out = []
    for acct, leg in legs:
        cut = (cuts or {}).get(leg) or {}
        since = cut.get("since")
        payload, cut_state = recent, "uncut"
        if cuts is not None:
            if since is None:
                cut_state = "unknown"
            else:
                p = (cut_payloads or {}).get(since)
                if p is not None and p.get("since") == since:
                    payload, cut_state = p, "applied"
                else:
                    cut_state = "unavailable"
        for key in ("realMoney", "mirror"):
            if cut_state == "unavailable":
                r = {"book": key, "leg": leg, "verdict": CUT_UNAVAILABLE, "next": NEXT_STEP[CUT_UNAVAILABLE],
                     "why": f"route did not serve since={since} (no echo); the uncut rows are not a substitute"}
            else:
                r = check_leg(leg, key, _leg_last(payload, key, leg), root, draws=draws,
                              current_fp=cut.get("fingerprint"))
            r.update(account=acct, config_cut=cut_state, config_since=since,
                     config_since_source=cut.get("source"), config_since_why=cut.get("why"))
            out.append(r)
    return out


def render(rows: List[Dict[str, Any]]) -> str:
    lines = ["live-vs-backtest (bootstrap of the leg's committed Stage-0 per-trade net_r; "
             f"p5/p95; seed {SEED}; i.i.d., see module docstring for limits)"]
    for r in rows:
        head = f"  {r['verdict']:15s} {r['account']:12s} {r['book']:9s} {r['leg']:24s}"
        if r.get("config_cut"):
            head += f" cut={r['config_cut']}" + (f"@{r['config_since']}" if r.get("config_since") else "")
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
    ap.add_argument("--no-config-cut", action="store_true",
                    help="read every leg UNCUT (the pre-2026-11-12 behaviour); the default cuts at config_since")
    ap.add_argument("--since", action="append", default=[], metavar="LEG=ISO",
                    help="override a leg's config_since (e.g. the trader restart that loaded the config)")
    ap.add_argument("--cut-json", action="append", default=[], metavar="ISO=PATH",
                    help="saved /performance/recent?n=200&since=ISO payload, instead of fetching it")
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
    cuts = cut_payloads = None
    if not a.no_config_cut:
        cuts = config_since(sorted({leg for _, leg in legs}))
        for c in cuts.values():
            c["source"] = "git:config/strategies.yaml" if c["since"] else None
        for ov in a.since:
            leg, _, iso = ov.partition("=")
            if leg in cuts and iso:
                cuts[leg].update(since=iso, state="override", source="--since", why=None)
        saved = dict(x.split("=", 1) for x in a.cut_json)
        cut_payloads = {}
        for iso in sorted({c["since"] for c in cuts.values() if c["since"]}):
            try:
                cut_payloads[iso] = (json.loads(Path(saved[iso]).read_text(encoding="utf-8")) if iso in saved
                                     else _fetch(a.url + "&since=" + urllib.parse.quote(iso)))
            except (OSError, ValueError) as e:
                print(f"warning: cut payload since={iso} unreadable: {e}", file=sys.stderr)
                cut_payloads[iso] = None
    rows = run(recent, legs, draws=a.draws, cuts=cuts, cut_payloads=cut_payloads)
    print(json.dumps(rows, indent=2, sort_keys=True) if a.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

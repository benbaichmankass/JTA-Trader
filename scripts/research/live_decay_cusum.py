#!/usr/bin/env python3
"""LIVE-DECAY-MONITOR: a one-sided CUSUM of a leg's LIVE per-trade R against its committed Stage-0 per-trade mean (Tier-1 tooling).

    python3 scripts/research/live_decay_cusum.py --leg trend_donchian_xrp_4h --out <dir>
    python3 scripts/research/live_decay_cusum.py --coverage            # which legs can be monitored, which cannot

WHY: R4 (scripts/ops/r4_demotion_gate.py) is a DEMOTION rule (two 20-trade windows) and abstains below 40 trades;
live_vs_backtest.py answers "is the cumulative result worse than luck" at one n. Neither is a sequential monitor. This is: a trip
opens a cause-naming re-research unit BEFORE the demotion rule can fire. It never edits a roster or config and never demotes.

THE DECLARED STATISTIC (fixed here, before any run; the queue template research/templates/live-decay.yaml restates it)
  Stage-0 side   per-trade ``net_r`` of the leg's committed evidence record (scripts/research/live_vs_backtest.load_backtest_r):
                 mean mu0, sd sd0, net of the full cost stack.
  Observation    x_t = live R of the t-th closed trade (oldest -> newest), or of the t-th complete BLOCK of b trades when the
                 route only serves blocks (see RESOLUTION below). Standardised z_t = (b*mu0 - x_t) / (sd0*sqrt(b)).
  Lower CUSUM    S_t = max(0, S_{t-1} + z_t - K), K = 0.25 (tuned to detect a drop of 0.5 sd0 per trade). TRIP when S_t > h.
  False alarms   ALPHA = 0.05 over HORIZON = 100 trades per leg: h is the (1-ALPHA) quantile of max_t S_t when the live trades are
                 resampled i.i.d. FROM THE LEG'S OWN Stage-0 TRADES (distribution-free, so skew and fat tails are in h), fixed seed.
                 The per-leg rate is 5% over 100 trades; across ~8 monitored legs the chance that SOME healthy leg trips is higher
                 (~1-(0.95)^8 = 34% over 100 trades each), so a trip is a re-research trigger, never a verdict.
  Grading        fail           the CUSUM tripped (or tripped earlier in the window) with >= MIN_N live trades
                 pass           no trip, >= MIN_N live trades
                 indeterminate  1..MIN_N-1 live trades / fewer than 2 complete blocks at block resolution
                 not_applicable could not look: no Stage-0 series, route unreadable, or no live series for this leg (read_state says which)

RESOLUTION. ``/api/bot/performance/recent`` serves only 20-trade blocks (fixed on purpose: R4's rule must not be re-priced by a
caller), and on 2026-11-12 no monitored leg had one complete block (live counts 0-18). So this adds the read-only
``/api/bot/performance/trade-series`` (one ``_aggregate`` row per trade, oldest first). The adapter uses it (block 1) and, until
that route is deployed (HTTP 404), falls back to 20-trade blocks of ``/performance/recent`` (CUSUM over block sums, h recalibrated
for that b and horizon), saying which in ``resolution``. Trades with no R basis are dropped from the series and counted
(``n_no_r_basis``), never folded to 0.

BASIS (JOURNAL-TRUTH). ``totalR`` is journal-net R. The route flags books whose journal is known to diverge from the venue
(``journalTrust.accountsKnownDivergent``; bybit_2 at the time of writing, the net_r double-cost defect). A venue-net series is not
available per trade, so the verdict carries ``basis: journal_net_r`` and ``basis_caveat`` naming the divergent accounts; a trip on a
divergent book is a CANDIDATE whose first re-research step is the venue-net re-read, never suppressed and never trusted blind.

LIMITS: i.i.d. resampling ignores regime clustering and parameter selection on the Stage-0 window; Stage-0 net_r is the
backtest's own cost stack; a CUSUM trip says "the live mean is below Stage-0's", not why.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import sys
import urllib.error
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[2]
for _p in (str(HERE.parent), str(REPO / "scripts" / "ops"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_vs_backtest as lvb  # noqa: E402

K = 0.25            # reference value, in sd0 units per observation
ALPHA = 0.05        # declared false-alarm probability per leg ...
HORIZON = 100       # ... over this many live trades
MIN_N = lvb.MIN_N   # live trades below which no verdict is given
SIM = 4000
SEED = 20261112
PROP_ACCOUNTS = ("breakout_2", "tradeify_1", "velotrade_1")
URL_SERIES = "https://ict-bot.duckdns.org/api/bot/performance/trade-series?n=400"
URL_BLOCK20 = lvb.DEFAULT_URL

FOLLOW_UP = ("cause-naming unit, never a config edit: name which of regime-cell drift / cost drift (realized slippage, funding) / "
             "fill-or-fidelity drift (TP/SL parity, entry timing) / config drift (roster, params vs the Stage-0 record) / "
             "journal-basis error moved the live mean; first re-read the leg on the venue-net basis")


def moments(xs: Sequence[float]) -> Tuple[float, float]:
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)
    return m, math.sqrt(var)


def cusum_path(zs: Sequence[float], k: float = K) -> List[float]:
    """Lower-sided CUSUM of already-standardised "shortfall" scores z (positive = worse than Stage-0). Pure."""
    s, out = 0.0, []
    for z in zs:
        s = max(0.0, s + z - k)
        out.append(s)
    return out


def _block_sums(xs: List[float], b: int, rng: random.Random, count: int) -> List[float]:
    m = len(xs)
    return [sum(xs[rng.randrange(m)] for _ in range(b)) for _ in range(count)]


def calibrate_h(xs: List[float], b: int = 1, *, alpha: float = ALPHA, horizon: int = HORIZON, k: float = K,
                sims: int = SIM, seed: int = SEED) -> float:
    """h such that P(max_t S_t > h) ~= alpha for ``ceil(horizon/b)`` observations drawn i.i.d. from the leg's own Stage-0 trades."""
    mu, sd = moments(xs)
    if sd <= 0:
        raise ValueError("Stage-0 series has zero variance")
    steps = max(1, math.ceil(horizon / b))
    rng = random.Random(seed)
    peaks = []
    for _ in range(sims):
        zs = [(b * mu - x) / (sd * math.sqrt(b)) for x in _block_sums(xs, b, rng, steps)]
        peaks.append(max(cusum_path(zs, k)))
    peaks.sort()
    return peaks[min(len(peaks) - 1, int((1 - alpha) * len(peaks)))]


def grade_series(xs0: List[float], live: List[float], b: int, *, h: Optional[float] = None,
                 n_trades: Optional[int] = None) -> Dict[str, Any]:
    """CUSUM verdict for one leg. ``live`` = observations oldest->newest, each the R of ``b`` trades. Pure; tested."""
    mu, sd = moments(xs0)
    n_trades = len(live) * b if n_trades is None else n_trades
    if not live:
        return {"verdict": "not_applicable", "read_state": "no_data", "n_trades": 0, "note": "no live observations"}
    if h is None:
        h = calibrate_h(xs0, b)
    zs = [(b * mu - x) / (sd * math.sqrt(b)) for x in live]
    path = cusum_path(zs)
    peak = max(path)
    tripped = [i for i, s in enumerate(path) if s > h]
    base = {"n_trades": n_trades, "n_observations": len(live), "block": b, "mu0": round(mu, 4), "sd0": round(sd, 4),
            "k": K, "h": round(h, 3), "alpha": ALPHA, "horizon_trades": HORIZON, "cusum_now": round(path[-1], 3),
            "cusum_peak": round(peak, 3), "live_mean_r": round(sum(live) / n_trades, 4),
            "first_trip_trade": (tripped[0] + 1) * b if tripped else None, "read_state": "measured"}
    if tripped and n_trades >= MIN_N:
        return {**base, "verdict": "fail",
                "note": (f"CUSUM tripped at trade ~{(tripped[0] + 1) * b} of {n_trades} (S={peak:.2f} > h={h:.2f}); live mean "
                         f"{base['live_mean_r']:+.3f}R/trade vs Stage-0 {mu:+.3f}R/trade")}
    if n_trades < MIN_N or (b > 1 and len(live) < 2):
        return {**base, "verdict": "indeterminate", "note": f"{n_trades} live trades / {len(live)} observation(s): too few to read"}
    return {**base, "verdict": "pass", "note": f"no CUSUM trip (S now {path[-1]:.2f}, peak {peak:.2f}, h={h:.2f}) over {n_trades} trades"}


def live_observations(recent: Dict[str, Any], leg: str, book: str = "realMoney") -> Dict[str, Any]:
    """``{"obs": [...oldest->newest], "b": int, "n_trades": int, "divergent": [...], "state": str}`` from a /performance/recent payload."""
    ent = ((recent.get(book) or {}).get("perStrategy") or {}).get(leg)
    if not ent:
        return {"obs": [], "b": 0, "n_trades": 0, "divergent": [], "state": "leg_not_on_book"}
    if "series" in ent:   # /performance/trade-series: one row per trade, oldest first
        div = list(((ent.get("journalTrust") or {}).get("accountsKnownDivergent")) or [])
        rs = [x.get("r") for x in ent["series"]]
        obs = [float(r) for r in rs if isinstance(r, (int, float)) and not isinstance(r, bool)]
        return {"obs": obs, "b": 1, "n_trades": len(obs), "n_no_r_basis": len(rs) - len(obs), "divergent": div,
                "state": "ok" if obs else "no_r_basis"}
    last = ent.get("last") or {}
    # route payloads nest the per-leg row under perStrategy[]; accept both shapes
    row = next((s for s in (last.get("perStrategy") or []) if s.get("name") == leg), last)
    jt = (row.get("journalTrust") or {}) if isinstance(row, dict) else {}
    div = list(jt.get("accountsKnownDivergent") or [])
    b = int(recent.get("block") or 20)
    blocks = ent.get("blocks") or []
    obs = []
    for blk in reversed(blocks):   # served newest-first
        r = next((s for s in (blk.get("perStrategy") or []) if s.get("name") == leg), blk)
        v = r.get("totalR")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and int(r.get("rTradeCount") or 0) == b:
            obs.append(float(v))
    if b == 20 and not obs:
        # no complete block: the leg's sub-20 tail is one block-less sum; refuse to pretend it is a series
        n_t = int(row.get("rTradeCount") or 0) if isinstance(row, dict) else 0
        return {"obs": [], "b": b, "n_trades": n_t, "divergent": div, "state": "no_complete_block"}
    return {"obs": obs, "b": b, "n_trades": len(obs) * b, "divergent": div, "state": "ok"}


def _load(a: "argparse.Namespace") -> Dict[str, Any]:
    if a.recent_json:
        return json.loads(a.recent_json.read_text(encoding="utf-8"))
    import urllib.error
    try:
        return lvb._fetch(a.url)
    except urllib.error.HTTPError as e:
        if e.code == 404 and a.url == URL_SERIES:     # trade-series not deployed yet: coarser, honest fallback
            return lvb._fetch(URL_BLOCK20)
        raise


def monitored_legs(root: pathlib.Path = REPO) -> List[Dict[str, Any]]:
    """Stage-2 roster legs + prop legs, de-duplicated by leg, each with the accounts it sits on. Re-parsed from config every call."""
    import r4_demotion_gate as g
    from src.config.accounts_loader import load_accounts_dict
    accts = load_accounts_dict(root / "config" / "accounts.yaml")
    legs: Dict[str, Dict[str, Any]] = {}
    for acct, leg in g.stage2_legs(root):
        legs.setdefault(leg, {"leg": leg, "accounts": [], "classes": set()})["accounts"].append(acct)
        legs[leg]["classes"].add("stage2")
    for acct in PROP_ACCOUNTS:
        for leg in ((accts.get(acct) or {}).get("strategies") or []):
            legs.setdefault(str(leg), {"leg": str(leg), "accounts": [], "classes": set()})["accounts"].append(acct)
            legs[str(leg)]["classes"].add("prop")
    out = []
    for leg in sorted(legs):
        e = legs[leg]
        out.append({"leg": leg, "accounts": sorted(set(e["accounts"])), "classes": sorted(e["classes"])})
    return out


def coverage(root: pathlib.Path = REPO) -> List[Dict[str, Any]]:
    """Per monitored leg: does it have a committed Stage-0 per-trade series (the CUSUM needs it), and can the live side be read?"""
    rows = []
    for e in monitored_legs(root):
        bt = lvb.load_backtest_r(e["leg"], root)
        on_s2 = "stage2" in e["classes"]
        rows.append({**e, "stage0_n": len(bt["xs"]), "stage0_state": "series" if bt["xs"] else "no_series",
                     "stage0_why": bt["why"],
                     "live_series": "performance/recent (realMoney book)" if on_s2 else "none on a public route (prop VM prop_fills)",
                     "monitorable": bool(bt["xs"]) and on_s2})
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--url", default=URL_SERIES)
    ap.add_argument("--recent-json", type=pathlib.Path)
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args(argv)
    if a.coverage:
        print(json.dumps(coverage(), indent=2, sort_keys=True))
        return 0
    if not a.leg or not a.out:
        ap.error("--leg and --out are required (or --coverage)")
    a.out.mkdir(parents=True, exist_ok=True)
    pop = (f"{a.leg}: live realMoney closed trades with an R basis (journal-net R) vs the leg's committed Stage-0 per-trade net_r; "
           f"lower CUSUM K={K}, false-alarm {ALPHA} over {HORIZON} trades")
    out: Dict[str, Any]
    try:
        entry = next((e for e in monitored_legs() if e["leg"] == a.leg), None)
        bt = lvb.load_backtest_r(a.leg)
        if entry is None:
            out = {"verdict": "not_applicable", "read_state": "no_data", "n_trades": None, "note": "leg is on no Stage-2 or prop roster"}
        elif not bt["xs"]:
            out = {"verdict": "not_applicable", "read_state": "no_stage0_series", "n_trades": None, "note": bt["why"],
                   "next": "backtest unit: build the Stage-0 per-trade series (the CUSUM cannot run without it)"}
        elif "stage2" not in entry["classes"]:
            out = {"verdict": "not_applicable", "read_state": "no_live_series", "n_trades": None,
                   "note": "prop-only leg: its live closes are in the prop VM's prop_fills, not on a public route -- we could not look"}
        else:
            recent = _load(a)
            if recent.get("error") or (recent.get("realMoney") or {}).get("readState") != "ok":
                raise ValueError("route could not read the realMoney book")
            lo = live_observations(recent, a.leg)
            if not lo["obs"]:
                out = {"verdict": "not_applicable" if lo["n_trades"] == 0 else "indeterminate", "read_state": lo["state"],
                       "n_trades": lo["n_trades"], "note": f"no observations at block={lo['b']}: {lo['state']}"}
            else:
                out = grade_series(bt["xs"], lo["obs"], lo["b"])
            out["resolution"] = f"block={lo['b']}" if lo["obs"] or lo["b"] else None
            if lo.get("n_no_r_basis"):
                out["n_no_r_basis"] = lo["n_no_r_basis"]
            out["basis"] = "journal_net_r"
            if lo["divergent"]:
                out["basis_caveat"] = (f"journal known-divergent from the venue on {sorted(lo['divergent'])} (JOURNAL-TRUTH, net_r double-cost "
                                       "defect): a trip here is a CANDIDATE; re-read on the venue-net basis before any cause is named")
            if out["verdict"] == "fail":
                out["demotion_candidate"] = True
                out["follow_up"] = FOLLOW_UP
    except (OSError, ValueError, urllib.error.URLError) as e:
        out = {"verdict": "not_applicable", "read_state": "no_data", "n_trades": None, "note": f"could not look: {e}"}
    out["population"] = pop
    (a.out / "verdict.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: out.get(k) for k in ("verdict", "read_state", "n_trades", "note")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

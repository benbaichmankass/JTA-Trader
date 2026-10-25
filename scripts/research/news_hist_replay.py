#!/usr/bin/env python3
"""NEWS-HIST-REPLAY step 2 -- replay the LIVE news layer over a historical corpus at historical signal times.

WHAT IT ANSWERS (WEPE gate G1, offline): does the news layer add net R on the harness trade books
-- i.e. are the signals the news layer would have VETOED / DOWNSIZED worse than the ones it left alone,
net of the full cost stack? The live arm (RQ-20261009-902, runtime_logs/news_decisions.jsonl) holds 13
veto rows in 121 days; this arm replays the same decision over years of history.

NOTHING IS RE-IMPLEMENTED. For every historical signal this imports and calls the production code:

    src.news.news_feeds.feeds_for_tags        -> which feeds (hence domains) the live path reads for the symbol
    src.news.news_normalizer.normalize_articles -> sentiment / relevance / impact / is_macro_only
    src.news.news_score.score_news            -> adjustment, veto, decision (boost/reduce/veto/neutral)
    src.news.news_influence.news_size_factor  -> the reductive downsize factor (policy mode forced to "downsize"
                                                 for the counterfactual; production mode is OFF)

The only seam is the clock: ``normalize_article`` stamps ``freshness_minutes`` from ``datetime.now()``.
``frozen_clock(t)`` swaps ``news_normalizer._freshness_minutes`` for age-at-``t`` for the duration of
one signal's evaluation (and restores it). tests/test_news_hist_replay.py pins that the swap is used.

POINT-IN-TIME RULE (no look-ahead)
  An item is visible to the signal at ``t`` iff ``available_at < t`` (strict) -- ``available_at`` is the GDELT
  ingest time (see news_hist_fetch.py), never earlier than publication. An item stamped exactly ``t`` or later is
  excluded. ``t`` = the trade row's ``entry_time`` minus ``--decision-lag-s`` (default 0).

TRADE SOURCE
  Any JSONL emitted by a costed harness' ``--emit-trades`` (rows carry strategy, symbol, direction, entry_time,
  exit_time, entry, sl, gross_r [, net_r]). Cost is RECOMPUTED here via
  ``execution_costs.resolve_cost_policy(symbol)`` + ``roundtrip_cost_r`` (fee + slippage + funding), and when the
  row already carries ``net_r`` the two are cross-checked (max |diff| is reported; a larger-than-tolerance gap
  is a refusal, not a footnote).

ARMS (all reported with n and the population)
  veto        trades the live veto would have blocked (decision == "veto"): mean net R of vetoed vs taken, the
              book's total-R delta had they been skipped, bootstrap CI on the mean difference, date-split halves.
  influence   hypothetical downsize arm: sum((factor - 1) * net_r). event_risk is 0 (no calendar in the replay).
  rank        Spearman IC between side-signed alignment (adjustment * +-1) and net R over trades with >= 1 scored
              item, plus mean net R per decision bucket.
  coverage    share of trades with >= 1 scored news item -- an arm resting on thin coverage says so.

Gaps: using the corpus ``_ledger.jsonl``, a signal whose look-back window contains ANY file not confirmed ``ok``
(missing, errored, or never fetched) is flagged ``window_gap`` and EXCLUDED from the verdict population -- it is
not counted as "no news". With no ledger the population is graded as given and the verdict says so.

Writes ``verdict.json`` (read_state: measured | insufficient_base | no_corpus | refused) -- never raises on thin data.
"""
from __future__ import annotations

import argparse
import bisect
import contextlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.news import news_normalizer as _nn  # noqa: E402
from src.news.news_feeds import feeds_for_tags  # noqa: E402
from src.news.news_influence import NewsInfluencePolicy, news_size_factor  # noqa: E402
from src.news.news_normalizer import normalize_articles  # noqa: E402
from src.news.news_score import score_news  # noqa: E402
from src.runtime import execution_costs  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_hist_fetch import DOMAIN_ALIASES, _registrable, floor15, STEP  # noqa: E402

DEFAULT_MAX_AGE_MIN = 120.0
COST_XCHECK_TOL = 1e-3


# ── time helpers ────────────────────────────────────────────────────────────
def to_dt(v: Any) -> datetime:
    s = str(v).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@contextlib.contextmanager
def frozen_clock(t: datetime) -> Iterator[None]:
    """Make the LIVE normalizer measure freshness against ``t`` instead of wall-clock now."""
    orig = _nn._freshness_minutes

    def _at(published_at: str) -> float:
        try:
            pub = to_dt(published_at)
            return max(0.0, round((t - pub).total_seconds() / 60.0, 1))
        except Exception:  # noqa: BLE001  # allow-silent: mirrors live normalizer, unparseable timestamp = maximally stale
            return 9999.0

    _nn._freshness_minutes = _at
    try:
        yield
    finally:
        _nn._freshness_minutes = orig


# ── corpus ──────────────────────────────────────────────────────────────────
class Corpus:
    """Items sorted by ``available_at`` for O(log n) point-in-time window queries."""

    def __init__(self, items: List[Dict[str, Any]]):
        items = [i for i in items if i.get("available_at")]
        items.sort(key=lambda i: i["available_at"])  # ISO-Z strings sort chronologically
        self.items = items
        self._keys = [i["available_at"] for i in items]

    @classmethod
    def load(cls, root: Path) -> "Corpus":
        rows: List[Dict[str, Any]] = []
        for p in sorted(root.rglob("*.jsonl")):
            if p.name.startswith("_"):
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return cls(rows)

    def visible(self, t: datetime, max_age_min: float) -> List[Dict[str, Any]]:
        """Items with available_at in [t - window, t) -- STRICTLY before t."""
        hi = bisect.bisect_left(self._keys, t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        lo_key = (t - timedelta(minutes=max_age_min + 15)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lo = bisect.bisect_left(self._keys, lo_key)
        return self.items[lo:hi]


def tags_for(symbol: str) -> List[str]:
    """Same derivation as src/runtime/pipeline.py (news_score phase)."""
    base = symbol.upper().split("/")[0]
    if base.endswith("USDT"):
        base = base[:-4]
    return list(dict.fromkeys(t for t in [base, symbol] if t))


def feed_domains(symbol: str) -> set:
    """Registrable domains the LIVE path reads for this symbol (feeds_for_tags + aliases)."""
    out = set()
    for u in feeds_for_tags(tags_for(symbol)):
        host = urlparse(u).hostname or ""
        if host in DOMAIN_ALIASES:
            out.update(DOMAIN_ALIASES[host])
        out.add(_registrable(host))
    return out


# ── per-signal decision ────────────────────────────────────────────────────
def decide(corpus: Corpus, symbol: str, side: str, t: datetime, *, settings: Optional[Dict[str, Any]] = None,
           max_age_min: float = DEFAULT_MAX_AGE_MIN, policy: Optional[NewsInfluencePolicy] = None,
           domains: Optional[set] = None) -> Dict[str, Any]:
    """``domains``: None -> the domains the LIVE path reads for ``symbol`` (population "live");
    a set -> exactly those (population "broad": live feeds + broad financial press, every symbol)."""
    settings = dict(settings or {})
    settings.setdefault("NEWS_MAX_AGE_MINUTES", max_age_min)
    if domains is None:
        domains = feed_domains(symbol)
    vis = [i for i in corpus.visible(t, max_age_min)
           if i["available_at"] < t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
           and (_registrable(i["source"]["name"]) in domains or i["source"]["name"] in domains)]
    with frozen_clock(t):
        normalized = normalize_articles(vis, symbol_tags=tags_for(symbol), settings=settings)
        res = score_news(normalized, settings)
    pol = policy or NewsInfluencePolicy(mode="downsize")
    factor, _rec = news_size_factor(res.adjustment, side, pol, flag_enabled=True, event_risk=0.0)
    return {"decision": res.decision, "adjustment": res.adjustment, "veto": bool(res.veto),
            "item_count": res.item_count, "n_visible": len(vis), "size_factor": factor,
            "alignment": res.adjustment * (1 if side == "buy" else -1)}


# ── trades & costs ──────────────────────────────────────────────────────────
def net_r_for(row: Dict[str, Any]) -> Tuple[float, float, Optional[float]]:
    """-> (net_r recomputed, total_cost_r, abs diff vs the row's own net_r or None)."""
    entry, sl = float(row["entry"]), float(row["sl"])
    risk = abs(entry - sl)
    g = float(row["gross_r"])
    d = 1.0 if str(row.get("direction", "")).lower() in ("long", "buy") else -1.0
    exit_px = entry + d * g * risk
    slip, fund = execution_costs.resolve_cost_policy(row["symbol"])
    cb = execution_costs.roundtrip_cost_r(entry=entry, exit_price=exit_px, risk=risk,
                                          entry_time=row["entry_time"], exit_time=row["exit_time"],
                                          slippage_bps_roundtrip=slip, funding_bps_per_window=fund)
    net = g - cb["total_cost_r"]
    diff = abs(net - float(row["net_r"])) if row.get("net_r") is not None else None
    return net, cb["total_cost_r"], diff


def load_trades(path: Path) -> List[Dict[str, Any]]:
    txt = path.read_text(encoding="utf-8").strip()
    return json.loads(txt) if txt.startswith("[") else [json.loads(ln) for ln in txt.splitlines() if ln.strip()]


# ── stats (no scipy in the runner image) ───────────────────────────────────
def _ranks(xs: Sequence[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(x: Sequence[float], y: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    """-> (rho, one-sided p for rho > 0 via the t approximation)."""
    n = len(x)
    if n < 4:
        return None, None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None, None
    rho = sxy / math.sqrt(sxx * syy)
    if abs(rho) >= 1:
        return rho, 0.0 if rho > 0 else 1.0
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    # normal approximation of the t tail (n >= ~25 in any graded use)
    p = 0.5 * math.erfc(t / math.sqrt(2))
    return rho, p


def mean(xs: Sequence[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def boot_diff_ci(a: Sequence[float], b: Sequence[float], n_boot: int = 2000, seed: int = 7):
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    ds = sorted(mean(rng.choices(a, k=len(a))) - mean(rng.choices(b, k=len(b))) for _ in range(n_boot))
    return [round(ds[int(0.025 * n_boot)], 4), round(ds[int(0.975 * n_boot)], 4)]


def _r(x: Optional[float], k: int = 4) -> Optional[float]:
    return None if x is None else round(x, k)


# ── the replay ──────────────────────────────────────────────────────────────
def replay(trades: List[Dict[str, Any]], corpus: Corpus, *, decision_lag_s: float = 0.0,
           max_age_min: float = DEFAULT_MAX_AGE_MIN, ok_files: Optional[set] = None) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    xdiffs: List[float] = []
    for tr in trades:
        net, cost, diff = net_r_for(tr)
        if diff is not None:
            xdiffs.append(diff)
        t = to_dt(tr["entry_time"]) - timedelta(seconds=decision_lag_s)
        side = "buy" if str(tr.get("direction", "")).lower() in ("long", "buy") else "sell"
        d = decide(corpus, tr["symbol"], side, t, max_age_min=max_age_min)
        gap = False
        if ok_files is not None:
            # a window is gapless only if EVERY file in it is confirmed ok in the ledger: a file that was
            # never fetched, or failed, is a gap -- "no items" and "not looked" must stay distinguishable.
            f = floor15(t - timedelta(minutes=max_age_min + 15))
            while f < t:
                if f.strftime("%Y%m%d%H%M%S") not in ok_files:
                    gap = True
                    break
                f += STEP
        rows.append({"strategy": tr.get("strategy"), "symbol": tr["symbol"], "side": side,
                     "t": t.isoformat(), "net_r": net, "cost_r": cost, "window_gap": gap, **d})
    return {"rows": rows, "cost_xcheck_max_abs_diff": _r(max(xdiffs), 6) if xdiffs else None,
            "cost_xcheck_n": len(xdiffs)}


def summarize(rep: Dict[str, Any]) -> Dict[str, Any]:
    allrows = rep["rows"]
    rows = [r for r in allrows if not r["window_gap"]]
    n = len(rows)
    out: Dict[str, Any] = {
        "population": {"n_trades_in": len(allrows), "n_excluded_window_gap": len(allrows) - n,
                       "n_with_scored_news": sum(1 for r in rows if r["item_count"] > 0),
                       "legs": sorted({f"{r['strategy']}:{r['symbol']}" for r in rows}),
                       "first": min((r["t"] for r in rows), default=None),
                       "last": max((r["t"] for r in rows), default=None)},
        "cost_xcheck_max_abs_diff": rep["cost_xcheck_max_abs_diff"], "cost_xcheck_n": rep["cost_xcheck_n"],
    }
    out["population"]["coverage_pct"] = _r(100.0 * out["population"]["n_with_scored_news"] / n, 2) if n else None
    if not n:
        out["read_state"] = "insufficient_base"
        return out
    vetoed = [r for r in rows if r["veto"]]
    taken = [r for r in rows if not r["veto"]]
    vm, tm = mean([r["net_r"] for r in vetoed]), mean([r["net_r"] for r in taken])
    srt = sorted(rows, key=lambda r: r["t"])
    half = len(srt) // 2
    halves = []
    for part in (srt[:half], srt[half:]):
        pv = [r["net_r"] for r in part if r["veto"]]
        pt = [r["net_r"] for r in part if not r["veto"]]
        halves.append({"n_vetoed": len(pv), "mean_vetoed": _r(mean(pv)), "mean_taken": _r(mean(pt))})
    out["veto"] = {
        "n_vetoed": len(vetoed), "n_taken": len(taken),
        "mean_net_r_vetoed": _r(vm), "mean_net_r_taken": _r(tm),
        "mean_diff_vetoed_minus_taken": _r(vm - tm) if vm is not None and tm is not None else None,
        "boot95_ci_diff": boot_diff_ci([r["net_r"] for r in vetoed], [r["net_r"] for r in taken]),
        "total_r_removed_by_veto": _r(sum(r["net_r"] for r in vetoed)),
        "book_total_net_r": _r(sum(r["net_r"] for r in rows)),
        "date_split_halves": halves,
    }
    out["influence"] = {
        "n_downsized": sum(1 for r in rows if r["size_factor"] < 1.0),
        "delta_total_r": _r(sum((r["size_factor"] - 1.0) * r["net_r"] for r in rows)),
        "event_risk": 0.0, "mode": "downsize (hypothetical; production mode is off)",
    }
    scored = [r for r in rows if r["item_count"] > 0]
    rho, p = spearman([r["alignment"] for r in scored], [r["net_r"] for r in scored])
    out["rank"] = {"n_scored": len(scored), "spearman_ic": _r(rho), "one_sided_p_ic_gt_0": _r(p),
                   "by_decision": {k: {"n": sum(1 for r in rows if r["decision"] == k),
                                       "mean_net_r": _r(mean([r["net_r"] for r in rows if r["decision"] == k]))}
                                   for k in ("boost", "reduce", "veto", "neutral")}}
    out["read_state"] = "measured"
    return out


# ── ARM E: signal-agnostic event study (the POWERED veto arm) ──────────────────────────────────────
# The harness trade books are too small to power the veto arm (the live veto fires on ~0.1% of
# evaluations), but the news decision depends only on (symbol, time) -- not on which strategy fired. So
# evaluate it at EVERY bar close and ask the decision-relevant question directly: after the state the live
# veto blocks, do longs (the trades it would have blocked) earn less than at baseline, net of cost?
def round_trip_cost_bps(symbol: str, hold_hours: float) -> float:
    slip, fund = execution_costs.resolve_cost_policy(symbol)
    windows = hold_hours / execution_costs.FUNDING_WINDOW_HOURS if fund else 0.0
    return execution_costs.DEFAULT_FEE_BPS_ROUNDTRIP + slip + fund * windows


def event_study(corpus: Corpus, candles, symbol: str, *, bar_minutes: int, horizon_bars: int,
                max_age_min: float = DEFAULT_MAX_AGE_MIN, ok_files: Optional[set] = None,
                start: Optional[datetime] = None, end: Optional[datetime] = None,
                domains: Optional[set] = None) -> Dict[str, Any]:
    """Decision at each bar CLOSE t (= open + bar_minutes); forward return close[i+H]/close[i] - 1.

    ``candles``: DataFrame with ``timestamp`` (bar OPEN, tz-aware) and ``close``. Overlap is handled by
    EPISODES: consecutive veto-state bars merge into one episode (anchored at its first bar; a new
    episode needs a gap > H bars). The baseline is every non-veto bar not inside an episode window,
    sub-sampled at stride H so its windows do not overlap.
    """
    ts = [to_dt(x) for x in candles["timestamp"]]
    close = [float(x) for x in candles["close"]]
    H = horizon_bars
    cost_bps = round_trip_cost_bps(symbol, H * bar_minutes / 60.0)
    obs: List[Dict[str, Any]] = []
    for i in range(0, len(ts) - H):
        t = ts[i] + timedelta(minutes=bar_minutes)  # decision at bar close
        if (start and t < start) or (end and t > end):
            continue
        if ok_files is not None:
            f, gap = floor15(t - timedelta(minutes=max_age_min + 15)), False
            while f < t:
                if f.strftime("%Y%m%d%H%M%S") not in ok_files:
                    gap = True
                    break
                f += STEP
            if gap:
                continue
        d = decide(corpus, symbol, "buy", t, max_age_min=max_age_min, domains=domains)
        ret = (close[i + H] / close[i] - 1.0) * 1e4
        obs.append({"i": i, "t": t, "ret_bps": ret, **d})
    veto_eps: List[Dict[str, Any]] = []
    last_veto_i = -10 ** 9
    for o in obs:
        if o["veto"]:
            if o["i"] - last_veto_i > H:
                veto_eps.append(o)
            last_veto_i = o["i"]
    in_window = set()
    for e in veto_eps:
        in_window.update(range(e["i"], e["i"] + H + 1))
    base = [o for o in obs if not o["veto"] and o["i"] not in in_window][::max(1, H)]
    long_net = lambda o: o["ret_bps"] - cost_bps   # noqa: E731
    short_net = lambda o: -o["ret_bps"] - cost_bps  # noqa: E731
    v_l, b_l = [long_net(o) for o in veto_eps], [long_net(o) for o in base]
    v_s, b_s = [short_net(o) for o in veto_eps], [short_net(o) for o in base]
    ordered = sorted(veto_eps, key=lambda o: o["t"])
    h = len(ordered) // 2
    halves = [{"n": len(part), "mean_long_net_bps": _r(mean([long_net(o) for o in part]), 2)}
              for part in (ordered[:h], ordered[h:])]
    sub = obs[::max(1, H)]
    sc = [o for o in sub if o["item_count"] > 0]
    rho, p = spearman([o["adjustment"] for o in sc], [o["ret_bps"] for o in sc])
    return {
        "symbol": symbol, "horizon_bars": H, "bar_minutes": bar_minutes, "cost_bps_roundtrip": _r(cost_bps, 2),
        "n_decision_bars": len(obs), "n_veto_bars": sum(1 for o in obs if o["veto"]),
        "n_veto_episodes": len(veto_eps), "n_baseline_obs": len(base),
        "veto_long": {"mean_net_bps": _r(mean(v_l), 2), "baseline_mean_net_bps": _r(mean(b_l), 2),
                      "diff_bps": _r(mean(v_l) - mean(b_l), 2) if v_l and b_l else None,
                      "boot95_ci_diff": boot_diff_ci(v_l, b_l), "date_split_halves": halves},
        "veto_short": {"mean_net_bps": _r(mean(v_s), 2), "baseline_mean_net_bps": _r(mean(b_s), 2),
                       "diff_bps": _r(mean(v_s) - mean(b_s), 2) if v_s and b_s else None,
                       "boot95_ci_diff": boot_diff_ci(v_s, b_s)},
        "rank": {"n_scored": len(sc), "n_subsampled": len(sub), "spearman_ic_adj_vs_fwd_ret": _r(rho),
                 "one_sided_p": _r(p)},
        "by_decision_bars": {k: sum(1 for o in obs if o["decision"] == k) for k in ("boost", "reduce", "veto", "neutral")},
        "first": obs[0]["t"].isoformat() if obs else None, "last": obs[-1]["t"].isoformat() if obs else None,
        "_raw": {"veto": [(o["t"].isoformat(), long_net(o), short_net(o)) for o in veto_eps],
                 "base_long": b_l, "base_short": b_s,
                 "scored": [(o["adjustment"], o["ret_bps"]) for o in sc]},
    }


# ── pooling + the PRE-REGISTERED grading rule (RQ-20261012-2a7b-01; constants mirror the unit's decision_rule) ──
N_FLOOR_E = 25        # pooled veto episodes needed to grade arm E at all
MIN_HALF = 5          # episodes needed in a date-half for the half to be evaluable
N_FLOOR_R = 200       # pooled scored observations needed to grade arm R
P_R = 0.01            # one-sided p for arm R (pooled symbols are NOT independent -> stricter than 0.05)


def pool_event_arm(per_symbol: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    veto = [v for d in per_symbol.values() for v in d["_raw"]["veto"]]
    bl = [x for d in per_symbol.values() for x in d["_raw"]["base_long"]]
    bs = [x for d in per_symbol.values() for x in d["_raw"]["base_short"]]
    sc = [x for d in per_symbol.values() for x in d["_raw"]["scored"]]
    veto.sort()
    vl, vs = [v[1] for v in veto], [v[2] for v in veto]
    h = len(veto) // 2
    halves = [{"n": len(part), "mean_long_net_bps": _r(mean([v[1] for v in part]), 2)} for part in (veto[:h], veto[h:])]
    rho, p = spearman([a for a, _ in sc], [b for _, b in sc])
    per_sym_ic = {k: d["rank"]["spearman_ic_adj_vs_fwd_ret"] for k, d in per_symbol.items()}
    return {
        "n_veto_episodes": len(veto), "n_baseline_obs": len(bl),
        "veto_long": {"mean_net_bps": _r(mean(vl), 2), "baseline_mean_net_bps": _r(mean(bl), 2),
                      "diff_bps": _r(mean(vl) - mean(bl), 2) if vl and bl else None,
                      "boot95_ci_diff": boot_diff_ci(vl, bl), "date_split_halves": halves},
        "veto_short": {"mean_net_bps": _r(mean(vs), 2), "baseline_mean_net_bps": _r(mean(bs), 2),
                       "diff_bps": _r(mean(vs) - mean(bs), 2) if vs and bs else None,
                       "boot95_ci_diff": boot_diff_ci(vs, bs)},
        "rank": {"n_scored": len(sc), "spearman_ic": _r(rho), "one_sided_p": _r(p), "per_symbol_ic": per_sym_ic},
    }


def grade_event_arm(pooled: Dict[str, Any]) -> Dict[str, str]:
    """-> {"arm_e": ..., "arm_r": ..., "g1_offline": ...}. Mechanical; mirrors the registered rule text."""
    v = pooled["veto_long"]
    n = pooled["n_veto_episodes"]
    if n < N_FLOOR_E or v["diff_bps"] is None:
        e = "INSUFFICIENT_BASE"
    else:
        ci = v["boot95_ci_diff"]
        halves_ok = all(h["n"] >= MIN_HALF and h["mean_long_net_bps"] is not None
                        and h["mean_long_net_bps"] < v["baseline_mean_net_bps"] for h in v["date_split_halves"])
        if v["diff_bps"] >= 0:
            e = "FAIL"
        elif ci is not None and ci[1] < 0 and v["mean_net_bps"] < 0 and halves_ok:
            e = "PASS"
        else:
            e = "INCONCLUSIVE"
    r = pooled["rank"]
    if r["n_scored"] < N_FLOOR_R or r["spearman_ic"] is None:
        rr = "INSUFFICIENT_BASE"
    elif r["spearman_ic"] <= 0:
        rr = "FAIL"
    else:
        pos = sum(1 for x in r["per_symbol_ic"].values() if x is not None and x > 0)
        rr = "PASS" if (r["one_sided_p"] < P_R and pos >= 2) else "INCONCLUSIVE"
    if "FAIL" in (e, rr):
        g = "RETIRE_OR_REPLACE_REVIEW"
    elif e == "PASS" and rr != "FAIL":
        g = "PASS"
    else:
        g = "OPEN"
    return {"arm_e": e, "arm_r": rr, "g1_offline": g}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trades", nargs="+", help="harness --emit-trades JSONL file(s) (trade arm)")
    ap.add_argument("--event-study", nargs="+", metavar="SYMBOL=CANDLES.csv",
                    help="signal-agnostic arm: SYMBOL=path pairs (candle CSV with timestamp,close)")
    ap.add_argument("--sources", nargs="+", choices=["live", "broad"], default=["live"],
                    help="event-study populations: live = the feeds the live path reads per symbol; broad = live + "
                         "BROAD_DOMAINS press for every symbol (secondary; cannot pass G1 by itself)")
    ap.add_argument("--bar-minutes", type=int, default=60)
    ap.add_argument("--horizon-bars", type=int, default=24)
    ap.add_argument("--corpus", required=True, help="news_hist_fetch.py output root")
    ap.add_argument("--out", required=True, help="verdict.json path")
    ap.add_argument("--decision-lag-s", type=float, default=0.0)
    ap.add_argument("--max-age-min", type=float, default=DEFAULT_MAX_AGE_MIN)
    ap.add_argument("--emit-rows", help="write per-signal decision rows JSONL here")
    a = ap.parse_args(argv)

    if not a.trades and not a.event_study:
        ap.error("give --trades and/or --event-study")
    root = Path(a.corpus)
    verdict: Dict[str, Any]
    if not root.exists() or not any(root.rglob("*.jsonl")):
        verdict = {"read_state": "no_corpus", "corpus": str(root)}
    else:
        trades: List[Dict[str, Any]] = []
        for p in a.trades or []:
            trades.extend(load_trades(Path(p)))
        led = root / "_ledger.jsonl"
        ok = ({r["file"] for r in map(json.loads, led.read_text().splitlines()) if r["status"] == "ok"}
              if led.exists() else None)
        corpus = Corpus.load(root)
        verdict = {"read_state": "measured", "ledger_present": ok is not None}
        if trades:
            rep = replay(trades, corpus, decision_lag_s=a.decision_lag_s, max_age_min=a.max_age_min, ok_files=ok)
            xd = rep["cost_xcheck_max_abs_diff"]
            if xd is not None and xd > COST_XCHECK_TOL:
                verdict = {"read_state": "refused",
                           "reason": f"recomputed net_r differs from the harness row by {xd} > {COST_XCHECK_TOL}"}
            else:
                verdict["trade_arm"] = summarize(rep)
                if a.emit_rows:
                    Path(a.emit_rows).write_text("\n".join(json.dumps(r) for r in rep["rows"]) + "\n", encoding="utf-8")
        if a.event_study and verdict["read_state"] == "measured":
            sys.path.insert(0, str(REPO / "scripts"))
            import candle_io
            from news_hist_fetch import BROAD_DOMAINS, feed_domain_allowlist
            verdict["populations"] = {}
            for pop in a.sources:
                doms = None if pop == "live" else set(BROAD_DOMAINS) | feed_domain_allowlist()
                arm = {}
                for pair in a.event_study:
                    sym, path = pair.split("=", 1)
                    df = candle_io.load_candles(path)
                    arm[sym] = event_study(corpus, df, sym, bar_minutes=a.bar_minutes, horizon_bars=a.horizon_bars,
                                           max_age_min=a.max_age_min, ok_files=ok, domains=doms)
                pooled = pool_event_arm(arm)
                grades = grade_event_arm(pooled)
                for d in arm.values():
                    d.pop("_raw", None)
                verdict["populations"][pop] = {"event_arm": arm, "event_pooled": pooled, "grades": grades}
            if "live" in verdict["populations"]:
                verdict["grades"] = verdict["populations"]["live"]["grades"]  # the graded read is the LIVE population
            if "broad" in verdict["populations"]:
                verdict["g1_offline_broad"] = verdict["populations"]["broad"]["grades"]["g1_offline"]  # informational only
        verdict["corpus"] = str(root)
        verdict["decision_lag_s"] = a.decision_lag_s
        verdict["max_age_min"] = a.max_age_min
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

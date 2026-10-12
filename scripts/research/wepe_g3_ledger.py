#!/usr/bin/env python3
# wiring: research-only - run by research queue unit RQ-20261012-wepe-g3 (research-script-run-trainer.yml); no timer, no service, no order path.
"""WEPE gate G3 on HISTORY: question contracts + resolution ledger + honest scoring.

WHY. WEPE-BUILDOUT gate G3 asks for a question-contract + resolution ledger on ONE domain (FOMC and
scheduled macro releases) scored Brier / log-loss against the base rate AND the market at matched
timestamps. Operator 2026-10-12 ("We need to be able to build that sleeve on backtesting not just live
testing"; "Start G3 backfill now"): build it on past releases instead of waiting for 25 live ones.
Research only -- nothing here feeds the macro sleeve.

WHAT. For each past release (CPI YoY, core CPI MoM, FOMC) a versioned binary question contract is
generated with a FIXED as-of time before the release (scheduled_at - AS_OF_HOURS_BEFORE). Inputs are
point-in-time by construction: only the consensus recorded for THAT release, and the surprise history of
releases dated STRICTLY BEFORE it. Forecaster v0 is declared and deliberately simple (docs below). The
resolution is the realized value. The market leg (Kalshi) is read from the off-repo trainer backfill
when --kalshi-dir is given, via the last two-sided quote with candle_end_utc <= as_of.

HONEST LIMITS (carried into the scorecard, not hidden):
  * The consensus history is `pit_basis: fxstreet_current_state` -- a third-party current-state read of a
    pre-release survey, not a vintage snapshot. Leakage of the realized value into it is possible and is
    not testable from here; the scorecard states it.
  * Headline NFP has no consensus in comms/macro/econ_calendar_snapshots*.jsonl (measured), so NFP is not
    a question family here. It appears only if a consensus source is added.
  * Third-party market data is never written to a committed file: the public ledger omits market fields.
No LLM claim extraction anywhere (WEPE gate rule).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
MACRO = REPO / "comms" / "macro"
SNAP_FILES = ("econ_calendar_snapshots_survey_backfill.jsonl", "econ_calendar_snapshots.jsonl")

CONTRACT_VERSION = 1
AS_OF_HOURS_BEFORE = 3          # fixed as-of: release instant minus 3 h (hourly Kalshi candles end on the hour)
MIN_HISTORY = 12                # a forecast needs >= this many strictly-earlier releases of the same kind
EPS = 0.01                      # probability clip for log loss (declared; applied to every arm alike)
BOOT = 2000
SEED = 20261012
RES_STEP = {"cpi_yoy": 0.1, "core_cpi_mom": 0.1, "cpi_mom": 0.1}   # reported precision (continuity correction)
KINDS = ("cpi_yoy", "core_cpi_mom", "cpi_mom", "fomc")
HOT_STEPS = (1, 2)              # CPI-family questions: actual >= consensus + k*step, for k in HOT_STEPS


# ── time / small math ────────────────────────────────────────────────────────────────────────────────
def _parse(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def clip(p: float) -> float:
    return min(1.0 - EPS, max(EPS, p))


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    p = clip(p)
    return -math.log(p if y else 1.0 - p)


# ── releases (point-in-time inputs) ──────────────────────────────────────────────────────────────────
def load_releases(macro_dir: Path = MACRO) -> List[Dict[str, Any]]:
    """One row per (kind, release date): consensus, prior, actual, scheduled_at. The live snapshot file
    wins over the survey backfill for the same (kind, date). Rows lacking any of the three numbers are
    dropped. Sorted by scheduled_at."""
    by: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for name in SNAP_FILES:                                   # later file overrides earlier
        path = macro_dir / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("kind") not in KINDS or d.get("status") != "resolved":
                continue
            if "n.s.a" in (d.get("event_name") or "").lower():
                continue    # kind cpi_mom ALSO holds the NSA index LEVEL (e.g. 334.7): not the MoM % print (measured 2026-10-12)
            exp, real = d.get("expected") or {}, d.get("realized_outcome") or {}
            cons, act, prior = exp.get("consensus"), real.get("actual"), exp.get("prior")
            if cons is None or act is None or prior is None or not d.get("scheduled_at"):
                continue
            by[(d["kind"], d["scheduled_for"])] = {
                "kind": d["kind"], "date": d["scheduled_for"], "scheduled_at": d["scheduled_at"],
                "consensus": float(cons), "prior": float(prior), "actual": float(act),
                "consensus_basis": d.get("consensus_basis") or d.get("expectation_source") or d.get("source"),
                "pit_basis": d.get("pit_basis") or "live_snapshot"}
    return sorted(by.values(), key=lambda r: (r["scheduled_at"], r["kind"]))


# ── question contracts ───────────────────────────────────────────────────────────────────────────────
def make_questions(rel: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Binary contracts for one release (WEPE design s5: versioned, explicit cutoff, named authority)."""
    sched = _parse(rel["scheduled_at"])
    as_of = _iso(sched - _dt.timedelta(hours=AS_OF_HOURS_BEFORE))
    base = {"version": CONTRACT_VERSION, "domain": "macro_release", "outcome_type": "binary",
            "forecast_cutoff": as_of, "resolution_deadline": _iso(sched + _dt.timedelta(days=1)),
            "resolution_authority": ["first print of the scheduled release as recorded in "
                                     "comms/macro/econ_calendar_snapshots*.jsonl realized_outcome.actual"],
            "status": "resolved", "kind": rel["kind"], "release_date": rel["date"],
            "release_at": rel["scheduled_at"]}
    qs: List[Dict[str, Any]] = []
    if rel["kind"] in RES_STEP:
        step = RES_STEP[rel["kind"]]
        for k in HOT_STEPS:
            thr = round(rel["consensus"] + k * step, 6)
            qs.append({**base, "template": f"{rel['kind']}_ge_cons_plus_{k}",
                       "question_id": f"wepe-g3:{rel['kind']}:{rel['date']}:ge_cons_plus_{k}",
                       "title": f"Will the first print of {rel['kind']} released {rel['date']} be >= {thr:g} "
                                f"(consensus {rel['consensus']:g} + {k}x{step:g})?",
                       "threshold": thr, "k_steps": k,
                       "resolution_criteria": f"YES iff realized first print >= {thr:g}; NO otherwise."})
    else:  # fomc: did the policy rate change vs the prior target?
        qs.append({**base, "template": "fomc_rate_changes",
                   "question_id": f"wepe-g3:fomc:{rel['date']}:rate_changes",
                   "title": f"Will the FOMC decision of {rel['date']} change the target rate from {rel['prior']:g}?",
                   "threshold": rel["prior"], "k_steps": None,
                   "resolution_criteria": "YES iff realized target-rate value differs from the prior value; NO if equal."})
    return qs


def resolve(q: Dict[str, Any], rel: Dict[str, Any]) -> int:
    if q["kind"] == "fomc":
        return int(abs(rel["actual"] - rel["prior"]) > 1e-9)
    return int(rel["actual"] >= q["threshold"] - 1e-9)


# ── Forecaster v0 + base rate (both use ONLY strictly-earlier releases) ──────────────────────────────
def _earlier(history: List[Dict[str, Any]], rel: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [h for h in history if h["kind"] == rel["kind"] and h["scheduled_at"] < rel["scheduled_at"]]


def forecast_v0(q: Dict[str, Any], rel: Dict[str, Any], history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """CPI family: actual ~ Normal(consensus, sigma), sigma = sample std of (actual - consensus) over the
    strictly-earlier releases of the kind; P(actual >= T) with a half-step continuity correction.
    FOMC: P(change) = Laplace-smoothed frequency of a change among earlier meetings whose consensus did / did
    not differ from the prior, matching this meeting's consensus-vs-prior state."""
    past = _earlier(history, rel)
    if len(past) < MIN_HISTORY:
        return None
    if rel["kind"] == "fomc":
        moved = abs(rel["consensus"] - rel["prior"]) > 1e-9
        grp = [h for h in past if (abs(h["consensus"] - h["prior"]) > 1e-9) == moved]
        ch = sum(1 for h in grp if abs(h["actual"] - h["prior"]) > 1e-9)
        return {"p_yes": (ch + 1.0) / (len(grp) + 2.0), "model": "fomc_state_freq_v0", "n_history": len(grp)}
    sur = [h["actual"] - h["consensus"] for h in past]
    mu = sum(sur) / len(sur)
    sd = math.sqrt(sum((s - mu) ** 2 for s in sur) / (len(sur) - 1))
    sd = max(sd, 0.05)
    step = RES_STEP[rel["kind"]]
    z = (q["threshold"] - 0.5 * step - rel["consensus"]) / sd
    return {"p_yes": 1.0 - norm_cdf(z), "model": "cons_centred_normal_v0", "n_history": len(sur), "sigma": round(sd, 4)}


def base_rate(q: Dict[str, Any], rel: Dict[str, Any], history: List[Dict[str, Any]]) -> float:
    """Laplace-smoothed earlier frequency of the SAME template's YES outcome (no consensus used)."""
    ys = []
    for h in _earlier(history, rel):
        for hq in make_questions(h):
            if hq["template"] == q["template"]:
                ys.append(resolve(hq, h))
    return (sum(ys) + 1.0) / (len(ys) + 2.0)


# ── market leg (Kalshi, trainer-resident, never committed) ───────────────────────────────────────────
MARKET_MAX_AGE_HOURS = 6.0       # the matched quote must be at most this old at the as-of time
MARKET_JOIN_WINDOW_HOURS = 36.0  # Kalshi event close_time must lie within this of the scheduled release
SERIES_FOR_KIND = {"cpi_mom": "KXCPI", "fomc": "KXFEDDECISION"}   # KXCPI is the MoM print (pm_surprise.KIND_SPEC)


def _pms():
    """The PM-SURPRISE-JOIN helpers (last usable two-sided quote, FOMC ladder parsing) are REUSED, not copied."""
    sys.path.insert(0, str(REPO / "scripts" / "macro"))
    import pm_surprise  # noqa: PLC0415
    return pm_surprise


class KalshiBook:
    """Per series: events (grouped backfill rows with their close_time). Lookups are by release instant."""

    def __init__(self, events_by_series: Dict[str, List[Dict[str, Any]]]):
        self.events = events_by_series
        self.miss: Dict[str, int] = {}

    def _note(self, why: str) -> None:
        self.miss[why] = self.miss.get(why, 0) + 1

    def _event(self, series: str, rel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        t0 = _parse(rel["scheduled_at"])
        best = None
        for ev in self.events.get(series, []):
            dt = abs((_parse(ev["close_time"]) - t0).total_seconds()) / 3600.0
            if dt <= MARKET_JOIN_WINDOW_HOURS and (best is None or dt < best[0]):
                best = (dt, ev)
        return best[1] if best else None

    def prob(self, q: Dict[str, Any], rel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        series = SERIES_FOR_KIND.get(rel["kind"])
        if not series:
            return None                                  # no matching Kalshi series (cpi_yoy, core_cpi_mom)
        ev = self._event(series, rel)
        if ev is None:
            self._note(f"{series}:no_event_in_window")
            return None
        pms = _pms()
        quotes = pms.last_quotes(ev["rows"], q["forecast_cutoff"])      # candle_end_utc <= as-of, two-sided only
        asof = _parse(q["forecast_cutoff"])
        quotes = {m: v for m, v in quotes.items()
                  if (asof - _parse(v[0])).total_seconds() / 3600.0 <= MARKET_MAX_AGE_HOURS}
        if rel["kind"] == "fomc":
            hold = [v for m, v in quotes.items() if pms.fomc_delta_bps(m) == 0.0]
            if not hold:
                self._note("KXFEDDECISION:no_fresh_hold_quote")
                return None
            ce, mid, row = hold[0]
            return {"p": 1.0 - mid, "quote_candle_end_utc": ce, "market_id": row["market_id"]}
        want = round(q["threshold"] - RES_STEP[rel["kind"]], 6)         # P(X > want) == P(printed >= threshold)
        for m, (ce, mid, row) in quotes.items():
            if row.get("strike_type") == "greater" and row.get("floor_strike") is not None \
                    and abs(float(row["floor_strike"]) - want) < 1e-6:
                return {"p": mid, "quote_candle_end_utc": ce, "market_id": m}
        self._note(f"{series}:no_fresh_two_sided_quote_at_strike")
        return None


def build_kalshi(path: Optional[Path]) -> Optional[KalshiBook]:
    if not path:
        return None
    pms = _pms()
    ev_by: Dict[str, List[Dict[str, Any]]] = {}
    for series in SERIES_FOR_KIND.values():
        f = Path(path) / f"{series}.jsonl"
        if not f.exists():
            continue
        by: Dict[str, List[Dict[str, Any]]] = {}
        for r in pms.read_jsonl(f):
            by.setdefault(r["event_ticker"], []).append(r)
        ev_by[series] = [{"event_ticker": e, "close_time": min(r["close_time"] for r in rs), "rows": rs}
                         for e, rs in by.items()]
    return KalshiBook(ev_by)


def market_prob(q: Dict[str, Any], rel: Dict[str, Any], kalshi: Optional[KalshiBook]) -> Optional[Dict[str, Any]]:
    return kalshi.prob(q, rel) if kalshi else None


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────
def boot_ci(diffs: List[float], clusters: Optional[List[Any]] = None, seed: int = SEED) -> Optional[Tuple[float, float]]:
    """95% bootstrap interval of the mean of `diffs`. When `clusters` is given (one id per diff) whole
    clusters are resampled: CPI k=1 and k=2 questions of one release are NOT independent draws."""
    if len(diffs) < 2:
        return None
    rng = random.Random(seed)
    if clusters is None:
        clusters = list(range(len(diffs)))
    groups: Dict[Any, List[float]] = {}
    for d, c in zip(diffs, clusters):
        groups.setdefault(c, []).append(d)
    gl = list(groups.values())
    if len(gl) < 2:
        return None
    means = []
    for _ in range(BOOT):
        tot = cnt = 0
        for _ in gl:
            g = gl[rng.randrange(len(gl))]
            tot += sum(g)
            cnt += len(g)
        means.append(tot / cnt)
    means.sort()
    return means[int(0.025 * BOOT)], means[int(0.975 * BOOT) - 1]


def score(rows: List[Dict[str, Any]], arm: str, ref: str) -> Dict[str, Any]:
    """Mean Brier / log loss of `arm` vs `ref` over rows where BOTH exist; lower is better.
    diff = ref - arm (positive => arm better); 95% interval by release-clustered bootstrap."""
    sub = [r for r in rows if r.get(arm) is not None and r.get(ref) is not None]
    out: Dict[str, Any] = {"arm": arm, "ref": ref, "n": len(sub),
                           "n_releases": len({(r["question"]["kind"], r["question"]["release_date"])
                                              for r in sub}) if sub and "question" in sub[0] else None}
    if not sub:
        return out
    cl = [(r["question"]["kind"], r["question"]["release_date"]) if "question" in r else i for i, r in enumerate(sub)]
    for name, fn in (("brier", brier), ("logloss", logloss)):
        a = [fn(r[arm], r["y"]) for r in sub]
        b = [fn(r[ref], r["y"]) for r in sub]
        d = [bb - aa for aa, bb in zip(a, b)]
        ci = boot_ci(d, cl)
        out[name] = {"arm_mean": round(sum(a) / len(a), 5), "ref_mean": round(sum(b) / len(b), 5),
                     "ref_minus_arm": round(sum(d) / len(d), 5),
                     "ci95": [round(ci[0], 5), round(ci[1], 5)] if ci else None}
    return out


def calibration(rows: List[Dict[str, Any]], arm: str, bins: int = 5) -> List[Dict[str, Any]]:
    sub = [r for r in rows if r.get(arm) is not None]
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        b = [r for r in sub if lo <= r[arm] < hi or (i == bins - 1 and r[arm] == 1.0)]
        if b:
            out.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": len(b),
                        "mean_p": round(sum(r[arm] for r in b) / len(b), 4),
                        "freq_yes": round(sum(r["y"] for r in b) / len(b), 4)})
    return out


# ── ledger build ─────────────────────────────────────────────────────────────────────────────────────
def build_ledger(releases: List[Dict[str, Any]], kalshi: Optional[KalshiBook] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rel in releases:
        for q in make_questions(rel):
            f = forecast_v0(q, rel, releases)
            if f is None:
                continue                              # not enough strictly-earlier history: no forecast issued
            m = market_prob(q, rel, kalshi) if kalshi else None
            rows.append({"question": q, "forecast": {**f, "as_of": q["forecast_cutoff"]},
                         "p_model": round(f["p_yes"], 6), "p_base": round(base_rate(q, rel, releases), 6),
                         "p_market": None if m is None else round(m["p"], 6), "market_meta": m,
                         "y": resolve(q, rel),
                         "resolution": {"actual": rel["actual"], "consensus": rel["consensus"], "prior": rel["prior"],
                                        "resolved_value_source": "comms/macro/econ_calendar_snapshots*.jsonl"},
                         "provenance": {"consensus_basis": rel["consensus_basis"], "pit_basis": rel["pit_basis"]}})
    return rows


def leakage_check(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every forecast's as-of must be strictly before its release; every market quote at or before as-of;
    history used must be strictly earlier (enforced structurally by _earlier; asserted again here)."""
    bad_asof = [r["question"]["question_id"] for r in rows
                if not _parse(r["question"]["forecast_cutoff"]) < _parse(r["question"]["release_at"])]
    bad_mkt = [r["question"]["question_id"] for r in rows if r.get("market_meta")
               and not _parse(r["market_meta"]["quote_candle_end_utc"]) <= _parse(r["question"]["forecast_cutoff"])]
    return {"asof_not_before_release": bad_asof, "market_quote_after_asof": bad_mkt,
            "ok": not bad_asof and not bad_mkt}


def scorecard(rows: List[Dict[str, Any]], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    by_t: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_t.setdefault(r["question"]["template"], []).append(r)
    card: Dict[str, Any] = {
        "n_questions": len(rows),
        "n_releases": len({(r["question"]["kind"], r["question"]["release_date"]) for r in rows}),
        "by_template_n": {t: len(v) for t, v in sorted(by_t.items())},
        "yes_rate": round(sum(r["y"] for r in rows) / len(rows), 4) if rows else None,
        "model_vs_base": score(rows, "p_model", "p_base"),
        "model_vs_market": score(rows, "p_model", "p_market"),
        "market_vs_base": score(rows, "p_market", "p_base"),
        "calibration_model": calibration(rows, "p_model"),
        "per_template_model_vs_base": {t: score(v, "p_model", "p_base") for t, v in sorted(by_t.items())},
        "cpi_family_model_vs_base": score([r for r in rows if r["question"]["kind"] != "fomc"], "p_model", "p_base"),
        "fomc_model_vs_base": score([r for r in rows if r["question"]["kind"] == "fomc"], "p_model", "p_base"),
        "model_vs_market_by_kind": {k: score([r for r in rows if r["question"]["kind"] == k], "p_model", "p_market")
                                    for k in sorted({r["question"]["kind"] for r in rows})},
        "leakage": leakage_check(rows),
        "limits": ["consensus pit_basis is fxstreet_current_state (not a vintage snapshot); leakage of the "
                   "realized value into it cannot be tested here",
                   "headline NFP has no consensus in comms/macro/econ_calendar_snapshots*.jsonl: not scored",
                   "CPI questions at k=1 and k=2 share a release: questions are not independent",
                   "log-loss clips probabilities to [%.2f, %.2f] for every arm" % (EPS, 1 - EPS)]}
    if extra:
        card.update(extra)
    return card


# ── verdict, per the rule registered in research/queue/RQ-20261012-wepe-g3.yaml BEFORE the run ────────
MIN_QUESTIONS = 25
MIN_MARKET_MATCHED = 25


def _claim(sc: Dict[str, Any]) -> str:
    """Brier-only reading of a ref-minus-arm interval: supported / opposite / not distinguishable / no data."""
    b = sc.get("brier")
    if not b or not b.get("ci95"):
        return "no_data"
    lo, hi = b["ci95"]
    return "model_better" if lo > 0 else ("model_worse" if hi < 0 else "not_distinguishable")


def verdict(card: Dict[str, Any]) -> Dict[str, Any]:
    n, nm = card["n_questions"], card["model_vs_market"]["n"]
    leak = card["leakage"]["ok"]
    if not leak:
        v, why = "fail", "leakage check failed: " + json.dumps(card["leakage"])
    elif n < MIN_QUESTIONS:
        v, why = "indeterminate", f"{n} resolved questions < {MIN_QUESTIONS}"
    elif nm < MIN_MARKET_MATCHED:
        v, why = "indeterminate", f"{nm} market-matched questions < {MIN_MARKET_MATCHED}: market arm not scored (instrument incomplete)"
    else:
        v, why = "pass", f"ledger valid: {n} questions, {nm} market-matched, leakage clean; all three arms scored"
    claims = {"cpi_family_model_vs_base": _claim(card["cpi_family_model_vs_base"]),
              "fomc_model_vs_base": _claim(card["fomc_model_vs_base"]),
              "model_vs_market_pooled": _claim(card["model_vs_market"]),
              "market_vs_base_pooled": _claim(card["market_vs_base"])}
    return {"verdict": v, "read_state": "measured" if v != "indeterminate" or n >= MIN_QUESTIONS else "no_data",
            "population": f"{card['n_releases']} past releases (CPI YoY / core CPI MoM / CPI MoM / FOMC), "
                          f"{n} binary questions, as-of release-{AS_OF_HOURS_BEFORE}h; {nm} Kalshi-matched",
            "n": n, "note": why,
            "measurement": {"n_market_matched": nm, "claims_brier_ci95_release_clustered": claims,
                            "caveat": card["limits"][0]}}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--macro-dir", type=Path, default=MACRO)
    ap.add_argument("--kalshi-dir", type=Path, default=None, help="trainer-resident pm_backfill/kalshi (optional)")
    ap.add_argument("--out-dir", "--out", type=Path, required=True)
    ap.add_argument("--unit", default=None, help="queue unit id (informational)")
    a = ap.parse_args(argv)
    releases = load_releases(a.macro_dir)
    kdir = a.kalshi_dir
    if kdir is not None and str(kdir) == "auto":      # trainer-resident, off-repo
        sys.path.insert(0, str(REPO))
        from src.utils.paths import data_dir  # noqa: PLC0415
        kdir = data_dir() / "pm_backfill" / "kalshi"
        if not kdir.exists():
            print(f"kalshi dir {kdir} not found: market arm unscored", file=sys.stderr)
            kdir = None
    kalshi = build_kalshi(kdir) if kdir else None
    rows = build_ledger(releases, kalshi)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    pub = []
    for r in rows:      # public ledger: no third-party market fields
        p = {k: v for k, v in r.items() if k not in ("p_market", "market_meta")}
        p["market_matched"] = r["p_market"] is not None
        pub.append(p)
    (a.out_dir / "ledger_public.jsonl").write_text("".join(json.dumps(p, sort_keys=True) + "\n" for p in pub))
    card = scorecard(rows, {"releases_loaded": len(releases), "kalshi_dir_given": bool(kdir),
                            "market_unmatched_reasons": dict(sorted(kalshi.miss.items())) if kalshi else None,
                            "market_matched_by_template": {t: sum(1 for r in rows if r["question"]["template"] == t
                                                                  and r["p_market"] is not None)
                                                           for t in sorted({r["question"]["template"] for r in rows})}})
    (a.out_dir / "scorecard.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    v = verdict(card)
    (a.out_dir / "verdict.json").write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
    print(json.dumps(v, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

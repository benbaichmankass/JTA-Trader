# wiring: imported by scripts/ops/live_replay_parity.py (resolve_legs / fetch_bundle / run); the workflow
# .github/workflows/live-replay-parity.yml runs it weekly through that script. Row ML-LIVE-PARITY-ML-LEGS.
"""LIVE-vs-REPLAY PARITY for the ML legs (``ml_entry``, ``ml_entry_eq_struct``).

The technical legs are replayed frame-by-frame by ``live_replay_parity.analyse_leg``. The two ML legs decide
differently, so each gets the replay that matches how it decides (offline, read-only, Tier 1; nothing here touches
the order path):

``ml_entry`` (closed 1h bars, every 4th close, one decision per symbol per bar)
    Live writes one ``ml_entry_eval`` audit row per decision: a package row (entry / stop / take-profit /
    ``p_long`` / ``p_short``) or a refusal whose reason carries the model's inputs (``p_long``, ``p_short``,
    ``n_ref`` and the 20-feature vector ``feat=``). The replay rebuilds the symbol's closed frame and the
    cross-sectional reference frames from the bot's own candles (``/api/bot/candles``, same source) cut at the
    decision bar, runs the LIVE ``ml_entry.order_package`` with the served artifact, and diffs, in this order:
    reference count -> feature vector -> scores -> decision -> package geometry. The first level that differs is
    the class, so a wrong-candle frame (``ml_feature_mismatch``) is never read as a model bug
    (``ml_score_mismatch``).

``ml_entry_eq_struct`` (pool snapshot per decision close)
    Live scores the whole pool from one snapshot file the refresher writes; since #24889 each decision close's
    snapshot is archived (``<data>/ml_entry_eq/history/<bar>.json``, read here through
    ``/api/diag/ml_pool_snapshots``). The replay re-scores each archived snapshot with the LIVE
    ``ml_entry_eq.score_pool`` (same artifact, same leg config) and diffs the set of packages against the live
    ``ml_entry_eq_struct_eval`` rows of that close: a package the replay holds that live never emitted
    (``ml_missed_package``), a live package the replay cannot produce (``ml_live_only_package``), or the same
    symbol with different geometry (``ml_package_mismatch``). Live logs refusals only to the journal
    (INFO), not to the audit store, so the refusal side is NOT diffed -- the artifact says so.

COLLAPSED STATES: a leg with nothing it could compare is ``could_not_check`` with the reason and ``divergences:
null`` -- an empty / unreadable fetch is never ``0 divergences``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

ML_UNITS = {"ml_entry": "ml_entry", "ml_entry_eq": "ml_entry_eq"}   # builder monitor_unit (or leg name) -> replay kind
ML_LEGS = ("ml_entry", "ml_entry_eq_struct")

ML_CLASSES = ("lost_bar", "ml_feature_mismatch", "ml_score_mismatch", "ml_side_mismatch", "ml_package_mismatch",
              "ml_refusal_mismatch", "ml_missed_package", "ml_live_only_package")

#: Printed precision of the live audit tail is 5 dp (features) / 4-5 dp (scores); one unit in the last place plus slack.
FEAT_TOL = 2e-5
SCORE_TOL = 2e-4
GEOM_REL = 1e-6
#: A live decision lands within this long after the decision bar closes (retries on a pending reference set included).
LIVE_DECISION_WINDOW_S = 3 * 3600
#: The first reference frame ``min_reference_symbols`` refusal is real; below this many replayable reference frames the
#: replay itself is not a trustworthy comparator, so the bar is reported not_comparable.
BAR_S = 3600


def _epoch(v: Any) -> float | None:
    from scripts.ops.live_replay_parity import to_epoch
    return to_epoch(v)


def _iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _norm_side(s: Any) -> str:
    from scripts.ops.live_replay_parity import norm_side
    return norm_side(s)


def _close(a: float, b: float, rel: float = GEOM_REL) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


# ── reason parsing (the live audit tail and the replay's refusal text share one grammar) ─────────────────────────

_KV = re.compile(r"(p_long|p_short|tau|pred|n_ref)=(-?[0-9.]+(?:e-?[0-9]+)?)")


def parse_reason(reason: str | None) -> dict:
    """``{head, p_long, p_short, n_ref, feat[20], own_bar}`` from a below_tau / cost_gate refusal; ``head`` is the text
    before the first ``:`` / ``;`` (the named refusal)."""
    r = str(reason or "")
    out: dict = {"head": re.split(r"[:;]", r, maxsplit=1)[0], "feat": None, "own_bar": None}
    for k, v in _KV.findall(r):
        try:
            out[k] = float(v)
        except ValueError:
            pass
    m = re.search(r";feat=([^;]*)", r)
    if m:
        try:
            out["feat"] = [float(x) for x in m.group(1).split(",")]
        except ValueError:
            out["feat"] = None
    m = re.search(r";own_bar=([0-9T:\-]+)\|", r)
    if m:
        out["own_bar"] = m.group(1)
    return out


# ── ml_entry ─────────────────────────────────────────────────────────────────

def _frame(candles: list[dict]):
    import pandas as pd
    df = pd.DataFrame(candles)
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]].sort_values("ts").reset_index(drop=True)


def decision_bars(since: float, until: float, every_h: int = 4) -> list[float]:
    """Bar OPEN epochs of the 1h bars whose CLOSE is a decision close and falls in [since, until)."""
    out = []
    t = (int(since) // BAR_S) * BAR_S
    while t < until:
        close = t + BAR_S
        if since <= close < until and datetime.fromtimestamp(close, tz=timezone.utc).hour % every_h == 0:
            out.append(float(t))
        t += BAR_S
    return out


def _live_decisions(rows: list[dict], strategy: str) -> dict[tuple[str, float], dict]:
    """``{(symbol, bar_open_epoch): first live eval row}`` -- the bar comes from the audit tail's own_bar when printed,
    else from the time the row was written (the tick that follows a close evaluates the bar that just closed)."""
    out: dict[tuple[str, float], dict] = {}
    for r in sorted(rows, key=lambda x: _epoch(x.get("logged_at_utc")) or 0.0):
        if r.get("event") != f"{strategy}_eval":
            continue
        if str(r.get("reason") or "") == "not_a_decision_bar":
            continue
        t = _epoch(r.get("logged_at_utc"))
        if t is None:
            continue
        p = parse_reason(r.get("reason"))
        bar = _epoch((p["own_bar"] + ":00+00:00")) if p.get("own_bar") else None
        if bar is None:
            bar = float((int(t) // BAR_S) * BAR_S - BAR_S)
        out.setdefault((str(r.get("symbol")), bar), r)
    return out


ARTIFACT_DEPLOY_GRACE_S = 1800   # git-sync (~5 min) + trader restart after a served-pointer commit


def served_epoch(repo: Any = None) -> float | None:
    """Commit time of the last change to the ONE served-entry pointer (``ml/served/ENTRY_SERVED.json``), or None when git cannot
    say. A decision made before it (plus the deploy grace) was scored by a DIFFERENT artifact than the one the replay loads, so it
    is not comparable -- it is reported as such, never as a score mismatch."""
    import subprocess
    from pathlib import Path
    root = Path(repo) if repo else Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%ct", "--", "ml/served/ENTRY_SERVED.json"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _entry_replay(cfg: Mapping, symbol: str, bar: float, frames: Mapping[str, Any], model: Mapping, PR: Any) -> dict:
    """The LIVE ml_entry.order_package on the frame cut at ``bar``; returns {side, reason|pkg, ...}."""
    import pandas as pd
    from src.units.strategies import ml_entry as ME
    T = pd.Timestamp(bar, unit="s", tz="UTC")
    own = frames.get(symbol)
    if own is None:
        return {"error": f"no candles for {symbol}"}
    cut = {s: f[f["ts"] <= T].iloc[-400:].reset_index(drop=True) for s, f in frames.items() if f is not None}
    df = cut[symbol]
    if len(df) == 0 or df["ts"].iloc[-1] != T:
        return {"error": f"replay frame has no closed bar {T.isoformat()} (candle reach)"}
    prof = PR.resolve(dict(cfg), symbol, ME.NAME)
    c = {"symbol": symbol, "timeframe": "1h", **cfg, "_profile": prof}
    refs = {s: f for s, f in cut.items() if s != symbol}
    try:
        pkg = ME.order_package(c, candles_df=df, reference_frames=refs, model=dict(model))
    except ValueError as exc:
        return {"side": "none", "reason": str(exc), "parsed": parse_reason(str(exc))}
    return {"side": _norm_side(pkg["direction"]), "pkg": pkg, "parsed": {
        "p_long": pkg["meta"]["p_long"], "p_short": pkg["meta"]["p_short"], "n_ref": pkg["meta"]["n_reference"],
        "feat": None, "head": "package"}}


def _rep_cached(bundle: Mapping, cfg: Mapping, sym: str, bar: float, frames: Mapping, model: Mapping, PR: Any,
                use_cache: bool = True) -> dict:
    """One replay is ~0.5 s (60 reference frames of features); the controls re-analyse the same bars several times, so the
    decision is memoised on the bundle (its frames never change within a run)."""
    if not use_cache or not isinstance(bundle, dict):
        return _entry_replay(cfg, sym, bar, frames, model, PR)
    cache = bundle.setdefault("_ml_rep_cache", {})
    k = (sym, bar)
    if k not in cache:
        cache[k] = _entry_replay(cfg, sym, bar, frames, model, PR)
    return cache[k]


def compare_entry(live: Mapping, rep: Mapping) -> tuple[str | None, dict]:
    """(class | None, detail) for one (symbol, bar): the first level that differs wins."""
    lp = parse_reason(live.get("reason"))
    rp = rep.get("parsed") or {}
    l_side = _norm_side(live.get("side"))
    r_side = rep.get("side")
    live_is_pkg = l_side != "none"
    # 1. inputs: reference count, feature vector (only when BOTH sides printed one)
    if lp.get("n_ref") is not None and rp.get("n_ref") is not None and int(lp["n_ref"]) != int(rp["n_ref"]):
        return "ml_feature_mismatch", {"what": "n_ref", "live": int(lp["n_ref"]), "replay": int(rp["n_ref"])}
    if lp.get("feat") and rp.get("feat"):
        if len(lp["feat"]) != len(rp["feat"]):
            return "ml_feature_mismatch", {"what": "feature_count", "live": len(lp["feat"]), "replay": len(rp["feat"])}
        bad = [(i, a, b) for i, (a, b) in enumerate(zip(lp["feat"], rp["feat"])) if abs(a - b) > FEAT_TOL]
        if bad:
            return "ml_feature_mismatch", {"what": "features", "n_differ": len(bad),
                                           "first": [{"i": i, "live": a, "replay": b} for i, a, b in bad[:4]]}
    # 2. scores
    for k in ("p_long", "p_short"):
        a = lp.get(k) if not live_is_pkg else live.get(k)
        b = rp.get(k)
        if a is not None and b is not None and abs(float(a) - float(b)) > SCORE_TOL:
            return "ml_score_mismatch", {"what": k, "live": float(a), "replay": float(b)}
    # 3. decision
    if not live_is_pkg and r_side != "none" and lp["head"] not in ("below_tau", "cost_gate"):
        # live REFUSED for a non-model reason (feature_row_unformable, reference_symbols, insufficient_bars ...) where the
        # replay, from the same candles, decides: a degraded live input, reported as its own class
        return "ml_refusal_mismatch", {"live": lp["head"], "live_reason": str(live.get("reason"))[:120], "replay": r_side}
    if live_is_pkg or r_side != "none":
        if live_is_pkg != (r_side != "none"):
            return "ml_side_mismatch", {"live": l_side, "replay": r_side, "live_reason": str(live.get("reason"))[:120],
                                        "replay_reason": str(rep.get("reason"))[:120]}
        if l_side != r_side:
            return "ml_side_mismatch", {"live": l_side, "replay": r_side}
        # 4. geometry
        pkg = rep["pkg"]
        for lk, rk in (("entry", "entry"), ("stop_loss", "sl"), ("take_profit", "tp")):
            a, b = live.get(lk), pkg.get(rk)
            if a is None or b is None or not _close(float(a), float(b)):
                return "ml_package_mismatch", {"what": lk, "live": a, "replay": b}
        return None, {}
    # both refused: the named refusal must agree (below_tau vs cost_gate vs reference_symbols ...)
    if lp["head"] != rp.get("head"):
        return "ml_refusal_mismatch", {"live": lp["head"], "replay": rp.get("head")}
    return None, {}


def analyse_ml_entry(leg: Any, bundle: Mapping, since: float, until: float, *,
                     evals_override: Mapping | None = None, frames_override: Mapping | None = None) -> dict:
    out = _result(leg)
    sig = (bundle.get("signals") or {}).get(leg.name) or {}
    if sig.get("error"):
        out["reason"] = f"signals: {sig['error']}"
        return out
    cdata = bundle.get("ml_candles") or {}
    if not cdata:
        out["reason"] = "no ml candle frames in the bundle (fetch not run)"
        return out
    frames: dict = {}
    errs = []
    for s, blob in cdata.items():
        if (blob or {}).get("error") or not (blob or {}).get("candles"):
            errs.append(f"{s}: {(blob or {}).get('error') or 'empty'}")
            continue
        frames[s] = _frame(blob["candles"])
    if frames_override is not None:
        frames = dict(frames_override)
    try:
        from src.runtime import ml_entry_profile as PR
        from src.units.strategies import ml_entry as ME
        model = ME.load_model()
        every_h = int(model["meta"]["bracket"]["decision_every_h"])
        ref_set = list(model["meta"]["xs_reference"])
    except Exception as exc:  # noqa: BLE001 -- recorded as could-not-check, never as zero
        out["reason"] = f"served artifact unreadable: {type(exc).__name__}: {exc}"
        return out
    have_refs = [s for s in ref_set if s in frames]
    if len(have_refs) < int(leg.cfg.get("min_reference_symbols", 40)):
        out["reason"] = f"only {len(have_refs)}/{len(ref_set)} reference frames fetched ({'; '.join(errs[:3])})"
        return out
    rows = (evals_override if evals_override is not None else sig.get("rows")) or []
    live = _live_decisions(list(rows), leg.name)
    # symbols the replay can reproduce: a Bybit-perp symbol inside the artifact's reference set (the real-money roster).
    # Others (alpaca_paper ETFs: reference/anchor from another venue) are listed, not silently dropped.
    cfg = dict(leg.cfg)
    cfg_syms = [str(s) for s in (cfg.get("symbols") or [])]
    replayable = [s for s in cfg_syms if s in frames and s in ref_set]
    not_replayed = sorted(s for s in cfg_syms if s not in replayable)
    if not replayable:
        out["reason"] = "no configured symbol has a replayable bybit-perp frame"
        return out
    divs: list[dict] = []
    bars: list[dict] = []
    n_cmp = 0
    nc = 0
    art_epoch = served_epoch()
    older_artifact = 0
    for bar in decision_bars(since, until, every_h):
        if art_epoch is not None and bar + BAR_S < art_epoch + ARTIFACT_DEPLOY_GRACE_S:
            older_artifact += 1
            bars.append({"bar": _iso(bar), "status": "not_comparable", "reason": "decided by the previous served artifact"})
            continue
        per: list[dict] = []
        for sym in replayable:
            lv = live.get((sym, bar))
            rep = _rep_cached(bundle, cfg, sym, bar, frames, model, PR, use_cache=frames_override is None)
            if rep.get("error"):
                nc += 1
                continue
            if lv is None:
                # the replay decides, live never recorded one inside the window after the close
                if bar + BAR_S + LIVE_DECISION_WINDOW_S < (bundle.get("audit_until_epoch") or until):
                    divs.append({"class": "lost_bar", "bar": _iso(bar), "t": _iso(bar + BAR_S), "symbol": sym,
                                 "detail": {"replay_side": rep["side"]}})
                    per.append({"symbol": sym, "status": "lost_bar"})
                continue
            n_cmp += 1
            cls, det = compare_entry(lv, rep)
            if cls:
                divs.append({"class": cls, "bar": _iso(bar), "t": lv.get("logged_at_utc"), "symbol": sym, "detail": det})
                per.append({"symbol": sym, "status": cls})
            else:
                per.append({"symbol": sym, "status": "matched_signal" if rep["side"] != "none" else "matched_no_signal",
                            "side": rep["side"]})
        if per:
            bars.append({"bar": _iso(bar), "status": "divergent" if any(p["status"] in ML_CLASSES for p in per)
                         else ("matched_signal" if any(p["status"] == "matched_signal" for p in per) else "matched_no_signal"),
                         "symbols": per})
    return _finish(out, n_cmp, divs, bars, nc, extra={"symbols_replayed": replayable, "symbols_not_replayed": not_replayed,
                                                      "not_replayed_reason": "non-bybit symbols: reference/anchor from another venue, paper roster only"
                                                      if not_replayed else None,
                                                      "reference_frames": f"{len(have_refs)}/{len(ref_set)}",
                                                      "served_artifact_changed_at": _iso(art_epoch) if art_epoch else None,
                                                      "bars_before_served_artifact": older_artifact})


# ── ml_entry_eq_struct ───────────────────────────────────────────────────────

def _live_eq(rows: list[dict], strategy: str) -> list[dict]:
    out = []
    for r in rows:
        if r.get("event") != f"{strategy}_eval" or _norm_side(r.get("side")) == "none":
            continue
        t = _epoch(r.get("logged_at_utc"))
        if t is not None:
            out.append({**r, "_t": t})
    return sorted(out, key=lambda x: x["_t"])


def compare_eq(live: Mapping | None, pkg: Mapping | None) -> tuple[str | None, dict]:
    if pkg is not None and live is None:
        return "ml_missed_package", {"replay_entry": pkg.get("entry")}
    if pkg is None and live is not None:
        return "ml_live_only_package", {"live_entry": live.get("entry")}
    if pkg is None:
        return None, {}
    for lk, rk in (("entry", "entry"), ("stop_loss", "sl"), ("take_profit", "tp")):
        a, b = live.get(lk), pkg.get(rk)
        if a is None or b is None or not _close(float(a), float(b)):
            return "ml_package_mismatch", {"what": lk, "live": a, "replay": b}
    return None, {}


def analyse_ml_eq(leg: Any, bundle: Mapping, since: float, until: float, *,
                  evals_override: Mapping | None = None, snapshots_override: Mapping | None = None) -> dict:
    out = _result(leg)
    sig = (bundle.get("signals") or {}).get(leg.name) or {}
    if sig.get("error"):
        out["reason"] = f"signals: {sig['error']}"
        return out
    snaps_blob = bundle.get("ml_pool_snapshots") or {}
    if snapshots_override is None and (snaps_blob.get("error") or snaps_blob.get("snapshots") is None):
        out["reason"] = f"pool snapshot archive: {snaps_blob.get('error') or 'not fetched / unreadable'}"
        return out
    snaps = dict(snapshots_override if snapshots_override is not None else snaps_blob["snapshots"])
    snaps = {k: v for k, v in snaps.items() if v and v.get("bar_close")
             and since <= (_epoch(v["bar_close"]) or 0) < until}
    if not snaps:
        out["reason"] = (f"no archived pool snapshot inside the window ({snaps_blob.get('index_count', 0)} in the archive; "
                         f"present={snaps_blob.get('present')}) -- the archive started with #24889")
        return out
    try:
        from src.units.strategies import ml_entry_eq as L
        cfg = dict(leg.cfg)
        model = L.load_model(L.artifact_path(cfg))
        symbols = [str(s) for s in (cfg.get("symbols") or [])]
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"artifact unreadable: {type(exc).__name__}: {exc}"
        return out
    rows = (evals_override if evals_override is not None else sig.get("rows")) or []
    live = _live_eq(list(rows), leg.name)
    max_age = float(cfg.get("max_snapshot_age_h", 4.0)) * 3600
    divs: list[dict] = []
    bars: list[dict] = []
    n_cmp = 0
    audit_until = bundle.get("audit_until_epoch") or until
    ordered = sorted(snaps.values(), key=lambda v: _epoch(v["bar_close"]))
    for snap in ordered:
        b = _epoch(snap["bar_close"])
        nxt = next((_epoch(s["bar_close"]) for s in ordered if _epoch(s["bar_close"]) > b), None)
        lo, hi = b, min(b + max_age, nxt if nxt is not None else b + max_age)
        if hi > audit_until:   # live had not finished this close inside the fetched audit window
            continue
        try:
            res = L.score_pool(dict(cfg), snap, symbols, model)
        except ValueError as exc:   # not a decision close: nothing to compare
            bars.append({"bar": snap["bar_close"], "status": "not_comparable", "reason": str(exc)})
            continue
        pk = {s: v for s, v in res.items() if isinstance(v, dict)}
        lv: dict[str, dict] = {}
        for r in live:
            if lo <= r["_t"] < hi:
                lv.setdefault(str(r.get("symbol")), r)
        cls_here = []
        for s in sorted(set(pk) | set(lv)):
            cls, det = compare_eq(lv.get(s), pk.get(s))
            if cls:
                cls_here.append(cls)
                divs.append({"class": cls, "bar": snap["bar_close"], "t": (lv.get(s) or {}).get("logged_at_utc"),
                             "symbol": s, "detail": {**det, "snapshot_built_at": snap.get("built_at")}})
        n_cmp += len(set(pk) | set(lv))
        bars.append({"bar": snap["bar_close"], "status": "divergent" if cls_here else ("matched_signal" if pk else "matched_no_signal"),
                     "replay_packages": len(pk), "live_packages": len(lv), "scored": len(res),
                     **({"classes": sorted(set(cls_here))} if cls_here else {})})
    comparable = [x for x in bars if x["status"] != "not_comparable"]
    if not comparable:
        out["reason"] = "every archived snapshot in the window was unscorable or past the audit fetch"
        return out
    return _finish(out, max(n_cmp, 0), divs, bars, 0, extra={
        "snapshots_replayed": len(comparable),
        "refusals": "not diffed: live logs ml_entry_eq* refusals to the journal only, not the audit store"})


# ── shared result shape (the render / findings / controls in live_replay_parity.py read these keys) ────────────

def _result(leg: Any) -> dict:
    return {"leg": leg.name, "symbol": leg.symbol, "timeframe": leg.timeframe, "unit": leg.unit,
            "decision_bar": leg.decision_bar, "execution": leg.execution, "accounts": leg.accounts,
            "real_money": leg.real_money, "features": leg.features, "state": "could_not_check", "reason": None,
            "bars_checked": None, "evals_checked": None, "divergences": None, "by_class": None, "bars": None,
            "ml_replay": True}


def _finish(out: dict, n_cmp: int, divs: list[dict], bars: list[dict], not_comparable: int, *, extra: Mapping) -> dict:
    comparable = [b for b in bars if b.get("status") != "not_comparable"]
    if not comparable or n_cmp == 0:
        out["reason"] = "nothing comparable: no (symbol, decision bar) held both a live record and a replay"
        return out
    out.update({
        "state": "checked", "reason": None, "bars_checked": len(comparable), "evals_checked": n_cmp,
        "divergences": len(divs), "by_class": {k: sum(1 for d in divs if d["class"] == k) for k in ML_CLASSES},
        "bars": bars, "replay_not_comparable": not_comparable,
        "divergence_detail": _first_per_class(divs, 10), "_divs": divs,
        "matched_signal_bars": [b["bar"] for b in comparable if b["status"] == "matched_signal"],
        **dict(extra)})
    return out


def _first_per_class(divs: list[dict], n: int) -> list[dict]:
    seen: dict = {}
    out = []
    for d in divs:
        seen[d["class"]] = seen.get(d["class"], 0) + 1
        if seen[d["class"]] <= n:
            out.append(d)
    return out


def analyse(leg: Any, bundle: Mapping, since: float, until: float, **kw: Any) -> dict:
    kind = ML_UNITS.get(str(leg.unit)) or ML_UNITS.get(leg.name)
    if kind == "ml_entry":
        return analyse_ml_entry(leg, bundle, since, until, **kw)
    return analyse_ml_eq(leg, bundle, since, until, **kw)


# ── controls ─────────────────────────────────────────────────────────────────

def ml_planted_defect(legs: list, results: list[dict], bundle: Mapping, since: float, until: float) -> dict:
    """Fabricate live records the check MUST flag, on this run's real data; AND a clean round-trip it MUST pass.

    ``ml_entry``: (a) a live refusal's feature vector nudged -> ml_feature_mismatch; (b) a live no-signal flipped to a
    package -> ml_side_mismatch. ``ml_entry_eq_struct``: (c) a replay package's live row deleted -> ml_missed_package;
    (d) a live package for a symbol the replay refused -> ml_live_only_package. Clean control: the live records
    REGENERATED from the replay itself (what an exact live would have written) must yield zero divergences."""
    by_leg = {r["leg"]: r for r in results if r.get("ml_replay")}
    plants: list[dict] = []
    clean: list[dict] = []
    for lg in legs:
        r = by_leg.get(lg.name)
        if not r or r["state"] != "checked":
            continue
        rows = list(((bundle.get("signals") or {}).get(lg.name) or {}).get("rows") or [])
        if ML_UNITS.get(str(lg.unit)) == "ml_entry":
            plants += _plant_entry(lg, bundle, since, until, rows)
            clean += _clean_entry(lg, bundle, since, until, rows)
        else:
            plants += _plant_eq(lg, bundle, since, until, rows)
            clean += _clean_eq(lg, bundle, since, until, rows)
    return {"plants": plants, "clean": clean}


def _plant_entry(lg: Any, bundle: Mapping, since: float, until: float, rows: list[dict]) -> list[dict]:
    live = _live_decisions(rows, lg.name)
    ep = served_epoch()
    floor = max(since, (ep + ARTIFACT_DEPLOY_GRACE_S) if ep else since)   # a plant in a not-comparable bar can never be flagged
    from src.units.strategies import ml_entry as ME
    _ref = set(ME.load_model()["meta"]["xs_reference"])
    syms = {str(x) for x in (lg.cfg.get("symbols") or []) if str(x) in _ref}   # the symbols the replay reproduces
    tail = [(k, v) for k, v in live.items() if floor <= k[1] + BAR_S < until and k[0] in syms
            and parse_reason(v.get("reason")).get("feat")]
    out: list[dict] = []
    if tail:
        (sym, bar), v = tail[0]
        p = parse_reason(v["reason"])
        nudged = ",".join(f"{x + (0.01 if i == 8 else 0.0):.5f}" for i, x in enumerate(p["feat"]))
        fake = dict(v, reason=re.sub(r";feat=[^;]*", f";feat={nudged}", v["reason"]))
        res = analyse_ml_entry(lg, bundle, since, until, evals_override=[_as_row(fake)] + [
            r for r in rows if not (r.get("event") == f"{lg.name}_eval" and r.get("id") == v.get("id"))])
        out.append({"plant": "ml_feature_nudged", "leg": lg.name, "bar": _iso(bar), "symbol": sym,
                    "flagged": any(d["class"] == "ml_feature_mismatch" and d["symbol"] == sym and d["bar"] == _iso(bar)
                                   for d in res.get("_divs") or [])})
        none = [(k, x) for k, x in live.items() if _norm_side(x.get("side")) == "none" and floor <= k[1] + BAR_S < until
                and k[0] in syms and parse_reason(x.get("reason")).get("head") == "below_tau"]
        if none:
            (s2, b2), v2 = none[0]
            pkg_row = {k: val for k, val in v2.items() if k != "reason"}
            pkg_row.update({"side": "buy", "reason": None, "entry": 1.0, "stop_loss": 0.9, "take_profit": 1.2,
                            "p_long": 0.5, "p_short": 0.0})
            res = analyse_ml_entry(lg, bundle, since, until, evals_override=[pkg_row] + [
                r for r in rows if not (r.get("event") == f"{lg.name}_eval" and r.get("id") == v2.get("id"))])
            out.append({"plant": "ml_none_flipped_to_package", "leg": lg.name, "bar": _iso(b2), "symbol": s2,
                        "flagged": any(d["symbol"] == s2 and d["bar"] == _iso(b2)
                                       and d["class"] in ("ml_side_mismatch", "ml_score_mismatch", "ml_feature_mismatch")
                                       for d in res.get("_divs") or [])})
    else:
        out.append({"plant": "ml_feature_nudged", "leg": lg.name, "flagged": None,
                    "reason": "no live refusal with a printed feature vector in the window"})
    return out


def _as_row(r: Mapping) -> dict:
    return dict(r)


def _clean_entry(lg: Any, bundle: Mapping, since: float, until: float, rows: list[dict]) -> list[dict]:
    """Regenerate every live record from the replay and re-run the comparison: an exact live must read 0 divergences."""
    from src.runtime import ml_entry_profile as PR
    from src.units.strategies import ml_entry as ME
    frames = {s: _frame(b["candles"]) for s, b in (bundle.get("ml_candles") or {}).items() if (b or {}).get("candles")}
    model = ME.load_model()
    synth: list[dict] = []
    every_h = int(model["meta"]["bracket"]["decision_every_h"])
    for bar in decision_bars(since, until, every_h):
        for k, sym in enumerate(str(x) for x in (lg.cfg.get("symbols") or [])):
            if sym not in frames or sym not in model["meta"]["xs_reference"]:
                continue
            rep = _rep_cached(bundle, dict(lg.cfg), sym, bar, frames, model, PR)
            if rep.get("error"):
                continue
            row = {"event": f"{lg.name}_eval", "strategy": lg.name, "symbol": sym, "id": 10_000 + len(synth),
                   "logged_at_utc": _iso(bar + BAR_S + 120 + k)}
            if rep["side"] == "none":
                row.update({"side": "none", "reason": rep["reason"]})
            else:
                p = rep["pkg"]
                row.update({"side": "buy" if rep["side"] == "long" else "sell", "reason": None, "entry": p["entry"],
                            "stop_loss": p["sl"], "take_profit": p["tp"], "p_long": p["meta"]["p_long"],
                            "p_short": p["meta"]["p_short"]})
            synth.append(row)
    res = analyse_ml_entry(lg, bundle, since, until, evals_override=synth)
    return [{"clean": "ml_entry_roundtrip", "leg": lg.name, "state": res["state"], "records": len(synth),
             "divergences": res.get("divergences"),
             "passed": res["state"] == "checked" and res.get("divergences") == 0}]


def _plant_eq(lg: Any, bundle: Mapping, since: float, until: float, rows: list[dict]) -> list[dict]:
    from src.units.strategies import ml_entry_eq as L
    cfg = dict(lg.cfg)
    snaps = {k: v for k, v in (bundle.get("ml_pool_snapshots") or {}).get("snapshots", {}).items()}
    live = _live_eq(rows, lg.name)
    out: list[dict] = []
    model = L.load_model(L.artifact_path(cfg))
    syms = [str(s) for s in (cfg.get("symbols") or [])]
    for snap in sorted(snaps.values(), key=lambda v: _epoch(v["bar_close"])):
        b = _epoch(snap["bar_close"])
        if not (since <= b < until):
            continue
        try:
            res = L.score_pool(dict(cfg), snap, syms, model)
        except ValueError:
            continue
        pk = [s for s, v in res.items() if isinstance(v, dict)]
        refused = [s for s, v in res.items() if isinstance(v, str)]
        lv_in = [r for r in live if b <= r["_t"] < b + float(cfg.get("max_snapshot_age_h", 4.0)) * 3600]
        hit = next((r for r in lv_in if str(r.get("symbol")) in pk), None)
        if hit is not None:
            kept = [r for r in rows if r is not hit and r.get("id") != hit.get("id")]
            r2 = analyse_ml_eq(lg, bundle, since, until, evals_override=kept)
            out.append({"plant": "ml_live_package_deleted", "leg": lg.name, "bar": snap["bar_close"], "symbol": hit["symbol"],
                        "flagged": any(d["class"] == "ml_missed_package" and d["symbol"] == hit["symbol"]
                                       and d["bar"] == snap["bar_close"] for d in r2.get("_divs") or [])})
        if refused:
            fake = {"event": f"{lg.name}_eval", "strategy": lg.name, "symbol": refused[0], "side": "buy", "entry": 1.0,
                    "stop_loss": 0.9, "take_profit": 1.2, "logged_at_utc": _iso(b + 300), "id": -1}
            r3 = analyse_ml_eq(lg, bundle, since, until, evals_override=list(rows) + [fake])
            out.append({"plant": "ml_live_package_invented", "leg": lg.name, "bar": snap["bar_close"], "symbol": refused[0],
                        "flagged": any(d["class"] == "ml_live_only_package" and d["symbol"] == refused[0]
                                       and d["bar"] == snap["bar_close"] for d in r3.get("_divs") or [])})
        if out:
            break
    if not out:
        out.append({"plant": "ml_live_package_deleted", "leg": lg.name, "flagged": None,
                    "reason": "no archived snapshot in the window held a package live also emitted"})
    return out


def _clean_eq(lg: Any, bundle: Mapping, since: float, until: float, rows: list[dict]) -> list[dict]:
    from src.units.strategies import ml_entry_eq as L
    cfg = dict(lg.cfg)
    model = L.load_model(L.artifact_path(cfg))
    syms = [str(s) for s in (cfg.get("symbols") or [])]
    synth = []
    for snap in (bundle.get("ml_pool_snapshots") or {}).get("snapshots", {}).values():
        b = _epoch(snap["bar_close"])
        if not (since <= b < until):
            continue
        try:
            res = L.score_pool(dict(cfg), snap, syms, model)
        except ValueError:
            continue
        for i, (s, v) in enumerate(res.items()):
            if isinstance(v, dict):
                synth.append({"event": f"{lg.name}_eval", "strategy": lg.name, "symbol": s, "side": "buy",
                              "entry": v["entry"], "stop_loss": v["sl"], "take_profit": v["tp"],
                              "logged_at_utc": _iso(b + 120 + i), "id": -100 - len(synth)})
    res = analyse_ml_eq(lg, bundle, since, until, evals_override=synth)
    return [{"clean": "ml_eq_roundtrip", "leg": lg.name, "state": res["state"], "records": len(synth),
             "divergences": res.get("divergences"),
             "passed": res["state"] == "checked" and res.get("divergences") == 0}]


def control_state(c: Mapping) -> str:
    """pass / fail / could_not_check for the ML control block (plants must ALL be flagged; clean must ALL pass)."""
    plants, clean = c.get("plants") or [], c.get("clean") or []
    vals = [p["flagged"] for p in plants]
    if any(v is False for v in vals) or any(not x["passed"] for x in clean):
        return "fail"
    if vals and all(v is True for v in vals) and clean:
        return "pass"
    return "could_not_check"

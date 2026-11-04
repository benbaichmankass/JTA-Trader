"""ml_entry — the ML ENTRY decision model as a strategy (row ML-ENTRY-LIVE-ADAPTER; Tier 3).

One model, pooled across symbols and tied to no strategy (operator directive 2026-11-01, row ML-DECISION-MODELS): at the
close of every 4th 1h bar it decides LONG / SHORT / NOTHING for a symbol from market context alone. Evidence:
``research/results/RQ-20261101-c692-01/`` (pooled held-out PASS) and ``research/results/RQ-20261101-c692-06/`` (the same
frozen model on the bybit_2 symbols). Spec: ``docs/research/ml-decision-models-2026-11-01/DESIGN.md`` section 2.

Pure signal generator (``.claude/skills/new-strategy/SKILL.md``): no accounts, no sizing (the RiskManager sizes; this
module emits a fixed neutral confidence), no order placement. Both brackets are always set at entry: SL = 2 x ATR14,
TP = 3 x ATR14 (the reference bracket the model was scored with); a 24 h time stop rides ``meta.max_hold_min`` and is
enforced by :func:`monitor` through the same ``max_hold_verdict`` the desk uses.

MOVING TP (row ML-ENTRY-TP-REVISION; evidence ``research/results/RQ-20261101-383f-01/``): when the leg declares
``tp_revision: {rule: ml_first_passage}`` in ``config/strategies.yaml`` the package meta carries it. At each 4h check-in (4, 8, .., 20 closed 1h bars after the decision
bar) :func:`monitor` re-scores the first-passage model of ``src/runtime/ml_entry_tp_policy.py`` and returns
``{"tp": x, "tp_reason": ...}`` through ``src/runtime/tp_revision.py`` (the TP-doctrine path) when a grid level beats
the resting TP by more than the dev-chosen margin. EXTEND-ONLY (operator 2026-11-01 ~22:50Z "Extend-only, now"): the TP
only moves farther from entry, never closer. The SL is never touched; a close verdict always wins.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

import src.runtime.ml_decision_features as F

logger = logging.getLogger(__name__)

NAME = "ml_entry"
ARTIFACT = Path(__file__).resolve().parents[3] / "ml" / "served" / "ml_decision_entry_v1" / "model.json"
#: The RiskManager maps ``confidence`` to a size scalar only when an account sets ``confidence_sizing`` (default
#: ``off`` -> 1.0; bybit_2 / bybit_portfolio set none, MEASURED 2026-11-01). 1.0 is the full account basis under every
#: mode, i.e. the RiskManager's default risk: this model never sizes (operator 2026-11-01 "No position sizing").
NEUTRAL_CONFIDENCE = 1.0
_CACHE: Dict[str, Any] = {}


def load_model(path: Path = ARTIFACT) -> Dict[str, Any]:
    """``{"meta": ..., "long": Booster, "short": Booster}``, cached by mtime. Raises when the artifact is unreadable."""
    import lightgbm as lgb
    st = path.stat()
    hit = _CACHE.get(str(path))
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    art = json.loads(path.read_text(encoding="utf-8"))
    model = {"meta": {k: v for k, v in art.items() if k != "booster_txt"},
             "long": lgb.Booster(model_str=art["booster_txt"]["long"]),
             "short": lgb.Booster(model_str=art["booster_txt"]["short"])}
    _CACHE[str(path)] = (st.st_mtime, model)
    return model


def is_decision_bar(ts: pd.Timestamp, every_h: int) -> bool:
    """The decision is taken at the CLOSE of bar ``ts`` (bar open time) when that close lands on an ``every_h`` hour."""
    return int((ts + pd.Timedelta(hours=1)).hour) % int(every_h) == 0


def _bracket_k(meta: Mapping[str, Any], cost_basis: Mapping[str, float]) -> float:
    """``k_cost_x_atr`` re-derived from an ACCOUNT cost basis (row ML-ENTRY-ALL-ACCOUNTS): bps / 1e4 / sl_atr."""
    from src.runtime.ml_entry_profile import total_bps_rt
    br = meta.get("bracket") or {}
    return total_bps_rt(cost_basis, float(br.get("horizon_h", 24))) / 1e4 / float(br.get("sl_atr", 2.0))


def cost_r_estimate(meta: Mapping[str, Any], row: Mapping[str, float],
                    cost_basis: Optional[Mapping[str, float]] = None) -> Optional[float]:
    """Estimated round-trip cost per R when the artifact declares a ``cost_gate`` (None otherwise, so v1 is untouched).
    Cost per R = (fee + slippage + funding, in bps) / 1e4 / (2 x ATR/price), so it needs only ``atr_pct`` from the feature
    row and the constant ``k_cost_x_atr`` = total round-trip bps / 20,000 fixed from the research cost stack.
    ``cost_basis`` (an account profile's, ``src/runtime/ml_entry_profile.py``) replaces that constant with the
    account's own stack; ``None`` = the artifact's constant, unchanged."""
    g = meta.get("cost_gate")
    if not g:
        return None
    a = float(row[g.get("input", "atr_pct")])
    k = _bracket_k(meta, cost_basis) if cost_basis else float(g["k_cost_x_atr"])
    return k / a if a > 0 else float("inf")


def decide(row: Mapping[str, float], model: Dict[str, Any], *, sides: tuple = ("long", "short"),
           cost_basis: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    """LONG / SHORT / NOTHING for one feature row. With the defaults (both sides, the artifact's cost stack) this is
    the pre-2026-11-04 rule verbatim. ``sides``: the argmax runs over the ALLOWED sides only. ``cost_basis`` with an
    ``artifact_bps_rt``: ``pred_net_r`` is re-based from the artifact's stack to the account's (cost per R at this
    row's ATR) before the tau compare; without ``artifact_bps_rt`` the prediction is left as the artifact made it."""
    x = pd.DataFrame([[row[k] for k in model["meta"]["features"]]], columns=model["meta"]["features"])
    p_long = float(model["long"].predict(x)[0])
    p_short = float(model["short"].predict(x)[0])
    if tuple(sides) == ("long",):
        side = "long"
    elif tuple(sides) == ("short",):
        side = "short"
    else:
        side = "long" if p_long >= p_short else "short"
    best = p_long if side == "long" else p_short
    pred = best
    if cost_basis and cost_basis.get("artifact_bps_rt") is not None:
        from src.runtime.ml_entry_profile import cost_r, total_bps_rt
        br = model["meta"].get("bracket") or {}
        a, sl = float(row.get("atr_pct", 0.0)), float(br.get("sl_atr", 2.0))
        pred = best + cost_r(float(cost_basis["artifact_bps_rt"]), a, sl) \
            - cost_r(total_bps_rt(cost_basis, float(br.get("horizon_h", 24))), a, sl)
    est = cost_r_estimate(model["meta"], row, cost_basis)
    gated = est is not None and est > float(model["meta"]["cost_gate"]["max_cost_r"])
    return {"p_long": p_long, "p_short": p_short, "side": side if (pred > float(model["meta"]["tau"]) and not gated) else "none",
            "pred_net_r": pred, "cost_r_est": est, "gated": gated}


def _audit_inputs(row: Mapping[str, float], df: pd.DataFrame, n_ref: int) -> str:
    """``;feat=<20 values in meta.features order, 5dp>;own_bar=<ts>|close|volume;eval_at=<UTC>`` appended to the eval audit
    reasons so a live score can be diffed against a replay (PI-20261103-MLV2-0001: the BTC/XRP residual after the
    perp-candles fix). LOGGING ONLY: it reads values already computed, never changes a decision, and never raises."""
    try:
        feats = ",".join(f"{float(row[k]):.5f}" for k in F.FEATURES if k in row)
        last = df.iloc[-1]
        return (f";feat={feats};own_bar={pd.Timestamp(last['ts']).strftime('%Y-%m-%dT%H:%M')}|{float(last['close']):.6g}"
                f"|{float(last['volume']):.8g};eval_at={pd.Timestamp.now(tz='UTC').strftime('%H:%M:%S')}")
    except Exception:  # noqa: BLE001 -- an audit tail must never change or break a decision
        return ""


def order_package(cfg: dict, candles_df: Optional[pd.DataFrame] = None,
                  reference_frames: Optional[Mapping[str, pd.DataFrame]] = None,
                  model: Optional[Dict[str, Any]] = None) -> dict:
    """``candles_df``: the symbol's CLOSED 1h bars (last row = decision bar). ``reference_frames``: closed 1h bars of
    the cross-sectional reference symbols (must include BTCUSDT). Raises ``ValueError`` on a non-actionable tick."""
    symbol = str(cfg.get("symbol") or "")
    if candles_df is None or len(candles_df) < F.MIN_BARS:
        raise ValueError(f"insufficient_bars:{0 if candles_df is None else len(candles_df)}")
    df = candles_df.reset_index(drop=True)
    model = model or load_model()
    meta = model["meta"]
    br = meta["bracket"]
    t = pd.Timestamp(df["ts"].iloc[-1])
    if not is_decision_bar(t, int(br["decision_every_h"])):
        raise ValueError("not_a_decision_bar")
    # Per-account profile (row ML-ENTRY-ALL-ACCOUNTS): resolved by the builder from strategies.yaml::<leg>.account_profiles;
    # absent / undeclared = the artifact defaults, i.e. the pre-2026-11-04 path verbatim (bybit parity).
    prof = cfg.get("_profile") if isinstance(cfg.get("_profile"), Mapping) else {}
    if prof.get("conflict"):
        raise ValueError(f"profile_conflict:{prof['conflict']}")
    from src.runtime import ml_entry_profile as PR
    _sess = PR.session_refusal(prof.get("session"), symbol, t + pd.Timedelta(hours=1), int(br["horizon_h"]) * 60)
    if _sess:
        raise ValueError(_sess)
    frames = dict(reference_frames or {})
    frames[symbol] = df
    _ref = PR.reference_universe(prof, meta) if prof.get("reference_universe") else meta.get("xs_reference")
    row = F.decision_row(symbol, frames, reference=_ref, anchor=PR.anchor(prof, meta))
    if row is None:
        raise ValueError("feature_row_unformable")
    n_ref = int(row.pop("_n_reference"))
    audit_tail = _audit_inputs(row, df, n_ref)   # logging only (PI-20261103-MLV2-0001): the inputs behind the score
    min_ref = int(cfg.get("min_reference_symbols", 40))
    if n_ref < min_ref:
        raise ValueError(f"reference_symbols:{n_ref}<{min_ref}")
    _cost = prof.get("cost_basis") or None
    d = decide(row, model, sides=PR.allowed_sides(prof.get("side_filter") or "both"), cost_basis=_cost)
    if d["gated"]:
        raise ValueError(f"cost_gate:est_cost_r={d['cost_r_est']:.4f}>{float(meta['cost_gate']['max_cost_r']):g}"
                         f";p_long={d['p_long']:.4f};p_short={d['p_short']:.4f};tau={float(meta['tau']):.4f};n_ref={n_ref}{audit_tail}")
    from src.runtime.tp_revision import declared_rule
    if d["side"] == "none":
        raise ValueError(f"below_tau:pred={d['pred_net_r']:.4f};p_long={d['p_long']:.4f};p_short={d['p_short']:.4f}"
                         f";tau={float(meta['tau']):.4f};n_ref={n_ref}{audit_tail}")
    atr = F.atr_last(df)
    entry = float(df["close"].iloc[-1])  # next-bar open ~ this close; the venue fills at market
    s = 1.0 if d["side"] == "long" else -1.0
    sl = entry - s * float(br["sl_atr"]) * atr
    tp = entry + s * float(br["tp_atr"]) * atr
    if not (atr > 0 and sl > 0 and tp > 0):
        raise ValueError("bracket_unformable")
    pkg = {
        "symbol": symbol, "direction": d["side"], "entry": entry, "sl": sl, "tp": tp,
        "confidence": NEUTRAL_CONFIDENCE,
        "meta": {"model_id": meta.get("model_id"), "decision_bar": t.isoformat(), "p_long": round(d["p_long"], 5),
                 "p_short": round(d["p_short"], 5), "tau": meta["tau"], "atr14": atr, "n_reference": n_ref,
                 "risk_per_unit": abs(entry - sl), "entry_time": t.isoformat(),
                 "tp_intent": "predictive", "tp_basis": f"{float(br['tp_atr']):g} x ATR14 first-passage target the model was scored on"
                 + ("; re-predicted at each 4h check-in by the ml_first_passage TP revision (RQ-20261101-383f-01)"
                    if declared_rule(cfg) == TP_RULE else ""),
                 **({"tp_revision": cfg["tp_revision"]} if declared_rule(cfg) == TP_RULE else {}),
                 # STRUCTURE-EXITS-DEFAULT: declared structure exit; absent = no key, byte-identical.
                 **({"structure_exit": cfg["structure_exit"]} if cfg.get("structure_exit") else {}),
                 "max_hold_min": int(br["horizon_h"]) * 60,
                 "features": {k: round(float(v), 6) for k, v in row.items()}},
    }
    if d["cost_r_est"] is not None:  # only a gated artifact (v2) reports it; the v1 package meta is unchanged
        pkg["meta"]["cost_r_est"] = round(d["cost_r_est"], 5)
    if prof.get("declared"):  # only a leg that declares account_profiles carries it; bybit_2's meta is unchanged
        pkg["meta"]["account_profile"] = {
            "accounts": list(prof.get("accounts") or []), "reference_venue": prof.get("reference_venue"),
            "anchor": PR.anchor(prof, meta), "side_filter": prof.get("side_filter"), "session": prof.get("session"),
            "cost_basis": _cost, "pred_net_r": round(d["pred_net_r"], 5)}
    if cfg.get("_candle_venue"):  # non-Bybit account: the moving-TP check-in fetches the own frame from this venue
        pkg["meta"]["candle_venue"] = str(cfg["_candle_venue"])
    return pkg


def _telemetry(candles_df: Optional[pd.DataFrame], open_pkg: dict) -> None:
    """M31 peak-R position telemetry, the same hook as e4_oi_shock_1h / squeeze_breakout_4h. Observe-only: it reads
    nothing back and cannot alter the exit. Swallows everything."""
    try:
        if candles_df is None or len(candles_df) == 0:
            return
        from src.runtime.exit_levers import since_entry
        from src.runtime.position_telemetry import record_position_telemetry

        meta = open_pkg.get("meta") or {}
        record_position_telemetry(
            candles_df=candles_df, atr=meta.get("atr14"), open_pkg=open_pkg, meta=meta,
            window=since_entry(candles_df, open_pkg), direction=str(open_pkg.get("direction") or ""),
            current_price=float(candles_df["close"].iloc[-1]), stop=open_pkg.get("sl"),
            target=open_pkg.get("tp"), strategy=NAME)
    except Exception:  # noqa: BLE001 -- telemetry must never break the time stop
        logger.debug("ml_entry: telemetry failed", exc_info=True)


def monitor(cfg, candles_df, open_pkg):
    """The 24 h time stop, then the moving TP at a 4h check-in (a close verdict wins); never raises.
    Also records peak-R position telemetry (observe-only)."""
    _telemetry(candles_df, open_pkg)
    base = None
    try:
        from datetime import datetime, timezone
        from src.units.strategies.claude_desk import max_hold_verdict
        base = max_hold_verdict(open_pkg, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry.monitor: time-stop verdict failed", exc_info=True)
    if isinstance(base, dict) and base.get("action") == "close":
        return base
    _sx = structure_verdict(open_pkg, candles_df)
    if _sx is not _NOT_DECLARED and not _structure_sl_only(open_pkg):
        return _sx  # full structure mode owns SL + TP (the TP revision does not run)
    try:
        from src.runtime.tp_revision import merge_verdict
        merged = merge_verdict(base, tp_revision(cfg, candles_df, open_pkg))
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry.monitor: tp revision failed", exc_info=True)
        merged = base
    if _sx is _NOT_DECLARED:
        return merged
    return merge_structure_sl(merged, _sx)


def _structure_sl_only(open_pkg: Any) -> bool:
    try:
        from src.runtime.structure_exit_live import declared
        p = declared(_meta(open_pkg))
        return bool(p and p.get("sl_only"))
    except Exception:  # noqa: BLE001
        return False


def merge_structure_sl(tp_side: Optional[Dict[str, Any]], sx: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """SL-ONLY structure mode (operator 2026-11-03, option B; record #22645): ONE owner per bracket side.

    ``tp_side`` is the time-stop / ml_first_passage verdict and contributes ONLY its TP (``tp``, ``tp_reason``)
    or a close; ``sx`` is the SL-only structure verdict and contributes ONLY ``sl`` (+ its ``structure_move``
    journal record) or its ``structure_sl_cross`` close. A close from either side wins (the time stop's close
    never reaches here). Any SL key on ``tp_side`` and any TP key on ``sx`` is dropped, so one tick can never
    carry two SL owners or two TP owners to the venue."""
    tp_side = dict(tp_side) if isinstance(tp_side, dict) else None
    sx = dict(sx) if isinstance(sx, dict) else None
    for v in (tp_side, sx):
        if v is not None and v.get("action") == "close":
            return v
    out: Dict[str, Any] = {}
    if tp_side:
        out.update({k: v for k, v in tp_side.items() if k not in ("sl", "sl_reason")})
    if sx:
        if sx.get("sl") is not None:
            out["sl"] = sx["sl"]
        if isinstance(sx.get("structure_move"), dict):
            mv = dict(sx["structure_move"])
            mv["tp_after"] = mv.get("tp_before")  # the structure source did not move the TP
            out["structure_move"] = mv
    return out or None


_NOT_DECLARED = object()


def structure_verdict(open_pkg: Any, candles_df: Any):
    """STRUCTURE-EXITS-DEFAULT: the declared structure exit on 1h closed bars (replaces the moving TP when
    declared). Returns ``_NOT_DECLARED`` when the package does not declare it (byte-identical path)."""
    try:
        from src.runtime.structure_exit_live import declared, structure_exit_verdict
        meta = _meta(open_pkg)
        if declared(meta) is None:
            return _NOT_DECLARED
        return structure_exit_verdict(meta, open_pkg, candles_df, timeframe="1h")
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry.structure_verdict failed", exc_info=True)
        return None


# ----------------------------------------------------------------------------------------------- moving TP
TP_RULE = "ml_first_passage"
_TP_FRAMES: Dict[str, Any] = {}


def _frame(df: Any) -> Optional[pd.DataFrame]:
    """Closed 1h bars as ``ts`` (UTC bar OPEN) + OHLCV; the forming bar dropped. None when unreadable."""
    if df is None or len(df) == 0:
        return None
    from src.runtime.closed_bars import drop_forming_bar
    from src.runtime.strategy_signal_builders import _ml_entry_frame
    return _ml_entry_frame(drop_forming_bar(df, "1h"))


def _meta(open_pkg: Any) -> Dict[str, Any]:
    meta = (open_pkg or {}).get("meta") if isinstance(open_pkg, dict) else None
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    return meta if isinstance(meta, dict) else {}


def checkin_bars_held(decision_bar: Any, last_closed_bar: Any, checkins) -> Optional[int]:
    """Bars held at a check-in: the last CLOSED bar is ``k`` hours after the decision bar with ``k`` in ``checkins``."""
    try:
        k = (pd.Timestamp(last_closed_bar) - pd.Timestamp(decision_bar)) / pd.Timedelta(hours=1)
    except (TypeError, ValueError):
        return None
    return int(k) if float(k).is_integer() and int(k) in set(int(x) for x in checkins) else None


def _checkin_frames(symbol: str, bar_iso: str, xs_symbols, venue: Optional[str] = None) -> tuple:
    """(own 400-bar closed frame, reference frames) for this check-in bar; fetched once per (symbol, bar).

    ``venue``: the package's ``meta.candle_venue`` (a non-Bybit account, row ML-ENTRY-ALL-ACCOUNTS). ``None`` = the
    pre-2026-11-04 fetch verbatim (default client = Bybit). Before this an alpaca_paper package asked BYBIT for SPY's
    own frame, got nothing, and the moving TP silently never ran there."""
    from src.runtime.market_data import fetch_candles
    from src.runtime.strategy_signal_builders import _ml_entry_reference_frames
    key = f"{symbol}|{bar_iso}" if not venue else f"{venue}|{symbol}|{bar_iso}"
    if key not in _TP_FRAMES:
        from src.runtime.strategy_signal_builders import _ml_entry_candle_symbol
        if venue:
            own = _frame(fetch_candles(_ml_entry_candle_symbol(symbol, None, venue), "1h", settings={"EXCHANGE": venue},
                                       limit=400, bypass_cache=True))
        else:
            own = _frame(fetch_candles(_ml_entry_candle_symbol(symbol), "1h", limit=400, bypass_cache=True))
        if own is not None and (not len(own) or own["ts"].iloc[-1].isoformat() != bar_iso):
            own = None
        if len(_TP_FRAMES) > 256:
            _TP_FRAMES.clear()
        _TP_FRAMES[key] = own
    return _TP_FRAMES[key], _ml_entry_reference_frames(list(xs_symbols), bar_iso, None, venue=venue or "bybit")


def tp_revision(cfg: Any, candles_df: Any, open_pkg: Any, *, frames_fn=None, tp_model=None):
    """The ml_first_passage revision for one open package, or None. ``frames_fn(symbol, bar_iso, xs) -> (own, refs)``
    and ``tp_model`` are injectable for tests. Never raises."""
    try:
        from src.runtime.tp_revision import declared_rule, plan_tp_revision
        meta = _meta(open_pkg)
        if declared_rule(meta) != TP_RULE:
            return None
        bars = _frame(candles_df)
        if bars is None or not len(bars):
            return None
        import src.runtime.ml_entry_tp_policy as P
        model = tp_model or P.load_tp_model()
        tm = model["meta"]
        jc = checkin_bars_held(meta.get("decision_bar"), bars["ts"].iloc[-1], tm["checkins_bars_held"])
        if jc is None:
            return None                       # not a check-in bar: the resting TP is the prediction
        symbol = str(open_pkg.get("symbol") or "")
        bar_iso = bars["ts"].iloc[-1].isoformat()
        xs = load_model()["meta"]["xs_reference"]
        _ap = meta.get("account_profile") if isinstance(meta.get("account_profile"), dict) else {}
        _venue = meta.get("candle_venue")
        own, refs = ((frames_fn or _checkin_frames)(symbol, bar_iso, xs) if not _venue
                     else (frames_fn or _checkin_frames)(symbol, bar_iso, xs, _venue))
        if own is None:
            return None
        leg = {**meta, "_xs": (list(xs) if _venue else None), "_anchor": _ap.get("anchor"),
               "_cost_basis": _ap.get("cost_basis"), "_own": own, "_refs": refs, "_resting_tp": open_pkg.get("tp"), "_bars_held": jc,
               "_symbol": symbol, "_tp_model": model, "min_reference_symbols": (cfg or {}).get("min_reference_symbols", 40)}
        return plan_tp_revision(leg=leg, direction=str(open_pkg.get("direction") or meta.get("direction") or ""),
                                entry=open_pkg.get("entry"), risk=float(tm["sl_atr"]) * float(meta.get("atr14") or 0),
                                bars=own, entry_time=meta.get("decision_bar"), ref_price=float(own["close"].iloc[-1]))
    except Exception:  # noqa: BLE001 -- a revision must never break the monitor
        logger.debug("ml_entry.tp_revision failed", exc_info=True)
        return None


def _register_rule() -> None:
    from src.runtime.tp_revision import register_rule

    @register_rule(TP_RULE)
    def _ml_first_passage(*, direction, entry, risk, bars, entry_time, params, leg):
        """bars = the own closed frame ending at the check-in bar; leg carries the reference frames, the resting TP,
        the bars held and the TP model (set by :func:`tp_revision`). None = keep the resting TP."""
        import src.runtime.ml_entry_tp_policy as P
        from src.runtime.execution_costs import resolve_cost_policy
        model = leg["_tp_model"]
        tm = model["meta"]
        side = 1 if direction == "long" else -1
        atr = float(leg["atr14"])
        sl_atr = float(tm["sl_atr"])
        sl = entry - side * sl_atr * atr
        df = bars.reset_index(drop=True)
        jc = int(leg["_bars_held"])
        at = (df["ts"] == pd.Timestamp(entry_time)).to_numpy().nonzero()[0]
        if not len(at) or int(at[-1]) + jc != len(df) - 1:
            return None                       # the decision bar is not jc bars before the check-in: could not look
        win = df.iloc[int(at[-1]) + 1:]
        frames = dict(leg.get("_refs") or {})
        frames[leg["_symbol"]] = df
        # A non-Bybit package (meta.candle_venue) reads its references AS-OF, as at entry; a Bybit one keeps the
        # equal-timestamp rule verbatim (reference=None, the default anchor).
        row = (F.decision_row(leg["_symbol"], frames) if not leg.get("_xs") and not leg.get("_anchor")
               else F.decision_row(leg["_symbol"], frames, reference=leg.get("_xs"), anchor=leg.get("_anchor") or F.ANCHOR))
        if row is None or int(row.pop("_n_reference")) < int(leg.get("min_reference_symbols") or 40):
            return None
        close = float(df["close"].iloc[-1])
        st = P.state_features(side=side, entry=entry, atr_entry=atr, sl=sl, highs=win["high"], lows=win["low"],
                              close_now=close, atr_now=F.atr_last(df), ret_4=row["ret_4"], ret_24=row["ret_24"],
                              bars_held=jc, sl_atr=sl_atr)
        grid = tm["grid_atr"]
        ridx = P.grid_index(leg.get("_resting_tp"), entry, atr, side, grid)
        if ridx is None:
            return None                       # an off-grid resting TP was set by something else: do not fight it
        cb = leg.get("_cost_basis") if isinstance(leg.get("_cost_basis"), dict) else None
        if cb:  # the account profile's cost stack (row ML-ENTRY-ALL-ACCOUNTS); absent = the crypto stack, unchanged
            fee, slip, fund = (float(cb.get("fee_bps_rt", 0.0)), float(cb.get("slippage_bps_rt", 0.0)),
                               float(cb.get("funding_bps_per_8h", 0.0)))
        else:
            fee = float(tm["fee_bps"])
            slip, fund = resolve_cost_policy(leg["_symbol"])
        cost = P.level_cost(entry, atr, side, grid, sl_atr, fee, slip, fund)
        from src.runtime.tp_venue_cap import TP_VENUE_CAP_PCT
        c = P.choose(P.class_probs(model, {**row, **st}), tm["class_mean_net_r"], side=side, entry=entry, atr=atr,
                     close=close, resting_idx=ridx, grid=grid, sl_atr=sl_atr, min_gap_atr=float(tm["min_gap_atr"]),
                     cap_pct=TP_VENUE_CAP_PCT, margin=float(tm["margin_r"]), cost=cost,
                     extend_only=bool(params.get("extend_only", True)))
        if c["move_to"] is None:
            return None
        q = c["move_to"]
        return entry + side * grid[q] * atr, {
            "model_id": tm.get("model_id"), "bars_held": jc, "from_atr": grid[ridx], "to_atr": grid[q],
            "kind": "extend" if q > ridx else "pull_in", "ev_resting_r": round(c["ev_resting"], 4),
            "ev_new_r": round(c["ev_best"], 4), "margin_r": tm["margin_r"]}


_register_rule()

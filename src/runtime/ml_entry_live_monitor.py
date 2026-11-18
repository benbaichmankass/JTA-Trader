"""Live ENTRY monitor — the demotion SIGNAL for the ML entry model (row ML-ENTRY-LIVE-MONITOR; REPORT-ONLY).

The rule below was written BEFORE the first live read (operator 2026-11-01, ENTRY goes live on bybit_2 as approved)
and is implemented exactly as written on the row. Nothing here is tuned after a result.

THE RULE (verbatim from the row)
  Expected band from dev / held-out: traded-5 -0.041 net R per decision (dev, 4 seeds, n ~ 5.5k each); pooled
  frozen-60 +0.007; October 2026 -0.019R. Evaluate realised net R per closed ENTRY decision (full cost stack: fees,
  slippage, funding) per account over ALL its closed ENTRY trades, every 50 closes once n >= 100.
    ENTRY_LIVE_NEGATIVE    when mean + 2*SE < 0               (the live loss is statistically real)
    ENTRY_LIVE_BELOW_DEV   when mean < -0.041 - 2*SE          (worse than even the weak traded-5 dev reading)
  SE = SD / sqrt(n), SD the sample SD (ddof 1).

WHAT A FLAG IS. A REPORT: one realtime ping with the numbers (+ the brief line from ``brief_line()``). It gates nothing,
halts nothing, flips no ``mode:``, sizes nothing (operator 2026-11-04: detectors land report-only; Prime Directive
rule 7). A demotion is the mirror-window rule's, and the operator's. Gates this adds: none.

POPULATION (stated, never implied). Closed, non-backtest rows of ``strategy_name = 'ml_entry'`` on each account, from
``trade_journal.db``. ``ml_entry_v2`` (bybit_1 demo) is a different leg and is NOT in this population.
  * EXCLUDED as operational, counted and reported: every exit_reason in :data:`OPERATIONAL_EXIT_REASONS` (the same
    ``NOT_STRATEGY_EXIT`` vocabulary ``scripts/research/real_money_close_attribution.py`` uses; equality is pinned by
    a test). bybit_2 trades 6844/6845 were relabelled ``operator_flatten_reconciled`` on 2026-11-04 and fall out here.
  * net R = ``src.runtime.net_r_label.net_r_for_trade`` (gross pnl - taker - maker - funding) / SL-distance risk. A row
    whose R is uncomputable is counted and left out, never read as 0. A row with no attributed cost
    (``cost_source`` null) is INCLUDED but counted in ``uncosted`` — its costs read 0, which flatters the mean, so the
    ping states how many there were.
  * Read states stay apart: ``insufficient_n`` (n < 100: we have not read, there is no verdict) / ``evaluated`` /
    ``unreadable`` (the journal could not be read: nothing latches, nothing clears).

NO BROKER CALL. One read-only SQLite connection, same shape as ``losing_streak_alert``.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from src.runtime import alert_cooldown as _alert_cooldown
from src.runtime.net_r_label import net_r_for_trade
from src.utils.paths import runtime_logs_dir

logger = logging.getLogger(__name__)

ALERT_KIND = "ml_entry_live_monitor"
STRATEGY_NAME = "ml_entry"

# --- the pre-registered rule: constants, not knobs. Changing one is changing the rule. ---
MIN_N = 100
STEP = 50
Z = 2.0
DEV_BAND_R = -0.041

FLAG_NEGATIVE = "ENTRY_LIVE_NEGATIVE"
FLAG_BELOW_DEV = "ENTRY_LIVE_BELOW_DEV"

STATE_INSUFFICIENT = "insufficient_n"
STATE_EVALUATED = "evaluated"
STATE_UNREADABLE = "unreadable"

#: Closes that are not the model's decision playing out. MUST equal the keys of
#: ``scripts/research/real_money_close_attribution.NOT_STRATEGY_EXIT`` (tests/runtime/test_ml_entry_live_monitor.py).
OPERATIONAL_EXIT_REASONS = frozenset({
    "reconciler_filled", "reconciler_incomplete", "exchange_flat_reconciled", "backfill_closed_pnl_recovery",
    "netting_attributed", "netting_phantom_reconciled", "netted_misattributed", "adopted_orphan_disappeared",
    "operator_flatten_reconciled", "manual_closeall", "intent_reduce_executed", "intent_reduce",
    "stuck_strategy_watchdog", "exit_coverage_no_strategy", "pairs_half_open_cleanup", "exchange_reset_flat",
})

#: One page per account per CHECKPOINT at most (the checkpoint already rate-limits); the cooldown only guards a
#: restart that loses the observation file.
COOLDOWN_S = 6 * 3600.0
_STATE_FILENAME = "ml_entry_live_monitor_state.json"
_LAST_CHECK_KEY = "__last_check__"
_FRESHNESS_KEY = "__model_freshness__"
_META_KEYS = (_LAST_CHECK_KEY, _FRESHNESS_KEY)

# --- served-model freshness (row ML-ENTRY-RETRAIN-CADENCE) ---------------------------------------------------------
#: A weekly retrain trains on data through (run day - 7d embargo - 25h purge) ~ 8.0 days old when fit, so the freshest
#: artifact is ~8 days "old" on day 0 and ~15 days old a week later, when the next candidate lands. The first limit was 22
#: days (one whole missed weekly cycle beyond that). OPERATOR 2026-11-06 ~17:02Z (popup, verbatim): "Raise to 35 days (Recommended)":
#: a GRADED candidate is a refit as of (run day - 14 d) with the 7d+25h embargo, so it is ~22-23 days old the day it can be promoted,
#: and 22 would label every promoted model stale at once. Over the limit the served model is graded STALE and ONE flag is raised per
#: FRESHNESS_COOLDOWN_S. A report, never a gate: the served model keeps trading.
FRESH_MAX_AGE_DAYS = 35
FRESHNESS_COOLDOWN_S = 7 * 24 * 3600.0
FRESHNESS_KIND = "ml_entry_model_stale"
SERVED_ARTIFACT_REL = "ml/served/ml_decision_entry_v1/model.json"


# ───────────────────────────── pure statistics ─────────────────────────────
def checkpoint_for(n: int) -> int:
    """The latest evaluation checkpoint reached: 0 below MIN_N, else MIN_N, MIN_N+STEP, ..."""
    if n < MIN_N:
        return 0
    return MIN_N + ((n - MIN_N) // STEP) * STEP


def summarize_rs(rs: Sequence[float]) -> Dict[str, Optional[float]]:
    n = len(rs)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "se": None}
    mean = sum(rs) / n
    if n < 2:
        return {"n": n, "mean": mean, "sd": None, "se": None}
    var = sum((r - mean) ** 2 for r in rs) / (n - 1)
    sd = math.sqrt(var)
    return {"n": n, "mean": mean, "sd": sd, "se": sd / math.sqrt(n)}


def flags_for(mean: Optional[float], se: Optional[float]) -> List[str]:
    """The two pre-registered flags. Both can hold at once; neither holds when mean/SE are unknown."""
    if mean is None or se is None:
        return []
    out = []
    if mean + Z * se < 0:
        out.append(FLAG_NEGATIVE)
    if mean < DEV_BAND_R - Z * se:
        out.append(FLAG_BELOW_DEV)
    return out


def _is_entry(row: Mapping[str, Any]) -> bool:
    # A partial-close child row (setup_type 'partial_close', PARTIAL-CLOSE-PNL-NOT-JOURNALED) books
    # part of the SAME decision's realised P&L; counting it would add a second R for one entry.
    if str(row.get("setup_type") or "") == "partial_close":
        return False
    return str(row.get("strategy_name") or row.get("strategy") or "") == STRATEGY_NAME


def assess(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per account, over ALL its closed ENTRY rows. Pure; ``rows`` need the columns ``net_r_for_trade`` reads plus
    ``account_id`` / ``strategy_name`` / ``exit_reason``. Returns ``{account: {state, n, mean, sd, se, flags, ...}}``."""
    acc: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not _is_entry(row):
            continue
        a = acc.setdefault(str(row.get("account_id") or ""), {
            "rs": [], "closed_rows": 0, "excluded_operational": {}, "r_uncomputable": 0, "uncosted": 0})
        a["closed_rows"] += 1
        reason = str(row.get("exit_reason") or "")
        if reason in OPERATIONAL_EXIT_REASONS:
            a["excluded_operational"][reason] = a["excluded_operational"].get(reason, 0) + 1
            continue
        res = net_r_for_trade(row)
        if res is None:
            a["r_uncomputable"] += 1
            continue
        if not res["costed"]:
            a["uncosted"] += 1
        a["rs"].append(float(res["net_R"]))
    out: Dict[str, Dict[str, Any]] = {}
    for acct, a in acc.items():
        s = summarize_rs(a["rs"])
        n = int(s["n"] or 0)
        cp = checkpoint_for(n)
        out[acct] = {
            "state": STATE_EVALUATED if cp else STATE_INSUFFICIENT,
            "n": n, "mean": s["mean"], "sd": s["sd"], "se": s["se"], "checkpoint": cp,
            "flags": flags_for(s["mean"], s["se"]) if cp else [],
            "closed_rows": a["closed_rows"], "excluded_operational": a["excluded_operational"],
            "r_uncomputable": a["r_uncomputable"], "uncosted": a["uncosted"],
            "population": (f"closed non-backtest strategy_name={STRATEGY_NAME} rows on {acct}: "
                           f"{a['closed_rows']} closed, {sum(a['excluded_operational'].values())} operational excluded, "
                           f"{a['r_uncomputable']} R-uncomputable, {n} graded ({a['uncosted']} with no attributed cost)"),
        }
    return out


def describe(acct: str, e: Mapping[str, Any]) -> str:
    """Ping body: the numbers, the rule, the population, and that it is a report."""
    return (
        f"\U0001F7E1 [WARN] ML ENTRY live monitor — {acct}: {', '.join(e['flags'])}. "
        f"Realised net R per closed ENTRY decision (fees + slippage + funding) mean {e['mean']:+.4f} R, "
        f"SE {e['se']:.4f}, n={e['n']} (checkpoint {e['checkpoint']}); mean+2SE = {e['mean'] + Z * e['se']:+.4f}, "
        f"dev band {DEV_BAND_R:+.3f}-2SE = {DEV_BAND_R - Z * e['se']:+.4f}. Population: {e['population']}. "
        f"This is a REPORT, not a switch: nothing was halted, demoted or resized; demotion is the mirror-window "
        f"rule's and yours."
    )


def brief_line(state: Mapping[str, Any]) -> str:
    """One brief line per account from the persisted observation (read-state always visible)."""
    accts = {k: v for k, v in state.items() if k not in _META_KEYS and isinstance(v, dict)}
    if not accts:
        return "ML ENTRY live monitor: no closed ml_entry rows observed yet (we have not read a verdict)."
    parts = []
    for acct, v in sorted(accts.items()):
        ev = v.get("evaluated")
        if ev:
            parts.append(f"{acct} n={ev['n']} mean {ev['mean']:+.4f}R SE {ev['se']:.4f} "
                         f"@cp{ev['checkpoint']} flags={','.join(ev['flags']) or 'none'}")
        else:
            parts.append(f"{acct} n={v.get('n', 0)}/{MIN_N} (no verdict yet)")
    return "ML ENTRY live monitor: " + "; ".join(parts)


# ───────────────────────────── state + I/O ─────────────────────────────
def _state_path():
    return runtime_logs_dir() / _STATE_FILENAME


def _load_state() -> dict:
    try:
        p = _state_path()
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("ml_entry_live_monitor: state load failed: %s", exc)
        return {}


def _save_state(state: dict) -> None:
    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ml_entry_live_monitor: state save failed: %s", exc)


def status() -> Dict[str, Dict[str, Any]]:
    """Last observation per account — the read surface for the brief and the review."""
    return {k: v for k, v in _load_state().items() if k not in _META_KEYS and isinstance(v, dict)}


def served_model_freshness(now: Optional[datetime] = None, artifact_path: Optional[Any] = None) -> Dict[str, Any]:
    """The served ENTRY artifact's data-through date and age. ``read_state`` keeps "we could not look" apart from a
    real age: ``unreadable`` never grades fresh or stale. ``data_through`` is the artifact's ``train_end_exclusive``
    (the last bar its fit saw), field not prose."""
    from pathlib import Path
    now = now or datetime.now(timezone.utc)
    from src.runtime.ml_entry_served import served_artifact
    path = Path(artifact_path) if artifact_path else served_artifact()   # the ONE served pointer
    try:
        art = json.loads(path.read_text(encoding="utf-8"))
        raw = str(art["train_end_exclusive"])
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds() / 86400.0
        return {"read_state": "measured", "model_id": art.get("model_id"), "data_through": raw,
                "age_days": round(age, 1), "grade": "fresh" if age <= FRESH_MAX_AGE_DAYS else "stale",
                "fresh_max_age_days": FRESH_MAX_AGE_DAYS}
    except Exception as exc:  # noqa: BLE001
        return {"read_state": "unreadable", "grade": None, "error": f"{type(exc).__name__}: {exc}"[:200]}


def freshness_line(f: Mapping[str, Any]) -> str:
    if f.get("read_state") != "measured":
        return "ML ENTRY served-model freshness: unreadable (we could not look)."
    return (f"ML ENTRY served-model freshness: {f['model_id']} data through {f['data_through']}, "
            f"{f['age_days']} days old, {f['grade'].upper()} (limit {f['fresh_max_age_days']}d).")


def _read_rows(db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            """
            SELECT id, account_id, strategy_name, exit_reason, entry_price, stop_loss, position_size, pnl,
                   fee_taker_usd, fee_maker_usd, funding_paid_usd, cost_source
              FROM trades
             WHERE is_backtest = 0 AND status = 'closed' AND strategy_name = ?
            """, (STRATEGY_NAME,)).fetchall()]
    finally:
        conn.close()


def _send_alert(message: str) -> None:
    """Same two-channel shape as ``losing_streak_alert`` (Telegram + typed WARNING push). WARNING, never CRITICAL."""
    try:
        from src.runtime.notify import send_telegram_direct
        send_telegram_direct(message, parse_mode=None, mirror_to_fcm=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ml_entry_live_monitor: telegram send failed: %s", exc)
    try:
        from src.runtime.mobile_push import publish_event
        from src.runtime.mobile_push.event_kinds import WARNING
        publish_event(WARNING, {"text": message})
    except Exception as exc:  # noqa: BLE001
        logger.debug("ml_entry_live_monitor: fcm WARNING publish failed: %s", exc)


def run_ml_entry_live_monitor(*, now: Optional[datetime] = None, rows: Optional[Sequence[Mapping[str, Any]]] = None,
                              force: bool = False) -> dict:
    """One tick; call once per trader tick. Cadence-gated (hourly), best-effort, never raises, never gates anything.
    ``rows`` is a test seam. A journal that cannot be read changes nothing (we could not look)."""
    now = now or datetime.now(timezone.utc)
    try:
        interval = int(os.environ.get("ML_ENTRY_LIVE_MONITOR_SECONDS", "3600"))
    except ValueError:
        interval = 3600
    state = _load_state()
    if interval <= 0:
        return {"checked": False, "reason": "paused"}
    if not force and rows is None and state.get(_LAST_CHECK_KEY):
        try:
            prev = datetime.fromisoformat(str(state[_LAST_CHECK_KEY]).replace("Z", "+00:00"))
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=timezone.utc)
            if (now - prev).total_seconds() < interval:
                return {"checked": False, "reason": "cadence"}
        except (TypeError, ValueError):
            pass
    if rows is None:
        try:
            from src.utils.paths import trade_journal_db_path
            rows = _read_rows(str(trade_journal_db_path()))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ml_entry_live_monitor: journal read failed: %s", exc)
            return {"checked": False, "reason": "read_failed"}

    graded = assess(rows)
    state[_LAST_CHECK_KEY] = now.isoformat()
    alerted: List[str] = []
    fresh = served_model_freshness(now)
    state[_FRESHNESS_KEY] = dict(fresh, checked_at=now.isoformat())
    if fresh.get("grade") == "stale" and _alert_cooldown.cooldown_admits(
            FRESHNESS_KIND, str(fresh.get("model_id")), FRESHNESS_COOLDOWN_S):
        _send_alert("\U0001F7E1 [WARN] " + freshness_line(fresh) + " The weekly candidate retrain "
                    "(ml-entry-retrain) produces a CANDIDATE only; serving it is the operator's call. This is a "
                    "report: the served model keeps trading.")
        alerted.append("model_freshness")
    for acct, g in graded.items():
        prev = state.get(acct) if isinstance(state.get(acct), dict) else {}
        last_cp = int((prev.get("evaluated") or {}).get("checkpoint") or 0)
        entry = {"state": g["state"], "n": g["n"], "closed_rows": g["closed_rows"],
                 "excluded_operational": g["excluded_operational"], "r_uncomputable": g["r_uncomputable"],
                 "uncosted": g["uncosted"], "population": g["population"], "updated_at": now.isoformat(),
                 "evaluated": prev.get("evaluated")}
        if g["checkpoint"] > last_cp:
            # A NEW checkpoint (every 50 closes once n >= 100): this is the pre-registered read.
            entry["evaluated"] = {k: g[k] for k in ("n", "mean", "sd", "se", "checkpoint", "flags")}
            entry["evaluated"]["at"] = now.isoformat()
            if g["flags"] and _alert_cooldown.cooldown_admits(ALERT_KIND, f"{acct}:{g['checkpoint']}", COOLDOWN_S):
                _send_alert(describe(acct, g))
                alerted.append(acct)
        state[acct] = entry
    _save_state(state)
    return {"checked": True, "alerted": alerted, "assessed": len(graded)}


__all__ = ["assess", "freshness_line", "served_model_freshness", "brief_line", "checkpoint_for", "describe", "flags_for", "run_ml_entry_live_monitor", "status",
           "summarize_rs", "FLAG_NEGATIVE", "FLAG_BELOW_DEV", "OPERATIONAL_EXIT_REASONS"]

#!/usr/bin/env python3
# wiring: .claude/skills/performance-review/SKILL.md § "Blind-then-reveal grade" (the producer);
#         ml/datasets/families/claude_judgments.py::_grade_rows (the consumer); tests/test_blind_grade.py.
"""CJ-3: the blind-then-reveal post-trade grade -- masking helper, packets, stores.

Design: ``docs/plans/ml-claude-distillation-DESIGN.md`` § 4.3 (the protocol) and
§ 3.1 / § 3.5.5 (no lookahead, LLM-memory masking). Schema:
``comms/schema/claude_judgments.schema.json``.

THE PROTOCOL. A closed trade is graded twice, by a grader that is shown nothing
else:

1. **Blind (T0).** The grader gets a MASKED packet: decision-time inputs only.
   No outcome, no bar after the decision, no symbol, no date, no absolute
   price. Every price is expressed in ATR from the entry; candles are
   ATR-normalised to the decision bar's close and indexed ``-N .. -1``.
   It writes ``grade_score``, ``entry_quality``, ``risk_management``,
   ``p_win`` and a thesis.
2. **Reveal (T1).** The same packet plus the outcome (net R, MFE/MAE in R,
   exit kind, bars held) and the grader's own blind grade. It writes
   ``exit_quality``, a revised grade and ``alternative_action``.

The blind half is the teacher target; the reveal half is a T1 label only.

THE STORES (append-only JSONL, projection of judgement keyed to the journal):
``comms/claude_judgments/blind_grades.jsonl`` and ``revealed_grades.jsonl``.
They carry the judgement and its join keys (``order_package_id``, ``trade_id``)
and NEVER a copy of trade state -- the CJ-2 family joins the outcome from the
journal by ``trade_id``. What the grader was shown is reproducible from
``packet_sha`` plus the committed packet file of the run.

MASKING IS AN ALLOWLIST, NOT A BLACKLIST. ``mask_signal_logic`` keeps only the
keys it names below; an unknown key is dropped (and counted locally), never
passed through. ``find_leaks`` is the independent check -- it scans the
finished packet for anything that could carry the outcome or identify the
market (symbol tokens, dates/epochs, any absolute price of the trade, outcome
key names, a bar index >= 0). The builder REFUSES a packet with a leak; it does
not repair it. ``tests/test_blind_grade.py`` plants each leak class and shows
it is caught (a probe that has never caught anything proves nothing).

CLI::

    python3 scripts/ops/blind_grade.py select   --journal DIR --n 50 --seed 20261026 --out sel.json
    python3 scripts/ops/blind_grade.py packets  --selection sel.json --out-dir DIR   # needs candles
    python3 scripts/ops/blind_grade.py ingest   --run-dir DIR --map map.json ...     # grader output -> stores
    python3 scripts/ops/blind_grade.py validate [--comms-root comms]                 # the stores (CI)
    python3 scripts/ops/blind_grade.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MASK_VERSION = "mask-v1"
SCHEMA_VERSION = 1
STORE_DIR = Path("comms/claude_judgments")
BLIND_STORE = STORE_DIR / "blind_grades.jsonl"
REVEALED_STORE = STORE_DIR / "revealed_grades.jsonl"
N_BARS = 64

# ---------------------------------------------------------------- enums (mirrored in the schema file)
GRADES = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
ENTRY_QUALITY = ("optimal", "acceptable", "late", "early", "should_skip", "unknown")
RISK_MANAGEMENT = ("correct", "sl_too_tight", "sl_too_wide", "tp_too_close", "tp_too_far", "unknown")
EXIT_QUALITY = ("optimal", "tp_appropriate", "sl_appropriate", "premature_exit", "held_too_long", "unknown")
ALTERNATIVE_ACTION = ("none", "skip", "tighter_sl", "wider_sl", "closer_tp", "further_tp",
                      "earlier_exit", "later_exit", "unknown")
EXIT_KIND = ("tp", "sl", "trail", "time", "strategy_close", "reconciled_or_other")

# ---------------------------------------------------------------- the allowlist
# scale-free numbers kept as they are
_KEEP_NUM = frozenset({
    "confidence", "adx_14", "adx", "adx_min", "adx_max", "atr_period", "trail_mult", "tp_r",
    "atr_stop_mult", "sweep_idx_from_end", "displacement_idx_from_end", "displacement_body_to_range",
    "pullback_pos_in_range", "donchian", "trail_decay_tight_mult", "trail_decay_arm_r",
    "trail_decay_stall_bars", "vol_at_entry_pctl", "stale_exit_bars", "stale_exit_below_r",
    "atr_stop_buffer", "pierce_min", "timeout_bars", "bb_period", "bb_std", "kc_mult",
    "body_to_range", "bars_back_of_setup", "rolling_log_return_vol", "trail_vol_below_pctl",
    "trail_vol_tight_mult", "vol_pctl_window",
})
# categorical tokens kept (values are checked against _TOKEN_RE)
_KEEP_CAT = frozenset({"timeframe", "setup_tf", "direction", "regime", "vol_regime",
                       "mitigation_mode", "htf_filter_active", "entry_bar_closed"})
# absolute PRICE levels -> (level - entry) / atr
_PRICE_KEYS = frozenset({"sweep_extreme", "sweep_level", "fvg_low", "fvg_high", "trend_midline",
                         "donchian_hi", "donchian_lo", "level", "tp2", "basis"})
# absolute price DISTANCES -> distance / atr
_DIST_KEYS = frozenset({"fvg_size", "risk_per_unit"})
_TOKEN_RE = re.compile(r"^(?:[a-z][a-z0-9_]{0,31}|\d{1,2}[mhd])$")

# strategy name -> family token; the name itself carries the symbol (ict_scalp_eth_15m)
_FAMILIES = ("ict_scalp", "trend_donchian", "pullback", "squeeze_breakout", "fade", "vwap", "orb")


def strategy_family(name: str) -> str:
    n = (name or "").lower()
    for f in _FAMILIES:
        if f in n:
            return f
    return "other"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (f != f or math.isinf(f)) else f


def _r4(x: float) -> float:
    return round(float(x), 4)


def mask_signal_logic(sl: Mapping[str, Any], *, entry: float, atr: float) -> tuple[dict, list[str]]:
    """Allowlist projection of a package's ``signal_logic``. Returns (masked, dropped_keys)."""
    out: dict[str, Any] = {}
    dropped: list[str] = []
    for k, v in sl.items():
        if k in _KEEP_NUM:
            f = _num(v)
            if f is not None:
                out[k] = _r4(f)
            elif v is None:
                out[k] = None
        elif k in _KEEP_CAT:
            if isinstance(v, bool) or v is None:
                out[k] = v
            elif isinstance(v, str) and _TOKEN_RE.match(v):
                out[k] = v
            else:
                dropped.append(k)
        elif k in _PRICE_KEYS:
            f = _num(v)
            if f is not None:
                out[f"{k}_atr_from_entry"] = _r4((f - entry) / atr)
        elif k in _DIST_KEYS:
            f = _num(v)
            if f is not None:
                out[f"{k}_atr"] = _r4(f / atr)
        elif k == "atr":
            out["atr_pct_of_entry"] = _r4(100.0 * atr / entry)
        elif k == "news" and isinstance(v, Mapping):
            d = v.get("decision")
            out["news_decision"] = d if isinstance(d, str) and _TOKEN_RE.match(d) else None
            out["news_item_count"] = _num(v.get("item_count"))
            out["news_event_risk"] = _num(v.get("event_risk"))
        elif k == "conviction" and isinstance(v, Mapping):
            out["conviction"] = _num(v.get("conviction"))
        else:
            dropped.append(k)
    return out, dropped


def normalise_bars(bars: list[Mapping[str, Any]], *, decision_ts: float, interval_s: int,
                   atr: float, n: int = N_BARS) -> list[list[float]]:
    """The last ``n`` bars that CLOSED at or before the decision, ATR-normalised.

    Row = [index, open, high, low, close, rel_volume], prices as (x - last_close) / atr,
    index -n..-1. A bar is admitted only when ``time + interval_s <= decision_ts``:
    the no-lookahead rule, applied here and not left to the caller.
    """
    closed = sorted((b for b in bars if float(b["time"]) + interval_s <= decision_ts),
                    key=lambda b: float(b["time"]))[-n:]
    if not closed:
        return []
    ref = float(closed[-1]["close"])
    vols = [float(b.get("volume") or 0.0) for b in closed]
    mv = (sum(vols) / len(vols)) if vols and sum(vols) > 0 else None
    out = []
    for i, b in enumerate(closed):
        idx = i - len(closed)
        out.append([idx] + [_r4((float(b[k]) - ref) / atr) for k in ("open", "high", "low", "close")]
                   + [_r4(float(b.get("volume") or 0.0) / mv) if mv else None])
    return out


# ---------------------------------------------------------------- the independent leak check
_OUTCOME_KEYS = frozenset({
    "pnl", "pnl_percent", "exit_price", "exit_reason", "closed_at", "close_reason", "status",
    "linked_trade_id", "order_package_id", "trade_id", "net_r", "gross_r", "mfe", "mae", "mfe_r",
    "mae_r", "outcome", "realized", "realised", "updated_at", "created_at", "entry_time", "account_id",
    "symbol", "strategy_name", "contributing_strategies", "exit_plan_state",
})
_DATE_RE = re.compile(r"(19|20)\d\d[-/]\d\d|\b\d{1,2}:\d\d\b")
_SYMBOL_TOKENS = ("usdt", "usd", "btc", "eth", "sol", "bnb", "xrp", "avax", "ada", "doge", "link",
                  "mgc", "mes", "gld", "spy", "tlt", "iau", "xau", "splg")


def _walk(obj: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            yield f"{path}.{k}" if path else str(k), k
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def find_leaks(packet: Mapping[str, Any], *, secret_prices: Iterable[float] = (),
               raw_bars: Iterable[Mapping[str, Any]] = (), symbol: str = "",
               min_field_matches: int = 3) -> list[str]:
    """Everything in ``packet`` that could reveal the outcome or the market. Empty = clean.

    Independent of ``mask_signal_logic``: it inspects the finished packet, so a
    bug in the masker (or a field added later) is caught here regardless.

    ``secret_prices`` (the trade's own entry / stop / target / exit) leak on ONE
    exact match anywhere. ``raw_bars`` (every OHLC bar the builder fetched) leak
    STRUCTURALLY: a packet bar row whose open/high/low/close equal 3+ of the SAME
    raw bar's values in position, or ``min_field_matches``+ raw prices among the
    non-bar fields. Single values are not enough: a low-priced market (ADA ~0.17)
    and an ATR-normalised value (0.167) coincide by chance -- MEASURED 2026-10-26
    on three of the pilot's 50 packages before this rule replaced a plain
    value-equality check.
    """
    leaks: list[str] = []
    prices = [float(p) for p in secret_prices if _num(p) is not None and float(p) != 0.0]
    raw = [tuple(round(float(b[k]), 10) for k in ("open", "high", "low", "close")) for b in raw_bars]
    raw_set = {v for r in raw for v in r if v != 0.0}
    sym_tokens = set(_SYMBOL_TOKENS)
    base = (symbol or "").lower().replace("usdt", "")
    if base:
        sym_tokens.add(base)
    field_hits: list[str] = []
    for path, v in _walk(packet):
        if isinstance(v, str):
            key = path.rsplit(".", 1)[-1]
            if v in _OUTCOME_KEYS and key == v:
                leaks.append(f"outcome_key:{path}")
            low = v.lower()
            if _DATE_RE.search(v):
                leaks.append(f"date:{path}")
            for tok in sym_tokens:
                if re.search(rf"(^|[^a-z]){re.escape(tok)}([^a-z]|$)", low):
                    leaks.append(f"symbol:{path}")
                    break
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v)
            if 1.0e9 <= abs(f) <= 1.0e13:
                leaks.append(f"epoch:{path}")
            for p in prices:
                if abs(f - p) <= 1e-9 * max(1.0, abs(p)) and abs(p) >= 1e-6:
                    leaks.append(f"absolute_price:{path}")
                    break
            if not path.startswith("bars[") and f != 0.0 and round(f, 10) in raw_set:
                field_hits.append(path)
    if len(field_hits) >= min_field_matches:
        leaks += [f"raw_bar_price:{h}" for h in field_hits]
    for i, row in enumerate(packet.get("bars") or []):
        if not row or not isinstance(row[0], (int, float)) or row[0] >= 0:
            leaks.append(f"bar_index_not_past:bars[{i}]")
        vals = [round(float(x), 10) if _num(x) is not None else None for x in list(row)[1:5]]
        for r in raw:
            if sum(1 for a, b in zip(vals, r) if a is not None and a == b) >= 3:
                leaks.append(f"raw_bar_row:bars[{i}]")
                break
    return sorted(set(leaks))


def packet_sha(packet: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def packet_id(order_package_id: str, salt: str) -> str:
    """Opaque id: the grader cannot map it back to the journal without the salt."""
    return "BP-" + hashlib.sha256(f"{salt}:{order_package_id}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------- packet construction
_TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def timeframe_of(pkg: Mapping[str, Any], sl: Mapping[str, Any]) -> Optional[str]:
    tf = sl.get("timeframe") or sl.get("setup_tf")
    if isinstance(tf, str) and tf in _TF_S:
        return tf
    m = re.search(r"_(5m|15m|30m|1h|2h|4h|1d)$", str(pkg.get("strategy_name") or ""))
    return m.group(1) if m else None


def _ts(v: Any) -> Optional[float]:
    if not v:
        return None
    s = str(v).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def open_exposure(trades: Iterable[Mapping[str, Any]], *, at_ts: float, symbol: str,
                  direction: str, exclude_pkg: str) -> dict[str, int]:
    """Counts of other journal positions open at the decision (all accounts, no backtests)."""
    c = {"same_market_same_dir": 0, "same_market_opp_dir": 0, "other_crypto_same_dir": 0,
         "other_crypto_opp_dir": 0}
    for t in trades:
        if t.get("is_backtest") or t.get("order_package_id") == exclude_pkg:
            continue
        o, cl = _ts(t.get("created_at") or t.get("timestamp")), _ts(t.get("closed_at"))
        if o is None or o > at_ts or (cl is not None and cl <= at_ts):
            continue
        # only rows that were really a position: closed with a close time, or open now.
        # rejected / exchange_rejected / orphaned / error rows have no closed_at and were never
        # open exposure (MEASURED 2026-10-26: 4,304 such rows would otherwise count as open forever)
        st = str(t.get("status"))
        if not ((st == "closed" and cl is not None) or st == "open"):
            continue
        same = t.get("symbol") == symbol
        if not same and not str(t.get("symbol") or "").endswith("USDT"):
            continue
        sd = "same_dir" if t.get("direction") == direction else "opp_dir"
        c[f"{'same_market' if same else 'other_crypto'}_{sd}"] += 1
    return c


def build_blind_packet(pkg: Mapping[str, Any], *, bars: list[Mapping[str, Any]],
                       exposure: Mapping[str, int], salt: str) -> tuple[dict, dict]:
    """(packet, private) -- ``private`` holds what the packet must not, for the ingest map."""
    sl = json.loads(pkg["signal_logic"]) if isinstance(pkg.get("signal_logic"), str) else dict(pkg.get("signal_logic") or {})
    entry, stop, tp = _num(pkg.get("entry")), _num(pkg.get("sl")), _num(pkg.get("tp"))
    atr = _num(sl.get("atr"))
    tf = timeframe_of(pkg, sl)
    decision_ts = _ts(pkg.get("created_at"))
    if None in (entry, stop, tp, atr, decision_ts) or not tf or atr <= 0 or entry == stop:
        raise ValueError(f"{pkg.get('order_package_id')}: missing entry/sl/tp/atr/timeframe/created_at")
    masked, dropped = mask_signal_logic(sl, entry=entry, atr=atr)
    nb = normalise_bars(bars, decision_ts=decision_ts, interval_s=_TF_S[tf], atr=atr)
    risk = abs(entry - stop)
    pid = packet_id(pkg["order_package_id"], salt)
    packet = {
        "packet_id": pid,
        "mask_version": MASK_VERSION,
        "strategy_family": strategy_family(str(pkg.get("strategy_name"))),
        "timeframe": tf,
        "direction": pkg.get("direction"),
        "bracket": {
            "entry_atr": 0.0,
            "stop_atr_from_entry": _r4((stop - entry) / atr),
            "target_atr_from_entry": _r4((tp - entry) / atr),
            "risk_atr": _r4(risk / atr),
            "target_r": _r4(abs(tp - entry) / risk),
        },
        "signal": masked,
        "open_exposure_at_decision": dict(exposure),
        "bars_note": "rows [index, open, high, low, close, rel_volume]; prices in ATR from the last closed bar's close",
        "bars": nb,
    }
    leaks = find_leaks(packet, secret_prices=[entry, stop, tp], raw_bars=bars,
                       symbol=str(pkg.get("symbol") or ""))
    if leaks:
        raise ValueError(f"{pkg.get('order_package_id')}: masked packet leaks {leaks[:5]}")
    private = {"packet_id": pid, "order_package_id": pkg["order_package_id"], "dropped_keys": sorted(dropped),
               "decision_ts": decision_ts, "n_bars": len(nb), "packet_sha": packet_sha(packet)}
    return packet, private


def exit_kind(reason: Any) -> str:
    r = str(reason or "").lower()
    if "trail" in r:
        return "trail"
    if "time" in r or "stale" in r or "timeout" in r:
        return "time"
    if r.startswith("tp") or "take_profit" in r or r == "target":
        return "tp"
    if r.startswith("sl") or "stop" in r:
        return "sl"
    if r.startswith("intent_reduce") or r in ("strategy_close", "signal_exit", "reverse"):
        return "strategy_close"
    return "reconciled_or_other"


def path_excursions(bars: list[Mapping[str, Any]], *, entry: float, stop: float, direction: str,
                    open_ts: float, close_ts: float, interval_s: int) -> tuple[Optional[float], Optional[float], int]:
    """(MFE R, MAE R, bars held) over bars overlapping [open_ts, close_ts], gross price R."""
    risk = abs(entry - stop)
    held = [b for b in bars if float(b["time"]) + interval_s > open_ts and float(b["time"]) < close_ts]
    if not held or risk <= 0:
        return None, None, len(held)
    hi = max(float(b["high"]) for b in held)
    lo = min(float(b["low"]) for b in held)
    if direction == "long":
        return _r4((hi - entry) / risk), _r4((lo - entry) / risk), len(held)
    return _r4((entry - lo) / risk), _r4((entry - hi) / risk), len(held)


# ---------------------------------------------------------------- record validation (CI + ingest)
def _req(row: Mapping, key: str, errs: list[str], types: tuple) -> Any:
    v = row.get(key)
    if not isinstance(v, types) or isinstance(v, bool) and bool not in types:
        errs.append(f"{key}: expected {'/'.join(t.__name__ for t in types)}, got {v!r}"[:160])
    return v


def grader_row_problems(row: Mapping[str, Any], *, kind: str) -> list[str]:
    """Validate what a GRADER wrote (before ingest)."""
    errs: list[str] = []
    _req(row, "packet_id", errs, (str,))
    if kind == "blind":
        g = _req(row, "decision_grade", errs, (str,))
        if g not in GRADES:
            errs.append(f"decision_grade {g!r} not in A-F")
        elif row.get("grade_score") != GRADES[g]:
            errs.append(f"grade_score {row.get('grade_score')!r} != {GRADES[g]} for {g}")
        if row.get("entry_quality") not in ENTRY_QUALITY:
            errs.append(f"entry_quality {row.get('entry_quality')!r}")
        if row.get("risk_management") not in RISK_MANAGEMENT:
            errs.append(f"risk_management {row.get('risk_management')!r}")
        p = _num(row.get("p_win"))
        if p is None or not 0.0 <= p <= 1.0:
            errs.append(f"p_win {row.get('p_win')!r} not in [0,1]")
        if _num(row.get("expected_r")) is None:
            errs.append(f"expected_r {row.get('expected_r')!r}")
        if not isinstance(row.get("thesis"), str) or not row.get("thesis"):
            errs.append("thesis missing")
    elif kind == "revealed":
        g = _req(row, "revised_decision_grade", errs, (str,))
        if g not in GRADES:
            errs.append(f"revised_decision_grade {g!r} not in A-F")
        elif row.get("revised_grade_score") != GRADES[g]:
            errs.append(f"revised_grade_score {row.get('revised_grade_score')!r} != {GRADES[g]}")
        if row.get("exit_quality") not in EXIT_QUALITY:
            errs.append(f"exit_quality {row.get('exit_quality')!r}")
        if row.get("alternative_action") not in ALTERNATIVE_ACTION:
            errs.append(f"alternative_action {row.get('alternative_action')!r}")
        if not isinstance(row.get("hindsight_note"), str) or not row.get("hindsight_note"):
            errs.append("hindsight_note missing")
    else:
        errs.append(f"unknown kind {kind!r}")
    return errs


_STORE_REQ = ("schema_version", "judgment_id", "kind", "order_package_id", "trade_id", "judged_at",
              "info_cutoff_at", "decision_ts", "author_kind", "model_id", "prompt_sha", "mask_version",
              "packet_sha", "run_id", "session_id")


def store_row_problems(row: Mapping[str, Any]) -> list[str]:
    errs = [f"missing {k}" for k in _STORE_REQ if row.get(k) in (None, "")]
    kind = row.get("kind")
    if kind not in ("blind_grade", "revealed_grade"):
        return errs + [f"kind {kind!r}"]
    if row.get("author_kind") != "llm":
        errs.append("author_kind must be llm")
    if not isinstance(row.get("trade_id"), int):
        errs.append("trade_id must be an int (trades.id)")
    cut, dec, jud = _ts(row.get("info_cutoff_at")), _ts(row.get("decision_ts")), _ts(row.get("judged_at"))
    if kind == "blind_grade":
        # T0 by construction: the grader saw nothing after the decision
        if cut is not None and dec is not None and cut > dec:
            errs.append("blind info_cutoff_at is after decision_ts: not blind")
    elif not row.get("blind_judgment_id"):
        errs.append("revealed row must name blind_judgment_id")
    if cut is not None and jud is not None and cut > jud:
        errs.append("info_cutoff_at after judged_at")
    errs += grader_row_problems(row, kind="blind" if kind == "blind_grade" else "revealed")
    return errs


def read_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)  # a corrupt line must fail loudly, never read as empty
        if isinstance(obj, dict) and "_meta" not in obj:
            out.append(obj)
    return out


def validate_stores(comms_root: Path) -> list[str]:
    errs: list[str] = []
    blind = read_jsonl(comms_root / "claude_judgments" / "blind_grades.jsonl")
    rev = read_jsonl(comms_root / "claude_judgments" / "revealed_grades.jsonl")
    ids: set[str] = set()
    for r in blind:
        for e in store_row_problems(r):
            errs.append(f"blind {r.get('judgment_id')}: {e}")
        if r.get("judgment_id") in ids:
            errs.append(f"blind {r.get('judgment_id')}: duplicate judgment_id")
        ids.add(r.get("judgment_id"))
    for r in rev:
        for e in store_row_problems(r):
            errs.append(f"revealed {r.get('judgment_id')}: {e}")
        if r.get("blind_judgment_id") not in ids:
            errs.append(f"revealed {r.get('judgment_id')}: blind_judgment_id not in blind store")
    return errs


# ---------------------------------------------------------------- pilot selection + I/O
def load_journal(journal_dir: Path) -> tuple[dict[str, dict], dict[int, dict]]:
    """Packages + trades from diag pulls saved as ``pk_*.json`` / ``trades_*.json``
    (``scripts/ops/diag_fetch.sh 'journal?table=<t>&limit=1000&offset=<n>'``)."""
    pk: dict[str, dict] = {}
    tr: dict[int, dict] = {}
    for f in sorted(journal_dir.glob("pk_*.json")):
        for p in json.loads(f.read_text()):
            pk[p["order_package_id"]] = p
    for f in sorted(journal_dir.glob("trades_*.json")):
        for t in json.loads(f.read_text()):
            tr[int(t["id"])] = t
    return pk, tr


PILOT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT", "ADAUSDT")


def eligible(pk: Mapping[str, dict], tr: Mapping[int, dict], *, since: str) -> tuple[list[dict], dict]:
    """One (package, trade) per package; every exclusion counted by reason."""
    from src.runtime.net_r_label import net_r_for_trade  # noqa: PLC0415

    excl: dict[str, int] = {}

    def x(reason: str) -> None:
        excl[reason] = excl.get(reason, 0) + 1

    by_pkg: dict[str, list[dict]] = {}
    for t in tr.values():
        if t.get("is_backtest"):
            x("backtest")
            continue
        if str(t.get("status")) != "closed" or t.get("exit_price") is None:
            x("not_closed")
            continue
        if t.get("symbol") not in PILOT_SYMBOLS:
            x("symbol_outside_pilot_candle_source")
            continue
        if str(t.get("strategy_name") or "").startswith("pairs"):
            x("pairs_two_leg")
            continue
        if not t.get("order_package_id") or t["order_package_id"] not in pk:
            x("no_package_row")
            continue
        by_pkg.setdefault(t["order_package_id"], []).append(t)
    out = []
    for pid, ts in by_pkg.items():
        p = pk[pid]
        if str(p.get("created_at") or "") < since:
            excl["decided_before_since"] = excl.get("decided_before_since", 0) + len(ts)
            continue
        t = min(ts, key=lambda r: int(r["id"]))
        try:
            sl = json.loads(p.get("signal_logic") or "{}")
        except ValueError:
            sl = {}
        if not isinstance(sl, dict) or _num(sl.get("atr")) is None or not timeframe_of(p, sl) \
                or None in (_num(p.get("entry")), _num(p.get("sl")), _num(p.get("tp"))):
            x("package_missing_bracket_or_atr")
            continue
        lab = net_r_for_trade(dict(t, stop_loss=p.get("sl")))
        if lab is None:
            x("net_r_uncomputable")
            continue
        if len(ts) > 1:
            excl["fanout_sibling_trades_not_graded"] = excl.get("fanout_sibling_trades_not_graded", 0) + len(ts) - 1
        out.append({"order_package_id": pid, "trade_id": int(t["id"]), "net_r": lab["net_R"]})
    return sorted(out, key=lambda r: r["order_package_id"]), excl


def binance_bars(symbol: str, tf: str, start_ms: int, end_ms: int) -> list[dict]:
    """Spot klines from Binance's public data mirror (a PROXY for the Bybit perp price path:
    Bybit's own API is geo-blocked from the session sandbox, MEASURED 2026-10-26)."""
    out: list[dict] = []
    cur = start_ms
    while cur < end_ms:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": tf, "startTime": cur,
                                    "endTime": end_ms, "limit": 1000})
        with urllib.request.urlopen(f"https://data-api.binance.vision/api/v3/klines?{q}", timeout=30) as r:
            rows = json.loads(r.read())
        if not rows:
            break
        for k in rows:
            out.append({"time": k[0] / 1000.0, "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
        nxt = rows[-1][0] + 1
        if nxt <= cur or len(rows) < 1000:
            break
        cur = nxt
    return out


def cmd_select(a: argparse.Namespace) -> int:
    pk, tr = load_journal(Path(a.journal))
    pop, excl = eligible(pk, tr, since=a.since)
    rng = random.Random(a.seed)
    sample = sorted(rng.sample(pop, min(a.n, len(pop))), key=lambda r: r["order_package_id"])
    rep = {"since": a.since, "seed": a.seed, "n_trades_in_journal": len(tr), "n_packages_in_journal": len(pk),
           "n_eligible_packages": len(pop), "excluded_by_reason": excl, "n_selected": len(sample),
           "selected": sample}
    Path(a.out).write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps({k: v for k, v in rep.items() if k != "selected"}, indent=1))
    return 0


def cmd_packets(a: argparse.Namespace, bar_fn: Callable[..., list[dict]] = binance_bars) -> int:
    from src.runtime.net_r_label import net_r_for_trade  # noqa: PLC0415

    pk, tr = load_journal(Path(a.journal))
    sel = json.loads(Path(a.selection).read_text())["selected"]
    salt = a.salt
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    blind, reveal_ctx, private = [], [], []
    for s in sel:
        p, t = pk[s["order_package_id"]], tr[s["trade_id"]]
        sl = json.loads(p["signal_logic"])
        tf = timeframe_of(p, sl)
        iv = _TF_S[tf]
        dec = _ts(p["created_at"])
        close = _ts(t["closed_at"])
        bars = bar_fn(p["symbol"], tf, int((dec - iv * (N_BARS + 2)) * 1000), int((close + iv) * 1000))
        exp = open_exposure(tr.values(), at_ts=dec, symbol=p["symbol"], direction=p["direction"],
                            exclude_pkg=p["order_package_id"])
        packet, priv = build_blind_packet(p, bars=bars, exposure=exp, salt=salt)
        entry, stop = float(p["entry"]), float(p["sl"])
        mfe, mae, held = path_excursions(bars, entry=entry, stop=stop, direction=p["direction"],
                                         open_ts=_ts(t["created_at"]) or dec, close_ts=close, interval_s=iv)
        lab = net_r_for_trade(dict(t, stop_loss=p["sl"]))
        outcome = {"net_r": _r4(lab["net_R"]), "exit_kind": exit_kind(t.get("exit_reason")),
                   "mfe_r": mfe, "mae_r": mae, "bars_held": held,
                   "cost_source": lab["cost_source"]}
        priv.update({"trade_id": s["trade_id"], "info_cutoff_blind": p["created_at"],
                     "closed_at": t["closed_at"], "leg": p["strategy_name"], "symbol": p["symbol"]})
        rp = {"packet_id": packet["packet_id"], "outcome": outcome}
        leaks = find_leaks(rp, secret_prices=[entry, stop, float(p["tp"]), float(t["exit_price"])],
                           symbol=p["symbol"])
        # the reveal is allowed to carry outcome VALUES, never identity: only symbol/date/price leaks fail it
        leaks = [lk for lk in leaks if not lk.startswith("outcome_key")]
        if leaks:
            raise ValueError(f"reveal packet {packet['packet_id']} leaks {leaks}")
        blind.append(packet)
        reveal_ctx.append(rp)
        private.append(priv)
    (out / "blind_packets.jsonl").write_text("".join(json.dumps(b, sort_keys=True) + "\n" for b in blind))
    Path(a.private_out).write_text(json.dumps({"salt": salt, "rows": private, "reveal": reveal_ctx}, indent=1) + "\n")
    print(json.dumps({"n_packets": len(blind), "out": str(out)}))
    return 0


def cmd_ingest(a: argparse.Namespace) -> int:
    """Map grader output (packet ids) back to journal keys and append to the canonical stores."""
    priv = json.loads(Path(a.private).read_text())
    by_pid = {r["packet_id"]: r for r in priv["rows"]}
    run = json.loads(Path(a.run_meta).read_text())
    blind_rows = read_jsonl(Path(a.run_dir) / "blind_grades.jsonl")
    rev_rows = read_jsonl(Path(a.run_dir) / "revealed_grades.jsonl")
    comms = Path(a.comms_root)
    existing = {r["judgment_id"] for r in read_jsonl(comms / "claude_judgments" / "blind_grades.jsonl")}
    existing_rev = {r["judgment_id"] for r in read_jsonl(comms / "claude_judgments" / "revealed_grades.jsonl")}
    bad: list[str] = []
    new_b, new_r = [], []
    bid: dict[str, str] = {}
    for g in blind_rows:
        bad += [f"blind {g.get('packet_id')}: {e}" for e in grader_row_problems(g, kind="blind")]
        pv = by_pid.get(g.get("packet_id"))
        if pv is None:
            bad.append(f"blind {g.get('packet_id')}: unknown packet_id")
            continue
        jid = f"BG-{pv['order_package_id']}-{run['blind']['prompt_sha'][:8]}"
        bid[g["packet_id"]] = jid
        dec_iso = datetime.fromtimestamp(pv["decision_ts"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {"schema_version": SCHEMA_VERSION, "judgment_id": jid, "kind": "blind_grade",
               "order_package_id": pv["order_package_id"], "trade_id": pv["trade_id"], "leg": pv["leg"],
               "judged_at": run["blind"]["judged_at"], "info_cutoff_at": dec_iso, "decision_ts": dec_iso,
               "author_kind": "llm", "model_id": run["blind"]["model_id"], "prompt_sha": run["blind"]["prompt_sha"],
               "mask_version": MASK_VERSION, "packet_sha": pv["packet_sha"], "packet_id": g["packet_id"],
               "run_id": run["run_id"], "session_id": run["blind"]["session_id"], "pre_cutoff": run.get("pre_cutoff"),
               **{k: g.get(k) for k in ("decision_grade", "grade_score", "entry_quality", "risk_management",
                                       "p_win", "expected_r", "thesis")}}
        if jid not in existing:
            new_b.append(row)
    for g in rev_rows:
        bad += [f"revealed {g.get('packet_id')}: {e}" for e in grader_row_problems(g, kind="revealed")]
        pv = by_pid.get(g.get("packet_id"))
        if pv is None or g.get("packet_id") not in bid:
            bad.append(f"revealed {g.get('packet_id')}: no blind row for this packet")
            continue
        jid = f"RG-{pv['order_package_id']}-{run['reveal']['prompt_sha'][:8]}"
        dec_iso = datetime.fromtimestamp(pv["decision_ts"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {"schema_version": SCHEMA_VERSION, "judgment_id": jid, "kind": "revealed_grade",
               "blind_judgment_id": bid[g["packet_id"]],
               "order_package_id": pv["order_package_id"], "trade_id": pv["trade_id"], "leg": pv["leg"],
               "judged_at": run["reveal"]["judged_at"],
               "info_cutoff_at": _iso_z(pv["closed_at"]), "decision_ts": dec_iso,
               "author_kind": "llm", "model_id": run["reveal"]["model_id"], "prompt_sha": run["reveal"]["prompt_sha"],
               "mask_version": MASK_VERSION, "packet_sha": pv["packet_sha"], "packet_id": g["packet_id"],
               "run_id": run["run_id"], "session_id": run["reveal"]["session_id"], "pre_cutoff": run.get("pre_cutoff"),
               **{k: g.get(k) for k in ("revised_decision_grade", "revised_grade_score", "exit_quality",
                                       "alternative_action", "hindsight_note")}}
        if jid not in existing_rev:
            new_r.append(row)
    for r in new_b + new_r:
        bad += [f"{r['judgment_id']}: {e}" for e in store_row_problems(r)]
    if bad:
        print("\n".join(bad[:50]), file=sys.stderr)
        return 1
    d = comms / "claude_judgments"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "blind_grades.jsonl").open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, sort_keys=True) + "\n" for r in new_b)
    with (d / "revealed_grades.jsonl").open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, sort_keys=True) + "\n" for r in new_r)
    print(json.dumps({"appended_blind": len(new_b), "appended_revealed": len(new_r)}))
    return 0


def _iso_z(v: Any) -> Optional[str]:
    t = _ts(v)
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t is not None else None


def self_test() -> int:
    from tests.test_blind_grade import run_all  # noqa: PLC0415

    return run_all()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("select")
    s.add_argument("--journal", required=True)
    s.add_argument("--since", default="2026-07-01")
    s.add_argument("--n", type=int, default=50)
    s.add_argument("--seed", type=int, default=20261026)
    s.add_argument("--out", required=True)
    p = sub.add_parser("packets")
    p.add_argument("--journal", required=True)
    p.add_argument("--selection", required=True)
    p.add_argument("--salt", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--private-out", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("--run-dir", required=True)
    i.add_argument("--private", required=True)
    i.add_argument("--run-meta", required=True)
    i.add_argument("--comms-root", default="comms")
    v = sub.add_parser("validate")
    v.add_argument("--comms-root", default="comms")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd == "select":
        return cmd_select(a)
    if a.cmd == "packets":
        return cmd_packets(a)
    if a.cmd == "ingest":
        return cmd_ingest(a)
    if a.cmd == "validate":
        errs = validate_stores(Path(a.comms_root))
        n_b = len(read_jsonl(Path(a.comms_root) / "claude_judgments" / "blind_grades.jsonl"))
        n_r = len(read_jsonl(Path(a.comms_root) / "claude_judgments" / "revealed_grades.jsonl"))
        print(f"claude_judgments stores: {n_b} blind, {n_r} revealed rows checked; {len(errs)} problem(s)")
        for e in errs[:50]:
            print("  " + e)
        return 1 if errs else 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# wiring: row DESK-MACRO-DAILY; writes comms/desk/macro/packets/<YYYY-MM-DDTHHMMZ>.json (the brief's input packet)
"""Desk macro daily INPUT PACKET: everything the brief lane needs to propose trades, built BEFORE drafting.

Why (operator, 2026-11-26, rejecting the first brief: 0 trades, 5 sources): "It needs to have very wide variety of inputs, all the
information that it needs in order to propose trades, and it needs to be proposing trades. That's what we built here." The
prototype had a writer and a grader but no input packet, so the lane had no prices, no ATR and no positioning, and fell back to
news. This builds ONE packet JSON. Every part carries a ``read_state`` (measured | stale | could_not_look | not_applicable) and the
reason; a part that could not be read is written as could_not_look, NEVER as an empty list or a zero.

Universe (operator, 2026-11-26, verbatim: "it shouldn't be limited to any specific symbols. It should be able to recommend trades on
any symbols that we are able to trade if it has the data to support it."): the packet's base PANEL is every symbol any roster
already pulls (claude_desk + every leg in config/strategies.yaml); the lane adds ANY other venue-tradable symbol with
``fetch SYMBOL ...``, which writes a write-once, sha-stamped fetch file the brief cites in ``fetch_paths``. A brief may trade a symbol
only when its bars are in the packet or a fetch file (retrieved_at <= judged_at) AND it is venue-tradable (the tradability part).

Parts:
  prices      daily OHLC of every panel symbol from the trader's own bar API (GET /api/bot/candles, the bars the system already
              pulls: Alpaca SIP, Bybit, IB), CLOSED bars only: last close, ATR(14) Wilder, returns 1/5/20 d, realised vol 20 d
              (annualised), 20 d high/low, distance to SMA20/SMA50, and the ATR-scaled levels a 1d trade would use.
  calendar    scheduled macro releases in the next 14 days (comms/macro/econ_calendar_upcoming.json) with consensus and prior.
  priors      the econ event-study scorecards (comms/macro/econ_event_study_*_scorecard.json), summary per release kind.
  cot         the newest CFTC positioning row per symbol (comms/macro/cot_snapshots.jsonl), with its age in days.
  valuation   the newest M28 valuation row per (symbol, metric) (comms/macro/valuation_snapshots.jsonl), with its age.
  crypto_oi   Binance Vision daily metrics for each desk perp (open interest, top-trader and taker long/short ratios) for the
              last two days available; funding rate is could_not_look (the live Bybit/Binance APIs are geo-blocked from the
              session container and Vision publishes funding monthly only).
  book        the desk's newest scan packet (origin/desk/decisions comms/desk/latest_scan.json): the system book (open
              packages per symbol) and the desk book; plus the rostered legs per desk symbol from config/strategies.yaml.
  outcomes    the shadow-trade record of earlier briefs (desk_macro_outcomes.summary: n, hit rate, mean net R, Brier).
  screen      from the panel: biggest 1-day and 5-day movers in ATR units, and unusual last-bar range (range / ATR).
  tradability per symbol: the venue answer from GET /api/bot/tradable (Alpaca /v2/assets, Bybit instruments-info, IB = configured
              futures) where the route answers, plus ``rostered_on`` (the exchanges whose account rosters already trade it,
              from config/accounts.yaml + strategies.yaml): the evidence the writer accepts.

  python3 scripts/ops/desk_macro_packet.py [--out-dir comms/desk/macro/packets] [--print]
  python3 scripts/ops/desk_macro_packet.py --check            # dry run: every part's read_state, writes nothing
  python3 scripts/ops/desk_macro_packet.py fetch --packet PACKET.json SYM [SYM ...]   # in-run bars for any symbol
  python3 scripts/ops/desk_macro_packet.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import subprocess
import sys
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
MACRO = REPO / "comms" / "macro"
OUT_DIR = REPO / "comms" / "desk" / "macro" / "packets"
API = "https://ict-bot.duckdns.org/api/bot/candles"
TRADABLE_API = "https://ict-bot.duckdns.org/api/bot/tradable"
FETCH_SCHEMA = "desk_macro_fetch/1"
# venue_class (the brief's proposal field) -> the exchange names that can fill it (accounts.yaml `exchange:`)
VENUE_EXCHANGES = {"perp": ("bybit", "breakout"), "etf": ("alpaca",), "equity": ("alpaca",), "future": ("interactive_brokers",)}
VISION = "https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"
SCHEMA = "desk_macro_packet/1"
STALE_DAYS = {"cot": 14, "valuation": 7, "calendar": 2, "calendar_row": 7}
PERP_SUFFIX = "USDT"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _strategies() -> dict:
    from src.config.symbol_sets import load_strategies_cfg
    return load_strategies_cfg()


def universe() -> list[str]:
    """The base panel: every symbol any leg declares (claude_desk included), via the canonical leg_symbols."""
    from src.config.symbol_sets import leg_symbols
    out: set[str] = set()
    for cfg in _strategies().values():
        if isinstance(cfg, dict):
            out |= set(leg_symbols(cfg) or [])
    return sorted(out)


def rostered_on() -> dict[str, list[str]]:
    """symbol -> sorted exchanges whose account rosters trade it (config evidence of venue tradability)."""
    from src.config.accounts_loader import load_accounts_dict
    from src.config.symbol_sets import leg_symbols
    strat, out = _strategies(), {}
    for acct, a in (load_accounts_dict() or {}).items():
        if not isinstance(a, dict) or not a.get("exchange"):
            continue
        for leg in a.get("strategies") or []:
            for sym in leg_symbols(strat.get(leg) or {}, acct, leg=leg) or []:
                out.setdefault(sym, set()).add(str(a["exchange"]))
    return {k: sorted(v) for k, v in out.items()}


# ----------------------------------------------------------------------------------------------------------------- prices
def bar_stats(bars: list[dict], now: datetime) -> dict:
    """Stats over CLOSED daily bars only (a bar whose day has not ended is dropped). ``bars``: [{time, open, high, low, close}]."""
    closed = [b for b in sorted(bars, key=lambda b: b["time"])
              if datetime.fromtimestamp(b["time"], timezone.utc) + timedelta(days=1) <= now]
    if len(closed) < 21:
        return {"read_state": "could_not_look", "reason": f"only {len(closed)} closed daily bars (need >= 21)"}
    c = [float(b["close"]) for b in closed]
    h = [float(b["high"]) for b in closed]
    lo = [float(b["low"]) for b in closed]
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]
    atr = sum(tr[1:15]) / 14.0
    for x in tr[15:]:
        atr = (atr * 13 + x) / 14.0                                         # Wilder
    rets = [math.log(c[i] / c[i - 1]) for i in range(1, len(c)) if c[i - 1] > 0 and c[i] > 0]
    r20 = rets[-20:]
    mu = sum(r20) / len(r20)
    vol = math.sqrt(sum((x - mu) ** 2 for x in r20) / (len(r20) - 1)) * math.sqrt(252)
    last, ts = c[-1], datetime.fromtimestamp(closed[-1]["time"], timezone.utc)
    sma = lambda n: sum(c[-n:]) / n if len(c) >= n else None  # noqa: E731
    s20, s50 = sma(20), sma(50)
    return {
        "read_state": "measured", "last_bar": _iso(ts), "last_close": round(last, 6), "n_closed_bars": len(closed),
        "atr14": round(atr, 6), "atr14_pct": round(atr / last * 100.0, 4),
        "ret_1d_pct": round((c[-1] / c[-2] - 1) * 100, 4), "ret_5d_pct": round((c[-1] / c[-6] - 1) * 100, 4),
        "ret_20d_pct": round((c[-1] / c[-21] - 1) * 100, 4), "realised_vol_20d_ann_pct": round(vol * 100, 3),
        "high_20d": max(h[-20:]), "low_20d": min(lo[-20:]), "range_last_atr": round((h[-1] - lo[-1]) / atr, 3),
        "dist_sma20_atr": round((last - s20) / atr, 3) if s20 else None,
        "dist_sma50_atr": round((last - s50) / atr, 3) if s50 else None,
        "closes_61": [round(x, 8) for x in c[-61:]], "closes_61_last_time": int(closed[-1]["time"]),
        "levels_1atr": {"long": {"stop": round(last - atr, 6), "tp_2r": round(last + 2 * atr, 6)},
                        "short": {"stop": round(last + atr, 6), "tp_2r": round(last - 2 * atr, 6)}},
    }


def fetch_bars(symbol: str, limit: int = 120) -> list[dict]:
    import requests
    r = requests.get(API, params={"symbol": symbol, "interval": "1d", "limit": limit}, timeout=60)
    r.raise_for_status()
    return r.json().get("candles") or []


def _one(s: str, now: datetime, fetch: Callable[[str], list[dict]]) -> dict:
    try:
        return bar_stats(fetch(s), now)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded per symbol as could_not_look with the reason
        return {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}


def part_prices(symbols: list[str], now: datetime, fetch: Callable[[str], list[dict]] = fetch_bars, workers: int = 3,
                retry_pause_s: float = 11.0) -> dict:
    """Bars per symbol. A parallel pass, then ONE serial retry of every symbol that came back empty: under parallel load the
    web API's Alpaca path cools down and its 10 s cache serves the empty answer (2026-11-26: 74 of 184 panel symbols read
    0 bars in a 6-worker pass, each of them 120 bars when re-read alone), so the retry waits out that cache first."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = dict(zip(symbols, ex.map(lambda s: _one(s, now, fetch), symbols)))
    empty = [s for s, v in out.items() if v["read_state"] != "measured"]
    if empty and len(empty) < len(symbols) and retry_pause_s >= 0:
        time.sleep(retry_pause_s)
        for s in empty:
            out[s] = dict(_one(s, now, fetch), retried=True)
            time.sleep(0.25)
    n_ok = sum(1 for v in out.values() if v["read_state"] == "measured")
    state = "measured" if n_ok == len(symbols) else ("could_not_look" if n_ok == 0 else "partial")
    return {"read_state": state, "source": API + "?interval=1d", "n_measured": n_ok, "n_symbols": len(symbols), "symbols": out}


# --------------------------------------------------------------------------------------------------------- macro files
def _jsonl_latest(path: Path, key: Callable[[dict], tuple]) -> dict:
    last: dict = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            last[key(r)] = r
    return last


def part_calendar(now: datetime, days: int = 14) -> dict:
    p = MACRO / "econ_calendar_upcoming.json"
    try:
        u = json.loads(p.read_text())
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    gen = _parse(u["generated_from_observed_at"])
    lo, hi = now.date(), (now + timedelta(days=days)).date()
    ev = []
    for e in u.get("events") or []:
        if not lo <= datetime.fromisoformat(str(e["scheduled_for"])).date() <= hi:
            continue
        row = {k: e.get(k) for k in ("event_id", "kind", "event_name", "country", "scheduled_at", "impact", "expected", "observed_at")}
        try:  # a schedule last observed long ago may have moved (a 2026-11-09 observation kept a PCE row on 11-27 after the
            #   release moved to 11-25): the lane re-checks the date of any row flagged here before trading around it
            row["observed_age_days"] = round((now - _parse(e["observed_at"])).total_seconds() / 86400, 1)
        except (KeyError, TypeError, ValueError):
            row["observed_age_days"] = None
        row["schedule_unconfirmed"] = row["observed_age_days"] is None or row["observed_age_days"] > STALE_DAYS["calendar_row"]
        ev.append(row)
    ev.sort(key=lambda e: str(e.get("scheduled_at")))
    age = (now - gen).total_seconds() / 86400
    n_cons = sum(1 for e in ev if (e.get("expected") or {}).get("consensus") is not None)
    state = "stale" if age > STALE_DAYS["calendar"] else ("partial" if ev and n_cons == 0 else "measured")
    out = {"read_state": state, "source": str(p.relative_to(REPO)),
           "generated_from_observed_at": _iso(gen), "age_days": round(age, 2), "window_days": days,
           "n_events": len(ev), "n_with_consensus": n_cons,
           "n_schedule_unconfirmed": sum(1 for e in ev if e["schedule_unconfirmed"]),
           "high_impact": [e for e in ev if e.get("impact") == "HIGH"], "events": ev}
    if state == "partial":
        out["reason"] = (f"0 of {len(ev)} events carry a consensus: the dates are read, the expectations could not be; "
                         "search each high-impact event's consensus before using it")
    return out


def part_priors() -> dict:
    out = {}
    for p in sorted(MACRO.glob("econ_event_study_*scorecard.json")):
        try:
            d = json.loads(p.read_text())
            out[p.stem] = {"summary": d.get("summary"), "meta": {k: (d.get("meta") or {}).get(k)
                                                                for k in ("built_at", "kind", "n", "window", "as_of")}}
        except Exception as exc:  # noqa: BLE001  # allow-silent: per-file could_not_look
            out[p.stem] = {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    if not out:
        return {"read_state": "could_not_look", "reason": "no econ_event_study_*scorecard.json under comms/macro"}
    return {"read_state": "measured", "source": "comms/macro/econ_event_study_*scorecard.json", "scorecards": out}


def _latest_rows(name: str, now: datetime, stale_days: int) -> dict:
    p = MACRO / name
    try:
        last = _jsonl_latest(p, lambda r: (r["symbol"], r["metric"]))
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    rows = []
    for (sym, metric), r in sorted(last.items()):
        age = (now - _parse(r["as_of"])).total_seconds() / 86400
        rows.append({"symbol": sym, "metric": metric, "value": r.get("value"), "label": r.get("label"),
                     "cheap_score": r.get("cheap_score"), "z_score": r.get("z_score"), "percentile": r.get("percentile"),
                     "as_of": r.get("as_of"), "age_days": round(age, 1), "stale": age > stale_days})
    if not rows:
        return {"read_state": "could_not_look", "reason": f"{name} has no rows"}
    n_stale = sum(r["stale"] for r in rows)
    return {"read_state": "stale" if n_stale == len(rows) else "measured", "source": str(p.relative_to(REPO)),
            "stale_after_days": stale_days, "n_rows": len(rows), "n_stale": n_stale, "rows": rows}


# ---------------------------------------------------------------------------------------------------------- crypto OI
def _vision_day(symbol: str, day: str) -> dict | None:
    import requests
    r = requests.get(VISION.format(s=symbol, d=day), timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        text = z.read(z.namelist()[0]).decode()
    rows = [ln.split(",") for ln in text.strip().splitlines()]
    head, last = rows[0], rows[-1]
    return dict(zip(head, last))


def part_crypto_oi(symbols: list[str], now: datetime, get: Callable[[str, str], dict | None] = _vision_day) -> dict:
    perps = [s for s in symbols if s.endswith(PERP_SUFFIX)]
    out = {}
    for s in perps:
        try:
            days = []
            for k in range(1, 5):
                d = (now - timedelta(days=k)).strftime("%Y-%m-%d")
                row = get(s, d)
                if row:
                    days.append((d, row))
                if len(days) == 2:
                    break
            if not days:
                out[s] = {"read_state": "could_not_look", "reason": "no Binance Vision metrics file in the last 4 days"}
                continue
            (d0, r0) = days[0]
            rec = {"read_state": "measured", "day": d0, "create_time": r0.get("create_time"),
                   "sum_open_interest": float(r0["sum_open_interest"]), "sum_open_interest_value": float(r0["sum_open_interest_value"]),
                   "top_trader_ls_ratio": float(r0["count_toptrader_long_short_ratio"]),
                   "taker_ls_vol_ratio": float(r0["sum_taker_long_short_vol_ratio"])}
            if len(days) == 2:
                prev = float(days[1][1]["sum_open_interest"])
                rec["oi_change_1d_pct"] = round((rec["sum_open_interest"] / prev - 1) * 100, 3) if prev else None
            out[s] = rec
        except Exception as exc:  # noqa: BLE001  # allow-silent: per-symbol could_not_look with the reason
            out[s] = {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    n_ok = sum(1 for v in out.values() if v["read_state"] == "measured")
    return {"read_state": "measured" if perps and n_ok == len(perps) else ("could_not_look" if n_ok == 0 else "partial"),
            "source": "data.binance.vision futures/um daily metrics (UTC day files; the latest is yesterday's)",
            "funding": {"read_state": "could_not_look",
                        "reason": "live Bybit/Binance funding endpoints are geo-blocked from the session container; Vision "
                                  "publishes funding monthly only"},
            "symbols": out}


# -------------------------------------------------------------------------------------------------------------- book
def part_book(symbols: list[str]) -> dict:
    legs: dict[str, list[str]] = {s: [] for s in symbols}
    d = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]
    for name, cfg in d.items():
        if not isinstance(cfg, dict) or name == "claude_desk":
            continue
        syms = set(cfg.get("symbols") or []) | {cfg.get("symbol")} if cfg.get("symbol") else set(cfg.get("symbols") or [])
        for s in symbols:
            if s in syms:
                legs[s].append(name)
    out = {"roster_legs_by_symbol": legs}
    try:
        subprocess.run(["git", "-C", str(REPO), "fetch", "-q", "origin", "desk/decisions"], check=True, timeout=120,
                       capture_output=True)
        ptr = json.loads(subprocess.run(["git", "-C", str(REPO), "show", "origin/desk/decisions:comms/desk/latest_scan.json"],
                                        check=True, capture_output=True, text=True, timeout=60).stdout)
        pkt = json.loads(subprocess.run(["git", "-C", str(REPO), "show", f"origin/desk/decisions:{ptr['path']}"],
                                        check=True, capture_output=True, text=True, timeout=60).stdout)
        out.update({"read_state": "measured", "scan_packet_id": ptr.get("packet_id"), "scan_built_at": ptr.get("built_at"),
                    "system_book": pkt.get("system_book"), "desk_book": pkt.get("desk_book")})
    except Exception as exc:  # noqa: BLE001  # allow-silent: the roster part is still measured; the scan is could_not_look
        out.update({"read_state": "partial", "scan": {"read_state": "could_not_look",
                                                      "reason": f"{type(exc).__name__}: {exc}"[:200]}})
    return out


def part_screen(prices: dict, top: int = 10) -> dict:
    m = {s: v for s, v in (prices.get("symbols") or {}).items() if v.get("read_state") == "measured" and v.get("atr14_pct")}
    if not m:
        return {"read_state": "could_not_look", "reason": "no measured panel symbols"}
    z1 = {s: round(v["ret_1d_pct"] / v["atr14_pct"], 3) for s, v in m.items()}
    z5 = {s: round(v["ret_5d_pct"] / v["atr14_pct"], 3) for s, v in m.items()}
    rank = lambda d, rev: [{"symbol": s, "atr_units": d[s]} for s in sorted(d, key=d.get, reverse=rev)[:top]]  # noqa: E731
    wide = sorted(((s, v["range_last_atr"]) for s, v in m.items() if v.get("range_last_atr") is not None), key=lambda x: -x[1])
    return {"read_state": "measured", "population": f"{len(m)} measured panel symbols",
            "up_1d": rank(z1, True), "down_1d": rank(z1, False), "up_5d": rank(z5, True), "down_5d": rank(z5, False),
            "unusual_range": [{"symbol": s, "range_atr": r} for s, r in wide if r >= 1.8][:top]}


def tradable_api(symbols: list[str]) -> dict:
    import requests
    out = {}
    for i in range(0, len(symbols), 40):
        r = requests.get(TRADABLE_API, params={"symbols": ",".join(symbols[i:i + 40])}, timeout=90)
        r.raise_for_status()
        out.update(r.json().get("symbols") or {})
    return out


def part_tradability(symbols: list[str], api: Callable[[list[str]], dict] = tradable_api,
                     roster: Callable[[], dict] = rostered_on) -> dict:
    try:
        ro = roster()
        ro_state = "measured"
    except Exception as exc:  # noqa: BLE001  # allow-silent: roster evidence could_not_look with the reason
        ro, ro_state = {}, f"could_not_look: {type(exc).__name__}"
    try:
        venue, v_state = api(symbols), "measured"
    except Exception as exc:  # noqa: BLE001  # allow-silent: the venue route may not be deployed yet; roster evidence still counts
        venue, v_state = {}, f"could_not_look: {type(exc).__name__}: {exc}"[:200]
    rows = {s: {"rostered_on": ro.get(s, []), "venue": venue.get(s)} for s in symbols}
    state = "measured" if v_state == "measured" and ro_state == "measured" else (
        "partial" if (v_state == "measured") != (ro_state == "measured") else "could_not_look")
    return {"read_state": state, "venue_route": v_state, "roster": ro_state, "source": TRADABLE_API, "symbols": rows}


def is_tradable(row: dict | None, venue_class: str) -> tuple[bool, str]:
    """(tradable, basis) for one tradability row and the proposal's venue_class. Venue answer first, roster evidence second."""
    if not row:
        return False, "no tradability row (fetch the symbol first)"
    exch = VENUE_EXCHANGES.get(venue_class)
    if exch is None:
        return False, f"venue_class {venue_class!r} not in {sorted(VENUE_EXCHANGES)}"
    v = row.get("venue") or {}
    if v.get("read_state") == "measured" and v.get("exchange") in exch:
        return bool(v.get("tradable")), f"venue {v.get('exchange')}: tradable={v.get('tradable')}"
    hit = sorted(set(row.get("rostered_on") or []) & set(exch))
    if hit:
        return True, f"rostered on {hit}"
    return False, f"not confirmed tradable on {exch} (venue answer {v.get('read_state') or 'absent'}, not rostered there)"


def fetch(symbols: list[str], packet: dict, now: datetime | None = None, bars=fetch_bars,
          api: Callable[[list[str]], dict] = tradable_api) -> dict:
    """In-run bars + tradability for ANY symbol, tied to the packet it extends (the brief cites the file in fetch_paths)."""
    now = now or _now()
    syms = sorted({s.strip().upper() for s in symbols if s.strip()})
    f = {"schema": FETCH_SCHEMA, "fetch_id": f"DMF-{now.strftime('%Y%m%dT%H%M%SZ')}", "retrieved_at": _iso(now),
         "packet_id": packet.get("packet_id"), "packet_sha": packet.get("packet_sha"),
         "prices": part_prices(syms, now, bars), "tradability": part_tradability(syms, api)}
    f["fetch_sha"] = hashlib.sha256(json.dumps(f, sort_keys=True, default=str).encode()).hexdigest()
    return f


def part_outcomes() -> dict:
    try:
        import desk_macro_outcomes as dmo
        return {"read_state": "measured", "source": "comms/desk/macro/outcomes.jsonl",
                "summary": dmo.summary(REPO / "comms" / "desk" / "macro" / "outcomes.jsonl")}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}


# ------------------------------------------------------------------------------------------------------------- build
def build(now: datetime | None = None, fetch=fetch_bars, vision=_vision_day, tradable=None, syms: list[str] | None = None) -> dict:
    now = now or _now()
    syms = syms or universe()
    parts = {
        "prices": part_prices(syms, now, fetch),
        "calendar": part_calendar(now),
        "priors": part_priors(),
        "cot": _latest_rows("cot_snapshots.jsonl", now, STALE_DAYS["cot"]),
        "valuation": _latest_rows("valuation_snapshots.jsonl", now, STALE_DAYS["valuation"]),
        "crypto_oi": part_crypto_oi(syms, now, vision),
        "book": part_book(syms),
        "outcomes": part_outcomes(),
    }
    parts["screen"] = part_screen(parts["prices"])
    parts["tradability"] = part_tradability(syms, tradable) if tradable else part_tradability(syms)
    pkt = {"schema": SCHEMA, "packet_id": f"DMP-{now.strftime('%Y%m%dT%H%MZ')}", "built_at": _iso(now),
           "info_cutoff_at": _iso(now), "universe": syms,
           "read_states": {k: v.get("read_state") for k, v in parts.items()}, "parts": parts}
    body = json.dumps(pkt, sort_keys=True, default=str)
    pkt["packet_sha"] = hashlib.sha256(body.encode()).hexdigest()
    return pkt


def write(pkt: dict, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{pkt['packet_id'].removeprefix('DMP-')}.json"
    if p.exists():
        raise SystemExit(f"refusing to overwrite {p}")
    p.write_text(json.dumps(pkt, indent=1, default=str) + "\n")
    return p


def sha_ok(pkt: dict, key: str = "packet_sha") -> bool:
    """True iff pkt[key] is the sha256 of the body without it (a brief cites the packet / fetch file it actually read)."""
    body = {k: v for k, v in pkt.items() if k != key}
    return pkt.get(key) == hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def prices_could_not_look(pkt: dict) -> bool:
    """True iff the packet shows the price panel itself could not be read (the ONE reason a brief may carry no trade)."""
    return ((pkt.get("parts") or {}).get("prices") or {}).get("read_state") == "could_not_look"


# --------------------------------------------------------------------------------------------------------- self-test
def _bars(n: int, start: float, step: float, t0: int) -> list[dict]:
    out, p = [], start
    for i in range(n):
        o, c = p, p + step
        out.append({"time": t0 + i * 86400, "open": o, "high": max(o, c) + 1, "low": min(o, c) - 1, "close": c})
        p = c
    return out


def self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    now = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)
    t0 = int((now - timedelta(days=60)).replace(hour=0, minute=0).timestamp())
    bars = _bars(61, 100.0, 1.0, t0)                       # the last bar (today) is forming
    s = bar_stats(bars, now)
    check("closed bars only: today's forming bar is dropped", s["n_closed_bars"] == 60)
    check("ATR14 of a steady 1.0 trend with +/-1 wicks is 3.0", abs(s["atr14"] - 3.0) < 1e-9)
    check("levels are ATR-scaled around the last close", s["levels_1atr"]["long"]["stop"] == s["last_close"] - s["atr14"])
    check("too few bars is could_not_look, never zeros", bar_stats(bars[:10], now)["read_state"] == "could_not_look")
    pp = part_prices(["A", "B"], now, lambda sym: bars if sym == "A" else (_ for _ in ()).throw(OSError("blocked")), retry_pause_s=0)
    check("one failing symbol -> partial, with its reason", pp["read_state"] == "partial" and "blocked" in pp["symbols"]["B"]["reason"])
    allfail = part_prices(["A"], now, lambda sym: (_ for _ in ()).throw(OSError("down")), retry_pause_s=0)
    flaky = {"n": 0}

    def once_empty(sym):  # inert: sym — the stub answers by call order, not by symbol
        flaky["n"] += 1
        return [] if flaky["n"] == 2 else bars           # B's first read is empty, its retry is full
    rt = part_prices(["A", "B"], now, once_empty, workers=1, retry_pause_s=0)
    check("an empty read is retried once, serially", rt["read_state"] == "measured" and rt["symbols"]["B"].get("retried"))
    check("every symbol failing -> could_not_look", allfail["read_state"] == "could_not_look")
    check("prices_could_not_look reads the packet", prices_could_not_look({"parts": {"prices": allfail}}) and
          not prices_could_not_look({"parts": {"prices": pp}}))
    oi = part_crypto_oi(["BTCUSDT", "SPY"], now, lambda sym, d: {"create_time": d, "sum_open_interest": "100" if d.endswith("25") else "90",
                                                                  "sum_open_interest_value": "1", "count_toptrader_long_short_ratio": "1.2",
                                                                  "sum_taker_long_short_vol_ratio": "0.9"})
    check("crypto OI: perps only, 1d change computed", list(oi["symbols"]) == ["BTCUSDT"] and
          abs(oi["symbols"]["BTCUSDT"]["oi_change_1d_pct"] - 11.111) < 0.01)
    check("funding is declared could_not_look, not omitted", oi["funding"]["read_state"] == "could_not_look")
    u = universe()
    check("the panel is every rostered symbol, wider than the 14 desk symbols", "SPY" in u and "BTCUSDT" in u and len(u) > 14)
    scr = part_screen({"symbols": {"A": dict(s, ret_1d_pct=5.0, ret_5d_pct=1.0, atr14_pct=2.0, range_last_atr=2.5),
                                   "B": dict(s, ret_1d_pct=-1.0, ret_5d_pct=-8.0, atr14_pct=2.0, range_last_atr=0.5)}})
    check("screen ranks movers in ATR units and flags unusual range", scr["up_1d"][0] == {"symbol": "A", "atr_units": 2.5}
          and scr["down_5d"][0]["symbol"] == "B" and [x["symbol"] for x in scr["unusual_range"]] == ["A"])
    check("screen with nothing measured is could_not_look", part_screen({"symbols": {}})["read_state"] == "could_not_look")
    tr = part_tradability(["SPY", "ZZZ"], api=lambda syms: (_ for _ in ()).throw(OSError("404")), roster=lambda: {"SPY": ["alpaca"]})
    check("venue route down -> partial, roster evidence kept", tr["read_state"] == "partial" and tr["symbols"]["SPY"]["rostered_on"] == ["alpaca"])
    check("is_tradable: rostered on the venue class's exchange", is_tradable(tr["symbols"]["SPY"], "etf")[0])
    check("is_tradable: rostered elsewhere is not enough", not is_tradable(tr["symbols"]["SPY"], "perp")[0])
    check("is_tradable: unknown symbol is refused with the reason", not is_tradable(tr["symbols"]["ZZZ"], "equity")[0])
    v_no = {"rostered_on": ["alpaca"], "venue": {"read_state": "measured", "exchange": "alpaca", "tradable": False}}
    check("is_tradable: a measured venue 'no' beats the roster", not is_tradable(v_no, "etf")[0])
    f = fetch(["aapl"], {"packet_id": "DMP-x", "packet_sha": "abc"}, now, bars=lambda sym: bars,
              api=lambda syms: {"AAPL": {"read_state": "measured", "exchange": "alpaca", "tradable": True}})
    check("fetch: any symbol, upper-cased, sha-stamped, tied to its packet", list(f["prices"]["symbols"]) == ["AAPL"]
          and f["packet_sha"] == "abc" and sha_ok(f, "fetch_sha") and is_tradable(f["tradability"]["symbols"]["AAPL"], "equity")[0])
    print("self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["fetch"]:
        fp = argparse.ArgumentParser(prog="desk_macro_packet.py fetch")
        fp.add_argument("--packet", type=Path, required=True)
        fp.add_argument("--out-dir", type=Path, default=OUT_DIR)
        fp.add_argument("symbols", nargs="+")
        fa = fp.parse_args(argv[1:])
        f = fetch(fa.symbols, json.loads(fa.packet.read_text()))
        fa.out_dir.mkdir(parents=True, exist_ok=True)
        out = fa.out_dir / f"fetch-{f['fetch_id'].removeprefix('DMF-')}.json"
        if out.exists():
            raise SystemExit(f"refusing to overwrite {out}")
        out.write_text(json.dumps(f, indent=1, default=str) + "\n")
        print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
        for s, v in f["prices"]["symbols"].items():
            t = f["tradability"]["symbols"][s]
            print(f"  {s}: bars {v['read_state']}" + (f" (close {v.get('last_close')}, ATR {v.get('atr14')})" if v["read_state"] == "measured"
                  else f" ({v.get('reason')})") + f"; venue {(t.get('venue') or {}).get('tradable')}, rostered_on {t['rostered_on']}")
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--print", action="store_true", help="print the packet instead of writing it")
    ap.add_argument("--check", action="store_true", help="dry run: build, print every part's read_state + reason, write nothing")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    pkt = build()
    if a.check:
        for k, v in pkt["parts"].items():
            extra = {x: v.get(x) for x in ("n_measured", "n_symbols", "n_with_consensus", "n_schedule_unconfirmed", "venue_route",
                                           "reason", "n_stale", "n_rows") if v.get(x) is not None}
            print(f"  {k:12s} {v.get('read_state'):15s} {json.dumps(extra, default=str)}")
        return 0 if pkt["parts"]["prices"]["read_state"] != "could_not_look" else 1
    if a.print:
        print(json.dumps(pkt, indent=1, default=str))
        return 0
    p = write(pkt, a.out_dir)
    print(f"wrote {p.relative_to(REPO) if p.is_relative_to(REPO) else p}  read_states={pkt['read_states']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# wiring: row DESK-MACRO-DAILY; writes comms/desk/macro/packets/<YYYY-MM-DDTHHMMZ>.json (the brief's input packet)
"""Desk macro daily INPUT PACKET: everything the brief lane needs to propose trades, built BEFORE drafting.

Why (operator, 2026-11-26, rejecting the first brief: 0 trades, 5 sources): "It needs to have very wide variety of inputs, all the
information that it needs in order to propose trades, and it needs to be proposing trades. That's what we built here." The
prototype had a writer and a grader but no input packet, so the lane had no prices, no ATR and no positioning, and fell back to
news. This builds ONE packet JSON. Every part carries a ``read_state`` (measured | stale | could_not_look | not_applicable) and the
reason; a part that could not be read is written as could_not_look, NEVER as an empty list or a zero.

Parts:
  prices      daily OHLC of every desk symbol from the trader's own bar API (GET /api/bot/candles, the bars the system already
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

  python3 scripts/ops/desk_macro_packet.py [--out-dir comms/desk/macro/packets] [--print]
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
if str(REPO / "scripts" / "ops") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts" / "ops"))
MACRO = REPO / "comms" / "macro"
OUT_DIR = REPO / "comms" / "desk" / "macro" / "packets"
API = "https://ict-bot.duckdns.org/api/bot/candles"
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


def universe() -> list[str]:
    d = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]
    return sorted(d.get("claude_desk", {}).get("symbols") or [])


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
        "high_20d": max(h[-20:]), "low_20d": min(lo[-20:]),
        "dist_sma20_atr": round((last - s20) / atr, 3) if s20 else None,
        "dist_sma50_atr": round((last - s50) / atr, 3) if s50 else None,
        "levels_1atr": {"long": {"stop": round(last - atr, 6), "tp_2r": round(last + 2 * atr, 6)},
                        "short": {"stop": round(last + atr, 6), "tp_2r": round(last - 2 * atr, 6)}},
    }


def fetch_bars(symbol: str, limit: int = 120) -> list[dict]:
    import requests
    r = requests.get(API, params={"symbol": symbol, "interval": "1d", "limit": limit}, timeout=60)
    r.raise_for_status()
    return r.json().get("candles") or []


def part_prices(symbols: list[str], now: datetime, fetch: Callable[[str], list[dict]] = fetch_bars) -> dict:
    out = {}
    for s in symbols:
        try:
            out[s] = bar_stats(fetch(s), now)
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded per symbol as could_not_look with the reason
            out[s] = {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}
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


def part_outcomes() -> dict:
    try:
        import desk_macro_outcomes as dmo
        return {"read_state": "measured", "source": "comms/desk/macro/outcomes.jsonl",
                "summary": dmo.summary(REPO / "comms" / "desk" / "macro" / "outcomes.jsonl")}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}


# ------------------------------------------------------------------------------------------------------------- build
def build(now: datetime | None = None, fetch=fetch_bars, vision=_vision_day) -> dict:
    now = now or _now()
    syms = universe()
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


def sha_ok(pkt: dict) -> bool:
    """True iff packet_sha is the sha256 of the packet body without it (a brief cites the packet it actually read)."""
    body = {k: v for k, v in pkt.items() if k != "packet_sha"}
    return pkt.get("packet_sha") == hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


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
    pp = part_prices(["A", "B"], now, lambda sym: bars if sym == "A" else (_ for _ in ()).throw(OSError("blocked")))
    check("one failing symbol -> partial, with its reason", pp["read_state"] == "partial" and "blocked" in pp["symbols"]["B"]["reason"])
    allfail = part_prices(["A"], now, lambda sym: (_ for _ in ()).throw(OSError("down")))
    check("every symbol failing -> could_not_look", allfail["read_state"] == "could_not_look")
    check("prices_could_not_look reads the packet", prices_could_not_look({"parts": {"prices": allfail}}) and
          not prices_could_not_look({"parts": {"prices": pp}}))
    oi = part_crypto_oi(["BTCUSDT", "SPY"], now, lambda sym, d: {"create_time": d, "sum_open_interest": "100" if d.endswith("25") else "90",
                                                                  "sum_open_interest_value": "1", "count_toptrader_long_short_ratio": "1.2",
                                                                  "sum_taker_long_short_vol_ratio": "0.9"})
    check("crypto OI: perps only, 1d change computed", list(oi["symbols"]) == ["BTCUSDT"] and
          abs(oi["symbols"]["BTCUSDT"]["oi_change_1d_pct"] - 11.111) < 0.01)
    check("funding is declared could_not_look, not omitted", oi["funding"]["read_state"] == "could_not_look")
    check("the real desk universe loads", "SPY" in universe() and "BTCUSDT" in universe())
    print("self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--print", action="store_true", help="print the packet instead of writing it")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    pkt = build()
    if a.print:
        print(json.dumps(pkt, indent=1, default=str))
        return 0
    p = write(pkt, a.out_dir)
    print(f"wrote {p.relative_to(REPO) if p.is_relative_to(REPO) else p}  read_states={pkt['read_states']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

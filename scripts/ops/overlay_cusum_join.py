#!/usr/bin/env python3
"""ML-REAL-MONEY-OVERLAY: the demotion CUSUM's live input -- join overlay shadow rows to closed trades.

`scripts/ops/overlay_cusum.py` grades the mirror's REDUCED trades by win/loss. Its input is one row per closed
trade carrying the overlay multiplier that applied (or, under annotate, WOULD have applied) to that trade's
package on that account. This builds those rows from two read-only live sources, both on the diag relay:

  * ``log_file?name=overlay_shadow&lines=N`` -- runtime_logs/overlay_shadow.jsonl, one row per account per scored
    package (src/runtime/overlay_shadow.record_overlay_shadow);
  * ``journal?table=trades&limit=N`` -- trade_journal.db ``trades`` (SELECT *).

JOIN, in order (the basis is recorded on every row, never hidden):
  1. ``order_package_id`` + ``account``: shadow rows written by the canary build carry the package id that
     ``trades.order_package_id`` is stamped from (``Coordinator.multi_account_execute``).
  2. fallback for rows without it (the annotate build deployed 2026-10-29 17e450d9 logs only ``trace_id``, which
     the trade row does not carry): same account, strategy, symbol and direction, and the trade's ``timestamp``
     within ``--window-min`` (default 10) minutes after the shadow row's ``logged_at_utc``. Ambiguous matches
     (two shadow rows for one trade, or the reverse) are DROPPED and counted, never guessed.
WIN/LOSS: net PnL = gross PnL - fee_taker_usd - fee_maker_usd - funding_paid_usd, the canonical definition in
src/runtime/net_r_label.py (net_r_for_trade, used when it can compute; its net_pnl_usd otherwise). Only the SIGN
is used, so the R denominator (trades.stop_loss is the CURRENT stop, src/runtime/r_provenance.py) cannot bias it.
Only CLOSED trades with a resolved pnl are emitted.
RELAY SIZE: a `journal?table=trades&limit=30` comment is already ~51 kB against the relay's ~55 kB cap
(measured 2026-10-29, relay #21233), so page with limit<=30 and offset=0,30,60,... and pass every page.

    python3 scripts/ops/overlay_cusum_join.py --shadow <relay comment | jsonl> --trades <relay comment | json> \\
        [--account bybit_portfolio] [--out joined.jsonl] [--cusum]
    python3 scripts/ops/overlay_cusum_join.py --self-test
"""
# wiring: manual-only - run by the manager (or a lane) over one batched diag-relay pull; PI-20261029-XME2GXW7-0001
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))


def _ts(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    s = str(v).strip().replace("Z", "+00:00")
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _json_blocks(text: str) -> list[Any]:
    """Every ```json fenced block of a relay comment, parsed; a plain JSON/JSONL file also works."""
    blocks = re.findall(r"```json\s*\n(.*?)\n```", text, flags=re.S)
    out = []
    for b in blocks or [text]:
        b = b.strip()
        try:
            out.append(json.loads(b, strict=False))
            continue
        except json.JSONDecodeError:
            pass
        for ln in b.splitlines():  # JSONL
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln, strict=False))
                except json.JSONDecodeError:
                    continue
    return out


_TRUNCATION_MARKERS = ("are NOT shown", "Re-request this path alone", "Re-request with a smaller")


def relay_completeness(text: str) -> dict:
    """Could we actually read this input? A relay comment whose ```json block was cut by the ~55 kB comment cap
    neither parses as one JSON value nor is JSONL, and the relay appends a truncation note. Either one means the
    rows below are NOT a census: the caller must report `incomplete_read`, never "no trades" / "no rows"
    (measured 2026-10-29, relay #21272: a 4-path batch cut the trades block mid-JSON and the loader read 0 rows)."""
    unparsed = 0
    for b in re.findall(r"```json\s*\n(.*?)\n```", text, flags=re.S):
        b = b.strip()
        try:
            json.loads(b, strict=False)
            continue
        except json.JSONDecodeError:
            pass
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        ok = 0
        for ln in lines:
            try:
                json.loads(ln, strict=False)
                ok += 1
            except json.JSONDecodeError:
                pass
        if not lines or ok < len(lines):
            unparsed += 1
    truncated = any(m in text for m in _TRUNCATION_MARKERS)
    return {"unparsed_blocks": unparsed, "truncated": truncated, "complete": unparsed == 0 and not truncated}


def load_shadow(text: str) -> list[dict]:
    rows: list[dict] = []
    for blk in _json_blocks(text):
        if isinstance(blk, dict) and isinstance(blk.get("lines"), list):  # log_file envelope
            for ln in blk["lines"]:
                try:
                    rows.append(json.loads(ln) if isinstance(ln, str) else ln)
                except json.JSONDecodeError:
                    continue
        elif isinstance(blk, dict) and "would_be_multiplier" in blk:
            rows.append(blk)
    return [r for r in rows if isinstance(r, dict) and r.get("action") == "annotate"]


def load_trades(text: str) -> list[dict]:
    rows: list[dict] = []
    for blk in _json_blocks(text):
        if isinstance(blk, list):
            rows.extend(r for r in blk if isinstance(r, dict) and "order_package_id" in r)
        elif isinstance(blk, dict) and isinstance(blk.get("rows"), list):
            rows.extend(blk["rows"])
        elif isinstance(blk, dict) and "order_package_id" in blk and "pnl" in blk:
            rows.append(blk)
    return rows


def net_pnl(trade: dict) -> float | None:
    """Canonical net PnL (src/runtime/net_r_label.py): gross - fees - funding. None if pnl is unresolved."""
    from src.runtime.net_r_label import net_r_for_trade
    lab = net_r_for_trade(trade)
    if lab is not None:
        return float(lab["net_pnl_usd"])
    gross = trade.get("gross_pnl", trade.get("pnl"))
    try:
        g = float(gross)
    except (TypeError, ValueError):
        return None
    cost = 0.0
    for k in ("fee_taker_usd", "fee_maker_usd", "funding_paid_usd"):
        try:
            cost += float(trade.get(k) or 0.0)
        except (TypeError, ValueError):
            pass
    return g - cost


def join(shadow: Iterable[dict], trades: Iterable[dict], window_min: float = 10.0) -> dict:
    shadow = [s for s in shadow if isinstance(s, dict) and s.get("action") == "annotate"]
    trades = list(trades)
    closed = [t for t in trades if str(t.get("status") or "").lower() == "closed" or t.get("closed_at")]
    by_pkg = {}
    for s in shadow:
        if s.get("order_package_id"):
            by_pkg.setdefault((s["order_package_id"], s.get("account")), []).append(s)
    rows, unmatched, ambiguous = [], 0, 0
    used: set[int] = set()
    win = timedelta(minutes=window_min)
    for t in closed:
        n = net_pnl(t)
        if n is None:
            continue
        acct = t.get("account_id")
        cands = by_pkg.get((t.get("order_package_id"), acct), [])
        basis = "order_package_id"
        if not cands:
            tt = _ts(t.get("timestamp") or t.get("created_at"))
            basis = "time_window"
            cands = [s for s in shadow if not s.get("order_package_id") and s.get("account") == acct
                     and s.get("strategy_id") == t.get("strategy_name")
                     and str(s.get("symbol", "")).replace("/", "").split(":")[0]
                     == str(t.get("symbol", "")).replace("/", "").split(":")[0]
                     and str(s.get("direction", "")).lower() == str(t.get("direction", "")).lower()
                     and tt is not None and _ts(s.get("logged_at_utc")) is not None
                     and timedelta(0) <= tt - _ts(s.get("logged_at_utc")) <= win]
        if not cands:
            unmatched += 1
            continue
        if len(cands) > 1 or id(cands[0]) in used:
            ambiguous += 1
            continue
        s = cands[0]
        used.add(id(s))
        rows.append({"strategy": t.get("strategy_name"), "account": acct, "trade_id": t.get("id"),
                     "order_package_id": t.get("order_package_id"), "multiplier": float(s["would_be_multiplier"]),
                     "p_win": s.get("p_win"), "net_r": n, "net_pnl_usd": round(n, 6),
                     "closed_at": t.get("closed_at"), "join_basis": basis})
    return {"rows": rows, "n_shadow": len(shadow), "n_closed_trades": len(closed), "n_joined": len(rows),
            "n_unmatched_trades": unmatched, "n_ambiguous_dropped": ambiguous,
            "read_state": "measured" if shadow and closed else ("no_shadow_rows" if not shadow else "no_closed_trades")}


def _dedupe(trades: list[dict]) -> list[dict]:
    """Pages can overlap when trades land between pulls; keep one row per trades.id (the last seen)."""
    return list({t.get("id", i): t for i, t in enumerate(trades)}.values())


def _self_test() -> int:
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    sh = [
        {"action": "annotate", "strategy_id": "trend_donchian_eth_4h", "symbol": "ETHUSDT", "direction": "long",
         "account": "bybit_portfolio", "order_package_id": "pkg-a", "would_be_multiplier": 0.5, "p_win": 0.2,
         "logged_at_utc": now.isoformat()},
        {"action": "annotate", "strategy_id": "trend_donchian_eth_4h", "symbol": "ETHUSDT", "direction": "long",
         "account": "bybit_2", "order_package_id": "pkg-a", "would_be_multiplier": 0.5, "p_win": 0.2,
         "logged_at_utc": now.isoformat()},
        {"action": "annotate", "strategy_id": "trend_donchian_xrp_4h", "symbol": "XRPUSDT", "direction": "short",
         "account": "bybit_portfolio", "would_be_multiplier": 1.0, "p_win": 0.5,  # pre-canary row: no pkg id
         "logged_at_utc": now.isoformat()},
        {"action": "unscored", "strategy_id": "trend_donchian_sol_prop", "account": "bybit_portfolio"},
    ]
    tr = [
        {"id": 1, "status": "closed", "closed_at": "2026-10-31T00:00:00Z", "account_id": "bybit_portfolio",
         "order_package_id": "pkg-a", "strategy_name": "trend_donchian_eth_4h", "symbol": "ETHUSDT",
         "direction": "long", "pnl": 10.0, "fee_taker_usd": 12.0, "entry_price": 100, "stop_loss": 98,
         "position_size": 1, "timestamp": now.isoformat()},  # net -2: a LOSS once costs are taken
        {"id": 2, "status": "closed", "closed_at": "2026-10-31T01:00:00Z", "account_id": "bybit_portfolio",
         "order_package_id": "pkg-x", "strategy_name": "trend_donchian_xrp_4h", "symbol": "XRP/USDT:USDT",
         "direction": "short", "pnl": 5.0, "timestamp": (now + timedelta(minutes=3)).isoformat()},
        {"id": 3, "status": "open", "account_id": "bybit_portfolio", "order_package_id": "pkg-a", "pnl": None},
        {"id": 4, "status": "closed", "closed_at": "2026-10-31T02:00:00Z", "account_id": "bybit_portfolio",
         "order_package_id": "pkg-y", "strategy_name": "ada_pullback_2h", "symbol": "ADAUSDT",
         "direction": "long", "pnl": 1.0, "timestamp": now.isoformat()},
    ]
    j = join(sh, tr)
    from overlay_cusum import cusum
    c = cusum(j["rows"], "bybit_portfolio")
    r = {x["trade_id"]: x for x in j["rows"]}
    relay = ("## `log_file?name=overlay_shadow&lines=5`\n```json\n" + json.dumps(
        {"name": "overlay_shadow", "present": True, "lines": [json.dumps(sh[0])]}) + "\n```\n")
    ok = (set(r) == {1, 2} and r[1]["join_basis"] == "order_package_id" and r[1]["net_r"] < 0
          and r[2]["join_basis"] == "time_window" and j["n_unmatched_trades"] == 1
          and c["n_reduced"] == 1 and c["reduced_win_rate"] == 0.0 and len(load_shadow(relay)) == 1)
    print(json.dumps({"self_test": "PASS" if ok else "FAIL", "join": {k: v for k, v in j.items() if k != "rows"},
                      "cusum": c}, indent=1, default=str))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shadow", required=True, help="relay comment / log_file JSON / overlay_shadow.jsonl")
    ap.add_argument("--trades", required=True, nargs="+", help="relay comment(s) / journal?table=trades JSON pages")
    ap.add_argument("--account", default="bybit_portfolio")
    ap.add_argument("--window-min", type=float, default=10.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--cusum", action="store_true", help="also run scripts/ops/overlay_cusum.py on the joined rows")
    a = ap.parse_args(argv)
    texts = {"shadow": [Path(a.shadow).read_text(encoding="utf-8")],
             "trades": [Path(p).read_text(encoding="utf-8") for p in a.trades]}
    completeness = {k: [relay_completeness(t) for t in v] for k, v in texts.items()}
    j = join(load_shadow(texts["shadow"][0]),
             _dedupe([t for txt in texts["trades"] for t in load_trades(txt)]), a.window_min)
    if not all(c["complete"] for v in completeness.values() for c in v):
        j["read_state"] = "incomplete_read"  # a cut/unparsed relay block: the counts below are not a census
    if a.out:
        Path(a.out).write_text("".join(json.dumps(r, default=str) + "\n" for r in j["rows"]), encoding="utf-8")
    out = {k: v for k, v in j.items() if k != "rows"}
    out["input_completeness"] = completeness
    if a.cusum and j["read_state"] == "incomplete_read":
        out["cusum"] = {"state": "could_not_read", "note": "an input was truncated or unparsed; re-pull smaller pages"}
    elif a.cusum:
        from overlay_cusum import cusum
        out["cusum"] = cusum(j["rows"], None if a.account == "all" else a.account)
    print(json.dumps(out, indent=1, default=str))
    if j["read_state"] == "incomplete_read":
        return 2  # could not look: never reported as clean
    return 1 if (out.get("cusum") or {}).get("state") == "ALARM" else 0


if __name__ == "__main__":
    sys.exit(main())

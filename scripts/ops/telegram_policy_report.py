#!/usr/bin/env python3
"""TELEGRAM-TRIM dry run: every Telegram sender -> on / off / filtered, and the
policy replayed over real traffic. Read-only; sends nothing.

    python3 scripts/ops/telegram_policy_report.py                       # sender table only
    python3 scripts/ops/telegram_policy_report.py --trades T.json --operator-alerts OA.json

``--trades`` is a ``/api/diag/journal?table=trades&limit=N`` reply (a JSON list);
``--operator-alerts`` a ``/api/diag/log_file?name=operator_alerts&lines=N`` reply.
The window is the 24 h ending at the newest timestamp in the input; the report
states the population it measured over, and whether the window is fully covered
(a capped pull that does not reach back 24 h is said, never read as a full day).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.runtime import telegram_channels as tc  # noqa: E402
from src.runtime import telegram_policy as tp  # noqa: E402

_TRADE_KINDS = {"trade_opened", "trade_closed", "trade_updated", "trade-open", "trade-close",
                "trade-update", "demotrade"}


def kind_state(kind: str, pol: dict) -> str:
    if tp.recurring_off(kind, pol):
        return "OFF (recurring; recorded)"
    if kind in _TRADE_KINDS:
        return "FILTERED (one per package; testing paper recorded)"
    if kind == "execution_alert":
        return "ON (testing-paper rejections -> ledger only)"
    ch = tc.EVENT_CHANNEL.get(kind)
    if ch == tc.RETIRED:
        return "RETIRED (unchanged)"
    if ch == tc.REPLY:
        return "ON (command reply)"
    return "ON (event)"


def sender_table(pol: dict) -> list[str]:
    out = ["SENDER | KIND | CHANNEL | STATE"]
    for path, kinds in sorted(tc.SENDERS.items()):
        for k in kinds:
            out.append(f"{path} | {k} | {tc.EVENT_CHANNEL.get(k, '?')} | {kind_state(k, pol)}")
    out.append(".github/workflows/health-snapshot.yml | alert (6-hourly status) | system | "
               "OFF when level=ok (recurring); ON for watch/concern")
    return out


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def replay_trades(rows: list, pol: dict) -> list[str]:
    """Replay open + close events of the window through the policy (dedupe
    claims in a throwaway dict, not the VM store)."""
    events = []
    for r in rows:
        if r.get("is_backtest") or str(r.get("status")) == "rejected":
            continue
        t_open = _ts(r.get("created_at") or r.get("timestamp"))
        if t_open:
            events.append((t_open, "trade-open", r))
        t_close = _ts(r.get("closed_at"))
        if t_close and str(r.get("status")) == "closed":
            events.append((t_close, "trade-close", r))
    if not events:
        return ["trades: no events in the input"]
    newest = max(e[0] for e in events)
    oldest_row = min(_ts(r.get("created_at") or r.get("timestamp")) or newest for r in rows)
    start = newest - timedelta(hours=24)
    covered = oldest_row <= start
    seen: set = set()
    by: Counter = Counter()
    sent_lines = []
    for t, kind, r in sorted(events, key=lambda e: e[0]):
        if t < start:
            continue
        d = tp.trade_decision(kind, account=r.get("account_id"), strategy=r.get("strategy_name"),
                              symbol=r.get("symbol"), package_id=r.get("order_package_id"),
                              now=t.timestamp(), policy=pol)
        if d.send and d.dedupe_key in seen:
            by[(kind, "duplicate_package_event")] += 1
            continue
        if d.send:
            seen.add(d.dedupe_key)
            sent_lines.append(f"  SEND {t:%m-%d %H:%MZ} {kind:11} {r.get('account_id'):18} "
                              f"{r.get('strategy_name')} {r.get('symbol')}"
                              + (f" · {d.note}" if d.note else ""))
        by[(kind, d.reason)] += 1
    n = sum(by.values())
    acct = Counter(r.get("account_id") for t, k, r in events if t >= start)
    n_open = sum(1 for t, k, _ in events if t >= start and k == "trade-open")
    out = [f"trades: {n} open/close events in the 24 h to {newest:%Y-%m-%d %H:%MZ} "
           f"(population: {len(rows)} trade rows pulled; window "
           f"{'FULLY covered' if covered else 'NOT fully covered — the pull is capped; counts are a floor'}; "
           f"closes of trades opened before the oldest pulled row are not seen)",
           f"  before the policy (one per account per event; opens fire on two producer paths, "
           f"journal observer + execute enqueue): {n + n_open} pings",
           f"  under the policy: {sum(v for (k, why), v in by.items() if why.endswith('_send') or why == 'priority_bypass')} pings",
           "  by (event, decision): " + ", ".join(f"{k}/{why}={v}" for (k, why), v in sorted(by.items())),
           "  events by account: " + ", ".join(f"{a}={c}" for a, c in acct.most_common()),
           *sent_lines]
    return out


def replay_rejections(oa: dict, pol: dict) -> list[str]:
    lines = [json.loads(x) for x in (oa.get("lines") or []) if x.strip().startswith("{")]
    rows = [r for r in lines if r.get("kind") == "execution_failure"]
    if not lines:
        return ["rejections: no operator_alerts rows in the input"]
    newest = max(_ts(r.get("ts")) for r in lines if _ts(r.get("ts")))
    start = newest - timedelta(hours=24)
    covered = min(_ts(r.get("ts")) for r in lines if _ts(r.get("ts"))) <= start
    c: Counter = Counter()
    for r in rows:
        t = _ts(r.get("ts"))
        if not t or t < start:
            continue
        acct = r.get("account")
        if not acct:
            body = str(r.get("body") or "")
            acct = next((ln.split(":", 1)[1].strip() for ln in body.splitlines()
                         if ln.startswith("Account:")), None)
        c["ledger_only" if tp.rejection_ledger_only(acct, policy=pol) else f"ping:{tp.account_class(acct)}"] += 1
    kinds = Counter(r.get("kind") for r in lines if (_ts(r.get("ts")) or start) >= start)
    return [f"rejections (operator_alerts execution_failure, 24 h to {newest:%Y-%m-%d %H:%MZ}; "
            f"population {len(lines)} rows; window {'FULLY covered' if covered else 'NOT fully covered'}): "
            + (", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "none"),
            "  all operator_alerts kinds in window (unchanged by this policy unless execution_failure): "
            + ", ".join(f"{k}={v}" for k, v in kinds.most_common())]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trades")
    ap.add_argument("--operator-alerts")
    a = ap.parse_args(argv)
    pol = tp.load_policy()
    print("\n".join(sender_table(pol)))
    print("\nRECURRING (expected/day from timers, ESTIMATED from declared cadence, not measured): "
          "system_health 24 · trades_snapshot 24 · manager_update digest 24 · daily_heartbeat 1 · "
          "health-snapshot.yml 4 -> under the policy 0 (+ only NEW actionable digest items)")
    if a.trades:
        print()
        print("\n".join(replay_trades(json.loads(Path(a.trades).read_text()), pol)))
    if a.operator_alerts:
        print()
        print("\n".join(replay_rejections(json.loads(Path(a.operator_alerts).read_text()), pol)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

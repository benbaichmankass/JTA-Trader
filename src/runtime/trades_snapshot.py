"""TRADES channel periodic PERFORMANCE SNAPSHOT — every account, incl. prop.

Operator, 2026-10-11 (checklist row ``TELEGRAM-CHANNELS``): divide the CONTENT
of the periodic updates between channels. TRADES carries performance: trades
opened, trades closed (won / lost, R and $ P&L, exit reason), open positions
with unrealized where measured, per-account and total realized P&L for the
window, and notable events (protection repairs / stop moves, rejects). The
SYSTEM health check carries none of this; this carries no health.

POPULATION (stated in the message): ``trades`` rows with ``is_backtest = 0`` in
the canonical journal (``src.utils.paths.trade_journal_db_path``), plus
``prop_fills`` closed in the window (the prop executor's broker-screen report).
Window = since the last snapshot (``telegram_settings.window_start``).

PROVENANCE (``src/runtime/provenance.py``). A closed trade's ``pnl`` is bucketed
with ``classify_pnl``: MEASURED sums into "realized (measured)", ESTIMATED is
summed SEPARATELY, FABRICATED / UNVERIFIED are UNPRICED — counted and listed,
never summed and never called won or lost. R is
``r_provenance.r_multiple_provenanced`` (entry-time declared risk first); "—"
when it has no basis. Unrealized P&L is the broker position read
(``unrealised_pnl``) — "—" when the account was not read.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_REJECTED = ("rejected", "exchange_rejected", "rejected_too_small")
_MAX_LINES = 12


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _r(row: dict) -> float | None:
    try:
        from src.runtime.local_pnl import contract_value_usd_for
        from src.runtime.r_provenance import r_multiple_provenanced

        r, _basis = r_multiple_provenanced(row, contract_value_usd_for(row.get("symbol")))
        return r
    except Exception:  # noqa: BLE001 — R is optional; "—" when it cannot be computed
        return None


def gather(since: datetime, now: datetime, db_path: str | None = None) -> dict[str, Any]:
    """Read the journal. Never raises: ``read_state`` = ``read`` · ``absent`` ·
    ``error: …`` — "could not look" is never an empty window."""
    from src.runtime.provenance import ESTIMATED, MEASURED, classify_pnl

    if db_path is None:
        try:
            from src.utils.paths import trade_journal_db_path
            db_path = str(trade_journal_db_path())
        except Exception as exc:  # noqa: BLE001
            return {"read_state": f"error: {type(exc).__name__}"}
    s, e = since.astimezone(timezone.utc).isoformat(), now.astimezone(timezone.utc).isoformat()
    out: dict[str, Any] = {"read_state": "read", "opened": [], "closed": [], "open": [],
                           "rejects": [], "repairs": [], "prop_closed": [],
                           "prop_state": "read"}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"read_state": "absent"}
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(trades)")}
        if not cols:
            return {"read_state": "absent"}
        has_pkg = bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_packages'").fetchone())
        pkg_cols = {r[1] for r in conn.execute("PRAGMA table_info(order_packages)")} if has_pkg else set()
        meta_sel = ", op.meta AS package_meta" if "meta" in pkg_cols else ""
        join = (" LEFT JOIN order_packages op ON op.order_package_id = t.order_package_id"
                if meta_sel else "")
        base = f"SELECT t.*{meta_sel} FROM trades t{join} WHERE COALESCE(t.is_backtest,0)=0"

        def q(where: str, args: tuple) -> list[dict]:
            return [dict(r) for r in conn.execute(f"{base} AND {where}", args)]
        from src.utils.closed_at import closed_at_norm_sql

        # Both sides through datetime(): the journal mixes ISO-T+offset,
        # space-separated and epoch-ms encodings (src/utils/closed_at.py).
        created = "datetime(COALESCE(t.created_at, t.timestamp))"
        closed_ts = (f"datetime(COALESCE({closed_at_norm_sql('t.closed_at')}, t.timestamp))"
                     if "closed_at" in cols else "datetime(t.timestamp)")
        out["opened"] = q(f"COALESCE(t.status,'open') NOT IN {_REJECTED + ('orphaned',)} "
                          f"AND {created} >= datetime(?) AND {created} < datetime(?)", (s, e))
        out["closed"] = q(f"t.status = 'closed' AND {closed_ts} >= datetime(?) "
                          f"AND {closed_ts} < datetime(?)", (s, e))
        out["open"] = q("t.status = 'open'", ())
        out["rejects"] = q(f"t.status IN {_REJECTED} AND {created} >= datetime(?) "
                           f"AND {created} < datetime(?)", (s, e))
        if "protection_repair_last_at" in cols:
            out["repairs"] = q("datetime(t.protection_repair_last_at) >= datetime(?) "
                               "AND datetime(t.protection_repair_last_at) < datetime(?)", (s, e))
        try:
            from src.prop.exec_test_trades import exclude_exec_test
            out["prop_closed"] = exclude_exec_test([dict(r) for r in conn.execute(
                "SELECT * FROM prop_fills WHERE " + closed_at_norm_sql("closed_at")
                + " >= datetime(?) AND " + closed_at_norm_sql("closed_at")
                + " < datetime(?)", (s, e))], fills=True)   # MD-EXEC-DEV-TEST-TRADES: test trades are not performance
        except sqlite3.Error:
            out["prop_state"] = "absent"
    except sqlite3.Error as exc:
        logger.warning("trades_snapshot: journal read failed: %s", exc)
        return {"read_state": f"error: {type(exc).__name__}"}
    finally:
        conn.close()
    for t in out["closed"]:
        bucket, _why = classify_pnl(t)
        t["_prov"] = ("measured" if bucket == MEASURED else
                      "estimated" if bucket == ESTIMATED else "unpriced")
        t["_r"] = _r(t)
    return out


def _acct(t: dict) -> str:
    return str(t.get("account_id") or "—")


def _closed_line(t: dict) -> str:
    pnl = _f(t.get("pnl"))
    if t["_prov"] == "unpriced":
        tag = "⚪ unpriced"
    else:
        tag = ("🟢 won" if (pnl or 0) > 0 else "🔴 lost" if (pnl or 0) < 0 else "⚪ flat")
        if t["_prov"] == "estimated":
            tag += " (est.)"
    r = t.get("_r")
    r_s = f"R {r:+.2f}" if r is not None and t["_prov"] != "unpriced" else "R —"
    pnl_s = _money(pnl) if t["_prov"] != "unpriced" else "$ —"
    return (f"{tag} {t.get('strategy_name') or '—'} {t.get('symbol') or '—'} "
            f"{t.get('direction') or '—'} · {r_s} · {pnl_s} · exit {t.get('exit_reason') or '—'}")


def build_sections(data: dict, accounts: list | None = None):
    """``(headline, [Section…])`` for the snapshot."""
    from src.units.ui.telegram_format import Section

    if data.get("read_state") != "read":
        msg = (f"⚠️ trade journal NOT READ ({data.get('read_state')}) — we could not look; "
               "this is NOT 'no trades'.")
        return "📊 trades: ⚠️ journal NOT READ", [Section(summary="Trades — could not look", body=msg)]

    per: dict[str, dict] = defaultdict(lambda: {"measured": 0.0, "estimated": 0.0, "won": 0,
                                                "lost": 0, "unpriced": 0, "n_m": 0, "n_e": 0})
    for t in data["closed"]:
        a = per[_acct(t)]
        pnl = _f(t.get("pnl"))
        if t["_prov"] == "unpriced" or pnl is None:
            a["unpriced"] += 1
            continue
        if pnl:
            a["won" if pnl > 0 else "lost"] += 1
        key = "measured" if t["_prov"] == "measured" else "estimated"
        a[key] += pnl
        a["n_m" if key == "measured" else "n_e"] += 1
    for p in data.get("prop_closed") or []:
        a = per[str(p.get("account_id") or "—")]
        pnl = _f(p.get("pnl"))
        if pnl is None:
            a["unpriced"] += 1
            continue
        if pnl:
            a["won" if pnl > 0 else "lost"] += 1
        a["measured"] += pnl  # broker-screen report from the prop executor
        a["n_m"] += 1

    tot_m = sum(a["measured"] for a in per.values())
    tot_e = sum(a["estimated"] for a in per.values())
    n_unp = sum(a["unpriced"] for a in per.values())
    won = sum(a["won"] for a in per.values())
    lost = sum(a["lost"] for a in per.values())
    n_closed = len(data["closed"]) + len(data.get("prop_closed") or [])
    head = (f"📊 trades: {len(data['opened'])} opened · {n_closed} closed "
            f"({won}W/{lost}L{f'/{n_unp} unpriced' if n_unp else ''}) · "
            f"realized {_money(tot_m)} measured"
            + (f" {_money(tot_e)} est." if tot_e else "") + f" · {len(data['open'])} open")

    def cap(lines: list[str]) -> list[str]:
        return lines[:_MAX_LINES] + ([f"… +{len(lines) - _MAX_LINES} more"] if len(lines) > _MAX_LINES else [])

    pnl_lines = []
    for aid in sorted(per):
        a = per[aid]
        pnl_lines.append(
            f"{aid}: {_money(a['measured'])} measured (n={a['n_m']})"
            + (f" · {_money(a['estimated'])} est. (n={a['n_e']})" if a["n_e"] else "")
            + (f" · {a['unpriced']} unpriced (not summed)" if a["unpriced"] else "")
            + f" · {a['won']}W/{a['lost']}L")
    pnl_lines.append(f"TOTAL: {_money(tot_m)} measured"
                     + (f" · {_money(tot_e)} estimated (separate)" if tot_e else "")
                     + (f" · {n_unp} unpriced, NOT summed" if n_unp else ""))

    closed_lines = [f"{_acct(t)}: {_closed_line(t)}" for t in data["closed"]]
    closed_lines += [f"{p.get('account_id') or '—'}: prop {p.get('symbol') or '—'} "
                     f"{p.get('direction') or '—'} · {_money(_f(p.get('pnl')))} · "
                     f"exit {p.get('reason') or '—'} (prop report)"
                     for p in data.get("prop_closed") or []]
    opened_lines = [f"{_acct(t)}: {t.get('strategy_name') or '—'} {t.get('symbol') or '—'} "
                    f"{t.get('direction') or '—'} @ {t.get('entry_price') or '—'} "
                    f"qty {t.get('position_size') or '—'}" for t in data["opened"]]

    # open positions: broker read where it exists (unrealized MEASURED), else
    # the journal's open rows with unrealized "—"
    pos_lines, read_accts = [], set()
    for a in accounts or []:
        if isinstance(a.get("positions"), list):
            read_accts.add(a.get("account_id"))
            for p in a["positions"]:
                pos_lines.append(f"{a.get('account_id')}: {p.get('symbol') or '—'} "
                                 f"{p.get('side') or '—'} {p.get('size') or '—'} @ "
                                 f"{p.get('entry_price') or '—'} · uPnL "
                                 f"{_money(_f(p.get('unrealised_pnl')))}")
    for t in data["open"]:
        if _acct(t) not in read_accts:
            pos_lines.append(f"{_acct(t)}: {t.get('symbol') or '—'} {t.get('direction') or '—'} "
                             f"@ {t.get('entry_price') or '—'} · uPnL — (account not read)")

    ev = [f"{_acct(t)}: stop/protection {t.get('protection_repair_last_kind') or 'repair'} "
          f"{t.get('symbol') or '—'} (trade {t.get('id')})" for t in data["repairs"]]
    ev += [f"{_acct(t)}: REJECTED {t.get('symbol') or '—'} {t.get('direction') or '—'} "
           f"({t.get('status')})" for t in data["rejects"]]

    secs = [
        Section(summary="Realized P&L by account", body="\n".join(pnl_lines), priority=10),
        Section(summary=f"Closed — {n_closed}", body="\n".join(cap(closed_lines)) or "none",
                priority=20),
        Section(summary=f"Opened — {len(data['opened'])}", body="\n".join(cap(opened_lines)) or "none",
                priority=30),
        Section(summary=f"Open positions — {len(pos_lines)}", body="\n".join(cap(pos_lines)) or "none",
                priority=40),
        Section(summary=f"Notable — {len(ev)} (stop moves / repairs, rejects)",
                body="\n".join(cap(ev)) or "none", priority=50),
    ]
    return head, secs


def render(data: dict, *, since: datetime, now: datetime,
           accounts: list | None = None) -> str:
    from src.units.ui.telegram_format import render_html_fitted

    head, secs = build_sections(data, accounts)
    pop = (f"Population: journal trades (is_backtest=0) + prop_fills, "
           f"{since:%m-%d %H:%M}–{now:%H:%M}Z")
    if data.get("prop_state") == "absent":
        pop += " · prop_fills NOT READ"
    return render_html_fitted(
        header=f"📈 Performance snapshot · {now:%Y-%m-%d %H:00}Z\n{head}",
        sections=secs, footer=pop)

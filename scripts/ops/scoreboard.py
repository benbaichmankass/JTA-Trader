#!/usr/bin/env python3
"""THE SCOREBOARD — net $ and % per book, trials vs survivors, measured cost per trade.

Row ``SCOREBOARD-PNL-FIRST`` (docs/audits/2026-11-01-from-scratch/AUDIT.md § 1a-1c, § 7 day 1-3): the brief had no
P&L line at all. This is the ONE script behind the API route (``GET /api/bot/work/scoreboard``) and brief §1.

Gates this adds or changes: none (Tier-1 read path; nothing here writes, blocks or gates).

Rules this module keeps (CLAUDE.md RULE ONE / "Numbers carry provenance"):

* **Every number names its population and an explicit read-state.** A block we could not read is
  ``read_state: unreadable`` with every number ``None`` — never ``0``. A null renders as a dash.
* **MEASURED vs ESTIMATED is never folded.** Cost per trade is bucketed by ``cost_source`` using the
  ``src.runtime.provenance`` vocabulary (``broker`` → MEASURED, ``estimate`` → ESTIMATED, anything else →
  UNVERIFIED) and each bucket is summed on its own. Realized P&L carries ``provenance.classify_pnl`` coverage.
* **The population is the AUDIT's.** Closed rows with a non-null ``pnl`` in ``trades``; the closed rows WITHOUT a
  price are counted beside it (``closed_unpriced``), not dropped silently. Books split by ``account_class`` plus the
  Stage-2 mirror accounts (``*_portfolio``). Reproduces AUDIT § 1a at its 2026-11-01 ~08:20Z cutoff (``--as-of``).
* **% = net $ / broker equity at the window start** (operator 2026-11-06, "Broker equity at start (Rec.)") for real money,
  mirror and paper, read from ``balance_snapshots`` (hourly broker reads); prop keeps ``account_size_usd``. No readable
  start equity → ``pct: None`` + ``pct_state`` (``no_start_equity`` / ``partial``), never 0.

Sources: ``db`` (the VM's ``trade_journal.db``, read-only), ``diag`` (the public read-only diag relay, for sessions
off the VM) or ``file`` (a JSON list of trade rows). Usage::

    python3 scripts/ops/scoreboard.py --source diag --as-of 2026-11-01T08:20:00Z
    python3 scripts/ops/scoreboard.py --source db --format json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.runtime import provenance as prov  # noqa: E402

SCHEMA_VERSION = 1
TRAILING_DAYS = 30
BOOKS = ("real_money", "prop", "mirror", "paper")
BOOK_LABEL = {"real_money": "Real money", "prop": "Prop", "mirror": "Mirror (Stage-2 paper twin)", "paper": "Paper (soak + floor)"}
#: Stage-2 mirrors carry ``account_class: paper`` but are their own book (AUDIT § 1a).
MIRROR_SUFFIX = "_portfolio"
#: ``cost_source`` → provenance bucket. ``provenance.classify`` does not know this column's vocabulary.
_COST_BUCKET = {"broker": prov.MEASURED, "estimate": prov.ESTIMATED}
_COST_COLS = ("fee_taker_usd", "fee_maker_usd", "funding_paid_usd")
_DASH = "—"


# ── small helpers ──────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_ts(row: dict) -> datetime | None:
    """Close time, falling back to entry time (AUDIT reproduces on either)."""
    return _parse_ts(row.get("closed_at")) or _parse_ts(row.get("timestamp"))


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def book_of(row: dict) -> str | None:
    acct = str(row.get("account_id") or "")
    cls = str(row.get("account_class") or "")
    if cls == "real_money":
        return "real_money"
    if cls == "prop":
        return "prop"
    if cls == "paper":
        return "mirror" if acct.endswith(MIRROR_SUFFIX) else "paper"
    return None


def fmt_money(v: float | None) -> str:
    return _DASH if v is None else f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def fmt_pct(v: float | None) -> str:
    return _DASH if v is None else f"{v:+.2f}%"


def fmt_num(v: float | None, nd: int = 2) -> str:
    return _DASH if v is None else f"{v:.{nd}f}"


# ── start-of-window broker equity (the % basis) ───────────────────────────
#
# OPERATOR 2026-11-06 ~00:50Z (popup, verbatim): "Broker equity at start (Rec.)". % = net $ / broker-read account equity at
# the START of the window, so it follows deposits and withdrawals. Source: `balance_snapshots` (hourly, broker read,
# `api_ok`). Prop keeps `account_size_usd`. Where no start equity can be read the % is None with a read-state, never 0.
EQUITY_TOLERANCE = timedelta(hours=48)  # a snapshot older than this before the window start is not "equity at start"


def _snap_index(snapshots: list[dict] | None) -> dict[str, list[tuple[datetime, float]]]:
    idx: dict[str, list[tuple[datetime, float]]] = {}
    for r in snapshots or []:
        ts, bal = _parse_ts(r.get("ts")), _num(r.get("balance"))
        if ts is None or bal is None or not r.get("api_ok", 1) or bal <= 0:
            continue  # a failed read (api_ok=0 / NULL balance) is a gap, not an equity of 0
        idx.setdefault(str(r.get("account_id")), []).append((ts, bal))
    for v in idx.values():
        v.sort()
    return idx


def start_equity(idx: dict[str, list[tuple[datetime, float]]], account: str, start: datetime | None) -> tuple[float | None, datetime | None]:
    """Equity of *account* at *start* (``None`` = inception → its first snapshot). Returns ``(equity, snapshot_ts)``."""
    pts = idx.get(account) or []
    if not pts:
        return None, None
    if start is None:
        return pts[0][1], pts[0][0]
    prior = [p for p in pts if p[0] <= start]
    if not prior or start - prior[-1][0] > EQUITY_TOLERANCE:
        return None, None
    return prior[-1][1], prior[-1][0]


def pct_for_window(rows: list[dict], idx: dict, start: datetime | None, until: datetime) -> dict[str, Any]:
    """Σ net / Σ start equity over the accounts of *rows* that have a readable start equity.

    Each account's numerator only counts trades closed at/after ITS start snapshot, so numerator and denominator cover the
    same period (inception starts at an account's first snapshot, which can be later than its first trade)."""
    accts = sorted({str(r.get("account_id")) for r in rows})
    net = eq = 0.0
    used: list[str] = []
    missing: list[str] = []
    n_used = 0
    for a in accts:
        e, snap_ts = start_equity(idx, a, start)
        if e is None:
            missing.append(a)
            continue
        win_start = snap_ts if start is None else start
        sub = [r for r in rows if str(r.get("account_id")) == a and (_row_ts(r) or until) >= win_start]
        net += sum(float(r["pnl"]) for r in sub)
        n_used += len(sub)
        eq += e
        used.append(f"{a}@{snap_ts:%Y-%m-%d}")
    if not accts:
        return {"pct": None, "pct_state": "empty", "pct_basis": "no priced closes in the window"}
    if not used:
        return {"pct": None, "pct_state": "no_start_equity",
                "pct_basis": f"no readable broker equity at window start for {','.join(missing)}"}
    return {"pct": round(100.0 * net / eq, 2), "pct_state": "partial" if missing else "read",
            "pct_basis": (f"net of {n_used} trades / Σ broker equity at start ({','.join(used)}; "
                          "balance_snapshots, broker read, MEASURED)" + (f"; NO start equity for {','.join(missing)}" if missing else "")),
            "pct_start_equity_usd": round(eq, 2)}


# ── aggregation ────────────────────────────────────────────────────────────

def aggregate(rows: list[dict], population: str) -> dict[str, Any]:
    """Net / PF / win% over *rows* (already priced + closed). Empty → read_state ``empty``, numbers None."""
    n = len(rows)
    if n == 0:
        return {"read_state": "empty", "population": population, "n": 0, "net_usd": None, "profit_factor": None,
                "win_pct": None, "pnl_measured_share": None}
    pnls = [float(r["pnl"]) for r in rows]
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    counts = {prov.MEASURED: 0, prov.ESTIMATED: 0, prov.FABRICATED: 0, prov.UNVERIFIED: 0, "total": n}
    for r in rows:
        counts[prov.classify_pnl(r)[0]] += 1
    return {
        "read_state": "read", "population": population, "n": n,
        "net_usd": round(sum(pnls), 2),
        "profit_factor": round(gw / gl, 2) if gl > 0 else None,
        "win_pct": round(100.0 * sum(p > 0 for p in pnls) / n, 1),
        # share of this population's pnl whose own provenance keys say MEASURED (provenance.coverage).
        "pnl_measured_share": prov.coverage(counts),
        "pnl_provenance_counts": {k: counts[k] for k in (prov.MEASURED, prov.ESTIMATED, prov.FABRICATED, prov.UNVERIFIED)},
    }


def _window(rows: list[dict], since: datetime | None, until: datetime) -> list[dict]:
    out = []
    for r in rows:
        ts = _row_ts(r)
        if ts is None or ts > until or (since is not None and ts < since):
            continue
        out.append(r)
    return out


def trade_books(rows: Iterable[dict], now: datetime, snapshots: list[dict] | None = None) -> dict[str, Any]:
    """Real-money / mirror / paper from the ``trades`` journal (prop is added separately)."""
    rows = [r for r in rows if not r.get("is_backtest")]
    closed = [r for r in rows if r.get("status") == "closed"]
    since30 = now - timedelta(days=TRAILING_DAYS)
    idx = _snap_index(snapshots)
    out: dict[str, Any] = {}
    for book in ("real_money", "mirror", "paper"):
        b_closed = [r for r in closed if book_of(r) == book]
        priced = [r for r in b_closed if _num(r.get("pnl")) is not None]
        unpriced = len(b_closed) - len(priced)
        pop_base = f"{book} accounts, trades journal, status=closed AND pnl NOT NULL, is_backtest=0, closed by {now:%Y-%m-%dT%H:%MZ}"
        inc = _window(priced, None, now)
        t30 = _window(priced, since30, now)
        out[book] = {
            "book": book, "label": BOOK_LABEL[book],
            "closed_unpriced": unpriced,
            "capital_basis": "broker equity at window start (balance_snapshots)",
            "inception": {**aggregate(inc, pop_base + " (inception→now)"), **pct_for_window(inc, idx, None, now)},
            "trailing_30d": {**aggregate(t30, pop_base + f" and closed in the last {TRAILING_DAYS} d"),
                             **pct_for_window(t30, idx, since30, now)},
        }
    return out


# ── prop (venue equity vs declared account size; fills for the trailing window) ──

def prop_book(overview: dict | None, fills: dict | None, sizes: dict[str, float], now: datetime) -> dict[str, Any]:
    base = {"book": "prop", "label": BOOK_LABEL["prop"], "closed_unpriced": None}
    dash = {"read_state": "unreadable", "n": None, "net_usd": None, "pct": None, "profit_factor": None, "win_pct": None,
            "pnl_measured_share": None}
    if not isinstance(overview, dict) or overview.get("present") is False or not (overview.get("equity") or {}).get("accounts"):
        why = "prop overview unreadable — we did not look; this is not zero"
        return {**base, "capital_basis_usd": None, "pct_state": "unreadable",
                "inception": {**dash, "population": why}, "trailing_30d": {**dash, "population": why}}
    accts = [a for a in overview["equity"]["accounts"] if a.get("counted_in_total") and a.get("equity") is not None
             and a.get("account_id") in sizes]
    total_size = sum(sizes[a["account_id"]] for a in accts)
    net = sum(float(a["equity"]) - sizes[a["account_id"]] for a in accts)
    names = ",".join(a["account_id"] for a in accts)
    inc = {
        "read_state": "read" if accts else "empty",
        "population": (f"{len(accts)} of {overview['equity'].get('accounts_total')} prop accounts ({names}); "
                       "net = latest operator-reported/venue equity − declared account_size_usd; equity snapshot "
                       f"as of {overview.get('generated_at')} — a point-in-time read, so it does NOT move with --as-of"),
        "n": None, "net_usd": round(net, 2) if accts else None,
        "pct": round(100.0 * net / total_size, 2) if accts and total_size else None,
        "profit_factor": None, "win_pct": None, "pnl_measured_share": None,
        "equity_provenance": sorted({str(a.get("unrealized_provenance") or "unverified") for a in accts}),
    }
    rows = (fills or {}).get("fills") if isinstance(fills, dict) else None
    if rows is None or (fills or {}).get("present") is False:
        t30: dict[str, Any] = {**dash, "population": "prop fills unreadable — we did not look; this is not zero"}
        unpriced = None
    else:
        since30 = now - timedelta(days=TRAILING_DAYS)
        closed = []
        for r in rows:
            if r.get("status") != "closed":
                continue
            ts = _parse_ts(r.get("closed_at"))
            if ts is not None and since30 <= ts <= now:
                closed.append(r)
        priced = [r for r in closed if _num(r.get("pnl")) is not None]
        unpriced = len(closed) - len(priced)
        agg = aggregate([{**r, "pnl": float(r["pnl"])} for r in priced], "")
        # fills are venue/operator reports or inferred closes; their own `provenance` key is read, not assumed.
        shares: dict[str, int] = {}
        for r in priced:
            try:
                p = str((json.loads(r.get("raw") or "{}")).get("provenance") or "unverified").lower()
            except ValueError:
                p = "unverified"
            shares[p] = shares.get(p, 0) + 1
        trunc = " (fills list is capped at 500 — older closes may be missing)" if len(rows) >= 500 else ""
        t30 = {k: agg[k] for k in ("read_state", "n", "net_usd", "profit_factor", "win_pct")}
        t30.update({"pct": round(100.0 * agg["net_usd"] / total_size, 2) if agg["net_usd"] is not None and total_size else None,
                    "pnl_measured_share": None, "fill_provenance_counts": shares,
                    "population": (f"prop fills, status=closed AND pnl NOT NULL, closed in the last {TRAILING_DAYS} d, "
                                   f"{unpriced} closed-unpriced excluded{trunc}")})
    return {**base, "closed_unpriced": unpriced, "capital_basis_usd": total_size or None, "pct_state": "declared_account_size",
            "inception": inc, "trailing_30d": t30}


# ── cost per trade ─────────────────────────────────────────────────────────

def cost_block(rows: Iterable[dict], now: datetime) -> dict[str, Any]:
    """Per-trade cost (fees + funding, USD) on the real-money closed priced population, split by provenance."""
    pop = [r for r in rows if not r.get("is_backtest") and r.get("status") == "closed" and _num(r.get("pnl")) is not None
           and book_of(r) == "real_money" and (_row_ts(r) or now) <= now]
    buckets: dict[str, dict[str, Any]] = {b: {"n": 0, "usd": 0.0} for b in (prov.MEASURED, prov.ESTIMATED, prov.UNVERIFIED)}
    for r in pop:
        costs = [_num(r.get(c)) for c in _COST_COLS]
        if all(c is None for c in costs):
            b = prov.UNVERIFIED  # no cost recorded at all — uncosted, never 0
            usd = 0.0
        else:
            b = _COST_BUCKET.get(str(r.get("cost_source") or ""), prov.UNVERIFIED)
            usd = sum(c for c in costs if c is not None)
        buckets[b]["n"] += 1
        buckets[b]["usd"] += usd
    n = len(pop)
    pop_s = f"real-money closed priced trades, closed by {now:%Y-%m-%dT%H:%MZ}"
    out: dict[str, Any] = {"population": pop_s, "n": n, "read_state": "read" if n else "empty", "buckets": {}}
    for b, v in buckets.items():
        out["buckets"][b] = {"n": v["n"], "total_usd": round(v["usd"], 2) if v["n"] else None,
                             "per_trade_usd": round(v["usd"] / v["n"], 4) if v["n"] else None}
    # never folded: MEASURED and ESTIMATED are separate numbers; the share says how little is measured.
    out["measured_share"] = round(buckets[prov.MEASURED]["n"] / n, 4) if n else None
    net = sum(float(r["pnl"]) for r in pop)
    out["real_money_net_usd"] = round(net, 2) if n else None
    out["estimated_vs_net_note"] = (
        f"ESTIMATED ${buckets[prov.ESTIMATED]['usd']:,.2f} (not measured) against net {fmt_money(net)}" if n else None)
    return out


# ── trials vs survivors ────────────────────────────────────────────────────

def trials_block(root: Path) -> dict[str, Any]:
    paths = sorted(root.glob("comms/research/*/*/trial_ledger.json"),
                   key=lambda p: (json.loads(p.read_text()).get("generated_at") or "") if p.exists() else "")
    if not paths:
        return {"read_state": "unreadable", "population": "comms/research/*/*/trial_ledger.json — none found; we did not look",
                "configs_tried": None, "stage0_pass": None, "survivors": None}
    try:
        d = json.loads(paths[-1].read_text())
        fam = d["families"]
        s = d["summary"]
        return {
            "read_state": "read",
            "population": (f"{paths[-1].relative_to(root)} generated {d.get('generated_at')} by scripts/research/trial_ledger.py; "
                           f"{s.get('evidence_records')} evidence records; report_only={d.get('report_only')}"),
            "generated_at": d.get("generated_at"),
            "configs_tried": sum(int(v.get("n_configs") or 0) for v in fam.values()),
            "configs_tried_by_family": {k: int(v.get("n_configs") or 0) for k, v in fam.items() if v.get("n_configs")},
            "stage0_pass": s.get("stage0_pass"),
            "survivors": s.get("stage0_pass_surviving_dsr_and_bhy_haircut"),
            "survivor_rule": (d.get("method") or {}).get("survival"),
            "real_money_legs": len(s.get("real_money_legs") or []),
        }
    except (KeyError, ValueError, TypeError) as exc:
        return {"read_state": "unreadable", "population": f"trial ledger present but unparseable ({exc!r})",
                "configs_tried": None, "stage0_pass": None, "survivors": None}


# ── assembly ───────────────────────────────────────────────────────────────

def compute(rows: list[dict], *, now: datetime, overview: dict | None = None, fills: dict | None = None,
            sizes: dict[str, float] | None = None, root: Path | None = None, source: str = "rows",
            snapshots: list[dict] | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    books = trade_books(rows, now, snapshots)
    books["prop"] = prop_book(overview, fills, sizes or {}, now)
    return {
        "schemaVersion": SCHEMA_VERSION, "asOf": now.replace(microsecond=0).isoformat(), "source": source,
        "readState": "read", "rowsRead": len(rows),
        "snapshotsRead": None if snapshots is None else len(snapshots),
        "books": {b: books[b] for b in BOOKS},
        "cost": cost_block(rows, now),
        "trials": trials_block(root),
    }


def unreadable(reason: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {"schemaVersion": SCHEMA_VERSION, "asOf": now.replace(microsecond=0).isoformat(), "source": None,
            "readState": "unreadable", "reason": reason, "rowsRead": None, "books": None, "cost": None, "trials": None}


# ── loaders ────────────────────────────────────────────────────────────────

def prop_sizes(root: Path | None = None) -> dict[str, float]:
    from src.config.accounts_loader import load_accounts_dict  # noqa: PLC0415
    accts = load_accounts_dict(Path(root or REPO_ROOT) / "config/accounts.yaml")
    return {k: float(v["account_size_usd"]) for k, v in accts.items()
            if isinstance(v, dict) and v.get("account_class") == "prop" and v.get("account_size_usd")}


def rows_from_db(path: str) -> list[dict]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM trades")]
    finally:
        con.close()


def snapshots_from_db(path: str) -> list[dict] | None:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT account_id, balance, api_ok, ts FROM balance_snapshots")]
        finally:
            con.close()
    except sqlite3.Error:
        return None  # unreadable → every % renders a dash + no_start_equity, never 0


def snapshots_from_diag() -> list[dict] | None:
    try:
        rows: list[dict] = []
        off = 0
        while True:
            d = _diag(f"journal?table=balance_snapshots&limit=1000&offset={off}&envelope=1")
            rows += d["rows"]
            if not d.get("has_more"):
                return rows
            off += 1000
    except Exception:  # noqa: BLE001  # allow-silent: None = could not look; pct renders a dash with state no_start_equity
        return None


def _diag(path: str) -> Any:
    p = subprocess.run([str(REPO_ROOT / "scripts/ops/diag_fetch.sh"), path], capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError(f"diag_fetch {path} exit {p.returncode}")
    return json.loads(p.stdout)


def rows_from_diag() -> list[dict]:
    rows: list[dict] = []
    off = 0
    while True:
        d = _diag(f"journal?table=trades&limit=1000&offset={off}&envelope=1")
        rows += d["rows"]
        if not d.get("has_more"):
            return rows
        off += 1000


def _http_json(path: str) -> Any:
    import urllib.request  # noqa: PLC0415
    tok = os.environ.get("DASHBOARD_API_TOKEN", "").strip()   # UI-OAUTH-SIGNIN: GET service bearer
    req = urllib.request.Request(f"https://ict-bot.duckdns.org/api/bot/{path}",
                                 headers={"Authorization": f"Bearer {tok}"} if tok else {})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.load(r)


def prop_from_vm() -> tuple[dict | None, dict | None]:
    """Direct (on-VM) prop reads; each degrades to None independently."""
    ov = fl = None
    try:
        from src.prop import prop_journal, prop_overview  # noqa: PLC0415
        ov = {"present": True, **prop_overview.build_overview("7d")}
        fl = {"present": bool(prop_journal.tables_present()), "fills": prop_journal.list_fills(account_id=None, limit=500)}
    except Exception:  # noqa: BLE001  # allow-silent: a missing prop read is reported as unreadable by prop_book, never as zero
        pass
    return ov, fl


def build(*, root: Path | None = None, now: datetime | None = None, source: str = "db", rows_file: str | None = None) -> dict[str, Any]:
    """Assemble the scoreboard. stdout is diverted to stderr for the duration: importing the prop/DB modules prints
    '✓ Database tables created/verified', which would corrupt a caller's `--json` stdout (render_daily_brief --json)."""
    import contextlib  # noqa: PLC0415
    with contextlib.redirect_stdout(sys.stderr):
        return _build(root=root, now=now, source=source, rows_file=rows_file)


def _build(*, root: Path | None, now: datetime | None, source: str, rows_file: str | None) -> dict[str, Any]:
    root = Path(root or REPO_ROOT)
    now = now or datetime.now(timezone.utc)
    snaps: list[dict] | None = None
    try:
        if source == "file":
            rows = json.loads(Path(rows_file or "").read_text())
        elif source == "diag":
            rows = rows_from_diag()
            snaps = snapshots_from_diag()
        else:
            from src.utils.paths import trade_journal_db_path  # noqa: PLC0415
            db = trade_journal_db_path()
            if not Path(db).exists():
                return unreadable(f"no trade journal at {db} (not on the live VM) — we did not look; this is not zero", now)
            rows = rows_from_db(db)
            snaps = snapshots_from_db(db)
    except Exception as exc:  # noqa: BLE001 — unreadable is a state, not a crash
        return unreadable(f"trades unreadable: {exc!r}", now)
    if source == "db":
        ov, fl = prop_from_vm()
    else:
        try:
            ov, fl = _http_json("prop/overview"), _http_json("prop/fills?limit=500")
        except Exception:  # noqa: BLE001  # allow-silent: prop_book renders None as unreadable
            ov = fl = None
    try:
        sizes = prop_sizes(root)
    except Exception:  # noqa: BLE001  # allow-silent: no sizes → prop renders unreadable
        sizes = {}
    return compute(rows, now=now, overview=ov, fills=fl, sizes=sizes, root=root, source=source, snapshots=snaps)


# ── rendering (brief §1) ───────────────────────────────────────────────────

def render_lines(sb: dict | None) -> list[str]:
    L = ["### SCOREBOARD — net P&L per book, trials vs survivors, measured cost", ""]
    if not sb or sb.get("readState") != "read":
        reason = (sb or {}).get("reason") or "scoreboard not built"
        return L + [f"**Scoreboard {_DASH} we could not look** ({reason}). This is not zero.", ""]
    L += [f"_As of {sb['asOf']} · source `{sb['source']}` · {sb['rowsRead']} journal rows read. `—` = no number "
          "(unreadable / empty / no capital basis). Populations are in the JSON (`/api/bot/work/scoreboard`)._", "",
          "| book | inception net | inception % | n | PF | trailing 30 d net | 30 d % | n | PF | pnl measured |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for b in BOOKS:
        bk = sb["books"][b]
        i, t = bk["inception"], bk["trailing_30d"]
        share = i.get("pnl_measured_share")
        L.append(f"| {bk['label']} | {fmt_money(i['net_usd'])} | {fmt_pct(i.get('pct'))} | {i['n'] if i['n'] is not None else _DASH} "
                 f"| {fmt_num(i['profit_factor'])} | {fmt_money(t['net_usd'])} | {fmt_pct(t.get('pct'))} "
                 f"| {t['n'] if t['n'] is not None else _DASH} | {fmt_num(t['profit_factor'])} "
                 f"| {_DASH if share is None else f'{share * 100:.0f}%'} |")
    L += ["", "Paper and mirror dollars are paper notional, not money. % = net / broker equity at window start "
          "(`balance_snapshots`; prop: declared `account_size_usd`); `—` where no start equity could be read."]
    c = sb["cost"]
    if c and c.get("read_state") == "read":
        m, e, u = (c["buckets"][k] for k in (prov.MEASURED, prov.ESTIMATED, prov.UNVERIFIED))
        ms = _DASH if c["measured_share"] is None else "{:.1f}%".format(c["measured_share"] * 100)
        L += ["", f"**Cost per trade** ({c['population']}; n={c['n']}): MEASURED {fmt_num(m['per_trade_usd'], 3)} $/trade (n={m['n']}) · "
              f"ESTIMATED {fmt_num(e['per_trade_usd'], 3)} $/trade (n={e['n']}) · UNVERIFIED/uncosted n={u['n']}. "
              f"Measured share {ms}; "
              "estimated is not folded into measured."]
    else:
        L += ["", f"**Cost per trade** {_DASH} (no priced real-money closes read)."]
    t = sb["trials"]
    if t and t.get("read_state") == "read":
        L += ["", f"**Trials vs survivors** ({t['population']}): {t['configs_tried']} configs tried · {t['stage0_pass']} Stage-0 pass · "
              f"**{t['survivors']} survive** ({t['survivor_rule']})."]
    else:
        L += ["", f"**Trials vs survivors** {_DASH} ({(t or {}).get('population', 'not read')})."]
    return L + [""]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", choices=("db", "diag", "file"), default="db")
    ap.add_argument("--rows-file")
    ap.add_argument("--as-of", help="ISO UTC cutoff (e.g. 2026-11-01T08:20:00Z); default now")
    ap.add_argument("--format", choices=("json", "md"), default="md")
    a = ap.parse_args(argv)
    now = _parse_ts(a.as_of) if a.as_of else None
    sb = build(now=now, source=a.source, rows_file=a.rows_file)
    print(json.dumps(sb, indent=2) if a.format == "json" else "\n".join(render_lines(sb)))
    return 0 if sb["readState"] == "read" else 1


if __name__ == "__main__":
    raise SystemExit(main())

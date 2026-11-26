#!/usr/bin/env python3
# wiring: row LTR-PHANTOM-GIVEBACK-PRE-ENTRY-BARS part (C); one-shot audit, writes docs/research/ltr-phantom-peak-audit-2026-11-26/
"""Audit: which past live-review CLOSE / TIGHTEN / PARTIAL rows acted on a peak measured over PRE-FILL bars.

Row LTR-PHANTOM-GIVEBACK-PRE-ENTRY-BARS (2026-11-26, live money; operator: "These both sound like good trades for the ml
entry that weren't managed well"). Until PR #29238, position_telemetry measured peak_r over a window anchored on
meta.entry_time, which several legs stamp as the DECISION bar's open, and which always included the bar containing the
entry. A review's state.peak_r could therefore be a pre-fill extreme.

Population: every row of comms/live_review/reviews.jsonl whose recommendation.action is close / tighten_sl /
partial_close (stated in the output with its date range).

Per row (each field carries a read_state; could-not-look is never written as clean):
  * fill_at        = the latest of the package's created_at and meta.entry_time (the same anchor #29238 uses)
  * true_peak_r    = MFE in R over leg-timeframe bars that OPENED at/after fill_at and CLOSED at/before reviewed_at,
                     floored at the review's own open_r (the live price), entry and 1R from the package
  * excess_r       = state.peak_r (what the reviewer saw) - true_peak_r
  * contaminated   = excess_r >= 0.25 R  (the pre-fill bar supplied the peak the review read)
  * excursion_basis = the trigger was giveback / new_peak / r_milestone, or the reason cites giveback / peak / MFE
  * applied        = a trade whose notes.live_review_actions carries this review_id, OR (closes) a trade of the same
                     package closed with exit_reason live_review_close within 60 min of reviewed_at
  * counterfactual (applied closes only): from the review time, the ORIGINAL bracket replayed on the same bars
                     (stop first on a both-touch bar; open at the end of the data = marked at the last close)
                     -> cf_r; realised_r = the review's open_r; forfeited_r = cf_r - realised_r
Gross of costs. Read-only: GET /api/diag/journal (order_packages, trades) and GET /api/bot/candles.

  python3 scripts/research/ltr_phantom_peak_audit.py [--out-dir docs/research/ltr-phantom-peak-audit-2026-11-26]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = "https://ict-bot.duckdns.org"
ACTIONS = ("close", "tighten_sl", "partial_close")
EXCURSION_EVENTS = ("giveback", "new_peak", "r_milestone")
TF = {"m": 60, "h": 3600, "d": 86400}


def _ts(v) -> float | None:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def _get(path: str, **params):
    import requests
    r = requests.get(BASE + path, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def page_table(table: str, want: set, key: str, max_pages: int = 20) -> dict:
    out = {}
    for p in range(max_pages):
        rows = _get("/api/diag/journal", table=table, limit=1000, offset=p * 1000)
        if not rows:
            break
        for r in rows:
            k = str(r.get(key))
            if k in want or not want:
                out.setdefault(k, []).append(r)
        if want and want <= set(out):
            break
    return out


def leg_tf(leg: str) -> int:
    import re
    m = re.search(r"_(\d+)(m|h|d)$", str(leg or ""))
    return int(m.group(1)) * TF[m.group(2)] if m else 3600


def _meta(pkg: dict) -> dict:
    m = pkg.get("meta")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = {}
    return m if isinstance(m, dict) else {}


def audit_row(r: dict, pkg: dict | None, bars: list | None, applied: bool) -> dict:
    rec = r.get("recommendation") or {}
    st = r.get("state") or {}
    out = {"review_id": r.get("review_id"), "reviewed_at": r.get("reviewed_at"), "leg": r.get("leg"),
           "order_package_id": r.get("order_package_id"), "action": rec.get("action"),
           "trigger": (r.get("trigger") or {}).get("event"), "seen_peak_r": st.get("peak_r"), "open_r": st.get("open_r"),
           "applied": applied}
    reason = str(rec.get("reason") or "").lower()
    out["excursion_basis"] = out["trigger"] in EXCURSION_EVENTS or any(w in reason for w in ("gave back", "giveback", "peak", "mfe"))
    if not pkg:
        return {**out, "read_state": "could_not_look", "why": "order package not found in the journal pages read"}
    m = _meta(pkg)
    entry, risk = pkg.get("entry"), m.get("risk_per_unit")
    try:
        entry, risk = float(entry), float(risk)
    except (TypeError, ValueError):
        return {**out, "read_state": "could_not_look", "why": "package entry / risk_per_unit unreadable"}
    fills = [t for t in (_ts(pkg.get("created_at")), _ts(m.get("entry_time"))) if t]
    if not fills or risk <= 0:
        return {**out, "read_state": "could_not_look", "why": "no fill anchor or zero risk"}
    fill, rev = max(fills), _ts(r.get("reviewed_at"))
    out.update({"fill_at": datetime.fromtimestamp(fill, timezone.utc).isoformat(), "entry_time_meta": m.get("entry_time"),
                "entry_time_before_fill_s": round(fill - (_ts(m.get("entry_time")) or fill))})
    if not bars:
        return {**out, "read_state": "could_not_look", "why": "candles unreadable"}
    tf = leg_tf(r.get("leg"))
    if min(b["time"] for b in bars) > fill - tf:
        return {**out, "read_state": "could_not_look", "why": "candles do not reach back to the fill (API limit 1000 bars)"}
    short = str(pkg.get("direction")) == "short"
    post = [b for b in bars if b["time"] >= fill and b["time"] + tf <= rev]
    exts = [(entry - float(b["low"])) / risk if short else (float(b["high"]) - entry) / risk for b in post]
    floor = float(st["open_r"]) if st.get("open_r") is not None else None
    true_peak = max([x for x in exts + ([floor] if floor is not None else [])], default=None)
    out.update({"post_fill_bars": len(post), "true_peak_r": None if true_peak is None else round(true_peak, 4)})
    if out["seen_peak_r"] is not None and true_peak is not None:
        out["excess_r"] = round(float(out["seen_peak_r"]) - true_peak, 4)
        out["contaminated"] = out["excess_r"] >= 0.25
    else:
        out["excess_r"], out["contaminated"] = None, None
    if applied and out["action"] == "close" and floor is not None:
        sl, tp = float(pkg.get("sl")), float(pkg.get("tp"))
        fwd = [b for b in bars if b["time"] >= rev - tf]
        cf, how = None, "open_at_data_end"
        for b in fwd:
            hi, lo = float(b["high"]), float(b["low"])
            hit_sl = hi >= sl if short else lo <= sl
            hit_tp = lo <= tp if short else hi >= tp
            if hit_sl:
                cf, how = ((entry - sl) if short else (sl - entry)) / risk, "sl"
                break
            if hit_tp:
                cf, how = ((entry - tp) if short else (tp - entry)) / risk, "tp"
                break
        if cf is None and fwd:
            last = float(fwd[-1]["close"])
            cf = ((entry - last) if short else (last - entry)) / risk
        if cf is not None:
            out.update({"cf_r": round(cf, 4), "cf_exit": how, "realised_r": round(floor, 4), "forfeited_r": round(cf - floor, 4)})
    return {**out, "read_state": "measured"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", type=Path, default=REPO / "docs" / "research" / "ltr-phantom-peak-audit-2026-11-26")
    a = ap.parse_args(argv)
    rows = [json.loads(x) for x in (REPO / "comms" / "live_review" / "reviews.jsonl").read_text().splitlines() if x.strip()]
    act = [r for r in rows if (r.get("recommendation") or {}).get("action") in ACTIONS]
    pkgs = page_table("order_packages", {str(r.get("order_package_id")) for r in act}, "order_package_id")
    applied_ids, lr_closes = set(), {}
    for p in range(20):
        trs = _get("/api/diag/journal", table="trades", limit=1000, offset=p * 1000)
        if not trs:
            break
        for t in trs:
            n = t.get("notes")
            try:
                n = json.loads(n) if isinstance(n, str) else (n or {})
            except ValueError:
                n = {}
            if t.get("exit_reason") == "live_review_close" and t.get("order_package_id"):
                lr_closes.setdefault(str(t["order_package_id"]), []).append(_ts(t.get("closed_at")))
            for x in (n.get("live_review_actions") or []) if isinstance(n, dict) else []:
                if isinstance(x, dict) and x.get("review_id"):
                    applied_ids.add(x["review_id"])
        if min((_ts(t.get("timestamp")) or 1e18) for t in trs) < _ts("2026-10-20T00:00:00Z"):
            break
    candles = {}
    out = []
    for r in act:
        pid = str(r.get("order_package_id"))
        pkg = (pkgs.get(pid) or [None])[0]
        sym = (pkg or {}).get("symbol")
        tf = leg_tf(r.get("leg"))
        iv = {60 * 15: "15m", 3600: "1h", 14400: "4h", 86400: "1d", 7200: "2h"}.get(tf, "1h")
        key = (sym, iv)
        if sym and key not in candles:
            try:
                candles[key] = _get("/api/bot/candles", symbol=sym, interval=iv, limit=1000).get("candles") or []
            except Exception:  # noqa: BLE001  # allow-silent: the row is could_not_look with the reason
                candles[key] = None
        rv = _ts(r.get("reviewed_at")) or 0
        by_close = (r.get("recommendation") or {}).get("action") == "close" and any(
            c and abs(c - rv) <= 3600 for c in lr_closes.get(pid, []))
        out.append(audit_row(r, pkg, candles.get(key), r.get("review_id") in applied_ids or by_close))
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "rows.jsonl").write_text("".join(json.dumps(x) + "\n" for x in out))
    meas = [x for x in out if x["read_state"] == "measured"]
    cont = [x for x in meas if x.get("contaminated")]
    summ = {"population": f"{len(act)} close/tighten_sl/partial_close review rows in comms/live_review/reviews.jsonl, "
                          f"{min(r['reviewed_at'] for r in act)}..{max(r['reviewed_at'] for r in act)}",
            "n_rows": len(out), "n_measured": len(meas), "n_could_not_look": len(out) - len(meas),
            "n_contaminated": len(cont), "n_contaminated_excursion_basis": sum(1 for x in cont if x["excursion_basis"]),
            "n_contaminated_applied": sum(1 for x in cont if x["applied"]),
            "forfeited_r_contaminated_applied_closes": round(sum(x.get("forfeited_r") or 0 for x in cont if x["applied"]), 4),
            "by_leg": {}, "computed_at": datetime.now(timezone.utc).isoformat(), "gross_of_costs": True}
    for x in cont:
        summ["by_leg"][x["leg"]] = summ["by_leg"].get(x["leg"], 0) + 1
    (a.out_dir / "summary.json").write_text(json.dumps(summ, indent=1) + "\n")
    print(json.dumps(summ, indent=1))
    for x in cont:
        print(f"  {x['reviewed_at']} {x['leg']} {x['order_package_id']} {x['action']} trig={x['trigger']} seen={x['seen_peak_r']} "
              f"true={x['true_peak_r']} excess={x['excess_r']} applied={x['applied']} forfeited={x.get('forfeited_r')} ({x.get('cf_exit')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

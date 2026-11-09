#!/usr/bin/env python3
# wiring: research/queue/RQ-20261109-98e3-30.yaml (runner unit); PROP-ML-NEW-DATA step 1 re-census of the funding_basis family
"""Funding / basis census with a rule that fits how the archive publishes them (supersedes the funding_basis GRADE of RQ-20261108-98e3-28).

The first census graded funding_basis NOT-USABLE largely because of its own rule: funding is published as MONTHLY files only (so a
5-day staleness bar can never pass), and partial FIRST files (a contract that started mid-month) tripped a rows-per-day check. That
census and its grade are NOT edited. This unit re-measures the same two streams for ETHUSDT / SOLUSDT (BTCUSDT context) under a rule
registered in research/queue/RQ-20261109-98e3-30.yaml BEFORE the run:

  * monthly-aware staleness: funding must list the last COMPLETE month; premiumIndexKlines must list a day within 5 days of the run
  * a partial FIRST file is detected from its own timestamps and reported, never graded
  * EVERY complete monthly file in [2022-01, last complete month] is downloaded, checksum-verified and row-counted, so a hole inside
    a file (the 2026-10 premium file holds 41,760 rows = 29 of 31 days in the first census) is located by timestamp and REPORTED as a
    finding with the days it spans; findings are listed whatever the verdict and are never rewritten away

    python3 scripts/research/funding_basis_census.py run --out DIR --unit RQ-... [--rule-id ..] [--registered-at ..] [--run-date ..]
    python3 scripts/research/funding_basis_census.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "data_lake")]

SYMBOLS = ["ETHUSDT", "SOLUSDT", "BTCUSDT"]
REQUIRED = ["ETHUSDT", "SOLUSDT"]
STREAMS = ["fundingRate", "premiumIndexKlines"]
# ---- the rule, registered before the run (research/queue/RQ-20261109-98e3-30.yaml); not changed after any result ----
GRADE_START = date(2022, 1, 1)
MAX_SHORTFALL_SHARE = 0.01        # missing rows / expected rows over all complete files in the grade window
MAX_GAP_PREMIUM = timedelta(days=3)
MAX_GAP_FUNDING = timedelta(hours=24)
FINDING_SHARE = 0.005             # a complete file short by more than this is listed as a finding
MIN_NONNULL = 0.99
PREMIUM_STALE_DAYS = 5
PARTIAL_FIRST_DAYS = 2            # first file whose first timestamp is > 2 days after its month start = partial first file
SPANS = {"backward_heldout_2020-07_2021-12": (date(2020, 7, 1), date(2021, 12, 21)),
         "discovery_2022_to_2026-09": (date(2022, 1, 1), date(2026, 9, 30)),
         "forward_2025-10_2026-09": (date(2025, 10, 1), date(2026, 9, 30))}
BACKWARD_SHARE = 0.95             # a stream "supports" a span when it covers >= this share of it


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), (d.month % 12) + 1, 1)


def last_complete_month(run_date: date) -> date:
    return month_start(month_start(run_date) - timedelta(days=1))


def expected_rows(stream: str, month: date, interval_h: float | None) -> int:
    days = (next_month(month) - month).days
    if stream == "premiumIndexKlines":
        return days * 1440
    return round(days * 24 / (interval_h or 8.0))


def check_month_file(df: pd.DataFrame, stream: str, month: date, first_month: date) -> dict:
    """Pure: one monthly file -> completeness, gaps, partial-first detection, point-in-time sanity."""
    ts = pd.to_datetime(df["ts"], utc=True).sort_values().reset_index(drop=True)
    interval = None
    if stream == "fundingRate" and "funding_interval_hours" in df.columns:
        iv = pd.to_numeric(df["funding_interval_hours"], errors="coerce").dropna()
        interval = float(iv.mode().iloc[0]) if len(iv) else None
    exp = expected_rows(stream, month, interval)
    out = {"month": month.strftime("%Y-%m"), "rows": len(df), "expected_rows": exp, "ts_min": str(ts.min()) if len(ts) else None,
           "ts_max": str(ts.max()) if len(ts) else None, "interval_hours": interval}
    if len(ts) == 0:
        return {**out, "class": "EMPTY", "ok": False, "shortfall": exp, "longest_gap": None}
    month_begin = pd.Timestamp(month, tz="UTC")
    partial_first = month == first_month and ts.min() > month_begin + pd.Timedelta(days=PARTIAL_FIRST_DAYS)
    step = pd.Timedelta(minutes=1) if stream == "premiumIndexKlines" else pd.Timedelta(hours=interval or 8.0)
    d = ts.diff().dropna()
    big = d[d > step * 2]
    gaps = [{"from": str(ts.iloc[i - 1]), "to": str(ts.iloc[i]), "span": str(ts.iloc[i] - ts.iloc[i - 1])} for i in big.index[:10]]
    longest = max(d) if len(d) else pd.Timedelta(0)
    nonnull_cols = [c for c in ("close", "funding_rate") if c in df.columns]
    nonnull = float(df[nonnull_cols].notna().all(axis=1).mean()) if nonnull_cols else 1.0
    future = bool(ts.max() >= pd.Timestamp(next_month(month), tz="UTC") + pd.Timedelta(days=1))
    return {**out, "class": "PARTIAL_FIRST" if partial_first else "COMPLETE", "shortfall": max(exp - len(df), 0),
            "longest_gap": str(longest), "longest_gap_td_s": float(longest.total_seconds()), "gaps": gaps, "nonnull_share": nonnull,
            "monotone": bool(ts.is_monotonic_increasing), "future_dated": future,
            "ok": nonnull >= MIN_NONNULL and not future}


def grade(stream: str, files: list[dict], listing: dict, run_date: date) -> tuple[str, str, list[dict]]:
    """(verdict, why, findings) under the registered monthly-aware rule."""
    if listing.get("error"):
        return "INDETERMINATE", f"archive unreachable: {listing['error']}"[:200], []
    if not files:
        return "NOT-USABLE", "no monthly file could be read", []
    window = [f for f in files if f["class"] == "COMPLETE" and f["month"] >= GRADE_START.strftime("%Y-%m")]
    findings = [{"month": f["month"], "rows": f["rows"], "expected_rows": f["expected_rows"], "shortfall": f["shortfall"],
                 "shortfall_share": f["shortfall"] / f["expected_rows"], "gaps": f.get("gaps", [])}
                for f in files if f["class"] == "COMPLETE" and f["shortfall"] / f["expected_rows"] > FINDING_SHARE]
    if any(not f["ok"] for f in window):
        return "NOT-USABLE", "a complete file failed the integrity / point-in-time check", findings
    lcm = last_complete_month(run_date).strftime("%Y-%m")
    if stream == "fundingRate":
        if listing["last_monthly"] < lcm:
            return "NOT-USABLE", f"stale: last listed month {listing['last_monthly']} < last complete month {lcm}", findings
    elif (run_date - date.fromisoformat(listing["last_day"])).days > PREMIUM_STALE_DAYS:
        return "NOT-USABLE", f"stale: last listed day {listing['last_day']}", findings
    if not window:
        return "INDETERMINATE", "no complete file inside the grade window was read", findings
    exp = sum(f["expected_rows"] for f in window)
    short = sum(f["shortfall"] for f in window)
    cap = MAX_GAP_PREMIUM if stream == "premiumIndexKlines" else MAX_GAP_FUNDING
    worst = max(f["longest_gap_td_s"] for f in window)
    if short / exp > MAX_SHORTFALL_SHARE or worst > cap.total_seconds():
        return "NOT-USABLE", f"gaps: shortfall {short / exp:.4f} of expected, longest in-file gap {worst / 3600:.1f} h", findings
    first_full = next((f["month"] for f in sorted(files, key=lambda x: x["month"]) if f["class"] == "COMPLETE"), None)
    if first_full is None or first_full > GRADE_START.strftime("%Y-%m"):
        return "USABLE-PARTIAL", f"first complete month {first_full}, after the {GRADE_START} discovery start", findings
    return "USABLE", f"{len(window)} complete files in the grade window pass; {len(findings)} finding(s) listed", findings


def span_cover(first_day: date | None, last_day: date | None, lo: date, hi: date) -> float | None:
    if first_day is None or last_day is None or hi < lo:
        return None
    a, b = max(first_day, lo), min(last_day, hi)
    return 0.0 if b < a else ((b - a).days + 1) / ((hi - lo).days + 1)


def unit_verdict(grades: dict) -> tuple[str, dict]:
    """pass iff funding_basis counts: >= 1 stream USABLE / USABLE-PARTIAL for BOTH required symbols; indeterminate if an INDETERMINATE could
    still make it count; else fail."""
    ok_streams, pending = [], []
    for s in STREAMS:
        vs = [grades[(sym, s)][0] for sym in REQUIRED]
        if all(v in ("USABLE", "USABLE-PARTIAL") for v in vs):
            ok_streams.append(s)
        elif "INDETERMINATE" in vs and all(v in ("USABLE", "USABLE-PARTIAL", "INDETERMINATE") for v in vs):
            pending.append(s)
    if ok_streams:
        return "pass", {"funding_basis_usable_streams": ok_streams}
    return ("indeterminate" if pending else "fail"), {"funding_basis_usable_streams": [], "pending": pending}


def census_one(B, NI, sym: str, stream: str, run_date: date) -> dict:
    """List the archive, then download + check EVERY monthly file in [2022-01, last complete month] plus the first monthly file."""
    spec = B.STREAMS[stream]
    try:
        monthly = sorted(B.list_zips(spec["monthly"], "um_perp", sym))
        daily = sorted(B.list_zips(spec["daily"], "um_perp", sym))
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as `error`, graded INDETERMINATE, never hidden
        return {"symbol": sym, "stream": stream, "listing": {"error": f"{type(exc).__name__}: {exc}"[:240]}, "files": [], "unreadable": []}
    months: dict[date, str] = {}
    for k in monthly:
        parsed = NI._day_from_key(k)
        if parsed is not None and parsed[0] == "month":
            months[parsed[1]] = k
    daily_days = [d for d in (NI._day_from_key(k) for k in daily) if d is not None and d[0] == "day"]
    first_month = min(months) if months else None
    todo = [(m, k) for m, k in sorted(months.items()) if m <= last_complete_month(run_date) and (m >= GRADE_START or m == first_month)]

    def one(item):
        m, k = item
        try:
            df, state = B.fetch_zip(k, spec["parse"], verify=True)
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded on the file row; an unreadable complete file makes the cell INDETERMINATE
            return {"month": m.strftime("%Y-%m"), "class": "UNREADABLE", "ok": False, "shortfall": 0, "expected_rows": 1, "rows": 0,
                    "longest_gap_td_s": 0.0, "error": f"{type(exc).__name__}: {exc}"[:160], "key": k.rsplit("/", 1)[-1]}
        row = check_month_file(df, stream, m, first_month)
        row["checksum"] = state
        row["ok"] = bool(row["ok"] and state in ("ok", "no_checksum"))
        row["key"] = k.rsplit("/", 1)[-1]
        return row

    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(one, todo))
    files = [f for f in rows if f["class"] != "UNREADABLE"]
    last_day = max((d[1] for d in daily_days), default=None) or (next_month(max(months)) - timedelta(days=1) if months else None)
    partial = next((f for f in files if f["class"] == "PARTIAL_FIRST"), None)
    first_day = (pd.Timestamp(partial["ts_min"]).date() if partial else first_month)
    listing = {"files": len(monthly) + len(daily), "monthly_files": len(monthly), "daily_files": len(daily),
               "first_month": first_month.strftime("%Y-%m") if first_month else None,
               "last_monthly": max(months).strftime("%Y-%m") if months else "0000-00", "last_day": str(last_day) if last_day else None}
    return {"symbol": sym, "stream": stream, "listing": listing, "files": files, "unreadable": [f for f in rows if f["class"] == "UNREADABLE"],
            "first_day": first_day, "last_day_d": last_day}


def run(a) -> int:
    import binance_vision_lake as B
    import nonprice_inventory as NI
    run_date = date.fromisoformat(a.run_date)
    res: dict[tuple[str, str], dict] = {}
    for sym in SYMBOLS:
        for stream in STREAMS:
            res[(sym, stream)] = census_one(B, NI, sym, stream, run_date)
            r = res[(sym, stream)]
            print(f"{sym} {stream}: files={len(r['files'])} unreadable={len(r.get('unreadable', []))}", flush=True)
    grades, table = {}, []
    for (sym, stream), r in res.items():
        files = r["files"]
        if r.get("unreadable"):
            verdict_, why, findings = "INDETERMINATE", f"{len(r['unreadable'])} complete monthly file(s) could not be read", []
        else:
            verdict_, why, findings = grade(stream, files, r["listing"], run_date)
        grades[(sym, stream)] = (verdict_, why)
        first_day = r.get("first_day")
        part_first = next((f for f in files if f["class"] == "PARTIAL_FIRST"), None)
        table.append({"symbol": sym, "stream": stream, "verdict": verdict_, "why": why, "listing": r["listing"], "n_files_checked": len(files),
                      "partial_first_file": ({k: part_first[k] for k in ("month", "rows", "expected_rows", "ts_min")} if part_first else None),
                      "findings": findings, "unreadable": r.get("unreadable", []),
                      "covers": {k: (None if (c := span_cover(first_day, r.get("last_day_d"), lo, hi)) is None else round(c, 4))
                                 for k, (lo, hi) in SPANS.items()}})
    verdict, detail = unit_verdict(grades)
    findings_all = [(t["symbol"], t["stream"], f["month"], f["rows"], f["expected_rows"]) for t in table for f in t["findings"]]
    note = (f"{verdict}: funding_basis usable streams on ETH+SOL = {detail['funding_basis_usable_streams']}; "
            + "; ".join(f"{t['symbol'][:3]} {t['stream']} {t['verdict']}" for t in table if t["symbol"] in REQUIRED)
            + f"; {len(findings_all)} finding(s): " + ", ".join(f"{s[:3]} {st[:7]} {m} {r}/{e}" for s, st, m, r, e in findings_all[:8]))
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured" if verdict in ("pass", "fail") else "not_measured", "verdict": verdict,
           "population": ("Binance USD-M archive monthly files for fundingRate and premiumIndexKlines, ETHUSDT/SOLUSDT (required) and BTCUSDT (context); "
                          "every complete month from 2022-01 to the last complete month downloaded, checksum-verified and row-counted; as of " + a.run_date),
           "note": note, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {"detail": detail, "table": table, "supersedes": "the funding_basis GRADE of RQ-20261108-98e3-28 (which is not edited)",
                           "rule_constants": {"grade_start": str(GRADE_START), "max_shortfall_share": MAX_SHORTFALL_SHARE,
                                              "max_gap_premium_h": MAX_GAP_PREMIUM.total_seconds() / 3600,
                                              "max_gap_funding_h": MAX_GAP_FUNDING.total_seconds() / 3600, "finding_share": FINDING_SHARE,
                                              "min_nonnull": MIN_NONNULL, "premium_stale_days": PREMIUM_STALE_DAYS}},
           "n": len(table), "produced_by": {"tool": "python3 scripts/research/funding_basis_census.py run", "where": a.where}}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print("FUNDING-BASIS: " + note, flush=True)
    return 0


def self_test() -> int:
    rd = date(2026, 11, 9)
    assert last_complete_month(rd) == date(2026, 10, 1) and last_complete_month(date(2026, 1, 3)) == date(2025, 12, 1)
    assert expected_rows("premiumIndexKlines", date(2026, 10, 1), None) == 31 * 1440 and expected_rows("fundingRate", date(2026, 10, 1), 8.0) == 93
    assert expected_rows("fundingRate", date(2026, 10, 1), 4.0) == 186

    def prem(month: date, days: int, start_day: int = 0):
        t0 = pd.Timestamp(month, tz="UTC") + pd.Timedelta(days=start_day)
        return pd.DataFrame({"ts": pd.date_range(t0, periods=days * 1440, freq="1min", tz="UTC"), "close": 1.0})

    full = check_month_file(prem(date(2026, 9, 1), 30), "premiumIndexKlines", date(2026, 9, 1), date(2020, 9, 1))
    assert full["class"] == "COMPLETE" and full["shortfall"] == 0 and full["ok"]
    short = prem(date(2026, 10, 1), 31)
    short = pd.concat([short[short.ts < pd.Timestamp("2026-10-10", tz="UTC")], short[short.ts >= pd.Timestamp("2026-10-12", tz="UTC")]])
    s = check_month_file(short, "premiumIndexKlines", date(2026, 10, 1), date(2020, 9, 1))
    assert s["class"] == "COMPLETE" and s["shortfall"] == 2 * 1440 and s["gaps"][0]["from"].startswith("2026-10-09 23:59") and s["gaps"][0]["to"].startswith("2026-10-12"), s["gaps"]
    pf = check_month_file(prem(date(2020, 9, 1), 17, start_day=13), "premiumIndexKlines", date(2020, 9, 1), date(2020, 9, 1))
    assert pf["class"] == "PARTIAL_FIRST"                                   # a mid-month contract start is detected, never graded
    base = {"files": 80, "last_monthly": "2026-10", "last_day": "2026-11-07"}
    ok_files = [{**full, "month": "2022-01"}, {**full, "month": "2022-02"}]
    assert grade("fundingRate", ok_files, base, rd)[0] == "USABLE"           # last monthly == last complete month: not stale
    assert grade("fundingRate", ok_files, {**base, "last_monthly": "2026-09"}, rd)[0] == "NOT-USABLE"
    assert grade("premiumIndexKlines", ok_files, {**base, "last_day": "2026-10-01"}, rd)[0] == "NOT-USABLE"
    many = [{**full, "month": f"{2022 + i // 12}-{i % 12 + 1:02d}"} for i in range(58)]                 # a realistic grade window
    v, _, finds = grade("premiumIndexKlines", [*many, {**s, "month": "2026-10"}], base, rd)
    assert v == "USABLE" and len(finds) == 1 and finds[0]["shortfall"] == 2880      # a 2-day hole is USABLE under the registered cap AND reported
    v2, _, _ = grade("premiumIndexKlines", [*many[:2], {**s, "month": "2022-03"}], base, rd)
    assert v2 == "NOT-USABLE"                                                       # the same hole in a tiny window breaches the 1% shortfall cap
    late = [{**full, "month": "2023-05"}]
    assert grade("premiumIndexKlines", late, base, rd)[0] == "USABLE-PARTIAL"
    assert grade("premiumIndexKlines", [], base, rd)[0] == "NOT-USABLE" and grade("x", [], {"error": "boom"}, rd)[0] == "INDETERMINATE"
    assert span_cover(date(2020, 9, 14), date(2026, 11, 1), *SPANS["backward_heldout_2020-07_2021-12"]) < BACKWARD_SHARE
    assert span_cover(date(2019, 12, 24), date(2026, 11, 1), *SPANS["backward_heldout_2020-07_2021-12"]) == 1.0
    U, N = ("USABLE", ""), ("NOT-USABLE", "")
    g = {(sym, st): U for sym in SYMBOLS for st in STREAMS}
    assert unit_verdict(g)[0] == "pass"
    assert unit_verdict({k: (N if k[1] == "fundingRate" else U) for k in g})[1]["funding_basis_usable_streams"] == ["premiumIndexKlines"]
    assert unit_verdict({k: N for k in g})[0] == "fail"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--out", default="/tmp/funding_basis_census_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-09")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run" or not a.unit:
        ap.error("run --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())

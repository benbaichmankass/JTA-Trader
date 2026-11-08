#!/usr/bin/env python3
# wiring: research/queue/RQ-20261108-98e3-28.yaml (runner unit); row PROP-ML-NEW-DATA step 1; lane ML-ENTRY-EQ-STRUCTURE-RETEST
"""PROP-ML-NEW-DATA step 1: inventory + verification of the NON-PRICE sources for the prop symbols. No model is trained.

For ETHUSDT and SOLUSDT (the symbols breakout_2 / tradeify_1 / velotrade_1 trade; BTCUSDT is context-only, graded but not
required) and each non-price stream of the Binance USD-M archive (data.binance.vision, public, keyless):

  fundingRate (funding events) | premiumIndexKlines (1m basis proxy) | metrics (5m OI, long/short, taker ratios) | bookDepth
  aggTrades is LISTED ONLY (raw ~130 GB for the traded perps: not downloaded, not graded).

it reports, from the archive listing: first/last day, files, coverage of three candidate held-out spans, missing days and the
longest gap; and from up to three checksum-verified sample files per stream: rows, null share, monotonic timestamps, point-in-time
sanity, rows per day. Each (source, symbol) is graded by the "usable as a feature" rule registered in
research/queue/RQ-20261108-98e3-28.yaml BEFORE any run (constants below). It does NOT read the private lake: HF returns 403 (storage
cap) and the Kaggle mirror is not a published_data target of the runner, so the lake's presence is reported as UNVERIFIED beside
the plan in config/data_universe.yaml, never as present.

    python3 scripts/research/nonprice_inventory.py run --out DIR --unit RQ-... [--rule-id ..] [--registered-at ..]
    python3 scripts/research/nonprice_inventory.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "data_lake")]

SYMBOLS = ["ETHUSDT", "SOLUSDT", "BTCUSDT"]
REQUIRED = ["ETHUSDT", "SOLUSDT"]
STREAMS = ["fundingRate", "premiumIndexKlines", "metrics", "bookDepth"]
LISTED_ONLY = ["aggTrades"]
FAMILY = {"fundingRate": "funding_basis", "premiumIndexKlines": "funding_basis", "metrics": "oi_flow", "bookDepth": "book_depth"}
# ---- the rule, registered before the run (research/queue/RQ-20261108-98e3-28.yaml); not changed after any result ----
GRADE_START = date(2022, 1, 1)
MAX_MISSING_SHARE = 0.02
MAX_GAP_DAYS = 3
MAX_STALE_DAYS = 5
MIN_NONNULL = 0.99
MIN_FAMILIES = 2
SPANS = {"backward_heldout_2020-07_2021-12": (date(2020, 7, 1), date(2021, 12, 21)),
         "discovery_2022_to_2026-09": (date(2022, 1, 1), date(2026, 9, 30)),
         "forward_2025-10_2026-09": (date(2025, 10, 1), date(2026, 9, 30))}
VALUE_COLS = {"fundingRate": ["funding_rate"], "premiumIndexKlines": ["close"],
              "metrics": ["sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
                          "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"],
              "bookDepth": ["depth", "notional"]}
NOMINAL_ROWS_PER_DAY = {"metrics": 288, "premiumIndexKlines": 1440, "fundingRate": 2}   # funding: at least 2 events a day on average


def _day_from_key(key: str):
    import re
    m = re.search(r"(\d{4})-(\d{2})(?:-(\d{2}))?\.zip$", key)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    return ("day", date(y, mo, int(d))) if d else ("month", date(y, mo, 1))


def covered_days(keys: list[str]) -> set[date]:
    """Days the listed files cover: a daily file covers its day, a monthly file every day of its month."""
    out: set[date] = set()
    for k in keys:
        r = _day_from_key(k)
        if r is None:
            continue
        kind, d = r
        if kind == "day":
            out.add(d)
        else:
            nxt = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
            out.update(d + timedelta(days=i) for i in range((nxt - d).days))
    return out


def gap_report(days: set[date], lo: date, hi: date) -> dict:
    """Missing days and longest missing run inside [lo, hi] (inclusive), plus the share of the window covered."""
    if hi < lo:
        return {"window_days": 0, "missing_days": 0, "missing_share": None, "longest_gap_days": 0, "covered_share": None}
    n = (hi - lo).days + 1
    miss, run, longest = 0, 0, 0
    for i in range(n):
        if lo + timedelta(days=i) in days:
            run = 0
        else:
            miss += 1
            run += 1
            longest = max(longest, run)
    return {"window_days": n, "missing_days": miss, "missing_share": miss / n, "longest_gap_days": longest, "covered_share": 1 - miss / n}


def check_sample(df: pd.DataFrame, stream: str, file_lo: date, file_hi: date) -> dict:
    """Point-in-time sanity of one parsed sample file."""
    cols = [c for c in VALUE_COLS[stream] if c in df.columns]
    if len(df) == 0 or not cols:
        return {"ok": False, "rows": len(df), "reason": "empty or value columns missing"}
    nonnull = float(df[cols].notna().all(axis=1).mean())
    ts = pd.to_datetime(df["ts"], utc=True)
    monotone = bool(ts.sort_values().is_monotonic_increasing)
    future = bool(ts.max() > pd.Timestamp(file_hi + timedelta(days=1), tz="UTC") + pd.Timedelta(hours=1))
    days = (file_hi - file_lo).days + 1
    rpd = len(df) / max(days, 1)
    nominal = NOMINAL_ROWS_PER_DAY.get(stream)
    rows_ok = True if nominal is None else (rpd >= nominal if stream == "fundingRate" else abs(rpd - nominal) / nominal <= 0.05)
    ok = nonnull >= MIN_NONNULL and monotone and not future and rows_ok
    return {"ok": ok, "rows": len(df), "nonnull_share": nonnull, "monotone": monotone, "future_dated": future,
            "rows_per_day": rpd, "rows_ok": rows_ok, "ts_min": str(ts.min()), "ts_max": str(ts.max())}


def grade(inv: dict, run_date: date) -> tuple[str, str]:
    """(verdict, why) for one (symbol, stream) by the registered rule."""
    if inv.get("error"):
        return "INDETERMINATE", f"archive unreachable: {inv['error']}"[:200]
    if inv["files"] == 0:
        return "NOT-USABLE", "no files listed"
    samples = inv["samples"]
    if len(samples) < 3 and inv["files"] >= 3:
        return "INDETERMINATE", f"only {len(samples)} of 3 sample files could be read"
    if any(not s["ok"] for s in samples):
        return "NOT-USABLE", "a sample file failed the point-in-time/integrity check"
    first, last = date.fromisoformat(inv["first_day"]), date.fromisoformat(inv["last_day"])
    if (run_date - last).days > MAX_STALE_DAYS:
        return "NOT-USABLE", f"stale: last listed day {last} is {(run_date - last).days} days old"
    g = inv["gaps_grade_window"]
    if g["missing_share"] is not None and (g["missing_share"] > MAX_MISSING_SHARE or g["longest_gap_days"] > MAX_GAP_DAYS):
        return "NOT-USABLE", f"gaps: {g['missing_days']} missing days ({g['missing_share']:.3f}), longest {g['longest_gap_days']}"
    if first > GRADE_START:
        return "USABLE-PARTIAL", f"history starts {first}, after the {GRADE_START} discovery start"
    return "USABLE", "span, gaps and samples pass"


def unit_verdict(grades: dict) -> tuple[str, dict]:
    """pass iff >= MIN_FAMILIES distinct families are USABLE/USABLE-PARTIAL for every required symbol; indeterminate if any required
    (symbol, stream) is INDETERMINATE and the families could still change the answer; else fail."""
    fams: dict[str, bool] = {}
    pending = set()
    for fam in set(FAMILY.values()):
        streams = [s for s, f in FAMILY.items() if f == fam]
        ok = False
        for s in streams:
            vs = [grades[(sym, s)][0] for sym in REQUIRED]
            if all(v in ("USABLE", "USABLE-PARTIAL") for v in vs):
                ok = True
            if "INDETERMINATE" in vs:
                pending.add(fam)
        fams[fam] = ok
    n_ok = sum(fams.values())
    if n_ok >= MIN_FAMILIES:
        return "pass", {"families_usable": fams}
    if n_ok + len(pending - {f for f, v in fams.items() if v}) >= MIN_FAMILIES:
        return "indeterminate", {"families_usable": fams, "pending": sorted(pending)}
    return "fail", {"families_usable": fams}


def lake_plan() -> dict:
    """What config/data_universe.yaml PLANS for these streams. A plan, not a verification."""
    import yaml
    cfg = yaml.safe_load((REPO / "config" / "data_universe.yaml").read_text())
    um = cfg["crypto"]["um_perp"]
    core = {k: v for k, v in (um.get("streams") or {}).items()}
    opt = {k: {"stream": v.get("stream"), "scope": v.get("scope")} for k, v in (um.get("optional_streams") or {}).items()}
    return {"core_streams": core, "optional_streams": opt,
            "verified": False,
            "why_unverified": ("the private HF lake returns 403 (storage cap since 2026-11-05) and the Kaggle mirror metis-market-lake-pNNN is "
                               "not a routing.published_data target of the runner twin (loader row HF-LAKE-KAGGLE-LOADER is open); no runner can "
                               "read the manifest today. Presence of a stream here means PLANNED, not present.")}


def inventory_one(B, sym: str, stream: str, run_date: date) -> dict:
    spec = B.STREAMS[stream]
    try:
        keys = B.list_zips(spec["monthly"], "um_perp", sym) + B.list_zips(spec["daily"], "um_perp", sym)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded in the row as `error`, graded INDETERMINATE, never hidden
        return {"symbol": sym, "stream": stream, "error": f"{type(exc).__name__}: {exc}"[:240], "files": 0, "samples": []}
    keys = sorted(set(keys))
    days = covered_days(keys)
    out = {"symbol": sym, "stream": stream, "files": len(keys), "samples": []}
    if not days:
        return out
    first, last = min(days), max(days)
    out.update({"first_day": str(first), "last_day": str(last),
                "gaps_grade_window": gap_report(days, max(first, GRADE_START), min(last, run_date)),
                "spans": {k: gap_report(days, lo, hi) for k, (lo, hi) in SPANS.items()}})
    # three samples: first, middle, last file (checksum-verified by the lake tool)
    pick = sorted({keys[0], keys[len(keys) // 2], keys[-1]})
    for k in pick:
        r = _day_from_key(k)
        lo = r[1]
        hi = lo if r[0] == "day" else (date(lo.year + (lo.month == 12), (lo.month % 12) + 1, 1) - timedelta(days=1))
        try:
            df, state = B.fetch_zip(k, spec["parse"], verify=True)
            s = check_sample(df, stream, lo, hi)
            s.update({"key": k, "checksum": state})
            s["ok"] = bool(s["ok"] and state in ("ok", "no_checksum"))
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded on the sample, the sample then fails or leaves <3 samples -> graded
            s = {"key": k, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        out["samples"].append(s)
    # a sample that could not be READ (network) is not a sample: only parsed samples count toward the 3
    out["samples"] = [s for s in out["samples"] if "error" not in s] + []
    out["sample_errors"] = [s for s in pick if s not in {x["key"] for x in out["samples"]}]
    return out


def run(a) -> int:
    import binance_vision_lake as B
    run_date = date.fromisoformat(a.run_date)
    inv: dict[tuple[str, str], dict] = {}
    for sym in SYMBOLS:
        for stream in STREAMS:
            inv[(sym, stream)] = inventory_one(B, sym, stream, run_date)
            print(f"{sym} {stream}: files={inv[(sym, stream)]['files']} first={inv[(sym, stream)].get('first_day')} "
                  f"last={inv[(sym, stream)].get('last_day')}", flush=True)
    listed = {}
    for sym in SYMBOLS:
        for stream in LISTED_ONLY:
            try:
                keys = sorted(set(B.list_zips(B.STREAMS[stream]["monthly"], "um_perp", sym) + B.list_zips(B.STREAMS[stream]["daily"], "um_perp", sym)))
                days = covered_days(keys)
                listed[f"{sym}:{stream}"] = {"files": len(keys), "first_day": str(min(days)) if days else None,
                                              "last_day": str(max(days)) if days else None, "graded": False,
                                              "why": "raw ticks ~130 GB zipped for the traded perps: listed only, not downloaded, not graded"}
            except Exception as exc:  # noqa: BLE001  # allow-silent: recorded
                listed[f"{sym}:{stream}"] = {"error": f"{type(exc).__name__}: {exc}"[:200], "graded": False}
    grades = {k: grade(v, run_date) for k, v in inv.items()}
    verdict, detail = unit_verdict(grades)
    table = []
    for (sym, stream), (v, why) in grades.items():
        i = inv[(sym, stream)]
        table.append({"symbol": sym, "stream": stream, "family": FAMILY[stream], "verdict": v, "why": why, "files": i["files"],
                      "first_day": i.get("first_day"), "last_day": i.get("last_day"),
                      "gaps_grade_window": i.get("gaps_grade_window"),
                      "covers": {k: (None if s["covered_share"] is None else round(s["covered_share"], 4)) for k, s in (i.get("spans") or {}).items()},
                      "samples": [{k: s.get(k) for k in ("key", "ok", "rows", "nonnull_share", "monotone", "future_dated", "rows_per_day", "checksum")}
                                  for s in i["samples"]],
                      "sample_errors": i.get("sample_errors", []), "error": i.get("error")})
    note = (f"{verdict}: families usable on ETH+SOL = {detail['families_usable']}; " +
            "; ".join(f"{r['symbol'][:3]} {r['stream']} {r['verdict']}" for r in table if r["symbol"] in REQUIRED))
    row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured" if verdict in ("pass", "fail") else "not_measured",
           "verdict": verdict,
           "population": ("Binance USD-M archive (data.binance.vision) for ETHUSDT/SOLUSDT (required) and BTCUSDT (context): fundingRate, "
                          "premiumIndexKlines, metrics, bookDepth graded; aggTrades listed only; as of " + a.run_date),
           "note": note, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "measurement": {"detail": detail, "table": table, "listed_only": listed, "lake_plan": lake_plan(),
                           "rule_constants": {"grade_start": str(GRADE_START), "max_missing_share": MAX_MISSING_SHARE,
                                              "max_gap_days": MAX_GAP_DAYS, "max_stale_days": MAX_STALE_DAYS, "min_nonnull": MIN_NONNULL,
                                              "min_families": MIN_FAMILIES}},
           "n": len(table), "produced_by": {"tool": "python3 scripts/research/nonprice_inventory.py run", "where": a.where}}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print("INVENTORY: " + note, flush=True)
    return 0


def self_test() -> int:
    ks = ["data/futures/um/monthly/fundingRate/ETHUSDT/ETHUSDT-fundingRate-2022-01.zip",
          "data/futures/um/daily/metrics/ETHUSDT/ETHUSDT-metrics-2022-02-01.zip",
          "data/futures/um/daily/metrics/ETHUSDT/ETHUSDT-metrics-2022-02-03.zip"]
    d = covered_days(ks)
    assert date(2022, 1, 31) in d and date(2022, 1, 1) in d and date(2022, 2, 1) in d and date(2022, 2, 2) not in d and len(d) == 31 + 2
    g = gap_report(d, date(2022, 1, 1), date(2022, 2, 3))
    assert g["missing_days"] == 1 and g["longest_gap_days"] == 1 and abs(g["missing_share"] - 1 / 34) < 1e-12
    assert gap_report(set(), date(2022, 1, 1), date(2021, 1, 1))["missing_share"] is None
    ts = pd.date_range("2024-03-01", periods=288, freq="5min", tz="UTC")
    good = pd.DataFrame({"ts": ts, **{c: 1.0 for c in VALUE_COLS["metrics"]}})
    assert check_sample(good, "metrics", date(2024, 3, 1), date(2024, 3, 1))["ok"]
    bad = good.copy()
    bad.loc[:10, "sum_open_interest"] = float("nan")
    assert not check_sample(bad, "metrics", date(2024, 3, 1), date(2024, 3, 1))["ok"]
    short = good.iloc[:100]
    assert not check_sample(short, "metrics", date(2024, 3, 1), date(2024, 3, 1))["ok"]            # rows per day far below 288
    fut = good.copy()
    fut["ts"] = fut["ts"] + pd.Timedelta(days=10)
    assert check_sample(fut, "metrics", date(2024, 3, 1), date(2024, 3, 1))["future_dated"]
    s_ok = {"ok": True}
    inv = {"files": 100, "samples": [s_ok] * 3, "first_day": "2021-12-01", "last_day": "2026-11-05",
           "gaps_grade_window": {"missing_share": 0.0, "longest_gap_days": 0, "missing_days": 0}}
    rd = date(2026, 11, 8)
    assert grade(inv, rd)[0] == "USABLE"
    assert grade({**inv, "first_day": "2023-01-01"}, rd)[0] == "USABLE-PARTIAL"
    assert grade({**inv, "last_day": "2026-10-01"}, rd)[0] == "NOT-USABLE"
    assert grade({**inv, "gaps_grade_window": {"missing_share": 0.05, "longest_gap_days": 1, "missing_days": 50}}, rd)[0] == "NOT-USABLE"
    assert grade({**inv, "gaps_grade_window": {"missing_share": 0.0, "longest_gap_days": 4, "missing_days": 4}}, rd)[0] == "NOT-USABLE"
    assert grade({**inv, "samples": [s_ok, {"ok": False}, s_ok]}, rd)[0] == "NOT-USABLE"
    assert grade({**inv, "samples": [s_ok]}, rd)[0] == "INDETERMINATE"
    assert grade({"error": "x", "files": 0, "samples": []}, rd)[0] == "INDETERMINATE"
    assert grade({"files": 0, "samples": []}, rd)[0] == "NOT-USABLE"
    U = ("USABLE", "")
    N = ("NOT-USABLE", "")
    IND = ("INDETERMINATE", "")
    g = {(s, st): U for s in SYMBOLS for st in STREAMS}
    assert unit_verdict(g)[0] == "pass"
    g2 = {k: (N if k[1] in ("metrics", "bookDepth") else U) for k in g}
    assert unit_verdict(g2)[0] == "fail"                                   # only funding_basis family usable
    g3 = {k: (IND if k[1] == "metrics" else (N if k[1] == "bookDepth" else U)) for k in g}
    assert unit_verdict(g3)[0] == "indeterminate"                          # oi_flow undecided and could make 2
    g4 = {k: (N if k[0] == "SOLUSDT" and k[1] == "metrics" else U) for k in g}
    assert unit_verdict(g4)[1]["families_usable"]["oi_flow"] is False      # one required symbol failing fails the family
    assert lake_plan()["verified"] is False
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--out", default="/tmp/nonprice_inventory_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--run-date", dest="run_date", default="2026-11-08")
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

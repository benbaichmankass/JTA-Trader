#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (check: every capture job; merge: the manifest job)
"""Validate the market data lake and emit MACHINE-READABLE HEALTH RECORDS -- the feeds run as automations, and Claude
reads these records in reviews; Claude does not run the feeds (operator 2026-11-01). Row MARKET-DATA-LAKE.

check  (in each capture job, over what that job just built)
       per series: schema, duplicate timestamps, non-monotonic ts, OHLC violations (high<max(o,c), low>min(o,c),
       low>high, price<=0, volume<0), return outliers (|log r| > max(0.2, 25 x median |log r|)), missing bars vs
       the bar calendar (crypto: continuous; US equity 1d: business days less US federal holidays, an approximation
       of the NYSE calendar stated as such). -> <out>/_health/<tag>.json

merge  (in the manifest job, over the whole lake)
       folds every shard's checks, adds FEED STALENESS per (asset, market, tf) -- the newest last bar across the
       feed's series vs a per-feed threshold -- and counts consecutive failing runs per series/feed from the
       previous health record. Writes health/latest.json + health/<YYYYmmddTHHMMZ>.json.
       --flag: a series or feed reaching FLAG_AFTER consecutive failures raises ONE red flag (a comment on the
       ops-flags PR + one Telegram message on the operator SYSTEM channel, the same GhProbe path
       research-watchdog uses). One flag per incident: it re-arms only after the series recovers. A failure never
       halts a feed; the next run retries it.

    python3 scripts/data_lake/validate.py check --out lake --tag crypto-1m-0of12
    python3 scripts/data_lake/validate.py merge --dir lake --previous prev/latest.json --flag
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

FLAG_AFTER = 3
BAR_COLS = ["ts", "open", "high", "low", "close"]
SCHEMA = {"funding": ["ts", "funding_rate"], "metrics_5m": ["ts", "sum_open_interest"]}
# hours before a FEED (its freshest series) counts as stale. Binance daily files land the next day; FRED/CBOE
# publish on business days; COT weekly (Friday); monthly macro monthly.
STALE_H = {("crypto", "*"): 54, ("macro", "fred_monthly"): 24 * 75, ("macro", "cftc_cot"): 24 * 12,
           ("macro", "*"): 24 * 6, ("fx", "*"): 24 * 8, ("options", "cboe_iv"): 24 * 5, ("options", "*"): 24 * 6,
           ("futures", "*"): 24 * 5, ("us_equity", "*"): 24 * 5}


def stale_hours(asset: str, market: str) -> float:
    return STALE_H.get((asset, market)) or STALE_H.get((asset, "*")) or 24 * 7


def _required(tf: str, cols: List[str]) -> List[str]:
    if tf in SCHEMA:
        return SCHEMA[tf]
    if "value" in cols and "open" not in cols:
        return ["ts", "value"]
    return BAR_COLS


def check_frame(df: pd.DataFrame, tf: str) -> Dict[str, Any]:
    cols = list(df.columns)
    req = _required(tf, cols)
    missing_cols = [c for c in req if c not in cols]
    res: Dict[str, Any] = {"rows": int(len(df)), "schema_missing": missing_cols}
    if missing_cols or df.empty:
        return res
    ts = pd.to_datetime(df["ts"], utc=True)
    res["dup_ts"] = int(ts.duplicated().sum())
    res["non_monotonic"] = int((ts.diff().dropna() < pd.Timedelta(0)).sum())
    if "open" in cols:
        o, h, l, c = (pd.to_numeric(df[k], errors="coerce") for k in ("open", "high", "low", "close"))
        bad = (h < np.maximum(o, c) - 1e-12) | (l > np.minimum(o, c) + 1e-12) | (l > h) | (c <= 0) | (o <= 0)
        if "volume" in cols:
            bad |= pd.to_numeric(df["volume"], errors="coerce") < 0
        res["ohlc_violations"] = int(bad.sum())
        px = c
    else:
        px = pd.to_numeric(df[req[1]], errors="coerce")
    lr = np.log(px.where(px > 0)).diff().abs().dropna()
    if len(lr) > 20:
        med = float(lr.median())
        thr = max(0.2, 25 * med) if med > 0 else 0.2
        res["outliers"] = int((lr > thr).sum())
        res["max_abs_log_return"] = round(float(lr.max()), 4)
    return res


def us_business_days(start: pd.Timestamp, end: pd.Timestamp) -> int:
    from pandas.tseries.holiday import USFederalHolidayCalendar
    days = pd.bdate_range(start.normalize(), end.normalize(),
                          freq="C", holidays=USFederalHolidayCalendar().holidays(start, end))
    return len(days)


def series_state(chk: Dict[str, Any], entry: Dict[str, Any]) -> str:
    if entry.get("state") == "error" or chk.get("schema_missing"):
        return "fail"
    warn = any((chk.get(k) or 0) > 0 for k in ("dup_ts", "non_monotonic", "ohlc_violations", "outliers"))
    exp, miss = chk.get("expected_rows") or 0, chk.get("missing_bars") or 0
    if exp and miss / max(exp, 1) > 0.01:
        warn = True
    if chk.get("calendar_coverage") is not None and chk["calendar_coverage"] < 0.95:
        warn = True
    return "warn" if warn else "ok"


def cmd_check(a) -> int:
    out = Path(a.out)
    records = []
    for mf in sorted((out / "_manifests").glob("*.json")):
        for e in json.loads(mf.read_text()):
            parts = e.get("partitions") or ({"_": {"path": e["path"]}} if e.get("path") else {})
            agg: Dict[str, Any] = {"rows": 0, "dup_ts": 0, "non_monotonic": 0, "ohlc_violations": 0, "outliers": 0,
                                   "missing_bars": 0, "expected_rows": 0, "schema_missing": []}
            frames_first, frames_last = None, None
            for p in parts.values():
                fp = out / p["path"]
                if not fp.exists():
                    continue
                try:
                    df = pd.read_parquet(fp)
                except Exception as ex:
                    agg["schema_missing"] = [f"unreadable: {str(ex)[:80]}"]
                    continue
                c = check_frame(df, str(e.get("tf")))
                for k in ("rows", "dup_ts", "non_monotonic", "ohlc_violations", "outliers"):
                    agg[k] += int(c.get(k) or 0)
                agg["schema_missing"] = agg["schema_missing"] or c.get("schema_missing") or []
                agg["missing_bars"] += int(p.get("missing_bars") or 0)
                agg["expected_rows"] += int(p.get("expected_rows") or 0)
                if len(df):
                    t = pd.to_datetime(df["ts"], utc=True)
                    frames_first = t.min() if frames_first is None else min(frames_first, t.min())
                    frames_last = t.max() if frames_last is None else max(frames_last, t.max())
            if e.get("asset_class") == "us_equity" and e.get("tf") == "1d" and frames_first is not None:
                bd = us_business_days(frames_first, frames_last)
                agg["calendar_coverage"] = round(agg["rows"] / bd, 4) if bd else None
            agg["first"] = frames_first.isoformat() if frames_first is not None else None
            agg["last"] = frames_last.isoformat() if frames_last is not None else None
            key = f"{e.get('asset_class')}/{e.get('market')}/{e.get('tf')}/{e.get('symbol')}"
            records.append({"series": key, "state": series_state(agg, e), "checks": agg,
                            "n_errors": int(e.get("n_errors") or 0), "errors": (e.get("errors") or [])[:3]})
    (out / "_health").mkdir(parents=True, exist_ok=True)
    (out / "_health" / f"{a.tag}.json").write_text(json.dumps(records, indent=1))
    by = {s: sum(r["state"] == s for r in records) for s in ("ok", "warn", "fail")}
    print(f"[validate] {a.tag}: {len(records)} series {by}")
    return 0


def feed_staleness(manifest: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    feeds: Dict[tuple, Optional[pd.Timestamp]] = {}
    for e in manifest.get("files", []):
        k = (e.get("asset_class"), e.get("market"), e.get("tf"))
        last = e.get("last")
        if last:
            t = pd.Timestamp(last)
            feeds[k] = t if feeds.get(k) is None else max(feeds[k], t)
        else:
            feeds.setdefault(k, None)
    out = []
    for (asset, market, tf), last in sorted(feeds.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        lim = stale_hours(str(asset), str(market))
        age = None if last is None else (now - last.to_pydatetime()).total_seconds() / 3600
        state = "fail" if age is None or age > lim else "ok"
        out.append({"series": f"feed:{asset}/{market}/{tf}", "state": state,
                    "checks": {"newest_last_bar": None if last is None else last.isoformat(),
                               "age_hours": None if age is None else round(age, 1), "stale_after_hours": lim}})
    return out


def fold(records: List[Dict], previous: Optional[Dict]) -> List[Dict]:
    prev = {r["series"]: r for r in (previous or {}).get("series", [])}
    for r in records:
        p = prev.get(r["series"], {})
        r["consecutive_failures"] = (int(p.get("consecutive_failures") or 0) + 1) if r["state"] == "fail" else 0
        r["flagged_at"] = p.get("flagged_at") if r["state"] == "fail" else None
    # a series not rebuilt this run keeps its previous record (it was not re-checked, so it is not 'ok' by default)
    seen = {r["series"] for r in records}
    for k, p in prev.items():
        if k not in seen and not k.startswith("feed:"):
            records.append({**p, "carried": True})
    return records


def cmd_merge(a) -> int:
    base = Path(a.dir)
    now = datetime.now(timezone.utc)
    records: List[Dict] = []
    for hf in sorted((base / "_health").glob("*.json")):
        records += json.loads(hf.read_text())
    mp = base / "MANIFEST.json"
    manifest = json.loads(mp.read_text()) if mp.exists() else {"files": []}
    records += feed_staleness(manifest, now)
    previous = json.loads(Path(a.previous).read_text()) if a.previous and Path(a.previous).exists() else None
    records = fold(records, previous)
    to_flag = [r for r in records if r.get("consecutive_failures", 0) >= FLAG_AFTER and not r.get("flagged_at")]
    summary = {s: sum(r["state"] == s for r in records) for s in ("ok", "warn", "fail")}
    health = {"generated_at": now.isoformat(timespec="seconds"), "schema": "market-data-lake-health/v1",
              "run_id": a.run_id, "flag_after": FLAG_AFTER, "summary": summary, "n_series": len(records),
              "feeds": [r for r in records if r["series"].startswith("feed:")],
              "new_flags": [r["series"] for r in to_flag], "series": records}
    flagged = False
    if a.flag and to_flag:
        flagged = raise_flag(to_flag, health)
        if flagged:
            for r in to_flag:
                r["flagged_at"] = health["generated_at"]
    health["flag_delivered"] = flagged if to_flag else None
    hdir = base / "health"
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / "latest.json").write_text(json.dumps(health, indent=1))
    (hdir / f"{now.strftime('%Y%m%dT%H%MZ')}.json").write_text(json.dumps(health, indent=1))
    # small repo copy (no per-series detail beyond failures) for reviews that cannot read HF
    slim = {k: v for k, v in health.items() if k != "series"}
    slim["failing"] = [r for r in records if r["state"] == "fail"][:200]
    slim["warning_count_by_feed"] = {}
    for r in records:
        if r["state"] == "warn":
            f = "/".join(r["series"].split("/")[:3])
            slim["warning_count_by_feed"][f] = slim["warning_count_by_feed"].get(f, 0) + 1
    if a.repo_copy:
        Path(a.repo_copy).parent.mkdir(parents=True, exist_ok=True)
        Path(a.repo_copy).write_text(json.dumps(slim, indent=1))
    print(json.dumps({"summary": summary, "feeds_failing": [r["series"] for r in health["feeds"] if r["state"] == "fail"],
                      "new_flags": health["new_flags"], "flag_delivered": health["flag_delivered"]}))
    return 0


def raise_flag(rows: List[Dict], health: Dict) -> bool:
    """ONE flag per run: one ops-flags PR comment + one Telegram message, listing every series newly over the line."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import yaml
        from scripts.research.research_watchdog import GhProbe
        cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "scripts/research/research_watchdog.yaml").read_text())
        pr = cfg["ops_flags"].get("pr_number")
    except Exception as ex:
        print(f"::error::cannot load the ops-flags route: {ex}")
        return False
    probe = GhProbe()
    lines = [f"- `{r['series']}`: {r['consecutive_failures']} consecutive failing runs; "
             f"{json.dumps(r.get('checks'))[:300]}" for r in rows[:40]]
    text = (f"🔴 market-data-lake: {len(rows)} feed/series failing for >= {FLAG_AFTER} consecutive runs "
            f"(run {health.get('run_id')}). The feeds keep retrying; nothing halted.\n" + "\n".join(lines) +
            "\nHealth: hf://datasets/bentzbk/jta-market-lake/health/latest.json · comms/data_lake/health_latest.json")
    posted = bool(pr) and probe.post_comment(int(pr), text + "\n\n<!-- market-data-lake-flag -->")
    pinged = probe.ping(text[:3500])
    print(f"[validate] flag: ops-flags comment={posted} telegram={pinged}")
    return bool(posted or pinged)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "merge"])
    ap.add_argument("--out", default="lake")
    ap.add_argument("--dir", default="lake")
    ap.add_argument("--tag", default="local")
    ap.add_argument("--previous", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--repo-copy", default="")
    ap.add_argument("--flag", action="store_true")
    a = ap.parse_args(argv)
    return {"check": cmd_check, "merge": cmd_merge}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

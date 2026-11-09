#!/usr/bin/env python3
# wiring: research/queue/RQ-20261109-98e3-36.yaml (run.command) -> research-script-run.yml
"""Point-in-time book-depth table for the ETH+SOL prop slice (Binance USD-M perp, public archive bookDepth).

SOURCE   https://data.binance.vision/data/futures/um/daily/bookDepth/<SYM>/<SYM>-bookDepth-<YYYY-MM-DD>.zip, daily, keyless.
         One CSV per day: timestamp (UTC, whole seconds, ~30 s apart), percentage (-5..-1, 1..5; later files also +-0.2),
         depth (base units), notional (quote units): cumulative resting liquidity within that % of mid on each side.
         The archive starts 2023-01-01. The lake mirror holds no bookDepth (RQ-20261108-98e3-29).

OUTPUT   bar table: one row per (symbol, bar close T) for a bar of `bar_hours`, with features computed ONLY from snapshots whose
         timestamp is <= T. A snapshot older than TOL_S at T is "stale" and its features are NaN (nothing is forward-filled
         across a gap). Every file is accounted for: present / absent (404) / unreachable / unparseable, never silently dropped.

POINT-IN-TIME  the table's feature at close T is the last snapshot with ts <= T (merge_asof backward); window features use
         snapshots in (T - bar, T]. `audit()` recomputes sampled bars from the raw per-day snapshots by brute force and must
         match exactly. ASSUMPTION (stated, not provable from the file): the CSV `timestamp` is when the snapshot was taken.

    python3 scripts/research/book_depth_pit.py run --out DIR [--cache DIR] [--span 2023-01-01:2026-09-30]
    python3 scripts/research/book_depth_pit.py --self-test
"""
from __future__ import annotations

import argparse
import io
import json
import pickle
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = "book_depth_pit/1"
SYMBOLS = ("ETHUSDT", "SOLUSDT")
SPAN = ("2023-01-01", "2026-09-30")
BANDS = (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)          # present in every file; +-0.2 appears later and is never used
REQUIRED_COLS = ("timestamp", "percentage", "depth", "notional")
URL = "https://data.binance.vision/data/futures/um/daily/bookDepth/{s}/{s}-bookDepth-{d}.zip"
TOL_S = 900                                           # a snapshot older than 15 minutes at the bar close is stale (300 s drafted; see RQ-20261109-98e3-36 disclosure)
SNAP_S = 30                                           # nominal spacing of snapshots
BAR_HOURS = (4, 8)                                    # both are measured; the model unit picks one
FEATURES = ("imb1", "imb2", "imb5", "lq1", "lq5", "slope", "imb1_mean", "d_imb1")


def _get(url: str):
    """(content or None, state): state is 'ok' | 'absent' (404) | 'error' (network or HTTP failure after retries)."""
    import requests
    last = "error"
    for wait in (0, 2, 4):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None, "absent"
            r.raise_for_status()
            return r.content, "ok"
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure is returned as state 'error' and counted
            continue
    return None, last


def parse_day(raw: bytes, day: str) -> tuple[pd.DataFrame, dict]:
    """One day's zip -> (wide snapshot frame indexed by UTC ts, meta). Never raises: a bad file is reported in meta['state']."""
    meta = {"day": day, "state": "ok", "extra_cols": [], "bands_seen": [], "n_snap": 0, "n_incomplete": 0,
            "ts_in_day_share": None, "monotonic": None, "nonmonotone_cum_share": None}
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        d = pd.read_csv(z.open(z.namelist()[0]))
    except Exception as exc:  # noqa: BLE001  # allow-silent: reported in meta['state'] and counted in the census
        meta["state"] = f"unparseable:{type(exc).__name__}"
        return pd.DataFrame(), meta
    miss = [c for c in REQUIRED_COLS if c not in d.columns]
    meta["extra_cols"] = sorted(set(d.columns) - set(REQUIRED_COLS))
    if miss:
        meta["state"] = f"missing_columns:{','.join(miss)}"
        return pd.DataFrame(), meta
    if d.empty:
        meta["state"] = "empty"
        return pd.DataFrame(), meta
    d = d.copy()
    d["ts"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    d["pct"] = pd.to_numeric(d["percentage"], errors="coerce")
    d["notional"] = pd.to_numeric(d["notional"], errors="coerce")
    d = d.dropna(subset=["ts", "pct", "notional"])
    meta["bands_seen"] = sorted(float(x) for x in d["pct"].unique())
    d = d[d["pct"].isin([float(b) for b in BANDS])]
    if d.empty:
        meta["state"] = "no_expected_bands"
        return pd.DataFrame(), meta
    w = d.pivot_table(index="ts", columns="pct", values="notional", aggfunc="last")
    w.columns = [f"n{int(c)}" for c in w.columns]
    need = [f"n{b}" for b in BANDS]
    full = w.reindex(columns=need)
    ok = full.notna().all(axis=1)
    meta["n_incomplete"] = int((~ok).sum())
    full = full[ok]
    meta["n_snap"] = len(full)
    if full.empty:
        meta["state"] = "no_complete_snapshot"
        return pd.DataFrame(), meta
    full = full.sort_index()
    day0 = pd.Timestamp(day, tz="UTC")
    meta["ts_in_day_share"] = float(((full.index >= day0) & (full.index < day0 + pd.Timedelta(days=1))).mean())
    meta["monotonic"] = bool(pd.Index(pd.to_datetime(d["ts"].drop_duplicates())).is_monotonic_increasing)
    # sanity: a wider band can never hold LESS than a narrower one on the same side
    bid = full[["n-1", "n-2", "n-3", "n-4", "n-5"]].to_numpy()
    ask = full[["n1", "n2", "n3", "n4", "n5"]].to_numpy()
    bad = (np.diff(bid, axis=1) < -1e-6 * np.abs(bid[:, :-1])).any(axis=1) | (np.diff(ask, axis=1) < -1e-6 * np.abs(ask[:, :-1])).any(axis=1)
    meta["nonmonotone_cum_share"] = float(bad.mean())
    return full, meta


def snap_features(w: pd.DataFrame) -> pd.DataFrame:
    """Per-snapshot features from the +-1, 2, 5 % bands (notional). imb = (bid - ask) / (bid + ask)."""
    out = pd.DataFrame(index=w.index)
    for k in (1, 2, 5):
        b, a = w[f"n-{k}"], w[f"n{k}"]
        out[f"imb{k}"] = (b - a) / (b + a)
    t1 = w["n-1"] + w["n1"]
    t5 = w["n-5"] + w["n5"]
    out["lq1"] = np.log(t1.where(t1 > 0))
    out["lq5"] = np.log(t5.where(t5 > 0))
    out["slope"] = out["lq5"] - out["lq1"]
    return out


def bar_closes(span: tuple[str, str], bar_hours: int) -> pd.DatetimeIndex:
    """Bar close instants: every `bar_hours` from the first close after span start through the end of the last span day."""
    start = pd.Timestamp(span[0], tz="UTC")
    end = pd.Timestamp(span[1], tz="UTC") + pd.Timedelta(days=1)
    return pd.date_range(start + pd.Timedelta(hours=bar_hours), end, freq=f"{bar_hours}h")


def asof_table(feat: pd.DataFrame, span: tuple[str, str], bar_hours: int, tol_s: int = TOL_S) -> pd.DataFrame:
    """One row per bar close T. Every value uses snapshots with ts <= T only; stale (> tol_s old at T) -> NaN."""
    closes = bar_closes(span, bar_hours)
    left = pd.DataFrame({"T": closes})
    if feat.empty:
        out = left.copy()
        out["age_s"] = np.nan
        for c in FEATURES:
            out[c] = np.nan
        out["n_in_bar"] = 0
        return out
    f = feat.sort_index().copy()
    f["snap_ts"] = f.index
    # merge_asof on same-resolution int keys (mixed datetime units make it refuse or misorder)
    lk = left.assign(_k=left["T"].astype("datetime64[ns, UTC]").astype("int64"))
    rk = f.reset_index(drop=True).assign(_k=f["snap_ts"].astype("datetime64[ns, UTC]").astype("int64").to_numpy())
    m = pd.merge_asof(lk.sort_values("_k"), rk.sort_values("_k"), on="_k", direction="backward")
    m["age_s"] = (m["T"] - pd.to_datetime(m["snap_ts"], utc=True)).dt.total_seconds()
    fresh = m["age_s"] <= tol_s
    for c in ("imb1", "imb2", "imb5", "lq1", "lq5", "slope"):
        m[c] = m[c].where(fresh)
    # window mean of imb1 over (T - bar, T], needing at least half of the nominal snapshots
    bar_s = bar_hours * 3600
    ts_int = f["snap_ts"].astype("datetime64[ns, UTC]").astype("int64").to_numpy() // 10**9
    v = f["imb1"].to_numpy()
    tc = m["T"].astype("datetime64[ns, UTC]").astype("int64").to_numpy() // 10**9
    lo = np.searchsorted(ts_int, tc - bar_s, side="right")      # first snapshot with ts > T - bar
    hi = np.searchsorted(ts_int, tc, side="right")              # first snapshot with ts > T, i.e. snapshots <= T are [.., hi)
    csum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(v))])
    cok = np.concatenate([[0], np.cumsum(~np.isnan(v))])
    cnt = (cok[hi] - cok[lo]).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (csum[hi] - csum[lo]) / cnt
    need = 0.5 * bar_s / SNAP_S
    m["imb1_mean"] = np.where(cnt >= need, mean, np.nan)
    m["n_in_bar"] = cnt.astype(int)
    m = m.sort_values("T").reset_index(drop=True)
    m["d_imb1"] = m["imb1"] - m["imb1"].shift(1)                   # change since the previous bar close; NaN if either is stale
    return m[["T", "age_s", *FEATURES, "n_in_bar"]]


def audit(snaps: pd.DataFrame, table: pd.DataFrame, bar_hours: int, n: int = 1000, seed: int = 20261109) -> dict:
    """Recompute `imb1` and `lq1` for n sampled bar closes by brute force from the RAW snapshot frame and compare."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(table), size=min(n, len(table)), replace=False)
    bad = lookahead = checked = 0
    for i in idx:
        T = table["T"].iloc[i]
        upto = snaps[snaps.index <= T]
        if upto.empty:
            exp_imb = exp_lq = np.nan
        else:
            last = upto.iloc[-1]
            ts = upto.index[-1]
            if (T - ts).total_seconds() > TOL_S:
                exp_imb = exp_lq = np.nan
            else:
                exp_imb = (last["n-1"] - last["n1"]) / (last["n-1"] + last["n1"])
                exp_lq = np.log(last["n-1"] + last["n1"])
        got_imb, got_lq = table["imb1"].iloc[i], table["lq1"].iloc[i]
        same = (np.isnan(exp_imb) and np.isnan(got_imb)) or (not np.isnan(exp_imb) and not np.isnan(got_imb) and abs(exp_imb - got_imb) < 1e-12 and abs(exp_lq - got_lq) < 1e-9)
        checked += 1
        bad += 0 if same else 1
        if not np.isnan(got_imb) and not upto.empty and upto.index[-1] > T:
            lookahead += 1
    return {"checked": checked, "mismatch": bad, "lookahead": lookahead, "bar_hours": bar_hours}


def days_in(span: tuple[str, str]) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(span[0], span[1], freq="D")]


def load_day(cache: Path, sym: str, day: str) -> tuple[pd.DataFrame, dict]:
    p = cache / sym / f"{day}.pkl"
    if p.is_file():
        try:
            return pickle.loads(p.read_bytes())
        except Exception:  # noqa: BLE001, S110  # allow-silent: a corrupt cache entry is refetched
            pass
    raw, st = _get(URL.format(s=sym, d=day))
    if raw is None:
        res = (pd.DataFrame(), {"day": day, "state": st})
    else:
        res = parse_day(raw, day)
    if res[1]["state"] != "error":                       # an unreachable day is never cached as if it were an answer
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pickle.dumps(res))
    return res


def census_symbol(sym: str, parts: list[tuple[pd.DataFrame, dict]]) -> tuple[pd.DataFrame, dict]:
    metas = [m for _, m in parts]
    present = [m for m in metas if m["state"] == "ok"]
    bad = [m for m in metas if m["state"] not in ("ok", "absent", "error")]
    err = [m for m in metas if m["state"] == "error"]
    absent = [m for m in metas if m["state"] == "absent"]
    snaps = pd.concat([w for w, m in parts if m["state"] == "ok"]).sort_index() if present else pd.DataFrame()
    if not snaps.empty:
        snaps = snaps[~snaps.index.duplicated(keep="last")]
    cen = {"symbol": sym, "days_expected": len(metas), "days_present": len(present), "days_absent_404": len(absent), "days_unreachable": len(err),
           "days_unparseable": len(bad), "first_absent_days": [m["day"] for m in absent][:20], "unparseable_sample": [(m["day"], m["state"]) for m in bad][:10],
           "snapshots": int(sum(m["n_snap"] for m in present)), "incomplete_snapshots": int(sum(m["n_incomplete"] for m in present)),
           "extra_cols_seen": sorted({c for m in present for c in m["extra_cols"]}),
           "band_sets": sorted({tuple(m["bands_seen"]) for m in present}), "nonmonotone_files": int(sum(1 for m in present if m["monotonic"] is False)),
           "min_ts_in_day_share": min((m["ts_in_day_share"] for m in present), default=None),
           "max_nonmonotone_cum_share": max((m["nonmonotone_cum_share"] for m in present), default=None),
           "first_day": present[0]["day"] if present else None, "last_day": present[-1]["day"] if present else None}
    return snaps, cen


def run(a) -> int:
    span = tuple(a.span.split(":")) if a.span else SPAN
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    days = days_in(span)
    res: dict = {"schema": SCHEMA, "span": list(span), "symbols": list(SYMBOLS), "tol_s": TOL_S, "bands": list(BANDS), "bar_hours": list(BAR_HOURS),
                 "assumption": "the CSV timestamp is the snapshot capture time; not provable from the file", "per_symbol": {}}
    tables = {}
    with ThreadPoolExecutor(8) as ex:
        for sym in SYMBOLS:
            parts = list(ex.map(lambda d, s=sym: load_day(cache, s, d), days))
            snaps, cen = census_symbol(sym, parts)
            feat = snap_features(snaps) if not snaps.empty else pd.DataFrame()
            cen["bars"] = {}
            for bh in BAR_HOURS:
                t = asof_table(feat, span, bh)
                fresh = t["imb1"].notna()
                run_len = int((fresh != fresh.shift()).cumsum()[~fresh].value_counts().max()) if (~fresh).any() else 0
                cen["bars"][str(bh)] = {"expected": len(t), "fresh": int(fresh.sum()), "coverage": float(fresh.mean()),
                                        "longest_stale_run_bars": run_len, "all_features_present_share": float(t[list(FEATURES)].notna().all(axis=1).mean())}
                tt = t.assign(m=t["T"].dt.strftime("%Y-%m"), f=fresh)
                cen["bars"][str(bh)]["coverage_by_month"] = {k: round(float(v), 3) for k, v in tt.groupby("m")["f"].mean().items()}
                cen["bars"][str(bh)]["coverage_300s"] = float((t["age_s"] <= 300).mean())
                tables[(sym, bh)] = t
                cen.setdefault("audit", {})[str(bh)] = audit(snaps, t, bh) if not snaps.empty else {"checked": 0, "mismatch": 0, "lookahead": 0, "bar_hours": bh}
            res["per_symbol"][sym] = cen
            cov = ", ".join(f"{k}h: {v['coverage']:.3f}" for k, v in cen["bars"].items())
            print(f"{sym}: days present {cen['days_present']}/{cen['days_expected']} unreachable {cen['days_unreachable']} "
                  f"unparseable {cen['days_unparseable']} bar coverage {{{cov}}}", flush=True)
    verdict, why = grade(res)
    res["verdict"], res["reason"] = verdict, why
    for (sym, bh), t in tables.items():
        t.assign(symbol=sym).to_pickle(out / f"book_depth_{sym}_{bh}h.pkl")
    (out / "measurement.json").write_text(json.dumps(res, indent=1, default=str))
    row = {"schema_version": 1, "research_unit": a.unit, "verdict": {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate"}[verdict],
           "read_state": "measured" if verdict != "INDETERMINATE" else "no_data", "note": f"{SCHEMA}; {verdict}: {why}",
           "population": {"description": f"Binance USD-M perp bookDepth daily archive, {'/'.join(SYMBOLS)}, {span[0]}..{span[1]}, bars {list(BAR_HOURS)} h",
                          "n": int(sum(c["days_present"] for c in res["per_symbol"].values()))},
           "measurement": {"per_symbol": {s: {k: c[k] for k in ("days_expected", "days_present", "days_unreachable", "days_unparseable")} | {"bars": c["bars"], "audit": c["audit"]}
                                          for s, c in res["per_symbol"].items()}}}
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"BOOK-DEPTH-PIT: {verdict}: {why}", flush=True)
    return 0


def grade(res: dict) -> tuple[str, str]:
    """The registered rule (RULE-RQ20261109-98e3-36-BOOKDEPTH-PIT). Thresholds are fixed in the unit before any run."""
    ps = res["per_symbol"]
    n_days = sum(c["days_expected"] for c in ps.values())
    n_err = sum(c["days_unreachable"] for c in ps.values())
    if n_days == 0 or n_err / n_days > 0.05:
        return "INDETERMINATE", f"{n_err} of {n_days} day-files unreachable (> 5%): absent vs unreachable cannot be told apart"
    fails = []
    for s, c in ps.items():
        if c["days_present"] / c["days_expected"] < 0.95:
            fails.append(f"{s}: only {c['days_present']}/{c['days_expected']} day-files present (< 95%)")
        if c["days_unparseable"] > 0:
            fails.append(f"{s}: {c['days_unparseable']} unparseable day-file(s)")
        if c["nonmonotone_files"] > 0.01 * max(c["days_present"], 1):
            fails.append(f"{s}: {c['nonmonotone_files']} files with non-monotone timestamps (> 1%)")
        for bh, b in c["bars"].items():
            if b["coverage"] < 0.95:
                fails.append(f"{s}: {bh}h bar coverage {b['coverage']:.3f} (< 0.95)")
        for bh, au in c["audit"].items():
            if au["checked"] < 1000 or au["mismatch"] or au["lookahead"]:
                fails.append(f"{s}: {bh}h audit checked {au['checked']} mismatch {au['mismatch']} lookahead {au['lookahead']}")
    return ("PASS", "every clause holds for both symbols") if not fails else ("FAIL", "; ".join(fails[:6]))


# ----------------------------------------------------------------------------------------------- self-test
def _fake_day(day: str, start_s: int = 0, step: int = 30, n: int = 2880, bands=BANDS, bid_scale: float = 1.0, cols=REQUIRED_COLS, cum_ok: bool = True) -> bytes:
    t0 = pd.Timestamp(day, tz="UTC") + pd.Timedelta(seconds=start_s)
    rows = []
    for i in range(n):
        ts = (t0 + pd.Timedelta(seconds=i * step)).strftime("%Y-%m-%d %H:%M:%S")
        for b in bands:
            k = abs(b) if cum_ok else 6 - abs(b)
            rows.append((ts, b, 1.0, (100.0 * k * (bid_scale if b < 0 else 1.0)) + i * 0.01))
    d = pd.DataFrame(rows, columns=["timestamp", "percentage", "depth", "notional"])
    d = d[[c for c in cols if c in d.columns]]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", d.to_csv(index=False))
    return buf.getvalue()


def _self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  PASS: " if cond else "  FAIL: ") + name)
        ok &= bool(cond)

    day = "2023-01-02"
    w, m = parse_day(_fake_day(day), day)
    check("a complete day parses: 2880 snapshots, schema ok", m["state"] == "ok" and m["n_snap"] == 2880 and w.shape[1] == 10)
    check("timestamps inside the day and cumulative bands monotone", m["ts_in_day_share"] == 1.0 and m["nonmonotone_cum_share"] == 0.0)
    _, m2 = parse_day(_fake_day(day, cols=("timestamp", "percentage", "notional")), day)
    check("a missing column is reported, never silently parsed", m2["state"].startswith("missing_columns"))
    _, m3 = parse_day(b"not a zip", day)
    check("garbage bytes are reported as unparseable", m3["state"].startswith("unparseable"))
    _, m4 = parse_day(_fake_day(day, bands=BANDS + (0.2, -0.2)), day)
    check("extra +-0.2 bands are tolerated and never used", m4["state"] == "ok" and 0.2 in m4["bands_seen"])
    _w5, m5 = parse_day(_fake_day(day, cum_ok=False), day)
    check("a band set that shrinks outward is counted as non-monotone", m5["nonmonotone_cum_share"] > 0.99)

    # as-of: bar 00:00-04:00 close at 04:00; a snapshot at 04:00:20 must NOT reach the 04:00 bar
    f = snap_features(w)
    t = asof_table(f, (day, day), 4)
    row = t[t["T"] == pd.Timestamp("2023-01-02 04:00:00", tz="UTC")].iloc[0]
    exp = f[f.index <= pd.Timestamp("2023-01-02 04:00:00", tz="UTC")].iloc[-1]
    check("feature at close T equals the last snapshot <= T", abs(row["imb1"] - exp["imb1"]) < 1e-12 and row["age_s"] <= 30)
    t2 = asof_table(f.iloc[:480], (day, day), 4)          # snapshots only up to ~04:00; the 08:00 close must be stale
    r8 = t2[t2["T"] == pd.Timestamp("2023-01-02 08:00:00", tz="UTC")].iloc[0]
    check("a bar closing long after the last snapshot is stale -> NaN, not forward-filled", np.isnan(r8["imb1"]) and r8["age_s"] > TOL_S)
    # planted look-ahead: shift the recorded snapshot timestamps back 60 s and the audit must notice
    shifted = w.copy()
    shifted.index = shifted.index - pd.Timedelta(seconds=60)
    au_ok = audit(w, t, 4, n=1000)
    au_bad = audit(shifted, t, 4, n=1000)
    check("audit passes on the honest table", au_ok["mismatch"] == 0 and au_ok["lookahead"] == 0)
    check("PLANTED DEFECT: a table built from different timestamps fails the audit", au_bad["mismatch"] > 0 or au_bad["lookahead"] > 0)
    check("window mean needs half the nominal snapshots", asof_table(f.iloc[:30], (day, day), 4)["imb1_mean"].isna().all())
    # grading
    base = {"days_expected": 100, "days_present": 100, "days_unreachable": 0, "days_unparseable": 0, "nonmonotone_files": 0,
            "bars": {"4": {"coverage": 0.99}, "8": {"coverage": 0.99}}, "audit": {"4": {"checked": 1000, "mismatch": 0, "lookahead": 0}, "8": {"checked": 1000, "mismatch": 0, "lookahead": 0}}}
    good = {"per_symbol": {"ETHUSDT": dict(base), "SOLUSDT": dict(base)}}
    check("grade: PASS when every clause holds", grade(good)[0] == "PASS")
    bad = {"per_symbol": {"ETHUSDT": dict(base), "SOLUSDT": dict(base, days_present=90)}}
    check("grade: FAIL when a symbol has < 95% of day-files", grade(bad)[0] == "FAIL")
    unr = {"per_symbol": {"ETHUSDT": dict(base, days_unreachable=20), "SOLUSDT": dict(base)}}
    check("grade: INDETERMINATE when > 5% of day-files are unreachable (absent is not told from unreachable)", grade(unr)[0] == "INDETERMINATE")
    low = {"per_symbol": {"ETHUSDT": dict(base, bars={"4": {"coverage": 0.9}, "8": {"coverage": 0.99}}), "SOLUSDT": dict(base)}}
    check("grade: FAIL when bar coverage < 95%", grade(low)[0] == "FAIL")
    mis = {"per_symbol": {"ETHUSDT": dict(base, audit={"4": {"checked": 1000, "mismatch": 1, "lookahead": 0}, "8": {"checked": 1000, "mismatch": 0, "lookahead": 0}}), "SOLUSDT": dict(base)}}
    check("grade: FAIL on a single audit mismatch", grade(mis)[0] == "FAIL")
    print("book_depth_pit self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--cache", default="/tmp/book_depth_cache")
    r.add_argument("--span", default="", help="START:END ISO dates (default 2023-01-01:2026-09-30)")
    r.add_argument("--unit", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.cmd == "run":
        return run(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

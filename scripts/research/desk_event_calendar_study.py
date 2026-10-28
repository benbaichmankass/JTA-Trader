"""DESK-EVENT-CALENDAR event study (Tier 1, research only). Rule registered in
docs/research/desk-event-calendar-scope-2026-10-28.md § 1 BEFORE this ran.
Subcommands: fetch (Binance Vision klines 5m / fundingRate / metrics) and run.
Off-VM only; never imported by the trader."""
# wiring: manual-only - off-VM research study run by hand; its result is committed to comms/research/desk_event_calendar/study.json
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

SYMS = ["ADAUSDT", "AVAXUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
BASE = "https://data.binance.vision/data/futures/um"
COST = 12.3
HORIZ = {"1h": 12, "4h": 48, "24h": 288}  # 5m bars
LAT = 1  # entry = first bar at/after known_at + 5 min
END = dt.datetime(2026, 9, 30, 23, 59, tzinfo=dt.UTC)
FAMILY = 15
BOOT = 10000
MIN_CLUSTERS = 100
RNG = np.random.default_rng(20261028)


def _get(url):
    for i in range(3):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except OSError:
            time.sleep(1 + i)
    return None


def _months(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def fetch(root: Path, oi_from=dt.date(2024, 1, 1)):
    jobs = []
    for s in SYMS:
        for y, m in _months((2020, 9), (2026, 9)):
            jobs.append((f"{BASE}/monthly/klines/{s}/5m/{s}-5m-{y}-{m:02d}.zip", root / "k5" / s / f"{y}-{m:02d}.csv"))
            jobs.append((f"{BASE}/monthly/fundingRate/{s}/{s}-fundingRate-{y}-{m:02d}.zip", root / "fr" / s / f"{y}-{m:02d}.csv"))
        d = oi_from
        while d <= END.date():
            jobs.append((f"{BASE}/daily/metrics/{s}/{s}-metrics-{d}.zip", root / "oi" / s / f"{d}.csv"))
            d += dt.timedelta(days=1)

    def one(j):
        url, out = j
        if out.exists():
            return 1
        b = _get(url)
        if b is None:
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        z = zipfile.ZipFile(io.BytesIO(b))
        out.write_bytes(z.read(z.namelist()[0]))
        return 1
    with ThreadPoolExecutor(32) as ex:
        ok = sum(ex.map(one, jobs))
    print(f"fetched {ok}/{len(jobs)}")


def _read_csv(p):
    txt = p.read_text().splitlines()
    return [ln.split(",") for ln in txt if ln and not ln[0].isalpha()]


def _dir_rows(d):
    """Every data row of every monthly/daily CSV in directory d, files in name order."""
    out = []
    for p in sorted(d.glob("*.csv")):
        out += _read_csv(p)
    return out


def load_k5(root, s):
    rows = [(int(r[0]), float(r[1]), float(r[4])) for r in _dir_rows(root / "k5" / s)]
    a = np.array(rows, dtype=float)
    t = (a[:, 0] // 300000).astype(np.int64) * 300  # sec, 5m aligned
    _, ix = np.unique(t, return_index=True)
    return t[ix], a[ix, 1], a[ix, 2]


def vol_dec(c):
    lr = np.diff(np.log(c), prepend=np.log(c[0]))
    cs = np.cumsum(lr ** 2)
    n = 288
    v = np.full(len(c), np.nan)
    v[n:] = np.sqrt((cs[n:] - cs[:-n]) / n)
    good = ~np.isnan(v)
    edges = np.nanquantile(v[good], np.linspace(0, 1, 11)[1:-1])
    dec = np.full(len(c), -1)
    dec[good] = np.searchsorted(edges, v[good])
    return dec


def entry_ix(t, known_at):
    return int(np.searchsorted(t, known_at + 300 * LAT, side="left"))


def fwd_gross(o, ix, h, d):
    j = ix + h
    if ix < 0 or j >= len(o):
        return np.nan
    return d * (o[j] / o[ix] - 1) * 1e4


class Sym:
    def __init__(self, root, s):
        self.s = s
        self.t, self.o, self.c = load_k5(root, s)
        self.dec = vol_dec(self.c)
        self.hour = ((self.t // 3600) % 24).astype(int)
        self.cache = {}

    def pool(self, ev_times, h):
        """base arrays: random-entry fwd return (long) per bar, by (decile,hour) cell excluding bars within 24h of events."""
        key = (id(ev_times), h)
        if key in self.cache:
            return self.cache[key]
        n = len(self.o)
        r = np.full(n, np.nan)
        r[: n - h] = (self.o[h:] / self.o[: n - h] - 1) * 1e4
        ok = ~np.isnan(r) & (self.dec >= 0)
        if len(ev_times):
            ev = np.sort(np.asarray(ev_times))
            ix = np.searchsorted(ev, self.t)
            near = np.zeros(n, bool)
            for k in (ix - 1, ix):
                kk = np.clip(k, 0, len(ev) - 1)
                near |= np.abs(ev[kk] - self.t) < 86400
            ok &= ~near
        cell = self.dec * 24 + self.hour
        sums = np.zeros(240)
        cnt = np.zeros(240)
        np.add.at(sums, cell[ok], r[ok])
        np.add.at(cnt, cell[ok], 1)
        out = (sums, cnt)
        self.cache[key] = out
        return out

    def base(self, ix, ev_times, h, d):
        sums, cnt = self.pool(ev_times, h)
        c = self.dec[ix] * 24 + self.hour[ix]
        if self.dec[ix] < 0 or cnt[c] < 30:
            return np.nan
        return d * sums[c] / cnt[c]


def boot_ci(vals, days, alpha):
    ud = np.unique(days)
    grp = {u: vals[days == u] for u in ud}
    sums = np.array([grp[u].sum() for u in ud])
    ns = np.array([len(grp[u]) for u in ud])
    k = len(ud)
    idx = RNG.integers(0, k, size=(BOOT, k))
    m = sums[idx].sum(1) / ns[idx].sum(1)
    return float(np.quantile(m, alpha / 2)), float(np.quantile(m, 1 - alpha / 2))


def verdict(n_cl, net_lo, ex_lo, ex_hi, halves_ok, cost=COST):
    if n_cl < MIN_CLUSTERS:
        return "insufficient_n"
    if net_lo > 0 and ex_lo > 0 and halves_ok:
        return "candidate"
    if ex_hi < cost:
        return "no_edge"
    return "inconclusive"


def evaluate(syms, events, planted=0.0):
    """events: list of (sym, known_at_sec, dir). One class. Returns {h: stats}."""
    ev_times = {}
    for s, k, d in events:
        ev_times.setdefault(s, []).append(k)
    ev_times = {s: np.array(v) for s, v in ev_times.items()}
    out = {}
    for S in syms.values():
        S.cache.clear()  # the pool cache is keyed by id(ev_times): never reuse it across event sets
    for hn, h in HORIZ.items():
        g, b, days, ks = [], [], [], []
        for s, k, d in events:
            S = syms[s]
            ix = entry_ix(S.t, k)
            if ix >= len(S.t) or S.t[ix] - k > 900:  # no bar within 15 min of known_at+5m: skip
                continue
            gr = fwd_gross(S.o, ix, h, d)
            if np.isnan(gr):
                continue
            ba = S.base(ix, ev_times[s], h, d)
            if np.isnan(ba):
                continue
            g.append(gr + (planted if (planted and hn == "4h") else 0.0))
            b.append(ba)
            days.append(int(k // 86400))
            ks.append(k)
        g = np.array(g)
        b = np.array(b)
        days = np.array(days)
        ks = np.array(ks)
        if len(g) == 0:
            out[hn] = {"n_rows": 0, "n_events": 0, "n_day_clusters": 0, "verdict": "insufficient_n"}
            continue
        net = g - COST
        ex = g - b
        ncl = len(np.unique(days))
        a1, a2 = 0.05, 0.05 / FAMILY
        net_ci95 = boot_ci(net, days, a1)
        ex_ci95 = boot_ci(ex, days, a1)
        net_ciC = boot_ci(net, days, a2)
        ex_ciC = boot_ci(ex, days, a2)
        med = np.median(ks)
        halves_ok = bool(net[ks <= med].mean() > 0 and net[ks > med].mean() > 0)
        span_y = max((ks.max() - ks.min()) / (365.25 * 86400), 1e-9)
        out[hn] = {
            "n_rows": len(g), "n_events": len(np.unique(ks)), "n_day_clusters": int(ncl),
            "gross_bps": round(float(g.mean()), 2), "baseline_bps": round(float(b.mean()), 2),
            "net_bps": round(float(net.mean()), 2), "excess_bps": round(float(ex.mean()), 2),
            "net_ci95": [round(x, 2) for x in net_ci95], "excess_ci95": [round(x, 2) for x in ex_ci95],
            "net_ci_corrected": [round(x, 2) for x in net_ciC], "excess_ci_corrected": [round(x, 2) for x in ex_ciC],
            "halves_net_pos": halves_ok,
            "clusters_per_year": round(ncl / span_y, 1),
            "verdict": verdict(ncl, net_ciC[0], ex_ciC[0], ex_ciC[1], halves_ok),
        }
        if ncl < MIN_CLUSTERS:
            out[hn]["time_to_n_years"] = round((MIN_CLUSTERS - ncl) / max(ncl / span_y, 1e-9), 2)
    return out


def build_events(root):
    adir = Path(__file__).resolve().parents[2] / "comms/research/desk_event_calendar"
    ann = {c: json.loads((adir / f"ann_{c}.json").read_text()) for c in (48, 161)}
    ev = {k: [] for k in ("C1", "C2", "C3", "C4", "C5")}
    start1 = dt.datetime(2020, 10, 1, tzinfo=dt.UTC).timestamp()
    start2 = dt.datetime(2022, 2, 17, tzinfo=dt.UTC).timestamp()
    end = END.timestamp()
    for cat, key, d, st in ((48, "C1", 1, start1), (161, "C2", -1, start2)):
        for k in sorted({int(r["ts"] // 1000) for r in ann[cat]}):
            if st <= k <= end:
                ev[key] += [(s, k, d) for s in SYMS]
    for s in SYMS:
        fr = [(int(r[0]) // 1000, float(r[2])) for r in _dir_rows(root / "fr" / s)]
        fr.sort()
        ft = np.array([x[0] for x in fr])
        fv = np.array([x[1] for x in fr])
        for i in range(90, len(fv)):
            w = fv[i - 90:i]
            sd = w.std()
            if sd > 0 and abs(fv[i] - w.mean()) / sd >= 2 and ft[i] <= end:
                ev["C3"].append((s, int(ft[i]), -1 if fv[i] > 0 else 1))
        # C4
        rows = [(dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC).timestamp(), float(r[2]))
                for r in _dir_rows(root / "oi" / s)]
        if rows:
            rows.sort()
            t = np.array([r[0] for r in rows])
            oi = np.array([r[1] for r in rows])
            # require contiguous 5m grid
            ch = np.zeros(len(oi))
            okv = np.zeros(len(oi), bool)
            good = (oi[12:] > 0) & (oi[:-12] > 0)
            ch[12:][good] = oi[12:][good] / oi[:-12][good] - 1
            okv[12:] = good
            ok12 = np.zeros(len(oi), bool)
            ok12[12:] = good & ((t[12:] - t[:-12]) == 3600)
            W = 2016
            S = Sym(root, s)
            last = -1e18
            cs = np.cumsum(ch)
            cs2 = np.cumsum(ch ** 2)
            for i in range(W + 12, len(oi)):
                if not ok12[i] or t[i] - t[i - W] > 7.5 * 86400:
                    continue
                m = (cs[i - 1] - cs[i - W - 1]) / W
                v = (cs2[i - 1] - cs2[i - W - 1]) / W - m * m
                if v <= 0:
                    continue
                z = (ch[i] - m) / np.sqrt(v)
                known = t[i] + 300
                if z >= 3 and known - last >= 6 * 3600 and known <= end:
                    j = int(np.searchsorted(S.t, known, side="left"))
                    if j > 14 and j < len(S.t):
                        pr = S.c[j - 1] / S.c[j - 13] - 1
                        if pr != 0:
                            ev["C4"].append((s, int(known), 1 if pr > 0 else -1))
                            last = known
    for y, m in _months((2020, 10), (2026, 9)):
        ev["C5"].append(("XRPUSDT", int(dt.datetime(y, m, 1, tzinfo=dt.UTC).timestamp()), -1))
    return ev


def run(root, out):
    syms = {s: Sym(root, s) for s in SYMS}
    ev = build_events(root)
    res = {"cost_bps": COST, "family": FAMILY, "classes": {}, "controls": {}}
    for k, e in ev.items():
        # restrict each event to symbol-specific data start
        e = [(s, t, d) for s, t, d in e if t >= syms[s].t[0] + 30 * 86400]
        res["classes"][k] = {"n_event_rows_registered": len(e), "horizons": evaluate(syms, e)}
        print(k, len(e), {h: (v.get("verdict"), v.get("net_bps"), v.get("excess_bps"), v.get("n_day_clusters")) for h, v in res["classes"][k]["horizons"].items()}, flush=True)
    # controls: 200 random events across symbols (one per random bar), planted +30 bps at 4h
    rr = np.random.default_rng(7)
    ctl = []
    for _ in range(200):
        s = SYMS[rr.integers(6)]
        S = syms[s]
        i = int(rr.integers(S.dec.size // 10, S.dec.size - 400))
        ctl.append((s, int(S.t[i]), 1))
    res["controls"]["null"] = evaluate(syms, ctl)
    for pl in (30.0, 100.0):  # AMENDED 2026-10-28: the registered 30 bps planting is under-powered at n=200 (see doc 4.1); 100 bps added
        res["controls"][f"planted_{int(pl)}bps_4h"] = evaluate(syms, ctl, planted=pl + COST)  # bps NET of cost over the null mean
    Path(out).write_text(json.dumps(res, indent=1))
    print("controls 4h:", {k: (v["4h"]["verdict"], v["4h"].get("net_ci_corrected")) for k, v in res["controls"].items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    ap.add_argument("--root", default="/tmp/claude-0/sp/data")
    ap.add_argument("--out", default="comms/research/desk_event_calendar/study.json")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(Path(a.root))
    else:
        run(Path(a.root), a.out)

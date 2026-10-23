#!/usr/bin/env python3
"""NEWS-HIST-REPLAY step 1 -- build a POINT-IN-TIME historical news corpus from GDELT 2.0 GKG.

WHY GDELT GKG (evaluated 2026-10-12; the comparison table is in research/news_hist/MANIFEST.json)
-------------------------------------------------------------------------------------------------------
* Free, keyless, 15-minute files back to 2015-02-18 (history depth >> the 3y target).
* Each GKG 2.1 row carries the article URL, its source domain, a PAGE_TITLE (the
  headline -- all the live scorer needs; the RSS path in production is title+summary
  and the normalizer's sentiment is a keyword count) and -- for ~40-45% of rows --
  a PAGE_PRECISEPUBTIMESTAMP (the publisher's own time).
* NO LOOK-AHEAD BY CONSTRUCTION: each row sits in the file stamped with the time
  GDELT *ingested* it (V2.1DATE). We store that as ``available_at`` and the replay
  harness only lets an item influence a signal when ``available_at < signal_ts``.
  ``publishedAt`` = min(precise-pub, ingest) is used ONLY for the freshness term
  (age at decision time) -- never for gating availability. So an item can arrive
  late relative to live RSS (conservative: biases toward FEWER vetoes), never early.

OUTPUT SHAPE
------------
One JSONL line per kept article, in the RAW shape ``src.news.news_normalizer.normalize_article``
already consumes in production (NewsAPI/RSS-shaped), so the replay harness runs the
LIVE normalizer + scorer over it unchanged:

    {"title", "description": "", "url", "publishedAt" (ISO-8601 Z),
     "source": {"name": "<domain>"},
     "available_at" (ISO-8601 Z, GDELT ingest time), "pub_basis": "precise"|"ingest"}

Files are sharded per UTC *availability* day: ``<out>/YYYY/MM/YYYY-MM-DD.jsonl``.
Data is large and lives OFF-REPO (trainer VM, ``--out`` of your choice); only this code and
``research/news_hist/MANIFEST.json`` are committed.

PRE-FILTER (never drops anything the live scorer would count)
-------------------------------------------------------------
Keep a row iff its source domain is in the allow-list derived from the LIVE feed config
(``config/news_feeds.yaml``, every feed URL's registrable domain + a small alias map; ``--sources broad`` adds
``BROAD_DOMAINS``, a superset the replay filters back down) AND
its title contains any relevance keyword the live normalizer could match (every
``news_symbols.yaml`` symbol keyword + the shared macro keywords + the built-in crypto map)
-- the same lower-cased substring test ``news_normalizer._relevance_breakdown`` uses, so
the filter is a superset of "relevance > 0" for every instrument.

MODES
-----
  --start/--end            every 15-min file in the range (full coverage; optionally --stride N)
  --signal-times FILE      only the files that can influence a signal: for each signal time t
                           (JSONL/JSON rows with ``entry_time``) the files stamped in
                           [t - (max_age + slack), t). Orders of magnitude cheaper for sparse legs.

Resumable: ``<out>/_ledger.jsonl`` records each file (ok / missing / error) and is
consulted on re-run. Streams download -> filter -> delete; the zip is never kept.

⚠️ Verification: a missing/failed file is a GAP, recorded in the ledger and the manifest as
such -- "no items" and "file not fetched" are different states and never collapsed.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

GKG_URL = "https://data.gdeltproject.org/gdeltv2/{ts}.gkg.csv.zip"
GKG_FIRST = datetime(2015, 2, 18, 23, 0, tzinfo=timezone.utc)  # first GDELT 2.0 file
STEP = timedelta(minutes=15)
# Column positions in GKG 2.1 (tab-separated, 27 columns).
C_DATE, C_DOMAIN, C_URL, C_EXTRAS = 1, 3, 4, 26

# Feed hosts that are not the article's registrable domain in GKG.
DOMAIN_ALIASES: Dict[str, List[str]] = {
    "feeds.content.dowjones.io": ["marketwatch.com", "wsj.com", "barrons.com"],
    "federalreserve.gov": ["federalreserve.gov"],
}

# Credible financial / crypto / commodity press beyond the live RSS set (--sources broad). Chosen BEFORE any
# outcome was computed, from the domains present in a one-day all-source GKG sample (2024-03-05) minus
# press-release aggregators / auto-generated ticker sites (biztoc, wkrb13, tickerreport, openpr, ...).
BROAD_DOMAINS = frozenset("""
reuters.com bloomberg.com bnnbloomberg.ca ft.com wsj.com barrons.com marketwatch.com cnbc.com forbes.com
businessinsider.com benzinga.com seekingalpha.com fool.com investing.com fxstreet.com forexlive.com yahoo.com
cnn.com apnews.com rttnews.com streetinsider.com marketscreener.com finanznachrichten.de thestreet.com
zerohedge.com fortune.com nasdaq.com investopedia.com tradingview.com financialexpress.com moneycontrol.com
livemint.com theglobeandmail.com coindesk.com cointelegraph.com decrypt.co theblock.co bitcoinist.com newsbtc.com
cryptoslate.com cryptonews.com u.today beincrypto.com ambcrypto.com cryptopotato.com bitcoinmagazine.com
coingape.com cryptobriefing.com dailyhodl.com bitcoin.com oilprice.com kitco.com mining.com federalreserve.gov
""".split())

_PRECISE_RE = re.compile(r"<PAGE_PRECISEPUBTIMESTAMP>(\d{14})")
_TITLE_RE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)


def _registrable(host: str) -> str:
    host = host.lower().split(":")[0]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def feed_domain_allowlist() -> Set[str]:
    """Registrable domains of every feed in the LIVE config (+ aliases)."""
    from urllib.parse import urlparse

    from src.news.news_feeds import load_feeds_config

    out: Set[str] = set()
    for urls in (load_feeds_config().get("groups") or {}).values():
        for u in urls:
            host = urlparse(str(u)).hostname or ""
            if not host:
                continue
            if host in DOMAIN_ALIASES:
                out.update(DOMAIN_ALIASES[host])
            out.add(_registrable(host))
    return out


def relevance_keywords() -> List[str]:
    """Every keyword the live normalizer could match (superset of relevance > 0)."""
    from src.news import news_normalizer as nn
    from src.news import news_symbols as ns

    kws: Set[str] = set(ns.macro_keywords())
    cfg = ns.load_symbol_config().get("symbols", {})
    for base in cfg:
        kws.update(ns.keywords_for_base(base) or [])
    for words in nn._SYMBOL_KEYWORDS.values():
        kws.update(words)
    return sorted(k for k in kws if k)


def parse_ts14(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_gkg_rows(
    fh: Iterable[str],
    *,
    domains: Optional[Set[str]],
    keywords: Sequence[str],
) -> Iterator[Dict[str, Any]]:
    """Yield raw normalizer-shaped articles from one decoded GKG file.

    ``publishedAt`` is clamped to ``<= available_at`` so a bogus future precise
    timestamp can never make an item look younger than it is.
    """
    # GKG is unquoted TSV: a plain split is ~5x cheaper than csv.reader and the domain test below
    # discards >99% of rows before anything else is parsed (fetch is CPU-bound, not network-bound).
    for line in fh:
        r = line.rstrip("\r\n").split("\t")
        if len(r) < 27:
            continue
        domain = r[C_DOMAIN].lower()
        if domains is not None and _registrable(domain) not in domains and domain not in domains:
            continue
        m = _TITLE_RE.search(r[C_EXTRAS])
        if not m:
            continue
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        low = title.lower()
        if not title or not any(k in low for k in keywords):
            continue
        try:
            avail = parse_ts14(r[C_DATE])
        except ValueError:
            continue
        pub, basis = avail, "ingest"
        pm = _PRECISE_RE.search(r[C_EXTRAS])
        if pm:
            try:
                p = parse_ts14(pm.group(1))
                if p <= avail:
                    pub, basis = p, "precise"
            except ValueError:
                pass
        yield {
            "title": title, "description": "", "url": r[C_URL],
            "publishedAt": iso_z(pub), "source": {"name": domain},
            "available_at": iso_z(avail), "pub_basis": basis,
        }



# ── ARCHIVE profile (NEWS-ALPHA reuse): EVERY GKG row, compact metadata, no keyword/domain filter ─────
# The default profile above keeps only title-bearing rows the live scorer could count (a slice built for the
# G1-offline replay). A standalone-edge research family needs the whole point-in-time stream: per item the
# publish/ingest timestamps, source domain, URL hash (dedup key), GDELT tone vector, theme / person / org /
# country entities, and the headline. Schema version ARCHIVE_SCHEMA; one gz JSONL shard per UTC availability day.
ARCHIVE_SCHEMA = "gkg-archive-v1"
C_THEMES, C_LOCS, C_PERSONS, C_ORGS, C_TONE = 7, 9, 11, 13, 15


def _names(field: str, cap: int = 40) -> List[str]:
    out, seen = [], set()
    for x in field.split(";"):
        x = x.split(",")[0].strip()          # themes carry ",offset"; persons/orgs are bare names
        if x and x not in seen:
            seen.add(x)
            out.append(x)
            if len(out) >= cap:
                break
    return out


def archive_rows(fh: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Yield one compact record per GKG row. ``a`` (ingest) is the availability time; ``p`` <= ``a`` always."""
    for line in fh:
        r = line.rstrip("\r\n").split("\t")
        if len(r) < 27:
            continue
        try:
            avail = parse_ts14(r[C_DATE])
        except ValueError:
            continue
        pub, basis = avail, "ingest"
        pm = _PRECISE_RE.search(r[C_EXTRAS])
        if pm:
            try:
                pp = parse_ts14(pm.group(1))
                if pp <= avail:
                    pub, basis = pp, "precise"
            except ValueError:
                pass
        tm = _TITLE_RE.search(r[C_EXTRAS])
        tone = []
        for x in r[C_TONE].split(",")[:7]:
            try:
                tone.append(round(float(x), 3))
            except ValueError:
                tone.append(None)
        countries = sorted({b.split("#")[2] for b in r[C_LOCS].split(";") if b.count("#") >= 3 and b.split("#")[2]})
        yield {"a": iso_z(avail), "p": iso_z(pub), "pb": basis[0], "d": r[C_DOMAIN].lower(),
               "u": hashlib.sha1(r[C_URL].encode("utf-8", "replace")).hexdigest()[:16],
               "tone": tone,  # [tone, positive, negative, polarity, activity_ref_density, selfgroup_density, wordcount]
               "th": _names(r[C_THEMES]), "pe": _names(r[C_PERSONS], 15), "or": _names(r[C_ORGS], 15),
               "cc": countries[:15], "ti": re.sub(r"\s+", " ", tm.group(1)).strip() if tm else ""}


# ── AGGREGATE profile (NEWS-ALPHA-CORPUS-SLICE1): stream each 15-min file -> per (ingest hour, entity) counts ─
# The raw GKG stream is ~6.4 MB zipped per 15-min file (~0.68 TB for 2023-10..; ~1.7 TB for 2019..), so the raw
# corpus is NEVER persisted: each file is downloaded, folded into per-(hour, entity) sums with the FROZEN map
# research/news_alpha/entity_map_v1.json, and discarded. What is kept per UTC month under --out:
#   panel_YYYY-MM.csv.gz     hour, entity, n, n_dom, tone_sum, tone_sq, tone_min, tone_max, cls_<c>..., top_<t>...
#   coverage_YYYY-MM.csv.gz  hour, files_ok, files_missing, files_error, max_avail
#   manifest_YYYY-MM.json    counts + the entity map's sha256
# ``hour`` is the floor of the FILE stamp (= V2.1DATE ingest), so everything in it is available by hour+45min;
# a missing (404) or failed file is a GAP in coverage, never zero news (scripts/research/news_alpha_features.py
# turns any hour with files_ok < 4 into NaN). Re-running a month is incremental: hours already fully read are
# kept, everything else is re-fetched (a 404 is re-tried too; GDELT does have permanent gaps).
AGG_SCHEMA = "gdelt-gkg-hourly-panel-v1"
ENTITY_MAP = REPO / "research" / "news_alpha" / "entity_map_v1.json"


def load_entity_map(path: Path = ENTITY_MAP) -> Dict[str, Any]:
    raw = path.read_bytes()
    m = json.loads(raw)
    m["_sha256"] = hashlib.sha256(raw).hexdigest()
    m["_ent_re"] = {e: re.compile("|".join(ps)) for e, ps in m["entities"].items()}
    m["_any_re"] = re.compile("|".join(p for ps in m["entities"].values() for p in ps))
    m["_cls_re"] = {c: re.compile("|".join(ps)) for c, ps in m["event_classes"].items()}
    m["_top"] = {t: frozenset(ths) for t, ths in m["topics_by_theme"].items()}
    m["_coins"] = frozenset(e for e in m["entities"] if e != "CRYPTO")
    return m


def _url_words(url: str) -> str:
    from urllib.parse import urlparse
    try:
        path = urlparse(url).path
    except ValueError:
        return ""
    return re.sub(r"[-_/.+%0-9]+", " ", path).lower()


def _acc(bucket: Dict[str, Any], tone: Optional[float], domain: str) -> None:
    bucket["n"] = bucket.get("n", 0) + 1
    bucket.setdefault("_dom", set()).add(domain)
    if tone is not None:
        bucket["tone_sum"] = bucket.get("tone_sum", 0.0) + tone
        bucket["tone_sq"] = bucket.get("tone_sq", 0.0) + tone * tone
        bucket["tone_min"] = min(bucket.get("tone_min", tone), tone)
        bucket["tone_max"] = max(bucket.get("tone_max", tone), tone)
        bucket["n_tone"] = bucket.get("n_tone", 0) + 1


def aggregate_rows(fh: Iterable[str], emap: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fold one decoded GKG file into {entity: sums}. Pure; the map is the only matching policy."""
    out: Dict[str, Dict[str, Any]] = {}
    macro = emap["macro_entity"]
    for line in fh:
        r = line.rstrip("\r\n").split("\t")
        if len(r) < 27:
            continue
        domain = r[C_DOMAIN].lower()
        try:
            tone: Optional[float] = float(r[C_TONE].split(",")[0])
        except ValueError:
            tone = None
        mb = out.setdefault(macro, {})
        _acc(mb, tone, domain)
        themes = {t.split(",")[0] for t in r[C_THEMES].split(";") if t}
        for t, ths in emap["_top"].items():
            if themes & ths:
                mb[f"top_{t}"] = mb.get(f"top_{t}", 0) + 1
        tm = _TITLE_RE.search(r[C_EXTRAS])
        title = re.sub(r"\s+", " ", tm.group(1)).strip().lower() if tm else ""
        text = title + " " + _url_words(r[C_URL])
        if not emap["_any_re"].search(text):
            continue
        classes = [c for c, rx in emap["_cls_re"].items() if rx.search(text)]
        for ent, rx in emap["_ent_re"].items():
            if rx.search(text):
                b = out.setdefault(ent, {})
                _acc(b, tone, domain)
                if ent in emap["_coins"]:
                    for c in classes:
                        b[f"cls_{c}"] = b.get(f"cls_{c}", 0) + 1
    return out


def aggregate_one(ts: datetime, emap_path: str) -> Tuple[datetime, str, Dict[str, Dict[str, Any]], int]:
    """-> (ts, status, {entity: sums}, rows_scanned). status: ok | missing | error:<msg>."""
    emap = load_entity_map(Path(emap_path))
    url = GKG_URL.format(ts=ts.strftime("%Y%m%d%H%M%S"))
    try:
        blob = _download(url)
    except Exception as e:  # noqa: BLE001  # allow-silent: recorded as status error:<msg> in coverage, never counted ok
        return ts, f"error:{e}"[:200], {}, 0
    if blob is None:
        return ts, "missing", {}, 0
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            text = io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8", errors="replace")
            lines = list(text)
        return ts, "ok", aggregate_rows(lines, emap), len(lines)
    except Exception as e:  # noqa: BLE001  # allow-silent: recorded as status error:<msg> in coverage, never counted ok
        return ts, f"error:{e}"[:200], {}, 0


def _month_bounds(month: str) -> Tuple[datetime, datetime]:
    y, m = (int(x) for x in month.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


def _read_gz_csv(path: Path) -> List[Dict[str, str]]:
    import csv
    if not path.is_file():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_gz_csv(path: Path, cols: Sequence[str], rows: Iterable[Dict[str, Any]]) -> None:
    import csv
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    tmp.replace(path)


def aggregate_month(month: str, out: Path, *, workers: int = 8, now: Optional[datetime] = None,
                    emap_path: Path = ENTITY_MAP) -> Dict[str, Any]:
    emap = load_entity_map(emap_path)
    start, end = _month_bounds(month)
    now = now or datetime.now(timezone.utc)
    end = min(end, floor15(now - timedelta(minutes=30)) + STEP)
    out.mkdir(parents=True, exist_ok=True)
    ppath, cpath = out / f"panel_{month}.csv.gz", out / f"coverage_{month}.csv.gz"
    cov_prev = {r["hour"]: r for r in _read_gz_csv(cpath)}
    done_hours = {h for h, r in cov_prev.items() if int(r["files_ok"]) == 4}
    files = [f for f in files_in_range(start, end - timedelta(seconds=1))
             if iso_z(f.replace(minute=0)) not in done_hours]
    print(f"{month}: {len(files)} file(s) to fetch, {len(done_hours)} hour(s) already complete")
    hours: Dict[str, Dict[str, Any]] = {}
    agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    scanned = 0
    if workers <= 1:   # in-process (tests; a tiny month)
        results: Iterable[Any] = (aggregate_one(f, str(emap_path)) for f in files)
        ex = None
    else:
        ex = ProcessPoolExecutor(max_workers=workers)
        results = (fu.result() for fu in as_completed([ex.submit(aggregate_one, f, str(emap_path)) for f in files]))
    try:
        for k, (ts, status, ents, nrows) in enumerate(results, 1):
            h = iso_z(ts.replace(minute=0))
            c = hours.setdefault(h, {"hour": h, "files_ok": 0, "files_missing": 0, "files_error": 0, "max_avail": ""})
            if status == "ok":
                c["files_ok"] += 1
                c["max_avail"] = max(c["max_avail"], iso_z(ts))
                scanned += nrows
                for ent, b in ents.items():
                    a = agg.setdefault((h, ent), {})
                    for key, v in b.items():
                        if key == "_dom":
                            a.setdefault("_dom", set()).update(v)
                        elif key == "tone_min":
                            a[key] = min(a.get(key, v), v)
                        elif key == "tone_max":
                            a[key] = max(a.get(key, v), v)
                        else:
                            a[key] = a.get(key, 0) + v
            elif status == "missing":
                c["files_missing"] += 1
            else:
                c["files_error"] += 1
            if k % 200 == 0:
                print(f"  {month}: {k}/{len(files)}", flush=True)
    finally:
        if ex is not None:
            ex.shutdown()
    cls_cols = [f"cls_{c}" for c in emap["event_classes"]]
    top_cols = [f"top_{t}" for t in emap["topics_by_theme"]]
    cols = ["hour", "entity", "n", "n_dom", "n_tone", "tone_sum", "tone_sq", "tone_min", "tone_max"] + cls_cols + top_cols
    new_rows = []
    for (h, ent), a in agg.items():
        r = {k: v for k, v in a.items() if k != "_dom"}
        r.update({"hour": h, "entity": ent, "n_dom": len(a.get("_dom", ()))})
        for k in ("tone_sum", "tone_sq", "tone_min", "tone_max"):
            if k in r:
                r[k] = round(r[k], 4)
        new_rows.append(r)
    kept = [r for r in _read_gz_csv(ppath) if r["hour"] in done_hours]
    rows = sorted(kept + new_rows, key=lambda r: (r["hour"], r["entity"]))
    cov = dict(cov_prev)
    cov.update(hours)
    cov_rows = [cov[h] for h in sorted(cov)]
    _write_gz_csv(ppath, cols, rows)
    _write_gz_csv(cpath, ["hour", "files_ok", "files_missing", "files_error", "max_avail"], cov_rows)
    man = {
        "schema": AGG_SCHEMA, "month": month, "generated_at": iso_z(now),
        "source": "GDELT 2.0 GKG 15-min files (https://data.gdeltproject.org/gdeltv2/)",
        "entity_map": str(emap_path.relative_to(REPO)) if emap_path.is_relative_to(REPO) else str(emap_path),
        "entity_map_sha256": emap["_sha256"],
        "hours": len(cov_rows),
        "hours_complete": sum(1 for r in cov_rows if int(r["files_ok"]) == 4),
        "files_ok": sum(int(r["files_ok"]) for r in cov_rows),
        "files_missing": sum(int(r["files_missing"]) for r in cov_rows),
        "files_error": sum(int(r["files_error"]) for r in cov_rows),
        "rows_scanned_this_run": scanned, "panel_rows": len(rows),
        "availability_rule": "hour = floor(GKG file stamp = V2.1DATE ingest); max_avail = latest ok stamp in the hour",
        "note": "files_ok < 4 marks an hour as NOT fully read: features over it are NaN, never zero news",
    }
    (out / f"manifest_{month}.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(man, indent=2))
    return man


def months_status(out: Path, first: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every month first..now with whether its coverage is FINAL (every past file read ok or 404)."""
    now = now or datetime.now(timezone.utc)
    y, m = (int(x) for x in first.split("-"))
    res = []
    while (y, m) <= (now.year, now.month):
        month = f"{y:04d}-{m:02d}"
        start, end = _month_bounds(month)
        cov = _read_gz_csv(out / f"coverage_{month}.csv.gz")
        expect = int((min(end, now) - start).total_seconds() // 3600)
        final_hours = sum(1 for r in cov if int(r["files_ok"]) + int(r["files_missing"]) >= 4)
        res.append({"month": month, "hours_expected": expect, "hours_final": final_hours,
                    "complete": end <= now and final_hours >= expect, "current": end > now})
        y, m = (y + (m == 12), m % 12 + 1)
    return res


def floor15(dt: datetime) -> datetime:
    return dt.replace(minute=dt.minute - dt.minute % 15, second=0, microsecond=0)


def files_in_range(start: datetime, end: datetime, stride: int = 1) -> List[datetime]:
    t = max(floor15(start), GKG_FIRST)
    out: List[datetime] = []
    i = 0
    while t <= end:
        if i % max(1, stride) == 0:
            out.append(t)
        t += STEP
        i += 1
    return out


def _read_times(path: Path) -> List[datetime]:
    txt = path.read_text(encoding="utf-8").strip()
    rows = json.loads(txt) if txt.startswith("[") else [json.loads(ln) for ln in txt.splitlines() if ln.strip()]
    out = []
    for r in rows:
        v = r.get("entry_time") if isinstance(r, dict) else r
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        out.append(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
    return out


def files_for_signals(times: Sequence[datetime], max_age_min: float, slack_min: float) -> List[datetime]:
    """Union of files stamped in [t - (max_age+slack), t) for every signal time t."""
    need: Set[datetime] = set()
    back = timedelta(minutes=max_age_min + slack_min)
    for t in times:
        f = floor15(t - back)
        while f < t:
            if f >= GKG_FIRST:
                need.add(f)
            f += STEP
    return sorted(need)


def _download(url: str, tries: int = 4) -> Optional[bytes]:
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # noqa: BLE001  # allow-silent: recorded as status error:<msg> in the ledger, never counted ok
            err = e
        time.sleep(2 ** (k + 1))
    raise RuntimeError(f"download failed {url}: {err}")


def fetch_one(ts: datetime, domains: Optional[Set[str]], keywords: Sequence[str], archive: bool = False) -> Tuple[datetime, str, List[Dict[str, Any]], int]:
    """-> (ts, status, items, rows_scanned). status: ok | missing | error:<msg>."""
    url = GKG_URL.format(ts=ts.strftime("%Y%m%d%H%M%S"))
    try:
        blob = _download(url)
    except Exception as e:  # noqa: BLE001  # allow-silent: recorded as status error:<msg> in the ledger, never counted ok
        return ts, f"error:{e}"[:200], [], 0
    if blob is None:
        return ts, "missing", [], 0
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = z.namelist()[0]
            text = io.TextIOWrapper(z.open(name), encoding="utf-8", errors="replace")
            n = 0

            def counted(f):
                nonlocal n
                for line in f:
                    n += 1
                    yield line

            items = (list(archive_rows(counted(text))) if archive else
                     list(parse_gkg_rows(counted(text), domains=domains, keywords=keywords)))
    except Exception as e:  # noqa: BLE001  # allow-silent: recorded as status error:<msg> in the ledger, never counted ok
        return ts, f"error:{e}"[:200], [], 0
    return ts, "ok", items, n


def shard_path(out: Path, avail_iso: str) -> Path:
    d = avail_iso[:10]
    return out / d[:4] / d[5:7] / f"{d}.jsonl"


def load_ledger(out: Path) -> Dict[str, Dict[str, Any]]:
    p = out / "_ledger.jsonl"
    led: Dict[str, Dict[str, Any]] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                led[r["file"]] = r
    return led


def build_manifest(out: Path, domains: Optional[Set[str]], keywords: Sequence[str], archive: bool = False) -> Dict[str, Any]:
    led = load_ledger(out)
    ok = [r for r in led.values() if r["status"] == "ok"]
    ts = sorted(led)
    return {
        "source": "GDELT 2.0 GKG (https://data.gdeltproject.org/gdeltv2/)",
        "schema": ARCHIVE_SCHEMA if archive else "raw normalizer-shaped article + available_at + pub_basis",
        "profile": "archive" if archive else "replay-slice",
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "files_listed": len(led),
        "files_ok": len(ok),
        "files_missing": sum(1 for r in led.values() if r["status"] == "missing"),
        "files_error": sum(1 for r in led.values() if r["status"].startswith("error")),
        "rows_scanned": sum(r.get("rows", 0) for r in ok),
        "items_kept": sum(r.get("kept", 0) for r in ok),
        "first_file": ts[0] if ts else None,
        "last_file": ts[-1] if ts else None,
        "domain_allowlist": sorted(domains) if domains is not None else "ALL",
        "live_feed_domains": sorted(feed_domain_allowlist()),
        "n_keywords": len(keywords),
        "availability_rule": "available_at = GDELT ingest time (V2.1DATE); replay requires available_at < signal_ts",
        "note": "gaps (missing/error files) are listed in _ledger.jsonl; absence of items in a window with a gap is NOT evidence of no news",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="corpus root (OFF-REPO, e.g. trainer data dir)")
    ap.add_argument("--start", help="YYYY-MM-DD[THH:MM] UTC")
    ap.add_argument("--end", help="YYYY-MM-DD[THH:MM] UTC")
    ap.add_argument("--stride", type=int, default=1, help="take every Nth 15-min file (coverage trade-off)")
    ap.add_argument("--signal-times", help="trades JSON/JSONL with entry_time: fetch only the windows that can influence them")
    ap.add_argument("--max-age-min", type=float, default=120.0, help="live NEWS_MAX_AGE_MINUTES")
    ap.add_argument("--slack-min", type=float, default=15.0)
    ap.add_argument("--sources", choices=["live", "broad", "all"], default="live",
                    help="live = domains of the LIVE feed config; broad = live + BROAD_DOMAINS (superset: the replay "
                         "filters back down to live per symbol); all = no domain filter")
    ap.add_argument("--archive", action="store_true",
                    help="ARCHIVE profile: every row, compact tone/theme/entity metadata, gz shards (no keyword/domain filter)")
    ap.add_argument("--workers", type=int, default=12, help="processes (download + parse are CPU-heavy)")
    ap.add_argument("--aggregate", metavar="YYYY-MM", default=None,
                    help="AGGREGATE profile: fold one UTC month into panel/coverage/manifest files under --out "
                         "(NEWS-ALPHA-CORPUS-SLICE1); the raw files are never kept")
    ap.add_argument("--plan-months", metavar="YYYY-MM", default=None,
                    help="print JSON: every month from this one to now with its coverage state under --out")
    ap.add_argument("--manifest", help="write manifest JSON here (commit this, not the data)")
    ap.add_argument("--dry-run", action="store_true", help="list how many files would be fetched")
    a = ap.parse_args(argv)

    out = Path(a.out)
    if a.plan_months:
        print(json.dumps(months_status(out, a.plan_months)))
        return 0
    if a.aggregate:
        aggregate_month(a.aggregate, out, workers=a.workers)
        return 0
    domains = (None if a.sources == "all" else
               feed_domain_allowlist() | (BROAD_DOMAINS if a.sources == "broad" else frozenset()))
    kws = relevance_keywords()

    if a.signal_times:
        files = files_for_signals(_read_times(Path(a.signal_times)), a.max_age_min, a.slack_min)
    elif a.start and a.end:
        def p(s):
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        files = files_in_range(p(a.start), p(a.end), a.stride)
    else:
        ap.error("give --signal-times, or --start and --end")

    led = load_ledger(out)
    todo = [f for f in files if led.get(f.strftime("%Y%m%d%H%M%S"), {}).get("status") != "ok"]
    print(f"files wanted={len(files)} already_ok={len(files) - len(todo)} todo={len(todo)} "
          f"domains={'ALL' if domains is None else len(domains)} keywords={len(kws)}")
    if a.dry_run:
        return 0
    out.mkdir(parents=True, exist_ok=True)

    done = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex, open(out / "_ledger.jsonl", "a", encoding="utf-8") as lf:
        futs = [ex.submit(fetch_one, f, domains, kws, a.archive) for f in todo]
        for fu in as_completed(futs):
            ts, status, items, nrows = fu.result()
            by_shard: Dict[Path, List[str]] = {}
            for it in items:
                sp = shard_path(out, it["a" if a.archive else "available_at"])
                if a.archive:
                    sp = sp.with_suffix(".jsonl.gz")
                by_shard.setdefault(sp, []).append(json.dumps(it, ensure_ascii=False, separators=(",", ":")))
            for sp, lines in by_shard.items():
                sp.parent.mkdir(parents=True, exist_ok=True)
                if a.archive:  # concatenated gzip members are one valid stream
                    with gzip.open(sp, "at", encoding="utf-8") as sf:
                        sf.write("\n".join(lines) + "\n")
                else:
                    with open(sp, "a", encoding="utf-8") as sf:
                        sf.write("\n".join(lines) + "\n")
            lf.write(json.dumps({"file": ts.strftime("%Y%m%d%H%M%S"), "status": status,
                                 "rows": nrows, "kept": len(items)}) + "\n")
            lf.flush()
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}", flush=True)
    man = build_manifest(out, domains, kws, a.archive)
    print(json.dumps(man, indent=2))
    if a.manifest:
        Path(a.manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(a.manifest).write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

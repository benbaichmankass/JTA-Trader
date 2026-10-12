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
    rows = json.loads(txt) if txt.startswith("[") else [json.loads(l) for l in txt.splitlines() if l.strip()]
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
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(2 ** (k + 1))
    raise RuntimeError(f"download failed {url}: {err}")


def fetch_one(ts: datetime, domains: Optional[Set[str]], keywords: Sequence[str]) -> Tuple[datetime, str, List[Dict[str, Any]], int]:
    """-> (ts, status, items, rows_scanned). status: ok | missing | error:<msg>."""
    url = GKG_URL.format(ts=ts.strftime("%Y%m%d%H%M%S"))
    try:
        blob = _download(url)
    except Exception as e:  # noqa: BLE001
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

            items = list(parse_gkg_rows(counted(text), domains=domains, keywords=keywords))
    except Exception as e:  # noqa: BLE001
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


def build_manifest(out: Path, domains: Optional[Set[str]], keywords: Sequence[str]) -> Dict[str, Any]:
    led = load_ledger(out)
    ok = [r for r in led.values() if r["status"] == "ok"]
    ts = sorted(led)
    return {
        "source": "GDELT 2.0 GKG (https://data.gdeltproject.org/gdeltv2/)",
        "schema": "raw normalizer-shaped article + available_at + pub_basis",
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
    ap.add_argument("--workers", type=int, default=12, help="processes (download + parse are CPU-heavy)")
    ap.add_argument("--manifest", help="write manifest JSON here (commit this, not the data)")
    ap.add_argument("--dry-run", action="store_true", help="list how many files would be fetched")
    a = ap.parse_args(argv)

    out = Path(a.out)
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
        futs = [ex.submit(fetch_one, f, domains, kws) for f in todo]
        for fu in as_completed(futs):
            ts, status, items, nrows = fu.result()
            by_shard: Dict[Path, List[str]] = {}
            for it in items:
                by_shard.setdefault(shard_path(out, it["available_at"]), []).append(json.dumps(it, ensure_ascii=False))
            for sp, lines in by_shard.items():
                sp.parent.mkdir(parents=True, exist_ok=True)
                with open(sp, "a", encoding="utf-8") as sf:
                    sf.write("\n".join(lines) + "\n")
            lf.write(json.dumps({"file": ts.strftime("%Y%m%d%H%M%S"), "status": status,
                                 "rows": nrows, "kept": len(items)}) + "\n")
            lf.flush()
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}", flush=True)
    man = build_manifest(out, domains, kws)
    print(json.dumps(man, indent=2))
    if a.manifest:
        Path(a.manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(a.manifest).write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

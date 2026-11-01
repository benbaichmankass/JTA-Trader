#!/usr/bin/env python3
# wiring: manual-only - regenerates config/data_universe/sp500_membership.csv (committed); the ETF history pipeline reads that file. Re-run quarterly.
"""Build the point-in-time S&P 500 membership table the equity-bar pipeline reads.

SOURCE: github.com/fja05680/sp500 "S&P 500 Historical Components & Changes (Updated)" (daily constituent snapshots since 1996, merged with the maintainer's post-2019 change list;
symbols are as listed on each date; a ticker later reused by another company is NOT disambiguated). Keyless.
OUTPUT ``config/data_universe/sp500_membership.csv``: one row per (member_symbol) interval since ``--since`` (default
2016-01-04, the start of Alpaca bar history): ``member_symbol, symbol, first_in, last_in, still_member``.
  * ``symbol``      = the ticker to request bars for (suffix stripped).
  * ``still_member``= present in the newest snapshot.
  * Delisted names are KEPT (survivorship bias is the point of keeping them); whether a data vendor still serves their
    bars is MEASURED by the fetcher and recorded in the manifest (``no_data``), never assumed here.
Membership dates are the source's snapshot dates, not S&P's announcement dates (<= a few days of lag): use
``first_in``/``last_in`` for universe selection as-of a date, not as an event timestamp.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

URL = "https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
_SUFFIX = re.compile(r"^(.*?)-(\d{6})$")


def build(text: str, since: str):
    rows = list(csv.DictReader(io.StringIO(text)))
    rows = [r for r in rows if r["date"] >= since] or rows[-1:]
    # include the snapshot in force at `since` (the last one before it) so a name already in the index on day 1 is not dropped
    seen: dict = {}
    for r in rows:
        for t in r["tickers"].split(","):
            t = t.strip()
            if not t:
                continue
            d = r["date"]
            if t not in seen:
                seen[t] = [d, d]
            else:
                seen[t][1] = d
    newest = rows[-1]["date"]
    out = []
    for member, (first, last) in sorted(seen.items()):
        m = _SUFFIX.match(member)
        out.append({"member_symbol": member, "symbol": m.group(1) if m else member, "first_in": first, "last_in": last,
                    "still_member": str(last == newest).lower()})
    return out, newest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2016-01-04")
    ap.add_argument("--out", default="config/data_universe/sp500_membership.csv")
    ap.add_argument("--from-file", help="read the source CSV from a file instead of the network (tests)")
    a = ap.parse_args(argv)
    if a.from_file:
        text = Path(a.from_file).read_text()
    else:
        import requests
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
        text = r.text
    out, newest = build(text, a.since)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["member_symbol", "symbol", "first_in", "last_in", "still_member"])
        w.writeheader()
        w.writerows(out)
    cur = sum(1 for o in out if o["still_member"] == "true")
    print(f"wrote {a.out}: {len(out)} member-symbols since {a.since}; newest snapshot {newest}; still members {cur}; "
          f"delisted/removed {len(out) - cur}; distinct request symbols {len({o['symbol'] for o in out})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

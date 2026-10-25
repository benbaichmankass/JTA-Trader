"""Tests for the NEWS-ALPHA-CORPUS-SLICE1 aggregate-on-ingest panel (scripts/research/news_hist_fetch.py --aggregate).

Synthetic GKG 2.1 rows with a known answer: entity matching through the FROZEN map, topic counts on MACRO,
event classes only on coin entities, missing files recorded as coverage gaps (never zero news), incremental
re-runs keep complete hours and retry the rest, and the produced panel feeds news_alpha_features.
"""
from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from scripts.research import news_alpha_features as naf
from scripts.research import news_hist_fetch as nhf


def _row(ts: str, url: str, title: str, tone: float, themes: str = "", domain: str = "example.com") -> str:
    r = [""] * 27
    r[0], r[1], r[3], r[4] = "x", ts, domain, url
    r[7] = themes
    r[15] = f"{tone},1,2,3,4,5,600"
    r[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(r) + "\n"


def test_aggregate_rows_uses_the_frozen_map():
    emap = nhf.load_entity_map()
    lines = [
        _row("20240301000000", "https://a.com/markets/bitcoin-etf-flows", "Bitcoin ETF sees record inflows", 2.0,
             "ECON_BITCOIN,1;ECON_INFLATION,5", "a.com"),
        _row("20240301000000", "https://b.com/x", "Solana network hacked, funds drained", -6.0, "", "b.com"),
        _row("20240301000000", "https://c.com/y", "DOGE cuts federal jobs", -1.0, "ARMEDCONFLICT,3", "c.com"),
        _row("20240301000000", "https://d.com/z", "Ripple effect of rate cuts", 0.5, "ECON_CENTRALBANK,2", "d.com"),
    ]
    out = nhf.aggregate_rows(lines, emap)
    assert out["MACRO"]["n"] == 4 and len(out["MACRO"]["_dom"]) == 4
    assert out["MACRO"]["top_inflation"] == 1 and out["MACRO"]["top_conflict"] == 1
    assert out["MACRO"]["top_central_bank"] == 1
    assert out["BTC"]["n"] == 1 and out["BTC"]["cls_listing_etf"] == 1
    assert out["SOL"]["cls_hack_exploit"] == 1 and out["SOL"]["tone_sum"] == -6.0
    assert "DOGE" not in out           # the Department of Government Efficiency is not dogecoin
    assert "XRP" not in out            # "ripple effect" is not Ripple


def _zip_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("f.gkg.csv", text)
    return buf.getvalue()


def test_aggregate_month_gaps_and_incremental(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, tries=4):
        calls.append(url)
        stamp = url.rsplit("/", 1)[1][:14]
        if stamp == "20240301011500":
            return None                                  # a GDELT 404: a gap, not zero news
        return _zip_bytes(_row(stamp, "https://a.com/bitcoin-news", "Bitcoin rallies", 1.0, "", "a.com"))

    monkeypatch.setattr(nhf, "_download", fake_download)
    now = datetime(2024, 3, 1, 2, 30, tzinfo=timezone.utc)      # files 00:00 .. 01:45 + 02:00
    man = nhf.aggregate_month("2024-03", tmp_path, workers=1, now=now)
    assert man["files_missing"] == 1 and man["hours_complete"] == 1
    cov = pd.read_csv(tmp_path / "coverage_2024-03.csv.gz")
    assert list(cov["files_ok"]) == [4, 3, 1]
    panel = pd.read_csv(tmp_path / "panel_2024-03.csv.gz")
    btc = panel[panel["entity"] == "BTC"].set_index("hour")
    assert btc.loc["2024-03-01T00:00:00Z", "n"] == 4 and btc.loc["2024-03-01T01:00:00Z", "n"] == 3
    # re-run later: the complete hour is NOT re-fetched; the gap and the partial hour are
    calls.clear()
    nhf.aggregate_month("2024-03", tmp_path, workers=1, now=datetime(2024, 3, 1, 3, 30, tzinfo=timezone.utc))
    assert not any("20240301000000" in u or "20240301004500" in u for u in calls)
    assert any("20240301011500" in u for u in calls)
    cov = pd.read_csv(tmp_path / "coverage_2024-03.csv.gz")
    assert list(cov["files_ok"]) == [4, 3, 4, 1]          # 01:15 is still a 404; 03:00 is the only 03h file yet
    panel = pd.read_csv(tmp_path / "panel_2024-03.csv.gz")
    assert panel[(panel["entity"] == "BTC") & (panel["hour"] == "2024-03-01T00:00:00Z")]["n"].tolist() == [4]
    m = json.loads((tmp_path / "manifest_2024-03.json").read_text())
    assert m["entity_map_sha256"] == nhf.load_entity_map()["_sha256"]
    # the panel feeds the feature builder; the 01:00 hour (3 of 4 files) is NaN downstream, never zero
    p, c = naf.load_panel(tmp_path)
    dense = naf.entity_hourly(p, c, "BTC")
    assert pd.isna(dense.loc[pd.Timestamp("2024-03-01 01:00", tz="UTC"), "n"])
    assert dense.loc[pd.Timestamp("2024-03-01 00:00", tz="UTC"), "n"] == 4


def test_months_status(tmp_path):
    with gzip.open(tmp_path / "coverage_2023-10.csv.gz", "wt") as fh:
        fh.write("hour,files_ok,files_missing,files_error,max_avail\n")
        for h in pd.date_range("2023-10-01", "2023-10-31 23:00", freq="1h", tz="UTC"):
            fh.write(f"{h.strftime('%Y-%m-%dT%H:%M:%SZ')},4,0,0,x\n")
    st = nhf.months_status(tmp_path, "2023-10", now=datetime(2023, 12, 5, tzinfo=timezone.utc))
    assert [s["month"] for s in st] == ["2023-10", "2023-11", "2023-12"]
    assert st[0]["complete"] and not st[1]["complete"] and st[2]["current"]

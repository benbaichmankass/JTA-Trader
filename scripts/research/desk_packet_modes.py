#!/usr/bin/env python3
# wiring: manual-only - imported by scripts/research/desk_gen_replay_driver.py (build_masked_packet mode=B|C) and run by lane DESK-PACKET-REDESIGN (scripts/research/desk_packet_arms.py); no schedule consumes it.
"""DESK-PACKET-REDESIGN -- packet builder modes B and C for the desk entry-generation replay.

Mode A is today's masked scan packet (scripts/ops/desk_scan_packet.py via desk_gen_replay_driver.build_masked_packet):
summaries only (ATR, swing distances, htf_trend, session) plus the net-of-cost forward-R BASE-RATE rows (`history`,
mirrored as `*.mean_r` keys in `features_at_review`). Lane DESK-EDGE-PROGRAM measured that the judge's cell scores are
a linear function of those base-rate rows (R^2 0.90-1.00), so this module builds two alternatives on the SAME packet
(same packet_id, same aliases, same price rebasing, so the same mask key scores all three):

  B  -- A with every base-rate / history quantity REMOVED (history, features_at_review *.mean_r). Nothing else changes.
  C  -- RAW data only: no summaries, no precomputed statistics. Per alias, multi-timeframe OHLC bars before the cutoff
        (1m, 5m, 1h, 4h, 1d) with relative volume and taker-buy share, plus the funding prints known at the cutoff.
        Kept from A, because the scored bracket and the masking need them: the alias, the 1h ATR(14) (the bracket is
        defined in it), the session label, and the rebasing (last 1h close = 100). Nothing at or after the cutoff.

STATED LIMITS
* Bars are Binance Vision USD-M PERP 1m klines (taker-buy volume included) for the six USDT symbols, aggregated here
  (the replay engine's own 1h candles are USD-M perp too: fetch_backtest_candles.py --source binance_vision); the
  1h path is checked against the replay's own 1h series (`check_against_1h`). Funding is Binance USD-M perp funding.
* No equity index: a calendar-hours series (weekend gaps) would un-mask the calendar the packet withholds. The
  cross-asset context is the six aliased series themselves (BTC and ETH are among them, aliased, as in A).
* No news: the replay's packet history has no point-in-time news text (`news: could_not_look`).
* Volume is shown RELATIVE (100 = the median bar of that table), never absolute: absolute volume identifies a symbol.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

MODES = ("A", "B", "C")
VISION = "https://data.binance.vision/data"
# rows per alias in mode C, by timeframe (oldest first): 30 min of 1m, 4 h of 5m, 2 days of 1h, 5 days of 4h, 20 days of 1d.
# Amendment 1 (2026-10-27, before any further C judging): the registered 90/96/96/60/30 rows measured ~50k tokens per
# packet in the first judge batch (numbers tokenise near 1 token per char), which priced 100 packets at ~$39 and the
# judge skipped analysing 4 of 5 packets. Cut to 176 rows per alias, and the open column is dropped (o = previous c).
RAW_TABLES: Tuple[Tuple[str, int, int], ...] = (("1m", 60, 30), ("5m", 300, 48), ("1h", 3600, 48), ("4h", 14400, 30), ("1d", 86400, 20))
FUNDING_PRINTS = 9          # the last 9 funding prints (3 days at 8h) known at the cutoff
RAW_SCHEMA = "desk-raw-v1"


# ----------------------------------------------------------------------------- mode B
def strip_base_rates(packet: dict) -> dict:
    """Mode B: the A packet with every base-rate / forward-R history quantity removed. Pure; the input is not mutated."""
    p = deepcopy(packet)
    p.pop("history", None)
    far = p.get("features_at_review")
    if isinstance(far, dict):
        p["features_at_review"] = {k: v for k, v in far.items() if not k.endswith("_r")}
    p.setdefault("meta", {})["packet_mode"] = "B"
    p["meta"].setdefault("missing_inputs", []).append("history: removed by packet mode B (no base-rate rows)")
    return p


def base_rate_keys_left(packet: dict) -> List[str]:
    """Every remaining key path that carries a base-rate quantity; [] for a correct mode-B / mode-C packet."""
    out = []
    if "history" in packet:
        out.append("history")
    for k in (packet.get("features_at_review") or {}):
        if k.endswith("_r"):
            out.append(f"features_at_review.{k}")
    txt = json.dumps(packet)
    for tok in ("mean_r", "p50_r", "p90_r", "p10_r", "sd_r", "mean_cost_r"):
        if tok in txt and not out:
            out.append(f"token {tok}")
    return out


# ----------------------------------------------------------------------------- raw data (mode C)
@dataclass
class Raw1m:
    """One symbol's 1m USD-M perp klines as arrays (open epoch seconds), with taker-buy base volume."""
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    v: np.ndarray
    tb: np.ndarray

    def upto(self, cutoff_epoch: int) -> "Raw1m":
        """Bars whose CLOSE (open + 60 s) is <= the cutoff: the point-in-time view."""
        n = int(np.searchsorted(self.t + 60, cutoff_epoch, side="right"))
        return Raw1m(*(a[:n] for a in (self.t, self.o, self.h, self.l, self.c, self.v, self.tb)))


@dataclass
class RawStore:
    bars: Dict[str, Raw1m]                       # real symbol -> 1m
    funding: Dict[str, np.ndarray]               # real symbol -> [[epoch_s, rate], ...] sorted


def _get(url: str) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except (urllib.error.URLError, OSError):   # HTTPError (404: month not published) is a URLError; the caller names it
        return None


def _rows(blob: bytes) -> List[List[str]]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))))


def fetch_raw(dest: Path, symbols: Sequence[str], months: Sequence[str]) -> List[str]:
    """Download (cached) 1m USD-M perp klines and USD-M funding for `months` (YYYY-MM). Returns the missing (symbol, month)s."""
    dest.mkdir(parents=True, exist_ok=True)
    missing = []
    for s in symbols:
        for m in months:
            kf, ff = dest / f"{s}_1m_{m}.npy", dest / f"{s}_funding_{m}.npy"
            if not kf.exists():
                blob = _get(f"{VISION}/futures/um/monthly/klines/{s}/1m/{s}-1m-{m}.zip")
                if blob is None:
                    missing.append(f"{s}:1m:{m}")
                else:
                    rows = [r for r in _rows(blob) if r and r[0].isdigit()]
                    a = np.array([[float(x) for x in (r[0], r[1], r[2], r[3], r[4], r[5], r[9])] for r in rows])
                    a[:, 0] = np.where(a[:, 0] > 1e14, a[:, 0] / 1e6, a[:, 0] / 1e3)   # vision: us from 2025, ms before
                    np.save(kf, a)
            if not ff.exists():
                blob = _get(f"{VISION}/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip")
                if blob is None:
                    missing.append(f"{s}:funding:{m}")
                else:
                    rows = [r for r in _rows(blob) if r and r[0].isdigit()]
                    np.save(ff, np.array([[float(r[0]) / 1e3, float(r[2])] for r in rows]))
    return missing


def load_raw(src: Path, symbols: Sequence[str]) -> RawStore:
    bars, fund = {}, {}
    for s in symbols:
        ks = sorted(src.glob(f"{s}_1m_*.npy"))
        fs = sorted(src.glob(f"{s}_funding_*.npy"))
        if not ks:
            raise FileNotFoundError(f"no 1m klines for {s} under {src}")
        a = np.concatenate([np.load(k) for k in ks])
        a = a[np.argsort(a[:, 0], kind="stable")]
        bars[s] = Raw1m(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], a[:, 6])
        f = np.concatenate([np.load(x) for x in fs]) if fs else np.zeros((0, 2))
        fund[s] = f[np.argsort(f[:, 0], kind="stable")] if len(f) else f
    return RawStore(bars, fund)


def aggregate(b: Raw1m, sec: int, cutoff_epoch: int, n: int) -> np.ndarray:
    """The last n CLOSED bars of width `sec`, aligned to epoch multiples, ending at or before the cutoff, built from the
    1m bars only. Rows [open_epoch, o, h, l, c, v, tb]; a bucket with no 1m bar is dropped (counted by the caller)."""
    p = b.upto(cutoff_epoch)
    if not len(p.t):
        return np.zeros((0, 7))
    last_close = (cutoff_epoch // sec) * sec               # the newest bucket that has CLOSED by the cutoff
    lo = last_close - n * sec
    m = (p.t >= lo) & (p.t < last_close)
    t, o, h, l, c, v, tb = (a[m] for a in (p.t, p.o, p.h, p.l, p.c, p.v, p.tb))  # noqa: E741
    if not len(t):
        return np.zeros((0, 7))
    k = (t // sec) * sec
    keys, start = np.unique(k, return_index=True)
    end = np.r_[start[1:], len(k)]
    out = np.array([[keys[j], o[start[j]], h[start[j]:end[j]].max(), l[start[j]:end[j]].min(), c[end[j] - 1],
                     v[start[j]:end[j]].sum(), tb[start[j]:end[j]].sum()] for j in range(len(keys))])
    return out


def raw_packet(packet_a: dict, key: dict, raw: RawStore, tables: Sequence[Tuple[str, int, int]] = RAW_TABLES) -> dict:
    """Mode C from the A packet and its key: per alias, the bar tables (prices in bps from the last 1h close = 100,
    i.e. rebased price = 100 x (1 + bps/10000)), relative volume and taker-buy share, and the funding prints known at
    the cutoff. Keeps packet_id, the alias, the 1h ATR (rebased) and the session label from A; nothing else."""
    ce = int(key["cutoff_epoch"])
    uni = {u["symbol"]: u for u in packet_a["universe"]}
    assets = {}
    gaps = []
    for alias in sorted(uni):
        sym = key["alias"][alias]
        scale = float(key["price_scale"][alias])
        b = raw.bars[sym]
        ref = 100.0 / scale                                # the real last 1h close the A packet rebased to 100
        tabs = {}
        for name, sec, n in tables:
            a = aggregate(b, sec, ce, n)
            if len(a) < n:
                gaps.append(f"{alias}.{name}: {len(a)} of {n} bars")
            med = float(np.median(a[:, 5])) if len(a) else 0.0
            rows = []
            for r in a:
                bps = [int(round((x / ref - 1.0) * 1e4)) for x in r[2:5]]       # h, l, c (o is the previous c)
                rv = int(round(100 * r[5] / med)) if med > 0 else None
                tbs = int(round(100 * r[6] / r[5])) if r[5] > 0 else None
                rows.append(bps + [rv, tbs])
            tabs[name] = rows
        f = raw.funding.get(sym)
        fp = [] if f is None or not len(f) else [round(float(x) * 1e4, 2) for x in f[f[:, 0] <= ce][-FUNDING_PRINTS:, 1]]
        assets[alias] = {"atr_1h": uni[alias]["atr"], "session": uni[alias].get("session"),
                         "funding_bps_per_8h": fp, "bars": tabs}
    return {"schema": RAW_SCHEMA, "packet_id": packet_a["meta"]["packet_id"], "packet_mode": "C",
            "columns": ["h_bps", "l_bps", "c_bps", "rel_volume", "taker_buy_pct"],
            "tables": [[nm, n] for nm, _, n in tables], "gaps": gaps, "news": "could_not_look", "assets": assets}


def check_against_1h(c_packet: dict, packet_a_close_bps_last: float = 0.0) -> List[str]:
    """Mode C's own consistency check: every alias's newest 1h close is the A packet's rebased last close (0 bps,
    tolerance 1 bps: the 1m-built 1h bar must equal the replay's 1h bar). [] = consistent."""
    out = []
    for alias, a in c_packet["assets"].items():
        h = a["bars"].get("1h") or []
        if not h:
            out.append(f"{alias}: no 1h bars")
        elif abs(h[-1][2] - packet_a_close_bps_last) > 1:
            out.append(f"{alias}: newest 1h close {h[-1][2]} bps, expected 0")
    return out


def render_raw_text(c: dict) -> str:
    """The judge-facing text of a mode-C packet: compact space-separated tables, oldest row first."""
    lines = [f"### PACKET {c['packet_id']}  (mode C, {c['schema']})",
             "Prices: bps from the alias's last 1h close (rebased price = 100 x (1 + bps/10000)). Rows oldest -> newest; "
             "the last row of each table is the last CLOSED bar before the decision. Columns: o h l c (bps) rel_vol "
             "(100 = median bar of that table) taker_buy_pct.", f"news: {c['news']}"]
    if c["gaps"]:
        lines.append("gaps: " + "; ".join(c["gaps"]))
    for alias, a in c["assets"].items():
        lines.append(f"\n## {alias}  atr_1h={a['atr_1h']}  session={a['session']}  "
                     f"funding_bps_per_8h(oldest->newest)={a['funding_bps_per_8h']}")
        for name, rows in a["bars"].items():
            lines.append(f"[{name}] " + str(len(rows)))
            lines.extend(" ".join("-" if x is None else str(x) for x in r) for r in rows)
    return "\n".join(lines) + "\n"


def apply(mode: str, packet_a: dict, key: dict, raw: Optional[RawStore] = None) -> dict:
    """The builder-mode switch desk_gen_replay_driver.build_masked_packet calls. A returns the packet unchanged."""
    if mode == "A":
        return packet_a
    if mode == "B":
        return strip_base_rates(packet_a)
    if mode == "C":
        if raw is None:
            raise ValueError("mode C needs a RawStore (1m klines + funding)")
        return raw_packet(packet_a, key, raw)
    raise ValueError(f"packet mode {mode!r} not in {MODES}")


def months_for(cutoffs: Sequence[int], back_days: int = 31) -> List[str]:
    """Every YYYY-MM that the C tables of these cutoffs can touch (the 1d table looks back 30 days)."""
    ms = set()
    for c in cutoffs:
        for dd in (0, back_days * 86400):
            ms.add(datetime.fromtimestamp(c - dd, tz=timezone.utc).strftime("%Y-%m"))
    return sorted(ms)

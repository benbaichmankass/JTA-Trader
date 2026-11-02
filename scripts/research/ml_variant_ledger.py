#!/usr/bin/env python3
# wiring: imported by scripts/research/ml_entry_timeframe.py and ml_entry_tp_revision.py (ML-PROP-ITERATE ledger emission, lane PROP-STRUCT-EXITS-ML-LEDGERS)
"""Emit the ETH+SOL trade ledger the prop gate reads (ledger_ethsol.jsonl) from an ML-ENTRY variant's own trades.

scripts/research/ml_variant_prop_gate.py finds ``ledger_ethsol.jsonl`` beside a variant unit's result and otherwise returns INDETERMINATE
(read_state no_variant_ledger, PR #22369). This module is the missing piece: it turns a variant's trade frame into the ml_entry gate-ledger
row shape {symbol, direction, entry_time, exit_time, entry, sl, exit_reason, gross_r} that prop_ev_sim re-prices under each firm cost stack.

Nothing here changes a variant's result or its rule: it only writes an extra file. ``mfe_r`` is omitted when the harness does not track it
(prop_ev_sim then skips the intra-trade bridge, see bridge_min_r) - stated in the first row's ``ledger_note``, never invented.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SYMS = ("ETHUSDT", "SOLUSDT")
REASON = {0: "time", 1: "sl", 2: "take_profit"}   # ml_decision_entry reason codes (build_ledger.py)
NOTE = "dev-OOS ledger from policy frame; entry at decision-bar close, exit = entry + bars x bar_hours; price normalised to 1.0; mfe_r not tracked"


def ledger_from_policy(trades: pd.DataFrame, tab: pd.DataFrame, bar_hours: float, sl_atr: float,
                       symbols: tuple[str, ...] = SYMS) -> list[dict]:
    """trades: E.policy frame (symbol, ts, side, gross_r, reason, ...); tab: the decision table that produced it
    (needs symbol, ts, atr_pct, bars_long, bars_short). Returns ledger rows for ``symbols`` ordered by entry_time."""
    if trades is None or len(trades) == 0:
        return []
    t = trades[trades.symbol.isin(symbols)]
    if len(t) == 0:
        return []
    cols = ["symbol", "ts", "atr_pct", "bars_long", "bars_short"]
    m = t.merge(tab[cols].drop_duplicates(["symbol", "ts"]), on=["symbol", "ts"], how="left", validate="m:1")
    if m["atr_pct"].isna().any():
        raise ValueError(f"{int(m['atr_pct'].isna().sum())} trade rows not found in the decision table (symbol, ts)")
    bar = pd.Timedelta(hours=bar_hours)
    out = []
    for r in m.itertuples(index=False):
        s = 1 if r.side == "long" else -1
        nb = int(r.bars_long if r.side == "long" else r.bars_short)
        et = pd.Timestamp(r.ts) + bar
        xt = et + nb * bar
        risk = sl_atr * float(r.atr_pct)              # stop distance as a fraction of entry (entry normalised to 1)
        out.append({"leg": "ml_entry", "strategy": "ml_entry", "symbol": r.symbol, "direction": r.side,
                    "entry_time": str(et), "exit_time": str(xt), "entry": 1.0, "sl": 1.0 - s * risk,
                    "exit_reason": REASON.get(int(r.reason), "time"), "gross_r": round(float(r.gross_r), 6)})
    out.sort(key=lambda x: x["entry_time"])
    if out:
        out[0]["ledger_note"] = NOTE
    return out


def ledger_from_walks(trades: pd.DataFrame, rec: list, win: list, bars: dict, sl_atr: float,
                      symbols: tuple[str, ...] = SYMS) -> list[dict]:
    """First-passage harnesses (ml_entry_tp_revision): ``rec[k]`` = (exit_px, exit_j, reason) of trade k as the policy walked it,
    ``win[k]`` = (open, high, low, close) arrays after entry, ``bars[symbol]['ts']`` the bar clock. Same row construction as
    docs/research/ml-entry-prop-gate-2026-11-02/build_ledger.py (which reproduced the evidence record to 1e-6), with mfe_r tracked."""
    if len(rec) != len(trades) or len(win) != len(trades):
        raise ValueError(f"walk record length {len(rec)} / window length {len(win)} != trades {len(trades)}")
    out = []
    for k, t in trades.reset_index(drop=True).iterrows():
        if t.symbol not in symbols:
            continue
        px, j, reason = rec[k]
        sd = 1 if t.side == "long" else -1
        _, hh, lo, _ = win[k]
        entry = float(win[k][0][0])
        risk = sl_atr * float(t.atr)
        ts = bars[t.symbol]["ts"]
        et = ts.iloc[int(t.i) + 1]
        xt = ts.iloc[int(t.i) + j] + pd.Timedelta(hours=1)
        fav = (hh[:j].max() - entry) if sd > 0 else (entry - lo[:j].min())
        gross = sd * (px - entry) / risk
        out.append({"leg": "ml_entry", "strategy": "ml_entry", "symbol": t.symbol, "direction": t.side, "entry_time": str(et),
                    "exit_time": str(xt), "entry": entry, "sl": entry - sd * risk, "exit_reason": REASON.get(int(reason), "time"),
                    "gross_r": round(float(gross), 6), "mfe_r": round(float(max(fav / risk, gross)), 6)})
    out.sort(key=lambda x: x["entry_time"])
    return out


def write_ledger(rows: list[dict], out_dir: Path, name: str = "ledger_ethsol.jsonl") -> Path:
    """Always writes the file (an empty variant writes zero rows, which the gate grades n_below_floor, not no_variant_ledger)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _self_test() -> None:
    ts = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    tab = pd.DataFrame({"symbol": ["ETHUSDT", "SOLUSDT", "BTCUSDT", "ETHUSDT"], "ts": ts, "atr_pct": [0.01, 0.02, 0.01, 0.01],
                        "bars_long": [3, 4, 5, 2], "bars_short": [3, 4, 5, 2]})
    tr = pd.DataFrame({"symbol": ["SOLUSDT", "ETHUSDT", "BTCUSDT"], "ts": [ts[1], ts[0], ts[2]], "side": ["short", "long", "long"],
                       "gross_r": [1.5, -1.0, 0.3], "reason": [2, 1, 0]})
    rows = ledger_from_policy(tr, tab, 1.0, 1.5)
    assert [r["symbol"] for r in rows] == ["ETHUSDT", "SOLUSDT"], rows            # BTC dropped, ordered by entry
    e, s = rows
    assert e["exit_reason"] == "sl" and abs(e["sl"] - (1 - 0.015)) < 1e-9 and e["exit_time"] == "2024-01-01 04:00:00+00:00", e
    assert s["direction"] == "short" and abs(s["sl"] - (1 + 0.03)) < 1e-9 and s["exit_reason"] == "take_profit", s
    assert ledger_from_policy(tr.iloc[0:0], tab, 1.0, 1.5) == []
    try:
        ledger_from_policy(tr.assign(ts=ts[3] + pd.Timedelta(days=9)), tab, 1.0, 1.5)
        raise SystemExit("expected ValueError")
    except ValueError:
        pass
    print("ml_variant_ledger self-test ok")


if __name__ == "__main__":
    _self_test()

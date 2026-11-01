#!/usr/bin/env python3
# wiring: manual-only - run by a RESEARCH-EDGE session for unit RQ-20261101-58e4-04 (row COST-LEVER-LIVE-LEGS).
"""Upper bounds on two cost levers for the legs currently on real money, from the trades journal.

Legs  : the `strategies:` of the accounts whose mode is live AND account_class real money, re-read from config/accounts.yaml
        (bybit_2, alpaca_live today; never quoted). Population: journal rows with status closed, pnl not null, account_class
        real_money, setup_type in those legs.
Costs : fee_taker_usd + fee_maker_usd + funding_paid_usd on the row. `cost_source` is `estimate` on almost every row (audit
        2026-11-01), so every cost figure here is an ESTIMATE; COST-BROKER-SOURCED is the measured follow-up. Rows with null
        cost fields are counted and listed, never read as 0 cost.
Lever A (maker/limit entries): ENTRY leg only. saving per trade = notional x (taker_entry_bps - maker_entry_bps)/1e4 with
        taker_entry = 5.5 (half of the measured 11.0 round trip) + 0.434 slippage (half of the 0.868 measured), maker = 2.0
        (published, UNVERIFIED on our account; 3 maker fills ever). Fill probability p in {1.0, 0.75, 0.5}; unfilled trades
        are NO TRADE (their net P&L is not earned or lost). NO adverse-selection term is applied: with p<1 the removed trades
        are assumed uncorrelated with outcome, which is an UPPER bound for a strategy whose winners run away from a limit.
Lever B (lower frequency): keep a fraction (1-f) of trades, f in {0.25, 0.5}, removed uniformly (no signal-strength selection).
        delta = -f x net. Any gain beyond that needs a SELECTION effect, which needs signal-level data (not in the journal).
Rule  : registered in research/queue/RQ-20261101-58e4-04.yaml.
"""
from __future__ import annotations
import argparse, glob, json, sys
from pathlib import Path
import pandas as pd, yaml

TAKER_ENTRY_BPS = 5.5 + 0.434
MAKER_ENTRY_BPS = 2.0


def real_legs(accounts_yaml: Path):
    a = yaml.safe_load(accounts_yaml.read_text())
    accs = a.get("accounts", a)
    legs, names = set(), []
    for k, v in accs.items():
        if isinstance(v, dict) and v.get("mode") == "live" and v.get("account_class", "real_money") != "paper" and v.get("strategies"):
            legs |= set(v["strategies"]); names.append(k)
    return sorted(legs), names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal-dir", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--accounts", default="config/accounts.yaml")
    a = ap.parse_args()
    legs, accts = real_legs(Path(a.accounts))
    rows = []
    for f in sorted(glob.glob(a.journal_dir + "/p*.json")):
        rows += json.load(open(f))["rows"]
    df = pd.DataFrame(rows)
    d = df[(df.status == "closed") & df.pnl.notna() & (df.account_class == "real_money") & df.setup_type.isin(legs)].copy()
    d["cost"] = d.fee_taker_usd.fillna(0) + d.fee_maker_usd.fillna(0) + d.funding_paid_usd.fillna(0)
    d["cost_known"] = d.fee_taker_usd.notna()
    d["notional"] = d.entry_price * d.position_size
    out = {"legs": legs, "accounts": accts, "n": int(len(d)), "n_cost_fields_null": int((~d.cost_known).sum()),
           "cost_source_counts": d.cost_source.fillna("null").value_counts().to_dict(),
           "net_pnl": round(float(d.pnl.sum()), 2), "cost_total_est": round(float(d.cost.sum()), 2),
           "gross_before_cost": round(float((d.pnl + d.cost).sum()), 2), "notional_total": round(float(d.notional.sum()), 0),
           "first": str(d.timestamp.min()), "last": str(d.timestamp.max()), "per_leg": {}, "lever_A": {}, "lever_B": {}}
    for leg, g in d.groupby("setup_type"):
        out["per_leg"][leg] = {"n": int(len(g)), "net": round(float(g.pnl.sum()), 2), "cost_est": round(float(g.cost.sum()), 2),
                               "gross": round(float((g.pnl + g.cost).sum()), 2), "notional": round(float(g.notional.sum()), 0)}
    net = float(d.pnl.sum())
    sav = float((d.notional * (TAKER_ENTRY_BPS - MAKER_ENTRY_BPS) / 1e4).sum())
    for p in (1.0, 0.75, 0.5):
        delta = p * sav - (1 - p) * net
        out["lever_A"][f"p={p}"] = {"net_delta_upper": round(delta, 2), "net_after": round(net + delta, 2), "turns_pooled_net_ge_0": net + delta >= 0}
    out["lever_A"]["max_saving_at_p1"] = round(sav, 2)
    for f in (0.25, 0.5):
        delta = -f * net
        out["lever_B"][f"f={f}"] = {"net_delta_no_selection": round(delta, 2), "net_after": round(net + delta, 2), "turns_pooled_net_ge_0": net + delta >= 0,
                                    "needs_selection_effect_to_clear": True}
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    sys.exit(main())

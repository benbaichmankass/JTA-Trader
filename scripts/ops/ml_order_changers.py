#!/usr/bin/env python3
"""One line per model that has a consumer, real money first (row ML-ONE-LADDER; /ml-review fixed checks).

READ-ONLY, REPORT-ONLY: reads GET /api/bot/ml/registry (rows[].consumers[]) and docs/reference/ml-order-changers-power.yaml, prints
sd, se, t, clustered se, trades needed to confirm and the model's named demotion signal. Refuses nothing, gates nothing; the
demotion signal is a LABEL. A figure that is unknown prints '—', never 0. 't=2' in 'trades_to_confirm' is the reporting
yardstick for how far a record is from a two-sided 2-sigma read, not a promotion threshold.
Exit 0 ok; 2 = could-not-look (feed unreadable) so the caller treats it as an incident, never as 'no consumers'.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POWER = ROOT / "docs" / "reference" / "ml-order-changers-power.yaml"
FEED = "https://ict-bot.duckdns.org/api/bot/ml/registry"
_RANK = {"real_money": 0, "prop": 1}
DASH = "—"


def _f(x, nd=3):
    return DASH if x is None else f"{x:.{nd}f}"


def power_cols(rec: dict) -> dict:
    """sd/se/t/clustered se/trades-to-confirm from one record; None where an input is unknown."""
    mean, n, sd, cse = rec.get("mean_net_r"), rec.get("n"), rec.get("sd_r"), rec.get("clustered_se")
    se = sd / math.sqrt(n) if sd and n else None
    se_used = cse if cse else se
    t = mean / se_used if mean is not None and se_used else None
    need = None
    if mean and mean > 0 and se_used and n:
        need = math.ceil(n * (2 * se_used / mean) ** 2)
    return {"sd": sd, "se": se, "t": t, "cse": cse, "need": need}


def load_feed(path: str | None) -> dict:
    if path:
        return json.loads(Path(path).read_text())
    with urllib.request.urlopen(FEED, timeout=30) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read())


def load_power_doc(path) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def slot_map(doc: dict) -> dict:
    """Machine-readable slot map: per served artifact its slot, baseline, competition metric and demotion read, joined from `slots:`.

    A model whose slot or baseline is undeclared reports None for those fields (printed '—'), never a made-up value.
    """
    slots, models = doc.get("slots") or {}, doc.get("models") or {}
    out = {"slots": slots, "models": {}, "undeclared": []}
    for mid, rec in models.items():
        sl = slots.get(rec.get("baseline"))
        row = {
            "slot": rec.get("slot"),
            "baseline": sl.get("baseline") if sl else None,
            "competition_metric": sl.get("competition_metric") if sl else None,
            "cost_net_metric": sl.get("cost_net_metric") if sl else None,
            "demotion_read": rec.get("demotion_read"),
        }
        out["models"][mid] = row
        if not all(row[k] for k in ("slot", "baseline", "competition_metric", "demotion_read")):
            out["undeclared"].append(mid)
    return out


def build_lines(feed: dict, power: dict, slots: dict | None = None) -> list[str]:
    rows = [r for r in feed.get("rows", []) if r.get("consumers")]

    def best(r):
        return min(_RANK.get(c.get("account_class"), 2) for c in r["consumers"])

    rows.sort(key=lambda r: (best(r), r.get("model_id", "")))
    out = []
    for r in rows:
        mid = r["model_id"]
        rec = power.get(mid)
        books = sorted({f"{c['account']}({c.get('account_class', '?')})" for c in r["consumers"]})
        name = r.get("display_name") or mid
        if rec is None:
            out.append(f"{name} [{mid}] slot={r.get('slot')} books={','.join(books)} | NO POWER RECORD (add to "
                       f"docs/reference/ml-order-changers-power.yaml) | sd={DASH} se={DASH} t={DASH} cse={DASH} need={DASH}")
            continue
        p = power_cols(rec)
        out.append(
            f"{name} [{mid}] slot={r.get('slot')} order_effect={rec.get('order_effect', DASH)} books={','.join(books)} | "
            f"mean_net_r={_f(rec.get('mean_net_r'), 4)} n={rec.get('n') or DASH} sd={_f(p['sd'], 2)} se={_f(p['se'], 4)} "
            f"t={_f(p['t'], 2)} cse={_f(p['cse'], 3)} trades_to_confirm(t=2)={p['need'] or DASH} | "
            f"slot={rec.get('slot') or DASH} baseline={((slots or {}).get(rec.get('baseline')) or {}).get('baseline') or DASH} | "
            f"demotion_signal(label, report-only)={rec.get('demotion_read') or rec.get('demotion_signal') or DASH}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry-json", help="read the feed from a file instead of HTTPS")
    ap.add_argument("--power", default=str(POWER))
    ap.add_argument("--slot-map", action="store_true",
                    help="print the machine-readable slot map (JSON; baseline, metric, demotion read per artifact) and exit; "
                         "needs no feed. Exit 0 ok; 1 = an artifact has an undeclared field; 2 = could-not-look")
    a = ap.parse_args(argv)
    if a.slot_map:
        try:
            sm = slot_map(load_power_doc(a.power))
        except Exception as e:  # noqa: BLE001
            print(f"could-not-look: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        print(json.dumps(sm, indent=2, sort_keys=True))
        return 1 if sm["undeclared"] else 0
    try:
        feed = load_feed(a.registry_json)
        if feed.get("inventory_read_state") != "ok":
            print(f"could-not-look: inventory_read_state={feed.get('inventory_read_state')!r}", file=sys.stderr)
            return 2
        pdoc = load_power_doc(a.power)
        power, slots = pdoc.get("models") or {}, pdoc.get("slots") or {}
    except Exception as e:  # noqa: BLE001 - any failure to look is could-not-look, not 'none'
        print(f"could-not-look: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    lines = build_lines(feed, power, slots)
    print(f"# models with a consumer: {len(lines)} (population: feed rows with consumers[]; real money first; "
          f"feed inventory_count={feed.get('inventory_count')}, rows={feed.get('total_count')})")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

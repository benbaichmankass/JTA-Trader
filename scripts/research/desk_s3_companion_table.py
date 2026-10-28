#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-S3-VOL-MATCHED-BASELINE; no schedule consumes it.
"""DESK-S3-VOL-MATCHED-BASELINE step 3: re-score the edge program's committed evidence with the S3 COMPANIONS.

  judged-1   the driver's score() on comms/research/desk_gen_replay/judged-1 (proposals + mask key), all filled proposals
  arms A/B/C desk_packet_arms.score_arm on the dev sample and the committed ranks (top-pick policy)
  -> comms/research/desk_s3_companions/table.json  (+ table.md)

Companions only: S3 here is re-derived by the same code path and is checked against the committed value; a mismatch is
printed and recorded, never papered over. Population (n) is stated on every number.
  run --candles DIR --out DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402
from scripts.research import desk_packet_arms as pa  # noqa: E402

COMM = REPO / "comms/research"
ARMS = {"A": COMM / "desk_edge/dev-1/V1/ranks.jsonl", "B": COMM / "desk_packet_redesign/B/ranks.jsonl",
        "C": COMM / "desk_packet_redesign/C/ranks.jsonl"}
SAMPLE = COMM / "desk_edge/dev-1/sample.json"
COMMITTED = {a: COMM / f"desk_packet_redesign/scores-100/arm-{a}.json" for a in "ABC"}


def fmt(c: Dict[str, Any]) -> str:
    ci = c.get("ci95")
    return "n/a" if c.get("mean") is None else f"{c['mean']:+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}] n={c['n']}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candles", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    uni, _ = d.parse_universe()
    syms = [u["symbol"] for u in uni]
    classes = {u["symbol"]: u["classes"] for u in uni}
    mkt, missing = d.load_market(Path(a.candles), syms)
    if missing:
        raise SystemExit(f"candles missing {missing}")
    table: List[dict] = []
    # judged-1
    key_path = COMM / "desk_gen_replay/judged-1/mask-key.json"
    keys = {k["packet_id"]: k for k in json.loads(key_path.read_text())["keys"]}
    ns = argparse.Namespace(mask_key=str(key_path), packets=None, proposals=str(COMM / "desk_gen_replay/judged-1/proposals.jsonl"), seed=d.SEED)
    got, err = d._load_judged(ns, mkt, classes)
    if err:
        table.append({"record": "judged-1", "error": err})
    else:
        keys, _, by, intake = got
        sc = d.score(mkt, keys, by, [], {}, subset="all", cutoff=None, selfcheck=None)
        st = sc["stats"]
        table.append({"record": "judged-1 (all filled proposals)", "policy": "every valid proposal", "rescored_S3": st.get("paired_diff_vs_random"),
                      "companions": st["companions"], "S1": st.get("mean_net_r"), "n_filled": st["n"], "weeks": st.get("weeks")})
    # arms
    sample = json.loads(SAMPLE.read_text())["packets"]
    karm = {k["packet_id"]: k for k in json.loads(pa.dl.JUDGED1_KEY.read_text())["keys"]}
    for arm, rp in ARMS.items():
        res = pa.score_arm(arm, mkt, classes, karm, sample, rp)
        com = json.loads(COMMITTED[arm].read_text())
        t = res["s3_top_pick"]
        table.append({"record": f"packet-redesign arm {arm} (top-pick policy, dev sample)", "policy": "top-pick", "rescored_S3": t["s3"],
                      "committed_S3": com["s3_top_pick"]["s3"], "matches_committed": abs(t["s3"] - com["s3_top_pick"]["s3"]) < 1e-9,
                      "companions": t["companions"], "S1": t["mean_net_r"], "n_picks": t["n"], "weeks": t["weeks"],
                      "packets_ranked": res["packets_ranked"]})
        pr = res["proposals"]
        table.append({"record": f"packet-redesign arm {arm} (proposals, dev sample)", "policy": "every valid proposal", "rescored_S3": pr["s3"],
                      "committed_S3": com["proposals"]["s3"], "matches_committed": (pr["s3"] is None and com["proposals"]["s3"] is None) or
                      (pr["s3"] is not None and abs(pr["s3"] - com["proposals"]["s3"]) < 1e-9),
                      "companions": res.get("proposals_companions"), "n_filled": pr["filled"]})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "table.json").write_text(json.dumps(table, indent=1) + "\n")
    print(json.dumps([{k: r.get(k) for k in ("record", "rescored_S3", "committed_S3", "matches_committed")} for r in table], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

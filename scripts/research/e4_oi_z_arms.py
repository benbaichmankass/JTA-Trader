#!/usr/bin/env python3
# wiring: research-script-run.yml via research/queue/RQ-20261101-78fc-11.yaml (run.commands). Tier-1 research read:
# re-replays the frozen E4 arm at other OI-shock thresholds; no config, no order path.
"""RQ-20261101-78fc-11: the frozen E4 arm re-replayed at oi_z 4.0 / 5.0 on the held-out window, graded by the unit's rule.

RULE-RQ-20261101-78fc-11 (registered 2026-11-01, not edited here): PASS iff an arm has n >= 30 AND mean net R > 0 AND a
95% ISO-week cluster CI lower bound > 0 on the held-out rows (the E18G-03 rule, unchanged, per arm; denominator 2 arms).
FAIL otherwise; INDETERMINATE if every arm has n < 30.

Instrument control (run first, gates the arms): the oi_z 3.0 replay of the held-out window must reproduce the committed
ledger docs/research/e4-prop-sim-2026-10-30/ledgers/e4_full.jsonl (window == holdout; 856 rows) row for row on
(symbol, direction, entry_time, exit_time, exit_reason, gross_r). If it does not, the arms are reported but NOT graded:
the run is `measured` / `indeterminate` with the mismatch named, never a pass or fail on an instrument that moved.

Net R per trade is the driver's own `driver_net_r` (the same engine and full cost stack the E4 evidence record was graded
on, desk_gen_replay_driver.transplant); the cluster unit is the ISO week of the fill; the bootstrap is
desk_event_entry_replay.cluster_mean (seed 20261030, 10,000 draws).

Usage:
    python3 scripts/research/e4_oi_z_arms.py --root <cache> --out <dir> [--fetch]
    python3 scripts/research/e4_oi_z_arms.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

UNIT = "RQ-20261101-78fc-11"
RULE_ID = "RULE-RQ-20261101-78fc-11"
ARMS = (4.0, 5.0)
CONTROL_OI_Z = 3.0
N_MIN = 30
ALPHA = 0.05
LEDGER = REPO / "docs" / "research" / "e4-prop-sim-2026-10-30" / "ledgers" / "e4_full.jsonl"
KEY = ("symbol", "direction", "entry_time", "exit_time", "exit_reason", "gross_r")


def iso_week(ts: str) -> str:
    y, w, _ = datetime.fromisoformat(ts).isocalendar()
    return f"{y}-W{w:02d}"


def _key(r: Dict[str, Any]) -> tuple:
    return tuple(round(float(r[k]), 6) if k == "gross_r" else str(r[k]) for k in KEY)


def control_diff(replayed: Sequence[Dict[str, Any]], committed: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    a, b = sorted(map(_key, replayed)), sorted(map(_key, committed))
    sa, sb = set(a), set(b)
    return {"reproduces": a == b, "n_replayed": len(a), "n_committed": len(b),
            "only_replayed": len(sa - sb), "only_committed": len(sb - sa)}


def grade_arm(rows: Sequence[Dict[str, Any]], cluster_mean) -> Dict[str, Any]:
    vals = [float(r["driver_net_r"]) for r in rows]
    cm = cluster_mean(vals, [iso_week(r["entry_time"]) for r in rows], ALPHA)
    n, mean, lb = cm["n"], cm["mean"], (cm.get("ci") or [None])[0]
    if n < N_MIN:
        state = "indeterminate"
    else:
        state = "pass" if (mean is not None and mean > 0 and lb is not None and lb > 0) else "fail"
    return {"n": n, "weeks": cm.get("weeks"), "mean_net_r": mean, "ci95": cm.get("ci"), "state": state}


def verdict_from(arms: Dict[str, Dict[str, Any]], control: Dict[str, Any]) -> Dict[str, Any]:
    states = [a["state"] for a in arms.values()]
    if not control["reproduces"]:
        verdict, why = "indeterminate", (f"instrument control failed: oi_z {CONTROL_OI_Z} replay does not reproduce the committed "
                                         f"held-out ledger ({control}); arms reported, NOT graded")
    elif "pass" in states:
        verdict, why = "pass", "an arm clears n >= 30, mean net R > 0 and the 95% ISO-week cluster CI lower bound > 0"
    elif all(s == "indeterminate" for s in states):
        verdict, why = "indeterminate", "every arm has n < 30"
    else:
        verdict, why = "fail", "no arm clears n >= 30 with mean > 0 and cluster CI LB > 0"
    n = sum(a["n"] for a in arms.values())
    return {"verdict": verdict, "read_state": "measured", "n": n,
            "population": (f"{UNIT}: frozen E4 arm re-replayed on the held-out window (2024-11-01..2025-10-25), "
                           f"{ARM_KIND} arms {', '.join(str(k) for k in arms)}; n = summed filled trades over the {len(arms)} arms; net R = driver net "
                           f"(full cost stack); control oi_z {CONTROL_OI_Z} vs committed ledger: "
                           f"{'reproduces' if control['reproduces'] else 'DOES NOT reproduce'}"),
            "note": f"{RULE_ID}: {verdict} -- {why}; " + "; ".join(
                f"{ARM_KIND} {k}: n {a['n']} mean {a['mean_net_r']} ci95 {a['ci95']} -> {a['state']}" for k, a in arms.items()),
            "measurement": {"rule_id": RULE_ID, "control": control, "arms": arms, "arm_kind": ARM_KIND, "alpha": ALPHA,
                            "n_min": N_MIN}}


ARM_KIND = "oi_z"   # E4-OI-LEVER-DRIVER (2026-11-25): oi_z (default, byte-identical) | horizon | side


def arm_kwargs() -> Dict[str, Dict[str, Any]]:
    """{arm label: e4_prop_ledger.rows_for kwargs}. oi_z arms vary the threshold (labels '4.0', as before); horizon arms
    vary the time-stop in bars at the frozen oi_z 3.0 ('h48'); side arms vary the side rule at oi_z 3.0 ('fade')."""
    if ARM_KIND == "oi_z":
        return {str(float(z)): {"oi_z": float(z)} for z in ARMS}
    if ARM_KIND == "horizon":
        return {f"h{int(h)}": {"oi_z": CONTROL_OI_Z, "geom": {"horizon": int(h)}} for h in ARMS}
    if ARM_KIND == "side":
        return {str(sd): {"oi_z": CONTROL_OI_Z, "side_mode": str(sd)} for sd in ARMS}
    raise ValueError(f"--arm-kind {ARM_KIND!r}")


def run(root: Path, out: Path, fetch: bool) -> Dict[str, Any]:
    import desk_event_entry_replay as m
    import e4_prop_ledger as led
    if fetch:
        m.fetch(root, "holdout")
    committed = [r for r in (json.loads(ln) for ln in LEDGER.read_text().splitlines() if ln.strip())
                 if r.get("window") == "holdout"]
    control = control_diff(led.rows_for(root, m.HOLDOUT, CONTROL_OI_Z), committed)
    arms = {label: grade_arm(led.rows_for(root, m.HOLDOUT, **kw), m.cluster_mean) for label, kw in arm_kwargs().items()}
    v = verdict_from(arms, control)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n")
    return v


def self_test() -> int:
    import desk_event_entry_replay as m
    ok = True

    def chk(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    def rows(n: int, val: float, weeks: int = 10) -> List[Dict[str, Any]]:
        return [{"driver_net_r": val + (0.01 if i % 2 else -0.01), "entry_time": f"2025-0{1 + (i % weeks) // 5}-{1 + (i % 5) * 5:02d}T00:00:00+00:00"}
                for i in range(n)]
    good = {"reproduces": True}
    chk("positive arm with n 40 passes", verdict_from({"4.0": grade_arm(rows(40, 0.3), m.cluster_mean),
                                                       "5.0": grade_arm(rows(10, 0.3), m.cluster_mean)}, good)["verdict"] == "pass")
    chk("negative arms fail", verdict_from({"4.0": grade_arm(rows(40, -0.2), m.cluster_mean),
                                            "5.0": grade_arm(rows(35, -0.1), m.cluster_mean)}, good)["verdict"] == "fail")
    chk("every arm n < 30 -> indeterminate", verdict_from({"4.0": grade_arm(rows(20, 0.5), m.cluster_mean),
                                                           "5.0": grade_arm(rows(5, 0.5), m.cluster_mean)}, good)["verdict"] == "indeterminate")
    chk("control mismatch -> indeterminate even with a passing arm",
        verdict_from({"4.0": grade_arm(rows(40, 0.3), m.cluster_mean)}, {"reproduces": False})["verdict"] == "indeterminate")
    r = {"symbol": "X", "direction": "long", "entry_time": "t", "exit_time": "u", "exit_reason": "tp", "gross_r": 2.0000001}
    chk("control compares on the key, gross_r to 6 dp", control_diff([r], [{**r, "gross_r": 2.0}])["reproduces"])
    chk("control catches a missing row", not control_diff([r], [r, {**r, "symbol": "Y"}])["reproduces"])
    chk("detect() default threshold is the frozen OI_Z 3.0", __import__("inspect").signature(m.detect).parameters["oi_z"].default == 3.0 == m.OI_Z)
    global ARM_KIND, ARMS
    saved = (ARM_KIND, ARMS)
    ARM_KIND, ARMS = "oi_z", (4.0, 5.0)
    chk("oi_z arms keep their labels and kwargs (byte-identical)", arm_kwargs() == {"4.0": {"oi_z": 4.0}, "5.0": {"oi_z": 5.0}})
    ARM_KIND, ARMS = "horizon", (12.0, 48.0)
    chk("horizon arms run at the frozen oi_z with the horizon overridden",
        arm_kwargs() == {"h12": {"oi_z": 3.0, "geom": {"horizon": 12}}, "h48": {"oi_z": 3.0, "geom": {"horizon": 48}}})
    ARM_KIND, ARMS = "side", ("fade", "long_only")
    chk("side arms run at the frozen oi_z with the side mode", arm_kwargs()["fade"] == {"oi_z": 3.0, "side_mode": "fade"})
    ARM_KIND, ARMS = saved
    import e4_prop_ledger as led
    try:
        led.rows_for(Path("/nonexistent"), m.HOLDOUT, side_mode="sideways")
        refused = False
    except ValueError:
        refused = True
    chk("an unknown side mode is refused before any data is read", refused)
    import inspect
    sig = inspect.signature(led.rows_for).parameters
    chk("rows_for defaults are the frozen arm", sig["geom"].default is None and sig["side_mode"].default == "as_event")
    print("e4_oi_z_arms self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root")
    ap.add_argument("--out")
    ap.add_argument("--fetch", action="store_true", help="fetch the held-out window's OI/funding/candles into --root first")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--arms", help="comma list of arm values: oi_z thresholds (default 4.0,5.0, the 78fc-11 grid), horizon "
                                   "bars (e.g. 12,48) or side modes (long_only,short_only,fade) per --arm-kind")
    ap.add_argument("--arm-kind", choices=("oi_z", "horizon", "side"), default="oi_z",
                    help="the lever the arms vary (E4-OI-LEVER-DRIVER); horizon/side arms run at the frozen oi_z 3.0. "
                         "The oi_z 3.0 instrument control is unchanged for every kind")
    ap.add_argument("--unit", help="research unit id stamped in the verdict (default RQ-20261101-78fc-11)")
    ap.add_argument("--rule-id", help="decision rule id stamped in the verdict (default RULE-RQ-20261101-78fc-11)")
    a = ap.parse_args(argv)
    global UNIT, RULE_ID, ARMS, ARM_KIND
    ARM_KIND = a.arm_kind
    if a.arms:
        vals = [x.strip() for x in a.arms.split(",") if x.strip()]
        ARMS = tuple(vals) if ARM_KIND == "side" else tuple(float(x) for x in vals)
    elif ARM_KIND != "oi_z":
        ap.error("--arm-kind horizon|side needs --arms")
    if ARM_KIND == "side":
        import e4_prop_ledger as led
        bad = [x for x in ARMS if x not in led.SIDE_MODES or x == "as_event"]
        if bad:
            ap.error(f"side arms {bad} not in {[x for x in led.SIDE_MODES if x != 'as_event']}")
    if a.unit:
        UNIT = a.unit
    if a.rule_id:
        RULE_ID = a.rule_id
    if a.self_test:
        return self_test()
    if not a.root or not a.out:
        ap.error("--root and --out are required (or --self-test)")
    v = run(Path(a.root), Path(a.out), a.fetch)
    print(json.dumps({k: v[k] for k in ("verdict", "n", "note")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# wiring: research/queue/RQ-20261106-5b7a-01..03 (research-script-run.yml), RESEARCH-NO-WAIT-FOR-DATA 2026-11-28
"""SIBLING-SYMBOL read of ONE leg's exact config: k-of-N per-symbol Stage-0 grades -> one verdict.json.

Why (RESEARCH-NO-WAIT-FOR-DATA, operator 2026-11-28 ~09:55Z, relayed by Manager 2026-11-28b): a leg whose params last
changed recently has no clean TIME span to re-measure them on for months. Symbols that no same-family leg was ever
tuned on are clean NOW: the config was not chosen on them. The unit runs ``exit_lever_ablation.py --grade stage0
--symbol <S>`` (the config-exact symbol-twin harness) once per pre-registered symbol into ``<out>/<S>/``, then this
script applies the pre-registered k-of-N rule:

    pass           iff >= k symbols read pass
    fail           iff passes + indeterminates < k   (k can no longer be reached)
    indeterminate  otherwise (including a symbol whose run produced no verdict.json: could_not_look, never a fail)

It also reports the pooled n and net R over the symbols that ran (descriptive; the rule is the count). Writes
``<out>/verdict.json`` in the research-script-run contract. Report-only; Gates this adds or changes: none.

    python3 scripts/research/twin_family_read.py --out DIR --leg L --symbols DOTUSDT,LINKUSDT,... --min-pass 4
    python3 scripts/research/twin_family_read.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def read(out: Path, symbols: list[str]) -> dict[str, dict]:
    res = {}
    for s in symbols:
        p = out / s / "verdict.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            res[s] = {"verdict": "indeterminate", "read_state": "could_not_look", "why": f"{p} absent or unreadable"}
            continue
        g = (d.get("measurement") or {}).get("grade") or {}
        res[s] = {"verdict": d.get("verdict") if d.get("verdict") in ("pass", "fail") else "indeterminate",
                  "read_state": d.get("read_state"), "n": g.get("n", d.get("n")), "net_r": g.get("net_r"),
                  "folds_positive": g.get("folds_positive"), "why": g.get("why") or d.get("note")}
    return res


def decide(per: dict[str, dict], k: int) -> tuple[str, str]:
    p = sum(v["verdict"] == "pass" for v in per.values())
    i = sum(v["verdict"] == "indeterminate" for v in per.values())
    if p >= k:
        return "pass", f"{p} of {len(per)} sibling symbols pass (>= {k})"
    if p + i < k:
        return "fail", f"{p} pass + {i} indeterminate of {len(per)} < {k}: the config does not hold on unseen symbols"
    return "indeterminate", f"{p} pass, {i} indeterminate of {len(per)}: {k} not reached and not excluded"


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        for s, v, n, r in (("A", "pass", 100, 5.0), ("B", "pass", 90, 2.0), ("C", "fail", 80, -3.0)):
            (out / s).mkdir()
            (out / s / "verdict.json").write_text(json.dumps({"verdict": v, "read_state": "measured", "measurement": {
                "grade": {"verdict": v, "n": n, "net_r": r, "folds_positive": 3}}}))
        per = read(out, ["A", "B", "C", "D"])
        assert per["D"]["read_state"] == "could_not_look" and per["D"]["verdict"] == "indeterminate"
        assert decide(per, 2)[0] == "pass"
        assert decide(per, 3)[0] == "indeterminate"            # D could still make it 3
        assert decide(per, 4)[0] == "fail"                     # 2 pass + 1 indeterminate < 4
    print("twin-family-read self-test OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--leg")
    ap.add_argument("--symbols")
    ap.add_argument("--min-pass", type=int)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not (a.out and a.leg and a.symbols and a.min_pass):
        ap.error("--out --leg --symbols --min-pass are required")
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    out = Path(a.out)
    per = read(out, syms)
    verdict, why = decide(per, a.min_pass)
    ran = [v for v in per.values() if isinstance(v.get("n"), int)]
    pooled = {"n": sum(v["n"] for v in ran), "net_r": round(sum(float(v.get("net_r") or 0.0) for v in ran), 4),
              "symbols_measured": len(ran)}
    doc = {"verdict": verdict, "read_state": "measured" if ran else "could_not_look", "n": pooled["n"],
           "note": why, "population": f"{a.leg} exact config on sibling symbols {syms} (no same-family leg tuned on them), "
                                      "each graded by exit_lever_ablation --grade stage0 net of fee + slippage + funding",
           "measurement": {"leg": a.leg, "rule": {"min_pass": a.min_pass, "of": len(syms)}, "per_symbol": per,
                           "pooled_descriptive": pooled}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "why": why, "pooled": pooled}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

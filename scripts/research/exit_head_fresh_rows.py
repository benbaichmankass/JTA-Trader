#!/usr/bin/env python3
"""Rebuild exit-head training rows on FRESH candles and publish them to a NEW path.

Row ML-EXITHEAD-ROWS-FRESH-REBUILD (unit RQ-20261119-a10d-10). The donchian 1h
exit-head corpus (datasets-out/exit_head/1h/donchian/rows.jsonl) was built
2026-07-12 with last bars BTC 07-10 / ETH 07-07 / SOL 07-05. Five units read it
and are blocked until a fresh corpus exists (a10d-07/-08, 04a5-04, aadc-13,
a10d-06). This driver:

  1. runs scripts/research/m20_exit_head_round.py --build-only (the same emit +
     build_exit_head_dataset.py path the July corpus came from; it takes the
     trainer heavy queue) into --build-out;
  2. reads <build-out>/<family>/rows.jsonl and build_report.json and measures,
     per required symbol, the row count and the last bar_t;
  3. PASS iff build_report.generated_at is at or after this run's start AND
     every required symbol's last bar_t is after --after; then (and only then)
     copies the rows to --publish atomically. FAIL publishes nothing.

It refuses to publish over the frozen corpus (any path ending
``exit_head/<tf>/<family>/rows.jsonl``): queued units read that file.

verdict.json -> {verdict, read_state, per_symbol, build_report, published}.
Trains nothing, registers nothing, edits no config, places no order.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _ts(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 1000.0 if x > 1e12 else x


def measure_rows(rows_path: Path) -> dict:
    """Per-symbol {rows, trades, last_bar_t (ISO), sources} from a rows.jsonl."""
    per: dict[str, dict] = {}
    with rows_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = str(r.get("symbol") or "unknown")
            d = per.setdefault(sym, {"rows": 0, "last": None, "trades": set(),
                                     "sources": {}})
            d["rows"] += 1
            t = _ts(r.get("bar_t"))
            if t is not None and (d["last"] is None or t > d["last"]):
                d["last"] = t
            key = r.get("trade_key") or r.get("trade_id")
            if key is not None:
                d["trades"].add(str(key))
            src = str(r.get("source") or "unknown")
            d["sources"][src] = d["sources"].get(src, 0) + 1
    out = {}
    for sym, d in per.items():
        out[sym] = {
            "rows": d["rows"],
            "trades": len(d["trades"]) if d["trades"] else None,
            "last_bar_t": (datetime.fromtimestamp(d["last"], timezone.utc)
                           .isoformat() if d["last"] is not None else None),
            "sources": d["sources"],
        }
    return out


def decide(per_symbol: dict, required: list[str], after: datetime,
           generated_at: str | None, started: datetime) -> tuple[str, list[str]]:
    """(verdict, reasons). pass only if fresh build and every symbol past `after`."""
    reasons: list[str] = []
    try:
        gen = datetime.fromisoformat(str(generated_at)) if generated_at else None
    except ValueError:
        gen = None
    if gen is None:
        reasons.append("build_report.generated_at missing or unparseable")
    elif gen < started:
        reasons.append(f"build_report.generated_at {gen.isoformat()} predates this run "
                       f"({started.isoformat()}): stale report")
    for sym in required:
        d = per_symbol.get(sym)
        if not d or not d.get("last_bar_t"):
            reasons.append(f"{sym}: no rows")
            continue
        if datetime.fromisoformat(d["last_bar_t"]) <= after:
            reasons.append(f"{sym}: last bar_t {d['last_bar_t']} not after {after.date()}")
    return ("pass" if not reasons else "fail"), reasons


def frozen_target(publish: Path) -> bool:
    parts = publish.parts
    return (len(parts) >= 4 and parts[-1] == "rows.jsonl"
            and parts[-4] == "exit_head" and not parts[-2].endswith("_fresh"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--legs", required=True)
    ap.add_argument("--tf", required=True)
    ap.add_argument("--family", required=True, help="builder family dir, e.g. donchian")
    ap.add_argument("--symbols", required=True, help="CSV of symbols that must be fresh")
    ap.add_argument("--after", required=True, help="YYYY-MM-DD; every symbol's last bar_t must be after it")
    ap.add_argument("--build-out", required=True)
    ap.add_argument("--publish", required=True, help="destination rows.jsonl (must be a *_fresh dir)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--unit", default=os.environ.get("RESEARCH_UNIT"))
    ap.add_argument("--out", required=True, help="dir for verdict.json")
    ap.add_argument("--skip-build", action="store_true",
                    help="measure + publish an existing build (tests / re-publish)")
    a = ap.parse_args(argv[1:])

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    publish = Path(a.publish)
    build_out = Path(a.build_out)
    started = datetime.now(timezone.utc)
    after = datetime.fromisoformat(a.after).replace(tzinfo=timezone.utc)
    required = [s.strip() for s in a.symbols.split(",") if s.strip()]
    verdict: dict = {"unit": a.unit, "started_at": started.isoformat(),
                     "legs": a.legs, "tf": a.tf, "family": a.family,
                     "required_symbols": required, "after": a.after,
                     "build_out": str(build_out), "publish": str(publish),
                     "published": False}

    def write(v: str, rs: str, **kw) -> int:
        verdict.update({"verdict": v, "read_state": rs, **kw})
        (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
        print(json.dumps({k: verdict[k] for k in ("verdict", "read_state")}), flush=True)
        return 0

    if frozen_target(publish):
        return write("not_applicable", "producer_failed",
                     error=f"refusing to publish over a frozen corpus path: {publish}")

    if not a.skip_build:
        cmd = [sys.executable, str(REPO / "scripts/research/m20_exit_head_round.py"),
               "--legs", a.legs, "--tf", a.tf, "--out", str(build_out), "--build-only"]
        if a.db:
            cmd += ["--db", a.db]
        print("RUN", " ".join(cmd), flush=True)
        p = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
        print(p.stdout[-6000:], p.stderr[-2000:], flush=True)
        verdict["round_returncode"] = p.returncode
        if p.returncode != 0:
            return write("not_applicable", "producer_failed",
                         error=f"m20_exit_head_round exited {p.returncode}",
                         stderr_tail=(p.stderr or p.stdout)[-1500:])

    rows = build_out / a.family / "rows.jsonl"
    rep_path = build_out / "build_report.json"
    if not rows.exists():
        return write("not_applicable", "producer_failed", error=f"no rows at {rows}")
    try:
        report = json.loads(rep_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        report = {"_error": f"{type(exc).__name__}: {exc}"}
    per_symbol = measure_rows(rows)
    gen = report.get("generated_at") if isinstance(report, dict) else None
    v, reasons = decide(per_symbol, required, after,
                        gen if not a.skip_build else (gen or started.isoformat()),
                        started if not a.skip_build else datetime.min.replace(tzinfo=timezone.utc))
    verdict.update({"per_symbol": per_symbol, "reasons": reasons,
                    "build_report_generated_at": gen,
                    "build_report": {k: report.get(k) for k in list(report)[:40]}
                    if isinstance(report, dict) else None,
                    "n_rows": sum(d["rows"] for d in per_symbol.values())})
    if v == "pass":
        publish.parent.mkdir(parents=True, exist_ok=True)
        tmp = publish.with_suffix(".jsonl.tmp")
        shutil.copyfile(rows, tmp)
        os.replace(tmp, publish)
        shutil.copyfile(rep_path, publish.parent / "build_report.json") if rep_path.exists() else None
        verdict["published"] = True
        print(f"published {rows} -> {publish}", flush=True)
    else:
        print("NOT published: " + "; ".join(reasons), flush=True)
    return write(v, "measured")


def _self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        b = td / "build" / "donchian"
        b.mkdir(parents=True)
        t_new = int(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp())
        t_old = int(datetime(2026, 7, 10, tzinfo=timezone.utc).timestamp())
        with (b / "rows.jsonl").open("w") as fh:
            for sym, t in (("BTCUSDT", t_new), ("ETHUSDT", t_new * 1000), ("SOLUSDT", t_old)):
                fh.write(json.dumps({"symbol": sym, "bar_t": t, "trade_key": sym + "1", "source": "harness"}) + "\n")
        (td / "build" / "build_report.json").write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat()}))
        per = measure_rows(b / "rows.jsonl")
        assert per["ETHUSDT"]["last_bar_t"].startswith("2026-11-18"), per
        after = datetime(2026, 11, 1, tzinfo=timezone.utc)
        early = datetime(2000, 1, 1, tzinfo=timezone.utc)
        v, why = decide(per, ["BTCUSDT", "ETHUSDT", "SOLUSDT"], after, datetime.now(timezone.utc).isoformat(), early)
        assert v == "fail" and any("SOLUSDT" in w for w in why), why
        v, _ = decide(per, ["BTCUSDT", "ETHUSDT"], after, datetime.now(timezone.utc).isoformat(), early)
        assert v == "pass"
        v, why = decide(per, ["BTCUSDT"], after, "2026-07-12T10:37:00+00:00", datetime.now(timezone.utc))
        assert v == "fail" and "stale" in why[0], why
        assert frozen_target(Path("datasets-out/exit_head/1h/donchian/rows.jsonl"))
        assert not frozen_target(Path("datasets-out/exit_head/1h/donchian_fresh/rows.jsonl"))
        pub = td / "exit_head" / "1h" / "donchian_fresh" / "rows.jsonl"
        rc = main(["x", "--legs", "a", "--tf", "1h", "--family", "donchian", "--symbols", "BTCUSDT,ETHUSDT",
                   "--after", "2026-11-01", "--build-out", str(td / "build"), "--publish", str(pub),
                   "--out", str(td / "o"), "--skip-build"])
        got = json.loads((td / "o" / "verdict.json").read_text())
        assert rc == 0 and got["verdict"] == "pass" and got["published"] and pub.exists(), got
        rc = main(["x", "--legs", "a", "--tf", "1h", "--family", "donchian", "--symbols", "BTCUSDT",
                   "--after", "2026-11-01", "--build-out", str(td / "build"),
                   "--publish", str(td / "exit_head" / "1h" / "donchian" / "rows.jsonl"),
                   "--out", str(td / "o2"), "--skip-build"])
        got = json.loads((td / "o2" / "verdict.json").read_text())
        assert got["read_state"] == "producer_failed" and not got["published"], got
    print("self-test OK")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(_self_test())
    sys.exit(main(sys.argv))

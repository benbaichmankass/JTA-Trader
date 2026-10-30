#!/usr/bin/env python3
# wiring: .github/workflows/broad-paths-corpus.yml (labelled issue `broad-paths-corpus-request` or workflow_dispatch); lane ML-DATA-BROAD-PATHS.
"""Corpus v2: the six money-leg configs run config-exact on a frozen 60-perp universe (Tier-1 research tooling).

Spec: docs/research/ml-data-rate-path-2026-10-29.md section 2. Three stages, each a subcommand:

* ``universe`` -- freeze the symbol list. EVERY Binance Vision USDT-M perp (``^[A-Z0-9]+USDT$``; delivery
  contracts such as ``BTCUSDT_260327`` are not perps) whose monthly 1h klines start on or before
  ``end - 730 days`` and run to the month containing ``end``; sorted by (first monthly kline month, symbol);
  the first 60. Chosen by history length ONLY, never by performance. ``corpus_id`` = ``bp2-`` + the first 12
  hex of sha256 over the canonical JSON of {rule, end, legs, symbols+first/last month}.
* ``shard`` -- for each symbol of this shard (``symbols[i::n]``) and each of the six legs: fetch the leg's
  candles (one fetch per symbol x timeframe, shared by the legs on that timeframe), run the leg's harness
  with the leg's own committed config (``regime_debt_matrix.build_harness_cmd`` via
  ``exit_lever_ablation.build_arm_argv``, ``symbols[0]`` swapped) plus ``--emit-paths --emit-features``,
  and keep the trades and path rows. Cost stack = the harness's own (venue-resolved fee + slippage +
  perp funding); every trade row carries ``cost_fee_r``/``cost_slippage_r``/``cost_funding_r`` and ``net_r``.
  A (symbol, leg) that cannot run is recorded in ``could_not_run`` with its reason; nothing halts.
* ``merge`` -- concatenate the shards, de-duplicate on ``trade_key`` (leg-qualified, see below), write
  ``manifest.json``.

``trade_key`` = ``<leg>|<symbol>|<entry_time>|<direction>`` (the harness's own ``harness_emit.trade_key``
shape with the LEG as the strategy). The trend harness stamps every leg ``trend_donchian``, so the harness's
own key would collide across the four trend configs; this stage re-stamps ``strategy`` and the path rows'
``trade_key`` with the leg name and keeps the harness's key as ``harness_trade_key``.

Honesty: a trade count here is a count of harness trades on the pinned window ``[start, end]``, not a claim
that the configs have edge on these symbols (that is queue unit RQ-20261029-7294-01). Shards are the corpus;
they are an Actions artifact (not the repo) and regenerate deterministically from the manifest's inputs.

    python3 scripts/research/broad_paths_corpus.py universe --out /tmp/u.json
    python3 scripts/research/broad_paths_corpus.py shard --universe /tmp/u.json --shard 0 --of 6 --out /tmp/s0
    python3 scripts/research/broad_paths_corpus.py merge --universe /tmp/u.json --shards /tmp/shards --out /tmp/m
    python3 scripts/research/broad_paths_corpus.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO / "scripts"), str(REPO)]

SCHEMA = "broad_paths_corpus/1"
#: The six money legs (docs/plans/ML-PROGRAMME-2026-10-28.md section 2: 2,627 trades / 50,926 bar-states).
LEGS = ("trend_donchian_eth_4h", "trend_donchian_xrp_4h", "xrp_pullback_2h", "ada_pullback_2h",
        "trend_donchian_eth_prop", "trend_donchian_sol_prop")
N_SYMBOLS = 60
MIN_DAYS = 730
END = "2026-09-30"
START = "2020-07-01"           # the window of the 2,627-trade corpus (RQ-20261024-09a6-01)
FETCH_DAYS = 2330              # same fetch depth as path_metric_giveback / first_passage
RULE = ("every Binance Vision USDT-M perp (^[A-Z0-9]+USDT$) with monthly 1h klines from <= end-730d to the month of end; "
        "sorted by (first kline month, symbol); first 60")
_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
_PREFIX = "data/futures/um/monthly/klines/"
_PERP = re.compile(r"^[A-Z0-9]+USDT$")
_MONTH = re.compile(r"-1h-(\d{4}-\d{2})\.zip$")


def _s3_list(prefix: str, delimiter: str = "/") -> list[str]:
    """All keys / common prefixes under ``prefix`` (paginated). Raises on an HTTP error."""
    import requests  # only the universe stage lists S3; the merge job installs no HTTP client
    out, marker = [], ""
    while True:
        r = None
        for wait in (0, 2, 4, 8):
            time.sleep(wait)
            try:
                r = requests.get(_S3, params={"prefix": prefix, "delimiter": delimiter, "marker": marker,
                                              "max-keys": 1000}, timeout=60)
                r.raise_for_status()
                break
            except requests.RequestException:
                r = None
        if r is None:
            raise RuntimeError(f"S3 listing failed for {prefix}")
        root = ET.fromstring(r.content)
        ns = {"s": root.tag.split("}")[0].strip("{")}
        out += [e.text for e in root.findall("s:CommonPrefixes/s:Prefix", ns)]
        out += [e.text for e in root.findall("s:Contents/s:Key", ns)]
        if root.findtext("s:IsTruncated", namespaces=ns) != "true":
            return out
        nm = root.findtext("s:NextMarker", namespaces=ns)
        marker = nm or out[-1]


def _span(symbol: str) -> tuple[str, str] | None:
    keys = _s3_list(f"{_PREFIX}{symbol}/1h/", delimiter="")
    months = sorted(m.group(1) for k in keys if (m := _MONTH.search(k)))
    return (months[0], months[-1]) if months else None


def select_universe(spans: dict[str, tuple[str, str]], end: str = END, n: int = N_SYMBOLS,
                    min_days: int = MIN_DAYS) -> list[dict[str, str]]:
    """The frozen-symbol rule on ``{symbol: (first_month, last_month)}``. Pure, so it is unit-tested."""
    end_d = date.fromisoformat(end)
    cutoff = end_d - timedelta(days=min_days)
    ok = []
    for sym, (first, last) in spans.items():
        if not _PERP.match(sym):
            continue
        first_d = date.fromisoformat(first + "-01")
        if first_d <= cutoff and last >= end_d.strftime("%Y-%m"):
            ok.append({"symbol": sym, "first_month": first, "last_month": last})
    ok.sort(key=lambda r: (r["first_month"], r["symbol"]))
    return ok[:n]


def corpus_id(symbols: list[dict[str, str]], end: str = END) -> tuple[str, dict[str, Any]]:
    inputs = {"schema": SCHEMA, "rule": RULE, "end": end, "start": START, "min_days": MIN_DAYS, "n": N_SYMBOLS,
              "legs": list(LEGS), "symbols": symbols}
    blob = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    return "bp2-" + hashlib.sha256(blob).hexdigest()[:12], inputs


def cmd_universe(a: argparse.Namespace) -> int:
    dirs = [p[len(_PREFIX):].rstrip("/") for p in _s3_list(_PREFIX)]
    perps = sorted(d for d in dirs if _PERP.match(d))
    print(f"listed {len(dirs)} USDT-M dirs, {len(perps)} perps", flush=True)
    spans, empty = {}, []
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for sym, sp in zip(perps, ex.map(_span, perps)):
            (spans.__setitem__(sym, sp) if sp else empty.append(sym))
    chosen = select_universe(spans, a.end)
    cid, inputs = corpus_id(chosen, a.end)
    out = {"corpus_id": cid, "hash_inputs": inputs,
           "census": {"usdtm_dirs": len(dirs), "perps_by_name": len(perps), "with_1h_monthly": len(spans),
                      "no_1h_monthly": len(empty), "qualifying": len(select_universe(spans, a.end, n=10**6)),
                      "selected": len(chosen), "listed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}}
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"corpus_id": cid, **out["census"]}))
    return 0 if len(chosen) == N_SYMBOLS else 1


# ── shard ───────────────────────────────────────────────────────────────────
def _read_jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def stamp(leg: str, trades: list[dict[str, Any]], paths: list[dict[str, Any]]) -> None:
    """Re-stamp harness rows with the LEG name (the trend harness labels every leg ``trend_donchian``)."""
    for t in trades:
        t["harness_trade_key"] = f"{t.get('strategy')}|{t['symbol']}|{t['entry_time']}|{t['direction']}"
        t["strategy"] = leg
        t["leg"] = leg
        t["trade_key"] = f"{leg}|{t['symbol']}|{t['entry_time']}|{t['direction']}"
    for p in paths:
        p["harness_trade_key"] = p["trade_key"]
        parts = p["trade_key"].split("|", 1)
        p["trade_key"] = f"{leg}|{parts[1]}"
        p["strategy"] = leg
        p["leg"] = leg


def run_one(leg: str, base: dict[str, Any], symbol: str, csv: str, resample: str, wd: Path,
            start: str, end: str) -> tuple[list[dict], list[dict], dict]:
    import exit_lever_ablation as ela
    cfg = {**base, "symbols": [symbol]}
    tag = f"{leg}__{symbol}"
    emit, jout, paths = str(wd / f"{tag}__t.jsonl"), str(wd / f"{tag}__bt.json"), str(wd / f"{tag}__p.jsonl")
    argv, omitted = ela.build_arm_argv(leg, cfg, csv, resample, emit, jout, [], start, end)
    argv += ["--emit-paths", paths, "--emit-features"]
    t0 = time.time()
    r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"harness exit {r.returncode}: {r.stderr[-600:]}")
    trades, prows = _read_jsonl(Path(emit)), (_read_jsonl(Path(paths)) if Path(paths).exists() else [])
    stamp(leg, trades, prows)
    bt = json.loads(Path(jout).read_text())
    return trades, prows, {"seconds": round(time.time() - t0, 1), "omitted_levers": omitted,
                           "cost_policy": {k: bt.get(k) for k in ("fee_bps_roundtrip", "slippage_bps_roundtrip",
                                                          "funding_bps_per_window", "mean_cost_r")}}


def cmd_shard(a: argparse.Namespace) -> int:
    import exit_lever_ablation as ela
    import yaml
    uni = json.loads(Path(a.universe).read_text())
    syms = [s["symbol"] for s in uni["hash_inputs"]["symbols"]][a.shard::a.of]
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    cfgs = cfgs.get("strategies", cfgs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    wd = Path(tempfile.mkdtemp(prefix="bp2_"))
    could_not, runs = [], []
    with gzip.open(out / "trades.jsonl.gz", "wt", encoding="utf-8") as tf, \
            gzip.open(out / "paths.jsonl.gz", "wt", encoding="utf-8") as pf:
        for sym in syms:
            fetched: dict[str, str | None] = {}
            for leg in LEGS:
                base = cfgs[leg]
                tfm = str(base["timeframe"])
                if tfm not in fetched:
                    csv = str(wd / f"{sym}__{tfm}.csv")
                    fetched[tfm] = None
                    for attempt in (1, 2):
                        try:
                            ela.fetch_candles(leg, {**base, "symbols": [sym]}, a.days, csv)
                            fetched[tfm] = csv
                            break
                        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- recorded in could_not_run with the cause; the corpus keeps going
                            err = str(exc)[-300:]
                    if fetched[tfm] is None:
                        fetched[tfm] = "FETCH_FAILED:" + err
                if str(fetched[tfm]).startswith("FETCH_FAILED"):
                    could_not.append({"symbol": sym, "leg": leg, "stage": "fetch", "reason": fetched[tfm]})
                    continue
                try:
                    trades, prows, meta = run_one(leg, base, sym, fetched[tfm], tfm, wd, a.start, a.end)
                except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- recorded in could_not_run with the cause
                    could_not.append({"symbol": sym, "leg": leg, "stage": "harness", "reason": str(exc)[-300:]})
                    continue
                for t in trades:
                    tf.write(json.dumps(t, default=str) + "\n")
                for p in prows:
                    pf.write(json.dumps(p, default=str) + "\n")
                runs.append({"symbol": sym, "leg": leg, "timeframe": tfm, "n_trades": len(trades),
                             "n_path_rows": len(prows), **meta})
                print(f"{sym} {leg}: {len(trades)} trades {len(prows)} path rows {meta['seconds']}s", flush=True)
            for f in wd.glob(f"{sym}__*.csv"):
                f.unlink()
    (out / "shard_manifest.json").write_text(json.dumps(
        {"shard": a.shard, "of": a.of, "symbols": syms, "runs": runs, "could_not_run": could_not,
         "start": a.start, "end": a.end}, indent=2) + "\n")
    return 0


# ── merge ───────────────────────────────────────────────────────────────────
def _iter_gz(p: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                yield json.loads(ln)


def merge_shards(shard_dirs: list[Path], out: Path) -> dict[str, Any]:
    """De-duplicate on ``trade_key`` across shards; write the merged gz files; return the counts."""
    out.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    n_in = 0
    per: dict[str, dict[str, int]] = {}
    keyhash = hashlib.sha256()
    runs, could_not = [], []
    with gzip.open(out / "trades.jsonl.gz", "wt", encoding="utf-8") as tf:
        for d in sorted(shard_dirs):
            sm = json.loads((d / "shard_manifest.json").read_text())
            runs += sm["runs"]
            could_not += sm["could_not_run"]
            for t in _iter_gz(d / "trades.jsonl.gz"):
                n_in += 1
                if t["trade_key"] in seen:
                    continue
                seen.add(t["trade_key"])
                c = per.setdefault(t["symbol"], {}).setdefault(t["leg"], 0)
                per[t["symbol"]][t["leg"]] = c + 1
                tf.write(json.dumps(t, default=str) + "\n")
    for k in sorted(seen):
        keyhash.update(k.encode() + b"\n")
    n_paths_in = n_paths = n_orphan = 0
    pseen: set[tuple[str, int]] = set()
    with gzip.open(out / "paths.jsonl.gz", "wt", encoding="utf-8") as pf:
        for d in sorted(shard_dirs):
            for p in _iter_gz(d / "paths.jsonl.gz"):
                n_paths_in += 1
                k = (p["trade_key"], p["bar_index"])
                if k in pseen:
                    continue
                if p["trade_key"] not in seen:
                    n_orphan += 1
                    continue
                pseen.add(k)
                n_paths += 1
                pf.write(json.dumps(p, default=str) + "\n")
    return {"trades_emitted": n_in, "trades_deduplicated": len(seen), "duplicates_removed": n_in - len(seen),
            "path_rows_emitted": n_paths_in, "path_rows_deduplicated": n_paths, "path_rows_orphan": n_orphan,
            "per_symbol_leg": {s: dict(sorted(v.items())) for s, v in sorted(per.items())},
            "trade_key_sha256": keyhash.hexdigest(), "runs": runs, "could_not_run": could_not}


def cmd_merge(a: argparse.Namespace) -> int:
    uni = json.loads(Path(a.universe).read_text())
    dirs = [d for d in sorted(Path(a.shards).iterdir()) if (d / "shard_manifest.json").exists()]
    if not dirs:
        n_ent = len(list(Path(a.shards).iterdir()))
        print(f"ERROR: 0 of {n_ent} entries under {a.shards} hold a shard_manifest.json", file=sys.stderr)
        return 2
    out = Path(a.out)
    m = merge_shards(dirs, out / "data")
    per_leg: dict[str, int] = {}
    for v in m["per_symbol_leg"].values():
        for leg, n in v.items():
            per_leg[leg] = per_leg.get(leg, 0) + n
    reasons: dict[str, int] = {}
    for c in m["could_not_run"]:
        key = f"{c['stage']}: {c['reason'][:80]}"
        reasons[key] = reasons.get(key, 0) + 1
    expected = len(uni["hash_inputs"]["symbols"]) * len(LEGS)
    manifest = {
        "schema": SCHEMA, "corpus_id": uni["corpus_id"], "hash_inputs": uni["hash_inputs"], "census": uni["census"],
        "window": {"start": a.start, "end": a.end}, "git_sha": a.git_sha, "run_id": a.run_id,
        "emit_flags": ["--emit-trades", "--emit-paths", "--emit-features"],
        "cost_stack": "harness-resolved: venue fee + slippage + perp funding (net_r; net_r_fee_only alongside); "
                      "backtest_orb.py and src/backtest/backtester.py are not used",
        "counts": {"shards": len(dirs), "symbol_leg_cells_expected": expected, "symbol_leg_cells_run": len(m["runs"]),
                   "symbol_leg_cells_could_not_run": len(m["could_not_run"]),
                   "trades_emitted": m["trades_emitted"], "trades_deduplicated": m["trades_deduplicated"],
                   "duplicates_removed": m["duplicates_removed"], "path_rows_emitted": m["path_rows_emitted"],
                   "path_rows_deduplicated": m["path_rows_deduplicated"], "path_rows_orphan": m["path_rows_orphan"],
                   "per_leg": dict(sorted(per_leg.items()))},
        "per_symbol_leg_trades": m["per_symbol_leg"], "could_not_run": m["could_not_run"],
        "could_not_run_by_reason": reasons, "trade_key": "<leg>|<symbol>|<entry_time>|<direction>",
        "trade_key_sha256": m["trade_key_sha256"],
        "data": {"location": f"Actions artifact `broad-paths-{uni['corpus_id']}-data` of run {a.run_id} (trades.jsonl.gz, "
                             "paths.jsonl.gz; NOT in the repo)", "regenerate": "same hash_inputs + git_sha reproduce it"},
        "unblocks": ["RQ-20261029-7294-01", "RQ-20261029-7294-03"],
    }
    mp = out / "manifest.json"
    mp.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest["counts"][k] for k in ("trades_deduplicated", "symbol_leg_cells_run",
                                                         "symbol_leg_cells_could_not_run")}))
    return 0


# ── self-test ───────────────────────────────────────────────────────────────
def _self_test() -> int:
    spans = {"AAAUSDT": ("2019-09", "2026-10"), "BBBUSDT": ("2019-09", "2026-09"), "OLDUSDT": ("2019-01", "2026-03"),
             "NEWUSDT": ("2025-01", "2026-10"), "EDGEUSDT": ("2024-09", "2026-09"), "LATEUSDT": ("2024-10", "2026-10"),
             "BTCUSDT_260327": ("2019-01", "2026-10")}
    sel = [r["symbol"] for r in select_universe(spans, n=10)]
    assert sel == ["AAAUSDT", "BBBUSDT", "EDGEUSDT"], sel
    assert select_universe(spans, n=2)[1]["symbol"] == "BBBUSDT"
    a1, i1 = corpus_id(select_universe(spans))
    a2, _ = corpus_id(select_universe(dict(reversed(list(spans.items())))))
    a3, _ = corpus_id(select_universe({**spans, "ZZZUSDT": ("2019-10", "2026-09")}))
    assert a1 == a2 and a1 != a3 and a1.startswith("bp2-")
    tr = [{"strategy": "trend_donchian", "symbol": "S", "entry_time": "t", "direction": "long"}]
    pr = [{"trade_key": "trend_donchian|S|t|long", "bar_index": 1}]
    stamp("trend_donchian_eth_4h", tr, pr)
    assert tr[0]["trade_key"] == pr[0]["trade_key"] == "trend_donchian_eth_4h|S|t|long"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i in (0, 1):
            d = td / f"s{i}"
            d.mkdir()
            rows = [{"trade_key": f"L|S|t{j}|long", "symbol": "S", "leg": "L"} for j in (0, 1, 2 + i)]
            with gzip.open(d / "trades.jsonl.gz", "wt") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
            with gzip.open(d / "paths.jsonl.gz", "wt") as f:
                f.writelines(json.dumps({"trade_key": r["trade_key"], "bar_index": 1}) + "\n" for r in rows)
            (d / "shard_manifest.json").write_text(json.dumps({"runs": [], "could_not_run": []}))
        m = merge_shards([td / "s0", td / "s1"], td / "o")
        assert (m["trades_emitted"], m["trades_deduplicated"], m["duplicates_removed"]) == (6, 4, 2), m
        assert m["path_rows_deduplicated"] == 4 and m["per_symbol_leg"] == {"S": {"L": 4}}
    print("self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("universe")
    u.add_argument("--out", required=True)
    u.add_argument("--end", default=END)
    u.set_defaults(fn=cmd_universe)
    s = sub.add_parser("shard")
    s.add_argument("--universe", required=True)
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--of", type=int, required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--days", type=int, default=FETCH_DAYS)
    s.add_argument("--start", default=START)
    s.add_argument("--end", default=END)
    s.set_defaults(fn=cmd_shard)
    m = sub.add_parser("merge")
    m.add_argument("--universe", required=True)
    m.add_argument("--shards", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--start", default=START)
    m.add_argument("--end", default=END)
    m.add_argument("--git-sha", default="")
    m.add_argument("--run-id", default="")
    m.set_defaults(fn=cmd_merge)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# wiring: .github/workflows/ml-data-export-kaggle.yml (stage + verify), scripts/research/compute_router.py (published-data coverage)
"""ML-DATA-OFF-TRAINER (2026-10-13): stage and verify the MARKET-ONLY ML shards that are published off the trainer.

WHY. The trainer VM is saturated (comms/cloud/compute_spare.json: 0 spare OCPU), and the ML/frontier research units
could only run there because the shards live only there. The shards the queued units read are market data only
(docs/research/ml-data-classification-2026-10-13.md); this module packages exactly those, with a manifest and
checksums, as a PRIVATE Kaggle dataset a Kaggle kernel or a GitHub runner can read.

WHAT IT GUARANTEES (each is a refusal, not a warning)
  * ONLY paths matching ``ALLOW`` are staged. Nothing else on the trainer can be shipped by editing a caller.
  * No shard column may look like OUR data (trades, fills, order packages, PnL, account, signals, outcomes).
  * The dataset is declared ``isPrivate: true``. Publishing anything public is a different decision.
  * MANIFEST.json records per-file sha256, bytes, rows, columns and first/last ts, plus ``stale_days`` -- so a stale
    shard (BTC 15m ended 2026-02-01 and SOL 15m 2023-08-12 on 2026-10-13) is VISIBLE to every consumer, not hidden.

Reads a staging tree, writes only ``--out``. No network. Tier-1 tooling.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = 1
DATASET_SLUG = "metis-market-data"
ROOT = "datasets-out"            # the layout ml_bakeoff resolves from $ML_DATA_ROOT: <ML_DATA_ROOT>/datasets-out/...

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = ("15m", "1h")
FAMILIES = ("market_features", "market_raw")
FILES = ("data.jsonl", "metadata.json")
VERSION = "v002"

#: Every path (relative to datasets-out/) this module will ever ship. Built from the four tuples above, so widening
#: the export is one reviewed edit here -- and `compute_router` reads the same list to decide which units can run off-VM.
ALLOW: List[str] = [f"{fam}/{sym}/{tf}/{VERSION}/{f}"
                    for fam in FAMILIES for sym in SYMBOLS for tf in TIMEFRAMES for f in FILES]

#: Column names that would mean a shard carries OUR data. `order_imbalance` / `order_flow` are market taker-flow
#: columns, so the order tokens are the package/account-shaped ones only.
OURS_COLUMN = re.compile(
    r"(pnl|fill_|_fill|trade_id|trade_|order_package|order_id|client_order|account|(^|_)balance|equity|position|journal|"
    r"signal_|strategy|r_multiple|^won$|^label_won|entry_price|exit_price|exit_reason|realized|api_key|secret|token)",
    re.I)


def allowed(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    return ".." not in rel.split("/") and rel in ALLOW


def covers(dataset_path: str) -> bool:
    """True when `dataset_path` (as a unit writes it, e.g. datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl,
    optionally a glob) names only published files. Used by the router: a unit may not claim published data it is not."""
    p = dataset_path.replace("\\", "/").lstrip("/")
    if not p.startswith(ROOT + "/"):
        return False
    rel = p[len(ROOT) + 1:]
    if any(ch in rel for ch in "*?["):
        hits = [a for a in ALLOW if fnmatch.fnmatch(a, rel)]
        return bool(hits) and all(allowed(a) for a in hits)
    return allowed(rel)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonl_facts(path: Path) -> Dict[str, Any]:
    rows, first, last = 0, None, None
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            if first is None:
                first = line
            last = line
            rows += 1
    if first is None:
        return {"rows": 0, "columns": [], "first_ts": None, "last_ts": None}
    f, lst = json.loads(first), json.loads(last)
    return {"rows": rows, "columns": sorted(f), "first_ts": f.get("ts"), "last_ts": lst.get("ts")}


def column_violations(columns: List[str]) -> List[str]:
    return [c for c in columns if OURS_COLUMN.search(c)]


def _stale_days(last_ts: Optional[str], now: datetime) -> Optional[float]:
    if not last_ts:
        return None
    try:
        t = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return round((now - t).total_seconds() / 86400.0, 1)


FEATURE_ROW_SLACK = 50     # market_features drops the first window/last forward-window rows of its market_raw


def _meta_rows(path: Path) -> Optional[int]:
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["row_count"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def integrity_problem(rel: str, rows: int, src: Path) -> Optional[str]:
    """None when the shard is consistent with its own metadata; otherwise why it is NOT.
    Found 2026-10-13: BTC/SOL 15m market_raw data.jsonl held 151,000 / 64,000 rows (round numbers) while their
    metadata.json said 175,296 / 175,104 -- rewritten later and cut short. A shard that disagrees with its metadata is
    withheld from the export rather than published as if it were whole."""
    parts = rel.split("/")
    if parts[0] == "market_raw":
        want = _meta_rows(src / "/".join(parts[:-1]) / "metadata.json")
        if want is not None and rows != want:
            return f"{rows} rows in data.jsonl but metadata.json row_count={want}"
    elif parts[0] == "market_features":
        want = _meta_rows(src / "market_raw" / "/".join(parts[1:-1]) / "metadata.json")
        if want is not None and not (0 <= want - rows <= FEATURE_ROW_SLACK):
            return f"{rows} rows but its market_raw metadata row_count={want} (expected within {FEATURE_ROW_SLACK})"
    return None


def build(src: Path, out: Path, *, username: str = "", now: Optional[datetime] = None, link: bool = True) -> Dict[str, Any]:
    """Stage `src` (a tree laid out as datasets-out/) into `out` and write MANIFEST.json + dataset-metadata.json.
    Missing allowed files are recorded as `absent`, never invented. Raises SystemExit on any guard violation."""
    now = now or datetime.now(timezone.utc)
    dst_root = out / ROOT
    files: List[Dict[str, Any]] = []
    absent: List[str] = []
    withheld: List[Dict[str, str]] = []
    for rel in ALLOW:
        s = src / rel
        if not s.is_file():
            absent.append(rel)
            continue
        if rel.endswith("data.jsonl"):
            bad_int = integrity_problem(rel, _jsonl_facts(s)["rows"], src)
            if bad_int:
                withheld.append({"path": f"{ROOT}/{rel}", "why": bad_int})
                continue
        elif any(w["path"] == f"{ROOT}/{rel.rsplit('/', 1)[0]}/data.jsonl" for w in withheld):
            continue                  # a withheld shard's metadata.json goes with it
        d = dst_root / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            d.unlink()
        if link:
            try:
                d.hardlink_to(s)
            except OSError:
                shutil.copy2(s, d)
        else:
            shutil.copy2(s, d)
        rec: Dict[str, Any] = {"path": f"{ROOT}/{rel}", "bytes": d.stat().st_size, "sha256": _sha256(d)}
        if rel.endswith(".jsonl"):
            facts = _jsonl_facts(d)
            bad = column_violations(facts["columns"])
            if bad:
                raise SystemExit(f"REFUSED: {rel} has column(s) that look like our own data: {bad[:8]} -- not publishing")
            rec.update(facts, stale_days=_stale_days(facts["last_ts"], now))
        files.append(rec)
    if not files:
        raise SystemExit("REFUSED: no allowed shard found under the source tree -- nothing to publish")
    manifest = {"schema": SCHEMA, "dataset": DATASET_SLUG, "generated_at": now.isoformat(), "private": True,
                "contents": "MARKET DATA ONLY: Bybit public klines/funding/OI/order-flow, public macro, model embeddings of the close series",
                "files": files, "absent": absent, "withheld": withheld,
                "stale_shards": [f["path"] for f in files if (f.get("stale_days") or 0) > 3.0]}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    (out / "dataset-metadata.json").write_text(json.dumps({
        "title": DATASET_SLUG, "id": f"{username or 'USER'}/{DATASET_SLUG}", "isPrivate": True,
        "licenses": [{"name": "other"}],
        "description": "Private. Market-only ML shards for the research queue (see MANIFEST.json)."}, indent=1) + "\n",
        encoding="utf-8")
    return manifest


def verify(root: Path) -> Dict[str, Any]:
    """Re-hash every file in `root/MANIFEST.json` and compare. Used on a GitHub runner and inside a Kaggle kernel after
    the dataset is downloaded/mounted, which is the proof the published copy equals what was staged."""
    mpath = next(iter(sorted(root.rglob("MANIFEST.json"))), None)
    if mpath is None:
        return {"ok": False, "why": "no MANIFEST.json under " + str(root)}
    base, man = mpath.parent, json.loads(mpath.read_text(encoding="utf-8"))
    bad, ok_n = [], 0
    for f in man["files"]:
        p = base / f["path"]
        if not p.is_file():
            bad.append({"path": f["path"], "why": "missing"})
        elif p.stat().st_size != f["bytes"] or _sha256(p) != f["sha256"]:
            bad.append({"path": f["path"], "why": "checksum/size mismatch"})
        else:
            ok_n += 1
    return {"ok": not bad, "files_ok": ok_n, "files_bad": bad, "stale_shards": man.get("stale_shards", []),
            "withheld": man.get("withheld", []),
            "generated_at": man.get("generated_at")}


def _self_test() -> int:
    import tempfile
    assert allowed("market_features/BTCUSDT/15m/v002/data.jsonl")
    assert not allowed("trade_outcomes/all/all/v002/data.jsonl") and not allowed("../etc/passwd")
    assert not allowed("market_features/MES/15m/v002/data.jsonl"), "licence-restricted MES stays out"
    assert covers("datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl")
    assert covers("datasets-out/market_features/*/15m/v002/data.jsonl")
    assert not covers("datasets-out/market_features/MES/15m/v002/data.jsonl")
    assert not covers("datasets-out/trade_outcomes/all/all/v002/data.jsonl")
    assert not covers("data/trade_journal.db")
    assert column_violations(["ts", "order_imbalance", "ofi", "vpin", "funding_rate"]) == []
    assert column_violations(["ts", "pnl", "order_package_id", "account_id"]) == ["pnl", "order_package_id", "account_id"]
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        src, out = Path(td) / "s", Path(td) / "o"
        d = src / "market_features/BTCUSDT/15m/v002"
        d.mkdir(parents=True)
        (d / "data.jsonl").write_text('{"ts":"2026-02-01T00:00:00Z","log_return":0.1}\n{"ts":"2026-02-01T00:15:00Z","log_return":0.2}\n')
        (d / "metadata.json").write_text("{}")
        m = build(src, out, username="u", now=now)
        assert m["files"][0]["rows"] == 2 and m["stale_shards"] and m["files"][0]["stale_days"] > 200, m
        assert verify(out)["ok"]
        (out / ROOT / "market_features/BTCUSDT/15m/v002/data.jsonl").write_text("tampered\n")
        assert not verify(out)["ok"]
        (d / "data.jsonl").write_text('{"ts":"2026-02-01T00:00:00Z","pnl":1.0}\n')
        try:
            build(src, Path(td) / "o2", username="u", now=now)
        except SystemExit as e:
            assert "REFUSED" in str(e)
        else:
            raise AssertionError("a pnl column must be refused")
        # a truncated market_raw (data.jsonl shorter than its own metadata) is withheld, with its features
        t_src, t_out = Path(td) / "t", Path(td) / "t_out"
        for fam, n_meta in (("market_raw", 5), ("market_features", 4)):
            d = t_src / fam / "BTCUSDT/15m/v002"
            d.mkdir(parents=True)
            rows = 2 if fam == "market_raw" else 2
            (d / "data.jsonl").write_text("".join('{"ts":"2026-10-12T00:%02d:00Z","log_return":0.1}\n' % (i * 15) for i in range(rows)))
            (d / "metadata.json").write_text(json.dumps({"row_count": n_meta if fam == "market_raw" else 2}))
        e_dir = t_src / "market_features/ETHUSDT/15m/v002"
        e_dir.mkdir(parents=True)
        (e_dir / "data.jsonl").write_text('{"ts":"2026-10-12T00:00:00Z","log_return":0.1}\n')
        (e_dir / "metadata.json").write_text(json.dumps({"row_count": 1}))
        er = t_src / "market_raw/ETHUSDT/15m/v002"
        er.mkdir(parents=True)
        (er / "data.jsonl").write_text('{"ts":"2026-10-12T00:00:00Z","close":1}\n')
        (er / "metadata.json").write_text(json.dumps({"row_count": 1}))
        m2 = build(t_src, t_out, username="u", now=now)
        wp = {w["path"] for w in m2["withheld"]}
        assert "datasets-out/market_raw/BTCUSDT/15m/v002/data.jsonl" in wp, m2["withheld"]
        shipped = {f["path"] for f in m2["files"]}
        assert not any("BTCUSDT" in p and p.endswith("data.jsonl") for p in shipped if "market_raw" in p), shipped
        assert "datasets-out/market_features/ETHUSDT/15m/v002/data.jsonl" in shipped, shipped
    print("market_data_export self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("self-test")
    sub.add_parser("list-paths", help="print the allowlisted paths relative to datasets-out/ (an rsync --files-from list)")
    b = sub.add_parser("build")
    b.add_argument("--src", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--username", default="")
    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        return _self_test()
    if a.cmd == "list-paths":
        print("\n".join(ALLOW))
        return 0
    if a.cmd == "build":
        m = build(Path(a.src), Path(a.out), username=a.username)
        print(json.dumps({"files": len(m["files"]), "absent": len(m["absent"]), "withheld": m["withheld"], "stale_shards": m["stale_shards"],
                          "bytes": sum(f["bytes"] for f in m["files"])}))
        return 0
    if a.cmd == "verify":
        r = verify(Path(a.root))
        print(json.dumps(r))
        return 0 if r["ok"] else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

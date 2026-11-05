#!/usr/bin/env python3
"""Dry contention soak for TICK-STAGE2-RECONCILE-OFFTICK. Touches no venue, no live DB.

Runs, against a temporary WAL journal, the REAL modules in this change:
  * src.runtime.reconcile_loop  - the reconciliation thread (fake pass: a few
    short journal writes plus a sleep standing in for venue calls);
  * src.runtime.journal_sync    - the lock, also taken by a fake "entry dispatch"
    thread that writes a trade row while holding it;
  * src.runtime.position_telemetry.write_record on a thread NAMED like the exit
    loop, 15 packages per pass, 30 s cadence scaled down by --scale;
  * a FOREIGN writer (a second sqlite connection) that holds BEGIN IMMEDIATE for
    --hold seconds every --every seconds. That shape reproduces the
    2026-11-05T08:00:30-08:01:12Z journal lock burst.

Reports: exit-pass completion-to-completion max vs the 60 s requirement (scaled),
dispatch lock wait max, reconciliation passes/failures, and any deadlock (a thread
that stops completing). Exit 0 when the scaled requirement holds and nothing wedged.

    python3 scripts/ops/soak_reconcile_offtick.py --seconds 60 --scale 0.1
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--scale", type=float, default=0.1,
                    help="time compression: 0.1 => a 30 s exit cadence runs at 3 s")
    ap.add_argument("--hold", type=float, default=8.0, help="foreign lock hold, unscaled s")
    ap.add_argument("--every", type=float, default=20.0, help="foreign lock period, unscaled s")
    ap.add_argument("--packages", type=int, default=15)
    ap.add_argument("--legacy", action="store_true",
                    help="exit writes use the pre-change 5 s busy timeout (control run)")
    a = ap.parse_args(argv)
    S = a.scale

    from src.runtime import journal_sync as js
    from src.runtime import position_telemetry as pt
    from src.runtime import reconcile_loop as rl

    tmp = tempfile.mkdtemp(prefix="soak-recon-")
    db = os.path.join(tmp, "j.db")
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, sym TEXT, ts REAL)")
        c.execute(f"""CREATE TABLE {pt.TABLE} (
            order_package_id TEXT PRIMARY KEY, trade_id TEXT, strategy TEXT,
            symbol TEXT, account_id TEXT, direction TEXT, entry REAL,
            risk_per_unit REAL, last_price REAL, open_r REAL, peak_r REAL,
            peak_state TEXT, giveback_r REAL, bars_held INTEGER,
            bars_since_peak INTEGER, cap_r REAL, pct_of_cap REAL,
            r_to_stop REAL, r_to_target REAL, rr_from_here REAL,
            peak_provenance TEXT, levers TEXT, updated_at TEXT,
            peak_authoritative INTEGER)""")

    import re
    base_rec = {k: None for k in re.findall(r":(\w+)", pt._UPSERT.split("ON CONFLICT")[0])}
    base_rec.update(symbol="X", account_id="a", strategy="s", updated_at="t")
    # Positive control: an uncontended write must land, or the soak measures nothing.
    assert pt.write_record(dict(base_rec, order_package_id="ctl", peak_r=0.0), db_path=db)

    stop = threading.Event()
    out = {"exit_intervals_ms": [], "dispatch_wait_ms": [], "dispatches": 0,
           "foreign_holds": 0, "exit_write_skipped": 0}
    # Scaled exit-write bound: the real one is 0.25 s; scale it with the clock.
    os.environ["EXIT_LOOP_DB_WRITE_TIMEOUT_SECONDS"] = str(
        5.0 * S if a.legacy else 0.25 * S)
    os.environ["RECONCILE_LOOP_INTERVAL_SECONDS"] = str(60.0 * S)

    real_wbt = js.write_busy_timeout

    def scaled_wbt(default):  # telemetry passes 5.0; scale the non-exit default too
        return real_wbt(default * S)

    js.write_busy_timeout = scaled_wbt

    def foreign():
        while not stop.wait(a.every * S):
            con = sqlite3.connect(db, isolation_level=None)
            con.execute("BEGIN IMMEDIATE")
            out["foreign_holds"] += 1
            stop.wait(a.hold * S)
            con.execute("ROLLBACK")
            con.close()

    def exit_loop():
        last = None
        while not stop.is_set():
            t0 = time.monotonic()
            for i in range(a.packages):
                time.sleep(0.05 * S)  # candle fetch + monitor()
                rec = dict(base_rec, order_package_id=f"pkg-{i}", peak_r=random.random())
                if not pt.write_record(rec, db_path=db):
                    out["exit_write_skipped"] += 1
            now = time.monotonic()
            if last is not None:
                out["exit_intervals_ms"].append((now - last) * 1000.0 / S)
            last = now
            slack = 30.0 * S - (now - t0)
            if slack > 0:
                stop.wait(slack)

    def dispatcher():
        while not stop.wait(random.uniform(5, 15) * S):
            t0 = time.monotonic()
            with js.journal_sync("entry_dispatch"):
                out["dispatch_wait_ms"].append((time.monotonic() - t0) * 1000.0 / S)
                time.sleep(2.0 * S)  # venue place
                con = sqlite3.connect(db, timeout=3.0)
                try:
                    con.execute("INSERT INTO trades (sym, ts) VALUES ('X', ?)", (time.time(),))
                    con.commit()
                except sqlite3.OperationalError:
                    pass
                finally:
                    con.close()
                out["dispatches"] += 1

    def recon_pass():
        time.sleep(random.uniform(20, 28) * S)  # venue reads
        con = sqlite3.connect(db, timeout=3.0)
        try:
            con.execute("UPDATE trades SET ts = ts WHERE id IN (SELECT id FROM trades LIMIT 5)")
            con.commit()
        finally:
            con.close()
        if random.random() < 0.1:
            raise RuntimeError("injected venue timeout")

    threads = [threading.Thread(target=foreign, daemon=True),
               threading.Thread(target=exit_loop, name=js.EXIT_LOOP_THREAD_NAME, daemon=True),
               threading.Thread(target=dispatcher, daemon=True)]
    for t in threads:
        t.start()
    rl.start(recon_pass)
    deadline = time.monotonic() + a.seconds
    while time.monotonic() < deadline:
        rl.ensure_running(recon_pass, send=lambda m: print("FLAG:", m))
        time.sleep(1.0)
    stop.set()
    st = rl.status()
    iv = out["exit_intervals_ms"]
    res = {
        "mode": "legacy_5s_exit_writes" if a.legacy else "bounded_exit_writes",
        "scale": S, "seconds_wall": a.seconds,
        "exit_intervals_n": len(iv),
        "exit_interval_max_ms_unscaled": round(max(iv), 1) if iv else None,
        "exit_interval_over_60s": sum(1 for x in iv if x > 60000.0),
        "exit_write_skipped": out["exit_write_skipped"],
        "dispatches": out["dispatches"],
        "dispatch_wait_max_ms_unscaled": round(max(out["dispatch_wait_ms"]), 1)
        if out["dispatch_wait_ms"] else None,
        "foreign_holds": out["foreign_holds"],
        "reconcile_passes": st.get("passes"), "reconcile_failures": st.get("failures"),
        "reconcile_thread_alive": st.get("thread_alive"),
    }
    print(json.dumps(res, indent=2))
    ok = (iv and res["exit_interval_over_60s"] == 0 and res["reconcile_thread_alive"]
          and (st.get("passes") or 0) >= 2 and out["dispatches"] >= 1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

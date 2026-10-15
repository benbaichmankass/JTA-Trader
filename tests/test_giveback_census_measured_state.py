"""giveback_census: a measured peak is graded, and a non-measured read_state never writes n=0.

Run 38540458035 (RQ-20261014-9807-01) exited 1 on the trainer. Two defects stacked:
  1. `census()` dropped every telemetry row with a truthy `peak_state`, but a measured row carries
     the literal "measured" -- so all 591 live rows were excluded and read_state became no_data.
  2. On no_data the producer passed population.n = 0; research_result.write refuses that
     ("never fabricate the reassuring value"), so the run crashed instead of recording no_data.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import giveback_census as gc  # noqa: E402

TEL = {"peak_r": 2.0, "peak_state": "measured", "open_r": 0.5, "terminal_state": "final",
       "peak_provenance": "measured", "risk_per_unit": 1}
TRADE = {"status": "closed", "account_class": "real_money", "strategy_name": "s1",
         "timestamp": "2026-10-01T00:00:00Z", "closed_at": "2026-10-02T00:00:00Z",
         "pnl": 1.0, "position_size": 1}


def test_measured_peak_state_is_graded():
    c = gc.census([{**TEL, "order_package_id": "a"}], [{**TRADE, "order_package_id": "a"}], min_n=1)
    assert c["n_graded"] == 1 and c["excluded"]["no_peak"] == 0


def test_reason_states_are_still_excluded():
    for st in ("thin_window", "unanchored", "no_risk"):
        c = gc.census([{**TEL, "order_package_id": "a", "peak_state": st}],
                      [{**TRADE, "order_package_id": "a"}], min_n=1)
        assert c["n_graded"] == 0 and c["excluded"]["no_peak"] == 1, st


def test_no_data_with_out_writes_a_record_instead_of_crashing(tmp_path):
    db = tmp_path / "j.db"
    con = sqlite3.connect(db)
    con.execute("create table position_telemetry(order_package_id text, peak_r real, peak_state text, "
                "open_r real, risk_per_unit real, terminal_state text, peak_provenance text, "
                "strategy text, account_id text)")
    con.execute("create table trades(order_package_id text, status text, timestamp text, closed_at text, "
                "pnl real, position_size real, account_class text, strategy_name text, exit_price real, "
                "exit_reason text)")
    con.commit()
    con.close()
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/giveback_census.py"), "--db", str(db),
                        "--unit", "RQ-20261014-9807-01", "--out", str(tmp_path / "o")],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr[-400:]
    assert "no_data" in r.stdout


def test_out_dir_gets_a_verdict_json_the_runner_can_derive_from(tmp_path):
    """script_run.derive_record lands a run as producer_failed unless <out>/verdict.json exists and is well-formed."""
    import json

    import script_run as sr  # noqa: E402

    db = tmp_path / "j.db"
    con = sqlite3.connect(db)
    con.execute("create table position_telemetry(order_package_id text, peak_r real, peak_state text, "
                "open_r real, risk_per_unit real, terminal_state text, peak_provenance text, "
                "strategy text, account_id text)")
    con.execute("create table trades(order_package_id text, status text, timestamp text, closed_at text, "
                "pnl real, position_size real, account_class text, strategy_name text, exit_price real, "
                "exit_reason text)")
    con.execute("insert into position_telemetry values('a',2.0,'measured',0.5,1,'final','measured','s1','x')")
    con.execute("insert into trades values('a','closed','2026-10-01T00:00:00Z','2026-10-02T00:00:00Z',"
                "1.0,1.0,'real_money','s1',1.0,'tp')")
    con.commit()
    con.close()
    out = tmp_path / "o"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/giveback_census.py"), "--db", str(db),
                        "--unit", "RQ-20261014-9807-01", "--out", str(out), "--min-n", "1"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr[-400:]
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["n"] == 1 and v["verdict"] == "pass" and v["population"]
    assert v["verdict"] in sr.VERDICTS and v["read_state"] in sr.READ_STATES

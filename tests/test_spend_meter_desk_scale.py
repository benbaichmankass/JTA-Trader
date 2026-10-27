"""DESK-10-CAPACITY: the desk scale lines in spend_meter --capacity."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ops import spend_meter as sm

ROOT = Path(__file__).resolve().parents[1]


def by(lines, prefix):
    return [d for d in lines if d["label"].startswith(prefix)]


def test_wake_stats_arithmetic():
    s = sm.desk_wake_stats([("a", "t", 0.4), ("b", "t", 0.6), ("c", "t", 1.1)])
    assert s["n"] == 3 and s["median"] == 0.6 and s["min"] == 0.4 and s["max"] == 1.1
    assert s["mean"] == pytest.approx(0.7)
    assert sm.desk_wake_stats([])["mean"] is None          # no sample is None, never 0


def test_committed_sample_matches_the_measured_population():
    s = sm.desk_wake_stats()
    assert s["n"] == 10 and len({i for i, _, _ in sm.DESK_WAKE_SAMPLES}) == 10
    assert s["mean"] == pytest.approx(0.6181, abs=1e-4)


def test_hourly_and_15min_lines():
    lines = sm.desk_scale_lines()
    h, q = by(lines, "hourly")[0], by(lines, "15-minute")[0]
    assert h["provenance"] == "measured" and h["n"] == 10
    assert h["usd_per_week"] == pytest.approx(h["usd_per_decision"] * 168)
    assert q["provenance"] == "estimated" and q["n"] == 0    # no 15-minute wake was ever run
    assert q["usd_per_week"] == pytest.approx(h["usd_per_week"] * 4)


def test_judged_run_lines_cover_sizes_and_routes():
    lines = sm.desk_scale_lines()
    for n in (200, 300, 1000):
        api = by(lines, f"DESK-18 judged run, {n} packets, API")[0]
        ses = by(lines, f"DESK-18 judged run, {n} packets, session")[0]
        assert api["usd_per_week"] == pytest.approx(api["usd_per_decision"] * n)
        assert ses["usd_per_week"] == pytest.approx(16.84 / 50 * n)
        assert api["provenance"] == "estimated" and ses["provenance"] == "measured"
        assert api["usd_per_decision"] < ses["usd_per_decision"] / 10   # the reason the API path exists


def test_api_estimate_reads_the_driver_and_stays_under_the_worst_case_guard():
    from scripts.research import desk_judge_api as dja
    e = sm.desk_api_usd_per_packet()
    assert e["mean"] < e["ceiling"] < e["worst_case_guard"]
    chars = sm.JUDGE_PACKET_CHARS + sm.JUDGE_PROTOCOL_CHARS + len(dja.USER_TMPL)
    assert e["worst_case_guard"] == pytest.approx(dja.worst_case_cost(chars, dja.PRICES))


def test_every_line_names_population_currency_and_a_known_grade():
    for d in sm.desk_scale_lines():
        assert d["population"] and d["currency"] and isinstance(d["n"], int)
        assert d["provenance"] in ("measured", "estimated", "unverified")


def test_cli_prints_and_json_carries_desk_scale():
    r = subprocess.run([sys.executable, "scripts/ops/spend_meter.py", "--capacity", "--json"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert len(json.loads(r.stdout)["desk_scale"]) == 8
    r2 = subprocess.run([sys.executable, "scripts/ops/spend_meter.py", "--capacity"],
                        cwd=ROOT, capture_output=True, text=True)
    assert "DESK SCALE" in r2.stdout and "two currencies" in r2.stdout

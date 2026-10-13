"""QUEUE-FILL-1013B -- scripts/research/macro_event_study_run.py: the registered rule, and an end-to-end run on fixtures."""
from __future__ import annotations

import json
import math

from scripts.research import macro_event_study_run as m


def _rows(n, t, ic):
    return [{"horizon_days": 1, "n": n, "ic": ic, "ic_t_eff": t}]


def test_pass_requires_n_t_and_sign():
    kw = dict(primary=[1], min_n=100, t_bar=2.4, expected_sign="negative")
    assert m.grade(_rows(200, -3.0, -0.2), **kw)["verdict"] == "pass"
    assert m.grade(_rows(200, 3.0, 0.2), **kw)["verdict"] == "fail"       # significant, WRONG sign: not a pass
    assert "WRONG-sign" in m.grade(_rows(200, 3.0, 0.2), **kw)["note"]
    assert m.grade(_rows(200, -1.0, -0.1), **kw)["verdict"] == "fail"
    assert m.grade(_rows(50, -3.0, -0.2), **kw)["verdict"] == "indeterminate"  # n bounded by the source
    assert m.grade([], **kw)["read_state"] == "no_data"


def test_end_to_end_on_fixtures(tmp_path):
    # planted negative relation: bigger surprise -> lower next-day return, 150 weekly releases
    import random
    rnd = random.Random(3)
    from datetime import date, timedelta
    d0 = date(2020, 1, 2)
    px, price = [], 100.0
    for i in range(1200):
        px.append((d0 + timedelta(days=i)).isoformat())
    closes = {}
    rel = []
    for k in range(150):
        day = d0 + timedelta(days=7 * k)
        s = rnd.gauss(0, 1)
        rel.append((day, s))
    # build closes: a flat random walk with a -0.01*surprise jump the day after each release
    jump = {(day + timedelta(days=1)).isoformat(): -0.01 * s for day, s in rel}
    for ds in px:
        price *= 1.0 + jump.get(ds, 0.0) + rnd.gauss(0, 0.0005)
        closes[ds] = price
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "NG=F.csv").write_text("date,close\n" + "\n".join(f"{k},{v}" for k, v in closes.items()))
    lines = [json.dumps({"kind": "eia_natgas_storage", "status": "resolved", "scheduled_for": day.isoformat(),
                         "observed_at": "2020-01-01T00:00:00Z",
                         "realized_outcome": {"surprise": s, "actual": 1.0, "consensus": 0.0, "change": 0.0}})
             for day, s in rel]
    (tmp_path / "snap.jsonl").write_text("\n".join(lines) + "\n")
    out = tmp_path / "out"
    assert m.main(["--kind", "eia_natgas_storage", "--snapshots", str(tmp_path / "snap.jsonl"),
                   "--candles-dir", str(tmp_path / "candles"), "--horizons", "1,3", "--primary-horizons", "1",
                   "--min-n", "100", "--t-bar", "2.4", "--expected-sign", "negative", "--out", str(out)]) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] == "pass", v
    assert v["n"] >= 100 and math.isfinite(v["measurement"]["per_horizon"][0]["ic_t_eff"])
    assert (out / "scorecard.json").exists()


def test_empty_panel_is_no_data_not_a_verdict(tmp_path):
    (tmp_path / "candles").mkdir()
    (tmp_path / "snap.jsonl").write_text("")
    out = tmp_path / "o"
    m.main(["--kind", "eia_natgas_storage", "--snapshots", str(tmp_path / "snap.jsonl"),
            "--candles-dir", str(tmp_path / "candles"), "--out", str(out)])
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "no_data" and v["verdict"] == "not_applicable"

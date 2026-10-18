"""holdout_incumbent_compare: selected vs declared arm on the verdict's own held-back span (synthetic run dir)."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research")]

import holdout_incumbent_compare as h  # noqa: E402


def _run(tmp_path, a_rows, c_rows, holdout):
    arms = tmp_path / "arms"
    arms.mkdir()
    for name, rows in (("A", a_rows), ("C1", c_rows)):
        (arms / f"{name}__trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    v = {"verdict": "pass", "measurement": {"leg": "leg", "grade": {
        "selected": "C1", "plan": {"boundary": "2025-01-01 00:00:00+00:00"}, "holdout": holdout}}}
    p = tmp_path / "verdict.json"
    p.write_text(json.dumps(v))
    return p


def _t(when, r):
    return {"entry_time": when, "net_r": r}


def test_baseline_beats_selected_and_reproduces(tmp_path):
    a = [_t("2024-06-01 00:00:00+00:00", 9.0), _t("2025-02-01 00:00:00+00:00", 3.0), _t("2025-03-01 00:00:00+00:00", 2.0)]
    c = [_t("2024-07-01 00:00:00+00:00", 9.0), _t("2025-02-02 00:00:00+00:00", 1.5)]
    r = h.compare(_run(tmp_path, a, c, {"n": 1, "net_r": 1.5}))
    assert r["selected_holdout"] == {"n": 1, "net_r": 1.5, "expectancy_r": 1.5}
    assert r["baseline_holdout"] == {"n": 2, "net_r": 5.0, "expectancy_r": 2.5}
    assert r["state"] == "baseline_beats_selected" and r["selected_minus_baseline_r"] == -3.5
    assert r["reproduces_verdict"] is True


def test_mismatch_with_verdict_is_flagged(tmp_path):
    a = [_t("2025-02-01 00:00:00+00:00", 1.0)]
    c = [_t("2025-02-01 00:00:00+00:00", 2.0)]
    r = h.compare(_run(tmp_path, a, c, {"n": 1, "net_r": 7.0}))
    assert r["state"] == "selected_beats_baseline" and r["reproduces_verdict"] is False


def test_no_holdout_read(tmp_path):
    p = tmp_path / "verdict.json"
    p.write_text(json.dumps({"verdict": "fail", "measurement": {"leg": "x", "grade": {"selected": None, "holdout": None}}}))
    assert h.compare(p)["state"] == "no_holdout_read"

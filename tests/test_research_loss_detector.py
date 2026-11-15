"""E57: the research loss detector's own self-test, run under pytest so a
regression in it reds CI rather than waiting for its next scheduled run."""
import importlib.util
import io
import json as _json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_P = Path(__file__).resolve().parents[1] / "scripts/ops/research_loss_detector.py"
_spec = importlib.util.spec_from_file_location("research_loss_detector", _P)
rld = importlib.util.module_from_spec(_spec)
sys.modules["research_loss_detector"] = rld
_spec.loader.exec_module(rld)


def test_self_test_passes():
    assert rld._self_test() == 0


def test_could_not_read_is_never_clean():
    # The collapsed-states rule, asserted directly: "we did not look" must
    # never be reported as "nothing lost".
    rep = {"overall": rld.COULD_NOT_READ, "generated_at": "t", "questions": {
        "A_stuck_research_prs": {"state": rld.COULD_NOT_READ, "error": "boom",
                                 "findings": None}}}
    assert "COULD NOT READ" in rld.alert_text(rep)
    assert rld.CLEAN != rld.COULD_NOT_READ


# ---- RESEARCH-LOSS-DETECTOR-RED: question C must survive an intermittent 500 ----
_NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def _http_err(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


class _Resp:
    def __init__(self, body):
        self._b = _json.dumps(body).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_api_retries_a_transient_500_then_reads():
    calls = {"n": 0}

    def fake_open(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_err(500)
        return _Resp({"ok": 1})

    with mock.patch.object(rld.urllib.request, "urlopen", side_effect=fake_open), \
            mock.patch.object(rld.time, "sleep"):
        assert rld._api("actions/artifacts", "o/r") == {"ok": 1}
    assert calls["n"] == 3


def test_api_persistent_500_is_could_not_read_not_empty():
    with mock.patch.object(rld.urllib.request, "urlopen", side_effect=_http_err(500)), \
            mock.patch.object(rld.time, "sleep"):
        try:
            rld._api("actions/artifacts", "o/r")
        except rld.CouldNotRead:
            return
    raise AssertionError("a persistent 500 must raise CouldNotRead")


def test_api_404_is_not_retried():
    with mock.patch.object(rld.urllib.request, "urlopen", side_effect=_http_err(404)) as m, \
            mock.patch.object(rld.time, "sleep"):
        try:
            rld._api("x", "o/r")
        except rld.CouldNotRead:
            pass
    assert m.call_count == 1


def _per_run_fake(bulk_ok, orphan=True):
    exp = (_NOW + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    art = {"id": 7, "name": "exit-lever-sweep-x", "expired": False, "expires_at": exp,
           "workflow_run": {"id": 555}}

    def fake_paged(path, repo, key, limit=1000):
        if path == "actions/artifacts":
            if not bulk_ok:
                raise rld.CouldNotRead("GET ...artifacts?page=1: HTTP Error 500")
            return [dict(art)]
        if path.startswith("actions/workflows/m20-exit-lever-sweep.yml/runs"):
            return [{"id": 555}]
        if path.startswith("actions/workflows/"):
            return []
        raise AssertionError(path)

    def fake_api(path, repo):
        if path.startswith("actions/runs/555/artifacts"):
            return {"artifacts": [dict(art)]}
        if path == "actions/runs/555":
            return {"path": ".github/workflows/m20-exit-lever-sweep.yml"}
        raise AssertionError(path)
    return fake_paged, fake_api


def _run_q(bulk_ok, mentioned):
    fp, fa = _per_run_fake(bulk_ok)
    with mock.patch.object(rld, "_paged", side_effect=fp), \
            mock.patch.object(rld, "_api", side_effect=fa), \
            mock.patch.object(rld, "research_workflow_files",
                              return_value=["m20-exit-lever-sweep.yml"]), \
            mock.patch.object(rld, "run_ids_mentioned", return_value=mentioned):
        return rld.q_expiring("o/r", _NOW, 72, "HEAD")


def test_bulk_500_falls_back_to_per_run_and_still_reads():
    q = _run_q(bulk_ok=False, mentioned=set())
    assert q["state"] == rld.FINDINGS and q["read_via"].startswith("per-run FALLBACK")
    assert [f["run_id"] for f in q["findings"]] == ["555"]
    assert "FALLBACK" in q["population"] and "NOT examined" in q["read_via"]


def test_positive_control_bulk_path_agrees_with_fallback():
    q = _run_q(bulk_ok=True, mentioned=set())
    assert q["read_via"] == "bulk" and q["state"] == rld.FINDINGS
    assert [f["run_id"] for f in q["findings"]] == ["555"]
    # landed copy present -> clean on both paths
    assert _run_q(True, {"555"})["state"] == rld.CLEAN
    assert _run_q(False, {"555"})["state"] == rld.CLEAN


def test_both_paths_down_stays_could_not_read():
    def dead(*a, **k):
        raise rld.CouldNotRead("500")
    with mock.patch.object(rld, "_paged", side_effect=dead), \
            mock.patch.object(rld, "_api", side_effect=dead), \
            mock.patch.object(rld, "research_workflow_files", return_value=["a.yml"]):
        rep = rld.sweep("o/r", "HEAD", 6, 1, 72)
    assert rep["questions"]["C_expiring_unlanded_artifacts"]["state"] == rld.COULD_NOT_READ
    assert rep["overall"] == rld.COULD_NOT_READ


def test_gdelt_panel_producer_is_not_research():
    assert rld.is_research_workflow("news-gdelt-panel.yml") is False
    assert rld.is_research_workflow("research-exit-head-build.yml") is True


# ---- RESEARCH-LOSS-M20-UNLANDED: a recorded disposition closes a run that can never land ----
def test_disposition_requires_a_reason_and_is_counted(tmp_path):
    d = tmp_path / "docs/claude/work"
    d.mkdir(parents=True)
    (d / "RESEARCH-LOSS-DISPOSITIONS.json").write_text(_json.dumps({
        "1": {"disposition": "retired", "reason": "died in plan; nothing to land", "ref": "X"},
        "2": {"disposition": "retired", "reason": "  "},
        "3": "not a dict"}))
    got = rld.load_dispositions(tmp_path)
    assert set(got) == {"1"}
    assert rld.load_dispositions(tmp_path / "missing") == {}

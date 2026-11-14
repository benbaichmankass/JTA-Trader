"""schedule-keeper: the slot/dedupe logic, and that every TARGET is wired.

A target the keeper dispatches WITHOUT a dedupe job would run twice per slot
(once dispatched, once when GitHub's late cron arrives). A dedupe job whose
main job does not `needs:` it decides nothing. Both halves are pinned here.
"""
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import schedule_keeper as sk  # noqa: E402


def test_self_test_passes():
    r = subprocess.run([sys.executable, "scripts/ops/schedule_keeper.py", "--self-test"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_target_exists_is_scheduled_and_dedupes():
    for wf in sk.TARGETS:
        path = REPO / ".github" / "workflows" / wf
        assert path.exists(), wf
        d = yaml.safe_load(path.read_text())
        on = d.get(True) or d.get("on")
        assert on.get("schedule"), f"{wf} has no schedule"
        assert "workflow_dispatch" in on, f"{wf} cannot be dispatched by the keeper"
        for c in sk.workflow_crons(str(path)):
            sk.parse_cron(c)  # the keeper's grammar must cover every target cron
        jobs = d["jobs"]
        if sk.TARGETS[wf].get("self_dedupes"):
            # declared idempotent per slot; the reason must be real text, and such a target
            # must not ALSO carry a half-wired dedupe job
            assert len(sk.TARGETS[wf]["self_dedupes"]) > 20, wf
            assert "dedupe" not in jobs, f"{wf}: declare self_dedupes OR a dedupe job, not both"
            continue
        assert "dedupe" in jobs, f"{wf} lacks the dedupe job"
        assert jobs["dedupe"]["if"] == "github.event_name == 'schedule'"
        others = [k for k in jobs if k != "dedupe"]
        for k in others:
            needs = jobs[k].get("needs")
            needs = [needs] if isinstance(needs, str) else (needs or [])
            if "dedupe" in needs:
                cond = str(jobs[k].get("if", ""))
                assert "!cancelled()" in cond and "needs.dedupe.outputs.skip != 'true'" in cond, (
                    f"{wf}:{k} must fail OPEN (!cancelled()) and honour skip")
        assert any("dedupe" in (jobs[k].get("needs") or []) for k in others), (
            f"{wf}: no job needs dedupe, so the skip decides nothing")


def test_keeper_workflow_pages_only_on_its_paging_cron():
    d = yaml.safe_load((REPO / ".github/workflows/schedule-keeper.yml").read_text())
    crons = [s["cron"] for s in d[True]["schedule"]]
    page = [s for s in d["jobs"]["keep"]["steps"] if s.get("name", "").startswith("Page")][0]
    assert any(c in page["if"] for c in crons)
    assert "push" in d[True], "the keeper must not depend only on the scheduler it compensates for"


def test_research_slo_is_kept_planted_and_clean():
    """research-slo's `41 */2` cron never fired (2026-10-16): it must stay a keeper target.

    planted: the real target is registered with a 2-hourly-fit stale window and a declared dedupe.
    clean: a workflow that is NOT a target (a made-up one) is absent, so the check can fail.
    """
    t = sk.TARGETS["research-slo.yml"]
    assert t["stale_hours"] == 3
    assert t["self_dedupes"]
    assert "research-slo-not-a-real-workflow.yml" not in sk.TARGETS


def _http_err(code):
    import urllib.error
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", {}, None)


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_api_retries_a_transient_502_then_succeeds(monkeypatch):
    """Run 43598757422 (2026-11-14): one GitHub 502 crashed the keep pass. It is now retried."""
    calls = []

    def fake(req, timeout):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise _http_err(502)
        return _Resp(b'{"ok": 1}')
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(sk.urllib.request, "urlopen", fake)
    monkeypatch.setattr(sk, "_sleep", lambda s: None)
    assert sk._api("/x") == {"ok": 1} and len(calls) == 3


def test_api_does_not_retry_a_real_4xx_and_gives_up_after_bounded_attempts(monkeypatch):
    import pytest
    calls = []
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(sk, "_sleep", lambda s: None)
    monkeypatch.setattr(sk.urllib.request, "urlopen", lambda req, timeout: calls.append(1) or (_ for _ in ()).throw(_http_err(404)))
    with pytest.raises(Exception):
        sk._api("/x")
    assert len(calls) == 1
    calls.clear()
    monkeypatch.setattr(sk.urllib.request, "urlopen", lambda req, timeout: calls.append(1) or (_ for _ in ()).throw(_http_err(503)))
    with pytest.raises(Exception):
        sk._api("/x")
    assert len(calls) == sk.API_ATTEMPTS


def test_keep_skips_one_unreadable_target_and_finishes_the_pass(monkeypatch, tmp_path, capsys):
    targets = list(sk.TARGETS)
    bad = targets[0]

    def runs(wf):
        if wf == bad:
            raise _http_err(502)
        return []
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(sk, "_runs", runs)
    monkeypatch.setattr(sk, "_api", lambda *a, **k: None)
    rc = sk.cmd_keep(type("A", (), {"dry_run": True})())
    text = capsys.readouterr().out
    assert rc == 0
    assert f"could_not_look: {bad}" in text
    for wf in targets[1:]:
        assert f"{wf}: slot" in text            # every other target was still decided
    assert f"could_not_look={bad}" in out.read_text()

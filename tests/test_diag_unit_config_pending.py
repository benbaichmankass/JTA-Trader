"""DEPLOY-UNIT-RESTART-DETECT: /api/diag/version flags a unit whose installed unit
file / drop-in is newer than its running process (MEASURED 2026-11-12, #25185:
web-api restarted on the OLD unit and restart_pending read False)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.web.api.routers import diag

U = "ict-web-api.service"
START = "Thu 2026-11-12 10:08:33 UTC"
T0 = datetime(2026, 11, 12, 10, 8, 33, tzinfo=timezone.utc).timestamp()


def _show(**props):
    base = {"FragmentPath": "/etc/systemd/system/ict-web-api.service", "DropInPaths": "",
            "ActiveEnterTimestamp": START, "NeedDaemonReload": "no"}
    base.update(props)
    return lambda units, _p: {U: base}


def _run(show, mtimes):
    return diag._unit_config_pending([U], show=show, mtime=lambda p: mtimes[p])[U]


def test_unit_file_installed_after_the_restart_is_pending():
    # The #25185 sequence: restart 10:08:33, unit rewritten 10:16:50.
    assert _run(_show(), {"/etc/systemd/system/ict-web-api.service": T0 + 497}) is True


def test_a_drop_in_newer_than_the_process_is_pending():
    show = _show(DropInPaths="/etc/systemd/system/ict-web-api.service.d/venv.conf")
    assert _run(show, {"/etc/systemd/system/ict-web-api.service": T0 - 3600,
                       "/etc/systemd/system/ict-web-api.service.d/venv.conf": T0 + 60}) is True


def test_config_older_than_the_process_is_not_pending():
    assert _run(_show(), {"/etc/systemd/system/ict-web-api.service": T0 - 5}) is False
    # same second as the start: not newer (systemd timestamps are whole seconds)
    assert _run(_show(), {"/etc/systemd/system/ict-web-api.service": T0 + 0.5}) is False


def test_daemon_reload_pending_is_pending():
    assert _run(_show(NeedDaemonReload="yes"), {"/etc/systemd/system/ict-web-api.service": T0 - 5}) is True


def test_could_not_look_is_none_never_false():
    assert diag._unit_config_pending([U], show=lambda u, p: {}, mtime=lambda p: 0)[U] is None
    assert _run(_show(ActiveEnterTimestamp=""), {"/etc/systemd/system/ict-web-api.service": T0}) is None
    assert _run(_show(ActiveEnterTimestamp="Thu 2026-11-12 10:08:33 CET"),
                {"/etc/systemd/system/ict-web-api.service": T0}) is None

    def gone(_p):
        raise OSError("no such file")
    assert diag._unit_config_pending([U], show=_show(), mtime=gone)[U] is None


def test_config_escalates_but_never_downgrades_the_code_verdict():
    e = diag._either_pending
    assert e(False, True) is True and e(None, True) is True and e(True, None) is True
    assert e(False, False) is False and e(True, False) is True
    # config could not look (no systemctl): the code verdict stands, not None
    assert e(False, None) is False and e(None, None) is None


def test_version_folds_config_into_restart_pending_by_unit(monkeypatch):
    monkeypatch.setattr(diag, "_require_diag_token", lambda request: None)
    monkeypatch.setattr(diag, "_resolve_git_sha", lambda: "abc")
    monkeypatch.setattr(diag, "_RUNNING_GIT_SHA", "abc")
    monkeypatch.setattr(diag, "_trader_running_sha", lambda: "abc")
    monkeypatch.setattr(diag, "_deployed_sha_by_unit", lambda: {})
    monkeypatch.setattr(diag, "_unit_config_pending",
                        lambda units: {diag.WEB_API_UNIT: True, diag.TRADER_UNIT: False})
    v = diag.get_version(request=None)
    # same sha (the #25185 case): the code says not pending, the unit file says pending
    assert v["restart_pending"] is False
    assert v["restart_pending_by_unit"] == {diag.WEB_API_UNIT: True, diag.TRADER_UNIT: False}
    assert v["unit_config_pending_by_unit"][diag.WEB_API_UNIT] is True

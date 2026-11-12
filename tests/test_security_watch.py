"""security_watch detectors: ssh (D1) baseline, new identity, burst, blind; files (D3)."""
import hashlib as _hl

from scripts.ops import security_watch as w

OK = "2026-11-11T22:00:08+0000 h sshd[1]: Accepted publickey for ubuntu from 192.0.2.1 port 5 ssh2: ED25519 SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
NEWKEY = OK.replace("SHA256:AAAA", "SHA256:BBBB").replace("192.0.2.1", "198.51.100.7")
PASSWD = "2026-11-11T22:00:09+0000 h sshd[2]: Accepted password for root from 198.51.100.7 port 5 ssh2"
FAIL = "2026-11-11T22:01:08+0000 h sshd[3]: Invalid user debian from 203.0.113.9 port 57996"


def _admit_all(*a, **k):
    return True


def _reader(lines):
    return lambda since: (list(lines), "read")


def test_parse_counts_and_identity():
    acc, failed = w.parse([OK, OK, PASSWD, FAIL, FAIL, "noise"])
    assert len(acc) == 3 and failed == 2
    assert acc[0]["id"].startswith("ubuntu|publickey|SHA256:AAAA")
    assert acc[2]["id"] == "root|password|-"


def test_first_run_records_baseline_and_sends_one_info():
    s, alerts = w.run_ssh({}, 1e9, _reader([OK, OK]), _admit_all, "vm")
    assert len(s["known"]) == 1 and len(alerts) == 1 and alerts[0].startswith("[INFO]")
    assert "192.0.2.1" not in alerts[0]


def test_known_identity_is_silent():
    s, _ = w.run_ssh({}, 1e9, _reader([OK]), _admit_all, "vm")
    s2, alerts = w.run_ssh(s, 1e9 + 300, _reader([OK] * 50), _admit_all, "vm")
    assert alerts == [] and s2["window"]["accepted"] == 50


def test_new_key_and_password_login_each_alert_once_and_are_not_trusted():
    s, _ = w.run_ssh({}, 1e9, _reader([OK]), _admit_all, "vm")
    s2, alerts = w.run_ssh(s, 1e9 + 300, _reader([OK, NEWKEY, NEWKEY, PASSWD]), _admit_all, "vm")
    assert len(alerts) == 2 and all(a.startswith("[RED FLAG]") for a in alerts)
    assert "Nothing was blocked" in alerts[0]
    assert s2["known"] == s["known"]            # never auto-trusted


def test_cooldown_suppresses_repeat():
    s, _ = w.run_ssh({}, 1e9, _reader([OK]), _admit_all, "vm")
    _, alerts = w.run_ssh(s, 1e9 + 300, _reader([NEWKEY]), lambda *a, **k: False, "vm")
    assert alerts == []


def test_failure_burst_threshold():
    s, _ = w.run_ssh({}, 1e9, _reader([OK]), _admit_all, "vm")
    under = [FAIL] * w.FAIL_BURST_PER_HOUR
    s2, alerts = w.run_ssh(s, 1e9 + 300, _reader(under), _admit_all, "vm")
    assert alerts == [] and s2["failed_last_hour"] == w.FAIL_BURST_PER_HOUR
    _, alerts = w.run_ssh(s, 1e9 + 300, _reader(under + [FAIL]), _admit_all, "vm")
    assert len(alerts) == 1 and "burst" in alerts[0]


def test_unreadable_journal_is_not_zero_and_alerts_after_three_runs():
    s, _ = w.run_ssh({}, 1e9, _reader([OK]), _admit_all, "vm")
    def blind(since):
        return None, "could_not_look: rc=1"

    out = []
    for i in range(w.BLIND_AFTER):
        s, alerts = w.run_ssh(s, 1e9 + 300 * (i + 1), blind, _admit_all, "vm")
        out.append(len(alerts))
    assert out == [0] * (w.BLIND_AFTER - 1) + [1]
    assert s["read_state"].startswith("could_not_look") and "known" in s


# ---------------------------------------------------------------------------
# D3: file integrity
# ---------------------------------------------------------------------------


def _h(b: bytes) -> str:
    return _hl.sha256(b).hexdigest()


class _FS:
    """In-memory filesystem: {path: bytes or None (exists but unreadable)}."""

    def __init__(self, files):
        self.files = dict(files)

    def collect(self):
        cats = {}
        for p in self.files:
            if p.startswith("/etc/systemd/system/"):
                cats[p] = "systemd"
            elif "authorized_keys" in p:
                cats[p] = "ssh_keys"
            elif "sudoers" in p:
                cats[p] = "sudoers"
            else:
                cats[p] = "cron"
        return cats, []

    def read(self, p):
        return self.files.get(p)


UNIT = "/etc/systemd/system/ict-web-api.service"
DROPIN = "/etc/systemd/system/ict-web-api.service.d/data-dir.conf"
KEYS = "/home/ubuntu/.ssh/authorized_keys"
DEPLOY = ({"ict-web-api.service": _h(b"unit v2")}, {_h(b"unit v2"), _h(b"dropin v2")})


def _pass(state, fs, admit=lambda *a, **k: True, monkeypatch=None):
    return w.run_files(state, 1000.0, "vm", admit, collect=fs.collect, reader=fs.read,
                       deploy=DEPLOY)


def test_files_first_run_records_baseline_and_one_info():
    fs = _FS({UNIT: b"unit v1", KEYS: b"ssh-ed25519 AAAA k"})
    st, alerts = _pass({}, fs)
    assert len(alerts) == 1 and alerts[0].startswith("[INFO]")
    assert set(st["hashes"]) == {UNIT, KEYS}


def test_files_deploy_copy_is_silent_foreign_edit_alerts_once():
    fs = _FS({UNIT: b"unit v1", DROPIN: b"dropin v1", KEYS: b"k1"})
    st, _ = _pass({}, fs)
    fs.files[UNIT] = b"unit v2"          # what install_systemd_units.sh copies
    fs.files[DROPIN] = b"dropin v2"      # a drop-in equal to a deploy/ file
    st, alerts = _pass(st, fs)
    assert alerts == [] and st["last"]["expected"] == 2
    fs.files[UNIT] = b"unit v2 + ExecStartPre=/tmp/x"   # not a deploy copy
    st, alerts = _pass(st, fs)
    assert len(alerts) == 1 and "CHANGED" in alerts[0] and UNIT in alerts[0]
    assert "ExecStartPre" not in alerts[0]              # content never shown
    st, alerts = _pass(st, fs)
    assert alerts == []                                  # baseline moved on: once


def test_files_new_key_and_removed_sudoers_alert():
    fs = _FS({KEYS: b"k1", "/etc/sudoers.d/90-x": b"x ALL"})
    st, _ = _pass({}, fs)
    fs.files[KEYS] = b"k1\nk2"
    del fs.files["/etc/sudoers.d/90-x"]
    st, alerts = _pass(st, fs)
    assert len(alerts) == 2
    assert any("CHANGED" in a and KEYS in a for a in alerts)
    assert any("REMOVED" in a and "90-x" in a for a in alerts)


def test_files_removed_unit_is_counted_not_alerted():
    fs = _FS({UNIT: b"unit v1"})
    st, _ = _pass({}, fs)
    del fs.files[UNIT]
    st, alerts = _pass(st, fs)
    assert alerts == [] and st["last"]["expected"] == 1


def test_files_unreadable_is_not_removed_and_alerts_once(monkeypatch):
    fs = _FS({KEYS: b"k1"})
    st, _ = _pass({}, fs)
    fs.files[KEYS] = None                       # exists, cannot be read
    monkeypatch.setattr(w.os.path, "lexists", lambda p: True)
    st, alerts = _pass(st, fs)
    assert st["hashes"][KEYS] == _h(b"k1")      # kept, not "removed"
    assert len(alerts) == 1 and "cannot read 1" in alerts[0]
    st, alerts = _pass(st, fs)
    assert alerts == []                          # same blind set: no repeat


def test_files_cooldown_suppresses_repeat_alert():
    fs = _FS({KEYS: b"k1"})
    st, _ = _pass({}, fs)
    fs.files[KEYS] = b"k2"
    _, alerts = _pass(st, fs, admit=lambda *a, **k: False)
    assert alerts == []


def test_deploy_index_matches_real_deploy_dir():
    by_name, every = w.deploy_index(w.REPO_ROOT / "deploy")
    assert "ict-security-watch.service" in by_name
    assert by_name["ict-security-watch.service"] in every


# SYSTEMD-WATCH-KNOWS-INSTALLER: install_systemd_units.sh records the sha256 of every
# file it edits in place; a matching receipt line is an expected deploy change.
VENV = "/etc/systemd/system/ict-web-api.service.d/venv.conf"


def _pass_r(state, fs, receipt):
    return w.run_files(state, 1000.0, "vm", lambda *a, **k: True, collect=fs.collect,
                       reader=fs.read, deploy=DEPLOY, receipt=receipt)


def test_files_installer_receipt_edit_is_silent_foreign_edit_still_alerts():
    fs = _FS({VENV: b"ExecStart=uvicorn --host 0.0.0.0"})
    st, _ = _pass_r({}, fs, {})
    rewritten = b"ExecStart=uvicorn --host 127.0.0.1"      # the installer's sed rewrite
    fs.files[VENV] = rewritten
    st, alerts = _pass_r(st, fs, {VENV: _h(rewritten)})
    assert alerts == [] and st["last"]["expected"] == 1
    # positive control: a foreign edit to the same drop-in still pages
    fs.files[VENV] = rewritten + b"\nExecStartPre=/tmp/x"
    st, alerts = _pass_r(st, fs, {VENV: _h(rewritten)})
    assert len(alerts) == 1 and "CHANGED" in alerts[0] and VENV in alerts[0]


def test_files_receipt_for_another_path_does_not_cover_this_one():
    fs = _FS({VENV: b"v1", UNIT: b"unit v1"})
    st, _ = _pass_r({}, fs, {})
    fs.files[UNIT] = b"unit edited"
    _, alerts = _pass_r(st, fs, {VENV: _h(b"unit edited")})
    assert len(alerts) == 1 and UNIT in alerts[0]


def test_load_receipt_parses_and_ignores_junk():
    good = _h(b"x")
    data = (f"{good}\t{VENV}\n"
            f"nothex\t{VENV}.bad\n"
            f"{good}\t/etc/passwd\n"                  # outside /etc/systemd/system
            "\n").encode()
    got = w.load_receipt(reader=lambda p: data, path="/r")
    assert got == {VENV: good}
    assert w.load_receipt(reader=lambda p: None, path="/r") == {}

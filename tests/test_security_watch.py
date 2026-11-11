"""security_watch ssh detector: baseline, new identity, burst, blind (SEC-DETECTORS D1)."""
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
    blind = lambda since: (None, "could_not_look: rc=1")
    out = []
    for i in range(w.BLIND_AFTER):
        s, alerts = w.run_ssh(s, 1e9 + 300 * (i + 1), blind, _admit_all, "vm")
        out.append(len(alerts))
    assert out == [0] * (w.BLIND_AFTER - 1) + [1]
    assert s["read_state"].startswith("could_not_look") and "known" in s

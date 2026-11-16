"""The gitleaks baseline accepts the reviewed findings and NOTHING that leaks a secret.

The weekly scan (gitleaks-history-weekly.yml) picks up `.gitleaks-baseline.json`
automatically. These checks pin the properties that make that safe: it is a redacted
report, the four known-revoked findings are baselined AND named in the notes doc, and
the workflow really reads the file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".gitleaks-baseline.json"
NOTES = ROOT / "docs" / "security" / "gitleaks-baseline.md"
WF = ROOT / ".github" / "workflows" / "gitleaks-history-weekly.yml"

KNOWN_REVOKED = {
    "2c7818524a785b85d2a8db767bd698cb4bdb71cb:.env:telegram-bot-api-token:1",
    "9ea895023d4781eeeeda55d729b52333e5ac5a6d:bybit_config.py:telegram-bot-api-token:1",
    "67f307e0a408dafe9096943ef5674df18671e9d0:test_bybit_keys.py:generic-api-key:5",
    "67f307e0a408dafe9096943ef5674df18671e9d0:test_bybit_keys.py:generic-api-key:6",
}


def _rows():
    return json.loads(BASELINE.read_text())


def test_baseline_is_a_redacted_report():
    rows = _rows()
    assert isinstance(rows, list) and len(rows) > 300
    assert all(r["Secret"] == "REDACTED" for r in rows)
    assert all("REDACTED" in r["Match"] for r in rows)
    assert all(r["Fingerprint"] and r["Commit"] and r["RuleID"] for r in rows)


def test_known_revoked_are_baselined_and_named_in_the_notes():
    fps = {r["Fingerprint"] for r in _rows()}
    assert KNOWN_REVOKED <= fps, KNOWN_REVOKED - fps
    notes = NOTES.read_text()
    for fp in KNOWN_REVOKED:
        commit, file, rule, line = fp.split(":")
        assert commit[:12] in notes, fp
        assert f"`{file.split(' ')[0]}" in notes, fp


def test_no_vendor_token_shape_survives_in_any_baseline_field():
    blob = BASELINE.read_text()
    for name, rx in {
        "aws": r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])",
        "github": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
        "pem": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "telegram": r"(?<!\d)\d{8,12}:AA[A-Za-z0-9_-]{30,}",
    }.items():
        assert not re.search(rx, blob), f"{name}-shaped string present in baseline"


def test_weekly_workflow_reads_the_baseline():
    doc = yaml.safe_load(WF.read_text())
    scan = next(s for s in doc["jobs"]["scan"]["steps"] if s["name"].startswith("Scan"))["run"]
    assert "--baseline-path .gitleaks-baseline.json" in scan
    assert "--redact=100" in scan


def test_fingerprints_are_unique():
    fps = [r["Fingerprint"] for r in _rows()]
    assert len(fps) == len(set(fps))


# --------------------------------------------------------------------------- the research-path allowlist
# SEC-GITLEAKS-BASELINE-1116 (manager approval 2026-11-16): `.gitleaks.toml` allowlists the `generic-api-key` rule ONLY,
# for the two machine-written research paths ONLY. Every vendor rule still scans them.
TOML = ROOT / ".gitleaks.toml"


def _toml():
    import tomllib
    return tomllib.loads(TOML.read_text())


def test_the_allowlist_is_scoped_to_one_rule_and_two_research_paths():
    cfg = _toml()
    assert cfg["extend"] == {"useDefault": True}                   # every default vendor rule stays on
    assert "allowlist" not in cfg and "allowlists" not in cfg      # no global allowlist
    rules = cfg["rules"]
    assert [r["id"] for r in rules] == ["generic-api-key"]         # exactly one rule is touched
    (rule,) = rules
    assert set(rule) == {"id", "allowlists"}                       # it narrows the rule, never redefines its regex
    (al,) = rule["allowlists"]
    assert al["paths"] == ["^comms/research/", "^research/results/"]
    assert not {"regexes", "stopwords", "commits", "condition"} & set(al)    # paths only: no value or commit exemptions


def test_the_notes_record_the_reason_and_population():
    notes = NOTES.read_text()
    assert "SEC-GITLEAKS-BASELINE-1116" in notes and "387" in notes and "trade_key_sha256" in notes


def test_a_planted_vendor_token_under_research_paths_is_still_caught(tmp_path):
    """Needs the gitleaks binary (the weekly workflow's pinned one); skipped where it is absent."""
    import os
    import secrets
    import shutil
    import string
    import subprocess

    import pytest

    binary = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
    if not binary:
        pytest.skip("gitleaks binary not available")
    alnum = string.ascii_letters + string.digits
    repo = tmp_path / "scan"
    (repo / "comms" / "research" / "RQ-x").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "comms/research/RQ-x/verdict.json").write_text('{"trade_key_sha256": "%s"}\n' % secrets.token_hex(32))
    (repo / "comms/research/RQ-x/planted.json").write_text(
        '{"note": "synthetic planted test value", "t": "ghp_%s"}\n' % "".join(secrets.choice(alnum) for _ in range(36)))
    (repo / "src/z.py").write_text('api_key = "%s"\n' % "".join(secrets.choice(alnum) for _ in range(40)))
    (repo / ".gitleaks.toml").write_text(TOML.read_text())
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "planted"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env)
    report = tmp_path / "r.json"
    subprocess.run([binary, "detect", "--source", str(repo), "--redact=100", "--no-banner", "--log-level", "error",
                    "--exit-code", "0", "--report-format", "json", "--report-path", str(report)], check=True)
    got = sorted((r["RuleID"], r["File"]) for r in json.loads(report.read_text()))
    assert got == [("generic-api-key", "src/z.py"), ("github-pat", "comms/research/RQ-x/planted.json")], got

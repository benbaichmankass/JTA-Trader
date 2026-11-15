"""PI-20261111-PREP1111-0002: a diag fetch failure must never print the bearer token.

realized_slippage._curl_json put the token in curl's argv with check=True, so a curl failure raised
CalledProcessError whose message is the command line, token included."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOK = "deadbeef" * 8


def _load():
    spec = importlib.util.spec_from_file_location("realized_slippage_t", REPO / "scripts/research/realized_slippage.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_token_never_in_argv_and_failure_message_is_redacted(monkeypatch):
    rs = _load()
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["input"] = argv, kw.get("input")
        return subprocess.CompletedProcess(argv, 22, stdout="", stderr=f"curl: (22) 401 for Bearer {TOK}")
    monkeypatch.setenv("DIAG_READ_TOKEN", TOK)
    monkeypatch.setattr(rs.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as ei:
        rs._curl_json("https://example.invalid/api/bot/pnl/exchange/fills?days=1")
    assert TOK not in " ".join(seen["argv"])
    assert TOK in seen["input"] and "-K" in seen["argv"]          # header rides stdin config only
    msg = str(ei.value)
    assert TOK not in msg and "curl exit 22" in msg and "***" in msg


def test_success_returns_json(monkeypatch):
    rs = _load()
    monkeypatch.setenv("DIAG_READ_TOKEN", TOK)
    monkeypatch.setattr(rs.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout='{"count": 0}', stderr=""))
    assert rs._curl_json("https://example.invalid/x") == {"count": 0}


@pytest.mark.parametrize("path", ["scripts/ops/relink_orphan_trade_5209_action.sh",
                                  "scripts/ops/reattach_stranded_package_legs_action.sh"])
def test_action_wrappers_send_the_diag_header_via_stdin(path):
    text = (REPO / path).read_text()
    assert '-H "Authorization: Bearer ${DIAG_TOKEN}"' not in text
    assert '<<<"Authorization: Bearer ${DIAG_TOKEN}"' in text


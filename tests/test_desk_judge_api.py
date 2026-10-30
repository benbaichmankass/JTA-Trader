"""desk_judge_api: a fake client only. No network, no key."""
import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location("dja", Path(__file__).resolve().parents[1] / "scripts/research/desk_judge_api.py")
dja = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dja)


class FakeClient:
    def __init__(self, replies, fail_first=0):
        self.replies, self.calls, self.fail = list(replies), [], fail_first
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail > 0:
            self.fail -= 1
            raise RuntimeError("boom")
        txt = self.replies.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=txt)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=5000))


def _setup(tmp_path, n=3):
    pk = tmp_path / "packets.jsonl"
    pk.write_text("\n".join(json.dumps({"packet_id": f"DP-{i}", "packet": {"meta": {"packet_id": f"DP-{i}"}, "x": i}}) for i in range(n)))
    pr = tmp_path / "JUDGE-PROTOCOL.md"
    pr.write_text("protocol " * 50)
    return argparse.Namespace(packets=str(pk), protocol=str(pr), out=str(tmp_path / "o"), offset=0, n=n, max_usd=5.0,
                              model="m", price_input=3.0, price_cache_read=0.3, price_output=15.0,
                              skip_done=True, estimate_only=False)


def test_cost_arithmetic():
    c = dja.call_cost({"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5000},
                      {"input": 3.0, "cache_read": 0.3, "output": 15.0})
    assert abs(c - (0.003 + 0.0015 + 0.0015)) < 1e-9


def test_run_writes_judged_files_and_ledger(tmp_path):
    a = _setup(tmp_path)
    fc = FakeClient(['{"packet_id":"DP-0","action":"no_trade"}', '```json\n{"packet_id":"DP-1","action":"no_trade"}\n```', 'not json'])
    r = dja.run(a, client=fc, sleep=lambda s: None)
    assert r["judged"] == 2 and r["unparsed"] == 1
    assert json.loads((tmp_path / "o/judged/p00.json").read_text()) == [{"packet_id": "DP-0", "action": "no_trade"}]
    assert not (tmp_path / "o/judged/p02.json").exists()           # unparsed is missing, never a silent no_trade
    assert len((tmp_path / "o/usage.jsonl").read_text().splitlines()) == 3
    sysb = fc.calls[0]["system"][0]
    assert sysb["cache_control"] == {"type": "ephemeral"} and "PACKET" not in sysb["text"]    # protocol only; packet is the user turn
    assert "mask" not in json.dumps(fc.calls[0]).lower()


def test_hard_cap_stops_before_the_call(tmp_path):
    a = _setup(tmp_path)
    a.max_usd = 0.0001
    fc = FakeClient([])
    r = dja.run(a, client=fc, sleep=lambda s: None)
    assert fc.calls == [] and r["judged"] == 0 and "would be exceeded" in r["stopped"]


def test_resume_skips_done_and_retries_transient(tmp_path):
    a = _setup(tmp_path, n=2)
    dja.run(a, client=FakeClient(['{"packet_id":"DP-0","action":"no_trade"}', '{"packet_id":"DP-1","action":"no_trade"}']), sleep=lambda s: None)
    fc = FakeClient([])
    assert dja.run(a, client=fc, sleep=lambda s: None)["skipped_existing"] == 2 and fc.calls == []
    b = _setup(tmp_path / "b", n=1) if (tmp_path / "b").mkdir() is None else None
    r = dja.run(b, client=FakeClient(['{"packet_id":"DP-0","action":"no_trade"}'], fail_first=1), sleep=lambda s: None)
    assert r["judged"] == 1


def test_wrong_packet_id_is_unparsed():
    rows, _ = dja.parse_rows('{"packet_id":"OTHER","action":"no_trade"}', "DP-0")
    assert rows is None


def test_estimate_only_needs_no_key(tmp_path):
    a = _setup(tmp_path)
    a.estimate_only = True
    r = dja.run(a)
    assert r["packets"] == 3 and r["worst_case_usd_per_packet"] > 0


class ApiErr(Exception):
    def __init__(self, status, etype, message):
        super().__init__(f"Error code: {status}")
        self.status_code, self.body = status, {"type": "error", "error": {"type": etype, "message": message}}


class AlwaysFail:
    def __init__(self, exc):
        self.exc, self.calls, self.messages = exc, [], self

    def create(self, **kw):
        self.calls.append(kw)
        raise self.exc


def test_describe_error_uses_body_and_classifies():
    msg, retry = dja.describe_error(ApiErr(400, "invalid_request_error", "Your credit balance is too low " + "x" * 300))
    assert msg.startswith("invalid_request_error: Your credit balance") and len(msg) > 300 and not retry
    assert dja.describe_error(ApiErr(429, "rate_limit_error", "slow"))[1]
    assert dja.describe_error(ApiErr(529, "overloaded_error", "busy"))[1]
    assert dja.describe_error(RuntimeError("conn"))[1]


def test_key_never_in_message(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret123")
    msg, _ = dja.describe_error(ApiErr(401, "authentication_error", "bad key sk-secret123"))
    assert "sk-secret123" not in msg


def test_non_retryable_4xx_not_retried_and_dispatch_stops_after_k(tmp_path):
    a = _setup(tmp_path, n=10)
    fc = AlwaysFail(ApiErr(400, "invalid_request_error", "credit balance too low"))
    sleeps = []
    r = dja.run(a, client=fc, sleep=sleeps.append)
    assert len(fc.calls) == dja.STOP_AFTER_SAME_FATAL and sleeps == []
    assert r["stopped"] == "invalid_request_error: credit balance too low [HTTP 400]"
    lines = [json.loads(x) for x in (tmp_path / "o/usage.jsonl").read_text().splitlines()]
    assert len(lines) == 3 and all("credit balance too low" in x["problem"] for x in lines)


def test_429_is_retried(tmp_path):
    a = _setup(tmp_path, n=1)
    fc = AlwaysFail(ApiErr(429, "rate_limit_error", "slow"))
    dja.run(a, client=fc, sleep=lambda s: None)
    assert len(fc.calls) == 3


def test_cli_and_client_are_disabled():
    """Nothing may spend Anthropic API credits (operator 2026-10-27/28): both entry points refuse."""
    import pytest
    with pytest.raises(SystemExit, match="DISABLED"):
        dja.make_client()
    with pytest.raises(SystemExit, match="DISABLED"):
        dja.main(["--packets", "p", "--protocol", "q", "--out", "o", "--n", "1", "--max-usd", "1"])

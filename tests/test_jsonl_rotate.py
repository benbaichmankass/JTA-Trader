"""Writer-side rotation for signal_audit / position_read_state_soak (VM-DISK-GROWTH-20261102)."""
import gzip
import json
import types

from src.utils import jsonl_rotate as jr


class _InlineThread:
    """Runs the rotation's gzip synchronously. The real background thread raced this test's own
    clean-up gzip on the same `.gz.tmp` under CPU contention (UnicodeDecodeError on gzip bytes on CI,
    #25216 run 43254089052 attempt 2; reproduced locally 8 times in 1,800 runs across 6 parallel
    processes, 0 in 400 serial runs), and could outlive the test (tmp dir "not empty")."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def test_rotates_at_cap_gzips_and_keeps_every_row(tmp_path, monkeypatch):
    monkeypatch.setenv(jr.ENV_MAX_MB, "0.001")  # ~1 KiB
    monkeypatch.setattr(jr, "threading", types.SimpleNamespace(Thread=_InlineThread))  # this module only
    p = tmp_path / "signal_audit.jsonl"
    n = iter(range(1000))
    monkeypatch.setattr(jr, "_stamp", lambda: f"2026-11-02T{next(n):06d}Z")
    rows = [json.dumps({"i": i, "pad": "x" * 100}) + "\n" for i in range(30)]
    for r in rows:
        jr.append_line(p, r, 256)
    # finish any background gzip deterministically
    for s in list(tmp_path.glob("signal_audit.jsonl.20*")):
        if not s.name.endswith(".gz"):
            jr._gzip_file(s)
    sibs = jr.rotated_siblings(p)
    assert sibs and all(s.name.endswith(".gz") for s in sibs)
    got = []
    for s in sibs:
        with jr.open_rotated(s) as fh:
            got += [json.loads(x)["i"] for x in fh]
    got += [json.loads(x)["i"] for x in p.read_text().splitlines()]
    assert got == list(range(30))  # nothing lost, nothing duplicated, in order
    assert p.exists() and p.stat().st_size < 1100


def test_below_cap_does_not_rotate_and_never_raises(tmp_path):
    p = tmp_path / "a.jsonl"
    jr.append_line(p, "{}\n", 256)
    assert jr.rotated_siblings(p) == []
    assert jr.rotate_if_needed(tmp_path / "missing.jsonl", 1) is False


def test_rotated_names_are_pruned_by_cap_runtime_logs():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
    import cap_runtime_logs as c
    for n in ("signal_audit.jsonl.2026-11-02T210000Z.gz", "signal_audit.jsonl.2026-11-02T210000Z",
              "signal_audit.jsonl.2026-11-02T210000Z.gz.tmp"):
        assert c.is_candidate(Path(n)), n
    assert not c.is_candidate(Path("signal_audit.jsonl"))


def test_siblings_prefers_gz_when_both_exist_and_skips_tmp(tmp_path):
    p = tmp_path / "x.jsonl"
    for n in ("x.jsonl.2026-11-01T000000Z", "x.jsonl.2026-11-01T000000Z.gz",
              "x.jsonl.2026-11-02T000000Z", "x.jsonl.2026-11-03T000000Z.gz.tmp"):
        (tmp_path / n).write_bytes(b"")
    assert [s.name for s in jr.rotated_siblings(p)] == ["x.jsonl.2026-11-01T000000Z.gz", "x.jsonl.2026-11-02T000000Z"]


def test_aggregate_jsonl_reads_rotated_and_live(tmp_path):
    from src.web.api.routers.diag import aggregate_jsonl
    p = tmp_path / "s.jsonl"
    with gzip.open(tmp_path / "s.jsonl.2026-11-01T000000Z.gz", "wb") as fh:
        fh.write(b'{"ts": "2026-11-01T00:00:00"}\n')
    p.write_text('{"ts": "2026-11-02T00:00:00"}\n')
    r = aggregate_jsonl(p, [], [])
    assert r["distinct_utc_days"] == 2 and r["scanned_lines"] == 2


def test_same_second_collision_never_overwrites_a_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv(jr.ENV_MAX_MB, "0.001")
    monkeypatch.setattr(jr, "_stamp", lambda: "2026-11-02T000000Z")
    monkeypatch.setattr(jr, "rotate_if_needed", lambda path, mb, _f=jr.rotate_if_needed: _f(path, mb, background=False))
    p = tmp_path / "a.jsonl"
    for i in range(30):
        jr.append_line(p, json.dumps({"i": i, "pad": "x" * 100}) + "\n", 256)
    got = []
    for s in jr.rotated_siblings(p):
        with jr.open_rotated(s) as fh:
            got += [json.loads(x)["i"] for x in fh]
    got += [json.loads(x)["i"] for x in p.read_text().splitlines()]
    assert got == list(range(30))

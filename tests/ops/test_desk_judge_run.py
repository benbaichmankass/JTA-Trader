"""run-desk-judge: argument parsing, refusals, dry-run, resume, merge, stop rule. A fake runner only: no network, no key, no API."""
import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


djr = _load("djr", "scripts/ops/desk_judge_run.py")


def test_registered_constants_match_the_driver():
    src = (ROOT / "scripts/research/desk_gen_replay_driver.py").read_text()
    assert f"SEED = {djr.REGISTERED_SEED}" in src and djr.REGISTERED_SEED != 20261027
    assert f"SCHEDULE_LEN = {djr.SCHEDULE_LEN}" in src


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "0", "-1", "nan", "inf", "40.01", "1e9"])
def test_max_usd_refusals(raw):
    with pytest.raises(djr.Refused):
        djr.parse_max_usd(raw)


@pytest.mark.parametrize("raw,v", [("7", 7.0), ("0.5", 0.5), ("40", 40.0)])
def test_max_usd_accepts(raw, v):
    assert djr.parse_max_usd(raw) == v


@pytest.mark.parametrize("n,off", [(0, 0), (-1, 0), (1, -1), (200, 1400), (1501, 0)])
def test_range_refusals(n, off):
    with pytest.raises(djr.Refused):
        djr.check_range(n, off)


def test_range_accepts_the_whole_schedule():
    djr.check_range(1500, 0)
    djr.check_range(100, 1400)


def _args(tmp_path, **kw):
    d = dict(n=3, offset=0, max_usd="2", apply=False, repo_dir=str(tmp_path / "repo"), root=str(tmp_path / "root"),
             python="py", deadline_s=840.0)
    d.update(kw)
    return argparse.Namespace(**d)


class FakeRunner:
    """Stands in for the driver and the judge: writes what they would write, records every command."""

    def __init__(self, props=None, judged=True, next_allowed=True):
        self.calls, self.props, self.judged, self.next_allowed = [], props or {}, judged, next_allowed

    def __call__(self, cmd, env):
        self.calls.append((cmd, env))
        if "packets" in cmd and "--offset" in cmd and cmd[2] == "packets":
            out = Path(cmd[cmd.index("--out") + 1])
            n, off = int(cmd[cmd.index("--n") + 1]), int(cmd[cmd.index("--offset") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "packets.jsonl").write_text("".join(json.dumps({"packet_id": f"DP-{off + k}", "packet": {"x": k}}) + "\n" for k in range(n)))
            (out / "mask-key.json").write_text(json.dumps({"keys": [{"packet_id": f"DP-{off + k}", "index": off + k, "packet_sha": "s"} for k in range(n)]}))
            (out / "JUDGE-PROTOCOL.md").write_text("proto")
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"packets": n, "withheld_for_leak": 0, "median_packet_chars": 10}), "")
        if cmd[1].endswith("desk_judge_api.py"):
            out = Path(cmd[cmd.index("--out") + 1])
            n = int(cmd[cmd.index("--n") + 1])
            if "--estimate-only" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"estimate_only": True, "worst_case_usd_total": 0.1}), "")
            (out / "judged").mkdir(parents=True, exist_ok=True)
            spent = 0.0
            for k in range(n if self.judged else 0):
                (out / "judged" / f"p{k:02d}.json").write_text(json.dumps(self.props.get(k, [{"packet_id": f"DP-{k}", "action": "no_trade"}])))
                with (out / "usage.jsonl").open("a") as fh:
                    fh.write(json.dumps({"index": k, "packet_id": f"DP-{k}", "usage": {"input_tokens": 5000, "output_tokens": 60}, "cost_usd": 0.02, "parsed": True, "problem": ""}) + "\n")
                spent += 0.02
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"judged": n, "spent_usd": spent, "stopped": None}), "")
        if "intake" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"packets_judged": 3, "valid_proposals_total": 0, "next_batch_allowed": self.next_allowed}), "")
        raise AssertionError(cmd)


def test_missing_cap_refuses_before_anything_runs(tmp_path):
    r, lines = FakeRunner(), []
    assert djr.execute(_args(tmp_path, max_usd=None), r, out=lines.append) == 2
    assert r.calls == [] and "--max-usd is required" in lines[0]


def test_apply_without_key_builds_nothing(tmp_path):
    r = FakeRunner()
    assert djr.execute(_args(tmp_path, apply=True), r, environ={}, out=lambda s: None) == 3
    assert r.calls == []


def test_dry_run_builds_packets_and_makes_no_judge_call_without_a_key(tmp_path):
    r, lines = FakeRunner(), []
    assert djr.execute(_args(tmp_path), r, environ={}, out=lines.append) == 0
    judge_calls = [c for c, _ in r.calls if c[1].endswith("desk_judge_api.py")]
    assert len(judge_calls) == 1 and "--estimate-only" in judge_calls[0]       # no client path, no key
    assert not any("intake" in c for c, _ in r.calls)
    assert "DRY-RUN complete" in lines[-1]
    assert not (Path(_args(tmp_path).root) / "export").exists()


def test_packets_use_the_registered_seed_and_the_requested_range(tmp_path):
    r = FakeRunner()
    djr.execute(_args(tmp_path, n=3, offset=0), r, environ={}, out=lambda s: None)
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--seed") + 1] == "20261026" and "20261027" not in " ".join(cmd)
    assert "--fetch" in cmd                                                    # empty candle cache -> fetch once


def test_apply_judges_merges_and_runs_intake(tmp_path):
    r, lines = FakeRunner(props={1: [{"packet_id": "DP-1", "action": "propose_entry"}]}), []
    assert djr.execute(_args(tmp_path, apply=True), r, environ={"ANTHROPIC_API_KEY": "sk-secret"}, out=lines.append) == 0
    judge = [(c, e) for c, e in r.calls if c[1].endswith("desk_judge_api.py")][0]
    assert judge[0][judge[0].index("--max-usd") + 1] == "2.0" and judge[1]["ANTHROPIC_API_KEY"] == "sk-secret"
    ex = Path(_args(tmp_path).root) / "export"
    assert len((ex / "proposals.jsonl").read_text().splitlines()) == 3
    assert [k["packet_id"] for k in json.loads((ex / "mask-key.json").read_text())["keys"]] == ["DP-0", "DP-1", "DP-2"]
    text = "\n".join(lines)
    assert "sk-secret" not in text and "0.02" in text
    assert text.index("per-call ledger") < text.index("=== SUMMARY ===")      # the summary is last: the comment keeps the tail


def test_second_batch_must_start_at_the_prefix_and_cannot_overlap(tmp_path):
    root = Path(_args(tmp_path).root)
    djr.execute(_args(tmp_path, n=3, offset=0, apply=True), FakeRunner(), environ={"ANTHROPIC_API_KEY": "k"}, out=lambda s: None)
    for n, off in ((3, 5), (2, 1)):                                            # a gap, then an overlap
        lines = []
        assert djr.execute(_args(tmp_path, n=n, offset=off), FakeRunner(), environ={}, out=lines.append) == 2, lines
    assert djr.execute(_args(tmp_path, n=3, offset=0, apply=True), FakeRunner(), environ={"ANTHROPIC_API_KEY": "k"}, out=lambda s: None) == 0  # same shape = resume
    assert djr.execute(_args(tmp_path, n=3, offset=3), FakeRunner(), environ={}, out=lambda s: None) == 0                                      # the prefix
    assert djr.judged_prefix(set(djr.judged_indices(root))) == 3                                                                                # dry run judged nothing new


def test_stop_rule_blocks_a_new_batch(tmp_path):
    djr.execute(_args(tmp_path, apply=True), FakeRunner(next_allowed=False), environ={"ANTHROPIC_API_KEY": "k"}, out=lambda s: None)
    lines = []
    assert djr.execute(_args(tmp_path, n=3, offset=3), FakeRunner(), environ={}, out=lines.append) == 2
    assert "next_batch_allowed=false" in lines[0]


def test_main_requires_an_explicit_cap(tmp_path, capsys):
    rc = djr.main(["--n", "3", "--offset", "0", "--repo-dir", str(tmp_path), "--root", str(tmp_path / "r")])
    assert rc == 2 and "--max-usd is required" in capsys.readouterr().out


def test_judge_deadline_stops_before_a_call(tmp_path):
    dja = _load("dja2", "scripts/research/desk_judge_api.py")
    pk = tmp_path / "packets.jsonl"
    pk.write_text("\n".join(json.dumps({"packet_id": f"DP-{i}", "packet": {"meta": {"packet_id": f"DP-{i}"}}}) for i in range(3)))
    pr = tmp_path / "p.md"
    pr.write_text("proto")
    a = argparse.Namespace(packets=str(pk), protocol=str(pr), out=str(tmp_path / "o"), offset=0, n=3, max_usd=5.0, model="m",
                           price_input=3.0, price_cache_read=0.3, price_output=15.0, skip_done=True, estimate_only=False, deadline_s=-1.0)
    res = dja.run(a, client=object())
    assert res["judged"] == 0 and "deadline_s" in res["stopped"]

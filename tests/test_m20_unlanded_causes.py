"""RESEARCH-LOSS-M20-UNLANDED (2026-11-12): the two causes behind 7 of the 10 unlanded m20 runs.

1. The generator must never mint a unit for a leg the sweep's `plan` job refuses (`classify` is None).
2. When `plan` dies, `research_result` must still name the legs it was asked for, so each gets a producer_failed
   row instead of the run aborting with 'no dispatched legs' (PI-20261112-TE74WG5Z-0005).
"""
import sys
from pathlib import Path

from scripts.research import queue_replenish as qr
from scripts.research import m20_sweep_result as msr

sys.path.insert(0, str(Path("scripts/research")))
from m20_fleet_exit_sweep import classify  # noqa: E402

UNROUTABLE = ["ml_entry_eq", "ml_entry_v2", "ml_entry", "turtle_soup", "e4_oi_shock_1h", "fade_breakout_4h",
              "claude_desk"]


def test_m20_template_only_generates_legs_the_sweep_can_route():
    facts = qr.repo_facts(Path("."))
    legs = {p["leg"] for p in qr._leg_source("live_roster_legs_m20_sweepable", {}, facts)}
    assert legs, "a sweepable source that yields nothing would silently stop the M20 refresh"
    assert all(classify(leg) is not None for leg in legs)
    assert not legs & set(UNROUTABLE)
    assert legs <= set(facts["legs"])


def test_m20_template_uses_the_sweepable_source():
    import yaml
    tpl = yaml.safe_load(Path("research/templates/m20-exit-lever.yaml").read_text())
    assert tpl["grid"]["legs"] == "live_roster_legs_m20_sweepable"


def test_fallback_prefers_input_then_sentinel_and_never_invents_legs():
    assert msr.fallback_dispatched_legs("a, b", "legs: z") == (["a", "b"], "dispatch input")
    assert msr.fallback_dispatched_legs("", "# prose\nlegs: x,y\n") == (["x", "y"], "sentinel file")
    assert msr.fallback_dispatched_legs("", "no legs line here") == ([], "none")
    assert msr.fallback_dispatched_legs("", "") == ([], "none")


def test_plan_failure_still_emits_producer_failed_per_leg(tmp_path):
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("")
    out = tmp_path / "r.jsonl"
    rc = msr.main(["--corpus", str(corpus), "--out", str(out), "--legs", "", "--input-legs", "turtle_soup",
                   "--sweep-result", "skipped"])
    assert rc == 0
    import json
    recs = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
    assert [r["measurement"]["leg"] for r in recs] == ["turtle_soup"]
    assert recs[0]["read_state"] == "producer_failed"


def test_nothing_named_still_fails_loudly(tmp_path):
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("")
    assert msr.main(["--corpus", str(corpus), "--out", str(tmp_path / "o.jsonl"), "--legs", ""]) == 1


def test_thin_leg_split_beyond_holdout_lands_a_record_not_a_crash(tmp_path):
    """The qld/mes/iaum runs crashed with HoldoutLeak (no verdicts.json). The sweep now writes a
    `split_beyond_holdout` leg status; the extractor and summarizer must turn it into a landed, measured record."""
    import json
    import subprocess
    d = tmp_path / "sweep_out" / "exit-lever-sweep-x"
    d.mkdir(parents=True)
    (d / "verdicts.json").write_text(json.dumps({
        "generated_at": "2026-11-12T00:00:00Z", "split": "2025-07-01", "tp_cap_pct": 0.099,
        "verdicts": {"qld_trend_long_1d": {"status": "split_beyond_holdout", "split": "2025-07-01",
                                           "split_fallback": "leg_too_thin",
                                           "holdout": {"last_discovery_day": "2022-11-10"}}}}))
    corpus, out = tmp_path / "c.jsonl", tmp_path / "r.jsonl"
    r = subprocess.run([sys.executable, "scripts/research/m20_corpus_extract.py", "--in",
                        str(tmp_path / "sweep_out"), "--corpus", str(corpus)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert msr.main(["--corpus", str(corpus), "--out", str(out), "--legs", "qld_trend_long_1d",
                     "--sweep-result", "success"]) == 0
    rec = json.loads(out.read_text().splitlines()[0])
    assert rec["measurement"]["leg"] == "qld_trend_long_1d" and rec["read_state"] == "measured"

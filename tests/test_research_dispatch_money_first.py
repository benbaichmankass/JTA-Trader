"""MONEY FIRST (operator 2026-10-18, "Fix now, money first"; lane DISPATCH-MONEY-FIRST-1018).

The dispatcher orders due units ACROSS themes by the router's value score; theme share only breaks ties; starved
units still go first; inside a theme an asked unit (authored or a programme node) still precedes a template refill.

PROGRAMME PRIORITY (operator 2026-10-18 ~06:20Z, "Those two items are our highest priority, we need to make sure we're
pushing forward on them": P1 active trade management, P2 AI trader): a due unit of a programme listed in
research_compute.yaml `value.programme_priority` ranks first on every backend, in list order, above every other
theme and programme; only a starved unit goes ahead of it.

The reproduced case is research-queue-dispatch run 39098686264 (2026-10-18 04:56Z): github_runner's three slots went
to RQ-20261017-ae17-08/-09 (regime, structural, score 6.5) and ae17-45 (infra, 30.7) while RQ-20261017-002
(live_strategy, own_losses, 141.9) and the other P1 real-money units deferred on "github_runner at capacity". The
old cross-theme step was a round-robin by (fires in window + picks) / weight, so the theme with no recent fire took
the scarce slot whatever its unit was worth.
"""
import copy
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts.research import compute_router as cr
from scripts.research import dispatch_queue as dq
from scripts.research import queue_grade
from scripts.research.research_queue import QueueJob, load_themes

CFG = cr.load_config()
NOW = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
# The live THEMES.yaml weights at the time of the measurement (regime 5, live_strategy 4, infra 2): the test pins its
# own copy so a re-weight cannot silently change what this file proves.
TH = {"share_window_hours": 48, "aging_hours": 72,
      "themes": {"regime": {"weight": 5}, "live_strategy": {"weight": 4}, "infra": {"weight": 2}}}
WF = "research-script-run.yml"
STAMP = (NOW - timedelta(hours=6)).isoformat()


def job(i, theme, **kw):
    raw = {"id": f"RQ-20300110-{i:03d}", "status": "queued", "cadence": "once", "theme": theme, "priority": 2,
           "run": {"workflow": WF, "inputs": {"research_unit": f"RQ-20300110-{i:03d}"}}}
    raw.update(kw)
    return QueueJob(path=Path(f"{raw['id']}.yaml"), raw=raw)


def fired(i, theme, bucket):
    """A unit that fired 6 h ago: counts toward its theme's share and its bucket's observed share."""
    return job(i, theme, status="done", last_dispatched_at=STAMP, value={"bucket": bucket, "usd_at_stake_per_month": 1})


def p1_unit(i=1, **kw):
    """RQ-20261017-002 as committed: P1 programme node, own_losses, $500/month, confidence 0.45, 25 min."""
    return job(i, "live_strategy", priority=1, compute="cpu_light",
               value={"bucket": "own_losses", "usd_at_stake_per_month": 500, "confidence": 0.45},
               routing={"needs_gpu": False, "needs_trainer_resident_data": False, "peak_memory_gb": 2, "est_minutes": 25},
               generated={"family": "programme:P1", "template": "research/programmes/01-active-trade-management.yaml",
                          "key": "programme:P1-Q3"}, **kw)


def regime_unit(i=2, **kw):
    """RQ-20261017-ae17-08 as committed: authored regime unit, structural, $60/month, confidence 0.2, 20 min."""
    return job(i, "regime", priority=3, compute="cpu_light",
               value={"bucket": "structural", "usd_at_stake_per_month": 60, "confidence": 0.2},
               routing={"needs_gpu": False, "needs_trainer_resident_data": False, "peak_memory_gb": 2, "est_minutes": 20}, **kw)


def window_as_measured():
    """The share window the 04:56Z run saw: live_strategy over its share (own_losses + information fires),
    structural over ITS bucket share, regime with no fire at all -- the state the round-robin served regime first in.
    Buckets: 10 own_losses + 13 structural + 7 information => own_losses boost 0.30/0.333 = 0.90,
    structural 0.25/0.433 = 0.58, which is what puts the two scores at ~142 and ~6.5."""
    return ([fired(100 + k, "live_strategy", "own_losses") for k in range(10)]
            + [fired(120 + k, "live_strategy", "structural") for k in range(13)]
            + [fired(140 + k, "live_strategy", "information") for k in range(7)])


def ranked(order):
    return [j for j in order if j.raw.get("_rank")]


def test_the_142_own_losses_unit_fires_before_the_6_5_structural_unit_in_the_under_share_theme():
    money, cheap = p1_unit(), regime_unit()
    order = ranked(dq.fair_order(window_as_measured() + [cheap, money], NOW, TH, CFG))
    assert [j.id for j in order] == [money.id, cheap.id]
    # the scores ARE the measured ones (141.9 and 6.5 on the run), so this is the case, not a caricature of it
    assert abs(money.raw["_rank"]["rank_value"] - 141.9) < 2.0, money.raw["_rank"]["derivation"]
    assert abs(cheap.raw["_rank"]["rank_value"] - 6.5) < 0.3, cheap.raw["_rank"]["derivation"]
    # and the precondition of the old failure holds: regime had NO fire in the window, live_strategy had 30
    assert not any(j.raw["theme"] == "regime" for j in window_as_measured())
    # the P1 unit is taken under the operator's programme priority; the regime unit by value
    assert money.raw["_rank"]["pick"] == "programme:P1" and cheap.raw["_rank"]["pick"] == "value"
    # and with the programme list emptied it STILL fires first, on value alone (the money-first rule on its own)
    order2 = ranked(dq.fair_order(window_as_measured() + [regime_unit(), p1_unit()], NOW, TH, cfg_with([])))
    assert [j.raw["theme"] for j in order2] == ["live_strategy", "regime"] and order2[0].raw["_rank"]["pick"] == "value"


def test_the_old_round_robin_is_what_the_no_cfg_path_still_does_so_the_change_is_the_cfg_merge():
    # Negative control for the test above: without cfg (pre-router order) the under-share theme is served first,
    # exactly the behaviour the live dispatcher no longer has. If this stops holding the control is broken.
    money, cheap = p1_unit(), regime_unit()
    order = [j for j in dq.fair_order(window_as_measured() + [cheap, money], NOW, TH) if j.status == "queued"]
    assert [j.id for j in order] == [cheap.id, money.id]


def test_value_orders_across_themes_not_only_inside_one():
    a = job(1, "live_strategy", value={"usd_at_stake_per_month": 500, "confidence": 0.5}, routing={"est_minutes": 10})
    b = job(2, "regime", value={"usd_at_stake_per_month": 200, "confidence": 0.5}, routing={"est_minutes": 10})
    c = job(3, "infra", value={"usd_at_stake_per_month": 300, "confidence": 0.5}, routing={"est_minutes": 10})
    d = job(4, "live_strategy", value={"usd_at_stake_per_month": 250, "confidence": 0.5}, routing={"est_minutes": 10})
    order = ranked(dq.fair_order([b, d, c, a], NOW, TH, CFG))
    assert [j.id for j in order] == [a.id, c.id, d.id, b.id]          # 500, 300, 250, 200 -- themes interleave by value
    assert [j.raw["_rank"]["rank_value"] for j in order] == sorted((j.raw["_rank"]["rank_value"] for j in order), reverse=True)


def test_theme_share_breaks_an_equal_score_and_only_that():
    # One declared bucket everywhere so the bucket boost is identical and theme share is the ONLY difference.
    def same():   # fresh dicts per unit: a shared `value` object would make the bump below hit all three
        return {"value": {"bucket": "structural", "usd_at_stake_per_month": 300, "confidence": 0.5}, "routing": {"est_minutes": 10}}
    live, regime, infra = job(1, "live_strategy", **same()), job(2, "regime", **same()), job(3, "infra", **same())
    # live_strategy fired 3x in the window; regime and infra never: at an equal score the under-share theme wins,
    # and between two themes at usage 0 the heavier weight (regime 5 > infra 2) goes first.
    recent = [fired(100 + k, "live_strategy", "structural") for k in range(3)]
    order = ranked(dq.fair_order(recent + [live, infra, regime], NOW, TH, CFG))
    assert len({round(j.raw["_rank"]["rank_value"], 6) for j in order}) == 1, [j.raw["_rank"]["derivation"] for j in order]
    assert [j.raw["theme"] for j in order] == ["regime", "infra", "live_strategy"]
    # ...but a strictly higher score in the over-share theme still goes first: share is a tie-break, not a term
    live.raw["value"]["usd_at_stake_per_month"] = 301
    order = ranked(dq.fair_order(recent + [live, infra, regime], NOW, TH, CFG))
    assert order[0] is live


def test_a_starved_unit_in_any_theme_goes_before_the_most_valuable_one():
    starved = job(1, "infra", priority=3, routing={"est_minutes": 300})
    starved.raw["id"] = "RQ-20291201-001"                        # due ~40 days before NOW: past starve_hours (240 h)
    money = p1_unit(2)
    order = ranked(dq.fair_order([money, starved], NOW, TH, CFG))
    assert order[0] is starved and starved.raw["_rank"]["starved"] and starved.raw["_rank"]["pick"] == "starved"
    assert order[1] is money


def test_a_programme_node_is_an_asked_question_not_a_refill_inside_its_theme():
    # The P1 units carry `generated: {family: programme:P1}`; they must not sort behind an authored unit of lower
    # value in their own theme (they did: 11 authored equity units, scores 13..27, preceded the 145-score unit).
    money = p1_unit(1)
    authored = job(2, "live_strategy", value={"usd_at_stake_per_month": 100, "confidence": 0.3}, routing={"est_minutes": 10})
    sweep = job(3, "live_strategy", value={"usd_at_stake_per_month": 5000, "confidence": 0.9}, routing={"est_minutes": 10},
                generated={"family": "e35-bracket", "key": "k"})
    order = ranked(dq.fair_order([sweep, authored, money], NOW, TH, CFG))
    assert [j.id for j in order] == [money.id, authored.id, sweep.id]   # asked by value, then the refill
    assert (money.raw["_rank"]["refill"], authored.raw["_rank"]["refill"], sweep.raw["_rank"]["refill"]) == (False, False, True)


def test_is_refill_draws_the_same_line_as_the_grader_template_cell():
    for gen in ({"family": "programme:P1"}, {"family": "e35-bracket"}, {"family": "m20-exit-lever"}, None, {}):
        u = {"generated": gen} if gen is not None else {}
        assert dq.is_refill(u) == queue_grade.template_cell(u), gen


def test_a_refill_still_fires_when_its_theme_has_nothing_asked_and_other_themes_are_cheaper():
    sweep = job(1, "live_strategy", value={"usd_at_stake_per_month": 5000, "confidence": 0.9}, routing={"est_minutes": 10},
                generated={"family": "e35-bracket", "key": "k"})
    cheap = regime_unit(2)
    order = ranked(dq.fair_order([cheap, sweep], NOW, TH, CFG))
    assert order[0] is sweep                                      # across themes a refill competes on value


def test_every_due_unit_is_in_the_order_exactly_once_and_not_due_ones_follow():
    due = [job(i, t) for i, t in enumerate(["regime", "live_strategy", "infra", "regime", "infra"], start=1)]
    done = job(50, "regime", status="done")
    later = job(51, "infra", not_before=(NOW + timedelta(days=1)).isoformat())
    order = dq.fair_order(due + [done, later], NOW, TH, CFG)
    assert sorted(j.id for j in order[:5]) == sorted(j.id for j in due)
    assert {j.id for j in order[5:]} == {done.id, later.id}


def test_the_committed_themes_file_keeps_the_rule_honest_and_the_decision_line_says_why(tmp_path, monkeypatch):
    """End to end through main(): a dry run over the measured case writes `pick=value` on both lines and lists the
    money unit first, with the live research/THEMES.yaml."""
    q = tmp_path / "queue"
    q.mkdir()
    base = {"title": "t", "question": "q", "status": "queued", "cadence": "once", "kind": "deterministic",
            "why_not_inferential": "deterministic grader over a fixed ledger", "lands": {"store": "research/results/"},
            "decision_rule": {"id": "R", "registered_at": "2030-01-01"}}
    for j in window_as_measured() + [regime_unit(), p1_unit()]:
        d = {**base, **j.raw}
        d["run"] = {"command": ["python3", "scripts/research/script_run.py", "--self-test"],
                    "inputs": {"research_unit": j.id}}
        if d["status"] == "done":
            d.pop("priority", None)
        (q / f"{j.id}.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    monkeypatch.setattr(dq, "RESULTS_ROOT", tmp_path / "results")
    assert "regime" in load_themes()["themes"] and "live_strategy" in load_themes()["themes"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        dq.main(["--queue-dir", str(q), "--json", "--ref", "main"])
    rows = [r for r in json.loads(buf.getvalue())["decisions"] if r["outcome"] == "would_dispatch"]
    assert [r["id"] for r in rows] == ["RQ-20300110-001", "RQ-20300110-002"]
    assert rows[0]["pick"] == "programme:P1" and rows[0]["value_score"] > 100 and "pick=programme:P1" in rows[0]["value_derivation"]
    assert rows[1]["pick"] == "value" and "pick=value" in rows[1]["value_derivation"]
    assert rows[1]["value_score"] < 10


# ── programme priority: a declared, ordered list the operator edits ─────────────────────────────────────────────


def cfg_with(priority):
    c = copy.deepcopy(CFG)
    c["value"]["programme_priority"] = priority
    return c


def prog_unit(i, prog, theme="live_strategy", usd=20, **kw):
    """A low-value programme node (programme_node + generated.family, as the emitter writes both)."""
    return job(i, theme, value={"bucket": "structural", "usd_at_stake_per_month": usd, "confidence": 0.2},
               routing={"est_minutes": 10}, programme_node={"programme": prog, "node": f"{prog}-Q1"},
               generated={"family": f"programme:{prog}", "key": f"programme:{prog}-Q1"}, **kw)


def test_the_committed_config_declares_the_operators_programme_priority_p1_then_p2():
    # Pinned to the operator's words (2026-10-18): P1 and P2 first, in that order. A re-prioritisation is a visible
    # edit of research_compute.yaml value.programme_priority, never drift.
    assert [str(x) for x in CFG["value"]["programme_priority"]] == ["P1", "P2"]


def test_a_p1_unit_outranks_a_higher_score_non_p1_unit_in_any_theme():
    p1 = prog_unit(1, "P1", usd=20)                                             # score ~3.4
    rich = job(2, "regime", value={"bucket": "structural", "usd_at_stake_per_month": 5000, "confidence": 0.9},
               routing={"est_minutes": 10})                                     # score ~4800
    rich_same_theme = job(3, "live_strategy", value={"bucket": "structural", "usd_at_stake_per_month": 5000,
                          "confidence": 0.9}, routing={"est_minutes": 10})
    order = ranked(dq.fair_order([rich, rich_same_theme, p1], NOW, TH, CFG))
    assert order[0] is p1 and p1.raw["_rank"]["rank_value"] < rich.raw["_rank"]["rank_value"]
    assert p1.raw["_rank"]["pick"] == "programme:P1" and p1.raw["_rank"]["programme_tier"] == 0
    assert rich.raw["_rank"]["programme_tier"] == 2                             # outside the list: len(list)


def test_programmes_rank_in_list_order_then_value_decides_inside_a_tier():
    p2_rich = prog_unit(1, "P2", theme="regime", usd=400)
    p1_poor = prog_unit(2, "P1", usd=20)
    p1_mid = prog_unit(3, "P1", theme="infra", usd=60)
    p5 = prog_unit(4, "P5", theme="regime", usd=900)                            # a programme, but not a listed one
    other = job(5, "infra", value={"bucket": "structural", "usd_at_stake_per_month": 300}, routing={"est_minutes": 10})
    order = ranked(dq.fair_order([other, p5, p1_poor, p2_rich, p1_mid], NOW, TH, CFG))
    assert [j.id for j in order] == [p1_mid.id, p1_poor.id, p2_rich.id, p5.id, other.id]
    assert p2_rich.raw["_rank"]["pick"] == "programme:P2" and p5.raw["_rank"]["pick"] == "value"


def test_the_list_is_the_priority_reordering_or_emptying_it_changes_the_dispatch():
    p2, p1 = prog_unit(1, "P2", theme="regime", usd=20), prog_unit(2, "P1", usd=20)
    rich = job(3, "infra", value={"bucket": "structural", "usd_at_stake_per_month": 5000, "confidence": 0.9},
               routing={"est_minutes": 10})
    assert [j.id for j in ranked(dq.fair_order([rich, p2, p1], NOW, TH, cfg_with(["P2", "P1"])))] == [p2.id, p1.id, rich.id]
    assert ranked(dq.fair_order([rich, p2, p1], NOW, TH, cfg_with([])))[0] is rich      # no list: pure money first
    assert ranked(dq.fair_order([rich, p2, p1], NOW, TH, cfg_with(["P1"])))[1] is rich  # P2 unlisted: by value


def test_a_starved_unit_still_goes_ahead_of_the_programme_priority():
    starved = job(1, "macro" if "macro" in TH["themes"] else "infra", priority=3, routing={"est_minutes": 300})
    starved.raw["id"] = "RQ-20291201-001"                                       # due ~40 days: past starve_hours
    p1 = prog_unit(2, "P1", usd=500)
    order = ranked(dq.fair_order([p1, starved], NOW, TH, CFG))
    assert order[0] is starved and order[1] is p1 and starved.raw["_rank"]["pick"] == "starved"


def test_programme_of_reads_the_node_field_or_the_generated_family():
    assert dq.programme_of({"programme_node": {"programme": "P1"}}) == "P1"
    assert dq.programme_of({"generated": {"family": "programme:P2"}}) == "P2"
    assert dq.programme_of({"generated": {"family": "e35-bracket"}}) == ""
    assert dq.programme_of({}) == ""
    assert dq.programme_tier({"generated": {"family": "programme:P1"}}, CFG) == 0
    assert dq.programme_tier({}, CFG) == len(CFG["value"]["programme_priority"])

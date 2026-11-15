"""LTR-APPLY-EXIT2 (2026-11-15): two direct-route live-review CLOSES on real money were refused with exit 2,
silently.

LR-20261115T0814Z-pkg-eb9ee0d2ec7e49cb (ADA long, bybit_2 + bybit_portfolio) and LR-20261115T0815Z-pkg-ec4066...
(SOL long, bybit_2 + bybit_portfolio + velotrade_1) were POSTed to /api/bot/live-review/rows. The watcher ran
``live_review_dispatch.py --local-root ...`` with no ``--ref``, so the dispatcher never materialized the outcome
table into the checkout. ``live_review_apply.py`` then refused ``--evidence comms/live_review/tables/...`` as "not a
file in the checkout" (exit 2) before any account. The watcher keeps only ``>>>`` lines, so the reason was lost,
and nothing pinged. Separately, the SOL row was handed over under the PROP-only auto mandate, which would have left
the bybit_2 real-money leg untouched even with the evidence fixed. Each test below fails on the pre-fix code.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts.ops import live_review_apply as lra
from scripts.ops import live_review_dispatch as d
from src.runtime import live_review_rows as rows_lib

RID = "LR-20261115T0814Z-pkg-eb9ee0d2ec7e49cb"
TABLE = f"comms/live_review/tables/{RID}.json"

CLOSE_ROW: Dict[str, Any] = {
    "review_id": RID, "order_package_id": "pkg-eb9ee0d2ec7e49cb", "leg": "ml_entry",
    "accounts": ["bybit_2", "bybit_portfolio"],
    "mechanics": {"verdict": "match", "evidence": "agree"},
    "outcome_table_source": TABLE, "packet_sha": "cb" * 32,
    "recommendation": {"action": "close", "level": None, "ev_delta_r": 0.1746, "worst_case_delta_r": 0.98,
                       "basis": "table", "confidence": "measured", "evidence_source": "table",
                       "reason": "close beats hold on the state-matched pullback cell, n=143"},
    "account_reads": [{"account_id": "bybit_2", "account_class": "real_money", "read": "would_apply", "evidence": "x"},
                      {"account_id": "bybit_portfolio", "account_class": "paper", "read": "would_apply",
                       "evidence": "x"}],
    "disposition": {"route": "recommended", "mandate": "MD-TRADE-DESK", "action_issue": None,
                    "applied_at": None, "verified_readback": None},
}
MEASURED = json.dumps({"read_state": "measured", "n_floor": 20})


@pytest.fixture
def direct(monkeypatch, tmp_path):
    """The DIRECT route: the row and its table live only under --local-root trees, never in the checkout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    direct_root, evidence_root = tmp_path / "direct", tmp_path / "local_evidence"
    w: Dict[str, Any] = {"calls": [], "rc": 0, "pings": [], "refusal": None, "repo": repo}

    def put(root: Path, rel: str, text: str) -> None:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)

    w["put_row"] = lambda row: put(direct_root, rows_lib.row_path(row["review_id"]), json.dumps(row))
    put(evidence_root, TABLE, MEASURED)
    w["put_row"](CLOSE_ROW)
    monkeypatch.setattr(d, "_REPO_ROOT", str(repo))
    monkeypatch.setattr(d, "EVIDENCE_DIR", repo / "runtime_logs" / "live_review" / "evidence")
    monkeypatch.setattr(d, "LOCAL_ROOTS", [direct_root, evidence_root])
    monkeypatch.setattr(d, "DISPATCH_STATE", tmp_path / "dispatch_state.json")
    monkeypatch.setattr(d, "APPLIED_LOG", tmp_path / "applied.jsonl")
    monkeypatch.setattr(d, "_ping", lambda row, line: w["pings"].append(line))
    # nothing is in git on the direct route: every read is a --local-root read
    monkeypatch.setattr(d, "_committed_text", lambda path, ref="HEAD": d._local_text(path))

    def run_apply(argv: List[str]) -> int:
        w["calls"].append(argv)
        pairs = dict(zip(argv[::2], argv[1::2]))
        # the apply's own first check (live_review_apply.main): the evidence must be a file in the checkout
        if "--apply" in argv and not Path(repo, pairs["--evidence"]).is_file():
            d._LAST_APPLY_REFUSAL[0] = f"evidence {pairs['--evidence']!r} is not a file in the checkout"
            return d.EXIT_REFUSED
        d._LAST_APPLY_REFUSAL[0] = w["refusal"]
        return w["rc"]
    monkeypatch.setattr(d, "_run_apply", run_apply)
    return w


def _pairs(argv: List[str]) -> Dict[str, str]:
    return dict(zip(argv[::2], argv[1::2]))


def test_a_direct_row_hands_the_apply_an_evidence_path_that_exists_in_the_checkout(direct):
    res = d.dispatch(RID, apply=True)
    ev = _pairs(direct["calls"][0])["--evidence"]
    assert Path(direct["repo"], ev).is_file(), ev
    assert Path(direct["repo"], ev).read_text() == MEASURED
    assert res["exit"] == 0 and res["verdict"] == "dispatched", res
    assert direct["pings"] == []


def test_a_refusal_inside_the_apply_on_a_money_row_pings_once_with_its_reason(direct):
    direct["rc"], direct["refusal"] = d.EXIT_REFUSED, "package pkg-eb9ee0d2ec7e49cb not open"
    res = d.dispatch(RID, apply=True)
    assert res["exit"] == d.EXIT_REFUSED and res["apply_refusal"] == "package pkg-eb9ee0d2ec7e49cb not open"
    assert len(direct["pings"]) == 1 and "not open" in direct["pings"][0] and RID in direct["pings"][0]
    d.dispatch(RID, apply=True)                         # nothing was sent, so a retry is allowed, but one ping
    assert len(direct["pings"]) == 1


def test_a_refusal_inside_the_apply_on_a_paper_only_row_does_not_ping(direct):
    row = copy.deepcopy(CLOSE_ROW)
    for a in row["account_reads"]:
        a["account_class"] = "paper"
    direct["put_row"](row)
    direct["rc"], direct["refusal"] = d.EXIT_REFUSED, "x"
    d.dispatch(RID, apply=True)
    assert direct["pings"] == []


def test_the_prop_auto_mandate_never_narrows_a_desk_covered_close_on_real_money(direct, monkeypatch):
    """On the REAL config/mandates.yaml: a close carried by bybit_2 (real money) AND velotrade_1 (prop) is
    scoped by MD-LTR-PROP-AUTO, but MD-TRADE-DESK covers it (nothing is advice-only), so the apply gets
    MD-TRADE-DESK and decides every account, real money included."""
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())
    row = copy.deepcopy(CLOSE_ROW)
    row["accounts"] = ["bybit_2", "bybit_portfolio", "velotrade_1"]
    direct["put_row"](row)
    from src.runtime import ltr_auto_mandate
    assert ltr_auto_mandate.exception_for(row) == "MD-LTR-PROP-AUTO"     # the interceptor is live in config
    d.dispatch(RID, apply=True)
    assert _pairs(direct["calls"][0])["--mandate"] == "MD-TRADE-DESK"


def test_the_auto_mandate_still_lifts_an_advice_only_action(direct, monkeypatch):
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ("close",))
    row = copy.deepcopy(CLOSE_ROW)
    row["accounts"] = ["velotrade_1"]
    row["account_reads"] = [{"account_id": "velotrade_1", "account_class": "prop", "read": "would_apply",
                             "evidence": "x"}]
    direct["put_row"](row)
    d.dispatch(RID, apply=True)
    assert _pairs(direct["calls"][0])["--mandate"] == "MD-LTR-PROP-AUTO"


def test_the_real_apply_refusal_line_is_recovered_from_its_stdout(capsys):
    """The real live_review_apply.main on the exact pre-fix argv shape: exit 2 and a bare line, which
    apply_refusal_line recovers (the watcher dropped it because it does not start with >>>)."""
    rc = lra.main(["--action", "close", "--package", "pkg-eb9ee0d2ec7e49cb", "--review-id", RID,
                   "--evidence", "comms/live_review/tables/does-not-exist.json", "--mandate", "MD-TRADE-DESK",
                   "--mechanics", "match", "--basis", "table", "--reason", "r", "--expected-cost-r", "0.1746",
                   "--apply"])
    out = capsys.readouterr().out
    assert rc == lra.EXIT_REFUSED
    assert d.apply_refusal_line(out) == ("evidence 'comms/live_review/tables/does-not-exist.json' "
                                         "is not a file in the checkout (it must be on main)")


def test_the_result_json_detail_wins_over_bare_lines():
    out = json.dumps({"exit": 2, "detail": "mandate MD-X does not scope pkg-1 / close", "accounts": []},
                     indent=2) + "\n"
    assert d.apply_refusal_line(out) == "mandate MD-X does not scope pkg-1 / close"
    assert d.apply_refusal_line("") is None


# ------------------------------------------------------------------ the watcher logs the full output tail

def test_the_watcher_keeps_the_non_marker_output_tail():
    from src.runtime import live_review_rows_watch as w
    out = ">>> live-review-apply: LR-x -> ...\nevidence 'x.json' is not a file in the checkout\n{\n  \"exit\": 2\n}\n"
    tail = w.output_tail(out, "Traceback: boom\n")
    assert "evidence 'x.json' is not a file in the checkout" in tail and "[stderr] Traceback: boom" in tail
    assert not any(ln.startswith(">>>") for ln in tail)
    assert len(w.output_tail("\n".join(f"l{i}" for i in range(100)))) == w.OUT_TAIL_LINES


def test_a_dispatched_row_logs_its_out_tail(tmp_path, monkeypatch):
    """The receipt line for a dispatched row carries the dispatcher's out_tail, so an exit 2 names its reason."""
    import json as _json
    from datetime import datetime, timezone
    from src.runtime import live_review_rows_watch as w
    from tests.test_live_review_rows_watch import FakeGit, row
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())

    def dispatch(rid, ref):
        return {"exit": 2, "verdict": "dispatched", "detail": None, "lines": [">>> refused"],
                "out_tail": ["evidence 'x.json' is not a file in the checkout"]}
    t0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    w.run_pass(git=FakeGit([]), dispatch=dispatch, now_fn=lambda: t0, logs=tmp_path)
    w.run_pass(git=FakeGit([row("LR-new")]), dispatch=dispatch, now_fn=lambda: t0, logs=tmp_path,
               alert=lambda text: True)
    recs = [_json.loads(x) for x in (tmp_path / "rows_watch.jsonl").read_text().splitlines()]
    assert recs[-1]["out_tail"] == ["evidence 'x.json' is not a file in the checkout"]

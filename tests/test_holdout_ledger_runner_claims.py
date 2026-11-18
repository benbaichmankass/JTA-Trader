"""Row HOLDOUT-LEDGER-RUNNER-CLAIMS (2026-11-15): a holdout claim made inside a runner job lands in the repo ledger.

Before: holdout_lock.claim_read appended to the runner checkout's comms/research/holdout_reads.jsonl, only
comms/research/<unit>/<run_id>/ came back as the artifact, and the claim was lost (n_tries undercounted)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import holdout_lock  # noqa: E402
from scripts.research import collect_runner_results as crr  # noqa: E402
from scripts.research import script_run  # noqa: E402


def _row(model_id, unit, start="2025-10-01", end="2026-09-30", **kw):
    return {"model_id": model_id, "family": model_id.split("-")[0], "start": start, "end": end, "unit": unit,
            "reader": "t", "read_at": kw.get("read_at", "2026-11-15T00:00:00Z"), "train_end": "2025-09-22"}


def _write(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_execute_copies_lines_the_run_appended_to_its_checkout_ledger(tmp_path):
    repo = tmp_path
    ledger = repo / script_run.HOLDOUT_LEDGER_REL
    _write(ledger, [_row("ENTRY-old", "RQ-old")])
    claimer = repo / "scripts" / "research" / "claimer.py"
    claimer.parent.mkdir(parents=True)
    claimer.write_text(
        "import json, pathlib\n"
        "p = pathlib.Path('comms/research/holdout_reads.jsonl')\n"
        "with p.open('a') as f: f.write(json.dumps({'model_id': 'ENTRY-new', 'start': '2025-10-01', 'end': '2026-09-30',"
        " 'unit': 'RQ-x'}) + '\\n')\n")
    plan = script_run.Plan("RQ-x", repo / "q.yaml", [[sys.executable, str(claimer)]], 5,
                           Path("comms/research/RQ-x/1"), "", "", [])
    man = script_run.execute(plan, repo=repo)
    assert man["holdout_claims"] == 1
    claims = (repo / "comms/research/RQ-x/1" / script_run.HOLDOUT_CLAIMS_NAME).read_text().splitlines()
    assert [json.loads(x)["model_id"] for x in claims] == ["ENTRY-new"]


def test_execute_with_no_claim_writes_no_claims_file(tmp_path):
    plan = script_run.Plan("RQ-y", tmp_path / "q.yaml", [[sys.executable, "-c", "pass"]], 5,
                           Path("comms/research/RQ-y/1"), "", "", [])
    man = script_run.execute(plan, repo=tmp_path)
    assert man["holdout_claims"] == 0
    assert not (tmp_path / "comms/research/RQ-y/1" / script_run.HOLDOUT_CLAIMS_NAME).exists()


def test_collector_merges_claims_file_and_reader_copy_without_duplicating_main_rows(tmp_path):
    root = tmp_path
    main = root / "comms/research/holdout_reads.jsonl"
    old = _row("ENTRY-old", "RQ-old")
    _write(main, [old])
    dest = root / "comms/research/RQ-x/7"
    _write(dest / "holdout_claims.jsonl", [_row("ENTRY-new", "RQ-x")])
    # a reader's out-dir COPY: main's old row (different read_at, same claim) + its own claim
    _write(dest / "ledger" / "holdout_reads.jsonl", [dict(old, read_at="2026-11-01T00:00:00Z"), _row("MANAGE-a", "RQ-x")])
    (root / "scripts/research").mkdir(parents=True)
    (root / "scripts/research/holdout_lock.py").write_text((ROOT / "scripts/research/holdout_lock.py").read_text())
    assert crr.merge_holdout_claims(root, dest) == 2
    ids = [json.loads(x)["model_id"] for x in main.read_text().splitlines()]
    assert ids == ["ENTRY-old", "ENTRY-new", "MANAGE-a"]
    assert crr.merge_holdout_claims(root, dest) == 0  # idempotent: a re-collect adds nothing


def test_merged_claim_counts_toward_the_next_bar(tmp_path):
    ledger = tmp_path / "l.jsonl"
    _write(ledger, [_row("ENTRY-a", "RQ-1")])
    src = tmp_path / "c.jsonl"
    _write(src, [_row("ENTRY-b", "RQ-2")])
    assert holdout_lock.next_bar("ENTRY", "2025-10-01", "2026-09-30", ledger=ledger)["n_tries"] == 2
    holdout_lock.merge_claims([src], ledger)
    assert holdout_lock.next_bar("ENTRY", "2025-10-01", "2026-09-30", ledger=ledger)["n_tries"] == 3


def test_key_keeps_two_windows_of_one_unit_and_drops_a_restarted_copy(tmp_path):
    ledger = tmp_path / "l.jsonl"
    _write(ledger, [_row("MANAGE-a", "RQ-1", start="2020-07-01", end="2026-09-30")])
    src = tmp_path / "c.jsonl"
    _write(src, [_row("MANAGE-a", "RQ-1", start="2020-10-20", end="2026-09-30"),   # same claim, approximate start
                 _row("MANAGE-a", "RQ-1", start="2026-10-01", end="2026-10-31")])  # a second window of the same unit
    added = holdout_lock.merge_claims([src], ledger)
    assert [(r["start"], r["end"]) for r in added] == [("2026-10-01", "2026-10-31")]

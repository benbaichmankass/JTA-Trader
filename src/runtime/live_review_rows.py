"""Read the review rows on ``live-review/rows`` at one commit: legacy ``reviews.jsonl`` + per-row files.

LTR-ROWS-SWAP-TRUNCATION (2026-10-27). A repo-less reviewer used to append its row by re-sending the
WHOLE ``comms/live_review/reviews.jsonl`` through a sha-guarded ``create_or_update_file``. The sha guard
proves the base blob was right, not that the body was: commit 3f1546c2d swapped 26 rows (71,121 B) for
4 rows plus a cut-off line when the reviewer's generation stopped mid-file. Since then each reviewer
creates ONE new file, ``comms/live_review/rows/<review_id>.json`` (create-only: an existing path means
already written), so a write no longer depends on the file's size. The legacy ``reviews.jsonl`` stays
readable so nothing already written is lost; scripted writers (``short_hold_write.py``) may still
append to it.

Every reader of the rows branch takes its rows from :func:`read_at`, and refuses a tip on which a
review_id it already saw is gone (:func:`lost_ids`): the branch is append-only, so a row that vanished
means the file was truncated or rewritten, and nothing is acted on from that tip.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

REVIEWS_PATH = "comms/live_review/reviews.jsonl"
ROWS_DIR = "comms/live_review/rows"

#: Actions a review row (or a desk decision) may RECOMMEND but no automatic path may EXECUTE.
#: Operator 2026-10-28 ~20:35Z, popup verbatim "Advice-only tightens (Recommended)", on the evidence of
#: LTR-TIGHTEN-OPTIMIZE (comms/research/ltr_tighten_optimize/verdict.json; DESK-LIFECYCLE-S0, PR #20967):
#: no stop-tighten cell or rule beat hold-to-bracket net of cost. Read by live_review_rows_watch,
#: live_review_dispatch and desk_intake; each logs the row as ADVICE_ONLY_VERDICT so it stays graded.
#: 2026-10-28 ~21:07Z EXTENDED to every in-trade class (operator popup to ask A1, verbatim "Advice-only until
#: tested", relayed by Manager session_01AFoLuJi1vLTnYv9LbP6539; row DESK-V1-MGMT-ADVICE-ONLY): each class is
#: recorded and graded but not executed until its OWN registered test passes (OOS, vs hold AND a matched random
#: intervention of the same class, net of cost; docs/plans/desk-v1-production-plan-2026-10-29.md § 5b).
#: GRADUATION = removing ONE class from this tuple AND from MD-TRADE-DESK functions.in_trade.advice_only in the
#: same PR, citing that class's committed passed-test record (tests/test_tighten_advice_only.py pins equality).
ADVICE_ONLY_ACTIONS = ("tighten_sl", "widen_sl", "move_tp", "partial_close", "close", "change_size", "add_entry")
ADVICE_ONLY_VERDICT = "advice_only"

#: ``git(*args) -> (returncode, stdout-or-stderr)``, the live_review_rows_watch seam.
Git = Callable[..., Tuple[int, str]]

#: blob sha -> parsed row (or the reason it is not one). Blobs are immutable, so this never goes stale.
_blob_cache: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str]]] = {}


def row_path(review_id: str) -> str:
    return f"{ROWS_DIR}/{review_id}.json"


def parse_legacy(text: str) -> Tuple[List[Dict[str, Any]], int]:
    """(rows with a review_id, count of non-empty lines that are not one) from a reviews.jsonl body."""
    rows, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(r, dict) and r.get("review_id"):
            rows.append(r)
        else:
            bad += 1
    return rows, bad


def parse_row_file(path: str, text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(row, None) or (None, why). One JSON object whose review_id is the file's name."""
    try:
        r = json.loads(text)
    except ValueError:
        return None, "not JSON"
    if not isinstance(r, dict) or not r.get("review_id"):
        return None, "not an object with a review_id"
    stem = path.rsplit("/", 1)[-1]
    if stem != f"{r['review_id']}.json":
        return None, f"file name does not match review_id {r['review_id']}"
    return r, None


def merge(legacy: Iterable[Dict[str, Any]], files: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Legacy rows in file order, then per-row files by (reviewed_at, review_id). One row per review_id:
    a legacy row keeps its place (it was written first); a per-row file adds only a new id."""
    out = list(legacy)
    have = {r["review_id"] for r in out}
    for r in sorted(files, key=lambda r: (str(r.get("reviewed_at") or ""), str(r["review_id"]))):
        if r["review_id"] not in have:
            have.add(r["review_id"])
            out.append(r)
    return out


def read_at(ref: str, git: Git) -> Dict[str, Any]:
    """Every row at ``ref``. ``state`` is ``ok`` or ``could_not_read`` (with ``detail``).

    ``rows``: merged (:func:`merge`); ``legacy_rows`` / ``file_rows``: counts; ``bad_lines``: legacy
    lines that are not a row (a cut-off line counts here); ``bad_files``: [{path, why}].
    A missing reviews.jsonl with per-row files present is fine (``legacy_present: False``).
    """
    rc_ls, listing = git("ls-tree", ref, "--", f"{ROWS_DIR}/")
    if rc_ls != 0:
        return {"state": "could_not_read", "detail": f"ls-tree {ROWS_DIR}: {listing[-200:]}"}
    rc, text = git("show", f"{ref}:{REVIEWS_PATH}")
    legacy_present = rc == 0
    if not legacy_present:
        # A path that does not exist at ref is fine once per-row files carry the rows; anything else is not.
        rc_t, typ = git("cat-file", "-t", ref)
        if rc_t != 0 or typ.strip() != "commit":
            return {"state": "could_not_read", "detail": f"show {REVIEWS_PATH}: {text[-200:]}"}
        text = ""
    legacy, bad = parse_legacy(text)
    files, bad_files = [], []
    for ln in listing.splitlines():
        meta, _, path = ln.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or parts[1] != "blob" or not path.endswith(".json"):
            continue
        blob = parts[2]
        if blob not in _blob_cache:
            rc_b, body = git("cat-file", "blob", blob)
            if rc_b != 0:
                return {"state": "could_not_read", "detail": f"cat-file {path}: {body[-200:]}"}
            _blob_cache[blob] = parse_row_file(path, body)
        r, why = _blob_cache[blob]
        if r is None:
            bad_files.append({"path": path, "why": why})
        else:
            files.append(r)
    return {"state": "ok", "rows": merge(legacy, files), "legacy_rows": len(legacy), "file_rows": len(files),
            "bad_lines": bad, "bad_files": bad_files, "legacy_present": legacy_present}


def find(ref: str, review_id: str, git: Git) -> Tuple[Optional[Dict[str, Any]], str]:
    """(row, where) for ONE review_id at ``ref``: its per-row file first, else the LAST legacy line
    with that id (the dispatcher's rule). ``where`` names the source, or why there is no row."""
    rc, body = git("show", f"{ref}:{row_path(review_id)}")
    if rc == 0:
        r, why = parse_row_file(row_path(review_id), body)
        return (r, row_path(review_id)) if r else (None, f"{row_path(review_id)}: {why}")
    rc, text = git("show", f"{ref}:{REVIEWS_PATH}")
    if rc != 0:
        return None, f"neither {row_path(review_id)} nor {REVIEWS_PATH} is readable at {ref}"
    found = None
    for r in parse_legacy(text)[0]:
        if r["review_id"] == review_id:
            found = r
    return (found, REVIEWS_PATH) if found else (None, f"{review_id} is in neither {row_path(review_id)} "
                                                      f"nor {REVIEWS_PATH} at {ref}")


def lost_ids(before: Iterable[str], rows: Iterable[Dict[str, Any]]) -> List[str]:
    """review_ids in ``before`` that are not in ``rows``: on an append-only branch, a shrunken file."""
    now = {r["review_id"] for r in rows}
    return sorted(set(before) - now)

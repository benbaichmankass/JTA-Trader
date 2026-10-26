"""`claude_judgments` dataset family (CJ-2-DATASET).

Design: ``docs/plans/ml-claude-distillation-DESIGN.md`` § 3-4.2 and
``docs/plans/claude-trading-desk-DESIGN.md`` § 4.1 / 4A. A POINT-IN-TIME
dataset over Claude's decisions, each joined to its realised outcome by a
stable id, so a student model can learn from the teacher's calls without
seeing anything the teacher could not.

Sources (all append-only JSONL on ``main``; the trainer git-pulls them):

* ``comms/live_review/reviews.jsonl`` -> ``kind: ltr_review`` (hold /
  tighten / ... calls on open packages, with ``judgement_confidence``).
  Outcome: ``comms/live_review/outcomes.jsonl`` (LTR-5) by ``review_id`` when
  present, else the journal's closed trade by ``trade_id``.
* ``comms/desk/decisions.jsonl`` -> ``kind: desk_<role>`` (entry generation,
  in-trade, exit). Outcome: ``comms/desk/outcomes.jsonl`` (DESK-20) by
  ``decision_id``. Both stores are empty until the desk writes rows; the
  family reads them so the pipe exists the day they do.
* ``comms/claude_judgments/blind_grades.jsonl`` -> ``kind: blind_grade`` and
  ``comms/claude_judgments/revealed_grades.jsonl`` -> ``kind: revealed_grade``
  (CJ-3, the blind-then-reveal post-trade grade, design § 4.3; producer
  ``scripts/ops/blind_grade.py``). Outcome: the journal's closed trade by
  ``trade_id``. A blind row's ``info_cutoff_at`` is the decision time, so it is
  T0 by construction; a revealed row saw the outcome and is T1 (label-only,
  excluded unless ``include_t1``). A blind row that computes T1 is refused
  (``blind_grade_not_t0``), never relabelled.

One row per (judgment). Columns fall in three disjoint groups, exported as
constants so the manifest lint (``scripts/ci/check_claude_judgments_manifests.py``,
guard ``claude-judgments-guard``) can refuse leakage mechanically:

* ``FEATURE_COLUMNS``  -- decision-time state, all as of ``info_cutoff_at``.
  For LTR rows this is the reviewer's ``features_at_review`` projection, i.e.
  exactly what the teacher was shown.
* ``JUDGMENT_COLUMNS`` -- the teacher's own output. A label, or bookkeeping;
  never a feature for a target in this family (§ 3.5 test 2).
* ``OUTCOME_COLUMNS``  -- realised after the decision. Labels only.

Labels: ``label_net_r`` is the trade's realised R net of the full measured
cost stack (``src.runtime.net_r_label``, with the PACKAGE's initial stop as
the risk basis -- ``trades.stop_loss`` is the trailed stop, see
``src/runtime/r_provenance.py``). ``cf_hold_r`` is the counterfactual hold.
``delta_r = label_net_r - cf_hold_r`` is the value of the call over holding.
For an LTR call that was NOT applied, the realised path IS the hold path, so
``cf_hold_r = label_net_r`` (``cf_source: realised_path_was_hold``); a
recommended-but-unapplied tighten therefore has ``delta_r`` null until LTR-5's
replay prices the recommended action (``cf_source: pending_replay``).

Leakage tests applied in the builder (§ 3.5):

1. Timestamp: a row whose ``info_cutoff_at`` is later than its ``judged_at``
   is refused (``cutoff_after_judged``). ``reviewed_at`` is minute-truncated
   by the LTR writer, so up to ``_JUDGED_ROUNDING_S`` seconds is tolerated
   and flagged on the row (``judged_at_rounded``), not silently passed.
   ``timing`` is COMPUTED (``T0`` iff ``info_cutoff_at < closed_at``), never
   read from a declared flag; ``T1`` rows saw the outcome and are excluded
   unless ``include_t1=true`` (label-only use).
4. Disjointness: every row carries ``order_package_id`` and ``trade_id`` and
   ``split_group`` (= the package) so a trainer splits by package, and a
   package reviewed several times or fanned out to several accounts cannot
   straddle folds.

Tests 2 (manifest lint) live in the guard. Test 3 (rubric reconstruction) is
for the legacy rubric file, which this v1 does not ingest (see below).

**The training marker (``never_trained_on``).** Desk rows carry
``training.train_eligible`` / ``exclusion_reasons`` (desk_decision schema
v2); an ineligible row is excluded with each reason counted. A row is also
excluded while its outcome is still inside its window -- the trade is open,
so there is nothing to learn from yet (``outcome_pending``) -- and, when
``holdout_days`` > 0, while it is younger than that holdout
(``holdout_window``). Every exclusion is counted by reason in the population
report (``population_report()``); nothing is dropped silently.

**Not ingested in v1:** ``comms/claude_strategy_scores.jsonl`` (the 4k-row
rubric file). It is T1 and ``author_kind`` is mostly ``rubric_script``, so it
is not a teacher (§ 4.2); it enters with the rubric-reconstruction test.

CLI (population report without writing a dataset)::

    python -m ml.datasets.families.claude_judgments --comms-root comms \\
        [--db-path data/trade_journal.db] [--holdout-days N]

The dataset build goes through the normal path
(``python -m ml build-dataset claude_judgments ... comms_root=... db_path=...``)
and is wired into ``scripts/ops/build_trainer_datasets.sh``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator, Mapping

from ..builder import DatasetBuilder
from ..metadata import LeakageStatus

# reviewed_at in comms/live_review/reviews.jsonl is written to the minute
# (MEASURED 2026-10-26 on main: 8 of 24 rows have info_cutoff_at 8 s after it).
_JUDGED_ROUNDING_S = 60

# Actions whose unapplied realised path is the hold path itself.
_HOLD_LIKE = frozenset({"hold", "no_recommendation", "flag_mechanics", "file_hypothesis"})

FEATURE_COLUMNS: tuple[str, ...] = (
    "f_open_r",
    "f_peak_r",
    "f_giveback_r",
    "f_atr_now_over_entry",
    "f_bars_since_peak",
    "f_r_to_stop",
    "f_r_to_target",
    "f_bars_held",
    "leg",
    "symbol",
    "direction",
    "account_class",
)
JUDGMENT_COLUMNS: tuple[str, ...] = (
    "grade_score",
    "decision_grade",
    "entry_quality",
    "risk_management",
    "exit_quality",
    "alternative_action",
    "p_win",
    "expected_r",
    "action",
    "level_atr",
    "ev_delta_r",
    "confidence",
    "judgement_confidence",
    "judge_prior",
    "basis",
    "applied",
    "model_tier",
)
OUTCOME_COLUMNS: tuple[str, ...] = (
    "label_net_r",
    "label_gross_r",
    "cf_hold_r",
    "delta_r",
    "closed_at",
    "exit_reason",
    "pnl_provenance",
    "cost_source",
    "outcome_source",
    "cf_source",
)


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    s = value.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "_meta" not in obj:
            out.append(obj)
    return out


def _journal_outcomes(db_path: Path | None, trade_ids: set[int]) -> dict[int, dict] | None:
    """Closed-trade facts by journal trade id, or None when the journal is absent.

    Read-only (``mode=ro``). The risk basis is the PACKAGE's ``sl`` (the
    initial stop); ``trades.stop_loss`` is mirrored from trailing amends.
    """
    if db_path is None or not Path(db_path).is_file():
        return None
    if not trade_ids:
        return {}
    from src.runtime.net_r_label import net_r_for_trade  # noqa: PLC0415
    from src.runtime.provenance import classify_pnl  # noqa: PLC0415

    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict[int, dict] = {}
    try:
        marks = ",".join("?" * len(trade_ids))
        rows = conn.execute(
            f"SELECT t.*, op.sl AS pkg_sl FROM trades t "
            f"LEFT JOIN order_packages op ON op.order_package_id = t.order_package_id "
            f"WHERE t.id IN ({marks})",
            sorted(trade_ids),
        ).fetchall()
    finally:
        conn.close()
    for r in rows:
        d = dict(r)
        closed = str(d.get("status") or "").lower() == "closed" and d.get("exit_price") is not None
        rec: dict[str, Any] = {
            "closed": closed,
            "closed_at": d.get("closed_at"),
            "exit_reason": d.get("exit_reason"),
            "symbol": d.get("symbol"),
            "direction": d.get("direction"),
            "account_class": d.get("account_class"),
            "net_r": None,
            "gross_r": None,
            "cost_source": None,
            "pnl_provenance": None,
        }
        if closed:
            basis = dict(d, stop_loss=d.get("pkg_sl"))
            lab = net_r_for_trade(basis) if d.get("pkg_sl") is not None else None
            if lab is not None:
                rec["net_r"] = lab["net_R"]
                rec["cost_source"] = lab["cost_source"]
                gross = _num(d.get("pnl"))
                rec["gross_r"] = round(gross / lab["risk_usd"], 8) if gross is not None else None
            rec["pnl_provenance"] = classify_pnl(d)[0]
        out[int(d["id"])] = rec
    return out


class ClaudeJudgmentsBuilder(DatasetBuilder):
    family: ClassVar[str] = "claude_judgments"
    builder_version: ClassVar[str] = "v1"
    # Tests 1 and 4 run in the builder; test 2 is the manifest guard.
    leakage_test_status: ClassVar[LeakageStatus] = LeakageStatus.PASSED
    label_version: ClassVar[str] = "cj-v1:net_r+cf_hold"
    schema: ClassVar[Mapping[str, type]] = {
        # identity / join keys
        "judgment_id": str,
        "kind": str,
        "source_file": str,
        "order_package_id": str,
        "trade_id": int,
        "split_group": str,
        "packet_sha": str,
        # timing (computed)
        "judged_at": str,
        "info_cutoff_at": str,
        "timing": str,
        "judged_at_rounded": bool,
        # label lineage
        "author_kind": str,
        "label_provenance": str,
        "row_label_version": str,
        "prompt_sha": str,
        "skill_sha": str,
        "train_eligible": bool,
        "gate_eligible": bool,
        "pre_cutoff": bool,
        # features (decision-time)
        "f_open_r": float,
        "f_peak_r": float,
        "f_giveback_r": float,
        "f_atr_now_over_entry": float,
        "f_bars_since_peak": float,
        "f_r_to_stop": float,
        "f_r_to_target": float,
        "f_bars_held": float,
        "leg": str,
        "symbol": str,
        "direction": str,
        "account_class": str,
        # judgment
        "grade_score": int,
        "decision_grade": str,
        "entry_quality": str,
        "risk_management": str,
        "exit_quality": str,
        "alternative_action": str,
        "p_win": float,
        "expected_r": float,
        "action": str,
        "level_atr": float,
        "ev_delta_r": float,
        "confidence": str,
        "judgement_confidence": float,
        "judge_prior": float,
        "basis": str,
        "applied": bool,
        "model_tier": str,
        # outcome / labels
        "label_net_r": float,
        "label_gross_r": float,
        "cf_hold_r": float,
        "delta_r": float,
        "closed_at": str,
        "exit_reason": str,
        "pnl_provenance": str,
        "cost_source": str,
        "outcome_source": str,
        "cf_source": str,
    }

    def __init__(self) -> None:
        self.last_report: dict[str, Any] = {}

    # ------------------------------------------------------------------ LTR
    def _ltr_rows(self, comms_root: Path, journal: dict[int, dict] | None,
                  excluded: Counter, as_of: datetime, holdout: timedelta,
                  include_t1: bool) -> Iterator[dict]:
        reviews = _read_jsonl(comms_root / "live_review" / "reviews.jsonl")
        ltr_out = {r.get("review_id"): r for r in _read_jsonl(comms_root / "live_review" / "outcomes.jsonl")}
        self.last_report["sources"]["ltr_review"] = len(reviews)
        for r in reviews:
            rid = r.get("review_id")
            judged = _parse_ts(r.get("reviewed_at"))
            cutoff = _parse_ts(r.get("info_cutoff_at"))
            if not rid or judged is None or cutoff is None:
                excluded["malformed"] += 1
                continue
            skew = (cutoff - judged).total_seconds()
            if skew > _JUDGED_ROUNDING_S:
                excluded["cutoff_after_judged"] += 1
                continue
            if holdout and as_of - judged < holdout:
                excluded["holdout_window"] += 1
                continue
            tid = r.get("trade_id")
            oc = ltr_out.get(rid)
            jr = journal.get(int(tid)) if (journal is not None and isinstance(tid, int)) else None
            if oc is not None:
                closed_at = _parse_ts(oc.get("closed_at"))
                net_r, gross_r = _num(oc.get("net_r")), None
                pnl_prov, cost_src, exit_reason = oc.get("pnl_provenance"), None, oc.get("exit_reason")
                outcome_source = "ltr_outcomes"
            elif jr is not None and jr["closed"]:
                closed_at = _parse_ts(jr["closed_at"])
                net_r, gross_r = jr["net_r"], jr["gross_r"]
                pnl_prov, cost_src, exit_reason = jr["pnl_provenance"], jr["cost_source"], jr["exit_reason"]
                outcome_source = "journal"
            elif jr is not None:
                excluded["outcome_pending"] += 1
                continue
            elif not isinstance(tid, int):
                excluded["no_trade_id"] += 1
                continue
            elif journal is None:
                excluded["outcome_unjoined_no_journal"] += 1
                continue
            else:
                excluded["outcome_unjoined_trade_not_in_journal"] += 1
                continue
            if net_r is None:
                excluded["outcome_no_net_r"] += 1
                continue
            timing = "T0" if (closed_at is None or cutoff < closed_at) else "T1"
            if timing == "T1" and not include_t1:
                excluded["t1_outcome_visible"] += 1
                continue
            rec = r.get("recommendation") or {}
            action = rec.get("action")
            applied = bool(r.get("applied"))
            if oc is not None and _num(oc.get("cf_r")) is not None:
                cf, cf_source = _num(oc.get("cf_r")), "ltr_replay"
            elif not applied:
                cf, cf_source = net_r, "realised_path_was_hold"
            else:
                cf, cf_source = None, "pending_replay"
            ltr_delta = _num(oc.get("delta_r")) if oc is not None else None
            if ltr_delta is not None:
                # LTR-5 priced the call itself (rec_r - cf_r). net_r - cf_r would read 0 for an
                # unapplied tighten, whose realised path IS the hold path.
                delta = round(ltr_delta, 8)
            elif action in _HOLD_LIKE or applied or cf_source == "ltr_replay":
                delta = round(net_r - cf, 8) if cf is not None else None
            else:
                # an unapplied tighten / tp_revise: the realised path is the hold,
                # the recommended path is unpriced until LTR-5 replays it
                delta, cf_source = None, "pending_replay"
            feats = r.get("features_at_review") or {}
            state = r.get("state") or {}
            yield {
                "judgment_id": rid,
                "kind": "ltr_review",
                "source_file": "comms/live_review/reviews.jsonl",
                "order_package_id": r.get("order_package_id"),
                "trade_id": tid,
                "split_group": r.get("order_package_id"),
                "packet_sha": r.get("packet_sha"),
                "judged_at": _iso(judged),
                "info_cutoff_at": _iso(cutoff),
                "timing": timing,
                "judged_at_rounded": skew > 0,
                "author_kind": "llm",
                "label_provenance": "measured" if outcome_source == "journal" else "computed",
                "row_label_version": f"llm:{(r.get('model') or 'unknown').split(' ')[0]}:"
                                     f"{(r.get('prompt_sha') or 'unknown')[:8]}:ltr@{r.get('schema_version')}",
                "prompt_sha": r.get("prompt_sha"),
                "skill_sha": r.get("skill_sha"),
                "train_eligible": True,
                "gate_eligible": True,
                "f_open_r": _num(feats.get("open_r")),
                "f_peak_r": _num(feats.get("peak_r")),
                "f_giveback_r": _num(feats.get("giveback_r")),
                "f_atr_now_over_entry": _num(feats.get("atr_now_over_entry")),
                "f_bars_since_peak": _num(feats.get("bars_since_peak")),
                "f_r_to_stop": _num(feats.get("r_to_stop")),
                "f_r_to_target": _num(feats.get("r_to_target")),
                "f_bars_held": _num(state.get("bars_held")),
                "leg": r.get("leg"),
                "symbol": jr["symbol"] if jr else None,
                "direction": jr["direction"] if jr else None,
                "account_class": jr["account_class"] if jr else None,
                "action": action,
                "level_atr": _num(rec.get("level_atr")),
                "ev_delta_r": _num(rec.get("ev_delta_r")),
                "confidence": rec.get("confidence"),
                "judgement_confidence": _num(rec.get("judgement_confidence")),
                "judge_prior": _num(r.get("judge_prior")),
                "basis": rec.get("basis"),
                "applied": applied,
                "model_tier": (r.get("model") or "").split(" ")[0] or None,
                "label_net_r": net_r,
                "label_gross_r": gross_r,
                "cf_hold_r": cf,
                "delta_r": delta,
                "closed_at": _iso(closed_at),
                "exit_reason": exit_reason,
                "pnl_provenance": pnl_prov,
                "cost_source": cost_src,
                "outcome_source": outcome_source,
                "cf_source": cf_source,
            }

    # ----------------------------------------------------------------- desk
    def _desk_rows(self, comms_root: Path, excluded: Counter, as_of: datetime,
                   holdout: timedelta) -> Iterator[dict]:
        decisions = _read_jsonl(comms_root / "desk" / "decisions.jsonl")
        outcomes: dict[str, list[dict]] = {}
        for o in _read_jsonl(comms_root / "desk" / "outcomes.jsonl"):
            outcomes.setdefault(o.get("decision_id"), []).append(o)
        self.last_report["sources"]["desk"] = len(decisions)
        for d in decisions:
            did = d.get("decision_id")
            judged = _parse_ts(d.get("judged_at"))
            cutoff = _parse_ts(d.get("info_cutoff_at"))
            if not did or judged is None or cutoff is None:
                excluded["malformed"] += 1
                continue
            if (cutoff - judged).total_seconds() > _JUDGED_ROUNDING_S:
                excluded["cutoff_after_judged"] += 1
                continue
            training = d.get("training") or {}
            if not training.get("train_eligible"):
                for reason in training.get("exclusion_reasons") or ["unstated"]:
                    excluded[f"never_train:{reason}"] += 1
                continue
            if holdout and as_of - judged < holdout:
                excluded["holdout_window"] += 1
                continue
            ocs = outcomes.get(did) or []
            realised = next((o for o in ocs if o.get("kind") == "realised" and _num(o.get("net_r")) is not None), None)
            replayed = next((o for o in ocs if o.get("kind") == "replayed" and _num(o.get("net_r")) is not None), None)
            chosen = realised or replayed
            if chosen is None:
                excluded["outcome_pending" if not ocs else "outcome_not_computable"] += 1
                continue
            computed_at = _parse_ts(chosen.get("computed_at"))
            if computed_at is not None and computed_at <= cutoff:
                excluded["outcome_before_cutoff"] += 1
                continue
            params = d.get("params") or {}
            proposal = d.get("proposal") or {}
            yield {
                "judgment_id": did,
                "kind": f"desk_{d.get('role')}",
                "source_file": "comms/desk/decisions.jsonl",
                "order_package_id": d.get("order_package_id") or chosen.get("order_package_id"),
                "trade_id": None,
                "split_group": d.get("order_package_id") or chosen.get("order_package_id") or did,
                "packet_sha": d.get("packet_sha"),
                "judged_at": _iso(judged),
                "info_cutoff_at": _iso(cutoff),
                "timing": "T0",
                "judged_at_rounded": (cutoff - judged).total_seconds() > 0,
                "author_kind": "llm",
                "label_provenance": chosen.get("provenance"),
                "row_label_version": f"llm:{d.get('model')}:{(d.get('prompt_sha') or 'unknown')[:8]}:"
                                     f"desk@{d.get('label_version')}",
                "prompt_sha": d.get("prompt_sha"),
                "skill_sha": d.get("skill_sha"),
                "train_eligible": True,
                "gate_eligible": bool(training.get("gate_eligible")),
                "f_open_r": None, "f_peak_r": None, "f_giveback_r": None,
                "f_atr_now_over_entry": None, "f_bars_since_peak": None,
                "f_r_to_stop": None, "f_r_to_target": None, "f_bars_held": None,
                "leg": "claude_desk",
                "symbol": proposal.get("symbol"),
                "direction": proposal.get("side"),
                "account_class": None,
                "action": d.get("action"),
                "level_atr": _num(params.get("level_atr")),
                "ev_delta_r": _num(proposal.get("expected_r_net")),
                "confidence": d.get("confidence"),
                "judgement_confidence": None,
                "judge_prior": _num(d.get("judge_prior")),
                "basis": d.get("basis"),
                "applied": any(a.get("applied") for a in (d.get("disposition") or {}).get("per_account") or []),
                "model_tier": d.get("model"),
                "label_net_r": _num(chosen.get("net_r")),
                "label_gross_r": None,
                "cf_hold_r": None,
                "delta_r": None,
                "closed_at": _iso(computed_at),
                "exit_reason": chosen.get("close_reason"),
                "pnl_provenance": chosen.get("provenance"),
                "cost_source": chosen.get("cost_policy"),
                "outcome_source": f"desk_outcomes:{chosen.get('kind')}",
                "cf_source": "pending_desk_20",
            }

    # --------------------------------------------------------- blind / reveal grades (CJ-3)
    def _grade_rows(self, comms_root: Path, journal: dict[int, dict] | None,
                    excluded: Counter, as_of: datetime, holdout: timedelta,
                    include_t1: bool) -> Iterator[dict]:
        d = comms_root / "claude_judgments"
        blind = _read_jsonl(d / "blind_grades.jsonl")
        revealed = _read_jsonl(d / "revealed_grades.jsonl")
        self.last_report["sources"]["blind_grade"] = len(blind)
        self.last_report["sources"]["revealed_grade"] = len(revealed)
        for r in blind + revealed:
            kind = r.get("kind")
            jid = r.get("judgment_id")
            judged = _parse_ts(r.get("judged_at"))
            cutoff = _parse_ts(r.get("info_cutoff_at"))
            if not jid or kind not in ("blind_grade", "revealed_grade") or judged is None or cutoff is None:
                excluded["malformed"] += 1
                continue
            if (cutoff - judged).total_seconds() > _JUDGED_ROUNDING_S:
                excluded["cutoff_after_judged"] += 1
                continue
            if holdout and as_of - judged < holdout:
                excluded["holdout_window"] += 1
                continue
            tid = r.get("trade_id")
            jr = journal.get(int(tid)) if (journal is not None and isinstance(tid, int)) else None
            if not isinstance(tid, int):
                excluded["no_trade_id"] += 1
                continue
            if journal is None:
                excluded["outcome_unjoined_no_journal"] += 1
                continue
            if jr is None:
                excluded["outcome_unjoined_trade_not_in_journal"] += 1
                continue
            if not jr["closed"]:
                excluded["outcome_pending"] += 1
                continue
            if jr["net_r"] is None:
                excluded["outcome_no_net_r"] += 1
                continue
            closed_at = _parse_ts(jr["closed_at"])
            timing = "T0" if (closed_at is None or cutoff < closed_at) else "T1"
            if kind == "revealed_grade":
                # T1 BY KIND: the grader was shown the outcome. Never by timestamp arithmetic --
                # the stored cutoff is second-truncated while journal closed_at carries
                # microseconds, so `cutoff < closed_at` read every pilot reveal row as T0
                # (MEASURED 2026-10-26: 50 of 50 on the journal mirror before this line).
                timing = "T1"
            if kind == "blind_grade" and timing != "T0":
                excluded["blind_grade_not_t0"] += 1
                continue
            if timing == "T1" and not include_t1:
                excluded["t1_outcome_visible"] += 1
                continue
            gs = r.get("revised_grade_score") if kind == "revealed_grade" else r.get("grade_score")
            dg = r.get("revised_decision_grade") if kind == "revealed_grade" else r.get("decision_grade")
            yield {
                "judgment_id": jid,
                "kind": kind,
                "source_file": f"comms/claude_judgments/{'blind' if kind == 'blind_grade' else 'revealed'}_grades.jsonl",
                "order_package_id": r.get("order_package_id"),
                "trade_id": tid,
                "split_group": r.get("order_package_id"),
                "packet_sha": r.get("packet_sha"),
                "judged_at": _iso(judged),
                "info_cutoff_at": _iso(cutoff),
                "timing": timing,
                "judged_at_rounded": (cutoff - judged).total_seconds() > 0,
                "author_kind": r.get("author_kind") or "llm",
                "label_provenance": "judgment",
                "row_label_version": f"llm:{r.get('model_id') or 'unknown'}:"
                                     f"{(r.get('prompt_sha') or 'unknown')[:8]}:{kind}@{r.get('mask_version')}",
                "prompt_sha": r.get("prompt_sha"),
                "skill_sha": None,
                "train_eligible": True,
                "gate_eligible": True,
                "pre_cutoff": r.get("pre_cutoff") if isinstance(r.get("pre_cutoff"), bool) else None,
                "leg": r.get("leg"),
                "symbol": jr["symbol"],
                "direction": jr["direction"],
                "account_class": jr["account_class"],
                "grade_score": gs if isinstance(gs, int) and not isinstance(gs, bool) else None,
                "decision_grade": dg,
                "entry_quality": r.get("entry_quality"),
                "risk_management": r.get("risk_management"),
                "exit_quality": r.get("exit_quality"),
                "alternative_action": r.get("alternative_action"),
                "p_win": _num(r.get("p_win")),
                "expected_r": _num(r.get("expected_r")),
                "model_tier": r.get("model_id"),
                "label_net_r": jr["net_r"],
                "label_gross_r": jr["gross_r"],
                "closed_at": _iso(closed_at),
                "exit_reason": jr["exit_reason"],
                "pnl_provenance": jr["pnl_provenance"],
                "cost_source": jr["cost_source"],
                "outcome_source": "journal",
                "cf_source": None,
            }

    # ----------------------------------------------------------------- main
    def iter_rows(
        self,
        *,
        comms_root: Path,
        db_path: Path | None = None,
        holdout_days: int = 0,
        include_t1: bool = False,
        **_: Any,
    ) -> Iterator[Mapping[str, Any]]:
        comms_root = Path(comms_root)
        if not comms_root.is_dir():
            raise FileNotFoundError(f"comms root not found at {comms_root}")
        as_of = datetime.now(timezone.utc)
        holdout = timedelta(days=int(holdout_days)) if holdout_days else timedelta(0)
        excluded: Counter = Counter()
        self.last_report = {"sources": {}, "emitted": 0, "excluded": excluded,
                            "journal": "absent" if db_path is None or not Path(db_path).is_file() else "read"}

        reviews = _read_jsonl(comms_root / "live_review" / "reviews.jsonl")
        grades = (_read_jsonl(comms_root / "claude_judgments" / "blind_grades.jsonl")
                  + _read_jsonl(comms_root / "claude_judgments" / "revealed_grades.jsonl"))
        tids = {r["trade_id"] for r in reviews + grades if isinstance(r.get("trade_id"), int)}
        journal = _journal_outcomes(Path(db_path) if db_path else None, tids)

        emitted: Counter = Counter()
        for gen in (self._ltr_rows(comms_root, journal, excluded, as_of, holdout, include_t1),
                    self._desk_rows(comms_root, excluded, as_of, holdout),
                    self._grade_rows(comms_root, journal, excluded, as_of, holdout, include_t1)):
            for row in gen:
                emitted[row["kind"]] += 1
                yield row
        self.last_report["emitted"] = sum(emitted.values())
        self.last_report["emitted_by_kind"] = dict(emitted)
        self.last_report["excluded"] = dict(excluded)
        print(json.dumps({"status": "claude_judgments_population", **population_report(self.last_report)}),
              file=sys.stderr)


def population_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """n read / n emitted (joined) / n excluded by reason -- the partition sums by construction."""
    n_in = sum(report.get("sources", {}).values())
    n_ex = sum(report.get("excluded", {}).values())
    return {
        "n_source_rows": n_in,
        "sources": dict(report.get("sources", {})),
        "n_emitted_joined": report.get("emitted", 0),
        "emitted_by_kind": dict(report.get("emitted_by_kind", {})),
        "n_excluded": n_ex,
        "excluded_by_reason": dict(report.get("excluded", {})),
        "partition_ok": n_in == n_ex + report.get("emitted", 0),
        "journal": report.get("journal"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="claude_judgments population report (no dataset written)")
    ap.add_argument("--comms-root", type=Path, default=Path("comms"))
    ap.add_argument("--db-path", type=Path, default=None)
    ap.add_argument("--holdout-days", type=int, default=0)
    ap.add_argument("--include-t1", action="store_true")
    a = ap.parse_args(argv)
    b = ClaudeJudgmentsBuilder()
    for _ in b.iter_rows(comms_root=a.comms_root, db_path=a.db_path,
                         holdout_days=a.holdout_days, include_t1=a.include_t1):
        pass
    print(json.dumps(population_report(b.last_report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

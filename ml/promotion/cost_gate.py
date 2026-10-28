"""Enforced cost-net promotion gate + deflated Sharpe (ML-TRAINING-PRINCIPLES-GAPS).

Practice principles M6 / M10 (``docs/reference/trading-and-model-practice-principles.md``):
promote on **out-of-sample decision value net of cost**, against the incumbent
and against simple and random baselines on the same decision points. A gain in
AUC or Brier over a constant is feature lift, not edge. Principle M5: deflate
for selection.

Operator Tier-2 approval 2026-10-28 ~07:36Z (popup, verbatim): "Yes, ship it
today (Recommended)" for: labels net of the full cost stack, plus an enforced
cost gate on model promotion, effective from the next training cycle; revert is
one config value (``config/ml_training.yaml::cost_net_labels``; when false this
gate is still computed and written, but never enforced).

**What is measured.** Each evaluation row carries a net R outcome (the family's
value column: ``r_multiple`` for entry decisions, ``fwd_r_multiple`` for the hold
decision). The model TAKES a row when its prediction clears the decision
threshold. Its decision value is the net R it collects per opportunity:
``sum(R of taken rows) / n_rows``. The same rows give the baselines:

- ``take_all``: the rule that takes every opportunity (``mean R``);
- ``take_none``: never act (``0``);
- ``matched_random``: take the same NUMBER of rows at random. Its expectation
  is ``take_rate * mean R`` (computed exactly, no random draw);
- ``champion``: the incumbent model's own decision value on the SAME rows,
  when one is at shadow/advisory and its state loads.

The gate PASSES only when the candidate's value is strictly greater than every
available comparator. It is APPLICABLE only to families with a value column;
for the others (regime/direction classifiers, execution quality) there is no
decision value to price yet, and the gate says ``not_applicable`` rather than
inventing one. That is a stated gap, not a pass.

**Cost basis.** Every evaluation row must be cost-net: ``label_cost_basis`` in
``{"net", "realized"}`` (realized = a real trade's journal pnl). A row with
``gross`` / ``harness`` / no basis makes the gate refuse (``eval_not_cost_net``)
— a gross evaluation cannot pass a cost gate.

**Deflated Sharpe (M5, report-only).** The candidate's taken-trade net R series
gets a probabilistic Sharpe ratio vs 0 (Bailey & López de Prado 2012) and a
deflated Sharpe ratio (Bailey & López de Prado 2014) whose benchmark is the
expected maximum Sharpe across ``n_trials`` configurations tried on the same
dataset. These are written into the evaluation report and metrics; they do not
gate.

Pure stdlib; never touches the order path. Scoring a model's predictions into
``(taken, net_r)`` pairs lives in ``ml.experiments.runner.score_decisions`` so
this module (imported by the registry, which the live trader imports) never
pulls the evaluator/predictor stack into the trader's import closure.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from statistics import NormalDist
from typing import Any, Mapping, Sequence

# Net-R value column per dataset family (an entry/hold decision with a priced
# outcome). A manifest may name its own via evaluator_config.cost_value_column.
VALUE_COLUMNS: Mapping[str, str] = {
    "setup_candidates": "r_multiple",
    "exit_candidates": "fwd_r_multiple",
    "conviction_meta": "r_multiple",
    "setup_labels_audit": "r_multiple",
}
NET_BASES: frozenset[str] = frozenset({"net", "realized"})
GATED_STAGES: frozenset[str] = frozenset({"shadow", "advisory"})

_EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def value_column_for(manifest: Any) -> str | None:
    cfg = dict(getattr(manifest, "evaluator_config", None) or {})
    if cfg.get("cost_value_column"):
        return str(cfg["cost_value_column"])
    family = getattr(getattr(manifest, "dataset", None), "family", None)
    return VALUE_COLUMNS.get(str(family or ""))


def decision_threshold(manifest: Any, value_column: str) -> float:
    """A head regressing the net R itself acts when it predicts R > 0; a
    probability head acts at its evaluator threshold (default 0.5)."""
    tcfg = dict(getattr(manifest, "trainer_config", None) or {})
    ecfg = dict(getattr(manifest, "evaluator_config", None) or {})
    if "decision_threshold" in ecfg:
        return float(ecfg["decision_threshold"])
    if tcfg.get("target_column") == value_column:
        return 0.0
    return float(ecfg.get("threshold", 0.5))


def decision_value(pairs: Sequence[tuple[bool, float]]) -> float | None:
    if not pairs:
        return None
    return sum(r for taken, r in pairs if taken) / len(pairs)


def _moments(xs: Sequence[float]) -> tuple[float, float, float, float] | None:
    n = len(xs)
    if n < 3:
        return None
    mu = statistics.fmean(xs)
    sd = statistics.pstdev(xs)
    if sd <= 0:
        return None
    m3 = sum((x - mu) ** 3 for x in xs) / n
    m4 = sum((x - mu) ** 4 for x in xs) / n
    return mu, sd, m3 / sd ** 3, m4 / sd ** 4


def probabilistic_sharpe(xs: Sequence[float], benchmark_sr: float = 0.0) -> float | None:
    """PSR: P(true per-trade Sharpe > benchmark) given n, skew and kurtosis."""
    mom = _moments(xs)
    if mom is None:
        return None
    mu, sd, skew, kurt = mom
    sr = mu / sd
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return None
    return _N.cdf((sr - benchmark_sr) * math.sqrt(len(xs) - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, n_obs: int) -> float:
    """Expected maximum Sharpe of ``n_trials`` zero-edge trials, each estimated
    from ``n_obs`` observations (null variance of the SR estimator ≈ 1/(n-1))."""
    if n_trials <= 1 or n_obs < 2:
        return 0.0
    sd_sr = math.sqrt(1.0 / (n_obs - 1))
    return sd_sr * (
        (1.0 - _EULER_GAMMA) * _N.inv_cdf(1.0 - 1.0 / n_trials)
        + _EULER_GAMMA * _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe(xs: Sequence[float], n_trials: int) -> float | None:
    return probabilistic_sharpe(xs, expected_max_sharpe(max(1, n_trials), len(xs)))


@dataclass
class CostGateResult:
    applicable: bool
    passed: bool
    enforced: bool
    reason: str
    value_column: str | None = None
    threshold: float | None = None
    n_rows: int = 0
    n_taken: int = 0
    take_rate: float | None = None
    candidate_value_r: float | None = None
    take_all_r: float | None = None
    take_none_r: float = 0.0
    matched_random_r: float | None = None
    champion_value_r: float | None = None
    champion_model_state_path: str | None = None
    eval_cost_bases: dict[str, int] = field(default_factory=dict)
    taken_sharpe: float | None = None
    psr: float | None = None
    dsr: float | None = None
    n_trials: int = 1

    @property
    def refuses(self) -> bool:
        """True when this result must stop a promotion / state swap."""
        return self.enforced and self.applicable and not self.passed

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["refuses"] = self.refuses
        return d

    def metrics(self) -> dict[str, float]:
        """Flat float metrics for the registry row (None → omitted)."""
        out: dict[str, float] = {
            "cost_gate_applicable": 1.0 if self.applicable else 0.0,
            "cost_gate_passed": 1.0 if self.passed else 0.0,
            "cost_gate_enforced": 1.0 if self.enforced else 0.0,
            "cost_net_n_trials": float(self.n_trials),
        }
        for key, val in (
            ("cost_net_value_r", self.candidate_value_r),
            ("cost_net_take_all_r", self.take_all_r),
            ("cost_net_matched_random_r", self.matched_random_r),
            ("cost_net_champion_value_r", self.champion_value_r),
            ("cost_net_take_rate", self.take_rate),
            ("cost_net_taken_sharpe", self.taken_sharpe),
            ("cost_net_psr", self.psr),
            ("cost_net_dsr", self.dsr),
        ):
            if val is not None:
                out[key] = float(val)
        return out


def not_applicable(reason: str, *, enforced: bool) -> CostGateResult:
    return CostGateResult(applicable=False, passed=False, enforced=enforced, reason=reason)


def evaluate_cost_gate(
    candidate_pairs: Sequence[tuple[bool, float]],
    *,
    eval_cost_bases: Mapping[str, int],
    value_column: str,
    threshold: float,
    enforced: bool,
    champion_pairs: Sequence[tuple[bool, float]] | None = None,
    champion_model_state_path: str | None = None,
    n_trials: int = 1,
) -> CostGateResult:
    """Decide the gate from scored ``(taken, net_r)`` pairs on the eval rows."""
    res = CostGateResult(
        applicable=True, passed=False, enforced=enforced, reason="",
        value_column=value_column, threshold=threshold,
        eval_cost_bases=dict(eval_cost_bases), n_trials=max(1, int(n_trials)),
        champion_model_state_path=champion_model_state_path,
    )
    n = len(candidate_pairs)
    res.n_rows = n
    if n == 0:
        res.reason = "no_scored_eval_rows"
        return res
    taken_r = [r for t, r in candidate_pairs if t]
    res.n_taken = len(taken_r)
    res.take_rate = res.n_taken / n
    mean_all = statistics.fmean(r for _, r in candidate_pairs)
    res.candidate_value_r = sum(taken_r) / n
    res.take_all_r = mean_all
    res.matched_random_r = res.take_rate * mean_all
    if taken_r:
        mom = _moments(taken_r)
        res.taken_sharpe = (mom[0] / mom[1]) if mom else None
        res.psr = probabilistic_sharpe(taken_r)
        res.dsr = deflated_sharpe(taken_r, res.n_trials)
    if champion_pairs:
        res.champion_value_r = decision_value(champion_pairs)

    gross_rows = sum(c for b, c in eval_cost_bases.items() if b not in NET_BASES)
    if gross_rows:
        res.reason = (
            f"eval_not_cost_net: {gross_rows} of {sum(eval_cost_bases.values())} "
            f"eval rows have a basis outside {sorted(NET_BASES)} ({dict(eval_cost_bases)})"
        )
        return res
    comparators = {
        "take_all": res.take_all_r,
        "take_none": res.take_none_r,
        "matched_random": res.matched_random_r,
    }
    if res.champion_value_r is not None:
        comparators["champion"] = res.champion_value_r
    best_name, best = max(comparators.items(), key=lambda kv: kv[1])
    if res.candidate_value_r > best:
        res.passed = True
        res.reason = (
            f"beats all comparators: value {res.candidate_value_r:+.4f}R/opp > "
            f"best {best_name} {best:+.4f}R/opp (n={n}, taken={res.n_taken})"
        )
    else:
        res.reason = (
            f"does_not_beat_{best_name}: value {res.candidate_value_r:+.4f}R/opp <= "
            f"{best:+.4f}R/opp (n={n}, taken={res.n_taken})"
        )
    return res


def gate_from_entry(entry: Any) -> dict[str, Any] | None:
    """The cost gate recorded with ``entry``'s current (served) run, or None."""
    m = dict(getattr(entry, "metrics", None) or {})
    if "cost_gate_applicable" not in m:
        return None
    return {
        "applicable": bool(m.get("cost_gate_applicable")),
        "passed": bool(m.get("cost_gate_passed")),
        "enforced": bool(m.get("cost_gate_enforced")),
        "value_r": m.get("cost_net_value_r"),
    }

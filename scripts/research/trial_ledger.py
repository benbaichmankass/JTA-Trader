#!/usr/bin/env python3
# wiring: research/queue/RQ-20261016-6013-01.yaml (weekly, research-script-run.yml) regenerates the ledger
"""The programme-level TRIAL LEDGER: how many configurations were tried per (leg, family), and what
that does to every Stage-0 evidence record once the selection is deflated.

WHY THIS EXISTS (checklist row RESEARCH-TRIAL-LEDGER; benchmark
docs/research/research-ops-benchmark-2026-10-16.md § 2, "Multiple testing at programme level")
-----------------------------------------------------------------------------------------------
We LOG trials but nothing COUNTED them. The Stage-0 rule (`RULE-D1-STAGE0-NET-OF-FULL-COST`,
net_r_oos > 0) and the `MD-PROMOTE-*` bars cannot see how many configurations were tried before the
one that passed, and at ~80 research fires a day the factory WILL produce passes by chance (Winton:
the best of 100 skill-free strategies has p ~ 0.15). This file counts them and deflates.

⚠️ REPORT-ONLY. Operator decision 2026-10-16 (PROMOTION-BAR-MULTIPLICITY, verbatim "Measure first
(Recommended)"): nothing here changes a bar, a mandate, a roster or a config. The ledger is the
measurement the decision comes back with.

WHAT IS COUNTED (the population, stated -- CLAUDE.md "Always state the population")
---------------------------------------------------------------------------------
A CONFIGURATION is one distinct parameterisation backtested on a leg. Three sources, folded:

  1. ``docs/research/m20-sweep-corpus.jsonl`` -- every ``kind: cell`` row; one config per distinct
     ``(lever, cell, split)``. Rows from re-runs of the same cell are the same config.
  2. ``research/results/**/*.jsonl`` (E5 records) with ``read_state: measured`` that carry a BACKTEST
     statistic: each ``measurement.arms`` entry with a ``net_r``, a row whose ``measurement.leg`` sits
     beside a net-R statistic, and each ``measurement.legs[]`` element that carries one. One config per
     distinct ``(research_unit, arm | label)`` -- a weekly re-ask of the same arm is the same config.
     NOT counted (they choose no configuration): live-vs-backtest reads, parity/walk checks, prop-EV
     sizing arms, and E5 rows that point at the m20 corpus (already counted in 1).
  3. ``comms/strategy_evidence/<leg>.json`` -- the record's own config (its ``config_fingerprint``).

``research/queue/*.yaml`` grading blocks are folded into the "what has been tried" INDEX (unit id,
title, graded verdict) for every leg a unit's results or ``--leg`` argument name. They add no
configs: the configs they tried are already in source 2.

EFFECTIVE N
-----------
Configs on one (leg, family) are not independent -- a trail-mult sweep is one idea, not 28. Where a
per-trade series exists (E5 arm ``--emit-trades`` files, ``measurement.trades_file``, the evidence
record's ``source_run``), configs are clustered on the correlation of their daily net-R series
(complete linkage: a config joins a cluster only if it correlates >= ``CLUSTER_RHO`` with EVERY
member). effective N = clusters among the series-bearing configs + every config WITHOUT a series.
The second term is an UPPER BOUND and labelled as one (``effective_n_basis``): an m20 cell row has no
per-trade series, so it can only be counted at face value.

THE DEFLATED STATISTICS, per evidence record, at N = that (leg, family)'s effective N
-------------------------------------------------------------------------------------
Per-trade series = the record's ``source_run`` (OOS trades, net of the full cost stack).

* **DSR** (Bailey & Lopez de Prado 2014). SR = mean/sd of per-trade net R; SR0 = the expected max
  SR of N skill-free trials = sqrt(V) * ((1-g)*Z(1-1/N) + g*Z(1-1/(N*e))), g = Euler-Mascheroni,
  V = 1/(T-1) (the null sampling variance of a per-trade SR: we hold no cross-trial SR series for
  m20 cells, so V is the null's, and the record says so). DSR = Phi((SR-SR0)*sqrt(T-1) /
  sqrt(1 - skew*SR + (kurt-1)/4*SR^2)). N = 1 -> SR0 = 0 (the probabilistic SR).
* **Harvey-Liu haircut** (2015). t = SR*sqrt(T), two-sided p. Adjusted p: Bonferroni p*N; Holm; BHY
  p*N*sum(1/i, i=1..N). ⚠️ Only N is known, not the other N-1 p-values, so the record is treated as
  the MOST significant of its N (the conservative convention): Holm's first step then EQUALS
  Bonferroni, and the field says so rather than pretending to a separate number. t_adj =
  Z(1-p_adj/2); haircut net expectancy = expectancy_r_oos * t_adj / t (0 when p_adj >= 1). A
  non-positive expectancy is not haircut -- it already fails.

SURVIVAL (the question the operator asked): DSR > 0.95 AND BHY-haircut net expectancy > 0.

The weekly unit writes the ledger + a ``verdict.json`` under its ``{out_dir}``; the committed
snapshot is ``comms/research/trial_ledger.json`` (the default ``--out``).

Tier-1 research tooling: reads config/accounts.yaml (to label real-money legs) and the research
stores; writes only the ledger (and verdict.json). No config write, no live path, no orders.

    python3 scripts/research/trial_ledger.py                       # write comms/research/trial_ledger.json
    python3 scripts/research/trial_ledger.py --real-money-table    # the n_configs table, print only
    python3 scripts/research/trial_ledger.py --out '{out_dir}'     # the weekly runner form
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, Iterable, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path("comms") / "research" / "trial_ledger.json"
M20_CORPUS = Path("docs") / "research" / "m20-sweep-corpus.jsonl"
RESULTS_DIR = Path("research") / "results"
QUEUE_DIR = Path("research") / "queue"
EVIDENCE_DIR = Path("comms") / "strategy_evidence"
ACCOUNTS = Path("config") / "accounts.yaml"

SCHEMA_VERSION = 1
#: The weekly unit's own rule: its rows are the ledger, not trials, and are never counted.
LEDGER_RULE_ID = "RULE-RQ20261016-6013-01-TRIAL-LEDGER-BUILD"
#: Complete-linkage threshold on daily net-R correlation. Declared, not tuned.
CLUSTER_RHO = 0.5
#: A series needs this many non-zero days to be correlated at all; thinner ones count at face value.
MIN_SERIES_DAYS = 5
DSR_BAR = 0.95
EULER_GAMMA = 0.5772156649015329
_Z = NormalDist()

#: E5 measurement keys that mean "this row is a backtest of a configuration".
_BACKTEST_KEYS = ("net_r", "net_total_r", "net_expectancy_r", "net_r_pooled")


# ── family ──────────────────────────────────────────────────────────────────
_FAMILY_RULES: Tuple[Tuple[str, str], ...] = (
    ("ict_scalp", "ict_scalp"), ("fvg_range", "fvg_range"), ("squeeze", "squeeze"),
    ("fade", "fade"), ("turtle_soup", "turtle_soup"), ("pullback", "pullback"),
    ("trend", "trend"), ("chop_scalp", "chop_scalp"), ("pairs", "pairs"),
    ("funding", "funding_carry"), ("orb", "orb"), ("vwap", "vwap"),
)


def family_of(leg: str, evidence: Optional[Dict[str, Any]] = None) -> str:
    """The evidence record's own `harness` when it has one (field beats name); else a name rule."""
    if evidence and isinstance(evidence.get("harness"), str) and evidence["harness"]:
        return evidence["harness"]
    low = leg.lower()
    for token, fam in _FAMILY_RULES:
        if token in low:
            return fam
    return "unclassified"


def key_of(leg: str, family: str) -> str:
    return f"{leg}::{family}"


# ── readers ─────────────────────────────────────────────────────────────────
def _jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_evidence(root: Path) -> Dict[str, Dict[str, Any]]:
    """Every ``comms/strategy_evidence/*.json`` by file stem (53 on 2026-10-16: 52 leg records + 1 h2h)."""
    out: Dict[str, Dict[str, Any]] = {}
    for f in sorted((root / EVIDENCE_DIR).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out[f.stem] = {"_unreadable": True}
            continue
        out[f.stem] = d if isinstance(d, dict) else {"_unreadable": True}
    return out


def real_money_legs(root: Path) -> List[str]:
    """Legs on a `real_money` account in `live` mode, in config order (bybit_2 then alpaca_live today)."""
    import yaml
    try:
        accts = (yaml.safe_load((root / ACCOUNTS).read_text(encoding="utf-8")) or {}).get("accounts") or {}
    except (OSError, yaml.YAMLError) as exc:
        # Could not look: said loudly, and the ledger's `real_money_legs: []` is then that, not "none".
        print(f"::warning::trial_ledger: {ACCOUNTS} unreadable ({exc}); no leg is labelled real-money", file=sys.stderr)
        return []
    out: List[str] = []
    for _name, acc in accts.items():
        if not isinstance(acc, dict):
            continue
        if acc.get("account_class") == "real_money" and acc.get("mode") == "live":
            for leg in acc.get("strategies") or []:
                if isinstance(leg, str) and leg not in out:
                    out.append(leg)
    return out


def _series_from_trades(root: Path, rel: Optional[str]) -> Optional[Dict[str, float]]:
    """Daily net-R buckets from a per-trade JSONL (exit_time, else entry_time). None when absent."""
    if not rel or ".." in str(rel):
        return None
    path = root / str(rel)
    if not path.is_file():
        return None
    days: Dict[str, float] = defaultdict(float)
    for row in _jsonl(path):
        r = row.get("net_r")
        when = row.get("exit_time") or row.get("entry_time")
        if isinstance(r, (int, float)) and isinstance(when, str) and len(when) >= 10:
            days[when[:10]] += float(r)
    return dict(days) if days else None


def _trade_returns(root: Path, rel: Optional[str]) -> Optional[List[float]]:
    if not rel or ".." in str(rel):
        return None
    path = root / str(rel)
    if not path.is_file():
        return None
    out = [float(r["net_r"]) for r in _jsonl(path) if isinstance(r.get("net_r"), (int, float))]
    return out or None


class Config:
    __slots__ = ("key", "source", "series", "label")

    def __init__(self, key: str, source: str, label: str, series: Optional[Dict[str, float]] = None):
        self.key, self.source, self.label, self.series = key, source, label, series


def fold_m20(root: Path, add) -> Dict[str, Any]:
    rows = cells = 0
    for r in _jsonl(root / M20_CORPUS):
        rows += 1
        if r.get("kind") != "cell" or not isinstance(r.get("leg"), str):
            continue
        cells += 1
        lever, cell, split = r.get("lever"), r.get("cell"), r.get("split")
        add(r["leg"], Config(f"m20:{lever}:{cell}:{split}", "m20", f"{lever}:{cell}"),
            tried=("m20_levers", str(lever)))
    return {"path": M20_CORPUS.as_posix(), "sha256": _sha256(root / M20_CORPUS), "rows": rows, "cell_rows": cells}


def _emit_trades_path(argv: Any) -> Optional[str]:
    if isinstance(argv, list) and "--emit-trades" in argv:
        i = argv.index("--emit-trades")
        if i + 1 < len(argv) and isinstance(argv[i + 1], str):
            return argv[i + 1]
    return None


def fold_e5(root: Path, add, touch) -> Dict[str, Any]:
    files = rows = measured = counted = 0
    for f in sorted(glob.glob(str(root / RESULTS_DIR / "*" / "*.jsonl"))):
        files += 1
        for d in _jsonl(Path(f)):
            rows += 1
            if d.get("read_state") != "measured":
                continue
            measured += 1
            if ((d.get("decision_rule") or {}).get("id")) == LEDGER_RULE_ID:
                continue
            unit = str(d.get("research_unit") or Path(f).parent.name)
            m = d.get("measurement") if isinstance(d.get("measurement"), dict) else {}
            leg = m.get("leg") if isinstance(m.get("leg"), str) else None
            if leg:
                touch(leg, unit)
            for x in m.get("legs") if isinstance(m.get("legs"), list) else []:
                if isinstance(x, dict) and isinstance(x.get("leg"), str):
                    touch(x["leg"], unit)
            if "m20-sweep-corpus" in str((d.get("artifact") or {}).get("store") or ""):
                continue
            arms = m.get("arms")
            if leg and isinstance(arms, dict) and arms:
                for arm, v in arms.items():
                    if isinstance(v, dict) and isinstance(v.get("net_r"), (int, float)):
                        counted += 1
                        add(leg, Config(f"e5:{unit}:{arm}", "e5", f"{unit}:{arm}",
                                        _series_from_trades(root, _emit_trades_path(v.get("argv")))),
                            tried=("e5_units", unit))
                continue
            if leg and any(isinstance(m.get(k), (int, float)) for k in _BACKTEST_KEYS):
                label = str(m.get("label") or m.get("run_label") or "")
                counted += 1
                add(leg, Config(f"e5:{unit}:{label}", "e5", f"{unit}:{label}" if label else unit,
                                _series_from_trades(root, m.get("trades_file"))),
                    tried=("e5_units", unit))
            for x in m.get("legs") if isinstance(m.get("legs"), list) else []:
                if (isinstance(x, dict) and isinstance(x.get("leg"), str)
                        and any(isinstance(x.get(k), (int, float)) for k in _BACKTEST_KEYS)):
                    counted += 1
                    add(x["leg"], Config(f"e5:{unit}:{x['leg']}", "e5", unit,
                                         _series_from_trades(root, x.get("trades_file"))),
                        tried=("e5_units", unit))
    return {"glob": f"{RESULTS_DIR.as_posix()}/*/*.jsonl", "files": files, "rows": rows,
            "measured_rows": measured, "config_entries": counted}


_LEG_ARG = re.compile(r"^[a-z0-9_]+$")


def fold_queue(root: Path, touch) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """{unit: {title, status, verdict, graded_at}} for every unit, and touch() each --leg it names."""
    import yaml
    units: Dict[str, Dict[str, Any]] = {}
    n = graded = 0
    for f in sorted((root / QUEUE_DIR).glob("RQ-*.yaml")):
        try:
            u = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            # skipped from the index, and said so; the unit's own validator refuses it
            print(f"::warning::trial_ledger: {f.name} unreadable ({exc}); not indexed", file=sys.stderr)
            continue
        if not isinstance(u, dict):
            continue
        n += 1
        uid = str(u.get("id") or f.stem)
        g = u.get("grading") if isinstance(u.get("grading"), dict) else {}
        graded += bool(g)
        units[uid] = {"title": str(u.get("title") or "")[:160], "status": u.get("status"),
                      "verdict": g.get("verdict"), "graded_at": g.get("graded_at")}
        run = u.get("run") if isinstance(u.get("run"), dict) else {}
        cmds = run.get("commands") or ([run["command"]] if run.get("command") else [])
        for argv in cmds if isinstance(cmds, list) else []:
            if isinstance(argv, list):
                for i, tok in enumerate(argv[:-1]):
                    if tok == "--leg" and isinstance(argv[i + 1], str) and _LEG_ARG.match(argv[i + 1]):
                        touch(argv[i + 1], uid)
    return units, {"glob": f"{QUEUE_DIR.as_posix()}/RQ-*.yaml", "units": n, "graded_units": graded}


# ── effective N ─────────────────────────────────────────────────────────────
def _corr(a: Dict[str, float], b: Dict[str, float]) -> float:
    days = sorted(set(a) | set(b))
    n = len(days)
    if n < 2:
        return 0.0
    xs = [a.get(d, 0.0) for d in days]
    ys = [b.get(d, 0.0) for d in days]
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def cluster_count(series: List[Dict[str, float]], rho: float = CLUSTER_RHO) -> int:
    """Complete-linkage clusters: a series joins the first cluster it correlates >= rho with EVERY
    member of; otherwise it opens a new one. Deterministic in input order (configs are key-sorted)."""
    clusters: List[List[int]] = []
    for i, s in enumerate(series):
        for c in clusters:
            if all(_corr(s, series[j]) >= rho for j in c):
                c.append(i)
                break
        else:
            clusters.append([i])
    return len(clusters)


def effective_n(configs: List[Config]) -> Tuple[int, str, int, int]:
    """(effective N, basis, n_with_series, n_clusters)."""
    with_series = [c for c in configs if c.series and sum(1 for v in c.series.values() if v) >= MIN_SERIES_DAYS]
    without = len(configs) - len(with_series)
    k = cluster_count([c.series for c in with_series]) if with_series else 0
    if not configs:
        return 0, "no_configs", 0, 0
    if not with_series:
        basis = "n_configs_upper_bound (no per-trade series on any config)"
    elif without:
        basis = (f"partial: {k} return-correlation clusters over {len(with_series)} configs with a series "
                 f"+ {without} without a series counted at face value (upper bound)")
    else:
        basis = f"clustered: {k} return-correlation clusters over {len(with_series)} configs (rho >= {CLUSTER_RHO})"
    return k + without, basis, len(with_series), k


# ── deflation ───────────────────────────────────────────────────────────────
def _moments(r: List[float]) -> Tuple[float, float, float, float]:
    """mean, sample sd (ddof 1), skew, raw (non-excess) kurtosis."""
    n = len(r)
    mu = sum(r) / n
    m2 = sum((x - mu) ** 2 for x in r) / n
    sd = math.sqrt(m2 * n / (n - 1)) if n > 1 else 0.0
    if m2 <= 0:
        return mu, sd, 0.0, 3.0
    m3 = sum((x - mu) ** 3 for x in r) / n
    m4 = sum((x - mu) ** 4 for x in r) / n
    return mu, sd, m3 / m2 ** 1.5, m4 / m2 ** 2


def expected_max_sr(n_trials: int, var: float) -> float:
    if n_trials <= 1:
        return 0.0
    return math.sqrt(var) * ((1 - EULER_GAMMA) * _Z.inv_cdf(1 - 1 / n_trials)
                             + EULER_GAMMA * _Z.inv_cdf(1 - 1 / (n_trials * math.e)))


def dsr(returns: List[float], n_trials: int) -> Dict[str, Any]:
    t = len(returns)
    mu, sd, skew, kurt = _moments(returns)
    if t < 3 or sd <= 0:
        return {"state": "insufficient_series", "n": t}
    sr = mu / sd
    sr0 = expected_max_sr(n_trials, 1.0 / (t - 1))
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if denom <= 0:
        return {"state": "degenerate_moments", "n": t, "sr": sr, "skew": skew, "kurtosis": kurt}
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)
    z1 = sr * math.sqrt(t - 1) / math.sqrt(denom)
    # `psr_n1` is the same statistic at N = 1 (no deflation): it separates "too few trades to clear
    # 0.95 even alone" from "would clear alone, fails once the N configs tried are counted".
    return {"state": "computed", "n": t, "sr_per_trade": round(sr, 6), "skew": round(skew, 6),
            "kurtosis": round(kurt, 6), "sr0": round(sr0, 6), "dsr": round(_Z.cdf(z), 6),
            "psr_n1": round(_Z.cdf(z1), 6), "series_mean_r": round(mu, 6)}


def haircut(returns: List[float], n_trials: int, expectancy: Optional[float]) -> Dict[str, Any]:
    t_n = len(returns)
    mu, sd, _s, _k = _moments(returns) if t_n else (0.0, 0.0, 0.0, 3.0)
    if t_n < 3 or sd <= 0 or not isinstance(expectancy, (int, float)):
        return {"state": "insufficient_series"}
    t = mu / sd * math.sqrt(t_n)
    p = 2 * (1 - _Z.cdf(abs(t)))
    n = max(1, n_trials)
    c_n = sum(1.0 / i for i in range(1, n + 1))
    out: Dict[str, Any] = {"state": "computed", "t_stat": round(t, 6), "p_single": p,
                           "convention": "record treated as the most significant of its N (only N is known); "
                                         "Holm's first step then equals Bonferroni"}
    for name, p_adj in (("bonferroni", p * n), ("holm", p * n), ("bhy", p * n * c_n)):
        p_adj = min(1.0, p_adj)
        if expectancy <= 0 or t <= 0:
            hx, t_adj = float(expectancy), None
        elif p_adj >= 1.0:
            hx, t_adj = 0.0, 0.0
        else:
            t_adj = _Z.inv_cdf(1 - p_adj / 2)
            hx = float(expectancy) * min(1.0, t_adj / t)
        out[name] = {"p_adj": p_adj, "t_adj": None if t_adj is None else round(t_adj, 6),
                     "haircut_expectancy_r": round(hx, 6)}
    return out


# ── build ───────────────────────────────────────────────────────────────────
def build(root: Path = _REPO, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    evidence = load_evidence(root)
    legs_ev = {d["strategy"]: (stem, d) for stem, d in evidence.items()
               if isinstance(d.get("strategy"), str)}
    configs: Dict[str, Dict[str, Config]] = defaultdict(dict)
    tried_idx: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    touched: Dict[str, set] = defaultdict(set)
    fam_cache: Dict[str, str] = {}

    def fam(leg: str) -> str:
        if leg not in fam_cache:
            fam_cache[leg] = family_of(leg, legs_ev.get(leg, (None, None))[1])
        return fam_cache[leg]

    def add(leg: str, cfg: Config, *, tried: Tuple[str, str]) -> None:
        k = key_of(leg, fam(leg))
        prior = configs[k].get(cfg.key)
        if prior is None or (cfg.series and not prior.series):
            configs[k][cfg.key] = cfg
        tried_idx[k][tried[0]][tried[1]] += 1

    def touch(leg: str, unit: str) -> None:
        touched[key_of(leg, fam(leg))].add(unit)

    inputs: Dict[str, Any] = {"m20": fold_m20(root, add), "e5": fold_e5(root, add, touch)}
    units, inputs["queue"] = fold_queue(root, touch)
    for leg, (stem, d) in legs_ev.items():
        fp = d.get("config_fingerprint") or stem
        add(leg, Config(f"evidence:{fp}", "evidence", stem, _series_from_trades(root, d.get("source_run"))),
            tried=("evidence_records", stem))
    inputs["evidence"] = {"dir": EVIDENCE_DIR.as_posix(), "records": len(evidence),
                          "leg_records": len(legs_ev)}

    real_money = real_money_legs(root)
    ledger_legs: Dict[str, Any] = {}
    for k in sorted(set(configs) | set(touched)):
        leg, family = k.split("::", 1)
        cfgs = [configs[k][c] for c in sorted(configs[k])]
        eff, basis, n_series, n_clusters = effective_n(cfgs)
        by_src: Dict[str, int] = defaultdict(int)
        for c in cfgs:
            by_src[c.source] += 1
        unit_ids = sorted(touched.get(k, set()) | set(tried_idx[k].get("e5_units", {})))
        ledger_legs[k] = {
            "leg": leg, "family": family, "real_money": leg in real_money,
            "n_configs": len(cfgs), "n_configs_by_source": dict(sorted(by_src.items())),
            "effective_n": eff, "effective_n_basis": basis,
            "n_configs_with_series": n_series, "n_clusters": n_clusters,
            "tried": {
                "m20_levers": dict(sorted(tried_idx[k].get("m20_levers", {}).items())),
                "e5_configs_by_unit": dict(sorted(tried_idx[k].get("e5_units", {}).items())),
                "queue_units": [{"unit": u, **units[u]} if u in units else {"unit": u, "status": "not_in_queue_dir"}
                                for u in unit_ids],
                "evidence_records": sorted(tried_idx[k].get("evidence_records", {})),
            },
        }

    families: Dict[str, Dict[str, int]] = defaultdict(lambda: {"legs": 0, "n_configs": 0, "effective_n": 0})
    for row in ledger_legs.values():
        f = families[row["family"]]
        f["legs"] += 1
        f["n_configs"] += row["n_configs"]
        f["effective_n"] += row["effective_n"]

    records: Dict[str, Any] = {}
    for stem in sorted(evidence):
        d = evidence[stem]
        rule = d.get("decision_rule") if isinstance(d.get("decision_rule"), dict) else {}
        if d.get("_unreadable"):
            records[stem] = {"state": "unreadable"}
            continue
        leg = d.get("strategy")
        if not isinstance(leg, str):
            records[stem] = {"state": "not_a_leg_record",
                             "why": "no `strategy` field (e.g. a head-to-head record); no leg N applies",
                             "id": d.get("id"), "verdict": rule.get("verdict")}
            continue
        k = key_of(leg, fam(leg))
        row = ledger_legs.get(k) or {}
        n_used = max(1, int(row.get("effective_n") or 1))
        rec: Dict[str, Any] = {
            "leg": leg, "family": fam(leg), "real_money": leg in real_money,
            "coverage_state": d.get("coverage_state"), "fidelity": d.get("fidelity"),
            "stage0_verdict": rule.get("verdict"), "stage0_rule": rule.get("id"),
            "net_r_oos": d.get("net_r_oos"), "expectancy_r_oos": d.get("expectancy_r_oos"),
            "n_trades_oos": d.get("n_trades_oos"),
            "param_selection_provenance": d.get("param_selection_provenance"),
            "n_configs": row.get("n_configs"), "N_used": n_used, "N_basis": row.get("effective_n_basis"),
            "source_run": d.get("source_run"),
        }
        rets = _trade_returns(root, d.get("source_run"))
        if not rets:
            rec["state"] = "no_series"
            rec["why"] = (f"coverage_state={d.get('coverage_state')!r}; source_run "
                          f"{'absent' if not d.get('source_run') else 'not readable'} -- no per-trade series, "
                          "no deflated statistic (we could not look; NOT a fail)")
            records[stem] = rec
            continue
        rec["state"] = "computed"
        rec["dsr"] = dsr(rets, n_used)
        rec["haircut"] = haircut(rets, n_used, d.get("expectancy_r_oos"))
        exp = d.get("expectancy_r_oos")
        smean = rec["dsr"].get("series_mean_r")
        rec["series_cross_check"] = (
            "ok" if isinstance(exp, (int, float)) and isinstance(smean, (int, float)) and abs(exp - smean) < 1e-3
            else f"MISMATCH: expectancy_r_oos={exp} vs source_run mean={smean}")
        dval = rec["dsr"].get("dsr")
        hb = (rec["haircut"].get("bhy") or {}).get("haircut_expectancy_r")
        hbf = (rec["haircut"].get("bonferroni") or {}).get("haircut_expectancy_r")
        rec["survives"] = {
            "dsr_gt_0_95": isinstance(dval, float) and dval > DSR_BAR,
            "haircut_bhy_gt_0": isinstance(hb, float) and hb > 0,
            "haircut_bonferroni_gt_0": isinstance(hbf, float) and hbf > 0,
        }
        rec["survives"]["both"] = rec["survives"]["dsr_gt_0_95"] and rec["survives"]["haircut_bhy_gt_0"]
        records[stem] = rec

    passes = [s for s, r in records.items() if r.get("stage0_verdict") == "pass"]
    survive = [s for s in passes if (records[s].get("survives") or {}).get("both")]
    order = sorted(passes, key=lambda s: (not records[s].get("real_money"), s))
    summary = {
        "evidence_records": len(records),
        "with_deflated_statistic": sum(1 for r in records.values() if r.get("state") == "computed"),
        "stage0_pass": len(passes),
        "stage0_pass_surviving_dsr_and_bhy_haircut": len(survive),
        "stage0_pass_clearing_0_95_at_n1": sum(
            1 for s in passes if ((records[s].get("dsr") or {}).get("psr_n1") or 0) > DSR_BAR),
        "stage0_pass_bonferroni_haircut_gt_0": sum(
            1 for s in passes if (records[s].get("survives") or {}).get("haircut_bonferroni_gt_0")),
        "real_money_legs": real_money,
        "stage0_pass_table": [
            {"record": s, "real_money": records[s]["real_money"], "N_used": records[s]["N_used"],
             "n_configs": records[s]["n_configs"], "net_r_oos": records[s]["net_r_oos"],
             "dsr": (records[s].get("dsr") or {}).get("dsr"),
             "psr_n1": (records[s].get("dsr") or {}).get("psr_n1"),
             "haircut_bhy_expectancy_r": ((records[s].get("haircut") or {}).get("bhy") or {}).get("haircut_expectancy_r"),
             "survives": (records[s].get("survives") or {}).get("both")}
            for s in order],
    }
    when = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": when,
        "generated_by": "scripts/research/trial_ledger.py",
        "report_only": True,
        "report_only_basis": "operator decision 2026-10-16, PROMOTION-BAR-MULTIPLICITY: \"Measure first (Recommended)\" "
                             "-- no bar, mandate, roster or config changes on this ledger",
        "key": "leg::family",
        "method": {"cluster_rho": CLUSTER_RHO, "min_series_days": MIN_SERIES_DAYS, "dsr_bar": DSR_BAR,
                   "sr_variance_basis": "null sampling variance 1/(T-1) of a per-trade SR",
                   "haircut_methods": ["bonferroni", "holm", "bhy"], "survival": "dsr > 0.95 AND bhy haircut expectancy > 0"},
        "inputs": inputs,
        "summary": summary,
        "families": dict(sorted(families.items())),
        "legs": ledger_legs,
        "evidence": records,
    }


def real_money_table(ledger: Dict[str, Any]) -> str:
    rows = ["| leg | family | n_configs (m20 / e5 / evidence) | effective N | net_r_oos | n_trades_oos | Stage-0 |",
            "|---|---|---|---|---|---|---|"]
    by_leg = {r["leg"]: r for r in ledger["evidence"].values() if isinstance(r.get("leg"), str)}
    for leg in ledger["summary"]["real_money_legs"]:
        ev = by_leg.get(leg, {})
        lr = ledger["legs"].get(key_of(leg, ev.get("family") or family_of(leg)), {})
        src = lr.get("n_configs_by_source", {})
        rows.append(f"| {leg} | {lr.get('family')} | {lr.get('n_configs')} ({src.get('m20', 0)} / {src.get('e5', 0)} / "
                    f"{src.get('evidence', 0)}) | {lr.get('effective_n')} | {ev.get('net_r_oos')} | "
                    f"{ev.get('n_trades_oos')} | {ev.get('stage0_verdict')} |")
    return "\n".join(rows)


def verdict_for(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """The weekly unit's verdict.json: PASS iff every leg evidence record carries N and either a deflated
    statistic or a stated reason it has none (`no_series` / `not_a_leg_record`)."""
    recs = ledger["evidence"]
    ok_states = {"computed", "no_series", "not_a_leg_record"}
    bad = [s for s, r in recs.items() if r.get("state") not in ok_states
           or (r.get("state") == "computed" and not r.get("N_used"))]
    s = ledger["summary"]
    return {
        "verdict": "pass" if recs and not bad else "indeterminate",
        "read_state": "measured" if recs else "no_data",
        "population": f"{len(recs)} comms/strategy_evidence records; {len(ledger['legs'])} (leg, family) keys",
        "n": len(recs) if recs else None,
        "measurement": {"stage0_pass": s["stage0_pass"],
                        "stage0_pass_surviving_dsr_and_bhy_haircut": s["stage0_pass_surviving_dsr_and_bhy_haircut"],
                        "with_deflated_statistic": s["with_deflated_statistic"], "records_without_state": bad},
        "note": "report-only (PROMOTION-BAR-MULTIPLICITY: Measure first); ledger at trial_ledger.json beside this file",
        "data_inputs": [M20_CORPUS.as_posix()],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", default=str(_REPO), help="repo root (tests only)")
    ap.add_argument("--out", default="", help=f"ledger path, or a directory (writes trial_ledger.json + verdict.json); "
                                              f"default {DEFAULT_OUT.as_posix()}")
    ap.add_argument("--real-money-table", action="store_true", help="print the real-money n_configs table; write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root)
    ledger = build(root)
    if args.real_money_table:
        print(real_money_table(ledger))
        return 0
    out = Path(args.out) if args.out else root / DEFAULT_OUT
    if not out.is_absolute():
        out = root / out
    if out.suffix != ".json":
        out.mkdir(parents=True, exist_ok=True)
        (out / "verdict.json").write_text(json.dumps(verdict_for(ledger), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        out = out / "trial_ledger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    s = ledger["summary"]
    print(f"wrote {out} : {s['evidence_records']} evidence records, {len(ledger['legs'])} (leg, family) keys, "
          f"{s['stage0_pass']} Stage-0 PASS, {s['stage0_pass_surviving_dsr_and_bhy_haircut']} survive DSR>0.95 + BHY haircut>0")
    return 0


if __name__ == "__main__":
    sys.exit(main())

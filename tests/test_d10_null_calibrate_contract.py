"""--null-calibrate must emit a research-result-contract verdict (2026-11-19: it wrote "report", the collector logged
producer_failed "verdict.json malformed" and the non-verdict retry ran RQ-20261119-b9d0-01 a second time)."""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_null_verdict_is_in_the_result_contract():
    d10 = _load("d10_basset_baseline_t", "scripts/research/d10_basset_baseline.py")
    sr = _load("script_run_t", "scripts/research/script_run.py")
    for ex, p, draws, n, legs in ((0.2, 0.01, 40, 675, 24), (-0.0107, 0.5122, 40, 675, 24), (0.02, 0.10, 40, 675, 24),
                                  (-0.01, 0.5, 20, 675, 24), (-0.01, 0.5, 40, 150, 24)):
        cal = {"learned": {"pooled": {"excess": ex, "p_one_sided": p, "draws": draws}},
               "cusum": {"pooled": {"excess": 0.14, "p_one_sided": 0.005}}}
        v, _why = d10.null_verdict(cal, n, legs)
        assert v in sr.VERDICTS, v


def test_no_report_verdict_token_in_the_harness():
    src = (REPO / "scripts/research/d10_basset_baseline.py").read_text()
    assert '"verdict": "report"' not in src

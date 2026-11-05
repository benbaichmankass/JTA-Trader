"""RQ-20261104-a41f-01 harness self-test (planted illiquid ETF excluded by the dev-window filter; PASS record round-trips through
src/config/ml_universe.load) plus the frozen pool-rule hash."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_entry_alpaca_score as S  # noqa: E402


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/ml_entry_alpaca_score.py"), "--self-test"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "self-test ok" in r.stdout, r.stdout + r.stderr


def test_pool_rule_is_frozen():
    # changing POOL_RULE changes this hash; the unit registers it (research/queue/RQ-20261104-a41f-01.yaml::etf_rule_sha256)
    assert S.POOL_RULE_SHA256 == hashlib.sha256(json.dumps(S.POOL_RULE, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert S.MIN_MEDIAN_DV == 50_000_000.0 and (S.DEV_START, S.DEV_END) == ("2019-01-01", "2020-12-31") and S.POOL_START == "2021-01-01"


def test_default_path_flags_unchanged():
    assert S.HOLDOUT_START == "2025-10-01" and S.FETCH_START == "2025-05-01"

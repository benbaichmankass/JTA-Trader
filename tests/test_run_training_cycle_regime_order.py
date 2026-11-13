"""The default manifest list trains regime heads last, and only every Nth UTC day (row ML-D2-CONSUMER-TEST, Tier 2)."""
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]
SH = (REPO / "scripts/ops/run_training_cycle.sh").read_text()
BLOCK = SH[SH.index('  _regime_n="${REGIME_HEAD_CYCLE_EVERY_N_DAYS:-3}"'):SH.index("  # Opt-in nightly rotation")]


def _run(day: str, n: str) -> list[str]:
    script = f'''set -euo pipefail
emit(){{ echo "EMIT $1"; }}; iso_now(){{ echo T; }}
date(){{ echo {day}; }}
export REGIME_HEAD_CYCLE_EVERY_N_DAYS={n}
TRAINING_MANIFEST_LIST=(ml/configs/a-head.yaml ml/configs/btc-regime-x.yaml ml/configs/b-head.yaml ml/configs/eth-regime-y.yaml)
{BLOCK}
printf '%s\\n' "${{TRAINING_MANIFEST_LIST[@]}}"
'''
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True, cwd=REPO).stdout.split("\n")
    return [x.rsplit("/", 1)[-1] for x in out if x.startswith("ml/")]


def test_regime_heads_last_on_their_day():
    assert _run("003", "3") == ["a-head.yaml", "b-head.yaml", "btc-regime-x.yaml", "eth-regime-y.yaml"]


def test_regime_heads_skipped_off_day_but_others_train():
    assert _run("004", "3") == ["a-head.yaml", "b-head.yaml"]


def test_every_day_knob_reverts_to_nightly():
    assert _run("004", "1") == ["a-head.yaml", "b-head.yaml", "btc-regime-x.yaml", "eth-regime-y.yaml"]


def test_bad_knob_falls_back_to_three():
    assert _run("004", "0") == ["a-head.yaml", "b-head.yaml"]

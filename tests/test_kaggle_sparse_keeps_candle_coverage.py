"""PI-20261118-EFILLW47-0003: the Kaggle research workflows must keep comms/research/candle_dataset/coverage.json in their sparse checkout.

MEASURED 2026-11-19: RQ-20261118-abab-04 ran on kaggle_cpu AFTER the candle dataset and its coverage record were published and merged, and still
fetched candles over the network (no 'candle dataset' line in cmd-0.log; the bundle info line said "published_data": []). The cause: the
workflows' sparse checkout excluded the whole `/comms/research/` directory, so candle_dataset.load_coverage() read nothing, covers() answered
False ("no candle dataset coverage record") and kaggle_run.py never mounted the dataset. The dispatcher's own checkout keeps the file, which is why
it routed 16 units to kaggle_cpu on a coverage record the kernel's bundle step could not see.
"""
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows"
NAMES = ("research-script-run-kaggle-cpu.yml", "research-script-run-kaggle.yml")


def _sparse_lines(name: str) -> list:
    doc = yaml.safe_load((WF / name).read_text())
    steps = next(iter(doc["jobs"].values()))["steps"]
    w = next(s["with"] for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    return [ln.strip() for ln in w["sparse-checkout"].splitlines() if ln.strip()]


def test_the_sparse_set_does_not_exclude_the_whole_comms_research_directory():
    for name in NAMES:
        lines = _sparse_lines(name)
        assert "!/comms/research/" not in lines, f"{name}: drops comms/research/candle_dataset/coverage.json"
        assert any(ln.startswith("!/comms/research/RQ-") for ln in lines), f"{name}: no longer excludes the 5 GB per-unit data"
        assert "!/comms/macro/" in lines


def test_a_real_sparse_checkout_with_that_set_keeps_the_coverage_record_and_drops_unit_data(tmp_path):
    def git(*a, **k):
        return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=tmp_path, check=True,
                              capture_output=True, text=True, **k)
    git("init", "-q")
    (tmp_path / "comms/research/RQ-1").mkdir(parents=True)
    (tmp_path / "comms/research/candle_dataset").mkdir(parents=True)
    (tmp_path / "comms/research/RQ-1/f.json").write_text("{}")
    (tmp_path / "comms/research/candle_dataset/coverage.json").write_text("{}")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/x.py").write_text("x")
    git("add", "-A")
    git("commit", "-qm", "i")
    for name in NAMES:
        git("sparse-checkout", "set", "--no-cone", "--stdin", input="\n".join(_sparse_lines(name)) + "\n")
        assert (tmp_path / "comms/research/candle_dataset/coverage.json").is_file(), name
        assert not (tmp_path / "comms/research/RQ-1/f.json").exists(), name
        assert (tmp_path / "scripts/x.py").is_file(), name

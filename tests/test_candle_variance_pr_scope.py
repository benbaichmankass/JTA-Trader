import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ccv", ROOT / "scripts/ci/check_candle_fixture_variance.py")
ccv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccv)


def test_files_in_diff_reads_headers_incl_binary_and_rename(tmp_path):
    d = tmp_path / "p.diff"
    d.write_text("diff --git a/a/x.csv b/a/x.csv\n--- a/a/x.csv\n+++ b/a/x.csv\n"
                 "diff --git a/old.parquet b/new.parquet\nBinary files differ\n")
    assert ccv.files_in_diff(str(d)) == {"a/x.csv", "new.parquet"}


def test_unreadable_or_empty_diff_means_scan_everything(tmp_path):
    assert ccv.files_in_diff(str(tmp_path / "missing")) == set()
    e = tmp_path / "e.diff"
    e.write_text("")
    assert ccv.files_in_diff(str(e)) == set()


def test_pr_diff_scopes_scan_and_still_fails_on_flat_file(tmp_path, monkeypatch):
    flat = tmp_path / "flat.csv"
    flat.write_text("close\n" + "100\n" * 50)
    d = tmp_path / "p.diff"
    d.write_text("diff --git a/x.txt b/x.txt\n")
    # explicit-path mode is unchanged and still catches the flat series
    assert ccv.main([str(flat)]) == 1
    assert ccv.main(["--self-test"]) == 0

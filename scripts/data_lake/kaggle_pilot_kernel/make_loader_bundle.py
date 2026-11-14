#!/usr/bin/env python3
# wiring: .github/workflows/hf-lake-kaggle-loader-proof.yml (builds the kernel source from kernel_loader_proof.py)
"""Embed the repo files the lake loader needs into kernel_loader_proof.py (a kernel has no repo checkout and no internet).

    make_loader_bundle.py --out DIR     writes DIR/kernel_loader_proof.py with __BUNDLE_B64__ replaced

Bundle = tracked files only: the loader (ml/datasets/lake.py + lake_mirror.py), the lake resampler and config/data_universe.yaml. The kernel
stubs the ``ml`` / ``ml.datasets`` package markers, so the dataset-family modules (which import src/) are not needed to read the lake. Public repo code and config only; no data, no secret.
"""
from __future__ import annotations

import argparse
import base64
import io
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PATHS = ["ml/datasets/lake.py", "ml/datasets/lake_mirror.py", "scripts/data_lake/resample.py", "config/data_universe.yaml"]


def bundle_b64() -> str:
    files = subprocess.check_output(["git", "ls-files", "--", *PATHS], cwd=REPO, text=True).split()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for f in files:
            tf.add(REPO / f, arcname=f)
    return base64.b64encode(buf.getvalue()).decode()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    src = (Path(__file__).with_name("kernel_loader_proof.py")).read_text()
    assert "__BUNDLE_B64__" in src
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kernel_loader_proof.py").write_text(src.replace("__BUNDLE_B64__", bundle_b64()))
    print(f"kernel source written: {(out / 'kernel_loader_proof.py').stat().st_size} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

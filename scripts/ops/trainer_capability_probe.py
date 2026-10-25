#!/usr/bin/env python3
"""Trainer-venv capability probe (FRONTIER-LEVER-TRAINER-DEPS, 2026-10-12).

Prints, for each package the ML research bake-offs may need, whether it
imports in the CURRENT interpreter, its version, and the versions of the
stack it must coexist with (torch, transformers, huggingface_hub, numpy,
scikit-learn). Read-only: no network, no files written. Exit code is 0
always -- a missing arm is a reported fact (``scripts/research/ml_bakeoff.py``
marks the arm ``unavailable``), not a failure of the probe.

Run on the trainer:
    /home/ubuntu/ict-trading-bot/.venv/bin/python scripts/ops/trainer_capability_probe.py

Each line is ``<name> <OK|MISSING|BROKEN> <version> [detail]``; a final
``pip check`` line reports resolver-level conflicts in the venv.
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import subprocess
import sys

# (label, import name, distribution name)
STACK = [
    ("torch", "torch", "torch"),
    ("transformers", "transformers", "transformers"),
    ("huggingface_hub", "huggingface_hub", "huggingface-hub"),
    ("numpy", "numpy", "numpy"),
    ("scikit-learn", "sklearn", "scikit-learn"),
    ("lightgbm", "lightgbm", "lightgbm"),
    ("chronos-forecasting", "chronos", "chronos-forecasting"),
]
ARMS = [
    ("catboost", "catboost", "catboost"),
    ("timesfm", "timesfm", "timesfm"),
    ("tirex", "tirex", "tirex-ts"),
    ("tabpfn", "tabpfn", "tabpfn"),
    ("tabicl", "tabicl", "tabicl"),
]


def _probe(label: str, mod: str, dist: str) -> str:
    try:
        version = md.version(dist)
    except md.PackageNotFoundError:
        version = "-"
    try:
        importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name == mod:
            return f"{label} MISSING {version}"
        return f"{label} BROKEN {version} missing-dep={e.name}"
    except Exception as e:  # noqa: BLE001 - report, never raise
        return f"{label} BROKEN {version} {type(e).__name__}: {str(e)[:160]}"
    return f"{label} OK {version}"


def main() -> int:
    print(f"python {sys.version.split()[0]}")
    for group, rows in (("stack", STACK), ("arms", ARMS)):
        print(f"--- {group}")
        for row in rows:
            print(_probe(*row))
    r = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    print("--- pip check")
    print((r.stdout or r.stderr).strip()[:2000] or "(no output)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

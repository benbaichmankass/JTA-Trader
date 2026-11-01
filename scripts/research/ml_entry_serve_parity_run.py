#!/usr/bin/env python3
"""Runner entry for RQ-20261101-c692-07: install the PINNED lightgbm the live trader runs, then run the serve-parity check.

The research runner image installs numpy/pandas/pyyaml/requests only; ``src.units.strategies.ml_entry.load_model`` imports lightgbm,
so the bare command failed in 0.6 s with ModuleNotFoundError (run 41306541056, reproduced locally in a clean venv). The runner only
executes ``python3 scripts/research/<name>.py``, so the install lives here. Pin = the live pin (4.6.0), not the sandbox's 4.7.0.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PIN = "lightgbm==4.6.0"


def main(argv: list[str]) -> int:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", PIN], check=True)
    import lightgbm  # noqa: PLC0415

    print(f"lightgbm {lightgbm.__version__} (pin {PIN})", flush=True)
    here = Path(__file__).resolve().parent
    return subprocess.call([sys.executable, str(here / "ml_entry_serve_parity.py"), *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

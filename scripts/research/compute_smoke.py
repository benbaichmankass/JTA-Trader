#!/usr/bin/env python3
# wiring: research/queue/RQ-20261013-0b07-01.yaml, RQ-20261013-0b07-02.yaml (RESEARCH-ROUTER smoke units, via the dispatcher's compute classes)
"""Plumbing smoke for the research router -- measures NOTHING about markets.

``--mode gpu``  : on a GPU backend (Kaggle), time a short fp16 matmul and record the device. PASS needs a CUDA
                  device and a positive TFLOPS figure; no CUDA is reported as FAIL (the unit asked for a GPU and
                  was not given one -- the route is wrong, not the device slow).
``--mode cpu``  : on a runner, time a short fp32 numpy matmul. PASS needs a positive GFLOPS figure.

Writes ``<out>/verdict.json`` in the shape scripts/research/script_run.py derives an E5 record from. Public data
only (none is read); no secret; no repo state is touched.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path


def _gpu() -> dict:
    try:
        import torch
    except ImportError:
        return {"cuda": False, "why": "torch not importable"}
    if not torch.cuda.is_available():
        return {"cuda": False, "why": "torch.cuda.is_available() is False", "torch": torch.__version__}
    n = 4096
    a = torch.randn(n, n, device="cuda", dtype=torch.float16)
    b = torch.randn(n, n, device="cuda", dtype=torch.float16)
    torch.cuda.synchronize()
    t0, it = time.time(), 0
    while time.time() - t0 < 10:
        for _ in range(10):
            a @ b
        it += 10
        torch.cuda.synchronize()
    dur = time.time() - t0
    return {"cuda": True, "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__,
            "n_gpus": torch.cuda.device_count(), "fp16_tflops": round(2 * n ** 3 * it / dur / 1e12, 2)}


def _cpu() -> dict:
    import numpy as np
    n = 1024
    rng = np.random.default_rng(0)
    a, b = rng.standard_normal((n, n), dtype=np.float32), rng.standard_normal((n, n), dtype=np.float32)
    t0, it = time.time(), 0
    while time.time() - t0 < 5:
        a @ b
        it += 1
    dur = time.time() - t0
    return {"cpu": platform.processor() or platform.machine(), "numpy": np.__version__,
            "fp32_gflops": round(2 * n ** 3 * it / dur / 1e9, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("gpu", "cpu"), required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    meas = _gpu() if a.mode == "gpu" else _cpu()
    ok = bool(meas.get("cuda") and meas.get("fp16_tflops", 0) > 0) if a.mode == "gpu" else meas["fp32_gflops"] > 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    verdict = {"verdict": "pass" if ok else "fail", "read_state": "measured",
               "population": f"router smoke, mode={a.mode}: one short matmul benchmark on whichever backend the dispatcher chose",
               "n": 1, "measurement": meas,
               "note": "plumbing only: proves the routed backend ran the unit and the result landed; says nothing about any strategy or model"}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

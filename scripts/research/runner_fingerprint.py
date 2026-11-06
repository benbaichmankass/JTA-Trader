#!/usr/bin/env python3
"""Which machine and library build a research run executed on (row ML-FS-RECIPE, 2026-11-06).

WHY. MEASURED 2026-11-06 (timeframe units b620..b626, one data pin, identical fold sizes): the in-unit 1h baseline took exactly TWO
outcomes across five runner runs, each reproduced exactly. Class A = round 1's n 71,950 / 71,886 / 72,063 at +0.0089486 (b620, b626);
class B = n 71,917 / 71,882 / 72,071 at +0.007953 (b625, b622, b624). The fit is deterministic but depends on where it ran; the run
manifests recorded nothing about the runner, so the cause could not be checked. A hardware/CPU-class dependence of the LightGBM fit is
the hypothesis, UNVERIFIED. This records the facts so the next run can test it, and so an exact-reproduction test can be compared
within one class.

WHAT. ``fingerprint()`` returns a JSON-able dict: CPU model and the instruction-set flags that change numeric kernels, core counts, OS
image, Python and the numeric libraries' versions, and ``class_id``, a short hash of the fields that can change a result. It never raises
(a field it cannot read is ``None`` and listed in ``unread``, never ``0`` or a guess), reads no secret (only the named environment keys)
and spends no network.

    python3 scripts/research/runner_fingerprint.py            # print this machine's fingerprint
    python3 scripts/research/runner_fingerprint.py --self-test
"""
# wiring: scripts/research/script_run.py (run-manifest.json "runner") and scripts/research/ml_entry_timeframe.py (result "runner")
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Environment keys that identify the hosted-runner image. Whitelisted: nothing else from the environment is ever read.
ENV_KEYS = ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT")
#: Instruction-set flags that select different numeric kernels (SIMD width / fused multiply-add) in BLAS, OpenMP and LightGBM builds.
SIMD_FLAGS = ("sse4_2", "avx", "avx2", "fma", "avx512f", "avx512bw", "avx512vl", "avx512_vnni", "amx_tile", "neon", "asimd", "sve")
LIBS = ("lightgbm", "numpy", "pandas", "scipy", "scikit-learn")


def _read(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_cpuinfo(text: Optional[str]) -> Dict[str, Any]:
    """Model name and the SIMD flags of the FIRST logical CPU in /proc/cpuinfo text (x86 'model name'/'flags'; arm 'Features')."""
    out: Dict[str, Any] = {"model": None, "simd": None, "logical_cpus_listed": None}
    if not text:
        return out
    model = flags = None
    n = 0
    for line in text.splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "processor":
            n += 1
        elif key in ("model name", "hardware", "cpu model") and model is None and val:
            model = val
        elif key in ("flags", "features") and flags is None and val:
            flags = set(val.split())
    out["model"] = model
    out["logical_cpus_listed"] = n or None
    if flags is not None:
        out["simd"] = sorted(f for f in SIMD_FLAGS if f in flags)
    return out


def _os_release(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _lib_versions() -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for name in LIBS:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _blas() -> Optional[str]:
    """The BLAS/LAPACK numpy was built against, when numpy can say cheaply; None otherwise (never a guess)."""
    try:
        import numpy as np
        cfg = np.show_config(mode="dicts")  # type: ignore[call-arg]
        deps = cfg.get("Build Dependencies", {})
        parts = [f"{k}={deps[k].get('name')} {deps[k].get('version')}" for k in ("blas", "lapack") if isinstance(deps.get(k), dict)]
        return "; ".join(parts) or None
    except Exception:  # noqa: BLE001  # allow-silent: a missing or older numpy says nothing; the field stays None and is listed in `unread`
        return None


def fingerprint(*, cpuinfo_text: Optional[str] = None, os_release_text: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The runner fingerprint. The three arguments exist so a test can inject what the machine would have said."""
    try:
        cpu = parse_cpuinfo(cpuinfo_text if cpuinfo_text is not None else _read("/proc/cpuinfo"))
        environ = os.environ if env is None else env
        try:
            affinity: Optional[int] = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            affinity = None
        fp: Dict[str, Any] = {
            "cpu_model": cpu["model"],
            "cpu_simd": cpu["simd"],
            "cores_logical": os.cpu_count(),
            "cores_usable": affinity,
            "machine": platform.machine() or None,
            "os": _os_release(os_release_text if os_release_text is not None else _read("/etc/os-release")),
            "kernel": platform.release() or None,
            "image": {k: environ.get(k) for k in ENV_KEYS},
            "python": platform.python_version(),
            "libs": _lib_versions(),
            "blas": _blas(),
        }
        unread: List[str] = [k for k in ("cpu_model", "cpu_simd", "cores_logical", "cores_usable", "machine", "os", "kernel", "blas") if fp[k] is None]
        fp["unread"] = unread
        # class_id: only fields that can change a numeric result or the kernel it runs. The kernel version and the image
        # build number are left out on purpose so one hardware class does not split into many ids; both stay in the record.
        basis = {"cpu_model": fp["cpu_model"], "cpu_simd": fp["cpu_simd"], "cores_usable": fp["cores_usable"], "machine": fp["machine"],
                 "libs": fp["libs"], "blas": fp["blas"], "python": ".".join(fp["python"].split(".")[:2])}
        fp["class_id"] = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:12]
        fp["read_state"] = "read" if not unread else "partial"
        return fp
    except Exception as exc:  # noqa: BLE001  # allow-silent: recording the runner must never fail a research run; the failure is recorded instead
        return {"read_state": "could_not_look", "error": f"{type(exc).__name__}: {exc}", "class_id": None}


def _self_test() -> None:
    x86 = ("processor\t: 0\nmodel name\t: AMD EPYC 7763 64-Core Processor\nflags\t\t: fpu sse4_2 avx avx2 fma\n\n"
           "processor\t: 1\nmodel name\t: AMD EPYC 7763 64-Core Processor\nflags\t\t: fpu sse4_2 avx avx2 fma\n")
    intel = x86.replace("AMD EPYC 7763 64-Core Processor", "Intel(R) Xeon(R) Platinum 8272CL").replace("avx2 fma", "avx2 fma avx512f avx512bw")
    a = fingerprint(cpuinfo_text=x86, os_release_text='PRETTY_NAME="Ubuntu 24.04 LTS"\n', env={"ImageOS": "ubuntu24", "ImageVersion": "20261101.1"})
    b = fingerprint(cpuinfo_text=x86, os_release_text='PRETTY_NAME="Ubuntu 24.04 LTS"\n', env={"ImageOS": "ubuntu24", "ImageVersion": "20261101.1"})
    c = fingerprint(cpuinfo_text=intel, os_release_text='PRETTY_NAME="Ubuntu 24.04 LTS"\n', env={})
    assert a["class_id"] == b["class_id"], "the same machine must give the same class id"
    assert a["class_id"] != c["class_id"], "a different CPU model/flag set must give a different class id"
    assert a["cpu_model"].startswith("AMD EPYC") and a["cpu_simd"] == ["avx", "avx2", "fma", "sse4_2"], a
    assert a["image"]["ImageVersion"] == "20261101.1" and c["image"]["ImageVersion"] is None
    d = fingerprint(cpuinfo_text="", os_release_text="", env={})
    assert d["cpu_model"] is None and "cpu_model" in d["unread"], "an unreadable field is None and listed, never 0"
    assert d["read_state"] == "partial"
    secret = fingerprint(env={"GITHUB_TOKEN": "s3cr3t", "ImageOS": "ubuntu24"})
    assert "s3cr3t" not in json.dumps(secret), "only the whitelisted keys are ever read"
    print("runner_fingerprint self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
    else:
        print(json.dumps(fingerprint(), indent=2))

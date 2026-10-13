"""Kaggle GPU pilot kernel (COMPUTE-KAGGLE-GPU). Public data only: prints the GPU
and times a fp32/fp16 matmul benchmark for ~60 s. No repo data, no secrets."""
import json
import subprocess
import time

import torch

print(subprocess.run(["nvidia-smi"], capture_output=True, text=True, check=False).stdout)

res = {"torch": torch.__version__, "cuda": torch.cuda.is_available()}
if res["cuda"]:
    res["gpu"] = torch.cuda.get_device_name(0)
    n = 4096
    for dt in (torch.float32, torch.float16):
        a = torch.randn(n, n, device="cuda", dtype=dt)
        b = torch.randn(n, n, device="cuda", dtype=dt)
        torch.cuda.synchronize()
        t0, it = time.time(), 0
        while time.time() - t0 < 30:
            for _ in range(10):
                a @ b
            it += 10
            torch.cuda.synchronize()
        dur = time.time() - t0
        res[str(dt)] = {"iters": it, "sec": round(dur, 2),
                        "tflops": round(2 * n ** 3 * it / dur / 1e12, 2)}
print("RESULT " + json.dumps(res))
with open("result.json", "w") as f:
    json.dump(res, f)

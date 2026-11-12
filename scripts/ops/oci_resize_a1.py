#!/usr/bin/env python3
"""Resize ONE of the two non-trader A1.Flex VMs inside the Always-Free pool (Tier 2).

Targets are pinned by display name: ict-trainer-vm, ict-ib-gateway. The live
trader (ict-bot-arm) is refused by name. OCPU count may not change (memory only).
Budget guard: total A1 OCPU <= 4 and memory <= 24 GB AFTER the change, summed over
every non-terminated A1 instance, so shrink one VM before growing the other.
Stop -> update shape -> start; on a failed update the VM is restarted at the old shape.
Env: OCI_CLI_*, OCI_COMPARTMENT_OCID, TARGET_NAME, TARGET_OCPUS, TARGET_MEMORY_GBS,
     MODE (plan|execute, default plan), CONFIRM (must be 'yes' for execute).
Revert = run again with the old memory.
"""
from __future__ import annotations

import json
import os
import sys
import time

ALLOWED = {"ict-trainer-vm", "ict-ib-gateway"}
MAX_OCPU, MAX_MEM = 4.0, 24.0


def emit(event: str, **f) -> None:
    print(json.dumps({"event": event, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **f}), flush=True)


def check_budget(rows: list[dict], name: str, ocpus: float, mem: float) -> tuple[bool, str, float, float]:
    """rows: dicts display_name/ocpus/memory_gb for every live A1 instance."""
    if name not in ALLOWED:
        return False, f"{name!r} is not a permitted target (allowed: {sorted(ALLOWED)})", 0, 0
    cur = [r for r in rows if r["display_name"] == name]
    if len(cur) != 1:
        return False, f"expected exactly one instance named {name!r}, found {len(cur)}", 0, 0
    if float(cur[0]["ocpus"]) != ocpus:
        return False, f"OCPU change refused (current {cur[0]['ocpus']}, target {ocpus}); memory only", 0, 0
    if mem < 1:
        return False, "memory must be >= 1 GB", 0, 0
    tot_o = sum(float(r["ocpus"]) for r in rows if r["display_name"] != name) + ocpus
    tot_m = sum(float(r["memory_gb"]) for r in rows if r["display_name"] != name) + mem
    if tot_o > MAX_OCPU or tot_m > MAX_MEM:
        return False, f"post-change total {tot_o} OCPU / {tot_m} GB exceeds {MAX_OCPU} / {MAX_MEM}", tot_o, tot_m
    return True, "ok", tot_o, tot_m


def main() -> int:
    import oci

    name = os.environ.get("TARGET_NAME", "").strip()
    try:
        t_o, t_m = float(os.environ["TARGET_OCPUS"]), float(os.environ["TARGET_MEMORY_GBS"])
    except (KeyError, ValueError) as e:
        emit("error", phase="input", message=str(e))
        return 2
    mode = os.environ.get("MODE", "plan").strip().lower()
    cfg = {"user": os.environ["OCI_CLI_USER"], "key_content": os.environ["OCI_CLI_KEY_CONTENT"],
           "fingerprint": os.environ["OCI_CLI_FINGERPRINT"], "tenancy": os.environ["OCI_CLI_TENANCY"],
           "region": os.environ["OCI_CLI_REGION"]}
    compute = oci.core.ComputeClient(cfg)
    insts = [i for i in oci.pagination.list_call_get_all_results(
        compute.list_instances, compartment_id=os.environ["OCI_COMPARTMENT_OCID"]).data
        if i.lifecycle_state not in ("TERMINATED", "TERMINATING") and "A1" in (i.shape or "")]
    rows = [{"display_name": i.display_name, "ocpus": i.shape_config.ocpus,
             "memory_gb": i.shape_config.memory_in_gbs, "state": i.lifecycle_state, "ocid": i.id} for i in insts]
    emit("inventory", instances=[{k: v for k, v in r.items() if k != "ocid"} for r in rows])
    ok, why, tot_o, tot_m = check_budget(rows, name, t_o, t_m)
    emit("budget", ok=ok, reason=why, post_total_ocpus=tot_o, post_total_memory_gb=tot_m)
    if not ok:
        emit("result", status="refused")
        return 3
    cur = next(r for r in rows if r["display_name"] == name)
    if cur["memory_gb"] == t_m:
        emit("result", status="noop", memory_gb=t_m)
        return 0
    if mode != "execute":
        emit("result", status="plan", name=name, before_gb=cur["memory_gb"], target_gb=t_m)
        return 0
    if os.environ.get("CONFIRM", "") != "yes":
        emit("result", status="refused", reason="CONFIRM must be 'yes'")
        return 3
    iid = cur["ocid"]

    def wait(st: str) -> None:
        oci.wait_until(compute, compute.get_instance(iid), "lifecycle_state", st,
                       max_wait_seconds=420, max_interval_seconds=10)

    try:
        if cur["state"] != "STOPPED":
            compute.instance_action(iid, "SOFTSTOP")
            wait("STOPPED")
        emit("stopped")
    except Exception as e:  # noqa: BLE001
        emit("error", phase="stop", message=f"{type(e).__name__}: {e}")
        try:
            compute.instance_action(iid, "STOP")
            wait("STOPPED")
            emit("stopped", hard=True)
        except Exception as e2:  # noqa: BLE001
            emit("error", phase="stop_hard", message=str(e2))
            emit("result", status="failed_stop")
            return 4
    try:
        compute.update_instance(iid, oci.core.models.UpdateInstanceDetails(
            shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(ocpus=t_o, memory_in_gbs=t_m)))
        emit("updated", memory_gb=t_m)
    except Exception as e:  # noqa: BLE001
        emit("error", phase="update", message=f"{type(e).__name__}: {e}")
        try:
            compute.instance_action(iid, "START")
            wait("RUNNING")
            emit("recovered_old_shape")
        except Exception as e2:  # noqa: BLE001
            emit("error", phase="recover", message=str(e2))
        emit("result", status="failed_update")
        return 5
    try:
        compute.instance_action(iid, "START")
        wait("RUNNING")
        emit("started")
    except Exception as e:  # noqa: BLE001
        emit("error", phase="start", message=f"{type(e).__name__}: {e}")
        emit("result", status="failed_start")
        return 6
    fin = compute.get_instance(iid).data
    emit("result", status="ok", name=name, ocpus=fin.shape_config.ocpus,
         memory_gb=fin.shape_config.memory_in_gbs, state=fin.lifecycle_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

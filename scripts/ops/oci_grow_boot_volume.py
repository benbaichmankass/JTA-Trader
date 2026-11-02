#!/usr/bin/env python3
"""Grow the LIVE VM's boot volume (ict-bot-arm) inside the Always-Free 200 GB cap.

Operator decision (popup, 2026-11-02 ~14:00Z, verbatim): "Free +6 GB only".
47 GB -> 53 GB, never more: anything past 53 GB is billed. Tier 2, approved.
Driven by `.github/workflows/oci-grow-boot-volume.yml`, which does the in-VM
partition/filesystem grow afterwards (scripts/ops/vm_grow_root_fs.sh).

The target is the instance whose IMDS document the workflow fetched over SSH
from the live host. Its boot volume OCID is resolved AT RUNTIME from that
instance (the repo is public: no OCID, IP or secret is committed). The IMDS
displayName must be EXPECTED_DISPLAY_NAME, so a mis-set host (e.g. the trainer)
is refused before any OCI call.

Modes:
  plan     (default) read-only. Prints current size, target, the tenancy's
           free-storage headroom (enumerated volumes AND the Limits API) and the
           backup count. Refuses (exit 2) when the target is past MAX_TARGET_GB,
           when the headroom is below the delta, or when a backup would exceed
           the free backup count.
  execute  plan checks again, then in order: FULL boot-volume backup (wait for
           AVAILABLE) -> update_boot_volume(size_in_gbs=target) (wait for
           AVAILABLE at >= target). A volume already at/above the target is a
           no-op (exit 0, nothing created) so a re-run after a half-finished
           attempt is safe.

Exit codes: 0 ok / plan printed / no-op; 2 refused before any mutation;
4 backup did not reach AVAILABLE (volume untouched); 6 resize issued but the
volume did not reach AVAILABLE at the target in time. (5 is reserved for the
VM-side script: sudo missing.)

Env: OCI_CLI_USER, OCI_CLI_FINGERPRINT, OCI_CLI_TENANCY, OCI_CLI_KEY_CONTENT,
OCI_CLI_REGION.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

EXPECTED_DISPLAY_NAME = "ict-bot-arm"
MAX_TARGET_GB = 53          # operator ceiling; anything more is billed
FREE_CEILING_GB = 200       # Always Free block+boot total
FREE_BACKUP_COUNT = 5       # Always Free backup count
LIVE_STATES = {"PROVISIONING", "RESTORING", "AVAILABLE", "FAULTY"}
LIVE_BACKUP_STATES = {"REQUEST_RECEIVED", "CREATING", "AVAILABLE"}


class Refused(Exception):
    """A check failed; `code` is the exit code and no further mutation happens."""

    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


def check_identity(imds: dict) -> None:
    name = imds.get("displayName")
    if name != EXPECTED_DISPLAY_NAME:
        raise Refused(f"IMDS displayName is {name!r}, expected {EXPECTED_DISPLAY_NAME!r}")
    if not imds.get("id") or not imds.get("availabilityDomain") or not imds.get("compartmentId"):
        raise Refused("IMDS document lacks id / availabilityDomain / compartmentId")


def _size(o) -> int:
    if o.size_in_gbs is None:
        raise Refused(f"{getattr(o, 'display_name', '?')} reports size_in_gbs=None; "
                      "the total cannot be trusted")
    return int(o.size_in_gbs)


def measure(api, imds: dict) -> dict:
    bv = api.boot_volume_for_instance(imds)
    comps = api.compartments()
    vols = [(v.id, _size(v)) for v in api.list_boot_volumes(comps) if v.lifecycle_state in LIVE_STATES]
    vols += [(v.id, _size(v)) for v in api.list_block_volumes(comps) if v.lifecycle_state in LIVE_STATES]
    if bv.id not in {i for i, _ in vols}:
        # Denominator check: the enumeration must see the volume we KNOW exists.
        raise Refused("the live boot volume is not in the enumerated set; the total cannot be trusted")
    backups = [b for b in api.list_backups(comps) if b.lifecycle_state in LIVE_BACKUP_STATES]
    return {"boot_volume_id": bv.id, "boot_volume_name": bv.display_name,
            "current_gb": _size(bv), "state": bv.lifecycle_state,
            "total_gb": sum(s for _, s in vols), "volume_count": len(vols),
            "compartments_read": len(comps), "backup_count": len(backups),
            "limits_available_gb": api.limits_free_available()}


def check_plan(m: dict, target: int) -> dict:
    """Pure decision. Raises Refused (code 2); returns the verdict dict."""
    if target > MAX_TARGET_GB:
        raise Refused(f"target {target} GB is past the operator ceiling {MAX_TARGET_GB} GB "
                      "(anything more is billed)")
    cur = m["current_gb"]
    delta = max(0, target - cur)
    headroom = FREE_CEILING_GB - m["total_gb"]
    lim = m["limits_available_gb"]          # None = could not look
    v = {"current_gb": cur, "target_gb": target, "delta_gb": delta,
         "enumerated_headroom_gb": headroom, "limits_api_headroom_gb": lim,
         "backup_count": m["backup_count"], "noop": delta == 0}
    if delta == 0:
        return v
    if m["state"] != "AVAILABLE":
        raise Refused(f"boot volume is {m['state']}, not AVAILABLE")
    if headroom < delta:
        raise Refused(f"free headroom {headroom} GB (enumerated {m['total_gb']}/{FREE_CEILING_GB}) "
                      f"is below the {delta} GB delta")
    if lim is not None and lim < delta:
        raise Refused(f"Limits API reports {lim} GB available, below the {delta} GB delta")
    if m["backup_count"] >= FREE_BACKUP_COUNT:
        raise Refused(f"{m['backup_count']} live backups already (Always Free allows "
                      f"{FREE_BACKUP_COUNT}); the safety backup would be billed")
    return v


def backup_and_wait(api, bv_id: str, name: str, timeout_s: int, poll_s: int = 30,
                    sleep=time.sleep, now=time.monotonic):
    try:
        b = api.create_backup(bv_id, name)
    except Exception as exc:  # noqa: BLE001
        raise Refused(f"create_boot_volume_backup failed: {exc}", 4) from exc
    print(f"backup requested: {b.id} ({b.lifecycle_state})")
    deadline = now() + timeout_s
    while True:
        b = api.get_backup(b.id)
        print(f"  backup poll: {b.lifecycle_state}")
        if b.lifecycle_state == "AVAILABLE":
            return b
        if b.lifecycle_state in ("FAULTY", "TERMINATING", "TERMINATED"):
            raise Refused(f"backup {b.id} ended {b.lifecycle_state}; volume NOT resized", 4)
        if now() >= deadline:
            raise Refused(f"backup {b.id} not AVAILABLE within {timeout_s}s "
                          f"(last {b.lifecycle_state}); volume NOT resized", 4)
        sleep(poll_s)


def run(api, imds: dict, *, mode: str, target: int, backup_timeout_s: int,
        resize_timeout_s: int, backup_name: str, sleep=time.sleep, now=time.monotonic) -> int:
    check_identity(imds)
    m = measure(api, imds)
    v = check_plan(m, target)
    print(f"boot volume: {m['boot_volume_name']} {v['current_gb']} GB {m['state']}")
    print(f"target: {v['target_gb']} GB (delta {v['delta_gb']} GB, ceiling {MAX_TARGET_GB} GB)")
    print(f"tenancy block+boot total: {m['total_gb']} GB of {FREE_CEILING_GB} GB "
          f"({m['volume_count']} volumes, {m['compartments_read']} compartments)")
    print(f"free headroom: enumerated {v['enumerated_headroom_gb']} GB; Limits API "
          f"{'COULD NOT LOOK' if v['limits_api_headroom_gb'] is None else str(v['limits_api_headroom_gb']) + ' GB'}")
    print(f"live backups: {m['backup_count']} (Always Free allows {FREE_BACKUP_COUNT})")
    if v["noop"]:
        print(f"no-op: boot volume already {v['current_gb']} GB >= {target} GB")
        return 0
    if mode == "plan":
        print("PLAN ONLY — nothing changed. Execute needs mode: execute and confirm: yes.")
        return 0
    b = backup_and_wait(api, m["boot_volume_id"], backup_name, backup_timeout_s, sleep=sleep, now=now)
    print(f"BACKUP AVAILABLE: {b.id}")
    print(f"resizing boot volume {v['current_gb']} -> {target} GB (online)")
    api.update_size(m["boot_volume_id"], target)
    deadline = now() + resize_timeout_s
    while now() < deadline:
        cur = api.get_boot_volume(m["boot_volume_id"])
        print(f"  resize poll: {cur.lifecycle_state} {cur.size_in_gbs} GB")
        if cur.lifecycle_state == "AVAILABLE" and int(cur.size_in_gbs) >= target:
            print(f"POST-STATE: boot volume {int(cur.size_in_gbs)} GB AVAILABLE; backup {b.id} kept")
            return 0
        sleep(15)
    print(f"ERROR: boot volume not AVAILABLE at >= {target} GB within {resize_timeout_s}s "
          f"(backup {b.id} kept)", file=sys.stderr)
    return 6


class OciApi:  # pragma: no cover — thin SDK adapter, exercised only against OCI
    def __init__(self, cfg: dict):
        import oci  # noqa: PLC0415

        self.oci, self.cfg = oci, cfg
        self.bs = oci.core.BlockstorageClient(cfg)
        self.compute = oci.core.ComputeClient(cfg)
        self.identity = oci.identity.IdentityClient(cfg)
        self.limits = oci.limits.LimitsClient(cfg)
        self._ads: list[str] | None = None

    def _all(self, fn, *a, **kw):
        return self.oci.pagination.list_call_get_all_results(fn, *a, **kw).data

    def compartments(self) -> list[str]:
        t = self.cfg["tenancy"]
        try:
            subs = self._all(self.identity.list_compartments, t, compartment_id_in_subtree=True,
                             access_level="ACCESSIBLE", lifecycle_state="ACTIVE")
        except Exception as exc:  # noqa: BLE001 — a root-only total UNDERCOUNTS
            raise Refused(f"could not list sub-compartments ({exc}); refusing on a possibly "
                          "undercounted total") from exc
        return [t] + [c.id for c in subs]

    def ads(self) -> list[str]:
        if self._ads is None:
            self._ads = [a.name for a in self.identity.list_availability_domains(self.cfg["tenancy"]).data]
        return self._ads

    def boot_volume_for_instance(self, imds: dict):
        atts = [a for a in self._all(self.compute.list_boot_volume_attachments,
                                     availability_domain=imds["availabilityDomain"],
                                     compartment_id=imds["compartmentId"], instance_id=imds["id"])
                if a.lifecycle_state == "ATTACHED"]
        if len(atts) != 1:
            raise Refused(f"expected exactly 1 ATTACHED boot volume on the instance, found {len(atts)}")
        return self.bs.get_boot_volume(atts[0].boot_volume_id).data

    def list_boot_volumes(self, comps):
        return [bv for c in comps for ad in self.ads()
                for bv in self._all(self.bs.list_boot_volumes, availability_domain=ad, compartment_id=c)]

    def list_block_volumes(self, comps):
        return [v for c in comps for v in self._all(self.bs.list_volumes, compartment_id=c)]

    def list_backups(self, comps):
        return [b for c in comps
                for b in (self._all(self.bs.list_boot_volume_backups, compartment_id=c)
                          + self._all(self.bs.list_volume_backups, compartment_id=c))]

    def limits_free_available(self):
        """Smallest `available` among block-storage limits whose name says 'free'
        and 'storage'/'gb'; None when none can be read (never 0)."""
        t = self.cfg["tenancy"]
        try:
            defs = self._all(self.limits.list_limit_definitions, compartment_id=t, service_name="block-storage")
            avail = []
            for d in defs:
                n = d.name.lower()
                if "free" in n and ("gb" in n or "storage" in n) \
                        and getattr(d, "is_resource_availability_supported", False):
                    kw = {}
                    if str(getattr(d, "scope_type", "")).upper() == "AD":
                        kw["availability_domain"] = self.ads()[0]
                    a = self.limits.get_resource_availability("block-storage", d.name, t, **kw).data
                    if a.available is not None:
                        avail.append(int(a.available))
            return min(avail) if avail else None
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: Limits API unreadable ({type(exc).__name__}: {str(exc)[:160]})", file=sys.stderr)
            return None

    def create_backup(self, bv_id, name):
        return self.bs.create_boot_volume_backup(self.oci.core.models.CreateBootVolumeBackupDetails(
            boot_volume_id=bv_id, display_name=name, type="FULL")).data

    def get_backup(self, bid):
        return self.bs.get_boot_volume_backup(bid).data

    def get_boot_volume(self, bv_id):
        return self.bs.get_boot_volume(bv_id).data

    def update_size(self, bv_id, gb):
        self.bs.update_boot_volume(bv_id, self.oci.core.models.UpdateBootVolumeDetails(size_in_gbs=gb))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=["plan", "execute"], default="plan")
    ap.add_argument("--target-gb", type=int, default=MAX_TARGET_GB)
    ap.add_argument("--imds", required=True, help="live VM IMDS /opc/v2/instance/ JSON file")
    ap.add_argument("--backup-timeout-s", type=int, default=5400)
    ap.add_argument("--resize-timeout-s", type=int, default=900)
    a = ap.parse_args(argv)
    missing = [k for k in ("OCI_CLI_USER", "OCI_CLI_FINGERPRINT", "OCI_CLI_TENANCY",
                           "OCI_CLI_KEY_CONTENT") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing env: {', '.join(missing)}", file=sys.stderr)
        return 2
    cfg = {"user": os.environ["OCI_CLI_USER"], "fingerprint": os.environ["OCI_CLI_FINGERPRINT"],
           "tenancy": os.environ["OCI_CLI_TENANCY"], "key_content": os.environ["OCI_CLI_KEY_CONTENT"],
           "region": os.environ.get("OCI_CLI_REGION") or "eu-paris-1"}
    with open(a.imds, encoding="utf-8") as fh:
        imds = json.load(fh)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    try:
        return run(OciApi(cfg), imds, mode=a.mode, target=a.target_gb,
                   backup_timeout_s=a.backup_timeout_s, resize_timeout_s=a.resize_timeout_s,
                   backup_name=f"ict-bot-arm-boot-pre-grow-{stamp}")
    except Refused as r:
        print(f"REFUSED: {r}", file=sys.stderr)
        return r.code


if __name__ == "__main__":
    sys.exit(main())

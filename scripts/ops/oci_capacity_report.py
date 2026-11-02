"""READ-ONLY OCI storage + compute capacity report (lane OCI-FREE-CAPACITY).

Measures, from the OCI API (never a remembered number): every boot volume and
block volume (size, state, attached instance), the tenancy's own Limits API
values + availability for block-storage and A1 compute, and object-storage
usage. Each section carries its own read_state; anything unreadable is
``could_not_look`` with the error, never 0. Only list_*/get_* calls are made.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

FREE_NOTE = ("The Always Free ceiling (200 GB total block+boot, 4 OCPU/24 GB A1, 20 GB object) "
             "is a BILLING rule, not a Limits-API value; this report prints what the API says "
             "and the totals so the caller can compare.")


def _cfg() -> dict[str, str]:
    need = ("OCI_CLI_USER", "OCI_CLI_KEY_CONTENT", "OCI_CLI_FINGERPRINT", "OCI_CLI_TENANCY", "OCI_CLI_REGION")
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        raise SystemExit(f"missing OCI env vars: {', '.join(miss)}")
    return {"user": os.environ["OCI_CLI_USER"], "key_content": os.environ["OCI_CLI_KEY_CONTENT"],
            "fingerprint": os.environ["OCI_CLI_FINGERPRINT"], "tenancy": os.environ["OCI_CLI_TENANCY"],
            "region": os.environ["OCI_CLI_REGION"]}


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:240]}"


def main() -> int:
    import oci
    from oci.pagination import list_call_get_all_results as lall

    cfg = _cfg()
    tenancy = cfg["tenancy"]
    comp = os.environ.get("OCI_COMPARTMENT_OCID") or tenancy
    ident = oci.identity.IdentityClient(cfg)
    compute = oci.core.ComputeClient(cfg)
    bs = oci.core.BlockstorageClient(cfg)
    lim = oci.limits.LimitsClient(cfg)
    rep: dict[str, Any] = {"compartment_is_tenancy": comp == tenancy, "note": FREE_NOTE}

    # availability domains
    ads: list[str] = []
    try:
        ads = [a.name for a in ident.list_availability_domains(compartment_id=tenancy).data]
        rep["availability_domains"] = ads
    except Exception as exc:  # noqa: BLE001
        rep["availability_domains"] = {"read_state": "could_not_look", "error": _err(exc)}

    # instances
    names: dict[str, str] = {}
    try:
        insts = lall(compute.list_instances, compartment_id=comp).data
        rep["instances"] = []
        for i in insts:
            if i.lifecycle_state in ("TERMINATED", "TERMINATING"):
                continue
            names[i.id] = i.display_name
            sc = i.shape_config
            rep["instances"].append({"name": i.display_name, "shape": i.shape, "state": i.lifecycle_state,
                                     "ocpus": getattr(sc, "ocpus", None), "memory_gb": getattr(sc, "memory_in_gbs", None)})
    except Exception as exc:  # noqa: BLE001
        rep["instances"] = {"read_state": "could_not_look", "error": _err(exc)}

    # boot volumes + attachments, per AD
    boots, battach = [], {}
    boot_err = {}
    for ad in ads:
        try:
            for b in lall(bs.list_boot_volumes, availability_domain=ad, compartment_id=comp).data:
                boots.append(b)
        except Exception as exc:  # noqa: BLE001
            boot_err[ad] = _err(exc)
        try:
            for a in lall(compute.list_boot_volume_attachments, availability_domain=ad, compartment_id=comp).data:
                if a.lifecycle_state != "DETACHED":
                    battach[a.boot_volume_id] = a.instance_id
        except Exception as exc:  # noqa: BLE001
            boot_err[ad + ":attach"] = _err(exc)
    rep["boot_volumes"] = {
        "read_state": "measured" if not boot_err else "partial", "errors": boot_err,
        "rows": [{"name": b.display_name, "size_gb": b.size_in_gbs, "state": b.lifecycle_state,
                  "vpus_per_gb": getattr(b, "vpus_per_gb", None),
                  "instance": names.get(battach.get(b.id), battach.get(b.id)), "ocid": b.id} for b in boots]}

    # block volumes + attachments
    try:
        vols = lall(bs.list_volumes, compartment_id=comp).data
        att = lall(compute.list_volume_attachments, compartment_id=comp).data
        vmap = {}
        for a in att:
            if a.lifecycle_state != "DETACHED":
                vmap.setdefault(a.volume_id, []).append(f"{names.get(a.instance_id, a.instance_id)}[{a.lifecycle_state}]")
        rep["block_volumes"] = {"read_state": "measured", "rows": [
            {"name": v.display_name, "size_gb": v.size_in_gbs, "state": v.lifecycle_state,
             "attached_to": vmap.get(v.id, []), "ocid": v.id} for v in vols]}
    except Exception as exc:  # noqa: BLE001
        rep["block_volumes"] = {"read_state": "could_not_look", "error": _err(exc)}

    # backups (they count against block-storage limits/billing, not free)
    try:
        bb = lall(bs.list_volume_backups, compartment_id=comp).data
        bbb = lall(bs.list_boot_volume_backups, compartment_id=comp).data
        rep["backups"] = {"read_state": "measured",
                          "volume_backups": [{"name": x.display_name, "state": x.lifecycle_state,
                                              "size_gb": x.size_in_gbs, "unique_gb": x.unique_size_in_gbs} for x in bb],
                          "boot_volume_backups": [{"name": x.display_name, "state": x.lifecycle_state,
                                                   "size_gb": x.size_in_gbs, "unique_gb": x.unique_size_in_gbs} for x in bbb]}
    except Exception as exc:  # noqa: BLE001
        rep["backups"] = {"read_state": "could_not_look", "error": _err(exc)}

    # totals
    try:
        tb = sum(r["size_gb"] or 0 for r in rep["boot_volumes"]["rows"])
        tv = sum(r["size_gb"] or 0 for r in rep["block_volumes"]["rows"])
        rep["totals_gb"] = {"boot": tb, "block": tv, "boot_plus_block": tb + tv}
    except Exception as exc:  # noqa: BLE001
        rep["totals_gb"] = {"read_state": "could_not_look", "error": _err(exc)}

    # tenancy Limits API: every block-storage + A1/compute-core limit and its availability
    limits: dict[str, Any] = {}
    for svc, pick in (("block-storage", None), ("compute", ("a1", "free"))):
        try:
            defs = lall(lim.list_limit_definitions, compartment_id=tenancy, service_name=svc).data
            for d in defs:
                if pick and not any(p in d.name for p in pick):
                    continue
                e: dict[str, Any] = {"read_state": "could_not_look"}
                try:
                    vals = lall(lim.list_limit_values, compartment_id=tenancy, service_name=svc, name=d.name).data
                    e["values"] = [{"scope": str(v.scope_type), "ad": v.availability_domain, "value": v.value} for v in vals]
                    e["read_state"] = "measured"
                    av = []
                    if getattr(d, "is_resource_availability_supported", False):
                        targets = ads if any(str(v.scope_type) == "AD" for v in vals) else [None]
                        for ad in targets:
                            try:
                                kw = {"availability_domain": ad} if ad else {}
                                a = lim.get_resource_availability(service_name=svc, limit_name=d.name,
                                                                           compartment_id=comp, **kw).data
                                av.append({"ad": ad, "used": a.used, "available": a.available,
                                           "fractional_used": getattr(a, "fractional_usage", None)})
                            except Exception as exc:  # noqa: BLE001
                                av.append({"ad": ad, "error": _err(exc)})
                    e["availability"] = av
                except Exception as exc:  # noqa: BLE001
                    e["error"] = _err(exc)
                limits[f"{svc}/{d.name}"] = e
        except Exception as exc:  # noqa: BLE001
            limits[f"{svc}/*"] = {"read_state": "could_not_look", "error": _err(exc)}
    rep["limits"] = limits

    # object storage
    try:
        os_c = oci.object_storage.ObjectStorageClient(cfg)
        ns = os_c.get_namespace().data
        rows = []
        for b in lall(os_c.list_buckets, namespace_name=ns, compartment_id=comp).data:
            d = os_c.get_bucket(ns, b.name, fields=["approximateSize", "approximateCount"]).data
            rows.append({"bucket": b.name, "approx_bytes": d.approximate_size, "approx_objects": d.approximate_count})
        rep["object_storage"] = {"read_state": "measured", "buckets": rows,
                                 "total_bytes": sum(r["approx_bytes"] or 0 for r in rows)}
    except Exception as exc:  # noqa: BLE001
        rep["object_storage"] = {"read_state": "could_not_look", "error": _err(exc)}

    print(json.dumps(rep, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

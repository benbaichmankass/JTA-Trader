#!/usr/bin/env python3
"""Remove the public OCI ingress rule for the web API port (SEC-8001-LOCKDOWN).

The inverse of ``scripts/ops/cloud_open_port.py``, narrowed on purpose.

Operator decisions page m3, 2026-11-12: "Lock it down: move those three clients
to HTTPS, then bind 8001 to localhost and drop its firewall rule".

Deletes ONLY ingress rules that are exactly:
    protocol TCP (6), source 0.0.0.0/0, destination port range 8001-8001
from (a) every security list on the live trader's primary-VNIC subnet and
(b) every network security group attached to that VNIC. A rule whose port
RANGE merely covers 8001 (e.g. 8000-8100) is reported and left alone: deleting
it would close other ports, and that is a human decision. 22/80/443 and every
other rule are never touched.

Modes:
  default (dry run)  lists what WOULD be removed and probes whether the key can
                     write, using a no-op update (each security list's own
                     freeform tags written back unchanged, guarded by its etag).
                     The probe changes nothing.
  --apply            removes the matching rules, then re-reads and prints the
                     before/after counts.

Identifiers come from the environment and the API at runtime, never the repo:
  OCI_CLI_USER / OCI_CLI_KEY_CONTENT / OCI_CLI_FINGERPRINT / OCI_CLI_TENANCY /
  OCI_CLI_REGION   API key (Actions secrets)
  OCI_COMPARTMENT_OCID  compartment to search (falls back to COMPARTMENT_ID, then
                        the tenancy OCID = root compartment, as oci_inventory.py does)
  LIVE_INSTANCE_NAME    instance display name (default ict-bot-arm)
Output never prints an OCID or an address: security lists and NSGs are named
by display name only (the output is posted to a public issue).

Exit codes: 0 ok (dry run or apply) · 2 usage/env · 3 refused (instance not
found or ambiguous) · 4 the key cannot write (dry run reports it; apply stops
before touching anything) · 1 an API call failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PORT = 8001
SOURCE = "0.0.0.0/0"
TCP = "6"


def emit(action: str, **kw: object) -> None:
    print(json.dumps({"action": action, **kw}, default=str), flush=True)


def _range(opts):
    pr = getattr(opts, "destination_port_range", None) if opts else None
    return (pr.min, pr.max) if pr else None


def classify(protocol: str, source: str, port_range) -> str:
    """'exact' -> delete, 'covers' -> report only, 'other' -> ignore."""
    if protocol != TCP or source != SOURCE or not port_range:
        return "other"
    lo, hi = port_range
    if lo == hi == PORT:
        return "exact"
    if lo <= PORT <= hi:
        return "covers"
    return "other"


def _self_test() -> int:
    assert classify("6", "0.0.0.0/0", (8001, 8001)) == "exact"
    assert classify("6", "0.0.0.0/0", (8000, 8100)) == "covers"
    assert classify("6", "10.0.0.0/24", (8001, 8001)) == "other"
    assert classify("17", "0.0.0.0/0", (8001, 8001)) == "other"
    assert classify("6", "0.0.0.0/0", (443, 443)) == "other"
    assert classify("6", "0.0.0.0/0", None) == "other"
    print("cloud_close_port self-test ok")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="remove the matching rules (default: dry run)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    # Same compartment resolution as scripts/ops/oci_inventory.py: an explicit
    # compartment wins; otherwise the tenancy (root compartment). Measured
    # 2026-11-12 (run 43211799160): the OCI_COMPARTMENT_OCID secret is empty.
    if not os.environ.get("OCI_COMPARTMENT_OCID"):
        os.environ["OCI_COMPARTMENT_OCID"] = (os.environ.get("COMPARTMENT_ID")
                                              or os.environ.get("OCI_CLI_TENANCY") or "")
    need = ("OCI_CLI_USER", "OCI_CLI_KEY_CONTENT", "OCI_CLI_FINGERPRINT", "OCI_CLI_TENANCY",
            "OCI_CLI_REGION", "OCI_COMPARTMENT_OCID")
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        emit("error", message="missing env", missing=missing)
        return 2

    import oci  # imported late so --self-test runs without the SDK

    config = {
        "user": os.environ["OCI_CLI_USER"],
        "key_content": os.environ["OCI_CLI_KEY_CONTENT"],
        "fingerprint": os.environ["OCI_CLI_FINGERPRINT"],
        "tenancy": os.environ["OCI_CLI_TENANCY"],
        "region": os.environ["OCI_CLI_REGION"],
    }
    oci.config.validate_config(config)
    compartment = os.environ["OCI_COMPARTMENT_OCID"]
    name = os.environ.get("LIVE_INSTANCE_NAME", "ict-bot-arm")
    compute = oci.core.ComputeClient(config)
    vnet = oci.core.VirtualNetworkClient(config)
    mode = "apply" if args.apply else "dry_run"

    try:
        insts = [i for i in oci.pagination.list_call_get_all_results(
                     compute.list_instances, compartment_id=compartment, display_name=name).data
                 if i.lifecycle_state not in ("TERMINATED", "TERMINATING")]
        if len(insts) != 1:
            emit("refused", reason=f"expected exactly 1 live instance named {name!r}, found {len(insts)}")
            return 3
        inst = insts[0]
        atts = [a for a in compute.list_vnic_attachments(compartment_id=compartment, instance_id=inst.id).data
                if a.lifecycle_state == "ATTACHED"]
        vnics = [vnet.get_vnic(a.vnic_id).data for a in atts]
        primary = next((v for v in vnics if v.is_primary), None)
        if primary is None:
            emit("refused", reason="no primary VNIC")
            return 3
        subnet = vnet.get_subnet(primary.subnet_id).data
        emit("context", mode=mode, instance=name, security_lists=len(subnet.security_list_ids or []),
             nsgs=len(primary.nsg_ids or []))

        # ---- security lists ------------------------------------------------
        plan = []  # (sl, keep_rules, removed_count)
        can_write = None
        for sl_id in subnet.security_list_ids or []:
            resp = vnet.get_security_list(sl_id)
            sl, etag = resp.data, resp.headers.get("etag")
            rules = sl.ingress_security_rules or []
            keep, removed = [], 0
            for r in rules:
                c = classify(r.protocol, r.source, _range(r.tcp_options))
                if c == "exact":
                    removed += 1
                    continue
                if c == "covers":
                    emit("left_alone", where="security_list", name=sl.display_name,
                         port_range=_range(r.tcp_options), reason="range covers 8001 but is wider; needs a human")
                keep.append(r)
            emit("security_list", name=sl.display_name, ingress_rules=len(rules), matching_8001=removed)
            plan.append((sl_id, sl, etag, keep, removed))
            if can_write is None:
                # Write probe: freeform tags written back unchanged, guarded by the
                # etag, so the stored state cannot change.
                try:
                    vnet.update_security_list(
                        sl_id, oci.core.models.UpdateSecurityListDetails(freeform_tags=sl.freeform_tags or {}),
                        if_match=etag)
                    can_write = True
                    # the no-op write bumps the etag; re-read it for the real update
                    plan[-1] = (sl_id, sl, vnet.get_security_list(sl_id).headers.get("etag"), keep, removed)
                except oci.exceptions.ServiceError as e:
                    if e.status in (401, 403, 404):
                        can_write = False
                    else:
                        raise
        # ---- NSGs ------------------------------------------------------------
        nsg_plan = []
        for nsg_id in primary.nsg_ids or []:
            nsg = vnet.get_network_security_group(nsg_id).data
            rules = oci.pagination.list_call_get_all_results(
                vnet.list_network_security_group_security_rules, network_security_group_id=nsg_id,
                direction="INGRESS").data
            ids = []
            for r in rules:
                c = classify(r.protocol, r.source, _range(r.tcp_options))
                if c == "exact":
                    ids.append(r.id)
                elif c == "covers":
                    emit("left_alone", where="nsg", name=nsg.display_name,
                         port_range=_range(r.tcp_options), reason="range covers 8001 but is wider; needs a human")
            emit("nsg", name=nsg.display_name, ingress_rules=len(rules), matching_8001=len(ids))
            nsg_plan.append((nsg_id, nsg, ids))

        total = sum(p[4] for p in plan) + sum(len(p[2]) for p in nsg_plan)
        emit("can_write", value=can_write if plan else "untested (no security list on the subnet)")
        if not args.apply:
            emit("done", mode=mode, would_remove=total, can_write=can_write)
            return 4 if can_write is False else 0
        if can_write is False:
            emit("refused", reason="the API key cannot write security lists; use the console fallback")
            return 4
        if total == 0:
            emit("done", mode=mode, removed=0, status="nothing to remove")
            return 0

        for sl_id, sl, etag, keep, removed in plan:
            if removed:
                vnet.update_security_list(
                    sl_id, oci.core.models.UpdateSecurityListDetails(ingress_security_rules=keep), if_match=etag)
                emit("removed", where="security_list", name=sl.display_name, count=removed)
        for nsg_id, nsg, ids in nsg_plan:
            if ids:
                vnet.remove_network_security_group_security_rules(
                    nsg_id, oci.core.models.RemoveNetworkSecurityGroupSecurityRulesDetails(security_rule_ids=ids))
                emit("removed", where="nsg", name=nsg.display_name, count=len(ids))

        # ---- after -------------------------------------------------------------
        left = 0
        for sl_id, sl, *_ in plan:
            rules = vnet.get_security_list(sl_id).data.ingress_security_rules or []
            m = sum(classify(r.protocol, r.source, _range(r.tcp_options)) == "exact" for r in rules)
            left += m
            emit("after", where="security_list", name=sl.display_name, ingress_rules=len(rules), matching_8001=m)
        for nsg_id, nsg, _ in nsg_plan:
            rules = oci.pagination.list_call_get_all_results(
                vnet.list_network_security_group_security_rules, network_security_group_id=nsg_id,
                direction="INGRESS").data
            m = sum(classify(r.protocol, r.source, _range(r.tcp_options)) == "exact" for r in rules)
            left += m
            emit("after", where="nsg", name=nsg.display_name, ingress_rules=len(rules), matching_8001=m)
        emit("done", mode=mode, removed=total, matching_8001_left=left)
        return 0 if left == 0 else 1
    except oci.exceptions.ServiceError as e:
        emit("error", status=e.status, code=e.code, message=str(e.message)[:200])
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

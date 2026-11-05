#!/usr/bin/env python3
"""Open TCP 80 + 443 to the trainer VM in OCI, for the console connector (row UI-CONSOLE-V1).

Operator decision 2026-11-05 ~09:55Z, verbatim popup option: "Open 443 + Google OAuth (Recommended)".
80 is needed for the ACME HTTP-01 challenge (Caddy's automatic certificate); 443 serves the
connector. Idempotent: an existing equivalent rule is left alone, nothing is ever removed.

  python3 scripts/ops/oci_console_ingress.py --ip <trainer public ip>            # plan only
  python3 scripts/ops/oci_console_ingress.py --ip <trainer public ip> --apply    # write

Reads OCI_CLI_{USER,KEY_CONTENT,FINGERPRINT,TENANCY,REGION} and OCI_COMPARTMENT_OCID from the env.
Revert: remove the two rules whose description starts with "jta-console" from the security list.
"""
from __future__ import annotations

import argparse
import os
import sys

PORTS = (80, 443)
TAG = "jta-console (UI-CONSOLE-V1)"


def _config() -> dict:
    cfg = {"user": os.environ["OCI_CLI_USER"], "key_content": os.environ["OCI_CLI_KEY_CONTENT"],
           "fingerprint": os.environ["OCI_CLI_FINGERPRINT"], "tenancy": os.environ["OCI_CLI_TENANCY"],
           "region": os.environ["OCI_CLI_REGION"]}
    import oci
    oci.config.validate_config(cfg)
    return cfg


def rule_covers(rule, port: int) -> bool:
    """True when an existing ingress rule already admits TCP `port` from anywhere."""
    if getattr(rule, "protocol", None) not in ("6", "all"):
        return False
    if getattr(rule, "source", None) != "0.0.0.0/0":
        return False
    if rule.protocol == "all":
        return True
    opts = getattr(rule, "tcp_options", None)
    rng = getattr(opts, "destination_port_range", None) if opts else None
    if rng is None:
        return True  # all TCP ports
    return rng.min <= port <= rng.max


def missing_ports(rules) -> list[int]:
    return [p for p in PORTS if not any(rule_covers(r, p) for r in rules)]


def find_trainer(cfg: dict, compartment: str, ip: str):
    import oci
    compute, net = oci.core.ComputeClient(cfg), oci.core.VirtualNetworkClient(cfg)
    for inst in oci.pagination.list_call_get_all_results(compute.list_instances, compartment).data:
        if inst.lifecycle_state != "RUNNING":
            continue
        for att in compute.list_vnic_attachments(compartment, instance_id=inst.id).data:
            vnic = net.get_vnic(att.vnic_id).data
            if vnic.public_ip == ip:
                return inst, vnic
    return None, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    import oci
    cfg = _config()
    compartment = os.environ["OCI_COMPARTMENT_OCID"]
    inst, vnic = find_trainer(cfg, compartment, a.ip)
    if inst is None:
        print(f"::error::no RUNNING instance in the compartment has public ip {a.ip}")
        return 2
    net = oci.core.VirtualNetworkClient(cfg)
    subnet = net.get_subnet(vnic.subnet_id).data
    print(f"instance {inst.display_name} subnet {subnet.display_name} security_lists {len(subnet.security_list_ids)} "
          f"nsgs {len(vnic.nsg_ids or [])}")
    lists = [net.get_security_list(s).data for s in subnet.security_list_ids]
    all_rules = [r for sl in lists for r in sl.ingress_security_rules]
    need = missing_ports(all_rules)
    print(f"ingress rules scanned {len(all_rules)}; ports already open {[p for p in PORTS if p not in need]}; "
          f"to add {need}")
    if not need:
        print("RESULT: nothing to do")
        return 0
    if not a.apply:
        print("RESULT: plan only (pass --apply to write)")
        return 0
    target = lists[0]
    new = list(target.ingress_security_rules) + [
        oci.core.models.IngressSecurityRule(
            protocol="6", source="0.0.0.0/0", source_type="CIDR_BLOCK", is_stateless=False,
            description=f"{TAG}: tcp {p}",
            tcp_options=oci.core.models.TcpOptions(destination_port_range=oci.core.models.PortRange(min=p, max=p)))
        for p in need]
    net.update_security_list(target.id, oci.core.models.UpdateSecurityListDetails(ingress_security_rules=new),
                             if_match=None)
    after = net.get_security_list(target.id).data.ingress_security_rules
    still = missing_ports(after)
    print(f"RESULT: wrote {len(need)} rule(s) to {target.display_name}; missing after write {still}")
    return 1 if still else 0


if __name__ == "__main__":
    sys.exit(main())

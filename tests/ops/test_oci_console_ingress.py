"""scripts/ops/oci_console_ingress.py: which existing ingress rules already admit 80/443."""
from __future__ import annotations

from types import SimpleNamespace as NS

from scripts.ops import oci_console_ingress as m


def _rule(protocol="6", source="0.0.0.0/0", lo=None, hi=None):
    opts = NS(destination_port_range=NS(min=lo, max=hi)) if lo is not None else None
    return NS(protocol=protocol, source=source, tcp_options=opts)


def test_only_ssh_open_needs_both_ports():
    assert m.missing_ports([_rule(lo=22, hi=22)]) == [80, 443]


def test_exact_and_range_and_all_rules_cover():
    assert m.missing_ports([_rule(lo=443, hi=443), _rule(lo=80, hi=80)]) == []
    assert m.missing_ports([_rule(lo=1, hi=1000)]) == []
    assert m.missing_ports([_rule(protocol="all")]) == []
    assert m.missing_ports([_rule(lo=None)]) == []  # TCP, no port range = all ports


def test_restricted_source_or_udp_does_not_count():
    assert m.missing_ports([_rule(source="10.0.0.0/16", lo=443, hi=443)]) == [80, 443]
    assert m.missing_ports([_rule(protocol="17", lo=443, hi=443)]) == [80, 443]

#!/usr/bin/env python3
"""Outside-in port probe for security-posture-report (SEC-VM-POSTURE-READ).

Runs ON THE GITHUB RUNNER, which is outside the VCN, so a connect here is what
the internet sees. Read-only: it opens a TCP connection and closes it, and for
UDP 111 it sends one portmapper NULL call (RFC 1833, proc 0) and waits for a
reply. It sends no data to the TCP ports and logs in to nothing.

The host address is taken from argv and NEVER printed (the output goes to a
public issue); the caller passes a label to print instead.

Usage: external_port_probe.py <host> <label> [tcp_port ...]
Output, one line per probe: "<label> tcp/<port>: open|refused|timeout|error".
Port 22 is the positive control: it is public by design (sshd), so if it
does not read "open", the runner cannot reach the host and the other
results say nothing.
"""
from __future__ import annotations

import os
import socket
import struct
import sys


def tcp(host: str, port: int, timeout: float = 5.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "open"
    except ConnectionRefusedError:
        return "refused"
    except (socket.timeout, TimeoutError):
        return "timeout"
    except OSError as exc:
        return f"error ({type(exc).__name__})"


def udp_portmap(host: str, timeout: float = 4.0) -> str:
    """One SUNRPC NULL call to portmapper (prog 100000 v2 proc 0) on UDP 111."""
    xid = int.from_bytes(os.urandom(4), "big")
    # xid, CALL(0), rpcvers 2, prog 100000, vers 2, proc 0, cred AUTH_NULL, verf AUTH_NULL
    msg = struct.pack(">IIIIIIIIII", xid, 0, 2, 100000, 2, 0, 0, 0, 0, 0)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(msg, (host, 111))
        data, _ = s.recvfrom(512)
        if len(data) >= 8 and struct.unpack(">II", data[:8]) == (xid, 1):
            return "open (portmapper replied)"
        return "open (unexpected reply)"
    except (socket.timeout, TimeoutError):
        return "no reply (filtered or closed)"
    except ConnectionRefusedError:
        return "refused (ICMP port unreachable)"
    except OSError as exc:
        return f"error ({type(exc).__name__})"
    finally:
        s.close()


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: external_port_probe.py <host> <label> [tcp_port ...]", file=sys.stderr)
        return 2
    host, label = argv[1], argv[2]
    ports = [int(p) for p in argv[3:]] or [22, 111, 8001, 2019]
    for p in ports:
        print(f"{label} tcp/{p}: {tcp(host, p)}")
    print(f"{label} udp/111: {udp_portmap(host)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

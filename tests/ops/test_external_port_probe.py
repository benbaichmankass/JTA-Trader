"""external_port_probe (SEC-VM-POSTURE-READ): outside-in, read-only, never prints the host."""
from __future__ import annotations

import socket
import struct
import threading

from scripts.ops import external_port_probe as p


def test_tcp_open_and_refused():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert p.tcp("127.0.0.1", port) == "open"
    finally:
        srv.close()
    assert p.tcp("127.0.0.1", port) == "refused"


def test_udp_portmapper_reply_is_recognised(monkeypatch):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv_send = srv.sendto  # bound before the patch below, so the reply is not redirected

    def answer():
        data, addr = srv.recvfrom(512)
        xid, mtype, rpcvers, prog = struct.unpack(">IIII", data[:16])
        assert (mtype, rpcvers, prog) == (0, 2, 100000)
        srv_send(struct.pack(">IIIIII", xid, 1, 0, 0, 0, 0), addr)

    t = threading.Thread(target=answer)
    t.start()
    real_sendto = socket.socket.sendto

    def to_test_port(self, data, addr):
        return real_sendto(self, data, (addr[0], port))

    monkeypatch.setattr(socket.socket, "sendto", to_test_port)
    try:
        assert p.udp_portmap("127.0.0.1").startswith("open")
    finally:
        t.join(timeout=5)
        srv.close()


def test_output_uses_label_never_host(capsys):
    p.main(["x", "127.0.0.1", "trader-public", "1"])
    out = capsys.readouterr().out
    assert "trader-public tcp/1:" in out and "udp/111" in out
    assert "127.0.0.1" not in out

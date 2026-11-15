"""SITE-AUTH step (iii): the site access log exists and redacts credentials.

A site-level `log` in Caddy gets its own logger, so the global filter does not
cover it. Pin that the site block's log deletes every credential header the
global filter deletes, plus the credential query keys.
"""
from __future__ import annotations

import re
from pathlib import Path

CADDY = Path(__file__).resolve().parents[1] / "deploy" / "caddy" / "Caddyfile"


def _site_block(text: str) -> str:
    start = text.index("ict-bot.duckdns.org {")
    return text[start:]


def _global_block(text: str) -> str:
    return text[: text.index("ict-bot.duckdns.org {")]


def _deleted(block: str) -> set[str]:
    return set(re.findall(r"^\s*((?:request|resp_headers)>\S+)\s+delete\s*$", block, re.M))


def test_site_block_has_an_access_log():
    site = _site_block(CADDY.read_text())
    assert re.search(r"^\s*log\s*\{", site, re.M)


def test_site_log_deletes_every_globally_deleted_header():
    text = CADDY.read_text()
    g, s = _deleted(_global_block(text)), _deleted(_site_block(text))
    assert g, "global filter not found (positive control)"
    assert g <= s, sorted(g - s)


def test_site_log_strips_credential_query_keys():
    site = _site_block(CADDY.read_text())
    q = site[site.index("request>uri query"):]
    q = q[: q.index("}")]
    for key in ("ticket", "token", "access_token"):
        assert re.search(rf"^\s*delete {key}\s*$", q, re.M), key

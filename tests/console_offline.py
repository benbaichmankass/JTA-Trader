"""Keep console-connector tests off the network (CI-CONSOLE-READS-LIVE-NETWORK, 2026-11-15).

Since the WORK-STORE S4 freeze, ``data.work_rows`` and ``workplan`` read the live work store on the trader VM over
GET /api/bot/work/items. A test that calls them unpatched makes every PR's pytest-run depend on that VM being
reachable and fast from the CI runner. On 2026-11-15 it was not, and #25314 and #25389 each failed one test with
``KeyError: 'closed_this_week'``. ``tests/console_connector/conftest.py`` already isolates the tests in that
directory; this helper gives the same isolation to console tests that live elsewhere.
"""
from __future__ import annotations


def isolate(monkeypatch) -> None:
    """Read the register from the repo files, refuse the live store and the live API, and start with empty caches."""
    from src.console_connector import data, server, tabs

    monkeypatch.setattr(data, "register_source", lambda repo: "files")

    def no_live_store(url):
        raise AssertionError(f"test reached the live work store: {url}")

    def no_live_api(path, token):
        raise ConnectionError(f"test reached the live API: {path}")

    monkeypatch.setattr(data, "STORE_FETCH", no_live_store)
    monkeypatch.setattr(data, "_STORE_CACHE", None)
    monkeypatch.setattr(tabs, "FETCH", no_live_api)
    monkeypatch.setattr(server, "CACHE", data.TTLCache())

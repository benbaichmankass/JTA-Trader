"""Console-connector tests never reach the live work store: the register reads come from the files
unless a test opts into the store path with its own fake STORE_FETCH."""
import pytest

from src.console_connector import data


@pytest.fixture(autouse=True)
def _register_from_files(monkeypatch, request):
    if "store_register" not in request.keywords:
        monkeypatch.setattr(data, "register_source", lambda repo: "files")

    def no_live(url):
        raise AssertionError(f"test reached the live work store: {url}")
    monkeypatch.setattr(data, "STORE_FETCH", no_live)
    monkeypatch.setattr(data, "_STORE_CACHE", None)


def pytest_configure(config):
    config.addinivalue_line("markers", "store_register: opt into the post-S4 live-store register path (with a fake fetch)")

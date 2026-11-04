"""TICK-DURATION-115S: the YAML parse cache must be indistinguishable from a fresh parse.

The cache exists to cut ~14 re-parses of config/strategies.yaml per symbol per
tick out of the live signal build. Its whole safety argument is that a caller
can never observe it: same value as ``yaml.safe_load`` on the same text, a
private copy per call, an edit seen on the very next call, errors re-raised.
Each test below pins one of those.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
import yaml

from src.utils import yaml_parse_cache as ypc

REPO = Path(__file__).resolve().parents[1]
REAL_CONFIGS = ["config/strategies.yaml", "config/accounts.yaml", "config/instruments.yaml"]


@pytest.fixture(autouse=True)
def _fresh_cache():
    ypc.clear()
    yield
    ypc.clear()


@pytest.mark.parametrize("rel", REAL_CONFIGS)
def test_real_config_parses_identically_cold_and_warm(rel):
    path = REPO / rel
    with open(path, "r", encoding="utf-8") as fh:
        expected = yaml.safe_load(fh)
    cold = ypc.safe_load_path(path)
    warm = ypc.safe_load_path(path)
    assert cold == expected
    assert warm == expected
    # Key ORDER is part of the value for a roster (registry order decides
    # evaluation order): compare it explicitly, == on dicts ignores it.
    assert list(warm) == list(expected)
    if isinstance(expected, dict) and isinstance(expected.get("strategies"), dict):
        assert list(warm["strategies"]) == list(expected["strategies"])
    assert ypc.stats()["hits"] >= 1


def test_each_call_gets_a_private_copy():
    text = "strategies:\n  a: {x: 1, tags: [p, q]}\n"
    first = ypc.safe_load_text(text)
    first["strategies"]["a"]["x"] = 999
    first["strategies"]["a"]["tags"].append("leak")
    first["strategies"]["b"] = {}
    second = ypc.safe_load_text(text)
    assert second == {"strategies": {"a": {"x": 1, "tags": ["p", "q"]}}}


def test_anchor_aliasing_is_preserved_like_a_fresh_parse():
    text = "base: &b {k: 1}\nx: *b\ny: *b\n"
    fresh = yaml.safe_load(text)
    assert fresh["x"] is fresh["y"]  # what safe_load does with an alias
    ypc.safe_load_text(text)
    warm = ypc.safe_load_text(text)
    assert warm == fresh
    assert warm["x"] is warm["y"]


def test_an_edit_is_seen_on_the_next_call_even_with_same_size_and_mtime(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("strategies:\n  a: {x: 1}\n", encoding="utf-8")
    st = os.stat(p)
    assert ypc.safe_load_path(p)["strategies"]["a"]["x"] == 1
    p.write_text("strategies:\n  a: {x: 2}\n", encoding="utf-8")  # same length
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # same mtime too
    assert ypc.safe_load_path(p)["strategies"]["a"]["x"] == 2


def test_parse_errors_are_raised_every_time_and_never_cached():
    bad = "a: [1, 2\n"
    for _ in range(2):
        with pytest.raises(yaml.YAMLError):
            ypc.safe_load_text(bad)
    assert ypc.stats()["entries"] == 0


def test_missing_file_raises_like_open(tmp_path):
    with pytest.raises(FileNotFoundError):
        ypc.safe_load_path(tmp_path / "nope.yaml")


def test_cache_is_bounded():
    for i in range(ypc._MAX_ENTRIES + 10):
        ypc.safe_load_text(f"v: {i}\n")
    assert ypc.stats()["entries"] == ypc._MAX_ENTRIES
    assert ypc.safe_load_text("v: 0\n") == {"v": 0}  # evicted entry re-parses correctly


def test_concurrent_callers_all_see_the_same_value():
    text = (REPO / "config/strategies.yaml").read_text(encoding="utf-8")
    expected = yaml.safe_load(text)
    out, errs = [], []

    def worker():
        try:
            for _ in range(3):
                out.append(ypc.safe_load_text(text) == expected)
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs
    assert out and all(out)


# --- the four production loaders that now route through the cache -----------

def test_load_strategy_config_matches_the_pre_change_parse():
    from src.units.strategies import load_strategy_config
    path = REPO / "config/strategies.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        expected = dict((yaml.safe_load(fh) or {}).get("strategies") or {})
    for _ in range(2):
        got = load_strategy_config(str(path))
        assert got == expected
        assert list(got) == list(expected)


def test_load_strategy_config_still_raises_on_missing_file(tmp_path):
    from src.units.strategies import load_strategy_config
    with pytest.raises(FileNotFoundError):
        load_strategy_config(str(tmp_path / "missing.yaml"))


def test_load_accounts_dict_matches_the_pre_change_parse(monkeypatch):
    monkeypatch.delenv("ACCOUNTS_YAML_PATH", raising=False)
    from src.config.accounts_loader import load_accounts_dict
    with open(REPO / "config/accounts.yaml", "r", encoding="utf-8") as fh:
        raw = (yaml.safe_load(fh) or {}).get("accounts") or {}
    expected = {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    for _ in range(2):
        got = load_accounts_dict(REPO / "config/accounts.yaml")
        assert got == expected
        assert list(got) == list(expected)


def test_load_accounts_dict_still_reports_a_parse_error(tmp_path):
    from src.config.accounts_loader import load_accounts_dict
    p = tmp_path / "accounts.yaml"
    p.write_text("accounts: [\n", encoding="utf-8")
    errors: list = []
    assert load_accounts_dict(p, errors=errors) == {}
    assert errors and errors[0]["path"] == str(p)


def test_strategy_registry_parse_and_digest_match_the_same_read():
    from src.runtime.loaded_config import digest_text
    from src.strategy_registry import _load_yaml_with_digest
    path = REPO / "config/strategies.yaml"
    text = path.read_text(encoding="utf-8")
    for _ in range(2):
        parsed, digest = _load_yaml_with_digest(str(path))
        assert parsed == yaml.safe_load(text)
        assert digest == digest_text(text)

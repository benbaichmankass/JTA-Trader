"""Display aliases for ML models (lane MODEL-NAMES, operator 2026-11-03).

Pure lookup over ml/model_names.yaml: model id -> display name, falling back to the id. Aliases are for
human-facing lines only; never use them as a key, never rename a model id."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("model_names.yaml")


@lru_cache(maxsize=1)
def _load(path: str = str(_PATH)) -> dict:
    try:
        return (yaml.safe_load(Path(path).read_text()) or {}).get("models") or {}
    except (OSError, yaml.YAMLError):
        return {}


def display_name(model_id: str, models: dict | None = None) -> str:
    """Alias for model_id (e.g. 'Collie-5a'), or model_id itself when unnamed."""
    m = (models if models is not None else _load()).get(model_id)
    return str(m["name"]) if isinstance(m, dict) and m.get("name") else model_id


def labelled(model_id: str, models: dict | None = None) -> str:
    """'Collie-5a (btc-regime-15m-...)' when named, else the bare id."""
    n = display_name(model_id, models)
    return model_id if n == model_id else f"{n} ({model_id})"

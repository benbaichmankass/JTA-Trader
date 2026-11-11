"""Bearer checks compare in constant time and still accept/refuse correctly (SEC-API-DEVICE-REGISTER-OPEN)."""
import inspect

import pytest
from fastapi import HTTPException

from src.web.api.routers import devices, prop


@pytest.mark.parametrize("check", [prop._require_write_token, devices._check_admin_token])
def test_right_token_passes_wrong_token_is_401(check, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "s3cret-token")
    assert check("Bearer s3cret-token") is None
    for bad in ("Bearer s3cret-toke", "Bearer s3cret-token2", "Bearer ", "Bearer é"):
        with pytest.raises(HTTPException) as e:
            check(bad)
        assert e.value.status_code == 401


@pytest.mark.parametrize("check", [prop._require_write_token, devices._check_admin_token])
def test_comparison_is_compare_digest_not_equality(check):
    src = inspect.getsource(check)
    assert "compare_digest" in src and "!= expected" not in src

"""Unit tests for auth dependency (api_key)."""

import pytest
from unittest.mock import patch, MagicMock

from app.api.dependencies.auth import get_optional_auth


@pytest.mark.asyncio
async def test_auth_none_returns_none():
    """When AUTH_METHOD is none, get_optional_auth returns None."""
    with patch("app.api.dependencies.auth.get_settings") as m:
        s = MagicMock()
        s.AUTH_METHOD = "none"
        m.return_value = s
        result = await get_optional_auth(api_key=None, credentials=None)
        assert result is None


@pytest.mark.asyncio
async def test_auth_api_key_valid():
    """When AUTH_METHOD=api_key and X-API-Key is valid, auth passes."""
    with patch("app.api.dependencies.auth.get_settings") as m:
        s = MagicMock()
        s.AUTH_METHOD = "api_key"
        s.API_KEY = "secret"
        s.API_KEYS = ""
        m.return_value = s
        result = await get_optional_auth(api_key="secret", credentials=None)
        assert result == {"auth": "api_key"}


@pytest.mark.asyncio
async def test_auth_bearer_valid():
    """When AUTH_METHOD=bearer and token matches, auth passes."""
    from fastapi.security import HTTPAuthorizationCredentials

    with patch("app.api.dependencies.auth.get_settings") as m:
        s = MagicMock()
        s.AUTH_METHOD = "bearer"
        s.BEARER_TOKEN = "secret-token"
        m.return_value = s
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-token")
        result = await get_optional_auth(api_key=None, credentials=credentials)
        assert result == {"auth": "bearer"}


@pytest.mark.asyncio
async def test_auth_bearer_invalid():
    """When AUTH_METHOD=bearer and token is wrong, raises 401."""
    from fastapi.security import HTTPAuthorizationCredentials

    with patch("app.api.dependencies.auth.get_settings") as m:
        s = MagicMock()
        s.AUTH_METHOD = "bearer"
        s.BEARER_TOKEN = "secret-token"
        m.return_value = s
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_optional_auth(api_key=None, credentials=credentials)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_api_key_invalid():
    """When AUTH_METHOD=api_key and key is wrong, raises 401."""
    with patch("app.api.dependencies.auth.get_settings") as m:
        s = MagicMock()
        s.AUTH_METHOD = "api_key"
        s.API_KEY = "secret"
        s.API_KEYS = ""
        m.return_value = s
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_optional_auth(api_key="wrong", credentials=None)
        assert exc_info.value.status_code == 401

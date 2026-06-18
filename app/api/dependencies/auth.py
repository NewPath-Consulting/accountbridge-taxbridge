"""Optional API authentication via AUTH_METHOD (none | api_key | bearer | jwt)."""

from typing import Any, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(
    scheme_name="Bearer",
    description="Enter the API bearer token (same value as BEARER_TOKEN in .env)",
    auto_error=False,
)


def _validate_api_key(api_key: Optional[str]) -> Optional[Any]:
    settings = get_settings()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
    allowed = [settings.API_KEY] if settings.API_KEY else []
    if settings.API_KEYS:
        allowed.extend(k.strip() for k in settings.API_KEYS.split(",") if k.strip())
    if api_key not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return {"auth": "api_key"}


def _validate_bearer(token: str) -> Optional[Any]:
    settings = get_settings()
    if not settings.BEARER_TOKEN or token != settings.BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"auth": "bearer"}


def _validate_jwt(token: str) -> Optional[Any]:
    try:
        import jwt as pyjwt
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT support not installed (install PyJWT)",
        )
    settings = get_settings()
    if not settings.JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT_SECRET not configured",
        )
    try:
        payload = pyjwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return {"auth": "jwt", "payload": payload}
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def _no_auth() -> None:
    return None


async def require_bearer_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> Optional[Any]:
    """Bearer (or JWT) auth — only this scheme appears in Swagger."""
    settings = get_settings()
    if settings.AUTH_METHOD == "none":
        return None

    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if settings.AUTH_METHOD == "bearer":
        return _validate_bearer(token)
    if settings.AUTH_METHOD == "jwt":
        return _validate_jwt(token)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"AUTH_METHOD={settings.AUTH_METHOD} does not use bearer tokens",
    )


async def require_api_key_auth(
    api_key: Optional[str] = Depends(_api_key_header),
) -> Optional[Any]:
    """API-key auth — only X-API-Key appears in Swagger."""
    settings = get_settings()
    if settings.AUTH_METHOD == "none":
        return None
    if settings.AUTH_METHOD != "api_key":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AUTH_METHOD={settings.AUTH_METHOD} does not use API keys",
        )
    return _validate_api_key(api_key)


def _resolve_auth_dependency() -> Depends:
    """Pick the auth dependency for the configured AUTH_METHOD (one scheme in Swagger)."""
    settings = get_settings()
    if settings.AUTH_METHOD == "none":
        return Depends(_no_auth)
    if settings.AUTH_METHOD == "api_key":
        return Depends(require_api_key_auth)
    return Depends(require_bearer_auth)


require_api_auth = _resolve_auth_dependency()


async def get_optional_auth(
    api_key: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> Optional[Any]:
    """
    Programmatic/test helper. Routes should use require_api_auth (bearer or api_key only).
    """
    settings = get_settings()
    if settings.AUTH_METHOD == "none":
        return None
    if settings.AUTH_METHOD == "api_key":
        return _validate_api_key(api_key)
    if settings.AUTH_METHOD in ("bearer", "jwt"):
        token = None
        if credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization: Bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if settings.AUTH_METHOD == "bearer":
            return _validate_bearer(token)
        return _validate_jwt(token)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Unknown AUTH_METHOD: {settings.AUTH_METHOD}",
    )

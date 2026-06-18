"""Core auth service: optional API authentication (api_key, bearer, jwt)."""

from app.auth.dependencies import get_optional_auth

__all__ = ["get_optional_auth"]

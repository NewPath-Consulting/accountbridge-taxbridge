"""Data models for WildApricot OAuth and API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class PermissionInfo:
    account_id: int
    security_profile_id: int | None = None
    available_scopes: list[str] = field(default_factory=list)


@dataclass
class TokenBundle:
    access_token: str
    token_type: str
    expires_in: int
    expires_at: datetime
    refresh_token: str | None = None
    permissions: list[PermissionInfo] = field(default_factory=list)

    @classmethod
    def from_oauth_response(cls, payload: dict[str, Any]) -> TokenBundle:
        access_token = payload.get("access_token") or payload.get("AccessToken")
        if not access_token:
            raise ValueError("OAuth response missing access_token")

        expires_in = int(payload.get("expires_in") or payload.get("ExpiresIn") or 1800)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        refresh = payload.get("refresh_token") or payload.get("RefreshToken")
        permissions = _parse_permissions(payload)

        return cls(
            access_token=access_token,
            token_type=payload.get("token_type") or payload.get("TokenType") or "Bearer",
            expires_in=expires_in,
            expires_at=expires_at,
            refresh_token=refresh,
            permissions=permissions,
        )


def _parse_permissions(payload: dict[str, Any]) -> list[PermissionInfo]:
    raw = payload.get("Permissions") or payload.get("permissions") or []
    result: list[PermissionInfo] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        account_id = item.get("AccountId") or item.get("accountId")
        if account_id is None:
            continue
        scopes = item.get("AvailableScopes") or item.get("availableScopes") or []
        result.append(
            PermissionInfo(
                account_id=int(account_id),
                security_profile_id=item.get("SecurityProfileId") or item.get("securityProfileId"),
                available_scopes=list(scopes) if isinstance(scopes, list) else [],
            )
        )
    return result

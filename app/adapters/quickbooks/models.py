"""Data models for QuickBooks OAuth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class TokenBundle:
    access_token: str
    token_type: str
    expires_in: int
    expires_at: datetime
    refresh_token: str | None = None

    @classmethod
    def from_oauth_response(cls, payload: dict[str, Any]) -> TokenBundle:
        access_token = payload.get("access_token") or payload.get("accessToken")
        if not access_token:
            raise ValueError("OAuth response missing access_token")

        expires_in = int(payload.get("expires_in") or 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        refresh = payload.get("refresh_token") or payload.get("refreshToken")

        return cls(
            access_token=access_token,
            token_type=payload.get("token_type") or "Bearer",
            expires_in=expires_in,
            expires_at=expires_at,
            refresh_token=refresh,
        )

    @classmethod
    def from_settings(
        cls,
        *,
        access_token: str,
        refresh_token: str | None,
        expires_in: int = 3600,
    ) -> TokenBundle:
        """Seed cache from env; assume full lifetime until refresh is required."""
        return cls(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            refresh_token=refresh_token,
        )

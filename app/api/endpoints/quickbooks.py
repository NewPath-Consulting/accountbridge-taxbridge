"""QuickBooks credential management endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.adapters.quickbooks.auth import (
    TokenManager,
    _looks_like_access_token,
    _looks_like_refresh_token,
    _oauth_error_hint,
    _sanitize_oauth_token,
    save_quickbooks_credentials_to_env,
)
from app.adapters.quickbooks.exceptions import (
    QuickBooksAuthError,
    QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
)
from app.config.settings import get_settings
from app.services.token_refresh_service import reset_token_refresh_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class QuickBooksCredentialsRequest(BaseModel):
    client_id: str = Field(..., min_length=5, description="QuickBooks app Client ID")
    client_secret: str = Field(..., min_length=5, description="QuickBooks app Client Secret")
    refresh_token: str = Field(
        ...,
        min_length=10,
        description="Refresh token (RT1-...) from the OAuth playground Get Tokens response",
    )
    access_token: Optional[str] = Field(
        None,
        description="Optional access token from the playground (saved and used until refresh runs)",
    )
    realm_id: Optional[str] = Field(
        None,
        description="Optional QuickBooks company / realm ID",
    )


class QuickBooksRefreshTokenRequest(BaseModel):
    """Legacy body — refresh token only (uses client id/secret from .env)."""

    refresh_token: str = Field(..., min_length=10)


class QuickBooksCredentialsResponse(BaseModel):
    status: str
    message: str
    notify: str


def _sanitize_credential(value: str) -> str:
    return _sanitize_oauth_token(value)


def _register_quickbooks_credentials(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    access_token: str | None,
    realm_id: str | None,
) -> None:
    cfg = get_settings()

    save_quickbooks_credentials_to_env(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        access_token=access_token,
        realm_id=realm_id,
    )
    get_settings.cache_clear()
    reset_token_refresh_manager()

    manager = TokenManager(
        client_id=client_id,
        client_secret=client_secret,
        oauth_url=cfg.QUICKBOOKS_OAUTH_URL,
        refresh_token=refresh_token,
        access_token=access_token,
        redirect_uri=cfg.QUICKBOOKS_REDIRECT_URI or None,
        refresh_buffer_seconds=cfg.QUICKBOOKS_TOKEN_REFRESH_BUFFER_SECONDS,
        timeout_seconds=cfg.QUICKBOOKS_HTTP_TIMEOUT_SECONDS,
    )

    if _looks_like_refresh_token(refresh_token):
        manager.update_refresh_token(refresh_token)
    else:
        manager.exchange_authorization_code(refresh_token)

    get_settings.cache_clear()
    reset_token_refresh_manager()


@router.post(
    "/quickbooks/credentials",
    response_model=QuickBooksCredentialsResponse,
    tags=["QuickBooks"],
    summary="Submit QuickBooks Client ID, Secret, and tokens",
)
async def submit_quickbooks_credentials(
    body: QuickBooksCredentialsRequest,
) -> QuickBooksCredentialsResponse:
    """
    Save and validate full QuickBooks credentials from the OAuth playground.

    Updates .env, validates the refresh token with Intuit, then saves rotated tokens.
    """
    try:
        client_id = _sanitize_credential(body.client_id)
        client_secret = _sanitize_credential(body.client_secret)
        refresh_token = _sanitize_oauth_token(body.refresh_token)
        access_token = (
            _sanitize_oauth_token(body.access_token) if body.access_token else None
        )
        realm_id = body.realm_id.strip() if body.realm_id else None

        if not refresh_token:
            raise QuickBooksAuthError("refresh_token is required")
        if _looks_like_access_token(refresh_token):
            raise QuickBooksAuthError(
                "refresh_token field contains an access token. "
                "Paste the refresh token (RT1-...) in refresh_token and the "
                "access token in access_token."
            )

        logger.info(
            "QuickBooks credentials submit client_id_prefix=%s refresh_prefix=%s",
            client_id[:8],
            refresh_token[:4],
        )

        _register_quickbooks_credentials(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            access_token=access_token,
            realm_id=realm_id,
        )

        return QuickBooksCredentialsResponse(
            status="ok",
            message="QuickBooks credentials saved and validated successfully.",
            notify=QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
        )
    except QuickBooksAuthError as exc:
        hint = _oauth_error_hint(exc)
        logger.error("QuickBooks credentials update failed: %s", exc)
        raise HTTPException(
            status_code=401,
            detail={
                "error": "quickbooks_refresh_token_invalid",
                "message": hint,
                "notify": QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
            },
        ) from exc


@router.post(
    "/quickbooks/refresh-token",
    response_model=QuickBooksCredentialsResponse,
    tags=["QuickBooks"],
    summary="Submit a new QuickBooks refresh token (legacy)",
)
async def submit_quickbooks_refresh_token(
    body: QuickBooksRefreshTokenRequest,
) -> QuickBooksCredentialsResponse:
    """Save and validate a refresh token using client id/secret already in .env."""
    cfg = get_settings()
    if not cfg.QUICKBOOKS_CLIENT_ID or not cfg.QUICKBOOKS_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="QUICKBOOKS_CLIENT_ID and QUICKBOOKS_CLIENT_SECRET must be set. "
            "Use POST /api/quickbooks/credentials instead.",
        )

    request = QuickBooksCredentialsRequest(
        client_id=cfg.QUICKBOOKS_CLIENT_ID,
        client_secret=cfg.QUICKBOOKS_CLIENT_SECRET,
        refresh_token=body.refresh_token,
        access_token=cfg.QUICKBOOKS_ACCESS_TOKEN or None,
        realm_id=cfg.QUICKBOOKS_REALM_ID or None,
    )
    return await submit_quickbooks_credentials(request)

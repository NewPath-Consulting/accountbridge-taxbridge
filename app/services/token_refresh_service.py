"""Background service to automatically refresh QuickBooks tokens before expiry."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.adapters.quickbooks.auth import TokenManager
from app.config.settings import settings

logger = logging.getLogger(__name__)


class TokenRefreshService:
    """
    Background service that automatically refreshes QuickBooks tokens.
    
    - Access tokens: Refresh every 50 minutes (before 1-hour expiry)
    - Refresh tokens: Refresh every 90 days (before 100-day expiry)
    """
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._token_manager: Optional[TokenManager] = None
        
        # Get refresh interval from settings
        self.refresh_interval_minutes = settings.QUICKBOOKS_AUTO_REFRESH_INTERVAL_MINUTES
        self.enabled = settings.QUICKBOOKS_AUTO_REFRESH_ENABLED
        
    def start(self):
        """Start the background token refresh service."""
        if not self.enabled:
            logger.info("Token auto-refresh is disabled in settings")
            return
        
        if self._running:
            logger.warning("Token refresh service already running")
            return
        
        if not settings.QUICKBOOKS_REFRESH_TOKEN and not settings.QUICKBOOKS_AUTH_CODE:
            logger.warning(
                "QuickBooks refresh token or auth code not configured, "
                "cannot start auto-refresh"
            )
            return
        
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info(
            f"Token refresh service started (will refresh every {self.refresh_interval_minutes} minutes)"
        )
    
    def stop(self):
        """Stop the background token refresh service."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Token refresh service stopped")
    
    async def _refresh_loop(self):
        """Main loop that periodically refreshes tokens."""
        await asyncio.sleep(10)  # Wait 10 seconds before first check
        
        while self._running:
            try:
                await self._refresh_tokens_if_needed()
            except Exception as e:
                logger.error(f"Token refresh failed: {str(e)}", exc_info=True)
            
            # Wait for configured interval before next refresh
            interval_seconds = self.refresh_interval_minutes * 60
            logger.info(f"Next token refresh in {self.refresh_interval_minutes} minutes")
            await asyncio.sleep(interval_seconds)
    
    async def _refresh_tokens_if_needed(self):
        """Check and refresh tokens if needed."""
        try:
            # Initialize token manager if needed
            if not self._token_manager:
                if not settings.QUICKBOOKS_REFRESH_TOKEN and not settings.QUICKBOOKS_AUTH_CODE:
                    logger.warning(
                        "QuickBooks refresh token or auth code not configured, "
                        "skipping auto-refresh"
                    )
                    return

                self._token_manager = TokenManager(
                    client_id=settings.QUICKBOOKS_CLIENT_ID,
                    client_secret=settings.QUICKBOOKS_CLIENT_SECRET,
                    oauth_url=settings.QUICKBOOKS_OAUTH_URL,
                    refresh_token=settings.QUICKBOOKS_REFRESH_TOKEN or None,
                    access_token=settings.QUICKBOOKS_ACCESS_TOKEN or None,
                    auth_code=settings.QUICKBOOKS_AUTH_CODE or None,
                    redirect_uri=settings.QUICKBOOKS_REDIRECT_URI or None,
                    refresh_buffer_seconds=300,
                )
            
            # Refresh only when the cached token is near expiry.
            loop = asyncio.get_event_loop()
            token = await loop.run_in_executor(
                None,
                self._token_manager.get_valid_token,
            )
            
            logger.info(
                f"✅ QuickBooks tokens refreshed and saved to .env successfully! "
                f"Next refresh in {self.refresh_interval_minutes} minutes"
            )
            
        except Exception as e:
            logger.error(f"Failed to refresh QuickBooks tokens: {str(e)}")
            # Don't stop the service, just try again next time
    
    async def refresh_now(self):
        """Manually trigger a token refresh."""
        logger.info("Manual token refresh triggered")
        await self._refresh_tokens_if_needed()


# Global instance
_token_refresh_service: Optional[TokenRefreshService] = None


def get_token_refresh_service() -> TokenRefreshService:
    """Get or create the global token refresh service."""
    global _token_refresh_service
    if _token_refresh_service is None:
        _token_refresh_service = TokenRefreshService()
    return _token_refresh_service


def start_token_refresh_service():
    """Start the global token refresh service."""
    service = get_token_refresh_service()
    service.start()


def stop_token_refresh_service():
    """Stop the global token refresh service."""
    service = get_token_refresh_service()
    service.stop()


def reset_token_refresh_manager() -> None:
    """Drop cached TokenManager so the next refresh reads updated .env credentials."""
    service = get_token_refresh_service()
    service._token_manager = None

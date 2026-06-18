"""QuickBooks adapter exceptions."""


class QuickBooksError(Exception):
    """Base exception for QuickBooks adapter errors."""


QUICKBOOKS_PLAYGROUND_URL = "https://developer.intuit.com/app/developer/playground"
QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE = (
    'You need to visit the "https://developer.intuit.com/app/developer/playground" '
    "link for generating the refresh token"
)


class QuickBooksAuthError(QuickBooksError):
    """OAuth or credential failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class QuickBooksRefreshTokenRequiredError(QuickBooksAuthError):
    """Refresh token is missing, expired, or invalid — user must supply a new one."""

    def __init__(
        self,
        message: str = "QuickBooks refresh token is expired or invalid",
        *,
        wildapricot_data: dict | None = None,
    ) -> None:
        super().__init__(message, status_code=401, response_body="invalid_grant")
        self.wildapricot_data = wildapricot_data


class QuickBooksAPIError(QuickBooksError):
    """HTTP API failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.response_body = response_body

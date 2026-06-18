"""WildApricot adapter exceptions."""


class WildApricotError(Exception):
    """Base exception for WildApricot adapter errors."""


class WildApricotAuthError(WildApricotError):
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


class WildApricotAPIError(WildApricotError):
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

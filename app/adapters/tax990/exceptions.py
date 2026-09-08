"""Errors from the Tax990 e-filing API."""

from __future__ import annotations

from typing import Any


class Tax990Error(Exception):
    """Base for anything that goes wrong talking to Tax990."""


class Tax990AuthError(Tax990Error):
    """The JWS handshake or token exchange was refused.

    Most often the three credentials are not from the same account, or the
    user token has been pasted where the client secret belongs -- they are
    similar-looking base64 strings and easy to transpose.
    """


class Tax990ValidationError(Tax990Error):
    """Tax990 accepted the request and rejected the return.

    Carries the field-level errors their validation engine returned, which is
    the most useful thing the API produces: it names the element at fault
    rather than failing the submission as a whole.
    """

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class Tax990ReturnExistsError(Tax990ValidationError):
    """A return already exists for this organization and tax year.

    Not a failure. Tax990 refuses a second 990-N for the same EIN and period,
    which is correct, and the existing draft can be retrieved instead.
    """

    CODE = "F990N037"

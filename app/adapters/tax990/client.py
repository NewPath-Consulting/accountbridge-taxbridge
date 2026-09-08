"""Client for the Tax990 e-filing API.

Tax990 is an IRS-authorised e-file provider. Their API currently accepts the
Form 990-N; support for the longer forms is on their roadmap.

Authentication is a two-step handshake rather than a single key exchange:

    POST /Auth/GenerateJWS      client id, secret, user token  ->  a JWS
    GET  /Auth/GetTax990Token   the JWS in an `authentication` header  ->  token

Every response is wrapped in an envelope -- `{"statusCode": .., "response": {..}}`
-- so the payload is one level deeper than it first appears.

The submission lifecycle:

    POST /v1/form990n/create     a draft return
    GET  /v1/form990n/list       resolve a draft that already exists
    GET  /v1/form990n/validate   Tax990's own field-level validation
    GET  /v1/form990n/getPDF     a link to the rendered form

Tax990 refuses a second 990-N for the same EIN and tax year. That is correct
behaviour, not an error, so it is raised as its own exception and callers can
retrieve the existing draft instead of failing.

The sandbox hosts are the default. Production requires both to be passed
explicitly, so a misconfigured environment variable cannot file a live return.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping, Optional

import httpx

from app.adapters.tax990.exceptions import (
    Tax990AuthError,
    Tax990Error,
    Tax990ReturnExistsError,
    Tax990ValidationError,
)

logger = logging.getLogger(__name__)

__all__ = ["Tax990Client", "SANDBOX_OAUTH_HOST", "SANDBOX_API_HOST"]

SANDBOX_OAUTH_HOST = "https://oauth-sandbox.tax990.com"
SANDBOX_API_HOST = "https://api-sandbox.tax990.com"


class Tax990Client:
    """Talks to Tax990. Sandbox unless told otherwise."""

    def __init__(
        self,
        client_id: str,
        client_secret_id: str,
        user_token: str,
        *,
        oauth_host: str = SANDBOX_OAUTH_HOST,
        api_host: str = SANDBOX_API_HOST,
        timeout: float = 60.0,
    ) -> None:
        if not all((client_id, client_secret_id, user_token)):
            raise Tax990AuthError(
                "Tax990 needs a client ID, client secret and user token. The "
                "secret and the user token are different values, though both "
                "look like base64."
            )
        self.client_id = client_id
        self.client_secret_id = client_secret_id
        self.user_token = user_token
        self.oauth_host = oauth_host.rstrip("/")
        self.api_host = api_host.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None

    @property
    def is_sandbox(self) -> bool:
        return "sandbox" in self.api_host

    # --- envelope handling ------------------------------------------------

    @staticmethod
    def _errors(body: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Collect errors from both places Tax990 puts them.

        A request-level problem lands in `Errors`. A problem with a particular
        return lands in `Form990NRecords.ErrorRecords[].Errors[]`, and the
        top-level `Errors` is then null -- so reading only the first misses
        the message that actually names the field at fault.
        """
        found = [e for e in (body.get("Errors") or []) if isinstance(e, dict)]

        records = body.get("Form990NRecords") or {}
        if isinstance(records, dict):
            for record in records.get("ErrorRecords") or []:
                if not isinstance(record, dict):
                    continue
                for error in record.get("Errors") or []:
                    if isinstance(error, dict):
                        found.append({**error, "SequenceId": record.get("SequenceId")})
        return found

    @staticmethod
    def _unwrap(response: httpx.Response, *, context: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise Tax990Error(
                f"{context}: Tax990 returned a non-JSON response "
                f"({response.status_code})."
            ) from exc

        inner = body.get("response")
        return inner if isinstance(inner, dict) else body

    # --- authentication ---------------------------------------------------

    def authenticate(self, client: httpx.Client) -> str:
        """Run the handshake and cache the access token."""
        if self._token:
            return self._token

        jws_response = client.post(
            f"{self.oauth_host}/Auth/GenerateJWS",
            json={
                "ClientId": self.client_id,
                "ClientSecretId": self.client_secret_id,
                "UserToken": self.user_token,
            },
            headers={"Accept": "application/json"},
        )
        if jws_response.status_code != 200:
            raise Tax990AuthError(
                f"Tax990 refused the credentials ({jws_response.status_code}). "
                f"Check the client ID and secret."
            )
        jws = self._unwrap(jws_response, context="GenerateJWS").get("JWSToken")
        if not jws:
            raise Tax990AuthError("Tax990 returned no JWS token.")

        token_response = client.get(
            f"{self.oauth_host}/Auth/GetTax990Token",
            headers={"authentication": jws, "Accept": "application/json"},
        )
        if token_response.status_code != 200:
            raise Tax990AuthError(
                f"Tax990 rejected the JWS ({token_response.status_code}). The "
                f"user token is most likely wrong -- it is a separate value "
                f"from the client secret."
            )
        token = self._unwrap(token_response, context="GetTax990Token").get("AccessToken")
        if not token:
            raise Tax990AuthError("Tax990 returned no access token.")

        self._token = token
        return token

    def _headers(self, correlation_id: str, *, idempotent: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "x-correlation-id": correlation_id,
        }
        if idempotent:
            headers["idempotency-key"] = correlation_id
        return headers

    # --- the submission lifecycle -----------------------------------------

    def submit_990n(
        self,
        payload: Mapping[str, Any],
        *,
        correlation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a 990-N draft, validate it, and retrieve the rendered form.

        Returns the submission and record identifiers, Tax990's validation
        result, and a link to the PDF. When a return already exists for the
        organization and year the existing draft is retrieved rather than
        treated as a failure.
        """
        correlation_id = correlation_id or str(uuid.uuid4())

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            self.authenticate(client)

            created = self._create(client, payload, correlation_id)
            submission_id, record_id, return_number, existed = created

            if not (submission_id and record_id):
                raise Tax990Error(
                    "Tax990 accepted the request but returned no record to retrieve."
                )

            validation = self._validate(client, submission_id, record_id, correlation_id)
            pdf_url = self._pdf_url(client, submission_id, record_id, correlation_id)

            return {
                "submission_id": submission_id,
                "record_id": record_id,
                "return_number": return_number,
                "already_existed": existed,
                "validation_errors": validation,
                "pdf_url": pdf_url,
                "is_sandbox": self.is_sandbox,
            }

    def _create(
        self, client: httpx.Client, payload: Mapping[str, Any], correlation_id: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], bool]:
        response = client.post(
            f"{self.api_host}/v1/form990n/create",
            json=dict(payload),
            headers=self._headers(correlation_id, idempotent=True),
        )
        body = response.json() if response.content else {}
        submission_id = body.get("SubmissionId")
        errors = self._errors(body)

        if any(
            isinstance(e, dict) and e.get("Code") == Tax990ReturnExistsError.CODE
            for e in errors
        ):
            logger.info("Tax990 already holds a return; retrieving the existing draft")
            record_id, return_number = self._find_existing(
                client, submission_id, correlation_id
            )
            return submission_id, record_id, return_number, True

        if errors:
            detail = "; ".join(
                f"{e.get('Field') or e.get('Code') or 'error'}: {e.get('Message')}"
                for e in errors
                if e.get("Message")
            )
            raise Tax990ValidationError(
                f"Tax990 rejected the return. {detail}".strip(), errors
            )

        record_id, return_number = self._first_success(body)
        return submission_id, record_id, return_number, False

    def _find_existing(
        self, client: httpx.Client, submission_id: Optional[str], correlation_id: str
    ) -> tuple[Optional[str], Optional[str]]:
        response = client.get(
            f"{self.api_host}/v1/form990n/list",
            params={"SubmissionId": submission_id} if submission_id else {},
            headers=self._headers(correlation_id),
        )
        body = response.json() if response.content else {}
        return self._first_success(body)

    @staticmethod
    def _first_success(body: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
        records = body.get("Form990NRecords") or {}
        successes = (
            records.get("SuccessRecords") or []
            if isinstance(records, dict) else records
        )
        for record in successes:
            if isinstance(record, dict) and record.get("RecordId"):
                return record["RecordId"], record.get("ReturnNumber")
        return None, None

    def _validate(
        self, client: httpx.Client, submission_id: str, record_id: str,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        response = client.get(
            f"{self.api_host}/v1/form990n/validate",
            params={"SubmissionId": submission_id, "RecordIds": record_id},
            headers=self._headers(correlation_id),
        )
        body = response.json() if response.content else {}
        return self._errors(body)

    def _pdf_url(
        self, client: httpx.Client, submission_id: str, record_id: str,
        correlation_id: str,
    ) -> Optional[str]:
        response = client.get(
            f"{self.api_host}/v1/form990n/getPDF",
            params={"SubmissionId": submission_id, "RecordIds": record_id},
            headers=self._headers(correlation_id),
        )
        body = response.json() if response.content else {}
        for record in body.get("Form990NRecords") or []:
            if isinstance(record, dict) and record.get("PDFUrl"):
                return record["PDFUrl"]
        return None

    def download_pdf(self, url: str) -> bytes:
        """Fetch the rendered form. The link is short-lived."""
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code != 200:
                raise Tax990Error(
                    f"Could not download the form ({response.status_code}). "
                    f"The link may have expired."
                )
            return response.content

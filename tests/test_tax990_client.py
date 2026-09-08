"""Tests for the Tax990 client.

Every response is faked through httpx's mock transport, so these run offline
and deterministically. The shapes are taken from real sandbox responses --
including the envelope, which puts the payload one level deeper than it looks.
"""

import json

import httpx
import pytest

from app.adapters.tax990.client import (
    SANDBOX_API_HOST,
    SANDBOX_OAUTH_HOST,
    Tax990Client,
)
from app.adapters.tax990.exceptions import (
    Tax990AuthError,
    Tax990Error,
    Tax990ValidationError,
)

CREDENTIALS = dict(
    client_id="8ad4e5f5e36e4e5e",
    client_secret_id="MjBkNTkwNjQzMGEwNDFhNDhhZDRlNWY1ZTM2ZTRlNWU",
    user_token="8e13fb6b6f6c45bfb9a13f4431f32e99",
)

PAYLOAD = {
    "Form990NRecords": [
        {
            "Business": {"BusinessNm": "Example Association", "EIN": "431633425"},
            "Form990N": {"TaxYr": "2026", "IsGrossReceiptsUnder50K": True},
        }
    ]
}


def _envelope(payload: dict, status: str = "Success") -> dict:
    return {"statusCode": 200, "status": status, "message": "ok", "response": payload}


class _Sandbox:
    """A fake Tax990. Records what it was asked for."""

    def __init__(self, *, create_body=None, list_body=None, validation_errors=None,
                 pdf_url="https://example/form.pdf", auth_ok=True, token_ok=True):
        self.create_body = create_body
        self.list_body = list_body
        self.validation_errors = validation_errors or []
        self.pdf_url = pdf_url
        self.auth_ok = auth_ok
        self.token_ok = token_ok
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)

        if path.endswith("/Auth/GenerateJWS"):
            if not self.auth_ok:
                return httpx.Response(401, json={"statusCode": 401})
            return httpx.Response(200, json=_envelope({"JWSToken": "a.jws.token"}))

        if path.endswith("/Auth/GetTax990Token"):
            if not self.token_ok:
                return httpx.Response(
                    401,
                    json={"statusCode": 401, "response": {
                        "Errors": {"ErrorCode": "401-ERR-03",
                                   "ErrorMessage": "Invalid JWS"}}},
                )
            return httpx.Response(200, json=_envelope({"AccessToken": "bearer.token"}))

        if path.endswith("/v1/form990n/create"):
            return httpx.Response(200, json=self.create_body or _success_create())

        if path.endswith("/v1/form990n/list"):
            return httpx.Response(200, json=self.list_body or _success_create())

        if path.endswith("/v1/form990n/validate"):
            return httpx.Response(
                200, json={"StatusCode": 200, "Errors": self.validation_errors}
            )

        if path.endswith("/v1/form990n/getPDF"):
            return httpx.Response(200, json={
                "Form990NRecords": [{"RecordId": "REC-1", "PDFUrl": self.pdf_url}]
            })

        return httpx.Response(200, content=b"%PDF-1.4 fake")


def _success_create(return_number="4B002372685573-1"):
    return {
        "StatusCode": 200,
        "SubmissionId": "SUB-1",
        "Errors": None,
        "Form990NRecords": {
            "SuccessRecords": [
                {"RecordId": "REC-1", "ReturnNumber": return_number,
                 "RecordStatus": "Created"}
            ],
            "ErrorRecords": None,
        },
    }


def _already_exists():
    return {
        "StatusCode": 400,
        "SubmissionId": "SUB-1",
        "Errors": [{
            "Classification": "business",
            "Code": "F990N037",
            "Message": "A return already exists for the organization.",
        }],
        "Form990NRecords": None,
    }


@pytest.fixture
def patched_transport(monkeypatch):
    def install(sandbox: _Sandbox):
        transport = httpx.MockTransport(sandbox.handler)
        original = httpx.Client.__init__

        def patched(self, *args, **kwargs):
            kwargs["transport"] = transport
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "__init__", patched)
        return sandbox

    return install


# --- credentials ----------------------------------------------------------

def test_missing_credentials_are_refused_before_any_request():
    with pytest.raises(Tax990AuthError) as exc:
        Tax990Client("id", "", "token")
    assert "different values" in str(exc.value)


def test_sandbox_is_the_default():
    client = Tax990Client(**CREDENTIALS)
    assert client.is_sandbox is True
    assert client.api_host == SANDBOX_API_HOST
    assert client.oauth_host == SANDBOX_OAUTH_HOST


def test_production_must_be_asked_for_explicitly():
    """A misconfigured environment variable should not be able to file a
    live return."""
    client = Tax990Client(
        **CREDENTIALS,
        oauth_host="https://oauth.tax990.com",
        api_host="https://api.tax990.com",
    )
    assert client.is_sandbox is False


# --- authentication -------------------------------------------------------

def test_bad_client_credentials_are_named(patched_transport):
    patched_transport(_Sandbox(auth_ok=False))
    with pytest.raises(Tax990AuthError) as exc:
        Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert "client ID and secret" in str(exc.value)


def test_bad_user_token_is_named(patched_transport):
    """The commonest setup error is pasting the client secret into the user
    token field, so the message points at it."""
    patched_transport(_Sandbox(token_ok=False))
    with pytest.raises(Tax990AuthError) as exc:
        Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert "user token" in str(exc.value)


def test_the_envelope_is_unwrapped(patched_transport):
    """Tax990 wraps every payload in a response object; the token is one
    level deeper than it appears."""
    sandbox = patched_transport(_Sandbox())
    result = Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert result["submission_id"] == "SUB-1"
    assert "/Auth/GenerateJWS" in sandbox.calls[0]
    assert "/Auth/GetTax990Token" in sandbox.calls[1]


# --- the submission lifecycle ---------------------------------------------

def test_full_round_trip(patched_transport):
    sandbox = patched_transport(_Sandbox())
    result = Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)

    assert result["record_id"] == "REC-1"
    assert result["return_number"] == "4B002372685573-1"
    assert result["already_existed"] is False
    assert result["validation_errors"] == []
    assert result["pdf_url"] == "https://example/form.pdf"
    assert result["is_sandbox"] is True

    assert [c.rsplit("/", 1)[-1] for c in sandbox.calls] == [
        "GenerateJWS", "GetTax990Token", "create", "validate", "getPDF",
    ]


def test_an_existing_return_is_retrieved_not_treated_as_failure(patched_transport):
    """Tax990 refuses a second 990-N for the same EIN and year. That is
    correct, so the existing draft is fetched instead."""
    sandbox = patched_transport(_Sandbox(create_body=_already_exists()))
    result = Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)

    assert result["already_existed"] is True
    assert result["record_id"] == "REC-1"
    assert result["pdf_url"]
    assert "list" in [c.rsplit("/", 1)[-1] for c in sandbox.calls]


def test_other_validation_errors_are_raised(patched_transport):
    patched_transport(_Sandbox(create_body={
        "StatusCode": 400,
        "SubmissionId": "SUB-1",
        "Errors": [{"Code": "F990N012", "Message": "EIN is not valid."}],
    }))
    with pytest.raises(Tax990ValidationError) as exc:
        Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert exc.value.errors[0]["Code"] == "F990N012"


def test_field_level_validation_is_carried_through(patched_transport):
    """Tax990's validation names the element at fault, which is the most
    useful thing it produces."""
    patched_transport(_Sandbox(validation_errors=[
        {"Code": "F990N021", "Message": "Phone must be ten digits.",
         "Name": "Business.Phone"}
    ]))
    result = Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert result["validation_errors"][0]["Name"] == "Business.Phone"


def test_no_record_returned_is_an_error(patched_transport):
    patched_transport(_Sandbox(create_body={
        "StatusCode": 200, "SubmissionId": "SUB-1", "Errors": None,
        "Form990NRecords": {"SuccessRecords": []},
    }))
    with pytest.raises(Tax990Error) as exc:
        Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert "no record" in str(exc.value)


def test_missing_pdf_link_is_tolerated(patched_transport):
    """A draft without a rendered form is still a draft."""
    patched_transport(_Sandbox(pdf_url=None))
    result = Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert result["record_id"] == "REC-1"
    assert result["pdf_url"] is None


def test_idempotency_key_is_sent_on_create(patched_transport):
    """A retried submission must not create a second draft."""
    seen = {}

    class _Recording(_Sandbox):
        def handler(self, request):
            if request.url.path.endswith("/create"):
                seen["idempotency-key"] = request.headers.get("idempotency-key")
                seen["x-correlation-id"] = request.headers.get("x-correlation-id")
            return super().handler(request)

    patched_transport(_Recording())
    Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD, correlation_id="fixed-id")
    assert seen["idempotency-key"] == "fixed-id"
    assert seen["x-correlation-id"] == "fixed-id"


def test_pdf_download(patched_transport):
    patched_transport(_Sandbox())
    client = Tax990Client(**CREDENTIALS)
    content = client.download_pdf("https://example/form.pdf")
    assert content.startswith(b"%PDF")


# --- errors nested per record ---------------------------------------------

def test_record_level_errors_are_surfaced(patched_transport):
    """Tax990 puts request-level problems in `Errors` and return-level ones in
    ErrorRecords[].Errors[], leaving the top-level null. Reading only the
    first missed the message that names the field at fault -- an unsupported
    tax year surfaced as a bare 502 rather than "TaxYr is not supported"."""
    patched_transport(_Sandbox(create_body={
        "StatusCode": 400,
        "StatusNm": "Bad Request",
        "SubmissionId": None,
        "Errors": None,
        "Form990NRecords": {
            "SuccessRecords": None,
            "ErrorRecords": [{
                "SequenceId": "1",
                "RecordStatus": "Failed",
                "Errors": [{
                    "Classification": "validation",
                    "Code": "F990N002",
                    "Message": "TaxYr is not supported",
                    "Field": "Form990NRecords[0].Form990N.TaxYr",
                }],
            }],
        },
    }))
    with pytest.raises(Tax990ValidationError) as exc:
        Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)

    assert "TaxYr is not supported" in str(exc.value)
    assert exc.value.errors[0]["Code"] == "F990N002"
    assert exc.value.errors[0]["SequenceId"] == "1"


def test_the_failing_field_is_named(patched_transport):
    patched_transport(_Sandbox(create_body={
        "StatusCode": 400, "SubmissionId": None, "Errors": None,
        "Form990NRecords": {"ErrorRecords": [{
            "SequenceId": "1",
            "Errors": [{"Code": "F990N021", "Message": "Phone must be ten digits.",
                        "Field": "Form990NRecords[0].Business.Phone"}],
        }]},
    }))
    with pytest.raises(Tax990ValidationError) as exc:
        Tax990Client(**CREDENTIALS).submit_990n(PAYLOAD)
    assert "Business.Phone" in str(exc.value)

#!/usr/bin/env python
"""Produce a Form 990-N and retrieve it from Tax990 as a PDF.

Runs the full round trip against Tax990's sandbox:

    POST /Auth/GenerateJWS       -> JWS
    GET  /Auth/GetTax990Token    -> access token
    POST /v1/form990n/create     -> draft return
    GET  /v1/form990n/list       -> resolve an existing draft, if any
    GET  /v1/form990n/validate   -> Tax990's own validation
    GET  /v1/form990n/getPDF     -> link to the rendered form
    (download, then open)

Tax990 refuses a second 990-N for the same EIN and tax year, so a re-run of
`create` returns a validation error rather than a new draft. That is correct
behaviour, and this script treats it as such: when a return already exists it
looks the draft up and continues, so the run always ends with the form on
screen whether or not it was created just now.

Nothing here touches production. Both hosts are hardcoded to the sandbox so
a mistyped environment variable cannot reach a live filing.

Usage:

    python scripts/tax990_sandbox_test.py                 # build only, no network
    python scripts/tax990_sandbox_test.py --submit        # full round trip
    python scripts/tax990_sandbox_test.py --submit --tax-year 2024
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.form_990n import build_form_990n_payload  # noqa: E402
from app.utils.form_routing import route_form_variant  # noqa: E402

OAUTH_HOST = "https://oauth-sandbox.tax990.com"
API_HOST = "https://api-sandbox.tax990.com"

SECRET_KEYS = {"accesstoken", "jwstoken", "clientsecretid", "usertoken", "clientid"}

# Tax990's code for "this organization already has a return for this year".
ALREADY_EXISTS = "F990N037"


SAMPLE_CONTENT = {
    "organizationInformation": {
        "legalName": "Kansas City Woodworkers Guild",
        "dbaNames": [],
        "ein": "43-1633425",
        "address": {
            "street": "3189 Mercier St",
            "city": "Kansas City",
            "state": "MO",
            "zip": "64111",
        },
        "telephone": "8167610075",
        "website": "https://kcwg.org",
        "principalOfficer": {"name": "Jane Doe", "title": "President"},
    },
    "organization_summary": {"tax_year": "2025", "gross_receipts": 10605.77},
}


def _redact(value):
    """Strip credentials from anything printed."""
    if isinstance(value, dict):
        return {
            k: "[redacted]" if k.lower() in SECRET_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _step(label: str) -> None:
    print(f"\n  {label}")


# --- authentication -------------------------------------------------------

def get_access_token(client: httpx.Client, client_id, secret_id, user_token) -> str:
    jws_response = client.post(
        f"{OAUTH_HOST}/Auth/GenerateJWS",
        json={
            "ClientId": client_id,
            "ClientSecretId": secret_id,
            "UserToken": user_token,
        },
        headers={"Accept": "application/json"},
    )
    print(f"    GenerateJWS       {jws_response.status_code}")
    jws_response.raise_for_status()
    jws = jws_response.json()["response"]["JWSToken"]

    token_response = client.get(
        f"{OAUTH_HOST}/Auth/GetTax990Token",
        headers={"authentication": jws, "Accept": "application/json"},
    )
    print(f"    GetTax990Token    {token_response.status_code}")
    if token_response.status_code != 200:
        print("    ", token_response.text[:400])
    token_response.raise_for_status()
    return token_response.json()["response"]["AccessToken"]


def _headers(token: str, request_id: str, *, idempotent: bool = False) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "x-correlation-id": request_id,
    }
    if idempotent:
        headers["idempotency-key"] = request_id
    return headers


# --- the round trip -------------------------------------------------------

def create_draft(client, token, payload, request_id) -> dict:
    response = client.post(
        f"{API_HOST}/v1/form990n/create",
        json=payload,
        headers=_headers(token, request_id, idempotent=True),
    )
    print(f"    create            {response.status_code}")
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def already_exists(response: dict) -> bool:
    for error in response.get("Errors") or []:
        if isinstance(error, dict) and error.get("Code") == ALREADY_EXISTS:
            return True
    return False


def find_existing(client, token, submission_id, request_id) -> dict:
    """Look up a draft Tax990 already holds, when create was refused."""
    response = client.get(
        f"{API_HOST}/v1/form990n/list",
        params={"SubmissionId": submission_id},
        headers=_headers(token, request_id),
    )
    print(f"    list              {response.status_code}")
    try:
        return response.json()
    except ValueError:
        return {}


def validate_draft(client, token, submission_id, record_id, request_id) -> dict:
    response = client.get(
        f"{API_HOST}/v1/form990n/validate",
        params={"SubmissionId": submission_id, "RecordIds": record_id},
        headers=_headers(token, request_id),
    )
    print(f"    validate          {response.status_code}")
    try:
        return response.json()
    except ValueError:
        return {}


def get_pdf_url(client, token, submission_id, record_id, request_id) -> str | None:
    response = client.get(
        f"{API_HOST}/v1/form990n/getPDF",
        params={"SubmissionId": submission_id, "RecordIds": record_id},
        headers=_headers(token, request_id),
    )
    print(f"    getPDF            {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        return None
    for record in body.get("Form990NRecords") or []:
        if isinstance(record, dict) and record.get("PDFUrl"):
            return record["PDFUrl"]
    return None


def download_and_open(client, url: str, destination: Path) -> bool:
    response = client.get(url)
    if response.status_code != 200:
        print(f"    download          {response.status_code}")
        return False
    destination.write_bytes(response.content)
    size = len(response.content) / 1024
    print(f"    download          200  ({size:,.0f} KB)")
    print(f"\n  Saved to {destination}")
    if sys.platform == "darwin":
        subprocess.run(["open", str(destination)], check=False)
    return True


# --- helpers --------------------------------------------------------------

def _first_record(response: dict) -> tuple[str | None, str | None]:
    """Return (submission_id, record_id) from a create or list response."""
    submission_id = response.get("SubmissionId")
    records = response.get("Form990NRecords") or {}
    if isinstance(records, dict):
        successes = records.get("SuccessRecords") or []
    else:
        successes = records
    for record in successes:
        if isinstance(record, dict) and record.get("RecordId"):
            return submission_id, record["RecordId"]
    return submission_id, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true",
                        help="call the sandbox. Without this the payload is printed only.")
    parser.add_argument("--content",
                        help="path to a reports_response.json; uses its tax_return content")
    parser.add_argument("--tax-year",
                        help="override the tax year, e.g. 2024, to create a fresh return")
    parser.add_argument("--out", default="form_990n_draft.pdf",
                        help="where to save the retrieved PDF")
    args = parser.parse_args()

    content = SAMPLE_CONTENT
    if args.content:
        with open(args.content) as handle:
            document = json.load(handle)
        content = document["reports"]["tax_return"]["content"]
        print(f"Using content from {args.content}")

    if args.tax_year:
        content = json.loads(json.dumps(content))
        content.setdefault("organization_summary", {})["tax_year"] = args.tax_year

    summary = content.get("organization_summary") or {}
    total_assets = (
        ((content.get("partX_balanceSheet") or {}).get("totalAssets") or {}).get("endOfYear")
    )

    routing = route_form_variant(summary.get("gross_receipts"), total_assets)
    print(f"\nRouted to Form {routing.form}   (basis: {routing.basis})")

    result = build_form_990n_payload(content, routing, allow_placeholder_phone=True)
    for error in result.blocking_errors:
        print(f"  BLOCKED  {error}")
    if not result.is_submittable:
        print("\nNo payload produced.")
        return 1

    record = result.payload["Form990NRecords"][0]
    print(f"  {record['Business']['BusinessNm']}  ·  EIN {record['Business']['EIN']}"
          f"  ·  tax year {record['Form990N']['TaxYr']}")

    if not args.submit:
        print("\nPayload:")
        print(json.dumps(result.payload, indent=2))
        print("\nDry run. Pass --submit to send this to the sandbox.")
        return 0

    client_id = os.environ.get("TAX990_CLIENT_ID")
    secret_id = os.environ.get("TAX990_CLIENT_SECRET_ID")
    user_token = os.environ.get("TAX990_USER_TOKEN")
    if not all((client_id, secret_id, user_token)):
        print("\nSet TAX990_CLIENT_ID, TAX990_CLIENT_SECRET_ID and TAX990_USER_TOKEN in .env")
        return 1

    request_id = str(uuid.uuid4())

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        _step("Authenticating with Tax990")
        token = get_access_token(client, client_id, secret_id, user_token)

        _step("Submitting the return")
        response = create_draft(client, token, result.payload, request_id)
        submission_id, record_id = _first_record(response)

        if already_exists(response):
            print("    Tax990 already holds a return for this organization and year.")
            print("    Retrieving the existing draft instead.")
            listed = find_existing(client, token, submission_id, request_id)
            listed_submission, listed_record = _first_record(listed)
            submission_id = listed_submission or submission_id
            record_id = listed_record or record_id
        elif record_id:
            print(f"    Accepted.  Return number "
                  f"{(response.get('Form990NRecords') or {}).get('SuccessRecords', [{}])[0].get('ReturnNumber', '')}")

        if not (submission_id and record_id):
            print("\n  Could not resolve a return to retrieve.")
            print(json.dumps(_redact(response), indent=2)[:1500])
            return 1

        _step("Validating with Tax990")
        validation = validate_draft(client, token, submission_id, record_id, request_id)
        errors = validation.get("Errors")
        print(f"    Errors: {errors if errors else 'none'}")

        _step("Retrieving the completed form")
        url = get_pdf_url(client, token, submission_id, record_id, request_id)
        if not url:
            print("    No PDF link returned.")
            return 1

        destination = Path(args.out).resolve()
        if not download_and_open(client, url, destination):
            return 1

    print("\n  Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

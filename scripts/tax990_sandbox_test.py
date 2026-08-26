#!/usr/bin/env python
"""Submit a Form 990-N draft to the Tax990 sandbox.

Runs the three-call handshake observed in the Make.com scenario:

    POST oauth-sandbox.tax990.com/Auth/GenerateJWS   -> JWSToken
    GET  oauth-sandbox.tax990.com/Auth/GetTax990Token -> AccessToken
    POST api-sandbox.tax990.com/v1/form990n/create    -> draft

Nothing here touches production. The sandbox host is hardcoded so a
misconfigured environment variable cannot send a live filing.

Usage:

    export TAX990_CLIENT_ID=...
    export TAX990_CLIENT_SECRET_ID=...
    export TAX990_USER_TOKEN=...

    python scripts/tax990_sandbox_test.py            # build and validate only
    python scripts/tax990_sandbox_test.py --submit   # actually create a draft
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.form_990n import build_form_990n_payload  # noqa: E402
from app.utils.form_routing import route_form_variant  # noqa: E402

from dotenv import load_dotenv
load_dotenv()



OAUTH_HOST = "https://oauth-sandbox.tax990.com"
API_HOST = "https://api-sandbox.tax990.com"


# A known-eligible organisation. Replace with real content from a pipeline
# run once the payload shape is confirmed.
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

SECRET_KEYS = {"accesstoken", "jwstoken", "clientsecretid", "usertoken", "clientid"}


def _redact(value):
    """Strip credentials from anything printed or logged."""
    if isinstance(value, dict):
        return {
            k: "[redacted]" if k.lower() in SECRET_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value

def get_access_token(client_id: str, secret_id: str, user_token: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        jws_response = client.post(
            f"{OAUTH_HOST}/Auth/GenerateJWS",
            json={
                "ClientId": client_id,
                "ClientSecretId": secret_id,
                "UserToken": user_token,
            },
            headers={"Accept": "application/json"},
        )
        print(f"  GenerateJWS      -> {jws_response.status_code}")
        jws_response.raise_for_status()
       
        jws = jws_response.json()["response"]["JWSToken"]

        token_response = client.get(
            f"{OAUTH_HOST}/Auth/GetTax990Token",
            headers={"authentication": jws, "Accept": "application/json"},
        )
        print(f"  GetTax990Token   -> {token_response.status_code}")
        if token_response.status_code != 200:
            print("  raw:", token_response.text[:800])
        token_response.raise_for_status()
        return token_response.json()["response"]["AccessToken"]

def create_draft(access_token: str, payload: dict) -> dict:
    request_id = str(uuid.uuid4())
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{API_HOST}/v1/form990n/create",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "idempotency-key": request_id,
                "x-correlation-id": request_id,
            },
        )
        print(f"  form990n/create  -> {response.status_code}")
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually call the sandbox. Without this the payload is built and printed only.",
    )
    parser.add_argument(
        "--content",
        help="Path to a reports_response.json; uses its tax_return content instead of the sample.",
    )
    args = parser.parse_args()

    content = SAMPLE_CONTENT
    if args.content:
        with open(args.content) as handle:
            document = json.load(handle)
        content = document["reports"]["tax_return"]["content"]
        print(f"Using content from {args.content}")

    summary = content.get("organization_summary") or {}
    gross_receipts = summary.get("gross_receipts")
    total_assets = (
        ((content.get("partX_balanceSheet") or {}).get("totalAssets") or {}).get("endOfYear")
    )

    routing = route_form_variant(gross_receipts, total_assets)
    print(f"\nRouting: {routing.form}  (basis: {routing.basis})")
    for reason in routing.review_reasons:
        print(f"  review: {reason}")

    result = build_form_990n_payload(content, routing, allow_placeholder_phone=True)

    for warning in result.warnings:
        print(f"  warn:   {warning}")
    for error in result.blocking_errors:
        print(f"  BLOCK:  {error}")

    if not result.is_submittable:
        print("\nNo payload produced. Nothing to submit.")
        return 1

    print("\nPayload:")
    print(json.dumps(result.payload, indent=2))

    if not args.submit:
        print("\nDry run. Pass --submit to send this to the sandbox.")
        return 0

    client_id = os.environ.get("TAX990_CLIENT_ID")
    secret_id = os.environ.get("TAX990_CLIENT_SECRET_ID")
    user_token = os.environ.get("TAX990_USER_TOKEN")
    if not all((client_id, secret_id, user_token)):
        print(
            "\nSet TAX990_CLIENT_ID, TAX990_CLIENT_SECRET_ID and TAX990_USER_TOKEN "
            "before submitting."
        )
        return 1

    print("\nAuthenticating:")
    token = get_access_token(client_id, secret_id, user_token)

    print("\nCreating draft:")
    response = create_draft(token, result.payload)
    print(json.dumps(_redact(response), indent=2)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Which tax years does the Tax990 sandbox accept for a Form 990-N?

Tax990 rejected a 2026 return with "TaxYr is not supported", which is worth
knowing precisely: it determines what the application can offer a preparer,
and it is not something their documentation states.

Sends a minimal, well-formed 990-N for each year and reports what comes back.
The organization details are the sandbox test values used elsewhere.

   * python scripts/tax990_year_probe.py
"""

from __future__ import annotations

import os
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

OAUTH = "https://oauth-sandbox.tax990.com"
API = "https://api-sandbox.tax990.com"

YEARS = (2022, 2023, 2024, 2025, 2026)


def token(client: httpx.Client) -> str:
    jws = client.post(
        f"{OAUTH}/Auth/GenerateJWS",
        json={
            "ClientId": os.environ["TAX990_CLIENT_ID"],
            "ClientSecretId": os.environ["TAX990_CLIENT_SECRET_ID"],
            "UserToken": os.environ["TAX990_USER_TOKEN"],
        },
    ).json()["response"]["JWSToken"]
    return client.get(
        f"{OAUTH}/Auth/GetTax990Token", headers={"authentication": jws}
    ).json()["response"]["AccessToken"]


def payload(year: int) -> dict:
    address = {
        "Address1": "3189 Mercier St",
        "City": "Kansas City",
        "State": "MO",
        "ZipCd": "64111",
    }
    return {
        "Form990NRecords": [
            {
                "Business": {
                    "BusinessNm": "Kansas City Woodworkers Guild",
                    "EIN": "431633425",
                    "Phone": "8167610075",
                    "IsForeign": False,
                    "USAddress": address,
                },
                "Form990N": {
                    "SequenceId": "1",
                    "TaxYr": str(year),
                    "TaxPeriodBeginDt": f"{year}-01-01",
                    "TaxPeriodEndDt": f"{year}-12-31",
                    "IsGrossReceiptsUnder50K": True,
                    "IsOrganizationTerminated": False,
                    "PrincipalOfficer": {
                        "OfficerNm": "Jane Doe",
                        "IsForeign": False,
                        "USAddress": address,
                    },
                },
            }
        ]
    }


def messages(body: dict) -> list[str]:
    """Errors live in two places: per request, and per record."""
    found = [
        e.get("Message") for e in (body.get("Errors") or []) if isinstance(e, dict)
    ]
    records = body.get("Form990NRecords") or {}
    if isinstance(records, dict):
        for record in records.get("ErrorRecords") or []:
            for error in record.get("Errors") or []:
                found.append(f"{error.get('Code')}: {error.get('Message')}")
    return found


def main() -> int:
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        access = token(client)
        print("Authenticated.\n")

        for year in YEARS:
            request_id = str(uuid.uuid4())
            response = client.post(
                f"{API}/v1/form990n/create",
                json=payload(year),
                headers={
                    "Authorization": f"Bearer {access}",
                    "Accept": "application/json",
                    "idempotency-key": request_id,
                    "x-correlation-id": request_id,
                },
            )
            body = response.json() if response.content else {}
            problems = messages(body)
            status = body.get("StatusCode", response.status_code)

            if not problems:
                records = (body.get("Form990NRecords") or {}).get("SuccessRecords") or []
                number = records[0].get("ReturnNumber") if records else ""
                print(f"  {year}   {status}   accepted   {number}")
            else:
                for problem in problems:
                    print(f"  {year}   {status}   {problem}")

    print(
        "\n'A return already exists' means the year is supported and you have "
        "filed it before."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

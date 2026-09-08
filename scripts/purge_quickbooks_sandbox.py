#!/usr/bin/env python
"""Empty a QuickBooks sandbox company through the API.

Intuit seeds every sandbox with a fictional business. The web purge page
(app/purgecompany) refuses companies older than 60 days, so this does the
same job through the ordinary endpoints: delete every transaction, then mark
the seeded customers, vendors, employees, items and accounts inactive.
Accounts and list entries cannot be deleted through the API, only deactivated.

    python scripts/purge_quickbooks_sandbox.py --dry-run
    python scripts/purge_quickbooks_sandbox.py --confirm <realm id>
    python scripts/purge_quickbooks_sandbox.py --confirm <realm id> --keep-lists

Credentials come from .env, the same ones the loader uses. The realm must be a
sandbox, must match --confirm exactly, and must not be the Humber landscaping
company. Every deletion is recorded in the company's Audit log.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
MINOR_VERSION = "75"

# The Intuit sample company the tests and fixtures depend on. Never purged.
PROTECTED_REALMS = {"9341457668846945"}

# Transactions, in an order that respects links between them: a deposit can
# hold payments, a payment applies to an invoice, a bill payment to a bill.
# Deleting the dependant first avoids "linked transaction" refusals.
TRANSACTIONS = [
    "Deposit",
    "Payment",
    "BillPayment",
    "RefundReceipt",
    "CreditMemo",
    "VendorCredit",
    "SalesReceipt",
    "Invoice",
    "Bill",
    "Purchase",
    "PurchaseOrder",
    "Estimate",
    "Transfer",
    "JournalEntry",
    "TimeActivity",
]

# Lists. These are set Active=false rather than deleted.
LISTS = ["Customer", "Vendor", "Employee", "Item", "Account"]


class Purger:
    def __init__(self, realm_id: str, token: str, *, dry_run: bool = False) -> None:
        self.realm = realm_id
        self.token = token
        self.dry_run = dry_run
        self.base = f"{SANDBOX_BASE}/v3/company/{realm_id}"
        self.deleted = 0
        self.deactivated = 0
        self.refused: list[str] = []

    # --- plumbing ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(3):
            response = client.request(method, url, headers=self._headers(), **kwargs)
            if response.status_code == 429:
                print("    rate limited; waiting 62 seconds")
                time.sleep(62)
                continue
            return response
        return response

    def _query(self, client: httpx.Client, entity: str) -> list[dict]:
        """Every row of an entity, paged. Returns Id and SyncToken."""
        rows: list[dict] = []
        start = 1
        while True:
            statement = (
                f"SELECT Id, SyncToken FROM {entity} "
                f"STARTPOSITION {start} MAXRESULTS 1000"
            )
            response = self._request(
                client, "GET", f"{self.base}/query",
                params={"query": statement, "minorversion": MINOR_VERSION},
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"query {entity} failed ({response.status_code}): {response.text[:400]}"
                )
            page = (response.json().get("QueryResponse") or {}).get(entity) or []
            rows.extend(page)
            if len(page) < 1000:
                return rows
            start += 1000

    # --- transactions --------------------------------------------------

    def delete_all(self, client: httpx.Client, entity: str) -> None:
        rows = self._query(client, entity)
        if not rows:
            print(f"    {entity:<14} none")
            return
        if self.dry_run:
            print(f"    {entity:<14} would delete {len(rows)}")
            return

        ok = 0
        for row in rows:
            response = self._request(
                client, "POST", f"{self.base}/{entity.lower()}",
                params={"operation": "delete", "minorversion": MINOR_VERSION},
                json={"Id": row["Id"], "SyncToken": row["SyncToken"]},
            )
            if response.status_code >= 400:
                self.refused.append(f"{entity} {row['Id']}: {response.text[:160]}")
                continue
            ok += 1
        self.deleted += ok
        print(f"    {entity:<14} deleted {ok} of {len(rows)}")

    # --- lists ---------------------------------------------------------

    def deactivate_all(self, client: httpx.Client, entity: str) -> None:
        rows = self._query(client, entity)   # active rows only, by default
        if not rows:
            print(f"    {entity:<14} none active")
            return
        if self.dry_run:
            print(f"    {entity:<14} would deactivate {len(rows)}")
            return

        ok = 0
        for row in rows:
            response = self._request(
                client, "POST", f"{self.base}/{entity.lower()}",
                params={"minorversion": MINOR_VERSION},
                json={
                    "Id": row["Id"],
                    "SyncToken": row["SyncToken"],
                    "Active": False,
                    "sparse": True,
                },
            )
            if response.status_code >= 400:
                # System accounts (Opening Balance Equity, Retained Earnings,
                # Undeposited Funds, A/R, A/P) refuse. That is expected.
                self.refused.append(f"{entity} {row['Id']}: {response.text[:160]}")
                continue
            ok += 1
        self.deactivated += ok
        print(f"    {entity:<14} deactivated {ok} of {len(rows)}")


# --- authentication ----------------------------------------------------

def access_token(client: httpx.Client) -> str:
    """Exchange the refresh token, the same way the loader does."""
    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID", "")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET", "")
    refresh = os.environ.get("QUICKBOOKS_REFRESH_TOKEN", "")
    if not all((client_id, client_secret, refresh)):
        raise SystemExit(
            "Set QUICKBOOKS_CLIENT_ID, QUICKBOOKS_CLIENT_SECRET and "
            "QUICKBOOKS_REFRESH_TOKEN in .env"
        )

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = client.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        headers={
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if response.status_code != 200:
        raise SystemExit(
            f"QuickBooks refused the refresh token ({response.status_code}). "
            f"Refresh tokens rotate on each use; get a fresh one from the "
            f"Intuit OAuth playground.\n{response.text[:300]}"
        )
    body = response.json()
    print("  authenticated")
    if body.get("refresh_token") and body["refresh_token"] != refresh:
        print("  note: QuickBooks issued a new refresh token; update .env if "
              "the pipeline stops working")
    return body["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--realm", help="overrides QUICKBOOKS_REALM_ID")
    parser.add_argument("--confirm", metavar="REALM_ID",
                        help="required to write: must equal the realm being purged")
    parser.add_argument("--dry-run", action="store_true",
                        help="count what would be removed without changing anything")
    parser.add_argument("--keep-lists", action="store_true",
                        help="delete transactions only; leave customers, vendors, "
                             "items and accounts active")
    args = parser.parse_args()

    realm = args.realm or os.environ.get("QUICKBOOKS_REALM_ID", "")
    if not realm:
        raise SystemExit("Set QUICKBOOKS_REALM_ID in .env, or pass --realm")
    if realm in PROTECTED_REALMS:
        raise SystemExit(f"Realm {realm} is the Intuit sample company. Refusing.")
    if not args.dry_run and args.confirm != realm:
        raise SystemExit(
            f"Pass --confirm {realm} to purge this company, or --dry-run to count."
        )

    print(f"\n  realm {realm}   {'(dry run)' if args.dry_run else '(WRITING)'}\n")

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        token = access_token(client)
        purger = Purger(realm, token, dry_run=args.dry_run)

        print("\n  Transactions")
        for entity in TRANSACTIONS:
            purger.delete_all(client, entity)

        if args.keep_lists:
            print("\n  Lists left active (--keep-lists).")
        else:
            print("\n  Lists")
            for entity in LISTS:
                purger.deactivate_all(client, entity)

        if not args.dry_run:
            print("\n  Remaining transactions")
            for entity in TRANSACTIONS:
                left = purger._query(client, entity)
                if left:
                    print(f"    {entity:<14} {len(left)} still present")

    print(f"\n  {purger.deleted} transactions deleted, "
          f"{purger.deactivated} list entries deactivated")
    if purger.refused:
        print(f"  {len(purger.refused)} refused:")
        for line in purger.refused:
            print(f"    {line}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

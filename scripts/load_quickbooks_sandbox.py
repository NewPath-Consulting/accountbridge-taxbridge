#!/usr/bin/env python
"""Load a synthetic organization into a QuickBooks sandbox company.

QuickBooks has no operation for "set total revenue to $190,081". Reports are
derived, not stored: you create accounts, post transactions, and QuickBooks
computes the profit and loss from them. So this creates a chart of accounts
and posts one journal entry per year, and the pipeline then reads the result
back through the ordinary endpoints with no special handling.

Journal entries are used rather than invoices because one entry can carry
every account for a year, so six years costs six calls rather than hundreds.
Debits must equal credits, and every account must exist first.

    python scripts/load_quickbooks_sandbox.py --dry-run
    python scripts/load_quickbooks_sandbox.py --accounts-only
    python scripts/load_quickbooks_sandbox.py

Credentials come from .env, the same ones the pipeline uses. The realm must be
a sandbox: the script refuses to write to a production company.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
MINOR_VERSION = "75"

DEFAULT_DEFINITION = ROOT / "data" / "crn_synthetic.json"

# QuickBooks account types. Income and expense accounts drive the profit and
# loss; bank accounts give the journal entries somewhere to balance to and
# populate the balance sheet.
ACCOUNT_TYPES = {
    "income": ("Income", "SalesOfProductIncome"),
    "expense": ("Expense", "OtherMiscellaneousServiceCost"),
    "bank": ("Bank", "Checking"),
}


class Loader:
    def __init__(self, realm_id: str, token: str, *, dry_run: bool = False) -> None:
        self.realm = realm_id
        self.token = token
        self.dry_run = dry_run
        self.base = f"{SANDBOX_BASE}/v3/company/{realm_id}"
        self._accounts: dict[str, str] = {}   # name -> Id
        self.created = 0
        self.reused = 0

    # --- plumbing ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _post(self, client: httpx.Client, entity: str, body: dict) -> dict:
        response = client.post(
            f"{self.base}/{entity}",
            params={"minorversion": MINOR_VERSION},
            json=body,
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"{entity} failed ({response.status_code}): {response.text[:400]}"
            )
        return response.json()

    def _query(self, client: httpx.Client, statement: str) -> dict:
        response = client.get(
            f"{self.base}/query",
            params={"query": statement, "minorversion": MINOR_VERSION},
            headers={**self._headers(), "Content-Type": "application/text"},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"query failed ({response.status_code}): {response.text[:400]}"
            )
        return response.json()

    # --- accounts ------------------------------------------------------

    def load_existing_accounts(self, client: httpx.Client) -> None:
        data = self._query(client, "SELECT Id, Name FROM Account MAXRESULTS 1000")
        for account in (data.get("QueryResponse") or {}).get("Account") or []:
            self._accounts[account["Name"]] = account["Id"]
        print(f"  {len(self._accounts)} accounts already in this company")

    def ensure_account(self, client: httpx.Client, name: str, kind: str) -> str:
        if name in self._accounts:
            self.reused += 1
            return self._accounts[name]

        account_type, account_subtype = ACCOUNT_TYPES[kind]
        if self.dry_run:
            print(f"    would create  {account_type:<8} {name}")
            self._accounts[name] = f"dry-{len(self._accounts)}"
            self.created += 1
            return self._accounts[name]

        body = {
            "Name": name,
            "AccountType": account_type,
            "AccountSubType": account_subtype,
        }
        created = self._post(client, "account", body)
        account_id = created["Account"]["Id"]
        self._accounts[name] = account_id
        self.created += 1
        print(f"    created  {account_type:<8} {name}  (id {account_id})")
        return account_id

    # --- journal entries -----------------------------------------------

    def post_year(self, client: httpx.Client, year: dict) -> None:
        """One entry per year, dated the last day of the year.

        Revenue is credited to income accounts and debited to the bank, so
        the bank balance carries the year's activity onto the balance sheet.
        Expenses are the mirror.
        """
        y = year["year"]
        date = f"{y}-12-31"
        lines: list[dict[str, Any]] = []

        revenue_total = round(sum(year["revenue"].values()), 2)
        expense_total = round(sum(year["expenses"].values()), 2)
        bank_name = next(iter(year["assets"]))
        bank_id = self._accounts[bank_name]

        for name, amount in year["revenue"].items():
            lines.append(self._line("Credit", self._accounts[name], name, amount))
        lines.append(self._line("Debit", bank_id, bank_name, revenue_total))

        for name, amount in year["expenses"].items():
            lines.append(self._line("Debit", self._accounts[name], name, amount))
        lines.append(self._line("Credit", bank_id, bank_name, expense_total))

        body = {
            "TxnDate": date,
            "DocNumber": f"CRN-{y}",
            "PrivateNote": (
                f"Synthetic {y} activity, derived from published Form 990 totals "
                f"for EIN 99-0370960. Not real bookkeeping."
            ),
            "Line": lines,
        }

        debits = sum(l["Amount"] for l in lines
                     if l["JournalEntryLineDetail"]["PostingType"] == "Debit")
        credits = sum(l["Amount"] for l in lines
                      if l["JournalEntryLineDetail"]["PostingType"] == "Credit")
        if round(debits - credits, 2) != 0:
            raise RuntimeError(
                f"{y} does not balance: debits {debits:,.2f} vs credits {credits:,.2f}"
            )

        if self.dry_run:
            print(f"    would post  {y}   revenue {revenue_total:>10,.2f}   "
                  f"expenses {expense_total:>10,.2f}   ({len(lines)} lines)")
            return

        created = self._post(client, "journalentry", body)
        entry_id = created["JournalEntry"]["Id"]
        print(f"    posted  {y}   revenue {revenue_total:>10,.2f}   "
              f"expenses {expense_total:>10,.2f}   (id {entry_id})")

    @staticmethod
    def _line(posting: str, account_id: str, account_name: str, amount: float) -> dict:
        return {
            "DetailType": "JournalEntryLineDetail",
            "Amount": round(float(amount), 2),
            "Description": account_name,
            "JournalEntryLineDetail": {
                "PostingType": posting,
                "AccountRef": {"value": account_id, "name": account_name},
            },
        }


# --- authentication ----------------------------------------------------

def access_token(client: httpx.Client) -> str:
    """Exchange the refresh token, the same way the pipeline does."""
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
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--realm", help="overrides QUICKBOOKS_REALM_ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be created without calling QuickBooks")
    parser.add_argument("--accounts-only", action="store_true",
                        help="create the chart of accounts but post nothing")
    args = parser.parse_args()

    if not args.definition.exists():
        raise SystemExit(f"Cannot find {args.definition}")
    definition = json.loads(args.definition.read_text())

    realm = args.realm or os.environ.get("QUICKBOOKS_REALM_ID", "")
    if not realm:
        raise SystemExit("Set QUICKBOOKS_REALM_ID in .env, or pass --realm")

    org = definition["organization"]
    print(f"\n  {org['name']}")
    print(f"  derived from {org['source']}")
    print(f"  realm {realm}   {'(dry run)' if args.dry_run else ''}\n")

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        token = "dry-run" if args.dry_run else access_token(client)
        loader = Loader(realm, token, dry_run=args.dry_run)

        if not args.dry_run:
            loader.load_existing_accounts(client)

        print("\n  Chart of accounts")
        for kind, names in definition["accounts"].items():
            for name in names:
                loader.ensure_account(client, name, kind)
        print(f"  {loader.created} created, {loader.reused} already present")

        if args.accounts_only:
            print("\n  Accounts only. Re-run without --accounts-only to post the years.")
            return 0

        print("\n  Journal entries")
        for year in definition["years"]:
            loader.post_year(client, year)

    print("\n  Done.")
    if not args.dry_run:
        first = definition["years"][0]["year"]
        last = definition["years"][-1]["year"]
        print(f"  Set the pipeline date range to a single year between "
              f"{first} and {last} and run the reports.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

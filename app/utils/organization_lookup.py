"""Look up an organization's identity and filing history from ProPublica.

QuickBooks holds the money and nothing else. It does not know the
organization's legal name, its address, when it was granted exempt status, or
what it reported in prior years -- and three of those change the outcome:

  * the ruling date gives the organization's age, which decides *which*
    990-N threshold applies: $75,000 in the first year, $60,000 up to three,
    $50,000 once established
  * prior-year gross receipts feed the rolling average the IRS "normally"
    test requires
  * the legal name and address go on the return itself

Without the first two, every routing decision comes back flagged: the
strictest threshold applied because the age is unknown, resting on a single
year because there is no history. The decision is still safe, but it is made
with less than the rules allow for.

ProPublica does not publish the principal officer. That remains manual, which
is why the Make.com scenario searches the organization's own website for it.
Everything returned here is a starting point for the preparer to correct, not
an authority.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional

from app.utils.propublica_client import ProPublicaClient
from app.utils.propublica_harness import age_years_at, form_label, gross_receipts

logger = logging.getLogger(__name__)

__all__ = ["OrganizationLookup", "lookup_organization"]

# Filings older than this add little to a threshold decision made today.
MAX_HISTORY_YEARS = 5


class OrganizationLookup:
    """What ProPublica knows, and what it does not."""

    __slots__ = (
        "found", "ein", "legal_name", "address", "ruling_date",
        "age_years", "prior_year_gross_receipts", "filings", "notes",
    )

    def __init__(
        self,
        *,
        found: bool,
        ein: str = "",
        legal_name: str = "",
        address: Optional[dict[str, str]] = None,
        ruling_date: Optional[str] = None,
        age_years: Optional[float] = None,
        prior_year_gross_receipts: Optional[list[float]] = None,
        filings: Optional[list[dict[str, Any]]] = None,
        notes: Optional[list[str]] = None,
    ) -> None:
        self.found = found
        self.ein = ein
        self.legal_name = legal_name
        self.address = address or {}
        self.ruling_date = ruling_date
        self.age_years = age_years
        self.prior_year_gross_receipts = prior_year_gross_receipts or []
        self.filings = filings or []
        self.notes = notes or []

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "ein": self.ein,
            "legal_name": self.legal_name,
            "address": dict(self.address),
            "ruling_date": self.ruling_date,
            "age_years": self.age_years,
            "prior_year_gross_receipts": list(self.prior_year_gross_receipts),
            "filings": list(self.filings),
            "notes": list(self.notes),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"OrganizationLookup(found={self.found!r}, name={self.legal_name!r})"


def _normalise_ein(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def _format_ein(digits: str) -> str:
    return f"{digits[:2]}-{digits[2:]}" if len(digits) == 9 else digits


def lookup_organization(
    ein: str,
    *,
    client: Optional[ProPublicaClient] = None,
    as_of: Optional[date] = None,
) -> OrganizationLookup:
    """Fetch identity, age and filing history for one EIN.

    Never raises on a lookup failure. A miss returns `found=False` with the
    reason in `notes`, so the preparer can enter the details by hand instead.
    """
    digits = _normalise_ein(ein)
    if len(digits) != 9:
        return OrganizationLookup(
            found=False,
            notes=[f"An EIN must be nine digits; got {ein!r}."],
        )

    client = client or ProPublicaClient()
    try:
        payload = client.organization(digits)
    except Exception as exc:  # noqa: BLE001 - a lookup miss must not break the flow
        logger.info("ProPublica lookup failed for %s: %s", digits, exc)
        return OrganizationLookup(
            found=False,
            ein=_format_ein(digits),
            notes=[
                "ProPublica had no record for this EIN, or could not be reached. "
                "Enter the organization's details manually."
            ],
        )

    org = payload.get("organization") or {}
    if not org:
        return OrganizationLookup(
            found=False,
            ein=_format_ein(digits),
            notes=["ProPublica returned no organization for this EIN."],
        )

    notes: list[str] = [
        "Principal officer is not published by ProPublica and must be entered."
    ]

    ruling_date = org.get("ruling_date")
    age = None
    if ruling_date:
        today = as_of or date.today()
        period = int(f"{today.year}{today.month:02d}")
        age = age_years_at(ruling_date, period)
        if age is not None:
            age = round(age, 2)
    else:
        notes.append(
            "No ruling date on file, so the organization's age is unknown and "
            "the strictest 990-N threshold will apply."
        )

    filings: list[dict[str, Any]] = []
    for filing in payload.get("filings_with_data") or []:
        label = form_label(filing.get("formtype"))
        receipts = gross_receipts(filing)
        period = filing.get("tax_prd")
        if label is None or receipts is None or period is None:
            continue
        filings.append({
            "tax_year": filing.get("tax_prd_yr") or str(period)[:4],
            "form_filed": label,
            "gross_receipts": round(float(receipts), 2),
            "total_revenue": filing.get("totrevenue"),
            "total_assets_end": filing.get("totassetsend"),
        })

    filings.sort(key=lambda f: str(f["tax_year"]), reverse=True)
    filings = filings[:MAX_HISTORY_YEARS]

    priors = [f["gross_receipts"] for f in filings]
    if not priors:
        notes.append(
            "No prior filings on record, so the multi-year average cannot be "
            "applied and the decision will rest on this year alone."
        )

    return OrganizationLookup(
        found=True,
        ein=_format_ein(digits),
        legal_name=str(org.get("name") or "").strip(),
        address={
            "street": str(org.get("address") or "").strip(),
            "city": str(org.get("city") or "").strip(),
            "state": str(org.get("state") or "").strip(),
            "zip": str(org.get("zipcode") or "").strip()[:5],
        },
        ruling_date=str(ruling_date) if ruling_date else None,
        age_years=age,
        prior_year_gross_receipts=priors,
        filings=filings,
        notes=notes,
    )

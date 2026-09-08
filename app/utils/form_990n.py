"""Assemble a Form 990-N (e-Postcard) submission payload.

The 990-N is an identity form. It carries no financial detail at all -- name,
EIN, address, principal officer, website, and two declarations. That is why
the Make.com scenario can produce one from public sources without touching an
accounting system.

The eight elements the IRS requires:

    1. Employer Identification Number
    2. Tax year
    3. Legal name and mailing address
    4. Any other names used (DBA)
    5. Name and address of the principal officer
    6. Web address, if any
    7. Confirmation that gross receipts are normally $50,000 or less
    8. Statement of termination, if the organization has gone out of business

Seven are already produced by the report pipeline. This module gathers them
into the shape Tax990's `/v1/form990n/create` endpoint expects, and supplies
the eighth.

Element 7 is the one that matters. The Make.com scenario hardcodes
`IsGrossReceiptsUnder50K: true` on every submission -- including one where
its own enrichment step flagged the organization as over the threshold. Here
it is driven by the routing decision, and a payload is refused outright if
the organization is not eligible.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.utils.form_routing import FORM_990N, FormRouting

__all__ = [
    "Form990NPayload",
    "build_form_990n_payload",
    "normalise_ein",
    "filing_window",
    "is_fileable_year",
]

# Tax990 rejects a phone that is not exactly ten digits. This is the reserved
# test number the sandbox scenario falls back to; it must never reach a live
# filing, so its use is recorded as a warning rather than applied silently.
SANDBOX_PLACEHOLDER_PHONE = "2025550100"

# The IRS accepts electronic 990-N filings for a rolling three-year window,
# and Tax990 enforces it: probing their sandbox in August 2026 returned
# "TaxYr is not supported" for 2022 and 2026, and accepted 2023 through 2025.
# A year cannot be filed before it has ended, which is why the current year
# is closed.
#
# Checking here saves a round trip and gives a reason the caller can act on,
# rather than a rejection code returned after the fact.
FILING_WINDOW_YEARS = 3


class Form990NPayload:
    """A payload, the warnings raised building it, and whether it may be sent."""

    __slots__ = ("payload", "warnings", "blocking_errors")

    def __init__(
        self,
        payload: dict[str, Any] | None,
        warnings: list[str],
        blocking_errors: list[str],
    ) -> None:
        self.payload = payload
        self.warnings = warnings
        self.blocking_errors = blocking_errors

    @property
    def is_submittable(self) -> bool:
        return self.payload is not None and not self.blocking_errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "warnings": list(self.warnings),
            "blocking_errors": list(self.blocking_errors),
            "is_submittable": self.is_submittable,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Form990NPayload(submittable={self.is_submittable!r})"


def filing_window(as_of: Any = None) -> tuple[int, int]:
    """The earliest and latest tax years currently accepted.

    Filing opens once a year has ended, so the newest year available is the
    one before the current one.
    """
    from datetime import date

    today = as_of or date.today()
    newest = today.year - 1
    return newest - (FILING_WINDOW_YEARS - 1), newest


def is_fileable_year(year: Any) -> bool:
    """Whether a tax year can be submitted, as opposed to merely prepared."""
    try:
        earliest, latest = filing_window()
        return earliest <= int(str(year)[:4]) <= latest
    except (TypeError, ValueError):
        return False


def normalise_ein(value: Any) -> str:
    """Strip formatting from an EIN. Tax990 expects nine bare digits."""
    return re.sub(r"[^0-9]", "", str(value or ""))


def _digits(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _zip5(value: Any) -> str:
    digits = _digits(value)
    return digits[:5]


def build_form_990n_payload(
    content: Mapping[str, Any],
    routing: FormRouting,
    *,
    tax_year: str | int | None = None,
    is_terminated: bool = False,
    allow_placeholder_phone: bool = False,
) -> Form990NPayload:
    """Build the Tax990 create-draft body for a Form 990-N.

    `routing` must come from `route_form_variant`. A payload is only produced
    when it selected the 990-N; anything else is a blocking error, because
    filing a 990-N an organization is not eligible for means the IRS treats
    the return as not filed at all.
    """
    warnings: list[str] = []
    blocking: list[str] = []

    if routing.form != FORM_990N:
        blocking.append(
            f"Organization routes to {routing.form or 'no form'}, not {FORM_990N}. "
            f"A 990-N filed by an ineligible organization is treated as not filed."
        )
        return Form990NPayload(None, warnings, blocking)

    if routing.requires_review:
        warnings.append(
            "ROUTING_REQUIRES_REVIEW: "
            + "; ".join(routing.review_reasons)
        )

    org = dict(content.get("organizationInformation") or {})
    summary = dict(content.get("organization_summary") or {})
    address = dict(org.get("address") or {})
    officer = dict(org.get("principalOfficer") or {})
    officer_address = officer.get("address")

    # --- element 1: EIN --------------------------------------------------
    ein = normalise_ein(org.get("ein") or summary.get("ein"))
    if len(ein) != 9:
        blocking.append(
            f"EIN must be nine digits; got {ein!r}."
        )

    # --- element 2: tax year ---------------------------------------------
    year = _clean(tax_year or summary.get("tax_year"))
    if not re.fullmatch(r"\d{4}", year):
        blocking.append(f"Tax year must be four digits; got {year!r}.")
    else:
        # Preparing a return for any year is useful: routing, the financial
        # figures and the classification are all worth seeing for a year that
        # cannot be submitted. Only the submission is constrained, so this is
        # a warning here and enforced at the point of filing.
        earliest, latest = filing_window()
        if not earliest <= int(year) <= latest:
            warnings.append(
                f"OUTSIDE_FILING_WINDOW: tax year {year} cannot be submitted. "
                f"Tax990 accepts {earliest} through {latest}; a year cannot be "
                f"filed before it has ended. The return can still be prepared "
                f"and reviewed."
            )

    # --- element 3: legal name and address -------------------------------
    legal_name = _clean(org.get("legalName") or summary.get("organization_name"))
    if not legal_name:
        blocking.append("Legal name is required.")

    street = _clean(address.get("street"))
    city = _clean(address.get("city"))
    state = _clean(address.get("state"))
    zip_code = _zip5(address.get("zip"))
    for label, value in (
        ("street", street), ("city", city), ("state", state), ("ZIP", zip_code)
    ):
        if not value:
            blocking.append(f"Mailing address {label} is required.")

    # --- element 4: other names ------------------------------------------
    dba_names = [n for n in (org.get("dbaNames") or []) if _clean(n)]

    # --- element 5: principal officer ------------------------------------
    officer_name = _clean(officer.get("name"))
    if not officer_name:
        blocking.append("Principal officer name is required.")

    # --- element 6: website ----------------------------------------------
    website = _clean(org.get("website"))

    # --- phone -----------------------------------------------------------
    phone = _digits(org.get("telephone"))
    if len(phone) != 10:
        if allow_placeholder_phone:
            warnings.append(
                f"PLACEHOLDER_PHONE: no valid ten-digit phone found; the reserved "
                f"test number {SANDBOX_PLACEHOLDER_PHONE} was substituted to satisfy "
                f"sandbox validation. This must not reach a live filing."
            )
            phone = SANDBOX_PLACEHOLDER_PHONE
        else:
            blocking.append(
                f"A ten-digit phone number is required; got {phone!r}."
            )

    # --- element 7: the gross receipts declaration -----------------------
    # Driven by the routing decision, never asserted. The Make.com scenario
    # hardcodes this true on every submission, including for organizations
    # its own enrichment flagged as over the threshold.
    warnings.append(
        f"GROSS_RECEIPTS_DECLARATION: attested from gross receipts of "
        f"{routing.gross_receipts:,.2f} against the {routing.gross_receipts_limit:,.0f} "
        f"limit for age tier '{routing.age_tier}' (basis: {routing.basis})."
    )

    if blocking:
        return Form990NPayload(None, warnings, blocking)

    officer_us_address = {
        "Address1": street,
        "Address2": None,
        "City": city,
        "State": state,
        "ZipCd": zip_code,
    }
    if isinstance(officer_address, Mapping):
        officer_us_address = {
            "Address1": _clean(officer_address.get("street")) or street,
            "Address2": None,
            "City": _clean(officer_address.get("city")) or city,
            "State": _clean(officer_address.get("state")) or state,
            "ZipCd": _zip5(officer_address.get("zip")) or zip_code,
        }

    payload = {
        "Form990NRecords": [
            {
                "Business": {
                    "BusinessId": None,
                    "BusinessNm": legal_name,
                    "EIN": ein,
                    "DBANm": dba_names[0] if dba_names else None,
                    "InCareOfNm": _clean(org.get("careOfName")) or None,
                    "EmailAddress": _clean(org.get("email")) or None,
                    "Phone": phone,
                    "IsForeign": False,
                    "USAddress": {
                        "Address1": street,
                        "Address2": None,
                        "City": city,
                        "State": state,
                        "ZipCd": zip_code,
                    },
                    "ForeignAddress": None,
                },
                "Form990N": {
                    "SequenceId": "1",
                    "RecordId": None,
                    "TaxYr": year,
                    "TaxPeriodBeginDt": f"{year}-01-01",
                    "TaxPeriodEndDt": f"{year}-12-31",
                    "IsGrossReceiptsUnder50K": True,
                    "IsOrganizationTerminated": bool(is_terminated),
                    "WebsiteAddress": website or None,
                    "PrincipalOfficer": {
                        "OfficerNm": officer_name,
                        "IsForeign": False,
                        "USAddress": officer_us_address,
                        "ForeignAddress": None,
                    },
                },
            }
        ]
    }

    return Form990NPayload(payload, warnings, blocking)

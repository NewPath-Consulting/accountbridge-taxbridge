"""Schemas for filing preparation.

Preparing a filing needs three things the reports pipeline does not:

  * the organization's identity, which QuickBooks does not hold
  * its age, which decides *which* 990-N threshold applies
  * its prior-year receipts, for the multi-year test

The first is entered by the preparer. The last two can be filled from
ProPublica through the lookup endpoint, and are optional here: without them
routing still returns an answer, but a conservative one, flagged for review.
"""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.reports import QuickBooksCredentialsInline

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PrincipalOfficer(BaseModel):
    """The one field neither QuickBooks nor ProPublica supplies."""

    name: str = Field("", description="Full name of the principal officer")
    title: str = Field("", description="Their title, e.g. President")
    address: Optional[Dict[str, str]] = Field(
        None,
        description="Officer address; the organization address is used when omitted",
    )


class OrganizationDetails(BaseModel):
    """Identity that goes on the return itself."""

    legalName: str = Field("", description="Legal name as registered with the IRS")
    ein: str = Field("", description="Employer Identification Number, any format")
    dbaNames: List[str] = Field(default_factory=list)
    address: Dict[str, str] = Field(default_factory=dict)
    telephone: str = Field("", description="Ten digits; Tax990 rejects anything else")
    website: str = Field("")
    principalOfficer: PrincipalOfficer = Field(default_factory=PrincipalOfficer)
    taxExemptStatus: str = Field("")
    yearOfFormation: str = Field("")


class LookupRequest(BaseModel):
    """Look an organization up in ProPublica by EIN."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"ein": "43-1633425"}]}
    )

    ein: str = Field(..., description="EIN in any format; nine digits after cleaning")


class LookupResponse(BaseModel):
    found: bool
    ein: str = ""
    legal_name: str = ""
    address: Dict[str, str] = Field(default_factory=dict)
    ruling_date: Optional[str] = None
    age_years: Optional[float] = None
    prior_year_gross_receipts: List[float] = Field(default_factory=list)
    filings: List[Dict[str, Any]] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PrepareFilingRequest(BaseModel):
    """Prepare a filing from a QuickBooks period."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "quickbooks_realm_id": "9341457668846945",
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                    "organization": {
                        "legalName": "Kansas City Woodworkers Guild",
                        "ein": "43-1633425",
                        "address": {
                            "street": "3189 Mercier St",
                            "city": "Kansas City",
                            "state": "MO",
                            "zip": "64111",
                        },
                        "telephone": "8167610075",
                        "principalOfficer": {"name": "Jane Doe", "title": "President"},
                    },
                    "organization_age_years": 48.0,
                    "prior_year_gross_receipts": [10200.0, 9800.0],
                }
            ]
        }
    )

    quickbooks_realm_id: str = Field(..., min_length=5)
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    organization: OrganizationDetails = Field(default_factory=OrganizationDetails)
    quickbooks_credentials: Optional[QuickBooksCredentialsInline] = None

    organization_age_years: Optional[float] = Field(
        None,
        description=(
            "Years since the IRS ruling date. Decides which 990-N limit applies: "
            "75,000 in the first year, 60,000 up to three, 50,000 thereafter. "
            "Left unset, the strictest applies and the decision is flagged."
        ),
    )
    prior_year_gross_receipts: List[float] = Field(
        default_factory=list,
        description="Earlier years, most recent first, for the multi-year test",
    )
    tax_year: Optional[str] = Field(
        None,
        description=(
            "The tax year printed on the return, which is not always the year "
            "of the accounting period. Defaults to the year of end_date. A "
            "year cannot be filed before it has ended, so the current year is "
            "never available."
        ),
    )
    report_content: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "tax_return.content from a previous /api/reports run. Required for "
            "the 990-EZ and full 990, which carry financial detail; a 990-N "
            "does not need it."
        ),
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        if not _DATE_PATTERN.match(value.strip()):
            raise ValueError("Dates must be YYYY-MM-DD")
        return value.strip()


class FilingStage(BaseModel):
    """One step of the preparation, with what it found."""

    stage: str
    status: str = Field(..., description="ok | warning | review | ready | blocked | failed")
    summary: str
    detail: Dict[str, Any] = Field(default_factory=dict)


class PrepareFilingResponse(BaseModel):
    status: str = Field(..., description="prepared | blocked")
    routed_form_variant: Optional[str] = None
    stages: List[FilingStage] = Field(default_factory=list)
    payload: Optional[Dict[str, Any]] = None
    routing: Optional[Dict[str, Any]] = None
    filing_available: bool = Field(
        False,
        description=(
            "True only for the 990-N. Tax990's API does not yet accept the "
            "990-EZ or the full 990."
        ),
    )
    processing_time: float = 0.0

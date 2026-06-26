"""Schemas for reports generation API."""
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Dict, Any, Optional

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PLACEHOLDER_PATTERN = re.compile(
    r"^(string|your[_-]?account[_-]?id|your[_-]?realm[_-]?id)$",
    re.IGNORECASE,
)


def _reject_placeholder(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if _PLACEHOLDER_PATTERN.match(cleaned):
        raise ValueError(
            f"{field_name} must be a real ID, not the Swagger placeholder {cleaned!r}"
        )
    return cleaned


class QuickBooksCredentialsInline(BaseModel):
    """Optional QuickBooks OAuth credentials supplied per request (e.g. from Streamlit)."""

    client_id: str = Field(..., min_length=5, description="QuickBooks app Client ID")
    client_secret: str = Field(..., min_length=5, description="QuickBooks app Client Secret")
    refresh_token: str = Field(
        ...,
        min_length=10,
        description="Refresh token (RT1-...) from the OAuth playground",
    )
    access_token: Optional[str] = Field(
        None,
        description="Optional access token from the playground (used until refresh is needed)",
    )
    realm_id: Optional[str] = Field(
        None,
        description="Optional QuickBooks company / realm ID override",
    )


class ReportsRequest(BaseModel):
    """Request model for generating reports."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "wildapricot_account_id": "497705",
                    "quickbooks_realm_id": "9341457191103538",
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-08",
                    "user_prompt": "Emphasize deferred membership revenue in the cash flow report.",
                }
            ]
        }
    )

    wildapricot_account_id: str = Field(..., description="WildApricot Account ID")
    quickbooks_realm_id: str = Field(..., description="QuickBooks Realm ID")
    start_date: Optional[str] = Field(None, description="Start date for reports (YYYY-MM-DD). Defaults to start of current year.")
    end_date: Optional[str] = Field(None, description="End date for reports (YYYY-MM-DD). Defaults to today.")
    wildapricot_data: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Optional cached WildApricot extraction payload. When provided, "
            "WildApricot is not re-fetched (used after a QuickBooks token retry)."
        ),
    )
    quickbooks_credentials: Optional[QuickBooksCredentialsInline] = Field(
        None,
        description=(
            "Optional QuickBooks credentials for this request only. When provided, "
            "these values are used instead of QUICKBOOKS_* settings in .env."
        ),
    )
    user_prompt: Optional[str] = Field(
        None,
        description=(
            "Optional user instructions for this report run. When provided, the LLM "
            "prioritizes this guidance across cash flow, balance sheet, and tax return generation."
        ),
    )

    @field_validator("wildapricot_account_id", mode="before")
    @classmethod
    def validate_wildapricot_account_id(cls, v: object) -> str:
        if v is None:
            raise ValueError("wildapricot_account_id is required")
        cleaned = _reject_placeholder(str(v), "wildapricot_account_id")
        if not cleaned.isdigit():
            raise ValueError(
                f"wildapricot_account_id must be numeric, got {cleaned!r}"
            )
        return cleaned

    @field_validator("quickbooks_realm_id", mode="before")
    @classmethod
    def validate_quickbooks_realm_id(cls, v: object) -> str:
        if v is None:
            raise ValueError("quickbooks_realm_id is required")
        cleaned = _reject_placeholder(str(v), "quickbooks_realm_id")
        if not cleaned.isdigit():
            raise ValueError(
                f"quickbooks_realm_id must be numeric, got {cleaned!r}"
            )
        return cleaned
    
    @field_validator('start_date', mode='before')
    @classmethod
    def set_default_start_date(cls, v):
        """Set default start date to beginning of current year if not provided."""
        if v is None or v == "":
            return f"{datetime.now().year}-01-01"
        return v
    
    @field_validator('end_date', mode='before')
    @classmethod
    def set_default_end_date(cls, v):
        """Set default end date to today if not provided."""
        if v is None or v == "":
            return datetime.now().strftime("%Y-%m-%d")
        return v

    @field_validator("start_date", "end_date", mode="after")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if _PLACEHOLDER_PATTERN.match(v.strip()):
            raise ValueError(
                f"Date must be YYYY-MM-DD, not the Swagger placeholder {v!r}"
            )
        if not _DATE_PATTERN.match(v):
            raise ValueError(f"Date must be YYYY-MM-DD, got {v!r}")
        datetime.strptime(v, "%Y-%m-%d")
        return v


class ReportData(BaseModel):
    """Individual report data."""
    report_type: str = Field(..., description="Type of report (cash_flow, balance_sheet, tax_return)")
    content: Dict[str, Any] = Field(..., description="Generated report content")
    processing_time: float = Field(..., description="Time taken to generate report in seconds")
    status: str = Field(..., description="Report generation status")
    error_message: Optional[str] = Field(None, description="Error message if generation failed")


class ReportsResponse(BaseModel):
    """Response model for reports generation."""
    request_id: str = Field(..., description="Unique request identifier")
    wildapricot_account_id: str
    quickbooks_realm_id: str
    start_date: str
    end_date: str

    reports: Dict[str, ReportData] = Field(..., description="Generated reports by type")

    total_processing_time: float = Field(..., description="Total time for all operations")
    status: str = Field(..., description="Overall status")


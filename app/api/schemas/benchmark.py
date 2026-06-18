"""Schemas for benchmark API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class AvailableReportItem(BaseModel):
    """A single benchmark reference document available for selection."""

    file_name: str = Field(description="PDF file name — pass this in selected_document_files")
    doc_type: str = Field(description="Document type: form_990 | cash_flow | financial_position")
    fiscal_year: int = Field(description="Fiscal year the document covers")
    start_date: str = Field(description="Fiscal year start date (YYYY-MM-DD)")
    end_date: str = Field(description="Fiscal year end date (YYYY-MM-DD)")


class AvailableReportsResponse(BaseModel):
    """Response listing available benchmark reference documents."""

    documents: List[AvailableReportItem] = Field(
        default_factory=list,
        description="All reference PDFs found in the benchmark document source",
    )
    total: int = Field(description="Total number of available documents")


class BenchmarkRequest(BaseModel):
    """Request model for running LLM benchmark comparison."""

    wildapricot_account_id: Optional[str] = Field(
        None, description="WildApricot Account ID"
    )
    quickbooks_realm_id: Optional[str] = Field(
        None, description="QuickBooks Realm ID"
    )
    start_date: Optional[str] = Field(
        None, description="Reports period start (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, description="Reports period end (YYYY-MM-DD)"
    )
    reports: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "cash_flow and tax_return from /api/reports. "
            "Omit when use_cached_reports=true."
        ),
    )
    use_cached_reports: bool = Field(
        False,
        description=(
            "TEMP: load reports from local data/reports/latest.json "
            "(saved by /api/reports) for benchmark-only testing."
        ),
    )
    years: Optional[List[int]] = Field(
        None,
        description=(
            "Fiscal years to benchmark. When omitted, years are derived from "
            "start_date/end_date and matched against reference docs."
        ),
    )
    selected_document_files: Optional[List[str]] = Field(
        None,
        description=(
            "Reference document file names to benchmark against (max 3). "
            "Fetch available file names from GET /api/benchmark/reports. "
            "Omit to use all available reference documents."
        ),
    )

    @field_validator("reports")
    @classmethod
    def validate_reports(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        for key in ("cash_flow", "tax_return"):
            if key not in v:
                raise ValueError(f"reports must include '{key}'")
            entry = v[key]
            if not isinstance(entry, dict) or not entry.get("content"):
                raise ValueError(f"reports['{key}'] must include non-empty content")
        return v

    @model_validator(mode="after")
    def validate_request_mode(self) -> "BenchmarkRequest":
        if self.use_cached_reports:
            return self

        missing = [
            name
            for name in (
                "wildapricot_account_id",
                "quickbooks_realm_id",
                "start_date",
                "end_date",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} required unless use_cached_reports=true"
            )
        if self.reports is None:
            raise ValueError("reports is required unless use_cached_reports=true")
        return self


class BenchmarkResponse(BaseModel):
    """Response model for LLM benchmark comparison."""

    request_id: str
    start_date: str = ""
    end_date: str = ""
    wildapricot_account_id: str = ""
    quickbooks_realm_id: str = ""
    years_benchmarked: List[int] = Field(default_factory=list)
    year_resolution_note: Optional[str] = None
    results: Dict[str, Any] = Field(default_factory=dict)
    overall_match_score: float = 0.0
    total_processing_time: float = 0.0
    status: str = "completed"

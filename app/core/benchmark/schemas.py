"""Core types for LLM benchmark evaluation."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

BenchmarkDocType = Literal["form_990", "cash_flow", "financial_position"]


class BenchmarkDocument(BaseModel):
    """A reference document eligible for benchmarking."""

    doc_type: BenchmarkDocType
    file_name: str
    file_path: str
    fiscal_year: int
    start_date: str
    end_date: str


class YearBenchmarkResult(BaseModel):
    """LLM benchmark results for a single fiscal year."""

    fiscal_year: int
    form_990_review: Optional[Dict[str, Any]] = None
    cash_flow_review: Optional[Dict[str, Any]] = None
    financial_position_review: Optional[Dict[str, Any]] = None
    synthesis: Optional[Dict[str, Any]] = None
    scorecard: Optional[Dict[str, Any]] = None
    reference_extractions: Optional[Dict[str, Any]] = None
    status: str = "completed"


class BenchmarkResult(BaseModel):
    """Full benchmark run output."""

    request_id: str
    start_date: str = ""
    end_date: str = ""
    wildapricot_account_id: str = ""
    quickbooks_realm_id: str = ""
    years_benchmarked: List[int] = Field(default_factory=list)
    year_resolution_note: Optional[str] = None
    results: Dict[str, YearBenchmarkResult] = Field(default_factory=dict)
    overall_match_score: float = 0.0
    total_processing_time: float = 0.0
    status: str = "completed"

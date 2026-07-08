"""Benchmark comparison endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Optional
import logging

from app.api.dependencies.rate_limit import limiter, rate_limit_string
from app.api.schemas.benchmark import (
    AvailableReportItem,
    AvailableReportsResponse,
    BenchmarkRequest,
    BenchmarkResponse,
)
from app.core.benchmark.document_source import get_document_source
from app.core.benchmark.service import BenchmarkService

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_DOC_TYPES = {"form_990", "cash_flow", "financial_position"}


def get_benchmark_service() -> BenchmarkService:
    """Get or create benchmark service (dependency injection)."""
    return BenchmarkService()


@router.get(
    "/benchmark/reports",
    response_model=AvailableReportsResponse,
    tags=["Benchmarking"],
    summary="List available benchmark reference documents",
)
async def list_benchmark_reports(
    doc_type: Optional[str] = Query(
        None,
        description="Filter by document type: form_990 | cash_flow | financial_position",
    ),
):
    """Return all benchmark reference PDFs available for selection.

    Pass the returned ``file_name`` values in the ``selected_document_files``
    field of ``POST /api/benchmark`` to benchmark against specific documents only.
    """
    if doc_type and doc_type not in _VALID_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid doc_type '{doc_type}'. Must be one of: {sorted(_VALID_DOC_TYPES)}",
        )

    try:
        source = get_document_source()
        docs = await source.list_documents(doc_type=doc_type or None)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to list benchmark documents: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Could not list benchmark documents: {exc}"
        ) from exc

    items = [
        AvailableReportItem(
            file_name=doc.file_name,
            doc_type=doc.doc_type,
            fiscal_year=doc.fiscal_year,
            start_date=doc.start_date,
            end_date=doc.end_date,
        )
        for doc in docs
    ]

    return AvailableReportsResponse(documents=items, total=len(items))


@router.post(
    "/benchmark",
    response_model=BenchmarkResponse,
    tags=["Benchmarking"],
    summary="LLM benchmark of Form 990 and cash flow reports against reference documents",
)
@limiter.limit(rate_limit_string)
async def run_benchmark(
    request: Request,
    benchmark_request: BenchmarkRequest,
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
):
    """
    Extract ground-truth from reference PDFs, compare against reports
    (cash_flow + tax_return from /api/reports) using split LLM evaluation,
    and return scores with explanations.
    """
    try:
        logger.info(
            "Benchmark request: wa=%s qb=%s years=%s period=%s..%s",
            benchmark_request.wildapricot_account_id,
            benchmark_request.quickbooks_realm_id,
            benchmark_request.years,
            benchmark_request.start_date,
            benchmark_request.end_date,
        )

        result = await benchmark_service.run_benchmark(
            reports=benchmark_request.reports,
            years=benchmark_request.years,
            start_date=benchmark_request.start_date,
            end_date=benchmark_request.end_date,
            wildapricot_account_id=benchmark_request.wildapricot_account_id,
            quickbooks_realm_id=benchmark_request.quickbooks_realm_id,
            selected_document_files=benchmark_request.selected_document_files,
        )

        return BenchmarkResponse(
            request_id=result.request_id,
            start_date=result.start_date,
            end_date=result.end_date,
            wildapricot_account_id=result.wildapricot_account_id,
            quickbooks_realm_id=result.quickbooks_realm_id,
            years_benchmarked=result.years_benchmarked,
            year_resolution_note=result.year_resolution_note,
            results={
                year: year_result.model_dump()
                for year, year_result in result.results.items()
            },
            overall_match_score=result.overall_match_score,
            total_processing_time=result.total_processing_time,
            status=result.status,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        logger.error("Benchmark failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Benchmark failed: {exc}",
        ) from exc

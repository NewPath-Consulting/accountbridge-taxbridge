"""Load filed Cash Flow and Financial Position reference PDFs (benchmark only).

The /api/reports pipeline does NOT call these helpers. Reports use QuickBooks +
WildApricot only, except Form 990 pages 1-2 (organizationInformation) during
tax return generation via form_990_organization.py.

Benchmark ground-truth extraction uses extract_reference_document in
app.core.benchmark.extraction directly.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.benchmark.document_source import get_document_source
from app.core.benchmark.extraction import extract_reference_document
from app.core.benchmark.schemas import BenchmarkDocType, BenchmarkDocument

logger = logging.getLogger(__name__)


async def resolve_reference_doc(
    doc_type: BenchmarkDocType,
    fiscal_year: int | None,
) -> BenchmarkDocument | None:
    """Pick a reference PDF for the fiscal year, falling back to the latest available."""
    source = get_document_source()
    docs = await source.list_documents(doc_type)
    if not docs:
        return None

    if fiscal_year is not None:
        for doc in docs:
            if doc.fiscal_year == fiscal_year:
                return doc

    return max(docs, key=lambda d: d.fiscal_year)


async def _load_reference_extraction(
    doc_type: BenchmarkDocType,
    fiscal_year: int | None,
) -> dict[str, Any] | None:
    doc = await resolve_reference_doc(doc_type, fiscal_year)
    if doc is None:
        return None

    try:
        file_bytes, file_name = await get_document_source().read_bytes(doc)
        extraction = await extract_reference_document(
            file_bytes=file_bytes,
            file_name=file_name,
            doc_type=doc_type,
        )
        output = extraction.llm_output or {}
        if output.get("_parse_error"):
            logger.warning(
                "Reference %s extraction parse failed for %s",
                doc_type,
                file_name,
            )
            return None
        return {
            "source_file": file_name,
            "fiscal_year": doc.fiscal_year,
            "extraction": output,
        }
    except Exception as exc:
        logger.warning(
            "Reference %s extraction failed for fiscal_year=%s: %s",
            doc_type,
            fiscal_year,
            exc,
        )
        return None


async def load_reference_cash_flow(end_date: str) -> dict[str, Any] | None:
    """Textract + LLM structure for filed Statement of Cash Flows (benchmark tooling)."""
    try:
        fiscal_year = int(str(end_date)[:4])
    except (TypeError, ValueError):
        fiscal_year = None
    return await _load_reference_extraction("cash_flow", fiscal_year)


async def load_reference_financial_position(end_date: str) -> dict[str, Any] | None:
    """Textract + LLM structure for filed Statement of Financial Position (benchmark tooling)."""
    try:
        fiscal_year = int(str(end_date)[:4])
    except (TypeError, ValueError):
        fiscal_year = None
    return await _load_reference_extraction("financial_position", fiscal_year)


async def load_prior_year_financial_position(end_date: str) -> dict[str, Any] | None:
    """Prior-year financial position (benchmark tooling)."""
    try:
        fiscal_year = int(str(end_date)[:4]) - 1
    except (TypeError, ValueError):
        return None
    if fiscal_year < 1:
        return None
    return await _load_reference_extraction("financial_position", fiscal_year)

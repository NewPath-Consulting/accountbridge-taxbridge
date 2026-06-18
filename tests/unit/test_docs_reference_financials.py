"""Unit tests for docs/ reference financial statement resolution."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.core.benchmark.schemas import BenchmarkDocument
from app.utils.docs_reference_financials import (
    load_prior_year_financial_position,
    resolve_reference_doc,
)


def test_resolve_reference_doc_matches_fiscal_year():
    docs = [
        BenchmarkDocument(
            doc_type="financial_position",
            file_name="Statement of Financial Position 12312024.pdf",
            file_path="/docs/fp2024.pdf",
            fiscal_year=2024,
            start_date="2024-01-01",
            end_date="2024-12-31",
        ),
        BenchmarkDocument(
            doc_type="financial_position",
            file_name="Statement of Financial Position 12312025.pdf",
            file_path="/docs/fp2025.pdf",
            fiscal_year=2025,
            start_date="2025-01-01",
            end_date="2025-12-31",
        ),
    ]

    mock_source = AsyncMock()
    mock_source.list_documents.return_value = docs

    with patch(
        "app.utils.docs_reference_financials.get_document_source",
        return_value=mock_source,
    ):
        doc = asyncio.run(resolve_reference_doc("financial_position", 2025))

    assert doc is not None
    assert doc.fiscal_year == 2025


def test_load_prior_year_financial_position_uses_previous_year():
    docs = [
        BenchmarkDocument(
            doc_type="financial_position",
            file_name="Statement of Financial Position 12312024.pdf",
            file_path="/docs/fp2024.pdf",
            fiscal_year=2024,
            start_date="2024-01-01",
            end_date="2024-12-31",
        ),
    ]

    mock_source = AsyncMock()
    mock_source.list_documents.return_value = docs
    mock_source.read_bytes.return_value = (b"%PDF", "fp2024.pdf")

    mock_extraction = AsyncMock()
    mock_extraction.return_value.llm_output = {
        "assets": {"cash": 100000, "total_assets": 500000}
    }

    with patch(
        "app.utils.docs_reference_financials.get_document_source",
        return_value=mock_source,
    ), patch(
        "app.utils.docs_reference_financials.extract_reference_document",
        mock_extraction,
    ):
        result = asyncio.run(load_prior_year_financial_position("2025-12-31"))

    assert result is not None
    assert result["fiscal_year"] == 2024
    assert result["extraction"]["assets"]["cash"] == 100000

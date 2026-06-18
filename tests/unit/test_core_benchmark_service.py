"""Unit tests for BenchmarkService with mocked LLM and extraction."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.core.benchmark.schemas import BenchmarkDocument, YearBenchmarkResult
from app.core.benchmark.service import (
    BenchmarkService,
    _year_match_score,
    resolve_benchmark_years,
    validate_benchmark_reports,
)


SAMPLE_REPORTS = {
    "cash_flow": {
        "report_type": "cash_flow",
        "status": "completed",
        "processing_time": 5.0,
        "content": {
            "report_metadata": {"organization_name": "KCWG"},
            "operating_activities": {
                "net_cash_from_operations": {"amount": 1000},
            },
            "cash_reconciliation": {
                "beginning_cash": {"amount": 500},
                "ending_cash": {"amount": 1500},
            },
        },
    },
    "tax_return": {
        "report_type": "tax_return",
        "status": "completed",
        "processing_time": 10.0,
        "content": {
            "organization_summary": {"organization_name": "KCWG"},
            "generated_tax_return_draft": {
                "revenue": {"total_revenue": 50000},
            },
        },
    },
}


def test_validate_benchmark_reports_missing_key():
    with pytest.raises(ValueError, match="tax_return"):
        validate_benchmark_reports({"cash_flow": SAMPLE_REPORTS["cash_flow"]})


def test_validate_benchmark_reports_empty_content():
    bad = {
        **SAMPLE_REPORTS,
        "tax_return": {**SAMPLE_REPORTS["tax_return"], "content": {}},
    }
    with pytest.raises(ValueError, match="no content"):
        validate_benchmark_reports(bad)


def test_year_match_score_from_scorecard():
    year_result = YearBenchmarkResult(
        fiscal_year=2025,
        scorecard={"adjusted_composite_score": 72.5},
        synthesis={"overall_score": 2},
    )
    assert _year_match_score(year_result) == 0.725


def test_year_match_score_from_parsed_synthesis():
    year_result = YearBenchmarkResult(
        fiscal_year=2025,
        synthesis={"overall_score": 2, "executive_summary": "Low match"},
        form_990_review={"score": 2},
        cash_flow_review={"score": 2},
    )
    assert _year_match_score(year_result) == 0.02


def test_run_benchmark_mocked_llm_parses_bedrock_envelope():
    doc_990 = BenchmarkDocument(
        doc_type="form_990",
        file_name="f990.pdf",
        file_path="/tmp/f990.pdf",
        fiscal_year=2024,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    doc_cf = BenchmarkDocument(
        doc_type="cash_flow",
        file_name="cf.pdf",
        file_path="/tmp/cf.pdf",
        fiscal_year=2024,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    mock_source = AsyncMock()
    mock_source.list_documents.return_value = [doc_990, doc_cf]
    mock_source.read_bytes.return_value = (b"%PDF-1.4", "test.pdf")

    llm_responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"score": 90, "rating": "good", "summary": "990 ok", '
                            '"key_differences": [], "issues": []}'
                        )
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"score": 85, "rating": "good", "summary": "cf ok", '
                            '"key_differences": [], "issues": []}'
                        )
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"overall_score": 88, "rating": "good", '
                            '"form_990_score": 90, "cash_flow_score": 85, '
                            '"summary": "Good overall match.", "top_issues": []}'
                        )
                    }
                }
            ]
        },
    ]

    async def fake_llm(_body, **kwargs):
        return llm_responses.pop(0), None

    mock_extraction = AsyncMock()
    mock_extraction.return_value.llm_output = {"revenue": {"total_revenue": 50000}}

    service = BenchmarkService(document_source=mock_source)

    with patch(
        "app.core.benchmark.extraction.extract_reference_document",
        mock_extraction,
    ), patch(
        "app.core.benchmark.llm.run_benchmark_llm",
        side_effect=fake_llm,
    ):
        result = asyncio.run(
            service.run_benchmark(
                reports=SAMPLE_REPORTS,
                years=[2024],
                start_date="2024-01-01",
                end_date="2024-12-31",
            )
        )

    assert result.years_benchmarked == [2024]
    year = result.results["2024"]
    assert year.scorecard is not None
    assert year.scorecard.get("adjusted_composite_score") is not None
    assert result.overall_match_score == pytest.approx(
        year.scorecard["adjusted_composite_score"] / 100.0
    )
    assert year.form_990_review is not None
    assert year.form_990_review.get("summary") == "990 ok"
    assert year.form_990_review.get("score") == 98.0
    assert year.cash_flow_review is not None
    assert year.synthesis is not None
    assert year.synthesis.get("summary") == "Good overall match."
    assert year.synthesis.get("overall_score") == year.scorecard["adjusted_composite_score"]


def test_resolve_benchmark_years_from_period():
    docs_by_year = {
        2023: {"form_990": object(), "cash_flow": object()},
        2024: {"form_990": object(), "cash_flow": object()},
        2025: {"form_990": object(), "cash_flow": object()},
    }
    years, note = resolve_benchmark_years(
        years=None,
        start_date="2025-01-01",
        end_date="2025-12-31",
        docs_by_year=docs_by_year,
    )
    assert years == [2025]
    assert note is None


def test_resolve_benchmark_years_falls_back_to_latest_two_when_period_missing():
    docs_by_year = {
        2023: {"form_990": object(), "cash_flow": object()},
        2024: {"form_990": object(), "cash_flow": object()},
        2025: {"form_990": object(), "cash_flow": object()},
    }
    years, note = resolve_benchmark_years(
        years=None,
        start_date="2026-01-01",
        end_date="2026-12-31",
        docs_by_year=docs_by_year,
    )
    assert years == [2024, 2025]
    assert note is not None
    assert "2026" in note


def test_resolve_benchmark_years_explicit_list():
    docs_by_year = {
        2024: {"form_990": object()},
        2025: {"form_990": object()},
    }
    years, note = resolve_benchmark_years(
        years=[2024, 2025],
        start_date="2025-01-01",
        end_date="2025-12-31",
        docs_by_year=docs_by_year,
    )
    assert years == [2024, 2025]
    assert note is None


def test_resolve_benchmark_years_explicit_missing_falls_back():
    docs_by_year = {
        2024: {"form_990": object(), "cash_flow": object()},
        2025: {"form_990": object(), "cash_flow": object()},
    }
    years, note = resolve_benchmark_years(
        years=[2026],
        start_date="2026-01-01",
        end_date="2026-12-31",
        docs_by_year=docs_by_year,
    )
    assert years == [2024, 2025]
    assert note is not None

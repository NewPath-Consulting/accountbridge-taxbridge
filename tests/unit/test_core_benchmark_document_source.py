"""Unit tests for benchmark document source."""

import asyncio

import pytest

from app.core.benchmark.document_source import (
    LocalBenchmarkDocumentSource,
    S3BenchmarkDocumentSource,
    get_document_source,
    parse_fiscal_year_from_filename,
    years_from_period,
)


@pytest.mark.parametrize(
    "file_name,expected",
    [
        ("Statement of Cash Flows 12312024.pdf", 2024),
        ("Statement of Cash Flows 12312023.pdf", 2023),
        ("KANSAS CITY WOODWORKERS GUILD INC_Form990 2024 filed 05152025.pdf", 2024),
        ("KANSAS CITY WOODWORKERS GUILD INC_Form990 2025 filed 04192025.pdf", 2025),
        (
            "KANSAS CITY WOODWORKERS GUILD INC_Form990 Final Submission 05142024.pdf",
            2023,
        ),
        ("Statement of Financial Position 12312025.pdf", 2025),
    ],
)
def test_parse_fiscal_year_from_filename(file_name, expected):
    if "Cash Flows" in file_name:
        doc_type = "cash_flow"
    elif "Financial Position" in file_name:
        doc_type = "financial_position"
    else:
        doc_type = "form_990"
    assert parse_fiscal_year_from_filename(file_name, doc_type) == expected


def test_local_document_source_lists_form_990_and_cash_flow():
    source = LocalBenchmarkDocumentSource()
    docs = asyncio.run(source.list_documents())

    form_990 = [d for d in docs if d.doc_type == "form_990"]
    cash_flow = [d for d in docs if d.doc_type == "cash_flow"]
    financial_position = [d for d in docs if d.doc_type == "financial_position"]

    assert len(form_990) == 3
    assert len(cash_flow) == 3
    assert len(financial_position) == 3
    assert {d.fiscal_year for d in form_990} == {2023, 2024, 2025}
    assert {d.fiscal_year for d in cash_flow} == {2023, 2024, 2025}
    assert {d.fiscal_year for d in financial_position} == {2023, 2024, 2025}


def test_local_document_source_read_bytes():
    source = LocalBenchmarkDocumentSource()
    docs = asyncio.run(source.list_documents(doc_type="cash_flow"))
    assert docs

    content, name = asyncio.run(source.read_bytes(docs[0]))
    assert name == docs[0].file_name
    assert content.startswith(b"%PDF")


def test_s3_document_source_lists_pdfs(monkeypatch):
    keys = [
        "form990 2024 filed.pdf",
        "Statement of Cash Flows 12312024.pdf",
        "Statement of Financial Position 12312024.pdf",
        "other-file.txt",
    ]

    class FakeS3Manager:
        async def list_objects(self, prefix: str = "") -> list[str]:
            assert prefix == "benchmark/"
            return keys

        async def get_object_bytes(self, s3_key: str) -> bytes:
            return b"%PDF-fake"

    source = S3BenchmarkDocumentSource(prefix="benchmark", bucket="test-bucket")
    source._s3 = FakeS3Manager()

    docs = asyncio.run(source.list_documents())
    assert len(docs) == 3
    assert {d.doc_type for d in docs} == {"form_990", "cash_flow", "financial_position"}

    content, name = asyncio.run(source.read_bytes(docs[0]))
    assert content == b"%PDF-fake"
    assert name == docs[0].file_name


def test_get_document_source_uses_s3_when_configured(monkeypatch):
    monkeypatch.setattr(
        "app.core.benchmark.document_source.settings.BENCHMARK_DOCS_SOURCE",
        "s3",
    )
    monkeypatch.setattr(
        "app.core.benchmark.document_source.settings.BENCHMARK_DOCS_S3_BUCKET",
        "test-bucket",
    )
    monkeypatch.setattr(
        "app.core.benchmark.document_source.settings.BUCKET_NAME",
        "",
    )
    source = get_document_source()
    assert isinstance(source, S3BenchmarkDocumentSource)


def test_years_from_period_single_year():
    assert years_from_period("2025-01-01", "2025-12-31") == [2025]


def test_years_from_period_multi_year():
    assert years_from_period("2023-01-01", "2025-12-31") == [2023, 2024, 2025]

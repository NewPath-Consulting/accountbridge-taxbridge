"""Unit tests for API schemas (PageRange, ExtractionRequest, TableInfo, etc.)."""

import pytest
from pydantic import ValidationError

from app.api.schemas.document import (
    FileType,
    PageRange,
    ExtractionRequest,
    ExtractionMethod,
    TableInfo,
    PageData,
    FormField,
    ExtractionResponse,
    ProcessingStatus,
)


def test_page_range_valid():
    """PageRange accepts start and optional end >= start."""
    r = PageRange(start=1, end=5)
    assert r.start == 1
    assert r.end == 5


def test_page_range_end_must_be_gte_start():
    """PageRange validates end >= start."""
    with pytest.raises(ValidationError):
        PageRange(start=5, end=3)


def test_extraction_request_defaults():
    """ExtractionRequest has expected defaults."""
    r = ExtractionRequest()
    assert r.process_with_llm is True
    assert r.extract_text is True
    assert r.extract_tables is True
    assert r.pages is None


def test_extraction_request_pages_empty_list_invalid():
    """ExtractionRequest rejects empty pages list."""
    with pytest.raises(ValidationError):
        ExtractionRequest(pages=[])


def test_extraction_request_pages_must_be_positive():
    """ExtractionRequest rejects page numbers < 1."""
    with pytest.raises(ValidationError):
        ExtractionRequest(pages=[0, 1])


def test_extraction_request_pages_valid():
    """ExtractionRequest accepts valid pages list."""
    r = ExtractionRequest(pages=[1, 3, 5])
    assert r.pages == [1, 3, 5]


def test_table_info_valid_rows_and_headers():
    """TableInfo accepts string rows and headers."""
    t = TableInfo(
        table_id="t1",
        page_number=1,
        headers=["A", "B"],
        rows=[["x", "y"], ["a", "b"]],
    )
    assert t.headers == ["A", "B"]
    assert t.rows == [["x", "y"], ["a", "b"]]


def test_table_info_empty_rows():
    """TableInfo accepts empty rows list."""
    t = TableInfo(
        table_id="t1",
        page_number=1,
        headers=["A", "B"],
        rows=[],
    )
    assert t.rows == []


def test_page_data_defaults():
    """PageData has empty defaults for optional collections."""
    p = PageData(page_number=1)
    assert p.page_number == 1
    assert p.text_content == ""
    assert p.tables == []
    assert p.forms == []
    assert p.images == []


def test_form_field():
    """FormField stores key and value."""
    f = FormField(key="name", value="John")
    assert f.key == "name"
    assert f.value == "John"


def test_extraction_response_required_fields():
    """ExtractionResponse requires document_id, file_name, file_type, status, etc."""
    r = ExtractionResponse(
        document_id="doc-1",
        file_name="f.pdf",
        file_type=FileType.PDF,
        status=ProcessingStatus.COMPLETED,
        method=ExtractionMethod.TEXTRACT,
        total_pages=1,
        pages_processed=1,
        pages_data=[],
        processing_time=0.0,
    )
    assert r.document_id == "doc-1"
    assert r.llm_output is None
    assert r.error_message is None

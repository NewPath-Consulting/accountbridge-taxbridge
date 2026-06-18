"""Unit tests for ExtractionService."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.api.schemas.document import (
    FileType,
    ExtractionRequest,
    ExtractionResponse,
    ExtractionMethod,
    ProcessingStatus,
    PageData,
)
from app.services.ingestion_service import ExtractionService


@pytest.fixture
def mock_extractor():
    """Extractor that returns a minimal ExtractionResponse."""
    ext = MagicMock()
    ext.get_extractor_name.return_value = "MockExtractor"
    async def _extract(**kwargs):
        doc_id = kwargs.get("document_id", "doc-1")
        return ExtractionResponse(
            document_id=doc_id,
            file_name=kwargs.get("file_name", "test.txt"),
            file_type=kwargs.get("file_type", FileType.TXT),
            status=ProcessingStatus.COMPLETED,
            method=ExtractionMethod.TEXTRACT,
            total_pages=1,
            pages_processed=1,
            pages_data=[PageData(page_number=1, text_content="Hello")],
            processing_time=0.1,
        )

    ext.extract = AsyncMock(side_effect=_extract)
    return ext


@pytest.fixture
def mock_llm_service():
    """LLM service that returns a fixed dict."""
    llm = MagicMock()
    llm.enhance_extraction = AsyncMock(return_value={"summary": "test"})
    return llm


@pytest.mark.asyncio
async def test_process_document_returns_extraction_response(mock_extractor, mock_llm_service):
    """process_document returns the extractor response when process_with_llm is False."""
    with patch("app.services.ingestion_service.ExtractorFactory") as mock_factory:
        with patch("app.services.ingestion_service.LLMService", return_value=mock_llm_service):
            mock_factory.create.return_value = mock_extractor
            service = ExtractionService()

    request = ExtractionRequest(
        method=ExtractionMethod.TEXTRACT,
        process_with_llm=False,
        extract_text=True,
        extract_tables=True,
        extract_images=True,
    )
    response = await service.process_document(
        file_path="",
        file_bytes=b"Hello",
        file_name="test.txt",
        file_type=FileType.TXT,
        request=request,
        document_id="doc-1",
    )
    assert response.document_id == "doc-1"
    assert response.file_name == "test.txt"
    assert response.file_type == FileType.TXT
    assert response.llm_output is None
    mock_extractor.extract.assert_called_once()
    mock_llm_service.enhance_extraction.assert_not_called()


@pytest.mark.asyncio
async def test_process_document_calls_llm_when_process_with_llm_true(mock_extractor, mock_llm_service):
    """When process_with_llm is True and pages_data present, LLM is called and output attached."""
    with patch("app.services.ingestion_service.ExtractorFactory") as mock_factory:
        with patch("app.services.ingestion_service.LLMService", return_value=mock_llm_service):
            mock_factory.create.return_value = mock_extractor
            service = ExtractionService()

    request = ExtractionRequest(
        method=ExtractionMethod.TEXTRACT,
        process_with_llm=True,
        extract_text=True,
        extract_tables=True,
        extract_images=True,
    )
    response = await service.process_document(
        file_path="",
        file_bytes=b"Hello",
        file_name="test.txt",
        file_type=FileType.TXT,
        request=request,
        document_id="doc-1",
    )
    assert response.llm_output == {"summary": "test"}
    mock_llm_service.enhance_extraction.assert_called_once()
    assert mock_llm_service.enhance_extraction.call_args[1]["extraction_response"] is response


@pytest.mark.asyncio
async def test_process_document_generates_document_id_when_none(mock_extractor, mock_llm_service):
    """When document_id is None, a UUID is generated."""
    with patch("app.services.ingestion_service.ExtractorFactory") as mock_factory:
        with patch("app.services.ingestion_service.LLMService", return_value=mock_llm_service):
            mock_factory.create.return_value = mock_extractor
            service = ExtractionService()

    request = ExtractionRequest(
        method=ExtractionMethod.TEXTRACT,
        process_with_llm=False,
        extract_text=True,
        extract_tables=True,
        extract_images=True,
    )
    response = await service.process_document(
        file_path="",
        file_bytes=b"Hi",
        file_name="x.txt",
        file_type=FileType.TXT,
        request=request,
        document_id=None,
    )
    assert response.document_id is not None
    assert len(response.document_id) > 0
    mock_extractor.extract.assert_called_once()
    call_kw = mock_extractor.extract.call_args[1]
    # Service generates a UUID and passes it to the extractor; response uses that id
    assert call_kw["document_id"] == response.document_id
    assert len(response.document_id) == 36  # UUID format

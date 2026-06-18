"""Unit tests for LLMService."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.api.schemas.document import (
    ExtractionResponse,
    FileType,
    ProcessingStatus,
    PageData,
)
from app.services.llm_service import LLMService


@pytest.fixture
def minimal_extraction_response():
    """Minimal ExtractionResponse for LLM input."""
    return ExtractionResponse(
        document_id="doc-1",
        file_name="test.txt",
        file_type=FileType.TXT,
        status=ProcessingStatus.COMPLETED,
        method="textract",
        total_pages=1,
        pages_processed=1,
        pages_data=[PageData(page_number=1, text_content="Some text")],
        processing_time=0.1,
    )


@pytest.mark.asyncio
async def test_enhance_extraction_returns_llm_result(minimal_extraction_response):
    """enhance_extraction returns the invoker's result when invoke_async succeeds."""
    mock_invoker = MagicMock()
    mock_invoker.invoke_async = AsyncMock(return_value={"result": {"key": "value"}})
    with patch("app.services.llm_service.LLMFactory") as mock_factory:
        mock_factory.create.return_value = mock_invoker
        service = LLMService()
        service._llm_invoker = mock_invoker

    result = await service.enhance_extraction(extraction_response=minimal_extraction_response)
    assert result == {"key": "value"}
    mock_invoker.invoke_async.assert_called_once()


@pytest.mark.asyncio
async def test_enhance_extraction_uses_custom_prompt(minimal_extraction_response):
    """When custom_prompt is provided, prompt body contains it."""
    mock_invoker = MagicMock()
    mock_invoker.invoke_async = AsyncMock(return_value={"result": {}})
    with patch("app.services.llm_service.LLMFactory") as mock_factory:
        mock_factory.create.return_value = mock_invoker
        service = LLMService()
        service._llm_invoker = mock_invoker

    await service.enhance_extraction(
        extraction_response=minimal_extraction_response,
        custom_prompt="Custom instruction",
    )
    call_body = mock_invoker.invoke_async.call_args[0][0]
    assert "messages" in call_body
    assert any("Custom instruction" in str(m) for m in call_body["messages"])


@pytest.mark.asyncio
async def test_enhance_extraction_raises_on_invoker_failure(minimal_extraction_response):
    """When invoke_async raises, enhance_extraction propagates the error."""
    mock_invoker = MagicMock()
    mock_invoker.invoke_async = AsyncMock(side_effect=RuntimeError("LLM error"))
    with patch("app.services.llm_service.LLMFactory") as mock_factory:
        mock_factory.create.return_value = mock_invoker
        service = LLMService()
        service._llm_invoker = mock_invoker

    with pytest.raises(RuntimeError) as exc_info:
        await service.enhance_extraction(extraction_response=minimal_extraction_response)
    assert "LLM error" in str(exc_info.value)

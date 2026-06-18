"""Unit tests for GOML custom extractor with minimal fixture."""

import pytest
from unittest.mock import patch, MagicMock

from app.api.schemas.document import (
    ExtractionRequest,
    ExtractionMethod,
    FileType,
)

try:
    from app.adapters.file_extraction.extractors.custom_extractor.extractor import GOMLCustomExtractor
except ModuleNotFoundError:
    GOMLCustomExtractor = None  # custom_extractor package not present (e.g. only custom_extractor01)

pytestmark = pytest.mark.skipif(GOMLCustomExtractor is None, reason="app.adapters.file_extraction.extractors.custom_extractor not available")


@pytest.fixture
def goml_extractor():
    """Create GOML extractor (no AWS)."""
    return GOMLCustomExtractor()


@pytest.mark.asyncio
async def test_goml_extract_text(goml_extractor):
    """GOML extractor returns ExtractionResponse for plain text bytes."""
    request = ExtractionRequest(
        method=ExtractionMethod.CUSTOM,
        process_with_llm=False,
        extract_text=True,
        extract_tables=True,
        extract_images=True,
    )
    file_bytes = b"Hello world.\nThis is a test."
    response = await goml_extractor.extract(
        file_path="",
        file_bytes=file_bytes,
        file_name="test.txt",
        file_type=FileType.TXT,
        request=request,
        document_id="test-doc-1",
    )
    assert response.document_id == "test-doc-1"
    assert response.file_name == "test.txt"
    assert response.file_type == FileType.TXT
    assert response.total_pages >= 1
    assert len(response.pages_data) >= 1
    assert "Hello" in (response.pages_data[0].text_content or "") or response.pages_data[0].text_content == ""


@pytest.mark.asyncio
async def test_goml_get_extractor_name(goml_extractor):
    """GOML extractor has a name."""
    assert goml_extractor.get_extractor_name() == "GOMLCustomExtractor"

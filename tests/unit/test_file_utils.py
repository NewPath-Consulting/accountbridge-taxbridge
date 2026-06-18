"""Unit tests for file_utils (FileValidator, TempFileManager, get_temp_dir)."""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from app.api.schemas.document import FileType
from app.utils.file_utils import (
    get_temp_dir,
    FileValidator,
    TempFileManager,
)


def test_get_temp_dir_returns_tmp_when_lambda():
    """In Lambda environment, get_temp_dir returns /tmp."""
    with patch.dict("os.environ", {"AWS_LAMBDA_FUNCTION_NAME": "test-fn"}):
        assert get_temp_dir() == "/tmp"


def test_get_temp_dir_returns_system_temp_when_not_lambda():
    """When not in Lambda, get_temp_dir returns system temp."""
    key = "AWS_LAMBDA_FUNCTION_NAME"
    old = os.environ.pop(key, None)
    try:
        result = get_temp_dir()
        assert result == tempfile.gettempdir()
    finally:
        if old is not None:
            os.environ[key] = old


def test_file_validator_mime_to_filetype():
    """MIME map includes expected types."""
    assert FileValidator.MIME_TO_FILETYPE["application/pdf"] == FileType.PDF
    assert FileValidator.MIME_TO_FILETYPE["text/plain"] == FileType.TXT
    assert FileValidator.MIME_TO_FILETYPE["image/png"] == FileType.IMAGE
    assert FileValidator.MIME_TO_FILETYPE["text/csv"] == FileType.CSV


def test_file_validator_file_signatures():
    """File signature map includes PDF and image magic bytes."""
    assert FileValidator.FILE_SIGNATURES[b"%PDF-"] == FileType.PDF
    assert FileValidator.FILE_SIGNATURES[b"\x89PNG\r\n\x1a\n"] == FileType.IMAGE


@pytest.mark.asyncio
async def test_detect_file_type_from_mime():
    """detect_file_type returns FileType from content_type when present."""
    file = MagicMock()
    file.content_type = "application/pdf"
    file.filename = "doc.pdf"
    file_bytes = b"%PDF-1.4"
    result = await FileValidator.detect_file_type(file, file_bytes)
    assert result == FileType.PDF


@pytest.mark.asyncio
async def test_detect_file_type_from_bytes_when_no_mime():
    """detect_file_type uses magic bytes when content_type not in map."""
    file = MagicMock()
    file.content_type = "application/octet-stream"
    file.filename = "doc.pdf"
    file_bytes = b"%PDF-1.4"
    result = await FileValidator.detect_file_type(file, file_bytes)
    assert result == FileType.PDF


@pytest.mark.asyncio
async def test_detect_file_type_from_extension():
    """detect_file_type falls back to extension when needed."""
    file = MagicMock()
    file.content_type = None
    file.filename = "data.csv"
    file_bytes = b"a,b,c\n1,2,3"
    result = await FileValidator.detect_file_type(file, file_bytes)
    assert result == FileType.CSV


@pytest.mark.asyncio
async def test_detect_file_type_raises_unsupported():
    """detect_file_type raises HTTPException for unsupported type."""
    from fastapi import HTTPException
    file = MagicMock()
    file.content_type = None
    file.filename = "file.xyz"
    file_bytes = b"unknown"
    with pytest.raises(HTTPException) as exc_info:
        await FileValidator.detect_file_type(file, file_bytes)
    assert exc_info.value.status_code == 415


@pytest.mark.asyncio
async def test_validate_file_size_returns_size_when_under_limit():
    """validate_file_size returns file size when under MAX_FILE_SIZE_MB."""
    file = MagicMock()
    file.file.seek = MagicMock()
    file.file.tell = MagicMock(return_value=1024)  # 1KB
    with patch("app.utils.file_utils.settings") as mock_settings:
        mock_settings.MAX_FILE_SIZE_MB = 100
        size = await FileValidator.validate_file_size(file)
    assert size == 1024


@pytest.mark.asyncio
async def test_validate_file_size_raises_when_over_limit():
    """validate_file_size raises HTTPException when file too large (413 or 400 from handler)."""
    from fastapi import HTTPException
    file = MagicMock()
    file.file.seek = MagicMock()
    file.file.tell = MagicMock(return_value=2 * 1024 * 1024)  # 2 MB
    mock_settings = MagicMock()
    mock_settings.MAX_FILE_SIZE_MB = 1  # 1 MB limit
    with patch("app.utils.file_utils.settings", mock_settings):
        with pytest.raises(HTTPException) as exc_info:
            await FileValidator.validate_file_size(file)
    # Implementation may raise 413 or wrap in 400; detail must mention size limit
    assert exc_info.value.status_code in (413, 400)
    assert "1MB" in str(exc_info.value.detail) or "too large" in str(exc_info.value.detail).lower()

"""Unit tests for ExtractorFactory."""

import sys
from types import ModuleType

import pytest
from unittest.mock import patch, MagicMock

from app.adapters.file_extraction.factory import ExtractorFactory


def _fake_goml_module():
    """Create a fake app.adapters.file_extraction.extractors.custom_extractor.extractor module so create() can import it."""
    mod = ModuleType("app.adapters.file_extraction.extractors.custom_extractor.extractor")
    mod.GOMLCustomExtractor = MagicMock()
    return mod


@patch("app.adapters.file_extraction.factory.get_settings")
def test_factory_creates_goml_custom_extractor_when_configured(mock_get_settings):
    """When EXTRACTOR_TYPE=goml_custom_extractor, factory returns GOMLCustomExtractor instance."""
    mock_get_settings.return_value = MagicMock(EXTRACTOR_TYPE="goml_custom_extractor")
    fake_mod = _fake_goml_module()
    instance = MagicMock()
    fake_mod.GOMLCustomExtractor.return_value = instance
    with patch.dict(sys.modules, {"app.adapters.file_extraction.extractors.custom_extractor.extractor": fake_mod}):
        result = ExtractorFactory.create()
    assert result is instance
    fake_mod.GOMLCustomExtractor.assert_called_once()


@patch("app.adapters.file_extraction.factory.get_settings")
def test_factory_creates_aws_textract_extractor_when_configured(mock_get_settings):
    """When EXTRACTOR_TYPE=AWS_textract, factory returns AWSTextractExtractor instance."""
    mock_get_settings.return_value = MagicMock(EXTRACTOR_TYPE="AWS_textract")
    with patch("app.adapters.file_extraction.extractors.textract.extractor.AWSTextractExtractor") as mock_textract:
        instance = MagicMock()
        mock_textract.return_value = instance
        result = ExtractorFactory.create()
        assert result is instance
        mock_textract.assert_called_once()


@patch("app.adapters.file_extraction.factory.get_settings")
def test_factory_raises_for_unknown_extractor_type(mock_get_settings):
    """When EXTRACTOR_TYPE is unknown, factory raises ValueError."""
    mock_get_settings.return_value = MagicMock(EXTRACTOR_TYPE="unknown_extractor")
    with pytest.raises(ValueError) as exc_info:
        ExtractorFactory.create()
    assert "Unknown EXTRACTOR_TYPE" in str(exc_info.value)
    assert "unknown_extractor" in str(exc_info.value)

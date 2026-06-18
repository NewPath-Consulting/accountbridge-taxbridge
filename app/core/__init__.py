"""
Core package: base extractor, factory, aws_textract, custom_extractor.

Usage:
    from app.core import ExtractorFactory
    extractor = ExtractorFactory.create()
"""

from app.adapters.file_extraction.extractors.base import BaseExtractor
from app.adapters.file_extraction.factory import ExtractorFactory

__all__ = ["BaseExtractor", "ExtractorFactory"]

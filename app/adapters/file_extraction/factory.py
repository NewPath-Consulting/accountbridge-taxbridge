"""Factory to create the configured extractor from settings."""

from app.config.settings import get_settings


class ExtractorFactory:
    """Creates the configured extractor based on EXTRACTOR_TYPE."""

    @staticmethod
    def create():
        """Create and return the extractor instance based on EXTRACTOR_TYPE."""
        settings = get_settings()
        if settings.EXTRACTOR_TYPE == "goml_custom_extractor":
            from app.adapters.file_extraction.extractors.custom_extractor.extractor import GOMLCustomExtractor
            return GOMLCustomExtractor()
        if settings.EXTRACTOR_TYPE == "AWS_textract":
            from app.adapters.file_extraction.extractors.textract.extractor import AWSTextractExtractor
            return AWSTextractExtractor()
        raise ValueError(f"Unknown EXTRACTOR_TYPE: {settings.EXTRACTOR_TYPE}")

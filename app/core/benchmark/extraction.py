"""In-process /extract wrapper for benchmark reference documents."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.api.schemas.document import (
    ExtractionRequest,
    ExtractionMethod,
    ExtractionResponse,
    FileType,
    ProcessingStatus,
)
from app.config.settings import settings
from app.core.benchmark.schemas import BenchmarkDocType
from app.core.prompts.benchmarking import (
    get_extraction_output_schema,
    get_extraction_prompt,
)
from app.core.benchmark.irs_xml import is_irs_xml, parse_form_990_xml, totals_agree
from app.utils.llm_json import coerce_llm_dict

logger = logging.getLogger(__name__)

_FORM_990_PAGES = [1, 9, 10, 11, 12]


def _reference_from_xml(
    file_bytes: bytes, file_name: str, doc_type: BenchmarkDocType
) -> ExtractionResponse:
    """Read a filed return out of IRS e-file XML, with no model in the loop."""
    if doc_type != "form_990":
        raise ValueError(
            f"IRS e-file XML carries a Form 990 return; {file_name} was offered "
            f"as {doc_type}"
        )

    extracted = parse_form_990_xml(file_bytes)
    for problem in totals_agree(extracted):
        # A reference that does not add up would be scored against the
        # pipeline, so say so rather than letting it look authoritative.
        logger.warning("IRS XML reference %s: %s", file_name, problem)

    summary = extracted.get("organization_summary") or {}
    return ExtractionResponse(
        document_id=f"irs-xml-{summary.get('tax_year') or file_name}",
        file_name=file_name,
        file_type=FileType.XML if hasattr(FileType, "XML") else FileType.PDF,
        status=ProcessingStatus.COMPLETED,
        method=ExtractionMethod.TEXTRACT,
        total_pages=0,
        pages_processed=0,
        processing_time=0.0,
        llm_output=extracted,
        metadata={
            "source": "irs_efile_xml",
            "return_type": summary.get("return_type"),
            "tax_year": summary.get("tax_year"),
        },
    )


async def extract_reference_document(
    file_bytes: bytes,
    file_name: str,
    doc_type: BenchmarkDocType,
    *,
    extraction_service=None,
    llm_service=None,
) -> ExtractionResponse:
    """
    Produce the reference figures a benchmark year is scored against.

    Ground truth is in ExtractionResponse.llm_output.

    An IRS e-file XML is read directly: every figure is a named element, so
    the reference is exact and no model is involved. A PDF has to go through
    Textract and a model, which means a disagreement with our own output says
    the two readings differ without saying which is wrong. Prefer the XML
    where it exists.
    """
    from app.services.ingestion_service import ExtractionService
    from app.services.llm_service import LLMService
    from app.utils.file_utils import FileValidator, TempFileManager

    if is_irs_xml(file_name):
        return _reference_from_xml(file_bytes, file_name, doc_type)

    extraction_service = extraction_service or ExtractionService()
    llm_service = llm_service or LLMService()

    temp_file_path: str | None = None
    try:
        temp_file_path = await FileValidator.create_temp_file(file_bytes, FileType.PDF)

        pages = _FORM_990_PAGES if doc_type == "form_990" else None
        request = ExtractionRequest(
            method=ExtractionMethod.TEXTRACT,
            process_with_llm=False,
            extract_text=True,
            extract_tables=True,
            extract_images=True,
            pages=pages,
        )

        response = await extraction_service.process_document(
            file_path=temp_file_path,
            file_bytes=file_bytes,
            file_name=file_name,
            file_type=FileType.PDF,
            request=request,
        )

        custom_prompt = get_extraction_prompt(doc_type)
        custom_output_format = get_extraction_output_schema(doc_type)

        llm_output = await llm_service.enhance_extraction(
            extraction_response=response,
            custom_prompt=custom_prompt,
            custom_output_format=custom_output_format,
            max_tokens=settings.BENCHMARK_LLM_MAX_TOKENS,
        )

        parsed = _coerce_llm_output(llm_output)
        response.llm_output = parsed
        return response

    finally:
        if temp_file_path:
            await TempFileManager.cleanup_temp_file(temp_file_path)


def _coerce_llm_output(llm_output: Any) -> Dict[str, Any]:
    """Normalize LLM response to a dict, salvaging JSON when needed."""
    return coerce_llm_dict(llm_output)

"""Extract organizationInformation from filed Form 990 pages 1-2 via Textract + LLM."""

from __future__ import annotations

import logging
from typing import Any

from app.api.schemas.document import (
    ExtractionMethod,
    ExtractionRequest,
    ExtractionResponse,
    FileType,
    ProcessingStatus,
)
from app.config.settings import settings
from app.core.benchmark.document_source import get_document_source
from app.core.benchmark.schemas import BenchmarkDocument
from app.core.prompts.form_990_organization import (
    ORGANIZATION_INFORMATION_SCHEMA,
    build_form_990_organization_extraction_prompt,
)
from app.utils.llm_json import salvage_json_object

logger = logging.getLogger(__name__)


def _parse_org_info_pages() -> list[int]:
    raw = getattr(settings, "FORM_990_ORG_INFO_PAGES", "1,2")
    pages: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            pages.append(int(part))
    return pages or [1, 2]


async def resolve_form_990_for_tax_year(end_date: str) -> BenchmarkDocument | None:
    """Pick Form 990 for tax year, falling back to the latest available filing."""
    try:
        tax_year = int(str(end_date)[:4])
    except (TypeError, ValueError):
        tax_year = None

    source = get_document_source()
    docs = await source.list_documents("form_990")
    if not docs:
        return None

    if tax_year is not None:
        for doc in docs:
            if doc.fiscal_year == tax_year:
                return doc

    return max(docs, key=lambda d: d.fiscal_year)


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def merge_organization_information(base: dict[str, Any], filed: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge organizationInformation; non-empty filed values win."""
    result = dict(base or {})
    filed = filed or {}

    for key, filed_value in filed.items():
        if key == "address" and isinstance(filed_value, dict):
            merged_address = dict(result.get("address") or {})
            for addr_key, addr_val in filed_value.items():
                if _is_nonempty(addr_val):
                    merged_address[addr_key] = addr_val
            result["address"] = merged_address
        elif key == "principalOfficer" and isinstance(filed_value, dict):
            merged_officer = dict(result.get("principalOfficer") or {})
            for officer_key, officer_val in filed_value.items():
                if _is_nonempty(officer_val):
                    merged_officer[officer_key] = officer_val
            result["principalOfficer"] = merged_officer
        elif key == "dbaNames" and isinstance(filed_value, list) and filed_value:
            result["dbaNames"] = filed_value
        elif key == "groupReturn" and isinstance(filed_value, bool):
            result["groupReturn"] = filed_value
        elif key == "groupExemptionNumber":
            if filed_value is not None:
                result["groupExemptionNumber"] = filed_value
        elif _is_nonempty(filed_value):
            result[key] = filed_value

    return result


def _extract_org_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Pull organizationInformation from a parsed JSON object."""
    if data.get("_parse_error"):
        return None
    if "organizationInformation" in data:
        org = data["organizationInformation"]
        return org if isinstance(org, dict) else None
    if "legalName" in data or "ein" in data:
        return data
    return None


def _coerce_organization_information(llm_output: Any) -> dict[str, Any] | None:
    """Normalize LLM response to organizationInformation dict."""
    from app.core.model_gateway.test_utils import extract_text

    if llm_output is None:
        return None

    if hasattr(llm_output, "model_dump"):
        try:
            llm_output = llm_output.model_dump()
        except Exception:
            pass

    if isinstance(llm_output, dict):
        org = _extract_org_block(llm_output)
        if org is not None:
            return org
        if "result" in llm_output:
            return _coerce_organization_information(llm_output["result"])
        if llm_output.get("choices") or llm_output.get("usage"):
            text = extract_text(llm_output)
            if text:
                return _coerce_organization_information(text)
        return None

    if isinstance(llm_output, str):
        parsed, _ = salvage_json_object(llm_output)
        if isinstance(parsed, dict):
            return _coerce_organization_information(parsed)
        return None

    text = extract_text(llm_output)
    if text:
        return _coerce_organization_information(text)
    return None


async def extract_organization_information_from_form_990(
    file_bytes: bytes,
    file_name: str,
    *,
    extraction_service=None,
    llm_service=None,
) -> dict[str, Any] | None:
    """
    Run Textract on pages 1-2 and structure with LLM into organizationInformation.

    Returns None on failure (non-fatal for callers).
    """
    from app.services.ingestion_service import ExtractionService
    from app.services.llm_service import LLMService
    from app.utils.file_utils import FileValidator, TempFileManager

    extraction_service = extraction_service or ExtractionService()
    llm_service = llm_service or LLMService()

    temp_file_path: str | None = None
    try:
        temp_file_path = await FileValidator.create_temp_file(file_bytes, FileType.PDF)
        pages = _parse_org_info_pages()

        request = ExtractionRequest(
            method=ExtractionMethod.TEXTRACT,
            process_with_llm=False,
            extract_text=True,
            extract_tables=True,
            extract_images=True,
            pages=pages,
        )

        response: ExtractionResponse = await extraction_service.process_document(
            file_path=temp_file_path,
            file_bytes=file_bytes,
            file_name=file_name,
            file_type=FileType.PDF,
            request=request,
        )

        if response.status == ProcessingStatus.FAILED or not response.pages_data:
            logger.warning(
                "Form 990 org extraction: Textract failed for %s: %s",
                file_name,
                response.error_message,
            )
            return None

        llm_output = await llm_service.enhance_extraction(
            extraction_response=response,
            custom_prompt=build_form_990_organization_extraction_prompt(),
            custom_output_format=ORGANIZATION_INFORMATION_SCHEMA,
            max_tokens=settings.BENCHMARK_LLM_MAX_TOKENS,
        )

        org_info = _coerce_organization_information(llm_output)
        if not org_info:
            preview = ""
            if isinstance(llm_output, dict):
                from app.core.model_gateway.test_utils import extract_text

                preview = (extract_text(llm_output) or str(llm_output))[:300]
            else:
                preview = str(llm_output)[:300]
            logger.warning(
                "Form 990 org extraction: could not parse LLM output for %s (preview=%s)",
                file_name,
                preview.replace("\n", " "),
            )
            return None

        logger.info("Form 990 org extraction succeeded for %s", file_name)
        return org_info

    except Exception as exc:
        logger.warning(
            "Form 990 org extraction failed for %s: %s",
            file_name,
            exc,
        )
        return None

    finally:
        if temp_file_path:
            await TempFileManager.cleanup_temp_file(temp_file_path)


async def load_filed_organization_information(end_date: str) -> dict[str, Any] | None:
    """Resolve and extract organizationInformation from the best-matching Form 990 in docs/."""
    doc = await resolve_form_990_for_tax_year(end_date)
    if not doc:
        logger.info("No Form 990 reference document found for tax year ending %s", end_date)
        return None

    source = get_document_source()
    try:
        file_bytes, file_name = await source.read_bytes(doc)
    except Exception as exc:
        logger.warning("Failed to read Form 990 %s: %s", doc.file_name, exc)
        return None

    logger.info(
        "Extracting organizationInformation from Form 990 %s (fiscal_year=%s)",
        file_name,
        doc.fiscal_year,
    )
    return await extract_organization_information_from_form_990(file_bytes, file_name)

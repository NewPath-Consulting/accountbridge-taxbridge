"""Document sources for benchmark reference PDFs."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from app.config.settings import settings
from app.core.benchmark.schemas import BenchmarkDocType, BenchmarkDocument
from app.utils.s3_utils import S3Manager

logger = logging.getLogger(__name__)

_FORM_990_PATTERN = re.compile(r"form990", re.IGNORECASE)
_CASH_FLOW_PATTERN = re.compile(r"statement of cash flows\s+(\d{8})", re.IGNORECASE)
_FINANCIAL_POSITION_PATTERN = re.compile(
    r"statement of financial position\s+(\d{8})", re.IGNORECASE
)
_FORM_990_YEAR_PATTERN = re.compile(r"form990\s+(\d{4})\s+filed", re.IGNORECASE)
_FORM_990_FINAL_SUBMISSION_PATTERN = re.compile(
    r"form990\s+final submission\s+(\d{2})(\d{2})(\d{4})",
    re.IGNORECASE,
)


def parse_fiscal_year_from_filename(file_name: str, doc_type: BenchmarkDocType) -> int | None:
    """Derive fiscal/tax year from a benchmark reference filename."""
    if doc_type == "cash_flow":
        match = _CASH_FLOW_PATTERN.search(file_name)
        if not match:
            return None
        date_suffix = match.group(1)
        return int(date_suffix[-4:])

    if doc_type == "financial_position":
        match = _FINANCIAL_POSITION_PATTERN.search(file_name)
        if not match:
            return None
        date_suffix = match.group(1)
        return int(date_suffix[-4:])

    if not _FORM_990_PATTERN.search(file_name):
        return None

    year_match = _FORM_990_YEAR_PATTERN.search(file_name)
    if year_match:
        return int(year_match.group(1))

    final_match = _FORM_990_FINAL_SUBMISSION_PATTERN.search(file_name)
    if final_match:
        filing_year = int(final_match.group(3))
        return filing_year - 1

    return None


def fiscal_year_to_period(fiscal_year: int) -> tuple[str, str]:
    """Return (start_date, end_date) for a calendar fiscal year."""
    return f"{fiscal_year}-01-01", f"{fiscal_year}-12-31"


def years_from_period(start_date: str, end_date: str) -> list[int]:
    """Derive fiscal years covered by a reports period (YYYY-MM-DD strings)."""
    try:
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
    except (TypeError, ValueError):
        return []

    if start_year > end_year:
        start_year, end_year = end_year, start_year

    return list(range(start_year, end_year + 1))


def _normalize_s3_prefix(prefix: str) -> str:
    """Ensure S3 prefix ends with / when non-empty."""
    cleaned = prefix.strip()
    if cleaned and not cleaned.endswith("/"):
        cleaned += "/"
    return cleaned


def _classify_benchmark_pdf(
    file_name: str,
    file_path: str,
    doc_types: list[BenchmarkDocType],
) -> BenchmarkDocument | None:
    """Return a BenchmarkDocument when file_name matches a supported doc type."""
    if not file_name.lower().endswith(".pdf"):
        return None

    for dtype in doc_types:
        if dtype == "form_990" and not _FORM_990_PATTERN.search(file_name):
            continue
        if dtype == "cash_flow" and not _CASH_FLOW_PATTERN.search(file_name):
            continue
        if dtype == "financial_position" and not _FINANCIAL_POSITION_PATTERN.search(
            file_name
        ):
            continue

        fiscal_year = parse_fiscal_year_from_filename(file_name, dtype)
        if fiscal_year is None:
            continue

        start_date, end_date = fiscal_year_to_period(fiscal_year)
        return BenchmarkDocument(
            doc_type=dtype,
            file_name=file_name,
            file_path=file_path,
            fiscal_year=fiscal_year,
            start_date=start_date,
            end_date=end_date,
        )

    return None


@runtime_checkable
class BenchmarkDocumentSource(Protocol):
    """Protocol for loading benchmark reference documents."""

    async def list_documents(
        self, doc_type: BenchmarkDocType | None = None
    ) -> list[BenchmarkDocument]:
        ...

    async def read_bytes(self, doc: BenchmarkDocument) -> tuple[bytes, str]:
        ...


class LocalBenchmarkDocumentSource:
    """Load benchmark reference PDFs from a local directory."""

    def __init__(self, base_path: str | None = None):
        raw = base_path or settings.BENCHMARK_DOCS_LOCAL_PATH
        self.base_path = Path(raw)
        if not self.base_path.is_absolute():
            project_root = Path(__file__).resolve().parents[3]
            self.base_path = project_root / raw

    async def list_documents(
        self, doc_type: BenchmarkDocType | None = None
    ) -> list[BenchmarkDocument]:
        if not self.base_path.is_dir():
            return []

        doc_types: list[BenchmarkDocType]
        if doc_type:
            doc_types = [doc_type]
        else:
            doc_types = ["form_990", "cash_flow", "financial_position"]

        documents: list[BenchmarkDocument] = []
        for path in sorted(self.base_path.iterdir()):
            if not path.is_file():
                continue

            doc = _classify_benchmark_pdf(path.name, str(path), doc_types)
            if doc:
                documents.append(doc)

        return documents

    async def read_bytes(self, doc: BenchmarkDocument) -> tuple[bytes, str]:
        path = Path(doc.file_path)
        return path.read_bytes(), doc.file_name


class S3BenchmarkDocumentSource:
    """Load benchmark reference PDFs from an S3 bucket prefix."""

    def __init__(self, prefix: str | None = None, bucket: str | None = None):
        self.prefix = _normalize_s3_prefix(
            prefix if prefix is not None else settings.BENCHMARK_DOCS_S3_PREFIX
        )
        self.bucket = (
            bucket
            or settings.BENCHMARK_DOCS_S3_BUCKET
            or settings.BUCKET_NAME
        )
        if not self.bucket:
            raise ValueError(
                "BENCHMARK_DOCS_S3_BUCKET or BUCKET_NAME is required when "
                "BENCHMARK_DOCS_SOURCE=s3"
            )
        self._s3 = S3Manager(bucket_name=self.bucket)

    async def list_documents(
        self, doc_type: BenchmarkDocType | None = None
    ) -> list[BenchmarkDocument]:
        doc_types: list[BenchmarkDocType]
        if doc_type:
            doc_types = [doc_type]
        else:
            doc_types = ["form_990", "cash_flow", "financial_position"]

        keys = await self._s3.list_objects(prefix=self.prefix)
        documents: list[BenchmarkDocument] = []

        for key in sorted(keys):
            if key.endswith("/"):
                continue

            file_name = Path(key).name
            doc = _classify_benchmark_pdf(file_name, key, doc_types)
            if doc:
                documents.append(doc)

        logger.info(
            "Listed %d benchmark document(s) from s3://%s/%s",
            len(documents),
            self.bucket,
            self.prefix or "",
        )
        return documents

    async def read_bytes(self, doc: BenchmarkDocument) -> tuple[bytes, str]:
        content = await self._s3.get_object_bytes(doc.file_path)
        return content, doc.file_name


def get_document_source(source: Literal["local", "s3"] | None = None) -> BenchmarkDocumentSource:
    """Factory for benchmark document sources."""
    selected = source or settings.BENCHMARK_DOCS_SOURCE
    if selected == "s3":
        return S3BenchmarkDocumentSource()
    return LocalBenchmarkDocumentSource()

"""Benchmark orchestration: reference extraction + split LLM evaluation."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.benchmark.compact import (
    compact_balance_sheet_report,
    compact_cash_flow_report,
    compact_manual_extraction,
    compact_tax_return_report,
)
from app.core.benchmark.document_source import (
    BenchmarkDocumentSource,
    get_document_source,
    years_from_period,
)
from app.core.benchmark.schemas import BenchmarkDocument, BenchmarkResult, YearBenchmarkResult
from app.core.benchmark.scoring import (
    blend_year_composite,
    build_cash_flow_scorecard,
    build_financial_position_scorecard,
    build_form_990_scorecard,
)
from app.core.prompts.benchmarking import (
    build_benchmark_cash_flow_prompt,
    build_benchmark_financial_position_prompt,
    build_benchmark_form_990_prompt,
    build_benchmark_synthesis_prompt,
)
from app.utils.llm_json import coerce_llm_dict

logger = logging.getLogger(__name__)


def _normalize_benchmark_review(review: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ensure stored review/synthesis dicts are parsed JSON, not raw LLM envelopes."""
    if not review or not isinstance(review, dict):
        return review
    if review.get("_parse_error"):
        return review
    if review.get("choices") or (review.get("usage") and not review.get("score")):
        return coerce_llm_dict(review)
    return review

_REQUIRED_REPORT_KEYS = ("cash_flow", "tax_return")


def validate_benchmark_reports(
    reports: Dict[str, Any],
    *,
    require_balance_sheet: bool = False,
) -> None:
    """Ensure client-provided reports contain required benchmark inputs."""
    missing = [k for k in _REQUIRED_REPORT_KEYS if k not in reports]
    if missing:
        raise ValueError(f"Missing required reports: {missing}")

    keys_to_check = list(_REQUIRED_REPORT_KEYS)
    if require_balance_sheet:
        keys_to_check.append("balance_sheet")

    for key in keys_to_check:
        entry = reports[key]
        if not isinstance(entry, dict):
            raise ValueError(f"Report '{key}' must be an object")
        if not entry.get("content"):
            raise ValueError(
                f"Report '{key}' has no content (status={entry.get('status')})"
            )


def _latest_reference_years(available: List[int]) -> List[int]:
    """Return the two most recent fiscal years with reference docs (or fewer if unavailable)."""
    if not available:
        return []
    return sorted(available)[-2:]


def resolve_benchmark_years(
    *,
    years: Optional[List[int]],
    start_date: str,
    end_date: str,
    docs_by_year: Dict[int, Dict[str, BenchmarkDocument]],
) -> tuple[List[int], Optional[str]]:
    """
    Choose fiscal years to benchmark against reference documents.

    When the reports period or explicit years have no matching reference PDFs,
    falls back to the latest and prior year available in docs/.
    """
    available = sorted(docs_by_year.keys())
    if not available:
        raise ValueError("No reference documents found in the configured document source")

    if years:
        target = [y for y in years if y in docs_by_year]
        if target:
            return target, None
        fallback = _latest_reference_years(available)
        note = (
            f"No reference documents for requested years {years}. "
            f"Using latest available reference years {fallback} instead."
        )
        logger.info(note)
        return fallback, note

    period_years = years_from_period(start_date, end_date)
    if period_years:
        target = [y for y in period_years if y in docs_by_year]
        if target:
            return target, None
        fallback = _latest_reference_years(available)
        note = (
            f"No reference documents for reports period {start_date}..{end_date} "
            f"(years {period_years}). Using latest available reference years "
            f"{fallback} instead."
        )
        logger.info(note)
        return fallback, note

    return available, None


def _synthesis_overall_score(synthesis: Dict[str, Any]) -> Optional[float]:
    """Extract overall score from synthesis (supports legacy nested schema)."""
    if synthesis.get("overall_score") is not None:
        return float(synthesis["overall_score"])
    summary = synthesis.get("benchmark_summary") or {}
    if summary.get("overall_score") is not None:
        return float(summary["overall_score"])
    return None


def _year_match_score(year_result: YearBenchmarkResult) -> Optional[float]:
    """Resolve a 0-1 match score from deterministic scorecard or synthesis."""
    scorecard = year_result.scorecard or {}
    if scorecard.get("adjusted_composite_score") is not None:
        return float(scorecard["adjusted_composite_score"]) / 100.0

    synthesis = year_result.synthesis or {}
    overall = _synthesis_overall_score(synthesis)
    if overall is not None:
        return overall / 100.0

    form_score = (year_result.form_990_review or {}).get("score")
    cash_score = (year_result.cash_flow_review or {}).get("score")
    fp_score = (year_result.financial_position_review or {}).get("score")
    if form_score is not None and cash_score is not None and fp_score is not None:
        return (float(form_score) + float(cash_score) + float(fp_score)) / 300.0
    if form_score is not None and cash_score is not None:
        blended = float(form_score) * 0.6 + float(cash_score) * 0.4
        return blended / 100.0
    if form_score is not None:
        return float(form_score) / 100.0
    if cash_score is not None:
        return float(cash_score) / 100.0
    return None


class BenchmarkService:
    """LLM-based benchmark of generated reports against manual reference documents."""

    def __init__(self, document_source: Optional[BenchmarkDocumentSource] = None):
        self.document_source = document_source or get_document_source()

    async def run_benchmark(
        self,
        reports: Dict[str, Any],
        years: Optional[List[int]] = None,
        *,
        start_date: str = "",
        end_date: str = "",
        wildapricot_account_id: str = "",
        quickbooks_realm_id: str = "",
        selected_document_files: Optional[List[str]] = None,
    ) -> BenchmarkResult:
        all_docs_preview = await self.document_source.list_documents()
        if selected_document_files:
            selected_set = set(selected_document_files)
            all_docs_preview = [
                doc for doc in all_docs_preview if doc.file_name in selected_set
            ]

        require_balance_sheet = any(
            doc.doc_type == "financial_position" for doc in all_docs_preview
        )
        validate_benchmark_reports(reports, require_balance_sheet=require_balance_sheet)

        request_id = str(uuid.uuid4())
        start_time = time.time()

        all_docs = await self.document_source.list_documents()

        if selected_document_files:
            selected_set = set(selected_document_files)
            all_docs = [doc for doc in all_docs if doc.file_name in selected_set]
            if not all_docs:
                raise ValueError(
                    "None of the selected document files were found in the reference library. "
                    "Check GET /api/benchmark/reports for available file names."
                )
            logger.info(
                "Benchmark filtered to %d selected document(s): %s",
                len(all_docs),
                [d.file_name for d in all_docs],
            )

        docs_by_year = _group_documents_by_year(all_docs)

        target_years, year_resolution_note = resolve_benchmark_years(
            years=years,
            start_date=start_date,
            end_date=end_date,
            docs_by_year=docs_by_year,
        )

        logger.info(
            "Benchmark run start request_id=%s target_years=%s period=%s..%s "
            "available_doc_years=%s explicit_years=%s",
            request_id,
            target_years,
            start_date,
            end_date,
            sorted(docs_by_year.keys()),
            years,
        )

        results: Dict[str, YearBenchmarkResult] = {}
        scores: List[float] = []
        had_failure = False
        had_partial = False

        tax_return_compact = compact_tax_return_report(reports["tax_return"])
        cash_flow_compact = compact_cash_flow_report(reports["cash_flow"])
        balance_sheet_compact = (
            compact_balance_sheet_report(reports["balance_sheet"])
            if reports.get("balance_sheet")
            else None
        )

        for year in target_years:
            year_docs = docs_by_year.get(year, {})
            prior_year_docs = docs_by_year.get(year - 1, {})
            year_result = await self._benchmark_year(
                year=year,
                year_docs=year_docs,
                prior_year_docs=prior_year_docs,
                tax_return_report=tax_return_compact,
                cash_flow_report=cash_flow_compact,
                balance_sheet_report=balance_sheet_compact,
                reports_raw=reports,
                data_quality_warnings=reports.get("data_quality_warnings"),
            )
            results[str(year)] = year_result

            synthesis = year_result.synthesis or {}
            overall = _year_match_score(year_result)
            if overall is not None:
                scores.append(overall)

            if year_result.status == "failed":
                had_failure = True
            elif year_result.status == "partial":
                had_partial = True

        overall_score = sum(scores) / len(scores) if scores else 0.0
        if had_failure and not scores:
            status = "failed"
        elif had_failure or had_partial:
            status = "partial"
        else:
            status = "completed"

        total_elapsed = time.time() - start_time
        logger.info(
            "Benchmark run complete request_id=%s status=%s years=%s "
            "overall_score=%.3f elapsed=%.2fs",
            request_id,
            status,
            target_years,
            overall_score,
            total_elapsed,
        )

        return BenchmarkResult(
            request_id=request_id,
            start_date=start_date,
            end_date=end_date,
            wildapricot_account_id=wildapricot_account_id,
            quickbooks_realm_id=quickbooks_realm_id,
            years_benchmarked=target_years,
            year_resolution_note=year_resolution_note,
            results=results,
            overall_match_score=overall_score,
            total_processing_time=total_elapsed,
            status=status,
        )

    async def _benchmark_year(
        self,
        *,
        year: int,
        year_docs: Dict[str, BenchmarkDocument],
        prior_year_docs: Dict[str, BenchmarkDocument],
        tax_return_report: Dict[str, Any],
        cash_flow_report: Dict[str, Any],
        balance_sheet_report: Optional[Dict[str, Any]],
        reports_raw: Dict[str, Any],
        data_quality_warnings: Optional[List[str]] = None,
    ) -> YearBenchmarkResult:
        logger.info("Benchmark year=%s start", year)
        year_started = time.monotonic()

        reference_extractions: Dict[str, Any] = {}
        form_990_review: Optional[Dict[str, Any]] = None
        cash_flow_review: Optional[Dict[str, Any]] = None
        financial_position_review: Optional[Dict[str, Any]] = None
        synthesis: Optional[Dict[str, Any]] = None
        form_990_scorecard: Optional[Dict[str, Any]] = None
        cash_flow_scorecard: Optional[Dict[str, Any]] = None
        financial_position_scorecard: Optional[Dict[str, Any]] = None
        errors: List[str] = []
        status = "completed"

        reports_context = {
            **reports_raw,
            "data_quality_warnings": data_quality_warnings or [],
        }

        prior_year_990: Dict[str, Any] = {}
        if "form_990" in prior_year_docs:
            try:
                from app.core.benchmark.extraction import extract_reference_document

                file_bytes, file_name = await self.document_source.read_bytes(
                    prior_year_docs["form_990"]
                )
                extraction = await extract_reference_document(
                    file_bytes=file_bytes,
                    file_name=file_name,
                    doc_type="form_990",
                )
                prior_year_990 = compact_manual_extraction(extraction.llm_output or {})
                reference_extractions["prior_year_form_990"] = prior_year_990
            except Exception as exc:
                logger.warning("Prior-year Form 990 extraction failed for %s: %s", year, exc)

        prior_year_fp: Dict[str, Any] = {}
        if "financial_position" in prior_year_docs:
            try:
                from app.core.benchmark.extraction import extract_reference_document

                file_bytes, file_name = await self.document_source.read_bytes(
                    prior_year_docs["financial_position"]
                )
                extraction = await extract_reference_document(
                    file_bytes=file_bytes,
                    file_name=file_name,
                    doc_type="financial_position",
                )
                prior_year_fp = compact_manual_extraction(extraction.llm_output or {})
                reference_extractions["prior_year_financial_position"] = prior_year_fp
            except Exception as exc:
                logger.warning(
                    "Prior-year financial position extraction failed for %s: %s",
                    year,
                    exc,
                )

        manual_990: Dict[str, Any] = {}
        if "form_990" in year_docs:
            try:
                from app.core.benchmark.extraction import extract_reference_document

                file_bytes, file_name = await self.document_source.read_bytes(
                    year_docs["form_990"]
                )
                step_started = time.monotonic()
                logger.info(
                    "Benchmark year=%s step=form_990_extract start file=%s",
                    year,
                    file_name,
                )
                extraction = await extract_reference_document(
                    file_bytes=file_bytes,
                    file_name=file_name,
                    doc_type="form_990",
                )
                logger.info(
                    "Benchmark year=%s step=form_990_extract done elapsed=%.2fs",
                    year,
                    time.monotonic() - step_started,
                )
                manual_990 = compact_manual_extraction(extraction.llm_output or {})
                reference_extractions["form_990"] = manual_990

                form_990_scorecard = build_form_990_scorecard(
                    fiscal_year=year,
                    manual_extraction=manual_990,
                    prior_year_extraction=prior_year_990 or None,
                    ai_report=tax_return_report,
                    cash_flow_report=cash_flow_report,
                    reports_raw=reports_context,
                )

                prompt = build_benchmark_form_990_prompt(
                    year,
                    manual_990,
                    tax_return_report,
                    prior_year_extraction=prior_year_990 or None,
                    deterministic_scorecard=form_990_scorecard,
                )
                from app.core.benchmark.llm import run_benchmark_llm

                form_990_review, err = await run_benchmark_llm(
                    prompt, step=f"year={year}/form_990_review"
                )
                form_990_review = _normalize_benchmark_review(form_990_review) or {}
                if err:
                    errors.append(f"form_990 LLM: {err}")
                if form_990_review.get("_parse_error"):
                    status = "partial"
                else:
                    form_990_review["score"] = form_990_scorecard.get(
                        "adjusted_composite_score"
                    )
                    form_990_review["dimension_scores"] = {
                        k: (form_990_scorecard.get("dimensions") or {})
                        .get(k, {})
                        .get("score")
                        for k in (
                            "accuracy",
                            "reconciliation",
                            "completeness",
                            "audit_quality",
                        )
                    }
                    form_990_review["confound_flags"] = form_990_scorecard.get(
                        "confound_flags", []
                    )
            except Exception as exc:
                logger.error("Form 990 benchmark failed for %s: %s", year, exc)
                errors.append(f"form_990: {exc}")
                status = "failed"
        else:
            errors.append(f"form_990: no reference document for {year}")

        manual_cf: Dict[str, Any] = {}
        if "cash_flow" in year_docs:
            try:
                from app.core.benchmark.extraction import extract_reference_document

                file_bytes, file_name = await self.document_source.read_bytes(
                    year_docs["cash_flow"]
                )
                step_started = time.monotonic()
                logger.info(
                    "Benchmark year=%s step=cash_flow_extract start file=%s",
                    year,
                    file_name,
                )
                extraction = await extract_reference_document(
                    file_bytes=file_bytes,
                    file_name=file_name,
                    doc_type="cash_flow",
                )
                logger.info(
                    "Benchmark year=%s step=cash_flow_extract done elapsed=%.2fs",
                    year,
                    time.monotonic() - step_started,
                )
                manual_cf = compact_manual_extraction(extraction.llm_output or {})
                reference_extractions["cash_flow"] = manual_cf

                cash_flow_scorecard = build_cash_flow_scorecard(
                    fiscal_year=year,
                    manual_extraction=manual_cf,
                    ai_report=cash_flow_report,
                    reports_raw=reports_context,
                )

                prompt = build_benchmark_cash_flow_prompt(
                    year,
                    manual_cf,
                    cash_flow_report,
                    deterministic_scorecard=cash_flow_scorecard,
                )
                from app.core.benchmark.llm import run_benchmark_llm

                cash_flow_review, err = await run_benchmark_llm(
                    prompt, step=f"year={year}/cash_flow_review"
                )
                cash_flow_review = _normalize_benchmark_review(cash_flow_review) or {}
                if err:
                    errors.append(f"cash_flow LLM: {err}")
                if cash_flow_review.get("_parse_error"):
                    status = "partial" if status != "failed" else status
                else:
                    cash_flow_review["score"] = cash_flow_scorecard.get(
                        "adjusted_composite_score"
                    )
                    cash_flow_review["dimension_scores"] = {
                        k: (cash_flow_scorecard.get("dimensions") or {})
                        .get(k, {})
                        .get("score")
                        for k in (
                            "accuracy",
                            "reconciliation",
                            "completeness",
                            "audit_quality",
                        )
                    }
                    cash_flow_review["confound_flags"] = cash_flow_scorecard.get(
                        "confound_flags", []
                    )
            except Exception as exc:
                logger.error("Cash flow benchmark failed for %s: %s", year, exc)
                errors.append(f"cash_flow: {exc}")
                status = "failed"
        else:
            errors.append(f"cash_flow: no reference document for {year}")

        manual_fp: Dict[str, Any] = {}
        if "financial_position" in year_docs:
            if not balance_sheet_report:
                errors.append(
                    f"financial_position: balance_sheet report required but missing for {year}"
                )
                status = "partial" if status != "failed" else status
            else:
                try:
                    from app.core.benchmark.extraction import extract_reference_document

                    file_bytes, file_name = await self.document_source.read_bytes(
                        year_docs["financial_position"]
                    )
                    step_started = time.monotonic()
                    logger.info(
                        "Benchmark year=%s step=financial_position_extract start file=%s",
                        year,
                        file_name,
                    )
                    extraction = await extract_reference_document(
                        file_bytes=file_bytes,
                        file_name=file_name,
                        doc_type="financial_position",
                    )
                    logger.info(
                        "Benchmark year=%s step=financial_position_extract done elapsed=%.2fs",
                        year,
                        time.monotonic() - step_started,
                    )
                    manual_fp = compact_manual_extraction(extraction.llm_output or {})
                    reference_extractions["financial_position"] = manual_fp

                    financial_position_scorecard = build_financial_position_scorecard(
                        fiscal_year=year,
                        manual_extraction=manual_fp,
                        prior_year_extraction=prior_year_fp or None,
                        ai_report=balance_sheet_report,
                        reports_raw=reports_context,
                    )

                    prompt = build_benchmark_financial_position_prompt(
                        year,
                        manual_fp,
                        balance_sheet_report,
                        prior_year_extraction=prior_year_fp or None,
                        prior_year_balance_sheet=reports_raw.get(
                            "prior_year_balance_sheet"
                        ),
                        deterministic_scorecard=financial_position_scorecard,
                    )
                    from app.core.benchmark.llm import run_benchmark_llm

                    financial_position_review, err = await run_benchmark_llm(
                        prompt, step=f"year={year}/financial_position_review"
                    )
                    financial_position_review = (
                        _normalize_benchmark_review(financial_position_review) or {}
                    )
                    if err:
                        errors.append(f"financial_position LLM: {err}")
                    if financial_position_review.get("_parse_error"):
                        status = "partial" if status != "failed" else status
                    else:
                        financial_position_review["score"] = (
                            financial_position_scorecard.get("adjusted_composite_score")
                        )
                        financial_position_review["dimension_scores"] = {
                            k: (financial_position_scorecard.get("dimensions") or {})
                            .get(k, {})
                            .get("score")
                            for k in (
                                "accuracy",
                                "reconciliation",
                                "completeness",
                                "audit_quality",
                            )
                        }
                        financial_position_review["confound_flags"] = (
                            financial_position_scorecard.get("confound_flags", [])
                        )
                except Exception as exc:
                    logger.error(
                        "Financial position benchmark failed for %s: %s", year, exc
                    )
                    errors.append(f"financial_position: {exc}")
                    status = "failed"

        year_scorecard: Optional[Dict[str, Any]] = None
        if form_990_scorecard and cash_flow_scorecard:
            year_scorecard = {
                "form_990": form_990_scorecard,
                "cash_flow": cash_flow_scorecard,
                "adjusted_composite_score": round(
                    blend_year_composite(
                        form_990_scorecard,
                        cash_flow_scorecard,
                        financial_position_scorecard,
                    )
                    * 100,
                    2,
                ),
                "composite_rating": form_990_scorecard.get("composite_rating"),
            }
            if financial_position_scorecard:
                year_scorecard["financial_position"] = financial_position_scorecard

        reviews_ready = (
            form_990_review
            and cash_flow_review
            and not form_990_review.get("_parse_error")
            and not cash_flow_review.get("_parse_error")
        )
        if financial_position_scorecard:
            reviews_ready = reviews_ready and bool(
                financial_position_review
                and not financial_position_review.get("_parse_error")
            )

        if reviews_ready:
            processing_metadata = {
                "tax_return_processing_time": reports_raw.get("tax_return", {}).get(
                    "processing_time"
                ),
                "cash_flow_processing_time": reports_raw.get("cash_flow", {}).get(
                    "processing_time"
                ),
                "balance_sheet_processing_time": (
                    reports_raw.get("balance_sheet") or {}
                ).get("processing_time"),
                "tax_return_status": reports_raw.get("tax_return", {}).get("status"),
                "cash_flow_status": reports_raw.get("cash_flow", {}).get("status"),
                "balance_sheet_status": (reports_raw.get("balance_sheet") or {}).get(
                    "status"
                ),
            }
            prompt = build_benchmark_synthesis_prompt(
                year,
                form_990_review,
                cash_flow_review,
                processing_metadata,
                form_990_scorecard=form_990_scorecard,
                cash_flow_scorecard=cash_flow_scorecard,
                financial_position_result=financial_position_review,
                financial_position_scorecard=financial_position_scorecard,
            )
            from app.core.benchmark.llm import run_benchmark_llm

            synthesis, err = await run_benchmark_llm(
                prompt, step=f"year={year}/synthesis"
            )
            synthesis = _normalize_benchmark_review(synthesis) or {}
            if err:
                errors.append(f"synthesis LLM: {err}")
            if synthesis.get("_parse_error"):
                status = "partial" if status != "failed" else status
            elif year_scorecard:
                synthesis["overall_score"] = year_scorecard["adjusted_composite_score"]
                synthesis["scorecard"] = year_scorecard
        elif status != "failed":
            status = "partial"

        if errors and synthesis is None:
            synthesis = {"errors": errors}
            if year_scorecard:
                synthesis["overall_score"] = year_scorecard["adjusted_composite_score"]
                synthesis["scorecard"] = year_scorecard

        logger.info(
            "Benchmark year=%s done status=%s elapsed=%.2fs errors=%s",
            year,
            status,
            time.monotonic() - year_started,
            len(errors),
        )

        return YearBenchmarkResult(
            fiscal_year=year,
            form_990_review=form_990_review,
            cash_flow_review=cash_flow_review,
            financial_position_review=financial_position_review,
            synthesis=synthesis,
            scorecard=year_scorecard,
            reference_extractions=reference_extractions or None,
            status=status,
        )


def _group_documents_by_year(
    documents: List[BenchmarkDocument],
) -> Dict[int, Dict[str, BenchmarkDocument]]:
    grouped: Dict[int, Dict[str, BenchmarkDocument]] = {}
    for doc in documents:
        grouped.setdefault(doc.fiscal_year, {})[doc.doc_type] = doc
    return grouped

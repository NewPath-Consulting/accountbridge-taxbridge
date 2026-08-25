"""Service for generating financial reports from WildApricot and QuickBooks data."""
import asyncio
import json
import logging
import time
from typing import Dict, Any, Tuple, Callable, Awaitable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.api.schemas.reports import QuickBooksCredentialsInline
import uuid

from app.adapters.llm.llm import _extract_json_from_llm_response
from app.utils.llm_json import salvage_json_object
from app.utils.tax_return_llm import (
    compact_quickbooks_for_reconciliation,
    compact_source_data_for_tax_return,
    compact_tax_return_financial_parts_for_reconciliation,
    derive_organization_details,
)
from app.utils.form_990_organization import (
    load_filed_organization_information,
    merge_organization_information,
)
from app.adapters.wildapricot.client import WildApricotClient
from app.adapters.wildapricot.workflow import run_extraction_workflow
from app.adapters.quickbooks.client import QuickBooksClient
from app.adapters.quickbooks.exceptions import (
    QuickBooksAuthError,
    QuickBooksRefreshTokenRequiredError,
)
from app.utils.postprocess_quickbooks import postprocess_quickbooks_data
from app.utils.postprocess_wildapricot import postprocess_wildapricot_data
from app.utils.llm_source_summary import (
    assess_data_quality_warnings,
    build_llm_inputs,
    build_reference_financials_from_qb,
    wildapricot_period_empty,
)
from app.utils.form_990_enforce import enforce_deterministic_amounts
from app.utils.form_990_propagate import propagate_enforced_totals
from app.utils.form_990_mapping import build_qb_mapping_hints
from app.utils.quickbooks_periods import prior_year_balance_sheet_period
from app.utils.report_normalization import (
    build_organization_summary,
    ensure_balance_sheet_mandatory_fields,
    ensure_part_ix_minimum_fields,
    ensure_part_x_mandatory_fields,
    normalize_tax_return_content,
)
from app.core.prompts.report_prompts import (
    build_cash_flow_report_prompt,
    build_balance_sheet_report_prompt,
    build_tax_return_part_viii_prompt,
    build_tax_return_part_ix_prompt,
    build_tax_return_part_x_prompt,
    build_tax_return_parts_i_vii_xi_xii_prompt,
    build_tax_return_reconciliation_prompt,
)
from app.core.model_gateway.aim_main import acompletion
from app.core.model_gateway.test_utils import extract_text
from app.config.settings import settings

logger = logging.getLogger(__name__)

_TAX_RETURN_COMPACT_RETRY = (
    "Your previous response was invalid or truncated JSON. "
    "Return ONLY valid, complete JSON matching the required schema."
)

_TAX_RETURN_TRUNCATION_RETRY = (
    "Your previous response was truncated before the JSON completed. "
    "Return ONLY valid, complete JSON. For Part IX: emit AT MOST 25 objects in "
    "partIX_expenses (IRS lines 1-25), aggregating QuickBooks accounts into those "
    "lines — never one object per QuickBooks account. Omit long labels and optional fields."
)


class ReportsService:
    """Service for generating financial reports."""

    def __init__(self):
        logger.info("ReportsService initialized")
        self._raw_pl_report: Dict[str, Any] = {}

    async def generate_reports(
        self,
        wildapricot_account_id: str,
        quickbooks_realm_id: str,
        start_date: str,
        end_date: str,
        request_id: str = None,
        wildapricot_data: Optional[Dict[str, Any]] = None,
        quickbooks_credentials: Optional["QuickBooksCredentialsInline"] = None,
        user_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate all three reports sequentially from WildApricot and QuickBooks data.
        """
        if request_id is None:
            request_id = str(uuid.uuid4())

        start_time = time.time()
        logger.info(f"Starting reports generation request_id={request_id}")

        try:
            logger.info(
                f"Fetching source data (QuickBooks, then WildApricot) request_id={request_id}"
            )
            wildapricot_data, quickbooks_data = await self._fetch_source_data(
                wildapricot_account_id,
                quickbooks_realm_id,
                start_date,
                end_date,
                wildapricot_data=wildapricot_data,
                quickbooks_credentials=quickbooks_credentials,
            )

            logger.info(f"Postprocessing source data request_id={request_id}")
            wildapricot_data = postprocess_wildapricot_data(wildapricot_data)
            quickbooks_data = postprocess_quickbooks_data(quickbooks_data)
            self._raw_pl_report = (
                (quickbooks_data.get("profit_and_loss") or {}).get("raw") or {}
            )

            llm_inputs = build_llm_inputs(
                wildapricot_data,
                quickbooks_data,
                max_wa_records_per_entity=settings.REPORTS_WA_MAX_RECORDS_PER_ENTITY,
                max_wa_financial_records_per_entity=settings.REPORTS_WA_FINANCIAL_RECORDS_PER_ENTITY,
            )
            data_quality_warnings = assess_data_quality_warnings(
                llm_inputs["wildapricot"],
                llm_inputs["quickbooks"],
                start_date=start_date,
                end_date=end_date,
            )
            reference_financials = build_reference_financials_from_qb(
                llm_inputs["quickbooks"]
            )
            if data_quality_warnings:
                for warning in data_quality_warnings:
                    logger.warning("%s request_id=%s", warning, request_id)

            logger.info(f"Successfully fetched source data request_id={request_id}")

            logger.info(
                "Generating reports sequentially request_id=%s user_prompt=%s "
                "(filed PDF Textract: Form 990 pages 1-2 only, during tax return)",
                request_id,
                "yes" if user_prompt and user_prompt.strip() else "no",
            )
            reports = await self._generate_reports_sequential(
                llm_inputs["wildapricot"],
                llm_inputs["quickbooks"],
                start_date,
                end_date,
                user_prompt=user_prompt,
                reference_financials=reference_financials,
            )

            total_time = time.time() - start_time
            failed_count = sum(1 for r in reports.values() if r.get("status") == "failed")
            partial_count = sum(1 for r in reports.values() if r.get("status") == "partial")
            if failed_count == len(reports):
                overall_status = "failed"
            elif failed_count > 0 or partial_count > 0:
                overall_status = "partial"
            else:
                overall_status = "completed"

            logger.info(
                f"Reports generation finished request_id={request_id} "
                f"status={overall_status} total_time={total_time:.2f}s"
            )

            result = {
                "request_id": request_id,
                "wildapricot_account_id": wildapricot_account_id,
                "quickbooks_realm_id": quickbooks_realm_id,
                "start_date": start_date,
                "end_date": end_date,
                "reports": reports,
                "data_quality_warnings": data_quality_warnings,
                "quickbooks_source": {
                    "prior_year_balance_sheet": llm_inputs["quickbooks"].get(
                        "prior_year_balance_sheet"
                    ),
                },
                "total_processing_time": total_time,
                "status": overall_status,
            }
            return result

        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"Reports generation failed request_id={request_id}: {str(e)}")
            raise

    async def _fetch_source_data(
        self,
        wildapricot_account_id: str,
        quickbooks_realm_id: str,
        start_date: str,
        end_date: str,
        wildapricot_data: Optional[Dict[str, Any]] = None,
        quickbooks_credentials: Optional["QuickBooksCredentialsInline"] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Fetch QuickBooks first, then WildApricot (or reuse cached WA on QB retry)."""
        qb_client_kwargs: Dict[str, Any] = {}
        if quickbooks_credentials is not None:
            qb_client_kwargs = {
                "client_id": quickbooks_credentials.client_id,
                "client_secret": quickbooks_credentials.client_secret,
                "refresh_token": quickbooks_credentials.refresh_token,
                "access_token": quickbooks_credentials.access_token,
                "realm_id": quickbooks_credentials.realm_id or quickbooks_realm_id,
            }
        qb_client = QuickBooksClient(**qb_client_kwargs)

        async def fetch_wildapricot() -> Dict[str, Any]:
            return await asyncio.to_thread(
                run_extraction_workflow,
                donation_start_date=start_date,
                donation_end_date=end_date,
                client=WildApricotClient(account_id=wildapricot_account_id),
                save_json=False,
                save_csv=False,
            )

        async def fetch_quickbooks() -> Dict[str, Any]:
            profit_loss_data = await qb_client.get_profit_and_loss(
                realm_id=quickbooks_realm_id,
                start_date=start_date,
                end_date=end_date,
            )

            balance_sheet_data = await qb_client.get_balance_sheet(
                realm_id=quickbooks_realm_id,
                start_date=start_date,
                end_date=end_date,
            )

            prior_year_balance_sheet = None
            prior_period = prior_year_balance_sheet_period(start_date)
            if prior_period:
                prior_start, prior_end = prior_period
                logger.info(
                    "Fetching prior-year QuickBooks balance sheet %s to %s",
                    prior_start,
                    prior_end,
                )
                prior_year_balance_sheet = await qb_client.get_balance_sheet(
                    realm_id=quickbooks_realm_id,
                    start_date=prior_start,
                    end_date=prior_end,
                    output_filename="prior-year-balance-sheet.json",
                )

            qb_payload: Dict[str, Any] = {
                "profit_and_loss": profit_loss_data,
                "balance_sheet": balance_sheet_data,
            }
            if prior_year_balance_sheet is not None:
                qb_payload["prior_year_balance_sheet"] = prior_year_balance_sheet
            return qb_payload

        try:
            await asyncio.to_thread(qb_client._token_manager.get_valid_token)
            logger.info("Fetching QuickBooks data")
            qb_data = await fetch_quickbooks()
        except QuickBooksRefreshTokenRequiredError as exc:
            raise QuickBooksRefreshTokenRequiredError(
                str(exc),
                wildapricot_data=wildapricot_data,
            ) from exc
        except QuickBooksAuthError as exc:
            raise QuickBooksRefreshTokenRequiredError(
                str(exc),
                wildapricot_data=wildapricot_data,
            ) from exc

        if wildapricot_data is None:
            logger.info("Fetching WildApricot data")
            wa_data = await fetch_wildapricot()
        else:
            logger.info("Using cached WildApricot data (QuickBooks retry)")
            wa_data = wildapricot_data

        return wa_data, qb_data

    async def _generate_reports_sequential(
        self,
        wildapricot_summary: Dict[str, Any],
        quickbooks_summary: Dict[str, Any],
        start_date: str,
        end_date: str,
        user_prompt: Optional[str] = None,
        reference_financials: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Generate reports one at a time to reduce Bedrock load and timeouts."""
        generators: list[tuple[str, Callable[..., Awaitable[Dict[str, Any]]]]] = [
            ("cash_flow", self._generate_cash_flow_report),
            ("balance_sheet", self._generate_balance_sheet_report),
            ("tax_return", self._generate_tax_return_report),
        ]

        reports: Dict[str, Dict[str, Any]] = {}
        for report_type, generator in generators:
            try:
                reports[report_type] = await generator(
                    wildapricot_summary,
                    quickbooks_summary,
                    start_date,
                    end_date,
                    user_prompt,
                    reference_financials=reference_financials,
                )
            except Exception as exc:
                logger.error(f"Report generation failed for {report_type}: {exc}")
                reports[report_type] = {
                    "report_type": report_type,
                    "content": {},
                    "processing_time": 0.0,
                    "status": "failed",
                    "error_message": str(exc),
                }

        return reports

    async def _call_report_llm(
        self,
        prompt_body: Dict[str, Any],
        *,
        max_tokens: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], Optional[str], bool]:
        response = await acompletion(
            model=settings.LLM_MODEL,
            custom_llm_provider=settings.LLM_PROVIDER,
            timeout=settings.REPORTS_LLM_TIMEOUT,
            **prompt_body,
        )
        raw_response = response.get("result", response)
        token_limit = int(
            max_tokens or prompt_body.get("max_tokens") or settings.REPORTS_MAX_TOKENS
        )
        return self._parse_report_llm_response(raw_response, max_tokens=token_limit)

    def _parse_report_llm_response(
        self,
        raw_response: Dict[str, Any],
        *,
        max_tokens: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], Optional[str], bool]:
        """Parse Bedrock/OpenAI-style completion into a report content dict."""
        usage = raw_response.get("usage") or {}
        completion_tokens = usage.get("completion_tokens")
        token_limit = int(max_tokens or settings.REPORTS_MAX_TOKENS)
        choices = raw_response.get("choices") or []
        finish_reason = (
            (choices[0] or {}).get("finish_reason") if choices else None
        )
        truncated = finish_reason == "length" or (
            completion_tokens is not None
            and int(completion_tokens) >= max(1, token_limit - 32)
        )

        raw_text = extract_text(raw_response)
        if not raw_text:
            return {}, "LLM returned an empty response", truncated

        json_text = _extract_json_from_llm_response(raw_text)
        try:
            content = json.loads(json_text)
        except json.JSONDecodeError as exc:
            salvaged, was_salvaged = salvage_json_object(raw_text)
            if salvaged is not None:
                if was_salvaged or truncated:
                    salvaged["_truncated"] = True
                    salvaged["_salvaged"] = True
                    salvaged["_truncation_warning"] = (
                        "Response was truncated; partial JSON was recovered"
                    )
                return (
                    salvaged,
                    "Response was truncated; partial JSON was recovered"
                    if was_salvaged or truncated
                    else None,
                    truncated or was_salvaged,
                )

            preview = raw_text[:300].replace("\n", " ")
            if truncated:
                message = (
                    "LLM response hit the token limit and could not be parsed as valid JSON"
                )
            else:
                message = f"Failed to parse LLM response as JSON: {exc}"
            return (
                {
                    "_parse_error": True,
                    "_truncated": truncated,
                    "_raw_preview": preview,
                },
                message,
                truncated,
            )

        if truncated:
            content["_truncated"] = True
            content["_truncation_warning"] = (
                "Response was truncated at the max_tokens limit; some sections may be incomplete"
            )

        return content, None, truncated

    async def _call_tax_return_llm(
        self,
        prompt_body: Dict[str, Any],
        step_name: str,
    ) -> Tuple[Dict[str, Any], Optional[str], bool]:
        """Call the LLM for a tax-return step with parse/truncation retries."""
        base_limit = int(
            prompt_body.get("max_tokens") or settings.REPORTS_TAX_RETURN_SECTION_MAX_TOKENS
        )
        token_limits: list[int] = []
        for limit in (base_limit, settings.REPORTS_MAX_TOKENS):
            if limit not in token_limits:
                token_limits.append(limit)

        messages = list(prompt_body.get("messages") or [])
        retry_messages = [
            {"role": "user", "content": _TAX_RETURN_COMPACT_RETRY},
            {"role": "user", "content": _TAX_RETURN_TRUNCATION_RETRY},
        ]

        last_content: Dict[str, Any] = {}
        last_error: Optional[str] = None
        last_truncated = False

        for attempt, token_limit in enumerate(token_limits):
            suffix = retry_messages[:attempt]
            body = {
                **prompt_body,
                "messages": messages + suffix,
                "max_tokens": token_limit,
            }
            content, error_message, truncated = await self._call_report_llm(
                body,
                max_tokens=token_limit,
            )
            last_content, last_error, last_truncated = content, error_message, truncated

            incomplete = (
                truncated
                or content.get("_parse_error")
                or content.get("_truncated")
                or error_message
            )
            if not incomplete:
                return content, None, False

            logger.warning(
                "Tax Return %s: attempt %s incomplete (truncated=%s parse_error=%s)",
                step_name,
                attempt + 1,
                truncated,
                bool(content.get("_parse_error")),
            )

        return last_content, last_error, last_truncated

    def _build_report_result(
        self,
        *,
        report_type: str,
        content: Dict[str, Any],
        processing_time: float,
        error_message: Optional[str],
        truncated: bool,
    ) -> Dict[str, Any]:
        has_usable_content = bool(content) and not content.get("_parse_error")
        if error_message:
            status = "partial" if (truncated or has_usable_content) else "failed"
        else:
            status = "partial" if truncated else "completed"

        return {
            "report_type": report_type,
            "content": content,
            "processing_time": processing_time,
            "status": status,
            "error_message": error_message,
        }

    async def _generate_cash_flow_report(
        self,
        wildapricot_data: Dict[str, Any],
        quickbooks_data: Dict[str, Any],
        start_date: str,
        end_date: str,
        user_prompt: Optional[str] = None,
        *,
        reference_financials: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate Cash Flow Report using LLM."""
        start_time = time.time()
        logger.info("Generating Cash Flow Report")

        prompt_body = build_cash_flow_report_prompt(
            wildapricot_data,
            quickbooks_data,
            start_date,
            end_date,
            reference_financials=reference_financials,
            user_prompt=user_prompt,
        )
        content, error_message, truncated = await self._call_report_llm(prompt_body)

        processing_time = time.time() - start_time
        logger.info(
            "Cash Flow Report generated in %.2fs status=%s",
            processing_time,
            "partial" if error_message or truncated else "completed",
        )

        return self._build_report_result(
            report_type="cash_flow",
            content=content,
            processing_time=processing_time,
            error_message=error_message,
            truncated=truncated,
        )

    async def _generate_balance_sheet_report(
        self,
        wildapricot_data: Dict[str, Any],
        quickbooks_data: Dict[str, Any],
        start_date: str,
        end_date: str,
        user_prompt: Optional[str] = None,
        *,
        reference_financials: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate Balance Sheet Report using LLM."""
        start_time = time.time()
        logger.info("Generating Balance Sheet Report")

        prompt_body = build_balance_sheet_report_prompt(
            wildapricot_data,
            quickbooks_data,
            start_date,
            end_date,
            reference_financials=reference_financials,
            user_prompt=user_prompt,
        )
        content, error_message, truncated = await self._call_report_llm(prompt_body)

        if content and not content.get("_parse_error"):
            content = ensure_balance_sheet_mandatory_fields(content)

        processing_time = time.time() - start_time
        logger.info(
            "Balance Sheet Report generated in %.2fs status=%s",
            processing_time,
            "partial" if error_message or truncated else "completed",
        )

        return self._build_report_result(
            report_type="balance_sheet",
            content=content,
            processing_time=processing_time,
            error_message=error_message,
            truncated=truncated,
        )

    def _merge_tax_return_step_results(
        self,
        part_viii: Dict[str, Any],
        part_ix: Dict[str, Any],
        part_x: Dict[str, Any],
        parts_i_vii_xi_xii: Dict[str, Any],
        reconciliation: Dict[str, Any],
        filed_organization_information: Optional[Dict[str, Any]] = None,
        *,
        start_date: str = "",
        end_date: str = "",
    ) -> Dict[str, Any]:
        """Combine split tax-return LLM outputs into a complete Form 990 (Parts I-XII)."""
        non_financial = parts_i_vii_xi_xii or {}
        statement = reconciliation.get("statement") or non_financial.get("statement") or {}
        if not statement:
            statement = {"type": "Form990"}

        organization_information = merge_organization_information(
            non_financial.get("organizationInformation") or {},
            filed_organization_information or {},
        )

        part_x_balance_sheet = ensure_part_x_mandatory_fields(
            part_x.get("partX_balanceSheet") or {}
        )

        merged: Dict[str, Any] = {
            "statement": statement,
            "organizationInformation": organization_information,
            "partI_summary": non_financial.get("partI_summary") or {},
            "partII_signatureBlock": non_financial.get("partII_signatureBlock") or {},
            "partIII_programServiceAccomplishments": (
                non_financial.get("partIII_programServiceAccomplishments") or {}
            ),
            "partIV_checklistOfRequiredSchedules": (
                non_financial.get("partIV_checklistOfRequiredSchedules") or []
            ),
            "partV_statementsRegardingOtherIRSFilings": (
                non_financial.get("partV_statementsRegardingOtherIRSFilings") or []
            ),
            "partVI_governance": non_financial.get("partVI_governance") or {},
            "partVII_compensation": non_financial.get("partVII_compensation") or {},
            "partVIII_revenue": part_viii.get("partVIII_revenue") or [],
            "partVIII_totalRevenue": part_viii.get("totalRevenue") or 0.0,
            "partIX_expenses": part_ix.get("partIX_expenses") or [],
            "partIX_totals": {
                "totalExpenses": part_ix.get("totalExpenses") or 0.0,
                "totalProgramServices": part_ix.get("totalProgramServices") or 0.0,
                "totalManagementAndGeneral": part_ix.get("totalManagementAndGeneral") or 0.0,
                "totalFundraising": part_ix.get("totalFundraising") or 0.0,
            },
            "partX_balanceSheet": part_x_balance_sheet,
            "partXI_reconciliationOfNetAssets": (
                non_financial.get("partXI_reconciliationOfNetAssets") or {}
            ),
            "partXII_financialStatementsAndReporting": (
                non_financial.get("partXII_financialStatementsAndReporting") or {}
            ),
            "scheduleA": non_financial.get("scheduleA") or {},
            "scheduleO": non_financial.get("scheduleO") or [],
            "reconciliationResults": reconciliation.get("reconciliationResults") or [],
            "reconciliation": reconciliation.get("reconciliation") or {},
            "validationErrors": reconciliation.get("validationErrors") or [],
            "generatedTaxReturnDraft": reconciliation.get("generatedTaxReturnDraft") or {},
        }
        merged["organization_summary"] = build_organization_summary(
            merged, start_date, end_date
        )
        return merged


    async def _generate_tax_return_report(
        self,
        wildapricot_data: Dict[str, Any],
        quickbooks_data: Dict[str, Any],
        start_date: str,
        end_date: str,
        user_prompt: Optional[str] = None,
        *,
        reference_financials: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate Tax Return Document Report using sequential split LLM calls."""
        start_time = time.time()
        logger.info("Generating Tax Return Document Report")

        wa_for_tax, qb_for_tax = compact_source_data_for_tax_return(
            wildapricot_data,
            quickbooks_data,
        )
        tax_ctx = {
            "wa_period_empty": wildapricot_period_empty(
                wildapricot_data, start_date, end_date
            ),
            "qb_mapping_hints": build_qb_mapping_hints(quickbooks_data),
        }

        section_steps: list[tuple[str, Callable[..., Dict[str, Any]]]] = [
            ("part_viii", build_tax_return_part_viii_prompt),
            ("part_ix", build_tax_return_part_ix_prompt),
            ("part_x", build_tax_return_part_x_prompt),
        ]

        step_results: Dict[str, Dict[str, Any]] = {}
        error_messages: list[str] = []
        truncated = False

        for step_name, prompt_builder in section_steps:
            step_start = time.time()
            logger.info("Tax Return: generating %s", step_name)

            prompt_body = prompt_builder(
                wa_for_tax,
                qb_for_tax,
                start_date,
                end_date,
                user_prompt,
                reference_financials=reference_financials,
                **tax_ctx,
            )
            content, error_message, step_truncated = await self._call_tax_return_llm(
                prompt_body,
                step_name,
            )
            if step_name == "part_ix" and content and not content.get("_parse_error"):
                content = ensure_part_ix_minimum_fields(content, quickbooks_data)
            step_results[step_name] = content

            if error_message:
                error_messages.append(f"{step_name}: {error_message}")
            if step_truncated:
                truncated = True

            logger.info(
                "Tax Return %s completed in %.2fs status=%s",
                step_name,
                time.time() - step_start,
                "partial" if error_message or step_truncated else "completed",
            )

        recon_start = time.time()
        logger.info("Tax Return: generating parts_i_vii_xi_xii")

        filed_org_info = await load_filed_organization_information(end_date)

        financial_parts = compact_tax_return_financial_parts_for_reconciliation(
            step_results.get("part_viii", {}),
            step_results.get("part_ix", {}),
            step_results.get("part_x", {}),
        )
        organization_details = {
            **derive_organization_details(quickbooks_data, wildapricot_data),
            "filed_organization_information": filed_org_info,
        }
        parts_prompt = build_tax_return_parts_i_vii_xi_xii_prompt(
            wa_for_tax,
            qb_for_tax,
            organization_details,
            start_date,
            end_date,
            financial_parts,
            user_prompt,
            reference_financials=reference_financials,
            **tax_ctx,
        )
        parts_content, parts_error, parts_truncated = await self._call_tax_return_llm(
            parts_prompt,
            "parts_i_vii_xi_xii",
        )
        step_results["parts_i_vii_xi_xii"] = parts_content
        if parts_error:
            error_messages.append(f"parts_i_vii_xi_xii: {parts_error}")
        if parts_truncated:
            truncated = True

        logger.info(
            "Tax Return parts_i_vii_xi_xii completed in %.2fs status=%s",
            time.time() - recon_start,
            "partial" if parts_error or parts_truncated else "completed",
        )

        recon_start = time.time()
        logger.info("Tax Return: generating reconciliation")

        financial_summary = compact_tax_return_financial_parts_for_reconciliation(
            step_results.get("part_viii", {}),
            step_results.get("part_ix", {}),
            step_results.get("part_x", {}),
        )
        recon_prompt = build_tax_return_reconciliation_prompt(
            start_date,
            end_date,
            part_viii_summary={
                "part_viii_revenue": financial_summary.get("partVIII_revenue") or [],
                "total_revenue": financial_summary.get("totalRevenue"),
            },
            part_ix_summary={
                "part_ix_expenses": financial_summary.get("partIX_expenses") or [],
                "total_expenses": financial_summary.get("totalExpenses"),
                "total_program_services": financial_summary.get("totalProgramServices"),
                "total_management_and_general": financial_summary.get(
                    "totalManagementAndGeneral"
                ),
                "total_fundraising": financial_summary.get("totalFundraising"),
            },
            part_x_summary={
                "part_x_balance_sheet": financial_summary.get("partX_balanceSheet") or {},
            },
            quickbooks_summary=compact_quickbooks_for_reconciliation(quickbooks_data),
            user_prompt=user_prompt,
        )
        recon_content, recon_error, recon_truncated = await self._call_tax_return_llm(
            recon_prompt,
            "reconciliation",
        )
        if recon_error:
            error_messages.append(f"reconciliation: {recon_error}")
        if recon_truncated:
            truncated = True

        logger.info(
            "Tax Return reconciliation completed in %.2fs status=%s",
            time.time() - recon_start,
            "partial" if recon_error or recon_truncated else "completed",
        )

        content = self._merge_tax_return_step_results(
            step_results.get("part_viii", {}),
            step_results.get("part_ix", {}),
            step_results.get("part_x", {}),
            step_results.get("parts_i_vii_xi_xii", {}),
            recon_content,
            filed_organization_information=filed_org_info,
            start_date=start_date,
            end_date=end_date,
        )

        pl_raw = self._raw_pl_report or {}
        content, enforcement_notes = enforce_deterministic_amounts(content, pl_raw)
        if enforcement_notes:
            existing = content.get("validationErrors") or []
            content["validationErrors"] = list(existing) + enforcement_notes
            logger.info(
                "Tax Return: deterministic enforcement applied %d correction(s)",
                len(enforcement_notes),
            )

        content, propagation_notes = propagate_enforced_totals(content, pl_raw)
        if propagation_notes:
            existing = content.get("validationErrors") or []
            content["validationErrors"] = list(existing) + propagation_notes

        content = normalize_tax_return_content(
            content, quickbooks_data=quickbooks_data
        )

        error_message = "; ".join(error_messages) if error_messages else None

        processing_time = time.time() - start_time
        logger.info(
            "Tax Return Document Report generated in %.2fs status=%s",
            processing_time,
            "partial" if error_message or truncated else "completed",
        )

        return self._build_report_result(
            report_type="tax_return",
            content=content,
            processing_time=processing_time,
            error_message=error_message,
            truncated=truncated,
        )

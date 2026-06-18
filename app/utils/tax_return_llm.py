"""Helpers for tax-return LLM orchestration."""

from __future__ import annotations

from typing import Any


def derive_organization_details(
    quickbooks_data: dict[str, Any],
    wildapricot_data: dict[str, Any],
) -> dict[str, Any]:
    """Build minimal organization metadata from available source payloads."""
    pl_meta = (quickbooks_data.get("profit_and_loss") or {}).get("metadata") or {}
    bs_meta = (quickbooks_data.get("balance_sheet") or {}).get("metadata") or {}
    return {
        "accounting_method": pl_meta.get("report_basis") or bs_meta.get("report_basis") or "",
        "currency": pl_meta.get("currency") or bs_meta.get("currency") or "USD",
        "wildapricot_account_id": wildapricot_data.get("account_id") or "",
    }


def compact_tax_return_financial_parts_for_reconciliation(
    part_viii: dict[str, Any],
    part_ix: dict[str, Any],
    part_x: dict[str, Any],
) -> dict[str, Any]:
    """Compact generated Part VIII/IX/X payloads for downstream LLM steps."""
    return {
        "partVIII_revenue": part_viii.get("partVIII_revenue") or [],
        "totalRevenue": part_viii.get("totalRevenue"),
        "partIX_expenses": part_ix.get("partIX_expenses") or [],
        "totalExpenses": part_ix.get("totalExpenses"),
        "totalProgramServices": part_ix.get("totalProgramServices"),
        "totalManagementAndGeneral": part_ix.get("totalManagementAndGeneral"),
        "totalFundraising": part_ix.get("totalFundraising"),
        "partX_balanceSheet": part_x.get("partX_balanceSheet") or {},
    }


def summarize_tax_return_part(part: dict[str, Any], items_key: str) -> dict[str, Any]:
    """Strip verbose fields before sending a section to the reconciliation step."""
    if not part or part.get("_parse_error"):
        return {
            items_key: [],
            "human_review_items": [],
            "warnings": [
                {
                    "warning_type": "SECTION_GENERATION_FAILED",
                    "severity": "HIGH",
                    "message": "This section could not be parsed from the LLM response.",
                }
            ],
            "_generation_error": True,
        }

    def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
        compact = {
            key: item[key]
            for key in (
                "form_section",
                "line_number",
                "amount",
                "classification",
                "confidence_score",
            )
            if key in item
        }
        source_records = item.get("source_records") or []
        if source_records:
            first = source_records[0]
            compact["source_record"] = (
                first if isinstance(first, str) else str(first)[:120]
            )
        return compact

    camel_aliases = {
        "part_viii_revenue": "partVIII_revenue",
        "part_ix_expenses": "partIX_expenses",
        "part_x_balance_sheet": "partX_balanceSheet",
    }
    resolved_key = camel_aliases.get(items_key, items_key)
    if resolved_key == "partX_balanceSheet":
        return {
            items_key: part.get(resolved_key) or {},
            "human_review_items": (part.get("human_review_items") or part.get("humanReviewItems") or [])[:12],
            "warnings": (part.get("warnings") or [])[:6],
        }

    items = part.get(resolved_key) or part.get(items_key) or []
    return {
        items_key: [_compact_item(item) for item in items if isinstance(item, dict)],
        "human_review_items": (part.get("human_review_items") or part.get("humanReviewItems") or [])[:12],
        "warnings": (part.get("warnings") or [])[:6],
    }


def compact_quickbooks_for_reconciliation(
    quickbooks_data: dict[str, Any],
) -> dict[str, Any]:
    """Pass formatted QuickBooks reports to the reconciliation prompt."""
    compact: dict[str, Any] = {}
    for report_key in ("profit_and_loss", "balance_sheet"):
        report = quickbooks_data.get(report_key) or {}
        compact[report_key] = {
            "metadata": report.get("metadata"),
            "formatted_report": report.get("formatted_report") or "",
        }
    return compact

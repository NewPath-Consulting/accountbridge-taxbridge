"""Compact report payloads before LLM benchmark calls."""

from __future__ import annotations

from typing import Any, Dict, List

from app.utils.tax_return_llm import summarize_tax_return_part


def compact_manual_extraction(data: Dict[str, Any]) -> Dict[str, Any]:
    """Manual /extract output is already structured; pass through."""
    return data or {}


def _to_amount(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("amount", "value", "total"):
            if key in value and value[key] is not None:
                return _to_amount(value[key])
    return 0.0


def _compact_line_items(items: List[Any], limit: int = 30) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("line_item") or item.get("label") or ""
        amount = _to_amount(item.get("amount"))
        compact.append({"name": name, "amount": amount})
    compact.sort(key=lambda x: abs(x.get("amount") or 0), reverse=True)
    return compact[:limit]


def _section(content: Dict[str, Any], snake: str, camel: str) -> Dict[str, Any]:
    section = content.get(snake) or content.get(camel)
    return section if isinstance(section, dict) else {}


def compact_tax_return_report(report_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Compact a tax_return ReportData entry for benchmark LLM input."""
    content = report_entry.get("content") or {}
    if not content:
        return {"status": report_entry.get("status"), "content": {}}

    draft = content.get("generated_tax_return_draft") or content.get("generatedTaxReturnDraft") or {}
    part_ix_totals = content.get("partIX_totals") or content.get("part_ix_totals") or {}
    part_x = content.get("partX_balanceSheet") or content.get("part_x_balance_sheet") or {}
    return {
        "status": report_entry.get("status"),
        "processing_time": report_entry.get("processing_time"),
        "organization_summary": (
            content.get("organization_summary")
            or content.get("organizationSummary")
            or content.get("organizationInformation")
            or {}
        ),
        "generated_tax_return_draft": draft,
        "totals": {
            "total_revenue": content.get("partVIII_totalRevenue")
            or content.get("part_viii_total_revenue"),
            "total_expenses": part_ix_totals.get("totalExpenses")
            or part_ix_totals.get("total_expenses"),
            "total_assets": part_x.get("total_assets") or part_x.get("totalAssets"),
            "total_liabilities": part_x.get("total_liabilities")
            or part_x.get("totalLiabilities"),
            "net_assets": part_x.get("net_assets") or part_x.get("netAssets"),
        },
        "part_viii_revenue": summarize_tax_return_part(
            content, "part_viii_revenue"
        ).get("part_viii_revenue"),
        "part_ix_expenses": summarize_tax_return_part(
            content, "part_ix_expenses"
        ).get("part_ix_expenses"),
        "part_x_balance_sheet": summarize_tax_return_part(
            content, "part_x_balance_sheet"
        ).get("part_x_balance_sheet"),
        "human_review_items": (
            content.get("human_review_items") or content.get("humanReviewItems") or []
        )[:12],
        "warnings": (content.get("warnings") or [])[:12],
        "validation_errors": (
            content.get("validation_errors") or content.get("validationErrors") or []
        ),
        "reconciliation_results": (
            content.get("reconciliation_results") or content.get("reconciliationResults") or []
        ),
        "audit_flags": (
            content.get("audit_flags") or content.get("auditFlags") or []
        ),
    }


def compact_cash_flow_report(report_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Compact a cash_flow ReportData entry for benchmark LLM input."""
    content = report_entry.get("content") or {}
    if not content:
        return {"status": report_entry.get("status"), "content": {}}

    operating = _section(content, "operating_activities", "operatingActivities")
    investing = _section(content, "investing_activities", "investingActivities")
    financing = _section(content, "financing_activities", "financingActivities")
    reconciliation = _section(content, "cash_reconciliation", "cashReconciliation")

    def _subtotal(section: dict, *keys: str) -> Any:
        for key in keys:
            if key in section and section[key] is not None:
                return section[key]
        return None

    operating_adjustments = (
        (operating.get("adjustments") or [])
        + (operating.get("changesInWorkingCapital") or [])
    )
    investing_items = investing.get("adjustments") or investing.get("line_items") or investing.get("items") or []
    financing_items = financing.get("adjustments") or financing.get("line_items") or financing.get("items") or []

    return {
        "status": report_entry.get("status"),
        "processing_time": report_entry.get("processing_time"),
        "report_metadata": content.get("report_metadata") or content.get("statement") or {},
        "operating_activities": {
            "net_revenue": _subtotal(
                operating,
                "net_revenue",
                "net_income_or_change_in_net_assets",
                "netIncome",
            ),
            "adjustments": _compact_line_items(operating_adjustments),
            "net_cash_from_operations": _subtotal(
                operating,
                "net_cash_from_operations",
                "operating_cash_flow",
                "netCashFromOperations",
            ),
        },
        "investing_activities": {
            "line_items": _compact_line_items(investing_items),
            "net_cash_from_investing": _subtotal(
                investing,
                "net_cash_from_investing",
                "investing_cash_flow",
                "netCashFromInvesting",
            ),
        },
        "financing_activities": {
            "line_items": _compact_line_items(financing_items),
            "net_cash_from_financing": _subtotal(
                financing,
                "net_cash_from_financing",
                "financing_cash_flow",
                "netCashFromFinancing",
            ),
        },
        "cash_reconciliation": {
            "beginning_cash": _subtotal(
                reconciliation, "beginning_cash", "cash_beginning", "beginningCash"
            ),
            "ending_cash": _subtotal(
                reconciliation, "ending_cash", "cash_ending", "endingCash"
            ),
            "net_increase": _subtotal(
                reconciliation, "net_increase", "net_cash_change", "netIncrease"
            ),
        },
        "validation_results": content.get("validation_results") or [],
        "human_review_items": (content.get("human_review_items") or [])[:12],
    }


def _sum_concept_amounts(items: List[Any], *concept_ids: str) -> Optional[float]:
    ids = {c.lower() for c in concept_ids}
    total = 0.0
    found = False
    for item in items or []:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("conceptId") or "").lower()
        if concept not in ids:
            continue
        total += _to_amount(item.get("amount"))
        found = True
    return total if found else None


def compact_balance_sheet_report(report_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Compact a balance_sheet ReportData entry for benchmark LLM input."""
    content = report_entry.get("content") or {}
    if not content:
        return {"status": report_entry.get("status"), "content": {}}

    assets = content.get("assets") or {}
    liabilities = content.get("liabilities") or {}
    net_assets = content.get("netAssets") or content.get("net_assets") or {}
    current_assets = assets.get("currentAssets") or []
    non_current_assets = assets.get("nonCurrentAssets") or []
    current_liabilities = liabilities.get("currentLiabilities") or []

    total_net = net_assets.get("totalNetAssets")
    if total_net is None:
        total_net = net_assets.get("total_net_assets")
    if total_net is None:
        total_net = _to_amount(
            (net_assets.get("withoutDonorRestrictions") or {}).get("amount")
        ) + _to_amount((net_assets.get("withDonorRestrictions") or {}).get("amount"))

    return {
        "status": report_entry.get("status"),
        "processing_time": report_entry.get("processing_time"),
        "statement": content.get("statement") or {},
        "assets": {
            "cash": _sum_concept_amounts(
                current_assets, "CashAndCashEquivalents", "Cash"
            ),
            "receivables": _sum_concept_amounts(
                current_assets, "AccountsReceivable", "AccountsReceivableNet"
            ),
            "prepaids": _sum_concept_amounts(
                current_assets, "PrepaidExpenses", "PrepaidExpense"
            ),
            "fixed_assets": _sum_concept_amounts(
                non_current_assets + current_assets,
                "PropertyPlantAndEquipmentNet",
                "PropertyPlantAndEquipmentGross",
                "FixedAssets",
            ),
            "total_assets": assets.get("totalAssets") or assets.get("total_assets"),
            "current_assets": _compact_line_items(current_assets),
            "non_current_assets": _compact_line_items(non_current_assets),
        },
        "liabilities": {
            "accounts_payable": _sum_concept_amounts(
                current_liabilities, "AccountsPayable"
            ),
            "deferred_revenue": _sum_concept_amounts(
                current_liabilities,
                "DeferredRevenue",
                "UnearnedRevenue",
                "MembershipDuesPayable",
            ),
            "other_liabilities": _sum_concept_amounts(
                (liabilities.get("nonCurrentLiabilities") or []) + current_liabilities,
                "OtherLiabilities",
                "NotesPayable",
                "LongTermDebt",
            ),
            "total_liabilities": liabilities.get("totalLiabilities")
            or liabilities.get("total_liabilities"),
            "current_liabilities": _compact_line_items(current_liabilities),
        },
        "net_assets": {
            "net_assets": total_net,
            "without_donor_restrictions": _to_amount(
                (net_assets.get("withoutDonorRestrictions") or {}).get("amount")
            ),
            "with_donor_restrictions": _to_amount(
                (net_assets.get("withDonorRestrictions") or {}).get("amount")
            ),
        },
        "accounting_equation": content.get("accountingEquation") or {},
        "human_review_items": (content.get("human_review_items") or [])[:12],
        "validation_results": content.get("validation_results") or [],
    }

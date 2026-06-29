"""Normalize and backfill AI report JSON for benchmark alignment and structural completeness."""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _tax_year_from_content(content: dict[str, Any], end_date: str) -> str | int | None:
    statement = content.get("statement") or {}
    tax_year = statement.get("taxYear") or statement.get("tax_year")
    if isinstance(tax_year, dict):
        end = tax_year.get("endDate") or tax_year.get("end_date")
        if end:
            return str(end)[:4]
    if isinstance(tax_year, str) and tax_year.strip():
        if " to " in tax_year:
            return tax_year.split(" to ")[-1].strip()[:4]
        return tax_year[:4]
    if end_date and len(str(end_date)) >= 4:
        return str(end_date)[:4]
    return None


def _gross_receipts_from_content(content: dict[str, Any]) -> float | None:
    total = content.get("partVIII_totalRevenue") or content.get("part_viii_total_revenue")
    if total is not None:
        return _num(total)

    part_i = content.get("partI_summary") or content.get("part_i_summary") or {}
    summary = part_i.get("revenueExpenseSummary") or {}
    line12 = summary.get("line12_totalRevenue") or {}
    if isinstance(line12, dict):
        return _num(line12.get("currentYear"))
    return _num(line12)


def build_organization_summary(
    content: dict[str, Any],
    start_date: str = "",
    end_date: str = "",
) -> dict[str, Any]:
    """Map tax return content to benchmark organization_summary schema."""
    org = (
        content.get("organization_summary")
        or content.get("organizationSummary")
        or content.get("organizationInformation")
        or {}
    )
    part_i = content.get("partI_summary") or content.get("part_i_summary") or {}

    tax_year = org.get("tax_year") or org.get("taxYear")
    if isinstance(tax_year, dict):
        tax_year = (tax_year.get("endDate") or tax_year.get("end_date") or "")[:4] or None
    if not tax_year:
        tax_year = _tax_year_from_content(content, end_date)

    gross_receipts = org.get("gross_receipts") or org.get("grossReceipts")
    if gross_receipts is None:
        gross_receipts = _gross_receipts_from_content(content)

    return {
        "organization_name": org.get("organization_name")
        or org.get("organizationName")
        or org.get("legalName"),
        "ein": org.get("ein"),
        "tax_year": tax_year,
        "gross_receipts": gross_receipts,
        "mission": org.get("mission") or part_i.get("missionStatement"),
    }


_PPE_CONCEPT_PREFIXES = (
    "PropertyPlantAndEquipmentNet",
    "PropertyPlantAndEquipmentGross",
    "FixedAssets",
)


def _has_ppe_line(items: list[Any]) -> bool:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("conceptId") or "")
        if any(concept.startswith(prefix) for prefix in _PPE_CONCEPT_PREFIXES):
            return True
    return False


def ensure_balance_sheet_mandatory_fields(content: dict[str, Any]) -> dict[str, Any]:
    """Ensure mandatory ASC 958 balance sheet lines exist with zero placeholders."""
    if not content:
        return content

    result = dict(content)
    assets = dict(result.get("assets") or {})
    liabilities = dict(result.get("liabilities") or {})

    non_current = list(assets.get("nonCurrentAssets") or [])
    if not _has_ppe_line(non_current):
        non_current.append(
            {
                "conceptId": "PropertyPlantAndEquipmentNet",
                "label": "Property, Plant and Equipment, Net",
                "amount": 0.0,
                "sourceSystem": "QuickBooks",
                "sourceAccounts": [],
                "dataQualityFlag": "No fixed asset accounts in source data; zero placeholder emitted.",
            }
        )
        assets["nonCurrentAssets"] = non_current

    has_liability_lines = bool(
        liabilities.get("currentLiabilities") or liabilities.get("nonCurrentLiabilities")
    )
    total_liab = liabilities.get("totalLiabilities")
    if total_liab is None and liabilities.get("total_liabilities") is None:
        if has_liability_lines or liabilities:
            liabilities["totalLiabilities"] = 0.0

    result["assets"] = assets
    result["liabilities"] = liabilities
    return result


def ensure_part_x_mandatory_fields(part_x: dict[str, Any]) -> dict[str, Any]:
    """Ensure Part X includes accounts payable line 17 when missing."""
    if not part_x:
        return part_x

    result = dict(part_x)
    items = list(result.get("liabilitiesAndNetAssets") or [])
    ap_keywords = ("accounts payable", "payable and accrued")

    has_ap = any(
        isinstance(item, dict)
        and any(kw in str(item.get("label") or "").lower() for kw in ap_keywords)
        for item in items
    )
    if not has_ap:
        items.insert(
            0,
            {
                "lineNumber": "17",
                "label": "Accounts payable and accrued expenses",
                "beginningOfYear": 0.0,
                "endOfYear": 0.0,
                "sourceSystem": "QuickBooks",
                "dataQualityFlag": "No accounts payable in source data; zero placeholder emitted.",
            },
        )
        result["liabilitiesAndNetAssets"] = items

    return result


def ensure_part_ix_minimum_fields(
    part_ix: dict[str, Any],
    quickbooks_data: dict[str, Any],
) -> dict[str, Any]:
    """Backfill Part IX totals from QuickBooks when LLM output is incomplete."""
    result = dict(part_ix or {})
    pl = quickbooks_data.get("profit_and_loss") or {}
    totals = pl.get("totals") or {}
    total_expenses = totals.get("total_expenses")

    if total_expenses is not None and result.get("totalExpenses") in (None, 0, 0.0):
        result["totalExpenses"] = float(total_expenses)

    expenses = result.get("partIX_expenses") or []
    if not expenses and total_expenses is not None:
        result["partIX_expenses"] = [
            {
                "lineNumber": "25",
                "label": "Total functional expenses",
                "totalExpenses": float(total_expenses),
                "programServices": float(result.get("totalProgramServices") or 0.0),
                "managementAndGeneral": float(
                    result.get("totalManagementAndGeneral") or 0.0
                ),
                "fundraising": float(result.get("totalFundraising") or 0.0),
                "sourceSystem": "QuickBooks",
                "dataQualityFlag": (
                    "Line detail unavailable; totals sourced from QuickBooks P&L."
                ),
            }
        ]
    return result


def _part_x_line_amount(items: list[Any], *keywords: str) -> float | None:
    total = 0.0
    found = False
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").lower()
        if keywords and not any(kw in label for kw in keywords):
            continue
        val = _num(item.get("endOfYear") or item.get("end_of_year") or item.get("amount"))
        if val is not None:
            total += val
            found = True
    return total if found else None


def _extract_part_x_totals(part_x: dict[str, Any]) -> dict[str, float | None]:
    assets = part_x.get("assets") or []
    liabilities = part_x.get("liabilitiesAndNetAssets") or part_x.get("liabilities") or []
    totals_block = part_x.get("totalAssets") or part_x.get("totals") or {}

    total_assets = _num(
        part_x.get("totalAssets")
        or (totals_block.get("endOfYear") if isinstance(totals_block, dict) else None)
    )
    total_liabilities = _num(part_x.get("totalLiabilities"))
    net_assets = _num(part_x.get("netAssets") or part_x.get("totalNetAssets"))

    cash = _part_x_line_amount(assets, "cash", "checking", "savings")
    receivables = _part_x_line_amount(assets, "receivable")
    prepaids = _part_x_line_amount(assets, "prepaid")
    fixed_assets = _part_x_line_amount(
        assets, "equipment", "fixed", "property", "leasehold", "shop"
    )
    accounts_payable = _part_x_line_amount(liabilities, "payable", "accrued")
    deferred_revenue = _part_x_line_amount(
        liabilities, "deferred", "unearned", "membership dues payable"
    )
    other_liabilities = _part_x_line_amount(
        liabilities, "other liabilit", "lease deposit", "notes payable", "loan"
    )

    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_assets": net_assets,
        "cash": cash,
        "receivables": receivables,
        "prepaids": prepaids,
        "fixed_assets": fixed_assets,
        "accounts_payable": accounts_payable,
        "deferred_revenue": deferred_revenue,
        "other_liabilities": other_liabilities,
    }


def _rollup_revenue_section(
    content: dict[str, Any],
    quickbooks_data: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.utils.form_990_mapping import suggest_part_viii_buckets_from_quickbooks

    revenue: dict[str, Any] = dict(content.get("revenue") or {})
    total = _num(content.get("partVIII_totalRevenue") or content.get("part_viii_total_revenue"))
    if total is not None:
        revenue["total_revenue"] = total

    qb_buckets: dict[str, float] = {}
    if quickbooks_data:
        qb_buckets = suggest_part_viii_buckets_from_quickbooks(quickbooks_data)

    for field in (
        "contributions",
        "membership_dues",
        "program_service_revenue",
        "investment_income",
        "other_revenue",
    ):
        if revenue.get(field) is not None:
            continue
        if qb_buckets.get(field):
            revenue[field] = qb_buckets[field]
            continue
        items = content.get("partVIII_revenue") or []
        keywords = {
            "contributions": ("contribution", "gift", "grant"),
            "membership_dues": ("membership", "dues"),
            "program_service_revenue": ("program", "membership", "event"),
            "investment_income": ("investment", "interest", "dividend"),
            "other_revenue": ("other", "miscellaneous", "royalt"),
        }.get(field, (field.replace("_", " "),))
        for item in items:
            if not isinstance(item, dict):
                continue
            label = " ".join(
                str(item.get(k) or "")
                for k in ("label", "category", "lineNumber")
            ).lower()
            if any(kw in label for kw in keywords):
                amount = _num(
                    item.get("totalRevenue")
                    or item.get("programServiceRevenue")
                    or item.get("amount")
                )
                if amount is not None:
                    revenue[field] = amount
                    break

    return revenue


def _rollup_expenses_section(
    content: dict[str, Any],
    quickbooks_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.utils.form_990_mapping import suggest_expense_buckets_from_quickbooks

    expenses: dict[str, Any] = dict(content.get("expenses") or {})
    part_ix_totals = content.get("partIX_totals") or content.get("part_ix_totals") or {}

    if expenses.get("total_expenses") is None:
        expenses["total_expenses"] = _num(
            part_ix_totals.get("totalExpenses") or part_ix_totals.get("total_expenses")
            or content.get("totalExpenses")
        )

    functional_map = {
        "program_services": ("totalProgramServices", "total_program_services"),
        "management_general": ("totalManagementAndGeneral", "total_management_and_general"),
        "fundraising": ("totalFundraising", "total_fundraising"),
    }
    for field, keys in functional_map.items():
        if expenses.get(field) is not None:
            continue
        for key in keys:
            val = _num(part_ix_totals.get(key))
            if val is not None:
                expenses[field] = val
                break

    keyword_map = {
        "depreciation": ("depreciat", "amortiz"),
        "occupancy": ("occupancy", "rent"),
        "insurance": ("insurance",),
    }
    items = content.get("partIX_expenses") or []
    for field, keywords in keyword_map.items():
        if expenses.get(field) is not None:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").lower()
            if any(kw in label for kw in keywords):
                amount = _num(
                    item.get("totalExpenses")
                    or item.get("programServices")
                    or item.get("amount")
                )
                if amount is not None:
                    expenses[field] = amount
                    break

    if quickbooks_data:
        qb_buckets = suggest_expense_buckets_from_quickbooks(quickbooks_data)
        for field in ("depreciation", "occupancy", "insurance", "program_services", "management_general", "fundraising"):
            if expenses.get(field) is None and qb_buckets.get(field):
                expenses[field] = qb_buckets[field]

    return expenses


def _rollup_balance_sheet_section(content: dict[str, Any]) -> dict[str, Any]:
    balance_sheet: dict[str, Any] = dict(content.get("balance_sheet") or {})
    part_x = content.get("partX_balanceSheet") or content.get("part_x_balance_sheet") or {}
    px_totals = _extract_part_x_totals(part_x if isinstance(part_x, dict) else {})

    for field, value in px_totals.items():
        if value is not None and balance_sheet.get(field) is None:
            balance_sheet[field] = value
    return balance_sheet


def _rollup_reconciliation_section(content: dict[str, Any]) -> dict[str, Any]:
    reconciliation: dict[str, Any] = dict(content.get("reconciliation") or {})
    part_x = content.get("partX_balanceSheet") or {}
    part_xi = (
        content.get("partXI_reconciliationOfNetAssets")
        or content.get("part_xi_reconciliation")
        or {}
    )

    if reconciliation.get("total_revenue") is None:
        reconciliation["total_revenue"] = _num(
            content.get("partVIII_totalRevenue") or content.get("part_viii_total_revenue")
        )
    if reconciliation.get("total_expenses") is None:
        part_ix_totals = content.get("partIX_totals") or {}
        reconciliation["total_expenses"] = _num(
            part_ix_totals.get("totalExpenses") or part_ix_totals.get("total_expenses")
        )

    if reconciliation.get("ending_net_assets") is None:
        reconciliation["ending_net_assets"] = _num(
            (part_x.get("netAssets") or {}).get("totalNetAssets")
            if isinstance(part_x.get("netAssets"), dict)
            else part_x.get("netAssets")
        ) or _num(part_x.get("totalNetAssets") or part_x.get("net_assets"))

    if reconciliation.get("beginning_net_assets") is None:
        reconciliation["beginning_net_assets"] = _num(
            part_xi.get("line4_netAssetsBeginningOfYear")
            or part_xi.get("line4_net_assets_beginning_of_year")
        )
        if reconciliation.get("beginning_net_assets") is None:
            net_items = part_x.get("liabilitiesAndNetAssets") or []
            for item in net_items:
                if not isinstance(item, dict):
                    continue
                if "net asset" in str(item.get("label") or "").lower():
                    reconciliation["beginning_net_assets"] = _num(
                        item.get("beginningOfYear") or item.get("beginning_of_year")
                    )
                    break

    if reconciliation.get("change_in_net_assets") is None:
        reconciliation["change_in_net_assets"] = _num(
            part_xi.get("line9_otherChangesInNetAssets")
            or part_xi.get("line9_other_changes_in_net_assets")
        )
        beginning = _num(reconciliation.get("beginning_net_assets"))
        ending = _num(reconciliation.get("ending_net_assets"))
        if reconciliation.get("change_in_net_assets") is None and beginning is not None and ending is not None:
            reconciliation["change_in_net_assets"] = ending - beginning

    recon_block = content.get("reconciliation") or {}
    if isinstance(recon_block, dict):
        for key in ("total_revenue", "total_expenses", "beginning_net_assets", "change_in_net_assets", "ending_net_assets"):
            if reconciliation.get(key) is None and recon_block.get(key) is not None:
                reconciliation[key] = recon_block.get(key)

    return reconciliation


def normalize_tax_return_content(
    content: dict[str, Any],
    *,
    quickbooks_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Add benchmark-aligned summary sections (revenue, expenses, balance_sheet,
    reconciliation) and enriched totals for scoring and client review.
    """
    if not content or content.get("_parse_error"):
        return content

    result = dict(content)
    result["revenue"] = _rollup_revenue_section(result, quickbooks_data)
    result["expenses"] = _rollup_expenses_section(result, quickbooks_data)
    result["balance_sheet"] = _rollup_balance_sheet_section(result)
    result["reconciliation"] = _rollup_reconciliation_section(result)

    part_x = result.get("partX_balanceSheet") or {}
    part_ix_totals = result.get("partIX_totals") or {}
    px = _extract_part_x_totals(part_x if isinstance(part_x, dict) else {})
    recon = result["reconciliation"]

    result["totals"] = {
        "total_revenue": recon.get("total_revenue") or result["revenue"].get("total_revenue"),
        "total_expenses": recon.get("total_expenses") or result["expenses"].get("total_expenses"),
        "total_assets": px.get("total_assets") or result["balance_sheet"].get("total_assets"),
        "total_liabilities": px.get("total_liabilities")
        or result["balance_sheet"].get("total_liabilities"),
        "net_assets": recon.get("ending_net_assets")
        or px.get("net_assets")
        or result["balance_sheet"].get("net_assets"),
        "beginning_net_assets": recon.get("beginning_net_assets"),
        "change_in_net_assets": recon.get("change_in_net_assets"),
        "ending_net_assets": recon.get("ending_net_assets"),
    }
    return result

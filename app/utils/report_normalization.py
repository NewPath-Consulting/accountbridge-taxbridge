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

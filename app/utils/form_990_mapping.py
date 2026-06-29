"""QuickBooks account-name heuristics mapped to Form 990 line buckets."""

from __future__ import annotations

import re
from typing import Any

# (pattern, revenue_field, part_viii_line_hint)
_REVENUE_ACCOUNT_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"contribution|gift|grant|donat", re.I), "contributions", "1"),
    (re.compile(r"membership|dues|renewal", re.I), "membership_dues", "2"),
    (re.compile(r"program|conference|education|event registr|workshop|class", re.I), "program_service_revenue", "2"),
    (re.compile(r"interest|dividend|investment|brokerage|mutual|nw mutual", re.I), "investment_income", "3"),
    (re.compile(r"royalt", re.I), "other_revenue", "5"),
    (re.compile(r"fundraising|gala|auction", re.I), "other_revenue", "8"),
    (re.compile(r"gaming", re.I), "other_revenue", "9"),
]

# (pattern, expense_field)
_EXPENSE_ACCOUNT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"depreciat|amortiz", re.I), "depreciation"),
    (re.compile(r"occupancy|rent|lease(?!hold)", re.I), "occupancy"),
    (re.compile(r"insurance", re.I), "insurance"),
    (re.compile(r"fundraising|development|solicit", re.I), "fundraising"),
    (re.compile(r"legal|accounting|audit|executive|admin|office|management|general", re.I), "management_general"),
    (re.compile(r"conference|program|education|membership service|workshop", re.I), "program_services"),
]

# (pattern, balance_sheet_field, part_x_line)
_BALANCE_SHEET_ACCOUNT_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"checking|savings|cash|stripe|paypal", re.I), "cash", "1"),
    (re.compile(r"mutual|brokerage|investment|money market", re.I), "cash", "11"),
    (re.compile(r"receivable", re.I), "receivables", "3"),
    (re.compile(r"prepaid", re.I), "prepaids", "6"),
    (re.compile(r"equipment|furniture|leasehold|fixed asset|property|shop asset", re.I), "fixed_assets", "10"),
    (re.compile(r"accumulated deprec", re.I), "accumulated_depreciation", "10"),
    (re.compile(r"accounts payable|payable and accrued", re.I), "accounts_payable", "17"),
    (re.compile(r"deferred|unearned|membership dues payable", re.I), "deferred_revenue", "19"),
    (re.compile(r"lease deposit|other liabilit|notes payable|loan|mortgage", re.I), "other_liabilities", "25"),
]


def _row_amount(row: dict[str, Any]) -> float:
    total = row.get("total")
    if isinstance(total, (int, float)):
        return float(total)
    values = row.get("values") or {}
    if isinstance(values, dict):
        total_cell = values.get("total") or {}
        if isinstance(total_cell, dict):
            raw = total_cell.get("value")
            try:
                return float(raw)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _row_label(row: dict[str, Any]) -> str:
    if row.get("account"):
        return str(row["account"])
    values = row.get("values") or {}
    if isinstance(values, dict):
        account_cell = values.get("account") or {}
        if isinstance(account_cell, dict) and account_cell.get("value"):
            return str(account_cell["value"])
    return str(row.get("hierarchy_path") or row.get("label") or "")


def classify_qb_income_account(account_name: str) -> tuple[str, str]:
    """Return (revenue_bucket_field, part_viii_line_hint)."""
    for pattern, field, line in _REVENUE_ACCOUNT_RULES:
        if pattern.search(account_name):
            return field, line
    return "other_revenue", "11"


def classify_qb_expense_account(account_name: str) -> str:
    """Return benchmark expense bucket field name."""
    for pattern, field in _EXPENSE_ACCOUNT_RULES:
        if pattern.search(account_name):
            return field
    return "program_services"


def classify_qb_balance_sheet_account(account_name: str) -> tuple[str, str]:
    """Return (balance_sheet_field, part_x_line_hint)."""
    for pattern, field, line in _BALANCE_SHEET_ACCOUNT_RULES:
        if pattern.search(account_name):
            return field, line
    return "other_liabilities", "25"


def suggest_part_viii_buckets_from_quickbooks(
    quickbooks_data: dict[str, Any],
) -> dict[str, float]:
    """Roll up QB P&L income rows into benchmark revenue bucket totals."""
    pl = quickbooks_data.get("profit_and_loss") or {}
    rows = pl.get("rows") or pl.get("top_rows") or []
    buckets: dict[str, float] = {
        "contributions": 0.0,
        "membership_dues": 0.0,
        "program_service_revenue": 0.0,
        "investment_income": 0.0,
        "other_revenue": 0.0,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("row_type") or "").lower() == "summary":
            continue
        label = _row_label(row)
        if not label or "income" in label.lower() and "total" in label.lower():
            continue
        amount = _row_amount(row)
        if amount == 0:
            continue
        field, _ = classify_qb_income_account(label)
        buckets[field] = buckets.get(field, 0.0) + amount
    return buckets


def suggest_expense_buckets_from_quickbooks(
    quickbooks_data: dict[str, Any],
) -> dict[str, float]:
    """Roll up QB P&L expense rows into benchmark expense bucket totals."""
    pl = quickbooks_data.get("profit_and_loss") or {}
    rows = pl.get("rows") or pl.get("top_rows") or []
    buckets: dict[str, float] = {
        "program_services": 0.0,
        "management_general": 0.0,
        "fundraising": 0.0,
        "depreciation": 0.0,
        "occupancy": 0.0,
        "insurance": 0.0,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("row_type") or "").lower() == "summary":
            continue
        label = _row_label(row)
        if not label:
            continue
        amount = abs(_row_amount(row))
        if amount == 0:
            continue
        field = classify_qb_expense_account(label)
        buckets[field] = buckets.get(field, 0.0) + amount
    return buckets


def build_qb_mapping_hints(quickbooks_data: dict[str, Any]) -> dict[str, Any]:
    """Structured hints for LLM prompts derived from QB account names."""
    return {
        "part_viii_revenue_buckets": suggest_part_viii_buckets_from_quickbooks(quickbooks_data),
        "part_ix_expense_buckets": suggest_expense_buckets_from_quickbooks(quickbooks_data),
        "balance_sheet_notes": [
            "NW Mutual / brokerage / investment accounts → Part X Line 11 (investments), not operating cash.",
            "Membership dues payable / unearned / deferred → Part X Line 19 when labeled accordingly.",
            "Lease deposits and other non-deferred payables → Part X Line 25.",
            "Report fixed assets at net (gross less accumulated depreciation) on Part X Line 10.",
        ],
    }

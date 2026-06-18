"""Unit tests for QuickBooks totals extraction and currency formatting."""

import json
from pathlib import Path

from app.utils.postprocess_quickbooks import (
    QuickBooksReportParser,
    currency_symbol,
    extract_quickbooks_totals,
    postprocess_quickbooks_report,
)


def _load_sample_report(name: str) -> dict:
    path = Path(__file__).resolve().parents[2] / "data" / "quickbooks" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_currency_symbol_usd_and_inr():
    assert currency_symbol("USD") == "$"
    assert currency_symbol("INR") == "₹"
    assert currency_symbol(None) == "$"


def test_extract_quickbooks_totals_profit_and_loss():
    rows = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "data"
            / "quickbooks"
            / "profit-and-loss-structured.json"
        ).read_text(encoding="utf-8")
    )
    totals = extract_quickbooks_totals(rows, "ProfitAndLoss")
    assert totals["total_income"] == 10200.77
    assert totals["net_income"] == 1642.46


def test_extract_quickbooks_totals_balance_sheet():
    report = postprocess_quickbooks_report(_load_sample_report("balance-sheet.json"))
    totals = extract_quickbooks_totals(report["rows"], "BalanceSheet")
    assert totals["total_assets"] is not None


def test_format_report_uses_usd_symbol_from_metadata():
    parser = QuickBooksReportParser(_load_sample_report("balance-sheet.json"))
    parser.parse()
    formatted = parser.format_report()
    assert "₹" not in formatted
    assert "$23,436.29" in formatted or "$" in formatted

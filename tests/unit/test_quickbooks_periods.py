"""Unit tests for QuickBooks period helpers."""

from app.utils.quickbooks_periods import prior_year_balance_sheet_period


def test_prior_year_balance_sheet_period_from_calendar_start():
    assert prior_year_balance_sheet_period("2025-01-01") == (
        "2024-01-01",
        "2024-12-31",
    )


def test_prior_year_balance_sheet_period_mid_year_start():
    assert prior_year_balance_sheet_period("2025-07-01") == (
        "2024-07-01",
        "2025-06-30",
    )


def test_prior_year_balance_sheet_period_invalid():
    assert prior_year_balance_sheet_period("not-a-date") is None

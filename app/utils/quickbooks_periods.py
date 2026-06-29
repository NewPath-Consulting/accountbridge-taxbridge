"""Date helpers for QuickBooks report periods."""

from __future__ import annotations

from datetime import date, timedelta


def prior_year_balance_sheet_period(start_date: str) -> tuple[str, str] | None:
    """
    Return (start_date, end_date) for the prior fiscal-year balance sheet.

    Uses the day before the reporting period start as the prior closing date,
    and the same calendar start date one year earlier as the opening anchor.
    """
    try:
        period_start = date.fromisoformat(start_date)
    except (TypeError, ValueError):
        return None

    prior_end = period_start - timedelta(days=1)
    if prior_end.year < 1:
        return None

    try:
        prior_start = period_start.replace(year=period_start.year - 1)
    except ValueError:
        prior_start = period_start.replace(year=period_start.year - 1, day=28)

    return prior_start.isoformat(), prior_end.isoformat()

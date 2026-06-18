"""Unit tests for QuickBooks report client endpoints and params."""

from app.adapters.quickbooks.client import QuickBooksClient


def test_get_report_params_match_documented_shape():
    client = QuickBooksClient()
    params = client._get_report_params("2025-01-01", "2025-12-31")

    assert params == {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "accounting_method": "Accrual",
        "minorversion": "75",
    }
    assert "customer" not in params


def test_report_endpoints_are_balance_sheet_and_profit_and_loss_only():
    """Client must only expose the two documented report types."""
    import inspect

    public_methods = [
        name
        for name, fn in inspect.getmembers(QuickBooksClient, predicate=inspect.isfunction)
        if not name.startswith("_") and name not in ("authenticate",)
    ]
    report_fetchers = [m for m in public_methods if m.startswith("get_")]
    assert sorted(report_fetchers) == ["get_balance_sheet", "get_profit_and_loss"]

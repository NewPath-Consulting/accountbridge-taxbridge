"""Unit tests for QB data quality warnings in LLM input preparation."""

from app.utils.llm_source_summary import (
    assess_qb_data_quality,
    build_reference_financials_from_qb,
    prepare_quickbooks_for_llm,
)


def test_assess_qb_data_quality_flags_zero_income_with_wa_activity():
    wildapricot = {
        "entities": {
            "invoices": {
                "aggregates": {"total_value": 5000.0},
            }
        }
    }
    quickbooks = prepare_quickbooks_for_llm(
        {
            "profit_and_loss": {
                "metadata": {"report_name": "ProfitAndLoss"},
                "rows": [],
                "formatted_report": "",
            },
            "balance_sheet": {
                "metadata": {"report_name": "BalanceSheet"},
                "rows": [],
                "formatted_report": "",
            },
        }
    )
    warnings = assess_qb_data_quality(wildapricot, quickbooks)
    assert any("QB_DATA_SUSPECT" in warning for warning in warnings)


def test_assess_qb_data_quality_flags_sandbox_reset_pattern():
    wildapricot = {"entities": {}}
    bs_rows = [
        {
            "hierarchy_path": "ASSETS > Current Assets > Checking",
            "row_type": "data",
            "values": {
                "account": {"value": "Checking"},
                "total": {"value": 5000.0},
            },
        },
        {
            "hierarchy_path": "LIABILITIES AND EQUITY > Equity > Opening Balance Equity",
            "row_type": "data",
            "values": {
                "account": {"value": "Opening Balance Equity"},
                "total": {"value": 5000.0},
            },
        },
        {
            "hierarchy_path": "ASSETS",
            "row_type": "summary",
            "values": {
                "account": {"value": "TOTAL ASSETS"},
                "total": {"value": 5000.0},
            },
        },
    ]
    quickbooks = prepare_quickbooks_for_llm(
        {
            "profit_and_loss": {
                "metadata": {"report_name": "ProfitAndLoss"},
                "rows": [],
                "formatted_report": "",
            },
            "balance_sheet": {
                "metadata": {"report_name": "BalanceSheet"},
                "rows": bs_rows,
                "formatted_report": "",
            },
        }
    )
    warnings = assess_qb_data_quality(wildapricot, quickbooks)
    assert any("sandbox/reset" in warning.lower() for warning in warnings)


def test_prepare_quickbooks_for_llm_includes_prior_year_balance_sheet():
    prepared = prepare_quickbooks_for_llm(
        {
            "profit_and_loss": {
                "metadata": {"report_name": "ProfitAndLoss"},
                "rows": [],
                "formatted_report": "",
            },
            "balance_sheet": {
                "metadata": {"report_name": "BalanceSheet"},
                "rows": [],
                "formatted_report": "",
            },
            "prior_year_balance_sheet": {
                "metadata": {
                    "report_name": "BalanceSheet",
                    "end_period": "2024-12-31",
                },
                "rows": [{"account": "Checking", "amount": 1000.0}],
                "formatted_report": "Checking 1000",
            },
        }
    )
    assert "prior_year_balance_sheet" in prepared
    assert prepared["prior_year_balance_sheet"]["metadata"]["end_period"] == "2024-12-31"


def test_build_reference_financials_from_qb_maps_prior_year():
    qb = {
        "prior_year_balance_sheet": {
            "metadata": {"end_period": "2024-12-31"},
            "totals": {"total_assets": 1000.0},
        }
    }
    ref = build_reference_financials_from_qb(qb)
    assert ref is not None
    assert ref["prior_financial_position"]["source"] == "QuickBooks"
    assert ref["prior_financial_position"]["as_of_date"] == "2024-12-31"


def test_assess_qb_data_quality_flags_missing_prior_year():
    quickbooks = prepare_quickbooks_for_llm(
        {
            "profit_and_loss": {
                "metadata": {"report_name": "ProfitAndLoss"},
                "rows": [],
                "formatted_report": "",
            },
            "balance_sheet": {
                "metadata": {"report_name": "BalanceSheet"},
                "rows": [],
                "formatted_report": "",
            },
        }
    )
    warnings = assess_qb_data_quality({"entities": {}}, quickbooks)
    assert any("QB_PRIOR_YEAR_MISSING" in warning for warning in warnings)


def test_assess_data_quality_warnings_includes_wa_period_empty():
    from app.utils.llm_source_summary import assess_data_quality_warnings

    warnings = assess_data_quality_warnings(
        {"entities": {}},
        {"profit_and_loss": {"rows": [{"account": "Sales", "total": 100.0}]}},
        start_date="2025-01-01",
        end_date="2025-12-31",
    )
    assert any("WA_PERIOD_EMPTY" in warning for warning in warnings)

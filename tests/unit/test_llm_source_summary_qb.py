"""Unit tests for QB data quality warnings in LLM input preparation."""

from app.utils.llm_source_summary import assess_qb_data_quality, prepare_quickbooks_for_llm


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

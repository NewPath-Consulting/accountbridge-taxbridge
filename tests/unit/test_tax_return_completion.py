"""Unit tests for tax-return completion safeguards."""

from app.utils.report_normalization import ensure_part_ix_minimum_fields
from app.utils.tax_return_llm import compact_source_data_for_tax_return


def test_compact_source_data_for_tax_return_strips_formatted_reports():
    wa, qb = compact_source_data_for_tax_return(
        {
            "account_id": "1",
            "entities": {
                "invoices": {
                    "formatted_report": "x" * 5000,
                    "aggregates": {"total_value": 100.0},
                    "sample_records": [],
                }
            },
        },
        {
            "profit_and_loss": {
                "metadata": {"report_name": "ProfitAndLoss"},
                "totals": {"total_expenses": 1000.0},
                "formatted_report": "y" * 5000,
                "top_rows": [{"account": "Rent", "total": 100.0}],
            }
        },
    )
    assert "formatted_report" not in wa["entities"]["invoices"]
    assert "formatted_report" not in qb["profit_and_loss"]
    assert qb["profit_and_loss"]["totals"]["total_expenses"] == 1000.0


def test_ensure_part_ix_minimum_fields_backfills_from_quickbooks():
    result = ensure_part_ix_minimum_fields(
        {},
        {
            "profit_and_loss": {
                "totals": {"total_expenses": 2500.0},
            }
        },
    )
    assert result["totalExpenses"] == 2500.0
    assert len(result["partIX_expenses"]) == 1
    assert result["partIX_expenses"][0]["lineNumber"] == "25"

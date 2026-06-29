"""Unit tests for QuickBooks → Form 990 mapping hints."""

from app.utils.form_990_mapping import build_qb_mapping_hints


def test_build_qb_mapping_hints_from_profit_and_loss():
    quickbooks_data = {
        "profit_and_loss": {
            "rows": [
                {"account": "Membership Dues", "total": 50000.0},
                {"account": "Depreciation Expense", "total": 3000.0},
            ]
        }
    }

    hints = build_qb_mapping_hints(quickbooks_data)

    assert "part_viii_revenue_buckets" in hints
    assert "part_ix_expense_buckets" in hints
    assert hints["part_viii_revenue_buckets"].get("membership_dues") == 50000.0
    assert hints["part_ix_expense_buckets"].get("depreciation") == 3000.0

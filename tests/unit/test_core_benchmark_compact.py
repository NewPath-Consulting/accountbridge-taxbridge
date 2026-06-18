"""Unit tests for benchmark report compaction."""

from app.core.benchmark.compact import (
    compact_cash_flow_report,
    compact_manual_extraction,
    compact_tax_return_report,
)


def test_compact_manual_extraction_passthrough():
    data = {"revenue": {"total_revenue": 100000}}
    assert compact_manual_extraction(data) == data


def test_compact_tax_return_report_keeps_draft():
    report = {
        "status": "completed",
        "processing_time": 12.5,
        "content": {
            "organization_summary": {"organization_name": "KCWG"},
            "generated_tax_return_draft": {"revenue": {"total_revenue": 50000}},
            "part_viii_revenue": [
                {
                    "line_number": "1",
                    "amount": 50000,
                    "source_records": ["x" * 500],
                }
            ],
            "human_review_items": list(range(20)),
        },
    }
    compact = compact_tax_return_report(report)
    assert compact["generated_tax_return_draft"]["revenue"]["total_revenue"] == 50000
    assert len(compact["human_review_items"]) <= 12
    assert len(compact["part_viii_revenue"]) == 1
    assert "source_record" in compact["part_viii_revenue"][0]


def test_compact_cash_flow_report_limits_adjustments():
    report = {
        "status": "completed",
        "content": {
            "report_metadata": {"organization_name": "KCWG"},
            "operating_activities": {
                "adjustments": [
                    {"line_item": f"Item {i}", "amount": i * 100}
                    for i in range(50)
                ],
                "net_cash_from_operations": {"amount": 48000},
            },
            "cash_reconciliation": {
                "beginning_cash": {"amount": 10000},
                "ending_cash": {"amount": 58000},
                "net_increase": {"amount": 48000},
            },
        },
    }
    compact = compact_cash_flow_report(report)
    assert len(compact["operating_activities"]["adjustments"]) <= 30
    assert compact["operating_activities"]["net_cash_from_operations"] == {"amount": 48000}


def test_compact_cash_flow_report_reads_camel_case_gaap_output():
    report = {
        "status": "completed",
        "content": {
            "statement": {"type": "CashFlowStatement"},
            "operatingActivities": {
                "netIncome": {"amount": 75000},
                "adjustments": [{"label": "Depreciation", "amount": 5000}],
                "netCashFromOperations": {"amount": 80000},
            },
            "investingActivities": {
                "items": [{"label": "Equipment", "amount": -10000}],
                "netCashFromInvesting": {"amount": -10000},
            },
            "financingActivities": {
                "items": [],
                "netCashFromFinancing": {"amount": 0},
            },
            "cashReconciliation": {
                "beginningCash": {"amount": 10000},
                "endingCash": {"amount": 80000},
                "netIncrease": {"amount": 70000},
            },
        },
    }
    compact = compact_cash_flow_report(report)
    assert compact["operating_activities"]["net_cash_from_operations"] == {"amount": 80000}
    assert compact["cash_reconciliation"]["ending_cash"] == {"amount": 80000}
    assert compact["report_metadata"]["type"] == "CashFlowStatement"

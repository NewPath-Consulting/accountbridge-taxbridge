"""Unit tests for deterministic benchmark scorecard."""

from app.core.benchmark.scoring import (
    build_form_990_scorecard,
    build_cash_flow_scorecard,
    build_financial_position_scorecard,
    blend_year_composite,
    _score_reconciliation,
    _ai_balance_sheet_field,
    _ai_expense_field,
    _ai_field_present,
)


def test_score_reconciliation_pass_rate():
    result = _score_reconciliation(
        [
            {"checkId": 1, "status": "PASS", "description": "Revenue check"},
            {"checkId": 2, "status": "PASS", "description": "Expense check"},
            {"checkId": 3, "status": "FAIL", "description": "Assets check", "difference": 100},
        ]
    )
    assert result["pass_count"] == 2
    assert result["fail_count"] == 1
    assert result["score"] == 66.67


def test_build_form_990_scorecard_includes_dimensions():
    manual = {
        "revenue": {"total_revenue": 100000, "contributions": 50000},
        "expenses": {"total_expenses": 80000},
        "balance_sheet": {
            "total_assets": 200000,
            "total_liabilities": 50000,
            "net_assets": 150000,
        },
    }
    ai_report = {
        "processing_time": 120.0,
        "totals": {
            "total_revenue": 100000,
            "total_expenses": 80000,
            "total_assets": 200000,
            "total_liabilities": 50000,
            "net_assets": 150000,
        },
        "part_viii_revenue": [
            {
                "category": "Contributions, Gifts, Grants",
                "totalRevenue": 50000,
            }
        ],
        "reconciliation_results": [
            {"checkId": 1, "status": "PASS", "description": "Revenue"},
            {"checkId": 2, "status": "PASS", "description": "Expenses"},
        ],
        "validation_errors": [
            {
                "errorId": "VE-001",
                "severity": "WARNING",
                "section": "Part IX",
                "description": "COGS excluded",
            }
        ],
        "warnings": [],
        "audit_flags": [],
    }
    scorecard = build_form_990_scorecard(
        fiscal_year=2025,
        manual_extraction=manual,
        prior_year_extraction=None,
        ai_report=ai_report,
        cash_flow_report={"processing_time": 60.0},
        reports_raw={"tax_return": {}, "cash_flow": {}},
    )
    assert "dimensions" in scorecard
    assert scorecard["dimensions"]["accuracy"]["score"] >= 90
    assert scorecard["dimensions"]["reconciliation"]["score"] == 100.0
    assert scorecard["composite_score"] > 0
    assert "adjusted_composite_score" in scorecard


def test_confound_flag_from_qb_data_suspect():
    manual = {
        "revenue": {"total_revenue": 356000, "contributions": 200000},
        "expenses": {"total_expenses": 311000, "program_services": 100000},
        "balance_sheet": {
            "total_assets": 532000,
            "total_liabilities": 100000,
            "net_assets": 432000,
        },
    }
    ai_report = {
        "totals": {
            "total_revenue": 260,
            "total_expenses": 0,
            "total_assets": 6360,
            "total_liabilities": 0,
            "net_assets": 6360,
        },
        "part_viii_revenue": [{"category": "Contributions", "totalRevenue": 260}],
        "part_ix_expenses": [{"classification": "Program Services", "amount": 0}],
        "reconciliation_results": [],
        "validation_errors": [],
        "warnings": [{"message": "sandbox partial year data"}],
        "audit_flags": [],
    }
    scorecard = build_form_990_scorecard(
        fiscal_year=2025,
        manual_extraction=manual,
        prior_year_extraction=None,
        ai_report=ai_report,
        cash_flow_report={},
        reports_raw={
            "data_quality_warnings": ["QB_DATA_SUSPECT: P&L total income is zero"],
            "tax_return": {},
            "cash_flow": {},
        },
    )
    codes = {f["code"] for f in scorecard["confound_flags"]}
    assert "DATA_INTEGRITY_QB" in codes
    assert scorecard["accuracy_unreliable"] is True
    # Fields are present so accuracy stays high; confound penalty reduces adjusted score
    assert scorecard["dimensions"]["accuracy"]["score"] >= 70
    assert scorecard["adjusted_composite_score"] <= scorecard["composite_score"]


def test_blend_year_composite():
    f990 = {"adjusted_composite_score": 80.0}
    cf = {"adjusted_composite_score": 60.0}
    assert blend_year_composite(f990, cf) == 0.72


def test_blend_year_composite_with_financial_position():
    f990 = {"adjusted_composite_score": 90.0}
    cf = {"adjusted_composite_score": 60.0}
    fp = {"adjusted_composite_score": 30.0}
    assert blend_year_composite(f990, cf, fp) == 0.6


def test_build_financial_position_scorecard_field_alignment():
    manual = {
        "assets": {"total_assets": 10000.0, "cash": 2000.0},
        "liabilities": {"total_liabilities": 3000.0},
        "net_assets": {"net_assets": 7000.0},
    }
    ai = {
        "processing_time": 20.0,
        "assets": {"total_assets": 10000.0, "cash": 2000.0},
        "liabilities": {"total_liabilities": 3000.0},
        "net_assets": {"net_assets": 7000.0},
        "accounting_equation": {"status": "Balanced"},
        "human_review_items": [],
        "validation_results": [],
    }
    scorecard = build_financial_position_scorecard(
        fiscal_year=2025,
        manual_extraction=manual,
        ai_report=ai,
        reports_raw={"balance_sheet": {"content": {}}},
    )
    assert scorecard["dimensions"]["accuracy"]["score"] >= 90
    assert (
        scorecard["comparison_source"]
        == "ai_balance_sheet_json_vs_manual_financial_position_extraction"
    )


def test_build_cash_flow_scorecard_field_alignment():
    """Field presence scores high even when dollar values differ."""
    manual = {
        "operating_activities": {"operating_cash_flow": 80000},
        "cash_reconciliation": {"cash_beginning": 300000, "cash_ending": 367000},
    }
    ai = {
        "processing_time": 45.0,
        "operating_activities": {"net_cash_from_operations": 250},
        "cash_reconciliation": {"beginning_cash": 5000, "ending_cash": 5000},
        "human_review_items": [],
        "validation_results": [],
    }
    scorecard = build_cash_flow_scorecard(
        fiscal_year=2025,
        manual_extraction=manual,
        ai_report=ai,
        reports_raw={"cash_flow": {"content": {"statement": {}}}},
    )
    assert scorecard["dimensions"]["accuracy"]["score"] >= 90
    assert scorecard["comparison_source"] == "ai_cash_flow_json_vs_manual_cash_flow_extraction"
    assert len(scorecard["dimensions"]["accuracy"]["field_comparisons"]) >= 1


def test_build_cash_flow_scorecard_missing_fields():
    manual = {
        "operating_activities": {"operating_cash_flow": 80000},
        "cash_reconciliation": {"cash_beginning": 300000, "cash_ending": 367000},
    }
    ai = {
        "processing_time": 45.0,
        "operating_activities": {},
        "cash_reconciliation": {},
        "human_review_items": [],
        "validation_results": [],
    }
    scorecard = build_cash_flow_scorecard(
        fiscal_year=2025,
        manual_extraction=manual,
        ai_report=ai,
        reports_raw={"cash_flow": {"content": {"statement": {}}}},
    )
    assert scorecard["dimensions"]["accuracy"]["score"] < 50


def test_part_x_accounts_payable_detected_in_liabilities_and_net_assets():
    ai_report = {
        "part_x_balance_sheet": {
            "partX_balanceSheet": {
                "liabilitiesAndNetAssets": [
                    {
                        "lineNumber": "17",
                        "label": "Accounts payable and accrued expenses",
                        "endOfYear": 0.0,
                    }
                ],
            }
        }
    }
    present, amount = _ai_balance_sheet_field(ai_report, "accounts_payable")
    assert present is True
    assert amount == 0.0


def test_expense_functional_rollups_from_normalized_section():
    ai_report = {
        "expenses": {
            "total_expenses": 80000.0,
            "program_services": 50000.0,
            "management_general": 25000.0,
            "fundraising": 5000.0,
        },
        "partIX_totals": {
            "totalProgramServices": 50000.0,
            "totalManagementAndGeneral": 25000.0,
            "totalFundraising": 5000.0,
        },
    }
    present, amount = _ai_expense_field(ai_report, "program_services")
    assert present is True
    assert amount == 50000.0


def test_reconciliation_fields_from_normalized_section():
    ai_report = {
        "reconciliation": {
            "beginning_net_assets": 140000.0,
            "change_in_net_assets": 10000.0,
            "ending_net_assets": 150000.0,
        },
        "totals": {
            "beginning_net_assets": 140000.0,
            "change_in_net_assets": 10000.0,
            "ending_net_assets": 150000.0,
        },
    }
    for field in ("beginning_net_assets", "change_in_net_assets", "ending_net_assets"):
        present, amount = _ai_field_present(ai_report, "reconciliation", field)
        assert present is True
        assert amount is not None


def test_confound_flag_from_wa_period_empty():
    manual = {
        "revenue": {"total_revenue": 100000, "membership_dues": 50000},
        "expenses": {"total_expenses": 80000},
        "balance_sheet": {"total_assets": 200000, "net_assets": 150000},
    }
    ai_report = {
        "totals": {"total_revenue": 100000, "total_expenses": 80000, "net_assets": 150000},
        "reconciliation_results": [],
        "validation_errors": [],
        "warnings": [],
        "audit_flags": [],
    }
    scorecard = build_form_990_scorecard(
        fiscal_year=2025,
        manual_extraction=manual,
        prior_year_extraction=None,
        ai_report=ai_report,
        cash_flow_report={},
        reports_raw={
            "data_quality_warnings": [
                "WA_PERIOD_EMPTY: No WildApricot financial activity in the reporting period."
            ],
            "tax_return": {},
            "cash_flow": {},
        },
    )
    codes = {f["code"] for f in scorecard["confound_flags"]}
    assert "DATA_INTEGRITY_WA_EMPTY" in codes

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
    _ai_revenue_field,
    _detect_confound_flags,
    _part_x_rollup,
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
    assert scorecard["adjusted_composite_score"] <= scorecard["composite_score"]

    # This fixture reports 260 against a reference of 356,000. It used to score
    # 100 for accuracy, because the score counted a field as matched whenever
    # the AI had the field at all. Figures this far apart must score near zero;
    # the confound flag says the input was suspect, not that the output was
    # right.
    assert scorecard["dimensions"]["accuracy"]["score"] == 0.0


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


# --- a return with no Part VIII ------------------------------------------
#
# Part VIII is the return's statement of revenue. When it is absent the
# report still carries a `revenue` block, but that block is built by keyword
# matching and does not agree with the return: on the run that prompted this,
# it read contributions of 57,654 against a Part VIII of 271,654 and still
# scored a composite of 96.79. These fix the figure being substituted.


def _part_viii_items():
    """Four line items whose families are settled by the IRS layout of Part VIII:
    line 1 is contributions, line 2 program service revenue, line 3 investment.
    """
    return [
        {"lineNumber": "1b", "label": "Annual Membership Dues", "totalRevenue": 214000.0},
        {"lineNumber": "1f", "label": "Sponsorship Income", "totalRevenue": 57654.0},
        {"lineNumber": "2a", "label": "Conference Registration", "totalRevenue": 32200.0},
        {"lineNumber": "3", "label": "Interest on Reserves", "totalRevenue": 1652.0},
    ]


def test_a_family_is_unavailable_when_the_return_has_no_part_viii():
    keyword_block = {
        "contributions": 57654.0,
        "program_service_revenue": 167200.0,
        "investment_income": 1652.0,
    }
    ai_report = {"revenue": dict(keyword_block)}

    for field, wrong_value in keyword_block.items():
        present, value = _ai_revenue_field(ai_report, field)
        assert present is False, field
        assert value is None, field
        assert value != wrong_value, field


def test_the_stated_total_is_still_read_without_part_viii():
    """The total is enforced from the ledger, so it is right even when the
    line items are missing. Only the families are unavailable."""
    ai_report = {"revenue": {"total_revenue": 305506.0}}
    present, value = _ai_revenue_field(ai_report, "total_revenue")
    assert present is True
    assert value == ai_report["revenue"]["total_revenue"]


def test_part_viii_wins_over_the_keyword_block_when_both_are_present():
    items = _part_viii_items()
    ai_report = {
        "part_viii_revenue": items,
        # deliberately disagreeing, so the assertion shows which one was read
        "revenue": {"contributions": 57654.0, "program_service_revenue": 167200.0},
    }

    expected = {
        "contributions": sum(
            i["totalRevenue"] for i in items if i["lineNumber"].startswith("1")
        ),
        "program_service_revenue": sum(
            i["totalRevenue"] for i in items if i["lineNumber"].startswith("2")
        ),
        "investment_income": sum(
            i["totalRevenue"] for i in items if i["lineNumber"].startswith("3")
        ),
    }
    for field, amount in expected.items():
        present, value = _ai_revenue_field(ai_report, field)
        assert present is True, field
        assert value == amount, field


def test_a_family_with_no_line_items_is_zero_not_unavailable():
    """2020 had no program service revenue at all and the filed return says so."""
    ai_report = {"part_viii_revenue": [_part_viii_items()[0]]}
    present, value = _ai_revenue_field(ai_report, "program_service_revenue")
    assert present is True
    assert value == 0.0


def test_missing_part_viii_is_flagged_high():
    flags = _detect_confound_flags(
        ai_report={"revenue": {"contributions": 57654.0}},
        cash_flow_report={},
        reports_raw={},
        fiscal_year=2024,
        field_rows=[],
    )
    flag = next((f for f in flags if f["code"] == "MISSING_PART_VIII"), None)
    assert flag is not None
    assert flag["severity"] == "HIGH"


def test_no_flag_when_part_viii_is_present():
    flags = _detect_confound_flags(
        ai_report={"part_viii_revenue": _part_viii_items()},
        cash_flow_report={},
        reports_raw={},
        fiscal_year=2024,
        field_rows=[],
    )
    assert "MISSING_PART_VIII" not in {f["code"] for f in flags}


def test_a_return_with_no_part_viii_is_penalised_rather_than_scored_excellent():
    items = _part_viii_items()
    manual = {
        "revenue": {
            "contributions": sum(
                i["totalRevenue"] for i in items if i["lineNumber"].startswith("1")
            ),
            "program_service_revenue": sum(
                i["totalRevenue"] for i in items if i["lineNumber"].startswith("2")
            ),
            "investment_income": sum(
                i["totalRevenue"] for i in items if i["lineNumber"].startswith("3")
            ),
            "total_revenue": sum(i["totalRevenue"] for i in items),
        },
        "expenses": {"total_expenses": 273306.0},
        "balance_sheet": {"total_assets": 192028.0},
    }
    ai_report = {
        # the keyword block, disagreeing with the reference, and no Part VIII
        "revenue": {"contributions": 57654.0, "program_service_revenue": 167200.0},
        "totals": {"total_revenue": manual["revenue"]["total_revenue"]},
        "reconciliation_results": [],
    }
    scorecard = build_form_990_scorecard(
        fiscal_year=2024,
        manual_extraction=manual,
        prior_year_extraction=None,
        ai_report=ai_report,
        cash_flow_report={},
        reports_raw={"tax_return": {}, "cash_flow": {}},
    )

    assert "MISSING_PART_VIII" in {f["code"] for f in scorecard["confound_flags"]}
    assert scorecard["confound_penalty"] > 0
    assert scorecard["adjusted_composite_score"] < scorecard["composite_score"]

    # The point of the fix: this used to read the keyword block's figures and
    # rate the result "excellent". A return with no statement of revenue is
    # not excellent, whatever its other fields say.
    assert scorecard["composite_rating"] != "excellent"


# --- the balance sheet comes from the enforced Part X ---------------------
#
# Part X is computed from the ledger and its net assets are derived as assets
# less liabilities. `totals` is not: on a 2024 run Part X said 192,028 and
# `totals.net_assets` still carried the model's uncorrected 217,675, and the
# scorer read the second one.


def _part_x(assets, liabilities, *, total_net_assets=None):
    part_x = {
        "totalAssets": {"beginningOfYear": 0.0, "endOfYear": assets},
        "totalLiabilities": {"beginningOfYear": 0.0, "endOfYear": liabilities},
    }
    if total_net_assets is not None:
        part_x["netAssets"] = {
            "totalNetAssets": {"beginningOfYear": 0.0, "endOfYear": total_net_assets}
        }
    return part_x


def test_part_x_wins_over_the_models_totals_block():
    assets, liabilities = 192028.0, 0.0
    ai_report = {
        "part_x_balance_sheet": _part_x(assets, liabilities, total_net_assets=assets),
        # the model's uncorrected figures, deliberately disagreeing
        "totals": {"net_assets": 217675.0, "total_assets": None},
        "balance_sheet": {"cash": assets},
    }
    present, value = _ai_balance_sheet_field(ai_report, "net_assets")
    assert present is True
    assert value == assets
    assert value != ai_report["totals"]["net_assets"]


def test_net_assets_is_derived_when_part_x_states_no_total():
    assets, liabilities = 250000.0, 40000.0
    ai_report = {"part_x_balance_sheet": _part_x(assets, liabilities)}
    assert _part_x_rollup(ai_report)["net_assets"] == assets - liabilities


def test_zero_liabilities_are_read_not_skipped():
    """CRN reports no liabilities at all; 0.0 is a value, not a missing field."""
    ai_report = {"part_x_balance_sheet": _part_x(192028.0, 0.0)}
    present, value = _ai_balance_sheet_field(ai_report, "total_liabilities")
    assert present is True
    assert value == 0.0


def test_without_part_x_the_old_path_still_works():
    ai_report = {"balance_sheet": {"total_assets": 5000.0}}
    assert _part_x_rollup(ai_report) == {}
    present, value = _ai_balance_sheet_field(ai_report, "total_assets")
    assert present is True
    assert value == ai_report["balance_sheet"]["total_assets"]


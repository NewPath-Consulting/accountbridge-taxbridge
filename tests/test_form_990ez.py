"""Tests for Form 990-EZ output.

The EZ collapses the full form's eleven revenue lines into five and its
twenty-five expense lines into three. The tests concentrate on that mapping
holding its arithmetic, because the IRS checks two identities on the face of
the form: line 9 against its components, and line 27 against assets less
liabilities.
"""

import json
from pathlib import Path

import pytest

from app.utils.form_990ez import build_form_990ez

FIXTURE = Path(__file__).parent / "fixtures" / "qb_pl_2026.json"


@pytest.fixture(scope="module")
def pl_report() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def enforced_content() -> dict:
    """Content after enforcement: Part VIII carrying ledger amounts."""
    return {
        "partVIII_revenue": [
            {"lineNumber": "1a", "category": "Contributions, Gifts, Grants",
             "label": "Design income", "totalRevenue": 2250.00},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Landscaping Services", "totalRevenue": 1477.50},
            {"lineNumber": "2b", "category": "Program Service Revenue",
             "label": "Pest Control Services", "totalRevenue": 110.00},
            {"lineNumber": "2c", "category": "Program Service Revenue",
             "label": "Sales of Product Income", "totalRevenue": 912.75},
            {"lineNumber": "2d", "category": "Program Service Revenue",
             "label": "Services", "totalRevenue": 503.55},
            {"lineNumber": "11a", "category": "Other Revenue",
             "label": "Discounts given", "totalRevenue": -89.50},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Fountains and Garden Lighting", "totalRevenue": 2246.50},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Plants and Soil", "totalRevenue": 2351.97},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Sprinklers and Drip Systems", "totalRevenue": 138.00},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Installation", "totalRevenue": 250.00},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Maintenance and Repair", "totalRevenue": 50.00},
        ],
        "partVIII_totalRevenue": 10200.77,
        "partIX_totals": {"totalExpenses": 8558.31},
        "partX_balanceSheet": {
            "assets": [
                {"label": "Cash", "beginningOfYear": 0.0, "endOfYear": 2001.00},
                {"label": "Accounts Receivable", "beginningOfYear": 0.0, "endOfYear": 5281.52},
                {"label": "Other Current Assets", "beginningOfYear": 0.0, "endOfYear": 2658.77},
                {"label": "Fixed Assets", "beginningOfYear": 0.0, "endOfYear": 13495.00},
            ],
            "totalAssets": {"beginningOfYear": 0.0, "endOfYear": 23436.29},
            "totalLiabilities": {"beginningOfYear": 0.0, "endOfYear": 31131.33},
            "netAssets": {
                "totalNetAssets": {"beginningOfYear": 0.0, "endOfYear": -7695.04}
            },
        },
    }


# --- Part I revenue -------------------------------------------------------

def test_line_9_equals_the_sum_of_its_components(enforced_content):
    """The first identity on the face of the form."""
    ez = build_form_990ez(enforced_content)
    part_i = ez.part_i
    components = (
        part_i["line_1_contributions"]
        + part_i["line_2_program_service_revenue"]
        + part_i["line_3_membership_dues"]
        + part_i["line_4_investment_income"]
        + part_i["line_8_other_revenue"]
    )
    assert round(components, 2) == part_i["line_9_total_revenue"]


def test_total_revenue_matches_the_ledger(enforced_content):
    ez = build_form_990ez(enforced_content)
    assert ez.part_i["line_9_total_revenue"] == 10200.77


def test_contributions_map_to_line_1(enforced_content):
    ez = build_form_990ez(enforced_content)
    assert ez.part_i["line_1_contributions"] == 2250.00


def test_program_service_revenue_is_aggregated(enforced_content):
    """Part VIII lines 2a through 2d collapse into a single EZ line 2."""
    ez = build_form_990ez(enforced_content)
    expected = 1477.50 + 110.00 + 912.75 + 503.55 + 2246.50 + 2351.97 + 138.00 + 250.00 + 50.00
    assert ez.part_i["line_2_program_service_revenue"] == round(expected, 2)


def test_negative_amounts_are_preserved(enforced_content):
    """'Discounts given' is -89.50 and belongs in other revenue, not dropped."""
    ez = build_form_990ez(enforced_content)
    assert ez.part_i["line_8_other_revenue"] == -89.50


def test_membership_dues_get_their_own_line(enforced_content):
    """Part VIII treats dues as contributions on line 1; the EZ separates
    them onto line 3."""
    enforced_content["partVIII_revenue"].append(
        {"lineNumber": "1a", "category": "Contributions, Gifts, Grants",
         "label": "Membership Dues", "totalRevenue": 5000.00}
    )
    enforced_content["partVIII_totalRevenue"] = 15200.77
    ez = build_form_990ez(enforced_content)
    assert ez.part_i["line_3_membership_dues"] == 5000.00
    assert ez.part_i["line_1_contributions"] == 2250.00


def test_mismatch_between_components_and_reported_total_is_reported(enforced_content):
    enforced_content["partVIII_totalRevenue"] = 99999.99
    ez = build_form_990ez(enforced_content)
    assert not ez.is_internally_consistent
    assert any("EZ_LINE_9_MISMATCH" in f for f in ez.check_failures)


# --- Part I expenses ------------------------------------------------------

def test_total_expenses_come_from_part_ix(enforced_content):
    ez = build_form_990ez(enforced_content)
    assert ez.part_i["line_17_total_expenses"] == 8558.31


def test_line_18_is_revenue_less_expenses(enforced_content):
    """The second identity on the face of the form."""
    ez = build_form_990ez(enforced_content)
    part_i = ez.part_i
    assert part_i["line_18_excess_or_deficit"] == round(
        part_i["line_9_total_revenue"] - part_i["line_17_total_expenses"], 2
    )
    assert part_i["line_18_excess_or_deficit"] == 1642.46


def test_unitemised_expenses_are_declared_not_hidden(enforced_content):
    """Lines 13 and 15 need expense detail the report endpoints do not
    provide. Carrying the total on line 16 is defensible; doing it silently
    is not."""
    ez = build_form_990ez(enforced_content)
    assert ez.part_i["line_16_other_expenses"] == 8558.31
    assert ez.part_i["line_13_professional_fees"] == 0.0
    assert any("EZ_EXPENSES_NOT_ITEMISED" in w for w in ez.warnings)


def test_expenses_fall_back_to_the_ledger(enforced_content, pl_report):
    enforced_content["partIX_totals"] = {}
    ez = build_form_990ez(enforced_content, pl_report)
    assert ez.part_i["line_17_total_expenses"] == 8558.31
    assert any("EZ_EXPENSES_FROM_LEDGER" in w for w in ez.warnings)


# --- Part II balance sheet ------------------------------------------------

def test_cash_and_investments_are_aggregated(enforced_content):
    ez = build_form_990ez(enforced_content)
    assert ez.part_ii["line_22_cash_savings_investments"]["end_of_year"] == 2001.00


def test_totals_carry_both_columns(enforced_content):
    ez = build_form_990ez(enforced_content)
    assets = ez.part_ii["line_25_total_assets"]
    assert assets["beginning_of_year"] == 0.0
    assert assets["end_of_year"] == 23436.29


def test_net_assets_identity_is_checked(enforced_content):
    """Assets less liabilities must equal net assets. The sandbox company is
    insolvent -- 23,436.29 less 31,131.33 is -7,695.04 -- which is unusual
    but internally consistent."""
    ez = build_form_990ez(enforced_content)
    assert ez.is_internally_consistent
    assert ez.part_ii["line_27_net_assets"]["end_of_year"] == -7695.04


def test_broken_net_assets_identity_is_reported(enforced_content):
    enforced_content["partX_balanceSheet"]["netAssets"]["totalNetAssets"][
        "endOfYear"
    ] = 999.00
    ez = build_form_990ez(enforced_content)
    assert not ez.is_internally_consistent
    assert any("EZ_LINE_27_MISMATCH" in f for f in ez.check_failures)


def test_missing_balance_sheet_is_declared(enforced_content):
    del enforced_content["partX_balanceSheet"]
    ez = build_form_990ez(enforced_content)
    assert any("EZ_PART_II_EMPTY" in w for w in ez.warnings)


# --- shape ----------------------------------------------------------------

def test_as_dict_carries_both_parts(enforced_content):
    result = build_form_990ez(enforced_content).as_dict()
    assert result["form"] == "990-EZ"
    assert "line_9_total_revenue" in result["part_i_revenue_expenses"]
    assert "line_25_total_assets" in result["part_ii_balance_sheet"]
    assert result["is_internally_consistent"] is True


def test_empty_content_produces_a_zero_return(enforced_content):
    ez = build_form_990ez({})
    assert ez.part_i["line_9_total_revenue"] == 0.0
    assert ez.part_i["line_18_excess_or_deficit"] == 0.0

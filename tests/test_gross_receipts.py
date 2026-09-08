"""Tests for IRS-definition gross receipts and figure propagation.

Gross receipts decides which form an organization files. Part VIII line 12
is revenue *net* of costs; the filing thresholds are tested against total
receipts *before* subtracting anything. On the sandbox fixture the two differ
by the 405.00 of cost of goods sold -- immaterial there, decisive for an
organization near a threshold.
"""

import json
from pathlib import Path

import pytest

from app.utils.form_990_propagate import propagate_enforced_totals
from app.utils.gross_receipts import (
    gross_receipts_from_pl,
    normally_gross_receipts,
    rolling_average_gross_receipts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qb_pl_2026.json"

QUICKBOOKS_INCOME = 10200.77
QUICKBOOKS_COGS = 405.00
GROSS_RECEIPTS = 10605.77


@pytest.fixture(scope="module")
def pl_report() -> dict:
    return json.loads(FIXTURE.read_text())


# --- the definition -------------------------------------------------------

def test_gross_receipts_adds_back_cost_of_goods_sold(pl_report):
    gr = gross_receipts_from_pl(pl_report)
    assert gr.revenue == QUICKBOOKS_INCOME
    assert gr.cost_of_goods_sold == QUICKBOOKS_COGS
    assert gr.total == GROSS_RECEIPTS


def test_gross_receipts_differs_from_total_revenue(pl_report):
    """Guards the premise. If these ever match, the fixture has no COGS and
    the test is no longer exercising the distinction it exists to check."""
    gr = gross_receipts_from_pl(pl_report)
    assert gr.total != gr.revenue


def test_components_are_reported_for_audit(pl_report):
    gr = gross_receipts_from_pl(pl_report)
    basis = gr.as_dict()
    assert basis["gross_receipts"] == GROSS_RECEIPTS
    assert basis["total_revenue"] == QUICKBOOKS_INCOME
    assert basis["cost_of_goods_sold_added_back"] == QUICKBOOKS_COGS


def test_other_costs_can_be_added_back(pl_report):
    """Direct fundraising and gaming expenses are netted in Part VIII lines 8
    and 9 and must be added back too, when identifiable."""
    gr = gross_receipts_from_pl(pl_report, other_costs_added_back=1500.00)
    assert gr.total == round(GROSS_RECEIPTS + 1500.00, 2)


def test_no_report_returns_none():
    """'No data' must be distinguishable from 'genuinely zero'."""
    assert gross_receipts_from_pl({}) is None
    assert gross_receipts_from_pl(None) is None


# --- the threshold decision this feeds ------------------------------------

def test_crossing_the_50k_threshold_on_costs_alone():
    """The case the definition exists for: revenue under 50,000 but gross
    receipts over it, because costs were netted away."""
    report = {
        "Rows": {
            "Row": [
                {
                    "group": "Income",
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Income"}, {"value": ""}]},
                    "Rows": {"Row": [
                        {"ColData": [{"value": "Sales", "id": "1"},
                                     {"value": "49800.00"}], "type": "Data"}
                    ]},
                    "Summary": {"ColData": [{"value": "Total Income"},
                                            {"value": "49800.00"}]},
                },
                {
                    "group": "COGS",
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Cost of Goods Sold"}, {"value": ""}]},
                    "Rows": {"Row": [
                        {"ColData": [{"value": "COGS", "id": "2"},
                                     {"value": "1000.00"}], "type": "Data"}
                    ]},
                    "Summary": {"ColData": [{"value": "Total COGS"},
                                            {"value": "1000.00"}]},
                },
            ]
        }
    }
    gr = gross_receipts_from_pl(report)
    assert gr.revenue == 49800.00
    assert gr.total == 50800.00
    assert gr.revenue < 50000 < gr.total


# --- the "normally" test --------------------------------------------------

def test_rolling_average_over_three_years():
    assert rolling_average_gross_receipts([30000, 45000, 60000]) == 45000.00


def test_rolling_average_ignores_missing_years():
    assert rolling_average_gross_receipts([40000, None, 60000]) == 50000.00


def test_rolling_average_of_nothing_is_none():
    assert rolling_average_gross_receipts([]) is None
    assert rolling_average_gross_receipts([None, None]) is None


@pytest.mark.parametrize(
    "current,priors,expected_basis",
    [
        (50000.0, [48000.0, 52000.0], "rolling_average_3yr"),
        (50000.0, [48000.0], "rolling_average_2yr_partial"),
        (50000.0, [], "current_year_only"),
        (None, [48000.0, 52000.0], "prior_years_only"),
        (None, [], "no_data"),
    ],
)
def test_normally_reports_how_it_decided(current, priors, expected_basis):
    """The caller is told which basis was used, because a decision made on a
    single year is weaker evidence and may warrant review."""
    _, basis = normally_gross_receipts(current, priors)
    assert basis == expected_basis


def test_normally_uses_only_the_three_most_recent_years():
    value, basis = normally_gross_receipts(60000.0, [30000.0, 30000.0, 999999.0])
    assert basis == "rolling_average_3yr"
    assert value == 40000.00


# --- propagation ----------------------------------------------------------

@pytest.fixture
def enforced_content() -> dict:
    """Content as it stands after enforcement: Part VIII corrected, the
    mirrored blocks still carrying the model's original figures."""
    return {
        "partVIII_totalRevenue": QUICKBOOKS_INCOME,
        "partIX_totals": {"totalExpenses": 8558.31},
        "partI_summary": {
            "revenueExpenseSummary": {
                "line12_totalRevenue": {"priorYear": None, "currentYear": 10210.77},
                "line18_totalExpenses": {"priorYear": None, "currentYear": 15678.32},
                "line19_revenueLessExpenses": {"priorYear": None, "currentYear": -5467.55},
            }
        },
        "organization_summary": {"gross_receipts": 10210.77, "tax_year": "2026"},
        "totals": {"total_revenue": 10210.77, "total_expenses": 15678.32},
    }


def test_part_i_line12_follows_part_viii(pl_report, enforced_content):
    out, _ = propagate_enforced_totals(enforced_content, pl_report)
    summary = out["partI_summary"]["revenueExpenseSummary"]
    assert summary["line12_totalRevenue"]["currentYear"] == QUICKBOOKS_INCOME


def test_part_i_line19_is_recomputed(pl_report, enforced_content):
    out, _ = propagate_enforced_totals(enforced_content, pl_report)
    summary = out["partI_summary"]["revenueExpenseSummary"]
    assert summary["line19_revenueLessExpenses"]["currentYear"] == round(
        QUICKBOOKS_INCOME - 8558.31, 2
    )


def test_prior_year_column_is_preserved(pl_report, enforced_content):
    enforced_content["partI_summary"]["revenueExpenseSummary"][
        "line12_totalRevenue"
    ]["priorYear"] = 9000.0
    out, _ = propagate_enforced_totals(enforced_content, pl_report)
    summary = out["partI_summary"]["revenueExpenseSummary"]
    assert summary["line12_totalRevenue"]["priorYear"] == 9000.0


def test_totals_block_follows(pl_report, enforced_content):
    out, _ = propagate_enforced_totals(enforced_content, pl_report)
    assert out["totals"]["total_revenue"] == QUICKBOOKS_INCOME
    assert out["totals"]["total_expenses"] == 8558.31


def test_gross_receipts_replaces_the_stale_revenue_figure(pl_report, enforced_content):
    """This is the field a routing decision reads. It held the model's
    10,210.77; it must hold the IRS figure of 10,605.77."""
    out, _ = propagate_enforced_totals(enforced_content, pl_report)
    assert out["organization_summary"]["gross_receipts"] == GROSS_RECEIPTS


def test_gross_receipts_basis_is_recorded(pl_report, enforced_content):
    out, _ = propagate_enforced_totals(enforced_content, pl_report)
    basis = out["organization_summary"]["gross_receipts_basis"]
    assert basis["total_revenue"] == QUICKBOOKS_INCOME
    assert basis["cost_of_goods_sold_added_back"] == QUICKBOOKS_COGS


def test_every_change_is_reported(pl_report, enforced_content):
    _, notes = propagate_enforced_totals(enforced_content, pl_report)
    prefixes = [n.split(":")[0] for n in notes]
    assert "PART_I_LINE12_CORRECTED" in prefixes
    assert "PART_I_LINE18_CORRECTED" in prefixes
    assert "PART_I_LINE19_CORRECTED" in prefixes
    assert "TOTALS_REVENUE_CORRECTED" in prefixes
    assert "GROSS_RECEIPTS_CORRECTED" in prefixes


def test_missing_ledger_leaves_gross_receipts_alone(enforced_content):
    out, notes = propagate_enforced_totals(enforced_content, {})
    assert out["organization_summary"]["gross_receipts"] == 10210.77
    assert not any(n.startswith("GROSS_RECEIPTS") for n in notes)


def test_absent_blocks_are_tolerated(pl_report):
    content = {"partVIII_totalRevenue": 100.0}
    out, notes = propagate_enforced_totals(content, pl_report)
    assert out["organization_summary"]["gross_receipts"] == GROSS_RECEIPTS

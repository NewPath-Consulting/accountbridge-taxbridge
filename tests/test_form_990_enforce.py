"""Tests for deterministic amount enforcement.

`MODEL_OUTPUT` below is the Part VIII the language model actually produced on
the first live run against the sandbox company. Its line items sum to
27,042.82, it states a total of 10,210.77, and QuickBooks reports 10,200.77 --
three figures, none of which agree. These tests assert that enforcement
resolves all three.
"""

import json
from pathlib import Path

import pytest

from app.utils.form_990_enforce import (
    enforce_deterministic_amounts,
    enforce_part_viii_amounts,
    normalise_account_label,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qb_pl_2026.json"

QUICKBOOKS_INCOME_TOTAL = 10200.77
MODEL_STATED_TOTAL = 10210.77
MODEL_LINE_ITEM_SUM = 27042.82


@pytest.fixture(scope="module")
def pl_report() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def model_output() -> dict:
    return {
        "partVIII_revenue": [
            {"lineNumber": "1a", "category": "Contributions, Gifts, Grants",
             "label": "Design income", "totalRevenue": 2250.00},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": "Total Landscaping Services", "totalRevenue": 6513.97},
            {"lineNumber": "2b", "category": "Program Service Revenue",
             "label": "Pest Control Services", "totalRevenue": 110.00},
            {"lineNumber": "2c", "category": "Program Service Revenue",
             "label": "Sales of Product Income", "totalRevenue": 912.75},
            {"lineNumber": "2d", "category": "Program Service Revenue",
             "label": "Services", "totalRevenue": 503.55},
            {"lineNumber": "11a", "category": "Other Revenue",
             "label": "Miscellaneous Income", "totalRevenue": 16752.55},
        ],
        "partVIII_totalRevenue": MODEL_STATED_TOTAL,
        "partIX_totals": {"totalExpenses": 15678.32},
    }


# --- the premise ----------------------------------------------------------

def test_model_output_is_internally_inconsistent(model_output):
    """Guards the fixture: if this stops failing, the premise has changed."""
    line_sum = round(sum(i["totalRevenue"] for i in model_output["partVIII_revenue"]), 2)
    assert line_sum == MODEL_LINE_ITEM_SUM
    assert model_output["partVIII_totalRevenue"] != line_sum
    assert model_output["partVIII_totalRevenue"] != QUICKBOOKS_INCOME_TOTAL


# --- the invariant --------------------------------------------------------

def test_line_items_sum_to_stated_total(pl_report, model_output):
    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    line_sum = round(sum(i["totalRevenue"] for i in out["partVIII_revenue"]), 2)
    assert line_sum == out["partVIII_totalRevenue"]


def test_total_equals_quickbooks(pl_report, model_output):
    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    assert out["partVIII_totalRevenue"] == QUICKBOOKS_INCOME_TOTAL


# --- each observed fault --------------------------------------------------

def test_fabricated_line_is_dropped(pl_report, model_output):
    """'Miscellaneous Income' 16,752.55 does not exist. The real account is
    'Miscellaneous' 2,916.00 and it sits under Other Expenses."""
    out, notes = enforce_part_viii_amounts(model_output, pl_report)
    labels = [i["label"] for i in out["partVIII_revenue"]]
    assert "Miscellaneous Income" not in labels
    assert any("PART_VIII_DROPPED" in n and "Miscellaneous Income" in n for n in notes)


def test_omitted_account_is_added(pl_report, model_output):
    """'Discounts given' -89.50 was absent from the model output."""
    out, notes = enforce_part_viii_amounts(model_output, pl_report)
    discounts = next(
        i for i in out["partVIII_revenue"] if i["label"] == "Discounts given"
    )
    assert discounts["totalRevenue"] == -89.50
    assert any("PART_VIII_ADDED" in n and "Discounts given" in n for n in notes)


def test_summary_label_resolves_to_parent_account_amount(pl_report, model_output):
    """The model labelled a line 'Total Landscaping Services' with 6,513.97.
    That is the section subtotal; the account itself holds 1,477.50 posted
    directly, with the remainder in its children."""
    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    parent = next(
        i for i in out["partVIII_revenue"] if i["label"] == "Landscaping Services"
    )
    assert parent["totalRevenue"] == 1477.50


def test_child_accounts_inherit_parent_classification(pl_report, model_output):
    """Accounts beneath a classified parent are program service revenue too,
    not Other Revenue by name-matching fallback."""
    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    child = next(
        i for i in out["partVIII_revenue"] if i["label"] == "Plants and Soil"
    )
    assert child["category"] == "Program Service Revenue"
    assert child["lineNumber"] == "2a"


def test_part_ix_total_comes_from_the_ledger(pl_report, model_output):
    """5,237.31 expenses + 405.00 COGS + 2,916.00 other = 8,558.31."""
    out, _ = enforce_deterministic_amounts(model_output, pl_report)
    assert out["partIX_totals"]["totalExpenses"] == 8558.31


# --- every account represented exactly once -------------------------------

def test_no_account_appears_twice(pl_report, model_output):
    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    labels = [i["label"] for i in out["partVIII_revenue"]]
    assert len(labels) == len(set(labels))


def test_every_income_account_is_represented(pl_report, model_output):
    from app.utils.form_990_totals import section_rows

    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    reported = {normalise_account_label(i["label"]) for i in out["partVIII_revenue"]}
    for account in section_rows(pl_report, "Income"):
        assert normalise_account_label(account.name) in reported


def test_source_account_ids_are_carried(pl_report, model_output):
    """Provenance: each line records the QuickBooks account it came from."""
    out, _ = enforce_part_viii_amounts(model_output, pl_report)
    design = next(
        i for i in out["partVIII_revenue"] if i["label"] == "Design income"
    )
    assert design["sourceAccountId"] == "82"


# --- notes are usable as validation warnings ------------------------------

def test_every_change_is_reported(pl_report, model_output):
    _, notes = enforce_deterministic_amounts(model_output, pl_report)
    assert any(n.startswith("PART_VIII_DROPPED") for n in notes)
    assert any(n.startswith("PART_VIII_ADDED") for n in notes)
    assert any(n.startswith("PART_VIII_CORRECTED") for n in notes)
    assert any(n.startswith("PART_VIII_TOTAL_CORRECTED") for n in notes)
    assert any(n.startswith("PART_IX_TOTAL_CORRECTED") for n in notes)


# --- label matching -------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Total Landscaping Services", "landscaping services"),
        ("Landscaping Services", "landscaping services"),
        ("Legal & Professional Fees", "legal professional fees"),
        ("  Design  income  ", "design income"),
        ("", ""),
        (None, ""),
    ],
)
def test_label_normalisation(raw, expected):
    assert normalise_account_label(raw) == expected


# --- degrades safely ------------------------------------------------------

def test_missing_quickbooks_data_leaves_content_untouched(model_output):
    out, notes = enforce_part_viii_amounts(model_output, {})
    assert out["partVIII_totalRevenue"] == MODEL_STATED_TOTAL
    assert any("PART_VIII_NOT_ENFORCED" in n for n in notes)


def test_empty_model_output_is_populated_from_the_ledger(pl_report):
    content = {"partVIII_revenue": [], "partVIII_totalRevenue": 0}
    out, _ = enforce_part_viii_amounts(content, pl_report)
    assert out["partVIII_totalRevenue"] == QUICKBOOKS_INCOME_TOTAL
    assert len(out["partVIII_revenue"]) > 0

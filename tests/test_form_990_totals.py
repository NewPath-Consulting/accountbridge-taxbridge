"""Tests for the deterministic P&L totals engine.

The fixture is a real QuickBooks ProfitAndLoss payload from the Humber
sandbox company. Its shape matters as much as its numbers: it contains a
Section that carries an amount on its own Header (money posted to a parent
account directly) as well as children, which is the case that defeats both
naive strategies -- summing leaves drops it, adding subtotals counts it twice.
"""

import json
from pathlib import Path

import pytest

from app.utils.form_990_totals import (
    _money,
    iter_accounts,
    section_rows,
    section_total,
    section_totals,
    verify_section,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qb_pl_2026.json"


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(FIXTURE.read_text())


# --- the headline figures -------------------------------------------------

def test_section_totals_match_quickbooks(report):
    totals = section_totals(report)
    assert totals["income"] == 10200.77
    assert totals["cogs"] == 405.00
    assert totals["expenses"] == 5237.31
    assert totals["other_expenses"] == 2916.00


def test_derived_sections_are_excluded(report):
    """Gross Profit and Net Income are computed by QuickBooks from the other
    sections. Including them would double count the entire report."""
    totals = section_totals(report)
    for key in ("gross_profit", "net_operating_income", "net_income"):
        assert key not in totals


# --- the invariant that makes every downstream figure trustworthy ---------

@pytest.mark.parametrize(
    "group", ["Income", "COGS", "Expenses", "OtherExpenses"]
)
def test_walked_accounts_sum_to_reported_total(report, group):
    """Each account counted exactly once, summing to QuickBooks' own total.

    A non-zero delta means an account was missed or counted twice.
    """
    walked, reported, delta = verify_section(report, group)
    assert delta == 0.0, (
        f"{group}: walked {walked} against reported {reported}"
    )


# --- the specific failures observed in the first live run ----------------

def test_parent_postings_are_not_dropped(report):
    """'Landscaping Services' has 1477.50 posted to the parent account plus
    children totalling 5036.47. Summing only leaves would lose the 1477.50."""
    rows = section_rows(report, "Income")
    parent = next(a for a in rows if a.name == "Landscaping Services")
    assert parent.is_parent is True
    assert parent.amount == 1477.50


def test_subtotals_are_never_emitted_as_accounts(report):
    """A Summary is a total of rows already counted. If one leaks into the
    account list the section will over-report -- this is the defect that
    produced 27,042.82 against a true total of 10,200.77."""
    names = [a.name for a in section_rows(report, "Income")]
    assert not any(n.lower().startswith("total ") for n in names)


def test_negative_contra_accounts_are_included(report):
    """'Discounts given' is -89.50 and was absent from the model's output."""
    rows = section_rows(report, "Income")
    discounts = next(a for a in rows if a.name == "Discounts given")
    assert discounts.amount == -89.50


def test_miscellaneous_is_an_expense_not_revenue(report):
    """The model reported 'Miscellaneous Income' of 16,752.55 in Part VIII.
    The account is 2,916.00 and sits under Other Expenses."""
    assert not any(
        a.name == "Miscellaneous" for a in section_rows(report, "Income")
    )
    other = section_rows(report, "OtherExpenses")
    misc = next(a for a in other if a.name == "Miscellaneous")
    assert misc.amount == 2916.00


# --- account metadata used downstream for classification ------------------

def test_accounts_carry_quickbooks_ids(report):
    rows = section_rows(report, "Income")
    design = next(a for a in rows if a.name == "Design income")
    assert design.account_id == "82"


def test_nesting_depth_is_recorded(report):
    rows = section_rows(report, "Income")
    top = next(a for a in rows if a.name == "Design income")
    nested = next(a for a in rows if a.name == "Plants and Soil")
    assert top.depth == 0
    assert nested.depth > top.depth


# --- parsing edge cases ---------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2250.00", 2250.00),
        ("-89.50", -89.50),
        ("1,477.50", 1477.50),
        ("$405.00", 405.00),
        ("(2,916.00)", -2916.00),
        ("", 0.0),
        (None, 0.0),
        ("n/a", 0.0),
        (110, 110.0),
    ],
)
def test_money_parsing(raw, expected):
    assert _money(raw) == expected


def test_empty_report_is_safe():
    assert section_totals({}) == {}
    assert section_rows({}, "Income") == []
    assert section_total({}, "Income") is None
    assert list(iter_accounts(None)) == []

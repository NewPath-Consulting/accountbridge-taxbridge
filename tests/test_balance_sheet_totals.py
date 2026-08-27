"""Tests for Part X enforcement.

Part VIII was taken away from the model in an earlier step; Part X was not.
Across two runs against the same company it reported net assets of -7,695.04
and then 23,436.29, the second being the total assets figure copied from
elsewhere on the page. Form routing reads total assets from Part X, so a
duplicated figure there can change which form an organization files.
"""

import json
from pathlib import Path

import pytest

from app.utils.balance_sheet_totals import (
    balance_sheet_totals,
    enforce_part_x,
    find_section,
    section_accounts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qb_bs_2025.json"


@pytest.fixture(scope="module")
def balance_sheet() -> dict:
    return json.loads(FIXTURE.read_text())


def _reported(section: dict) -> float:
    """The Summary total QuickBooks prints for a section."""
    from app.utils.form_990_totals import _money
    summary = (section.get("Summary") or {}).get("ColData") or []
    return round(_money(summary[1].get("value")), 2) if len(summary) > 1 else 0.0


@pytest.fixture(scope="module")
def reported_assets(balance_sheet) -> float:
    return _reported(find_section(balance_sheet, "TotalAssets") or {})


@pytest.fixture(scope="module")
def reported_liabilities(balance_sheet) -> float:
    section = find_section(balance_sheet, "Liabilities")
    return _reported(section) if section else 0.0


# --- the three figures Part X turns on ------------------------------------

def test_totals_match_the_report(balance_sheet, reported_assets, reported_liabilities):
    """Asserted against the fixture's own Summary rows, so refreshing it from
    QuickBooks does not break the test."""
    totals = balance_sheet_totals(balance_sheet)
    assert totals.total_assets == reported_assets
    assert totals.total_liabilities == reported_liabilities


def test_net_assets_are_computed_not_read(balance_sheet):
    """Assets less liabilities is the identity the IRS checks on the face of
    the form. Deriving it means the return cannot contradict itself."""
    totals = balance_sheet_totals(balance_sheet)
    assert totals.net_assets == round(
        totals.total_assets - totals.total_liabilities, 2
    )


def test_lines_sum_to_their_totals(balance_sheet):
    totals = balance_sheet_totals(balance_sheet)
    assert round(sum(a["amount"] for a in totals.assets), 2) == totals.total_assets
    assert round(sum(l["amount"] for l in totals.liabilities), 2) == totals.total_liabilities


# --- finding sections in a nested tree ------------------------------------

def test_nested_sections_are_found(balance_sheet):
    """Liabilities sits inside TotalLiabilitiesAndEquity, so a scan of the
    top level would miss it."""
    assert find_section(balance_sheet, "Liabilities") is not None
    assert find_section(balance_sheet, "AP") is not None


def test_unknown_section_returns_none(balance_sheet):
    assert find_section(balance_sheet, "NotASection") is None


def test_accounts_are_listed_for_provenance(balance_sheet):
    """Each section's accounts sum to the section's own total."""
    section = find_section(balance_sheet, "BankAccounts")
    if section is None:
        pytest.skip("this balance sheet has no bank accounts section")
    accounts = section_accounts(balance_sheet, "BankAccounts")
    assert accounts, "a section that exists should yield accounts"
    assert round(sum(a.amount for a in accounts), 2) == _reported(section)


# --- mapping onto Part X lines --------------------------------------------

def test_bank_accounts_map_to_line_1(balance_sheet):
    section = find_section(balance_sheet, "BankAccounts")
    if section is None:
        pytest.skip("this balance sheet has no bank accounts section")
    totals = balance_sheet_totals(balance_sheet)
    cash = next(a for a in totals.assets if a["lineNumber"] == "1")
    assert cash["amount"] == _reported(section)


def test_fixed_assets_map_to_line_10c(balance_sheet):
    section = find_section(balance_sheet, "FixedAssets")
    if section is None:
        pytest.skip("this balance sheet has no fixed assets section")
    totals = balance_sheet_totals(balance_sheet)
    fixed = next(a for a in totals.assets if a["lineNumber"] == "10c")
    assert fixed["amount"] == _reported(section)


def test_groups_sharing_a_line_are_combined(balance_sheet):
    """Accounts payable and credit cards are both accounts payable and
    accrued expenses, and the form has one box for them."""
    totals = balance_sheet_totals(balance_sheet)
    line_17 = [l for l in totals.liabilities if l["lineNumber"] == "17"]
    if not line_17:
        pytest.skip("this balance sheet has no payables")
    assert len(line_17) == 1, "one entry per line, not one per QuickBooks group"

    expected = sum(
        _reported(find_section(balance_sheet, g) or {})
        for g in line_17[0]["groups"]
    )
    assert line_17[0]["amount"] == round(expected, 2)


# --- enforcement ----------------------------------------------------------

@pytest.fixture
def model_output() -> dict:
    """Part X as the model produced it: net assets duplicating total assets."""
    return {
        "partX_balanceSheet": {
            "assets": [{"label": "Cash", "endOfYear": 23436.29}],
            "totalAssets": {"beginningOfYear": 0.0, "endOfYear": 23436.29},
            "totalLiabilities": {"beginningOfYear": 0.0, "endOfYear": 31131.33},
            "netAssets": {"totalNetAssets": {"endOfYear": 23436.29}},
        }
    }


def test_enforcement_replaces_the_figures(
    balance_sheet, model_output, reported_assets, reported_liabilities
):
    out, _ = enforce_part_x(model_output, balance_sheet)
    part_x = out["partX_balanceSheet"]
    assert part_x["totalAssets"]["endOfYear"] == reported_assets
    assert part_x["netAssets"]["totalNetAssets"]["endOfYear"] == round(
        reported_assets - reported_liabilities, 2
    )


def test_the_accounting_identity_holds_after_enforcement(balance_sheet, model_output):
    out, _ = enforce_part_x(model_output, balance_sheet)
    part_x = out["partX_balanceSheet"]
    assets = part_x["totalAssets"]["endOfYear"]
    liabilities = part_x["totalLiabilities"]["endOfYear"]
    net = part_x["netAssets"]["totalNetAssets"]["endOfYear"]
    assert round(assets - liabilities, 2) == net
    assert part_x["totalLiabilitiesAndNetAssets"]["endOfYear"] == assets


def test_the_duplicated_figure_is_reported(
    balance_sheet, model_output, reported_assets, reported_liabilities
):
    """The correction names both figures so a preparer can see what changed."""
    expected_net = round(reported_assets - reported_liabilities, 2)
    _, notes = enforce_part_x(model_output, balance_sheet)
    correction = next(
        (n for n in notes if n.startswith("PART_X_NET_ASSETS_CORRECTED")), None
    )
    if correction is None:
        pytest.skip("the model figure happens to match this fixture")
    assert "23436.29" in correction
    assert str(expected_net) in correction


def test_provenance_is_recorded(balance_sheet, model_output):
    """Each line carries the QuickBooks accounts behind it."""
    out, _ = enforce_part_x(model_output, balance_sheet)
    assets = out["partX_balanceSheet"]["assets"]
    if not assets:
        pytest.skip("this balance sheet has no asset sections")
    for line in assets:
        assert line["sourceSystem"] == "QuickBooks"
    assert any(line["sourceAccounts"] for line in assets)


def test_missing_balance_sheet_leaves_content_alone(model_output):
    out, notes = enforce_part_x(model_output, None)
    assert out["partX_balanceSheet"]["totalAssets"]["endOfYear"] == 23436.29
    assert any("PART_X_NOT_ENFORCED" in n for n in notes)


def test_absent_opening_balances_are_declared(balance_sheet, model_output):
    _, notes = enforce_part_x(model_output, balance_sheet)
    assert any("PART_X_NO_OPENING_BALANCES" in n for n in notes)


def test_prior_year_supplies_opening_balances(balance_sheet, model_output):
    """With a prior-year report the beginning-of-year column is populated
    rather than left at zero."""
    out, notes = enforce_part_x(
        model_output, balance_sheet, prior_report=balance_sheet
    )
    part_x = out["partX_balanceSheet"]
    assert part_x["totalAssets"]["beginningOfYear"] == part_x["totalAssets"]["endOfYear"]
    net = part_x["netAssets"]["totalNetAssets"]
    assert net["beginningOfYear"] == net["endOfYear"]
    assert not any("PART_X_NO_OPENING_BALANCES" in n for n in notes)


def test_empty_report_returns_none():
    assert balance_sheet_totals({}) is None
    assert balance_sheet_totals(None) is None

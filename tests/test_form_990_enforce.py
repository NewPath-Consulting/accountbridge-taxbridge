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


# --- Part IX columns ------------------------------------------------------

from app.utils.form_990_enforce import enforce_part_ix_columns  # noqa: E402


def _expenses(*rows):
    return {
        "partIX_expenses": [
            {"line_number": n, "label": label, "amount": amount,
             **({"classification": column} if column else {})}
            for n, label, amount, column in rows
        ],
        "partIX_totals": {},
    }


CRN_2024 = _expenses(
    ("1",   "Conference and Meeting Costs", 138000.00, "Program Services"),
    ("5",   "Management Services",           66000.00, "Management and General"),
    ("13",  "Office and Administration",      2000.00, "Management and General"),
    ("11b", "Professional Fees",             26000.00, None),
    ("12",  "Marketing and Communications",  22306.00, None),
    ("14",  "Website and Technology",        16000.00, None),
    ("23",  "Insurance",                      3000.00, None),
)


def _columns(totals):
    return round(
        totals["totalProgramServices"]
        + totals["totalManagementAndGeneral"]
        + totals["totalFundraising"], 2,
    )


def test_the_columns_account_for_the_total():
    """The identity on the face of the form. A return where the columns do
    not sum to the total contradicts itself."""
    out, _ = enforce_part_ix_columns(dict(CRN_2024), 273306.00)
    assert _columns(out["partIX_totals"]) == 273306.00


def test_classified_lines_keep_their_column():
    """The model decides which column an expense belongs to, because no
    ledger fact answers whether an insurance premium is a program cost."""
    out, _ = enforce_part_ix_columns(dict(CRN_2024), 273306.00)
    assert out["partIX_totals"]["totalProgramServices"] == 138000.00


def test_unclassified_lines_go_to_management_and_general():
    """IRS instructions put anything not directly attributable to a program
    under management and general, and it is the honest direction to guess in:
    program services is the ratio donors judge an organization by."""
    out, _ = enforce_part_ix_columns(dict(CRN_2024), 273306.00)
    # 66,000 + 2,000 classified, plus 67,306 that was not
    assert out["partIX_totals"]["totalManagementAndGeneral"] == 135306.00


def test_the_unclassified_lines_are_named():
    """A preparer needs to know what to move, not only how much."""
    _, notes = enforce_part_ix_columns(dict(CRN_2024), 273306.00)
    note = next(n for n in notes if "PART_IX_UNCLASSIFIED_LINES" in n)
    assert "Professional Fees" in note
    assert "Insurance" in note
    assert "4 expense line(s)" in note


def test_expenses_missing_from_the_lines_are_still_allocated():
    """An expense in the ledger total but absent from the line list would
    otherwise leave the columns short."""
    content = _expenses(("1", "Programs", 100000.00, "Program Services"))
    out, notes = enforce_part_ix_columns(content, 150000.00)
    assert _columns(out["partIX_totals"]) == 150000.00
    assert out["partIX_totals"]["totalManagementAndGeneral"] == 50000.00
    assert any("PART_IX_UNALLOCATED_TO_MANAGEMENT" in n for n in notes)


def test_over_allocation_is_reported_not_silently_corrected():
    """Columns claiming more than was spent means the lines are wrong.
    Scaling them down would hide a real defect."""
    content = _expenses(
        ("1", "Programs",   90000.00, "Program Services"),
        ("5", "Management", 30000.00, "Management and General"),
    )
    _, notes = enforce_part_ix_columns(content, 100000.00)
    assert any("PART_IX_OVER_ALLOCATED" in n for n in notes)


def test_column_spellings_are_recognised():
    for spelling in ("Program Services", "program", "PROGRAMS",
                     "Program Services (direct)"):
        content = _expenses(("1", "x", 100.00, spelling))
        out, _ = enforce_part_ix_columns(content, 100.00)
        assert out["partIX_totals"]["totalProgramServices"] == 100.00, spelling

    for spelling in ("Fundraising", "fund raising", "Development"):
        content = _expenses(("1", "x", 100.00, spelling))
        out, _ = enforce_part_ix_columns(content, 100.00)
        assert out["partIX_totals"]["totalFundraising"] == 100.00, spelling


def test_no_expenses_leaves_the_columns_at_zero_and_says_so():
    content = {"partIX_expenses": [], "partIX_totals": {}}
    out, notes = enforce_part_ix_columns(content, 0.0)
    assert _columns(out["partIX_totals"]) == 0.0


# --- the model abbreviates; that is not a hallucination -------------------
# Across an 18-run grid the model wrote "Membership Dues" for the account
# "Annual Membership Dues" twelve times. Exact matching dropped the line and
# the classification with it, and the rule classifier re-added the account on
# the wrong line. Every dues error in that grid came from this path.

def _income_accounts(pl_report):
    from app.utils.form_990_totals import section_rows

    return section_rows(pl_report, "Income")


def _account_with_at_least(pl_report, tokens: int):
    """An income account whose name has `tokens` words, from the fixture."""
    for account in _income_accounts(pl_report):
        if len(account.name.split()) >= tokens:
            return account
    pytest.skip(f"fixture has no income account of {tokens}+ words")


def test_an_abbreviated_label_keeps_the_model_classification(pl_report):
    account = _account_with_at_least(pl_report, 3)
    abbreviation = " ".join(account.name.split()[-2:])

    content = {
        "partVIII_revenue": [
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": abbreviation, "totalRevenue": 1.0},
        ],
    }
    out, notes = enforce_part_viii_amounts(content, pl_report)

    line = next(i for i in out["partVIII_revenue"] if i["label"] == account.name)
    assert line["category"] == "Program Service Revenue"
    assert any("PART_VIII_LABEL_MATCHED" in n and account.name in n for n in notes)
    assert not any("PART_VIII_DROPPED" in n and abbreviation in n for n in notes)


def test_an_abbreviation_cannot_take_an_account_named_outright(pl_report):
    """Exact matches resolve first, whatever order the model listed them in."""
    account = _account_with_at_least(pl_report, 3)
    abbreviation = " ".join(account.name.split()[-2:])

    content = {
        "partVIII_revenue": [
            {"lineNumber": "11d", "category": "Other Revenue",
             "label": abbreviation, "totalRevenue": 1.0},
            {"lineNumber": "2a", "category": "Program Service Revenue",
             "label": account.name, "totalRevenue": 2.0},
        ],
    }
    out, _ = enforce_part_viii_amounts(content, pl_report)

    lines = [i for i in out["partVIII_revenue"] if i["label"] == account.name]
    assert len(lines) == 1
    assert lines[0]["category"] == "Program Service Revenue"


def test_a_label_naming_nothing_is_still_dropped(pl_report):
    content = {
        "partVIII_revenue": [
            {"lineNumber": "11d", "category": "Other Revenue",
             "label": "Zzz Nonexistent Ledger Account", "totalRevenue": 999.0},
        ],
    }
    out, notes = enforce_part_viii_amounts(content, pl_report)

    labels = [i["label"] for i in out["partVIII_revenue"]]
    assert "Zzz Nonexistent Ledger Account" not in labels
    dropped = next(n for n in notes if "PART_VIII_DROPPED" in n)
    # The note records what classification was discarded, not just the amount.
    assert "11d" in dropped and "Other Revenue" in dropped


def test_an_ambiguous_abbreviation_is_not_guessed():
    from app.utils.form_990_enforce import _near_matches
    from app.utils.form_990_totals import PLAccount

    def account(name):
        return PLAccount(name, None, 0.0, 1, (name,), False)

    shared = [account("Spring Gala Income"), account("Autumn Gala Income")]
    assert len(_near_matches("Gala Income", shared)) == 2

    assert _near_matches("Income", shared) == []  # one word is never enough


# --- where regulation settles the answer, code decides --------------------
# Measured over an 18-run grid: sponsorship came out right 10/10 when the rule
# classifier decided it and about half the time when the model did.

def test_sponsorship_is_moved_to_contributions():
    from app.utils.form_990_enforce import apply_settled_classifications

    items = [{"label": "Sponsorship Income", "category": "Other Revenue",
              "lineNumber": "11d", "totalRevenue": 57654.0}]
    out, notes = apply_settled_classifications(items)

    assert out[0]["category"] == "Contributions, Gifts, Grants"
    note = next(n for n in notes if "PART_VIII_SETTLED" in n)
    # The note has to carry what was overridden and the authority for it,
    # or a preparer cannot tell a decision from a bug.
    assert "Other Revenue" in note and "513(i)" in note


def test_an_already_correct_classification_is_left_silent():
    from app.utils.form_990_enforce import apply_settled_classifications

    items = [{"label": "Sponsorship Income", "category": "Contributions, Gifts, Grants",
              "lineNumber": "1f", "totalRevenue": 57654.0}]
    out, notes = apply_settled_classifications(items)

    assert out[0]["category"] == "Contributions, Gifts, Grants"
    assert notes == []


def test_sponsorship_that_names_advertising_is_not_settled():
    """513(i) makes advertising the exception, so the account is left alone."""
    from app.utils.form_990_enforce import apply_settled_classifications

    items = [{"label": "Sponsorship Advertising", "category": "Other Revenue",
              "lineNumber": "11d", "totalRevenue": 5000.0}]
    out, notes = apply_settled_classifications(items)

    assert out[0]["category"] == "Other Revenue"
    assert notes == []


def test_accounts_the_regulation_does_not_settle_are_untouched():
    """The override is narrow on purpose: the model is better at these."""
    from app.utils.form_990_enforce import apply_settled_classifications

    items = [
        {"label": "Certification Fees", "category": "Program Service Revenue",
         "lineNumber": "2a", "totalRevenue": 3000.0},
        {"label": "Annual Membership Dues", "category": "Contributions, Gifts, Grants",
         "lineNumber": "1b", "totalRevenue": 214000.0},
    ]
    before = [dict(i) for i in items]
    out, notes = apply_settled_classifications(items)

    assert out == before
    assert notes == []


def test_the_override_reaches_a_contributions_line_number():
    """Only the category is set; the line number follows from it."""
    from app.utils.form_990_enforce import (
        apply_settled_classifications,
        assign_part_viii_lines,
        part_viii_family_for_line,
    )

    items = [{"label": "Sponsorship Income", "category": "Other Revenue",
              "lineNumber": "11d", "totalRevenue": 57654.0}]
    items, _ = apply_settled_classifications(items)
    items, _ = assign_part_viii_lines(items)

    assert part_viii_family_for_line(items[0]["lineNumber"]) == "contributions"

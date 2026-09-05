"""Give the deterministic engine authority over every reported amount.

The model classifies: it decides which IRS line an account belongs on, and it
writes the narrative. It does not decide what any number is. This module runs
after the section calls return and before normalisation, and it does three
things to Part VIII:

  * replaces each line item's amount with the figure from QuickBooks
  * drops line items naming accounts that do not exist
  * appends accounts the model omitted, classified by rule

In the first live run against the sandbox company the model reported six
revenue lines summing to 27,042.82 and stated a total of 10,210.77, while
QuickBooks reported 10,200.77. Three separate faults: a fabricated line
("Miscellaneous Income" 16,752.55, which is an expense account of 2,916.00),
an omission ("Discounts given" -89.50), and a stated total agreeing with
neither its own line items nor the ledger.

After this module runs, the line items are the accounts that exist, carrying
the amounts the ledger holds, and the total is their sum.
"""

from __future__ import annotations

import re
from typing import Any

from app.utils.form_990_mapping import classify_qb_income_account
from app.utils.form_990_totals import PLAccount, section_rows, section_totals

__all__ = [
    "enforce_part_viii_amounts",
    "enforce_deterministic_amounts",
    "normalise_account_label",
]

# Part VIII line number -> category label, matching the prompt's vocabulary.
_LINE_CATEGORY = {
    "1": "Contributions, Gifts, Grants",
    "2": "Program Service Revenue",
    "3": "Investment Income",
    "5": "Royalties",
    "8": "Fundraising Event Revenue",
    "9": "Gaming Revenue",
    "11": "Other Revenue",
}

_PROGRAM_SERVICE_LINES = {"2"}


def normalise_account_label(label: Any) -> str:
    """Reduce a label to a comparable key.

    The model tends to echo QuickBooks' own summary wording, so
    "Total Landscaping Services" has to match the account "Landscaping
    Services". Case, punctuation and the leading "Total" are all discarded.
    """
    text = str(label or "").strip().lower()
    text = re.sub(r"^total\s+", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _line_number_root(line_number: Any) -> str:
    """'2a' -> '2'. Sub-letters are presentation, not classification."""
    match = re.match(r"\s*(\d+)", str(line_number or ""))
    return match.group(1) if match else "11"


def _build_line_item(
    account: PLAccount, line_number: str, category: str
) -> dict[str, Any]:
    program = account.amount if _line_number_root(line_number) in _PROGRAM_SERVICE_LINES else 0.0
    return {
        "lineNumber": line_number,
        "category": category,
        "label": account.name,
        "totalRevenue": round(account.amount, 2),
        "programServiceRevenue": round(program, 2),
        "unrelatedBusinessRevenue": 0.0,
        "excludedRevenue": 0.0,
        "sourceSystem": "QuickBooks",
        "sourceAccountId": account.account_id,
    }


def enforce_part_viii_amounts(
    content: dict[str, Any],
    pl_report: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Rebuild Part VIII from the ledger, keeping the model's classifications.

    Returns the amended content and a list of notes describing every change,
    suitable for surfacing as validation warnings.
    """
    notes: list[str] = []
    accounts = section_rows(pl_report, "Income")
    if not accounts:
        notes.append(
            "PART_VIII_NOT_ENFORCED: no QuickBooks Income accounts available; "
            "model amounts left unchanged"
        )
        return content, notes

    index: dict[str, PLAccount] = {}
    for account in accounts:
        index.setdefault(normalise_account_label(account.name), account)

    claimed: set[str] = set()
    enforced: list[dict[str, Any]] = []
    # label -> (line number, category) for every account the model classified,
    # so descendants can inherit rather than fall back to name matching.
    classified_by_path: dict[str, tuple[str, str]] = {}

    for item in content.get("partVIII_revenue") or []:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        key = normalise_account_label(label)
        account = index.get(key)

        if account is None:
            notes.append(
                f"PART_VIII_DROPPED: '{label}' does not exist in the QuickBooks "
                f"Income accounts (model reported {item.get('totalRevenue')})"
            )
            continue

        if key in claimed:
            notes.append(f"PART_VIII_DUPLICATE: '{label}' reported more than once")
            continue

        claimed.add(key)
        model_amount = item.get("totalRevenue")
        line_number = item.get("lineNumber") or "11"
        classified_by_path[key] = (line_number, item.get("category") or "")

        amended = dict(item)
        amended.update(_build_line_item(account, line_number, item.get("category") or ""))
        # The model's category wording is kept; only the figures are replaced.
        if item.get("category"):
            amended["category"] = item["category"]
        enforced.append(amended)

        try:
            if model_amount is not None and round(float(model_amount), 2) != amended["totalRevenue"]:
                notes.append(
                    f"PART_VIII_CORRECTED: '{account.name}' {model_amount} -> "
                    f"{amended['totalRevenue']}"
                )
        except (TypeError, ValueError):
            notes.append(f"PART_VIII_CORRECTED: '{account.name}' -> {amended['totalRevenue']}")

    for account in accounts:
        key = normalise_account_label(account.name)
        if key in claimed:
            continue

        # A child account inherits the classification of the nearest ancestor
        # the model classified. When the model labelled "Total Landscaping
        # Services" as program service revenue, the accounts beneath it are
        # program service revenue too -- falling back to the name-matching
        # rule would strand them in Other Revenue.
        inherited = None
        for ancestor in reversed(account.path):
            inherited = classified_by_path.get(normalise_account_label(ancestor))
            if inherited:
                break

        if inherited:
            line_hint, category = inherited
            reason = f"inherited from '{' / '.join(account.path)}'"
        else:
            _, line_hint = classify_qb_income_account(account.name)
            category = _LINE_CATEGORY.get(line_hint, _LINE_CATEGORY["11"])
            reason = "classified by rule"

        enforced.append(_build_line_item(account, line_hint, category))
        claimed.add(key)
        notes.append(
            f"PART_VIII_ADDED: '{account.name}' {account.amount:.2f} was missing "
            f"from the model output; line {line_hint}, {reason}"
        )

    content["partVIII_revenue"] = enforced
    total = round(sum(i["totalRevenue"] for i in enforced), 2)
    previous = content.get("partVIII_totalRevenue")
    content["partVIII_totalRevenue"] = total

    try:
        if previous is not None and round(float(previous), 2) != total:
            notes.append(
                f"PART_VIII_TOTAL_CORRECTED: {previous} -> {total}"
            )
    except (TypeError, ValueError):
        pass

    return content, notes


# The Part IX columns as the IRS names them, and the strings a model is
# likely to use for each.
PART_IX_COLUMNS = {
    "totalProgramServices": (
        "program services", "program service", "program", "programs",
        "program_services", "programservices",
    ),
    "totalManagementAndGeneral": (
        "management and general", "management & general", "management",
        "administration", "administrative", "general",
        "management_and_general", "managementandgeneral",
    ),
    "totalFundraising": (
        "fundraising", "fund raising", "fund-raising", "development",
    ),
}

# Where an expense goes when the model did not say. IRS instructions put
# anything not directly attributable to a program under management and
# general, and it is the honest direction to guess in: program services is
# the figure donors judge an organization by, so defaulting there would
# flatter the return.
DEFAULT_COLUMN = "totalManagementAndGeneral"


def _amount(value: Any) -> float:
    """A figure from model output, which may arrive as a string."""
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _column_for(classification: Any) -> str | None:
    """Which Part IX column a line's classification names."""
    text = str(classification or "").strip().lower()
    if not text:
        return None
    for column, spellings in PART_IX_COLUMNS.items():
        if text in spellings:
            return column
    # Fall back to a substring match, so "Program Services (direct)" lands.
    for column, spellings in PART_IX_COLUMNS.items():
        if any(word in text for word in spellings):
            return column
    return None


def enforce_part_ix_columns(
    content: dict[str, Any], total_expenses: float
) -> tuple[dict[str, Any], list[str]]:
    """Rebuild the Part IX columns so they account for the total.

    Form 990 requires every expense to be allocated across three columns --
    program services, management and general, and fundraising -- and the
    three must sum to the total in column A. A return where they do not is
    not merely incomplete; it contradicts itself on the face of the form.

    The model's per-line classification is kept, because deciding whether an
    insurance premium is a program cost or an administrative one depends on
    what it insures and no ledger fact answers it. What is not left to the
    model is the arithmetic: the columns are summed from the lines, and
    whatever the lines do not account for is placed in management and general
    and recorded, so a preparer can see exactly what was assumed and move it.

    Found on real data, where 67,306 of expenses -- professional fees,
    marketing, website and insurance -- sat in the total and in no column,
    while every other check passed.
    """
    notes: list[str] = []
    totals = dict(content.get("partIX_totals") or {})

    columns = {name: 0.0 for name in PART_IX_COLUMNS}
    unclassified: list[str] = []

    for item in content.get("partIX_expenses") or []:
        if not isinstance(item, dict):
            continue
        amount = _amount(item.get("amount"))
        if not amount:
            continue
        column = _column_for(item.get("classification"))
        if column is None:
            columns[DEFAULT_COLUMN] += amount
            unclassified.append(
                f"{item.get('label') or item.get('line_number') or 'unnamed'} "
                f"{amount:,.2f}"
            )
        else:
            columns[column] += amount

    allocated = round(sum(columns.values()), 2)
    shortfall = round(total_expenses - allocated, 2)

    if shortfall > 0.005:
        columns[DEFAULT_COLUMN] = round(columns[DEFAULT_COLUMN] + shortfall, 2)
        notes.append(
            f"PART_IX_UNALLOCATED_TO_MANAGEMENT: {shortfall:,.2f} of expenses "
            f"appeared in the total but in no column, and has been placed in "
            f"management and general so the columns account for the total. A "
            f"preparer should reallocate what belongs elsewhere."
        )
    elif shortfall < -0.005:
        notes.append(
            f"PART_IX_OVER_ALLOCATED: the columns claim {allocated:,.2f} "
            f"against a total of {total_expenses:,.2f}, {abs(shortfall):,.2f} "
            f"more than was spent. Left as reported; the line items need "
            f"review before this return can be filed."
        )

    if unclassified:
        notes.append(
            f"PART_IX_UNCLASSIFIED_LINES: {len(unclassified)} expense line(s) "
            f"carried no column and were placed in management and general "
            f"\u2014 {'; '.join(unclassified[:6])}"
            + (" and others" if len(unclassified) > 6 else "")
        )

    previous = {name: totals.get(name) for name in PART_IX_COLUMNS}
    for name, value in columns.items():
        totals[name] = round(value, 2)
    content["partIX_totals"] = totals

    for name, was in previous.items():
        try:
            if was is not None and round(float(was), 2) != totals[name]:
                notes.append(f"PART_IX_COLUMN_CORRECTED: {name} {was} -> {totals[name]}")
        except (TypeError, ValueError):
            pass

    return content, notes


def enforce_deterministic_amounts(
    content: dict[str, Any],
    pl_report: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Apply every deterministic override available at this stage.

    Part VIII line items and total are rebuilt from the ledger. Part IX's
    total is set from the ledger as well, and its three columns are summed
    from the classified lines so that they account for it. The line-by-line
    inventory itself depends on a static IRS line list and is handled
    separately.
    """
    content, notes = enforce_part_viii_amounts(content, pl_report)

    totals = section_totals(pl_report)
    if totals:
        total_expenses = round(
            totals.get("expenses", 0.0)
            + totals.get("cogs", 0.0)
            + totals.get("other_expenses", 0.0),
            2,
        )
        part_ix_totals = dict(content.get("partIX_totals") or {})
        previous = part_ix_totals.get("totalExpenses")
        part_ix_totals["totalExpenses"] = total_expenses
        content["partIX_totals"] = part_ix_totals
        try:
            if previous is not None and round(float(previous), 2) != total_expenses:
                notes.append(
                    f"PART_IX_TOTAL_CORRECTED: {previous} -> {total_expenses}"
                )
        except (TypeError, ValueError):
            pass

        content, column_notes = enforce_part_ix_columns(content, total_expenses)
        notes.extend(column_notes)

    return content, notes

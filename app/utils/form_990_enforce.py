"""Give the deterministic engine authority over every reported amount.

The model classifies: it decides which IRS line an account belongs on, and it
writes the narrative. It does not decide what any number is. This module runs
after the section calls return and before normalisation, and it does four
things to Part VIII:

  * replaces each line item's amount with the figure from QuickBooks
  * drops line items naming accounts that do not exist
  * appends accounts the model omitted, classified by rule
  * moves every line item onto a Part VIII line that exists

In the first live run against the sandbox company the model reported six
revenue lines summing to 27,042.82 and stated a total of 10,210.77, while
QuickBooks reported 10,200.77. Three separate faults: a fabricated line
("Miscellaneous Income" 16,752.55, which is an expense account of 2,916.00),
an omission ("Discounts given" -89.50), and a stated total agreeing with
neither its own line items nor the ledger.

After this module runs, the line items are the accounts that exist, carrying
the amounts the ledger holds, on lines the IRS prints, and the total is their
sum.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from app.utils.form_990_lines import PART_VIII_LINES, part_viii_kind
from app.utils.form_990_mapping import classify_qb_income_account
from app.utils.form_990_totals import PLAccount, section_rows, section_totals

__all__ = [
    "enforce_part_viii_amounts",
    "enforce_deterministic_amounts",
    "assign_part_viii_lines",
    "part_viii_family_for_line",
    "part_viii_prompt_lines",
    "part_viii_prompt_categories",
    "normalise_account_label",
]

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


# --- Part VIII line numbers ---------------------------------------------
# The model chooses the line number and, until now, nothing checked it. A
# run produced "7a Other Revenue": line 7 is gross amount from sales of
# assets other than inventory, and other revenue is 11a-11d.
#
# The prompt causes it, the same way it caused Schedules S through AK. It
# names root lines -- 1, 2, 3, 5, 8, 9, 11 -- and then supplies a single
# example row numbered "1a". The model learns that sub-letters exist and is
# never told which ones do.
#
# The category is the part of the vocabulary the prompt actually teaches, so
# where the category and the line number disagree the category is believed
# and the line number is corrected to match it. No amount changes here.

_PART_VIII_LABEL = {line: label for line, _, label in PART_VIII_LINES}

# A line the model gave may be kept if it takes an amount at all. Totals,
# the noncash memo box, and the "less"/net rows of a netted family do not.
_KEEPABLE_KINDS = frozenset({"amount", "described", "gross"})

# Category as the model writes it, reduced to a key -> the family it names.
# Both prompt vocabularies are covered: the Part VIII section prompt offers
# seven categories, the full-form prompt eleven, and the four only the
# latter knows about -- bonds, rents, asset sales, inventory -- had no
# mapping anywhere before this.
_CATEGORY_FAMILY = {
    "contributions gifts grants": "contributions",
    "contributions gifts grants and other similar amounts": "contributions",
    "contributions": "contributions",
    "program service revenue": "program_service",
    "program services": "program_service",
    "investment income": "investment",
    "income from tax exempt bonds": "tax_exempt_bonds",
    "royalties": "royalties",
    "rental income": "rental",
    "gain loss on sale of assets": "asset_sales",
    "fundraising event revenue": "fundraising_events",
    "gaming revenue": "gaming",
    "sales of inventory": "inventory",
    "other revenue": "other",
    "miscellaneous revenue": "other",
}

# Line root -> family, for output carrying a number and no usable category.
_ROOT_FAMILY = {
    "1": "contributions",
    "2": "program_service",
    "3": "investment",
    "4": "tax_exempt_bonds",
    "5": "royalties",
    "6": "rental",
    "7": "asset_sales",
    "8": "fundraising_events",
    "9": "gaming",
    "10": "inventory",
    "11": "other",
}

# Family -> the category name the prompt teaches and the model echoes back.
# This is the single source: the prompt is rendered from it, and
# `_CATEGORY_FAMILY` above maps whatever comes back onto it.
_FAMILY_CATEGORY = {
    "contributions": "Contributions, Gifts, Grants",
    "program_service": "Program Service Revenue",
    "investment": "Investment Income",
    "tax_exempt_bonds": "Income from Tax-Exempt Bonds",
    "royalties": "Royalties",
    "rental": "Rental Income",
    "asset_sales": "Gain/Loss on Sale of Assets",
    "fundraising_events": "Fundraising Event Revenue",
    "gaming": "Gaming Revenue",
    "inventory": "Sales of Inventory",
    "other": "Other Revenue",
}

# Part VIII line root -> category label, for accounts classified by rule.
_LINE_CATEGORY = {
    root: _FAMILY_CATEGORY[family] for root, family in _ROOT_FAMILY.items()
}

# Where a family lands when the model's own number cannot be kept. Every
# value is a line that exists: 1f and 11d are the catch-alls the form
# provides, and 2a and 11a the first of the rows the filer describes.
_FAMILY_DEFAULT_LINE = {
    "contributions": "1f",
    "program_service": "2a",
    "investment": "3",
    "tax_exempt_bonds": "4",
    "royalties": "5",
    "rental": "6a",
    "asset_sales": "7a",
    "fundraising_events": "8a",
    "gaming": "9a",
    "inventory": "10a",
    "other": "11a",
}

# Families whose column (A) figure is a gross amount less its own direct
# expenses. A ledger income account carries the gross only, so the net
# cannot be computed from it. Saying so is better than passing the gross
# off as net revenue.
_NETTED_FAMILIES = frozenset(
    {"rental", "asset_sales", "fundraising_events", "gaming", "inventory"}
)


def _root_of(line_number: Any) -> str:
    """'11d' -> '11'. Empty when the value carries no leading digits.

    Distinct from `_line_number_root`, which falls back to "11" and so
    cannot tell "the model said line 11" from "the model said nothing".
    """
    match = re.match(r"\s*(\d+)", str(line_number or ""))
    return match.group(1) if match else ""


# --- matching a model label to a ledger account --------------------------
# The model abbreviates. Across an eighteen-run grid it wrote "Membership
# Dues" for the account "Annual Membership Dues" twelve times, and exact
# matching treated that exactly as it treats a hallucinated account: the line
# was dropped, and the model's classification went with it. The rule
# classifier then re-added the account under its own answer, which for dues
# is line 2 and wrong. Every dues error in that grid came from this path --
# twelve wrong where the rule decided, six right where the model's label
# happened to match. The model was never wrong about dues; we discarded it.
#
# So an abbreviation is resolved to the account it plainly names, and only a
# label naming nothing in the ledger is dropped. Two guards keep that from
# becoming guesswork: the match is on whole tokens, one label's words being a
# subset of the other's, and it must be unambiguous -- exactly one unclaimed
# account can satisfy it. A single shared word is not enough, so a model
# writing "Fees" against "Certification Fees" and "Trade Show Booth Fees"
# resolves to neither and is dropped, as before.


def _label_tokens(label: Any) -> frozenset[str]:
    return frozenset(normalise_account_label(label).split())


def _near_matches(
    label: Any, candidates: Iterable[PLAccount]
) -> list[PLAccount]:
    """Accounts whose name is an abbreviation of `label`, or it of them."""
    wanted = _label_tokens(label)
    if len(wanted) < 2:
        return []
    found = []
    for account in candidates:
        tokens = _label_tokens(account.name)
        if len(tokens) < 2:
            continue
        if wanted <= tokens or tokens <= wanted:
            found.append(account)
    return found


def _normalise_category(category: Any) -> str:
    """Reduce a category to a comparable key, as labels are reduced."""
    text = str(category or "").strip().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _family_for(item: dict[str, Any]) -> tuple[str, str]:
    """Which Part VIII family a line item belongs to, and on what evidence."""
    family = _CATEGORY_FAMILY.get(_normalise_category(item.get("category")))
    if family:
        return family, "category"

    root = _root_of(item.get("lineNumber"))
    if root in _ROOT_FAMILY:
        return _ROOT_FAMILY[root], "line number"

    _, hint = classify_qb_income_account(str(item.get("label") or ""))
    return _ROOT_FAMILY.get(hint, "other"), "account name"


def assign_part_viii_lines(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Put every revenue line on a Part VIII line that exists.

    The model's number is kept when it takes an amount and belongs to the
    family the category names. Otherwise the family's default line is used.
    Several accounts sharing one line is expected and left alone: this
    records which line an account belongs on, and the aggregation into the
    form's five described rows is a rendering step we do not perform.

    Supplying a missing sub-letter -- "11" to "11a" -- is not reported; it
    is the form's numbering, not a correction. A change of family is.
    """
    notes: list[str] = []
    netted: dict[str, list[str]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        stated = str(item.get("lineNumber") or "").strip()
        family, basis = _family_for(item)
        stated_root = _root_of(stated)
        same_family = _ROOT_FAMILY.get(stated_root) == family

        if same_family and part_viii_kind(stated) in _KEEPABLE_KINDS:
            line = stated
        else:
            line = _FAMILY_DEFAULT_LINE[family]

        if line != stated and stated and not (stated == stated_root and same_family):
            was = _PART_VIII_LABEL.get(stated)
            notes.append(
                f"PART_VIII_LINE_CORRECTED: '{item.get('label')}' was on line "
                f"{stated}" + (f" ({was})" if was else ", which is not a Part VIII line")
                + f"; moved to {line} ({_PART_VIII_LABEL[line]}) on the {basis}"
            )

        item["lineNumber"] = line
        # Column (B) follows the line, so it has to be re-derived after a move.
        item["programServiceRevenue"] = (
            _amount(item.get("totalRevenue"))
            if _line_number_root(line) in _PROGRAM_SERVICE_LINES
            else 0.0
        )

        if family in _NETTED_FAMILIES:
            netted.setdefault(line, []).append(
                f"'{item.get('label')}' {_amount(item.get('totalRevenue')):,.2f}"
            )

    for line, accounts in netted.items():
        notes.append(
            f"PART_VIII_GROSS_ON_NET_LINE: line {line} "
            f"({_PART_VIII_LABEL[line]}) reaches column (A) only after its "
            f"direct expenses are subtracted, and the ledger supplies the "
            f"gross alone \u2014 {'; '.join(accounts)}. The expense and net "
            f"lines are undetermined and the amount is carried gross."
        )

    return items, notes


# --- Rendering the inventory into the prompt -----------------------------
# The prompt has to teach exactly the vocabulary `assign_part_viii_lines`
# accepts. Written out by hand in two files, the two drift, and the drift is
# invisible until a return comes back on a line that does not exist -- which
# is how "7a Other Revenue" happened in the first place. Generating the
# prompt text from the same tables that validate it is what stops that, so
# these live here beside the validator rather than in the prompt module.


def _and_join(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _described_span(lines: list[str]) -> str:
    return lines[0] if len(lines) == 1 else f"{lines[0]}-{lines[-1]}"


def _part_viii_groups() -> list[tuple[str, list[tuple[str, str, str]]]]:
    """The assignable Part VIII lines, grouped by family in the form's order."""
    groups: dict[str, list[tuple[str, str, str]]] = {}
    order: list[str] = []
    for line, kind, label in PART_VIII_LINES:
        if kind not in _KEEPABLE_KINDS:
            continue
        family = _ROOT_FAMILY.get(_root_of(line))
        if family is None:
            continue
        if family not in groups:
            groups[family] = []
            order.append(family)
        groups[family].append((line, kind, label))
    return [(family, groups[family]) for family in order]


def part_viii_family_for_line(line_number: Any) -> str | None:
    """The Part VIII family a line number belongs to, or None if it has none.

    Public because the classification harness scores against families and must
    use the same mapping the enforcement pass does, not a second copy of it.
    """
    return _ROOT_FAMILY.get(_root_of(line_number))


def part_viii_prompt_categories() -> str:
    """The category vocabulary, pipe-separated, for the output schema."""
    return " | ".join(_FAMILY_CATEGORY[family] for family, _ in _part_viii_groups())


def part_viii_prompt_lines() -> str:
    """The assignable Part VIII lines, rendered as prompt text."""
    blocks: list[str] = []
    for family, entries in _part_viii_groups():
        # On the form the filer-described rows come first in every family
        # that has them -- 2a-2e before 2f, 11a-11c before 11d -- so they
        # are rendered first, as a span.
        described = [(line, label) for line, kind, label in entries if kind == "described"]
        plain = [(line, label) for line, kind, label in entries if kind != "described"]

        rows: list[str] = []
        if described:
            span = _described_span([line for line, _ in described])
            rows.append(
                f"  {span:<8}{described[0][1]} \u2014 you supply the "
                f"description and business code"
            )
        rows.extend(f"  {line:<8}{label}" for line, label in plain)
        blocks.append(f"{_FAMILY_CATEGORY[family]}\n" + "\n".join(rows))

    netted = _and_join([
        _FAMILY_DEFAULT_LINE[family]
        for family, _ in _part_viii_groups()
        if family in _NETTED_FAMILIES
    ])
    totals = _and_join([line for line, kind, _ in PART_VIII_LINES if kind == "total"])

    return (
        "**PART VIII LINE NUMBERS**\n\n"
        "Use only the line numbers listed here. They are the boxes printed on "
        "Form 990 Part VIII; a number that does not appear below does not "
        "exist. The category and the line number must agree \u2014 a line item "
        "categorised Other Revenue belongs on 11a-11d, never on line 7, which "
        "is sales of assets other than inventory.\n\n"
        + "\n\n".join(blocks)
        + f"\n\nLines {netted} report a gross figure that the form reduces by "
        f"its own direct expenses further down. Report the gross; do not net "
        f"anything yourself.\n\n"
        f"Lines {totals} are totals computed from the line items. Do not "
        f"report them as line items."
    )


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

    # Exact matches are resolved first and claim their account, so a model
    # line abbreviating one account can never take an account that another
    # line names outright.
    model_items = [i for i in (content.get("partVIII_revenue") or []) if isinstance(i, dict)]
    resolved: dict[int, PLAccount] = {}
    for position, item in enumerate(model_items):
        account = index.get(normalise_account_label(item.get("label")))
        if account is not None:
            resolved[position] = account

    spoken_for = {id(a) for a in resolved.values()}
    for position, item in enumerate(model_items):
        if position in resolved:
            continue
        candidates = _near_matches(
            item.get("label"), (a for a in accounts if id(a) not in spoken_for)
        )
        if len(candidates) == 1:
            resolved[position] = candidates[0]
            spoken_for.add(id(candidates[0]))
            notes.append(
                f"PART_VIII_LABEL_MATCHED: the model wrote "
                f"'{item.get('label')}'; the ledger account is "
                f"'{candidates[0].name}', and its classification is kept"
            )
        elif len(candidates) > 1:
            notes.append(
                f"PART_VIII_LABEL_AMBIGUOUS: '{item.get('label')}' could be "
                f"{' or '.join(repr(c.name) for c in candidates)}; left to the "
                f"classification rules rather than guessed"
            )

    for position, item in enumerate(model_items):
        label = item.get("label")
        account = resolved.get(position)

        if account is None:
            notes.append(
                f"PART_VIII_DROPPED: '{label}' does not exist in the QuickBooks "
                f"Income accounts (model reported {item.get('totalRevenue')} on "
                f"line {item.get('lineNumber') or '(none)'}, "
                f"{item.get('category') or 'uncategorised'})"
            )
            continue

        key = normalise_account_label(account.name)

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
            f"from the model output; {reason}"
        )

    enforced, line_notes = assign_part_viii_lines(enforced)
    notes.extend(line_notes)

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

def _row_name(item: dict[str, Any]) -> str:
    """Whatever identifies an expense row, under either field spelling."""
    return str(
        item.get("label")
        or item.get("lineNumber")
        or item.get("line_number")
        or "unnamed"
    )


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

    The model answers in one of two shapes, because the prompt asks for
    both: `amount` with a `classification` naming a column, or
    `totalExpenses` with the three column figures given directly. Both are
    read. Reading only the first cost one run its entire program services
    column -- 138,000 the model had classified correctly, discarded here,
    and the full 273,306 forced into management and general -- while every
    other check passed and the two runs differed only in which shape the
    model happened to choose.

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

        # A row carrying its own column figures has said more than any
        # classification string could, so it is taken as it stands. All
        # three at zero says nothing, and falls through to the text.
        explicit = {
            "totalProgramServices": _amount(item.get("programServices")),
            "totalManagementAndGeneral": _amount(item.get("managementAndGeneral")),
            "totalFundraising": _amount(item.get("fundraising")),
        }
        if any(explicit.values()):
            for name, value in explicit.items():
                columns[name] += value
            continue

        amount = _amount(item.get("totalExpenses")) or _amount(item.get("amount"))
        if not amount:
            continue

        column = _column_for(item.get("classification"))
        if column is None:
            columns[DEFAULT_COLUMN] += amount
            unclassified.append(f"{_row_name(item)} {amount:,.2f}")
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
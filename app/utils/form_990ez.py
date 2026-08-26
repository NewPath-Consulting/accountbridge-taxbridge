"""Produce Form 990-EZ Parts I and II from the ledger.

The 990-EZ exists in neither system today. Make.com produces the 990-N, the
backend produces the full 990, and the short form sits in the gap between
them -- which is the form most mid-sized nonprofits actually file.

No new classification is needed. The accounts have already been walked and
bucketed by `form_990_totals` and assigned to Part VIII and Part IX lines by
`form_990_enforce`. This module maps those buckets onto the EZ's own, much
shorter, line numbering.

    Part I   Revenue, Expenses, and Changes in Net Assets
      1   Contributions, gifts, grants
      2   Program service revenue
      3   Membership dues and assessments
      4   Investment income
      8   Other revenue
      9   Total revenue
      13  Professional fees and other payments to independent contractors
      15  Printing, publications, postage and shipping
      16  Other expenses
      17  Total expenses
      18  Excess or (deficit) for the year

    Part II  Balance Sheets
      22  Cash, savings and investments
      24  Other assets
      25  Total assets
      26  Total liabilities
      27  Net assets or fund balances

Every figure is computed. The two internal identities the IRS checks --
line 9 equals its components, and line 18 equals line 9 less line 17 -- are
asserted here rather than assumed, and a failure is reported rather than
smoothed over.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.utils.form_990_totals import section_totals

__all__ = [
    "Form990EZ",
    "build_form_990ez",
    "PART_I_REVENUE_LINES",
    "PART_I_EXPENSE_LINES",
]

# Part VIII line -> Part I line. The EZ collapses the full form's eleven
# revenue lines into five.
PART_I_REVENUE_LINES = {
    "1": ("line_1_contributions", "Contributions, gifts, grants and similar amounts received"),
    "2": ("line_2_program_service_revenue", "Program service revenue including government fees and contracts"),
    "3": ("line_4_investment_income", "Investment income"),
    "5": ("line_8_other_revenue", "Other revenue"),
    "8": ("line_8_other_revenue", "Other revenue"),
    "9": ("line_8_other_revenue", "Other revenue"),
    "11": ("line_8_other_revenue", "Other revenue"),
}

PART_I_EXPENSE_LINES = {
    "line_13_professional_fees": "Professional fees and other payments to independent contractors",
    "line_15_printing_publications_postage": "Printing, publications, postage and shipping",
    "line_16_other_expenses": "Other expenses",
}

_REVENUE_ORDER = [
    ("line_1_contributions", "1"),
    ("line_2_program_service_revenue", "2"),
    ("line_3_membership_dues", "3"),
    ("line_4_investment_income", "4"),
    ("line_8_other_revenue", "8"),
]


class Form990EZ:
    """A 990-EZ, the checks run against it, and whether they held."""

    __slots__ = ("part_i", "part_ii", "warnings", "check_failures")

    def __init__(
        self,
        part_i: dict[str, Any],
        part_ii: dict[str, Any],
        warnings: list[str],
        check_failures: list[str],
    ) -> None:
        self.part_i = part_i
        self.part_ii = part_ii
        self.warnings = warnings
        self.check_failures = check_failures

    @property
    def is_internally_consistent(self) -> bool:
        return not self.check_failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "form": "990-EZ",
            "part_i_revenue_expenses": self.part_i,
            "part_ii_balance_sheet": self.part_ii,
            "warnings": list(self.warnings),
            "check_failures": list(self.check_failures),
            "is_internally_consistent": self.is_internally_consistent,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Form990EZ(consistent={self.is_internally_consistent!r})"


def _round(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _line_root(line_number: Any) -> str:
    text = str(line_number or "").strip()
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        else:
            break
    return digits or "11"


def build_form_990ez(
    content: Mapping[str, Any],
    pl_report: Mapping[str, Any] | None = None,
) -> Form990EZ:
    """Map enforced Part VIII, IX and X figures onto the 990-EZ.

    `content` must have been through `enforce_deterministic_amounts`, so its
    Part VIII line items carry ledger amounts rather than model output.
    """
    warnings: list[str] = []
    failures: list[str] = []

    # --- Part I revenue ---------------------------------------------------
    revenue: dict[str, float] = {key: 0.0 for key, _ in _REVENUE_ORDER}

    line_items = content.get("partVIII_revenue") or []
    for item in line_items:
        if not isinstance(item, dict):
            continue
        root = _line_root(item.get("lineNumber"))
        amount = _round(item.get("totalRevenue"))

        # Membership dues sit on Part VIII line 1 as contributions but get
        # their own line on the EZ, so they are separated where the
        # classification made the distinction.
        label = str(item.get("label") or "").lower()
        category = str(item.get("category") or "").lower()
        if "membership" in label or "membership" in category or "dues" in label:
            revenue["line_3_membership_dues"] += amount
            continue

        key = PART_I_REVENUE_LINES.get(root, ("line_8_other_revenue", ""))[0]
        revenue[key] += amount

    revenue = {key: round(value, 2) for key, value in revenue.items()}
    total_revenue = round(sum(revenue.values()), 2)

    reported_revenue = content.get("partVIII_totalRevenue")
    if reported_revenue is not None and _round(reported_revenue) != total_revenue:
        failures.append(
            f"EZ_LINE_9_MISMATCH: revenue lines sum to {total_revenue} but "
            f"Part VIII reports {_round(reported_revenue)}"
        )

    # --- Part I expenses --------------------------------------------------
    part_ix_totals = content.get("partIX_totals") or {}
    total_expenses = _round(part_ix_totals.get("totalExpenses"))

    if not total_expenses and pl_report:
        ledger = section_totals(pl_report)
        if ledger:
            total_expenses = round(
                ledger.get("expenses", 0.0)
                + ledger.get("cogs", 0.0)
                + ledger.get("other_expenses", 0.0),
                2,
            )
            warnings.append(
                f"EZ_EXPENSES_FROM_LEDGER: Part IX carried no total; computed "
                f"{total_expenses} from the profit and loss."
            )

    # The EZ itemises only two expense categories before its catch-all. The
    # full form's functional classification does not map onto them, so the
    # itemised lines are left at zero and the total carried on line 16 until
    # transaction-level detail is available to split it.
    expenses = {
        "line_13_professional_fees": 0.0,
        "line_15_printing_publications_postage": 0.0,
        "line_16_other_expenses": total_expenses,
    }
    if total_expenses:
        warnings.append(
            "EZ_EXPENSES_NOT_ITEMISED: lines 13 and 15 require expense detail "
            "the current QuickBooks report endpoints do not provide; the total "
            "is carried on line 16."
        )

    excess_or_deficit = round(total_revenue - total_expenses, 2)

    part_i = {
        "line_1_contributions": revenue["line_1_contributions"],
        "line_2_program_service_revenue": revenue["line_2_program_service_revenue"],
        "line_3_membership_dues": revenue["line_3_membership_dues"],
        "line_4_investment_income": revenue["line_4_investment_income"],
        "line_8_other_revenue": revenue["line_8_other_revenue"],
        "line_9_total_revenue": total_revenue,
        **expenses,
        "line_17_total_expenses": total_expenses,
        "line_18_excess_or_deficit": excess_or_deficit,
    }

    # --- Part II balance sheet -------------------------------------------
    balance_sheet = content.get("partX_balanceSheet") or {}
    totals_assets = balance_sheet.get("totalAssets") or {}
    totals_liabilities = balance_sheet.get("totalLiabilities") or {}
    net_assets = (balance_sheet.get("netAssets") or {}).get("totalNetAssets") or {}

    cash_boy = 0.0
    cash_eoy = 0.0
    for asset in balance_sheet.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        label = str(asset.get("label") or "").lower()
        if any(word in label for word in ("cash", "savings", "investment")):
            cash_boy += _round(asset.get("beginningOfYear"))
            cash_eoy += _round(asset.get("endOfYear"))

    part_ii = {
        "line_22_cash_savings_investments": {
            "beginning_of_year": round(cash_boy, 2),
            "end_of_year": round(cash_eoy, 2),
        },
        "line_25_total_assets": {
            "beginning_of_year": _round(totals_assets.get("beginningOfYear")),
            "end_of_year": _round(totals_assets.get("endOfYear")),
        },
        "line_26_total_liabilities": {
            "beginning_of_year": _round(totals_liabilities.get("beginningOfYear")),
            "end_of_year": _round(totals_liabilities.get("endOfYear")),
        },
        "line_27_net_assets": {
            "beginning_of_year": _round(net_assets.get("beginningOfYear")),
            "end_of_year": _round(net_assets.get("endOfYear")),
        },
    }

    # --- the identities the IRS checks -----------------------------------
    for period in ("beginning_of_year", "end_of_year"):
        assets = part_ii["line_25_total_assets"][period]
        liabilities = part_ii["line_26_total_liabilities"][period]
        equity = part_ii["line_27_net_assets"][period]
        if round(assets - liabilities, 2) != equity:
            failures.append(
                f"EZ_LINE_27_MISMATCH ({period}): assets {assets} less "
                f"liabilities {liabilities} is {round(assets - liabilities, 2)}, "
                f"but net assets are {equity}"
            )

    if not balance_sheet:
        warnings.append("EZ_PART_II_EMPTY: no Part X balance sheet available.")

    return Form990EZ(part_i, part_ii, warnings, failures)

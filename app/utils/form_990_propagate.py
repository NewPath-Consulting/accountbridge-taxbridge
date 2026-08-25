"""Propagate enforced figures into the summary blocks that mirror them.

The Form 990 repeats the same numbers in several places: Part VIII carries
the revenue detail, Part I line 12 restates the total, and the benchmark
`organization_summary` and `totals` blocks restate it again. Only Part VIII
is rebuilt by `form_990_enforce`, so without this the corrected figure sits
alongside three stale copies of the model's original.

That is not cosmetic. `organization_summary.gross_receipts` is what a form
routing decision reads, so a stale value there means filing the wrong form.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.utils.gross_receipts import gross_receipts_from_pl

__all__ = ["propagate_enforced_totals"]


def _round(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _set_current_year(block: dict[str, Any], key: str, value: float) -> Any:
    """Set a Part I revenueExpenseSummary entry, preserving priorYear."""
    entry = block.get(key)
    previous = None
    if isinstance(entry, dict):
        previous = entry.get("currentYear")
        entry["currentYear"] = value
    else:
        previous = entry
        block[key] = {"priorYear": None, "currentYear": value}
    return previous


def propagate_enforced_totals(
    content: dict[str, Any],
    pl_report: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Push enforced Part VIII and Part IX figures into the summary blocks.

    Also replaces `organization_summary.gross_receipts` with the IRS-defined
    figure computed from the ledger, rather than total revenue.
    """
    notes: list[str] = []

    revenue = content.get("partVIII_totalRevenue")
    expenses = (content.get("partIX_totals") or {}).get("totalExpenses")

    # --- Part I summary --------------------------------------------------
    part_i = content.get("partI_summary")
    if isinstance(part_i, dict):
        summary = part_i.get("revenueExpenseSummary")
        if isinstance(summary, dict):
            if revenue is not None:
                previous = _set_current_year(
                    summary, "line12_totalRevenue", _round(revenue)
                )
                if previous is not None and _round(previous) != _round(revenue):
                    notes.append(
                        f"PART_I_LINE12_CORRECTED: {previous} -> {_round(revenue)}"
                    )
            if expenses is not None:
                previous = _set_current_year(
                    summary, "line18_totalExpenses", _round(expenses)
                )
                if previous is not None and _round(previous) != _round(expenses):
                    notes.append(
                        f"PART_I_LINE18_CORRECTED: {previous} -> {_round(expenses)}"
                    )
            if revenue is not None and expenses is not None:
                net = _round(_round(revenue) - _round(expenses))
                previous = _set_current_year(
                    summary, "line19_revenueLessExpenses", net
                )
                if previous is not None and _round(previous) != net:
                    notes.append(
                        f"PART_I_LINE19_CORRECTED: {previous} -> {net}"
                    )

    # --- benchmark totals block -----------------------------------------
    totals = content.get("totals")
    if isinstance(totals, dict):
        if revenue is not None and _round(totals.get("total_revenue")) != _round(revenue):
            notes.append(
                f"TOTALS_REVENUE_CORRECTED: {totals.get('total_revenue')} -> {_round(revenue)}"
            )
            totals["total_revenue"] = _round(revenue)
        if expenses is not None and _round(totals.get("total_expenses")) != _round(expenses):
            notes.append(
                f"TOTALS_EXPENSES_CORRECTED: {totals.get('total_expenses')} -> {_round(expenses)}"
            )
            totals["total_expenses"] = _round(expenses)

    # --- gross receipts, to the IRS definition ---------------------------
    computed = gross_receipts_from_pl(pl_report)
    if computed is not None:
        org = content.get("organization_summary")
        if not isinstance(org, dict):
            org = {}
            content["organization_summary"] = org
        previous = org.get("gross_receipts")
        org["gross_receipts"] = computed.total
        org["gross_receipts_basis"] = computed.as_dict()
        if previous is None or _round(previous) != computed.total:
            notes.append(
                f"GROSS_RECEIPTS_CORRECTED: {previous} -> {computed.total} "
                f"(revenue {computed.revenue} + COGS {computed.cost_of_goods_sold}; "
                f"IRS gross receipts is before subtracting costs)"
            )

    return content, notes

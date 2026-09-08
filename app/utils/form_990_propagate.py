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


def _year_value(node: Any, key: str) -> float | None:
    """Read `beginningOfYear` / `endOfYear` from a Part X figure."""
    if isinstance(node, dict):
        if key in node:
            return _round(node[key])
        return None
    if node is None:
        return None
    return _round(node)


def _part_x_net_assets(content: dict[str, Any]) -> dict[str, float]:
    """Assets, liabilities and net assets from the enforced Part X.

    Net assets are derived as assets less liabilities, the same identity
    `balance_sheet_totals` enforces inside Part X. Nothing here is read from
    the model.
    """
    part_x = content.get("partX_balanceSheet")
    if not isinstance(part_x, dict):
        return {}

    out: dict[str, float] = {}
    for name, key in (
        ("assets_boy", "beginningOfYear"),
        ("assets_eoy", "endOfYear"),
    ):
        value = _year_value(part_x.get("totalAssets"), key)
        if value is not None:
            out[name] = value
    for name, key in (
        ("liabilities_boy", "beginningOfYear"),
        ("liabilities_eoy", "endOfYear"),
    ):
        value = _year_value(part_x.get("totalLiabilities"), key)
        if value is not None:
            out[name] = value

    for period in ("boy", "eoy"):
        if f"assets_{period}" in out and f"liabilities_{period}" in out:
            out[f"net_{period}"] = _round(
                out[f"assets_{period}"] - out[f"liabilities_{period}"]
            )
    return out


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

    # --- balance sheet figures, from the enforced Part X ------------------
    #
    # Part X computes net assets as assets less liabilities and never reads
    # the model's. `totals` restated the model's figure anyway: on a 2024 run
    # Part X reported 192,028 -- matching the filed return -- while
    # totals.net_assets still said 217,675. The payload contradicted itself,
    # and totals is the block a reader reaches for first.
    balance = _part_x_net_assets(content)
    if isinstance(totals, dict) and balance:
        for key, name in (
            ("total_assets", "assets_eoy"),
            ("total_liabilities", "liabilities_eoy"),
            ("net_assets", "net_eoy"),
            ("ending_net_assets", "net_eoy"),
            ("beginning_net_assets", "net_boy"),
        ):
            if name not in balance:
                continue
            if _round(totals.get(key)) != balance[name] or totals.get(key) is None:
                if totals.get(key) is not None and _round(totals.get(key)) != balance[name]:
                    notes.append(
                        f"TOTALS_{key.upper()}_CORRECTED: "
                        f"{totals.get(key)} -> {balance[name]}"
                    )
                totals[key] = balance[name]
        if "net_eoy" in balance and "net_boy" in balance:
            change = _round(balance["net_eoy"] - balance["net_boy"])
            if totals.get("change_in_net_assets") is not None and _round(
                totals.get("change_in_net_assets")
            ) != change:
                notes.append(
                    f"TOTALS_CHANGE_IN_NET_ASSETS_CORRECTED: "
                    f"{totals.get('change_in_net_assets')} -> {change}"
                )
            totals["change_in_net_assets"] = change

    # --- Part XI, which is a reconciliation and must actually reconcile ---
    #
    # Line 10 is line 4 plus lines 3 and 5 through 9. It is a sum, so it is
    # computed here rather than taken from the model, which reported 217,675
    # against a line 4 of 159,828 and a line 3 of 32,200 -- out by 25,647 on
    # the one part of the form whose purpose is to prove the balance sheet
    # ties to the income statement.
    part_xi = content.get("partXI_reconciliationOfNetAssets")
    if isinstance(part_xi, dict):
        if revenue is not None:
            part_xi["line1_totalRevenue"] = _round(revenue)
        if expenses is not None:
            part_xi["line2_totalExpenses"] = _round(expenses)
        if revenue is not None and expenses is not None:
            part_xi["line3_revenueLessExpenses"] = _round(
                _round(revenue) - _round(expenses)
            )
        if "net_boy" in balance:
            part_xi["line4_netAssetsBeginningOfYear"] = balance["net_boy"]

        addends = [
            part_xi.get("line4_netAssetsBeginningOfYear"),
            part_xi.get("line3_revenueLessExpenses"),
            part_xi.get("line5_netUnrealizedGainsLosses"),
            part_xi.get("line6_donatedServicesAndUseOfFacilities"),
            part_xi.get("line7_investmentExpenses"),
            part_xi.get("line8_priorPeriodAdjustments"),
            part_xi.get("line9_otherChanges"),
        ]
        if any(value is not None for value in addends):
            computed_end = _round(sum(_round(value) for value in addends))
            previous = part_xi.get("line10_netAssetsEndOfYear")
            if previous is not None and _round(previous) != computed_end:
                notes.append(
                    f"PART_XI_LINE10_CORRECTED: {previous} -> {computed_end}"
                )
            part_xi["line10_netAssetsEndOfYear"] = computed_end

            # Part XI and Part X must agree on the same figure. If they do
            # not, one of the inputs is wrong and the return should say so
            # rather than quietly present two numbers.
            if "net_eoy" in balance and computed_end != balance["net_eoy"]:
                notes.append(
                    f"PART_XI_PART_X_DISAGREE: Part XI line 10 {computed_end} "
                    f"vs Part X net assets {balance['net_eoy']}"
                )

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

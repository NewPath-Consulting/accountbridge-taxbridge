"""Gross receipts to the IRS definition, computed from the ledger.

Gross receipts decides which form an organization files, so it has to be
right and it has to be computed rather than generated.

The figure is *not* total revenue. Part VIII line 12 is revenue net of
several costs, and the instructions for the filing thresholds are explicit
that gross receipts is the total the organization received from all sources
during its annual accounting period, **without subtracting any costs or
expenses**. The gap matters: an organization at 49,800 of revenue with
1,000 of cost of goods sold has gross receipts of 50,800 and cannot file a
990-N, even though its revenue is under the threshold.

Concretely, gross receipts adds back:

  * cost of goods sold, netted against sales in Part VIII line 10
  * the cost basis of assets sold, netted in line 7
  * direct expenses of fundraising events and gaming, netted in lines 8 and 9

This module computes the figure from the QuickBooks profit and loss, where
those costs appear as their own sections rather than being netted away, and
provides the three-year rolling average the "normally" test requires.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.utils.form_990_totals import section_totals

__all__ = [
    "GrossReceipts",
    "gross_receipts_from_pl",
    "rolling_average_gross_receipts",
    "normally_gross_receipts",
    "AgeTier",
    "NEW_ORG_LIMIT",
    "YOUNG_ORG_LIMIT",
    "ESTABLISHED_ORG_LIMIT",
    "age_tier_for",
    "threshold_990n_for_age",
]

# The 990-N eligibility threshold is not a single number. The IRS applies a
# higher limit and a shorter look-back to newer organizations, on the basis
# that startup-year revenue can spike without meaning the organization has
# outgrown the e-Postcard.
#
#   1 year or less   received or pledged $75,000 or less in the first tax year
#   1 to 3 years     averaged $60,000 or less across the first two tax years
#   3 years or more  averaged $50,000 or less across the preceding 3 tax
#                    years, including the year being calculated
NEW_ORG_LIMIT = 75_000.0
YOUNG_ORG_LIMIT = 60_000.0
ESTABLISHED_ORG_LIMIT = 50_000.0


class AgeTier:
    NEW = "new_1yr_or_less"
    YOUNG = "young_1_to_3yr"
    ESTABLISHED = "established_3yr_or_more"
    UNKNOWN = "age_unknown"


def age_tier_for(age_years: float | None) -> str:
    """Classify an organization by age for the 990-N eligibility test."""
    if age_years is None:
        return AgeTier.UNKNOWN
    if age_years <= 1:
        return AgeTier.NEW
    if age_years < 3:
        return AgeTier.YOUNG
    return AgeTier.ESTABLISHED


def threshold_990n_for_age(age_years: float | None) -> tuple[float, str]:
    """Return the 990-N gross receipts limit and the tier it came from.

    When age is unknown the strictest limit applies. That is the safe
    direction -- it can only route an organization to a longer form than
    required, never to one it is ineligible for -- but callers should
    surface it, because the decision rests on an assumption.
    """
    tier = age_tier_for(age_years)
    if tier == AgeTier.NEW:
        return NEW_ORG_LIMIT, tier
    if tier == AgeTier.YOUNG:
        return YOUNG_ORG_LIMIT, tier
    return ESTABLISHED_ORG_LIMIT, tier


class GrossReceipts:
    """Gross receipts with the components that produced it."""

    __slots__ = ("total", "revenue", "cost_of_goods_sold", "other_costs_added_back")

    def __init__(
        self,
        total: float,
        revenue: float,
        cost_of_goods_sold: float = 0.0,
        other_costs_added_back: float = 0.0,
    ) -> None:
        self.total = total
        self.revenue = revenue
        self.cost_of_goods_sold = cost_of_goods_sold
        self.other_costs_added_back = other_costs_added_back

    def as_dict(self) -> dict[str, float]:
        return {
            "gross_receipts": self.total,
            "total_revenue": self.revenue,
            "cost_of_goods_sold_added_back": self.cost_of_goods_sold,
            "other_costs_added_back": self.other_costs_added_back,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"GrossReceipts(total={self.total!r}, revenue={self.revenue!r})"


def _round(value: float) -> float:
    return round(float(value or 0.0), 2)


def gross_receipts_from_pl(
    pl_report: Mapping[str, Any] | None,
    *,
    other_costs_added_back: float = 0.0,
) -> GrossReceipts | None:
    """Compute gross receipts for one period from a QuickBooks P&L.

    Returns None when the report carries no sections at all, so callers can
    tell "no data" apart from "genuinely zero".
    """
    totals = section_totals(pl_report or {})
    if not totals:
        return None

    revenue = _round(totals.get("income", 0.0))
    cogs = _round(totals.get("cogs", 0.0))
    other = _round(other_costs_added_back)

    return GrossReceipts(
        total=_round(revenue + cogs + other),
        revenue=revenue,
        cost_of_goods_sold=cogs,
        other_costs_added_back=other,
    )


def rolling_average_gross_receipts(values: Iterable[float | None]) -> float | None:
    """Average the gross receipts supplied, ignoring years with no data.

    The IRS "normally" test looks at the organization's recent history rather
    than a single year, so a one-off spike does not by itself change which
    form is filed. Returns None when nothing usable was supplied.
    """
    usable = [float(v) for v in values if v is not None]
    if not usable:
        return None
    return _round(sum(usable) / len(usable))


def normally_gross_receipts(
    current: float | None,
    prior_years: Iterable[float | None] = (),
    age_years: float | None = None,
) -> tuple[float | None, str]:
    """Return the figure to test against the thresholds, and how it was derived.

    With three years available the rolling average is used. With fewer, the
    current year stands on its own -- and the caller is told so, because a
    threshold decision made on one year of data is weaker evidence and may
    warrant review.
    """
    priors = [float(v) for v in prior_years if v is not None]

    if current is None and not priors:
        return None, "no_data"

    tier = age_tier_for(age_years)

    # A first-year organization is tested on that year alone. Averaging in
    # prior years would be wrong -- there are none to average.
    if tier == AgeTier.NEW and current is not None:
        return _round(current), "first_year_only"

    # Between one and three years the test looks at the first two tax years,
    # so at most one prior year joins the current one.
    if tier == AgeTier.YOUNG and current is not None:
        if priors:
            return rolling_average_gross_receipts([current, priors[0]]), "average_first_2yr"
        return _round(current), "first_year_only"

    if len(priors) >= 2 and current is not None:
        window = [current, *priors][:3]
        return rolling_average_gross_receipts(window), "rolling_average_3yr"

    if current is None:
        return rolling_average_gross_receipts(priors), "prior_years_only"

    if priors:
        window = [current, *priors]
        return rolling_average_gross_receipts(window), (
            f"rolling_average_{len(window)}yr_partial"
        )

    return _round(current), "current_year_only"

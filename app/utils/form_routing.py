"""Decide which return in the 990 series an organization files.

This is the single most consequential decision the system makes. Filing the
wrong variant is a compliance failure, not a formatting one, so the decision
is made here in code from validated figures -- never by the model.

The IRS thresholds:

    Form 990-N    gross receipts *normally* at or below the age-based limit
    Form 990-EZ   gross receipts < $200,000 *for the tax year*
                  AND total assets < $500,000 at year end
    Form 990      otherwise

Only the 990-N threshold carries the "normally" language, and only it is
tested against a multi-year average. The 990-EZ test is made on the tax
year alone. Averaging it sends organizations to the full 990 that qualify
for the short form: measured against real filings, an organization with
42,347 of receipts and two large prior years was routed to the 990 when it
filed -- correctly -- a 990-EZ.

The 990-N limit is not a fixed $50,000. The IRS sets it by the age of the
organization -- $75,000 for a first-year filer, $60,000 between one and three
years, $50,000 once established -- with a correspondingly shorter look-back.
Applying $50,000 to a one-year-old organization with $70,000 of receipts
would route it to the 990-EZ when it is eligible for the e-Postcard.

Two details that are easy to get wrong and expensive to get wrong:

  * The 990-EZ test is a conjunction. An organization with $60,000 of gross
    receipts and $800,000 of assets files the full 990, not the EZ. The
    demo intake form asks only about revenue and would route it wrongly.

  * "Normally" is a multi-year test, not a single year. A one-off bequest
    does not by itself move an organization off the 990-N.

Anything close to a boundary is not routed automatically. The specification
requires human review within 5% of a threshold, because a late journal entry
or a reclassified account can move an organization across it after the fact.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.utils.gross_receipts import (
    AgeTier,
    normally_gross_receipts,
    threshold_990n_for_age,
)

__all__ = [
    "FORM_990N",
    "FORM_990EZ",
    "FORM_990",
    "GROSS_RECEIPTS_990N_LIMIT",
    "AgeTier",
    "GROSS_RECEIPTS_990EZ_LIMIT",
    "TOTAL_ASSETS_990EZ_LIMIT",
    "REVIEW_BAND",
    "FormRouting",
    "route_form_variant",
]

FORM_990N = "990-N"
FORM_990EZ = "990-EZ"
FORM_990 = "990"

GROSS_RECEIPTS_990N_LIMIT = 50_000.0
GROSS_RECEIPTS_990EZ_LIMIT = 200_000.0
TOTAL_ASSETS_990EZ_LIMIT = 500_000.0

# Proximity to a threshold, as a fraction, within which the decision is held
# for a preparer rather than made automatically.
REVIEW_BAND = 0.05


class FormRouting:
    """A routing decision, with everything needed to defend it."""

    __slots__ = (
        "form",
        "gross_receipts",
        "total_assets",
        "basis",
        "gross_receipts_current",
        "age_tier",
        "gross_receipts_limit",
        "requires_review",
        "review_reasons",
        "notes",
    )

    def __init__(
        self,
        form: str | None,
        gross_receipts: float | None,
        total_assets: float | None,
        basis: str,
        requires_review: bool,
        review_reasons: list[str],
        notes: list[str],
        age_tier: str = AgeTier.UNKNOWN,
        gross_receipts_limit: float = GROSS_RECEIPTS_990N_LIMIT,
        gross_receipts_current: float | None = None,
    ) -> None:
        self.form = form
        self.gross_receipts = gross_receipts
        self.total_assets = total_assets
        self.basis = basis
        self.age_tier = age_tier
        self.gross_receipts_limit = gross_receipts_limit
        self.gross_receipts_current = gross_receipts_current
        self.requires_review = requires_review
        self.review_reasons = review_reasons
        self.notes = notes

    def as_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "gross_receipts": self.gross_receipts,
            "gross_receipts_normally": self.gross_receipts,
            "gross_receipts_current_year": self.gross_receipts_current,
            "total_assets": self.total_assets,
            "gross_receipts_basis": self.basis,
            "age_tier": self.age_tier,
            "gross_receipts_990n_limit": self.gross_receipts_limit,
            "requires_human_review": self.requires_review,
            "review_reasons": list(self.review_reasons),
            "notes": list(self.notes),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FormRouting({self.form!r}, review={self.requires_review!r})"


def _within_band(value: float, threshold: float, band: float = REVIEW_BAND) -> bool:
    return abs(value - threshold) <= threshold * band


def route_form_variant(
    gross_receipts: float | None,
    total_assets: float | None = None,
    *,
    prior_year_gross_receipts: Iterable[float | None] = (),
    organization_age_years: float | None = None,
    review_band: float = REVIEW_BAND,
) -> FormRouting:
    """Select the form variant, or withhold the decision for review.

    `gross_receipts` must already be on the IRS basis -- receipts before
    subtracting costs. Passing Part VIII line 12 here will route small
    organizations wrongly.
    """
    notes: list[str] = []
    review_reasons: list[str] = []

    limit_990n, age_tier = threshold_990n_for_age(organization_age_years)

    # `tested` is the "normally" figure -- averaged where history allows -- and
    # governs the 990-N test only. `current` is the tax year's own figure and
    # governs the 990-EZ test.
    current = None if gross_receipts is None else round(float(gross_receipts), 2)
    tested, basis = normally_gross_receipts(
        gross_receipts, prior_year_gross_receipts, organization_age_years
    )

    if tested is None:
        return FormRouting(
            form=None,
            gross_receipts=None,
            total_assets=total_assets,
            basis=basis,
            requires_review=True,
            review_reasons=["No gross receipts available; cannot determine form."],
            notes=notes,
            age_tier=age_tier,
            gross_receipts_limit=limit_990n,
            gross_receipts_current=current,
        )

    if age_tier == AgeTier.UNKNOWN:
        review_reasons.append(
            f"Organization age unknown, so the strictest 990-N limit "
            f"({GROSS_RECEIPTS_990N_LIMIT:,.0f}) was applied. A newer "
            f"organization may qualify under a higher limit."
        )
    else:
        notes.append(
            f"990-N limit {limit_990n:,.0f} applied for age tier "
            f"'{age_tier}'."
        )

    if basis == "first_year_only":
        notes.append(
            "Tested on the first tax year alone, as the IRS requires for a "
            "newly formed organization."
        )
    elif basis == "average_first_2yr":
        notes.append("Tested on the average of the first two tax years.")
    elif basis == "current_year_only":
        review_reasons.append(
            "Only one year of gross receipts available; the IRS 'normally' test "
            "looks at recent history, so this decision rests on a single period."
        )
    elif basis.endswith("_partial"):
        notes.append(
            f"Rolling average computed from fewer than three years ({basis})."
        )

    # --- the decision ----------------------------------------------------
    assets = float(total_assets) if total_assets is not None else None

    if tested <= limit_990n:
        form = FORM_990N
        notes.append(
            f"Gross receipts {tested:,.2f} is at or below the "
            f"{limit_990n:,.0f} e-Postcard limit for this organization."
        )
    elif (
        current is not None
        and current < GROSS_RECEIPTS_990EZ_LIMIT
        and assets is not None
        and assets < TOTAL_ASSETS_990EZ_LIMIT
    ):
        form = FORM_990EZ
        notes.append(
            f"Gross receipts for the tax year {current:,.2f} is below "
            f"{GROSS_RECEIPTS_990EZ_LIMIT:,.0f} and total assets {assets:,.2f} "
            f"below {TOTAL_ASSETS_990EZ_LIMIT:,.0f}."
        )
    else:
        form = FORM_990
        if assets is None:
            notes.append(
                f"Gross receipts for the tax year "
                f"{(current if current is not None else tested):,.2f} tested "
                f"against {GROSS_RECEIPTS_990EZ_LIMIT:,.0f}."
            )
            review_reasons.append(
                "Total assets unknown; the 990-EZ test requires both gross "
                "receipts and total assets, so the full 990 was chosen "
                "conservatively."
            )
        elif assets >= TOTAL_ASSETS_990EZ_LIMIT:
            notes.append(
                f"Total assets {assets:,.2f} is at or above "
                f"{TOTAL_ASSETS_990EZ_LIMIT:,.0f}, which requires the full return "
                f"regardless of gross receipts."
            )
        else:
            notes.append(
                f"Gross receipts for the tax year "
                f"{(current if current is not None else tested):,.2f} is at or "
                f"above {GROSS_RECEIPTS_990EZ_LIMIT:,.0f}."
            )

    # --- boundary proximity ----------------------------------------------
    # Each band measures the figure its own test used: the averaged figure
    # against the 990-N limit, the tax year's figure against the 990-EZ limit.
    if _within_band(tested, limit_990n, review_band):
        review_reasons.append(
            f"Gross receipts {tested:,.2f} is within {review_band:.0%} of "
            f"the 990-N limit ({limit_990n:,.0f})."
        )

    if current is not None and _within_band(
        current, GROSS_RECEIPTS_990EZ_LIMIT, review_band
    ):
        review_reasons.append(
            f"Gross receipts for the tax year {current:,.2f} is within "
            f"{review_band:.0%} of the 990-EZ gross receipts limit "
            f"({GROSS_RECEIPTS_990EZ_LIMIT:,.0f})."
        )

    if assets is not None and _within_band(
        assets, TOTAL_ASSETS_990EZ_LIMIT, review_band
    ):
        review_reasons.append(
            f"Total assets {assets:,.2f} is within {review_band:.0%} of the "
            f"990-EZ asset limit ({TOTAL_ASSETS_990EZ_LIMIT:,.0f})."
        )

    return FormRouting(
        form=form,
        gross_receipts=round(tested, 2),
        total_assets=round(assets, 2) if assets is not None else None,
        basis=basis,
        requires_review=bool(review_reasons),
        review_reasons=review_reasons,
        notes=notes,
        age_tier=age_tier,
        gross_receipts_limit=limit_990n,
        gross_receipts_current=current,
    )

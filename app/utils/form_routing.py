"""Decide which return in the 990 series an organization files.

This is the single most consequential decision the system makes. Filing the
wrong variant is a compliance failure, not a formatting one, so the decision
is made here in code from validated figures -- never by the model.

The IRS thresholds:

    Form 990-N    gross receipts normally <= $50,000
    Form 990-EZ   gross receipts < $200,000  AND  total assets < $500,000
    Form 990      gross receipts >= $200,000  OR  total assets >= $500,000

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

from app.utils.gross_receipts import normally_gross_receipts

__all__ = [
    "FORM_990N",
    "FORM_990EZ",
    "FORM_990",
    "GROSS_RECEIPTS_990N_LIMIT",
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
    ) -> None:
        self.form = form
        self.gross_receipts = gross_receipts
        self.total_assets = total_assets
        self.basis = basis
        self.requires_review = requires_review
        self.review_reasons = review_reasons
        self.notes = notes

    def as_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "gross_receipts": self.gross_receipts,
            "total_assets": self.total_assets,
            "gross_receipts_basis": self.basis,
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
    review_band: float = REVIEW_BAND,
) -> FormRouting:
    """Select the form variant, or withhold the decision for review.

    `gross_receipts` must already be on the IRS basis -- receipts before
    subtracting costs. Passing Part VIII line 12 here will route small
    organizations wrongly.
    """
    notes: list[str] = []
    review_reasons: list[str] = []

    tested, basis = normally_gross_receipts(gross_receipts, prior_year_gross_receipts)

    if tested is None:
        return FormRouting(
            form=None,
            gross_receipts=None,
            total_assets=total_assets,
            basis=basis,
            requires_review=True,
            review_reasons=["No gross receipts available; cannot determine form."],
            notes=notes,
        )

    if basis == "current_year_only":
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

    if tested <= GROSS_RECEIPTS_990N_LIMIT:
        form = FORM_990N
        notes.append(
            f"Gross receipts {tested:,.2f} is at or below the "
            f"{GROSS_RECEIPTS_990N_LIMIT:,.0f} e-Postcard limit."
        )
    elif tested < GROSS_RECEIPTS_990EZ_LIMIT and (
        assets is not None and assets < TOTAL_ASSETS_990EZ_LIMIT
    ):
        form = FORM_990EZ
        notes.append(
            f"Gross receipts {tested:,.2f} is below {GROSS_RECEIPTS_990EZ_LIMIT:,.0f} "
            f"and total assets {assets:,.2f} below {TOTAL_ASSETS_990EZ_LIMIT:,.0f}."
        )
    else:
        form = FORM_990
        if assets is None:
            notes.append(
                f"Gross receipts {tested:,.2f} is at or above "
                f"{GROSS_RECEIPTS_990EZ_LIMIT:,.0f}."
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
                f"Gross receipts {tested:,.2f} is at or above "
                f"{GROSS_RECEIPTS_990EZ_LIMIT:,.0f}."
            )

    # --- boundary proximity ----------------------------------------------
    for threshold, label in (
        (GROSS_RECEIPTS_990N_LIMIT, "the 990-N limit"),
        (GROSS_RECEIPTS_990EZ_LIMIT, "the 990-EZ gross receipts limit"),
    ):
        if _within_band(tested, threshold, review_band):
            review_reasons.append(
                f"Gross receipts {tested:,.2f} is within "
                f"{review_band:.0%} of {label} ({threshold:,.0f})."
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
    )

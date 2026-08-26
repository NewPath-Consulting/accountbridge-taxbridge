"""Assemble the unified draft payload.

The Product Research Specification names this as a deliverable:

    DRAFT Tax990.com E-File Draft JSON Payload: A unified JSON payload
    structure that maps core data outputs for organizations routed to
    Form 990-EZ and the Full Form 990 based on the thresholds determined
    in Initiative 1.

Note "DRAFT". Tax990's API supports Form 990-N only; there is no 990-EZ or
full 990 endpoint to conform to. This is therefore a proposal rather than a
mapping -- the concrete artefact to put in front of Tax990 when agreeing the
functional specification, showing exactly what TaxBridge would send.

The envelope carries only the elements the routed variant needs, so the
routing decision determines the shape of the document rather than sitting
alongside a full return regardless.

Confidence is derived, not asserted. The specification's example carries a
bare `confidence_score: 0.942` with no indication of where it came from. A
number the model reports about its own output is another generated token; the
score here is computed from validation outcomes already available -- whether
the arithmetic reconciles, how many accounts fell through to a default
classification, how much of the form remains undetermined, and how close the
organization sits to a filing threshold -- and every component is published
alongside it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.utils.form_routing import FORM_990, FORM_990EZ, FORM_990N, FormRouting

__all__ = [
    "ConfidenceScore",
    "DraftPayload",
    "build_draft_payload",
    "score_confidence",
    "VARIANT_KEYS",
]

VARIANT_KEYS = {
    FORM_990N: "990_N",
    FORM_990EZ: "990_EZ",
    FORM_990: "990_FULL",
}

# Weights sum to 1.0. Arithmetic integrity carries the most because a return
# whose figures do not reconcile is not merely uncertain, it is wrong.
CONFIDENCE_WEIGHTS = {
    "arithmetic_integrity": 0.35,
    "reconciliation": 0.25,
    "structural_completeness": 0.20,
    "classification_certainty": 0.15,
    "threshold_margin": 0.05,
}


class ConfidenceScore:
    """A score with the components that produced it."""

    __slots__ = ("overall", "components", "notes")

    def __init__(
        self, overall: float, components: dict[str, float], notes: list[str]
    ) -> None:
        self.overall = overall
        self.components = components
        self.notes = notes

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.overall,
            "components": dict(self.components),
            "weights": dict(CONFIDENCE_WEIGHTS),
            "notes": list(self.notes),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ConfidenceScore({self.overall!r})"


class DraftPayload:
    """The assembled document and whether it is fit to send."""

    __slots__ = ("payload", "confidence", "blocking_errors")

    def __init__(
        self,
        payload: dict[str, Any],
        confidence: ConfidenceScore,
        blocking_errors: list[str],
    ) -> None:
        self.payload = payload
        self.confidence = confidence
        self.blocking_errors = blocking_errors

    @property
    def is_submittable(self) -> bool:
        return not self.blocking_errors

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DraftPayload(variant={self.payload.get('taxbridge_metadata', {}).get('routed_form_variant')!r})"


def _round(value: Any, places: int = 2) -> float:
    try:
        return round(float(value or 0.0), places)
    except (TypeError, ValueError):
        return 0.0


def _reconciliation_pass_rate(content: Mapping[str, Any]) -> tuple[float, int, int]:
    results = content.get("reconciliationResults") or []
    total = 0
    passed = 0
    for entry in results:
        if isinstance(entry, dict):
            total += 1
            if str(entry.get("result", "")).lower() == "pass":
                passed += 1
        elif isinstance(entry, str):
            total += 1
            if "(pass)" in entry.lower():
                passed += 1
    if not total:
        return 0.0, 0, 0
    return passed / total, passed, total


def _arithmetic_holds(content: Mapping[str, Any]) -> bool:
    """Do the Part VIII line items sum to the stated total?"""
    items = content.get("partVIII_revenue") or []
    if not items:
        return False
    walked = round(
        sum(_round(i.get("totalRevenue")) for i in items if isinstance(i, dict)), 2
    )
    stated = _round(content.get("partVIII_totalRevenue"))
    return walked == stated


def _classification_certainty(validation_notes: list[str]) -> tuple[float, int, int]:
    """How much of Part VIII was classified rather than defaulted.

    Accounts the enforcement layer had to add and classify by rule are less
    certain than those the model recognised, because the rule set is name
    matching and defaults to Other Revenue when nothing matches.
    """
    added = sum(1 for note in validation_notes if note.startswith("PART_VIII_ADDED"))
    dropped = sum(1 for note in validation_notes if note.startswith("PART_VIII_DROPPED"))
    corrected = sum(
        1 for note in validation_notes if note.startswith("PART_VIII_CORRECTED")
    )
    touched = added + dropped + corrected
    if not touched:
        return 1.0, 0, 0
    # Every intervention is evidence the model's output needed repair.
    return max(0.0, 1.0 - min(1.0, touched / 12.0)), added, dropped


def _structural_completeness(structure_report: Any) -> float:
    if structure_report is None:
        return 0.5
    missing = getattr(structure_report, "missing", None) or []
    if not missing:
        return 1.0
    return max(0.0, 1.0 - min(1.0, len(missing) / 4.0))


def _threshold_margin(routing: FormRouting) -> float:
    if routing.requires_review:
        return 0.5
    return 1.0


def score_confidence(
    content: Mapping[str, Any],
    routing: FormRouting,
    *,
    structure_report: Any = None,
) -> ConfidenceScore:
    """Derive a confidence score from validation outcomes."""
    notes: list[str] = []
    validation_notes = [
        str(n) for n in (content.get("validationErrors") or []) if n
    ]

    arithmetic = 1.0 if _arithmetic_holds(content) else 0.0
    if arithmetic == 0.0:
        notes.append(
            "Part VIII line items do not sum to the stated total; the return "
            "is not merely uncertain, it is arithmetically wrong."
        )

    recon_rate, passed, total = _reconciliation_pass_rate(content)
    if total:
        notes.append(f"{passed} of {total} reconciliation checks passed.")
    else:
        notes.append("No reconciliation checks were recorded.")

    completeness = _structural_completeness(structure_report)
    if completeness < 1.0:
        notes.append("Parts of the return remain undetermined.")

    certainty, added, dropped = _classification_certainty(validation_notes)
    if added or dropped:
        notes.append(
            f"Enforcement added {added} account(s) and dropped {dropped} "
            f"fabricated line(s) from Part VIII."
        )

    margin = _threshold_margin(routing)
    if margin < 1.0:
        notes.append("Routing was held for review; the form choice is not settled.")

    components = {
        "arithmetic_integrity": round(arithmetic, 3),
        "reconciliation": round(recon_rate, 3),
        "structural_completeness": round(completeness, 3),
        "classification_certainty": round(certainty, 3),
        "threshold_margin": round(margin, 3),
    }
    overall = round(
        sum(components[key] * weight for key, weight in CONFIDENCE_WEIGHTS.items()), 3
    )
    return ConfidenceScore(overall, components, notes)


def _organization_details(content: Mapping[str, Any]) -> dict[str, Any]:
    org = content.get("organizationInformation") or {}
    summary = content.get("organization_summary") or {}
    officer = org.get("principalOfficer") or {}
    return {
        "ein": org.get("ein") or summary.get("ein") or "",
        "legal_name": org.get("legalName") or summary.get("organization_name") or "",
        "dba_names": list(org.get("dbaNames") or []),
        "address": dict(org.get("address") or {}),
        "website": org.get("website") or "",
        "principal_officer": {
            "name": officer.get("name") or "",
            "title": officer.get("title") or "",
            "address": officer.get("address") or "",
        },
        "tax_exempt_status": org.get("taxExemptStatus") or "",
        "year_of_formation": org.get("yearOfFormation") or "",
    }


def _full_990_elements(content: Mapping[str, Any]) -> dict[str, Any]:
    part_iii = content.get("partIII_programServiceAccomplishments") or {}
    services = []
    for service in part_iii.get("programServices") or []:
        if not isinstance(service, dict):
            continue
        services.append(
            {
                "program_code": service.get("code") or "",
                "expense_allocated": _round(service.get("expenses")),
                "revenue_generated": _round(service.get("revenue")),
                "grants_included": _round(service.get("grantsIncluded")),
                "description_narrative": service.get("description") or "",
            }
        )

    totals = content.get("partIX_totals") or {}
    return {
        "part_iii_program_accomplishments": services,
        "part_viii_revenue": content.get("partVIII_revenue") or [],
        "part_ix_functional_expenses": {
            "line_25_total_functional_expenses": {
                "program_service_expenses": _round(totals.get("totalProgramServices")),
                "management_and_general_expenses": _round(
                    totals.get("totalManagementAndGeneral")
                ),
                "fundraising_expenses": _round(totals.get("totalFundraising")),
                "total_expenses": _round(totals.get("totalExpenses")),
            }
        },
        "part_x_balance_sheet": content.get("partX_balanceSheet") or {},
    }


def build_draft_payload(
    content: Mapping[str, Any],
    routing: FormRouting,
    *,
    organization_id: str = "",
    form_990ez: Any = None,
    form_990n_payload: Mapping[str, Any] | None = None,
    structure_report: Any = None,
    generated_at: datetime | None = None,
) -> DraftPayload:
    """Assemble the unified draft payload for whichever variant was routed."""
    blocking: list[str] = []

    if routing.form is None:
        blocking.append("No form variant was determined; nothing can be assembled.")

    confidence = score_confidence(
        content, routing, structure_report=structure_report
    )

    timestamp = (generated_at or datetime.now(timezone.utc)).isoformat()

    payload: dict[str, Any] = {
        "taxbridge_metadata": {
            "organization_id": organization_id,
            "timestamp_generated": timestamp,
            "routed_form_variant": VARIANT_KEYS.get(routing.form or "", None),
            "confidence_score": confidence.overall,
            "confidence_basis": confidence.as_dict(),
            "requires_human_review": routing.requires_review,
            "review_reasons": list(routing.review_reasons),
            "routing_basis": {
                "gross_receipts": routing.gross_receipts,
                "total_assets": routing.total_assets,
                "gross_receipts_basis": routing.basis,
                "age_tier": routing.age_tier,
                "gross_receipts_990n_limit": routing.gross_receipts_limit,
            },
        },
        "organization_details": _organization_details(content),
    }

    # Only the routed variant's elements are carried. A 990-N filer has no
    # financial schedule to send, and sending one would invite the reader to
    # treat figures as filed that are not part of the return.
    if routing.form == FORM_990N:
        if form_990n_payload:
            payload["form_990n_elements"] = dict(form_990n_payload)
        else:
            blocking.append(
                "Routed to 990-N but no 990-N payload was supplied."
            )
    elif routing.form == FORM_990EZ:
        if form_990ez is None:
            blocking.append("Routed to 990-EZ but no 990-EZ output was supplied.")
        else:
            payload["form_990ez_elements"] = {
                "part_i_revenue_expenses": dict(form_990ez.part_i),
                "part_ii_balance_sheet": dict(form_990ez.part_ii),
            }
            if not form_990ez.is_internally_consistent:
                blocking.extend(form_990ez.check_failures)
    elif routing.form == FORM_990:
        payload["form_990_full_elements"] = _full_990_elements(content)

    validation: dict[str, Any] = {
        "reconciliation_results": content.get("reconciliationResults") or [],
        "validation_notes": [str(n) for n in (content.get("validationErrors") or [])],
    }
    if structure_report is not None:
        validation["structural_gaps"] = list(getattr(structure_report, "missing", []))
        validation["invented_lines_removed"] = list(
            getattr(structure_report, "invented", [])
        )
    payload["validation"] = validation

    return DraftPayload(payload, confidence, blocking)

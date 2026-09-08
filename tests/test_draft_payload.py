"""Tests for the unified draft payload.

The specification asks for a payload structure covering organizations routed
to 990-EZ and the full 990. Tax990's API supports 990-N only, so this is a
proposal to put in front of them rather than a mapping onto an existing
contract -- which makes it more important, not less, that the shape is
defensible and every figure in it traceable.
"""

from datetime import datetime, timezone

import pytest

from app.utils.draft_payload import (
    CONFIDENCE_WEIGHTS,
    build_draft_payload,
    score_confidence,
)
from app.utils.form_990ez import build_form_990ez
from app.utils.form_990_structure import apply_static_line_inventories
from app.utils.form_routing import route_form_variant

ESTABLISHED = 10.0
FIXED_TIME = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def content() -> dict:
    """Content after enforcement: figures reconciled, structure still thin."""
    return {
        "organizationInformation": {
            "legalName": "Example Nonprofit Inc",
            "dbaNames": ["Example"],
            "ein": "43-1633425",
            "address": {"street": "1 Main St", "city": "Kansas City",
                        "state": "MO", "zip": "64111"},
            "website": "https://example.org",
            "principalOfficer": {"name": "Jane Doe", "title": "President"},
            "taxExemptStatus": "501(c)(3)",
        },
        "organization_summary": {"tax_year": "2026", "gross_receipts": 10605.77},
        "partVIII_revenue": [
            {"lineNumber": "1a", "label": "Donations", "totalRevenue": 2250.00},
            {"lineNumber": "2a", "label": "Program Fees", "totalRevenue": 7950.77},
        ],
        "partVIII_totalRevenue": 10200.77,
        "partIX_totals": {
            "totalExpenses": 8558.31,
            "totalProgramServices": 8000.00,
            "totalManagementAndGeneral": 558.31,
            "totalFundraising": 0.0,
        },
        "partIII_programServiceAccomplishments": {
            "programServices": [
                {"code": "PC_01", "expenses": 8000.00, "revenue": 7950.77,
                 "grantsIncluded": 0.0, "description": "Community workshops"}
            ]
        },
        "partX_balanceSheet": {
            "assets": [{"label": "Cash", "beginningOfYear": 0.0, "endOfYear": 2001.00}],
            "totalAssets": {"beginningOfYear": 0.0, "endOfYear": 23436.29},
            "totalLiabilities": {"beginningOfYear": 0.0, "endOfYear": 31131.33},
            "netAssets": {"totalNetAssets": {"beginningOfYear": 0.0,
                                             "endOfYear": -7695.04}},
        },
        "reconciliationResults": [
            {"check": "QuickBooks Revenue = Part VIII Total Revenue", "result": "Pass"},
            {"check": "QuickBooks Expenses = Part IX Total Expenses", "result": "Pass"},
            {"check": "Beginning Net Assets + Change = Ending", "result": "Pass"},
            {"check": "Assets = Liabilities + Net Assets", "result": "Pass"},
        ],
        "validationErrors": [],
    }


def _routing(gross_receipts=10605.77, assets=23436.29, priors=(10000.0, 11000.0)):
    return route_form_variant(
        gross_receipts, assets,
        organization_age_years=ESTABLISHED,
        prior_year_gross_receipts=priors,
    )


# --- the envelope ---------------------------------------------------------

def test_metadata_carries_the_routed_variant(content):
    result = build_draft_payload(content, _routing(), generated_at=FIXED_TIME)
    meta = result.payload["taxbridge_metadata"]
    assert meta["routed_form_variant"] == "990_N"
    assert meta["timestamp_generated"] == FIXED_TIME.isoformat()


def test_routing_basis_is_published(content):
    """The reader can see why this variant was chosen, not just that it was."""
    result = build_draft_payload(content, _routing(), generated_at=FIXED_TIME)
    basis = result.payload["taxbridge_metadata"]["routing_basis"]
    assert basis["gross_receipts_basis"] == "rolling_average_3yr"
    assert basis["age_tier"] == "established_3yr_or_more"
    assert basis["gross_receipts_990n_limit"] == 50000.0


def test_organization_details_are_extracted(content):
    result = build_draft_payload(content, _routing(), generated_at=FIXED_TIME)
    details = result.payload["organization_details"]
    assert details["legal_name"] == "Example Nonprofit Inc"
    assert details["ein"] == "43-1633425"
    assert details["principal_officer"]["name"] == "Jane Doe"


def test_validation_travels_with_the_payload(content):
    result = build_draft_payload(content, _routing(), generated_at=FIXED_TIME)
    assert len(result.payload["validation"]["reconciliation_results"]) == 4


# --- the routed variant determines the shape ------------------------------

def test_ez_payload_carries_only_ez_elements(content):
    routing = _routing(120_000.0, 200_000.0, (120_000.0, 120_000.0))
    ez = build_form_990ez(content)
    result = build_draft_payload(
        content, routing, form_990ez=ez, generated_at=FIXED_TIME
    )
    assert result.payload["taxbridge_metadata"]["routed_form_variant"] == "990_EZ"
    assert "form_990ez_elements" in result.payload
    assert "form_990_full_elements" not in result.payload


def test_ez_elements_match_the_specification_shape(content):
    routing = _routing(120_000.0, 200_000.0, (120_000.0, 120_000.0))
    ez = build_form_990ez(content)
    result = build_draft_payload(
        content, routing, form_990ez=ez, generated_at=FIXED_TIME
    )
    elements = result.payload["form_990ez_elements"]
    assert "part_i_revenue_expenses" in elements
    assert "part_ii_balance_sheet" in elements
    assert elements["part_i_revenue_expenses"]["line_9_total_revenue"] == 10200.77


def test_full_990_payload_carries_program_accomplishments(content):
    routing = _routing(400_000.0, 900_000.0, (400_000.0, 400_000.0))
    result = build_draft_payload(content, routing, generated_at=FIXED_TIME)
    assert result.payload["taxbridge_metadata"]["routed_form_variant"] == "990_FULL"
    services = result.payload["form_990_full_elements"]["part_iii_program_accomplishments"]
    assert services[0]["program_code"] == "PC_01"
    assert services[0]["expense_allocated"] == 8000.00


def test_full_990_carries_functional_expense_totals(content):
    routing = _routing(400_000.0, 900_000.0, (400_000.0, 400_000.0))
    result = build_draft_payload(content, routing, generated_at=FIXED_TIME)
    line25 = result.payload["form_990_full_elements"]["part_ix_functional_expenses"][
        "line_25_total_functional_expenses"
    ]
    assert line25["total_expenses"] == 8558.31
    assert line25["program_service_expenses"] == 8000.00


def test_990n_payload_is_carried_when_supplied(content):
    result = build_draft_payload(
        content, _routing(),
        form_990n_payload={"Form990NRecords": [{"Business": {}}]},
        generated_at=FIXED_TIME,
    )
    assert "form_990n_elements" in result.payload


def test_missing_variant_output_blocks(content):
    routing = _routing(120_000.0, 200_000.0, (120_000.0, 120_000.0))
    result = build_draft_payload(content, routing, generated_at=FIXED_TIME)
    assert not result.is_submittable
    assert any("990-EZ" in e for e in result.blocking_errors)


def test_inconsistent_ez_blocks(content):
    content["partVIII_totalRevenue"] = 99999.99
    routing = _routing(120_000.0, 200_000.0, (120_000.0, 120_000.0))
    ez = build_form_990ez(content)
    result = build_draft_payload(
        content, routing, form_990ez=ez, generated_at=FIXED_TIME
    )
    assert not result.is_submittable


# --- confidence, derived rather than asserted -----------------------------

def test_weights_sum_to_one():
    assert round(sum(CONFIDENCE_WEIGHTS.values()), 6) == 1.0


def test_clean_output_scores_high(content):
    score = score_confidence(content, _routing())
    assert score.overall > 0.85


def test_broken_part_viii_halves_the_arithmetic_score(content):
    """Two independent checks. Failing one is worse than failing neither and
    better than failing both."""
    clean = score_confidence(content, _routing())
    assert clean.components["arithmetic_integrity"] == 1.0

    content["partVIII_totalRevenue"] = 99999.99
    broken = score_confidence(content, _routing())
    assert broken.components["arithmetic_integrity"] == 0.5
    assert broken.overall < clean.overall
    assert any("Part VIII line items sum to" in n for n in broken.notes)


def test_unallocated_part_ix_expenses_are_caught(content):
    """The columns must account for the total. An expense in the total and in
    no column is a wrong return that reads as complete, because the total is
    right and nothing obviously looks amiss.

    Found on a real organization's data: 67,306 unallocated while the
    arithmetic check still scored full marks.
    """
    content["partIX_totals"] = {
        "totalExpenses": 273306.00,
        "totalProgramServices": 138000.00,
        "totalManagementAndGeneral": 68000.00,
        "totalFundraising": 0.00,
    }
    score = score_confidence(content, _routing())
    assert score.components["arithmetic_integrity"] == 0.5
    problem = next(n for n in score.notes if "Part IX columns" in n)
    assert "67,306.00" in problem
    assert "unallocated" in problem


def test_both_arithmetic_checks_failing_scores_zero(content):
    content["partVIII_totalRevenue"] = 99999.99
    content["partIX_totals"] = {
        "totalExpenses": 273306.00,
        "totalProgramServices": 1.00,
        "totalManagementAndGeneral": 0.00,
        "totalFundraising": 0.00,
    }
    score = score_confidence(content, _routing())
    assert score.components["arithmetic_integrity"] == 0.0


def test_over_allocated_columns_are_named_as_such(content):
    content["partIX_totals"] = {
        "totalExpenses": 100000.00,
        "totalProgramServices": 90000.00,
        "totalManagementAndGeneral": 30000.00,
        "totalFundraising": 0.00,
    }
    score = score_confidence(content, _routing())
    assert any("over-allocated" in n for n in score.notes)


def test_no_reported_expenses_is_not_a_failure(content):
    """Nothing reported cannot contradict anything."""
    content["partIX_totals"] = {}
    score = score_confidence(content, _routing())
    assert score.components["arithmetic_integrity"] == 1.0


def test_failed_reconciliation_lowers_the_score(content):
    clean = score_confidence(content, _routing()).overall
    for check in content["reconciliationResults"]:
        check["result"] = "Fail"
    assert score_confidence(content, _routing()).overall < clean


def test_enforcement_interventions_lower_certainty(content):
    clean = score_confidence(content, _routing()).components["classification_certainty"]
    content["validationErrors"] = [
        "PART_VIII_ADDED: 'Discounts given' was missing",
        "PART_VIII_DROPPED: 'Miscellaneous Income' does not exist",
        "PART_VIII_CORRECTED: 'Landscaping Services' 6513.97 -> 1477.50",
    ]
    touched = score_confidence(content, _routing()).components["classification_certainty"]
    assert touched < clean


def test_structural_gaps_lower_the_score(content):
    report = apply_static_line_inventories(content)
    with_gaps = score_confidence(content, _routing(), structure_report=report)
    assert with_gaps.components["structural_completeness"] < 1.0


def test_review_flag_lowers_the_threshold_margin(content):
    """An organization within 5% of a limit is less certain than one
    comfortably clear of it."""
    near = route_form_variant(
        49_000.0, 10_000.0, organization_age_years=ESTABLISHED,
        prior_year_gross_receipts=(49_000.0, 49_000.0),
    )
    assert score_confidence(content, near).components["threshold_margin"] < 1.0


def test_every_component_is_published(content):
    result = build_draft_payload(content, _routing(), generated_at=FIXED_TIME)
    basis = result.payload["taxbridge_metadata"]["confidence_basis"]
    assert set(basis["components"]) == set(CONFIDENCE_WEIGHTS)
    assert basis["weights"] == CONFIDENCE_WEIGHTS
    assert basis["notes"]


def test_confidence_notes_explain_the_score(content):
    for check in content["reconciliationResults"]:
        check["result"] = "Fail"
    score = score_confidence(content, _routing())
    assert any("0 of 4 reconciliation checks" in n for n in score.notes)


# --- structural report integration ---------------------------------------

def test_structural_gaps_are_reported_in_validation(content):
    report = apply_static_line_inventories(content)
    result = build_draft_payload(
        content, _routing(), structure_report=report, generated_at=FIXED_TIME
    )
    assert result.payload["validation"]["structural_gaps"]


def test_no_routing_blocks_assembly(content):
    routing = route_form_variant(None)
    result = build_draft_payload(content, routing, generated_at=FIXED_TIME)
    assert not result.is_submittable
    assert any("No form variant" in e for e in result.blocking_errors)

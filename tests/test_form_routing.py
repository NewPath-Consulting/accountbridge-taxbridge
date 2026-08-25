"""Tests for form variant routing.

Routing is the decision that determines whether a filing is correct or a
compliance failure, so the tests concentrate on the boundaries and on the
two conditions that are easy to get wrong: the 990-EZ asset test, and the
multi-year "normally" test.
"""

import pytest

from app.utils.gross_receipts import (
    ESTABLISHED_ORG_LIMIT,
    NEW_ORG_LIMIT,
    YOUNG_ORG_LIMIT,
    AgeTier,
)
from app.utils.form_routing import (
    FORM_990,
    FORM_990EZ,
    FORM_990N,
    GROSS_RECEIPTS_990EZ_LIMIT,
    GROSS_RECEIPTS_990N_LIMIT,
    TOTAL_ASSETS_990EZ_LIMIT,
    route_form_variant,
)


ESTABLISHED = 10.0  # years; an organisation past the three-year tier


def _route(gr, assets=None, priors=(50_000.0, 50_000.0), age=ESTABLISHED):
    """Route with enough history and a known age, so threshold behaviour can
    be tested without the single-year or unknown-age review flags firing."""
    return route_form_variant(
        gr, assets, prior_year_gross_receipts=priors, organization_age_years=age
    )


# --- the three variants ---------------------------------------------------

def test_small_organisation_files_990n():
    r = route_form_variant(30_000.0, 10_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(29_000.0, 31_000.0))
    assert r.form == FORM_990N


def test_mid_sized_organisation_files_990ez():
    r = route_form_variant(120_000.0, 200_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(118_000.0, 122_000.0))
    assert r.form == FORM_990EZ


def test_large_organisation_files_full_990():
    r = route_form_variant(400_000.0, 900_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(390_000.0, 410_000.0))
    assert r.form == FORM_990


# --- the asset test, which the intake form ignores ------------------------

def test_high_assets_force_the_full_990_despite_low_receipts():
    """60,000 of gross receipts would suggest the EZ, but 800,000 of assets
    requires the full return. The demo intake form asks only about revenue
    and would route this wrongly."""
    r = route_form_variant(60_000.0, 800_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(60_000.0, 60_000.0))
    assert r.form == FORM_990
    assert any("total assets" in n.lower() for n in r.notes)


def test_ez_requires_both_conditions():
    below_both = route_form_variant(
        150_000.0, 400_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(150_000.0, 150_000.0)
    )
    assets_over = route_form_variant(
        150_000.0, 600_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(150_000.0, 150_000.0)
    )
    assert below_both.form == FORM_990EZ
    assert assets_over.form == FORM_990


def test_unknown_assets_choose_the_full_return_and_ask_for_review():
    """With assets unknown the EZ test cannot be evaluated, so the safer
    return is chosen and the gap is surfaced rather than hidden."""
    r = route_form_variant(150_000.0, None, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(150_000.0, 150_000.0))
    assert r.form == FORM_990
    assert r.requires_review
    assert any("assets unknown" in x.lower() for x in r.review_reasons)


# --- exact boundaries -----------------------------------------------------

@pytest.mark.parametrize(
    "gross_receipts,expected",
    [
        (GROSS_RECEIPTS_990N_LIMIT, FORM_990N),          # at the limit: 990-N
        (GROSS_RECEIPTS_990N_LIMIT + 0.01, FORM_990EZ),  # a cent over: EZ
        (GROSS_RECEIPTS_990EZ_LIMIT - 0.01, FORM_990EZ),
        (GROSS_RECEIPTS_990EZ_LIMIT, FORM_990),          # at the limit: full
    ],
)
def test_threshold_edges(gross_receipts, expected):
    r = route_form_variant(
        gross_receipts,
        1_000.0,
        organization_age_years=ESTABLISHED, prior_year_gross_receipts=(gross_receipts, gross_receipts),
    )
    assert r.form == expected


def test_asset_limit_edge():
    at_limit = route_form_variant(
        100_000.0, TOTAL_ASSETS_990EZ_LIMIT,
        organization_age_years=ESTABLISHED, prior_year_gross_receipts=(100_000.0, 100_000.0),
    )
    just_under = route_form_variant(
        100_000.0, TOTAL_ASSETS_990EZ_LIMIT - 0.01,
        organization_age_years=ESTABLISHED, prior_year_gross_receipts=(100_000.0, 100_000.0),
    )
    assert at_limit.form == FORM_990
    assert just_under.form == FORM_990EZ


# --- the review band ------------------------------------------------------

def test_just_under_the_50k_limit_is_held_for_review():
    r = _route(49_000.0, 10_000.0, priors=(49_000.0, 49_000.0))
    assert r.form == FORM_990N
    assert r.requires_review
    assert any("990-N limit" in x for x in r.review_reasons)


def test_just_over_the_50k_limit_is_held_for_review():
    r = _route(51_500.0, 10_000.0, priors=(51_500.0, 51_500.0))
    assert r.requires_review


def test_comfortably_clear_of_thresholds_is_not_flagged():
    r = _route(20_000.0, 10_000.0, priors=(20_000.0, 20_000.0))
    assert r.form == FORM_990N
    assert not r.requires_review
    assert r.review_reasons == []


def test_assets_near_the_limit_are_flagged():
    r = _route(100_000.0, 490_000.0, priors=(100_000.0, 100_000.0))
    assert r.form == FORM_990EZ
    assert r.requires_review
    assert any("asset limit" in x.lower() for x in r.review_reasons)


def test_review_band_is_configurable():
    tight = route_form_variant(
        49_000.0, 10_000.0,
        organization_age_years=ESTABLISHED, prior_year_gross_receipts=(49_000.0, 49_000.0),
        review_band=0.001,
    )
    assert not tight.requires_review


# --- the "normally" test --------------------------------------------------

def test_a_single_spike_does_not_move_a_small_organisation():
    """One 90,000 year against two 20,000 years averages to 43,333 and stays
    on the 990-N -- which is what 'normally' is for."""
    r = route_form_variant(90_000.0, 5_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(20_000.0, 20_000.0))
    assert r.form == FORM_990N
    assert r.basis == "rolling_average_3yr"


def test_one_year_of_data_is_flagged_for_review():
    r = route_form_variant(30_000.0, 5_000.0, organization_age_years=ESTABLISHED)
    assert r.form == FORM_990N
    assert r.requires_review
    assert any("single period" in x for x in r.review_reasons)


def test_no_data_withholds_the_decision():
    r = route_form_variant(None)
    assert r.form is None
    assert r.requires_review
    assert r.basis == "no_data"


# --- the decision is auditable -------------------------------------------

def test_decision_records_its_inputs_and_reasoning():
    r = route_form_variant(120_000.0, 200_000.0, organization_age_years=ESTABLISHED, prior_year_gross_receipts=(118_000.0, 122_000.0))
    d = r.as_dict()
    assert d["form"] == FORM_990EZ
    assert d["gross_receipts"] == 120_000.0
    assert d["total_assets"] == 200_000.0
    assert d["gross_receipts_basis"] == "rolling_average_3yr"
    assert d["requires_human_review"] is False
    assert d["notes"]


def test_sandbox_company_routes_to_990n():
    """The fixture organisation: gross receipts 10,605.77, assets 23,436.29.
    Held for review because only one year of history exists."""
    r = route_form_variant(10_605.77, 23_436.29, organization_age_years=ESTABLISHED)
    assert r.form == FORM_990N
    assert r.requires_review
    assert any("single period" in x for x in r.review_reasons)


# --- the age tiers --------------------------------------------------------

def test_first_year_organisation_uses_the_75k_limit():
    """A one-year-old organisation with 70,000 of gross receipts is eligible
    for the e-Postcard. Applying the established 50,000 limit would route it
    to the 990-EZ, which is a wrong filing."""
    r = route_form_variant(70_000.0, 5_000.0, organization_age_years=1.0)
    assert r.form == FORM_990N
    assert r.gross_receipts_limit == NEW_ORG_LIMIT
    assert r.age_tier == AgeTier.NEW


def test_established_organisation_with_the_same_receipts_files_990ez():
    """Same figures, older organisation, different answer."""
    r = route_form_variant(
        70_000.0, 5_000.0,
        organization_age_years=10.0,
        prior_year_gross_receipts=(70_000.0, 70_000.0),
    )
    assert r.form == FORM_990EZ
    assert r.gross_receipts_limit == ESTABLISHED_ORG_LIMIT


def test_young_organisation_uses_the_60k_limit():
    r = route_form_variant(
        58_000.0, 5_000.0,
        organization_age_years=2.0,
        prior_year_gross_receipts=(58_000.0,),
    )
    assert r.form == FORM_990N
    assert r.gross_receipts_limit == YOUNG_ORG_LIMIT
    assert r.age_tier == AgeTier.YOUNG


def test_first_year_is_tested_on_that_year_alone():
    """There are no prior years to average, so any supplied are ignored."""
    r = route_form_variant(
        70_000.0, 5_000.0,
        organization_age_years=0.5,
        prior_year_gross_receipts=(10_000.0, 10_000.0),
    )
    assert r.basis == "first_year_only"
    assert r.gross_receipts == 70_000.0


def test_young_organisation_averages_its_first_two_years():
    r = route_form_variant(
        70_000.0, 5_000.0,
        organization_age_years=2.0,
        prior_year_gross_receipts=(50_000.0, 999_999.0),
    )
    assert r.basis == "average_first_2yr"
    assert r.gross_receipts == 60_000.0


def test_unknown_age_applies_the_strictest_limit_and_asks_for_review():
    """Safe direction -- it can only route to a longer form than required --
    but the assumption is surfaced rather than hidden."""
    r = route_form_variant(
        70_000.0, 5_000.0, prior_year_gross_receipts=(70_000.0, 70_000.0)
    )
    assert r.gross_receipts_limit == ESTABLISHED_ORG_LIMIT
    assert r.age_tier == AgeTier.UNKNOWN
    assert r.requires_review
    assert any("age unknown" in x.lower() for x in r.review_reasons)


def test_age_tier_is_recorded_in_the_decision():
    r = route_form_variant(70_000.0, 5_000.0, organization_age_years=1.0)
    d = r.as_dict()
    assert d["age_tier"] == AgeTier.NEW
    assert d["gross_receipts_990n_limit"] == NEW_ORG_LIMIT


def test_review_band_follows_the_applicable_limit():
    """Proximity is measured against the limit that actually applies, not a
    fixed 50,000."""
    r = route_form_variant(73_000.0, 5_000.0, organization_age_years=1.0)
    assert r.form == FORM_990N
    assert r.requires_review
    assert any("990-N limit" in x for x in r.review_reasons)

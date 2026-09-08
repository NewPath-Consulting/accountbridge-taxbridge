"""Regression tests: the rolling average applies to the 990-N test only.

IRS rule (Form 990-EZ item L; Form 990 instructions, Who Must File):
    990-N   gross receipts *normally* $50,000 or less -- the multi-year average
    990-EZ  gross receipts under $200,000 *for the tax year* and total assets
            under $500,000 at year end -- no averaging
    990     otherwise

The figures below are real cases from data/propublica_harness/results.csv where
the averaged figure and the current-year figure fall on opposite sides of the
$200,000 line; each organization filed the 990-EZ.
"""

import pytest

from app.utils.form_routing import FORM_990, FORM_990EZ, FORM_990N, route_form_variant

ESTABLISHED = 10.0  # years; the 990-N limit is $50,000 and the average covers three years


def route(current, priors, assets, age=ESTABLISHED, **kwargs):
    return route_form_variant(current, assets, organization_age_years=age, prior_year_gross_receipts=tuple(priors), **kwargs)


# 1. The 990-EZ test uses the current year, not the average --------------------------------


@pytest.mark.parametrize(
    "current, priors, assets, average",
    [
        (197_169, (286_083, 262_543), 235_814, 248_598),
        (182_280, (183_725, 330_720), 243_474, 232_242),
        (93_993, (155_953, 454_151), 346_269, 234_699),
    ],
)
def test_ez_eligible_on_current_year_despite_average_over_200k(current, priors, assets, average):
    assert round((current + sum(priors)) / 3) == average  # the figure the old code tested
    result = route(current, priors, assets)
    assert result.form == FORM_990EZ, f"routed to {result.form}; average {average:,} must not govern the 990-EZ test"


def test_ez_decision_clear_of_all_bands_is_not_held():
    # 182,280 is outside the 190,000-210,000 band; assets 243,474 outside 475,000-525,000; three years of history
    result = route(182_280, (183_725, 330_720), 243_474)
    assert result.form == FORM_990EZ
    assert result.requires_review is False


# 2. Which threshold governs when the average is huge and the year is tiny -----------------


def test_average_fails_990n_test_then_current_year_passes_ez_test():
    """Average 888,599 > 50,000: not 990-N. Current year 42,347 < 200,000 with assets 45,974: 990-EZ.

    The averaging rule can only make an organization *eligible* for the 990-N; once
    that test fails, the 990-EZ test is made on the year alone. The organization filed a 990-EZ.
    """
    result = route(42_347, (1_612_074, 1_011_375), 45_974)
    assert result.form == FORM_990EZ
    assert result.form != FORM_990N
    assert result.form != FORM_990


# 3. The 990-N test still uses the average -----------------------------------------------------


def test_990n_test_still_averages():
    # (90,000 + 20,000 + 20,000) / 3 = 43,333 <= 50,000, although the current year alone is 90,000
    result = route(90_000, (20_000, 20_000), 10_000)
    assert result.form == FORM_990N


def test_990n_test_fails_when_average_exceeds_limit_even_if_current_year_is_small():
    # (10,000 + 100,000 + 100,000) / 3 = 70,000 > 50,000 -> not 990-N; current year 10,000 -> 990-EZ
    result = route(10_000, (100_000, 100_000), 20_000)
    assert result.form == FORM_990EZ


# 4. Averaging has not simply been switched off --------------------------------------------


def test_current_year_over_200k_routes_to_990_despite_low_priors():
    # average (250,000 + 60,000 + 55,000) / 3 = 121,667 would have passed the old EZ test
    result = route(250_000, (60_000, 55_000), 100_000)
    assert result.form == FORM_990


def test_assets_at_or_above_500k_route_to_990_regardless_of_receipts():
    result = route(100_000, (90_000, 95_000), 600_000)
    assert result.form == FORM_990


# 5. The review band on the 990-EZ receipts limit measures the current year ---------------


def test_ez_band_does_not_fire_on_the_average():
    # current 401,821 and assets 847,191 are far from every limit; the average 199,187 is inside the band
    result = route(401_821, (101_351, 94_390), 847_191, age=11.6)
    assert result.form == FORM_990
    assert result.requires_review is False


def test_ez_band_fires_on_current_year_near_the_limit():
    # current 198,000 is inside the 190,000-210,000 band; the average 142,667 is not
    result = route(198_000, (120_000, 110_000), 100_000)
    assert result.form == FORM_990EZ
    assert result.requires_review is True


def test_990n_band_still_measures_the_average():
    # average (49,000 + 49,000 + 49,000) / 3 = 49,000 is inside the 47,500-52,500 band
    result = route(49_000, (49_000, 49_000), 10_000)
    assert result.form == FORM_990N
    assert result.requires_review is True

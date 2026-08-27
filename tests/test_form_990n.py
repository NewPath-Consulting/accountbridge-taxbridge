"""Tests for Form 990-N payload assembly.

The payload is built against the contract observed in the Make.com scenario's
call to `/v1/form990n/create`, so the field names here are Tax990's, not ours.

The behaviour these tests exist to pin down is refusal. A 990-N filed by an
organization that is not eligible is treated by the IRS as not filed at all,
so the builder must decline rather than produce something plausible.
"""

import pytest

from app.utils.form_990n import (
    SANDBOX_PLACEHOLDER_PHONE,
    build_form_990n_payload,
    normalise_ein,
)
from app.utils.form_990n import filing_window
from app.utils.form_routing import route_form_variant

ESTABLISHED = 10.0

# The most recent year Tax990 will accept. Derived rather than hard-coded, so
# these tests do not start failing on 1 January.
FILEABLE_YEAR = str(filing_window()[1])


@pytest.fixture
def content() -> dict:
    return {
        "organizationInformation": {
            "legalName": "Kansas City Woodworkers Guild",
            "dbaNames": ["KCWG"],
            "ein": "43-1633425",
            "address": {
                "street": "3189 Mercier St",
                "city": "Kansas City",
                "state": "MO",
                "zip": "64111-2432",
            },
            "telephone": "(816) 761-0075",
            "website": "https://kcwg.org",
            "principalOfficer": {"name": "Jane Doe", "title": "President"},
        },
        # Inside the filing window; a year cannot be filed before it ends.
        "organization_summary": {"tax_year": FILEABLE_YEAR, "gross_receipts": 10605.77},
    }


@pytest.fixture
def eligible_routing():
    return route_form_variant(
        10_605.77, 23_436.29,
        organization_age_years=ESTABLISHED,
        prior_year_gross_receipts=(10_000.0, 11_000.0),
    )


# --- the happy path -------------------------------------------------------

def test_payload_is_built_for_an_eligible_organisation(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing)
    assert result.is_submittable
    assert result.blocking_errors == []


def test_payload_matches_the_tax990_contract(content, eligible_routing):
    """Field names are Tax990's, taken from the observed create call."""
    result = build_form_990n_payload(content, eligible_routing)
    record = result.payload["Form990NRecords"][0]
    assert set(record) == {"Business", "Form990N"}
    business = record["Business"]
    assert business["BusinessNm"] == "Kansas City Woodworkers Guild"
    assert business["EIN"] == "431633425"
    assert business["USAddress"]["ZipCd"] == "64111"
    form = record["Form990N"]
    assert form["TaxYr"] == FILEABLE_YEAR
    assert form["TaxPeriodBeginDt"] == f"{FILEABLE_YEAR}-01-01"
    assert form["TaxPeriodEndDt"] == f"{FILEABLE_YEAR}-12-31"
    assert form["PrincipalOfficer"]["OfficerNm"] == "Jane Doe"


def test_ein_is_stripped_of_formatting():
    assert normalise_ein("43-1633425") == "431633425"
    assert normalise_ein("43 1633425") == "431633425"
    assert normalise_ein(None) == ""


def test_zip_is_truncated_to_five_digits(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload["Form990NRecords"][0]["Business"]["USAddress"]["ZipCd"] == "64111"


def test_dba_name_is_carried(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload["Form990NRecords"][0]["Business"]["DBANm"] == "KCWG"


def test_absent_dba_is_null_not_empty_string(content, eligible_routing):
    content["organizationInformation"]["dbaNames"] = []
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload["Form990NRecords"][0]["Business"]["DBANm"] is None


# --- element 8: termination ----------------------------------------------

def test_termination_defaults_to_false(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload["Form990NRecords"][0]["Form990N"]["IsOrganizationTerminated"] is False


def test_termination_can_be_declared(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing, is_terminated=True)
    assert result.payload["Form990NRecords"][0]["Form990N"]["IsOrganizationTerminated"] is True


# --- element 7: the declaration that must not be assumed ------------------

def test_ineligible_organisation_produces_no_payload(content):
    """The Make.com scenario hardcodes IsGrossReceiptsUnder50K true on every
    submission. Here an organization over the threshold is refused."""
    routing = route_form_variant(
        250_000.0, 100_000.0,
        organization_age_years=ESTABLISHED,
        prior_year_gross_receipts=(250_000.0, 250_000.0),
    )
    result = build_form_990n_payload(content, routing)
    assert result.payload is None
    assert not result.is_submittable
    assert any("not filed" in e for e in result.blocking_errors)


def test_ez_routed_organisation_is_refused(content):
    routing = route_form_variant(
        120_000.0, 200_000.0,
        organization_age_years=ESTABLISHED,
        prior_year_gross_receipts=(120_000.0, 120_000.0),
    )
    result = build_form_990n_payload(content, routing)
    assert result.payload is None


def test_declaration_records_the_basis_it_rests_on(content, eligible_routing):
    """The figure attested is the one eligibility was tested on -- the rolling
    average of 10,605.77, 10,000 and 11,000 -- not the current year alone.
    That is what 'normally' means, and it is what the declaration must rest on."""
    result = build_form_990n_payload(content, eligible_routing)
    note = next(w for w in result.warnings if w.startswith("GROSS_RECEIPTS_DECLARATION"))
    assert "10,535.26" in note
    assert "50,000" in note
    assert "rolling_average_3yr" in note


def test_declaration_reports_the_current_year_when_no_history_exists(content):
    routing = route_form_variant(
        10_605.77, 23_436.29, organization_age_years=ESTABLISHED
    )
    result = build_form_990n_payload(content, routing)
    note = next(w for w in result.warnings if w.startswith("GROSS_RECEIPTS_DECLARATION"))
    assert "10,605.77" in note
    assert "current_year_only" in note


def test_review_flag_is_carried_into_the_payload_warnings(content):
    """An organization within 5% of the limit still produces a payload, but
    the reason it needs a preparer's eye travels with it."""
    routing = route_form_variant(
        49_000.0, 10_000.0,
        organization_age_years=ESTABLISHED,
        prior_year_gross_receipts=(49_000.0, 49_000.0),
    )
    result = build_form_990n_payload(content, routing)
    assert result.is_submittable
    assert any(w.startswith("ROUTING_REQUIRES_REVIEW") for w in result.warnings)


# --- required fields ------------------------------------------------------

@pytest.mark.parametrize(
    "path,message_fragment",
    [
        (("organizationInformation", "legalName"), "Legal name"),
        (("organizationInformation", "ein"), "EIN"),
    ],
)
def test_missing_required_field_blocks(content, eligible_routing, path, message_fragment):
    node = content
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = ""
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None
    assert any(message_fragment in e for e in result.blocking_errors)


def test_missing_officer_blocks(content, eligible_routing):
    content["organizationInformation"]["principalOfficer"] = {}
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None
    assert any("Principal officer" in e for e in result.blocking_errors)


def test_incomplete_address_blocks(content, eligible_routing):
    content["organizationInformation"]["address"]["city"] = ""
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None
    assert any("city" in e for e in result.blocking_errors)


def test_malformed_ein_blocks(content, eligible_routing):
    content["organizationInformation"]["ein"] = "12345"
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None
    assert any("nine digits" in e for e in result.blocking_errors)


# --- the placeholder phone -----------------------------------------------

def test_missing_phone_blocks_by_default(content, eligible_routing):
    content["organizationInformation"]["telephone"] = ""
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None
    assert any("ten-digit phone" in e for e in result.blocking_errors)


def test_placeholder_phone_is_opt_in_and_warned(content, eligible_routing):
    """The sandbox scenario substitutes a reserved test number silently. Here
    it must be asked for, and it is recorded when used."""
    content["organizationInformation"]["telephone"] = ""
    result = build_form_990n_payload(
        content, eligible_routing, allow_placeholder_phone=True
    )
    assert result.is_submittable
    phone = result.payload["Form990NRecords"][0]["Business"]["Phone"]
    assert phone == SANDBOX_PLACEHOLDER_PHONE
    assert any("must not reach a live filing" in w for w in result.warnings)


def test_phone_formatting_is_stripped(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload["Form990NRecords"][0]["Business"]["Phone"] == "8167610075"


# --- officer address ------------------------------------------------------

def test_officer_address_defaults_to_the_organisation_address(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing)
    officer = result.payload["Form990NRecords"][0]["Form990N"]["PrincipalOfficer"]
    assert officer["USAddress"]["Address1"] == "3189 Mercier St"


def test_officer_address_is_used_when_supplied(content, eligible_routing):
    content["organizationInformation"]["principalOfficer"]["address"] = {
        "street": "1 Elsewhere Ave", "city": "Topeka", "state": "KS", "zip": "66603",
    }
    result = build_form_990n_payload(content, eligible_routing)
    officer = result.payload["Form990NRecords"][0]["Form990N"]["PrincipalOfficer"]
    assert officer["USAddress"]["Address1"] == "1 Elsewhere Ave"
    assert officer["USAddress"]["City"] == "Topeka"


# --- reporting shape ------------------------------------------------------

def test_as_dict_is_serialisable(content, eligible_routing):
    result = build_form_990n_payload(content, eligible_routing).as_dict()
    assert result["is_submittable"] is True
    assert isinstance(result["warnings"], list)
    assert isinstance(result["blocking_errors"], list)


# --- the filing window ----------------------------------------------------

def test_the_window_is_three_years_ending_last_year():
    """A year cannot be filed before it has ended, so the newest available is
    the one before the current one. Probing Tax990's sandbox in August 2026
    confirmed this: 2023 to 2025 accepted, 2022 and 2026 refused."""
    from datetime import date
    earliest, latest = filing_window(date(2026, 8, 27))
    assert (earliest, latest) == (2023, 2025)


def test_the_current_year_cannot_be_filed(content, eligible_routing):
    from datetime import date
    content["organization_summary"]["tax_year"] = str(date.today().year)
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None
    assert any("outside the filing window" in e for e in result.blocking_errors)


def test_a_year_too_old_cannot_be_filed(content, eligible_routing):
    earliest, _ = filing_window()
    content["organization_summary"]["tax_year"] = str(earliest - 1)
    result = build_form_990n_payload(content, eligible_routing)
    assert result.payload is None


def test_the_window_boundaries_are_accepted(content, eligible_routing):
    earliest, latest = filing_window()
    for year in (str(earliest), str(latest)):
        content["organization_summary"]["tax_year"] = year
        result = build_form_990n_payload(content, eligible_routing)
        assert result.is_submittable, f"{year} should be fileable"


def test_the_rejection_names_the_years_available(content, eligible_routing):
    """A preparer should be told what they can file, not only what they cannot."""
    earliest, latest = filing_window()
    content["organization_summary"]["tax_year"] = "2026"
    result = build_form_990n_payload(content, eligible_routing)
    message = next(e for e in result.blocking_errors if "filing window" in e)
    assert str(earliest) in message and str(latest) in message

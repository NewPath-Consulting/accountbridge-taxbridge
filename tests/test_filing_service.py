"""Tests for filing preparation.

Preparing a filing is the deterministic half of the pipeline: ledger to
payload with no model call anywhere. These tests pin down the two things that
matter about it -- that the routing decision is made from computed figures,
and that the flow degrades honestly when a source is missing rather than
guessing.
"""

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from app.services.filing_service import FilingPreparationService
from app.utils.form_990n import filing_window

# The most recent tax year Tax990 will accept. Derived rather than fixed, so
# these tests do not start failing on 1 January.
FILEABLE_YEAR = filing_window()[1]

FIXTURES = Path(__file__).parent / "fixtures"


def _quickbooks_returning(report: dict):
    """A stand-in for the QuickBooks adapter.

    Injected through the service's client factory rather than patched into
    sys.modules, so nothing leaks into other tests.
    """

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def get_profit_and_loss(self, realm_id, start_date, end_date):
            return report

    return _Client


@pytest.fixture(scope="module")
def pl_report() -> dict:
    return json.loads((FIXTURES / "qb_pl_2026.json").read_text())


@pytest.fixture
def service(pl_report):
    return FilingPreparationService(_quickbooks_returning(pl_report))


@pytest.fixture
def organization() -> dict:
    return {
        "legalName": "Kansas City Woodworkers Guild",
        "ein": "43-1633425",
        "address": {"street": "3189 Mercier St", "city": "Kansas City",
                    "state": "MO", "zip": "64111"},
        "telephone": "8167610075",
        "website": "https://kcwg.org",
        "principalOfficer": {"name": "Jane Doe", "title": "President"},
    }


def _prepare(service, **kwargs):
    defaults = dict(
        quickbooks_realm_id="9341457668846945",
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    defaults.update(kwargs)
    return asyncio.run(service.prepare(**defaults))


# --- the stages -----------------------------------------------------------

def test_all_five_stages_are_reported(service, organization):
    from app.services.filing_service import STAGE_ORDER
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    assert [s["stage"] for s in result["stages"]] == list(STAGE_ORDER)


def test_source_data_lists_the_accounts_read(service, organization):
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    stage = result["stages"][0]
    assert stage["status"] == "ok"
    assert len(stage["detail"]["accounts"]) == 11


def test_totals_reconcile_to_quickbooks(service, organization):
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    detail = result["stages"][1]["detail"]
    assert detail["reconciles"] is True
    assert detail["income"] == 10200.77
    assert detail["walked_sum"] == detail["income"]


def test_gross_receipts_add_back_is_shown(service, organization):
    """The figure the threshold is tested against is not total revenue, and
    the difference is published rather than buried."""
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    detail = result["stages"][2]["detail"]
    assert detail["total_revenue"] == 10200.77
    assert detail["cost_of_goods_sold_added_back"] == 405.00
    assert detail["gross_receipts"] == 10605.77


def test_routing_uses_the_computed_figure(service, organization):
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        prior_year_gross_receipts=[10200.0, 9800.0],
    )
    routing = result["stages"][3]["detail"]
    assert result["routed_form_variant"] == "990-N"
    assert routing["gross_receipts_basis"] == "rolling_average_3yr"


def test_990n_payload_is_assembled(service, organization):
    """The ledger is a 2026 period but a return cannot be filed for a year
    that has not ended, so the payload is dated to the newest fileable year."""
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        prior_year_gross_receipts=[10200.0, 9800.0],
        end_date=f"{FILEABLE_YEAR}-12-31",
    )
    assert result["status"] == "prepared"
    assert result["filing_available"] is True
    payload = result["payload"]["Form990NRecords"][0]
    assert payload["Business"]["EIN"] == "431633425"
    assert payload["Form990N"]["IsGrossReceiptsUnder50K"] is True


def test_no_model_call_is_made(service, organization):
    """The whole path is deterministic. If a model call is ever introduced
    this test will not catch it directly, but the timing will: a model call
    takes seconds, and this must not."""
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    assert result["processing_time"] < 1.0


# --- degrading honestly ---------------------------------------------------

def test_unknown_age_is_flagged_not_assumed(service, organization):
    result = _prepare(service, organization=organization)
    routing = result["stages"][3]["detail"]
    assert routing["requires_human_review"] is True
    assert any("age unknown" in r.lower() for r in routing["review_reasons"])


def test_missing_officer_blocks_the_payload(service, organization):
    organization["principalOfficer"] = {}
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    stage = result["stages"][-1]
    assert stage["status"] == "blocked"
    assert any("Principal officer" in e for e in stage["detail"]["blocking_errors"])


def test_empty_ledger_stops_at_the_first_stage():
    empty = FilingPreparationService(_quickbooks_returning({"Rows": {"Row": []}}))
    result = _prepare(empty)
    assert result["status"] == "blocked"
    assert result["stages"][0]["status"] == "failed"
    assert len(result["stages"]) == 1


def test_ez_without_a_reports_run_is_declared_not_guessed(pl_report, organization):
    """The 990-EZ needs classified revenue detail. Without a reports run the
    flow says so rather than emitting an empty form."""
    scaled = json.loads(json.dumps(pl_report))

    def scale(node, factor):
        for row in node.get("Row", []):
            cols = row.get("ColData")
            if cols and len(cols) > 1:
                try:
                    cols[1]["value"] = f"{float(cols[1]['value']) * factor:.2f}"
                except (TypeError, ValueError):
                    pass
            for block in ("Header", "Summary"):
                data = (row.get(block) or {}).get("ColData")
                if data and len(data) > 1:
                    try:
                        data[1]["value"] = f"{float(data[1]['value']) * factor:.2f}"
                    except (TypeError, ValueError):
                        pass
            if "Rows" in row:
                scale(row["Rows"], factor)

    scale(scaled["Rows"], 14.0)
    result = _prepare(
        FilingPreparationService(_quickbooks_returning(scaled)),
        organization=organization,
        organization_age_years=20.0,
    )
    stage = result["stages"][-1]
    assert stage["status"] == "blocked"
    assert result["filing_available"] is False
    assert "reports run" in stage["summary"]


# --- the organization lookup ---------------------------------------------

class _StubProPublica:
    def __init__(self, payload):
        self._payload = payload

    def organization(self, ein):
        if self._payload is None:
            raise RuntimeError("not found")
        return self._payload


@pytest.fixture
def propublica_payload() -> dict:
    return json.loads((FIXTURES / "propublica_010165097.json").read_text())


def test_lookup_returns_identity(propublica_payload):
    """Asserted against the fixture's own values, so refreshing it from
    ProPublica does not break the test."""
    from app.utils.organization_lookup import lookup_organization
    org = propublica_payload["organization"]
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload),
        as_of=date(2026, 8, 1),
    )
    assert result.found is True
    assert result.legal_name == org["name"].strip()
    assert result.address["city"] == org["city"].strip()
    assert result.address["zip"] == str(org["zipcode"])[:5]
    assert len(result.address["zip"]) == 5, "Tax990 takes a five-digit ZIP"


def test_lookup_derives_age_from_the_ruling_date(propublica_payload):
    """Age decides which 990-N threshold applies, so it is not optional.

    Asserted against the fixture's own ruling date rather than a literal, so
    the test does not break when the fixture is refreshed from ProPublica.
    """
    from app.utils.organization_lookup import lookup_organization
    ruling = propublica_payload["organization"]["ruling_date"]
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload),
        as_of=date(2026, 8, 1),
    )
    assert result.ruling_date == str(ruling)

    # Age is measured to the end of the tax period, not to an arbitrary date,
    # because that is when the filing threshold is applied.
    from app.utils.propublica_harness import age_years_at
    expected = age_years_at(ruling, 202608)
    assert abs(result.age_years - expected) < 0.01
    assert result.age_years > 3, "an organization ruled decades ago is established"


def test_lookup_returns_prior_year_receipts(propublica_payload):
    """History feeds the rolling average, capped so that filings too old to
    bear on a current decision are left out."""
    from app.utils.organization_lookup import lookup_organization, MAX_HISTORY_YEARS
    available = len(propublica_payload["filings_with_data"])
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload),
    )
    assert len(result.filings) == min(available, MAX_HISTORY_YEARS)
    assert len(result.prior_year_gross_receipts) == len(result.filings)
    years = [int(f["tax_year"]) for f in result.filings]
    assert years == sorted(years, reverse=True), "most recent first"


def test_lookup_always_notes_the_officer_gap(propublica_payload):
    from app.utils.organization_lookup import lookup_organization
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload),
    )
    assert any("Principal officer" in n for n in result.notes)


def test_lookup_failure_does_not_raise():
    """A miss must leave the preparer able to type the details in."""
    from app.utils.organization_lookup import lookup_organization
    result = lookup_organization("01-0165097", client=_StubProPublica(None))
    assert result.found is False
    assert result.ein == "01-0165097"
    assert any("manually" in n for n in result.notes)


def test_malformed_ein_is_rejected_before_any_request():
    from app.utils.organization_lookup import lookup_organization
    result = lookup_organization("12345")
    assert result.found is False
    assert any("nine digits" in n for n in result.notes)


def test_missing_ruling_date_is_flagged(propublica_payload):
    propublica_payload["organization"].pop("ruling_date")
    from app.utils.organization_lookup import lookup_organization
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload),
    )
    assert result.age_years is None
    assert any("strictest" in n for n in result.notes)


def test_no_filings_is_flagged(propublica_payload):
    propublica_payload["filings_with_data"] = []
    from app.utils.organization_lookup import lookup_organization
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload),
    )
    assert result.prior_year_gross_receipts == []
    assert any("this year alone" in n for n in result.notes)


# --- guarding against mismatched sources ---------------------------------

def test_receipts_far_below_the_history_are_flagged(service, organization):
    """The likeliest cause is that the organization looked up and the ledger
    being read are not the same one. Identity comes from an EIN the preparer
    types; the figures come from whichever QuickBooks company is connected,
    and nothing forces them to agree."""
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        prior_year_gross_receipts=[900_000.0, 850_000.0, 880_000.0],
    )
    routing = result["stages"][3]["detail"]
    assert routing["requires_human_review"] is True
    assert any("same organization" in r for r in routing["review_reasons"])


def test_receipts_far_above_the_history_are_flagged(service, organization):
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        prior_year_gross_receipts=[500.0, 600.0],
    )
    routing = result["stages"][3]["detail"]
    assert any("same organization" in r for r in routing["review_reasons"])


def test_receipts_in_line_with_history_are_not_flagged(service, organization):
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        prior_year_gross_receipts=[10_400.0, 9_900.0],
    )
    routing = result["stages"][3]["detail"]
    assert not any("same organization" in r for r in routing["review_reasons"])


def test_no_history_cannot_diverge(service, organization):
    """With nothing to compare against, the check must stay silent rather
    than guess."""
    result = _prepare(service, organization=organization, organization_age_years=48.0)
    routing = result["stages"][3]["detail"]
    assert not any("same organization" in r for r in routing["review_reasons"])


def test_divergence_names_both_figures(service, organization):
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        prior_year_gross_receipts=[900_000.0],
    )
    reason = next(
        r for r in result["stages"][3]["detail"]["review_reasons"]
        if "same organization" in r
    )
    assert "10,605.77" in reason
    assert "900,000.00" in reason


def test_an_explicit_tax_year_overrides_the_report(service, organization, pl_report):
    """A prior reports run carries the year of its accounting period. The
    return is often filed for a different year -- the current one never can
    be -- so an explicit choice must win rather than defer."""
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        end_date="2026-12-31",
        tax_year=str(FILEABLE_YEAR),
        report_content={"organization_summary": {"tax_year": "2026"}},
    )
    form = result["payload"]["Form990NRecords"][0]["Form990N"]
    assert form["TaxYr"] == str(FILEABLE_YEAR)
    assert form["TaxPeriodBeginDt"] == f"{FILEABLE_YEAR}-01-01"


def test_without_an_explicit_year_the_period_is_used(service, organization):
    result = _prepare(
        service, organization=organization, organization_age_years=48.0,
        end_date=f"{FILEABLE_YEAR}-12-31",
    )
    assert result["payload"]["Form990NRecords"][0]["Form990N"]["TaxYr"] == str(FILEABLE_YEAR)


def test_lookup_carries_the_subsection_code(propublica_payload):
    """A model asked to fill this in answers 501(c)(3), because most
    nonprofits are charities. A business league is 501(c)(6), and Part IV
    line 5 asks specifically about membership dues for c4, c5 and c6
    organizations -- which for a trade association is the largest revenue
    line on the return."""
    from app.utils.organization_lookup import lookup_organization
    propublica_payload["organization"]["subsection_code"] = 6
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload)
    )
    assert result.tax_exempt_status == "501(c)(6)"
    assert result.as_dict()["tax_exempt_status"] == "501(c)(6)"


def test_an_absent_subsection_is_left_empty(propublica_payload):
    """Empty is better than a guess. Downstream can see it is missing."""
    from app.utils.organization_lookup import lookup_organization
    propublica_payload["organization"].pop("subsection_code", None)
    result = lookup_organization(
        "01-0165097", client=_StubProPublica(propublica_payload)
    )
    assert result.tax_exempt_status == ""

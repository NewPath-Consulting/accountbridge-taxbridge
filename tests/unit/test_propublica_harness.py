"""Tests for app.utils.propublica_client and app.utils.propublica_harness.

The fixture is the verbatim API response for EIN 01-0165097 (Maine Grocers &
Food Producers Association), fetched 2026-08-24. It has thirteen extracted
filings, 2011 through 2023, eleven Form 990-EZ and two Form 990. In both Form
990 years total revenue was under $200,000 and gross receipts was over
$200,000, so the form actually filed follows the IRS gross receipts definition,
not total revenue.
"""

import json
from enum import Enum
from pathlib import Path

import pytest

from app.utils import propublica_harness as h
from app.utils.propublica_client import ProPublicaClient

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "propublica_010165097.json"


@pytest.fixture(scope="module")
def org_json():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records(org_json):
    return build_records_by_period(org_json)


def build_records_by_period(org_json):
    report = h.build_records(org_json)
    return {r.tax_prd: r for r in report.records}


# ---- Gross receipts -----------------------------------------------------------------


def test_form_990_gross_receipts_adds_back_direct_expenses(records):
    r = records[202312]
    assert r.form_filed == h.FORM_990
    assert r.total_revenue == 196_226
    assert r.gross_receipts == 205_226  # 196,226 + 9,000 direct fundraising expenses (line 8b)
    assert r.gross_receipts_addbacks == 9_000


def test_form_990_gross_receipts_crosses_threshold_where_total_revenue_does_not(records):
    for period in (202312, 201312):
        r = records[period]
        assert r.total_revenue < h.EZ_GROSS_RECEIPTS_LIMIT
        assert r.gross_receipts >= h.EZ_GROSS_RECEIPTS_LIMIT
        assert r.form_filed == h.FORM_990


def test_form_990ez_gross_receipts_uses_item_l(records):
    r = records[202212]
    assert r.form_filed == h.FORM_990EZ
    assert r.total_revenue == 154_216  # line 9
    assert r.gross_receipts == 163_579  # + 9,363 line 6c direct expenses


def test_gross_receipts_990_handles_all_addback_lines():
    filing = {
        "formtype": 0,
        "totrevenue": 100,
        "rntlexpnsreal": 1,
        "rntlexpnsprsnl": 2,
        "cstbasisecur": 3,
        "cstbasisothr": 4,
        "lessdirfndrsng": 5,
        "lessdirgaming": 6,
        "lesscstofgoods": 7,
    }
    assert h.gross_receipts(filing) == 128


def test_gross_receipts_990ez_handles_all_addback_lines_and_nulls():
    filing = {"formtype": 1, "totrevnue": 100, "basisalesexpnsothr": None, "direxpns": 5, "costgoodsold": 7}
    assert h.gross_receipts(filing) == 112


def test_gross_receipts_missing_total_revenue_is_none():
    assert h.gross_receipts({"formtype": 0}) is None
    assert h.gross_receipts({"formtype": 1}) is None


def test_gross_receipts_990pf_is_none():
    assert h.gross_receipts({"formtype": 2, "totrevenue": 100}) is None


# ---- Dataset construction ----------------------------------------------------------


def test_build_records_counts_and_labels(org_json):
    report = h.build_records(org_json)
    assert len(report.records) == 13
    assert report.skipped_pf == 0
    assert report.skipped_missing_data == 0
    forms = [r.form_filed for r in report.records]
    assert forms.count(h.FORM_990) == 2
    assert forms.count(h.FORM_990EZ) == 11
    assert [r.tax_prd for r in report.records] == sorted((r.tax_prd for r in report.records), reverse=True)


def test_build_records_skips_pf_and_missing_data():
    org = {
        "organization": {"ein": 1, "name": "X", "ruling_date": "2000-01-01"},
        "filings_with_data": [
            {"tax_prd": 202312, "tax_prd_yr": 2023, "formtype": 2, "totrevenue": 5},
            {"tax_prd": 202212, "tax_prd_yr": 2022, "formtype": 0},
            {"tax_prd": 202112, "tax_prd_yr": 2021, "formtype": 1, "totrevnue": 10, "totassetsend": 3},
        ],
    }
    report = h.build_records(org)
    assert report.skipped_pf == 1
    assert report.skipped_missing_data == 1
    assert [r.tax_prd for r in report.records] == [202112]


def test_age_from_ruling_date(records):
    r = records[202312]
    assert r.ruling_date == "1983-08-01"
    assert r.age_years == pytest.approx(40.4, abs=0.05)


def test_age_unknown_without_ruling_date():
    assert h.age_years_at(None, 202312) is None
    assert h.age_years_at("", 202312) is None


def test_tax_period_end_handles_fiscal_years():
    assert h.tax_period_end(202306).isoformat() == "2023-06-30"
    assert h.tax_period_end(202402).isoformat() == "2024-02-29"
    assert h.previous_period(202306) == 202206


def test_history_is_three_consecutive_periods_most_recent_first(records):
    r = records[202312]
    assert r.history == (205_226, 163_579, 167_944)
    assert r.history_complete


def test_history_incomplete_at_start_of_data(records):
    assert records[201112].history == (188_753,)
    assert not records[201112].history_complete
    assert records[201212].history == (181_081, 188_753)
    assert not records[201212].history_complete


def test_history_breaks_on_gap():
    org = {
        "organization": {"ein": 1, "name": "X"},
        "filings_with_data": [
            {"tax_prd": 202312, "tax_prd_yr": 2023, "formtype": 1, "totrevnue": 30, "totassetsend": 1},
            {"tax_prd": 202112, "tax_prd_yr": 2021, "formtype": 1, "totrevnue": 10, "totassetsend": 1},
            {"tax_prd": 202012, "tax_prd_yr": 2020, "formtype": 1, "totrevnue": 5, "totassetsend": 1},
        ],
    }
    by_period = build_records_by_period(org)
    assert by_period[202312].history == (30,)
    assert by_period[202112].history == (10, 5)


def test_bmf_fields_carried(records):
    r = records[202312]
    assert r.filing_requirement_code == 1
    assert r.subsection_code == 6
    assert r.total_assets_end == 132_752


# ---- Prediction normalization ---------------------------------------------------


class Variant(Enum):
    N = "990-N"
    EZ = "990-EZ"
    FULL = "990"


@pytest.mark.parametrize(
    "raw, variant, review",
    [
        ("990-N", h.FORM_990N, False),
        ("990N", h.FORM_990N, False),
        ("990-EZ", h.FORM_990EZ, False),
        ("990ez", h.FORM_990EZ, False),
        ("990", h.FORM_990, False),
        ("FULL_990", h.FORM_990, False),
        ("REVIEW", None, True),
        (Variant.EZ, h.FORM_990EZ, False),
        ({"variant": "990-EZ", "review": False}, h.FORM_990EZ, False),
        ({"form_variant": "990", "needs_review": True, "reason": "within 5%"}, h.FORM_990, True),
        ({"variant": Variant.N}, h.FORM_990N, False),
        (None, None, False),
    ],
)
def test_normalize_prediction_shapes(raw, variant, review):
    p = h.normalize_prediction(raw)
    assert p.variant == variant
    assert p.review == review


def test_normalize_prediction_object_attributes():
    class Result:
        variant = "990-N"
        hold_for_review = True
        reasons = ["single year of data", "age under 3"]

    p = h.normalize_prediction(Result())
    assert p.variant == h.FORM_990N
    assert p.review
    assert p.reason == "single year of data | age under 3"


# ---- Router adapter -----------------------------------------------------------------


def test_adapter_binds_by_parameter_name(records):
    seen = {}

    def route_form_variant(gross_receipts, total_assets, age_years):
        seen.update(gross_receipts=gross_receipts, total_assets=total_assets, age_years=age_years)
        return "990"

    router = h.make_router_adapter(route_form_variant)
    assert router(records[202312]).variant == h.FORM_990
    assert seen == {"gross_receipts": 205_226, "total_assets": 132_752, "age_years": records[202312].age_years}


def test_adapter_passes_history_and_ignores_defaults(records):
    seen = {}

    def route_form_variant(gross_receipts_history, total_assets, age, margin=0.05):
        seen.update(history=gross_receipts_history, margin=margin)
        return {"variant": "990-EZ"}

    router = h.make_router_adapter(route_form_variant)
    router(records[202212])
    assert seen["history"] == (163_579, 167_944, 161_946)
    assert seen["margin"] == 0.05


def test_adapter_rejects_unknown_required_parameter():
    def route_form_variant(gross_receipts, quickbooks_ledger):
        return "990"

    with pytest.raises(TypeError, match="quickbooks_ledger"):
        h.make_router_adapter(route_form_variant)


# ---- Regression: the parameter-binding bug that held all 891 filings for review ----
#
# route_form_variant's real signature is
#     route_form_variant(gross_receipts, total_assets, organization_age_years=None, prior_year_gross_receipts=())
# The adapter used to recognize neither keyword, both have defaults, so both were silently
# omitted: age became unknown, the router applied its strictest limit and held every record.


def real_signature_stand_in(gross_receipts, total_assets, organization_age_years=None, prior_year_gross_receipts=()):
    """Mimics the project router's interface and its hold-when-age-unknown rule."""

    class Decision:
        pass

    d = Decision()
    d.form = "990" if (gross_receipts >= 200_000 or (total_assets or 0) >= 500_000) else ("990-N" if gross_receipts <= 50_000 else "990-EZ")
    d.reason = f"Gross receipts {gross_receipts:,.2f}"
    d.review_reasons = []
    if organization_age_years is None:
        d.review_reasons.append("Organization age unknown, so the strictest 990-N limit (50,000) was applied.")
    if len(prior_year_gross_receipts) < 2:
        d.review_reasons.append("Fewer than three years of gross receipts; the three-year average rests on a single year.")
    d.requires_review = bool(d.review_reasons)
    d.age_tier = "unknown" if organization_age_years is None else "established_3yr_or_more"
    d.received = dict(age=organization_age_years, priors=prior_year_gross_receipts)
    return d


def test_adapter_passes_organization_age_years(records):
    seen = {}

    def route_form_variant(gross_receipts, total_assets, organization_age_years=None, prior_year_gross_receipts=()):
        seen["organization_age_years"] = organization_age_years
        return "990"

    h.make_router_adapter(route_form_variant)(records[202312])
    assert seen["organization_age_years"] == records[202312].age_years
    assert seen["organization_age_years"] is not None


def test_adapter_passes_prior_years_only_not_the_current_year(records):
    seen = {}

    def route_form_variant(gross_receipts, total_assets, organization_age_years=None, prior_year_gross_receipts=()):
        seen["gross_receipts"] = gross_receipts
        seen["prior_year_gross_receipts"] = prior_year_gross_receipts
        return "990"

    record = records[202312]
    h.make_router_adapter(route_form_variant)(record)
    assert record.history == (205_226, 163_579, 167_944)
    assert seen["gross_receipts"] == 205_226
    assert seen["prior_year_gross_receipts"] == record.history[1:] == (163_579, 167_944)
    assert seen["prior_year_gross_receipts"] != record.history


def test_adapter_prior_years_empty_when_only_one_year_exists(records):
    seen = {}

    def route_form_variant(gross_receipts, total_assets, organization_age_years=None, prior_year_gross_receipts=()):
        seen["priors"] = prior_year_gross_receipts
        return "990-EZ"

    h.make_router_adapter(route_form_variant)(records[201112])
    assert seen["priors"] == ()


def test_adapter_lists_defaulted_parameters_it_cannot_supply():
    def route_form_variant(gross_receipts, total_assets, fiscal_year_end_month=12, organization_age_years=None):
        return "990"

    router = h.make_router_adapter(route_form_variant)
    assert router.bound_parameters == ("gross_receipts", "total_assets", "organization_age_years")
    assert router.unbound_parameters == ("fiscal_year_end_month",)


def test_adapter_treats_review_band_as_configuration_not_as_unbound():
    """The project router takes review_band=0.05; it configures the rule and stays at its default."""

    def route_form_variant(gross_receipts, total_assets, organization_age_years=None, prior_year_gross_receipts=(), review_band=0.05):
        return "990"

    router = h.make_router_adapter(route_form_variant)
    assert router.unbound_parameters == ()
    assert router.configuration_parameters == ("review_band",)
    assert "review_band" not in router.bound_parameters


def test_stand_in_router_is_not_held_when_age_and_history_are_supplied(records):
    router = h.make_router_adapter(real_signature_stand_in)
    assert router.unbound_parameters == ()
    prediction = router(records[202312])
    assert prediction.variant == h.FORM_990
    assert prediction.review is False
    assert "age unknown" not in (prediction.reason or "")


def test_stand_in_router_holds_when_age_is_missing_and_the_harness_reports_it(records):
    """The failure mode itself, reproduced: no age supplied -> held, and the review reason is surfaced."""
    raw = real_signature_stand_in(205_226, 132_752)  # what the old adapter effectively did
    prediction = h.normalize_prediction(raw)
    assert prediction.variant == h.FORM_990
    assert prediction.review is True
    assert "age unknown" in prediction.reason
    assert "single year" in prediction.reason


def test_fixture_is_fully_decided_with_the_real_signature(org_json):
    results = h.evaluate_organization(org_json, h.make_router_adapter(real_signature_stand_in))
    summary = h.summarize(results)
    assert summary["outcomes"].get(h.REVIEW, 0) == 2  # only the two oldest filings lack two prior years
    assert summary["decided"] == 11
    assert summary["strict_accuracy"] == 1.0


def test_review_flag_reads_only_real_flags():
    assert h.review_flag(True) is True
    assert h.review_flag(False) is False
    assert h.review_flag(None) is None
    assert h.review_flag("not required") is False
    assert h.review_flag("required") is True
    assert h.review_flag("Total assets above threshold") is None  # descriptive text is not a flag
    assert h.review_flag([]) is False
    assert h.review_flag(["single year"]) is True
    assert h.review_flag(lambda: True) is None  # a method is not a flag
    assert h.review_flag(object()) is None  # an arbitrary object is not a flag


def test_normalize_prediction_does_not_hold_on_non_flag_values():
    class Decision:
        form = "990"
        reason = "Total assets 600,000.00 is at or above 500,000, which requires the full return regardless of gross receipts."
        review = object()  # an object, not a flag
        requires_review = False
        review_reasons = []

        def hold(self):
            return True

    p = h.normalize_prediction(Decision())
    assert p.variant == h.FORM_990
    assert p.review is False
    assert p.reason.startswith("Total assets 600,000.00")


def test_normalize_prediction_word_boundary_for_hold():
    # "threshold" contains "hold"; a decision string mentioning a threshold is not a hold
    p = h.normalize_prediction("990 (total assets at or above the threshold)")
    assert p.variant == h.FORM_990
    assert p.review is False
    assert h.normalize_prediction("HOLD for review").review is True


@pytest.mark.parametrize(
    "gross_receipts, total_assets, expected",
    [
        (1_000_000.0, 2_000_000.0, h.FORM_990),
        (120_000.0, 150_000.0, h.FORM_990EZ),
    ],
)
def test_project_router_decides_when_clear_of_all_thresholds(gross_receipts, total_assets, expected):
    """Runs only where the project router exists. Known age, three years of history, far from every threshold."""
    form_routing = pytest.importorskip("app.utils.form_routing")
    router = h.make_router_adapter(form_routing.route_form_variant)
    assert {"organization_age_years", "prior_year_gross_receipts"} <= set(router.bound_parameters), router.signature
    assert router.unbound_parameters == (), f"unbound router parameters: {router.unbound_parameters}"
    assert set(router.configuration_parameters) <= h.CONFIGURATION_PARAMETERS
    record = h.FilingRecord(
        ein=1, name="X", tax_prd=202312, tax_year=2023, form_filed=expected,
        total_revenue=gross_receipts, gross_receipts=gross_receipts, total_assets_end=total_assets,
        age_years=15.0, ruling_date="2008-06-01", subsection_code=3, filing_requirement_code=1,
        history=(gross_receipts, gross_receipts * 0.95, gross_receipts * 0.9), history_complete=True,
    )
    prediction = router(record)
    assert prediction.variant == expected
    assert prediction.review is False, prediction.reason


def test_summary_records_the_990n_limitation():
    summary = h.summarize([])
    assert any("990-N" in line for line in summary["limitations"])
    assert summary["labels_present"] == []


# ---- Classification --------------------------------------------------------------


def make_record(form_filed, gross_receipts, total_assets=1_000.0):
    return h.FilingRecord(
        ein=1, name="X", tax_prd=202312, tax_year=2023, form_filed=form_filed,
        total_revenue=gross_receipts, gross_receipts=gross_receipts, total_assets_end=total_assets,
        age_years=10.0, ruling_date="2013-01-01", subsection_code=3, filing_requirement_code=1,
        history=(gross_receipts,), history_complete=False,
    )


def test_classify_match():
    assert h.classify(h.Prediction(h.FORM_990EZ), make_record(h.FORM_990EZ, 100_000)) == (h.MATCH, None)


def test_classify_permitted_upgrade_990n_predicted():
    outcome, attribution = h.classify(h.Prediction(h.FORM_990N), make_record(h.FORM_990EZ, 30_000))
    assert outcome == h.PERMITTED_UPGRADE
    assert attribution == h.N_ELIGIBLE_FILED_FULLER_FORM


def test_classify_permitted_upgrade_ez_predicted_full_filed():
    outcome, attribution = h.classify(h.Prediction(h.FORM_990EZ), make_record(h.FORM_990, 150_000))
    assert outcome == h.PERMITTED_UPGRADE
    assert attribution == h.EZ_ELIGIBLE_FILED_FULL_990


def test_classify_under_filed_attributed_to_filer_when_own_figures_exceed_limits():
    outcome, attribution = h.classify(h.Prediction(h.FORM_990), make_record(h.FORM_990EZ, 250_000))
    assert outcome == h.UNDER_FILED
    assert attribution == h.FILER_INELIGIBLE_BY_OWN_FIGURES
    outcome, attribution = h.classify(h.Prediction(h.FORM_990), make_record(h.FORM_990EZ, 100_000, total_assets=600_000))
    assert attribution == h.FILER_INELIGIBLE_BY_OWN_FIGURES


def test_classify_under_filed_attributed_to_router_when_form_test_is_satisfied():
    outcome, attribution = h.classify(h.Prediction(h.FORM_990), make_record(h.FORM_990EZ, 150_000))
    assert outcome == h.UNDER_FILED
    assert attribution == h.ROUTER_DISAGREES_WITH_FORM_TEST


def test_classify_review_and_no_prediction():
    assert h.classify(h.Prediction(h.FORM_990, review=True), make_record(h.FORM_990, 1)) == (h.REVIEW, None)
    assert h.classify(h.Prediction(None), make_record(h.FORM_990, 1)) == (h.NO_PREDICTION, None)


def test_near_boundary_flags():
    assert h.near_boundary(make_record(h.FORM_990EZ, 195_000)) == ("ez_receipts",)
    assert h.near_boundary(make_record(h.FORM_990EZ, 100_000, total_assets=510_000)) == ("ez_assets",)
    assert h.near_boundary(make_record(h.FORM_990EZ, 48_000)) == ("n_receipts",)
    assert h.near_boundary(make_record(h.FORM_990EZ, 100_000)) == ()


# ---- End to end on the fixture ------------------------------------------------------


def test_reference_router_matches_every_filing_in_fixture(org_json):
    results = h.evaluate_organization(org_json, h.reference_router)
    assert len(results) == 13
    assert {r.outcome for r in results} == {h.MATCH}
    summary = h.summarize(results)
    assert summary["filings"] == 13
    assert summary["organizations"] == 1
    assert summary["strict_accuracy"] == 1.0
    assert summary["lenient_accuracy"] == 1.0
    assert summary["confusion_actual_vs_predicted"] == {h.FORM_990: {h.FORM_990: 2}, h.FORM_990EZ: {h.FORM_990EZ: 11}}
    assert summary["history_complete"] == 11
    assert summary["age_under_three_years_by_ruling_date"] == 0


def test_total_revenue_router_gets_the_two_990_years_wrong(org_json):
    """A router that used total revenue instead of gross receipts would misroute both Form 990 years."""

    def total_revenue_router(record):
        return h.Prediction(h.FORM_990 if record.total_revenue >= h.EZ_GROSS_RECEIPTS_LIMIT else h.FORM_990EZ)

    results = h.evaluate_organization(org_json, total_revenue_router)
    wrong = [r for r in results if r.outcome != h.MATCH]
    assert sorted(r.record.tax_prd for r in wrong) == [201312, 202312]
    assert all(r.outcome == h.PERMITTED_UPGRADE for r in wrong)
    assert h.summarize(results)["strict_accuracy"] == pytest.approx(11 / 13)


def test_summarize_accuracy_math():
    rec_ez = make_record(h.FORM_990EZ, 100_000)
    rec_full = make_record(h.FORM_990, 300_000)
    results = [
        h.EvaluationResult(rec_ez, h.Prediction(h.FORM_990EZ), h.MATCH, None, ()),
        h.EvaluationResult(rec_full, h.Prediction(h.FORM_990EZ), h.PERMITTED_UPGRADE, h.EZ_ELIGIBLE_FILED_FULL_990, ()),
        h.EvaluationResult(rec_ez, h.Prediction(h.FORM_990), h.UNDER_FILED, h.ROUTER_DISAGREES_WITH_FORM_TEST, ()),
        h.EvaluationResult(rec_ez, h.Prediction(h.FORM_990EZ, review=True), h.REVIEW, None, ("ez_receipts",)),
    ]
    summary = h.summarize(results)
    assert summary["decided"] == 3
    assert summary["strict_accuracy"] == pytest.approx(1 / 3)
    assert summary["lenient_accuracy"] == pytest.approx(2 / 3)
    assert summary["outcomes"][h.REVIEW] == 1
    assert summary["near_boundary"] == {"ez_receipts": {h.REVIEW: 1}}


# ---- Sampling ----------------------------------------------------------------------------


def test_size_band_edges():
    assert h.size_band(0) == "under_50k"
    assert h.size_band(49_999) == "under_50k"
    assert h.size_band(50_000) == "50k_to_200k"
    assert h.size_band(199_999) == "50k_to_200k"
    assert h.size_band(200_000) == "200k_to_500k"
    assert h.size_band(500_000) == "500k_plus"
    assert h.size_band(None) is None


def test_band_filler_stops_at_target():
    filler = h.BandFiller(target=1)
    assert filler.accept(10_000)
    assert not filler.accept(20_000)
    assert filler.accept(100_000)
    assert filler.accept(300_000)
    assert not filler.is_full()
    assert filler.accept(1_000_000)
    assert filler.is_full()


# ---- Client ----------------------------------------------------------------------------------


def test_search_url_encodes_bracket_parameters():
    url = ProPublicaClient.search_url(q="food bank", page=2, state="ME", c_code=3)
    assert url.startswith("https://projects.propublica.org/nonprofits/api/v2/search.json?")
    assert "q=food+bank" in url
    assert "page=2" in url
    assert "state%5Bid%5D=ME" in url
    assert "c_code%5Bid%5D=3" in url


def test_organization_url_strips_formatting_and_leading_zeros():
    assert ProPublicaClient.organization_url("01-0165097") == "https://projects.propublica.org/nonprofits/api/v2/organizations/10165097.json"
    assert ProPublicaClient.organization_url(10165097) == "https://projects.propublica.org/nonprofits/api/v2/organizations/10165097.json"


def test_client_caches_responses(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return '{"organization": {"ein": 1}, "filings_with_data": []}'

    client = ProPublicaClient(cache_dir=tmp_path, delay_seconds=0, fetch=fetch)
    first = client.organization(1)
    second = client.organization("00-0000001")
    assert first == second
    assert len(calls) == 1
    assert client.live_requests == 1
    assert client.cache_hits == 1


def test_iter_search_pages_until_last(tmp_path):
    pages = {
        0: {"num_pages": 2, "organizations": [{"ein": 1}, {"ein": 2}]},
        1: {"num_pages": 2, "organizations": [{"ein": 3}]},
    }

    def fetch(url):
        page = int(url.split("page=")[1].split("&")[0])
        return json.dumps(pages[page])

    client = ProPublicaClient(cache_dir=None, delay_seconds=0, fetch=fetch)
    assert [o["ein"] for o in client.iter_search(q="x")] == [1, 2, 3]
    assert [o["ein"] for o in client.iter_search(q="x", max_pages=1)] == [1, 2]


# ---- CLI sampling ----------------------------------------------------------------------


def test_sample_eins_fills_bands_and_skips_organizations_without_filings():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "propublica_routing_harness", Path(__file__).resolve().parent.parent.parent / "scripts" / "propublica_routing_harness.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    def filing(period, revenue):
        return {"tax_prd": period, "tax_prd_yr": period // 100, "formtype": 1, "totrevnue": revenue, "totassetsend": 1}

    orgs = {
        1: {"organization": {"ein": 1, "income_amount": 10_000}, "filings_with_data": [filing(202312, 10_000)]},
        2: {"organization": {"ein": 2, "income_amount": 20_000}, "filings_with_data": []},  # no extracted filings
        3: {"organization": {"ein": 3, "income_amount": 30_000}, "filings_with_data": [filing(202312, 30_000)]},
        4: {"organization": {"ein": 4, "income_amount": 100_000}, "filings_with_data": [filing(202312, 100_000)]},
        5: {"organization": {"ein": 5, "income_amount": 300_000}, "filings_with_data": [filing(202312, 300_000)]},
        6: {"organization": {"ein": 6, "income_amount": 900_000}, "filings_with_data": [filing(202312, 900_000)]},
    }
    search_page = {"num_pages": 1, "organizations": [{"ein": e, "name": f"org {e}"} for e in orgs]}  # no income_amount

    def fetch(url):
        if "search.json" in url:
            return json.dumps(search_page)
        ein = int(url.rsplit("/", 1)[1].split(".")[0])
        return json.dumps(orgs[ein])

    client = ProPublicaClient(cache_dir=None, delay_seconds=0, fetch=fetch)
    chosen = cli.sample_eins(client, per_band=1, queries=["x"], state=None, c_code=None, max_pages=1)
    assert chosen == [1, 4, 5, 6]

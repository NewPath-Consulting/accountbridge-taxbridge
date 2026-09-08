"""Tests for reading a filed return out of IRS e-file XML.

Where the real filings are present in `docs/`, they are read and checked
against `data/crn_synthetic.json` — the answer key was written by hand from
ProPublica, the XML is the filed return itself, and they should agree. That
part skips when the filings are absent, because they are not in the
repository.

The rest builds its own XML, so the parser is tested everywhere.
"""

import glob
import json
from pathlib import Path

import pytest

from app.core.benchmark.irs_xml import (
    is_irs_xml,
    parse_form_990_xml,
    totals_agree,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "crn_synthetic.json"

_990 = b"""<?xml version="1.0"?>
<Return xmlns="http://www.irs.gov/efile">
  <ReturnHeader>
    <TaxYr>2024</TaxYr>
    <Filer><EIN>990370960</EIN>
      <BusinessName><BusinessNameLine1Txt>TEST ORG</BusinessNameLine1Txt></BusinessName>
    </Filer>
    <PreparerFirmName><BusinessNameLine1Txt>SOME ACCOUNTANTS</BusinessNameLine1Txt></PreparerFirmName>
  </ReturnHeader>
  <ReturnData><IRS990>
    <ReturnTypeCd>990</ReturnTypeCd>
    <GrossReceiptsAmt>1000</GrossReceiptsAmt>
    <CYContributionsGrantsAmt>600</CYContributionsGrantsAmt>
    <CYProgramServiceRevenueAmt>300</CYProgramServiceRevenueAmt>
    <CYInvestmentIncomeAmt>100</CYInvestmentIncomeAmt>
    <CYOtherRevenueAmt>0</CYOtherRevenueAmt>
    <CYTotalRevenueAmt>1000</CYTotalRevenueAmt>
    <CYTotalExpensesAmt>800</CYTotalExpensesAmt>
    <TotalAssetsEOYAmt>5000</TotalAssetsEOYAmt>
    <TotalLiabilitiesEOYAmt>200</TotalLiabilitiesEOYAmt>
  </IRS990></ReturnData>
</Return>"""

_990EZ = b"""<?xml version="1.0"?>
<Return xmlns="http://www.irs.gov/efile">
  <ReturnHeader><TaxYr>2019</TaxYr>
    <Filer><EIN>990370960</EIN>
      <BusinessName><BusinessNameLine1Txt>TEST ORG</BusinessNameLine1Txt></BusinessName>
    </Filer>
  </ReturnHeader>
  <ReturnData><IRS990EZ>
    <ReturnTypeCd>990EZ</ReturnTypeCd>
    <GrossReceiptsAmt>500</GrossReceiptsAmt>
    <MembershipDuesAmt>200</MembershipDuesAmt>
    <ProgramServiceRevenueAmt>290</ProgramServiceRevenueAmt>
    <InvestmentIncomeAmt>10</InvestmentIncomeAmt>
    <TotalRevenueAmt>500</TotalRevenueAmt>
    <TotalExpensesAmt>400</TotalExpensesAmt>
    <NetAssetsOrFundBalancesEOYAmt>900</NetAssetsOrFundBalancesEOYAmt>
  </IRS990EZ></ReturnData>
</Return>"""


def test_is_irs_xml():
    assert is_irs_xml("form990 2024 filed.xml")
    assert not is_irs_xml("form990 2024 filed.pdf")


def test_the_full_form_is_read():
    out = parse_form_990_xml(_990)
    assert out["organization_summary"]["return_type"] == "990"
    assert out["organization_summary"]["tax_year"] == 2024
    assert out["revenue"] == {
        "contributions": 600.0,
        "program_service_revenue": 300.0,
        "investment_income": 100.0,
        "other_revenue": 0.0,
        "total_revenue": 1000.0,
    }
    assert out["balance_sheet"]["total_assets"] == 5000.0


def test_the_short_form_is_read():
    """The EZ has its own element names, not the CY... set."""
    out = parse_form_990_xml(_990EZ)
    assert out["organization_summary"]["return_type"] == "990EZ"
    # Dues that are contributions sit on Part I line 3 of the EZ, so
    # MembershipDuesAmt is what the full form would call contributions.
    assert out["revenue"]["contributions"] == 200.0
    assert out["revenue"]["total_revenue"] == 500.0


def test_the_filer_is_named_not_the_preparer():
    """BusinessNameLine1Txt appears for the preparer first in document order."""
    assert parse_form_990_xml(_990)["organization_summary"]["organization_name"] == "TEST ORG"


def test_a_missing_figure_stays_missing():
    """A reference invented to fill a gap is worse than a gap."""
    stripped = _990.replace(b"<TotalAssetsEOYAmt>5000</TotalAssetsEOYAmt>", b"")
    out = parse_form_990_xml(stripped)
    assert "total_assets" not in (out.get("balance_sheet") or {})


def test_unparseable_bytes_raise():
    """Silently returning nothing would score as every field missing."""
    with pytest.raises(ValueError):
        parse_form_990_xml(b"not xml at all")


def test_totals_agree_catches_a_mapping_error():
    out = parse_form_990_xml(_990)
    assert totals_agree(out) == []

    out["revenue"]["contributions"] = 1.0
    assert totals_agree(out)


# --- against the real filings, when they are present ----------------------

def _filings():
    return sorted(glob.glob(str(ROOT / "docs" / "form990 *.xml")))


@pytest.mark.skipif(not _filings(), reason="filed returns not present in docs/")
def test_the_filings_agree_with_the_answer_key():
    """Two independent records of the same returns should match.

    The key in the fixture was written by hand from ProPublica; the XML is the
    return as filed. A disagreement means one of them is wrong.
    """
    key = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = {y["year"]: y for y in key["years"]}
    mapping = key["expected_classification"]["line_mapping"]

    checked = 0
    for path in _filings():
        out = parse_form_990_xml(Path(path).read_bytes())
        year = out["organization_summary"]["tax_year"]
        if year not in expected:
            continue  # the fixture does not cover every filed year
        revenue = expected[year]["revenue"]

        for section, accounts in (
            ("contributions", mapping["contributions"]),
            ("program_service_revenue", mapping["program_service_revenue"]),
            ("investment_income", mapping["investment_income"]),
        ):
            want = round(sum(revenue.get(a, 0.0) for a in accounts), 2)
            # A line with no activity is omitted from the return rather than
            # filed as zero -- 2020 reports no program service revenue at all,
            # because the events stopped. Absent and zero agree.
            got = out["revenue"].get(section)
            if got is None:
                assert want == 0, f"{year} {section}: filing omits it, key expects {want:,.0f}"
                continue
            assert got == pytest.approx(want), f"{year} {section}"

        assert out["revenue"]["total_revenue"] == pytest.approx(
            expected[year]["published"]["revenue"]
        )
        checked += 1

    assert checked, "no filed year overlapped the fixture"

"""Read a filed return straight from the IRS e-file XML.

The benchmark's reference figures used to come from a model reading a PDF.
That makes a disagreement uninterpretable: two readings differ and nothing
says which is wrong. The IRS publishes the same returns as XML, where every
figure is a named element, so the reference can be *read* rather than
inferred and a disagreement means our pipeline is wrong.

Two schemas, because the same organization files different forms as it grows.
Form 990 tags its current-year figures `CY...`; the 990-EZ has its own,
shorter set. Commercial Relocation Network filed 990-EZ through 2021 and the
full 990 from 2022, so both paths are exercised by the fixture.

One thing to know about the 990-EZ: contributions and membership dues are not
the same line as on the full form. Dues that are contributions sit on Part I
line 3, and `MembershipDuesAmt` is where the filing puts them, so for those
years that element carries what the full form would call contributions. The
fixture's own note records the same thing.

Nothing here is inferred or defaulted. An element that is absent stays None,
because a reference figure invented to fill a gap is worse than a gap.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

__all__ = [
    "is_irs_xml",
    "parse_form_990_xml",
    "parse_organization_information_xml",
    "return_type",
    "tax_year",
]

# Element name -> where it lands in FORM_990_OUTPUT_SCHEMA, for the full 990.
_FORM_990_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("organization_summary", "ein"): ("EIN",),
    ("organization_summary", "tax_year"): ("TaxYr",),
    ("organization_summary", "gross_receipts"): ("GrossReceiptsAmt",),
    ("revenue", "contributions"): ("CYContributionsGrantsAmt",),
    ("revenue", "program_service_revenue"): ("CYProgramServiceRevenueAmt",),
    ("revenue", "investment_income"): ("CYInvestmentIncomeAmt",),
    ("revenue", "other_revenue"): ("CYOtherRevenueAmt",),
    ("revenue", "total_revenue"): ("CYTotalRevenueAmt",),
    ("expenses", "fundraising"): ("CYTotalFundraisingExpenseAmt",),
    ("expenses", "total_expenses"): ("CYTotalExpensesAmt",),
    ("balance_sheet", "total_assets"): ("TotalAssetsEOYAmt",),
    ("balance_sheet", "total_liabilities"): ("TotalLiabilitiesEOYAmt",),
    ("balance_sheet", "net_assets"): ("NetAssetsOrFundBalancesEOYAmt",),
    ("reconciliation", "total_revenue"): ("CYTotalRevenueAmt",),
    ("reconciliation", "total_expenses"): ("CYTotalExpensesAmt",),
}

# The 990-EZ. `MembershipDuesAmt` is Part I line 3, which is where dues that
# are contributions are reported on this form -- see the module docstring.
_FORM_990EZ_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("organization_summary", "ein"): ("EIN",),
    ("organization_summary", "tax_year"): ("TaxYr",),
    ("organization_summary", "gross_receipts"): ("GrossReceiptsAmt",),
    ("revenue", "contributions"): ("ContributionsGiftsGrantsEtcAmt", "MembershipDuesAmt"),
    ("revenue", "membership_dues"): ("MembershipDuesAmt",),
    ("revenue", "program_service_revenue"): ("ProgramServiceRevenueAmt",),
    ("revenue", "investment_income"): ("InvestmentIncomeAmt",),
    ("revenue", "other_revenue"): ("OtherRevenueTotalAmt",),
    ("revenue", "total_revenue"): ("TotalRevenueAmt",),
    ("expenses", "program_services"): ("ProgramServiceExpensesAmt",),
    ("expenses", "other_expenses"): ("OtherExpensesTotalAmt",),
    ("expenses", "total_expenses"): ("TotalExpensesAmt",),
    ("balance_sheet", "total_assets"): ("NetAssetsOrFundBalancesEOYAmt", "EOYAmt"),
    ("balance_sheet", "net_assets"): ("NetAssetsOrFundBalancesEOYAmt",),
    ("reconciliation", "total_revenue"): ("TotalRevenueAmt",),
    ("reconciliation", "total_expenses"): ("TotalExpensesAmt",),
}


def is_irs_xml(file_name: str) -> bool:
    return file_name.lower().endswith(".xml")


def _local(tag: str) -> str:
    """'{ns}TaxYr' -> 'TaxYr'. IRS returns are namespaced; the names are not."""
    return tag.rsplit("}", 1)[-1]


def _index(root: ET.Element) -> dict[str, str]:
    """Every element with text, by local name.

    First occurrence wins. The IRS schema repeats some names inside schedules,
    and the return's own body comes first.
    """
    found: dict[str, str] = {}
    for element in root.iter():
        text = (element.text or "").strip()
        if text:
            found.setdefault(_local(element.tag), text)
    return found


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def return_type(root: ET.Element) -> str | None:
    """'990', '990EZ', or None. Not every filing states it."""
    values = _index(root)
    stated = values.get("ReturnTypeCd")
    if stated:
        return stated.upper()
    # Fall back to the shape of the document: only the full form carries the
    # current-year elements.
    return "990" if "CYTotalRevenueAmt" in values else "990EZ"


def tax_year(root: ET.Element) -> int | None:
    raw = _index(root).get("TaxYr")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def parse_form_990_xml(file_bytes: bytes) -> dict[str, Any]:
    """Reference figures from an IRS e-file return, in the benchmark's schema.

    Raises ValueError when the bytes are not parseable XML, so a corrupt file
    is a failure rather than a silently empty reference that would score as
    every field missing.
    """
    try:
        root = ET.fromstring(file_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"not parseable as IRS e-file XML: {exc}") from exc

    values = _index(root)
    kind = return_type(root)
    mapping = _FORM_990EZ_MAP if kind == "990EZ" else _FORM_990_MAP

    # An EIN is an identifier and a tax year is a year; only money is a float.
    verbatim = {"ein"}
    integral = {"tax_year"}

    extracted: dict[str, dict[str, Any]] = {}
    for (section, field), candidates in mapping.items():
        for name in candidates:
            if name not in values:
                continue
            if field in verbatim:
                value: Any = values[name]
            elif field in integral:
                value = int(_number(values[name]) or 0) or None
            else:
                value = _number(values[name])
            if value is not None:
                extracted.setdefault(section, {})[field] = value
                break

    summary = extracted.setdefault("organization_summary", {})
    # BusinessNameLine1Txt appears for the preparer firm and the officer's
    # employer as well as the filer, and the preparer comes first in document
    # order, so the filer has to be addressed rather than searched for.
    name_element = root.find(".//{*}Filer/{*}BusinessName/{*}BusinessNameLine1Txt")
    if name_element is not None and name_element.text:
        summary["organization_name"] = name_element.text.strip()
    summary["return_type"] = kind

    logger.info(
        "IRS XML reference: %s %s, %d field(s) read",
        kind,
        summary.get("tax_year"),
        sum(len(v) for v in extracted.values()),
    )
    return extracted


def totals_agree(extracted: Mapping[str, Any]) -> list[str]:
    """Internal checks on what was read, so a bad mapping is visible.

    A reference that does not add up is worse than no reference, because the
    scorecard would blame the pipeline for it.
    """
    problems: list[str] = []
    revenue = extracted.get("revenue") or {}
    stated = revenue.get("total_revenue")
    parts = [
        revenue.get(name)
        for name in ("contributions", "program_service_revenue", "investment_income", "other_revenue")
    ]
    known = [p for p in parts if p is not None]
    if stated is not None and known:
        walked = round(sum(known), 2)
        if abs(walked - stated) > 1.0:
            problems.append(
                f"revenue lines sum to {walked:,.0f} against a stated total of {stated:,.0f}"
            )
    return problems


# --- organization identity -----------------------------------------------
# The filed return carries everything Item A through M asks for, including the
# principal officer, which ProPublica does not publish and which was therefore
# a manual field. Reading it here is exact where OCR plus a model was neither.

_ORG_OF_TYPE = {
    "TypeOfOrganizationCorpInd": "Corporation",
    "TypeOfOrganizationTrustInd": "Trust",
    "TypeOfOrganizationAssocInd": "Association",
    "TypeOfOrganizationOtherInd": "Other",
}


def _text(root: ET.Element, path: str) -> str | None:
    el = root.find(path)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _format_ein(raw: str | None) -> str | None:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    return f"{digits[:2]}-{digits[2:]}" if len(digits) == 9 else (raw or None)


def parse_organization_information_xml(file_bytes: bytes) -> dict[str, Any] | None:
    """Item A-M identity from a filed return, in organizationInformation shape.

    Returns None when the bytes are not a parseable return, so a caller can
    fall back rather than publish an empty identity block.
    """
    try:
        root = ET.fromstring(file_bytes)
    except ET.ParseError:
        return None

    filer = root.find(".//{*}Filer")
    if filer is None:
        return None

    status = root.find(".//{*}Organization501cInd")
    subsection = status.get("organization501cTypeTxt") if status is not None else None
    if subsection is None and root.find(".//{*}Organization501c3Ind") is not None:
        subsection = "3"

    form_of = next(
        (label for tag, label in _ORG_OF_TYPE.items()
         if root.find(f".//{{*}}{tag}") is not None),
        None,
    )

    officer = _text(root, ".//{*}PrincipalOfficerNm") or _text(
        root, ".//{*}BusinessOfficerGrp/{*}PersonNm"
    )

    return {
        "organizationInformation": {
            "legalName": _text(filer, "./{*}BusinessName/{*}BusinessNameLine1Txt"),
            "dbaNames": [],
            "ein": _format_ein(_text(filer, "./{*}EIN")),
            "address": {
                "street": _text(filer, ".//{*}AddressLine1Txt"),
                "city": _text(filer, ".//{*}CityNm"),
                "state": _text(filer, ".//{*}StateAbbreviationCd"),
                "zip": _text(filer, ".//{*}ZIPCd"),
            },
            "telephone": _text(filer, "./{*}PhoneNum"),
            "website": _text(root, ".//{*}WebsiteAddressTxt"),
            "principalOfficer": {
                "name": officer,
                "title": _text(root, ".//{*}BusinessOfficerGrp/{*}PersonTitleTxt"),
                "address": None,
            },
            "taxExemptStatus": f"501(c)({subsection})" if subsection else None,
            "formOfOrganization": form_of,
            "yearOfFormation": _text(root, ".//{*}FormationYr"),
            "stateOfLegalDomicile": _text(root, ".//{*}LegalDomicileStateCd"),
            "groupReturn": _text(root, ".//{*}GroupReturnForAffiliatesInd") in ("1", "true", "X"),
            "groupExemptionNumber": _text(root, ".//{*}GroupExemptionNum"),
        }
    }

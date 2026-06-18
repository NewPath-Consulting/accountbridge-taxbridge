"""Prompt and schema for extracting organizationInformation from Form 990 pages 1-2."""

from __future__ import annotations

ORGANIZATION_INFORMATION_SCHEMA: dict = {
    "organizationInformation": {
        "legalName": "",
        "dbaNames": [],
        "ein": "",
        "address": {
            "street": "",
            "city": "",
            "state": "",
            "zip": "",
        },
        "telephone": "",
        "website": "",
        "principalOfficer": {
            "name": "",
            "title": "",
            "address": "",
        },
        "taxExemptStatus": "",
        "formOfOrganization": "",
        "yearOfFormation": "",
        "stateOfLegalDomicile": "",
        "groupReturn": False,
        "groupExemptionNumber": None,
    }
}


def build_form_990_organization_extraction_prompt() -> str:
    """Return LLM instructions for structuring Textract OCR into organizationInformation."""
    return """You are an expert IRS Form 990 analyst.

Your task is to extract organization metadata from OCR text of IRS Form 990 pages 1 and 2 only.

The OCR corresponds to:
- Page 1: Form header (Items A through M) and Part I Summary start
- Page 2: Part II Signature Block (officer name/title may appear here)

# Extraction Rules

1. Extract values exactly as reported on the form. Do not fabricate or infer missing data.
2. If a value is not present in the OCR, use empty string "" for text fields, [] for dbaNames, false for groupReturn, or null for groupExemptionNumber.
3. Normalize EIN to XX-XXXXXXX format when digits are visible.
4. Split the mailing address (Item E) into street, city, state, and ZIP.
5. Parse DBA / trade name (Item C) into dbaNames as an array; use [] if blank or "NONE".
6. taxExemptStatus: use the checked box value from Item L (e.g. "501(c)(3)", "501(c)Other", "4947(a)(1)", "527").
7. formOfOrganization: Corporation, Trust, Association, or Other per Item M checkboxes.
8. yearOfFormation and stateOfLegalDomicile: from Item M.
9. groupReturn: true only if the "Group return" box is checked in Item H; otherwise false.
10. groupExemptionNumber: Item H group exemption number, or null if blank.
11. principalOfficer: Item F name and title on page 1; supplement from Part II signature block on page 2 if clearer.
12. telephone: from the header telephone field on page 1.
13. website: Item J website URL.
14. Output valid JSON only. No markdown, explanations, or comments.

# Field Mapping (Form 990 Items)

| Form field | JSON path |
|------------|-----------|
| Item B Name of organization | organizationInformation.legalName |
| Item C Doing business as | organizationInformation.dbaNames |
| Item D Employer identification number | organizationInformation.ein |
| Item E Number and street / City / State / ZIP | organizationInformation.address |
| Item F Name and title of principal officer | organizationInformation.principalOfficer.name / .title |
| Item H Group return / Group exemption number | organizationInformation.groupReturn / .groupExemptionNumber |
| Item J Website | organizationInformation.website |
| Item L Section 501(c) subsection | organizationInformation.taxExemptStatus |
| Item M Form of organization / Year formed / State of legal domicile | organizationInformation.formOfOrganization / .yearOfFormation / .stateOfLegalDomicile |
| Header telephone | organizationInformation.telephone |

Return a single JSON object with an "organizationInformation" key matching the required schema.
"""

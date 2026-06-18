"""Unit tests for Form 990 organization information extraction."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.benchmark.schemas import BenchmarkDocument
from app.core.prompts.form_990_organization import (
    ORGANIZATION_INFORMATION_SCHEMA,
    build_form_990_organization_extraction_prompt,
)
from app.utils.form_990_organization import (
    _coerce_organization_information,
    merge_organization_information,
    resolve_form_990_for_tax_year,
)


def _sample_doc(fiscal_year: int, file_name: str) -> BenchmarkDocument:
    return BenchmarkDocument(
        doc_type="form_990",
        file_name=file_name,
        file_path=f"/docs/{file_name}",
        fiscal_year=fiscal_year,
        start_date=f"{fiscal_year}-01-01",
        end_date=f"{fiscal_year}-12-31",
    )


def test_merge_organization_information_filed_overrides_empty_base():
    base = {
        "legalName": "",
        "ein": "",
        "address": {"street": "", "city": "", "state": "", "zip": ""},
        "principalOfficer": {"name": "", "title": "", "address": ""},
        "groupReturn": False,
        "groupExemptionNumber": None,
    }
    filed = {
        "legalName": "Kansas City Woodworkers Guild Inc",
        "ein": "43-1234567",
        "address": {"street": "123 Main St", "city": "Kansas City", "state": "MO", "zip": "64111"},
        "principalOfficer": {"name": "Jane Doe", "title": "President", "address": ""},
        "taxExemptStatus": "501(c)(3)",
        "formOfOrganization": "Association",
        "groupReturn": False,
    }
    merged = merge_organization_information(base, filed)
    assert merged["legalName"] == "Kansas City Woodworkers Guild Inc"
    assert merged["ein"] == "43-1234567"
    assert merged["address"]["city"] == "Kansas City"
    assert merged["principalOfficer"]["name"] == "Jane Doe"


def test_merge_organization_information_preserves_base_when_filed_empty():
    base = {
        "legalName": "Existing Name",
        "website": "https://example.org",
        "dbaNames": ["DBA One"],
    }
    filed = {"legalName": "", "website": ""}
    merged = merge_organization_information(base, filed)
    assert merged["legalName"] == "Existing Name"
    assert merged["website"] == "https://example.org"
    assert merged["dbaNames"] == ["DBA One"]


def test_merge_organization_information_group_return_boolean():
    base = {"groupReturn": False}
    filed = {"groupReturn": True}
    merged = merge_organization_information(base, filed)
    assert merged["groupReturn"] is True


def test_coerce_organization_information_nested_key():
    payload = {
        "organizationInformation": {
            "legalName": "Test Org",
            "ein": "12-3456789",
        }
    }
    assert _coerce_organization_information(payload) == payload["organizationInformation"]


def test_coerce_organization_information_flat_key():
    payload = {"legalName": "Test Org", "ein": "12-3456789"}
    assert _coerce_organization_information(payload) == payload


def test_coerce_organization_information_parse_error_returns_none():
    assert _coerce_organization_information({"_parse_error": True}) is None


def test_coerce_organization_information_bedrock_choices_envelope():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"organizationInformation": {'
                        '"legalName": "Kansas City Woodworkers Guild Inc", '
                        '"ein": "43-1234567", '
                        '"dbaNames": [], '
                        '"address": {"street": "123 Main", "city": "Kansas City", "state": "MO", "zip": "64111"}, '
                        '"telephone": "816-555-0100", '
                        '"website": "https://example.org", '
                        '"principalOfficer": {"name": "Jane Doe", "title": "President", "address": ""}, '
                        '"taxExemptStatus": "501(c)(3)", '
                        '"formOfOrganization": "Association", '
                        '"yearOfFormation": "1985", '
                        '"stateOfLegalDomicile": "MO", '
                        '"groupReturn": false, '
                        '"groupExemptionNumber": null'
                        "}}"
                    ),
                },
                "finish_reason": "stop",
                "index": 0,
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    org = _coerce_organization_information(payload)
    assert org is not None
    assert org["legalName"] == "Kansas City Woodworkers Guild Inc"
    assert org["ein"] == "43-1234567"


def test_prompt_includes_field_mapping_and_schema_keys():
    prompt = build_form_990_organization_extraction_prompt()
    assert "organizationInformation" in prompt
    assert "Item B" in prompt
    assert "501(c)(3)" in prompt
    assert "organizationInformation" in ORGANIZATION_INFORMATION_SCHEMA


@pytest.mark.parametrize(
    "end_date,expected_year",
    [
        ("2025-12-31", 2025),
        ("2024-12-31", 2024),
    ],
)
def test_resolve_form_990_for_tax_year_matches_fiscal_year(end_date, expected_year):
    docs = [
        _sample_doc(2023, "form990_2023.pdf"),
        _sample_doc(2024, "form990_2024.pdf"),
        _sample_doc(2025, "form990_2025.pdf"),
    ]

    async def _run():
        with patch(
            "app.utils.form_990_organization.get_document_source"
        ) as mock_source_factory:
            mock_source = MagicMock()
            mock_source.list_documents = AsyncMock(return_value=docs)
            mock_source_factory.return_value = mock_source
            return await resolve_form_990_for_tax_year(end_date)

    result = asyncio.run(_run())
    assert result is not None
    assert result.fiscal_year == expected_year


def test_resolve_form_990_for_tax_year_falls_back_to_latest():
    docs = [
        _sample_doc(2023, "form990_2023.pdf"),
        _sample_doc(2024, "form990_2024.pdf"),
    ]

    async def _run():
        with patch(
            "app.utils.form_990_organization.get_document_source"
        ) as mock_source_factory:
            mock_source = MagicMock()
            mock_source.list_documents = AsyncMock(return_value=docs)
            mock_source_factory.return_value = mock_source
            return await resolve_form_990_for_tax_year("2025-12-31")

    result = asyncio.run(_run())
    assert result is not None
    assert result.fiscal_year == 2024


def test_resolve_form_990_for_tax_year_no_docs():
    async def _run():
        with patch(
            "app.utils.form_990_organization.get_document_source"
        ) as mock_source_factory:
            mock_source = MagicMock()
            mock_source.list_documents = AsyncMock(return_value=[])
            mock_source_factory.return_value = mock_source
            return await resolve_form_990_for_tax_year("2025-12-31")

    assert asyncio.run(_run()) is None


def test_merge_step_pattern_llm_then_filed():
    """Mirrors ReportsService._merge_tax_return_step_results org info overlay."""
    non_financial = {"organizationInformation": {"legalName": "LLM Guess", "ein": ""}}
    filed = {"legalName": "Filed Org Name", "ein": "99-9999999"}
    organization_information = merge_organization_information(
        non_financial.get("organizationInformation") or {},
        filed,
    )
    assert organization_information["legalName"] == "Filed Org Name"
    assert organization_information["ein"] == "99-9999999"

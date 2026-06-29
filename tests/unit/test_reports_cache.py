"""Unit tests for local reports cache (TEMP benchmark testing aid)."""

import json
from pathlib import Path

import pytest

from app.utils.reports_cache import (
    extract_benchmark_reports_slice,
    latest_cache_path,
    load_benchmark_inputs_from_cache,
    save_reports_response,
)

SAMPLE_RESPONSE = {
    "request_id": "test-123",
    "wildapricot_account_id": "497705",
    "quickbooks_realm_id": "9341457191103538",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "status": "completed",
    "reports": {
        "cash_flow": {
            "report_type": "cash_flow",
            "status": "completed",
            "processing_time": 1.0,
            "content": {"operating_activities": {}},
        },
        "tax_return": {
            "report_type": "tax_return",
            "status": "completed",
            "processing_time": 2.0,
            "content": {"organization_summary": {}},
        },
        "balance_sheet": {
            "report_type": "balance_sheet",
            "status": "completed",
            "processing_time": 1.5,
            "content": {"assets": {}},
        },
    },
}


def test_save_and_load_cached_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.utils.reports_cache.settings.REPORTS_CACHE_DIR",
        str(tmp_path),
    )

    path = save_reports_response(SAMPLE_RESPONSE)
    assert path == tmp_path / "latest.json"
    assert (tmp_path / "test-123.json").is_file()

    context, reports = load_benchmark_inputs_from_cache()
    assert context["request_id"] == "test-123"
    assert set(reports.keys()) == {"cash_flow", "tax_return", "balance_sheet"}


def test_extract_benchmark_reports_slice_includes_prior_year_balance_sheet():
    response = {
        **SAMPLE_RESPONSE,
        "quickbooks_source": {
            "prior_year_balance_sheet": {
                "metadata": {"end_period": "2023-12-31"},
                "totals": {"total_assets": 5000.0},
            }
        },
    }
    _, reports = extract_benchmark_reports_slice(response)
    assert reports["prior_year_balance_sheet"]["metadata"]["end_period"] == "2023-12-31"


def test_extract_benchmark_reports_slice_missing_key():
    bad = {**SAMPLE_RESPONSE, "reports": {"cash_flow": SAMPLE_RESPONSE["reports"]["cash_flow"]}}
    with pytest.raises(ValueError, match="tax_return"):
        extract_benchmark_reports_slice(bad)


def test_load_cached_reports_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.utils.reports_cache.settings.REPORTS_CACHE_DIR",
        str(tmp_path),
    )
    with pytest.raises(ValueError, match="No cached reports"):
        load_benchmark_inputs_from_cache()


def test_latest_cache_path_uses_settings(monkeypatch):
    monkeypatch.setattr(
        "app.utils.reports_cache.settings.REPORTS_CACHE_DIR",
        "data/reports",
    )
    assert latest_cache_path() == Path("data/reports/latest.json")

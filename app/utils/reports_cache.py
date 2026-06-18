"""TEMP: local cache for /api/reports output to support benchmark-only testing."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Tuple

from app.config.settings import settings

logger = logging.getLogger(__name__)

BENCHMARK_REPORT_KEYS = ("cash_flow", "tax_return", "balance_sheet")
LATEST_FILENAME = "latest.json"


def cache_dir() -> Path:
    return Path(settings.REPORTS_CACHE_DIR)


def latest_cache_path() -> Path:
    return cache_dir() / LATEST_FILENAME


def save_reports_response(response: Dict[str, Any]) -> Path:
    """Persist full /api/reports response for benchmark replay."""
    out_dir = cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    path = latest_cache_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(response, f, indent=2, ensure_ascii=False)

    request_id = response.get("request_id")
    if request_id:
        request_path = out_dir / f"{request_id}.json"
        with open(request_path, "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2, ensure_ascii=False)

    logger.info("Saved reports response to %s", path)
    return path


def load_cached_reports_response() -> Dict[str, Any]:
    path = latest_cache_path()
    if not path.is_file():
        raise ValueError(
            f"No cached reports at {path}. Run /api/reports first."
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Cached reports at {path} are not a JSON object")
    return data


def extract_benchmark_reports_slice(
    reports_response: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Return (context, cash_flow+tax_return slice) from a reports API response."""
    reports = reports_response.get("reports") or {}
    missing = [k for k in BENCHMARK_REPORT_KEYS if k not in reports]
    if missing:
        raise ValueError(f"Cached reports missing: {missing}")

    benchmark_slice = {k: reports[k] for k in BENCHMARK_REPORT_KEYS}
    for key in BENCHMARK_REPORT_KEYS:
        entry = benchmark_slice[key]
        if not isinstance(entry, dict) or not entry.get("content"):
            raise ValueError(
                f"Cached report '{key}' has no content (status={entry.get('status')})"
            )

    if reports_response.get("data_quality_warnings"):
        benchmark_slice["data_quality_warnings"] = reports_response[
            "data_quality_warnings"
        ]

    context = {
        "request_id": reports_response.get("request_id"),
        "start_date": reports_response.get("start_date"),
        "end_date": reports_response.get("end_date"),
        "wildapricot_account_id": reports_response.get("wildapricot_account_id"),
        "quickbooks_realm_id": reports_response.get("quickbooks_realm_id"),
        "reports_status": reports_response.get("status"),
    }
    return context, benchmark_slice


def load_benchmark_inputs_from_cache() -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Load context + reports slice from latest cached /api/reports response."""
    response = load_cached_reports_response()
    return extract_benchmark_reports_slice(response)

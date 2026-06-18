"""WildApricot supporting-source extraction (Form 990)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.adapters.wildapricot.client import WildApricotClient
from app.adapters.wildapricot.exceptions import WildApricotAPIError, WildApricotAuthError
from app.adapters.wildapricot.export import save_extraction_exports
from app.adapters.wildapricot.resources import SUPPORTED_RESOURCES, WildApricotResources
from app.config.settings import Settings, settings

logger = logging.getLogger(__name__)

def _authenticate_with_401_retry(client: WildApricotClient) -> None:
    try:
        client.authenticate()
    except WildApricotAuthError as exc:
        if exc.status_code == 401:
            logger.info("Workflow auth 401; regenerating bearer token and retrying")
            client.regenerate_bearer_token()
            client.authenticate(_retried=True)
            return
        raise


def _call_with_401_retry(client: WildApricotClient, fn):
    try:
        return fn()
    except WildApricotAPIError as exc:
        if exc.status_code == 401:
            logger.info("Workflow API 401; regenerating bearer token and retrying")
            client.regenerate_bearer_token()
            return fn()
        raise


def pluck_ids(items: list[dict[str, Any]], *, key: str = "Id") -> list[int | str]:
    ids: list[int | str] = []
    for item in items:
        value = item.get(key) or item.get(key.lower())
        if value is not None:
            ids.append(value)
    return ids


def run_extraction_workflow(
    *,
    donation_start_date: str | None = None,
    donation_end_date: str | None = None,
    app_settings: Settings | None = None,
    client: WildApricotClient | None = None,
    save_json: bool = False,
    save_csv: bool | None = None,
    export_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Fetch WildApricot supporting-source data in priority order.

    APIs: invoices, payments, contacts, events, event_registrations, donations.
    Used for membership statistics, program metrics, event participation,
    revenue validation, and narrative generation (QuickBooks remains primary financial source).
    """
    wa_client = client or WildApricotClient(app_settings=app_settings or settings)
    warnings: list[dict[str, Any]] = []
    logger.info("WildApricot extraction starting account_id=%s", wa_client.account_id)
    _authenticate_with_401_retry(wa_client)
    api = WildApricotResources(wa_client)

    invoice_list = _call_with_401_retry(wa_client, api.list_invoices)
    payment_list = _call_with_401_retry(wa_client, api.list_payments)
    contact_list = _call_with_401_retry(wa_client, api.list_contacts)
    event_list = _call_with_401_retry(wa_client, api.list_events)

    registration_list: list[dict[str, Any]] = []
    event_ids = pluck_ids(event_list)
    for event_id in event_ids:
        try:
            registration_list.extend(api.list_event_registrations(event_id))
        except Exception as exc:
            logger.warning(
                "Failed to fetch event registrations event_id=%s: %s",
                event_id,
                exc,
            )
            warnings.append(
                {
                    "step": "event_registrations",
                    "status": "partial_failure",
                    "event_id": event_id,
                    "message": str(exc),
                }
            )

    donation_list: list[dict[str, Any]] = []
    try:
        # Try to fetch donations without date filters (WildApricot donations API may not accept date params)
        donation_list = _call_with_401_retry(
            wa_client,
            lambda: api.list_donations(
                start_date=None,
                end_date=None,
            ),
        )
    except Exception as donation_error:
        logger.warning(
            "Failed to fetch donations: %s. Continuing without donation data.",
            donation_error,
        )
        warnings.append(
            {
                "step": "donations",
                "status": "failed",
                "message": str(donation_error),
            }
        )

    contact_ids = pluck_ids(contact_list)
    data = {
        "invoices": invoice_list,
        "payments": payment_list,
        "contacts": contact_list,
        "events": event_list,
        "event_registrations": registration_list,
        "donations": donation_list,
    }

    identifiers = {
        "account_id": wa_client.account_id,
        "invoice_ids": pluck_ids(invoice_list),
        "payment_ids": pluck_ids(payment_list),
        "contact_ids": contact_ids,
        "event_ids": event_ids,
        "registration_ids": pluck_ids(registration_list),
        "donation_ids": pluck_ids(donation_list),
    }

    result: dict[str, Any] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "account_id": wa_client.account_id,
        "source": "wildapricot",
        "purpose": (
            "Supporting source: membership statistics, program metrics, "
            "event participation, revenue validation, narrative generation"
        ),
        "extraction_order": list(SUPPORTED_RESOURCES),
        "warnings": warnings,
        "identifiers": identifiers,
        "data": data,
    }

    logger.info(
        "WildApricot extraction complete invoices=%s payments=%s contacts=%s "
        "events=%s registrations=%s donations=%s",
        len(invoice_list),
        len(payment_list),
        len(contact_ids),
        len(event_ids),
        len(registration_list),
        len(donation_list),
    )

    cfg = app_settings or settings
    should_save_json = save_json or export_path is not None or bool(cfg.WILDAPRICOT_EXPORT_JSON)
    should_save_csv = save_csv if save_csv is not None else cfg.WILDAPRICOT_EXPORT_CSV

    if should_save_json or should_save_csv:
        paths = save_extraction_exports(
            result,
            path=export_path,
            app_settings=cfg,
            save_json=should_save_json,
            save_csv=should_save_csv,
        )
        if "json" in paths:
            result["export_file"] = str(paths["json"])
        if "csv_dir" in paths:
            result["export_csv_dir"] = str(paths["csv_dir"])

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        result = run_extraction_workflow(save_json=True)
        print("WildApricot Supporting-Source Extraction")
        if result.get("export_file"):
            print(f"  JSON: {result['export_file']}")
        if result.get("export_csv_dir"):
            print(f"  CSV:  {result['export_csv_dir']}")
        print(f"  Account ID: {result.get('account_id')}")
        id_keys = {
            "invoices": "invoice_ids",
            "payments": "payment_ids",
            "contacts": "contact_ids",
            "events": "event_ids",
            "event_registrations": "registration_ids",
            "donations": "donation_ids",
        }
        for key in result.get("extraction_order", SUPPORTED_RESOURCES):
            count = len(result.get("identifiers", {}).get(id_keys[key], []))
            print(f"  {key}: {count}")
        workflow_warnings = result.get("warnings") or []
        if workflow_warnings:
            print(f"  Warnings: {len(workflow_warnings)}")
    except Exception as exc:
        logger.exception("Workflow failed: %s", exc)

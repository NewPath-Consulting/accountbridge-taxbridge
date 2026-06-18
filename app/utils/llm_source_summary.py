"""Prepare source data for LLM report prompts and API responses."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.utils.postprocess_quickbooks import (
    _top_quickbooks_rows,
    extract_quickbooks_totals,
)
from app.utils.postprocess_wildapricot import WildApricotProcessor

logger = logging.getLogger(__name__)

_WA_FINANCIAL_ENTITIES = frozenset(
    {"invoices", "payments", "donations", "event_registrations"}
)

_WA_FINANCIAL_ATTR_KEYS = frozenset(
    {
        "value",
        "paidamount",
        "amount",
        "total",
        "balance",
        "price",
        "sum",
        "fee",
        "tax",
        "quantity",
        "ispaid",
        "status",
        "ordertype",
        "documentdate",
        "createddate",
        "memo",
        "description",
        "type",
        "donationtype",
        "paymenttype",
        "currency",
        "contact.name",
        "event.name",
    }
)


def _attr_get(attributes: dict[str, Any], *names: str) -> Any:
    """Read a flattened attribute by exact or case-insensitive key."""
    for name in names:
        if name in attributes:
            return attributes[name]
        lower = name.lower()
        for key, value in attributes.items():
            if key.lower() == lower or key.lower().endswith(f".{lower}"):
                return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return None


def _pick_financial_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    picked: dict[str, Any] = {}
    for key, value in attributes.items():
        if value in (None, "", [], {}):
            continue
        key_lower = key.lower()
        if any(
            key_lower == token or key_lower.endswith(f".{token}")
            for token in _WA_FINANCIAL_ATTR_KEYS
        ):
            if isinstance(value, list) and len(value) > 3:
                picked[key] = value[:3]
            else:
                picked[key] = value
    return picked


def _month_key(date_value: Any) -> str | None:
    if not date_value:
        return None
    text = str(date_value)
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    return None


def _aggregate_wa_entity(entity_name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute financial rollups so the LLM sees totals even when records are sampled."""
    aggregates: dict[str, Any] = {"record_count": len(records)}

    if entity_name == "invoices":
        total_value = 0.0
        paid_value = 0.0
        unpaid_value = 0.0
        paid_count = 0
        unpaid_count = 0
        by_order_type: dict[str, float] = defaultdict(float)
        by_month: dict[str, float] = defaultdict(float)

        for record in records:
            attrs = record.get("attributes") or {}
            value = _to_float(_attr_get(attrs, "Value", "value")) or 0.0
            is_paid = _to_bool(_attr_get(attrs, "IsPaid", "ispaid"))
            order_type = _attr_get(attrs, "OrderType", "ordertype") or "Unknown"
            month = _month_key(_attr_get(attrs, "DocumentDate", "documentdate", "CreatedDate"))
            total_value += value
            by_order_type[str(order_type)] += value
            if month:
                by_month[month] += value
            if is_paid is True:
                paid_count += 1
                paid_value += _to_float(_attr_get(attrs, "PaidAmount", "paidamount")) or value
            elif is_paid is False:
                unpaid_count += 1
                unpaid_value += value

        aggregates.update(
            {
                "total_value": round(total_value, 2),
                "paid_count": paid_count,
                "unpaid_count": unpaid_count,
                "paid_value": round(paid_value, 2),
                "unpaid_value": round(unpaid_value, 2),
                "by_order_type": dict(by_order_type),
                "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
            }
        )

    elif entity_name == "payments":
        total_amount = 0.0
        by_month: dict[str, float] = defaultdict(float)
        for record in records:
            attrs = record.get("attributes") or {}
            amount = _to_float(_attr_get(attrs, "Value", "value", "Amount", "amount"))
            if amount is not None:
                total_amount += amount
                month = _month_key(_attr_get(attrs, "DocumentDate", "documentdate", "CreatedDate"))
                if month:
                    by_month[month] += amount
        aggregates["total_amount"] = round(total_amount, 2)
        aggregates["by_month"] = {k: round(v, 2) for k, v in sorted(by_month.items())}

    elif entity_name == "donations":
        total_amount = 0.0
        by_month: dict[str, float] = defaultdict(float)
        for record in records:
            attrs = record.get("attributes") or {}
            amount = _to_float(_attr_get(attrs, "Value", "value", "Amount", "amount"))
            if amount is not None:
                total_amount += amount
                month = _month_key(_attr_get(attrs, "DocumentDate", "documentdate", "CreatedDate"))
                if month:
                    by_month[month] += amount
        aggregates["total_amount"] = round(total_amount, 2)
        aggregates["by_month"] = {k: round(v, 2) for k, v in sorted(by_month.items())}

    elif entity_name == "event_registrations":
        by_status: dict[str, int] = defaultdict(int)
        paid_count = 0
        for record in records:
            attrs = record.get("attributes") or {}
            status = _attr_get(attrs, "Status", "status") or "Unknown"
            by_status[str(status)] += 1
            if str(status).lower() == "paid":
                paid_count += 1
        aggregates["by_status"] = dict(by_status)
        aggregates["paid_count"] = paid_count

    return aggregates


def _sample_wa_records(
    entity_name: str,
    records: list[dict[str, Any]],
    *,
    max_records: int,
    max_financial_records: int,
) -> tuple[list[dict[str, Any]], bool]:
    limit = (
        max_financial_records
        if entity_name in _WA_FINANCIAL_ENTITIES
        else max_records
    )
    truncated = len(records) > limit
    sample: list[dict[str, Any]] = []

    for record in records[:limit]:
        if not isinstance(record, dict):
            continue
        sample.append(
            {
                "entity_id": record.get("entity_id"),
                "display_name": record.get("display_name"),
                "attributes": _pick_financial_attributes(record.get("attributes") or {}),
            }
        )

    return sample, truncated


def prepare_wildapricot_for_llm(
    wildapricot_data: dict[str, Any],
    *,
    max_records_per_entity: int,
    max_financial_records_per_entity: int,
) -> dict[str, Any]:
    """
    WildApricot LLM payload: full financial aggregates plus representative transaction samples.
    """
    entities = wildapricot_data.get("data") or {}
    entity_blocks: dict[str, Any] = {}

    for entity_name, entity_block in entities.items():
        if not isinstance(entity_block, dict):
            continue

        records = entity_block.get("records") or []
        total_count = entity_block.get("record_count", len(records))
        sample, truncated = _sample_wa_records(
            entity_name,
            records,
            max_records=max_records_per_entity,
            max_financial_records=max_financial_records_per_entity,
        )

        entity_blocks[entity_name] = {
            "entity_type": entity_name,
            "record_count": total_count,
            "records_in_prompt": len(sample),
            "records_truncated": truncated,
            "aggregates": _aggregate_wa_entity(entity_name, records),
            "sample_records": sample,
        }

    for entity_name, block in entity_blocks.items():
        block["formatted_report"] = WildApricotProcessor.format_entity_block(
            entity_name,
            record_count=block.get("record_count", 0),
            records_in_prompt=block.get("records_in_prompt", 0),
            records_truncated=bool(block.get("records_truncated")),
            aggregates=block.get("aggregates") or {},
            sample_records=block.get("sample_records") or [],
        )

    formatted_report = WildApricotProcessor.format_wildapricot_report(
        account_id=wildapricot_data.get("account_id"),
        fetched_at=wildapricot_data.get("fetched_at"),
        entity_blocks=entity_blocks,
    )

    return {
        "account_id": wildapricot_data.get("account_id"),
        "fetched_at": wildapricot_data.get("fetched_at"),
        "formatted_report": formatted_report,
        "entities": {
            entity_name: {
                "entity_type": block.get("entity_type"),
                "record_count": block.get("record_count"),
                "records_in_prompt": block.get("records_in_prompt"),
                "records_truncated": block.get("records_truncated"),
                "formatted_report": block.get("formatted_report") or "",
            }
            for entity_name, block in entity_blocks.items()
        },
    }


def _prepare_quickbooks_report_block(report: dict[str, Any]) -> dict[str, Any]:
    rows = report.get("rows") or []
    metadata = report.get("metadata") or {}
    report_name = metadata.get("report_name") if isinstance(metadata, dict) else None
    totals = extract_quickbooks_totals(rows, report_name)
    block: dict[str, Any] = {
        "metadata": metadata,
        "totals": totals,
        "formatted_report": report.get("formatted_report") or "",
        "row_count": len(rows),
        "top_rows": _top_quickbooks_rows(rows),
    }
    if report.get("error"):
        block["error"] = report["error"]
    return block


def prepare_quickbooks_for_llm(quickbooks_data: dict[str, Any]) -> dict[str, Any]:
    """Pass postprocessed QuickBooks reports with totals and row samples for LLM prompts."""
    pl = quickbooks_data.get("profit_and_loss") or {}
    bs = quickbooks_data.get("balance_sheet") or {}
    return {
        "profit_and_loss": _prepare_quickbooks_report_block(pl),
        "balance_sheet": _prepare_quickbooks_report_block(bs),
    }


def assess_qb_data_quality(
    wildapricot_data: dict[str, Any],
    quickbooks_data: dict[str, Any],
) -> list[str]:
    """Return pre-flight warnings when QuickBooks sandbox data looks incomplete."""
    warnings: list[str] = []
    pl = (quickbooks_data.get("profit_and_loss") or {})
    totals = pl.get("totals") or {}
    total_income = totals.get("total_income")
    row_count = pl.get("row_count", 0)

    wa_entities = wildapricot_data.get("entities") or {}
    wa_financial_total = 0.0
    for entity_name, block in wa_entities.items():
        if entity_name not in _WA_FINANCIAL_ENTITIES:
            continue
        aggregates = (block or {}).get("aggregates") or {}
        for key in ("total_value", "total_amount"):
            value = aggregates.get(key)
            if isinstance(value, (int, float)) and value:
                wa_financial_total += float(value)

    if (total_income is None or total_income == 0) and wa_financial_total > 0:
        warnings.append(
            "QB_DATA_SUSPECT: QuickBooks P&L total income is null or zero while "
            "WildApricot shows financial activity. Reports and benchmark scores may be low."
        )
    if row_count == 0 and not pl.get("error"):
        warnings.append(
            "QB_DATA_SUSPECT: QuickBooks Profit & Loss returned no rows for this period."
        )

    bs = (quickbooks_data.get("balance_sheet") or {})
    bs_totals = bs.get("totals") or {}
    if bs_totals.get("total_assets") in (None, 0) and bs.get("row_count", 0) == 0:
        warnings.append(
            "QB_DATA_SUSPECT: QuickBooks Balance Sheet has no usable totals for this period."
        )

    bs_rows = bs.get("top_rows") or []
    row_labels = " ".join(
        str((row or {}).get("account") or "").lower() for row in bs_rows
    )
    if (
        "opening balance equity" in row_labels
        and bs_totals.get("total_assets") not in (None, 0)
        and (bs_totals.get("total_assets") or 0) <= 10000
        and row_count == 0
    ):
        warnings.append(
            "QB_DATA_SUSPECT: QuickBooks balance sheet looks like a sandbox/reset company "
            "(Opening Balance Equity with minimal assets and no P&L activity)."
        )

    return warnings


def build_llm_inputs(
    wildapricot_data: dict[str, Any],
    quickbooks_data: dict[str, Any],
    *,
    max_wa_records_per_entity: int = 50,
    max_wa_financial_records_per_entity: int = 200,
) -> dict[str, dict[str, Any]]:
    """
    Build LLM-facing payloads: aggregated WA + full QB postprocessed reports.
    """
    wa_for_llm = prepare_wildapricot_for_llm(
        wildapricot_data,
        max_records_per_entity=max_wa_records_per_entity,
        max_financial_records_per_entity=max_wa_financial_records_per_entity,
    )
    qb_for_llm = prepare_quickbooks_for_llm(quickbooks_data)

    wa_entities = wa_for_llm.get("entities") or {}
    logger.info(
        "Prepared LLM inputs wa_entities=%s wa_formatted_chars=%s qb_pl_formatted_chars=%s "
        "qb_bs_formatted_chars=%s",
        len(wa_entities),
        len(wa_for_llm.get("formatted_report") or ""),
        len((qb_for_llm.get("profit_and_loss") or {}).get("formatted_report") or ""),
        len((qb_for_llm.get("balance_sheet") or {}).get("formatted_report") or ""),
    )

    return {"wildapricot": wa_for_llm, "quickbooks": qb_for_llm}


# Backwards-compatible alias
build_llm_source_summary = build_llm_inputs

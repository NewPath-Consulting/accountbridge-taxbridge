from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_ENTITY_LABELS: Dict[str, str] = {
    "invoices": "Invoices",
    "payments": "Payments",
    "donations": "Donations",
    "payment_allocations": "Payment Allocations",
    "event_registrations": "Event Registrations",
    "events": "Events",
    "event_details": "Event Details",
    "contacts": "Contacts",
    "membership_levels": "Membership Levels",
    "refunds": "Refunds",
}

_ENTITY_ORDER: tuple[str, ...] = (
    "invoices",
    "payments",
    "donations",
    "payment_allocations",
    "event_registrations",
    "events",
    "contacts",
    "membership_levels",
    "refunds",
)

_SKIP_FORMATTED_ENTITIES = frozenset({"event_details", "account"})


def _attr_get(attributes: dict[str, Any], *names: str) -> Any:
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


def _format_money(value: Any) -> str:
    amount = _to_float(value)
    if amount is None:
        return "(No value)"
    return f"${amount:,.2f}"


def _format_bool(value: Any) -> str | None:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return "Yes"
        if lowered in ("false", "0", "no"):
            return "No"
    return None


def _short_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else text


class WildApricotProcessor:
    def __init__(
        self,
        entity_name: str,
        payload: Dict[str, Any]
    ):
        self.entity_name = entity_name
        self.payload = payload
        logger.debug(f"Initialized WildApricotProcessor for entity '{entity_name}'.")


    def normalize(self) -> Dict[str, Any]:
        logger.info(f"Normalizing records for entity '{self.entity_name}'.")
        records = []
        try:
            items = self._extract_items()
            logger.debug(f"Extracted {len(items)} items for normalization.")
        except Exception as e:
            logger.error(f"Failed to extract items for entity '{self.entity_name}': {e}")
            return {
                "entity_type": self.entity_name,
                "record_count": 0,
                "records": [],
                "error": str(e)
            }

        for idx, item in enumerate(items):
            try:
                normalized = self._normalize_record(item)
                records.append(normalized)
                logger.debug(f"Normalized record {idx + 1}/{len(items)}: {normalized.get('entity_id')}")
            except Exception as e:
                logger.error(f"Error normalizing record {idx + 1}: {e}")
                continue

        result = {
            "entity_type": self.entity_name,
            "record_count": len(records),
            "records": records,
        }
        logger.info(f"Normalization complete. Record count: {len(records)}.")
        return result

    def to_llm_facts(self) -> List[Dict]:
        logger.info(f"Building LLM facts for entity '{self.entity_name}'.")
        facts = []
        try:
            items = self._extract_items()
            logger.debug(f"Extracted {len(items)} items for LLM facts.")
        except Exception as e:
            logger.error(f"Failed to extract items for LLM facts: {e}")
            return []

        for idx, item in enumerate(items):
            try:
                fact = self._build_fact(item)
                facts.append(fact)
                logger.debug(f"Built fact {idx + 1}/{len(items)}: {fact.get('entity_id')}")
            except Exception as e:
                logger.error(f"Error building fact {idx + 1}: {e}")
                continue

        logger.info(f"Built {len(facts)} facts.")
        return facts

    def to_llm_text(self) -> str:
        logger.info(f"Converting facts to LLM text for entity '{self.entity_name}'.")
        lines = []
        try:
            facts = self.to_llm_facts()
        except Exception as e:
            logger.error(f"Failed to convert facts to LLM text: {e}")
            return ""

        for idx, fact in enumerate(facts):
            try:
                parts = []
                for key, value in fact.items():
                    if value is None:
                        continue
                    parts.append(f"{key}={value}")
                line = " | ".join(parts)
                lines.append(line)
                logger.debug(f"LLM text line {idx + 1}: {line}")
            except Exception as e:
                logger.error(f"Error processing LLM text line {idx + 1}: {e}")
                continue

        result_text = "\n".join(lines)
        logger.info("LLM text conversion complete.")
        return result_text

    @staticmethod
    def format_record_line(entity_name: str, record: Dict[str, Any]) -> str:
        entity_id = record.get("entity_id") or "?"
        attrs = record.get("attributes") or {}
        parts: List[str] = [f"**{entity_id}**"]

        display_name = record.get("display_name")
        if display_name:
            parts.append(str(display_name))

        if entity_name == "invoices":
            parts.extend(
                [
                    f"Value: {_format_money(_attr_get(attrs, 'Value', 'value'))}",
                    f"Paid: {_format_bool(_attr_get(attrs, 'IsPaid', 'ispaid')) or 'Unknown'}",
                    str(_attr_get(attrs, "OrderType", "ordertype") or "Unknown type"),
                    _short_date(_attr_get(attrs, "DocumentDate", "documentdate")) or "",
                    str(_attr_get(attrs, "Contact.Name", "Contact.Name") or ""),
                ]
            )
        elif entity_name == "payments":
            parts.extend(
                [
                    f"Value: {_format_money(_attr_get(attrs, 'Value', 'value'))}",
                    str(_attr_get(attrs, "Type", "type") or ""),
                    _short_date(_attr_get(attrs, "DocumentDate", "documentdate")) or "",
                    str(_attr_get(attrs, "Contact.Name") or ""),
                    str(_attr_get(attrs, "Tender.Name") or ""),
                ]
            )
        elif entity_name == "donations":
            parts.extend(
                [
                    f"Value: {_format_money(_attr_get(attrs, 'Value', 'value'))}",
                    str(_attr_get(attrs, "DonationType", "donationtype") or ""),
                    _short_date(
                        _attr_get(attrs, "DonationDate", "donationdate", "DocumentDate")
                    )
                    or "",
                    str(
                        _attr_get(attrs, "FirstName")
                        or _attr_get(attrs, "Contact.Name")
                        or ""
                    ),
                ]
            )
        elif entity_name == "payment_allocations":
            parts.extend(
                [
                    f"Value: {_format_money(_attr_get(attrs, 'Value', 'value'))}",
                    _short_date(_attr_get(attrs, "PaymentDate", "paymentdate")) or "",
                    _short_date(_attr_get(attrs, "InvoiceDate", "invoicedate")) or "",
                    str(_attr_get(attrs, "PaymentType", "paymenttype") or ""),
                    f"Invoice #{_attr_get(attrs, 'InvoiceNumber', 'invoicenumber') or '?'}",
                ]
            )
        elif entity_name == "event_registrations":
            parts.extend(
                [
                    str(_attr_get(attrs, "Status", "status") or "Unknown"),
                    f"Paid: {_format_bool(_attr_get(attrs, 'IsPaid', 'ispaid')) or 'Unknown'}",
                    f"PaidSum: {_format_money(_attr_get(attrs, 'PaidSum', 'paidsum'))}",
                    str(_attr_get(attrs, "Event.Name", "event.name") or ""),
                    str(_attr_get(attrs, "Contact.Name") or ""),
                    _short_date(
                        _attr_get(attrs, "RegistrationDate", "registrationdate")
                    )
                    or "",
                ]
            )
        elif entity_name == "events":
            parts.extend(
                [
                    str(_attr_get(attrs, "Name", "name") or ""),
                    _short_date(_attr_get(attrs, "StartDate", "startdate")) or "",
                    _short_date(_attr_get(attrs, "EndDate", "enddate")) or "",
                    f"Confirmed: {_attr_get(attrs, 'ConfirmedRegistrationsCount') or 0}",
                ]
            )
        elif entity_name == "membership_levels":
            parts.extend(
                [
                    str(_attr_get(attrs, "Name", "name") or ""),
                    str(_attr_get(attrs, "Type", "type") or ""),
                    f"Fee: {_format_money(_attr_get(attrs, 'MembershipFee', 'membershipfee'))}",
                ]
            )
        elif entity_name == "contacts":
            for key in ("Status", "MembershipEnabled", "MemberSince", "RenewalDue"):
                value = _attr_get(attrs, key)
                if value not in (None, ""):
                    parts.append(f"{key}: {value}")
        else:
            for key, value in list(attrs.items())[:6]:
                if value in (None, "", [], {}):
                    continue
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value[:3])
                parts.append(f"{key}: {value}")

        return " | ".join(part for part in parts if part)

    @staticmethod
    def format_aggregates_section(
        entity_name: str,
        aggregates: Dict[str, Any],
    ) -> List[str]:
        lines: List[str] = ["#### Summary"]
        record_count = aggregates.get("record_count", 0)
        lines.append(f"**Records:** {record_count}")

        if entity_name == "invoices":
            lines.append(f"**Total value:** {_format_money(aggregates.get('total_value'))}")
            lines.append(
                f"**Paid:** {aggregates.get('paid_count', 0)} records "
                f"({_format_money(aggregates.get('paid_value'))})"
            )
            lines.append(
                f"**Unpaid:** {aggregates.get('unpaid_count', 0)} records "
                f"({_format_money(aggregates.get('unpaid_value'))})"
            )
            by_order_type = aggregates.get("by_order_type") or {}
            if by_order_type:
                lines.append("")
                lines.append("#### By order type")
                for label, amount in sorted(by_order_type.items()):
                    lines.append(f"- {label}: {_format_money(amount)}")
            by_month = aggregates.get("by_month") or {}
            if by_month:
                lines.append("")
                lines.append("#### By month")
                for month, amount in sorted(by_month.items()):
                    lines.append(f"- {month}: {_format_money(amount)}")

        elif entity_name in ("payments", "donations"):
            total_key = "total_amount" if entity_name == "payments" else "total_amount"
            lines.append(f"**Total amount:** {_format_money(aggregates.get(total_key))}")
            by_month = aggregates.get("by_month") or {}
            if by_month:
                lines.append("")
                lines.append("#### By month")
                for month, amount in sorted(by_month.items()):
                    lines.append(f"- {month}: {_format_money(amount)}")

        elif entity_name == "event_registrations":
            by_status = aggregates.get("by_status") or {}
            if by_status:
                lines.append("**By status:**")
                for status, count in sorted(by_status.items()):
                    lines.append(f"- {status}: {count}")
            lines.append(f"**Paid registrations:** {aggregates.get('paid_count', 0)}")

        return lines

    @staticmethod
    def format_entity_block(
        entity_name: str,
        *,
        record_count: int,
        records_in_prompt: int,
        records_truncated: bool,
        aggregates: Dict[str, Any],
        sample_records: List[Dict[str, Any]],
    ) -> str:
        label = _ENTITY_LABELS.get(entity_name, entity_name.replace("_", " ").title())
        lines = [f"## {label}"]

        if record_count == 0:
            lines.append("*(No records)*")
            return "\n".join(lines)

        if records_truncated:
            shown = f"showing {records_in_prompt} of {record_count}"
        else:
            shown = f"{record_count} total"
        lines.append(f"**Records:** {shown}")
        lines.append("")
        lines.extend(WildApricotProcessor.format_aggregates_section(entity_name, aggregates))

        if sample_records:
            lines.append("")
            lines.append("#### Records")
            for record in sample_records:
                lines.append(f"- {WildApricotProcessor.format_record_line(entity_name, record)}")

        return "\n".join(lines)

    @staticmethod
    def format_wildapricot_report(
        *,
        account_id: Any,
        fetched_at: Any,
        entity_blocks: Dict[str, Dict[str, Any]],
    ) -> str:
        lines = ["# WildApricot Data", ""]
        if account_id is not None:
            lines.append(f"**Account ID:** {account_id}")
        if fetched_at:
            lines.append(f"**Fetched at:** {fetched_at}")
        lines.append("")

        ordered_names = list(_ENTITY_ORDER) + [
            name for name in entity_blocks if name not in _ENTITY_ORDER
        ]
        sections: List[str] = []
        for entity_name in ordered_names:
            if entity_name in _SKIP_FORMATTED_ENTITIES:
                continue
            block = entity_blocks.get(entity_name)
            if not isinstance(block, dict):
                continue
            section = WildApricotProcessor.format_entity_block(
                entity_name,
                record_count=block.get("record_count", 0),
                records_in_prompt=block.get("records_in_prompt", 0),
                records_truncated=bool(block.get("records_truncated")),
                aggregates=block.get("aggregates") or {},
                sample_records=block.get("sample_records") or [],
            )
            sections.append(section)

        lines.extend(section for section in sections if section)
        return "\n".join(lines)


    def _extract_items(self):
        logger.debug(f"Extracting items from payload for entity '{self.entity_name}'.")

        if not self.payload:
            logger.error("Payload is empty.")
            raise ValueError("Empty payload; nothing to extract.")

        try:
            if isinstance(self.payload, list):
                logger.debug("Payload is a list.")
                return self.payload

            for key in ["Contacts", "Donations", "Invoices", "Payments", "Events"]:
                if key in self.payload:
                    items = self.payload[key]
                    logger.debug(f"Found '{key}' in payload; extracting {len(items)} items.")
                    return items

            if "Contacts" not in self.payload and "Items" in self.payload:
                items = self.payload["Items"]
                logger.debug("Found 'Items' in payload (no 'Contacts'); extracting items.")
                return items

            logger.debug("Payload did not match known keys; returning payload as single-item list.")
            return [self.payload]
        except Exception as e:
            logger.error(f"Exception in _extract_items: {e}")
            raise

    def _normalize_record(
        self,
        item: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            normalized = {
                "entity_type": self.entity_name,
                "entity_id": item.get("Id"),
                "display_name": self._extract_name(item),
                "attributes": self._flatten(item),
            }
            logger.debug(f"Normalized record: {normalized}")
            return normalized
        except Exception as e:
            logger.error(f"Failed to normalize record: {e}")
            raise

    def _build_fact(
        self,
        item: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            flat = self._flatten(item)
            fact = {
                "entity_type": self.entity_name,
                "entity_id": item.get("Id"),
                "name": self._extract_name(item),
            }
            for key, value in flat.items():
                if value in [None, "", []]:
                    continue
                fact[key] = value
            logger.debug(f"Built fact: {fact}")
            return fact
        except Exception as e:
            logger.error(f"Failed to build fact: {e}")
            raise

    def _extract_name(
        self,
        item: Dict[str, Any]
    ):
        try:
            candidates = [
                "DisplayName",
                "Name",
                "ContactName",
                "FirstName",
                "EventTitle",
                "Title",
            ]

            for field in candidates:
                name = item.get(field)
                if name:
                    logger.debug(f"Extracted name using '{field}': {name}")
                    return name

            first = item.get("FirstName")
            last = item.get("LastName")
            if first or last:
                full_name = f"{first or ''} {last or ''}".strip()
                logger.debug(f"Constructed name from FirstName/LastName: {full_name}")
                return full_name

            logger.debug("No suitable name found in item.")
            return None
        except Exception as e:
            logger.error(f"Failed to extract name: {e}")
            return None

    def _flatten(
        self,
        obj: Any,
        prefix: str = ""
    ):
        result = {}
        try:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_key = f"{prefix}.{key}" if prefix else key
                    result.update(self._flatten(value, new_key))
            elif isinstance(obj, list):
                values = []
                for item in obj:
                    if isinstance(item, dict):
                        if "Value" in item:
                            values.append(item["Value"])
                        elif "Label" in item:
                            values.append(item["Label"])
                        else:
                            try:
                                values.append(json.dumps(item))
                            except Exception as e:
                                logger.error(f"Error serializing dict in list: {e}")
                                values.append(str(item))
                    else:
                        values.append(item)
                result[prefix] = values
            else:
                result[prefix] = obj
            logger.debug(f"Flattened object at prefix='{prefix}': {result}")
            return result
        except Exception as e:
            logger.error(f"Exception during flatten for prefix '{prefix}': {e}")
            return {}


def postprocess_wildapricot_data(wildapricot_data: Dict[str, Any]) -> Dict[str, Any]:
    """Clean WildApricot extraction payload for downstream LLM use."""
    raw_entities = wildapricot_data.get("data") or {}
    processed_entities: Dict[str, Any] = {}

    for entity_name, items in raw_entities.items():
        if not isinstance(items, list):
            logger.warning(
                "Skipping WildApricot entity %s: expected list, got %s",
                entity_name,
                type(items).__name__,
            )
            continue

        processor = WildApricotProcessor(entity_name, items)
        processed_entities[entity_name] = processor.normalize()
        logger.info(
            "Postprocessed WildApricot %s records=%s",
            entity_name,
            processed_entities[entity_name].get("record_count", 0),
        )

    return {
        **{key: value for key, value in wildapricot_data.items() if key != "data"},
        "data": processed_entities,
    }
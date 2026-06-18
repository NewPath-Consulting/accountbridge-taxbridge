"""Flatten nested WildApricot API JSON records for CSV export."""

from __future__ import annotations

import json
from typing import Any

# Keys whose string values are truncated when flattening (Excel-friendly).
_TRUNCATE_KEYS = frozenset(
    {
        "DescriptionHtml",
        "Description",
        "FieldInstructions",
        "Text",
        "Memo",
    }
)
_DEFAULT_TRUNCATE_LEN = 500


def truncate_text(value: Any, max_len: int = _DEFAULT_TRUNCATE_LEN) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _is_primitive(item: Any) -> bool:
    return item is None or isinstance(item, (str, int, float, bool))


def _format_primitive_list(items: list[Any]) -> str:
    return "|".join("" if x is None else str(x) for x in items)


def flatten_record(
    obj: dict[str, Any],
    *,
    prefix: str = "",
    max_depth: int = 4,
    depth: int = 0,
    skip_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    Flatten a nested dict for tabular export.

    - Nested dicts: Parent_Child keys
    - Lists of primitives: pipe-separated
    - Lists of objects / max depth: omitted (use extract_child_table instead)
    """
    skip = skip_keys or frozenset()
    flat: dict[str, Any] = {}

    for key, value in obj.items():
        if key in skip:
            continue
        col = f"{prefix}_{key}" if prefix else key

        if isinstance(value, dict):
            if depth + 1 >= max_depth:
                flat[col] = json.dumps(value, default=str)
            else:
                flat.update(
                    flatten_record(
                        value,
                        prefix=col,
                        max_depth=max_depth,
                        depth=depth + 1,
                        skip_keys=skip,
                    )
                )
        elif isinstance(value, list):
            if not value:
                flat[col] = ""
            elif all(_is_primitive(x) for x in value):
                flat[col] = _format_primitive_list(value)
            elif depth + 1 >= max_depth:
                flat[col] = json.dumps(value, default=str)
            # else: skip; extracted via extract_child_table
        else:
            if isinstance(value, str) and key in _TRUNCATE_KEYS:
                flat[col] = truncate_text(value)
            else:
                flat[col] = value

    return flat


def _column_order(fieldnames: list[str]) -> list[str]:
    priority = ("Id", "id", "Name", "name", "Url", "url")
    ordered: list[str] = []
    for p in priority:
        if p in fieldnames and p not in ordered:
            ordered.append(p)
    for f in sorted(fieldnames):
        if f not in ordered:
            ordered.append(f)
    return ordered


def records_to_rows(
    items: list[dict[str, Any]],
    *,
    skip_keys: frozenset[str] | None = None,
    max_depth: int = 4,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Flatten a list of records; return (column_names, rows)."""
    rows: list[dict[str, Any]] = []
    all_keys: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        row = flatten_record(item, skip_keys=skip_keys, max_depth=max_depth)
        rows.append(row)
        all_keys.update(row.keys())

    fieldnames = _column_order(list(all_keys))
    return fieldnames, rows


def extract_child_table(
    items: list[dict[str, Any]],
    array_key: str,
    *,
    parent_id_key: str = "Id",
    parent_id_column: str | None = None,
) -> list[dict[str, Any]]:
    """
    Pull nested array items into long-format rows linked to parent Id.

    Example: donations FieldValues -> donation_id, FieldName, Value, ...
    """
    parent_col = parent_id_column or f"{parent_id_key.lower()}_parent_id"
    child_rows: list[dict[str, Any]] = []

    for parent in items:
        if not isinstance(parent, dict):
            continue
        parent_id = parent.get(parent_id_key) or parent.get(parent_id_key.lower())
        children = parent.get(array_key)
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            row = {parent_col: parent_id, **flatten_record(child, max_depth=2)}
            child_rows.append(row)

    return child_rows

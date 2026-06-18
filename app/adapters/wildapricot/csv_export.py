"""Export WildApricot supporting-source extraction to structured CSV files."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from app.adapters.wildapricot.flatten import extract_child_table, records_to_rows
from app.config.settings import Settings, settings

logger = logging.getLogger(__name__)

_MANIFEST_FILE = "_manifest.csv"
_CONTACTS_NOTE = (
    "Membership/contacts; rows may be async query jobs (ResultId/State) until polling is added"
)

# CSV export order matches workflow priority
_CSV_RESOURCES: list[tuple[str, frozenset[str] | None, str]] = [
    ("invoices", None, "Revenue validation"),
    ("payments", None, "Revenue validation"),
    ("contacts", None, _CONTACTS_NOTE),
    ("events", None, "Program metrics and event participation"),
    ("event_registrations", None, "Event participation"),
    ("donations", frozenset({"FieldValues"}), "Program metrics and donor activity"),
]


def _write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: "" if row.get(k) is None else row.get(k) for k in fieldnames}
            )
    return len(rows)


def _write_list_resource(
    output_dir: Path,
    name: str,
    items: list[Any],
    *,
    skip_keys: frozenset[str] | None = None,
    notes: str = "",
) -> tuple[str, int, str]:
    if not isinstance(items, list):
        items = []
    dict_items = [x for x in items if isinstance(x, dict)]
    fieldnames, rows = records_to_rows(dict_items, skip_keys=skip_keys)
    if not fieldnames:
        fieldnames = ["_empty"]
        rows = []
    count = _write_csv(output_dir / f"{name}.csv", fieldnames, rows)
    return f"{name}.csv", count, notes


def _export_donations_field_values(
    output_dir: Path,
    donations: list[dict[str, Any]],
) -> tuple[str, int, str]:
    fv_rows = extract_child_table(
        donations,
        "FieldValues",
        parent_id_key="Id",
        parent_id_column="donation_id",
    )
    if not fv_rows:
        return "donations_field_values.csv", 0, "No FieldValues rows"
    fv_fields, fv_flat = records_to_rows(fv_rows, max_depth=2)
    count = _write_csv(output_dir / "donations_field_values.csv", fv_fields, fv_flat)
    return (
        "donations_field_values.csv",
        count,
        "Donation custom field values (long format)",
    )


def _export_identifiers(output_dir: Path, identifiers: Any) -> tuple[str, int, str]:
    rows: list[dict[str, Any]] = []
    if isinstance(identifiers, dict):
        for resource, ids in identifiers.items():
            if isinstance(ids, list):
                for id_val in ids:
                    rows.append({"resource": resource, "id": id_val})
            else:
                rows.append({"resource": resource, "id": ids})
    count = _write_csv(output_dir / "identifiers.csv", ["resource", "id"], rows)
    return "identifiers.csv", count, "Traceability IDs"


def export_extraction_to_csv(
    result: dict[str, Any],
    output_dir: str | Path | None = None,
    *,
    app_settings: Settings | None = None,
) -> Path:
    """Write one CSV per supporting-source API under ``result[\"data\"]``."""
    cfg = app_settings or settings
    json_path = result.get("export_file")
    if output_dir is not None:
        out_dir = Path(output_dir)
    elif json_path:
        out_dir = Path(json_path).parent / f"{Path(json_path).stem}_csv"
    else:
        account_id = result.get("account_id", "unknown")
        out_dir = Path(cfg.WILDAPRICOT_EXPORT_DIR) / f"wildapricot_account_{account_id}_csv"

    out_dir.mkdir(parents=True, exist_ok=True)
    data = result.get("data") or {}
    manifest_rows: list[tuple[str, int, str]] = []

    for name, skip_keys, note in _CSV_RESOURCES:
        payload = data.get(name, [])
        manifest_rows.append(
            _write_list_resource(out_dir, name, payload, skip_keys=skip_keys, notes=note)
        )
        if name == "donations":
            dict_donations = [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []
            manifest_rows.append(_export_donations_field_values(out_dir, dict_donations))

    warnings = result.get("warnings") or []
    manifest_rows.append(
        _write_list_resource(out_dir, "warnings", warnings, notes="Workflow warnings")
    )
    manifest_rows.append(_export_identifiers(out_dir, result.get("identifiers")))

    _write_csv(
        out_dir / _MANIFEST_FILE,
        ["file", "row_count", "notes"],
        [{"file": f, "row_count": c, "notes": n} for f, c, n in manifest_rows],
    )

    logger.info("WildApricot CSV export written to %s", out_dir)
    return out_dir.resolve()


def load_extraction_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def main_cli() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Export WildApricot supporting-source JSON to CSV",
    )
    parser.add_argument("json_path", type=Path)
    parser.add_argument("-o", "--output-dir", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    json_path = args.json_path.resolve()
    if not json_path.is_file():
        logger.error("File not found: %s", json_path)
        return 1

    result = load_extraction_json(json_path)
    if "export_file" not in result:
        result["export_file"] = str(json_path)

    out_dir = export_extraction_to_csv(result, output_dir=args.output_dir)
    print(f"CSV export written to: {out_dir}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main_cli())

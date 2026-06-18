"""Persist WildApricot extraction results to JSON for analysis."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import Settings, settings

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency at module load
def _csv_exporter():
    from app.adapters.wildapricot.csv_export import export_extraction_to_csv

    return export_extraction_to_csv


def default_export_path(
    account_id: int | str,
    *,
    export_dir: str | Path | None = None,
    app_settings: Settings | None = None,
) -> Path:
    cfg = app_settings or settings
    base = Path(export_dir or cfg.WILDAPRICOT_EXPORT_DIR)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"wildapricot_account_{account_id}_{timestamp}.json"
    return base / filename


def save_extraction_to_json(
    result: dict[str, Any],
    path: str | Path | None = None,
    *,
    export_dir: str | Path | None = None,
    app_settings: Settings | None = None,
    indent: int = 2,
) -> Path:
    """
    Write the full workflow result (all API responses under ``data``) to a JSON file.

    Returns the path written.
    """
    cfg = app_settings or settings
    account_id = result.get("account_id", "unknown")

    if path is not None:
        out_path = Path(path)
    elif cfg.WILDAPRICOT_EXPORT_JSON:
        out_path = Path(cfg.WILDAPRICOT_EXPORT_JSON)
    else:
        out_path = default_export_path(
            account_id,
            export_dir=export_dir,
            app_settings=cfg,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        **result,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "export_file": str(out_path.resolve()),
    }

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=indent, ensure_ascii=False, default=str)

    logger.info("WildApricot extraction saved to %s", out_path)
    return out_path.resolve()


def save_extraction_exports(
    result: dict[str, Any],
    *,
    path: str | Path | None = None,
    export_dir: str | Path | None = None,
    app_settings: Settings | None = None,
    save_json: bool = True,
    save_csv: bool | None = None,
    indent: int = 2,
) -> dict[str, Path]:
    """
    Save JSON and optionally CSV exports. Returns paths written.
    """
    cfg = app_settings or settings
    paths: dict[str, Path] = {}
    payload = dict(result)

    if save_json:
        json_path = save_extraction_to_json(
            payload,
            path=path,
            export_dir=export_dir,
            app_settings=cfg,
            indent=indent,
        )
        paths["json"] = json_path
        payload["export_file"] = str(json_path)

    do_csv = save_csv if save_csv is not None else cfg.WILDAPRICOT_EXPORT_CSV
    if do_csv:
        csv_dir = _csv_exporter()(
            payload,
            output_dir=None,
            app_settings=cfg,
        )
        paths["csv_dir"] = csv_dir

    return paths

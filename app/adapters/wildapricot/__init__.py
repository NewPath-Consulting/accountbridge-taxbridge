"""WildApricot Admin API v2 client adapter."""

from app.adapters.wildapricot.auth import TokenManager
from app.adapters.wildapricot.client import WildApricotClient
from app.adapters.wildapricot.exceptions import (
    WildApricotAPIError,
    WildApricotAuthError,
    WildApricotError,
)
from app.adapters.wildapricot.models import PermissionInfo, TokenBundle
from app.adapters.wildapricot.resources import SUPPORTED_RESOURCES, WildApricotResources
from app.adapters.wildapricot.csv_export import export_extraction_to_csv, load_extraction_json
from app.adapters.wildapricot.export import (
    default_export_path,
    save_extraction_exports,
    save_extraction_to_json,
)
from app.adapters.wildapricot.workflow import pluck_ids, run_extraction_workflow

__all__ = [
    "TokenManager",
    "WildApricotClient",
    "WildApricotError",
    "WildApricotAuthError",
    "WildApricotAPIError",
    "TokenBundle",
    "PermissionInfo",
    "WildApricotResources",
    "SUPPORTED_RESOURCES",
    "save_extraction_to_json",
    "save_extraction_exports",
    "export_extraction_to_csv",
    "load_extraction_json",
    "default_export_path",
    "run_extraction_workflow",
    "pluck_ids",
]

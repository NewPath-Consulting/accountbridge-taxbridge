import streamlit as st

import filing_tab, run_progress
import requests
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BENCHMARK_REPORT_KEYS = ("cash_flow", "tax_return", "balance_sheet")
MAX_BENCHMARK_REFERENCE_DOCS = 3
DEFAULT_API_BASE_URL = "http://localhost:8000"
UI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = UI_DIR.parent
_PLACEHOLDER_API_URLS = {
    "https://api.example.com",
    "http://api.example.com",
    "api.example.com",
}
DEFAULT_WILDAPRICOT_ACCOUNT_ID = "497705"
DEFAULT_QUICKBOOKS_REALM_ID = "9130356628667026"
_PLACEHOLDER_ID_VALUES = {
    "string",
    "your_account_id",
    "your-account-id",
    "your_realm_id",
    "your-realm-id",
}

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(UI_DIR / ".env", override=True)

# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="TaxBridge · Reports → Prepare → File",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# Custom CSS
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Theme-aware tokens — inherit Streamlit light/dark variables */
    .stApp {
        --ab-border: color-mix(in srgb, var(--text-color) 18%, transparent);
        --ab-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
        --ab-surface: var(--secondary-background-color);
        --ab-surface-elevated: color-mix(in srgb, var(--text-color) 4%, var(--background-color));
    }

    /* Let Streamlit control app/sidebar backgrounds; avoid overriding button label <p> tags */
    .stApp h1, .stApp h2, .stApp h3,
    .stApp .main .block-container > div p,
    .stApp [data-testid="stSidebar"] p,
    .stApp li, .stApp label {
        color: var(--text-color);
    }

    .ab-subtitle {
        color: var(--ab-muted);
        margin-top: -0.5rem;
    }

    /* ---- cards ---- */
    .card {
        background: var(--ab-surface);
        border: 1px solid var(--ab-border);
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        color: var(--text-color);
    }
    .card-success { border-left: 4px solid #22c55e; }
    .card-info    { border-left: 4px solid var(--primary-color); }
    .card-warn    { border-left: 4px solid #f59e0b; }
    .card-error   { border-left: 4px solid #ef4444; }

    /* ---- status badges ---- */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.03em;
    }
    .badge-green  { background: #dcfce7; color: #166534; }
    .badge-blue   { background: #dbeafe; color: #1d4ed8; }
    .badge-red    { background: #fee2e2; color: #b91c1c; }
    .badge-yellow { background: #fef3c7; color: #b45309; }
    .stApp[data-theme="dark"] .badge-green  { background: #14532d; color: #4ade80; }
    .stApp[data-theme="dark"] .badge-blue   { background: #1e3a5f; color: #60a5fa; }
    .stApp[data-theme="dark"] .badge-red    { background: #450a0a; color: #f87171; }
    .stApp[data-theme="dark"] .badge-yellow { background: #451a03; color: #fbbf24; }

    /* ---- metric tiles ---- */
    .metric-tile {
        background: var(--ab-surface-elevated);
        border: 1px solid var(--ab-border);
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .metric-tile .value {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--text-color);
    }
    .metric-tile .label {
        font-size: 0.75rem;
        color: var(--ab-muted);
        margin-top: 2px;
    }

    /* ---- step indicator ---- */
    .step-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
    .step-label { color: var(--text-color); font-size: 0.85rem; opacity: 0.85; }
    .step-num {
        width: 26px; height: 26px;
        border-radius: 50%;
        background: var(--primary-color);
        color: #fff;
        font-size: 0.75rem;
        font-weight: 700;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
    }
    .step-num.done  { background: #22c55e; }
    .step-num.idle {
        background: #e2e8f0;
        color: #475569;
    }
    .stApp[data-theme="dark"] .step-num.idle {
        background: #334155;
        color: #e2e8f0;
    }

    /* ---- action buttons (visible in light + dark) ---- */
    /* Streamlit 1.36 uses .stButton; newer versions also use data-testid="stButton" */
    .stApp .stButton > button,
    .stApp div[data-testid="stButton"] > button {
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.02em;
        border-radius: 0.5rem !important;
        min-height: 2.75rem;
        box-shadow: none !important;
    }

    /* Primary: Save & Run, Run Reports, Run Benchmark */
    .stApp .stButton > button[kind="primary"],
    .stApp .stButton > button[data-testid="stBaseButton-primary"],
    .stApp .stButton > button[data-testid="baseButton-primary"],
    .stApp div[data-testid="stButton"] > button[kind="primary"],
    .stApp button[data-testid="stBaseButton-primary"],
    .stApp button[data-testid="baseButton-primary"] {
        background-color: #2563eb !important;
        background-image: none !important;
        border: 2px solid #1d4ed8 !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    .stApp[data-theme="dark"] .stButton > button[kind="primary"],
    .stApp[data-theme="dark"] .stButton > button[data-testid="stBaseButton-primary"],
    .stApp[data-theme="dark"] .stButton > button[data-testid="baseButton-primary"],
    .stApp[data-theme="dark"] div[data-testid="stButton"] > button[kind="primary"],
    .stApp[data-theme="dark"] button[data-testid="stBaseButton-primary"],
    .stApp[data-theme="dark"] button[data-testid="baseButton-primary"] {
        background-color: #3b82f6 !important;
        border-color: #93c5fd !important;
    }
    .stApp .stButton > button[kind="primary"] *,
    .stApp .stButton > button[data-testid="stBaseButton-primary"] *,
    .stApp .stButton > button[data-testid="baseButton-primary"] *,
    .stApp div[data-testid="stButton"] > button[kind="primary"] *,
    .stApp button[data-testid="stBaseButton-primary"] *,
    .stApp button[data-testid="baseButton-primary"] * {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        font-weight: 700 !important;
    }
    .stApp .stButton > button[kind="primary"]:hover,
    .stApp .stButton > button[data-testid="stBaseButton-primary"]:hover,
    .stApp div[data-testid="stButton"] > button[kind="primary"]:hover,
    .stApp button[data-testid="stBaseButton-primary"]:hover,
    .stApp button[data-testid="baseButton-primary"]:hover {
        background-color: #1d4ed8 !important;
        border-color: #1e3a8a !important;
        color: #ffffff !important;
    }

    /* Per-key fallbacks (Streamlit 1.41+) */
    .stApp .st-key-save_and_run_reports button,
    .stApp .st-key-run_reports_btn button,
    .stApp .st-key-run_benchmark_btn button {
        background-color: #2563eb !important;
        border: 2px solid #1d4ed8 !important;
        color: #ffffff !important;
    }
    .stApp .st-key-save_and_run_reports button *,
    .stApp .st-key-run_reports_btn button *,
    .stApp .st-key-run_benchmark_btn button * {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        font-weight: 700 !important;
    }

    /* Secondary / default: Refresh, Reset, etc. */
    .stApp .stButton > button[kind="secondary"],
    .stApp .stButton > button[data-testid="stBaseButton-secondary"],
    .stApp .stButton > button[data-testid="baseButton-secondary"],
    .stApp div[data-testid="stButton"] > button[kind="secondary"],
    .stApp button[data-testid="stBaseButton-secondary"],
    .stApp button[data-testid="baseButton-secondary"] {
        background-color: #e2e8f0 !important;
        background-image: none !important;
        border: 2px solid #475569 !important;
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
    }
    .stApp[data-theme="dark"] .stButton > button[kind="secondary"],
    .stApp[data-theme="dark"] .stButton > button[data-testid="stBaseButton-secondary"],
    .stApp[data-theme="dark"] div[data-testid="stButton"] > button[kind="secondary"],
    .stApp[data-theme="dark"] button[data-testid="stBaseButton-secondary"],
    .stApp[data-theme="dark"] button[data-testid="baseButton-secondary"] {
        background-color: #1e293b !important;
        border-color: #94a3b8 !important;
        color: #f8fafc !important;
        -webkit-text-fill-color: #f8fafc !important;
    }
    .stApp .stButton > button[kind="secondary"] *,
    .stApp .stButton > button[data-testid="stBaseButton-secondary"] *,
    .stApp button[data-testid="stBaseButton-secondary"] * {
        color: inherit !important;
        -webkit-text-fill-color: inherit !important;
        font-weight: 700 !important;
    }
    .stApp .stButton > button[kind="secondary"]:hover,
    .stApp .stButton > button[data-testid="stBaseButton-secondary"]:hover {
        background-color: #cbd5e1 !important;
        border-color: #334155 !important;
    }
    .stApp[data-theme="dark"] .stButton > button[kind="secondary"]:hover,
    .stApp[data-theme="dark"] .stButton > button[data-testid="stBaseButton-secondary"]:hover {
        background-color: #334155 !important;
        border-color: #cbd5e1 !important;
    }

    /* Disabled buttons */
    .stApp .stButton > button:disabled,
    .stApp div[data-testid="stButton"] > button:disabled {
        opacity: 0.55 !important;
        cursor: not-allowed !important;
    }
    .stApp .stButton > button[kind="primary"]:disabled,
    .stApp button[data-testid="stBaseButton-primary"]:disabled {
        background-color: #94a3b8 !important;
        border-color: #64748b !important;
        color: #ffffff !important;
    }
    .stApp .stButton > button[kind="primary"]:disabled * {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

QUICKBOOKS_PLAYGROUND_URL = "https://developer.intuit.com/app/developer/playground"


class QuickBooksRefreshTokenRequired(Exception):
    """Raised when the API needs a new QuickBooks refresh token."""

    def __init__(self, detail: dict) -> None:
        self.detail = detail
        super().__init__(detail.get("message", "QuickBooks refresh token required"))


# ──────────────────────────────────────────────
# Session state defaults
# ──────────────────────────────────────────────
def _init_state():
    defaults = {
        "reports_response": None,
        "reports_context": None,
        "stored_reports": None,
        "benchmark_response": None,
        "step": 0,
        "reports_elapsed": None,
        "benchmark_elapsed": None,
        "available_reports": None,
        "available_reports_error": None,
        "selected_report_files": [],
        "pending_wildapricot_data": None,
        "qb_credentials_error": None,
        "user_prompt": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def badge(text: str, kind: str = "blue") -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'


def env_value(key: str, default: str = "") -> str:
    """Read a trimmed .env value (strips surrounding quotes)."""
    value = os.getenv(key, default) or default
    return value.strip().strip("'\"")


def resolve_api_base_url() -> str:
    """Use localhost by default; ignore placeholder API_BASE_URL values."""
    env_url = env_value("API_BASE_URL").rstrip("/")
    if not env_url or env_url in _PLACEHOLDER_API_URLS:
        return DEFAULT_API_BASE_URL
    return env_url


def resolve_bearer_token() -> str:
    """Bearer token from .env (must match API server BEARER_TOKEN)."""
    return env_value("BEARER_TOKEN")


def resolve_wildapricot_account_id() -> str:
    """Fixed data source ID — edit only in ui/.env (falls back to project .env defaults)."""
    value = env_value("WILDAPRICOT_ACCOUNT_ID", DEFAULT_WILDAPRICOT_ACCOUNT_ID)
    return value or DEFAULT_WILDAPRICOT_ACCOUNT_ID


def resolve_quickbooks_realm_id() -> str:
    """Fixed data source ID — edit only in ui/.env (falls back to project .env defaults)."""
    value = env_value("QUICKBOOKS_REALM_ID", DEFAULT_QUICKBOOKS_REALM_ID)
    return value or DEFAULT_QUICKBOOKS_REALM_ID


def validate_data_source_id(value: str, field_label: str) -> Optional[str]:
    """Return a user-friendly error message, or None when the ID is valid."""
    cleaned = (value or "").strip()
    if not cleaned:
        return f"{field_label} is not configured. Set it in `ui/.env`."
    if cleaned.lower() in _PLACEHOLDER_ID_VALUES:
        return f"{field_label} must be a real numeric ID, not a placeholder."
    if not cleaned.isdigit():
        return f"{field_label} must contain digits only. Got `{cleaned}`."
    return None


def validate_data_source_ids(wa_id: str, qb_id: str) -> Optional[str]:
    for label, value in (
        ("WildApricot Account ID", wa_id),
        ("QuickBooks Realm ID", qb_id),
    ):
        error = validate_data_source_id(value, label)
        if error:
            return error
    return None


def format_api_error_detail(detail: object, status_code: int) -> str:
    """Turn FastAPI / API error payloads into readable messages."""
    if status_code == 403:
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("detail") or detail.get("error")
            if message:
                return (
                    f"Access denied (403): {message}. "
                    "Check your API bearer token in `ui/.env` and confirm you have permission "
                    "to access this resource."
                )
        if isinstance(detail, str) and detail.strip():
            return (
                f"Access denied (403): {detail}. "
                "Check your API bearer token in `ui/.env` and confirm you have permission "
                "to access this resource."
            )
        return (
            "Access denied (403). Your API credentials may be missing or invalid. "
            "Verify `BEARER_TOKEN` in `ui/.env` matches the API server configuration."
        )

    if status_code == 401:
        if isinstance(detail, dict):
            if detail.get("error") == "quickbooks_refresh_token_required":
                return detail.get(
                    "message",
                    "QuickBooks credentials expired. Update them in the QuickBooks section above.",
                )
            message = detail.get("message") or detail.get("detail")
            if message:
                return f"Authentication failed (401): {message}"
        if isinstance(detail, str) and detail.strip():
            return f"Authentication failed (401): {detail}"
        return (
            "Authentication failed (401). Set `BEARER_TOKEN` in `ui/.env` to match "
            "the API server `.env`."
        )

    if status_code == 422 and isinstance(detail, list):
        messages = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            loc = " → ".join(str(part) for part in item.get("loc", []) if part != "body")
            msg = item.get("msg", "Invalid value")
            if loc:
                messages.append(f"{loc}: {msg}")
            else:
                messages.append(msg)
        if messages:
            return "Request validation failed:\n- " + "\n- ".join(messages)

    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or detail.get("error")
        if message:
            return str(message)
        return json.dumps(detail, indent=2)

    if isinstance(detail, str):
        stripped = detail.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return format_api_error_detail(json.loads(stripped), status_code)
            except json.JSONDecodeError:
                pass
        return stripped or f"Request failed with status {status_code}."

    return f"Request failed with status {status_code}."


def validate_run_reports_inputs(
    *,
    wa_id: str,
    qb_id: str,
    bearer_token: str,
) -> Optional[str]:
    """Client-side checks before calling /api/reports."""
    id_error = validate_data_source_ids(wa_id, qb_id)
    if id_error:
        return id_error
    if not bearer_token:
        return (
            "API bearer token is not configured. Add `BEARER_TOKEN` to `ui/.env` "
            "so it matches the API server."
        )
    return None


def get_bearer_token() -> str:
    """Bearer token from .env (sent automatically; not shown in the UI)."""
    return resolve_bearer_token()


def parse_http_error_detail(response: requests.Response) -> object:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


def is_quickbooks_refresh_token_error(detail: object) -> bool:
    return isinstance(detail, dict) and detail.get("error") == "quickbooks_refresh_token_required"


def quickbooks_credential_defaults() -> dict[str, str]:
    """Pre-fill QuickBooks fields from .env for the credential retry form."""
    return {
        "client_id": env_value("QUICKBOOKS_CLIENT_ID"),
        "client_secret": env_value("QUICKBOOKS_CLIENT_SECRET"),
        "refresh_token": env_value("QUICKBOOKS_REFRESH_TOKEN"),
        "access_token": env_value("QUICKBOOKS_ACCESS_TOKEN"),
    }


def submit_quickbooks_credentials(
    base_url: str,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    access_token: str = "",
    realm_id: str = "",
) -> None:
    import re

    def _clean(value: str) -> str:
        return re.sub(r"\s+", "", value.strip())

    url = f"{base_url.rstrip('/')}/api/quickbooks/credentials"
    payload: dict[str, str] = {
        "client_id": _clean(client_id),
        "client_secret": _clean(client_secret),
        "refresh_token": _clean(refresh_token),
    }
    if access_token.strip():
        payload["access_token"] = _clean(access_token)
    if realm_id.strip():
        payload["realm_id"] = realm_id.strip()

    resp = requests.post(
        url,
        json=payload,
        headers=build_api_headers(),
        timeout=60,
    )
    resp.raise_for_status()


def submit_quickbooks_refresh_token(base_url: str, refresh_token: str) -> None:
    """Legacy helper — prefer submit_quickbooks_credentials."""
    defaults = quickbooks_credential_defaults()
    submit_quickbooks_credentials(
        base_url,
        client_id=defaults["client_id"],
        client_secret=defaults["client_secret"],
        refresh_token=refresh_token,
        access_token=defaults["access_token"],
    )


def build_api_headers(*, json_content: bool = True) -> dict[str, str]:
    headers: dict[str, str] = {}
    if json_content:
        headers["Content-Type"] = "application/json"
    token = get_bearer_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def format_api_request_error(exc: Exception, base_url: str, endpoint: str) -> str:
    """Return a user-friendly API error message instead of raw urllib3 traces."""
    target = f"{base_url.rstrip('/')}{endpoint}"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status_code = exc.response.status_code
        try:
            payload = exc.response.json()
            detail = payload.get("detail", payload)
        except ValueError:
            detail = exc.response.text
        friendly = format_api_error_detail(detail, status_code)
        return f"API request to `{target}` failed ({status_code}): {friendly}"
    if isinstance(exc, requests.ConnectionError):
        if base_url.rstrip("/") in _PLACEHOLDER_API_URLS or "example.com" in base_url:
            return (
                f"Cannot connect to placeholder API URL `{base_url}`. "
                f"Set **API Base URL** in the sidebar to `{DEFAULT_API_BASE_URL}` "
                f"and start the server with `python run.py`."
            )
        return (
            f"Cannot connect to `{target}`. "
            f"Start the API with `python run.py`, verify **API Base URL** is "
            f"`{DEFAULT_API_BASE_URL}`, then try again."
        )
    if isinstance(exc, requests.Timeout):
        return (
            f"Request to `{target}` timed out. "
            "Report generation can take a long time; retry if the API is still running."
        )
    if isinstance(exc, requests.RequestException):
        return f"API request to `{target}` failed: {exc}"
    return str(exc)


def call_reports(
    base_url: str,
    wa_id: str,
    qb_id: str,
    start_date: str,
    end_date: str,
    *,
    wildapricot_data: Optional[dict] = None,
    quickbooks_credentials: Optional[dict] = None,
    user_prompt: Optional[str] = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/api/reports"
    headers = build_api_headers()
    payload = {
        "wildapricot_account_id": wa_id,
        "quickbooks_realm_id": qb_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if wildapricot_data is not None:
        payload["wildapricot_data"] = wildapricot_data
    if quickbooks_credentials is not None:
        payload["quickbooks_credentials"] = quickbooks_credentials
    if user_prompt and user_prompt.strip():
        payload["user_prompt"] = user_prompt.strip()
    resp = requests.post(url, json=payload, headers=headers, timeout=None)
    if resp.status_code == 401:
        detail = parse_http_error_detail(resp)
        if is_quickbooks_refresh_token_error(detail):
            raise QuickBooksRefreshTokenRequired(detail)
    resp.raise_for_status()
    return resp.json()


def store_reports_success(resp: dict, elapsed: float) -> None:
    context, benchmark_reports = extract_benchmark_reports(resp)
    st.session_state.reports_response = resp
    st.session_state.reports_context = context
    st.session_state.stored_reports = benchmark_reports
    st.session_state.benchmark_response = None
    st.session_state.reports_elapsed = elapsed
    st.session_state.step = max(st.session_state.step, 2)
    st.session_state.pending_wildapricot_data = None
    st.session_state.qb_credentials_error = None


def fetch_available_reports(base_url: str) -> list:
    """Fetch the list of available benchmark reference PDFs from the API."""
    url = f"{base_url.rstrip('/')}/api/benchmark/reports"
    resp = requests.get(url, headers=build_api_headers(json_content=False), timeout=15)
    resp.raise_for_status()
    return resp.json().get("documents", [])


def format_benchmark_doc_label(doc: dict) -> str:
    return (
        f"{doc['file_name']}  ·  {doc['doc_type'].replace('_', ' ').title()}  ·  "
        f"FY {doc['fiscal_year']}"
    )


def fiscal_year_document_sets(docs: list) -> dict[int, list[str]]:
    """Map fiscal year to available reference PDF file names (up to one per doc type)."""
    by_year: dict[int, dict[str, str]] = {}
    for doc in docs:
        year = doc.get("fiscal_year")
        doc_type = doc.get("doc_type")
        file_name = doc.get("file_name")
        if year is None or not doc_type or not file_name:
            continue
        by_year.setdefault(year, {})
        if doc_type not in by_year[year]:
            by_year[year][doc_type] = file_name

    sets: dict[int, list[str]] = {}
    for year, types in by_year.items():
        files = [
            types[key]
            for key in ("form_990", "cash_flow", "financial_position")
            if key in types
        ]
        if files:
            sets[year] = files[:3]
    return sets


def prune_selected_report_files(valid_file_names: set[str]) -> None:
    """Drop stale selections and enforce the max reference-document limit."""
    current = st.session_state.get("selected_report_files") or []
    pruned = [
        file_name for file_name in current if file_name in valid_file_names
    ]
    st.session_state.selected_report_files = pruned[:MAX_BENCHMARK_REFERENCE_DOCS]


def extract_benchmark_reports(reports_response: dict) -> Tuple[dict, dict]:
    """Validate and return (reports_context, benchmark report slice)."""
    reports = reports_response.get("reports") or {}
    missing = [k for k in BENCHMARK_REPORT_KEYS if k not in reports]
    if missing:
        raise ValueError(f"Missing required reports: {missing}")

    benchmark_slice = {k: reports[k] for k in BENCHMARK_REPORT_KEYS}
    for key in BENCHMARK_REPORT_KEYS:
        entry = benchmark_slice[key]
        if not entry.get("content"):
            raise ValueError(
                f"Report '{key}' has no content (status={entry.get('status')})"
            )
        if entry.get("status") == "failed":
            raise ValueError(
                f"Report '{key}' generation failed: {entry.get('error_message')}"
            )

    context = {
        "request_id": reports_response.get("request_id"),
        "start_date": reports_response.get("start_date"),
        "end_date": reports_response.get("end_date"),
        "wildapricot_account_id": reports_response.get("wildapricot_account_id"),
        "quickbooks_realm_id": reports_response.get("quickbooks_realm_id"),
        "reports_status": reports_response.get("status"),
    }
    return context, benchmark_slice


def benchmark_years_label(years: Optional[list], start_date: str, end_date: str) -> str:
    """Human-readable label for which fiscal years will be benchmarked."""
    if years:
        return ", ".join(str(y) for y in years)
    try:
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
    except (TypeError, ValueError):
        return "from reports period"
    if start_year == end_year:
        return f"from reports period ({start_year})"
    return f"from reports period ({start_year}–{end_year})"


def _benchmark_overall_score(synthesis: dict) -> Optional[float]:
    if not synthesis:
        return None
    if synthesis.get("overall_score") is not None:
        return float(synthesis["overall_score"])
    summary = synthesis.get("benchmark_summary") or {}
    if summary.get("overall_score") is not None:
        return float(summary["overall_score"])
    return None


def render_benchmark_section(title: str, review: dict) -> None:
    """Render a compact section review (Form 990 or Cash Flow)."""
    score = review.get("score")
    rating = review.get("rating", "—")
    header = f"**{title}**"
    if score is not None:
        header += f" — {score}/100 ({rating})"
    st.markdown(header)

    dims = review.get("dimension_scores") or {}
    if dims:
        cols = st.columns(4)
        for col, (label, key) in zip(
            cols,
            [
                ("Accuracy", "accuracy"),
                ("Reconciliation", "reconciliation"),
                ("Completeness", "completeness"),
                ("Audit quality", "audit_quality"),
            ],
        ):
            with col:
                val = dims.get(key)
                st.metric(label, f"{val:.0f}/100" if isinstance(val, (int, float)) else "—")

    confounds = review.get("confound_flags") or []
    if confounds:
        st.markdown("**Data integrity confounds**")
        for flag in confounds[:5]:
            if isinstance(flag, dict):
                st.warning(f"[{flag.get('code', 'CONFOUND')}] {flag.get('message', flag)}")
            else:
                st.warning(str(flag))

    if review.get("summary"):
        st.caption(review["summary"])
    diffs = review.get("key_differences") or []
    if diffs:
        st.markdown("Key differences")
        st.dataframe(diffs, use_container_width=True, hide_index=True)
    issues = review.get("issues") or []
    if issues:
        st.markdown("Issues")
        for issue in issues:
            st.markdown(f"- {issue}")


def render_scorecard_summary(scorecard: dict) -> None:
    """Render blended deterministic scorecard for a fiscal year."""
    if not scorecard:
        return
    adjusted = scorecard.get("adjusted_composite_score")
    if adjusted is not None:
        st.metric("Adjusted composite", f"{adjusted:.1f}/100")
    confounds = []
    for section in ("form_990", "cash_flow", "financial_position"):
        block = scorecard.get(section) or {}
        confounds.extend(block.get("confound_flags") or [])
    if confounds:
        st.caption(
            f"{len(confounds)} data-integrity confound(s) detected — "
            "variance may reflect bad inputs, not AI classification errors."
        )


def get_reports_context() -> Optional[dict]:
    """Return frozen reports context, rebuilding from reports_response when missing."""
    ctx = st.session_state.get("reports_context")
    if ctx and ctx.get("start_date") and ctx.get("end_date"):
        return ctx

    resp = st.session_state.get("reports_response")
    if not resp:
        return ctx

    rebuilt = {
        "request_id": resp.get("request_id"),
        "start_date": resp.get("start_date"),
        "end_date": resp.get("end_date"),
        "wildapricot_account_id": resp.get("wildapricot_account_id"),
        "quickbooks_realm_id": resp.get("quickbooks_realm_id"),
        "reports_status": resp.get("status"),
    }
    if rebuilt.get("start_date") and rebuilt.get("end_date"):
        st.session_state.reports_context = rebuilt
        return rebuilt
    return ctx


def benchmark_ready() -> bool:
    available = st.session_state.get("available_reports")
    selected = st.session_state.get("selected_report_files", [])
    if available is not None and len(selected) == 0:
        return False

    ctx = get_reports_context()
    stored = st.session_state.get("stored_reports")
    if not ctx or not stored:
        return False
    if not ctx.get("start_date") or not ctx.get("end_date"):
        return False
    return all(
        k in stored and stored[k].get("content")
        for k in BENCHMARK_REPORT_KEYS
    )


def call_benchmark(
    base_url: str,
    reports_context: dict,
    stored_reports: dict,
    years: Optional[list],
    *,
    selected_document_files: Optional[list] = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/api/benchmark"
    headers = build_api_headers()
    payload: dict = {
        "wildapricot_account_id": reports_context["wildapricot_account_id"],
        "quickbooks_realm_id": reports_context["quickbooks_realm_id"],
        "start_date": reports_context["start_date"],
        "end_date": reports_context["end_date"],
        "reports": stored_reports,
    }
    if years:
        payload["years"] = years
    if selected_document_files:
        payload["selected_document_files"] = selected_document_files
    resp = requests.post(url, json=payload, headers=headers, timeout=None)
    resp.raise_for_status()
    return resp.json()


def render_step(num: int, label: str, current_step: int):
    if current_step > num:
        cls = "done"
        icon = "✓"
    elif current_step == num:
        cls = ""
        icon = str(num)
    else:
        cls = "idle"
        icon = str(num)
    st.markdown(
        f'<div class="step-row"><div class="step-num {cls}">{icon}</div>'
        f'<span class="step-label">{label}</span></div>',
        unsafe_allow_html=True,
    )


def build_quickbooks_credentials_payload(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    access_token: str,
    realm_id: str,
) -> Optional[dict]:
    """Return inline QuickBooks credentials when all required fields are present."""
    if not all(
        value.strip()
        for value in (client_id, client_secret, refresh_token)
    ):
        return None
    payload = {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "refresh_token": refresh_token.strip(),
        "realm_id": realm_id.strip() or None,
    }
    if access_token.strip():
        payload["access_token"] = access_token.strip()
    return payload


def execute_reports_run(
    base_url: str,
    wa_id: str,
    qb_id: str,
    start_date: str,
    end_date: str,
    *,
    user_prompt: str = "",
    quickbooks_credentials: Optional[dict] = None,
) -> None:
    """Validate inputs, call /api/reports, and store results or surface friendly errors."""
    validation_error = validate_run_reports_inputs(
        wa_id=wa_id,
        qb_id=qb_id,
        bearer_token=get_bearer_token(),
    )
    if validation_error:
        st.error(validation_error)
        return

    t0 = time.time()
    try:
        resp = run_progress.run_with_progress(
            lambda: call_reports(
                base_url,
                wa_id,
                qb_id,
                start_date,
                end_date,
                wildapricot_data=st.session_state.get("pending_wildapricot_data"),
                quickbooks_credentials=quickbooks_credentials,
                user_prompt=user_prompt,
            )
        )
        store_reports_success(resp, time.time() - t0)
        st.session_state.qb_credentials_error = None
        st.rerun()
    except QuickBooksRefreshTokenRequired as e:
        if e.detail.get("wildapricot_data"):
            st.session_state.pending_wildapricot_data = e.detail["wildapricot_data"]
        st.session_state.qb_credentials_error = (
            e.detail.get("message")
            or "QuickBooks credentials are invalid or expired. Update them above and try again."
        )
        st.rerun()
    except ValueError as e:
        st.error(f"Invalid reports response: {e}")
    except requests.HTTPError as e:
        if e.response is not None:
            detail = parse_http_error_detail(e.response)
            if is_quickbooks_refresh_token_error(detail):
                if isinstance(detail, dict) and detail.get("wildapricot_data"):
                    st.session_state.pending_wildapricot_data = detail["wildapricot_data"]
                st.session_state.qb_credentials_error = (
                    detail.get("message")
                    if isinstance(detail, dict)
                    else "QuickBooks credentials are invalid or expired. Update them above and try again."
                )
                st.rerun()
            st.error(format_api_request_error(e, base_url, "/api/reports"))
        else:
            st.error(format_api_request_error(e, base_url, "/api/reports"))
    except requests.RequestException as e:
        st.error(format_api_request_error(e, base_url, "/api/reports"))
    except Exception as e:
        st.error(format_api_request_error(e, base_url, "/api/reports"))


# ──────────────────────────────────────────────
# Sidebar – Configuration
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    st.markdown("---")

    base_url = st.text_input(
        "API Base URL",
        value=resolve_api_base_url(),
        help=f"Root URL of the AccountBridge API (default: {DEFAULT_API_BASE_URL})",
    )
    if base_url.rstrip("/") in _PLACEHOLDER_API_URLS or "example.com" in base_url:
        st.warning(
            f"Placeholder URL detected. Use `{DEFAULT_API_BASE_URL}` while running "
            "`python run.py` locally."
        )

    st.markdown("---")
    st.markdown("### 🏢 Data Sources")
    if "wildapricot_account_id" not in st.session_state:
        st.session_state.wildapricot_account_id = resolve_wildapricot_account_id()
    if "quickbooks_realm_id" not in st.session_state:
        st.session_state.quickbooks_realm_id = resolve_quickbooks_realm_id()
    wa_id = st.text_input(
        "WildApricot Account ID",
        key="wildapricot_account_id",
        help="WildApricot account ID for this client. Defaults from `WILDAPRICOT_ACCOUNT_ID` in `.env`.",
    )
    qb_id = st.text_input(
        "QuickBooks Realm ID",
        key="quickbooks_realm_id",
        help="QuickBooks company / realm ID for this client. Defaults from `QUICKBOOKS_REALM_ID` in `.env`.",
    )
    wa_id_error = validate_data_source_id(wa_id, "WildApricot Account ID")
    qb_id_error = validate_data_source_id(qb_id, "QuickBooks Realm ID")
    if wa_id_error:
        st.error(wa_id_error)
    if qb_id_error:
        st.error(qb_id_error)

    st.markdown("---")
    st.markdown("### 📅 Date Range")
    prior_year = date.today().year - 1
    col_s, col_e = st.columns(2)
    with col_s:
        start_date = st.date_input(
            "Start",
            value=date(prior_year, 1, 1),
            help="Use a full calendar year for benchmark (e.g. 2024-01-01)",
        )
    with col_e:
        end_date = st.date_input(
            "End",
            value=date(prior_year, 12, 31),
            help="Use year-end for benchmark reference PDFs",
        )

    if start_date.month != 1 or start_date.day != 1 or end_date.month != 12 or end_date.day != 31:
        st.warning(
            f"Reports will cover **{start_date}** → **{end_date}**. "
            "Benchmark reference docs are full calendar years — prefer Jan 1 → Dec 31."
        )
    elif start_date.year != end_date.year:
        st.warning("Start and end dates span multiple years. Use a single fiscal year.")

    st.markdown("---")
    st.markdown("### 🎯 Benchmark Options")
    years_input = st.text_input(
        "Fiscal Years (comma-separated, optional)",
        placeholder="e.g. 2025",
        help=(
            "Leave blank to benchmark the fiscal year(s) implied by the reports "
            "period (start/end dates). Only matching reference PDFs from the configured source are used."
        ),
    )

    st.markdown("---")
    st.markdown("### 🔄 Pipeline Status")
    render_step(1, "Generate Reports", st.session_state.step)
    render_step(2, "Store Reports slice", st.session_state.step)
    render_step(3, "Run Benchmark", st.session_state.step)

    if st.button("🔁 Reset", use_container_width=True):
        for k in [
            "reports_response", "reports_context", "stored_reports",
            "benchmark_response", "step", "reports_elapsed", "benchmark_elapsed",
            "available_reports", "available_reports_error",
            "selected_report_files",
            "pending_wildapricot_data", "qb_credentials_error",
        ]:
            if k == "step":
                st.session_state[k] = 0
            elif k == "selected_report_files":
                st.session_state[k] = []
            elif k == "qb_credentials_error":
                st.session_state[k] = None
            else:
                st.session_state[k] = None
        st.rerun()

# ──────────────────────────────────────────────
# Main area
# ──────────────────────────────────────────────
st.markdown("# 📊 TaxBridge · Reports → Prepare → File")
st.markdown(
    '<p class="ab-subtitle">Generate financial reports, benchmark them, '
    "then prepare and file a return through Tax990.</p>",
    unsafe_allow_html=True,
)

# ── QuickBooks credentials (always visible in header) ──
with st.container(border=True):
    st.markdown("### 🔐 QuickBooks Credentials")
    st.caption(
        f"Get tokens from the "
        f"[Intuit OAuth playground]({QUICKBOOKS_PLAYGROUND_URL}) (**Get Tokens**), "
        "then save them here before running reports."
    )
    if st.session_state.get("qb_credentials_error"):
        st.error(st.session_state.qb_credentials_error)
    if st.session_state.get("pending_wildapricot_data"):
        st.info(
            "WildApricot data is already fetched and will be reused on retry — "
            "only QuickBooks will be called again."
        )

    qb_defaults = quickbooks_credential_defaults()
    qb_hdr1, qb_hdr2 = st.columns(2)
    with qb_hdr1:
        qb_client_id = st.text_input(
            "QuickBooks Client ID",
            value=qb_defaults["client_id"],
            key="qb_client_id_input",
        )
        qb_refresh_token = st.text_area(
            "QuickBooks Refresh Token",
            value=qb_defaults["refresh_token"],
            height=72,
            key="qb_refresh_token_input",
            placeholder="refresh_token from playground (starts with RT1-)",
        )
    with qb_hdr2:
        qb_client_secret = st.text_input(
            "QuickBooks Client Secret",
            value=qb_defaults["client_secret"],
            type="password",
            key="qb_client_secret_input",
        )
        qb_access_token = st.text_area(
            "QuickBooks Access Token",
            value=qb_defaults["access_token"],
            height=72,
            key="qb_access_token_input",
            placeholder="access_token from playground (optional but recommended)",
        )

    save_run_col, _save_run_spacer = st.columns([1, 3])
    with save_run_col:
        save_and_run = st.button(
            "Save & Run",
            type="primary",
            use_container_width=True,
            key="save_and_run_reports",
        )

if save_and_run:
    missing = [
        label
        for label, value in (
            ("Client ID", qb_client_id),
            ("Client Secret", qb_client_secret),
            ("Refresh Token", qb_refresh_token),
        )
        if not value.strip()
    ]
    if missing:
        st.session_state.qb_credentials_error = f"Required QuickBooks fields: {', '.join(missing)}"
        st.rerun()
    else:
        with st.spinner("Saving QuickBooks credentials and running reports …"):
            try:
                submit_quickbooks_credentials(
                    base_url,
                    client_id=qb_client_id,
                    client_secret=qb_client_secret,
                    refresh_token=qb_refresh_token,
                    access_token=qb_access_token,
                    realm_id=qb_id,
                )
            except requests.HTTPError as e:
                detail = parse_http_error_detail(e.response) if e.response is not None else str(e)
                message = (
                    detail.get("message", detail)
                    if isinstance(detail, dict)
                    else format_api_error_detail(detail, e.response.status_code if e.response else 500)
                )
                st.session_state.qb_credentials_error = f"Could not save QuickBooks credentials: {message}"
                st.rerun()
            except requests.RequestException as e:
                st.session_state.qb_credentials_error = format_api_request_error(
                    e, base_url, "/api/quickbooks/credentials"
                )
                st.rerun()
            else:
                qb_creds_payload = build_quickbooks_credentials_payload(
                    qb_client_id,
                    qb_client_secret,
                    qb_refresh_token,
                    qb_access_token,
                    qb_id,
                )
                execute_reports_run(
                    base_url,
                    wa_id,
                    qb_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    user_prompt=st.session_state.get("user_prompt", ""),
                    quickbooks_credentials=qb_creds_payload,
                )

tab_pipeline, tab_reports, tab_filing, tab_benchmark, tab_raw = st.tabs(
    ["🚀 Pipeline", "📄 Reports", "📮 File a Return", "🎯 Benchmark", "🔩 Raw JSON"]
)

# ──────────────────────────────────────────────
# TAB · File a Return
# ──────────────────────────────────────────────
with tab_filing:
    _reports_response = st.session_state.get("reports_response") or {}
    _tax_return = (
        (_reports_response.get("reports") or {}).get("tax_return") or {}
    )
    filing_tab.render(
        base_url=resolve_api_base_url(),
        headers=build_api_headers(),
        quickbooks_realm_id=qb_id,
        start_date=str(start_date),
        end_date=str(end_date),
        report_content=_tax_return.get("content"),
        quickbooks_credentials=build_quickbooks_credentials_payload(
            qb_client_id, qb_client_secret, qb_refresh_token, qb_access_token, qb_id
        ),
        format_request_error=format_api_request_error,
    )

# ──────────────────────────────────────────────
# TAB 1 · Pipeline
# ──────────────────────────────────────────────
with tab_pipeline:

    # ── Step 1: Generate Reports ──
    st.markdown("### Step 1 · Generate Reports  `/api/reports`")

    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(
            f"WildApricot: **{wa_id}** &nbsp;|&nbsp; QuickBooks: **{qb_id}**  \n"
            f"Date range: **{start_date}** → **{end_date}**",
            unsafe_allow_html=True,
        )
    with c2:
        run_reports = st.button(
            "▶ Run Reports",
            use_container_width=True,
            type="primary",
            key="run_reports_btn",
        )

    st.markdown("#### ✍️ Report Instructions")
    user_prompt = st.text_area(
        "User prompt (optional)",
        value=st.session_state.get("user_prompt", ""),
        height=120,
        key="user_prompt_input",
        placeholder=(
            "e.g. Emphasize program service revenue breakdown, use accrual basis, "
            "or highlight deferred membership dues in the cash flow report."
        ),
        help=(
            "Optional guidance sent to the LLM for all three reports (cash flow, "
            "balance sheet, and tax return). When provided, it takes priority over "
            "the default report structuring instructions."
        ),
    )
    st.session_state.user_prompt = user_prompt

    if run_reports:
        qb_creds_payload = build_quickbooks_credentials_payload(
            qb_client_id,
            qb_client_secret,
            qb_refresh_token,
            qb_access_token,
            qb_id,
        )
        with st.spinner("Calling /api/reports …"):
            execute_reports_run(
                base_url,
                wa_id,
                qb_id,
                start_date.isoformat(),
                end_date.isoformat(),
                user_prompt=user_prompt,
                quickbooks_credentials=qb_creds_payload,
            )

    if st.session_state.stored_reports is not None:
        n_reports = len(st.session_state.stored_reports)
        elapsed = st.session_state.reports_elapsed or 0
        cols = st.columns(n_reports or 1)
        for i, (rtype, rdata) in enumerate(st.session_state.stored_reports.items()):
            with cols[i % len(cols)]:
                status = rdata.get("status", "unknown")
                badge_kind = "green" if status == "completed" else "red"
                st.markdown(
                    f'<div class="metric-tile">'
                    f'<div class="value">{rtype.replace("_", " ").title()}</div>'
                    f'<div class="label">{badge(status, badge_kind)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        st.success(
            f"✅ Stored **cash_flow**, **tax_return**, and **balance_sheet** for benchmark ({elapsed:.1f}s)."
        )
        ctx = get_reports_context()
        if ctx:
            st.caption(
                f"Frozen period: {ctx.get('start_date')} → {ctx.get('end_date')} "
                f"(request_id: {ctx.get('request_id', '—')})"
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Step 2: Stored Reports Preview ──
    with st.container(border=True):
        st.markdown("### Step 2 · Stored Reports Slice")
        if st.session_state.stored_reports:
            st.markdown(
                "In-session benchmark slice: "
                + ", ".join(f"`{k}`" for k in st.session_state.stored_reports.keys())
            )
            with st.expander("Preview stored `reports` JSON"):
                st.json(st.session_state.stored_reports)
        else:
            st.info("No reports stored yet. Run Step 1 first.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Step 3: Benchmark ──
    st.markdown("### Step 3 · Run Benchmark  `/api/benchmark`")
    st.caption(
        "Select up to 3 reference PDFs from the list below, then click **Run Benchmark**. "
        "The selected documents will be extracted and compared against your AI-generated reports."
    )

    # ── Reference document picker ──
    st.markdown("#### 📑 Select Reference Documents")
    _ref_hdr, _ref_btn_col = st.columns([4, 1])
    with _ref_btn_col:
        _refresh_docs = st.button("🔄 Refresh", key="refresh_docs", use_container_width=True)

    if _refresh_docs or st.session_state.available_reports is None:
        with st.spinner("Loading available reference documents …"):
            try:
                _docs = fetch_available_reports(base_url)
                st.session_state.available_reports = _docs
                st.session_state.available_reports_error = None
            except requests.RequestException as _e:
                st.session_state.available_reports_error = format_api_request_error(
                    _e, base_url, "/api/benchmark/reports"
                )
                if st.session_state.available_reports is None:
                    st.session_state.available_reports = []
            except Exception as _e:
                st.session_state.available_reports_error = str(_e)
                if st.session_state.available_reports is None:
                    st.session_state.available_reports = []

    if st.session_state.available_reports_error:
        st.error(
            f"Could not load reference documents: {st.session_state.available_reports_error}"
        )

    _available_docs = st.session_state.available_reports or []
    if _available_docs:
        _file_names = [d["file_name"] for d in _available_docs]
        _label_by_file = {
            d["file_name"]: format_benchmark_doc_label(d) for d in _available_docs
        }
        prune_selected_report_files(set(_file_names))

        _fy_sets = fiscal_year_document_sets(_available_docs)
        if _fy_sets:
            st.caption(
                f"Quick select a fiscal-year set "
                f"(up to {MAX_BENCHMARK_REFERENCE_DOCS} PDFs):"
            )
            _fy_cols = st.columns(min(len(_fy_sets), 4))
            for idx, (year, files) in enumerate(
                sorted(_fy_sets.items(), reverse=True)
            ):
                with _fy_cols[idx % len(_fy_cols)]:
                    if st.button(
                        f"FY {year} ({len(files)} docs)",
                        key=f"select_fy_{year}",
                        use_container_width=True,
                    ):
                        st.session_state.selected_report_files = (
                            files[:MAX_BENCHMARK_REFERENCE_DOCS]
                        )
                        st.rerun()

        _selected_files = st.multiselect(
            f"Choose 1–{MAX_BENCHMARK_REFERENCE_DOCS} reference PDFs to benchmark against:",
            options=_file_names,
            format_func=lambda file_name: _label_by_file[file_name],
            key="selected_report_files",
            help=(
                "Select Form 990, Cash Flow, and Financial Position PDFs (same fiscal year). "
                "Each PDF is extracted to JSON and compared to the matching AI report "
                f"(tax_return, cash_flow, balance_sheet). "
                f"Up to {MAX_BENCHMARK_REFERENCE_DOCS} documents."
            ),
        )

        if len(_selected_files) > MAX_BENCHMARK_REFERENCE_DOCS:
            st.warning(
                f"Only {MAX_BENCHMARK_REFERENCE_DOCS} reference documents can be "
                "benchmarked at once. Keeping the first "
                f"{MAX_BENCHMARK_REFERENCE_DOCS} selections."
            )
            st.session_state.selected_report_files = (
                _selected_files[:MAX_BENCHMARK_REFERENCE_DOCS]
            )
            st.rerun()

        if len(_selected_files) == 0:
            st.warning("Select at least 1 reference document to enable the benchmark.")
        else:
            st.success(
                f"{len(_selected_files)} document(s) selected: "
                + ", ".join(f"`{file_name}`" for file_name in _selected_files)
            )
    elif st.session_state.available_reports is not None:
        st.info(
            "No reference documents found. Check S3 settings "
            "(`BENCHMARK_DOCS_S3_BUCKET`, `BENCHMARK_DOCS_S3_PREFIX`) and ensure PDFs are uploaded."
        )

    st.markdown("---")

    years_list = None
    if years_input.strip():
        try:
            years_list = [int(y.strip()) for y in years_input.split(",") if y.strip()]
        except ValueError:
            st.warning("Invalid years input — will use reports period instead.")

    c3, c4 = st.columns([3, 1])
    with c3:
        ctx = get_reports_context()
        period = (
            f"{ctx['start_date']} → {ctx['end_date']}"
            if ctx and ctx.get("start_date") and ctx.get("end_date")
            else "— (run Reports first)"
        )
        if ctx and ctx.get("start_date") and ctx.get("end_date"):
            years_display = benchmark_years_label(
                years_list, ctx["start_date"], ctx["end_date"]
            )
        else:
            years_display = benchmark_years_label(
                years_list,
                start_date.isoformat(),
                end_date.isoformat(),
            )
        st.markdown(
            f"Period (frozen): **{period}**  \n"
            f"Years: **{years_display}**"
        )
    with c4:
        run_bench = st.button(
            "▶ Run Benchmark",
            use_container_width=True,
            type="primary",
            disabled=not benchmark_ready(),
            key="run_benchmark_btn",
        )

    if run_bench:
        if not benchmark_ready():
            st.error(
                "Benchmark prerequisites missing. Run Step 1 to generate reports first."
            )
        else:
            ctx = get_reports_context()
            years_hint = benchmark_years_label(
                years_list,
                (ctx or {}).get("start_date") or start_date.isoformat(),
                (ctx or {}).get("end_date") or end_date.isoformat(),
            )
            with st.spinner(
                f"Calling /api/benchmark (years: {years_hint}) — "
                "reference extraction + LLM review can take several minutes per year …"
            ):
                t0 = time.time()
                _sel_files = st.session_state.get("selected_report_files") or None
                try:
                    resp = call_benchmark(
                        base_url,
                        ctx,
                        st.session_state.stored_reports,
                        years_list,
                        selected_document_files=_sel_files,
                    )
                    st.session_state.benchmark_response = resp
                    st.session_state.benchmark_elapsed = time.time() - t0
                    st.session_state.step = 3
                    st.rerun()
                except requests.HTTPError as e:
                    st.error(format_api_request_error(e, base_url, "/api/benchmark"))
                except requests.RequestException as e:
                    st.error(format_api_request_error(e, base_url, "/api/benchmark"))
                except Exception as e:
                    st.error(format_api_request_error(e, base_url, "/api/benchmark"))

    if st.session_state.benchmark_response:
        br = st.session_state.benchmark_response
        score = br.get("overall_match_score", 0)
        elapsed = st.session_state.benchmark_elapsed or 0
        score_kind = "green" if score >= 0.9 else "yellow" if score >= 0.7 else "red"
        st.markdown(
            f"Overall match score: "
            + badge(f"{score*100:.1f}%", score_kind)
            + f"&nbsp; | &nbsp;Completed in **{elapsed:.1f}s**",
            unsafe_allow_html=True,
        )
    elif not benchmark_ready():
        st.caption("⚠ Run Reports first, then select reference documents.")


# ──────────────────────────────────────────────
# TAB 2 · Reports detail
# ──────────────────────────────────────────────
with tab_reports:
    if not st.session_state.stored_reports:
        st.info("Run the Reports step first.")
    else:
        st.markdown("## 📄 Generated Reports")
        reports_resp = st.session_state.get("reports_response") or {}
        warnings = reports_resp.get("data_quality_warnings") or []
        if warnings:
            for warning in warnings:
                st.warning(warning)
        for rtype, rdata in st.session_state.stored_reports.items():
            status = rdata.get("status", "unknown")
            pt = rdata.get("processing_time", 0)
            badge_kind = "green" if status == "completed" else "red"

            with st.expander(
                f"**{rtype.replace('_', ' ').title()}**  —  "
                + f"status: {status}  |  {pt:.2f}s",
                expanded=True,
            ):
                err = rdata.get("error_message")
                if err:
                    st.error(f"Error: {err}")

                content = rdata.get("content", {})
                if content:
                    st.markdown("#### Content")
                    st.json(content)
                else:
                    st.caption("No content returned.")


# ──────────────────────────────────────────────
# TAB 3 · Benchmark detail
# ──────────────────────────────────────────────
with tab_benchmark:
    if not st.session_state.benchmark_response:
        st.info("Run the Benchmark step first.")
    else:
        br = st.session_state.benchmark_response
        st.markdown("## 🎯 Benchmark Results")
        st.caption(
            "Scores compare AI-generated reports to filed reference PDFs. "
            "Sandbox or partial QuickBooks data often yields low match scores."
        )
        if br.get("year_resolution_note"):
            st.info(br["year_resolution_note"])

        score = br.get("overall_match_score", 0)
        total_time = br.get("total_processing_time", 0)
        years_done = br.get("years_benchmarked", [])
        bstatus = br.get("status", "unknown")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(
                f'<div class="metric-tile"><div class="value">{score*100:.1f}%</div>'
                f'<div class="label">Match Score</div></div>', unsafe_allow_html=True
            )
        with m2:
            st.markdown(
                f'<div class="metric-tile"><div class="value">{total_time:.1f}s</div>'
                f'<div class="label">Processing Time</div></div>', unsafe_allow_html=True
            )
        with m3:
            st.markdown(
                f'<div class="metric-tile"><div class="value">{len(years_done)}</div>'
                f'<div class="label">Years Benchmarked</div></div>', unsafe_allow_html=True
            )
        with m4:
            st.markdown(
                f'<div class="metric-tile"><div class="value">{bstatus.title()}</div>'
                f'<div class="label">Status</div></div>', unsafe_allow_html=True
            )

        st.markdown("<br>", unsafe_allow_html=True)

        results = br.get("results", {})
        if results:
            for year, year_data in results.items():
                with st.expander(f"Fiscal Year {year}", expanded=True):
                    if not isinstance(year_data, dict):
                        st.json(year_data)
                        continue

                    synthesis = year_data.get("synthesis") or {}
                    scorecard = year_data.get("scorecard") or {}
                    if scorecard:
                        st.markdown("#### Deterministic scorecard")
                        render_scorecard_summary(scorecard)

                    overall = _benchmark_overall_score(synthesis)
                    if overall is None and scorecard.get("adjusted_composite_score") is not None:
                        overall = float(scorecard["adjusted_composite_score"])
                    if overall is not None:
                        s1, s2, s3, s4 = st.columns(4)
                        with s1:
                            st.metric("Overall", f"{overall:.0f}/100")
                        with s2:
                            st.metric("Form 990", synthesis.get("form_990_score", "—"))
                        with s3:
                            st.metric("Cash Flow", synthesis.get("cash_flow_score", "—"))
                        with s4:
                            st.metric(
                                "Financial Position",
                                synthesis.get("financial_position_score", "—"),
                            )
                        if synthesis.get("rating"):
                            st.caption(f"Rating: **{synthesis['rating']}**")
                    elif synthesis.get("errors"):
                        st.warning("Synthesis incomplete: " + "; ".join(synthesis["errors"][:3]))
                    else:
                        st.caption("No synthesis scores returned for this year.")

                    summary_text = synthesis.get("summary") or synthesis.get("executive_summary")
                    if summary_text:
                        st.markdown("#### Summary")
                        st.markdown(summary_text)

                    top_issues = synthesis.get("top_issues") or synthesis.get("material_findings") or []
                    if top_issues:
                        st.markdown("#### Top Issues")
                        if isinstance(top_issues[0], dict):
                            for item in top_issues[:5]:
                                field = item.get("affected_field") or item.get("field", "—")
                                st.markdown(f"- **{field}**: {item.get('explanation', item)}")
                        else:
                            for issue in top_issues[:5]:
                                st.markdown(f"- {issue}")

                    for section_key, title in [
                        ("form_990_review", "Form 990"),
                        ("cash_flow_review", "Cash Flow"),
                        ("financial_position_review", "Financial Position"),
                    ]:
                        section = year_data.get(section_key)
                        if not section:
                            st.markdown("---")
                            st.caption(f"{title}: no review data returned.")
                            continue
                        if section.get("_parse_error"):
                            st.markdown("---")
                            st.warning(
                                f"{title}: review response could not be parsed."
                            )
                            continue
                        st.markdown("---")
                        render_benchmark_section(title, section)
        else:
            st.info("No benchmark results returned.")


# ──────────────────────────────────────────────
# TAB 4 · Raw JSON
# ──────────────────────────────────────────────
with tab_raw:
    st.markdown("## 🔩 Raw API Responses")

    col_r, col_b = st.columns(2)

    with col_r:
        st.markdown("### /api/reports response")
        if st.session_state.reports_response:
            # Download button
            st.download_button(
                "⬇ Download reports.json",
                data=json.dumps(st.session_state.reports_response, indent=2),
                file_name="reports_response.json",
                mime="application/json",
            )
            st.json(st.session_state.reports_response)
        else:
            st.info("No data yet.")

    with col_b:
        st.markdown("### /api/benchmark response")
        if st.session_state.benchmark_response:
            st.download_button(
                "⬇ Download benchmark.json",
                data=json.dumps(st.session_state.benchmark_response, indent=2),
                file_name="benchmark_response.json",
                mime="application/json",
            )
            st.json(st.session_state.benchmark_response)
        else:
            st.info("No data yet.")

    st.markdown("---")
    st.markdown("### Stored `reports` slice  _(what gets passed to benchmark)_")
    if st.session_state.stored_reports:
        st.download_button(
            "⬇ Download stored_reports.json",
            data=json.dumps(st.session_state.stored_reports, indent=2),
            file_name="stored_reports.json",
            mime="application/json",
        )
        st.json(st.session_state.stored_reports)
    else:
        st.info("No stored reports yet.")
import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only load .env file if not running in Lambda
# Lambda uses environment variables directly, not .env files
if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        # dotenv not available, continue without it
        pass


class Settings(BaseSettings):
    # Environment
    ENV: str = "development"  # development | production
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # text | json

    # AWS Configuration
    AWS_REGION: str = "us-east-1"
    BUCKET_NAME: str = ""  # Required when EXTRACTOR_TYPE=AWS_textract
    AWS_SSL_VERIFY: bool = True
    # Required when using LLM (LLM_MODEL takes precedence; MODEL_ID is a legacy alias)
    LLM_PROVIDER: str = "bedrock"
    LLM_MODEL: str = ""
    MODEL_ID: str = ""
    TEMPERATURE: float = 0.0
    MAX_TOKENS: int = 8192
    TOP_P: float = 0.6
    # OpenAI specific
    OPENAI_API_KEY: str = ""


    # Extractor Configuration
    EXTRACTOR_TYPE: str = "AWS_textract"  # AWS_textract | goml_custom_extractor

    # File Processing Limits
    MAX_FILE_SIZE_MB: int = 100
    MAX_PAGES_PER_REQUEST: int = 50
    CHUNK_SIZE_MB: int = 10
    MAX_BATCH_FILES: int = 10

    # Timeouts (seconds)
    TEXTRACT_TIMEOUT: int = 300
    LLM_TIMEOUT: int = 60
    REPORTS_LLM_TIMEOUT: int = 86400  # no practical limit for long report generation
    FILE_UPLOAD_TIMEOUT: int = 120
    SHUTDOWN_DRAIN_SECONDS: int = 30

    # Reports generation (LLM)
    REPORTS_MAX_TOKENS: int = 32768
    REPORTS_TAX_RETURN_SECTION_MAX_TOKENS: int = 16384
    REPORTS_TAX_RETURN_PART_IX_MAX_TOKENS: int = 16384
    REPORTS_TAX_RETURN_RECONCILIATION_MAX_TOKENS: int = 8192
    REPORTS_WA_MAX_RECORDS_PER_ENTITY: int = 50
    REPORTS_WA_FINANCIAL_RECORDS_PER_ENTITY: int = 200

    # Concurrency
    MAX_WORKERS: int = 4
    MAX_CONCURRENT_PAGES: int = 5

    # S3 Configuration
    S3_PREFIX: str = "document-uploads"
    S3_TEMP_EXPIRY_DAYS: int = 1

    # Retry Configuration
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 1.0

    # Health checks (optional dependency checks in readiness)
    HEALTH_CHECK_S3: bool = False
    HEALTH_CHECK_BEDROCK: bool = False

    # Auth: none | api_key | bearer | jwt
    AUTH_METHOD: str = "none"
    API_KEY: str = ""  # Single key, or use API_KEYS for comma-separated list
    API_KEYS: str = ""
    BEARER_TOKEN: str = ""
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_PER_MINUTE: int = 60

    # Input hardening: comma-separated MIME types; empty = no content-type check
    ALLOWED_UPLOAD_CONTENT_TYPES: str = ""

    # TEMP: local cache for /api/reports output (benchmark-only testing)
    REPORTS_CACHE_DIR: str = "data/reports"

    # Benchmark reference documents
    BENCHMARK_DOCS_LOCAL_PATH: str = "docs"
    BENCHMARK_DOCS_S3_BUCKET: str = ""
    BENCHMARK_DOCS_S3_PREFIX: str = ""
    BENCHMARK_DOCS_SOURCE: str = "local"  # local | s3
    BENCHMARK_LLM_MAX_TOKENS: int = 4096
    FORM_990_ORG_INFO_PAGES: str = "1,2"

    # WildApricot API (Form 990 / membership data extraction)
    WILDAPRICOT_OAUTH_URL: str = "https://oauth.wildapricot.org/auth/token"
    WILDAPRICOT_API_BASE_URL: str = "https://api.wildapricot.org"
    WILDAPRICOT_API_KEY: str = ""
    WILDAPRICOT_ACCOUNT_ID: str = ""
    WILDAPRICOT_TOKEN_REFRESH_BUFFER_SECONDS: int = 300
    WILDAPRICOT_HTTP_TIMEOUT_SECONDS: float = 60.0
    WILDAPRICOT_EXPORT_DIR: str = "exports/wildapricot"
    WILDAPRICOT_EXPORT_JSON: str = ""  # Optional fixed output file path
    WILDAPRICOT_EXPORT_CSV: bool = True
    # WildApricot allows ~30 requests/minute; stay below to avoid 429
    WILDAPRICOT_MAX_REQUESTS_PER_MINUTE: int = 28
    WILDAPRICOT_RETRY_MAX_ATTEMPTS: int = 8
    WILDAPRICOT_RETRY_429_DELAY_SECONDS: float = 62.0
    WILDAPRICOT_RETRY_429_MAX_DELAY_SECONDS: float = 120.0

    # QuickBooks API
    QUICKBOOKS_CLIENT_ID: str = ""
    QUICKBOOKS_CLIENT_SECRET: str = ""
    QUICKBOOKS_ACCESS_TOKEN: str = ""
    QUICKBOOKS_REFRESH_TOKEN: str = ""
    # One-time OAuth playground code; exchanged automatically when refresh_token fails
    QUICKBOOKS_AUTH_CODE: str = ""
    QUICKBOOKS_REDIRECT_URI: str = (
        "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"
    )
    QUICKBOOKS_REALM_ID: str = ""
    QUICKBOOKS_OAUTH_URL: str = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    QUICKBOOKS_SANDBOX_BASE_URL: str = "https://sandbox-quickbooks.api.intuit.com"
    QUICKBOOKS_OUTPUT_DIR: str = "data/quickbooks"
    # Access tokens expire in 60 minutes; refresh 5 minutes early by default
    QUICKBOOKS_TOKEN_REFRESH_BUFFER_SECONDS: int = 300
    QUICKBOOKS_HTTP_TIMEOUT_SECONDS: float = 60.0
    # Sandbox allows ~100 requests/minute per realm; stay below to avoid 429
    QUICKBOOKS_MAX_REQUESTS_PER_MINUTE: int = 90
    QUICKBOOKS_RETRY_MAX_ATTEMPTS: int = 8
    QUICKBOOKS_RETRY_429_DELAY_SECONDS: float = 62.0
    QUICKBOOKS_RETRY_429_MAX_DELAY_SECONDS: float = 120.0
    # Automatic token refresh
    QUICKBOOKS_AUTO_REFRESH_ENABLED: bool = True
    QUICKBOOKS_AUTO_REFRESH_INTERVAL_MINUTES: int = 50  # Refresh every 50 min (before 1hr expiry)

    @model_validator(mode="after")
    def _resolve_llm_model(self) -> "Settings":
        if self.LLM_MODEL and self.LLM_MODEL.strip():
            return self
        if self.MODEL_ID and self.MODEL_ID.strip():
            object.__setattr__(self, "LLM_MODEL", self.MODEL_ID.strip())
            return self
        object.__setattr__(
            self,
            "LLM_MODEL",
            "anthropic.claude-3-haiku-20240307-v1:0",
        )
        return self

    model_config = SettingsConfigDict(
        # Only use .env file if not in Lambda
        env_file=".env" if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else None,
        case_sensitive=True,
        extra="ignore"  # Ignore extra environment variables (like NEXT_PUBLIC_API_URL)
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

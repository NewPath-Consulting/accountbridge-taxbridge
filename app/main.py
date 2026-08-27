import asyncio
import logging
import os
import sys

core_path = os.path.join(os.path.dirname(__file__), "core")
if core_path not in sys.path:
    sys.path.insert(0, core_path)
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
import uvicorn

from app.api.dependencies.rate_limit import limiter
from app.api.dependencies.auth import require_api_auth
from app.api.endpoints import health, reports, benchmark, quickbooks, filing
from app.config.settings import get_settings
from app.observability.logging_config import configure_logging, request_id_ctx

# Load env and configure logging before creating app
_settings = get_settings()
configure_logging(log_level=_settings.LOG_LEVEL, log_format=_settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

IS_LAMBDA = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

SUPPORTED_EXTRACTOR_TYPES = ("AWS_textract", "goml_custom_extractor")


def _validate_config() -> None:
    """Validate EXTRACTOR_TYPE and required AWS config at startup; raise on error."""
    s = get_settings()
    if s.EXTRACTOR_TYPE not in SUPPORTED_EXTRACTOR_TYPES:
        msg = f"EXTRACTOR_TYPE must be one of {SUPPORTED_EXTRACTOR_TYPES}, got: {s.EXTRACTOR_TYPE}"
        logger.error(msg)
        raise ValueError(msg)
    if s.EXTRACTOR_TYPE == "AWS_textract":
        if not (s.BUCKET_NAME and s.BUCKET_NAME.strip()):
            msg = "BUCKET_NAME is required when EXTRACTOR_TYPE=AWS_textract"
            logger.error(msg)
            raise ValueError(msg)
        if not (s.LLM_MODEL and s.LLM_MODEL.strip()):
            logger.warning("LLM_MODEL is empty; LLM features may fail when EXTRACTOR_TYPE=AWS_textract")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init state and validate config. Shutdown: set draining and wait for in-flight requests."""
    _validate_config()
    app.state.request_count = 0
    app.state.draining = False
    
    # Start automatic token refresh service
    from app.services.token_refresh_service import start_token_refresh_service, stop_token_refresh_service
    logger.info("Starting automatic token refresh service")
    start_token_refresh_service()
    
    yield
    
    # Stop token refresh service
    logger.info("Stopping automatic token refresh service")
    stop_token_refresh_service()
    
    app.state.draining = True
    drain_seconds = get_settings().SHUTDOWN_DRAIN_SECONDS
    deadline = asyncio.get_event_loop().time() + drain_seconds
    while getattr(app.state, "request_count", 0) > 0 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.5)
    logger.info("Shutdown drain complete")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Read or generate X-Request-ID, set on state/response and inject into log context."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx.reset(token)


class DrainMiddleware(BaseHTTPMiddleware):
    """When draining: return 503. Otherwise track in-flight request count."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if not hasattr(request.app.state, "draining"):
            return await call_next(request)
        if request.app.state.draining:
            return JSONResponse(
                status_code=503,
                content={"detail": "Server is shutting down"},
                headers={"Retry-After": "30"},
            )
        request.app.state.request_count += 1
        try:
            return await call_next(request)
        finally:
            request.app.state.request_count -= 1


def create_app() -> FastAPI:
    """Create FastAPI app; use lifespan only when not running in Lambda."""
    app = FastAPI(
        title="AccountBridge Backend API",
        description="AccountBridge Backend API",
        version="2.0.0",
        lifespan=lifespan if not IS_LAMBDA else None,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(DrainMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "OPTIONS", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    
    # Routes (health is public; other API routes require bearer token when AUTH_METHOD=bearer)
    app.include_router(health.router, prefix="/api/health", tags=["Health"])
    app.include_router(
        reports.router,
        prefix="/api",
        tags=["Reports"],
        dependencies=[require_api_auth],
    )
    app.include_router(
        benchmark.router,
        prefix="/api",
        tags=["Benchmarking"],
        dependencies=[require_api_auth],
    )
    app.include_router(
        quickbooks.router,
        prefix="/api",
        tags=["QuickBooks"],
        dependencies=[require_api_auth],
    )

    app.include_router(
        filing.router,
        prefix="/api",
        tags=["Filing"],
        dependencies=[require_api_auth],
    )
    
    return app


app = create_app()

# Expose handler for Lambda
handler = Mangum(app, lifespan="off")
if __name__ == "__main__":
    uvicorn.run('app.main:app', host="0.0.0.0", port=8000, reload=True)
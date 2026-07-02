"""Reports generation endpoint."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.exceptions import ResponseValidationError
from typing import Optional, Any
import logging

from app.api.dependencies.rate_limit import limiter, rate_limit_string
from app.api.schemas.reports import ReportsRequest, ReportsResponse
from app.services.reports_service import ReportsService
from app.adapters.quickbooks.exceptions import (
    QuickBooksAuthError,
    QuickBooksRefreshTokenRequiredError,
    QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
)
from app.adapters.wildapricot.exceptions import WildApricotAuthError
from app.utils.reports_cache import latest_cache_path, load_cached_reports_response

logger = logging.getLogger(__name__)
router = APIRouter()


def _format_error_for_log(exc: Exception) -> str:
    """Return a concise error message without dumping full API payloads."""
    if isinstance(exc, ResponseValidationError):
        return f"response validation failed: {exc.errors()}"
    message = str(exc)
    if len(message) > 500:
        return f"{message[:500]}... [truncated, len={len(message)}]"
    return message


def _find_quickbooks_refresh_token_error(exc: BaseException) -> QuickBooksRefreshTokenRequiredError | None:
    """Extract QuickBooksRefreshTokenRequiredError from TaskGroup wrappers."""
    if isinstance(exc, QuickBooksRefreshTokenRequiredError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_quickbooks_refresh_token_error(sub)
            if found is not None:
                return found
    if exc.__cause__ is not None:
        return _find_quickbooks_refresh_token_error(exc.__cause__)
    return None


def _quickbooks_refresh_token_http_exception(
    *,
    wildapricot_data: dict | None = None,
) -> HTTPException:
    detail: dict[str, Any] = {
        "error": "quickbooks_refresh_token_required",
        "message": "Please enter a new QuickBooks refresh token.",
        "notify": QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
        "submit_endpoint": "/api/quickbooks/credentials",
    }
    if wildapricot_data is not None:
        detail["wildapricot_data_cached"] = True
        detail["wildapricot_data"] = wildapricot_data
    return HTTPException(status_code=401, detail=detail)


def get_reports_service() -> ReportsService:
    """Get or create reports service (dependency injection)."""
    return ReportsService()


@router.get(
    "/reports/cache/status",
    tags=["Reports"],
    summary="Check whether cached reports exist on the API server",
)
@limiter.limit(rate_limit_string)
async def cached_reports_status(request: Request):
    """Return cache availability and last-updated time for data/reports/latest.json."""
    path = latest_cache_path()
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No cached reports found. Run POST /api/reports first.",
        )
    mtime = path.stat().st_mtime
    return {
        "available": True,
        "path": str(path),
        "updated_at": datetime.fromtimestamp(mtime).isoformat(),
    }


@router.get(
    "/reports/cache",
    tags=["Reports"],
    summary="Load cached reports from the API server disk cache",
)
@limiter.limit(rate_limit_string)
async def get_cached_reports(request: Request):
    """Return the full /api/reports response saved to data/reports/latest.json."""
    try:
        return load_cached_reports_response()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/reports",
    response_model=ReportsResponse,
    tags=["Reports"],
    summary="Generate financial reports from WildApricot and QuickBooks data"
)
@limiter.limit(rate_limit_string)
async def generate_reports(
    request: Request,
    reports_request: ReportsRequest,
    reports_service: ReportsService = Depends(get_reports_service),
):
    """
    Generate three financial reports in parallel:
    1. Cash Flow Report
    2. Balance Sheet Report
    3. Tax Return Document (Form 990 support)
    
    The endpoint fetches QuickBooks data first, then WildApricot, and uses LLM
    to generate structured reports based on the combined data.
    
    Args:
        reports_request: Request containing WildApricot account ID, QuickBooks realm ID, and date range
        
    Returns:
        ReportsResponse containing all generated reports and source data
    """
    try:
        logger.info(
            f"Reports generation request received: "
            f"wildapricot_account={reports_request.wildapricot_account_id}, "
            f"quickbooks_realm={reports_request.quickbooks_realm_id}, "
            f"period={reports_request.start_date} to {reports_request.end_date}"
        )

        result = await reports_service.generate_reports(
            wildapricot_account_id=reports_request.wildapricot_account_id,
            quickbooks_realm_id=reports_request.quickbooks_realm_id,
            start_date=reports_request.start_date,
            end_date=reports_request.end_date,
            wildapricot_data=reports_request.wildapricot_data,
            quickbooks_credentials=reports_request.quickbooks_credentials,
            user_prompt=reports_request.user_prompt,
        )

        logger.info(f"Reports generation completed successfully for request_id={result['request_id']}")
        return result

    except HTTPException:
        raise

    except QuickBooksRefreshTokenRequiredError as e:
        logger.error("Reports generation failed (QuickBooks refresh token required): %s", e)
        raise _quickbooks_refresh_token_http_exception(
            wildapricot_data=e.wildapricot_data,
        ) from e

    except QuickBooksAuthError as e:
        logger.error(f"Reports generation failed (QuickBooks auth): {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=str(e),
        ) from e

    except WildApricotAuthError as e:
        logger.error(f"Reports generation failed (WildApricot auth): {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=str(e),
        ) from e

    except ResponseValidationError as e:
        logger.error(
            "Reports response validation failed request_id=unknown errors=%s",
            e.errors(),
        )
        raise HTTPException(
            status_code=500,
            detail="Reports generation produced an invalid response shape",
        ) from e

    except Exception as e:
        qb_refresh_error = _find_quickbooks_refresh_token_error(e)
        if qb_refresh_error is not None:
            logger.error(
                "Reports generation failed (QuickBooks refresh token required): %s",
                qb_refresh_error,
            )
            raise _quickbooks_refresh_token_http_exception(
                wildapricot_data=qb_refresh_error.wildapricot_data,
            ) from qb_refresh_error

        logger.error(
            "Reports generation failed: %s",
            _format_error_for_log(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Reports generation failed: {_format_error_for_log(e)}",
        )

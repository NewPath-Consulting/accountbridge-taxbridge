"""Submit a prepared Form 990-N to Tax990.

Separate from `/api/filing/prepare` on purpose. Preparation is idempotent and
free: it reads a ledger and computes. Submission creates a record inside an
IRS-authorised e-file provider, so it happens only when a preparer asks for it,
against a payload they have already seen.

That division is the human review gate the specification requires, made
concrete: nothing is transmitted that has not been shown first.
"""

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional

from app.adapters.tax990.client import (
    SANDBOX_API_HOST,
    SANDBOX_OAUTH_HOST,
    Tax990Client,
)
from app.adapters.tax990.exceptions import (
    Tax990AuthError,
    Tax990Error,
    Tax990ValidationError,
)
from app.api.dependencies.rate_limit import limiter, rate_limit_string
from app.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class SubmitFilingRequest(BaseModel):
    """A payload from /api/filing/prepare, unchanged."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"payload": {"Form990NRecords": [{"Business": {}, "Form990N": {}}]}}]
        }
    )

    payload: Dict[str, Any] = Field(
        ...,
        description="The Form990NRecords body produced by /api/filing/prepare",
    )
    include_pdf: bool = Field(
        True,
        description="Return the rendered form inline, base64 encoded",
    )


class SubmitFilingResponse(BaseModel):
    status: str = Field(..., description="submitted | rejected")
    submission_id: Optional[str] = None
    record_id: Optional[str] = None
    return_number: Optional[str] = None
    already_existed: bool = Field(
        False,
        description=(
            "True when Tax990 already held a return for this organization and "
            "year, in which case the existing draft was retrieved"
        ),
    )
    validation_errors: List[Dict[str, Any]] = Field(default_factory=list)
    pdf_url: Optional[str] = None
    pdf_base64: Optional[str] = None
    is_sandbox: bool = True
    message: str = ""


def get_tax990_client() -> Tax990Client:
    """Build a client from configuration.

    Sandbox unless both hosts are set, so a partially configured environment
    cannot reach production.
    """
    return Tax990Client(
        client_id=getattr(settings, "TAX990_CLIENT_ID", "") or "",
        client_secret_id=getattr(settings, "TAX990_CLIENT_SECRET_ID", "") or "",
        user_token=getattr(settings, "TAX990_USER_TOKEN", "") or "",
        oauth_host=getattr(settings, "TAX990_OAUTH_HOST", "") or SANDBOX_OAUTH_HOST,
        api_host=getattr(settings, "TAX990_API_HOST", "") or SANDBOX_API_HOST,
    )


@router.post(
    "/filing/submit",
    response_model=SubmitFilingResponse,
    tags=["Filing"],
    summary="Submit a prepared Form 990-N to Tax990",
)
@limiter.limit(rate_limit_string)
async def submit_filing(
    request: Request,
    submit_request: SubmitFilingRequest,
):
    """Send a prepared 990-N and return the rendered form.

    Runs Tax990's full lifecycle: authenticate, create the draft, run their
    validation, and retrieve the PDF. When a return already exists for the
    organization and tax year Tax990 declines to create a second one, which is
    correct; the existing draft is retrieved instead and `already_existed` is
    set.

    Only the Form 990-N is accepted. Tax990's API does not yet support the
    990-EZ or the full 990.
    """
    try:
        client = get_tax990_client()
    except Tax990AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not submit_request.payload.get("Form990NRecords"):
        raise HTTPException(
            status_code=400,
            detail="The payload has no Form990NRecords. Prepare the filing first.",
        )

    try:
        logger.info(
            "Submitting Form 990-N to Tax990 (%s)",
            "sandbox" if client.is_sandbox else "PRODUCTION",
        )
        result = client.submit_990n(submit_request.payload)

    except Tax990ValidationError as exc:
        logger.info("Tax990 rejected the return: %s", exc.errors)
        return SubmitFilingResponse(
            status="rejected",
            validation_errors=exc.errors,
            is_sandbox=client.is_sandbox,
            message=str(exc),
        )
    except Tax990AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Tax990Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    pdf_base64 = None
    if submit_request.include_pdf and result.get("pdf_url"):
        try:
            pdf_base64 = base64.b64encode(
                client.download_pdf(result["pdf_url"])
            ).decode("ascii")
        except Tax990Error as exc:
            # The return exists either way; only the rendering is missing.
            logger.info("Could not download the rendered form: %s", exc)

    message = (
        "Tax990 already held a return for this organization and tax year; the "
        "existing draft was retrieved."
        if result["already_existed"]
        else f"Return {result.get('return_number') or ''} created."
    )
    if client.is_sandbox:
        message += " Sandbox only — this is not a live filing."

    logger.info(
        "Tax990 submission complete: record=%s existed=%s errors=%d",
        result.get("record_id"),
        result["already_existed"],
        len(result.get("validation_errors") or []),
    )

    return SubmitFilingResponse(
        status="submitted",
        submission_id=result.get("submission_id"),
        record_id=result.get("record_id"),
        return_number=result.get("return_number"),
        already_existed=result["already_existed"],
        validation_errors=result.get("validation_errors") or [],
        pdf_url=result.get("pdf_url"),
        pdf_base64=pdf_base64,
        is_sandbox=result.get("is_sandbox", True),
        message=message,
    )

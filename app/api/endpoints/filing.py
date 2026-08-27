"""Filing preparation endpoints.

Two routes, both fast because neither calls a model:

    POST /api/filing/lookup    an EIN in, identity and filing history out
    POST /api/filing/prepare   a QuickBooks period in, a routed payload out

`/reports` remains the slow path: it makes three sequential model calls to
produce a full Form 990 draft. Preparing a filing is arithmetic and rules,
and returns in under a second.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.quickbooks.exceptions import (
    QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
    QuickBooksAuthError,
    QuickBooksRefreshTokenRequiredError,
)
from app.api.dependencies.rate_limit import limiter, rate_limit_string
from app.api.schemas.filing import (
    LookupRequest,
    LookupResponse,
    PrepareFilingRequest,
    PrepareFilingResponse,
)
from app.services.filing_service import FilingPreparationService
from app.utils.organization_lookup import lookup_organization

logger = logging.getLogger(__name__)
router = APIRouter()


def get_filing_service() -> FilingPreparationService:
    """Filing service (dependency injection)."""
    return FilingPreparationService()


@router.post(
    "/filing/lookup",
    response_model=LookupResponse,
    tags=["Filing"],
    summary="Look up an organization's identity and filing history by EIN",
)
@limiter.limit(rate_limit_string)
async def lookup(request: Request, lookup_request: LookupRequest):
    """Fetch what ProPublica holds for an EIN.

    Supplies the legal name and address for the return, and two things that
    change the routing outcome: the ruling date, which gives the organization's
    age and so which 990-N threshold applies, and prior-year gross receipts for
    the multi-year test.

    The principal officer is not published by ProPublica and must be entered by
    the preparer. A miss is not an error: the response carries `found: false`
    and a reason, so the details can be entered by hand instead.
    """
    logger.info("Organization lookup requested for EIN %s", lookup_request.ein)
    result = lookup_organization(lookup_request.ein)
    return LookupResponse(**result.as_dict())


@router.post(
    "/filing/prepare",
    response_model=PrepareFilingResponse,
    tags=["Filing"],
    summary="Prepare a filing from QuickBooks: totals, gross receipts, routing, payload",
)
@limiter.limit(rate_limit_string)
async def prepare_filing(
    request: Request,
    filing_request: PrepareFilingRequest,
    filing_service: FilingPreparationService = Depends(get_filing_service),
):
    """Run the deterministic path from the ledger to a submission payload.

    Five stages, each reported with what it found:

    1. **Source data** — the income accounts read from QuickBooks
    2. **Deterministic totals** — every figure computed in code, reconciled
       against QuickBooks' own totals
    3. **Gross receipts** — on the IRS basis, before costs are subtracted,
       which is not the same as total revenue
    4. **Form routing** — 990-N, 990-EZ or full 990, with the reason and any
       review flag
    5. **Payload** — assembled for the routed variant

    No model is called at any point, so this returns in under a second. A
    990-N payload is complete from this alone; the 990-EZ and full 990 carry
    financial detail and need `report_content` from a prior reports run.
    """
    try:
        logger.info(
            "Filing preparation requested: realm=%s period=%s to %s",
            filing_request.quickbooks_realm_id,
            filing_request.start_date,
            filing_request.end_date,
        )

        credentials = (
            filing_request.quickbooks_credentials.model_dump(exclude_none=True)
            if filing_request.quickbooks_credentials
            else None
        )

        result = await filing_service.prepare(
            quickbooks_realm_id=filing_request.quickbooks_realm_id,
            start_date=filing_request.start_date,
            end_date=filing_request.end_date,
            quickbooks_credentials=credentials,
            organization=filing_request.organization.model_dump(exclude_none=True),
            prior_year_gross_receipts=filing_request.prior_year_gross_receipts,
            organization_age_years=filing_request.organization_age_years,
            report_content=filing_request.report_content,
        )

        logger.info(
            "Filing preparation complete: status=%s variant=%s in %.2fs",
            result["status"],
            result["routed_form_variant"],
            result["processing_time"],
        )
        return PrepareFilingResponse(**result)

    except QuickBooksRefreshTokenRequiredError:
        raise HTTPException(
            status_code=401, detail=QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE
        )
    except QuickBooksAuthError as exc:
        raise HTTPException(status_code=401, detail=f"QuickBooks authentication failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.error("Filing preparation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Filing preparation failed: {exc}")

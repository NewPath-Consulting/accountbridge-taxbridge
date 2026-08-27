"""Prepare a filing: from the ledger to a payload, without the model.

The reports pipeline produces a full Form 990 draft in about four minutes,
because it makes three sequential model calls. Preparing a filing is a
different job and a much smaller one:

    QuickBooks  ->  totals  ->  gross receipts  ->  routing  ->  payload

Every stage is deterministic. Nothing here calls a model, so the whole thing
runs in seconds rather than minutes.

That matters beyond speed. Form selection is the decision with the largest
consequence -- an organization that files the wrong variant is treated by the
IRS as not having filed at all -- and it is now made from computed figures
with no generated content anywhere in the path.

For a Form 990-N the payload is complete from this alone, because a 990-N
carries no financial detail. The 990-EZ and the full 990 do, so their
elements are filled in from a prior reports run when one is supplied, and
reported as outstanding when it is not.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Optional

from app.utils.draft_payload import build_draft_payload
from app.utils.form_990_totals import section_rows, section_totals
from app.utils.form_990ez import build_form_990ez
from app.utils.form_990n import build_form_990n_payload
from app.utils.form_routing import FORM_990, FORM_990EZ, FORM_990N, route_form_variant
from app.utils.gross_receipts import gross_receipts_from_pl

logger = logging.getLogger(__name__)

__all__ = ["FilingPreparationService", "STAGE_ORDER"]

# A period whose receipts differ from the recent average by more than this
# is either a genuine anomaly or a sign that the ledger and the filing
# history belong to different organizations. Either way a preparer should
# look before the return is filed.
HISTORY_DIVERGENCE_FACTOR = 5.0

STAGE_ORDER = (
    "source_data",
    "deterministic_totals",
    "gross_receipts",
    "form_routing",
    "payload",
)


def _stage(name: str, status: str, summary: str, **detail: Any) -> dict[str, Any]:
    return {"stage": name, "status": status, "summary": summary, "detail": detail}


class FilingPreparationService:
    """Runs the deterministic path from ledger to payload."""

    def __init__(self, quickbooks_client_factory: Any = None) -> None:
        """`quickbooks_client_factory` is a seam for tests: any callable
        returning an object with `get_profit_and_loss`. Left unset, the real
        adapter is imported on first use."""
        self._quickbooks_client_factory = quickbooks_client_factory
        logger.info("FilingPreparationService initialized")

    async def prepare(
        self,
        *,
        quickbooks_realm_id: str,
        start_date: str,
        end_date: str,
        quickbooks_credentials: Optional[Mapping[str, Any]] = None,
        organization: Optional[Mapping[str, Any]] = None,
        prior_year_gross_receipts: Optional[list[float]] = None,
        organization_age_years: Optional[float] = None,
        report_content: Optional[Mapping[str, Any]] = None,
        tax_year: Optional[str] = None,
    ) -> dict[str, Any]:
        """Prepare a filing and report each stage.

        `report_content` is the `tax_return.content` from a prior reports run.
        Supplying it enables the 990-EZ and full 990 elements; without it the
        routing decision and any 990-N payload are still produced.

        `tax_year` is the year printed on the return, which is not always the
        year of the accounting period: an organization on a fiscal year files
        against the year the period began, and a sandbox whose transactions sit
        in the current year cannot be filed at all, since a year cannot be
        filed before it has ended. Left unset, the year of `end_date` is used.
        """
        started = time.time()
        stages: list[dict[str, Any]] = []

        # --- 1. source data ------------------------------------------------
        pl_report = await self._fetch_profit_and_loss(
            quickbooks_realm_id, start_date, end_date, quickbooks_credentials
        )
        accounts = section_rows(pl_report, "Income") if pl_report else []
        if not accounts:
            stages.append(_stage(
                "source_data", "failed",
                "QuickBooks returned no income accounts for this period.",
                realm_id=quickbooks_realm_id, period=f"{start_date} to {end_date}",
            ))
            return self._result(stages, started, form=None)

        stages.append(_stage(
            "source_data", "ok",
            f"Read {len(accounts)} income accounts from QuickBooks.",
            realm_id=quickbooks_realm_id,
            period=f"{start_date} to {end_date}",
            accounts=[
                {"name": a.name, "amount": a.amount, "account_id": a.account_id}
                for a in accounts
            ],
        ))

        # --- 2. deterministic totals ---------------------------------------
        totals = section_totals(pl_report)
        walked = round(sum(a.amount for a in accounts), 2)
        reported = round(totals.get("income", 0.0), 2)
        reconciles = walked == reported

        stages.append(_stage(
            "deterministic_totals",
            "ok" if reconciles else "warning",
            (
                f"Computed total income of {reported:,.2f}, reconciling exactly "
                f"to QuickBooks."
                if reconciles else
                f"Accounts sum to {walked:,.2f} against a reported total of "
                f"{reported:,.2f}."
            ),
            income=reported,
            cost_of_goods_sold=round(totals.get("cogs", 0.0), 2),
            expenses=round(totals.get("expenses", 0.0), 2),
            other_expenses=round(totals.get("other_expenses", 0.0), 2),
            walked_sum=walked,
            reconciles=reconciles,
        ))

        # --- 3. gross receipts ---------------------------------------------
        computed = gross_receipts_from_pl(pl_report)
        if computed is None:
            stages.append(_stage(
                "gross_receipts", "failed",
                "Could not compute gross receipts from the profit and loss.",
            ))
            return self._result(stages, started, form=None)

        stages.append(_stage(
            "gross_receipts", "ok",
            (
                f"Gross receipts {computed.total:,.2f} \u2014 total revenue "
                f"{computed.revenue:,.2f} plus {computed.cost_of_goods_sold:,.2f} "
                f"of costs added back, as the IRS filing thresholds require."
            ),
            **computed.as_dict(),
        ))

        # --- 4. routing -----------------------------------------------------
        total_assets = self._total_assets(report_content)
        routing = route_form_variant(
            computed.total,
            total_assets,
            prior_year_gross_receipts=tuple(prior_year_gross_receipts or ()),
            organization_age_years=organization_age_years,
        )

        routing_detail = routing.as_dict()
        divergence = self._history_divergence(
            computed.total, prior_year_gross_receipts
        )
        if divergence:
            routing_detail["requires_human_review"] = True
            routing_detail["review_reasons"] = [
                *routing_detail.get("review_reasons", []),
                divergence,
            ]

        needs_review = routing_detail["requires_human_review"]
        stages.append(_stage(
            "form_routing",
            "review" if needs_review else "ok",
            (
                f"Routed to Form {routing.form}."
                + (" Held for preparer review." if needs_review else "")
            ),
            **routing_detail,
        ))

        # --- 5. payload -----------------------------------------------------
        content = self._merge_content(
            report_content, organization, computed, tax_year or end_date
        )
        payload_stage, payload = self._build_payload(content, routing, report_content)
        stages.append(payload_stage)

        return self._result(
            stages, started, form=routing.form, routing=routing, payload=payload
        )

    # --- payload assembly --------------------------------------------------

    def _build_payload(
        self,
        content: dict[str, Any],
        routing: Any,
        report_content: Optional[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if routing.form == FORM_990N:
            result = build_form_990n_payload(content, routing, allow_placeholder_phone=False)
            if result.is_submittable:
                return _stage(
                    "payload", "ready",
                    "Form 990-N payload assembled and ready to file.",
                    variant=FORM_990N,
                    warnings=result.warnings,
                    payload=result.payload,
                    filing_available=True,
                ), result.payload
            return _stage(
                "payload", "blocked",
                "Form 990-N payload incomplete.",
                variant=FORM_990N,
                blocking_errors=result.blocking_errors,
                warnings=result.warnings,
                filing_available=True,
            ), None

        if routing.form == FORM_990EZ:
            if not report_content:
                return _stage(
                    "payload", "blocked",
                    "Form 990-EZ requires the classified revenue and expense detail "
                    "from a reports run. Generate the reports first.",
                    variant=FORM_990EZ, filing_available=False,
                ), None
            ez = build_form_990ez(content)
            draft = build_draft_payload(content, routing, form_990ez=ez)
            return _stage(
                "payload",
                "ready" if ez.is_internally_consistent else "blocked",
                (
                    "Form 990-EZ prepared. Awaiting Tax990 endpoint support before "
                    "it can be filed."
                    if ez.is_internally_consistent else
                    "Form 990-EZ prepared but its internal checks did not hold."
                ),
                variant=FORM_990EZ,
                check_failures=ez.check_failures,
                warnings=ez.warnings,
                payload=draft.payload,
                filing_available=False,
            ), draft.payload

        if not report_content:
            return _stage(
                "payload", "blocked",
                "The full Form 990 requires a reports run. Generate the reports first.",
                variant=FORM_990, filing_available=False,
            ), None

        draft = build_draft_payload(content, routing)
        return _stage(
            "payload", "ready",
            "Full Form 990 prepared. Awaiting Tax990 endpoint support before it "
            "can be filed.",
            variant=FORM_990,
            payload=draft.payload,
            filing_available=False,
        ), draft.payload

    # --- helpers -----------------------------------------------------------

    async def _fetch_profit_and_loss(
        self,
        realm_id: str,
        start_date: str,
        end_date: str,
        credentials: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Return the raw profit and loss. The totals engine walks the tree
        itself, so no post-processing is applied here."""
        factory = self._quickbooks_client_factory
        if factory is None:
            from app.adapters.quickbooks.client import QuickBooksClient

            factory = QuickBooksClient

        client = factory(**(dict(credentials) if credentials else {}))
        return await client.get_profit_and_loss(realm_id, start_date, end_date)

    @staticmethod
    def _history_divergence(
        current: float, priors: Optional[list[float]]
    ) -> Optional[str]:
        """Flag a period wildly out of line with the filing history.

        The most likely cause in practice is that the organization looked up
        and the ledger being read are not the same one: the identity comes
        from an EIN typed by the preparer, the figures from whichever
        QuickBooks company is connected, and nothing forces them to agree.
        A genuine tenfold swing is worth a second look regardless.
        """
        usable = [float(p) for p in (priors or []) if p]
        if not usable or current <= 0:
            return None

        average = sum(usable) / len(usable)
        if average <= 0:
            return None

        ratio = max(current, average) / min(current, average)
        if ratio < HISTORY_DIVERGENCE_FACTOR:
            return None

        direction = "below" if current < average else "above"
        return (
            f"Gross receipts of {current:,.2f} are {ratio:.0f}x {direction} the "
            f"{len(usable)}-year average of {average:,.2f}. Confirm the filing "
            f"history and the accounting records belong to the same organization."
        )

    @staticmethod
    def _total_assets(report_content: Optional[Mapping[str, Any]]) -> float | None:
        if not report_content:
            return None
        totals = (
            (report_content.get("partX_balanceSheet") or {}).get("totalAssets") or {}
        )
        value = totals.get("endOfYear")
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _merge_content(
        report_content: Optional[Mapping[str, Any]],
        organization: Optional[Mapping[str, Any]],
        computed: Any,
        end_date: str,
    ) -> dict[str, Any]:
        """Combine a prior report with identity supplied by the preparer."""
        content: dict[str, Any] = dict(report_content or {})

        org = dict(content.get("organizationInformation") or {})
        for key, value in (organization or {}).items():
            if value not in (None, "", {}, []):
                org[key] = value
        content["organizationInformation"] = org

        summary = dict(content.get("organization_summary") or {})
        summary["gross_receipts"] = computed.total
        summary["gross_receipts_basis"] = computed.as_dict()
        summary.setdefault("tax_year", (end_date or "")[:4])
        if org.get("legalName"):
            summary["organization_name"] = org["legalName"]
        if org.get("ein"):
            summary["ein"] = org["ein"]
        content["organization_summary"] = summary

        return content

    @staticmethod
    def _result(
        stages: list[dict[str, Any]],
        started: float,
        *,
        form: str | None,
        routing: Any = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blocked = [s for s in stages if s["status"] in ("failed", "blocked")]
        return {
            "status": "blocked" if blocked else "prepared",
            "routed_form_variant": form,
            "stages": stages,
            "payload": payload,
            "routing": routing.as_dict() if routing is not None else None,
            "filing_available": bool(form == FORM_990N),
            "processing_time": round(time.time() - started, 2),
        }

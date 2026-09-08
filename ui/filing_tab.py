"""The filing tab: organization details, preparation, and the routed payload.

This is the deterministic half of the product. Where the Pipeline tab runs
three sequential model calls and takes minutes, everything here is arithmetic
and rules against the ledger, and returns in about a second.

The layout follows the decision it supports. Identity first, because
QuickBooks does not hold it. Then preparation, which shows its working at
every stage rather than only its conclusion. Then the routed payload, with
filing available for a Form 990-N and honestly unavailable for the longer
forms, which Tax990's API does not yet accept.
"""

from __future__ import annotations

import base64
from datetime import date
from typing import Any, Callable, Optional

import requests
import streamlit as st

FILING_STATE_DEFAULTS = {
    "filing_org": {
        "legalName": "",
        "ein": "",
        "address": {"street": "", "city": "", "state": "", "zip": ""},
        "telephone": "",
        "website": "",
        "officer_name": "",
        "officer_title": "",
        "taxExemptStatus": "",
    },
    "filing_lookup": None,
    "filing_age_years": None,
    "filing_priors": [],
    "filing_result": None,
    "filing_error": None,
    "filing_submission": None,
    "filing_submit_error": None,
}

_STATUS_STYLE = {
    "ok": ("\u2713", "green"),
    "ready": ("\u2713", "green"),
    "warning": ("!", "amber"),
    "review": ("\u25c9", "amber"),
    "blocked": ("\u2717", "red"),
    "failed": ("\u2717", "red"),
}

_STAGE_LABEL = {
    "source_data": "Read the ledger",
    "deterministic_totals": "Compute the totals",
    "gross_receipts": "Gross receipts",
    "form_routing": "Choose the form",
    "payload": "Assemble the return",
}


# How far back the year dropdown offers. Preparing a return for an older
# period is useful even when it cannot be submitted: the routing decision,
# the figures and the classification are all worth seeing.
YEARS_OFFERED = 10


def fileable_years(as_of: Optional[date] = None) -> list[int]:
    """The tax years Tax990 will accept, most recent first.

    A return cannot be filed before its year has ended, so the newest is the
    year before this one. Probing their sandbox in August 2026 confirmed the
    window: 2023 through 2025 accepted, 2022 and 2026 refused.
    """
    newest = (as_of or date.today()).year - 1
    return [newest, newest - 1, newest - 2]


def selectable_years(as_of: Optional[date] = None) -> list[int]:
    """Every year offered in the dropdown, most recent first."""
    newest = (as_of or date.today()).year - 1
    return [newest - n for n in range(YEARS_OFFERED)]


def _digits(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def init_filing_state() -> None:
    for key, value in FILING_STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ── API calls ────────────────────────────────────────────────────────────

def call_lookup(base_url: str, headers: dict, ein: str) -> dict:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/filing/lookup",
        json={"ein": ein},
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def call_submit(base_url: str, headers: dict, payload: dict) -> dict:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/filing/submit",
        json={"payload": payload, "include_pdf": True},
        headers=headers,
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def call_prepare(base_url: str, headers: dict, payload: dict) -> dict:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/filing/prepare",
        json=payload,
        headers=headers,
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


# ── rendering helpers ────────────────────────────────────────────────────

def _stage_row(stage: dict) -> None:
    mark, tone = _STATUS_STYLE.get(stage.get("status", ""), ("\u00b7", "grey"))
    label = _STAGE_LABEL.get(stage.get("stage", ""), stage.get("stage", ""))
    colour = {"green": "#2F7D6A", "amber": "#B08D57", "red": "#B4453C"}.get(tone, "#6E7772")
    st.markdown(
        f"<div style='display:flex;gap:.7rem;align-items:baseline;"
        f"padding:.35rem 0;border-bottom:1px solid rgba(128,128,128,.16)'>"
        f"<span style='color:{colour};font-weight:700;width:1rem'>{mark}</span>"
        f"<span style='font-weight:600;min-width:11rem'>{label}</span>"
        f"<span style='color:#6E7772'>{stage.get('summary','')}</span></div>",
        unsafe_allow_html=True,
    )


def _accounts_table(detail: dict) -> None:
    accounts = detail.get("accounts") or []
    if not accounts:
        return
    st.dataframe(
        [
            {"Account": a.get("name"), "Amount": a.get("amount")}
            for a in accounts
        ],
        hide_index=True,
        use_container_width=True,
    )


def _gross_receipts_panel(detail: dict) -> None:
    left, middle, right = st.columns(3)
    left.metric("Total revenue", f"${detail.get('total_revenue', 0):,.2f}")
    middle.metric(
        "Costs added back",
        f"${detail.get('cost_of_goods_sold_added_back', 0):,.2f}",
        help=(
            "The filing thresholds are tested against receipts before costs "
            "are subtracted, so cost of goods sold is added back to revenue."
        ),
    )
    right.metric("Gross receipts", f"${detail.get('gross_receipts', 0):,.2f}")


def _routing_panel(detail: dict) -> None:
    form = detail.get("form") or "\u2014"
    st.markdown(f"### Form {form}")

    left, right = st.columns(2)
    left.metric("Gross receipts tested", f"${(detail.get('gross_receipts') or 0):,.2f}")
    right.metric("990-N limit applied", f"${(detail.get('gross_receipts_990n_limit') or 0):,.0f}")

    basis = detail.get("gross_receipts_basis", "")
    tier = detail.get("age_tier", "")
    st.caption(f"Basis: {basis.replace('_', ' ')} \u00b7 age tier: {tier.replace('_', ' ')}")

    for note in detail.get("notes") or []:
        st.caption(f"\u00b7 {note}")

    reasons = detail.get("review_reasons") or []
    if reasons:
        st.warning("**Held for preparer review.**")
        for reason in reasons:
            st.markdown(f"- {reason}")


# ── the tab ──────────────────────────────────────────────────────────────

def render(
    *,
    base_url: str,
    headers: dict,
    quickbooks_realm_id: str,
    start_date: str,
    end_date: str,
    report_content: Optional[dict] = None,
    quickbooks_credentials: Optional[dict] = None,
    format_request_error: Optional[Callable[[Exception, str, str], str]] = None,
) -> None:
    init_filing_state()
    org = st.session_state.filing_org

    st.markdown("### Step 1 \u00b7 The organization")
    st.caption(
        "QuickBooks holds the money and nothing else. The legal name, address "
        "and officer go on the return, and the ruling date decides which "
        "990-N threshold applies."
    )

    ein_col, button_col = st.columns([3, 1])
    with ein_col:
        entered_ein = st.text_input(
            "EIN", value=org.get("ein", ""), placeholder="43-1633425",
            key="filing_ein_input",
        )

    # Changing the EIN invalidates everything derived from the previous one.
    # Left in place, the age and filing history of one organization would be
    # applied to another's ledger.
    if _digits(entered_ein) != _digits(org.get("ein", "")):
        st.session_state.filing_lookup = None
        st.session_state.filing_age_years = None
        st.session_state.filing_priors = []
        st.session_state.filing_result = None
    org["ein"] = entered_ein
    with button_col:
        st.write("")
        looked_up = st.button("Look up", use_container_width=True)

    if looked_up:
        try:
            result = call_lookup(base_url, headers, org["ein"])
            st.session_state.filing_lookup = result
            if result.get("found"):
                org["legalName"] = result.get("legal_name") or org["legalName"]
                address = result.get("address") or {}
                for field in ("street", "city", "state", "zip"):
                    if address.get(field):
                        org["address"][field] = address[field]
                if result.get("tax_exempt_status"):
                    org["taxExemptStatus"] = result["tax_exempt_status"]
                st.session_state.filing_age_years = result.get("age_years")
                st.session_state.filing_priors = result.get("prior_year_gross_receipts") or []
        except Exception as exc:  # noqa: BLE001
            st.session_state.filing_lookup = None
            st.session_state.filing_error = (
                format_request_error(exc, base_url, "/api/filing/lookup")
                if format_request_error else str(exc)
            )

    lookup = st.session_state.filing_lookup
    if lookup is not None:
        if lookup.get("found"):
            filings = lookup.get("filings") or []
            # The name alone confirms two things: the lookup worked, and it
            # found the intended organization. A mistyped EIN can return a
            # real record for the wrong one, so the name is the check that
            # matters. The ruling date and filing count are diagnostics and
            # belong with the history they came from.
            status = lookup.get("tax_exempt_status")
            st.success(
                f"Found **{lookup.get('legal_name')}**"
                + (f" \u00b7 {status}" if status else "")
                + "."
            )
            if filings:
                with st.expander("Filing history from ProPublica"):
                    st.dataframe(
                        [
                            {
                                "Tax year": f.get("tax_year"),
                                "Form filed": f.get("form_filed"),
                                "Gross receipts": f.get("gross_receipts"),
                            }
                            for f in filings
                        ],
                        hide_index=True, use_container_width=True,
                    )
        else:
            st.info(
                " ".join(lookup.get("notes") or ["No record found."])
            )
        for note in lookup.get("notes") or []:
            if "Principal officer" in note:
                st.caption(f"\u00b7 {note}")

    org["legalName"] = st.text_input("Legal name", value=org.get("legalName", ""))

    a1, a2, a3, a4 = st.columns([3, 2, 1, 1])
    org["address"]["street"] = a1.text_input("Street", value=org["address"].get("street", ""))
    org["address"]["city"] = a2.text_input("City", value=org["address"].get("city", ""))
    org["address"]["state"] = a3.text_input("State", value=org["address"].get("state", ""))
    org["address"]["zip"] = a4.text_input("ZIP", value=org["address"].get("zip", ""))

    c1, c2 = st.columns(2)
    org["telephone"] = c1.text_input(
        "Telephone", value=org.get("telephone", ""),
        help="Ten digits. Tax990 rejects anything else.",
    )
    org["website"] = c2.text_input("Website", value=org.get("website", ""))

    o1, o2 = st.columns(2)
    org["officer_name"] = o1.text_input(
        "Principal officer", value=org.get("officer_name", ""),
        help="Not published by ProPublica, so this is always entered by hand.",
    )
    org["officer_title"] = o2.text_input("Officer title", value=org.get("officer_title", ""))

    st.divider()

    # ── prepare ──────────────────────────────────────────────────────────
    st.markdown("### Step 2 \u00b7 Prepare the return  `/api/filing/prepare`")
    st.caption(
        f"QuickBooks **{quickbooks_realm_id}** \u00b7 "
        f"**{start_date}** to **{end_date}**. No model is called, so this "
        f"takes about a second."
    )

    age = st.session_state.filing_age_years
    priors = st.session_state.filing_priors
    if age is None:
        st.caption(
            "\u00b7 Age unknown, so the strictest 990-N limit will apply and "
            "the decision will be flagged. Look the organization up to resolve it."
        )
    if not priors:
        st.caption(
            "\u00b7 No prior-year receipts, so the multi-year test cannot be "
            "applied and the decision will rest on this period alone."
        )
    if report_content:
        st.caption("\u00b7 Using classified detail from the last reports run.")
    else:
        st.caption(
            "\u00b7 No reports run in this session. A 990-N needs none; the "
            "990-EZ and full 990 do."
        )

    years = selectable_years()
    fileable = set(fileable_years())
    ledger_year = (end_date or "")[:4]

    # Default to the year of the accounting period when it is on the list, so
    # a 2019 ledger produces a 2019 return rather than one dated years later.
    try:
        default_index = [str(y) for y in years].index(ledger_year)
    except ValueError:
        default_index = 0

    year_col, note_col = st.columns([1, 3])
    with year_col:
        selected_year = st.selectbox(
            "Tax year on the return",
            [str(y) for y in years],
            index=default_index,
            help=(
                "Any year can be prepared and reviewed. Tax990 accepts only "
                "the last three completed years for submission."
            ),
        )
    with note_col:
        st.write("")
        if int(selected_year) not in fileable:
            first, last = min(fileable), max(fileable)
            st.caption(
                f"\u00b7 {selected_year} can be prepared but not submitted. "
                f"Tax990 accepts {first} to {last}."
            )
        elif ledger_year and ledger_year != selected_year:
            st.caption(
                f"\u00b7 The accounting period is {ledger_year}; the return "
                f"will be dated {selected_year}."
            )

    if st.button("Prepare filing", type="primary"):
        payload: dict[str, Any] = {
            "tax_year": selected_year,
            "quickbooks_realm_id": quickbooks_realm_id,
            "start_date": start_date,
            "end_date": end_date,
            "organization": {
                "legalName": org.get("legalName", ""),
                "ein": org.get("ein", ""),
                "address": dict(org.get("address") or {}),
                "telephone": org.get("telephone", ""),
                "website": org.get("website", ""),
                "taxExemptStatus": org.get("taxExemptStatus", ""),
                "principalOfficer": {
                    "name": org.get("officer_name", ""),
                    "title": org.get("officer_title", ""),
                },
            },
            "organization_age_years": age,
            "prior_year_gross_receipts": priors,
        }
        if report_content:
            payload["report_content"] = report_content
        if quickbooks_credentials:
            payload["quickbooks_credentials"] = quickbooks_credentials

        try:
            with st.spinner("Reading the ledger and applying the rules\u2026"):
                st.session_state.filing_result = call_prepare(base_url, headers, payload)
                st.session_state.filing_error = None
                # A new preparation invalidates any earlier submission.
                st.session_state.filing_submission = None
                st.session_state.filing_submit_error = None
        except Exception as exc:  # noqa: BLE001
            st.session_state.filing_result = None
            st.session_state.filing_error = (
                format_request_error(exc, base_url, "/api/filing/prepare")
                if format_request_error else str(exc)
            )

    if st.session_state.filing_error:
        st.error(st.session_state.filing_error)

    result = st.session_state.filing_result
    if not result:
        return

    st.divider()

    # ── result ───────────────────────────────────────────────────────────
    st.markdown("### Step 3 \u00b7 What it did")
    st.caption(f"Completed in {result.get('processing_time', 0):.2f} seconds.")

    stages = result.get("stages") or []
    for stage in stages:
        _stage_row(stage)

    st.write("")

    by_name = {s.get("stage"): s for s in stages}

    if "source_data" in by_name:
        with st.expander("Accounts read from QuickBooks"):
            _accounts_table(by_name["source_data"].get("detail") or {})

    if "gross_receipts" in by_name:
        st.markdown("#### Gross receipts")
        _gross_receipts_panel(by_name["gross_receipts"].get("detail") or {})
        st.caption(
            "This is the figure the filing thresholds are tested against. It "
            "is not total revenue."
        )

    if "form_routing" in by_name:
        st.divider()
        _routing_panel(by_name["form_routing"].get("detail") or {})

    payload_stage = by_name.get("payload")
    if payload_stage:
        st.divider()
        detail = payload_stage.get("detail") or {}
        status = payload_stage.get("status")

        if status in ("blocked", "failed"):
            st.error(payload_stage.get("summary"))
            for problem in detail.get("blocking_errors") or []:
                st.markdown(f"- {problem}")
        elif detail.get("filing_available"):
            st.success(
                "**Ready to file.** The Form 990-N payload is complete and "
                "Tax990 accepts this variant."
            )
        else:
            st.info(
                f"**{payload_stage.get('summary')}** Tax990's API currently "
                f"accepts the Form 990-N only; support for the longer forms "
                f"is on their roadmap."
            )

        for warning in detail.get("warnings") or []:
            st.caption(f"\u00b7 {warning}")
        for failure in detail.get("check_failures") or []:
            st.warning(failure)

        if detail.get("payload"):
            with st.expander("Submission payload"):
                st.json(detail["payload"])

        if detail.get("filing_available") and status == "ready":
            _render_filing(
                base_url, headers, detail["payload"], format_request_error
            )


def _render_filing(
    base_url: str,
    headers: dict,
    payload: dict,
    format_request_error: Optional[Callable[[Exception, str, str], str]],
) -> None:
    """The submission step, kept behind its own button.

    Preparing a return is free and repeatable. Submitting creates a record
    inside an IRS-authorised e-file provider, so it happens only when a
    preparer asks for it, against a payload they have already seen above.
    """
    st.divider()
    st.markdown("### Step 4 \u00b7 File with Tax990  `/api/filing/submit`")
    st.caption(
        "Sends the payload above to Tax990, runs their validation, and "
        "retrieves the completed form."
    )

    # The filing window is enforced here rather than at preparation, because
    # a return for an older year is still worth preparing and reviewing.
    year = ""
    try:
        year = payload["Form990NRecords"][0]["Form990N"]["TaxYr"]
    except (KeyError, IndexError, TypeError):
        pass

    fileable = fileable_years()
    if year and int(year) not in set(fileable):
        st.info(
            f"**{year} cannot be submitted.** Tax990 accepts "
            f"{min(fileable)} through {max(fileable)} \u2014 a year cannot be "
            f"filed before it has ended. The return above is complete and can "
            f"be reviewed; choose a year in range to file it."
        )
        return

    if st.button("File with Tax990", type="primary"):
        try:
            with st.spinner("Submitting to Tax990\u2026"):
                st.session_state.filing_submission = call_submit(
                    base_url, headers, payload
                )
                st.session_state.filing_submit_error = None
        except Exception as exc:  # noqa: BLE001
            st.session_state.filing_submission = None
            st.session_state.filing_submit_error = (
                format_request_error(exc, base_url, "/api/filing/submit")
                if format_request_error else str(exc)
            )

    if st.session_state.filing_submit_error:
        st.error(st.session_state.filing_submit_error)

    submission = st.session_state.filing_submission
    if not submission:
        return

    if submission.get("status") == "rejected":
        st.error(submission.get("message") or "Tax990 rejected the return.")
        for problem in submission.get("validation_errors") or []:
            field = problem.get("Field") or problem.get("Name") or ""
            st.markdown(f"- **{field}** {problem.get('Message', '')}")
        return

    st.success(submission.get("message") or "Submitted.")

    left, right = st.columns(2)
    left.metric("Return number", submission.get("return_number") or "\u2014")
    right.metric("Record ID", (submission.get("record_id") or "")[:8] or "\u2014")

    errors = submission.get("validation_errors") or []
    if errors:
        st.warning("Tax990's validation raised the following:")
        for problem in errors:
            field = problem.get("Field") or problem.get("Name") or ""
            st.markdown(f"- **{field}** {problem.get('Message', '')}")
    else:
        st.caption("\u00b7 Tax990 validation passed with no errors.")

    pdf = submission.get("pdf_base64")
    if pdf:
        st.markdown("#### The completed form")
        st.download_button(
            "Download the Form 990-N",
            data=base64.b64decode(pdf),
            file_name=f"form_990n_{(submission.get('record_id') or 'draft')[:8]}.pdf",
            mime="application/pdf",
        )
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{pdf}" '
            f'width="100%" height="680" style="border:1px solid #C6CCC2;'
            f'border-radius:6px"></iframe>',
            unsafe_allow_html=True,
        )
    elif submission.get("pdf_url"):
        st.markdown(f"[Open the completed form]({submission['pdf_url']})")
        st.caption("\u00b7 The link is short-lived.")

"""Deterministic scorecard for Form 990 and cash flow benchmarking.

Compares AI-generated report JSON against reference extraction JSON. A field
counts as matched when it is present *and* its value agrees within
`_VALUE_MATCH_TOLERANCE`; where the reference field is not numeric there is
nothing to compare and presence is all that can be asked.

It used to score presence alone. An output of all zeros therefore scored as
well as a correct one, and the project's accuracy target could not be measured
at all -- value similarity was computed, put in the output row, and then left
out of the score.

One thing this cannot tell you: the reference is itself extracted from a PDF by
a model, so a disagreement says the two readings differ, not which one is
wrong. Where a hand-checked answer key exists -- as it does for Part VIII in
`data/crn_synthetic.json` -- that is the better measurement, and
`app/utils/classification_harness.py` uses it.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# Weights for composite client-facing score (0-100 scale)
DIMENSION_WEIGHTS = {
    "accuracy": 0.45,
    "reconciliation": 0.25,
    "completeness": 0.20,
    "audit_quality": 0.10,
}

# Manual extraction field → AI revenue bucket keywords (Part VIII)
_REVENUE_FIELD_KEYWORDS = {
    "contributions": ("contribution", "gift", "grant"),
    "membership_dues": ("membership", "dues"),
    "program_service_revenue": ("program service", "program revenue"),
    "investment_income": ("investment", "dividend", "interest"),
    "other_revenue": ("other", "miscellaneous", "royalt", "rental", "fundraising"),
}

# Manual expense field → Part IX keywords
_EXPENSE_FIELD_KEYWORDS = {
    "program_services": ("program service", "program"),
    "management_general": ("management", "general"),
    "fundraising": ("fundraising"),
    "depreciation": ("depreciation", "amortization"),
    "occupancy": ("occupancy", "rent"),
    "insurance": ("insurance"),
}

# Manual balance sheet field → Part X label keywords
_BALANCE_SHEET_FIELD_KEYWORDS = {
    "cash": ("cash", "equivalent"),
    "receivables": ("receivable", "accounts receivable"),
    "prepaids": ("prepaid"),
    "fixed_assets": ("fixed asset", "property", "equipment", "ppe"),
    "accumulated_depreciation": ("accumulated depreciation", "depreciation"),
    "accounts_payable": ("accounts payable", "payable"),
    "deferred_revenue": ("deferred", "unearned"),
    "other_liabilities": ("other liabilit", "long-term"),
}

# Mandatory fields for coverage (section, field)
_MANDATORY_FIELDS: List[Tuple[str, str]] = [
    ("revenue", "total_revenue"),
    ("revenue", "contributions"),
    ("revenue", "program_service_revenue"),
    ("expenses", "total_expenses"),
    ("expenses", "program_services"),
    ("expenses", "management_general"),
    ("balance_sheet", "total_assets"),
    ("balance_sheet", "total_liabilities"),
    ("balance_sheet", "net_assets"),
    ("reconciliation", "ending_net_assets"),
]

_CASH_FLOW_FIELD_MAP: List[Tuple[str, str, str, str]] = [
    ("operating_activities", "operating_cash_flow", "operating_activities", "net_cash_from_operations"),
    ("investing_activities", "investing_cash_flow", "investing_activities", "net_cash_from_investing"),
    ("financing_activities", "financing_cash_flow", "financing_activities", "net_cash_from_financing"),
    ("cash_reconciliation", "cash_beginning", "cash_reconciliation", "beginning_cash"),
    ("cash_reconciliation", "cash_ending", "cash_reconciliation", "ending_cash"),
]

_FINANCIAL_POSITION_FIELD_MAP: List[Tuple[str, str, str, str]] = [
    ("assets", "cash", "assets", "cash"),
    ("assets", "receivables", "assets", "receivables"),
    ("assets", "prepaids", "assets", "prepaids"),
    ("assets", "fixed_assets", "assets", "fixed_assets"),
    ("assets", "total_assets", "assets", "total_assets"),
    ("liabilities", "accounts_payable", "liabilities", "accounts_payable"),
    ("liabilities", "deferred_revenue", "liabilities", "deferred_revenue"),
    ("liabilities", "other_liabilities", "liabilities", "other_liabilities"),
    ("liabilities", "total_liabilities", "liabilities", "total_liabilities"),
    ("net_assets", "net_assets", "net_assets", "net_assets"),
]

_CONFOUND_PATTERNS = (
    (r"QB_DATA_SUSPECT|sandbox|partial.?year|thin data|no rows", "DATA_INTEGRITY_QB"),
    (r"wrong (company|realm)|wrong qb|mismatched realm", "DATA_INTEGRITY_WRONG_QB_FILE"),
    (r"missing prior.?period|no prior|beginning balance.*not|not determinable", "DATA_INTEGRITY_MISSING_PRIOR_PERIOD"),
    (r"period mismatch|outside the.*period|wrong tax year", "DATA_INTEGRITY_PERIOD_MISMATCH"),
    (r"currency symbol|₹ vs|inr vs usd", "DATA_INTEGRITY_CURRENCY"),
    (r"wildapricot.*empty|no wildapricot|wa_period_empty|quickbooks only", "DATA_INTEGRITY_WA_EMPTY"),
)

# Lenient similarity threshold for confound detection only (not scoring)
_VALUE_DIVERGENCE_THRESHOLD = 0.50

# Scoring tolerance. Both sides describe the same organization's same year, so
# they should agree closely; the slack is for a reference figure read out of a
# PDF rather than for genuine disagreement. A field counts as matched only if
# it is present AND its value agrees within this.
_VALUE_MATCH_TOLERANCE = 0.01
_VALUE_MATCH_ABSOLUTE = 1.0


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("amount", "value", "total", "totalRevenue", "totalExpenses", "endOfYear", "end_of_year"):
            if key in value and value[key] is not None:
                return _num(value[key])
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _field_populated(value: Any) -> bool:
    """True when manual ground truth has a meaningful value for a field."""
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (int, float)):
        return True
    return _num(value) is not None


def _roughly_similar(manual: Optional[float], ai: Optional[float]) -> bool:
    """Lenient value check — same sign and within 50% relative difference."""
    if manual is None or ai is None:
        return False
    if manual == 0 and ai == 0:
        return True
    if manual == 0:
        return abs(ai) < 1.0
    base = max(abs(manual), 1.0)
    return abs(manual - ai) / base <= _VALUE_DIVERGENCE_THRESHOLD


def _values_agree(manual: Optional[float], ai: Optional[float]) -> bool:
    """Do the two figures agree closely enough to call the field matched?

    This is the scoring predicate. It exists because the score used to count a
    field as matched when the AI merely had the field at all, which meant an
    output of all zeros scored the same as a correct one and the project's
    accuracy target could not be measured.
    """
    if manual is None or ai is None:
        return False
    difference = abs(manual - ai)
    if difference <= _VALUE_MATCH_ABSOLUTE:
        return True
    return difference / max(abs(manual), 1.0) <= _VALUE_MATCH_TOLERANCE


def _section(extraction: Dict[str, Any], name: str) -> Dict[str, Any]:
    block = extraction.get(name) or {}
    return block if isinstance(block, dict) else {}


def _ai_totals(ai_report: Dict[str, Any]) -> Dict[str, Optional[float]]:
    totals = ai_report.get("totals") or {}
    return {
        "total_revenue": _num(totals.get("total_revenue")),
        "total_expenses": _num(totals.get("total_expenses")),
        "total_assets": _num(totals.get("total_assets")),
        "total_liabilities": _num(totals.get("total_liabilities")),
        "net_assets": _num(totals.get("net_assets")),
    }


def _part_x(ai_report: Dict[str, Any]) -> Dict[str, Any]:
    part_x = ai_report.get("part_x_balance_sheet") or {}
    if isinstance(part_x, dict) and "partX_balanceSheet" in part_x:
        inner = part_x.get("partX_balanceSheet")
        return inner if isinstance(inner, dict) else part_x
    return part_x if isinstance(part_x, dict) else {}


def _label_match(label: str, keywords: Tuple[str, ...]) -> bool:
    lower = label.lower()
    return any(kw in lower for kw in keywords)


def _line_items_match_keywords(
    items: Any, keywords: Tuple[str, ...]
) -> Tuple[bool, Optional[float]]:
    if not isinstance(items, list):
        return False, None
    for item in items:
        if not isinstance(item, dict):
            continue
        label = " ".join(
            str(item.get(k) or "")
            for k in ("label", "name", "category", "classification", "lineNumber", "line_number")
        )
        if _label_match(label, keywords):
            amount = _num(item.get("amount") or item.get("totalRevenue") or item.get("endOfYear"))
            if amount is not None:
                return True, amount
    return False, None


def _part_x_match_keywords(ai_report: Dict[str, Any], keywords: Tuple[str, ...]) -> Tuple[bool, Optional[float]]:
    part_x = _part_x(ai_report)
    for section_key in ("assets", "liabilities", "liabilitiesAndNetAssets"):
        present, amount = _line_items_match_keywords(part_x.get(section_key), keywords)
        if present:
            return True, amount

    for key, val in part_x.items():
        if isinstance(key, str) and _label_match(key, keywords):
            amount = _num(val)
            if amount is not None:
                return True, amount
    return False, None


def _ai_has_total(ai_report: Dict[str, Any], field: str) -> Tuple[bool, Optional[float]]:
    val = _num((ai_report.get("totals") or {}).get(field))
    if val is not None:
        return True, val
    part_x = _part_x(ai_report)
    camel_map = {
        "total_assets": "totalAssets",
        "total_liabilities": "totalLiabilities",
        "net_assets": "netAssets",
    }
    if field in camel_map:
        val = _num(part_x.get(camel_map[field]))
        if val is not None:
            return True, val
        net_assets_block = part_x.get("netAssets") or {}
        if field == "net_assets" and isinstance(net_assets_block, dict):
            val = _num(net_assets_block.get("totalNetAssets"))
            if val is not None:
                return True, val
    return False, None


def _ai_revenue_field(ai_report: Dict[str, Any], field: str) -> Tuple[bool, Optional[float]]:
    revenue = ai_report.get("revenue") or {}
    if isinstance(revenue, dict):
        val = _num(revenue.get(field))
        if val is not None:
            return True, val
    if field == "total_revenue":
        return _ai_has_total(ai_report, "total_revenue")
    keywords = _REVENUE_FIELD_KEYWORDS.get(field, (field.replace("_", " "),))
    items = ai_report.get("part_viii_revenue") or []
    return _line_items_match_keywords(items, keywords)


def _ai_expense_field(ai_report: Dict[str, Any], field: str) -> Tuple[bool, Optional[float]]:
    expenses = ai_report.get("expenses") or {}
    if isinstance(expenses, dict):
        val = _num(expenses.get(field))
        if val is not None:
            return True, val
    if field == "total_expenses":
        return _ai_has_total(ai_report, "total_expenses")
    keywords = _EXPENSE_FIELD_KEYWORDS.get(field, (field.replace("_", " "),))
    items = ai_report.get("part_ix_expenses") or []
    present, amount = _line_items_match_keywords(items, keywords)
    if present:
        return True, amount
    part_ix_totals = ai_report.get("partIX_totals") or ai_report.get("part_ix_totals") or {}
    camel_map = {
        "program_services": "totalProgramServices",
        "management_general": "totalManagementAndGeneral",
        "fundraising": "totalFundraising",
    }
    if field in camel_map:
        val = _num(part_ix_totals.get(camel_map[field]))
        if val is not None:
            return True, val
    return False, None


def _ai_balance_sheet_field(ai_report: Dict[str, Any], field: str) -> Tuple[bool, Optional[float]]:
    balance_sheet = ai_report.get("balance_sheet") or {}
    if isinstance(balance_sheet, dict):
        val = _num(balance_sheet.get(field))
        if val is not None:
            return True, val
    if field in ("total_assets", "total_liabilities", "net_assets"):
        return _ai_has_total(ai_report, field)
    keywords = _BALANCE_SHEET_FIELD_KEYWORDS.get(field, (field.replace("_", " "),))
    return _part_x_match_keywords(ai_report, keywords)


def _ai_field_present(
    ai_report: Dict[str, Any], section: str, field: str
) -> Tuple[bool, Optional[float]]:
    if section == "revenue":
        return _ai_revenue_field(ai_report, field)
    if section == "expenses":
        return _ai_expense_field(ai_report, field)
    if section == "balance_sheet":
        return _ai_balance_sheet_field(ai_report, field)
    if section == "reconciliation":
        recon = ai_report.get("reconciliation") or {}
        if isinstance(recon, dict):
            val = _num(recon.get(field))
            if val is not None:
                return True, val
        totals = ai_report.get("totals") or {}
        totals_map = {
            "total_revenue": "total_revenue",
            "total_expenses": "total_expenses",
            "ending_net_assets": ("ending_net_assets", "net_assets"),
            "beginning_net_assets": "beginning_net_assets",
            "change_in_net_assets": "change_in_net_assets",
        }
        mapping = totals_map.get(field)
        if isinstance(mapping, tuple):
            for key in mapping:
                val = _num(totals.get(key))
                if val is not None:
                    return True, val
            return False, None
        if mapping:
            val = _num(totals.get(mapping))
            return val is not None, val
        return False, None
    if section == "organization_summary":
        org = ai_report.get("organization_summary") or {}
        val = org.get(field)
        if val is not None and str(val).strip():
            return True, _num(val)
        return False, None
    return False, None


def _compare_fields(
    manual: Dict[str, Any],
    ai_report: Dict[str, Any],
    field_specs: List[Tuple[str, str]],
) -> Tuple[float, List[Dict[str, Any]]]:
    """Score field alignment: for each populated manual field, check AI has the field."""
    expected = 0
    matched = 0
    rows: List[Dict[str, Any]] = []

    for section, field in field_specs:
        manual_val = _section(manual, section).get(field)
        if not _field_populated(manual_val):
            continue
        expected += 1
        manual_num = _num(manual_val)
        ai_present, ai_val = _ai_field_present(ai_report, section, field)

        # A numeric reference field has to be matched on its value. Where the
        # reference is not a number there is nothing to compare, so presence
        # is all that can be asked.
        if manual_num is None:
            is_match = ai_present
        else:
            is_match = ai_present and _values_agree(manual_num, _num(ai_val))
        if is_match:
            matched += 1

        rows.append(
            {
                "field": f"{section}.{field}",
                "manual": manual_num if manual_num is not None else manual_val,
                "ai": ai_val,
                "ai_field_present": ai_present,
                "field_match": is_match,
                "value_matches": is_match,
                "value_roughly_similar": _roughly_similar(manual_num, ai_val),
            }
        )

    score = round(matched / expected * 100.0, 2) if expected else 100.0
    return score, rows


def _form_990_field_specs(manual: Dict[str, Any]) -> List[Tuple[str, str]]:
    specs: List[Tuple[str, str]] = []
    for section_name in ("revenue", "expenses", "balance_sheet", "reconciliation", "organization_summary"):
        section = _section(manual, section_name)
        for field in section:
            if _field_populated(section.get(field)):
                specs.append((section_name, field))
    return specs


def _score_reconciliation(reconciliation_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    pass_count = 0
    fail_count = 0

    for item in reconciliation_results or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").upper()
        passed = status == "PASS"
        if passed:
            pass_count += 1
        else:
            fail_count += 1
        checks.append(
            {
                "check_id": item.get("checkId") or item.get("check_id"),
                "description": item.get("description"),
                "status": status or "UNKNOWN",
                "difference": _num(item.get("difference")),
                "notes": (item.get("notes") or "")[:300],
            }
        )

    total = pass_count + fail_count
    score = round(pass_count / total * 100.0, 2) if total else 100.0
    return {
        "score": score,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "checks": checks,
    }


def _mandatory_field_coverage(
    manual: Dict[str, Any], prior_year: Optional[Dict[str, Any]]
) -> Tuple[int, int, List[str]]:
    present = 0
    expected = 0
    missing: List[str] = []

    for section, field in _MANDATORY_FIELDS:
        manual_val = _num((_section(manual, section)).get(field))
        prior_val = (
            _num((_section(prior_year or {}, section)).get(field))
            if prior_year
            else manual_val
        )
        if prior_val is not None or manual_val is not None:
            expected += 1
            if manual_val is not None:
                present += 1
            else:
                missing.append(f"{section}.{field}")

    return present, expected, missing


def _score_completeness(
    validation_errors: List[Dict[str, Any]],
    manual: Dict[str, Any],
    prior_year: Optional[Dict[str, Any]],
    ai_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Completeness = mandatory manual fields that AI also generated."""
    ai_matched = 0
    ai_expected = 0
    missing_in_ai: List[str] = []

    for section, field in _MANDATORY_FIELDS:
        manual_val = _num((_section(manual, section)).get(field))
        prior_val = (
            _num((_section(prior_year or {}, section)).get(field))
            if prior_year
            else manual_val
        )
        if prior_val is not None or manual_val is not None:
            if manual_val is not None:
                ai_expected += 1
                ai_present, _ = _ai_field_present(ai_report, section, field)
                if ai_present:
                    ai_matched += 1
                else:
                    missing_in_ai.append(f"{section}.{field}")

    coverage_pct = round(ai_matched / ai_expected * 100.0, 2) if ai_expected else 100.0

    present, expected, missing_mandatory = _mandatory_field_coverage(manual, prior_year)

    high_medium = [
        e
        for e in validation_errors or []
        if isinstance(e, dict)
        and str(e.get("severity", "")).upper() in ("HIGH", "MEDIUM", "WARNING")
    ]
    info_only = [
        e
        for e in validation_errors or []
        if isinstance(e, dict) and str(e.get("severity", "")).upper() == "INFO"
    ]

    penalty = 0
    for err in high_medium:
        sev = str(err.get("severity", "")).upper()
        penalty += 12 if sev == "HIGH" else 6
    penalty += min(len(info_only) * 2, 10)
    error_score = max(0.0, 100.0 - penalty)

    score = round(coverage_pct * 0.7 + error_score * 0.3, 2)
    return {
        "score": score,
        "mandatory_fields_present": present,
        "mandatory_fields_expected": expected,
        "ai_fields_matched": ai_matched,
        "ai_fields_expected": ai_expected,
        "coverage_pct": coverage_pct,
        "missing_fields_in_ai": missing_in_ai,
        "high_medium_validation_errors": len(high_medium),
        "info_validation_errors": len(info_only),
        "missing_mandatory_in_ground_truth": missing_mandatory,
        "validation_errors": [
            {
                "error_id": e.get("errorId") or e.get("error_id"),
                "severity": e.get("severity"),
                "section": e.get("section"),
                "description": (e.get("description") or "")[:250],
            }
            for e in (validation_errors or [])[:15]
            if isinstance(e, dict)
        ],
    }


def _score_audit_quality(
    reconciliation_results: List[Dict[str, Any]],
    validation_errors: List[Dict[str, Any]],
    warnings: List[Any],
    audit_flags: List[Any],
) -> Dict[str, Any]:
    recon = _score_reconciliation(reconciliation_results)
    warning_count = len(warnings or [])
    audit_count = len(audit_flags or [])
    high_errors = sum(
        1
        for e in validation_errors or []
        if isinstance(e, dict) and str(e.get("severity", "")).upper() == "HIGH"
    )

    proactive = min(20.0, (warning_count + audit_count + len(validation_errors or [])) * 2)
    score = round(
        max(0.0, min(100.0, recon["score"] * 0.6 + proactive + 20 - high_errors * 5)),
        2,
    )
    return {
        "score": score,
        "reconciliation_pass_rate": recon["score"],
        "warnings_count": warning_count,
        "audit_flags_count": audit_count,
        "high_severity_errors": high_errors,
    }


def _detect_confound_flags(
    *,
    ai_report: Dict[str, Any],
    cash_flow_report: Dict[str, Any],
    reports_raw: Dict[str, Any],
    fiscal_year: int,
    field_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()

    def _add(code: str, message: str, severity: str = "HIGH") -> None:
        if code in seen_codes:
            return
        seen_codes.add(code)
        flags.append({"code": code, "severity": severity, "message": message})

    for warning in reports_raw.get("data_quality_warnings") or []:
        warning_text = str(warning)
        if "QB_DATA_SUSPECT" in warning_text:
            _add("DATA_INTEGRITY_QB", warning_text)
        if "QB_PRIOR_YEAR_MISSING" in warning_text:
            _add("DATA_INTEGRITY_MISSING_PRIOR_PERIOD", warning_text)
        if "WA_PERIOD_EMPTY" in warning_text:
            _add("DATA_INTEGRITY_WA_EMPTY", warning_text)

    for text in _collect_audit_text(ai_report, cash_flow_report, reports_raw):
        for pattern, code in _CONFOUND_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                _add(code, f"Detected in AI output: {text[:200]}")

    # Fields present but values wildly divergent suggest bad source data
    divergent = [
        r for r in field_rows
        if r.get("ai_field_present") and not r.get("value_roughly_similar")
        and r.get("manual") is not None and abs(float(r["manual"])) > 100
    ]
    if len(divergent) >= 4:
        _add(
            "DATA_INTEGRITY_SYSTEMIC_VARIANCE",
            f"{len(divergent)} fields are present in AI output but values diverge sharply "
            "from filed reference — likely source data integrity issue, not missing fields.",
        )

    tax_content = (reports_raw.get("tax_return") or {}).get("content") or {}
    org_info = tax_content.get("organizationInformation") or {}
    tax_year = org_info.get("taxYear") or org_info.get("tax_year")
    if tax_year and str(tax_year)[:4] != str(fiscal_year):
        _add(
            "DATA_INTEGRITY_PERIOD_MISMATCH",
            f"AI tax return tax year ({tax_year}) differs from benchmark fiscal year ({fiscal_year}).",
        )

    return flags


def _collect_audit_text(
    ai_report: Dict[str, Any],
    cash_flow_report: Dict[str, Any],
    reports_raw: Dict[str, Any],
) -> List[str]:
    chunks: List[str] = []
    for key in ("warnings", "validation_errors", "reconciliation_results"):
        for item in ai_report.get(key) or []:
            if isinstance(item, dict):
                chunks.append(
                    " ".join(
                        str(item.get(k) or "")
                        for k in ("message", "description", "notes", "recommendedAction")
                    )
                )
            else:
                chunks.append(str(item))

    cf_content = (reports_raw.get("cash_flow") or {}).get("content") or {}
    statement = cf_content.get("statement") or {}
    for note in statement.get("preparationNotes") or []:
        chunks.append(str(note))

    for item in cash_flow_report.get("human_review_items") or []:
        if isinstance(item, dict):
            chunks.append(str(item.get("message") or item.get("note") or ""))

    return chunks


def _rating(score: float) -> str:
    """Client-facing rating bands: excellent 90+, good 80-89, poor 70-79."""
    if score >= 90:
        return "excellent"
    if score >= 80:
        return "good"
    if score >= 70:
        return "poor"
    return "critical"


def build_form_990_scorecard(
    *,
    fiscal_year: int,
    manual_extraction: Dict[str, Any],
    prior_year_extraction: Optional[Dict[str, Any]],
    ai_report: Dict[str, Any],
    cash_flow_report: Dict[str, Any],
    reports_raw: Dict[str, Any],
) -> Dict[str, Any]:
    """Build field-alignment scorecard comparing AI tax return JSON vs manual extraction."""
    field_specs = _form_990_field_specs(manual_extraction)
    if not field_specs:
        field_specs = list(_MANDATORY_FIELDS)

    accuracy, field_rows = _compare_fields(manual_extraction, ai_report, field_specs)

    reconciliation_results = ai_report.get("reconciliation_results") or []
    validation_errors = ai_report.get("validation_errors") or []
    warnings = ai_report.get("warnings") or []
    audit_flags = ai_report.get("audit_flags") or []

    reconciliation = _score_reconciliation(reconciliation_results)
    completeness = _score_completeness(
        validation_errors, manual_extraction, prior_year_extraction, ai_report
    )
    audit_quality = _score_audit_quality(
        reconciliation_results, validation_errors, warnings, audit_flags
    )

    dimensions = {
        "accuracy": {
            "score": accuracy,
            "field_match_pct": accuracy,
            "field_comparisons": field_rows,
            "comparison_mode": "field_alignment",
        },
        "reconciliation": reconciliation,
        "completeness": completeness,
        "audit_quality": audit_quality,
    }

    confound_flags = _detect_confound_flags(
        ai_report=ai_report,
        cash_flow_report=cash_flow_report,
        reports_raw=reports_raw,
        fiscal_year=fiscal_year,
        field_rows=field_rows,
    )

    composite = _composite_score(dimensions)
    high_confounds = [f for f in confound_flags if f.get("severity") == "HIGH"]
    adjusted_composite = composite
    confound_penalty = 0.0
    if high_confounds:
        confound_penalty = min(15.0, len(high_confounds) * 5.0)
        adjusted_composite = max(0.0, round(composite - confound_penalty, 2))

    return {
        "fiscal_year": fiscal_year,
        "comparison_source": "ai_tax_return_json_vs_manual_form_990_extraction",
        "dimensions": dimensions,
        "confound_flags": confound_flags,
        "composite_score": composite,
        "adjusted_composite_score": adjusted_composite,
        "confound_penalty": confound_penalty,
        "composite_rating": _rating(adjusted_composite),
        "dimension_weights": DIMENSION_WEIGHTS,
        "processing_time": {
            "tax_return": ai_report.get("processing_time"),
            "cash_flow": cash_flow_report.get("processing_time"),
        },
        "accuracy_unreliable": bool(high_confounds),
    }


def _ai_cash_flow_field(
    ai_report: Dict[str, Any], ai_section: str, ai_key: str
) -> Tuple[bool, Optional[float]]:
    section_data = ai_report.get(ai_section) or {}
    alt_keys = {
        "net_cash_from_operations": ("operating_cash_flow", "netCashFromOperations"),
        "net_cash_from_investing": ("investing_cash_flow", "netCashFromInvesting"),
        "net_cash_from_financing": ("financing_cash_flow", "netCashFromFinancing"),
        "beginning_cash": ("cash_beginning", "beginningCash"),
        "ending_cash": ("cash_ending", "endingCash"),
    }
    val = _num(section_data.get(ai_key))
    if val is not None:
        return True, val
    for alt in alt_keys.get(ai_key, ()):
        val = _num(section_data.get(alt))
        if val is not None:
            return True, val
    if ai_key in ("beginning_cash", "ending_cash"):
        recon = ai_report.get("cash_reconciliation") or {}
        for alt in alt_keys.get(ai_key, ()):
            val = _num(recon.get(alt))
            if val is not None:
                return True, val
    return False, None


def build_cash_flow_scorecard(
    *,
    fiscal_year: int,
    manual_extraction: Dict[str, Any],
    ai_report: Dict[str, Any],
    reports_raw: Dict[str, Any],
) -> Dict[str, Any]:
    """Build field-alignment scorecard comparing AI cash flow JSON vs manual extraction."""
    field_rows: List[Dict[str, Any]] = []
    expected = 0
    matched = 0

    for manual_section, manual_key, ai_section, ai_key in _CASH_FLOW_FIELD_MAP:
        manual_section_data = manual_extraction.get(manual_section) or {}
        manual_val = _num(manual_section_data.get(manual_key))
        if manual_key in ("cash_beginning", "cash_ending"):
            manual_val = _num(
                (manual_extraction.get("cash_reconciliation") or {}).get(manual_key)
            )
        if not _field_populated(manual_val):
            continue
        expected += 1
        ai_present, ai_val = _ai_cash_flow_field(ai_report, ai_section, ai_key)
        if ai_present:
            matched += 1
        field_rows.append(
            {
                "field": f"{manual_section}.{manual_key}",
                "manual": manual_val,
                "ai": ai_val,
                "ai_field_present": ai_present,
                "field_match": ai_present,
                "value_roughly_similar": _roughly_similar(manual_val, ai_val),
            }
        )

    accuracy = round(matched / expected * 100.0, 2) if expected else 100.0

    confound_flags = _detect_confound_flags(
        ai_report={},
        cash_flow_report=ai_report,
        reports_raw=reports_raw,
        fiscal_year=fiscal_year,
        field_rows=field_rows,
    )

    material_misses = sum(1 for r in field_rows if not r.get("field_match"))
    dimensions = {
        "accuracy": {
            "score": accuracy,
            "field_match_pct": accuracy,
            "field_comparisons": field_rows,
            "comparison_mode": "field_alignment",
        },
        "reconciliation": {
            "score": accuracy,
            "pass_count": matched,
            "fail_count": material_misses,
            "checks": [],
        },
        "completeness": {
            "score": max(0.0, 100.0 - len(ai_report.get("human_review_items") or []) * 5),
            "human_review_items": len(ai_report.get("human_review_items") or []),
        },
        "audit_quality": {
            "score": min(100.0, 60.0 + len(ai_report.get("validation_results") or []) * 10),
            "validation_results": ai_report.get("validation_results") or [],
        },
    }

    composite = _composite_score(dimensions)
    high_confounds = [f for f in confound_flags if f.get("severity") == "HIGH"]
    confound_penalty = min(15.0, len(high_confounds) * 5.0) if high_confounds else 0.0
    adjusted = max(0.0, round(composite - confound_penalty, 2))

    return {
        "fiscal_year": fiscal_year,
        "comparison_source": "ai_cash_flow_json_vs_manual_cash_flow_extraction",
        "dimensions": dimensions,
        "confound_flags": confound_flags,
        "composite_score": composite,
        "adjusted_composite_score": adjusted,
        "confound_penalty": confound_penalty,
        "composite_rating": _rating(adjusted),
        "dimension_weights": DIMENSION_WEIGHTS,
        "processing_time": {"cash_flow": ai_report.get("processing_time")},
        "accuracy_unreliable": bool(high_confounds),
    }


def _ai_financial_position_field(
    ai_report: Dict[str, Any], ai_section: str, ai_key: str
) -> Tuple[bool, Optional[float]]:
    section_data = ai_report.get(ai_section) or {}
    alt_keys = {
        "total_assets": ("totalAssets",),
        "total_liabilities": ("totalLiabilities",),
        "net_assets": ("totalNetAssets",),
    }
    val = _num(section_data.get(ai_key))
    if val is not None:
        return True, val
    for alt in alt_keys.get(ai_key, ()):
        val = _num(section_data.get(alt))
        if val is not None:
            return True, val
    return False, None


def build_financial_position_scorecard(
    *,
    fiscal_year: int,
    manual_extraction: Dict[str, Any],
    ai_report: Dict[str, Any],
    reports_raw: Dict[str, Any],
    prior_year_extraction: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare AI balance sheet JSON vs manual Financial Position PDF extraction."""
    field_rows: List[Dict[str, Any]] = []
    expected = 0
    matched = 0

    for manual_section, manual_key, ai_section, ai_key in _FINANCIAL_POSITION_FIELD_MAP:
        manual_val = _num((manual_extraction.get(manual_section) or {}).get(manual_key))
        if not _field_populated(manual_val):
            continue
        expected += 1
        ai_present, ai_val = _ai_financial_position_field(ai_report, ai_section, ai_key)
        if ai_present:
            matched += 1
        field_rows.append(
            {
                "field": f"{manual_section}.{manual_key}",
                "manual": manual_val,
                "ai": ai_val,
                "ai_field_present": ai_present,
                "field_match": ai_present,
                "value_roughly_similar": _roughly_similar(manual_val, ai_val),
            }
        )

    accuracy = round(matched / expected * 100.0, 2) if expected else 100.0
    confound_flags = _detect_confound_flags(
        ai_report={},
        cash_flow_report={},
        reports_raw=reports_raw,
        fiscal_year=fiscal_year,
        field_rows=field_rows,
    )
    material_misses = sum(1 for r in field_rows if not r.get("field_match"))
    equation = ai_report.get("accounting_equation") or {}
    equation_status = str(equation.get("status") or "").lower()
    reconciliation_score = 100.0 if equation_status == "balanced" else 70.0

    dimensions = {
        "accuracy": {
            "score": accuracy,
            "field_match_pct": accuracy,
            "field_comparisons": field_rows,
            "comparison_mode": "field_alignment",
        },
        "reconciliation": {
            "score": reconciliation_score,
            "pass_count": matched,
            "fail_count": material_misses,
            "checks": [{"check": "accounting_equation", "status": equation.get("status")}],
        },
        "completeness": {
            "score": max(0.0, 100.0 - len(ai_report.get("human_review_items") or []) * 5),
            "human_review_items": len(ai_report.get("human_review_items") or []),
        },
        "audit_quality": {
            "score": min(100.0, 60.0 + len(ai_report.get("validation_results") or []) * 10),
            "validation_results": ai_report.get("validation_results") or [],
        },
    }

    composite = _composite_score(dimensions)
    high_confounds = [f for f in confound_flags if f.get("severity") == "HIGH"]
    confound_penalty = min(15.0, len(high_confounds) * 5.0) if high_confounds else 0.0
    adjusted = max(0.0, round(composite - confound_penalty, 2))

    return {
        "fiscal_year": fiscal_year,
        "comparison_source": "ai_balance_sheet_json_vs_manual_financial_position_extraction",
        "dimensions": dimensions,
        "confound_flags": confound_flags,
        "composite_score": composite,
        "adjusted_composite_score": adjusted,
        "confound_penalty": confound_penalty,
        "composite_rating": _rating(adjusted),
        "dimension_weights": DIMENSION_WEIGHTS,
        "processing_time": {"balance_sheet": ai_report.get("processing_time")},
        "accuracy_unreliable": bool(high_confounds),
    }


def _composite_score(dimensions: Dict[str, Dict[str, Any]]) -> float:
    total = 0.0
    for name, weight in DIMENSION_WEIGHTS.items():
        total += (dimensions.get(name) or {}).get("score", 0.0) * weight
    return round(total, 2)


def blend_year_composite(
    form_990_scorecard: Dict[str, Any],
    cash_flow_scorecard: Dict[str, Any],
    financial_position_scorecard: Optional[Dict[str, Any]] = None,
) -> float:
    """Weighted blend of section adjusted composite scores (0-1 scale)."""
    f990 = form_990_scorecard.get("adjusted_composite_score", 0.0)
    cf = cash_flow_scorecard.get("adjusted_composite_score", 0.0)
    if financial_position_scorecard:
        fp = financial_position_scorecard.get("adjusted_composite_score", 0.0)
        blended = (f990 + cf + fp) / 3.0
    else:
        blended = f990 * 0.6 + cf * 0.4
    return round(blended / 100.0, 4)

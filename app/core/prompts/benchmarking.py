import json

form_990_extraction_prompt = """
You are an expert IRS Form 990 financial analyst.

Your task is to extract structured financial and organizational information from a manually filed IRS Form 990.

The document has already been OCR processed. The text provided corresponds only to the following sections of Form 990:

* Page 1: Part I Summary
* Page 9: Part VIII Statement of Revenue
* Page 10: Part IX Statement of Functional Expenses
* Page 11: Part X Balance Sheet
* Page 12: Part XI Reconciliation of Net Assets

These sections are the authoritative source for extraction.

# Extraction Rules

1. Extract values exactly as reported.
2. Do not estimate, infer, calculate, or fabricate values unless explicitly instructed.
3. If a value is not present, return null.
4. Remove currency symbols, commas, and formatting.
5. Return all monetary values as numbers.
6. Preserve organization names and mission statements exactly as written.
7. Use Part VIII as the source for revenue values.
8. Use Part IX as the source for expense values.
9. Use Part X as the source for balance sheet values.
10. Use Part XI as the source for reconciliation values.
11. Use Part I Summary only for organization metadata and validation.
12. If multiple sections contain the same value, prioritize:

    * Part X over Part I for balance sheet values
    * Part IX over Part I for expenses
    * Part VIII over Part I for revenue
13. Do not include explanations.
14. Output valid JSON only.

# Field Mapping

## organization_summary

organization_name
→ Page 1 header

ein
→ Page 1 Employer Identification Number

tax_year
→ Page 1 tax year

gross_receipts
→ Page 1 Gross Receipts

mission
→ Page 1 Briefly describe the organization's mission
If unavailable on Page 1, use Part III Program Service Accomplishments mission statement.

## revenue

contributions
→ Part VIII Line 1h Contributions and Grants

membership_dues
→ Part VIII Line 1b Membership Dues

program_service_revenue
→ Part VIII Line 2g Program Service Revenue Total

investment_income
→ Part VIII Line 3 Investment Income

other_revenue
→ Sum of:

* Part VIII Line 5 Royalties
* Part VIII Line 6d Rental Income
* Part VIII Line 7d Net Gain/Loss
* Part VIII Line 8c Fundraising Income
* Part VIII Line 9c Gaming Income
* Part VIII Line 10c Inventory Sales Income
* Part VIII Line 11e Miscellaneous Revenue

total_revenue
→ Part VIII Line 12 Total Revenue

## expenses

program_services
→ Part IX Column B Total Program Service Expenses
OR Part IX Line 25 Column B

management_general
→ Part IX Line 25 Column C

fundraising
→ Part IX Line 25 Column D

depreciation
→ Part IX Line 22

occupancy
→ Part IX Line 16

insurance
→ Part IX Line 23

other_expenses
→ Total Expenses
minus
(
Program Services +
Management General +
Fundraising
)

If calculation cannot be performed, return null.

total_expenses
→ Part IX Line 25 Column A

## balance_sheet

cash
→ Part X
Line 1 + Line 2

receivables
→ Part X
Line 3 + Line 4 + Line 5 + Line 6 + Line 7

prepaids
→ Part X Line 9

fixed_assets
→ Part X Line 10c

accumulated_depreciation
→ Extract from Line 10b if disclosed.
If not disclosed, return null.

total_assets
→ Part X Line 16

accounts_payable
→ Part X Line 17

deferred_revenue
→ Part X Line 19

other_liabilities
→ Sum of Lines 20–25 excluding deferred revenue

total_liabilities
→ Part X Line 26

net_assets
→ Part X Line 32
or
Part X Line 27 + Line 28 if applicable

## reconciliation

total_revenue
→ Part XI Line 1

total_expenses
→ Part XI Line 2

change_in_net_assets
→ Part XI Line 3

beginning_net_assets
→ Part XI Line 4

ending_net_assets
→ Part XI Line 10

# Validation Rules

Perform these checks:

1. Revenue Validation
   Part VIII Line 12 should equal reconciliation.total_revenue

2. Expense Validation
   Part IX Line 25 should equal reconciliation.total_expenses

3. Net Asset Validation
   Part X Net Assets should equal reconciliation.ending_net_assets

4. Accounting Equation Validation
   total_assets ≈ total_liabilities + net_assets

If validation fails, still return extracted values.

# Required Output Schema

{
"organization_summary": {
"organization_name": null,
"ein": null,
"tax_year": null,
"gross_receipts": null,
"mission": null
},
"revenue": {
"contributions": null,
"membership_dues": null,
"program_service_revenue": null,
"investment_income": null,
"other_revenue": null,
"total_revenue": null
},
"expenses": {
"program_services": null,
"management_general": null,
"fundraising": null,
"depreciation": null,
"occupancy": null,
"insurance": null,
"other_expenses": null,
"total_expenses": null
},
"balance_sheet": {
"cash": null,
"receivables": null,
"prepaids": null,
"fixed_assets": null,
"accumulated_depreciation": null,
"total_assets": null,
"accounts_payable": null,
"deferred_revenue": null,
"other_liabilities": null,
"total_liabilities": null,
"net_assets": null
},
"reconciliation": {
"total_revenue": null,
"total_expenses": null,
"change_in_net_assets": null,
"beginning_net_assets": null,
"ending_net_assets": null
}
}

Return JSON only.

"""

cash_flow_report_prompt = """

You are an expert nonprofit accountant and financial statement analyst.

Your task is to extract structured cash flow information from a Statement of Cash Flows document.

The document may come from:

* Audited financial statements
* QuickBooks exports
* Xero reports
* Sage reports
* Nonprofit financial reports
* CPA-prepared statements

The format may vary, but all extracted values must be based only on information explicitly present in the document.

# Extraction Rules

1. Extract values exactly as shown.
2. Do not estimate or invent values.
3. Return monetary values as numbers.
4. Remove commas, currency symbols, and formatting.
5. Preserve negative values.
6. If a value is not available, return null.
7. If a subtotal is explicitly provided, use the reported subtotal instead of recalculating.
8. Do not perform accounting adjustments.
9. Output valid JSON only.

# Section Identification

Locate the following sections if present:

1. Operating Activities
2. Investing Activities
3. Financing Activities
4. Cash Reconciliation

Section names may vary.

Examples:

Operating Activities:

* Cash Flows From Operations
* Operating Cash Flow
* Net Cash Provided by Operating Activities

Investing Activities:

* Cash Flows From Investing
* Investing Cash Flow

Financing Activities:

* Cash Flows From Financing
* Financing Cash Flow

Cash Reconciliation:

* Net Change in Cash
* Cash at Beginning of Period
* Cash at End of Period

# Extraction Instructions

## report_metadata

Extract:

statement_name
reporting_period
reporting_basis
organization_name

Examples:

"Statement of Cash Flows"
"January 1, 2024 - December 31, 2024"
"Accrual Basis"
"Kansas City Woodworkers Guild Inc"

## operating_activities

Extract:

net_income_or_change_in_net_assets

adjustments

List every adjustment line item individually.

Examples:

Depreciation
Amortization
Accounts Receivable Changes
Inventory Changes
Prepaid Expenses Changes
Accounts Payable Changes
Deferred Revenue Changes
Unearned Revenue Changes

For each adjustment capture:

{
"name": "",
"amount": 0
}

operating_cash_flow

Use:

* Net Cash Provided by Operating Activities
* Net Cash Used in Operating Activities

whichever exists.

## investing_activities

Capture every investing activity line item.

Example:

{
"name": "Purchase of Equipment",
"amount": -10000
}

Extract:

investing_cash_flow

Use the reported subtotal.

## financing_activities

Capture every financing activity line item.

Examples:

Loan Proceeds
Debt Repayment
Capital Contributions
Opening Balance Equity Contributions

Extract:

financing_cash_flow

Use the reported subtotal.

## cash_reconciliation

Extract:

net_cash_change

cash_beginning

cash_ending

# Validation Rules

Perform the following validation:

Validation 1

operating_cash_flow
+
investing_cash_flow
+
financing_cash_flow

should equal

net_cash_change

Validation 2

cash_beginning
+
net_cash_change

should equal

cash_ending

If validation cannot be performed, return validation_status = "insufficient_data"

# Required Output Schema

{
"report_metadata": {
"organization_name": null,
"statement_name": null,
"reporting_period": null,
"reporting_basis": null
},

"operating_activities": {
"net_income_or_change_in_net_assets": null,

```
"adjustments": [
  {
    "name": null,
    "amount": null
  }
],

"operating_cash_flow": null
```

},

"investing_activities": {
"line_items": [
{
"name": null,
"amount": null
}
],

```
"investing_cash_flow": null
```

},

"financing_activities": {
"line_items": [
{
"name": null,
"amount": null
}
],

```
"financing_cash_flow": null
```

},

"cash_reconciliation": {
"net_cash_change": null,
"cash_beginning": null,
"cash_ending": null
},

"validation_results": {
"cash_flow_reconciles": null,
"cash_balance_reconciles": null
}
}

# Source Traceability

For every extracted field include a source reference.

Example:

{
"field": "operating_cash_flow",
"source_text": "Net cash provided by operating activities",
"source_page": 1
}

Include source references whenever possible.

Return JSON only.

"""

benchmark_prompt = """
You are a CPA benchmarking AI-generated financial reports against manually filed reference documents.

Compare the AI-generated report JSON with the manual report extracted JSON (from filed PDFs).
Validate a confidence score by checking FIELDS only — do NOT compare dollar amounts strictly.

# What to compare

For each document type, verify the AI report generated the correct fields:

* tax_return (Form 990) — revenue, expenses, balance sheet (Part X), reconciliation
* cash_flow — operating, investing, financing activities and cash reconciliation
* balance_sheet — assets, liabilities, net assets (via Part X in tax return)

# Field-only rules

1. Manual extracted JSON is ground truth for which fields should exist.
2. Score whether each manual field has a corresponding field in the AI JSON.
3. Do NOT penalize for numeric differences — only missing or wrong fields.
4. Treat fields as matching if labels/categories are at least similar (not exact).
5. Do not penalize missing beginning balances, missing source docs, or disclosed assumptions.

# Confidence score bands (0-100)

* 90–95 = excellent — nearly all expected fields present and aligned
* 80–90 = good — most fields present with minor gaps
* 70–80 = poor — several expected fields missing or misaligned
* below 70 = critical — major structural gaps

# Penalize for

* Missing mandatory fields that exist in manual extraction
* Wrong field categories or classifications
* Hallucinated fields with no manual counterpart
* Reconciliation failures in AI output

Return valid JSON only.
"""

FORM_990_OUTPUT_SCHEMA: dict = {
    "organization_summary": {
        "organization_name": None,
        "ein": None,
        "tax_year": None,
        "gross_receipts": None,
        "mission": None,
    },
    "revenue": {
        "contributions": None,
        "membership_dues": None,
        "program_service_revenue": None,
        "investment_income": None,
        "other_revenue": None,
        "total_revenue": None,
    },
    "expenses": {
        "program_services": None,
        "management_general": None,
        "fundraising": None,
        "depreciation": None,
        "occupancy": None,
        "insurance": None,
        "other_expenses": None,
        "total_expenses": None,
    },
    "balance_sheet": {
        "cash": None,
        "receivables": None,
        "prepaids": None,
        "fixed_assets": None,
        "accumulated_depreciation": None,
        "total_assets": None,
        "accounts_payable": None,
        "deferred_revenue": None,
        "other_liabilities": None,
        "total_liabilities": None,
        "net_assets": None,
    },
    "reconciliation": {
        "total_revenue": None,
        "total_expenses": None,
        "change_in_net_assets": None,
        "beginning_net_assets": None,
        "ending_net_assets": None,
    },
}

CASH_FLOW_OUTPUT_SCHEMA: dict = {
    "report_metadata": {
        "organization_name": None,
        "statement_name": None,
        "reporting_period": None,
        "reporting_basis": None,
    },
    "operating_activities": {
        "net_income_or_change_in_net_assets": None,
        "adjustments": [{"name": None, "amount": None}],
        "operating_cash_flow": None,
    },
    "investing_activities": {
        "line_items": [{"name": None, "amount": None}],
        "investing_cash_flow": None,
    },
    "financing_activities": {
        "line_items": [{"name": None, "amount": None}],
        "financing_cash_flow": None,
    },
    "cash_reconciliation": {
        "net_cash_change": None,
        "cash_beginning": None,
        "cash_ending": None,
    },
    "validation_results": {
        "cash_flow_reconciles": None,
        "cash_balance_reconciles": None,
    },
}


financial_position_extraction_prompt = """
You are an expert nonprofit accountant and financial statement analyst.

Your task is to extract structured balance sheet information from a Statement of Financial Position
(also called a Balance Sheet).

The document may come from audited financial statements, CPA-prepared reports, or accounting exports.

# Extraction Rules

1. Extract values exactly as shown.
2. Do not estimate or invent values.
3. Return monetary values as numbers.
4. Remove commas, currency symbols, and formatting.
5. Preserve negative values.
6. If a value is not available, return null.
7. Output valid JSON only.

# Field Mapping

## report_metadata
organization_name
statement_name (e.g. "Statement of Financial Position")
as_of_date
reporting_basis

## assets
cash → sum of cash and cash equivalents if a single line is not shown
receivables → accounts receivable and similar current receivables
prepaids → prepaid expenses
fixed_assets → property and equipment (net or gross as reported)
total_assets → total assets line

## liabilities
accounts_payable
deferred_revenue → unearned/deferred revenue
other_liabilities → other current and long-term liabilities not captured above
total_liabilities → total liabilities line

## net_assets
net_assets → total net assets / equity / net assets without donor restrictions total

Return valid JSON only matching the required schema.
"""

FINANCIAL_POSITION_OUTPUT_SCHEMA: dict = {
    "report_metadata": {
        "organization_name": None,
        "statement_name": None,
        "as_of_date": None,
        "reporting_basis": None,
    },
    "assets": {
        "cash": None,
        "receivables": None,
        "prepaids": None,
        "fixed_assets": None,
        "total_assets": None,
    },
    "liabilities": {
        "accounts_payable": None,
        "deferred_revenue": None,
        "other_liabilities": None,
        "total_liabilities": None,
    },
    "net_assets": {
        "net_assets": None,
    },
}


def get_extraction_prompt(doc_type: str) -> str:
    """Return the /extract custom_prompt for a benchmark document type."""
    if doc_type == "form_990":
        return form_990_extraction_prompt
    if doc_type == "cash_flow":
        return cash_flow_report_prompt
    if doc_type == "financial_position":
        return financial_position_extraction_prompt
    raise ValueError(f"Unsupported benchmark doc_type: {doc_type}")


def get_extraction_output_schema(doc_type: str) -> dict:
    """Return custom_output_format schema for /extract LLM structuring."""
    if doc_type == "form_990":
        return FORM_990_OUTPUT_SCHEMA
    if doc_type == "cash_flow":
        return CASH_FLOW_OUTPUT_SCHEMA
    if doc_type == "financial_position":
        return FINANCIAL_POSITION_OUTPUT_SCHEMA
    raise ValueError(f"Unsupported benchmark doc_type: {doc_type}")


# ---------------------------------------------------------------------------
# LLM benchmark evaluation (split prompts — concise output)
# ---------------------------------------------------------------------------

_BENCHMARK_RULES = (
    "A deterministic FIELD-ALIGNMENT scorecard has already been computed by comparing "
    "ai_tax_return_report / ai_cash_flow_report / ai_balance_sheet_report JSON against "
    "manual_form_990_extraction / manual_cash_flow_extraction / "
    "manual_financial_position_extraction JSON (extracted from filed reference PDFs). "
    "Scoring validates FIELD PRESENCE and structural alignment — NOT strict numeric equality. "
    "Do NOT recalculate scores or dollar variances. "
    "Explain the scorecard for a CPA client: separate confound_flags (bad source data) "
    "from genuine missing-field errors. "
    "Rating bands: excellent 90+, good 80-89, poor 70-79, critical below 70."
)

benchmark_form_990_instructions = """
You are a CPA producing a client-facing Form 990 benchmark narrative for fiscal year {fiscal_year}.

""" + _BENCHMARK_RULES + """

INPUT includes:
- deterministic_scorecard (field-alignment scores for tax return + balance sheet fields)
- prior_year_form_990_extraction (prior filed ground truth)
- manual_form_990_extraction (current-year filed ground truth from reference PDF)
- ai_tax_return_report (AI-generated tax return JSON including Part X balance sheet)

Your job is NARRATIVE ONLY. Use pre-computed field-alignment scores. Highlight:
1. Which fields are present in manual extraction but missing in AI output
2. Which issues are confound_flags (bad QB/sandbox data) vs real missing-field errors
3. reconciliationResults PASS/FAIL implications
4. Do NOT emphasize dollar differences — focus on field coverage

Return JSON only:
- score: use deterministic_scorecard.adjusted_composite_score (0-100)
- rating: from scorecard composite_rating (excellent|good|poor|critical)
- summary: max 2 sentences
- key_differences: up to 5 from scorecard.dimensions.accuracy.field_comparisons
- issues: up to 5 — tag each as "confound" or "ai_error"
- confound_flags: echo from scorecard
- dimension_scores: {{accuracy, reconciliation, completeness, audit_quality}}
"""

benchmark_cash_flow_instructions = """
You are a CPA producing a client-facing cash flow benchmark narrative for fiscal year {fiscal_year}.

""" + _BENCHMARK_RULES + """

INPUT includes deterministic_scorecard, manual_cash_flow_extraction (from reference PDF),
and ai_cash_flow_report (AI-generated JSON).

Compare FIELD PRESENCE only — operating/investing/financing sections and cash reconciliation.
Do NOT recalculate scores or emphasize dollar variances.

Return JSON only:
- score: deterministic_scorecard.adjusted_composite_score
- rating: composite_rating (excellent|good|poor|critical)
- summary: one sentence
- key_differences: up to 5 from field_comparisons (missing or matched fields)
- issues: up to 5 (tag confound vs ai_error)
- confound_flags: echo from scorecard
- dimension_scores: {{accuracy, reconciliation, completeness, audit_quality}}
"""

benchmark_financial_position_instructions = """
You are a CPA producing a client-facing Statement of Financial Position benchmark narrative
for fiscal year {fiscal_year}.

""" + _BENCHMARK_RULES + """

INPUT includes deterministic_scorecard, manual_financial_position_extraction (from S3 PDF),
prior_year_financial_position_extraction (filed prior-year reference PDF when available),
prior_year_quickbooks_balance_sheet (QuickBooks closing balances from /api/reports),
and ai_balance_sheet_report (AI-generated balance sheet JSON from /api/reports).

Use prior-year sources to explain beginning-balance and roll-forward confounds — do not treat
missing prior-year data as an AI field omission when confound_flags already flag it.

Compare FIELD PRESENCE only — assets, liabilities, net assets line items and totals.
Do NOT recalculate scores or emphasize dollar variances.

Return JSON only:
- score: deterministic_scorecard.adjusted_composite_score
- rating: composite_rating (excellent|good|poor|critical)
- summary: one sentence
- key_differences: up to 5 from field_comparisons (missing or matched fields)
- issues: up to 5 (tag confound vs ai_error)
- confound_flags: echo from scorecard
- dimension_scores: {{accuracy, reconciliation, completeness, audit_quality}}
"""

benchmark_synthesis_instructions = """
Combine Form 990, Cash Flow, and Statement of Financial Position field-alignment scorecards
into a client-facing confidence summary.

All three compare AI-generated report JSON vs manual extracted JSON from S3 reference PDFs.
Field presence only — not strict numeric matching.

Use pre-computed dimension scores and confound_flags. Do NOT recalculate.
When financial_position_scorecard is present:
  overall_score = round average of form_990_score, cash_flow_score, financial_position_score)
Otherwise:
  overall_score = round(form_990_score * 0.6 + cash_flow_score * 0.4)
Use adjusted_composite_score values from each scorecard.

Rating bands: excellent 90+, good 80-89, poor 70-79, critical below 70.

Return JSON only:
- overall_score: 0-100 (confidence score)
- rating: excellent | good | poor | critical
- form_990_score, cash_flow_score, financial_position_score (null if not benchmarked)
- summary: max 3 sentences — state if low score is missing fields vs data confounds
- top_issues: up to 5 (dedupe; prefix [CONFOUND] or [AI])
- scorecard: {{
    form_990_dimensions: {{accuracy, reconciliation, completeness, audit_quality}},
    cash_flow_dimensions: {{...}},
    financial_position_dimensions: {{...}} or {{}},
    confound_flags: [...],
    data_integrity_warning: true/false,
    comparison_mode: "field_alignment"
  }}
"""

BENCHMARK_SECTION_OUTPUT_SCHEMA: dict = {
    "score": 0,
    "rating": "good",
    "summary": "",
    "key_differences": [
        {
            "field": "",
            "manual": 0,
            "ai": 0,
            "ai_field_present": False,
            "field_match": False,
        },
    ],
    "issues": [],
    "confound_flags": [],
    "dimension_scores": {
        "accuracy": 0,
        "reconciliation": 0,
        "completeness": 0,
        "audit_quality": 0,
    },
}

BENCHMARK_FORM_990_OUTPUT_SCHEMA = dict(BENCHMARK_SECTION_OUTPUT_SCHEMA)
BENCHMARK_CASH_FLOW_OUTPUT_SCHEMA = dict(BENCHMARK_SECTION_OUTPUT_SCHEMA)
BENCHMARK_FINANCIAL_POSITION_OUTPUT_SCHEMA = dict(BENCHMARK_SECTION_OUTPUT_SCHEMA)

BENCHMARK_FINAL_OUTPUT_SCHEMA: dict = {
    "overall_score": 0,
    "rating": "good",
    "form_990_score": 0,
    "cash_flow_score": 0,
    "financial_position_score": None,
    "summary": "",
    "top_issues": [],
    "scorecard": {
        "form_990_dimensions": {},
        "cash_flow_dimensions": {},
        "financial_position_dimensions": {},
        "confound_flags": [],
        "data_integrity_warning": False,
    },
}


def _benchmark_prompt_body(
    instructions: str,
    input_data: dict,
    output_schema: dict,
) -> dict:
    """Build acompletion payload with instructions and compact input data separated."""
    from app.config.settings import settings

    content = f"""{instructions.strip()}

INPUT (JSON):
{json.dumps(input_data, separators=(",", ":"))}

OUTPUT SCHEMA (JSON only, no markdown):
{json.dumps(output_schema, separators=(",", ":"))}
"""
    max_tokens = min(settings.BENCHMARK_LLM_MAX_TOKENS, 4096)
    return {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": settings.TEMPERATURE,
    }


def build_benchmark_form_990_prompt(
    fiscal_year: int,
    manual_extraction: dict,
    generated_report: dict,
    *,
    prior_year_extraction: dict | None = None,
    deterministic_scorecard: dict | None = None,
) -> dict:
    instructions = benchmark_form_990_instructions.format(fiscal_year=fiscal_year)
    input_data = {
        "fiscal_year": fiscal_year,
        "deterministic_scorecard": deterministic_scorecard or {},
        "prior_year_form_990_extraction": prior_year_extraction or {},
        "manual_form_990_extraction": manual_extraction,
        "ai_tax_return_report": generated_report,
    }
    return _benchmark_prompt_body(
        instructions,
        input_data,
        BENCHMARK_FORM_990_OUTPUT_SCHEMA,
    )


def build_benchmark_cash_flow_prompt(
    fiscal_year: int,
    manual_extraction: dict,
    generated_report: dict,
    *,
    deterministic_scorecard: dict | None = None,
) -> dict:
    instructions = benchmark_cash_flow_instructions.format(fiscal_year=fiscal_year)
    input_data = {
        "fiscal_year": fiscal_year,
        "deterministic_scorecard": deterministic_scorecard or {},
        "manual_cash_flow_extraction": manual_extraction,
        "ai_cash_flow_report": generated_report,
    }
    return _benchmark_prompt_body(
        instructions,
        input_data,
        BENCHMARK_CASH_FLOW_OUTPUT_SCHEMA,
    )


def build_benchmark_financial_position_prompt(
    fiscal_year: int,
    manual_extraction: dict,
    generated_report: dict,
    *,
    prior_year_extraction: dict | None = None,
    prior_year_balance_sheet: dict | None = None,
    deterministic_scorecard: dict | None = None,
) -> dict:
    instructions = benchmark_financial_position_instructions.format(fiscal_year=fiscal_year)
    input_data = {
        "fiscal_year": fiscal_year,
        "deterministic_scorecard": deterministic_scorecard or {},
        "manual_financial_position_extraction": manual_extraction,
        "prior_year_financial_position_extraction": prior_year_extraction or {},
        "prior_year_quickbooks_balance_sheet": prior_year_balance_sheet or {},
        "ai_balance_sheet_report": generated_report,
    }
    return _benchmark_prompt_body(
        instructions,
        input_data,
        BENCHMARK_FINANCIAL_POSITION_OUTPUT_SCHEMA,
    )


def build_benchmark_synthesis_prompt(
    fiscal_year: int,
    form_990_result: dict,
    cash_flow_result: dict,
    processing_metadata: dict,
    *,
    form_990_scorecard: dict | None = None,
    cash_flow_scorecard: dict | None = None,
    financial_position_result: dict | None = None,
    financial_position_scorecard: dict | None = None,
) -> dict:
    input_data = {
        "fiscal_year": fiscal_year,
        "form_990_review": form_990_result,
        "cash_flow_review": cash_flow_result,
        "financial_position_review": financial_position_result or {},
        "form_990_scorecard": form_990_scorecard or {},
        "cash_flow_scorecard": cash_flow_scorecard or {},
        "financial_position_scorecard": financial_position_scorecard or {},
        "processing_metadata": processing_metadata,
    }
    return _benchmark_prompt_body(
        benchmark_synthesis_instructions,
        input_data,
        BENCHMARK_FINAL_OUTPUT_SCHEMA,
    )

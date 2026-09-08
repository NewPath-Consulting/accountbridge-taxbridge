"""Prompts for generating financial reports from WildApricot and QuickBooks data."""
import json
from typing import Dict, Any, Optional
from app.config.settings import settings
from app.utils.form_990_enforce import (
    part_viii_prompt_categories,
    part_viii_prompt_lines,
)



_MANDATORY_STRUCTURAL_LINE_ITEMS_RULE = """
**MANDATORY STRUCTURAL LINE ITEMS:**
Required balance sheet and Part X line items must never be omitted. When no source account
exists, emit the line with amount `0.00` and a `dataQualityFlag` or source note — do not
leave the field out entirely.
"""


def _user_prompt_priority_block(user_prompt: Optional[str]) -> str:
    """When provided, prepend user instructions with highest priority for all report LLM calls."""
    if not user_prompt or not user_prompt.strip():
        return ""
    cleaned = user_prompt.strip()
    return f"""## USER INSTRUCTIONS (HIGHEST PRIORITY)

The user provided the following guidance for this report run. When it conflicts with
instructions below, follow the user instructions first — except you must still:
- Return valid JSON matching the required schema for this report section
- Never fabricate amounts; every figure must remain traceable to source data
- Preserve mandatory structural line items and compliance rules when the user does not override them

\"\"\"{cleaned}\"\"\"

---

"""


def _apply_user_prompt(instruction: str, user_prompt: Optional[str] = None) -> str:
    block = _user_prompt_priority_block(user_prompt)
    return f"{block}{instruction}" if block else instruction


def _reference_financials_block(reference_financials: Optional[Dict[str, Any]]) -> str:
    if not reference_financials:
        return ""
    return f"""
**FILED REFERENCE FINANCIALS (from docs/ — authoritative for period balances when QuickBooks is thin):**
Use `prior_financial_position` for beginning cash and working-capital anchors in cash flow.
Use `filed_cash_flow.cash_reconciliation` for cash flow validation targets when present.
Prefer `filed_financial_position` line items over inferred QuickBooks sandbox rows when present.

{json.dumps(reference_financials, indent=2)}
"""


def _wildapricot_empty_block(wa_period_empty: bool) -> str:
    if not wa_period_empty:
        return ""
    return """
**WILDAPRICOT PERIOD EMPTY:**
No WildApricot invoices/payments fall in this reporting period. Do NOT infer membership,
deferred revenue, or contribution splits from WildApricot. Use QuickBooks only and add
`dataQualityFlag` on ambiguous Part VIII / Part X lines.
"""


def _qb_mapping_hints_block(qb_mapping_hints: Optional[Dict[str, Any]]) -> str:
    if not qb_mapping_hints:
        return ""
    return f"""
**QUICKBOOKS → FORM 990 MAPPING HINTS (use when classifying accounts):**
{json.dumps(qb_mapping_hints, indent=2)}
"""


def build_cash_flow_report_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    reference_financials: Optional[Dict[str, Any]] = None,
    user_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Build prompt for generating Cash Flow Report using GAAP indirect method."""
    
    instruction = f"""You are a nonprofit financial reporting engine responsible for generating a Statement of Cash Flows from QuickBooks Online and WildApricot data.

## INPUT SOURCES

**QuickBooks APIs:**
- ProfitAndLoss Report
- BalanceSheet Report
- General Ledger (if available)
- Chart of Accounts (if available)

**WildApricot APIs:**
- Invoices
- Payments
- Membership Transactions
- Event Registration Transactions

## OBJECTIVE

Generate a GAAP-compliant Statement of Cash Flows using the INDIRECT METHOD.
The output must follow the same structure as standard nonprofit cash flow statements.

---

## STEP 1 – DETERMINE REPORT PERIOD

Use:
- Balance Sheet Start Period
- Balance Sheet End Period
- Profit & Loss Start Period
- Profit & Loss End Period

Determine:
- report_start_date
- report_end_date
- accounting_basis
- currency

---

## STEP 2 – CALCULATE OPERATING ACTIVITIES

**Starting Point:**
Net Revenue = Total Revenue − Total Expenses
Source: QuickBooks ProfitAndLoss Net Income

Example: Net Revenue = 75,000.25

**OPERATING ADJUSTMENTS**

Calculate changes between beginning and ending balances.

Formula:
Adjustment = Ending Balance − Beginning Balance

**For Assets:**
- Increase in Asset → Negative Cash Impact
- Decrease in Asset → Positive Cash Impact

**For Liabilities:**
- Increase in Liability → Positive Cash Impact
- Decrease in Liability → Negative Cash Impact

Evaluate:
- Accounts Receivable
- Inventory
- Prepaid Expenses
- Prepaid Insurance
- Prepaid Rent
- Deposits
- Undeposited Funds
- Accounts Payable
- Accrued Liabilities
- Deferred Revenue
- Unearned Revenue
- Membership Dues Payable
- Event Revenue Payable
- Sponsor Revenue Payable

**DEPRECIATION ADJUSTMENT**

If accumulated depreciation exists:
- Add back depreciation expense
- Reason: Non-cash expense
- Classification: Operating Activity Adjustment

**WILD APRICOT ADJUSTMENTS**

Analyze:
- Invoices
- Payments

Identify:
- Membership dues billed but unpaid
- Event registrations billed but unpaid
- Payments received for future periods
- Deferred membership revenue
- Deferred event revenue
- Unearned sponsor revenue

Rules:
- Payment received before service period → Unearned Revenue Liability
- Increase in Unearned Revenue → Positive Operating Cash Flow
- Decrease in Unearned Revenue → Negative Operating Cash Flow

**NET CASH FROM OPERATING ACTIVITIES**

Formula:
```
Net Revenue
+ Depreciation
+ Liability Increases
− Liability Decreases
− Asset Increases
+ Asset Decreases
= Net Cash Provided By Operating Activities
```

---

## STEP 3 – CALCULATE INVESTING ACTIVITIES

Analyze Fixed Assets.

Examples:
- Equipment
- Furniture
- Vehicles
- Computers
- Leasehold Improvements
- Buildings
- Machinery

Formula:
- Asset Purchase → Cash Outflow
- Asset Sale → Cash Inflow

Examples:
- Truck Purchase
- Equipment Purchase
- Building Improvements

Output: Net Cash Provided By Investing Activities

---

## STEP 4 – CALCULATE FINANCING ACTIVITIES

Analyze:
- Loan Payable
- Notes Payable
- Mortgage Payable
- Equity Contributions

Rules:
- New Loan → Cash Inflow
- Loan Repayment → Cash Outflow
- Capital Contribution → Cash Inflow

Output: Net Cash Provided By Financing Activities

---

## STEP 5 – CASH RECONCILIATION

**Beginning Cash** = Opening Cash Accounts
**Ending Cash** = Ending Cash Accounts
**Net Increase** = Operating Cash Flow + Investing Cash Flow + Financing Cash Flow

Validation:
Beginning Cash + Net Increase = Ending Cash

If mismatch > 1%: Flag reconciliation warning.

---


## INPUT DATA

**REPORTING PERIOD:**
Start Date: {start_date}
End Date: {end_date}

**WILDAPRICOT DATA (Membership & Events):**
Each entity includes `aggregates` computed from ALL records (totals, by_month, by_order_type)
and `sample_records` (representative transactions; may be truncated when record_count is large).
Use aggregates for totals and samples for line-item detail.

{json.dumps(wildapricot_data, indent=2)}

**QUICKBOOKS DATA (Financial Records):**
Use `totals` for headline figures; use `formatted_report` and `top_rows` for detail.
When `prior_year_balance_sheet` is present, use its closing balances for beginning cash,
working-capital opening balances, and investing/financing anchors (do not default to $0).

{json.dumps(quickbooks_data, indent=2)}
{_reference_financials_block(reference_financials)}

---

## OUTPUT FORMAT

Return JSON only. Follow the FDX-inspired GAAP structure below exactly.
Each line item must include: `conceptId`, `label`, `amount`, `direction`, and `sourceSystem`.

```json
{{
  "statement": {{
    "type": "CashFlowStatement",
    "standard": "GAAP-Indirect",
    "period": {{ "startDate": "{start_date}", "endDate": "{end_date}" }},
    "currency": "USD",
    "accountingBasis": "Accrual | Cash"
  }},
  "operatingActivities": {{
    "netIncome": {{
      "amount": 0.00,
      "label": "Net Income / Change in Net Assets",
      "sourceSystem": "QuickBooks"
    }},
    "adjustments": [
      {{
        "conceptId": "Depreciation",
        "label": "",
        "amount": 0.00,
        "direction": "add | deduct",
        "sourceSystem": "QuickBooks | WildApricot"
      }}
    ],
    "changesInWorkingCapital": [
      {{
        "conceptId": "AccountsReceivable",
        "label": "",
        "amount": 0.00,
        "direction": "add | deduct",
        "sourceSystem": "QuickBooks | WildApricot"
      }}
    ],
    "netCashFromOperations": {{ "amount": 0.00, "label": "Net Cash Provided by Operating Activities" }}
  }},
  "investingActivities": {{
    "items": [
      {{
        "conceptId": "CapitalExpenditures",
        "label": "",
        "amount": 0.00,
        "direction": "add | deduct",
        "sourceSystem": "QuickBooks"
      }}
    ],
    "netCashFromInvesting": {{ "amount": 0.00, "label": "Net Cash Provided by (Used in) Investing Activities" }}
  }},
  "financingActivities": {{
    "items": [
      {{
        "conceptId": "ProceedsFromLoans",
        "label": "",
        "amount": 0.00,
        "direction": "add | deduct",
        "sourceSystem": "QuickBooks"
      }}
    ],
    "netCashFromFinancing": {{ "amount": 0.00, "label": "Net Cash Provided by (Used in) Financing Activities" }}
  }},
  "cashReconciliation": {{
    "beginningCash": {{ "amount": 0.00, "label": "Cash and Cash Equivalents, Beginning of Period" }},
    "netIncrease": {{ "amount": 0.00, "label": "Net Increase (Decrease) in Cash" }},
    "endingCash": {{ "amount": 0.00, "label": "Cash and Cash Equivalents, End of Period" }},
    "reconciled": true,
    "discrepancy": 0.00
  }}
}}
```

**Requirements:**
- Use QuickBooks as the primary accounting source
- Use WildApricot invoices and payments for deferred revenue and membership cash-flow adjustments
- Follow GAAP indirect-method cash flow presentation
- Every line item must include `conceptId` and `sourceSystem` for traceability
- Never fabricate balances
- Every amount must be traceable to source records
"""

    return {
        "messages": [
            {"role": "user", "content": _apply_user_prompt(instruction, user_prompt)}
        ],
        "max_tokens": settings.REPORTS_MAX_TOKENS,
        "temperature": settings.TEMPERATURE
    }


def build_balance_sheet_report_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    reference_financials: Optional[Dict[str, Any]] = None,
    user_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Build prompt for generating Balance Sheet Report (Statement of Financial Position)."""
    
    instruction = f"""You are an expert Certified Public Accountant (CPA) AI.

Your responsibility is to generate a standardized, audit-ready Statement of Financial Position (Balance Sheet) based on raw JSON data from QuickBooks and WildApricot.

## INPUT DATA TO PROCESS:

1. QuickBooks Balance Sheet JSON
2. WildApricot Membership and Event Data JSON (to validate Unearned Revenue and Dues Payable)

---

## BALANCE SHEET CLASSIFICATION RULES:

### 1. ASSETS:

**Current Assets:**
- Bank Accounts (Checking, Savings, Stripe, PayPal)
- Accounts Receivable
- Prepaid Expenses
- Lease Deposits

**Fixed Assets:**
- Equipment
- Shop Assets
- Leasehold Improvements
- Less: Accumulated Depreciation

### 2. LIABILITIES:

**Current Liabilities:**
- Accounts Payable
- Credit Cards
- Unearned Skills Education Fees
- Unearned Storage Fees
- Membership Dues Payable (e.g., to KC Woodturners)

**Long-Term Liabilities:**
- Notes payable

### 3. EQUITY (Net Assets):

- Retained Earnings
- Net Income
- Net Assets Without Donor Restrictions

---

## VALIDATION & RECONCILIATION RULES:

**Rule 1:** Total Assets MUST exactly equal Total Liabilities + Total Equity

**Rule 2:** Identify Unearned Revenue by cross-referencing WildApricot prepaid event registrations against QuickBooks deferred revenue accounts

---

## INPUT DATA

**AS OF DATE:**
End Date: {end_date}

**WILDAPRICOT DATA (Membership & Events):**
Each entity includes `aggregates` computed from ALL records (totals, by_month, by_order_type)
and `sample_records` (representative transactions; may be truncated when record_count is large).
Use aggregates for totals and samples for line-item detail.

{json.dumps(wildapricot_data, indent=2)}

**QUICKBOOKS DATA (Financial Records):**
Use `totals` for headline figures; use `formatted_report` and `top_rows` for detail.
When `prior_year_balance_sheet` is present, use its closing balances for beginning-of-period
anchors where applicable.

{json.dumps(quickbooks_data, indent=2)}
{_reference_financials_block(reference_financials)}

---

## OUTPUT FORMAT:

Return ONLY valid JSON. Follow the FDX-inspired GAAP nonprofit structure (ASC 958) below exactly.
Each line item must include: `conceptId`, `label`, `amount`, `sourceSystem`, and `sourceAccounts`.

```json
{{
  "statement": {{
    "type": "StatementOfFinancialPosition",
    "standard": "GAAP-Nonprofit (ASC 958)",
    "asOfDate": "{end_date}",
    "currency": "USD",
    "accountingBasis": "Accrual | Cash"
  }},
  "assets": {{
    "currentAssets": [
      {{
        "conceptId": "CashAndCashEquivalents",
        "label": "",
        "amount": 0.00,
        "sourceSystem": "QuickBooks | WildApricot",
        "sourceAccounts": []
      }}
    ],
    "totalCurrentAssets": 0.00,
    "nonCurrentAssets": [
      {{
        "conceptId": "PropertyPlantAndEquipmentNet",
        "label": "",
        "amount": 0.00,
        "sourceSystem": "QuickBooks",
        "sourceAccounts": []
      }}
    ],
    "totalNonCurrentAssets": 0.00,
    "totalAssets": 0.00
  }},
  "liabilities": {{
    "currentLiabilities": [
      {{
        "conceptId": "AccountsPayable",
        "label": "",
        "amount": 0.00,
        "sourceSystem": "QuickBooks | WildApricot",
        "sourceAccounts": []
      }}
    ],
    "totalCurrentLiabilities": 0.00,
    "nonCurrentLiabilities": [],
    "totalNonCurrentLiabilities": 0.00,
    "totalLiabilities": 0.00
  }},
  "netAssets": {{
    "withoutDonorRestrictions": {{ "amount": 0.00, "label": "Net Assets Without Donor Restrictions" }},
    "withDonorRestrictions": {{ "amount": 0.00, "label": "Net Assets With Donor Restrictions" }},
    "totalNetAssets": 0.00
  }},
  "totalLiabilitiesAndNetAssets": 0.00,
  "accountingEquation": {{
    "status": "Balanced | Unbalanced",
    "assetsTotal": 0.00,
    "liabilitiesAndNetAssetsTotal": 0.00,
    "discrepancy": 0.00
  }}
}}
```

**CRITICAL INSTRUCTIONS:**
- Extract all relevant balance sheet information from both data sources
{_MANDATORY_STRUCTURAL_LINE_ITEMS_RULE}
- Ensure Assets = Liabilities + Net Assets (nonprofit accounting equation must balance)
- Use `withoutDonorRestrictions` and `withDonorRestrictions` for net assets per ASC 958
- Calculate totals and subtotals accurately
- Ensure all financial figures are numeric (float)
- Return ONLY valid JSON - no markdown, no explanations
- All monetary values should be in USD
- Every line item must include `conceptId`, `sourceSystem`, and `sourceAccounts` for FDX traceability
- Use WildApricot data to validate unearned revenue and membership dues payable
"""

    return {
        "messages": [
            {"role": "user", "content": _apply_user_prompt(instruction, user_prompt)}
        ],
        "max_tokens": settings.REPORTS_MAX_TOKENS,
        "temperature": settings.TEMPERATURE
    }


def _tax_return_prompt_body(
    instruction: str,
    max_tokens: int,
    user_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": _apply_user_prompt(instruction, user_prompt)}],
        "max_tokens": max_tokens,
        "temperature": settings.TEMPERATURE,
    }




def _tax_return_line_item_format() -> str:
    return """## LINE ITEM FORMAT

For every generated line produce:
```json
{
  "form_section": "",
  "line_number": "",
  "amount": 0,
  "source_system": "",
  "classification": ""
}
```"""


def _tax_return_compact_output_rules() -> str:
    return """## OUTPUT SIZE RULES (CRITICAL)

- Return ONLY valid JSON. No markdown fences, comments, or trailing commas.
- Emit one object per official IRS Form 990 line in the requested section — NOT one object per QuickBooks account.
- Keep labels short (under 80 characters). Omit sourceAccounts, source_records, and narrative fields.
- Part IX must contain at most 25 objects in `partIX_expenses` (IRS lines 1-25); aggregate QuickBooks accounts into those lines."""


def _tax_return_part_ix_output_rules() -> str:
    return """## PART IX OUTPUT RULES (CRITICAL)

- `partIX_expenses` must have AT MOST 25 entries — one per IRS Form 990 Part IX line (lines 1-25).
- Aggregate all QuickBooks expense accounts into the matching IRS line; never emit one JSON object per QB account.
- Include `totalExpenses`, `totalProgramServices`, `totalManagementAndGeneral`, and `totalFundraising` at the root.
- Return complete, valid JSON that closes all arrays and objects."""


def _tax_return_input_data_block(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    reference_financials: Optional[Dict[str, Any]] = None,
    *,
    wa_period_empty: bool = False,
    qb_mapping_hints: Optional[Dict[str, Any]] = None,
) -> str:
    return f"""## INPUT DATA

**TAX YEAR:**
Start Date: {start_date}
End Date: {end_date}
{_wildapricot_empty_block(wa_period_empty)}
{_qb_mapping_hints_block(qb_mapping_hints)}

**WILDAPRICOT DATA:**
Each entity includes `aggregates` computed from ALL records (totals, by_month, by_order_type)
and `sample_records` (representative transactions; may be truncated when record_count is large).
Use aggregates for totals and samples for line-item detail.

{json.dumps(wildapricot_data, indent=2)}

**QUICKBOOKS DATA:**
Use `totals` for headline figures; use `formatted_report` and `top_rows` for detail.
When `prior_year_balance_sheet` is present, use its closing balances for all beginning-of-year
columns in Part X and Part XI (do not default to $0).

{json.dumps(quickbooks_data, indent=2)}
{_reference_financials_block(reference_financials)}"""


def build_tax_return_part_viii_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    user_prompt: Optional[str] = None,
    reference_financials: Optional[Dict[str, Any]] = None,
    *,
    wa_period_empty: bool = False,
    qb_mapping_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build prompt for Form 990 Part VIII (Statement of Revenue) only."""
    instruction = f"""You are an expert US Nonprofit Tax Compliance engine generating IRS Form 990 Part VIII only.

**JURISDICTION:** United States Federal Tax Filing | **FORM:** IRS Form 990

Classify all incoming revenue into exactly one category, and report it on a line that belongs to that category.

{part_viii_prompt_lines()}

**NONPROFIT COMPLIANCE:**
- WildApricot Membership, Membership Renewal and Event Registration → Program Service Revenue
- Membership dues default to Program Service Revenue unless a charitable component is documented
- Event revenue with substantial benefit → Program Service Revenue; excess over FMV → Contributions
- Donor contributions → always Contributions, Gifts, Grants (never Program Revenue)
- Sponsorship payments → Contributions. Only a portion buying advertising or other substantial return benefit is Other Revenue; absent evidence of such a benefit in the account detail, treat the payment as a contribution.
- Exhibitor, booth and trade show fees from a convention or trade show the organization runs in furtherance of its exempt purpose → Program Service Revenue
- Other Revenue is a residual. Before using it, rule out contributions, exempt-function services and investment income.

**VALIDATION:**
- Every revenue item in exactly one category
- Total Revenue must reconcile to QuickBooks Profit & Loss revenue

{_tax_return_line_item_format()}

{_tax_return_compact_output_rules()}

{_tax_return_input_data_block(wildapricot_data, quickbooks_data, start_date, end_date, reference_financials, wa_period_empty=wa_period_empty, qb_mapping_hints=qb_mapping_hints)}

---

## OUTPUT FORMAT

Return JSON only. Do not fabricate values. Use the FDX-aligned structure below.

Each revenue line item must include: `lineNumber`, `category`, `label`, `totalRevenue`, `programServiceRevenue`, `unrelatedBusinessRevenue`, `excludedRevenue`, `sourceSystem`.

```json
{{
  "partVIII_revenue": [
    {{
      "lineNumber": "1a",
      "category": "{part_viii_prompt_categories()}",
      "label": "",
      "totalRevenue": 0.00,
      "programServiceRevenue": 0.00,
      "unrelatedBusinessRevenue": 0.00,
      "excludedRevenue": 0.00,
      "sourceSystem": "QuickBooks | WildApricot"
    }}
  ],
  "totalRevenue": 0.00
}}
```
"""
    return _tax_return_prompt_body(
        instruction, settings.REPORTS_TAX_RETURN_SECTION_MAX_TOKENS, user_prompt
    )


def build_tax_return_part_ix_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    user_prompt: Optional[str] = None,
    reference_financials: Optional[Dict[str, Any]] = None,
    *,
    wa_period_empty: bool = False,
    qb_mapping_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build prompt for Form 990 Part IX (Functional Expenses) only."""
    instruction = f"""You are an expert US Nonprofit Tax Compliance engine generating IRS Form 990 Part IX only.

**JURISDICTION:** United States Federal Tax Filing | **FORM:** IRS Form 990

Classify every QuickBooks expense into exactly one functional bucket:
1. Program Services
2. Management and General
3. Fundraising

**MAPPING RULES:**
- Legal/Accounting/Executive compensation → Management & General
- Conference, educational events, membership services → Program Services
- Donor solicitation advertising/events → Fundraising
- Travel: classify by purpose in description

**VALIDATION:**
- Total expenses must reconcile to QuickBooks Profit & Loss expenses

{_tax_return_line_item_format()}

{_tax_return_compact_output_rules()}

{_tax_return_part_ix_output_rules()}

{_tax_return_input_data_block(wildapricot_data, quickbooks_data, start_date, end_date, reference_financials, wa_period_empty=wa_period_empty, qb_mapping_hints=qb_mapping_hints)}

---

## OUTPUT FORMAT

Return JSON only. Do not fabricate values. Use the FDX-aligned structure below.

Each expense line item must include: `lineNumber`, `label`, `totalExpenses`, `programServices`, `managementAndGeneral`, `fundraising`, `sourceSystem`.

```json
{{
  "partIX_expenses": [
    {{
      "lineNumber": "1",
      "label": "",
      "totalExpenses": 0.00,
      "programServices": 0.00,
      "managementAndGeneral": 0.00,
      "fundraising": 0.00,
      "sourceSystem": "QuickBooks"
    }}
  ],
  "totalExpenses": 0.00,
  "totalProgramServices": 0.00,
  "totalManagementAndGeneral": 0.00,
  "totalFundraising": 0.00
}}
```
"""
    return _tax_return_prompt_body(
        instruction,
        settings.REPORTS_TAX_RETURN_PART_IX_MAX_TOKENS,
        user_prompt,
    )


def build_tax_return_part_x_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    user_prompt: Optional[str] = None,
    reference_financials: Optional[Dict[str, Any]] = None,
    *,
    wa_period_empty: bool = False,
    qb_mapping_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build prompt for Form 990 Part X (Balance Sheet) only."""
    instruction = f"""You are an expert US Nonprofit Tax Compliance engine generating IRS Form 990 Part X only.

**JURISDICTION:** United States Federal Tax Filing | **FORM:** IRS Form 990

Map QuickBooks balance sheet accounts to Part X:
- **Assets:** Cash, AR, prepaid, equipment, investments, etc.
- **Liabilities:** AP, accrued liabilities, deferred revenue, loans
- **Net Assets:** Without donor restrictions; With donor restrictions

Use WildApricot prepaid memberships/events to validate deferred revenue where applicable.

**VALIDATION:**
- Net Assets = Assets - Liabilities
- Beginning Net Assets + Current Year Change = Ending Net Assets
- Populate all `beginningOfYear` columns from `prior_year_balance_sheet` closing balances
  (or `prior_financial_position` in reference financials). Do not default to $0 when prior data exists.

{_MANDATORY_STRUCTURAL_LINE_ITEMS_RULE}

{_tax_return_line_item_format()}

{_tax_return_compact_output_rules()}

{_tax_return_input_data_block(wildapricot_data, quickbooks_data, start_date, end_date, reference_financials, wa_period_empty=wa_period_empty, qb_mapping_hints=qb_mapping_hints)}

---

## OUTPUT FORMAT

Return JSON only. Do not fabricate values. Use the FDX-aligned structure below.

Each balance sheet line item must include: `lineNumber`, `label`, `beginningOfYear`, `endOfYear`, `sourceSystem`.

```json
{{
  "partX_balanceSheet": {{
    "assets": [
      {{
        "lineNumber": "1",
        "label": "",
        "beginningOfYear": 0.00,
        "endOfYear": 0.00,
        "sourceSystem": "QuickBooks | WildApricot"
      }}
    ],
    "totalAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
    "liabilitiesAndNetAssets": [
      {{
        "lineNumber": "17",
        "label": "",
        "beginningOfYear": 0.00,
        "endOfYear": 0.00,
        "sourceSystem": "QuickBooks"
      }}
    ],
    "totalLiabilities": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
    "netAssets": {{
      "withoutDonorRestrictions": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "withDonorRestrictions": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "totalNetAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }}
    }},
    "totalLiabilitiesAndNetAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }}
  }}
}}
```
"""
    return _tax_return_prompt_body(
        instruction, settings.REPORTS_TAX_RETURN_SECTION_MAX_TOKENS, user_prompt
    )


def build_tax_return_parts_i_vii_xi_xii_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    organization_details: Dict[str, Any],
    start_date: str,
    end_date: str,
    financial_parts: Dict[str, Any],
    user_prompt: Optional[str] = None,
    reference_financials: Optional[Dict[str, Any]] = None,
    *,
    wa_period_empty: bool = False,
    qb_mapping_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build prompt for Form 990 Parts I-VII, XI, XII, Schedule A, and Schedule O.

    Part VIII, IX, and X are already generated separately and supplied via
    `financial_parts`; do not regenerate those sections.
    """
    instruction = f"""You are an expert US Nonprofit Tax Compliance engine generating IRS Form 990 (2025).

**JURISDICTION:** United States Federal Tax Filing | **FORM:** IRS Form 990
**TAX YEAR:** {start_date} to {end_date}

## OBJECTIVE

Generate Form 990 Parts I through VII, Part XI, Part XII, Schedule A, and Schedule O.
Parts VIII (Revenue), IX (Functional Expenses), and X (Balance Sheet) were already
generated — use the supplied financial parts for cross-references and totals.
Do not regenerate Part VIII, IX, or X line items.

Use QuickBooks and WildApricot source data plus `organization_details`.
When `organization_details.filed_organization_information` is present, copy it
verbatim into `organizationInformation` — it was extracted from a filed Form 990
and is authoritative. Do not override or fabricate those fields.
Do not fabricate figures; use 0 or null when data is unavailable.

---

## PRE-GENERATED FINANCIAL PARTS (VIII / IX / X)

{json.dumps(financial_parts, indent=2)}

---

## PART I - SUMMARY

Populate from organization details and the financial parts above:
- Mission statement (1-2 sentences)
- Lines 3-6: voting members, independent members, employees, volunteers
- Lines 7a-7b: unrelated business revenue / UBTI
- Lines 8-19: revenue/expense summary (current year from Parts VIII/IX; prior year from QuickBooks if available, else null)
- Lines 20-22: total assets, liabilities, net assets (from Part X)

## PART II - SIGNATURE BLOCK

Officer name/title from organization details; leave signature date null.

## PART III - PROGRAM SERVICE ACCOMPLISHMENTS

Three largest program services by expense (from Part IX program column), plus line 4d/4e totals.

## PART IV - CHECKLIST OF REQUIRED SCHEDULES

The questions are printed on the form and are supplied by the application, so
emit a line number and an answer only -- never the question text. Answer only
the lines the source data actually settles and omit the rest; every line you
leave out is marked undetermined for a preparer, which is more useful than a
guess. Line 38 is always Yes (Schedule O required).

## PART V - OTHER IRS FILINGS AND TAX COMPLIANCE

Line number and value only, on the same terms: omit what the data does not
settle rather than defaulting it to 0 or No.

## PART VI - GOVERNANCE, MANAGEMENT, AND DISCLOSURE

Sections A, B, and C per standard Form 990 governance questions.

## PART VII - COMPENSATION

Officers/directors from organization details or QuickBooks payroll; independent contractors over $100k from vendors.

## PART XI - RECONCILIATION OF NET ASSETS

Lines 1-10 using totals from Parts VIII, IX, and X (line 1 = Part VIII total, line 2 = Part IX total, etc.).

## PART XII - FINANCIAL STATEMENTS AND REPORTING

Accounting method from QuickBooks report basis; audit/compilation answers from organization details if present.

## SCHEDULE A - PUBLIC CHARITY STATUS

Part I status box and Part II or III 5-year support schedule when 501(c)(3).

## SCHEDULE O - SUPPLEMENTAL INFORMATION

Narrative entries for Part I Line 1, Part VI Line 19, and any Yes answers requiring explanation.

---

## ORGANIZATION DETAILS

`filed_organization_information` (when present) is the authoritative source for
the `organizationInformation` output block. Use it exactly; fill only missing
fields from QuickBooks company info or other `organization_details` keys.

{json.dumps(organization_details, indent=2)}

{_tax_return_input_data_block(wildapricot_data, quickbooks_data, start_date, end_date, reference_financials, wa_period_empty=wa_period_empty, qb_mapping_hints=qb_mapping_hints)}

{_tax_return_compact_output_rules()}

---

## OUTPUT FORMAT

Return JSON only. Include every section below. Do not include Part VIII, IX, or X arrays.

```json
{{
  "statement": {{
    "type": "Form990",
    "formYear": "2025",
    "taxYear": {{ "startDate": "{start_date}", "endDate": "{end_date}" }},
    "accountingMethod": "Cash | Accrual | Other",
    "currency": "USD"
  }},
  "organizationInformation": {{
    "legalName": "",
    "dbaNames": [],
    "ein": "",
    "address": {{ "street": "", "city": "", "state": "", "zip": "" }},
    "telephone": "",
    "website": "",
    "principalOfficer": {{ "name": "", "title": "", "address": "" }},
    "taxExemptStatus": "501(c)(3) | 501(c)Other | 4947(a)(1) | 527",
    "formOfOrganization": "Corporation | Trust | Association | Other",
    "yearOfFormation": "",
    "stateOfLegalDomicile": "",
    "groupReturn": false,
    "groupExemptionNumber": null
  }},
  "partI_summary": {{
    "missionStatement": "",
    "line3_votingMembers": 0,
    "line4_independentVotingMembers": 0,
    "line5_totalEmployees": 0,
    "line6_totalVolunteers": 0,
    "line7a_unrelatedBusinessRevenue": 0.00,
    "line7b_netUnrelatedBusinessTaxableIncome": 0.00,
    "revenueExpenseSummary": {{
      "line8_contributionsAndGrants": {{ "priorYear": null, "currentYear": 0.00 }},
      "line9_programServiceRevenue": {{ "priorYear": null, "currentYear": 0.00 }},
      "line10_investmentIncome": {{ "priorYear": null, "currentYear": 0.00 }},
      "line11_otherRevenue": {{ "priorYear": null, "currentYear": 0.00 }},
      "line12_totalRevenue": {{ "priorYear": null, "currentYear": 0.00 }},
      "line13_grantsPaid": {{ "priorYear": null, "currentYear": 0.00 }},
      "line14_benefitsPaidToMembers": {{ "priorYear": null, "currentYear": 0.00 }},
      "line15_salariesCompBenefits": {{ "priorYear": null, "currentYear": 0.00 }},
      "line16a_professionalFundraisingFees": {{ "priorYear": null, "currentYear": 0.00 }},
      "line16b_totalFundraisingExpenses": 0.00,
      "line17_otherExpenses": {{ "priorYear": null, "currentYear": 0.00 }},
      "line18_totalExpenses": {{ "priorYear": null, "currentYear": 0.00 }},
      "line19_revenueLessExpenses": {{ "priorYear": null, "currentYear": 0.00 }}
    }},
    "netAssetsSummary": {{
      "line20_totalAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "line21_totalLiabilities": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "line22_netAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }}
    }}
  }},
  "partII_signatureBlock": {{
    "officerName": "",
    "officerTitle": "",
    "signatureDate": null
  }},
  "partIII_programServiceAccomplishments": {{
    "missionStatement": "",
    "line2_newServices": "Yes | No",
    "line3_significantChanges": "Yes | No",
    "programServices": [
      {{
        "lineRef": "4a",
        "code": "",
        "expenses": 0.00,
        "grantsIncluded": 0.00,
        "revenue": 0.00,
        "description": ""
      }}
    ],
    "line4d_otherProgramServices": {{ "expenses": 0.00, "grantsIncluded": 0.00, "revenue": 0.00, "description": "" }},
    "line4e_totalProgramServiceExpenses": 0.00
  }},
  "partIV_checklistOfRequiredSchedules": [
    {{ "line": "1", "answer": "Yes | No" }}
  ],
  "partV_statementsRegardingOtherIRSFilings": [
    {{ "line": "1a", "value": 0 }}
  ],
  "partVI_governance": {{
    "sectionA": [
      {{ "line": "1a", "value": 0 }}
    ],
    "sectionB_policies": [
      {{ "line": "12a", "answer": "Yes | No" }}
    ],
    "sectionC_disclosure": {{
      "line17_statesFiledIn": [],
      "line18_availabilityMethod": [],
      "line19_narrative": "",
      "line20_booksAndRecordsCustodian": {{ "name": "", "address": "", "phone": "" }}
    }}
  }},
  "partVII_compensation": {{
    "sectionA_officersDirectorsTrustees": [
      {{
        "name": "",
        "title": "",
        "avgHoursPerWeek": 0,
        "positions": {{ "individualTrustee": false, "institutionalTrustee": false, "officer": false, "keyEmployee": false, "highestCompensated": false, "former": false }},
        "reportableCompFromOrg": 0.00,
        "reportableCompFromRelatedOrgs": 0.00,
        "estimatedOtherComp": 0.00
      }}
    ],
    "line1b_subtotal": {{ "reportableCompFromOrg": 0.00, "reportableCompFromRelatedOrgs": 0.00, "estimatedOtherComp": 0.00 }},
    "line1c_continuationTotal": {{ "reportableCompFromOrg": 0.00, "reportableCompFromRelatedOrgs": 0.00, "estimatedOtherComp": 0.00 }},
    "line1d_total": {{ "reportableCompFromOrg": 0.00, "reportableCompFromRelatedOrgs": 0.00, "estimatedOtherComp": 0.00 }},
    "line2_countOver100k": 0,
    "line3_formerOfficerListed": "Yes | No",
    "line4_compOver150k": "Yes | No",
    "line5_unrelatedOrgComp": "Yes | No",
    "sectionB_independentContractors": [
      {{ "name": "", "address": "", "description": "", "compensation": 0.00 }}
    ],
    "line2_independentContractorsOver100k": 0
  }},
  "partXI_reconciliationOfNetAssets": {{
    "line1_totalRevenue": 0.00,
    "line2_totalExpenses": 0.00,
    "line3_revenueLessExpenses": 0.00,
    "line4_netAssetsBeginningOfYear": 0.00,
    "line5_netUnrealizedGainsLosses": 0.00,
    "line6_donatedServicesAndUseOfFacilities": 0.00,
    "line7_investmentExpenses": 0.00,
    "line8_priorPeriodAdjustments": 0.00,
    "line9_otherChanges": 0.00,
    "line10_netAssetsEndOfYear": 0.00
  }},
  "partXII_financialStatementsAndReporting": {{
    "line1_accountingMethod": "Cash | Accrual | Other",
    "line2a_compiledOrReviewed": "Yes | No",
    "line2b_audited": "Yes | No",
    "line2c_auditCommittee": "Yes | No | N/A",
    "line3a_federalAwardAudit": "Yes | No",
    "line3b_auditCompleted": "Yes | No | N/A"
  }},
  "scheduleA": {{
    "partI_publicCharityStatus": {{ "lineChecked": "10", "description": "" }},
    "supportSchedule": {{
      "method": "Part II (170(b)(1)(A)) | Part III (509(a)(2))",
      "years": ["", "", "", "", ""],
      "giftsGrantsContributionsMembershipFees": [null, null, null, null, 0.00],
      "exemptFunctionGrossReceipts": [null, null, null, null, 0.00],
      "grossInvestmentIncome": [null, null, null, null, 0.00],
      "totalSupport": [null, null, null, null, 0.00],
      "publicSupportPercentage": null,
      "investmentIncomePercentage": null,
      "supportTestMet": "Yes | No | Undetermined"
    }}
  }},
  "scheduleO": [
    {{ "partAndLine": "Part I Line 1", "narrative": "" }}
  ]
}}
```
"""
    return _tax_return_prompt_body(
        instruction, settings.REPORTS_TAX_RETURN_SECTION_MAX_TOKENS, user_prompt
    )


def build_tax_return_reconciliation_prompt(
    start_date: str,
    end_date: str,
    part_viii_summary: Dict[str, Any],
    part_ix_summary: Dict[str, Any],
    part_x_summary: Dict[str, Any],
    quickbooks_summary: Dict[str, Any],
    user_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Build prompt to reconcile Part VIII/IX/X and assemble the Form 990 draft summary."""
    instruction = f"""You are an expert US Nonprofit Tax Compliance engine finalizing an IRS Form 990 draft.

The Part VIII, IX, and X sections were already generated. Your job is to:
1. Reconcile them against QuickBooks totals
2. Summarize organization metadata
3. Assemble a compact generatedTaxReturnDraft referencing the supplied parts (do not re-derive line items)

**RECONCILIATION CHECKS:**
- Check 1: QuickBooks Revenue = Part VIII Total Revenue
- Check 2: QuickBooks Expenses = Part IX Total Expenses
- Check 3: Beginning Net Assets + Change = Ending Net Assets
  (use `prior_year_balance_sheet` closing net assets for beginning when present)
- Check 4: Assets = Liabilities + Net Assets

**ACCOUNTING METHOD:** Use QuickBooks reported method if present; else infer Cash or Accrual.

**TAX YEAR:** {start_date} to {end_date}

**PART VIII (REVENUE):**
{json.dumps(part_viii_summary, indent=2)}

**PART IX (EXPENSES):**
{json.dumps(part_ix_summary, indent=2)}

**PART X (BALANCE SHEET):**
{json.dumps(part_x_summary, indent=2)}

**QUICKBOOKS DATA (for reconciliation):**
{json.dumps(quickbooks_summary, indent=2)}

{_tax_return_compact_output_rules()}

---

## OUTPUT FORMAT

Return JSON only. Do not fabricate values. Keep `generatedTaxReturnDraft` compact (section totals and key line references only).

```json
{{
  "statement": {{
    "type": "Form990",
    "taxYear": {{ "startDate": "{start_date}", "endDate": "{end_date}" }},
    "accountingMethod": "Cash | Accrual | Other"
  }},
  "organizationSummary": {{
    "name": "",
    "taxYear": "{start_date} to {end_date}"
  }},
  "reconciliation": {{
    "total_revenue": 0.00,
    "total_expenses": 0.00,
    "beginning_net_assets": 0.00,
    "change_in_net_assets": 0.00,
    "ending_net_assets": 0.00
  }},
  "reconciliationResults": [],
  "validationErrors": [],
  "generatedTaxReturnDraft": {{}}
}}
```
"""
    return _tax_return_prompt_body(
        instruction, settings.REPORTS_TAX_RETURN_RECONCILIATION_MAX_TOKENS, user_prompt
    )


def build_tax_return_full_form990_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    organization_details: Dict[str, Any],
    start_date: str,
    end_date: str,
    user_prompt: Optional[str] = None,
    reference_financials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build prompt for generating a COMPLETE IRS Form 990 (Parts I-XII) plus
    Schedule A Part I/II/III and Schedule O narrative responses, in a single
    structured JSON document, from QuickBooks + WildApricot source data.

    This mirrors the full Form 990 layout (Summary, Program Service
    Accomplishments, Checklist of Required Schedules, Governance, Compensation,
    Revenue, Functional Expenses, Balance Sheet, Reconciliation of Net Assets,
    and Financial Statements & Reporting) as filed by 501(c)(3) organizations.
    """
    instruction = f"""You are an expert US Nonprofit Tax Compliance engine generating a COMPLETE IRS Form 990 (2025) return.

**JURISDICTION:** United States Federal Tax Filing | **FORM:** IRS Form 990, Return of Organization Exempt From Income Tax
**TAX YEAR:** {start_date} to {end_date}

## OBJECTIVE

Generate every part of Form 990 (Parts I through XII), plus Schedule A (Part I and
Part II or III, whichever applies based on public support test results) and
Schedule O narrative responses, using QuickBooks and WildApricot source data.
Do not fabricate any figure. Every numeric value must be traceable to a source
account, invoice, or aggregate. If a value cannot be derived from source data,
output 0.

---

## ORGANIZATION METADATA (Part I, Items A-M)

Populate from `organization_details` plus any QuickBooks company-info fields:
- Legal name, DBA name(s)
- EIN
- Address (number/street, city, state, ZIP)
- Telephone number
- Website
- Principal officer name, title, and address
- Tax-exempt status (501(c)(3), 501(c)(other), 4947(a)(1), or 527)
- Form of organization (Corporation, Trust, Association, Other)
- Year of formation
- State of legal domicile
- Group return / group exemption indicators (default "No"/blank unless provided)

---

## PART I - SUMMARY

1. Mission statement / most significant activities (1-2 sentences, derived from
   `organization_details` description or inferred from program service data; this
   text also becomes the Schedule O response for Part I, Line 1).
2. Line 3: Number of voting members of governing body (from board/officer roster
   if available, else 0).
3. Line 4: Number of independent voting members (same source).
4. Line 5: Total individuals employed in the calendar year (from QuickBooks
   payroll/employee data; 0 if no payroll accounts).
5. Line 6: Total volunteers (estimate; 0 if not derivable).
6. Line 7a/7b: Unrelated business revenue / net UBTI (default 0 unless UBI
   accounts identified).
7. Revenue/Expense summary (Prior Year vs Current Year), computed from:
   - Line 8: Contributions and grants (= Part VIII line 1h)
   - Line 9: Program service revenue (= Part VIII line 2g)
   - Line 10: Investment income (= Part VIII line 3 + 4 + 7d)
   - Line 11: Other revenue (= Part VIII lines 5, 6d, 8c, 9c, 10c, 11e)
   - Line 12: Total revenue (= Part VIII line 12)
   - Line 13: Grants and similar amounts paid (= Part IX col A lines 1-3)
   - Line 14: Benefits paid to/for members (= Part IX col A line 4)
   - Line 15: Salaries/comp/benefits (= Part IX col A lines 5-10)
   - Line 16a: Professional fundraising fees (= Part IX col A line 11e)
   - Line 16b: Total fundraising expenses (= Part IX col D line 25)
   - Line 17: Other expenses (= Part IX col A lines 11a-11d, 11f-24e)
   - Line 18: Total expenses (= Part IX col A line 25)
   - Line 19: Revenue less expenses (line 12 - line 18)
8. Net Assets/Fund Balances (Beginning vs End of Current Year):
   - Line 20: Total assets (= Part X line 16)
   - Line 21: Total liabilities (= Part X line 26)
   - Line 22: Net assets/fund balances (line 20 - line 21)

Prior Year figures come from any prior-year comparison data supplied in
`quickbooks_data` (e.g., a prior-period column); if unavailable, set prior-year
values to null. Do NOT estimate prior-year values.

---

## PART II - SIGNATURE BLOCK

Populate officer name/title from `organization_details.principal_officer`.
Leave signature/date/preparer fields as null placeholders (these require
in-person signature and are not derivable from financial data).

---

## PART III - STATEMENT OF PROGRAM SERVICE ACCOMPLISHMENTS

1. Line 1: Restate the mission statement.
2. Line 2/3: Default "No" unless program-change narratives are supplied in
   `organization_details`.
3. Line 4a-4c: The three largest program services by expense, each with:
   - Program code (leave blank unless provided)
   - Expenses (sum of Part IX program-service-expense column items tagged to
     that program)
   - Grants included in that expense figure (0 unless grant accounts identified)
   - Revenue directly attributable to that program (from Part VIII program
     service revenue lines)
   - A narrative description (concise, derived from WildApricot event/category
     names and QuickBooks class/program tracking, if present)
4. Line 4d: Other program services not in the top three (aggregate).
5. Line 4e: Total program service expenses (sum of 4a-4d expenses; must equal
   Part IX column (B) total).

---

## PART IV - CHECKLIST OF REQUIRED SCHEDULES

For each of lines 1-38, output "Yes"/"No" based on derivable facts:
- Line 1: "Yes" if tax-exempt status is 501(c)(3) or 4947(a)(1), else "No".
- Line 2: "Yes" if Schedule B contributor thresholds are met (large individual
  contributions >= $5,000 or 2% of total support); else "No".
- Line 18: "Yes" if Part VIII lines 1c + 8a combined > $15,000 (fundraising
  event gross income/contributions).
- Line 19: "Yes" if Part VIII line 9a (gross gaming income) > $15,000.
- Line 38: Always "Yes" (Schedule O is always required).
- All other lines: "No" unless source data explicitly indicates the activity
  (e.g., foreign accounts, related-party transactions, bonds, donor-advised
  funds). Default to "No" for any line where the answer is uncertain rather
  than guessing "Yes".

---

## PART V - STATEMENTS REGARDING OTHER IRS FILINGS AND TAX COMPLIANCE

- Line 1a/1b: Count of Forms 1096/W-2G if 1099/W-2G data is present in
  QuickBooks vendor records; else 0.
- Line 2a: Number of employees from W-3/payroll summary; else 0.
- Line 2b: "Yes" if line 2a > 0 and payroll tax accounts show activity.
- Line 3a/3b: "Yes" if UBI accounts > $1,000; 990-T filed status unknown -> "No".
- Line 6a/6b: "Yes" to 6a if gross receipts > $100,000 and any non-deductible
  solicitations identified; else "No". 6b follows from 6a.
- Remaining lines: default "No" unless source data supports "Yes".

---

## PART VI - GOVERNANCE, MANAGEMENT, AND DISCLOSURE

**Section A:**
- Line 1a/1b: Voting members / independent voting members (same as Part I
  lines 3-4).
- Lines 2-9: "Yes"/"No" governance questions; default "No" unless explicit
  board-conflict, management-company, or asset-diversion data is supplied.
- Line 7a: "Yes" if the organization has a membership structure with voting
  rights over board elections (check `organization_details` for membership
  bylaws indicators).

**Section B (Policies):**
- Lines 10-16: Conflict of interest policy, whistleblower policy, document
  retention policy, compensation-review process, joint ventures - default
  "No" unless policy documents are referenced in `organization_details`.

**Section C (Disclosure):**
- Line 17: States where Form 990 must be filed (from organization's state of
  domicile and any multi-state registration data).
- Line 18: How Forms 1023/990/990-T are made available (Own website, Another's
  website, Upon request, Other) - infer from `organization_details.website`
  presence (if website exists, mark "Own website" + "Upon request" as a
  reasonable default).
- Line 19: Narrative on availability of governing documents/financial
  statements (goes to Schedule O).
- Line 20: Name/address/phone of person who possesses books and records
  (default to principal officer).

---

## PART VII - COMPENSATION OF OFFICERS, DIRECTORS, TRUSTEES, KEY EMPLOYEES,
## HIGHEST COMPENSATED EMPLOYEES, AND INDEPENDENT CONTRACTORS

**Section A:** For each person in the board/officer roster supplied in
`organization_details` (or QuickBooks payroll data tagged as officer/director):
- Name and title
- Average hours per week
- Position checkboxes (individual trustee, institutional trustee, officer, key
  employee, highest compensated employee, former)
- Reportable compensation from the organization (W-2/1099, from QuickBooks
  payroll/1099 records)
- Reportable compensation from related organizations (0 unless related-org data
  provided)
- Estimated other compensation (benefits, deferred comp - from QuickBooks if
  tagged)

Compute:
- Line 1b: Subtotal
- Line 1c: Total from continuation sheets (0 if none)
- Line 1d: Total (1b + 1c)
- Line 2: Count of individuals with reportable compensation > $100,000
- Line 3/4/5: "Yes"/"No" follow-up questions based on the above data

**Section B (Independent Contractors):** List any vendor in QuickBooks paid
more than $100,000 during the tax year, with description of services and
compensation amount. Line 2: count of such contractors.

---

## PART VIII - STATEMENT OF REVENUE

Reuse the classification rules below (identical to the standalone Part VIII
prompt) to populate lines 1a-12, columns (A) Total revenue, (B) Related or
exempt function revenue, (C) Unrelated business revenue, (D) Revenue excluded
under sections 512-514:

Classify all incoming revenue into exactly one category.

**CATEGORY 1: Contributions, Gifts, Grants** - Part VIII Line 1 (sub-lines
1a federated campaigns, 1b membership dues, 1c fundraising events, 1d related
organizations, 1e government grants, 1f all other contributions; 1g noncash
contributions included above; 1h total)
**CATEGORY 2: Program Service Revenue** - Part VIII Line 2 (lines 2a-2f by
business activity, 2g total)
  WildApricot: Membership, Membership Renewal, Event Registration -> Program
  Service Revenue
**CATEGORY 3: Investment Income** - Part VIII Line 3
**CATEGORY 4: Income from tax-exempt bond proceeds** - Part VIII Line 4
**CATEGORY 5: Royalties** - Part VIII Line 5
**CATEGORY 6: Rental Income** - Part VIII Line 6 (gross rents, rental expenses,
rental income/loss, net rental income/loss)
**CATEGORY 7: Gain/Loss from Sale of Assets** - Part VIII Line 7
**CATEGORY 8: Fundraising Event Revenue** - Part VIII Line 8 (gross income,
direct expenses, net income/loss)
**CATEGORY 9: Gaming Revenue** - Part VIII Line 9 (gross income, direct
expenses, net income/loss)
**CATEGORY 10: Sales of Inventory** - Part VIII Line 10 (gross sales, cost of
goods sold, net income/loss)
**CATEGORY 11: Miscellaneous/Other Revenue** - Part VIII Line 11
**Line 12: Total revenue** - sum of lines 1h, 2g, 3, 4, 5, 6d, 7d, 8c, 9c, 10c, 11e

**NONPROFIT COMPLIANCE:**
- Membership dues default to Program Service Revenue unless a charitable
  component is documented
- Event revenue with substantial benefit -> Program Service Revenue; excess
  over FMV -> Contributions
- Donor contributions -> always Contributions, Gifts, Grants (never Program
  Revenue)

**VALIDATION:**
- Every revenue item in exactly one category
- Total Revenue (line 12) must reconcile to QuickBooks Profit & Loss revenue
  and must equal Part I, line 12

---

## PART IX - STATEMENT OF FUNCTIONAL EXPENSES

Classify every QuickBooks expense into exactly one functional bucket across
columns (A) Total, (B) Program service expenses, (C) Management and general
expenses, (D) Fundraising expenses, for lines 1-24e:

1. Grants/assistance to domestic organizations and governments (line 1)
2. Grants/assistance to domestic individuals (line 2)
3. Grants to foreign orgs/governments/individuals (line 3)
4. Benefits paid to/for members (line 4)
5. Compensation of current officers/directors/trustees/key employees (line 5)
6. Compensation to disqualified persons (line 6)
7. Other salaries and wages (line 7)
8. Pension plan accruals/contributions (line 8)
9. Other employee benefits (line 9)
10. Payroll taxes (line 10)
11. Fees for services - management, legal, accounting, lobbying, professional
    fundraising, investment management, other (lines 11a-11g)
12. Advertising and promotion (line 12)
13. Office expenses (line 13)
14. Information technology (line 14)
15. Royalties (line 15)
16. Occupancy (line 16)
17. Travel (line 17)
18. Payments of travel/entertainment for public officials (line 18)
19. Conferences, conventions, and meetings (line 19)
20. Interest (line 20)
21. Payments to affiliates (line 21)
22. Depreciation, depletion, and amortization (line 22)
23. Insurance (line 23)
24. Other expenses, itemized (lines 24a-24e, with any category >10% of line 25
    listed individually)
25. Total functional expenses (line 25) = sum of lines 1-24e

**MAPPING RULES:**
- Legal/Accounting/Executive compensation -> Management & General
- Conference, educational events, membership services -> Program Services
- Donor solicitation advertising/events -> Fundraising
- Travel: classify by purpose in description
- Occupancy and depreciation: allocate to Program Services unless an
  administrative-only facility is indicated

**VALIDATION:**
- Total expenses (line 25, column A) must reconcile to QuickBooks Profit & Loss
  expenses and must equal Part I, line 18
- Column (B) total (line 25) must equal Part III, line 4e

---

## PART X - BALANCE SHEET

Map QuickBooks balance sheet accounts to Part X lines 1-33, for both (A)
Beginning of year and (B) End of year:

- Line 1: Cash - non-interest-bearing
- Line 2: Savings and temporary cash investments
- Line 3: Pledges and grants receivable, net
- Line 4: Accounts receivable, net
- Lines 5-6: Receivables from officers/directors/disqualified persons (0
  unless identified)
- Line 7: Notes and loans receivable, net
- Line 8: Inventories for sale or use
- Line 9: Prepaid expenses and deferred charges
- Line 10a/10b/10c: Land, buildings, equipment - cost basis, accumulated
  depreciation, book value (10c)
- Lines 11-15: Investments (publicly traded, other securities, program-related),
  intangible assets, other assets
- Line 16: Total assets (sum of lines 1-15)
- Line 17: Accounts payable and accrued expenses
- Line 18: Grants payable
- Line 19: Deferred revenue
- Line 20: Tax-exempt bond liabilities
- Line 21: Escrow or custodial account liability
- Line 22: Payables to officers/directors/disqualified persons (0 unless
  identified)
- Lines 23-24: Secured/unsecured notes and loans payable
- Line 25: Other liabilities
- Line 26: Total liabilities (sum of lines 17-25)
- Lines 27-28: Net assets without/with donor restrictions (FASB ASC 958)
- Lines 29-31: Capital stock, paid-in surplus, retained earnings (only if NOT
  following FASB ASC 958 - otherwise leave 0)
- Line 32: Total net assets or fund balances
- Line 33: Total liabilities and net assets/fund balances (must equal line 16)

Use WildApricot prepaid memberships/events to validate deferred revenue (line 19)
where applicable.

**VALIDATION:**
- Net Assets (line 32) = Assets (line 16) - Liabilities (line 26)
- Beginning Net Assets + Current Year Change (Part XI line 3) = Ending Net
  Assets (line 32, column B)
- Line 16 = Line 33 for both columns

---

## PART XI - RECONCILIATION OF NET ASSETS

- Line 1: Total revenue (= Part VIII line 12 = Part I line 12)
- Line 2: Total expenses (= Part IX line 25 = Part I line 18)
- Line 3: Revenue less expenses (line 1 - line 2)
- Line 4: Net assets at beginning of year (= Part X line 32, column A)
- Line 5: Net unrealized gains/losses on investments (0 unless investment
  revaluation accounts identified)
- Line 6: Donated services and use of facilities (0 unless in-kind accounts
  identified)
- Line 7: Investment expenses (0 unless identified)
- Line 8: Prior period adjustments (0 unless identified)
- Line 9: Other changes in net assets (0 unless identified; explain in
  Schedule O if non-zero)
- Line 10: Net assets at end of year = sum of lines 3-9; must equal Part X
  line 32, column B

---

## PART XII - FINANCIAL STATEMENTS AND REPORTING

- Line 1: Accounting method (Cash, Accrual, or Other) - read from QuickBooks
  reporting basis setting.
- Line 2a: "Yes" if compiled/reviewed financial statements indicated in
  `organization_details`, else "No".
- Line 2b: "Yes" if audited financial statements indicated, else "No".
- Line 2c: "Yes" if an audit committee is indicated, else "No" (only answer if
  2a or 2b is "Yes").
- Line 3a/3b: "Yes" only if federal award / Uniform Guidance audit requirements
  are indicated in source data; else "No".

---

## SCHEDULE A - PUBLIC CHARITY STATUS AND PUBLIC SUPPORT

Only generate if Part I tax-exempt status is 501(c)(3) or 4947(a)(1).

**Part I:** Determine the public charity status box (lines 1-12). Default to
line 10 (509(a)(2) - normally receives >1/3 support from contributions, dues,
and exempt-function gross receipts) unless source data clearly indicates a
different basis (e.g., predominantly government/general-public contributions
-> line 7).

**Part II or Part III (5-year support schedule):**
- Build a 5-year table (current year + 4 prior years) of:
  - Gifts, grants, contributions, and membership fees received
  - Gross receipts from admissions/merchandise/services related to exempt
    purpose
  - Gross receipts from activities not an unrelated trade or business
  - Gross investment income (interest, dividends, rents, royalties)
  - Total support
- Prior-year columns: use historical data if supplied in `quickbooks_data`;
  otherwise set to null (do not estimate).
- Compute public support percentage (line 15) and investment income percentage
  (line 17 for Part III).
- Check the 33-1/3% support test box if line 15 > 33.33% and line 17
  (Part III only) <= 33.33%.

---

## SCHEDULE O - SUPPLEMENTAL INFORMATION

Generate narrative text blocks keyed by Part/Line number for every Form 990
question that requires a Schedule O explanation, including at minimum:
- Part I, Line 1 (mission statement)
- Part III, Line 4d (other program services, if any)
- Part VI, Line 11b (review process for Form 990, if a process is known)
- Part VI, Line 19 (public availability of governing documents/financial
  statements)
- Any "Yes" answer in Part IV or Part VI that requires explanation
- Part XI, Line 9 (if non-zero, explain other changes in net assets)

Each entry: {{ "partAndLine": "Part VI Line 19", "narrative": "..." }}

---

{_tax_return_line_item_format()}

{_tax_return_compact_output_rules()}

## ORGANIZATION DETAILS

{json.dumps(organization_details, indent=2)}

{_tax_return_input_data_block(wildapricot_data, quickbooks_data, start_date, end_date, reference_financials)}

---

## OUTPUT FORMAT

Return JSON only. No markdown fences, comments, or trailing commas. Do not
fabricate values - use 0/null for anything not derivable from source data.
Every numeric line item must include `sourceSystem` for traceability.

```json
{{
  "statement": {{
    "type": "Form990",
    "formYear": "2025",
    "taxYear": {{ "startDate": "{start_date}", "endDate": "{end_date}" }},
    "accountingMethod": "Cash | Accrual | Other",
    "currency": "USD"
  }},
  "organizationInformation": {{
    "legalName": "",
    "dbaNames": [],
    "ein": "",
    "address": {{ "street": "", "city": "", "state": "", "zip": "" }},
    "telephone": "",
    "website": "",
    "principalOfficer": {{ "name": "", "title": "", "address": "" }},
    "taxExemptStatus": "501(c)(3) | 501(c)Other | 4947(a)(1) | 527",
    "formOfOrganization": "Corporation | Trust | Association | Other",
    "yearOfFormation": "",
    "stateOfLegalDomicile": "",
    "groupReturn": false,
    "groupExemptionNumber": null
  }},
  "partI_summary": {{
    "missionStatement": "",
    "line3_votingMembers": 0,
    "line4_independentVotingMembers": 0,
    "line5_totalEmployees": 0,
    "line6_totalVolunteers": 0,
    "line7a_unrelatedBusinessRevenue": 0.00,
    "line7b_netUnrelatedBusinessTaxableIncome": 0.00,
    "revenueExpenseSummary": {{
      "line8_contributionsAndGrants": {{ "priorYear": null, "currentYear": 0.00 }},
      "line9_programServiceRevenue": {{ "priorYear": null, "currentYear": 0.00 }},
      "line10_investmentIncome": {{ "priorYear": null, "currentYear": 0.00 }},
      "line11_otherRevenue": {{ "priorYear": null, "currentYear": 0.00 }},
      "line12_totalRevenue": {{ "priorYear": null, "currentYear": 0.00 }},
      "line13_grantsPaid": {{ "priorYear": null, "currentYear": 0.00 }},
      "line14_benefitsPaidToMembers": {{ "priorYear": null, "currentYear": 0.00 }},
      "line15_salariesCompBenefits": {{ "priorYear": null, "currentYear": 0.00 }},
      "line16a_professionalFundraisingFees": {{ "priorYear": null, "currentYear": 0.00 }},
      "line16b_totalFundraisingExpenses": 0.00,
      "line17_otherExpenses": {{ "priorYear": null, "currentYear": 0.00 }},
      "line18_totalExpenses": {{ "priorYear": null, "currentYear": 0.00 }},
      "line19_revenueLessExpenses": {{ "priorYear": null, "currentYear": 0.00 }}
    }},
    "netAssetsSummary": {{
      "line20_totalAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "line21_totalLiabilities": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "line22_netAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }}
    }}
  }},
  "partII_signatureBlock": {{
    "officerName": "",
    "officerTitle": "",
    "signatureDate": null
  }},
  "partIII_programServiceAccomplishments": {{
    "missionStatement": "",
    "line2_newServices": "Yes | No",
    "line3_significantChanges": "Yes | No",
    "programServices": [
      {{
        "lineRef": "4a",
        "code": "",
        "expenses": 0.00,
        "grantsIncluded": 0.00,
        "revenue": 0.00,
        "description": ""
      }}
    ],
    "line4d_otherProgramServices": {{ "expenses": 0.00, "grantsIncluded": 0.00, "revenue": 0.00, "description": "" }},
    "line4e_totalProgramServiceExpenses": 0.00
  }},
  "partIV_checklistOfRequiredSchedules": [
    {{ "line": "1", "answer": "Yes | No" }}
  ],
  "partV_statementsRegardingOtherIRSFilings": [
    {{ "line": "1a", "value": 0 }}
  ],
  "partVI_governance": {{
    "sectionA": [
      {{ "line": "1a", "value": 0 }}
    ],
    "sectionB_policies": [
      {{ "line": "12a", "answer": "Yes | No" }}
    ],
    "sectionC_disclosure": {{
      "line17_statesFiledIn": [],
      "line18_availabilityMethod": [],
      "line19_narrative": "",
      "line20_booksAndRecordsCustodian": {{ "name": "", "address": "", "phone": "" }}
    }}
  }},
  "partVII_compensation": {{
    "sectionA_officersDirectorsTrustees": [
      {{
        "name": "",
        "title": "",
        "avgHoursPerWeek": 0,
        "positions": {{ "individualTrustee": false, "institutionalTrustee": false, "officer": false, "keyEmployee": false, "highestCompensated": false, "former": false }},
        "reportableCompFromOrg": 0.00,
        "reportableCompFromRelatedOrgs": 0.00,
        "estimatedOtherComp": 0.00
      }}
    ],
    "line1b_subtotal": {{ "reportableCompFromOrg": 0.00, "reportableCompFromRelatedOrgs": 0.00, "estimatedOtherComp": 0.00 }},
    "line1c_continuationTotal": {{ "reportableCompFromOrg": 0.00, "reportableCompFromRelatedOrgs": 0.00, "estimatedOtherComp": 0.00 }},
    "line1d_total": {{ "reportableCompFromOrg": 0.00, "reportableCompFromRelatedOrgs": 0.00, "estimatedOtherComp": 0.00 }},
    "line2_countOver100k": 0,
    "line3_formerOfficerListed": "Yes | No",
    "line4_compOver150k": "Yes | No",
    "line5_unrelatedOrgComp": "Yes | No",
    "sectionB_independentContractors": [
      {{ "name": "", "address": "", "description": "", "compensation": 0.00 }}
    ],
    "line2_independentContractorsOver100k": 0
  }},
  "partVIII_revenue": [
    {{
      "lineNumber": "1a",
      "category": "Contributions, Gifts, Grants | Program Service Revenue | Investment Income | Income from Tax-Exempt Bonds | Royalties | Rental Income | Gain/Loss on Sale of Assets | Fundraising Event Revenue | Gaming Revenue | Sales of Inventory | Other Revenue",
      "label": "",
      "totalRevenue": 0.00,
      "relatedOrExemptFunctionRevenue": 0.00,
      "unrelatedBusinessRevenue": 0.00,
      "excludedRevenue": 0.00,
      "sourceSystem": "QuickBooks | WildApricot"
    }}
  ],
  "partVIII_totalRevenue": 0.00,
  "partIX_expenses": [
    {{
      "lineNumber": "1",
      "label": "",
      "totalExpenses": 0.00,
      "programServices": 0.00,
      "managementAndGeneral": 0.00,
      "fundraising": 0.00,
      "sourceSystem": "QuickBooks"
    }}
  ],
  "partIX_totals": {{ "totalExpenses": 0.00, "totalProgramServices": 0.00, "totalManagementAndGeneral": 0.00, "totalFundraising": 0.00 }},
  "partX_balanceSheet": {{
    "assets": [
      {{ "lineNumber": "1", "label": "", "beginningOfYear": 0.00, "endOfYear": 0.00, "sourceSystem": "QuickBooks | WildApricot" }}
    ],
    "totalAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
    "liabilities": [
      {{ "lineNumber": "17", "label": "", "beginningOfYear": 0.00, "endOfYear": 0.00, "sourceSystem": "QuickBooks" }}
    ],
    "totalLiabilities": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
    "netAssets": {{
      "withoutDonorRestrictions": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "withDonorRestrictions": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }},
      "totalNetAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }}
    }},
    "totalLiabilitiesAndNetAssets": {{ "beginningOfYear": 0.00, "endOfYear": 0.00 }}
  }},
  "partXI_reconciliationOfNetAssets": {{
    "line1_totalRevenue": 0.00,
    "line2_totalExpenses": 0.00,
    "line3_revenueLessExpenses": 0.00,
    "line4_netAssetsBeginningOfYear": 0.00,
    "line5_netUnrealizedGainsLosses": 0.00,
    "line6_donatedServicesAndUseOfFacilities": 0.00,
    "line7_investmentExpenses": 0.00,
    "line8_priorPeriodAdjustments": 0.00,
    "line9_otherChanges": 0.00,
    "line10_netAssetsEndOfYear": 0.00
  }},
  "partXII_financialStatementsAndReporting": {{
    "line1_accountingMethod": "Cash | Accrual | Other",
    "line2a_compiledOrReviewed": "Yes | No",
    "line2b_audited": "Yes | No",
    "line2c_auditCommittee": "Yes | No | N/A",
    "line3a_federalAwardAudit": "Yes | No",
    "line3b_auditCompleted": "Yes | No | N/A"
  }},
  "scheduleA": {{
    "partI_publicCharityStatus": {{ "lineChecked": "10", "description": "" }},
    "supportSchedule": {{
      "method": "Part II (170(b)(1)(A)) | Part III (509(a)(2))",
      "years": ["", "", "", "", ""],
      "giftsGrantsContributionsMembershipFees": [null, null, null, null, 0.00],
      "exemptFunctionGrossReceipts": [null, null, null, null, 0.00],
      "grossInvestmentIncome": [null, null, null, null, 0.00],
      "totalSupport": [null, null, null, null, 0.00],
      "publicSupportPercentage": null,
      "investmentIncomePercentage": null,
      "supportTestMet": "Yes | No | Undetermined"
    }}
  }},
  "scheduleO": [
    {{ "partAndLine": "Part I Line 1", "narrative": "" }}
  ]
}}
```
"""
    return _tax_return_prompt_body(
        instruction, settings.REPORTS_TAX_RETURN_RECONCILIATION_MAX_TOKENS, user_prompt
    )


def build_tax_return_report_prompt(
    wildapricot_data: Dict[str, Any],
    quickbooks_data: Dict[str, Any],
    start_date: str,
    end_date: str,
    user_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Backward-compatible alias; reports service uses split Part VIII/IX/X prompts."""
    return build_tax_return_part_viii_prompt(
        wildapricot_data, quickbooks_data, start_date, end_date, user_prompt
    )

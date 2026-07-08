#  User Manual

It has two parts:

- **Part A — Web Dashboard:** a step-by-step guide for everyday users (no technical knowledge required).
- **Part B — Backend API:** a reference for developers and integrators who call the FastAPI backend directly.

---


# Part A — Web Dashboard

A step-by-step guide to using the appplication. This part is written for everyday users — no technical knowledge required. Just follow the screens.

## 1. What Is This Tool?

This **Reports → Benchmark** dashboard is an AI-powered Virtual CFO tool for nonprofits. It automatically gathers your financial and membership data and turns it into professional financial reports — all from one web page.
**It connects to two systems:**

| System | What it provides |
|--------|------------------|
| **QuickBooks** | Accounting data (Profit & Loss, Balance Sheet) |
| **WildApricot** | Membership, events, donations, invoices, payments |

**It produces three reports:**

1. **Cash Flow Report** — how money moved in and out
2. **Balance Sheet** — what you own and owe
3. **Tax Return Document** — a draft IRS **Form 990**

It can also **benchmark** your AI reports against real, human-prepared documents to check accuracy.

---

## 2. Before You Begin

You will need:

- Your **WildApricot Account ID** (a number, e.g. `497705`)
- Your **QuickBooks Realm ID / Company ID** (a number)
- A web browser (Chrome, Edge, or Firefox)

> Your administrator normally sets up the QuickBooks and WildApricot connections once. Day to day, you usually only need the two ID numbers.

---

## 3. Opening the Dashboard

1. Open your web browser.
2. Go to the dashboard address.
3. The **Reports → Benchmark** page appears.

---

## 4. Understanding the Screen

The page has two areas:

- **Left sidebar** — your settings (IDs, dates, options, and pipeline status).
- **Main area** — the 3-step workflow and result tabs.

At the top of the main area are four tabs:

| Tab | Purpose |
|-----|---------|
| **Pipeline** | Run the full process, step by step |
| **Reports** | Read the generated reports |
| **Benchmark** | See benchmark accuracy scores |
| **Raw JSON** | View the full technical output |

You normally work top-to-bottom through **Step 1 → Step 2 → Step 3** in the Pipeline tab.

---

## 5. Sidebar: Configuration

Fill these in before running anything.

| Field | What to enter |
|-------|---------------|
| **API Base URL** | The backend address (usually already filled) |
| **WildApricot Account ID** | Your numeric WildApricot account ID |
| **QuickBooks Realm ID** | Your numeric QuickBooks company ID |
| **Date Range — Start / End** | The reporting period. For best benchmark results, use a full calendar year (Jan 1 → Dec 31) |
| **Benchmark Options** | Optional fiscal years for the benchmark run |

The sidebar also shows:

- **Pipeline Status** — a checklist of the 3 steps as you complete them.
- **Reset** — clears all results so you can start fresh.

> **Tip:** If your dates are not a full calendar year, a yellow warning appears. It is only a suggestion — you can still run reports.

---

## 6. Step 1 — Generate Reports

This is the main action. It builds all three reports.

1. Check the **WildApricot Account ID** and **QuickBooks Realm ID** in the sidebar.
2. Check the **date range**.
3. (Optional) Type a **User prompt** — see the [next section](#7-report-instructions-custom-prompt).
4. Click ** Run Reports**.
5. A spinner appears while data is fetched and reports are generated. This can take **several minutes** — please wait.
6. When it finishes, the reports are saved in the current session and **Step 2** unlocks.

> **If an ID is missing:** You'll see a friendly message asking you to enter the WildApricot and QuickBooks IDs. Fill them in and click Run Reports again.

---

## 7. Report Instructions (Custom Prompt)

Just below the buttons in Step 1 is a **Report Instructions** box (labeled *User prompt — optional*).

- Type any special guidance for the AI, for example:
  - *"Emphasize program service revenue breakdown."*
  - *"Use accrual basis."*
  - *"Highlight deferred membership dues in the cash flow report."*
- This guidance is applied to **all three reports** and is given **top priority** by the AI.
- Leave it **blank** to use the standard report format.

---

## 8. Step 2 — Stored Reports

After Step 1 succeeds, the three reports are stored automatically:

- **Cash Flow**, **Balance Sheet**, and **Tax Return** appear as status tiles.
- A **green** badge means the report completed successfully.
- These stored reports become the input for the benchmark in Step 3.

You don't need to click anything here — it confirms your reports are ready.

---

## 9. Step 3 — Run Benchmark

Benchmarking compares your AI reports against real reference PDFs to measure accuracy.

1. Under **Select Reference Documents**, either:
   - Click a **fiscal-year set** button (e.g. *FY 2025 (3 docs)*), **or**
   - Pick 1–3 PDFs from the **dropdown list**.
2. Click **▶ Run Benchmark**.
3. Wait for scoring to complete.
4. Open the **Benchmark** tab to see the scores.

> You must select at least one reference document to enable the benchmark. The document list loads automatically when you reach Step 3.

---

## 10. Viewing Your Results

Use the tabs at the top of the main area:

- **Reports tab** — a readable view of each report's content.
- **Benchmark tab** — accuracy scorecards after a benchmark run.
- **Raw JSON tab** — the complete technical output (handy if support asks for it, or to export).

---

## 11. If QuickBooks Asks for Credentials

Sometimes QuickBooks security tokens expire. When that happens, Step 1 shows a **QuickBooks credentials required** box.

1. Open the [Intuit OAuth Playground](https://developer.intuit.com/app/developer/playground) and click **Get Tokens**.
2. Copy these values into the form on the dashboard:
   - **Client ID**
   - **Client Secret**
   - **Refresh Token** (starts with `RT1-`)
   - **Access Token**
3. Click **Save & retry reports**.

The dashboard uses these credentials right away to finish your report run. Any WildApricot data already fetched is reused, so only QuickBooks is retried.

> **Common mistake:** Don't paste the Access Token into the Refresh Token box. The **Refresh Token starts with `RT1-`**; the **Access Token starts with `eyJ`**.

---

## 12. Common Messages & Fixes

| Message / Symptom | What it means | What to do |
|-------------------|---------------|------------|
| *"Please provide the WildApricot Account ID and QuickBooks Realm ID…"* | An ID field is empty | Fill in both numeric IDs in the sidebar |
| *"…must be numeric"* | An ID has letters or spaces | Enter numbers only |
| **HTTP 401 / Unauthorized** | The dashboard can't authenticate with the backend | Ask your administrator to confirm the token and the **API Base URL** |
| **Could not load reference documents** | Same authentication issue | Same as above |
| **QuickBooks credentials required** | QuickBooks tokens expired | Re-enter tokens from the Intuit playground and click *Save & retry reports* |
| **Credentials rejected** | Wrong or already-used token | Get a **fresh** Refresh Token from the playground and try again |
| **A report shows "failed"** | The AI service had a problem | Contact your administrator |
| **It's taking several minutes** | Normal for large jobs | Wait — the spinner means it's still working |
| **Cannot connect** | Backend not reachable | Confirm the **API Base URL** is correct and the service is running |

---

## 13. Glossary

| Term | Meaning |
|------|---------|
| **WildApricot Account ID** | Your organization's numeric ID in WildApricot |
| **QuickBooks Realm ID** | Your company's numeric ID in QuickBooks |
| **Form 990** | The IRS tax return form for nonprofits |
| **Benchmark** | Comparing AI reports against real documents to check accuracy |
| **Reference Document** | A human-prepared PDF (e.g. a filed Form 990) used as the accuracy yardstick |
| **User Prompt** | Optional instructions you give the AI to shape the reports |


---

# Part B — Backend API

A guide for developers and integrators who want to call the backend directly. The backend is a **FastAPI** service; the web dashboard uses these same endpoints behind the scenes.

## 14. API Overview

The API lets you:

- Generate financial reports (Cash Flow, Balance Sheet, Form 990 tax return)
- Benchmark generated reports against reference documents
- Manage QuickBooks OAuth credentials

All request and response bodies are **JSON**.

---

## 15. Base URL

All application routes are prefixed with `/api`.

---

## 16. Interactive Docs (Swagger)

The backend ships with built-in interactive documentation:

```
http://<backend-host>:8000/docs
```

From Swagger UI you can:
- Browse every endpoint and its schema
- Click **Authorize** to set your bearer token
- Use **Try it out** to send live requests

An OpenAPI schema is also available at `http://<backend-host>:8000/openapi.json`.

---

## 17. Authentication

Authentication is controlled by the server's `AUTH_METHOD` setting. In the standard configuration this is **`bearer`**.

Include this header on every request (health endpoints are exempt):

```
Authorization: Bearer <YOUR_BEARER_TOKEN>

BEARER_TOKEN=7hJ&3Yp$2MvQ8nK
```

- The token must match the backend's `BEARER_TOKEN`.
- In Swagger UI, click **Authorize** and paste the token once.
- Other supported modes (set by the administrator): `none`, `api_key` (header `X-API-Key`), and `jwt`.

**Missing/incorrect token → `401 Unauthorized`.**

---

## 18. Conventions

| Item | Rule |
|------|------|
| Content type | `application/json` |
| Dates | `YYYY-MM-DD` (e.g. `2025-01-01`) |
| IDs | `wildapricot_account_id` and `quickbooks_realm_id` must be **numeric strings** |
| Request tracing | Optionally send `X-Request-ID`; it is echoed back in the response |
| Long operations | Report and benchmark calls can take **several minutes**; use generous client timeouts (the dashboard uses 15 minutes) |

---

## 19. Endpoint Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/health` | No | Basic health check |
| GET | `/api/health/live` | No | Liveness probe |
| GET | `/api/health/ready` | No | Readiness probe |
| POST | `/api/reports` | Yes | Generate the three financial reports |
| GET | `/api/benchmark/reports` | Yes | List available reference documents |
| POST | `/api/benchmark` | Yes | Benchmark reports against reference documents |
| POST | `/api/quickbooks/credentials` | Yes | Save & validate QuickBooks OAuth credentials |
| POST | `/api/quickbooks/refresh-token` | Yes | Legacy: submit refresh token only |

---

## 20. Health Endpoints

No authentication required. Useful for uptime checks and orchestration.

### `GET /api/health`

```json
{ "status": "healthy", "service": "document-extraction-api", "version": "2.0.0" }
```

### `GET /api/health/live`

```json
{ "status": "ok" }
```

### `GET /api/health/ready`

Returns `200` with `{"status": "ready", "checks": {...}}` when the app is ready, or `503` with details if a dependency check fails.

---

## 21. Generate Reports — `POST /api/reports`

Generates Cash Flow, Balance Sheet, and Tax Return (Form 990) reports from QuickBooks + WildApricot data.

**Headers**

```
Authorization: Bearer <YOUR_BEARER_TOKEN>
Content-Type: application/json
```

**Request body**

```json
{
  "wildapricot_account_id": "497705",
  "quickbooks_realm_id": "9130356628667026",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "user_prompt": "Emphasize program service revenue and deferred membership dues."
}
```

**Fields**

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `wildapricot_account_id` | Yes | string | Numeric string |
| `quickbooks_realm_id` | Yes | string | Numeric string |
| `start_date` | No | string | `YYYY-MM-DD`; defaults to start of current year |
| `end_date` | No | string | `YYYY-MM-DD`; defaults to today |
| `user_prompt` | No | string | Custom AI guidance applied to all three reports (highest priority) |
| `wildapricot_data` | No | object | Cached WildApricot payload to skip re-fetching |
| `quickbooks_credentials` | No | object | Inline QuickBooks OAuth credentials for this request only (see below) |

**Inline `quickbooks_credentials` object (optional)**

```json
{
  "client_id": "ABC...",
  "client_secret": "xyz...",
  "refresh_token": "RT1-...",
  "access_token": "eyJ...",
  "realm_id": "9130356628667026"
}
```

When provided, these credentials are used **for this request only**, instead of the server's stored QuickBooks settings.

**Response (shape)**

```json
{
  "request_id": "e6b41a47-...",
  "wildapricot_account_id": "497705",
  "quickbooks_realm_id": "9130356628667026",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "reports": {
    "cash_flow":     { "report_type": "cash_flow",     "content": { }, "processing_time": 77.2, "status": "completed", "error_message": null },
    "balance_sheet": { "report_type": "balance_sheet", "content": { }, "processing_time": 58.7, "status": "completed", "error_message": null },
    "tax_return":    { "report_type": "tax_return",    "content": { }, "processing_time": 356.6, "status": "completed", "error_message": null }
  },
  "total_processing_time": 649.6,
  "status": "completed"
}
```

- Report `status` values: `completed`, `partial`, or `failed`.

**Special 401 — QuickBooks refresh needed**

If QuickBooks tokens are invalid, the endpoint returns `401` with a structured detail:

```json
{
  "detail": {
    "error": "quickbooks_refresh_token_required",
    "message": "Please enter a new QuickBooks refresh token.",
    "submit_endpoint": "/api/quickbooks/credentials"
  }
}
```

Resolve it by submitting fresh credentials (see [Section 24](#24-submit-quickbooks-credentials--post-apiquickbookscredentials)) or by passing `quickbooks_credentials` inline.

---

## 22. List Reference Documents — `GET /api/benchmark/reports`

Lists the reference PDFs available for benchmarking. Use the returned `file_name` values in `selected_document_files` when running a benchmark.

**Query parameters**

| Param | Required | Notes |
|-------|----------|-------|
| `doc_type` | No | Filter by `form_990`, `cash_flow`, or `financial_position` |

**Response**

```json
{
  "documents": [
    {
      "file_name": "KANSAS CITY WOODWORKERS GUILD INC_Form990 2025 filed 04192025.pdf",
      "doc_type": "form_990",
      "fiscal_year": 2025,
      "start_date": "2025-01-01",
      "end_date": "2025-12-31"
    }
  ],
  "total": 1
}
```

---

## 23. Run Benchmark — `POST /api/benchmark`

Compares generated reports against reference documents and returns accuracy scores.

**Request body**

```json
{
  "wildapricot_account_id": "497705",
  "quickbooks_realm_id": "9130356628667026",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "reports": {
    "cash_flow":  { "content": { } },
    "tax_return": { "content": { } }
  },
  "selected_document_files": [
    "KANSAS CITY WOODWORKERS GUILD INC_Form990 2025 filed 04192025.pdf"
  ]
}
```

**Fields**

| Field | Required | Notes |
|-------|----------|-------|
| `reports` | Yes | Must include `cash_flow` and `tax_return`, each with non-empty `content` |
| `wildapricot_account_id`, `quickbooks_realm_id`, `start_date`, `end_date` | Yes | Metadata from the reports run |
| `years` | No | Fiscal years to benchmark; derived from dates if omitted |
| `selected_document_files` | No | Up to 3 reference file names from `GET /api/benchmark/reports`; omit to use all available |

**Response (shape)**

```json
{
  "request_id": "…",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "years_benchmarked": [2025],
  "results": { },
  "overall_match_score": 0.0,
  "total_processing_time": 0.0,
  "status": "completed"
}
```

---

## 24. Submit QuickBooks Credentials — `POST /api/quickbooks/credentials`

Saves and validates full QuickBooks OAuth credentials, then stores the rotated tokens. The backend also auto-refreshes access tokens (~every 50 minutes), so this is usually only needed when tokens expire.

**Request body**

```json
{
  "client_id": "ABC...",
  "client_secret": "xyz...",
  "refresh_token": "RT1-...",
  "access_token": "eyJ...",
  "realm_id": "9130356628667026"
}
```

**Fields**

| Field | Required | Notes |
|-------|----------|-------|
| `client_id` | Yes | Min length 5 |
| `client_secret` | Yes | Min length 5 |
| `refresh_token` | Yes | Starts with `RT1-`; min length 10 |
| `access_token` | No | Starts with `eyJ`; recommended |
| `realm_id` | No | QuickBooks company ID |

**Success response**

```json
{
  "status": "ok",
  "message": "QuickBooks credentials saved and validated successfully.",
  "notify": "..."
}
```

**Failure response (`401`)**

```json
{
  "detail": {
    "error": "quickbooks_refresh_token_invalid",
    "message": "Intuit rejected the token. Paste the new refresh_token…",
    "notify": "..."
  }
}
```

> **Tip:** Get fresh tokens from the [Intuit OAuth Playground](https://developer.intuit.com/app/developer/playground) → **Get Tokens**. Do not swap the refresh and access tokens: refresh starts with `RT1-`, access starts with `eyJ`.

---

## 25. Submit Refresh Token (Legacy) — `POST /api/quickbooks/refresh-token`

Submits only a refresh token, using the Client ID/Secret already configured on the server.

**Request body**

```json
{ "refresh_token": "RT1-..." }
```

Prefer `POST /api/quickbooks/credentials` for new integrations. This endpoint returns `400` if the server has no `QUICKBOOKS_CLIENT_ID` / `QUICKBOOKS_CLIENT_SECRET` configured.

---

## 26. Error Handling

| Status | Meaning | Typical cause |
|--------|---------|---------------|
| `400` | Bad request | Invalid `doc_type` or malformed request |
| `401` | Unauthorized | Missing/incorrect bearer token, or QuickBooks token expired |
| `422` | Validation error | Missing/non-numeric IDs, wrong date format, missing required fields |
| `429` | Too many requests | Rate limit exceeded (if enabled) |
| `500` | Server error | Unexpected failure (check `error_message` / logs) |
| `503` | Not ready / draining | App starting up, shutting down, or a dependency check failed |

**Validation error example (`422`)**

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "wildapricot_account_id"],
      "msg": "Value error, wildapricot_account_id must be numeric, got ''"
    }
  ]
}
```

---

## 27. Rate Limiting

- Rate limiting is optional and controlled by the server (`RATE_LIMIT_ENABLED`, `RATE_LIMIT_PER_MINUTE`).
- When enabled and exceeded, the API returns `429 Too Many Requests`.
- Requests are keyed by API key (in `api_key` mode) or client IP.

---
---

*AccountBridge vCFO — built with GoML.io. For interactive API exploration*

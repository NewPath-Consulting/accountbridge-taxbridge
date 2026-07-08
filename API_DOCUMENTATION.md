# Backend API Documentation

REST API for the report generation and benchmark service. Generate nonprofit financial reports from QuickBooks and WildApricot, benchmark them against reference documents, and manage QuickBooks OAuth credentials.

The web dashboard calls these same endpoints. Interactive OpenAPI docs are also available at `/docs`.

---

## Table of Contents

- [Base URL](#base-url)
- [Interactive Docs](#interactive-docs)
- [Authentication](#authentication)
- [Conventions](#conventions)
- [Endpoint Summary](#endpoint-summary)
- [Health](#health)
- [Reports](#reports)
- [Benchmark](#benchmark)
- [QuickBooks](#quickbooks)
- [Error Handling](#error-handling)
- [Rate Limiting](#rate-limiting)
- [Typical Workflows](#typical-workflows)

---

## Base URL

```
http://<host>:8000
```

All application routes are under `/api`.

| Environment | Example |
|-------------|---------|
| Local | `http://localhost:8000` |
| Docker / deployed | Use your configured host and port |

---

## Interactive Docs

| Resource | URL |
|----------|-----|
| Swagger UI | `http://<host>:8000/docs` |
| OpenAPI schema | `http://<host>:8000/openapi.json` |

In Swagger UI, click **Authorize**, enter your bearer token once, then use **Try it out** on any endpoint.

---

## Authentication

Auth mode is set by `AUTH_METHOD` on the server (`none` | `bearer` | `api_key` | `jwt`). The usual production setting is **`bearer`**.

### Bearer token (`AUTH_METHOD=bearer`)

Send on every authenticated request:

```http
Authorization: Bearer <YOUR_BEARER_TOKEN>
```

The token must match `BEARER_TOKEN` in the server environment. Health endpoints do not require auth.

### API key (`AUTH_METHOD=api_key`)

```http
X-API-Key: <YOUR_API_KEY>
```

Keys are taken from `API_KEY` and/or the comma-separated `API_KEYS` list.

### None (`AUTH_METHOD=none`)

No credentials required. Suitable for local development only.

**Missing or invalid credentials → `401 Unauthorized`.**

---

## Conventions

| Item | Rule |
|------|------|
| Content type | `application/json` |
| Dates | `YYYY-MM-DD` (e.g. `2025-01-01`) |
| Account IDs | `wildapricot_account_id` and `quickbooks_realm_id` must be **numeric strings** |
| Request tracing | Optional `X-Request-ID` header; echoed on the response |
| Timeouts | Report and benchmark calls can take **several minutes**; use a client timeout of at least 15 minutes |
| CORS | `GET`, `OPTIONS`, `POST`, `PUT`, `DELETE` are allowed |

---

## Endpoint Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/health` | No | Basic health check |
| `GET` | `/api/health/live` | No | Liveness probe |
| `GET` | `/api/health/ready` | No | Readiness probe |
| `POST` | `/api/reports` | Yes | Generate Cash Flow, Balance Sheet, and Form 990 reports |
| `GET` | `/api/benchmark/reports` | Yes | List available reference documents |
| `POST` | `/api/benchmark` | Yes | Benchmark reports against reference documents |
| `POST` | `/api/quickbooks/credentials` | Yes | Save and validate QuickBooks OAuth credentials |
| `POST` | `/api/quickbooks/refresh-token` | Yes | Legacy: submit refresh token only |

---

## Health

No authentication required. Use these for uptime checks and orchestration.

### `GET /api/health`

Basic liveness alias.

**Response `200`**

```json
{
  "status": "healthy",
  "service": "document-extraction-api",
  "version": "2.0.0"
}
```

### `GET /api/health/live`

Process is up. No dependency checks.

**Response `200`**

```json
{ "status": "ok" }
```

### `GET /api/health/ready`

App is ready to accept traffic. Optionally checks extractor config, S3 (`HEALTH_CHECK_S3`), and Bedrock (`HEALTH_CHECK_BEDROCK`).

**Response `200`**

```json
{
  "status": "ready",
  "checks": {
    "config": "ok",
    "extractor": "ok"
  }
}
```

**Response `503`** when a required check fails:

```json
{
  "detail": {
    "status": "not_ready",
    "checks": { "config": "ok", "extractor": "…" },
    "failed": ["extractor"]
  }
}
```

---

## Reports

Generate Cash Flow, Balance Sheet, and Tax Return (Form 990) reports from QuickBooks and WildApricot data.

### `POST /api/reports`

**Headers**

```http
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

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `wildapricot_account_id` | Yes | string | Numeric string |
| `quickbooks_realm_id` | Yes | string | Numeric string |
| `start_date` | No | string | `YYYY-MM-DD`; defaults to start of current year |
| `end_date` | No | string | `YYYY-MM-DD`; defaults to today |
| `user_prompt` | No | string | Custom AI guidance applied across all three reports |
| `wildapricot_data` | No | object | Cached WildApricot payload to skip re-fetching |
| `quickbooks_credentials` | No | object | Per-request QuickBooks OAuth credentials (see below) |

**Inline `quickbooks_credentials` (optional)**

```json
{
  "client_id": "ABC...",
  "client_secret": "xyz...",
  "refresh_token": "RT1-...",
  "access_token": "eyJ...",
  "realm_id": "9130356628667026"
}
```

When provided, these credentials are used for this request only instead of server-stored QuickBooks settings.

**Response `200` (shape)**

```json
{
  "request_id": "e6b41a47-...",
  "wildapricot_account_id": "497705",
  "quickbooks_realm_id": "9130356628667026",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "reports": {
    "cash_flow": {
      "report_type": "cash_flow",
      "content": {},
      "processing_time": 77.2,
      "status": "completed",
      "error_message": null
    },
    "balance_sheet": {
      "report_type": "balance_sheet",
      "content": {},
      "processing_time": 58.7,
      "status": "completed",
      "error_message": null
    },
    "tax_return": {
      "report_type": "tax_return",
      "content": {},
      "processing_time": 356.6,
      "status": "completed",
      "error_message": null
    }
  },
  "total_processing_time": 649.6,
  "status": "completed"
}
```

Per-report `status` values: `completed`, `partial`, or `failed`.

**cURL**

```bash
curl -X POST "http://localhost:8000/api/reports" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "wildapricot_account_id": "497705",
    "quickbooks_realm_id": "9130356628667026",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31"
  }'
```

**Special `401` — QuickBooks refresh required**

```json
{
  "detail": {
    "error": "quickbooks_refresh_token_required",
    "message": "Please enter a new QuickBooks refresh token.",
    "submit_endpoint": "/api/quickbooks/credentials",
    "notify": "…"
  }
}
```

Resolve by calling `POST /api/quickbooks/credentials`, or by passing `quickbooks_credentials` inline on the next `/api/reports` call. The detail may also include `wildapricot_data` when that payload was already fetched, so the client can retry without re-calling WildApricot.

---

## Benchmark

Compare generated reports against reference PDFs and return match scores with explanations.

### `GET /api/benchmark/reports`

List reference documents available for selection. Pass returned `file_name` values in `selected_document_files` when running a benchmark.

**Query parameters**

| Param | Required | Notes |
|-------|----------|-------|
| `doc_type` | No | `form_990`, `cash_flow`, or `financial_position` |

**Response `200`**

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

**Response `400`** for an invalid `doc_type`.

### `POST /api/benchmark`

Compares `cash_flow` and `tax_return` report content against reference documents.

**Request body**

```json
{
  "wildapricot_account_id": "497705",
  "quickbooks_realm_id": "9130356628667026",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "reports": {
    "cash_flow": { "content": {} },
    "tax_return": { "content": {} }
  },
  "selected_document_files": [
    "KANSAS CITY WOODWORKERS GUILD INC_Form990 2025 filed 04192025.pdf"
  ]
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `reports` | Yes | Must include `cash_flow` and `tax_return`, each with non-empty `content` |
| `wildapricot_account_id`, `quickbooks_realm_id`, `start_date`, `end_date` | Yes | Metadata from the reports run |
| `years` | No | Fiscal years to benchmark; derived from dates if omitted |
| `selected_document_files` | No | Up to 3 file names from `GET /api/benchmark/reports`; omit to use all available |

**Response `200` (shape)**

```json
{
  "request_id": "…",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "wildapricot_account_id": "497705",
  "quickbooks_realm_id": "9130356628667026",
  "years_benchmarked": [2025],
  "year_resolution_note": null,
  "results": {},
  "overall_match_score": 0.0,
  "total_processing_time": 0.0,
  "status": "completed"
}
```

**cURL**

```bash
curl -X POST "http://localhost:8000/api/benchmark" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "wildapricot_account_id": "497705",
    "quickbooks_realm_id": "9130356628667026",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "reports": {
      "cash_flow": { "content": {} },
      "tax_return": { "content": {} }
    },
    "selected_document_files": ["example_Form990.pdf"]
  }'
```

---

## QuickBooks

Save and validate OAuth credentials. The backend also refreshes access tokens automatically (~every 50 minutes), so these endpoints are mainly needed when tokens expire or when onboarding a new company.

> Get fresh tokens from the [Intuit OAuth Playground](https://developer.intuit.com/app/developer/playground) → **Get Tokens**. Refresh tokens start with `RT1-`; access tokens start with `eyJ`. Do not swap them.

### `POST /api/quickbooks/credentials`

Save and validate full QuickBooks OAuth credentials, then store rotated tokens.

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

| Field | Required | Notes |
|-------|----------|-------|
| `client_id` | Yes | Min length 5 |
| `client_secret` | Yes | Min length 5 |
| `refresh_token` | Yes | Starts with `RT1-`; min length 10 |
| `access_token` | No | Starts with `eyJ`; recommended |
| `realm_id` | No | QuickBooks company ID |

**Response `200`**

```json
{
  "status": "ok",
  "message": "QuickBooks credentials saved and validated successfully.",
  "notify": "…"
}
```

**Response `401`**

```json
{
  "detail": {
    "error": "quickbooks_refresh_token_invalid",
    "message": "Intuit rejected the token. Paste the new refresh_token…",
    "notify": "…"
  }
}
```

### `POST /api/quickbooks/refresh-token`

Legacy endpoint: submit only a refresh token, using Client ID / Secret already configured on the server.

**Request body**

```json
{
  "refresh_token": "RT1-..."
}
```

Prefer `POST /api/quickbooks/credentials` for new integrations. Returns `400` if `QUICKBOOKS_CLIENT_ID` / `QUICKBOOKS_CLIENT_SECRET` are not configured.

---

## Error Handling

| Status | Meaning | Typical cause |
|--------|---------|---------------|
| `400` | Bad request | Invalid `doc_type` or malformed request |
| `401` | Unauthorized | Missing/incorrect auth, QuickBooks/WildApricot token issues |
| `422` | Validation error | Missing/non-numeric IDs, wrong date format, missing required fields |
| `429` | Too many requests | Rate limit exceeded |
| `500` | Server error | Unexpected failure |
| `503` | Not ready / draining | App starting up, shutting down, or a readiness check failed |

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

When the server is draining during shutdown, authenticated traffic may receive `503` with `Retry-After: 30`.

---

## Rate Limiting

- Controlled by `RATE_LIMIT_ENABLED` and `RATE_LIMIT_PER_MINUTE`.
- When enabled and exceeded, the API returns `429 Too Many Requests`.
- Requests are keyed by API key (in `api_key` mode) or by client IP.

---

## Typical Workflows

### Generate reports, then benchmark

```text
1. POST /api/reports
2. GET  /api/benchmark/reports?doc_type=form_990
3. POST /api/benchmark   (pass report content from step 1)
```

### Recover from expired QuickBooks tokens

```text
1. POST /api/reports  → 401 quickbooks_refresh_token_required
2. POST /api/quickbooks/credentials
3. POST /api/reports again
   (optional: reuse wildapricot_data from the 401 detail)
```

---

For project setup, configuration, and deployment, see the main [README.md](./README.md). For a end-user walkthrough of the dashboard, see [USER_MANUAL.md](./USER_MANUAL.md).

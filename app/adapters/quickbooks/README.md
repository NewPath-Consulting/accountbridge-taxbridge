# QuickBooks Integration

This module provides integration with QuickBooks Sandbox API for fetching financial reports.

## Features

- Fetch Profit and Loss reports
- Fetch Balance Sheet reports
- Automatic file saving to local storage
- Async/await support
- Automatic OAuth access token refresh (60-minute expiry; proactive refresh before expiry)
- Client-side rate limiting and 429 retry handling
- Comprehensive error handling and logging
- Realm ID configuration from environment variables

## Setup

### 1. Environment Variables

Add the following to your `.env` file:

```bash
QUICKBOOKS_CLIENT_ID=your-client-id
QUICKBOOKS_CLIENT_SECRET=your-client-secret
QUICKBOOKS_ACCESS_TOKEN=your-access-token
QUICKBOOKS_REFRESH_TOKEN=your-refresh-token
QUICKBOOKS_REALM_ID=9341457191103538
QUICKBOOKS_SANDBOX_BASE_URL=https://sandbox-quickbooks.api.intuit.com
QUICKBOOKS_OUTPUT_DIR=data/quickbooks
# Optional tuning (defaults shown)
QUICKBOOKS_OAUTH_URL=https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer
QUICKBOOKS_TOKEN_REFRESH_BUFFER_SECONDS=300
QUICKBOOKS_MAX_REQUESTS_PER_MINUTE=90
```

`QUICKBOOKS_ACCESS_TOKEN` is optional seed data; the client refreshes automatically via
`QUICKBOOKS_REFRESH_TOKEN` using the Intuit OAuth token endpoint. Access tokens expire
after 60 minutes.

### 2. Install Dependencies

Uses `httpx` (already in project requirements).

## Quick Test

Run the test script from the project root:

```bash
# From accountbridge-internal-dev directory
python test_quickbooks.py

# Or use the batch script
run_quickbooks_test.bat

# Or PowerShell script
.\run_quickbooks_test.ps1
```

See `QUICKBOOKS_TEST_README.md` for detailed testing instructions.

## Usage

### Basic Example

```python
import asyncio
from app.adapters.quickbooks import QuickBooksClient
from app.config.settings import settings

async def fetch_reports():
    client = QuickBooksClient()
    
    # Fetch Profit and Loss (realm_id from settings)
    profit_loss = await client.get_profit_and_loss(
        realm_id=settings.QUICKBOOKS_REALM_ID,
        start_date="2024-01-01",
        end_date="2024-12-31"
    )
    
    # Fetch Balance Sheet (realm_id from settings)
    balance_sheet = await client.get_balance_sheet(
        realm_id=settings.QUICKBOOKS_REALM_ID,
        start_date="2024-01-01",
        end_date="2024-12-31"
    )
    
    return profit_loss, balance_sheet

# Run
asyncio.run(fetch_reports())
```

### Custom Realm ID

You can override the realm_id from settings:

```python
client = QuickBooksClient()

# Use a different realm_id
profit_loss = await client.get_profit_and_loss(
    realm_id="1234567890",
    start_date="2024-01-01",
    end_date="2024-12-31"
)
```

## API Methods

### `get_profit_and_loss(realm_id, start_date, end_date)`

Fetches the Profit and Loss report.

**Parameters:**
- `realm_id` (str): QuickBooks company/realm ID
- `start_date` (str): Start date in YYYY-MM-DD format
- `end_date` (str): End date in YYYY-MM-DD format

**Returns:**
- `Dict[str, Any]`: Parsed JSON response

**Saves to:**
- `data/quickbooks/profit-and-loss.json`

### `get_balance_sheet(realm_id, start_date, end_date)`

Fetches the Balance Sheet report.

**Parameters:**
- `realm_id` (str): QuickBooks company/realm ID
- `start_date` (str): Start date in YYYY-MM-DD format
- `end_date` (str): End date in YYYY-MM-DD format

**Returns:**
- `Dict[str, Any]`: Parsed JSON response

**Saves to:**
- `data/quickbooks/balance-sheet.json`

## API Details

### Supported Report Endpoints

The client uses **only** these QuickBooks report APIs:

| Report | HTTP |
|--------|------|
| Balance Sheet | `GET /v3/company/{realmId}/reports/BalanceSheet` |
| Profit and Loss | `GET /v3/company/{realmId}/reports/ProfitAndLoss` |

No other report types (Cash Flow, Trial Balance, etc.) are called by the reports pipeline.

### Endpoint Format

```
GET https://sandbox-quickbooks.api.intuit.com/v3/company/{realmId}/reports/{ReportName}
```

### Query Parameters

- `start_date`: Start date (YYYY-MM-DD)
- `end_date`: End date (YYYY-MM-DD)
- `accounting_method`: Accrual
- `minorversion`: 75

The optional `customer` filter shown in some Intuit examples is **not** used by this client.

### Headers

```
Authorization: Bearer {access_token}
Accept: application/json
Content-Type: application/json
```

## Error Handling

The client includes comprehensive error handling:

- **HTTP errors**: Logs status code and message
- **Network errors**: Handles connection issues
- **Unexpected errors**: Catches and logs all exceptions

All errors are logged using Python's logging module.

## File Output

Reports are automatically saved to the directory specified in `QUICKBOOKS_OUTPUT_DIR` (default: `data/quickbooks/`).

The directory is created automatically if it doesn't exist.

Output files:
- `profit-and-loss.json`: Profit and Loss report
- `balance-sheet.json`: Balance Sheet report

## Logging

The module uses Python's standard logging. Example log messages:

```
INFO - Fetching ProfitAndLoss report for realm 9341457191103538 from 2024-01-01 to 2024-12-31
INFO - Successfully fetched ProfitAndLoss report. Saved to data/quickbooks/profit-and-loss.json
ERROR - Failed to fetch ProfitAndLoss report: HTTP 401 - Unauthorized
```

## Configuration

The client reads all configuration from environment variables via `app/config/settings.py`:

```python
from app.config.settings import settings

# Access configuration
client_id = settings.QUICKBOOKS_CLIENT_ID
realm_id = settings.QUICKBOOKS_REALM_ID
base_url = settings.QUICKBOOKS_SANDBOX_BASE_URL
output_dir = settings.QUICKBOOKS_OUTPUT_DIR
```

## Security Notes

- Never commit `.env` file to version control
- Store credentials securely (use AWS Secrets Manager in production)
- Access tokens expire after 60 minutes; the client refreshes them automatically
- Intuit rotates refresh tokens on each refresh — update `QUICKBOOKS_REFRESH_TOKEN` in
  `.env` if you persist tokens outside the running process
- Use the sandbox environment for testing

## References

- [QuickBooks API Documentation](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account)
- [QuickBooks Reports API](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/report-entities)
- [OAuth 2.0 Guide](https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/oauth-2.0)

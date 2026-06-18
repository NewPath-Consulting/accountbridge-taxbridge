"""
QuickBooks OAuth one-time setup helper.

Standard flow (POC):
  1. developer.intuit.com → your app → Keys & OAuth
  2. Add redirect URI: https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl
  3. OAuth 2.0 Playground → select your app → scope: com.intuit.quickbooks.accounting
  4. Get Authorization Code → Exchange for tokens
  5. Save refresh_token to .env — the app automates access tokens from there
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv, set_key

load_dotenv()

CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")
OAUTH_URL = os.getenv(
    "QUICKBOOKS_OAUTH_URL",
    "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
)
REDIRECT_URI = os.getenv(
    "QUICKBOOKS_REDIRECT_URI",
    "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl",
)
PLAYGROUND_URL = "https://developer.intuit.com/app/developer/playground"


def get_basic_auth_header() -> str:
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded = base64.standard_b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def _token_field(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def exchange_auth_code(auth_code: str, redirect_uri: str) -> dict | None:
    """Exchange a one-time authorization code for access + refresh tokens."""
    print("\nExchanging authorization code for tokens...")

    headers = {
        "Authorization": get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {
        "grant_type": "authorization_code",
        "code": auth_code.strip(),
        "redirect_uri": redirect_uri,
    }

    try:
        with httpx.Client(timeout=60.0, verify=False) as client:
            response = client.post(OAUTH_URL, data=data, headers=headers)

        if response.status_code == 200:
            return response.json()

        print(f"Error: {response.status_code}")
        print(f"Response: {response.text}")
        return None
    except Exception as exc:
        print(f"Request failed: {exc}")
        return None


def refresh_access_token(refresh_token: str) -> dict | None:
    """Refresh access token using the stored refresh token (automated app flow)."""
    print("\nTesting refresh_token grant...")

    headers = {
        "Authorization": get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
    }

    try:
        with httpx.Client(timeout=60.0, verify=False) as client:
            response = client.post(OAUTH_URL, data=data, headers=headers)

        if response.status_code == 200:
            print("Refresh token grant succeeded.")
            return response.json()

        error_data = response.json() if response.text else {}
        print(f"Refresh failed: {response.status_code}")
        print(f"Error: {error_data.get('error_description', response.text)}")
        return None
    except Exception as exc:
        print(f"Request failed: {exc}")
        return None


def save_tokens_to_env(access_token: str, refresh_token: str, realm_id: str = "") -> bool:
    """Persist tokens to .env (refresh_token is the long-lived credential)."""
    env_path = Path(".env")

    try:
        set_key(env_path, "QUICKBOOKS_ACCESS_TOKEN", access_token)
        set_key(env_path, "QUICKBOOKS_REFRESH_TOKEN", refresh_token)
        set_key(env_path, "QUICKBOOKS_AUTH_CODE", "")
        set_key(env_path, "QUICKBOOKS_REDIRECT_URI", REDIRECT_URI)
        if realm_id:
            set_key(env_path, "QUICKBOOKS_REALM_ID", realm_id)
        print("\nTokens saved to .env")
        print("  QUICKBOOKS_REFRESH_TOKEN  <- golden ticket (keep this)")
        print("  QUICKBOOKS_ACCESS_TOKEN   <- auto-refreshed by the app")
        return True
    except Exception as exc:
        print(f"\nFailed to save tokens: {exc}")
        print("\nManually add to .env:")
        print(f"QUICKBOOKS_REFRESH_TOKEN={refresh_token}")
        print(f"QUICKBOOKS_ACCESS_TOKEN={access_token}")
        return False


def print_playground_instructions() -> None:
    print("\n" + "=" * 70)
    print("ONE-TIME OAUTH PLAYGROUND SETUP")
    print("=" * 70)
    print("\n1. Open:", PLAYGROUND_URL)
    print("2. Select YOUR app credentials (must match QUICKBOOKS_CLIENT_ID in .env)")
    print(f"   Client ID prefix: {CLIENT_ID[:12]}...")
    print("3. Scope: com.intuit.quickbooks.accounting")
    print("4. Click 'Get Authorization Code' → sign in → grant consent")
    print("5. Click 'Get Tokens' (or copy the authorization code)")
    print(f"6. Redirect URI: {REDIRECT_URI}")
    print("\nThen paste the authorization code below (valid ~5 minutes, single use).")


def main() -> None:
    print("=" * 70)
    print("QUICKBOOKS OAUTH SETUP")
    print("=" * 70)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\nMissing QUICKBOOKS_CLIENT_ID / QUICKBOOKS_CLIENT_SECRET in .env")
        return

    print(f"\nClient ID: {CLIENT_ID[:20]}...")

    print("\n" + "=" * 70)
    print("OPTIONS")
    print("=" * 70)
    print("\n1. One-time setup via OAuth playground (recommended)")
    print("2. Test existing refresh_token from .env")
    print("3. Manual token entry")

    choice = input("\nEnter choice (1/2/3) [1]: ").strip() or "1"

    if choice == "1":
        print_playground_instructions()
        auth_code = input("\nPaste authorization code: ").strip()
        if not auth_code:
            print("No code provided.")
            return

        tokens = exchange_auth_code(auth_code, REDIRECT_URI)
        if not tokens:
            return

        access_token = _token_field(tokens, "access_token", "accessToken")
        refresh_token = _token_field(tokens, "refresh_token", "refreshToken")
        if not refresh_token:
            print("No refresh_token in response — cannot automate.")
            return

        realm_id = input(
            "\nSandbox company ID / realm ID (from playground, optional): "
        ).strip()

        save_tokens_to_env(access_token, refresh_token, realm_id)
        print("\nSetup complete. The app will auto-refresh access tokens using your refresh_token.")

    elif choice == "2":
        current_refresh = os.getenv("QUICKBOOKS_REFRESH_TOKEN", "").strip()
        if not current_refresh:
            print("\nNo QUICKBOOKS_REFRESH_TOKEN in .env — run option 1 first.")
            return

        tokens = refresh_access_token(current_refresh)
        if tokens:
            save_tokens_to_env(
                _token_field(tokens, "access_token", "accessToken"),
                _token_field(tokens, "refresh_token", "refreshToken") or current_refresh,
            )

    elif choice == "3":
        print("\nPaste tokens from the OAuth playground response:")
        access_token = input("Access Token: ").strip()
        refresh_token = input("Refresh Token: ").strip()
        realm_id = input("Realm ID (optional): ").strip()
        if access_token and refresh_token:
            save_tokens_to_env(access_token, refresh_token, realm_id)
        else:
            print("Both tokens are required.")

    else:
        print("Invalid choice.")

    print("\n" + "=" * 70)
    print("Next: restart the server and call POST /api/reports")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

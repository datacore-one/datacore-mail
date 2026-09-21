#!/usr/bin/env python3
"""
Gmail Authorization Script with Delete Permission.

Run this script to authorize Gmail access with full permissions including delete.
A browser window will open for Google OAuth.

Usage:
    python authorize_gmail.py user@organization.example.com
"""

import os
import sys
import pickle
import hashlib
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Full access scope (includes delete)
SCOPES = [
    'https://mail.google.com/',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
]

CREDS_DIR = Path(__file__).parent.parent.parent / "env" / "credentials"
CLIENT_SECRETS_FILE = CREDS_DIR / "google_calendar_client_secret.json"


def authorize(email: str):
    """Authorize Gmail access for an email account."""

    email_hash = hashlib.md5(email.encode()).hexdigest()[:8]
    token_path = CREDS_DIR / f"gmail_token_{email_hash}.pickle"

    print(f"Authorizing: {email}")
    print(f"Token path: {token_path}")
    print(f"Scopes: {SCOPES}")
    print()

    # Check for existing token
    creds = None
    if token_path.exists():
        print("Found existing token, checking validity...")
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)

        # Check if scopes match
        if creds.scopes != set(SCOPES) and set(SCOPES) != set(creds.scopes or []):
            print("Scopes changed, need re-authorization")
            creds = None

    # Refresh or get new credentials
    if creds and creds.valid:
        print("Token is valid!")
    elif creds and creds.expired and creds.refresh_token:
        print("Token expired, refreshing...")
        try:
            creds.refresh(Request())
            print("Token refreshed!")
        except Exception as e:
            print(f"Refresh failed: {e}")
            creds = None

    if not creds:
        print()
        print("Opening browser for authorization...")
        print("Please sign in with: " + email)
        print()

        if not CLIENT_SECRETS_FILE.exists():
            print(f"ERROR: Client secrets file not found: {CLIENT_SECRETS_FILE}")
            return False

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE),
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        # Save token
        with open(token_path, 'wb') as f:
            pickle.dump(creds, f)
        print(f"Token saved to: {token_path}")

    # Verify
    print()
    print("Authorized scopes:")
    for scope in (creds.scopes or []):
        print(f"  - {scope}")

    if 'https://mail.google.com/' in (creds.scopes or []):
        print()
        print("✓ DELETE PERMISSION GRANTED")
        return True
    else:
        print()
        print("✗ Delete permission not granted")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python authorize_gmail.py <email>")
        print("Example: python authorize_gmail.py user@organization.example.com")
        sys.exit(1)

    email = sys.argv[1]
    success = authorize(email)
    sys.exit(0 if success else 1)

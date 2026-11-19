"""One-time local setup: sign in with the channel's Google account and print GitHub secrets.

Usage:
    python auth_setup.py path\\to\\client_secret.json
"""
from __future__ import annotations

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from autopost.auth import SCOPES


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    flow = InstalledAppFlow.from_client_secrets_file(argv[1], scopes=SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Remove the app at https://myaccount.google.com/permissions and retry.")
        return 1
    print("\nAdd these as GitHub repository secrets (Settings > Secrets and variables > Actions):\n")
    print(f"GOOGLE_CLIENT_ID={creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

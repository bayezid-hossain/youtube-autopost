"""Google OAuth credentials built from environment variables (GitHub secrets)."""
from __future__ import annotations

import os
from typing import Mapping, Optional

from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/drive",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"
REQUIRED = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")


class MissingSecret(RuntimeError):
    """A required environment variable is not set."""


def credentials_from_env(env: Optional[Mapping[str, str]] = None) -> Credentials:
    env = os.environ if env is None else env
    missing = [key for key in REQUIRED if not env.get(key)]
    if missing:
        raise MissingSecret("missing environment variables: " + ", ".join(missing))
    return Credentials(
        token=None,
        refresh_token=env["GOOGLE_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=env["GOOGLE_CLIENT_ID"],
        client_secret=env["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )

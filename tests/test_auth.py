import pytest

from autopost.auth import SCOPES, MissingSecret, credentials_from_env

ENV = {
    "GOOGLE_CLIENT_ID": "cid",
    "GOOGLE_CLIENT_SECRET": "secret",
    "GOOGLE_REFRESH_TOKEN": "refresh",
}


def test_builds_credentials_from_env():
    creds = credentials_from_env(ENV)
    assert creds.client_id == "cid"
    assert creds.client_secret == "secret"
    assert creds.refresh_token == "refresh"
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert list(creds.scopes) == SCOPES


def test_missing_vars_listed():
    with pytest.raises(MissingSecret, match="GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN"):
        credentials_from_env({"GOOGLE_CLIENT_ID": "cid"})

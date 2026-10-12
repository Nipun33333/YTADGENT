"""Validate YouTube OAuth credentials before spending time on video generation.

GitHub Actions must provide YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET,
and YOUTUBE_REFRESH_TOKEN via encrypted repository secrets.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path

import config

TOKEN_PATH = Path(config.PROJECT_ROOT) / "youtube_token.pickle"
REQUIRED_SECRETS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


def validate_and_store_oauth(
    *,
    environ=None,
    credentials_class=None,
    request_factory=None,
    token_path=None,
):
    """Actually exchange the refresh token; merely pickling it proves nothing.

    Dependency injection permits fully offline unit tests. Failures are
    intentionally sanitized to avoid including secret strings in CI logs.
    """
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_SECRETS if not str(env.get(name, "")).strip()]
    if missing:
        raise RuntimeError(
            "YouTube OAuth configuration missing GitHub Secrets: " + ", ".join(missing)
        )

    if credentials_class is None:
        from google.oauth2.credentials import Credentials
        credentials_class = Credentials
    if request_factory is None:
        from google.auth.transport.requests import Request
        request_factory = Request

    credentials = credentials_class(
        token=None,
        refresh_token=env["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env["YOUTUBE_CLIENT_ID"],
        client_secret=env["YOUTUBE_CLIENT_SECRET"],
        scopes=config.YOUTUBE_SCOPES,
    )

    try:
        credentials.refresh(request_factory())
    except Exception as exc:
        detail = str(exc).lower()
        if "invalid_grant" in detail or "revoked" in detail or "expired" in detail:
            raise RuntimeError(
                "YouTube OAuth invalid_grant: refresh token expired or revoked. "
                "In Google Cloud, check OAuth Audience > Publishing status; "
                "External + Testing tokens generally expire after 7 days. "
                "Reauthorize with the matching OAuth client, then replace the "
                "YOUTUBE_REFRESH_TOKEN GitHub Actions secret."
            ) from None
        raise RuntimeError(
            "YouTube OAuth token refresh failed before video generation. "
            "Check the OAuth client configuration, Google API availability, "
            "and the encrypted GitHub Secrets; see the Actions error for context."
        ) from None

    if not credentials.valid or not credentials.token:
        raise RuntimeError(
            "YouTube OAuth did not return a usable access token. "
            "Reauthorize and replace the GitHub refresh-token secret."
        )

    path = Path(token_path) if token_path is not None else TOKEN_PATH
    with path.open("wb") as file:
        pickle.dump(credentials, file)

    print("   ✅ YouTube OAuth refresh token verified; valid access token saved.")
    return credentials


if __name__ == "__main__":
    validate_and_store_oauth()

"""Validate YouTube OAuth credentials before spending time on video generation.

GitHub Actions must provide YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET,
and YOUTUBE_REFRESH_TOKEN via encrypted repository secrets.
"""
from __future__ import annotations

import os
import pickle
import re
from pathlib import Path

import config

TOKEN_PATH = Path(config.PROJECT_ROOT) / "youtube_token.pickle"
REQUIRED_SECRETS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


# Google's documented OAuth error codes. Only the code (never the response
# text, which could echo request values) is printed, so CI logs stay secret-safe
# while still saying which credential is wrong.
_OAUTH_ERROR_HINTS = {
    "invalid_client": (
        "YOUTUBE_CLIENT_SECRET does not belong to YOUTUBE_CLIENT_ID (or that OAuth "
        "client no longer exists). Copy BOTH values from the same OAuth Desktop "
        "client in Google Cloud > Google Auth Platform > Clients."
    ),
    "unauthorized_client": (
        "YOUTUBE_REFRESH_TOKEN was issued to a different OAuth client than "
        "YOUTUBE_CLIENT_ID. Run renew_youtube_token.py with the client_secret.json "
        "of the client whose ID/secret are in GitHub Secrets, then replace "
        "YOUTUBE_REFRESH_TOKEN."
    ),
    "deleted_client": (
        "the OAuth client in YOUTUBE_CLIENT_ID was deleted in Google Cloud. Create "
        "a new Desktop client, update YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET, "
        "and reauthorize to get a new YOUTUBE_REFRESH_TOKEN."
    ),
    "disabled_client": (
        "the OAuth client in YOUTUBE_CLIENT_ID is disabled in Google Cloud. "
        "Re-enable it or create a new Desktop client and reauthorize."
    ),
    "invalid_scope": (
        "the refresh token was not granted the YouTube upload scope. Reauthorize "
        "with renew_youtube_token.py and replace YOUTUBE_REFRESH_TOKEN."
    ),
    "invalid_request": (
        "one of YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN "
        "is malformed (extra spaces, quotes or a partial copy). Re-paste them."
    ),
    "access_denied": (
        "the Google account or Workspace policy denied access. Reauthorize with the "
        "account that owns the YouTube channel."
    ),
}


def _oauth_error_code(detail: str) -> str | None:
    for code in _OAUTH_ERROR_HINTS:
        if re.search(rf"\b{code}\b", detail):
            return code
    return None


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
        code = _oauth_error_code(detail)
        if code:
            raise RuntimeError(
                f"YouTube OAuth token refresh failed: Google answered '{code}'. "
                + _OAUTH_ERROR_HINTS[code]
            ) from None
        raise RuntimeError(
            "YouTube OAuth token refresh failed before video generation "
            f"({type(exc).__name__}, no OAuth error code in Google's answer). "
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

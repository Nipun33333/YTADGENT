"""Obtain a fresh YouTube upload refresh token using your own browser.

Run from the project directory on your personal computer:
    python renew_youtube_token.py

Requires client_secret.json from the same OAuth Desktop client used in
GitHub Actions (YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET).
DO NOT upload the output token or client_secret.json to GitHub.
"""
from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from config import YOUTUBE_CLIENT_SECRET, YOUTUBE_SCOPES


def main():
    client_file = Path(YOUTUBE_CLIENT_SECRET)
    if not client_file.is_file():
        raise SystemExit(
            "Missing client_secret.json. Download the OAuth Desktop client JSON "
            "from Google Cloud Console and put it next to this script. "
            "Use the exact same client as the encrypted GitHub Actions secrets."
        )

    print("Opening a local browser authorization for YouTube upload.")
    print("Sign in to the Google account that owns/manages your YouTube channel.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), YOUTUBE_SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        access_type="offline",
        prompt="consent",
        open_browser=True,
    )
    if not credentials.refresh_token:
        raise SystemExit(
            "Google did not return a refresh token. Ensure prompt=consent, "
            "use a Desktop OAuth client, and check your Google Cloud app settings."
        )

    try:
        credentials.refresh(Request())
    except Exception:
        raise SystemExit(
            "The newly issued refresh token failed validation. Check whether "
            "you are using a matching OAuth client and authorized Google account."
        ) from None

    print("\nOAuth refresh token verified!\n")
    print("Save the token below ONLY to GitHub Settings > Secrets and variables "
          "> Actions > YOUTUBE_REFRESH_TOKEN. Never share it in a chat or commit.")
    print("\nYOUTUBE_REFRESH_TOKEN=" + credentials.refresh_token)
    print("\nAfter saving the secret, clear your terminal window. "
          "Keep client_secret.json and token out of git.")


if __name__ == "__main__":
    main()

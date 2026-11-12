"""Safely regenerate YouTube OAuth credentials and sync GitHub Actions secrets.

Requires the new Desktop OAuth client's client_secret.json in this folder.
Run: python sync_youtube_oauth_secrets.py

This program NEVER prints or commits client secrets or OAuth tokens.
It updates only the three YouTube OAuth secrets in Nipun33333/YTADGENT.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

REPO = "Nipun33333/YTADGENT"
ROOT = Path(__file__).resolve().parent
JSON_FILE = ROOT / "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def gh_command(*args, value=None):
    """Run GitHub CLI without ever showing credentials in logs or arguments."""
    cmd = [shutil.which("gh") or "gh", *args]
    try:
        result = subprocess.run(
            cmd,
            input=value,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=75,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise SystemExit("GitHub CLI (gh) is missing or timed out. Install GitHub CLI and run 'gh auth login'.") from None
    if result.returncode:
        raise SystemExit(
            "GitHub CLI command failed. Run 'gh auth login' and ensure your "
            "account can edit Nipun33333/YTADGENT Actions secrets."
        )
    return result.stdout.strip()


def main():
    if not JSON_FILE.is_file():
        raise SystemExit(
            "client_secret.json was not found next to this script. "
            "Download the JSON from the NEW Google Cloud Desktop OAuth client."
        )
    try:
        data = json.loads(JSON_FILE.read_text(encoding="utf-8"))
        item = data["installed"]
        client_id = item["client_id"].strip()
        client_secret = item["client_secret"].strip()
        if not client_id or not client_secret:
            raise ValueError("missing OAuth fields")
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit("JSON is not a valid Desktop OAuth client JSON file.") from None

    print("Checking GitHub CLI login and target repository...")
    gh_command("auth", "status", "--hostname", "github.com")
    full_name = gh_command(
        "repo", "view", REPO, "--json", "nameWithOwner", "--jq", ".nameWithOwner"
    )
    if full_name.lower() != REPO.lower():
        raise SystemExit("GitHub CLI returned a different repository. Aborting.")

    print("Opening Google authorization for YouTube upload...")
    print("Choose the Google account that owns/manages the intended channel.")
    flow = InstalledAppFlow.from_client_secrets_file(str(JSON_FILE), SCOPES)
    try:
        creds = flow.run_local_server(
            host="localhost",
            port=0,
            access_type="offline",
            prompt="consent",
            open_browser=True,
        )
        if not creds.refresh_token:
            raise ValueError("No refresh token was returned by Google.")
        creds.refresh(Request())
        if not creds.valid or not creds.token:
            raise ValueError("Google did not return a usable access token.")
    except Exception:
        raise SystemExit(
            "New Google OAuth authorization/refresh validation failed. "
            "No GitHub secrets were changed."
        ) from None

    values = {
        "YOUTUBE_CLIENT_ID": client_id,
        "YOUTUBE_CLIENT_SECRET": client_secret,
        "YOUTUBE_REFRESH_TOKEN": creds.refresh_token,
    }
    print("Google OAuth refresh succeeded. Syncing secrets directly to GitHub...")
    for name, value in values.items():
        gh_command("secret", "set", name, "--repo", REPO, "--app", "actions", value=value)
        print("Updated:", name)

    # Do not print or persist the token, and do not start an upload run.
    print("All 3 secrets updated in " + REPO + ".")
    print("Next: GitHub Actions > Check YouTube OAuth > Run workflow.")
    print("Do NOT upload client_secret.json or the refresh token to GitHub.")


if __name__ == "__main__":
    main()

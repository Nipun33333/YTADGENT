# Recover revoked or expired YouTube OAuth (GitHub Actions)

If the pipeline reports `invalid_grant: Token has been expired or revoked`,
the OAuth refresh token in the encrypted GitHub Actions repository secret is
not usable. Rerunning the same workflow without changing the credentials
will not fix it.

## 1. Check the app's publishing status

Open [Google Cloud Console](https://console.cloud.google.com/) for the
Google Cloud project that owns the **OAuth Desktop client** used by this
repository. In **Google Auth Platform > Audience**, check the publishing
status. If it is `External` and `Testing`, a refresh token for YouTube
upload permissions generally expires after **seven days**.

For continuous personal use, evaluate **Publish app / In production**.
The Google consent screen may warn about an unverified application, and
Google's verification/usage policies still apply. Changing the app status
does not restore an already revoked token: reauthorize afterward. A token
can still be revoked for other reasons in production.

## 2. Renew the token locally

On your own PC (not in GitHub Actions):

1. Download the **Desktop** OAuth client JSON from the same Google Cloud
   project and client used by the workflow. Save it as `client_secret.json`
   in the repository root. It is gitignored.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Run `python renew_youtube_token.py`.
4. Sign into the Google account controlling the target YouTube channel,
   approve `youtube.upload`, and copy the fresh
   `YOUTUBE_REFRESH_TOKEN` from your **local terminal**.

Never paste tokens/client secrets into ChatGPT, an issue, a pull request,
workflow logs, or source files. Do not commit `client_secret.json`.

## 3. Update GitHub encrypted secrets

Open **repository Settings > Secrets and variables > Actions**.
Replace the encrypted secret **`YOUTUBE_REFRESH_TOKEN`** with the newly
issued token. Verify **`YOUTUBE_CLIENT_ID`** and
**`YOUTUBE_CLIENT_SECRET`** correspond to the exact OAuth Desktop client
used in step 2. Copy values via the GitHub UI, not your shell history.

## 4. Verify

Manually trigger **Daily YouTube Pipeline** from **Actions**.
The new early verification step must show:

```
YouTube OAuth refresh token verified; valid access token saved.
```

If it instead fails with `invalid_grant`, confirm publishing status,
Google account, and the matching OAuth Desktop client. No video generation
should start until verification succeeds.

**Note:** The validation prevents wasting Gemini/media/rendering effort
with invalid OAuth credentials. It does not bypass the Google consent process
and cannot resurrect a revoked token.

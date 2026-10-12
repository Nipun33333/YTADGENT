"""Offline coverage for GitHub Actions YouTube OAuth preflight."""
import pickle
from pathlib import Path

import pytest

from uploader.oauth_preflight import validate_and_store_oauth

ENV = {
    "YOUTUBE_CLIENT_ID": "test-client-id",
    "YOUTUBE_CLIENT_SECRET": "test-secret",
    "YOUTUBE_REFRESH_TOKEN": "test-refresh-token",
}


class FakeCredentials:
    def __init__(self, **kwargs):
        self.values = kwargs
        self.valid = False
        self.token = None

    def refresh(self, request):
        if self.values["refresh_token"] == "revoked":
            raise ValueError("invalid_grant: Token has been expired or revoked.")
        if self.values["refresh_token"] == "other-failure":
            raise ValueError("invalid_client: test-secret should not appear in logs")
        self.valid = True
        self.token = "new-access-token"


def test_preflight_exchanges_refresh_token_and_persists_credentials(tmp_path, capsys):
    path = tmp_path / "youtube_token.pickle"
    creds = validate_and_store_oauth(
        environ=ENV,
        credentials_class=FakeCredentials,
        request_factory=object,
        token_path=path,
    )
    assert creds.token == "new-access-token"
    with path.open("rb") as stream:
        stored = pickle.load(stream)
    assert stored.valid
    assert stored.values["refresh_token"] == "test-refresh-token"
    assert "verified" in capsys.readouterr().out


@pytest.mark.parametrize("missing_key", list(ENV))
def test_preflight_rejects_missing_secrets_before_network(tmp_path, missing_key):
    partial = dict(ENV)
    partial[missing_key] = ""
    with pytest.raises(RuntimeError, match=missing_key):
        validate_and_store_oauth(
            environ=partial,
            credentials_class=FakeCredentials,
            request_factory=object,
            token_path=tmp_path / "token.pickle",
        )
    assert not (tmp_path / "token.pickle").exists()


def test_preflight_rejects_revoked_refresh_token_without_writing_file(tmp_path):
    env = dict(ENV, YOUTUBE_REFRESH_TOKEN="revoked")
    path = tmp_path / "token.pickle"
    with pytest.raises(RuntimeError, match="invalid_grant") as err:
        validate_and_store_oauth(
            environ=env, credentials_class=FakeCredentials,
            request_factory=object, token_path=path,
        )
    assert "YOUTUBE_REFRESH_TOKEN" in str(err.value)
    assert not path.exists()


def test_preflight_does_not_leak_secret_from_generic_failure(tmp_path):
    env = dict(ENV, YOUTUBE_REFRESH_TOKEN="other-failure")
    with pytest.raises(RuntimeError) as err:
        validate_and_store_oauth(
            environ=env, credentials_class=FakeCredentials,
            request_factory=object, token_path=tmp_path / "token.pickle",
        )
    assert "test-secret" not in str(err.value)


def test_workflow_validates_oauth_before_pipeline():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/daily-short.yml").read_text(encoding="utf-8")
    assert "python -m uploader.oauth_preflight" in workflow
    assert workflow.index("python -m uploader.oauth_preflight") < workflow.index("python -m pipeline")
    assert "YOUTUBE_REFRESH_TOKEN: ${{ secrets.YOUTUBE_REFRESH_TOKEN }}" in workflow
    assert "YouTube OAuth token created successfully" not in workflow

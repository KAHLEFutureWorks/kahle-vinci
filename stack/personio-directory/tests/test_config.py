import pytest

from app.config import ConfigError, PersonioConfig


def test_config_requires_both_credentials_without_echoing_values(monkeypatch):
    client_id = "client-visible-only-" + "to-process"
    monkeypatch.setenv("PERSONIO_CLIENT_ID", client_id)
    monkeypatch.delenv("PERSONIO_API", raising=False)

    with pytest.raises(ConfigError, match="personio_api_required") as error:
        PersonioConfig.from_env()

    assert client_id not in str(error.value)


def test_config_uses_expected_urls_and_read_only_timeout(monkeypatch):
    monkeypatch.setenv("PERSONIO_CLIENT_ID", "client")
    monkeypatch.setenv("PERSONIO_API", "secret")

    config = PersonioConfig.from_env()

    assert config.api_base_url == "https://api.personio.de"
    assert config.timeout_seconds == 20
    assert config.v1_token_url == "https://api.personio.de/v1/auth"
    assert config.v2_token_url == "https://api.personio.de/v2/auth/token"

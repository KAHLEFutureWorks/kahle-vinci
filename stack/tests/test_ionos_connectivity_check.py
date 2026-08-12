from ionos_connectivity_check import resolve_api_key


def test_connectivity_check_uses_same_token_precedence_as_compose(monkeypatch):
    monkeypatch.setenv("IONOS_API_KEY", "older-credential-token")
    monkeypatch.setenv("IONOS_API_TOKEN", "active-runtime-token")

    assert resolve_api_key() == ("active-runtime-token", "IONOS_API_TOKEN")


def test_connectivity_check_honors_an_explicit_variable(monkeypatch):
    monkeypatch.setenv("CUSTOM_IONOS_TOKEN", "explicit-token")
    monkeypatch.setenv("IONOS_API_TOKEN", "active-runtime-token")

    assert resolve_api_key("CUSTOM_IONOS_TOKEN") == ("explicit-token", "CUSTOM_IONOS_TOKEN")

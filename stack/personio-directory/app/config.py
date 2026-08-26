from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """A configuration error whose message is always a safe code."""


@dataclass(frozen=True)
class PersonioConfig:
    client_id: str
    client_secret: str
    api_base_url: str = "https://api.personio.de"
    timeout_seconds: int = 20
    max_response_bytes: int = 2 * 1024 * 1024
    max_retries: int = 3

    @property
    def v1_token_url(self) -> str:
        return f"{self.api_base_url}/v1/auth"

    @property
    def v2_token_url(self) -> str:
        return f"{self.api_base_url}/v2/auth/token"

    @classmethod
    def from_env(cls) -> "PersonioConfig":
        client_id = os.environ.get("PERSONIO_CLIENT_ID", "").strip()
        client_secret = os.environ.get("PERSONIO_API", "").strip()
        if not client_id:
            raise ConfigError("personio_client_id_required")
        if not client_secret:
            raise ConfigError("personio_api_required")
        return cls(client_id=client_id, client_secret=client_secret)

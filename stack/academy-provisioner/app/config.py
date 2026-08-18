from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProvisioningConfig:
    api_key: str
    api_base_url: str
    course_name: str
    interval_seconds: int
    allowed_emails: frozenset[str] | None

    @classmethod
    def from_env(cls) -> "ProvisioningConfig":
        api_key = os.getenv("LEARNINGSUITE_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("learningsuite_api_key_required")

        course_name = os.getenv(
            "LEARNINGSUITE_COURSE_NAME", "Einführung in die KAHLE-Vinci Nutzung"
        ).strip()
        if not course_name:
            raise ConfigError("learningsuite_course_name_required")

        allowed_emails_value = os.getenv("LEARNINGSUITE_ALLOWED_EMAILS", "").strip()
        if not allowed_emails_value:
            raise ConfigError("learningsuite_allowed_emails_required")
        if allowed_emails_value == "*":
            allowed_emails = None
        else:
            allowed_emails = frozenset(
                email.strip().lower()
                for email in allowed_emails_value.replace(";", ",").split(",")
                if email.strip()
            )
            if not allowed_emails or "*" in allowed_emails:
                raise ConfigError("learningsuite_allowed_emails_invalid")

        try:
            interval_seconds = int(
                os.getenv("LEARNINGSUITE_PROVISION_INTERVAL_SECONDS", "60")
            )
        except ValueError as exc:
            raise ConfigError("learningsuite_interval_invalid") from exc

        return cls(
            api_key=api_key,
            api_base_url=os.getenv(
                "LEARNINGSUITE_API_BASE_URL", "https://api.learningsuite.io/api/v1"
            ).rstrip("/"),
            course_name=course_name,
            interval_seconds=max(60, interval_seconds),
            allowed_emails=allowed_emails,
        )

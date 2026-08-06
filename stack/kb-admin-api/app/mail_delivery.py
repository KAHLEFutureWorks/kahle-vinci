from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import requests

try:
    from .maintenance import MaintenanceService, OutboxMessage
except ImportError:  # pragma: no cover
    from maintenance import MaintenanceService, OutboxMessage


class MailTransport(Protocol):
    def send(self, message: OutboxMessage) -> None: ...


@dataclass
class MicrosoftGraphMailTransport:
    tenant_id: str
    client_id: str
    client_secret: str
    sender: str
    timeout: int = 30

    def __post_init__(self) -> None:
        if not all((self.tenant_id, self.client_id, self.client_secret, self.sender)):
            raise ValueError("graph_mail_configuration_incomplete")
        self._token = ""
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        response = requests.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._token = str(payload["access_token"])
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    def send(self, message: OutboxMessage) -> None:
        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{self.sender}/sendMail",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json={"message": {
                "subject": message.subject,
                "body": {"contentType": "Text", "content": message.body},
                "toRecipients": [{"emailAddress": {"address": message.recipient}}],
            }, "saveToSentItems": True},
            timeout=self.timeout,
        )
        response.raise_for_status()


class OutboxDispatcher:
    def __init__(self, service: MaintenanceService, transport: MailTransport):
        self.service, self.transport = service, transport

    def dispatch(self, limit: int = 50) -> dict[str, int]:
        sent = failed = 0
        for message in self.service.pending_messages(limit):
            try:
                self.transport.send(message)
            except Exception as exc:
                self.service.mark_failed(message.message_id, str(exc))
                failed += 1
            else:
                self.service.mark_sent(message.message_id)
                sent += 1
        return {"sent": sent, "failed": failed}

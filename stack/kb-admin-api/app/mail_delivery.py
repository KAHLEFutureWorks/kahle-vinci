from __future__ import annotations

import time
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import requests

try:
    from .maintenance import MaintenanceService, OutboxMessage
except ImportError:  # pragma: no cover
    from maintenance import MaintenanceService, OutboxMessage


class MailTransport(Protocol):
    def send(self, message: OutboxMessage) -> None: ...


@dataclass
class MicrosoftGraphClient:
    tenant_id: str
    client_id: str
    client_secret: str
    timeout: int = 30

    def __post_init__(self) -> None:
        if not all((self.tenant_id, self.client_id, self.client_secret)):
            raise ValueError("graph_configuration_incomplete")
        self._token = ""
        self._token_expires_at = 0.0

    def access_token(self) -> str:
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

    def automatic_replies(self, user_principal_name: str) -> dict[str, Any]:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/users/"
            f"{quote(user_principal_name, safe='')}/mailboxSettings/automaticRepliesSetting",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("graph_automatic_replies_invalid")
        return payload


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
        self.client = MicrosoftGraphClient(
            self.tenant_id, self.client_id, self.client_secret, self.timeout,
        )

    def send(self, message: OutboxMessage) -> None:
        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{quote(self.sender, safe='')}/sendMail",
            headers={"Authorization": f"Bearer {self.client.access_token()}"},
            json={"message": {
                "subject": message.subject,
                "body": {"contentType": "Text", "content": message.body},
                "toRecipients": [{"emailAddress": {"address": message.recipient}}],
            }, "saveToSentItems": True},
            timeout=self.timeout,
        )
        response.raise_for_status()


@dataclass
class LocalMailCaptureTransport:
    """Append locally delivered messages as JSON lines for development evidence."""

    path: Path

    def send(self, message: OutboxMessage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "message_id": message.message_id,
            "recipient": message.recipient,
            "subject": message.subject,
            "body": message.body,
            "kind": message.kind,
        }
        with self.path.open("a", encoding="utf-8") as capture:
            capture.write(json.dumps(payload, ensure_ascii=False) + "\n")


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

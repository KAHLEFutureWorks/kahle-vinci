from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests

from .learningsuite import ProvisioningError
from .models import EligibleUser


WELCOME_SUBJECT = "Dein Zugang zu KAHLE-Vinci wurde freigeschaltet"
PENDING_ACCESS_SUBJECT = "Neue Zugriffsanfrage für KAHLE-Vinci"


def welcome_body(first_name: str) -> str:
    return (
        f"Hallo {first_name},\n\n"
        "dein Zugang zu KAHLE-Vinci wurde freigeschaltet.\n\n"
        "Du kannst KAHLE-Vinci ab sofort unter folgender Adresse nutzen:\n\n"
        "https://vinci.kahle.de\n\n"
        "Für den Einstieg erhältst du in Kürze eine weitere E-Mail von learningsuit.io. "
        "Diese Nachricht gehört zur offiziellen KAHLE-Academy und ist kein Phishing 😊 \n"
        "Über den Link in dieser E-Mail kannst du auf den Kurs „Einführung in die "
        "KAHLE-Vinci Nutzung“ in der KAHLE-Academy zugreifen.\n\n"
        "Wenn du Fragen zur Anmeldung oder zur Nutzung von KAHLE-Vinci hast, melde dich "
        "gerne bei mir.\n\n"
    )


def pending_access_body(admin_first_name: str, pending_user: EligibleUser) -> str:
    return (
        f"Hallo {admin_first_name},\n\n"
        f"{pending_user.first_name} {pending_user.last_name} "
        f"({pending_user.email}) hat den Zugang zu KAHLE-Vinci angefragt.\n\n"
        "Bitte prüfe die Anfrage und gib den Nutzer bei Bedarf als Benutzer oder Admin frei:\n\n"
        "https://vinci.kahle.de/admin/users\n\n"
        "Solange keine Freigabe erfolgt, bleibt der Zugang gesperrt.\n\n"
    )


@dataclass
class MicrosoftGraphWelcomeMailer:
    tenant_id: str
    client_id: str
    client_secret: str
    sender: str
    timeout: int = 30
    session: Any = requests
    _token: str = field(default="", init=False)
    _token_expires_at: float = field(default=0.0, init=False)

    def send_welcome(self, user: EligibleUser) -> None:
        self._send(user.email, WELCOME_SUBJECT, welcome_body(user.first_name))

    def send_pending_access_request(
        self, admin: EligibleUser, pending_user: EligibleUser
    ) -> None:
        self._send(
            admin.email,
            PENDING_ACCESS_SUBJECT,
            pending_access_body(admin.first_name, pending_user),
        )

    def _send(self, recipient: str, subject: str, body: str) -> None:
        try:
            response = self.session.post(
                "https://graph.microsoft.com/v1.0/users/"
                f"{quote(self.sender, safe='')}/sendMail",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                json={
                    "message": {
                        "subject": subject,
                        "body": {
                            "contentType": "Text",
                            "content": body,
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": recipient}}
                        ],
                    },
                    "saveToSentItems": True,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise ProvisioningError("welcome_mail_failed") from exc

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        response = self.session.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._token = str(payload["access_token"])
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._token

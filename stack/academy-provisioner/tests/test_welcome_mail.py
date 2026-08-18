from __future__ import annotations

from unittest.mock import Mock

from app.models import EligibleUser
from app.welcome_mail import MicrosoftGraphWelcomeMailer


def test_welcome_mail_uses_approved_text_and_preserves_signature_paragraph() -> None:
    session = Mock()
    token_response = Mock()
    token_response.json.return_value = {"access_token": "token", "expires_in": 3600}
    mail_response = Mock()
    session.post.side_effect = [token_response, mail_response]
    mailer = MicrosoftGraphWelcomeMailer(
        "tenant", "client", "secret", "oltmanns@kahle.de", session=session
    )

    mailer.send_welcome(
        EligibleUser("user-1", "reschke@kahle.de", "Ralf", "Reschke", "user")
    )

    request = session.post.call_args_list[1]
    assert request.args[0] == (
        "https://graph.microsoft.com/v1.0/users/oltmanns%40kahle.de/sendMail"
    )
    assert request.kwargs["json"] == {
        "message": {
            "subject": "Dein Zugang zu KAHLE-Vinci wurde freigeschaltet",
            "body": {
                "contentType": "Text",
                "content": (
                    "Hallo Ralf,\n\n"
                    "dein Zugang zu KAHLE-Vinci wurde freigeschaltet.\n\n"
                    "Du kannst KAHLE-Vinci ab sofort unter folgender Adresse nutzen:\n\n"
                    "https://vinci.kahle.de\n\n"
                    "Für den Einstieg erhältst du in Kürze eine weitere E-Mail von "
                    "learningsuit.io. Diese Nachricht gehört zur offiziellen KAHLE-Academy "
                    "und ist kein Phishing 😊 \n"
                    "Über den Link in dieser E-Mail kannst du auf den Kurs „Einführung in die "
                    "KAHLE-Vinci Nutzung“ in der KAHLE-Academy zugreifen.\n\n"
                    "Wenn du Fragen zur Anmeldung oder zur Nutzung von KAHLE-Vinci hast, "
                    "melde dich gerne bei mir.\n\n"
                ),
            },
            "toRecipients": [{"emailAddress": {"address": "reschke@kahle.de"}}],
        },
        "saveToSentItems": True,
    }


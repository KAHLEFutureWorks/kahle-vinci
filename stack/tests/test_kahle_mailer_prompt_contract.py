from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "open-webui-prompts" / "vincis" / "kahle-email-vinci-systemprompt.md"


def _prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


def test_mailer_classifies_source_text_before_writing():
    prompt = _prompt()
    lowered = prompt.lower()

    assert "Art der Eingabe" in prompt
    assert "eingehende mail" in lowered
    assert "ausgehender entwurf" in lowered
    assert "Mailverlauf" in prompt


def test_mailer_prioritizes_latest_message_in_threads():
    prompt = _prompt()

    assert "letzte relevante Nachricht" in prompt
    assert "Urspruengliche Nachricht" in prompt
    assert "aeltere Nachrichten" in prompt


def test_mailer_does_not_mirror_incoming_mail_as_reply():
    prompt = _prompt()

    assert "kopiere die Ursprungsmail nicht" in prompt
    assert "Antworte auf die offenen Punkte" in prompt


def test_mailer_infers_or_asks_for_du_sie_policy():
    prompt = _prompt()
    lowered = prompt.lower()

    assert "Du/Sie" in prompt
    assert "Wenn unklar ist, ob Du oder Sie" in prompt
    assert "externe kunden" in lowered
    assert "interne kahle" in lowered


def test_mailer_uses_compact_rag_queries_only_when_needed():
    prompt = _prompt()

    assert "Rufe RAG_Chat nie mit einer kompletten E-Mail" in prompt
    assert "maximal 12 Woertern" in prompt
    assert "Wenn der Mailentwurf ohne interne Fakten moeglich ist" in prompt


def test_mailer_asks_when_standalone_mail_direction_is_unclear():
    prompt = _prompt()

    assert "Allein eingefuegte formatierte Mail ohne Nutzerauftrag" in prompt
    assert "keinen Entwurf schreiben" in prompt
    assert "Soll ich auf diese Mail antworten oder diesen Entwurf verbessern?" in prompt


def test_mailer_requests_critical_missing_information_before_drafting():
    prompt = _prompt()

    assert "Kritische fehlende Informationen" in prompt
    assert "Dokumenten-ID" in prompt
    assert "frage zuerst nach" in prompt
    assert "Falls ich antworten soll: Welche Dokumenten-ID soll genannt werden?" in prompt


def test_mailer_answer_command_replies_from_recipient_perspective():
    prompt = _prompt()

    assert "Wenn der Nutzer ausdruecklich \"Beantworte die Mail\"" in prompt
    assert "aus Sicht des Empfaengers" in prompt
    assert "nicht an die Person aus der Anrede" in prompt
    assert "Frage den Absender nicht nach Informationen, die er von uns anfordert" in prompt

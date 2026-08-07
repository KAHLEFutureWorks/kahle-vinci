from app.content_classification import ContentConfidentialityClassifier, stricter_level


def test_sensitive_content_is_classified_without_weakening_user_choice():
    classifier = ContentConfidentialityClassifier()
    assert classifier.classify("Interne Schulungsunterlage").level == "internal"
    assert classifier.classify("Kontakt: max@example.com").level == "restricted"
    result = classifier.classify("IBAN DE02120300000000202051 und API-Key")
    assert result.level == "confidential"
    assert result.signals
    assert stricter_level("confidential", "internal") == "confidential"
    assert stricter_level("internal", "restricted") == "restricted"


def test_internal_contact_block_does_not_raise_the_level():
    """
    Fast jede KAHLE-Richtlinie endet mit einem Kontaktblock aus internen
    Adressen und einer Servicenummer. Als personenbezogenes Merkmal gewertet,
    landete dadurch praktisch jedes Dokument auf "bereichsbeschraenkt" und ging
    zur Adminpruefung; die Einstufung verlor damit ihre Aussagekraft.
    """
    classifier = ContentConfidentialityClassifier()
    richtlinie = (
        "# KAHLE KI Policy\n\n"
        "Diese Richtlinie regelt den Einsatz von KI.\n\n"
        "| Funktion | Name | Kontakt |\n"
        "| Geschaeftsfuehrung: | Lukas Kahle | l.kahle@kahle.de |\n"
        "| KI-Beauftragter: | Jan Oltmanns | oltmanns@kahle.de |\n"
        "| DS-Beauftragte: | Fr. Stratmann-Severin | 0800 1511751 |\n"
    )
    assert classifier.classify(richtlinie).level == "internal"


def test_external_addresses_still_raise_the_level():
    classifier = ContentConfidentialityClassifier()
    assert classifier.classify("Kontakt: max@example.com").level == "restricted"
    assert classifier.classify("Anwalt: info@melzgercke.de").level == "restricted"


def test_the_word_confidential_only_counts_as_a_classification_label():
    """
    "vertraulich" erklaert in Richtlinien meist einen Begriff, statt das
    Dokument selbst einzustufen.
    """
    classifier = ContentConfidentialityClassifier()
    erklaerung = "Geschaeftsgeheimnisse sind vertraulich zu behandeln."
    assert classifier.classify(erklaerung).level == "internal"

    for kennzeichnung in (
        "Klassifizierung: VERTRAULICH",
        "Einstufung: vertraulich",
        "Klassifizierung: INTERN",
    ):
        expected = "internal" if "INTERN" in kennzeichnung else "restricted"
        assert classifier.classify(kennzeichnung).level == expected, kennzeichnung


def test_genuinely_sensitive_content_is_unaffected():
    classifier = ContentConfidentialityClassifier()
    assert classifier.classify("Die Marge betraegt 12 Prozent.").level == "restricted"
    assert classifier.classify("Siehe Personalakte des Mitarbeiters.").level == "restricted"
    assert classifier.classify("IBAN DE02120300000000202051").level == "confidential"
    assert classifier.classify("Zugang mit Passwort geschuetzt").level == "confidential"

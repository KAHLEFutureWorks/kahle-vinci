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

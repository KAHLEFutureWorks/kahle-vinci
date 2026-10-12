"""Personal customer data is detected by category; values are never returned."""

import pytest

from app.personal_data import detect

FORM = (
    "Kunden-Nr.: 100001\n"
    "Name: Muster, Max\n"
    "Anschrift: Beispielweg 12, 30159 Hannover\n"
    "Telefon privat: 0511 1234567\n"
    "Telefon mobil: 0171 2345678\n"
    "E-Mail Privat: max.muster@example.org\n"
    "Kennzeichen: H AB 1234\n"
    "Fahrg.-Nr.: WVWZZZ1KZAW000001\n"
)


def test_customer_form_requires_confirmation_and_reports_only_categories():
    result = detect(FORM)

    assert result.requires_confirmation is True
    assert set(result.categories) == {
        "postal_address", "private_phone", "mobile_phone", "external_email", "licence_plate", "vin",
    }
    assert "Muster" not in repr(result) and "0171" not in repr(result)


@pytest.mark.parametrize("text", [
    "Autohaus KAHLE, Kabelkamp 1, 30179 Hannover",
    "Support des Herstellers: support@hersteller.example",
    "Bei Fragen: datenschutz@kahle.de oder https://ticket.kahle.de/login.php",
    "Rufnummer Zentrale: 0511 27999-0",
])
def test_business_contacts_alone_need_no_confirmation(text):
    assert detect(text).requires_confirmation is False


def test_two_weak_signals_together_need_confirmation():
    text = "Kunde wohnt Beispielweg 12, 30159 Hannover, E-Mail max@example.org"

    assert detect(text).requires_confirmation is True


@pytest.mark.parametrize(("text", "category"), [
    ("IBAN DE89 3704 0044 0532 0130 00", "iban"),
    ("geb. 01.02.1980", "birth_date"),
    ("Kennzeichen HAN-XY 123", "licence_plate"),
    ("Mobil +49 171 2345678", "mobile_phone"),
])
def test_each_strong_signal_alone_needs_confirmation(text, category):
    result = detect(text)

    assert result.requires_confirmation is True
    assert category in result.categories

"""Phase 3c: a restrictive document scope is an evidence obligation.

The scope and the path for everything outside it come from the evidence of
the current request: an editorial claim that limits validity to a strict
subset of KAHLE locations, and a typed functional contact whose scope
excludes exactly those locations. No process text or location list is
hard-coded for a single document.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"

SCOPE_ROW = (
    "| Geltungsbereich | Servicebereiche der Standorte Hannover (HAN), "
    "Wunstorf (WUN) und Wedemark (WED) |"
)
STEP = "Kunden in Vaudis anhand der gemeldeten Kundennummer aufrufen."
EXCEPTION_ROW = "| Datenschutz | E-Mail | datenschutz@kahle.de | Sperranfragen | Alle KAHLE-Standorte außer Hannover, Wunstorf und Wedemark |"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase3c", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _claim(text, number=1, index=1, role="editorial"):
    return {
        "claim_id": f"R{number}C{index}", "source_id": f"#{number}", "text": text,
        "evidence_span": text, "document_id": f"doc-{number}", "version_id": f"v-{number}",
        "evidence_role": role,
    }


def _contact_claim(row=EXCEPTION_ROW, scope="Alle KAHLE-Standorte außer Hannover, Wunstorf und Wedemark",
                   value="datenschutz@kahle.de", number=2):
    contact = {
        "schema_version": "kahle.functional-contact.v1", "function": "Datenschutz", "channel": "email",
        "value": value, "purpose": "Sperranfragen", "scope": scope, "row_number": 7, "evidence_span": row,
    }
    claim = {
        "claim_id": f"R{number}C1", "source_id": f"#{number}", "document_id": f"doc-{number}",
        "version_id": f"v-{number}", "text": row, "evidence_span": row,
        "claim_type": "functional_contact", "functional_contact": dict(contact),
    }
    source = {
        "number": number, "document_id": f"doc-{number}", "version_id": f"v-{number}",
        "chunk_kind": "functional_contact", "functional_contact": dict(contact),
    }
    return claim, source


def _bundle(harness, *claims, extra_sources=(), status="supported"):
    sources = [{"number": 1, "document_id": "doc-1", "version_id": "v-1", "title": "Prozess"}, *extra_sources]
    return harness.EvidenceBundle(status=status, supported_claims=tuple(claims), sources=tuple(sources))


def test_table_scope_and_excluding_contact_form_one_requirement():
    harness = load_harness()
    contact, source = _contact_claim()
    evidence = _bundle(harness, _claim(SCOPE_ROW), _claim(STEP, index=2), contact, extra_sources=(source,))

    assert harness._scope_requirements(evidence) == ({
        "source_id": "#1",
        "locations": ("Hannover", "Wunstorf", "Wedemark"),
        "exception_contacts": ("datenschutz@kahle.de",),
    },)


def test_sentence_scope_without_exception_path():
    harness = load_harness()
    evidence = _bundle(harness, _claim("Diese Anleitung gilt nur für Walsrode."))

    assert harness._scope_requirements(evidence) == ({
        "source_id": "#1", "locations": ("Walsrode",), "exception_contacts": (),
    },)


@pytest.mark.parametrize(
    "text",
    [
        "Geltungsbereich: alle KAHLE-Standorte",
        "| Geltungsbereich | Hannover, Wunstorf, Wedemark, Walsrode, Neustadt, Nienburg, Stadthagen |",
        "In Hannover und Wunstorf gibt es eine eigene Annahme.",
        "Die Annahme ist in Hannover besetzt; die Anleitung gilt für alle Standorte.",
    ],
    ids=["all_named_generically", "all_listed", "mere_mention", "not_restrictive"],
)
def test_non_restrictive_or_mere_mentions_create_no_requirement(text):
    harness = load_harness()

    assert harness._scope_requirements(_bundle(harness, _claim(text))) == ()


def test_contact_without_matching_exclusion_is_no_exception_path():
    harness = load_harness()
    contact, source = _contact_claim(
        row="| IT | E-Mail | it@kahle.de | Störungen | gruppenweit |", scope="gruppenweit", value="it@kahle.de",
    )
    evidence = _bundle(harness, _claim(SCOPE_ROW), contact, extra_sources=(source,))

    assert harness._scope_requirements(evidence)[0]["exception_contacts"] == ()


def test_exclusion_must_cover_exactly_the_scoped_locations():
    harness = load_harness()
    contact, source = _contact_claim(scope="Alle KAHLE-Standorte außer Hannover")
    evidence = _bundle(harness, _claim(SCOPE_ROW), contact, extra_sources=(source,))

    assert harness._scope_requirements(evidence)[0]["exception_contacts"] == ()


def test_non_editorial_or_unsupported_evidence_creates_no_requirement():
    harness = load_harness()

    assert harness._scope_requirements(_bundle(harness, _claim(SCOPE_ROW, role="auxiliary_ocr"))) == ()
    assert harness._scope_requirements(_bundle(harness, _claim(SCOPE_ROW), status="unsupported")) == ()

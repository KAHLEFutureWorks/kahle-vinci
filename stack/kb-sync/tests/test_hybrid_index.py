from app.hybrid_index import BM25Corpus, ParentChildChunker, german_tokens
import pytest


CONTACT_HEADER = "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |\n| --- | --- | --- | --- | --- |"
IT_ROW = "| IT | E-Mail | it@example.invalid | Störungen | gruppenweit |"
MARKETING_ROW = "| Marketing | E-Mail | marketing@example.invalid | Kampagnen | gruppenweit |"


def test_contact_child_never_contains_other_contact():
    markdown = "\n".join(("## Funktionskontakte", CONTACT_HEADER, IT_ROW, MARKETING_ROW))
    children = ParentChildChunker().chunk("synthetic-doc", markdown)
    contacts = [child for child in children if child.kind == "functional_contact"]
    assert len(contacts) == 2
    assert contacts[0].functional_contact["function"] == "IT"
    assert contacts[0].functional_contact["row_number"] == 4
    assert contacts[1].functional_contact["row_number"] == 5
    assert contacts[0].parent_id != contacts[1].parent_id
    for contact in contacts:
        assert contact.content == contact.parent_content == contact.functional_contact["evidence_span"]
    for child in children:
        if child.kind != "functional_contact":
            assert "it@example.invalid" not in child.parent_content
            assert "marketing@example.invalid" not in child.parent_content


def test_contact_rows_keep_global_frontmatter_free_crlf_line_numbers():
    markdown = "\n".join(("---", "title: Example", "---", "# Wissen", "", "Einleitung.", "", "## Funktionskontakte", CONTACT_HEADER, IT_ROW))
    children = ParentChildChunker().chunk("synthetic-doc", markdown.replace("\n", "\r\n"))
    contact = next(child for child in children if child.kind == "functional_contact")
    assert contact.functional_contact["row_number"] == 8
    assert contact.content == IT_ROW


@pytest.mark.parametrize("hint", ["Für Fragen wie", "Beispielanfragen", "Suchbegriffe", "Synonyme", "Kurzindex"])
def test_hint_classification_inherits_real_heading_depth(hint):
    markdown = f"### {hint}\nHinweis.\n#### Unterabschnitt\nBeispiel.\n### Prozess\nEchte Anweisung."
    children = ParentChildChunker().chunk("synthetic-doc", markdown)
    assert [child.kind for child in children] == ["retrieval_hint", "retrieval_hint", "text"]
    assert children[-1].heading_path == ("Prozess",)


@pytest.mark.parametrize("fence", ["```", "~~~~"])
def test_fenced_contact_example_never_becomes_typed_even_if_row_repeats(fence):
    markdown = "\n".join((fence, "## Funktionskontakte", CONTACT_HEADER, IT_ROW, fence,
                           "## Funktionskontakte", CONTACT_HEADER, IT_ROW))
    children = ParentChildChunker().chunk("synthetic-doc", markdown)
    contacts = [child for child in children if child.kind == "functional_contact"]
    assert len(contacts) == 1
    assert contacts[0].functional_contact["row_number"] == 10
    assert children[0].kind != "retrieval_hint"


def test_invalid_or_oversized_rows_remain_untyped_without_splitting_valid_row():
    invalid = IT_ROW.replace("it@example.invalid", "not-an-email")
    oversized = MARKETING_ROW.replace("Kampagnen", "x" * 201)
    markdown = "\n".join(("## Funktionskontakte", CONTACT_HEADER, invalid, oversized, IT_ROW))
    children = ParentChildChunker(child_max_chars=200).chunk("synthetic-doc", markdown)
    contacts = [child for child in children if child.kind == "functional_contact"]
    assert len(contacts) == 1
    assert contacts[0].content == IT_ROW
    assert all(child.functional_contact is None for child in children if child.kind != "functional_contact")


def test_german_bm25_preserves_identifiers_and_delegates_idf_to_qdrant():
    documents = ["Service Aktion A1b Reifen", "Service Termin Reifen", "Verkauf Fahrzeug Reifen"]
    corpus = BM25Corpus(documents)
    query = corpus.query_vector("Welche Aktion A1b gilt?")
    assert query.indices
    a1b_index = corpus.query_vector("A1b").indices[0]
    reifen_value = corpus.query_vector("Reifen").values[0]
    a1b_value = corpus.query_vector("A1b").values[0]
    assert a1b_index in query.indices
    assert a1b_value == reifen_value == 1.0
    assert "welche" not in german_tokens("Welche Aktion gilt?")


def test_parent_child_chunking_follows_headings_and_keeps_table_schema():
    markdown = """# Service

Ein kurzer Einleitungssatz.

## Aktionen

| Code | Beschreibung |
|---|---|
| A1a | Erste Aktion |
| A1b | Zweite Aktion |

## Ablauf

Schritt eins. Schritt zwei.
"""
    chunks = ParentChildChunker(child_max_chars=220).chunk("doc-1", markdown)
    table_chunks = [chunk for chunk in chunks if chunk.kind == "table"]
    assert len(table_chunks) == 2
    assert all("| Code | Beschreibung |" in chunk.content for chunk in table_chunks)
    assert table_chunks[0].heading_path == ("Service", "Aktionen")
    assert chunks[-1].heading_path == ("Service", "Ablauf")
    assert all(chunk.parent_id.startswith("doc-1:p") for chunk in chunks)


def test_parent_child_chunking_never_indexes_yaml_frontmatter_as_knowledge():
    markdown = """---
document_id: "doc-1"
owner_email: "owner@kahle.de"
valid_until: "2026-11-03"
---

# KI-Compliance

## 1. Begriffe

KI bezeichnet ein maschinengestütztes System.
"""

    chunks = ParentChildChunker().chunk("doc-1", markdown)

    assert chunks
    assert all("owner_email:" not in chunk.parent_content for chunk in chunks)
    assert chunks[0].heading_path == ("KI-Compliance", "1. Begriffe")


def test_parent_child_chunking_marks_search_examples_as_retrieval_hints():
    markdown = """# Kontakte

## Für Fragen wie

Wie lautet das Funktionspostfach des Marketings?

## Marketing

Das dokumentierte Funktionspostfach ist marketing@example.invalid.
"""

    chunks = ParentChildChunker().chunk("doc-1", markdown)

    hint_chunks = [chunk for chunk in chunks if chunk.heading_path == ("Kontakte", "Für Fragen wie")]
    answer_chunks = [chunk for chunk in chunks if chunk.heading_path == ("Kontakte", "Marketing")]
    assert [chunk.kind for chunk in hint_chunks] == ["retrieval_hint"]
    assert [chunk.kind for chunk in answer_chunks] == ["text"]

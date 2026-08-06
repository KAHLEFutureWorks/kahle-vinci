from app.hybrid_index import BM25Corpus, ParentChildChunker, german_tokens


def test_german_bm25_preserves_identifiers_and_rewards_rare_terms():
    documents = ["Service Aktion A1b Reifen", "Service Termin Reifen", "Verkauf Fahrzeug Reifen"]
    corpus = BM25Corpus(documents)
    query = corpus.query_vector("Welche Aktion A1b gilt?")
    assert query.indices
    a1b_index = corpus.query_vector("A1b").indices[0]
    reifen_value = corpus.query_vector("Reifen").values[0]
    a1b_value = corpus.query_vector("A1b").values[0]
    assert a1b_index in query.indices
    assert a1b_value > reifen_value
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

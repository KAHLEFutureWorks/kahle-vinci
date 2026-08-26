import hashlib
import sqlite3
from pathlib import Path

from app.retrieval_metadata import RetrievalMetadataClassifier, RetrievalMetadataStore


def _database(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE canonical_documents (
            document_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            active_version_id TEXT
        );
        CREATE TABLE document_versions (
            version_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            status TEXT NOT NULL
        );
        INSERT INTO canonical_documents VALUES ('doc-1', 'WPS Systemübersicht', 'v-1');
        INSERT INTO document_versions VALUES ('v-1', 'doc-1', 'active');
        """
    )
    db.commit()
    db.close()


def test_classifier_distinguishes_system_existence_from_a_procedure():
    result = RetrievalMetadataClassifier().classify(
        "WPS Systemübersicht",
        "WPS ist das interne System für die Terminplanung.",
    )

    assert result.domain == "internal_systems"
    assert result.document_type == "system_overview"
    assert "system_overview" in result.evidence_capabilities
    assert "procedure" not in result.evidence_capabilities


def test_classifier_does_not_infer_system_usage_locations_from_unrelated_place_names():
    result = RetrievalMetadataClassifier().classify(
        "KAHLE Systemlandkarte",
        """## Systeme
- Fleetback wird für die Servicestation in Hannover verwendet.
- WPS verwaltet Kundentermine und betreibt die Online-Terminbuchung.
""",
    )

    assert "explicit_usage_scope" not in result.evidence_capabilities


def test_classifier_marks_only_explicit_system_usage_scope():
    result = RetrievalMetadataClassifier().classify(
        "WPS Einsatz",
        "WPS wird an den Standorten Hannover und Wunstorf eingesetzt.",
    )

    assert "explicit_usage_scope" in result.evidence_capabilities


def test_classifier_marks_opening_hours_and_location_department_overview():
    result = RetrievalMetadataClassifier().classify(
        "Standort Hannover",
        """Öffnungszeiten:
- Verkauf: Mo-Fr 09:00-18:00, Sa 09:00-13:00
- Service: Mo-Fr 07:00-18:00, Sa 09:00-13:00
- Teiledienst: Mo-Fr 07:00-17:00, Sa 09:00-13:00
""",
    )

    assert "opening_hours" in result.evidence_capabilities
    assert "location_department_overview" in result.evidence_capabilities


def test_classifier_marks_an_explicit_approval_workflow_as_procedural_evidence():
    result = RetrievalMetadataClassifier().classify(
        "Arbeitsanweisung veröffentlichen",
        "# Ablauf\n1. Fachlich prüfen.\n2. Durch die Führungskraft freigeben.\n"
        "3. Im Wissensportal veröffentlichen.",
    )

    assert result.domain == "knowledge_governance"
    assert result.document_type == "work_instruction"
    assert result.evidence_capabilities == ("approval_workflow", "procedure")


def test_classifier_recognizes_procedural_prose_without_numbered_steps():
    result = RetrievalMetadataClassifier().classify(
        "Terminbuchung im internen System",
        "Öffne die Terminplanung. Wähle den Zeitraum. Gib Kunde und Fahrzeug ein. "
        "Speichere anschließend den Termin.",
    )

    assert result.document_type == "process_description"
    assert "procedure" in result.evidence_capabilities


def test_backfill_is_idempotent_and_does_not_modify_uploaded_content(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    files_root = tmp_path / "files"
    _database(db_path)
    markdown_path = files_root / "doc-1" / "v-1" / "rag.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "# WPS\nWPS ist das interne System für die Terminplanung.",
        encoding="utf-8",
    )
    before = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    store = RetrievalMetadataStore(db_path)

    first = store.backfill(files_root)
    second = store.backfill(files_root)

    assert first == {"classified": 1, "unchanged": 0, "missing_files": 0}
    assert second == {"classified": 0, "unchanged": 1, "missing_files": 0}
    assert hashlib.sha256(markdown_path.read_bytes()).hexdigest() == before
    row = store.for_version("v-1")
    assert row["domain"] == "internal_systems"
    assert row["document_type"] == "system_overview"
    assert row["evidence_capabilities"] == ["system_overview"]
    assert row["content_sha256"] == before


def test_backfill_reports_missing_files_without_inventing_metadata(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    _database(db_path)
    store = RetrievalMetadataStore(db_path)

    report = store.backfill(tmp_path / "files")

    assert report == {"classified": 0, "unchanged": 0, "missing_files": 1}
    assert store.for_version("v-1") is None


def test_backfill_dry_run_reports_work_without_writing_rows(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    files_root = tmp_path / "files"
    _database(db_path)
    markdown_path = files_root / "doc-1" / "v-1" / "rag.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("# Hinweise\nInterne Hinweise.", encoding="utf-8")
    store = RetrievalMetadataStore(db_path)

    report = store.backfill(files_root, dry_run=True)

    assert report == {"classified": 1, "unchanged": 0, "missing_files": 0}
    assert store.for_version("v-1") is None


def test_relationship_metadata_requires_one_explicit_evidence_span(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    _database(db_path)
    store = RetrievalMetadataStore(db_path)
    explicit = (
        "VaudisX wird zur Kundenpflege genutzt. "
        "Für den technischen Support von VaudisX ist Max Mustermann zuständig."
    )

    store.classify_version(
        document_id="doc-1", version_id="v-1", title="Systemkontakte", markdown=explicit,
    )
    metadata = store.for_version("v-1")

    assert "explicit_relationship" in metadata["evidence_capabilities"]
    assert metadata["relations"] == [{
        "subject_type": "person",
        "subject": "Max Mustermann",
        "predicate": "technical_support_for",
        "object": "VaudisX",
        "evidence_span": "Für den technischen Support von VaudisX ist Max Mustermann zuständig.",
    }]


def test_separate_person_and_system_mentions_do_not_create_a_relationship(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    _database(db_path)
    store = RetrievalMetadataStore(db_path)

    store.classify_version(
        document_id="doc-1",
        version_id="v-1",
        title="Übersicht",
        markdown=(
            "Max Mustermann arbeitet in der IT. "
            "VaudisX wird zur Kundenpflege genutzt."
        ),
    )
    metadata = store.for_version("v-1")

    assert "explicit_relationship" not in metadata["evidence_capabilities"]
    assert metadata["relations"] == []


def test_unclear_classification_waits_for_admin_confirmation(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    _database(db_path)
    store = RetrievalMetadataStore(db_path)
    store.classify_version(
        document_id="doc-1", version_id="v-1", title="Hinweise", markdown="Interne Hinweise.",
    )

    assert [item["version_id"] for item in store.review_required()] == ["v-1"]

    confirmed = store.confirm(
        version_id="v-1",
        domain="internal_processes",
        document_type="process_description",
        topics=("Tagesabschluss",),
        evidence_capabilities=("procedure",),
        actor_user_id="portal-admin",
    )

    assert confirmed["classification_status"] == "confirmed"
    assert confirmed["confidence"] == 1.0
    assert confirmed["confirmed_by_user_id"] == "portal-admin"
    assert store.review_required() == []

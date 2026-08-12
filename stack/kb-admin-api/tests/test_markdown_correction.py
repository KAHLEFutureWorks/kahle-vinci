import tempfile
from pathlib import Path

from app.global_analysis import GlobalCorpus, GlobalDocumentAnalyzer
from app.markdown_correction import MarkdownCorrectionService
from app.secure_ingest import QuarantineStorage
from app.document_lifecycle import Analysis
from test_document_lifecycle import SHA_A, setup, submit


class FakeCorrector:
    def correct(self, markdown: str, instruction: str) -> str:
        assert instruction in {"Überschrift korrigieren", "Titel korrigieren"}
        return markdown.replace("Falsch", "Richtig")


def prepared_case(root: Path):
    governance, lifecycle, kb_id = setup(root / "db")
    case = submit(lifecycle, kb_id, sha=SHA_A)
    storage = QuarantineStorage(root / "files")
    original = storage.store(case.document_id, case.version_id, "md", b"# Falsch\nInhalt")
    storage.store_markdown(original, "# Falsch\nInhalt")
    corpus = GlobalCorpus(governance.store)
    service = MarkdownCorrectionService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus, storage, FakeCorrector(),
    )
    return governance, lifecycle, service, case


def test_confirmed_employee_comment_creates_new_checked_draft_version():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, service, old = prepared_case(Path(directory))
        revised = service.revise(
            old.case_id, "employee", instruction="Überschrift korrigieren",
            reason="Konvertierungsfehler", confirmed=True,
        )
        assert revised.version_id != old.version_id
        assert revised.status == "pending_manager_approval"
        review = service.review(revised.case_id, "employee")
        assert "# Richtig" in review["markdown"]


def test_employee_sees_failed_conversion_and_can_release_a_plain_language_correction():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, service, old = prepared_case(Path(directory))
        lifecycle.record_analysis(
            case_id=old.case_id, normalized_sha256="b" * 64, markdown_sha256="c" * 64,
            analysis=Analysis(conversion_quality="failed", notes=("conversion_output_too_short",)),
        )
        assert [task.case_id for task in lifecycle.tasks_for("employee")] == [old.case_id]
        revised = service.revise(
            old.case_id, "employee", instruction="Titel korrigieren",
            reason="Die Ãœberschrift wurde falsch Ã¼bernommen", confirmed=True,
        )
        assert revised.status == "pending_manager_approval"


def test_admin_can_replace_markdown_but_still_creates_fresh_workflow():
    with tempfile.TemporaryDirectory() as directory:
        _, _, service, old = prepared_case(Path(directory))
        revised = service.revise(
            old.case_id, "admin", replacement_markdown="# Admin-Korrektur\nGeprüfter Inhalt",
            reason="Struktur repariert", confirmed=True,
        )
        assert revised.status == "pending_manager_approval"
        assert "Admin-Korrektur" in service.review(revised.case_id, "admin")["markdown"]

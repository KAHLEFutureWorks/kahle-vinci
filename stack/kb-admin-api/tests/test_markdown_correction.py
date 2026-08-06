import tempfile
from pathlib import Path

from app.global_analysis import GlobalCorpus, GlobalDocumentAnalyzer
from app.markdown_correction import MarkdownCorrectionService
from app.secure_ingest import QuarantineStorage
from test_document_lifecycle import SHA_A, setup, submit


class FakeCorrector:
    def correct(self, markdown: str, instruction: str) -> str:
        assert instruction == "Überschrift korrigieren"
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
        assert revised.status == "pending_employee_decision"
        review = service.review(revised.case_id, "employee")
        assert "# Richtig" in review["markdown"]


def test_admin_can_replace_markdown_but_still_creates_fresh_workflow():
    with tempfile.TemporaryDirectory() as directory:
        _, _, service, old = prepared_case(Path(directory))
        revised = service.revise(
            old.case_id, "admin", replacement_markdown="# Admin-Korrektur\nGeprüfter Inhalt",
            reason="Struktur repariert", confirmed=True,
        )
        assert revised.status == "pending_employee_decision"
        assert "Admin-Korrektur" in service.review(revised.case_id, "admin")["markdown"]

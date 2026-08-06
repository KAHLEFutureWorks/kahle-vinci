import tempfile
from datetime import date
from pathlib import Path

from app.document_changes import DocumentChangeService
from test_document_lifecycle import setup
from test_source_access import activate


def test_renewal_requires_owner_confirmation_then_manager_and_admin():
    with tempfile.TemporaryDirectory() as directory:
        governance,lifecycle,kb_id=setup(Path(directory)); active=activate(lifecycle,kb_id)
        ids=iter(("renewal-1",))
        service=DocumentChangeService(governance.store,governance,identifier=lambda:next(ids),today=lambda:date(2026,8,6))
        request=service.request_renewal(active.document_id,"employee","Inhalt weiterhin aktuell",True)
        assert service.pending_for("manager")[0]["request_id"]==request
        assert service.decide(request,"manager",True,"Fachlich bestätigt")=="pending_admin"
        assert service.decide(request,"admin",True,"Final freigegeben")=="approved"
        assert lifecycle.version_record(active.version_id)["valid_until"]=="2026-10-29"


def test_owner_may_raise_confidentiality_but_downgrade_needs_admin():
    with tempfile.TemporaryDirectory() as directory:
        governance,lifecycle,kb_id=setup(Path(directory)); active=activate(lifecycle,kb_id)
        ids=iter(("raise-1","lower-1")); service=DocumentChangeService(governance.store,governance,identifier=lambda:next(ids))
        service.request_confidentiality(active.document_id,"employee","confidential","Schutz erhöhen")
        with governance.store.connect() as db: assert db.execute("SELECT confidentiality FROM canonical_documents WHERE document_id=?",(active.document_id,)).fetchone()[0]=="confidential"
        lower=service.request_confidentiality(active.document_id,"employee","internal","Nicht mehr vertraulich")
        assert service.pending_for("admin")[0]["request_id"]==lower
        service.decide(lower,"admin",True,"Herabstufung geprüft")
        with governance.store.connect() as db: assert db.execute("SELECT confidentiality FROM canonical_documents WHERE document_id=?",(active.document_id,)).fetchone()[0]=="internal"
